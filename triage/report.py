"""Static HTML report of the triage queue: out/queue.html.

  python -m triage.report          rebuild out/queue.html from out/triage.jsonl, data/emails.jsonl
                                   and out/live.jsonl (no API calls; the CLI also rebuilds it after
                                   every batch run, every --single run and --clear-live)

The page shows the batch results plus any live entries (emails triaged with
`--single`, saved in out/live.jsonl). Live cards carry a "Live" tag. Live emails are
unlabelled and are never read by the eval.

Design:
- One self-contained file: inline CSS, no JavaScript, no external fonts, CDNs or
  network calls, so it opens offline. Standard library only (html.escape).
- Email text and model output are untrusted. Every value is escaped with
  html.escape(quote=True) before it goes into the page, including attribute values.
  As a second layer, a Content-Security-Policy meta tag blocks scripts and all
  network loads, so even an escaping mistake couldn't run code or call out.
- Cards are sorted exactly like queue.md (sort_queue is shared): needs a human
  first, then high, normal, low urgency, then id.
- Extracted details are highlighted in the body with <mark> only where they appear
  word for word, using the same rule as the quote check (triage/validate.py): case,
  whitespace runs and curly-vs-straight quotes and dashes are ignored, and matches
  must be whole words.
"""

from __future__ import annotations

import argparse
import html
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from triage.schema import (
    DROP_INVALID_ORDER_NUMBER,
    DROP_NOT_IN_EMAIL,
    Category,
    Details,
    Email,
    LiveEntry,
    TriageResult,
    Urgency,
)

URGENCY_RANK = {Urgency.HIGH: 0, Urgency.NORMAL: 1, Urgency.LOW: 2}

DEFAULT_RESULTS = Path("out/triage.jsonl")
DEFAULT_EMAILS = Path("data/emails.jsonl")
DEFAULT_OUT = Path("out/queue.html")
LIVE_FILE = "live.jsonl"  # lives next to triage.jsonl, e.g. out/live.jsonl
LIVE_ID_PREFIX = "live-"

DETAIL_FIELDS = (
    ("order_numbers", "Order numbers"),
    ("store", "Store"),
    ("product", "Product"),
    ("customer_name", "Customer name"),
)


def queue_sort_key(r: TriageResult) -> tuple:
    """Flagged first, then high -> normal -> low urgency, then by id."""
    return (not r.needs_human, URGENCY_RANK.get(r.urgency, 1), r.id)


def sort_queue(results: list[TriageResult]) -> list[TriageResult]:
    """The queue order, used by queue.md and queue.html (batch and live cards alike)."""
    return sorted(results, key=queue_sort_key)


def esc(value: object) -> str:
    """Escape any value for HTML text or a quoted attribute."""
    return html.escape(str(value), quote=True)


# --- Highlighting (same matching rule as the quote check) ---------------------

_EQUIVALENT = {
    "'": "['‘’]", "‘": "['‘’]", "’": "['‘’]",
    '"': '["“”]', "“": '["“”]', "”": '["“”]',
    "-": "[-–—]", "–": "[-–—]", "—": "[-–—]",
}


def detail_pattern(detail: str) -> re.Pattern[str] | None:
    """A regex finding `detail` word for word: any case, any whitespace run between words,
    curly or straight quotes and dashes, and whole words only."""
    words = detail.split()
    if not words:
        return None
    parts = ["".join(_EQUIVALENT.get(ch, re.escape(ch)) for ch in word) for word in words]
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


def highlight(body: str, details: Details) -> str:
    """The escaped body, with each extracted detail wrapped in <mark> wherever it appears word for word."""
    spans: list[tuple[int, int, str]] = []
    for field, label in DETAIL_FIELDS:
        value = getattr(details, field)
        for item in value if isinstance(value, list) else [value]:
            pattern = detail_pattern(item) if item else None
            if pattern:
                spans += [(m.start(), m.end(), label) for m in pattern.finditer(body)]

    # Merge overlapping matches so marks never nest or cross.
    spans.sort(key=lambda s: (s[0], -s[1]))
    merged: list[list] = []
    for start, end, label in spans:
        if merged and start < merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
            if label not in merged[-1][2]:
                merged[-1][2].append(label)
        else:
            merged.append([start, end, [label]])

    field_order = [label for _, label in DETAIL_FIELDS]
    out, pos = [], 0
    for start, end, labels in merged:
        labels = sorted(labels, key=field_order.index)  # stable: Order numbers, Store, Product, Customer name
        out.append(esc(body[pos:start]))
        out.append(f'<mark title="{esc(", ".join(labels))}">{esc(body[start:end])}</mark>')
        pos = end
    out.append(esc(body[pos:]))
    return "".join(out)


