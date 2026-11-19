"""Challenge set: hand-written hard emails in data/challenge.toml, labelled by the officer.

  python -m eval.challenge check   what's still to fill in, and any problems (no API calls)
  python -m eval.challenge run     run the pipeline on the challenge emails and score them (API calls)
  python -m eval.challenge score   re-score the saved run (out/challenge/triage.jsonl) against current labels

The file is TOML, read with Python's built-in tomllib, so there's no extra dependency.
Every TODO must be replaced before `run` will call the API. The report shows the
usual metrics plus each email next to its label, because with 5 emails the
per-email view matters more than the percentages.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from eval.run import ResultsFormatError, _matches, format_report, load_results, save_report, score
from triage import rules
from triage.schema import Category, Email, Label, TriageResult, Urgency
from triage.validate import appears_in

DEFAULT_FILE = Path("data/challenge.toml")
DEFAULT_OUT = Path("out/challenge")
DEFAULT_RESULTS_MD = Path("eval/results.md")

TODO = "TODO"
KNOWN_REASONS = (rules.LEGAL, rules.REGULATOR, rules.INJURY, rules.MEDIA, rules.CHARGEBACK, rules.INJECTION)
SPAN_FIELDS = ("order_numbers", "store", "product")
LABEL_FIELDS = ("category", "needs_human", "expected_reasons", *SPAN_FIELDS)


@dataclass
class ChallengeCase:
    email: Email
    label: Label
    why_hard: str
    urgency: Urgency | None  # optional label: None means "not labelled"


@dataclass
class CheckReport:
    cases: list[ChallengeCase] = field(default_factory=list)
    incomplete: dict[str, list[str]] = field(default_factory=dict)  # id -> fields still TODO
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(self.cases) and not self.incomplete and not self.errors


def _is_todo(value: Any) -> bool:
    if isinstance(value, str):
        return TODO in value
    if isinstance(value, list):
        return any(_is_todo(v) for v in value)
    return False


def _check_case(raw: dict[str, Any], report: CheckReport) -> None:
    cid = raw.get("id")
    if not isinstance(cid, str) or not cid.strip():
        report.errors.append("an [[email]] entry has no id")
        return
    label_raw = raw.get("label")
    if not isinstance(label_raw, dict):
        report.errors.append(f"{cid}: missing its [email.label] section")
        return

    # 1. Anything still TODO? Then the case is incomplete, not wrong.
    todo = [f for f in ("why_hard", "sender", "subject", "body") if _is_todo(raw.get(f, TODO))]
    todo += [f"label.{f}" for f in LABEL_FIELDS if _is_todo(label_raw.get(f, TODO))]
    if todo:
        report.incomplete[cid] = todo
        return

    errors: list[str] = []

    # 2. The email itself.
    try:
        email = Email(
            id=cid,
            sender=raw.get("sender", ""),
            subject=raw.get("subject", ""),
            body=str(raw.get("body", "")).strip("\n"),
        )
    except ValidationError as exc:
        report.errors.append(f"{cid}: email fields invalid: {exc.errors()[0]['msg']}")
        return
    if not email.body.strip():
        errors.append("body is empty")
    address = email.sender.rsplit("<", 1)[-1].rstrip(">").strip().lower()
    if not (address.endswith("@example.com") or address.endswith(".example.com")):
        errors.append(f"sender address must end in example.com (synthetic data only), got {address!r}")

    # 3. The label.
    category = label_raw.get("category")
    if category not in {c.value for c in Category}:
        errors.append(f"label.category {category!r} isn't one of: {', '.join(c.value for c in Category)}")
    needs_human = label_raw.get("needs_human")
    if not isinstance(needs_human, bool):
        errors.append(f"label.needs_human must be true or false without quotes, got {needs_human!r}")

    reasons = label_raw.get("expected_reasons")
    if not isinstance(reasons, list):
        errors.append("label.expected_reasons must be a list, e.g. [] or [\"legal threat\"]")
        reasons = []
    for reason in reasons:
        if reason not in KNOWN_REASONS:
            errors.append(f"label.expected_reasons: {reason!r} isn't a known signal ({', '.join(KNOWN_REASONS)})")

    spans: dict[str, list[str] | None] = {}
    text = f"{email.subject}\n{email.body}"
    for f in SPAN_FIELDS:
        value = label_raw.get(f)
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            errors.append(f"label.{f} must be a list of strings, e.g. [] or [\"...\"]")
            continue
        spans[f] = value or None  # [] means "nothing should be extracted"
        for span in value:
            if not appears_in(span, text):
                errors.append(f"label.{f}: {span!r} doesn't appear word for word in the subject or body")
    numbers = spans.get("order_numbers") or []
    for number in numbers:
        if number.startswith("#"):
            errors.append(f"label.order_numbers: write {number!r} without the # ({number[1:]!r})")
        elif not (len(number) == 9 and number.isdigit() and number.startswith("1")):
            errors.append(f"label.order_numbers: {number!r} isn't a valid order number (9 digits starting with 1)")
    if len(set(numbers)) != len(numbers):
        errors.append("label.order_numbers: list each order number once")

    urgency_raw = label_raw.get("urgency", "")
    urgency = None
    if urgency_raw not in ("", None):
        if urgency_raw in {u.value for u in Urgency}:
            urgency = Urgency(urgency_raw)
        else:
            errors.append(f"label.urgency must be high, normal, low or \"\", got {urgency_raw!r}")

    if errors:
        report.errors += [f"{cid}: {e}" for e in errors]
        return

    try:
        label = Label(
            id=cid,
            category=category,
            needs_human=needs_human,
            expected_reasons=reasons,
            details=spans,
            notes=str(label_raw.get("notes", "")),
        )
    except ValidationError as exc:  # backstop: the checks above should catch everything first
        report.errors.append(f"{cid}: label invalid: {exc.errors()[0]['msg']}")
        return
    report.cases.append(ChallengeCase(email=email, label=label, why_hard=str(raw["why_hard"]), urgency=urgency))

    # 4. Labels that can't match how the pipeline is designed (allowed, but flagged).
    if not needs_human and category in {c.value for c in rules.HUMAN_ONLY_CATEGORIES}:
        report.warnings.append(
            f"{cid}: labelled {category} but needs_human = false. The pipeline always sends "
            f"{category} to a person, so this will score as a false flag if the category is right."
        )
    if not needs_human and reasons:
        report.warnings.append(
            f"{cid}: lists expected_reasons but needs_human = false. Any rule signal sends the email to a person."
        )


def check_text(text: str) -> CheckReport:
    report = CheckReport()
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        report.errors.append(f"the file isn't valid TOML: {exc}")
        return report
    entries = data.get("email", [])
    if not isinstance(entries, list) or not entries:
        report.errors.append("no [[email]] entries found")
        return report
    ids = [e.get("id") for e in entries if isinstance(e, dict)]
    dupes = sorted({i for i in ids if ids.count(i) > 1 and i})
    if dupes:
        report.errors.append(f"duplicate ids: {', '.join(dupes)}")
    for raw in entries:
        _check_case(raw, report)
    return report


def check_file(path: Path) -> CheckReport:
    if not path.is_file():
        report = CheckReport()
        report.errors.append(f"file not found: {path}")
        return report
    return check_text(path.read_text(encoding="utf-8"))


def format_check(report: CheckReport) -> str:
    lines = []
    for case in report.cases:
        lines.append(f"{case.email.id}: complete")
    for cid, fields in report.incomplete.items():
        lines.append(f"{cid}: still to fill in: {', '.join(fields)}")
    lines += [f"error: {e}" for e in report.errors]
    lines += [f"warning: {w}" for w in report.warnings]
    if report.ready:
        lines.append(f"Ready: {len(report.cases)} emails. `python -m eval.challenge run` will score them.")
    else:
        lines.append("Not ready to run yet.")
    return "\n".join(lines)


# --- Per-email report --------------------------------------------------------


def _cell(text: str) -> str:
    """Untrusted text inside a markdown table cell: one line, no HTML, no links, no column breaks."""
    text = " ".join(str(text).split())
    for char, escaped in (("<", "&lt;"), (">", "&gt;"), ("[", "\\["), ("]", "\\]"), ("|", "\\|")):
        text = text.replace(char, escaped)
    return text


def _expected(field_name: str, value: list[str] | None) -> str:
    """Order numbers: all of them (joined with 'and'). Other fields: alternatives (joined with '/')."""
    if not value:
        return "(none)"
    return (" and " if field_name == "order_numbers" else " / ").join(value)


def _got(value: str | list[str] | None) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "(none)"
    return value or "(none)"


def _mark(ok: bool) -> str:
    return "ok" if ok else "**MISS**"


def per_email_report(cases: list[ChallengeCase], results: dict[str, TriageResult]) -> tuple[str, str]:
    """The per-email breakdown, and an urgency summary line (urgency is labelled per email, optionally)."""
    lines = ["### Per email", ""]
    urgency_hit = urgency_total = 0
    for case in cases:
        lab, r = case.label, results.get(case.email.id)
        lines += [f"#### {case.email.id} - {_cell(case.email.subject) or '(no subject)'}", "",
                  f"Why it's hard: {_cell(case.why_hard)}", ""]
        if r is None:
            lines += ["**No result for this email.**", ""]
            continue
        got_category = r.category.value if r.category else "none (classification failed)"
        expected_human = "yes" if lab.needs_human else "no"
        if lab.expected_reasons:
            expected_human += f" ({', '.join(lab.expected_reasons)})"
        got_human = ("yes: " + ", ".join(r.escalation_reasons)) if r.needs_human else "no"
        lines += [
            "| | Expected | Got | |",
            "| --- | --- | --- | --- |",
            f"| Category | {lab.category.value} | {got_category} | {_mark(r.category == lab.category)} |",
            f"| Needs a person | {expected_human} | {_cell(got_human)} | {_mark(r.needs_human == lab.needs_human)} |",
        ]
        if case.urgency is not None:
            urgency_total += 1
            ok = r.urgency == case.urgency
            urgency_hit += ok
            got_urgency = r.urgency.value if r.urgency else "none"
            lines.append(f"| Urgency | {case.urgency.value} | {got_urgency} | {_mark(ok)} |")
        for f in SPAN_FIELDS:
            expected, got = getattr(lab.details, f), getattr(r.details, f)
            lines.append(
                f"| {f.replace('_', ' ').capitalize()} | {_cell(_expected(f, expected))} | {_cell(_got(got))} "
                f"| {_mark(_matches(got, expected))} |"
            )
        lines += ["", f"- Summary: {_cell(r.summary or '(none)')}", f"- Route to: {r.route_to}"]
        for d in r.dropped_details:
            shown = d.value if d.reason != "not in email" else "(invented value, not shown)"
            lines.append(f"- Dropped {d.field}: {_cell(shown)} ({d.reason})")
        if r.status == "failed":
            lines.append(f"- Classification failed: {_cell(r.error or 'unknown')}")
        if lab.notes:
            lines.append(f"- Your note: {_cell(lab.notes)}")
        lines.append("")
    urgency_line = (
        f"Urgency (where labelled): {urgency_hit}/{urgency_total}" if urgency_total else "Urgency: not labelled"
    )
    return "\n".join(lines), urgency_line


def build_report(cases: list[ChallengeCase], results: dict[str, TriageResult], source: str, note: str) -> str:
    from triage import classify as classify_mod

    as_of = " (current code)" if source.startswith("scored from") else ""
    meta = {
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": f"CHALLENGE SET, {source}",
        "effort": classify_mod.EFFORT + as_of,
        "prompt_version": classify_mod.PROMPT_VERSION + as_of,
        "note": note,
    }
    summary = format_report(score(results, [c.label for c in cases]), meta)
    breakdown, urgency_line = per_email_report(cases, results)
    return f"{summary}\n{urgency_line}\n\n{breakdown}"


# --- Entry point ---------------------------------------------------------------


def main(argv: list[str] | None = None, client: Any = None) -> int:
    from triage import classify as classify_mod
    from triage import cli
    from triage.config import load_env, model_name

    parser = argparse.ArgumentParser(prog="python -m eval.challenge", description="Hand-written challenge set.")
    parser.add_argument("command", choices=("check", "run", "score"))
    parser.add_argument("--file", type=Path, default=DEFAULT_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--model", default=None)
    parser.add_argument("--note", default="")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_MD)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    report = check_file(args.file)
    print(format_check(report), file=sys.stderr)
    if args.command == "check":
        return 0 if report.ready else 1
    if not report.ready:
        print("Fix the items above first. Nothing was sent to the API.", file=sys.stderr)
        return 1

    emails = [c.email for c in report.cases]
    if args.command == "run":
        load_env()
        model = args.model or model_name()
        try:
            client = client or classify_mod.make_client()
            print(f"Running pipeline on {len(emails)} challenge emails with {model} ...", file=sys.stderr)
            run = cli.run_pipeline(emails, client, model)
        except cli.FATAL_ERRORS as exc:
            print(f"error: the API rejected the request ({type(exc).__name__}). Check .env and the model name.",
                  file=sys.stderr)
            return 2
        cli.write_outputs(run, emails, args.out, model)
        results = {r.id: r for r in run}
        source = f"live run, requested {model}"
    else:
        saved = args.out / "triage.jsonl"
        if not saved.is_file():
            print(f"error: no saved run at {saved}. Use `run` first.", file=sys.stderr)
            return 1
        try:
            results = load_results(saved)
        except ResultsFormatError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        source = f"scored from {saved}"

    text = build_report(report.cases, results, source, args.note)
    print(text)
    if not args.no_save:
        save_report(text, args.results)
        print(f"Appended to {args.results}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
