"""Run the triage pipeline.

Batch:   python -m triage.cli data/emails.jsonl [--out out] [--model NAME]
Single:  python -m triage.cli --single [--subject S] [--sender F] < email.txt
         python -m triage.cli --single --file email.txt [--subject S] [--sender F]
Reset:   python -m triage.cli --clear-live

For each email: rule checks -> one model call -> detail check (order number format,
then quote check) -> needs_human decision -> routing. Single mode runs the same
run_pipeline as batch mode; only the output differs.

Batch mode writes:
  out/triage.jsonl  one TriageResult per email
  out/queue.md      the officer's queue: flagged emails first, then by urgency, then by id
  out/queue.html    the same queue as a static, self-contained web page (triage/report.py),
                    including any live entries
Single mode prints the result, appends the email and result to out/live.jsonl, and
rebuilds out/queue.html (batch results plus live entries, each live card tagged "Live").
It never writes to data/ or to out/triage.jsonl: live emails are unlabelled, and the
eval never reads out/live.jsonl. --clear-live empties out/live.jsonl.

Nothing is sent anywhere. A person handles every email in the queue.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
from pydantic import ValidationError

from triage.classify import PROMPT_VERSION, classify, make_client
from triage.config import load_env, model_name
from triage.report import (
    DEFAULT_EMAILS,
    LIVE_FILE,
    append_live,
    clear_live,
    load_live,
    next_live_id,
    rebuild_html,
    render_html,
    sort_queue,
)
from triage.rules import check_rules, decide, final_urgency, route
from triage.schema import (
    DROP_INVALID_ORDER_NUMBER,
    DROP_NOT_IN_EMAIL,
    Details,
    Email,
    TriageResult,
)
from triage.validate import check_details

# Errors that would hit every email the same way: stop the run instead of failing each email.
FATAL_ERRORS = (
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.BadRequestError,
)

# sort_queue (imported from triage.report) orders both queue.md and queue.html.


class InputError(Exception):
    """The input file is missing or malformed."""


def load_emails(path: Path) -> list[Email]:
    if not path.is_file():
        raise InputError(f"input file not found: {path}")
    emails = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            emails.append(Email.model_validate_json(line))
        except ValidationError as exc:
            raise InputError(f"{path} line {line_no} is not a valid email record: {exc.errors()[0]['msg']}") from exc
    ids = [e.id for e in emails]
    if len(ids) != len(set(ids)):
        raise InputError(f"{path} has duplicate email ids")
    return emails


# --- Pipeline ----------------------------------------------------------------


def triage_email(email: Email, client: Any, model: str) -> TriageResult:
    """Triage one email. Model-side failures come back as status 'failed'; config errors raise."""
    rule_reasons = check_rules(email)
    result = classify(email, client, model)
    output = result.output

    if output is not None:
        details, dropped = check_details(output.details, email)
    else:
        details, dropped = Details.empty(), []

    needs_human, reasons = decide(rule_reasons, output)
    category = output.category if output else None
    return TriageResult(
        id=email.id,
        status="ok" if output else "failed",
        category=category,
        urgency=final_urgency(rule_reasons, output.urgency if output else None),
        summary=output.summary if output else None,
        details=details,
        dropped_details=dropped,
        route_to=route(category, details.store, rule_reasons),
        needs_human=needs_human,
        escalation_reasons=reasons,
        attempts=result.attempts,
        error=result.error,
        model_used=result.model_used,
    )


def error_result(email: Email, error: str) -> TriageResult:
    """An unexpected error on one email: send it to a person and keep going."""
    rule_reasons = check_rules(email)
    needs_human, reasons = decide(rule_reasons, None)
    return TriageResult(
        id=email.id,
        status="failed",
        category=None,
        urgency=final_urgency(rule_reasons, None),
        summary=None,
        details=Details.empty(),
        route_to=route(None, None, rule_reasons),
        needs_human=needs_human,
        escalation_reasons=reasons,
        attempts=0,
        error=error,
    )


def run_pipeline(emails: list[Email], client: Any, model: str, log=None) -> list[TriageResult]:
    results = []
    for email in emails:
        try:
            result = triage_email(email, client, model)
        except FATAL_ERRORS:
            raise
        except Exception as exc:  # one bad email mustn't stop the run
            result = error_result(email, f"internal error: {type(exc).__name__}: {exc}")
        results.append(result)
        if log:
            flag = "FLAG " + ", ".join(result.escalation_reasons) if result.needs_human else "routine"
            log(f"{email.id}: {result.status} - {flag}")
    return results


# --- Queue rendering ---------------------------------------------------------


def _md(text: str) -> str:
    """Untrusted text on one line. < > are escaped so it can't render as HTML, and [ ] so
    an email can't inject a clickable link into the officer's queue."""
    text = " ".join(text.split())
    for char, escaped in (("<", "&lt;"), (">", "&gt;"), ("[", "\\["), ("]", "\\]")):
        text = text.replace(char, escaped)
    return text


def _details_line(details: Details) -> str:
    parts = []
    if details.order_numbers:
        label = "order" if len(details.order_numbers) == 1 else "orders"
        parts.append(f"{label} " + ", ".join(f"`{n}`" for n in details.order_numbers))
    if details.store:
        parts.append(f"store {_md(details.store)}")
    if details.product:
        parts.append(f"product {_md(details.product)}")
    if details.customer_name:
        parts.append(f"customer {_md(details.customer_name)}")
    return " · ".join(parts) if parts else "none stated"


def _entry(n: int, r: TriageResult, email: Email) -> list[str]:
    lines = [f"### {n}. {r.id} - {_md(email.subject) or '(no subject)'}", ""]
    if r.needs_human:
        lines.append(f"- **Needs a person:** {', '.join(r.escalation_reasons)}")
    category = r.category.value if r.category else "unknown"
    urgency = r.urgency.value if r.urgency else "unknown"
    lines.append(f"- **Urgency:** {urgency} · **Category:** {category} · **Route to:** {r.route_to}")
    if r.status == "failed":
        lines.append(f"- **Classification failed** ({_md(r.error or 'unknown error')}). Read the email directly.")
    else:
        lines.append(f"- **Summary:** {_md(r.summary or '')}")
        lines.append(f"- **Details:** {_details_line(r.details)}")
    for d in r.dropped_details:
        if d.reason == DROP_INVALID_ORDER_NUMBER:
            # Copied from the email, but not a valid order number: useful for a follow-up.
            lines.append(f"- **Check with customer:** quoted `{_md(d.value)}`, which isn't a valid order number")
    invented = sum(d.reason == DROP_NOT_IN_EMAIL for d in r.dropped_details)
    if invented:
        lines.append(f"- _{invented} extracted detail(s) weren't in the email and were removed._")
    lines += [f"- **From:** {_md(email.sender)}", ""]
    return lines


def render_queue(results: list[TriageResult], emails: list[Email], model: str) -> str:
    by_id = {e.id: e for e in emails}
    ordered = sort_queue(results)
    flagged = [r for r in ordered if r.needs_human]
    routine = [r for r in ordered if not r.needs_human]
    failed = sum(r.status == "failed" for r in results)

    lines = [
        "# Triage queue",
        "",
        f"{len(results)} emails · {len(flagged)} need a person · {len(routine)} routine · {failed} failed classification",
        "",
        f"Model: `{model}` · prompt {PROMPT_VERSION}. Synthetic data. Nothing has been sent; a person handles every email.",
        "",
        f"## Needs a person ({len(flagged)})",
        "",
    ]
    n = 0
    for r in flagged:
        n += 1
        lines += _entry(n, r, by_id[r.id])
    lines += [f"## Routine ({len(routine)})", ""]
    for r in routine:
        n += 1
        lines += _entry(n, r, by_id[r.id])
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(
    results: list[TriageResult], emails: list[Email], out_dir: Path, model: str, run_info: str | None = None
) -> tuple[Path, Path, Path]:
    """Write triage.jsonl, queue.md and queue.html. `run_info` is shown as the report's run time.
    queue.html also shows any live entries saved in out_dir/live.jsonl; queue.md is batch only."""
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / "triage.jsonl"
    queue_path = out_dir / "queue.md"
    html_path = out_dir / "queue.html"
    jsonl_path.write_text("".join(r.model_dump_json() + "\n" for r in results), encoding="utf-8")
    queue_path.write_text(render_queue(results, emails, model), encoding="utf-8")
    run_info = run_info or f"finished {datetime.now():%Y-%m-%d %H:%M}"
    live, _ = load_live(out_dir / LIVE_FILE)
    html_path.write_text(
        render_html(results, emails, model=model, run_info=run_info, prompt_version=PROMPT_VERSION, live=live),
        encoding="utf-8",
    )
    return jsonl_path, queue_path, html_path


# --- Single-email mode ------------------------------------------------------------

def read_single_email(file: Path | None, subject: str, sender: str, stdin=None, email_id: str = "live-001") -> Email:
    """One email from a text file or stdin (multi-line, read to EOF). The text is untrusted.
    The id isn't sent to the model; it only keys the live entry and its card."""
    stdin = stdin or sys.stdin
    if file is not None:
        if not file.is_file():
            raise InputError(f"file not found: {file}")
        body = file.read_text(encoding="utf-8", errors="replace")
    else:
        if stdin.isatty():
            print("Paste the email body, then press Ctrl-D on a new line.", file=sys.stderr)
        body = stdin.read()
    body = body.strip("\n")
    if not body.strip():
        raise InputError("the email body is empty")
    return Email(id=email_id, sender=sender, subject=subject, body=body)


