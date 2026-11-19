"""The challenge set template, its validator, and the challenge eval CLI (offline)."""

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from eval.challenge import check_file, check_text, main
from triage.schema import Urgency

REPO_FILE = Path(__file__).resolve().parent.parent / "data" / "challenge.toml"


def case(cid="c01", **overrides):
    """One complete, valid [[email]] entry as TOML text. Overrides replace raw TOML values."""
    values = {
        "why_hard": '"Polite tone hides a legal threat."',
        "sender": '"Pat Lee <pat.lee@example.com>"',
        "subject": '"Order 100046249"',
        "body": "'''\nHi, my order #100046249 (Carrick CX irons) from Penrith hasn't arrived.\n"
                "I've spoken to my solicitor about my options.\n'''",
        "category": '"order_status"',
        "needs_human": "true",
        "urgency": '"high"',
        "expected_reasons": '["legal threat"]',
        "order_numbers": '["100046249"]',
        "store": '["Penrith"]',
        "product": '["Carrick CX irons"]',
        "notes": '""',
    } | overrides
    return textwrap.dedent(f"""
        [[email]]
        id = "{cid}"
        why_hard = {values['why_hard']}
        sender = {values['sender']}
        subject = {values['subject']}
        body = {values['body']}

          [email.label]
          category = {values['category']}
          needs_human = {values['needs_human']}
          urgency = {values['urgency']}
          expected_reasons = {values['expected_reasons']}
          order_numbers = {values['order_numbers']}
          store = {values['store']}
          product = {values['product']}
          notes = {values['notes']}
    """)


# --- The template in the repo --------------------------------------------------


def test_repo_template_parses_without_errors():
    """Passes while it's an empty template and once filled in. A mistake in a filled-in case fails here."""
    report = check_file(REPO_FILE)
    assert not report.errors, report.errors
    ids = [c.email.id for c in report.cases] + list(report.incomplete)
    assert len(ids) == len(set(ids)) >= 1  # the template offers 5; you may use fewer


def test_repo_template_header_warns_synthetic_only():
    assert "SYNTHETIC DATA ONLY" in REPO_FILE.read_text()


# --- Validator -----------------------------------------------------------------


def test_complete_case_is_ready():
    report = check_text(case())
    assert report.ready, (report.errors, report.incomplete)
    [c] = report.cases
    assert c.email.body.startswith("Hi, my order")
    assert c.label.needs_human is True
    assert c.label.details.order_numbers == ["100046249"]
    assert c.urgency is Urgency.HIGH


def test_todo_fields_are_listed_not_errors():
    report = check_text(case(subject='"TODO"', category='"TODO"', store='"TODO"'))
    assert report.incomplete == {"c01": ["subject", "label.category", "label.store"]}
    assert not report.errors
    assert not report.ready


def test_missing_field_counts_as_todo():
    text = case().replace('subject = "Order 100046249"\n', "")
    assert check_text(text).incomplete == {"c01": ["subject"]}


def test_empty_lists_mean_nothing_to_extract_and_blank_urgency_is_unlabelled():
    report = check_text(case(order_numbers="[]", store="[]", product="[]", urgency='""'))
    [c] = report.cases
    assert c.label.details.order_numbers is None and c.label.details.store is None
    assert c.urgency is None


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"category": '"refund"'}, "label.category 'refund' isn't one of"),
        ({"needs_human": '"yes"'}, "needs_human must be true or false"),
        ({"expected_reasons": '["lawyer"]'}, "'lawyer' isn't a known signal"),
        ({"expected_reasons": '"legal threat"'}, "expected_reasons must be a list"),
        ({"store": '["Geelong"]'}, "'Geelong' doesn't appear word for word"),
        ({"product": '"Carrick CX irons"'}, "label.product must be a list"),
        ({"order_numbers": '["#100046249"]'}, "without the #"),
        ({"order_numbers": '["46249"]'}, "doesn't appear word for word"),
        ({"order_numbers": '["100046249", "100046249"]'}, "list each order number once"),
        ({"urgency": '"urgent"'}, "label.urgency must be"),
        ({"sender": '"Pat <pat@gmail.com>"'}, "must end in example.com"),
        ({"body": "'''\n\n'''"}, "body is empty"),
    ],
)
def test_validation_errors(overrides, message):
    report = check_text(case(**overrides))
    assert any(message in e for e in report.errors), report.errors
    assert not report.ready


