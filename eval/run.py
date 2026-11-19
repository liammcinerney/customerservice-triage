"""Score triage output against the hand-checked labels.

  python -m eval.run                              run the pipeline (API calls), then score
  python -m eval.run --from out/triage.jsonl      score saved output, no API calls
  python -m eval.run --from out/triage.jsonl --note "what changed"

Prints a report and appends it to eval/results.md (use --no-save to skip).

Metrics:
- escalation recall (the headline): of emails labelled needs_human, how many were flagged
- escalation precision: of flagged emails, how many were labelled needs_human
- category accuracy
- extraction accuracy:
  - order numbers: the extracted set must equal the labelled set exactly (all of them,
    nothing extra). A null label means none.
  - store and product: exact match after normalizing case and whitespace, against any
    of the label's acceptable spans. A null label means nothing should be extracted.
- rule signals found: the labelled rule-level reasons that appear in escalation_reasons
- valid output on the first try / after the retry / failed
- dropped details by reason (invented vs not a valid order number)
- summaries with gendered pronouns or titles (gender is never guessed, from a name or anything else)
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from triage.schema import DROP_INVALID_ORDER_NUMBER, DROP_NOT_IN_EMAIL, Label, TriageResult
from triage.validate import normalize

EXTRACTION_FIELDS = ("order_numbers", "store", "product")
# Gendered pronouns and titles. Rule (prompt v2): summaries never guess anyone's gender.
GENDERED = re.compile(r"\b(he|him|his|himself|she|her|hers|herself|mr|mrs|ms)\b", re.IGNORECASE)

DEFAULT_EMAILS = Path("data/emails.jsonl")
DEFAULT_LABELS = Path("data/labels.jsonl")
DEFAULT_RESULTS_MD = Path("eval/results.md")


@dataclass
class Ratio:
    hit: int
    total: int

    def __str__(self) -> str:
        if self.total == 0:
            return "n/a"
        return f"{self.hit}/{self.total} ({100 * self.hit / self.total:.0f}%)"


@dataclass
class Scores:
    n: int
    recall: Ratio
    precision: Ratio
    category: Ratio
    extraction: dict[str, Ratio]
    rule_signals: Ratio
    valid_first_try: Ratio
    valid_after_retry: Ratio
    failed: int
    dropped: Counter
    gendered_summaries: Ratio
    models: Counter
    missed_escalations: list[str] = field(default_factory=list)
    false_flags: list[str] = field(default_factory=list)
    category_errors: list[str] = field(default_factory=list)
    extraction_errors: list[str] = field(default_factory=list)
    missed_signals: list[str] = field(default_factory=list)
    gendered_ids: list[str] = field(default_factory=list)
    missing_results: list[str] = field(default_factory=list)


def _matches(predicted: str | list[str] | None, acceptable: list[str] | None) -> bool:
    """Order numbers (a list): the sets must be equal. Other fields: any acceptable span matches."""
    if isinstance(predicted, list):
        return set(predicted) == set(acceptable or [])
    if acceptable is None:
        return predicted is None
    return predicted is not None and normalize(predicted) in {normalize(s) for s in acceptable}


def score(results: dict[str, TriageResult], labels: list[Label]) -> Scores:
    """Compare results with labels. A label with no result counts as wrong everywhere."""
    tp = fn = fp = 0
    category_hits = 0
    field_hits = Counter()
    signals_hit = signals_total = 0
    first_try = after_retry = failed = 0
    dropped: Counter = Counter()
    gendered: list[str] = []
    summaries = 0
    models: Counter = Counter()
    s = {
        "missed_escalations": [], "false_flags": [], "category_errors": [], "extraction_errors": [],
        "missed_signals": [], "missing_results": [],
    }

    for lab in labels:
        r = results.get(lab.id)
        if r is None:
            s["missing_results"].append(lab.id)
            if lab.needs_human:
                fn += 1
                s["missed_escalations"].append(lab.id)
            signals_total += len(lab.expected_reasons)
            continue

        # Escalation
        if lab.needs_human and r.needs_human:
            tp += 1
        elif lab.needs_human:
            fn += 1
            s["missed_escalations"].append(lab.id)
        elif r.needs_human:
            fp += 1
            s["false_flags"].append(f"{lab.id} ({', '.join(r.escalation_reasons)})")

        # Category
        if r.category == lab.category:
            category_hits += 1
        else:
            got = r.category.value if r.category else "none"
            s["category_errors"].append(f"{lab.id}: {got}, expected {lab.category.value}")

        # Extraction
        for f in EXTRACTION_FIELDS:
            predicted = getattr(r.details, f)
            acceptable = getattr(lab.details, f)
            if _matches(predicted, acceptable):
                field_hits[f] += 1
            else:
                s["extraction_errors"].append(f"{lab.id}.{f}: {predicted!r}, expected {acceptable}")

        # Rule signals
        for reason in lab.expected_reasons:
            signals_total += 1
            if reason in r.escalation_reasons:
                signals_hit += 1
            else:
                s["missed_signals"].append(f"{lab.id}: {reason}")

        # Validity
        if r.status == "ok":
            after_retry += 1
            if r.attempts == 1:
                first_try += 1
        else:
            failed += 1

        dropped.update(d.reason for d in r.dropped_details)
        if r.model_used:
            models[r.model_used] += 1

        if r.summary:
            summaries += 1
            if GENDERED.search(r.summary):
                gendered.append(lab.id)

    n = len(labels)
    return Scores(
        n=n,
        recall=Ratio(tp, tp + fn),
        precision=Ratio(tp, tp + fp),
        category=Ratio(category_hits, n),
        extraction={f: Ratio(field_hits[f], n) for f in EXTRACTION_FIELDS},
        rule_signals=Ratio(signals_hit, signals_total),
        valid_first_try=Ratio(first_try, n),
        valid_after_retry=Ratio(after_retry, n),
        failed=failed,
        dropped=dropped,
        gendered_summaries=Ratio(len(gendered), summaries),
        models=models,
        gendered_ids=gendered,
        **s,
    )


def format_report(scores: Scores, meta: dict[str, str]) -> str:
    def listed(items: list[str]) -> str:
        return ", ".join(items) if items else "none"

    models = ", ".join(f"{m} x{c}" for m, c in scores.models.most_common()) or "unknown"
    lines = [
        f"## {meta['when']} - {meta['source']}",
        "",
        f"Models that answered: {models} · effort {meta['effort']} · prompt {meta['prompt_version']} · {scores.n} emails",
    ]
    if meta.get("note"):
        lines += ["", f"Note: {meta['note']}"]
    lines += [
        "",
        "| Metric | Result |",
        "| --- | --- |",
        f"| **Escalation recall** (headline) | **{scores.recall}** |",
        f"| Escalation precision | {scores.precision} |",
        f"| Category accuracy | {scores.category} |",
        *(f"| Extraction: {f.replace('_', ' ')} | {r} |" for f, r in scores.extraction.items()),
        f"| Rule signals found | {scores.rule_signals} |",
        f"| Valid output, first try | {scores.valid_first_try} |",
        f"| Valid output, after retry | {scores.valid_after_retry} |",
        f"| Failed classification | {scores.failed} |",
        f"| Dropped details: invented (not in email) | {scores.dropped.get(DROP_NOT_IN_EMAIL, 0)} |",
        f"| Dropped details: not a valid order number | {scores.dropped.get(DROP_INVALID_ORDER_NUMBER, 0)} |",
        f"| Summaries with gendered pronouns or titles | {scores.gendered_summaries} |",
        "",
        f"- Missed escalations: {listed(scores.missed_escalations)}",
        f"- False flags: {listed(scores.false_flags)}",
        f"- Category errors: {listed(scores.category_errors)}",
        f"- Extraction errors: {listed(scores.extraction_errors)}",
        f"- Missed rule signals: {listed(scores.missed_signals)}",
        f"- Gendered summaries: {listed(scores.gendered_ids)}",
    ]
    if scores.missing_results:
        lines.append(f"- **Missing results:** {listed(scores.missing_results)}")
    return "\n".join(lines) + "\n"


RESULTS_HEADER = (
    "# Eval results\n\n"
    "Each run is appended by `python -m eval.run`. Newest at the bottom. "
    "Labels: `data/labels.jsonl` (hand-checked). Synthetic data only.\n"
)


def save_report(report: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else RESULTS_HEADER
    path.write_text(existing.rstrip() + "\n\n" + report, encoding="utf-8")


def load_labels(path: Path) -> list[Label]:
    return [Label.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ResultsFormatError(Exception):
    """A saved triage.jsonl is missing, or doesn't match the current result format."""


