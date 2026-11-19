"""Live entries: --single appends to out/live.jsonl, queue.html shows them with a "Live" tag,
--clear-live resets them, and the eval never reads them (offline, mocked model)."""

import io
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.run import main as eval_main
from triage.cli import main as cli_main
from triage.report import load_live, next_live_id, render_html
from triage.schema import Details, Email, Label, LiveEntry, TriageResult

DATA = Path(__file__).resolve().parent.parent / "data"


class FakeStdin(io.StringIO):
    def isatty(self):
        return False


def client_returning(category="complaint", urgency="high", summary="Customer threatens legal action.", **details):
    payload = {"category": category, "urgency": urgency, "summary": summary,
               "details": {"order_numbers": [], "store": None, "product": None, "customer_name": None} | details}

    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                               stop_reason="end_turn", model="claude-opus-5-5")
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def single(body, client, *extra):
    return cli_main(["--single", "--model", "claude-opus-5-5", *extra], client=client, stdin=FakeStdin(body))


def result(rid, needs_human=False, urgency="normal", category="order_status"):
    return TriageResult(id=rid, status="ok", category=category, urgency=urgency, summary="s",
                        details=Details.empty(), route_to="x", needs_human=needs_human,
                        escalation_reasons=["complaint"] if needs_human else [], attempts=1)


def live_entry(rid, **kw):
    return LiveEntry(recorded_at="2026-11-19 14:00", email=Email(id=rid, sender="", subject=f"Live {rid}", body="b"),
                     result=result(rid, **kw))


def card_order(page: str) -> list[str]:
    return re.findall(r'<article class="card [\w ]+" id="email-([\w-]+)"', page)


# --- The required test: a live entry appears in the HTML with the "Live" tag --------


def test_live_entry_appears_in_html_with_live_tag(capsys):
    code = single("My lawyer will be in touch about the double charge.", client_returning(),
                  "--subject", "Charged twice")
    assert code == 0
    page = Path("out/queue.html").read_text()
    card = re.search(r'<article class="card human live" id="email-live-001">.*?</article>', page, re.S)
    assert card, "live card missing"
    assert '<span class="tag live">Live</span>' in card.group(0)
    assert "Charged twice" in card.group(0)
    assert "legal threat" in card.group(0)
    assert '<li class="live"><strong>1</strong>live</li>' in page


def test_live_entries_are_appended_with_their_own_ids(capsys):
    single("My lawyer will be in touch.", client_returning())
    single("Is the Richmond store open Sunday?",
           client_returning(category="store_enquiry", urgency="normal", summary="Asks about hours.", store="Richmond"))
    entries, warnings = load_live(Path("out/live.jsonl"))
    assert warnings == []
    assert [e.email.id for e in entries] == ["live-001", "live-002"]
    assert entries[1].email.body == "Is the Richmond store open Sunday?"
    assert entries[1].result.route_to == "Store team (Richmond)"
    page = Path("out/queue.html").read_text()
    assert card_order(page) == ["live-001", "live-002"]  # flagged live entry first
    cards = page.split("</section>", 1)[1]  # after the header, whose legend also shows the tag
    assert cards.count('<span class="tag live">Live</span>') == 2


def test_batch_and_live_are_sorted_together():
    """Same key as queue.md: needs a human first, then urgency, then id; live cards interleave."""
    page = render_html(
        [result("e01", needs_human=False, urgency="high"), result("e02", needs_human=True, urgency="low")],
        [Email(id="e01", sender="", subject="a", body="b"), Email(id="e02", sender="", subject="c", body="d")],
        model="m", run_info="r",
        live=[live_entry("live-001", needs_human=True, urgency="high"), live_entry("live-002", urgency="low")],
    )
    assert card_order(page) == ["live-001", "e02", "e01", "live-002"]
    assert "<strong>4</strong>emails" in page
    # Only the live cards carry the tag.
    for cid, tagged in (("live-001", True), ("e02", False), ("e01", False), ("live-002", True)):
        card = re.search(rf'id="email-{cid}">.*?</article>', page, re.S).group(0)
        assert ('class="tag live"' in card) is tagged, cid


def test_batch_run_keeps_live_entries_in_the_page(tmp_path, capsys):
    single("My lawyer will be in touch.", client_returning())
    emails = tmp_path / "emails.jsonl"
    emails.write_text(json.dumps({"id": "e01", "sender": "", "subject": "Hours", "body": "Open Sunday?"}) + "\n")
    cli_main([str(emails), "--model", "m"],
             client=client_returning(category="store_enquiry", urgency="normal", summary="Hours."))
    page = Path("out/queue.html").read_text()
    assert set(card_order(page)) == {"e01", "live-001"}
    assert "live-001" not in Path("out/triage.jsonl").read_text()  # live entries never enter batch results


def test_live_card_escapes_hostile_email(capsys):
    single('<script>alert(1)</script> my lawyer will be in touch', client_returning(), "--subject", "<b>x</b>")
    page = Path("out/queue.html").read_text()
    assert "<script" not in page.lower() and "<b>x</b>" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_single_mode_survives_an_old_batch_file(capsys):
    Path("out").mkdir()
    Path("out/triage.jsonl").write_text('{"id": "e01", "details": {"order_number": null}}\n')
    code = single("My lawyer will be in touch.", client_returning())
    err = capsys.readouterr().err
    assert code == 0
    assert "warning: batch results not shown" in err
    assert "live-001" in Path("out/queue.html").read_text()