def test_invalid_order_number_format_rejected_even_if_in_email():
    body = "'''\nMy order 200046249 hasn't arrived. I've spoken to my solicitor. Carrick CX irons, Penrith.\n'''"
    report = check_text(case(body=body, subject='"Order"', order_numbers='["200046249"]'))
    assert any("isn't a valid order number" in e for e in report.errors)


def test_toml_syntax_error_reported():
    report = check_text(case() + '\nbroken = "unterminated\n')
    assert report.errors and "isn't valid TOML" in report.errors[0]


def test_duplicate_ids():
    report = check_text(case("c01") + case("c01"))
    assert any("duplicate ids: c01" in e for e in report.errors)


def test_warning_when_label_contradicts_pipeline_design():
    report = check_text(case(category='"complaint"', needs_human="false", expected_reasons="[]"))
    assert report.ready  # allowed, the officer's call...
    assert any("always sends complaint to a person" in w for w in report.warnings)  # ...but flagged


# --- CLI -----------------------------------------------------------------------


class NoClient:
    def __getattr__(self, name):
        raise AssertionError("must not call the API")


def test_check_command_exit_codes(tmp_path):
    good, todo = tmp_path / "good.toml", tmp_path / "todo.toml"
    good.write_text(case())
    todo.write_text(case(subject='"TODO"'))
    assert main(["check", "--file", str(good)]) == 0
    assert main(["check", "--file", str(todo)]) == 1


def test_run_refuses_incomplete_file_without_calling_api(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text(case(subject='"TODO"'))
    assert main(["run", "--file", str(path), "--results", str(tmp_path / "r.md")], client=NoClient()) == 1
    assert not (tmp_path / "r.md").exists()


def stub_client(payload):
    def create(**kwargs):
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                               stop_reason="end_turn", model="claude-opus-5-5")
    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))


def test_run_then_score(tmp_path):
    path, out, md = tmp_path / "c.toml", tmp_path / "out", tmp_path / "results.md"
    path.write_text(case())
    # The model misses the store and calls the urgency normal.
    payload = {
        "category": "order_status", "urgency": "normal", "summary": "Customer's order hasn't arrived.",
        "details": {"order_numbers": ["100046249"], "store": None, "product": "Carrick CX irons", "customer_name": None},
    }
    args = ["--file", str(path), "--out", str(out), "--results", str(md), "--model", "claude-opus-5-5"]
    assert main(["run", *args, "--note", "first try"], client=stub_client(payload)) == 0
    assert (out / "triage.jsonl").exists() and (out / "queue.md").exists()

    text = md.read_text()
    assert "CHALLENGE SET, live run, requested claude-opus-5-5" in text
    assert "Why it's hard: Polite tone hides a legal threat." in text
    assert "| Store | Penrith | (none) | **MISS** |" in text
    assert "| Order numbers | 100046249 | 100046249 | ok |" in text
    assert "| Urgency | high | high | ok |" in text  # the legal-threat rule forces high urgency
    assert "| Needs a person | yes (legal threat) | yes: legal threat | ok |" in text
    assert "Urgency (where labelled): 1/1" in text

    # Re-score the saved run without the API.
    assert main(["score", *args], client=NoClient()) == 0
    assert md.read_text().count("CHALLENGE SET") == 2
    assert "scored from" in md.read_text()


def test_score_without_saved_run(tmp_path):
    path = tmp_path / "c.toml"
    path.write_text(case())
    assert main(["score", "--file", str(path), "--out", str(tmp_path / "none")], client=NoClient()) == 1


def test_report_escapes_pipes_and_html(tmp_path):
    path, out, md = tmp_path / "c.toml", tmp_path / "out", tmp_path / "results.md"
    path.write_text(case(subject='"Order 100046249 | <b>urgent</b>"'))
    payload = {
        "category": "order_status", "urgency": "normal", "summary": "A | B",
        "details": {"order_numbers": [], "store": None, "product": None, "customer_name": None},
    }
    main(["run", "--file", str(path), "--out", str(out), "--results", str(md)], client=stub_client(payload))
    text = md.read_text()
    assert "Order 100046249 \\| &lt;b&gt;urgent&lt;/b&gt;" in text
    assert "Summary: A \\| B" in text
