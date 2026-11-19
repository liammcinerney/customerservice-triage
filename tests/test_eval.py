"""Eval metrics and the eval CLI, on hand-made predictions and labels (offline)."""

import json
from types import SimpleNamespace

import pytest

from eval.run import Ratio, format_report, main, score
from triage.classify import PROMPT_VERSION
from triage.schema import Details, DroppedDetail, Label, TriageResult


def label(lid, category="order_status", needs_human=False, order=None, store=None, product=None, reasons=()):
    return Label(
        id=lid, category=category, needs_human=needs_human, expected_reasons=list(reasons),
        details={"order_numbers": order, "store": store, "product": product},
    )


def result(rid, category="order_status", needs_human=False, reasons=None, order=None, store=None, product=None,
           summary="Customer wants an update.", status="ok", attempts=1, dropped=(), model="claude-opus-5-5"):
    reasons = reasons if reasons is not None else (["complaint"] if needs_human else [])
    return TriageResult(
        id=rid, status=status, category=category if status == "ok" else None,
        urgency="normal", summary=summary if status == "ok" else None,
        details=Details.empty().model_copy(update={
            "order_numbers": [order] if isinstance(order, str) else (order or []),
            "store": store, "product": product}),
        dropped_details=list(dropped), route_to="x", needs_human=needs_human, escalation_reasons=reasons,
        attempts=attempts, model_used=model,
    )


def by_id(*results):
    return {r.id: r for r in results}


# --- Ratio -------------------------------------------------------------------


def test_ratio_formatting():
    assert str(Ratio(7, 7)) == "7/7 (100%)"
    assert str(Ratio(2, 3)) == "2/3 (67%)"
    assert str(Ratio(0, 0)) == "n/a"


# --- Escalation --------------------------------------------------------------


def test_perfect_run():
    labels = [label("a", needs_human=True, category="complaint"), label("b")]
    s = score(by_id(result("a", category="complaint", needs_human=True), result("b")), labels)
    assert (s.recall.hit, s.recall.total) == (1, 1)
    assert (s.precision.hit, s.precision.total) == (1, 1)
    assert s.category.hit == 2
    assert all(r.hit == 2 for r in s.extraction.values())
    assert not (s.missed_escalations or s.false_flags or s.category_errors or s.extraction_errors)


def test_missed_escalation_and_false_flag():
    labels = [label("a", needs_human=True), label("b", needs_human=True), label("c"), label("d")]
    results = by_id(
        result("a", needs_human=True),
        result("b", needs_human=False),  # missed
        result("c", needs_human=True, reasons=["rated high urgency"]),  # false flag
        result("d"),
    )
    s = score(results, labels)
    assert (s.recall.hit, s.recall.total) == (1, 2)
    assert (s.precision.hit, s.precision.total) == (1, 2)
    assert s.missed_escalations == ["b"]
    assert s.false_flags == ["c (rated high urgency)"]


def test_no_flags_means_precision_not_applicable():
    s = score(by_id(result("a")), [label("a")])
    assert str(s.precision) == "n/a"


def test_missing_result_counts_as_miss():
    s = score({}, [label("a", needs_human=True, reasons=["legal threat"])])
    assert s.missing_results == ["a"]
    assert s.missed_escalations == ["a"]
    assert (s.recall.hit, s.recall.total) == (0, 1)
    assert s.category.hit == 0
    assert (s.rule_signals.hit, s.rule_signals.total) == (0, 1)


# --- Category and extraction -------------------------------------------------


def test_category_error_listed():
    s = score(by_id(result("a", category="complaint")), [label("a", category="order_status")])
    assert s.category_errors == ["a: complaint, expected order_status"]


def test_failed_result_has_no_category():
    s = score(by_id(result("a", status="failed", needs_human=True, reasons=["classification failed"], attempts=2)),
              [label("a")])
    assert s.category_errors == ["a: none, expected order_status"]
    assert s.failed == 1
    assert s.valid_after_retry.hit == 0