def _term(text: object) -> str:
    """Untrusted text made safe to print: one line, with control and format characters
    (ANSI escape sequences, bidi overrides, zero-width tricks) shown as visible \\u codes
    so an email can't recolour, hide or rewrite what's on the terminal."""
    out = []
    for ch in " ".join(str(text).split()):
        out.append(f"\\u{ord(ch):04x}" if unicodedata.category(ch) in ("Cc", "Cf") else ch)
    return "".join(out)


def _label(needs_human: bool, color: bool) -> str:
    text = "NEEDS A HUMAN" if needs_human else "ROUTINE"
    if not color:
        return text
    code = "1;97;41" if needs_human else "1;97;42"  # bold white on red / green
    return f"\033[{code}m {text} \033[0m"


def format_single(r: TriageResult, email: Email, model: str, elapsed: float, color: bool = False) -> str:
    """A readable plain-text result for one email."""
    rule = "=" * 60
    lines = [rule, _label(r.needs_human, color), rule]
    if email.subject:
        lines.append(f"Subject:   {_term(email.subject)}")
    if email.sender:
        lines.append(f"From:      {_term(email.sender)}")
    lines += [
        f"Category:  {_term(r.category.value if r.category else 'unclassified (classification failed)')}",
        f"Urgency:   {_term(r.urgency.value if r.urgency else 'unknown')}",
        f"Route to:  {_term(r.route_to)}",
        f"Reasons:   {_term(', '.join(r.escalation_reasons)) if r.escalation_reasons else 'none'}",
        f"Summary:   {_term(r.summary) if r.summary else '(none)'}",
        "",
        "Extracted details",
    ]
    for label, value in (
        ("Order numbers", ", ".join(r.details.order_numbers)),
        ("Store", r.details.store),
        ("Product", r.details.product),
        ("Customer name", r.details.customer_name),
    ):
        lines.append(f"  {label + ':':<15} {_term(value) if value else 'not stated'}")

    notes = []
    if r.status == "failed":
        notes.append(f"Classification failed ({_term(r.error or 'unknown error')}). Read the email directly.")
    for d in r.dropped_details:
        if d.reason == DROP_INVALID_ORDER_NUMBER:
            notes.append(f"Check with customer: quoted {_term(d.value)}, which isn't a valid order number.")
    invented = sum(d.reason == DROP_NOT_IN_EMAIL for d in r.dropped_details)
    if invented:
        notes.append(f"{invented} extracted detail(s) weren't in the email and were removed.")
    if notes:
        lines += ["", "Notes"] + [f"  - {n}" for n in notes]

    attempts = f"{r.attempts} attempt" + ("" if r.attempts == 1 else "s")
    lines += ["", f"{_term(r.model_used or model)} · prompt {PROMPT_VERSION} · {attempts} · {elapsed:.1f} s · "
                  "nothing was sent", rule]
    return "\n".join(lines)