# --- Page ----------------------------------------------------------------------

CSS = """
:root { --text: #1d2939; --muted: #475467; --line: #d0d5dd; --bg: #f2f4f7; --card: #ffffff;
        --red: #b42318; --red-bg: #fef3f2; --green: #067647; --green-bg: #ecfdf3; --mark: #fde68a; }
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--text);
       font: 16px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
main { max-width: 980px; margin: 0 auto; padding: 24px 16px 48px; }
h1 { font-size: 1.75rem; margin: 0 0 4px; }
h2.section { font-size: 1.25rem; margin: 32px 0 12px; }
.muted { color: var(--muted); }
.top { background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 20px 24px; }
.stats { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0; padding: 0; list-style: none; }
.stats li { border: 1px solid var(--line); border-radius: 8px; padding: 8px 14px; background: var(--bg); }
.stats strong { font-size: 1.4rem; display: block; line-height: 1.1; }
.stats .human { border-color: var(--red); background: var(--red-bg); color: var(--red); }
.stats .routine { border-color: var(--green); background: var(--green-bg); color: var(--green); }
table { border-collapse: collapse; }
.cats td, .cats th { padding: 3px 14px 3px 0; text-align: left; }
.cats td.n { text-align: right; font-variant-numeric: tabular-nums; }
.card { background: var(--card); border: 1px solid var(--line); border-left: 6px solid var(--green);
        border-radius: 10px; padding: 18px 22px; margin: 0 0 16px; }
.card.human { border-left-color: var(--red); }
.card h3 { font-size: 1.15rem; margin: 6px 0 4px; overflow-wrap: anywhere; }
.badge { display: inline-block; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.02em;
         padding: 3px 10px; border-radius: 999px; color: #fff; }
.badge.human { background: var(--red); }
.badge.routine { background: var(--green); }
.tag { display: inline-block; font-size: 0.75rem; font-weight: 700; padding: 2px 8px; margin-left: 6px;
       border-radius: 4px; vertical-align: 1px; }
.tag.live { background: #eff8ff; color: #175cd3; border: 1px solid #175cd3; }
.stats .live { border-color: #175cd3; background: #eff8ff; color: #175cd3; }
.meta { margin: 2px 0 10px; color: var(--muted); overflow-wrap: anywhere; }
.meta b { color: var(--text); font-weight: 600; }
.urgency-high { color: var(--red); font-weight: 700; }
.reasons { background: var(--red-bg); color: var(--red); border-radius: 6px; padding: 6px 10px; margin: 8px 0; }
.summary { font-size: 1.05rem; margin: 8px 0 12px; }
.failed { background: var(--red-bg); color: var(--red); border-radius: 6px; padding: 6px 10px; }
.details { margin: 4px 0 10px; font-size: 0.95rem; }
.details th { text-align: left; color: var(--muted); font-weight: 600; padding: 3px 16px 3px 0; vertical-align: top; }
.details td { padding: 3px 0; overflow-wrap: anywhere; }
.details td.none { color: var(--muted); font-style: italic; }
.note { font-size: 0.95rem; color: var(--muted); margin: 4px 0; }
details { margin-top: 8px; }
details > summary { cursor: pointer; color: var(--muted); font-weight: 600; }
.body { white-space: pre-wrap; overflow-wrap: anywhere; background: var(--bg); border: 1px solid var(--line);
        border-radius: 6px; padding: 12px 14px; margin-top: 8px; font-size: 0.95rem; }
mark { background: var(--mark); color: inherit; padding: 0 2px; border-radius: 3px; }
footer { margin-top: 32px; font-size: 0.9rem; color: var(--muted); }
"""

# No scripts, no network: everything the page needs is inline.
CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'none'; form-action 'none'; base-uri 'none'"


def _detail_rows(details: Details) -> str:
    rows = []
    for field, label in DETAIL_FIELDS:
        value = getattr(details, field)
        text = ", ".join(value) if isinstance(value, list) else value
        cell = f"<td>{esc(text)}</td>" if text else '<td class="none">not stated</td>'
        rows.append(f"<tr><th>{esc(label)}</th>{cell}</tr>")
    return '<table class="details">' + "".join(rows) + "</table>"