def test_extraction_accepts_any_listed_span_ignoring_case():
    labels = [label("a", store=["Richmond", "Richmond store"], product=["Vantage V7 driver"])]
    s = score(by_id(result("a", store="richmond STORE", product="vantage v7  driver")), labels)
    assert s.extraction["store"].hit == 1
    assert s.extraction["product"].hit == 1


def test_extraction_when_label_is_null_any_value_is_wrong():
    s = score(by_id(result("a", order="100046249")), [label("a", order=None)])
    assert s.extraction["order_numbers"].hit == 0
    assert s.extraction_errors == ["a.order_numbers: ['100046249'], expected None"]


def test_extraction_missing_value_is_wrong():
    s = score(by_id(result("a", order=None)), [label("a", order=["100046249"])])
    assert s.extraction["order_numbers"].hit == 0


# --- Rule signals, validity, dropped, pronouns, models -----------------------


def test_rule_signals():
    labels = [label("a", needs_human=True, reasons=["legal threat", "possible injury"])]
    s = score(by_id(result("a", needs_human=True, reasons=["legal threat", "complaint"])), labels)
    assert (s.rule_signals.hit, s.rule_signals.total) == (1, 2)
    assert s.missed_signals == ["a: possible injury"]


def test_validity_counts():
    labels = [label("a"), label("b"), label("c", needs_human=True)]
    results = by_id(
        result("a", attempts=1),
        result("b", attempts=2),
        result("c", status="failed", needs_human=True, reasons=["classification failed"], attempts=2),
    )
    s = score(results, labels)
    assert s.valid_first_try.hit == 1
    assert s.valid_after_retry.hit == 2
    assert s.failed == 1


def test_dropped_details_counted_by_reason():
    dropped = [
        DroppedDetail(field="store", value="Geelong", reason="not in email"),
        DroppedDetail(field="order_numbers", value="#10046249", reason="not a valid order number"),
    ]
    s = score(by_id(result("a", dropped=dropped)), [label("a")])
    assert s.dropped == {"not in email": 1, "not a valid order number": 1}


@pytest.mark.parametrize(
    "summary, gendered",
    [
        ("Customer wants to know how to check his points.", True),
        ("Staff mocked him at the counter.", True),
        ("She wants a refund.", True),
        ("Mr Hale wants the second charge refunded.", True),
        ("Ms. Okafor wants an explanation.", True),
        ("The customer wants to check their points.", False),
        ("Martin Hale wants the second charge refunded.", False),  # using the name is fine
        ("Their son was injured; they want an explanation.", False),
        ("Asks about this order and the Hereford store.", False),  # 'this', 'Hereford' aren't pronouns
        ("Wants a refund for the MS-200 shoes, and hems taken up.", True),  # known false positive: 'MS'
    ],
)
def test_gendered_pronoun_check(summary, gendered):
    s = score(by_id(result("a", summary=summary)), [label("a")])
    assert (s.gendered_ids == ["a"]) is gendered


def test_models_counted():
    s = score(by_id(result("a"), result("b", model="claude-opus-4-8")), [label("a"), label("b")])
    assert s.models == {"claude-opus-5-5": 1, "claude-opus-4-8": 1}


# --- Report and CLI ----------------------------------------------------------

META = {"when": "2026-11-19 10:00", "source": "test", "effort": "medium", "prompt_version": "v1", "note": "baseline"}


def test_report_contents():
    labels = [label("a", needs_human=True), label("b")]
    report = format_report(score(by_id(result("a", needs_human=False), result("b")), labels), META)
    assert "**Escalation recall** (headline) | **0/1 (0%)**" in report
    assert "- Missed escalations: a" in report
    assert "Note: baseline" in report
    assert "claude-opus-5-5 x2" in report


@pytest.fixture
def files(tmp_path):
    labels = [label("a", needs_human=True, category="complaint", reasons=["legal threat"]), label("b")]
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text("".join(lab.model_dump_json() + "\n" for lab in labels))
    results_path = tmp_path / "triage.jsonl"
    results_path.write_text(
        result("a", category="complaint", needs_human=True, reasons=["legal threat", "complaint"]).model_dump_json()
        + "\n" + result("b").model_dump_json() + "\n"
    )
    return SimpleNamespace(tmp=tmp_path, labels=labels_path, results=results_path, md=tmp_path / "results.md")