# --- Entry point ---------------------------------------------------------------


def main(argv: list[str] | None = None, client: Any = None, stdin=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m triage.cli", description="Triage customer emails into a review queue.")
    parser.add_argument("emails", type=Path, nargs="?", help="batch mode: JSONL file of emails (id, sender, subject, body)")
    parser.add_argument("--out", type=Path, default=Path("out"),
                        help="output directory: batch files, live.jsonl and queue.html (default: out)")
    parser.add_argument("--model", default=None, help="model id (default: TRIAGE_MODEL or claude-opus-5-5)")
    parser.add_argument("--single", action="store_true",
                        help="triage one email: body from stdin (to EOF) or --file; prints the result, adds it to "
                             "out/live.jsonl and rebuilds out/queue.html")
    parser.add_argument("--file", type=Path, default=None, help="single mode: read the email body from this text file")
    parser.add_argument("--subject", default="", help="single mode: the email's subject")
    parser.add_argument("--sender", default="", help="single mode: the sender, e.g. 'Pat Lee <pat@example.com>'")
    parser.add_argument("--clear-live", action="store_true",
                        help="empty out/live.jsonl (and rebuild out/queue.html) before anything else, e.g. before recording")
    args = parser.parse_args(argv)

    single = args.single or args.file is not None
    if single and args.emails:
        parser.error("use either a JSONL file of emails (batch) or --single, not both")
    if not single and (args.subject or args.sender):
        parser.error("--subject and --sender only apply with --single")
    if not single and not args.emails and not args.clear_live:
        parser.error("give a JSONL file of emails, or use --single (or --clear-live)")

    def log(msg: str) -> None:
        print(msg, file=sys.stderr)

    live_path = args.out / LIVE_FILE
    if args.clear_live:
        removed = clear_live(live_path)
        for w in rebuild_html(results_path=args.out / "triage.jsonl", emails_path=DEFAULT_EMAILS,
                              live_path=live_path, out_path=args.out / "queue.html"):
            log(f"warning: {w}")
        log(f"Cleared {removed} live entr{'y' if removed == 1 else 'ies'} from {live_path}; "
            f"rebuilt {args.out / 'queue.html'}")
        if not single and not args.emails:
            return 0

    try:
        if single:
            email_id = next_live_id(live_path)
            emails = [read_single_email(args.file, args.subject, args.sender, stdin=stdin, email_id=email_id)]
        else:
            emails = load_emails(args.emails)
    except InputError as exc:
        log(f"error: {exc}")
        return 2

    # From here on, single and batch mode share the same code: one pipeline for both.
    load_env()
    model = args.model or model_name()
    started, t0 = datetime.now(), time.monotonic()
    try:
        client = client or make_client()
        log(f"Triaging {len(emails)} email{'' if len(emails) == 1 else 's'} with {model} ...")
        results = run_pipeline(emails, client, model, log=None if single else log)
    except FATAL_ERRORS as exc:
        log(f"error: stopped before writing output. The API rejected the request ({type(exc).__name__}). "
            "Check ANTHROPIC_API_KEY in .env and the model name.")
        return 2
    except anthropic.AnthropicError as exc:
        log(f"error: could not create the API client: {exc}")
        return 2

    if single:
        color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        print(format_single(results[0], emails[0], model, time.monotonic() - t0, color=color))
        # Saved after printing, so a file problem can never hide the result during a demo.
        try:
            append_live(live_path, emails[0], results[0])
            html_path = args.out / "queue.html"
            for w in rebuild_html(results_path=args.out / "triage.jsonl", emails_path=DEFAULT_EMAILS,
                                  live_path=live_path, out_path=html_path):
                log(f"warning: {w}")
            log(f"Saved as {emails[0].id} in {live_path}; rebuilt {html_path}")
        except OSError as exc:
            log(f"warning: result shown above but not saved: {exc}")
        return 0

    run_info = f"{started:%Y-%m-%d %H:%M} · took {time.monotonic() - t0:.0f} s"
    jsonl_path, queue_path, html_path = write_outputs(results, emails, args.out, model, run_info)
    flagged = sum(r.needs_human for r in results)
    failed = sum(r.status == "failed" for r in results)
    log(f"Done: {flagged}/{len(results)} need a person, {failed} failed. "
        f"Wrote {jsonl_path}, {queue_path} and {html_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