def _card(n: int, r: TriageResult, email: Email | None, live_at: str | None = None) -> str:
    """One email's card. `live_at` is set for live entries (emails triaged with --single)."""
    human = r.needs_human
    badge = '<span class="badge human">Needs a human</span>' if human else '<span class="badge routine">Routine</span>'
    if live_at is not None:
        badge += '<span class="tag live">Live</span>'
    subject = email.subject if email and email.subject else "(no subject)"
    sender = email.sender if email and email.sender else "(sender not given)"
    category = r.category.value if r.category else "unclassified"
    urgency = r.urgency.value if r.urgency else "unknown"
    urgency_class = ' class="urgency-high"' if r.urgency is Urgency.HIGH else ""
    when = f" · triaged live {esc(live_at)}" if live_at is not None else ""

    parts = [
        f'<article class="card {"human" if human else "routine"}{" live" if live_at is not None else ""}" '
        f'id="email-{esc(r.id)}">',
        badge,
        f"<h3>{n}. {esc(subject)}</h3>",
        f'<p class="meta">{esc(r.id)}{when} · From <b>{esc(sender)}</b><br>'
        f"Category <b>{esc(category)}</b> · Urgency <b{urgency_class}>{esc(urgency)}</b> · "
        f"Route to <b>{esc(r.route_to)}</b></p>",
    ]
    if r.escalation_reasons:
        parts.append(f'<p class="reasons"><b>Why a human:</b> {esc(", ".join(r.escalation_reasons))}</p>')
    if r.status == "failed":
        parts.append(f'<p class="failed"><b>Classification failed</b> ({esc(r.error or "unknown error")}). '
                     "Read the email directly.</p>")
    else:
        parts.append(f'<p class="summary">{esc(r.summary or "")}</p>')
    parts.append(_detail_rows(r.details))
    for d in r.dropped_details:
        if d.reason == DROP_INVALID_ORDER_NUMBER:
            parts.append(f'<p class="note">Check with customer: quoted <b>{esc(d.value)}</b>, '
                         "which isn't a valid order number.</p>")
    invented = sum(d.reason == DROP_NOT_IN_EMAIL for d in r.dropped_details)
    if invented:
        parts.append(f'<p class="note">{invented} extracted detail(s) weren\'t in the email and were removed.</p>')
    if email is not None:
        parts.append('<details open><summary>Original email</summary>'
                     f'<div class="body">{highlight(email.body, r.details)}</div></details>')
    else:
        parts.append('<p class="note">Original email not found.</p>')
    parts.append("</article>")
    return "\n".join(parts)


def render_html(
    results: list[TriageResult],
    emails: list[Email],
    *,
    model: str,
    run_info: str,
    prompt_version: str | None = None,
    live: list[LiveEntry] | None = None,
) -> str:
    """The whole report as one self-contained HTML document: batch results plus live entries,
    all sorted together with the same key as queue.md."""
    by_id = {e.id: e for e in emails}
    live = live or []
    # (result, email, live timestamp or None). Live entries carry their own email.
    items = [(r, by_id.get(r.id), None) for r in results] + [(e.result, e.email, e.recorded_at) for e in live]
    items.sort(key=lambda item: queue_sort_key(item[0]))
    flagged = [item for item in items if item[0].needs_human]
    routine = [item for item in items if not item[0].needs_human]

    counts = Counter(item[0].category for item in items)
    cat_rows = [f'<tr><td>{esc(c.value)}</td><td class="n">{counts.get(c, 0)}</td></tr>' for c in Category]
    if counts.get(None):
        cat_rows.append(f'<tr><td>unclassified (failed)</td><td class="n">{counts[None]}</td></tr>')
    live_stat = f'\n<li class="live"><strong>{len(live)}</strong>live</li>' if live else ""

    model_line = f"Model <b>{esc(model)}</b>" + (f" · prompt {esc(prompt_version)}" if prompt_version else "")
    n = 0
    cards_flagged, cards_routine = [], []
    for r, email, live_at in flagged:
        n += 1
        cards_flagged.append(_card(n, r, email, live_at))
    for r, email, live_at in routine:
        n += 1
        cards_routine.append(_card(n, r, email, live_at))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{esc(CSP)}">