def load_results(path: Path) -> dict[str, TriageResult]:
    if not path.is_file():
        raise ResultsFormatError(f"no saved results at {path}")
    results = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            r = TriageResult.model_validate_json(line)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"])
            raise ResultsFormatError(
                f"{path} line {line_no} doesn't match the current result format ({where}: {first['msg']}). "
                "It was probably saved by an older version of the pipeline. Re-run it to regenerate the file."
            ) from exc
        results[r.id] = r
    return results


def main(argv: list[str] | None = None, client: Any = None) -> int:
    from triage import classify as classify_mod
    from triage import cli
    from triage.config import load_env, model_name

    parser = argparse.ArgumentParser(prog="python -m eval.run", description="Score triage output against labels.")
    parser.add_argument("--from", dest="from_path", type=Path, help="score this triage.jsonl instead of running the pipeline")
    parser.add_argument("--emails", type=Path, default=DEFAULT_EMAILS)
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--out", type=Path, default=Path("out"), help="where a live run writes its output")
    parser.add_argument("--model", default=None)
    parser.add_argument("--note", default="", help="what changed since the last run")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_MD)
    parser.add_argument("--no-save", action="store_true")
    args = parser.parse_args(argv)

    labels = load_labels(args.labels)

    if args.from_path:
        try:
            results = load_results(args.from_path)
        except ResultsFormatError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        source = f"scored from {args.from_path}"
    else:
        load_env()
        model = args.model or model_name()
        emails = cli.load_emails(args.emails)
        try:
            client = client or classify_mod.make_client()
            print(f"Running pipeline on {len(emails)} emails with {model} ...", file=sys.stderr)
            run = cli.run_pipeline(emails, client, model)
        except cli.FATAL_ERRORS as exc:
            print(f"error: the API rejected the request ({type(exc).__name__}). Check .env and the model name.", file=sys.stderr)
            return 2
        cli.write_outputs(run, emails, args.out, model)
        results = {r.id: r for r in run}
        source = f"live run, requested {model}"

    scores = score(results, labels)
    # A saved file doesn't record which prompt or effort produced it, so --from reports the current code's.
    as_of = " (current code)" if args.from_path else ""
    meta = {
        "when": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source": source,
        "effort": classify_mod.EFFORT + as_of,
        "prompt_version": classify_mod.PROMPT_VERSION + as_of,
        "note": args.note,
    }
    report = format_report(scores, meta)
    print(report)
    if not args.no_save:
        save_report(report, args.results)
        print(f"Appended to {args.results}", file=sys.stderr)
    if scores.missed_escalations:
        print(f"WARNING: missed escalations: {', '.join(scores.missed_escalations)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
