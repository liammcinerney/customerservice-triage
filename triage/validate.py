"""Schema validation of the model's output, the order number format check and the quote check.

Order number format (domain rule): always 9 digits starting with 1, e.g. #100046249.
Any other number isn't an order number. Values are stored in canonical form:
the 9 digits with no #. An email may mention several orders, and every valid one is kept.

Quote check: each extracted detail must appear in the email exactly as written,
ignoring only case, runs of whitespace and curly-vs-straight quotes and dashes.
It must also match whole words: "Richm" doesn't count as appearing in "Richmond".

A detail that fails either check is blanked and recorded as a DroppedDetail with
the reason. It isn't escalated (decided 2026-11-18).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from triage.schema import (
    DROP_INVALID_ORDER_NUMBER,
    DROP_NOT_IN_EMAIL,
    Details,
    DroppedDetail,
    Email,
    ModelOutput,
)

QUOTE_FIELDS = ("order_numbers", "store", "product", "customer_name")

_TYPOGRAPHIC = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", " ": " ",
})

# An order number standing on its own: not part of a longer run of digits.
_ORDER_TOKEN = re.compile(r"(?<!\d)1\d{8}(?!\d)")


def normalize(text: str) -> str:
    """Case-fold, straighten typographic quotes and dashes, and collapse whitespace runs."""
    return " ".join(text.translate(_TYPOGRAPHIC).casefold().split())


def appears_in(span: str, text: str) -> bool:
    """True if `span` appears word for word in `text` as whole words, after `normalize`."""
    needle = normalize(span)
    if not needle:
        return False
    pattern = rf"(?<!\w){re.escape(needle)}(?!\w)"
    return re.search(pattern, normalize(text)) is not None


# --- Order number format -----------------------------------------------------


def canonical_order_numbers(value: str) -> list[str] | None:
    """The canonical order numbers in one extracted value, or None if it isn't made of them.

    "#100046249", "100046249" and "Order #100046249" all give ["100046249"].
    "#100043249 and #100085626" gives both, in case the model puts two in one entry.
    "#10046249" (8 digits), "200046249" (starts with 2), "1000462491" (10 digits), "4471"
    and "100046249/2" (stray extra digits) all give None.
    """
    tokens = _ORDER_TOKEN.findall(value)
    if not tokens or sum(ch.isdigit() for ch in value) != 9 * len(tokens):
        return None
    return list(dict.fromkeys(tokens))


def find_order_numbers(text: str) -> list[str]:
    """All valid-format order numbers in `text`, canonical, unique, in order of appearance."""
    return list(dict.fromkeys(_ORDER_TOKEN.findall(text)))


def check_order_numbers(details: Details) -> tuple[Details, list[DroppedDetail]]:
    """Put each valid order number into canonical form. Drop each entry that isn't one."""
    kept: list[str] = []
    dropped: list[DroppedDetail] = []
    for value in details.order_numbers:
        canonical = canonical_order_numbers(value)
        if canonical is None:
            dropped.append(DroppedDetail(field="order_numbers", value=value, reason=DROP_INVALID_ORDER_NUMBER))
        else:
            kept.extend(canonical)
    return details.model_copy(update={"order_numbers": list(dict.fromkeys(kept))}), dropped


# --- Quote check -------------------------------------------------------------


def quote_source(email: Email, field: str) -> str:
    """The email text a detail must come from.

    The customer's name may come from the sender line ("Martin Hale <...>"). Other
    details must be in the subject or body, so a number in an address like
    dkowalski88@example.com can't pass as an order number.
    """
    if field == "customer_name":
        return f"{email.sender}\n{email.subject}\n{email.body}"
    return f"{email.subject}\n{email.body}"


def quote_check(details: Details, email: Email) -> tuple[Details, list[DroppedDetail]]:
    """Keep the details found in the email. Blank the others and return them as dropped.
    Each order number is checked on its own, so one invented number doesn't cost a real one."""
    kept: dict[str, object] = {}
    dropped: list[DroppedDetail] = []
    for field in QUOTE_FIELDS:
        value = getattr(details, field)
        source = quote_source(email, field)
        if isinstance(value, list):
            kept[field] = []
            for item in value:
                if appears_in(item, source):
                    kept[field].append(item)
                else:
                    dropped.append(DroppedDetail(field=field, value=item, reason=DROP_NOT_IN_EMAIL))
            continue
        if value is not None and not appears_in(value, source):
            dropped.append(DroppedDetail(field=field, value=value, reason=DROP_NOT_IN_EMAIL))
            value = None
        kept[field] = value
    return Details(**kept), dropped


def check_details(details: Details, email: Email) -> tuple[Details, list[DroppedDetail]]:
    """The full detail check: order number format first, then the quote check on what's left."""
    details, dropped_format = check_order_numbers(details)
    details, dropped_quote = quote_check(details, email)
    return details, dropped_format + dropped_quote


# --- Parsing the model's output ----------------------------------------------


@dataclass(frozen=True)
class ValidationFailure:
    """The model's output couldn't be used. `error` is short enough to send back on a retry."""

    error: str


def _summarize(exc: ValidationError, limit: int = 300) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        parts.append(f"{loc}: {err['msg']}")
    text = "; ".join(parts)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def parse_output(raw: str) -> ModelOutput | ValidationFailure:
    """Parse the model's JSON text into ModelOutput, or return why it failed. Never raises."""
    try:
        return ModelOutput.model_validate_json(raw)
    except ValidationError as exc:
        return ValidationFailure(error=_summarize(exc))