<meta name="referrer" content="no-referrer">
<title>Triage queue</title>
<style>{CSS}</style>
</head>
<body>
<main>
<section class="top">
<h1>Triage queue</h1>
<p class="muted">Run time: {esc(run_info)} · {model_line}</p>
<ul class="stats">
<li><strong>{len(items)}</strong>emails</li>
<li class="human"><strong>{len(flagged)}</strong>need a human</li>
<li class="routine"><strong>{len(routine)}</strong>routine</li>{live_stat}
</ul>
<table class="cats"><tr><th>Category</th><th>Emails</th></tr>{"".join(cat_rows)}</table>
<p class="muted">Synthetic data. Nothing has been sent; a person handles every email.
Highlighted text in each email is an extracted detail, shown where it appears word for word.
Cards tagged <span class="tag live">Live</span> were triaged one at a time with --single; they are unlabelled
and not part of the evaluation.</p>
</section>
<h2 class="section">Needs a human ({len(flagged)})</h2>
{chr(10).join(cards_flagged) or '<p class="muted">None.</p>'}
<h2 class="section">Routine ({len(routine)})</h2>
{chr(10).join(cards_routine) or '<p class="muted">None.</p>'}
<footer>Generated by python -m triage.report. Static page: no scripts, no network access.</footer>
</main>
</body>
</html>
"""


# --- Live entries (out/live.jsonl) --------------------------------------------------


def load_live(path: Path) -> tuple[list[LiveEntry], list[str]]:
    """Live entries, plus a warning for each line that can't be read (skipped, never fatal)."""
    if not path.is_file():
        return [], []
    entries, warnings = [], []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entries.append(LiveEntry.model_validate_json(line))
        except ValidationError:
            warnings.append(f"{path} line {line_no} isn't a valid live entry and was skipped")
    return entries, warnings


def next_live_id(path: Path) -> str:
    """live-001, live-002, ... one more than the entries already in the file."""
    count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip()) if path.is_file() else 0
    return f"{LIVE_ID_PREFIX}{count + 1:03d}"


def append_live(path: Path, email: Email, result: TriageResult) -> LiveEntry:
    entry = LiveEntry(recorded_at=f"{datetime.now():%Y-%m-%d %H:%M}", email=email, result=result)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(entry.model_dump_json() + "\n")
    return entry


def clear_live(path: Path) -> int:
    """Empty the live file. Returns how many entries were removed."""
    entries, _ = load_live(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return len(entries)


# --- Rebuild from saved files (no API calls) ------------------------------------


class ReportInputError(Exception):
    pass


def load_results(path: Path) -> list[TriageResult]:
    if not path.is_file():
        raise ReportInputError(f"no saved results at {path}. Run `python -m triage.cli data/emails.jsonl` first.")
    results = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            results.append(TriageResult.model_validate_json(line))
        except ValidationError as exc:
            raise ReportInputError(
                f"{path} line {line_no} doesn't match the current result format. "
                "It was probably saved by an older version of the pipeline: re-run it."
            ) from exc
    return results


def rebuild_html(
    *,
    results_path: Path = DEFAULT_RESULTS,
    emails_path: Path = DEFAULT_EMAILS,
    live_path: Path | None = None,
    out_path: Path = DEFAULT_OUT,
    strict: bool = False,
) -> list[str]:
    """Rebuild queue.html from the saved batch results, their emails and the live entries.

    strict=False (used after --single and --clear-live): a missing or unreadable batch file
    becomes a warning and the page shows the live entries alone, so a live demo never fails here.
    strict=True (python -m triage.report): those problems raise ReportInputError.
    Returns the warnings.
    """
    from triage.classify import PROMPT_VERSION
    from triage.cli import InputError, load_emails  # imported here: triage.cli imports this module

    live_path = live_path or results_path.parent / LIVE_FILE
    live, warnings = load_live(live_path)
    results: list[TriageResult] = []
    emails: list[Email] = []
    try:
        if results_path.is_file() or strict and not live:
            results = load_results(results_path)
            emails = load_emails(emails_path)
    except (ReportInputError, InputError) as exc:
        if strict:
            raise ReportInputError(str(exc)) from exc
        warnings.append(f"batch results not shown: {exc}")
        results, emails = [], []

    models = Counter(r.model_used for r in [*results, *(e.result for e in live)] if r.model_used)
    model = ", ".join(m for m, _ in models.most_common()) or "unknown"
    if results:
        saved = datetime.fromtimestamp(results_path.stat().st_mtime)
        run_info = f"batch results saved {saved:%Y-%m-%d %H:%M}"
    else:
        run_info = "no batch results"
    if live:
        run_info += f" · {len(live)} live, last at {live[-1].recorded_at}"
    page = render_html(results, emails, model=model, run_info=run_info,
                       prompt_version=f"{PROMPT_VERSION} (current code)", live=live)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(page, encoding="utf-8")
    return warnings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m triage.report", description="Rebuild the HTML queue report.")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--emails", type=Path, default=DEFAULT_EMAILS)
    parser.add_argument("--live", type=Path, default=None, help="live entries (default: live.jsonl next to --results)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    try:
        warnings = rebuild_html(results_path=args.results, emails_path=args.emails, live_path=args.live,
                                out_path=args.out, strict=True)
    except ReportInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    print(f"Wrote {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
