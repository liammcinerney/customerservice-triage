"""The static HTML report (triage/report.py), offline."""

import json
import re
from types import SimpleNamespace

import pytest

from triage.cli import main as cli_main
from triage.report import detail_pattern, highlight, main, render_html, sort_queue
from triage.schema import Details, DroppedDetail, Email, TriageResult


def details(**values) -> Details:
    return Details.empty().model_copy(update=values)


def result(rid, needs_human=False, urgency="normal", category="order_status", summary="Customer wants an update.",
           reasons=None, route_to="Online orders team", status="ok", dropped=(), **detail_values) -> TriageResult:
    reasons = reasons if reasons is not None else (["complaint"] if needs_human else [])
    return TriageResult(
        id=rid, status=status, category=category if status == "ok" else None, urgency=urgency,
        summary=summary if status == "ok" else None, details=details(**detail_values),
        dropped_details=list(dropped), route_to=route_to, needs_human=needs_human,
        escalation_reasons=reasons, attempts=1, model_used="claude-opus-5-5",
    )


def email(eid, body="Hello", subject="Subject", sender="Pat <pat@example.com>") -> Email:
    return Email(id=eid, sender=sender, subject=subject, body=body)


def page(results, emails) -> str:
    return render_html(results, emails, model="claude-opus-5-5", run_info="2026-11-19 13:00 · took 50 s",
                       prompt_version="v4")


# --- Escaping: email text and model output are untrusted -------------------------

HOSTILE = '<script>alert("x")</script><img src=x onerror=alert(1)> " onmouseover="alert(2)'


def test_email_text_with_html_and_script_tags_is_escaped():
    e = email("e1", body=f"Hi {HOSTILE} bye", subject=f"Re: {HOSTILE}", sender=f"Eve {HOSTILE} <eve@example.com>")
    r = result("e1", summary=f"Summary {HOSTILE}", reasons=["complaint"], needs_human=True,
               route_to="Store team (<b>Richmond</b>)", store="<i>store</i>", product='Club "X" & <Y>')
    out = page([r], [e])

    # Nothing the email or model wrote becomes markup...
    assert "<script" not in out.lower()
    assert "<img" not in out.lower()
    assert "<b>Richmond</b>" not in out and "<i>store</i>" not in out
    assert 'onmouseover="' not in out
    # ...it's shown as text instead.
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in out
    assert "&lt;img src=x onerror=alert(1)&gt;" in out
    assert "Store team (&lt;b&gt;Richmond&lt;/b&gt;)" in out
    assert "Club &quot;X&quot; &amp; &lt;Y&gt;" in out


def test_id_in_attribute_is_escaped():
    out = page([result('x" onclick="evil')], [email('x" onclick="evil')])
    assert 'id="email-x&quot; onclick=&quot;evil"' in out
    assert 'onclick="evil"' not in out


def test_page_is_self_contained_and_blocks_scripts_and_network():
    out = page([result("e1")], [email("e1")])
    lower = out.lower()
    for forbidden in ("<script", "<link", "@import", "http://", "https://", "src=", "url("):
        assert forbidden not in lower, forbidden
    assert '<meta http-equiv="Content-Security-Policy" content="default-src &#x27;none&#x27;' in out
    assert "<style>" in out


# --- Highlighting: only word-for-word matches --------------------------------------


def test_detail_is_marked_where_it_appears_word_for_word():
    body = "I bought a Strata pull buggy at the Richmond store."
    out = highlight(body, details(store="Richmond", product="Strata pull buggy"))
    assert '<mark title="Store">Richmond</mark>' in out
    assert '<mark title="Product">Strata pull buggy</mark>' in out


def test_detail_not_in_body_is_not_marked():
    out = highlight("I bought a Strata pull buggy.", details(store="Geelong", product="Vantage driver"))
    assert "<mark" not in out


def test_partial_word_is_not_marked():
    """Same whole-word rule as the quote check: 'Rich' isn't in 'Richmond'."""
    out = highlight("The Richmond store.", details(store="Rich"))
    assert "<mark" not in out


def test_matching_ignores_case_and_whitespace_but_keeps_original_text():
    body = "Tracking says\n  'in transit' at the RICHMOND store"
    out = highlight(body, details(store="richmond store", product="tracking says 'in transit'"))
    assert '<mark title="Store">RICHMOND store</mark>' in out
    assert "<mark title=\"Product\">Tracking says\n  &#x27;in transit&#x27;</mark>" in out


def test_curly_quote_in_body_matches_straight_quote_in_detail():
    out = highlight("It hasn\u2019t arrived", details(product="hasn't arrived"))
    assert '<mark title="Product">hasn\u2019t arrived</mark>' in out


def test_each_order_number_is_marked_but_not_the_hash():
    body = "Orders #100043249 and #100085626, not 10004324."
    out = highlight(body, details(order_numbers=["100043249", "100085626"]))
    assert '#<mark title="Order numbers">100043249</mark>' in out
    assert '#<mark title="Order numbers">100085626</mark>' in out
    assert out.count("<mark") == 2


def test_marked_text_is_still_escaped():
    out = highlight("My Black & Decker <trimmer>", details(product="Black & Decker"))
    assert '<mark title="Product">Black &amp; Decker</mark> &lt;trimmer&gt;' in out


def test_overlapping_details_give_one_mark():
    out = highlight("The Richmond store sells putters.", details(store="Richmond", product="Richmond store"))
    assert out.count("<mark") == 1
    assert '<mark title="Store, Product">Richmond store</mark>' in out