def test_main_from_file_appends_to_results_without_api(files):
    class NoClient:
        def __getattr__(self, name):
            raise AssertionError("--from must not call the API")

    args = ["--from", str(files.results), "--labels", str(files.labels), "--results", str(files.md), "--note", "baseline"]
    assert main(args, client=NoClient()) == 0
    assert main(args, client=NoClient()) == 0
    text = files.md.read_text()
    assert text.startswith("# Eval results")
    assert text.count("**Escalation recall** (headline) | **1/1 (100%)**") == 2  # appended, not overwritten
    assert f"prompt {PROMPT_VERSION} (current code)" in text


def test_main_no_save(files):
    assert main(["--from", str(files.results), "--labels", str(files.labels), "--results", str(files.md), "--no-save"]) == 0
    assert not files.md.exists()


def test_main_live_mode_uses_pipeline_and_writes_outputs(files):
    emails = [
        {"id": "a", "sender": "M <m@example.com>", "subject": "Refund", "body": "My lawyer will be in touch."},
        {"id": "b", "sender": "N <n@example.com>", "subject": "Hours", "body": "Open Sunday?"},
    ]
    emails_path = files.tmp / "emails.jsonl"
    emails_path.write_text("".join(json.dumps(e) + "\n" for e in emails))

    def respond(**kwargs):
        complaint = "<subject>Refund</subject>" in kwargs["messages"][0]["content"]
        payload = {
            "category": "complaint" if complaint else "order_status",
            "urgency": "normal",
            "details": {"order_numbers": [], "store": None, "product": None, "customer_name": None},
            "summary": "Test.",
        }
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                               stop_reason="end_turn", model="claude-opus-5-5")

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=respond)))
    out = files.tmp / "out"
    code = main(["--emails", str(emails_path), "--labels", str(files.labels), "--out", str(out),
                 "--results", str(files.md), "--model", "claude-opus-5-5"], client=client)
    assert code == 0
    assert (out / "triage.jsonl").exists() and (out / "queue.md").exists()
    text = files.md.read_text()
    assert "live run, requested claude-opus-5-5" in text
    assert "**1/1 (100%)**" in text


# --- Order numbers: every one must be extracted --------------------------------


@pytest.mark.parametrize(
    "predicted, hit",
    [
        (["100043249", "100085626"], True),
        (["100085626", "100043249"], True),  # order doesn't matter
        (["100043249"], False),  # lost an order
        (["100043249", "100085626", "100099999"], False),  # an extra one
        ([], False),
    ],
)
def test_order_numbers_must_match_as_a_set(predicted, hit):
    labels = [label("a", order=["100043249", "100085626"])]
    s = score(by_id(result("a", order=predicted)), labels)
    assert (s.extraction["order_numbers"].hit == 1) is hit


def test_no_order_numbers_expected_and_none_found():
    s = score(by_id(result("a", order=[])), [label("a", order=None)])
    assert s.extraction["order_numbers"].hit == 1


# --- Saved results from an older pipeline version ------------------------------


def test_old_format_results_give_a_clear_error_not_a_traceback(files, capsys):
    """A triage.jsonl saved before order_number became order_numbers can't be scored."""
    old = json.loads(files.results.read_text().splitlines()[0])
    old["details"]["order_number"] = old["details"].pop("order_numbers") or None
    files.results.write_text(json.dumps(old) + "\n")
    code = main(["--from", str(files.results), "--labels", str(files.labels), "--results", str(files.md)])
    assert code == 2
    err = capsys.readouterr().err
    assert "line 1 doesn't match the current result format" in err
    assert "Re-run it to regenerate the file" in err
    assert not files.md.exists()


def test_missing_results_file(files, capsys):
    code = main(["--from", str(files.tmp / "nope.jsonl"), "--labels", str(files.labels), "--no-save"])
    assert code == 2
    assert "no saved results at" in capsys.readouterr().err
