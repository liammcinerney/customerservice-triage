"""Integrity of the synthetic test set in data/ (offline, no API calls)."""

import json
import re
from pathlib import Path

import pytest

from triage.rules import HUMAN_ONLY_CATEGORIES
from triage.schema import Category, Email, Label
from triage.validate import appears_in, find_order_numbers

DATA = Path(__file__).resolve().parent.parent / "data"


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                pytest.fail(f"{path.name} line {line_no} is not valid JSON: {exc}")
    return rows


@pytest.fixture(scope="module")
def emails() -> list[Email]:
    return [Email.model_validate(row) for row in read_jsonl(DATA / "emails.jsonl")]


@pytest.fixture(scope="module")
def labels() -> list[Label]:
    return [Label.model_validate(row) for row in read_jsonl(DATA / "labels.jsonl")]


def test_ids_unique_and_match_one_to_one(emails, labels):
    email_ids = [e.id for e in emails]
    label_ids = [lab.id for lab in labels]
    assert len(email_ids) == len(set(email_ids)), "duplicate email ids"
    assert len(label_ids) == len(set(label_ids)), "duplicate label ids"
    assert set(email_ids) == set(label_ids)


def test_every_labelled_span_appears_in_its_email(emails, labels):
    by_id = {e.id: e for e in emails}
    missing = []
    for lab in labels:
        email = by_id[lab.id]
        text = f"{email.subject}\n{email.body}"
        for field in ("order_numbers", "store", "product"):
            for span in getattr(lab.details, field) or []:
                if not appears_in(span, text):
                    missing.append(f"{lab.id}.{field}: {span!r}")
    assert not missing, f"labelled spans not found word for word: {missing}"


def test_labelled_order_numbers_are_exactly_the_valid_format_numbers(emails, labels):
    """Domain rule: order numbers are 9 digits starting with 1. In this test set, every
    number in that format is an order number, and no other number is labelled as one."""
    by_id = {e.id: e for e in emails}
    for lab in labels:
        email = by_id[lab.id]
        found = find_order_numbers(f"{email.subject}\n{email.body}")
        assert found == (lab.details.order_numbers or []), f"{lab.id}: found {found}"


def test_every_category_covered(labels):
    assert {lab.category for lab in labels} == set(Category)


def test_both_outcomes_present(labels):
    outcomes = {lab.needs_human for lab in labels}
    assert outcomes == {True, False}


def test_human_only_categories_are_labelled_needs_human(labels):
    """Warranty claims, complaints and compliments always need a human (brief, Categories table)."""
    for lab in labels:
        if lab.category in HUMAN_ONLY_CATEGORIES:
            assert lab.needs_human, f"{lab.id} is {lab.category} but needs_human is false"


def test_rule_signals_imply_needs_human(labels):
    for lab in labels:
        if lab.expected_reasons:
            assert lab.needs_human, f"{lab.id} lists {lab.expected_reasons} but needs_human is false"


def test_senders_use_reserved_example_domains(emails):
    """Synthetic data only: every sender address is on example.com or a subdomain of it."""
    for email in emails:
        match = re.search(r"[\w.+-]+@([\w.-]+)", email.sender)
        assert match, f"{email.id} sender has no address"
        domain = match.group(1).lower()
        assert domain == "example.com" or domain.endswith(".example.com"), f"{email.id}: {domain}"