def test_dropped_invented_value_is_never_marked():
    """Only kept details are highlighted; a value the quote check removed isn't in Details."""
    r = result("e1", store=None, dropped=[DroppedDetail(field="store", value="Hello", reason="not in email")])
    out = page([r], [email("e1", body="Hello there")])
    assert "<mark" not in out


def test_blank_detail_makes_no_pattern():
    assert detail_pattern("   ") is None


# --- Sorting and layout --------------------------------------------------------------


def test_cards_sorted_needs_human_first_then_urgency_then_id():
    results = [
        result("a", needs_human=False, urgency="high"),
        result("b", needs_human=True, urgency="low"),
        result("c", needs_human=True, urgency="high"),
        result("d", needs_human=False, urgency="low"),
        result("e", needs_human=False, urgency="normal"),
    ]
    out = page(results, [email(r.id) for r in results])
    order = [m.group(1) for m in re.finditer(r'<article class="card \w+" id="email-(\w+)"', out)]
    assert order == ["c", "b", "a", "e", "d"]
    assert order == [r.id for r in sort_queue(results)]  # same order as queue.md
    assert out.index("Needs a human (2)") < out.index('id="email-c"') < out.index("Routine (3)") < out.index('id="email-a"')


def test_badges():
    out = page([result("h", needs_human=True), result("r")], [email("h"), email("r")])
    assert out.count('<span class="badge human">Needs a human</span>') == 1
    assert out.count('<span class="badge routine">Routine</span>') == 1


def test_header_counts_and_run_time():
    results = [
        result("a", needs_human=True, category="complaint"),
        result("b", needs_human=True, category="complaint"),
        result("c", category="store_enquiry"),
        result("d", status="failed", needs_human=True, reasons=["classification failed"]),
    ]
    out = page(results, [email(r.id) for r in results])
    assert "<strong>4</strong>emails" in out
    assert "<strong>3</strong>need a human" in out
    assert "<strong>1</strong>routine" in out
    assert '<tr><td>complaint</td><td class="n">2</td></tr>' in out
    assert '<tr><td>store_enquiry</td><td class="n">1</td></tr>' in out
    assert '<tr><td>compliment</td><td class="n">0</td></tr>' in out
    assert '<tr><td>unclassified (failed)</td><td class="n">1</td></tr>' in out
    assert "Run time: 2026-11-19 13:00 · took 50 s" in out
    assert "Classification failed" in out


def test_details_table_shows_not_stated_for_empty_fields():
    out = page([result("e1", order_numbers=["100043249", "100085626"], store="Richmond")], [email("e1")])
    assert "<tr><th>Order numbers</th><td>100043249, 100085626</td></tr>" in out
    assert "<tr><th>Store</th><td>Richmond</td></tr>" in out
    assert '<tr><th>Product</th><td class="none">not stated</td></tr>' in out
    assert '<tr><th>Customer name</th><td class="none">not stated</td></tr>' in out


def test_invalid_order_number_shown_as_check_with_customer():
    dropped = [DroppedDetail(field="order_numbers", value="#10046249", reason="not a valid order number")]
    out = page([result("e1", dropped=dropped)], [email("e1", body="It's #10046249 I think")])
    assert "Check with customer: quoted <b>#10046249</b>" in out


# --- Wiring ------------------------------------------------------------------------------


def _client():
    payload = {"category": "store_enquiry", "urgency": "normal", "summary": "Asks about Richmond.",
               "details": {"order_numbers": [], "store": "Richmond", "product": None, "customer_name": None}}

    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                               stop_reason="end_turn", model="claude-opus-5-5")
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_cli_writes_queue_html_next_to_queue_md(tmp_path):
    emails = tmp_path / "emails.jsonl"
    emails.write_text(json.dumps({"id": "e1", "sender": "N <n@example.com>", "subject": "Hours",
                                  "body": "Is the Richmond store open?"}) + "\n")
    out = tmp_path / "out"
    assert cli_main([str(emails), "--out", str(out), "--model", "claude-opus-5-5"], client=_client()) == 0
    assert (out / "queue.md").exists()
    html_text = (out / "queue.html").read_text()
    assert '<mark title="Store">Richmond</mark>' in html_text
    assert re.search(r"Run time: \d{4}-\d\d-\d\d \d\d:\d\d · took \d+ s", html_text)


def test_rebuild_from_saved_files(tmp_path):
    emails = tmp_path / "emails.jsonl"
    emails.write_text(email("e1", body="Richmond").model_dump_json() + "\n")
    results = tmp_path / "triage.jsonl"
    results.write_text(result("e1", store="Richmond").model_dump_json() + "\n")
    out = tmp_path / "queue.html"
    assert main(["--results", str(results), "--emails", str(emails), "--out", str(out)]) == 0
    text = out.read_text()
    assert "results saved" in text and "prompt v4 (current code)" in text


def test_rebuild_with_old_or_missing_results_fails_clearly(tmp_path, capsys):
    emails = tmp_path / "emails.jsonl"
    emails.write_text(email("e1").model_dump_json() + "\n")
    assert main(["--results", str(tmp_path / "none.jsonl"), "--emails", str(emails)]) == 2
    old = tmp_path / "old.jsonl"
    old.write_text('{"id": "e1", "details": {"order_number": null}}\n')
    assert main(["--results", str(old), "--emails", str(emails)]) == 2
    assert "older version" in capsys.readouterr().err