# --- --clear-live --------------------------------------------------------------------------


def test_clear_live_empties_the_file_and_rebuilds_the_page(capsys):
    single("My lawyer will be in touch.", client_returning())
    single("And again: my lawyer will be in touch.", client_returning())
    assert cli_main(["--clear-live"]) == 0
    assert Path("out/live.jsonl").read_text() == ""
    page = Path("out/queue.html").read_text()
    assert "live-001" not in page and 'class="tag live"' not in page.split("</section>", 1)[1]
    assert "Cleared 2 live entries" in capsys.readouterr().err
    assert next_live_id(Path("out/live.jsonl")) == "live-001"  # numbering restarts


def test_clear_live_then_single_in_one_command(capsys):
    single("My lawyer will be in touch.", client_returning())
    code = cli_main(["--clear-live", "--single", "--model", "m"], client=client_returning(),
                    stdin=FakeStdin("Fresh email, my lawyer will be in touch."))
    assert code == 0
    entries, _ = load_live(Path("out/live.jsonl"))
    assert [e.email.body for e in entries] == ["Fresh email, my lawyer will be in touch."]


def test_clear_live_when_nothing_exists(capsys):
    assert cli_main(["--clear-live"]) == 0
    assert Path("out/live.jsonl").read_text() == ""


def test_unreadable_live_line_is_skipped_with_a_warning():
    path = Path("live.jsonl")
    path.write_text(live_entry("live-001").model_dump_json() + "\n{not json}\n")
    entries, warnings = load_live(path)
    assert [e.email.id for e in entries] == ["live-001"]
    assert warnings and "line 2" in warnings[0]


# --- The eval ignores out/live.jsonl ---------------------------------------------------------


@pytest.fixture
def labelled(tmp_path):
    """One labelled email that needs a human, and its correct result."""
    labels = tmp_path / "labels.jsonl"
    labels.write_text(Label(id="e01", category="complaint", needs_human=True, expected_reasons=[],
                            details={"order_numbers": None, "store": None, "product": None}).model_dump_json() + "\n")
    out = Path("out")
    out.mkdir(exist_ok=True)
    (out / "triage.jsonl").write_text(result("e01", needs_human=True, category="complaint").model_dump_json() + "\n")
    return SimpleNamespace(labels=labels, results=out / "triage.jsonl", md=tmp_path / "results.md")


def _score(fx, capsys) -> str:
    assert eval_main(["--from", str(fx.results), "--labels", str(fx.labels), "--results", str(fx.md)]) == 0
    capsys.readouterr()
    return fx.md.read_text()


def test_eval_ignores_live_entries(labelled, capsys):
    before = _score(labelled, capsys).split("\n", 3)[3]  # drop the header and timestamp line
    labelled.md.unlink()
    # A wrong-looking live entry (unlabelled, flagged, category complaint) right next to the results.
    Path("out/live.jsonl").write_text(
        live_entry("live-001", needs_human=True, category="complaint").model_dump_json() + "\n"
        + live_entry("live-002", needs_human=False).model_dump_json() + "\n"
    )
    after = _score(labelled, capsys).split("\n", 3)[3]
    assert before == after
    assert "live-" not in after
    assert "**Escalation recall** (headline) | **1/1 (100%)**" in after
    assert "Escalation precision | 1/1 (100%)" in after


def test_eval_live_run_scores_only_labelled_emails(labelled, tmp_path, capsys):
    Path("out/live.jsonl").write_text(live_entry("live-001", needs_human=True).model_dump_json() + "\n")
    emails = tmp_path / "emails.jsonl"
    emails.write_text(json.dumps({"id": "e01", "sender": "", "subject": "s",
                                  "body": "Terrible service at your Geelong store."}) + "\n")
    code = eval_main(["--emails", str(emails), "--labels", str(labelled.labels), "--results", str(labelled.md),
                      "--model", "m"], client=client_returning(urgency="normal", summary="Unhappy with service."))
    assert code == 0
    text = labelled.md.read_text()
    assert "· 1 emails" in text and "live-" not in text
    assert "**Escalation recall** (headline) | **1/1 (100%)**" in text
    assert "Escalation precision | 1/1 (100%)" in text


def test_scoring_the_live_file_by_mistake_fails_clearly(labelled, capsys):
    Path("out/live.jsonl").write_text(live_entry("live-001").model_dump_json() + "\n")
    code = eval_main(["--from", "out/live.jsonl", "--labels", str(labelled.labels), "--no-save"])
    assert code == 2
    assert "doesn't match the current result format" in capsys.readouterr().err


def test_live_emails_never_reach_the_labelled_data(capsys):
    before = {p.name: p.read_bytes() for p in DATA.iterdir()}
    single("My lawyer will be in touch.", client_returning())
    assert {p.name: p.read_bytes() for p in DATA.iterdir()} == before
