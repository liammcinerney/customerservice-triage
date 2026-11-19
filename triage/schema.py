"""Pydantic models for the input emails, the model's output, and the final triage record.

Design rule: `ModelOutput` (what the LLM returns) has no `needs_human` or `route_to`.
The model can't vote on escalation or routing. Those are set later by rules.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUMMARY_MAX_CHARS = 200

# Fairway Supply order numbers are always 9 digits starting with 1, for example
# #100046249. They may be written with or without the leading #. Any other number
# is not an order number. The canonical stored form is the 9 digits with no #.
ORDER_NUMBER_RE = re.compile(r"1\d{8}")


class Category(StrEnum):
    ORDER_STATUS = "order_status"
    STORE_ENQUIRY = "store_enquiry"
    LOYALTY = "loyalty_programme"
    WARRANTY = "warranty_claim"
    COMPLAINT = "complaint"
    COMPLIMENT = "compliment"  # added 2026-11-19: praise had no category (challenge email c02)
    OTHER = "other_or_spam"


class Urgency(StrEnum):
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Email(BaseModel):
    """One line of data/emails.jsonl. The text is untrusted data, never instructions."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    sender: str
    subject: str
    body: str


class Details(BaseModel):
    """Key details. Each must appear word for word in the email, or be null (an empty
    list for order numbers).

    Every field is required (but nullable), so the model has to decide on each one
    explicitly instead of leaving it out.
    """

    model_config = ConfigDict(extra="forbid")

    # A list since 2026-11-19: an email can mention several orders (challenge email c03),
    # and every one must be kept.
    order_numbers: list[str] = Field(
        description=(
            "Every order number in the email, in the order they appear. Each is 9 digits starting "
            "with 1 (e.g. 100046249), digits only, no #. Empty list if the email has no number in "
            "exactly that format"
        )
    )
    store: str | None = Field(description="Store name exactly as written in the email, or null")
    product: str | None = Field(description="Product exactly as written in the email, or null")
    customer_name: str | None = Field(description="Customer's name exactly as written in the email, or null")

    @field_validator("store", "product", "customer_name", mode="before")
    @classmethod
    def blank_to_none(cls, value: object) -> object:
        """Treat "" or whitespace as "not stated", and trim surrounding whitespace."""
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("order_numbers", mode="before")
    @classmethod
    def clean_order_numbers(cls, value: object) -> object:
        """Trim each entry, drop blank ones and remove repeats (keeping first-seen order)."""
        if isinstance(value, list):
            cleaned = [v.strip() if isinstance(v, str) else v for v in value]
            return list(dict.fromkeys(v for v in cleaned if v != ""))
        return value

    @classmethod
    def empty(cls) -> Details:
        return cls(order_numbers=[], store=None, product=None, customer_name=None)


class ModelOutput(BaseModel):
    """Exactly what the model returns for one email: classification, details, summary."""

    model_config = ConfigDict(extra="forbid")

    category: Category
    urgency: Urgency
    details: Details
    summary: str = Field(
        min_length=1,
        max_length=SUMMARY_MAX_CHARS,
        description="One line on what the customer wants",
    )

    @field_validator("summary", mode="before")
    @classmethod
    def one_line(cls, value: object) -> object:
        """Collapse newlines and runs of whitespace into single spaces."""
        if isinstance(value, str):
            return " ".join(value.split())
        return value


class LabelDetails(BaseModel):
    """Expected details for one email. Customer name isn't scored.

    - order_numbers: null (none expected) or the exact list of order numbers the
      email contains. ALL of them must be extracted.
    - store, product: null (nothing should be extracted) or a list of acceptable
      spans copied from the email. ANY ONE of them counts as correct.
    """

    model_config = ConfigDict(extra="forbid")

    order_numbers: list[str] | None
    store: list[str] | None
    product: list[str] | None

    @field_validator("order_numbers", "store", "product")
    @classmethod
    def non_empty_spans(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and (not value or any(not span.strip() for span in value)):
            raise ValueError("use null for 'nothing to extract', or a list of non-blank spans")
        return value

    @field_validator("order_numbers")
    @classmethod
    def canonical_order_numbers(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not ORDER_NUMBER_RE.fullmatch(span) for span in value):
            raise ValueError("labelled order numbers must be canonical: 9 digits starting with 1, no #")
        if value is not None and len(set(value)) != len(value):
            raise ValueError("labelled order numbers must not repeat")
        return value


class Label(BaseModel):
    """One line of data/labels.jsonl: the hand-checked expected answer for one email."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    category: Category
    needs_human: bool
    # Rule-level signals the email contains, e.g. "legal threat". Category-based
    # escalation (warranty claim, complaint) isn't listed here.
    expected_reasons: list[str] = Field(default_factory=list)
    details: LabelDetails
    notes: str = ""


DROP_NOT_IN_EMAIL = "not in email"
DROP_INVALID_ORDER_NUMBER = "not a valid order number"


class DroppedDetail(BaseModel):
    """A detail the model returned that failed validation and was blanked.

    - "not in email": the value isn't in the email, so it was invented. It's for audit
      only and never shown to the officer as a fact.
    - "not a valid order number": the value doesn't match the order number format.
      It may be copied from the email (e.g. a mistyped number), so the queue can show
      it as "customer quoted ...".
    """

    model_config = ConfigDict(extra="forbid")

    field: Literal["order_numbers", "store", "product", "customer_name"]
    value: str
    reason: Literal["not in email", "not a valid order number"]


class TriageResult(BaseModel):
    """One line of out/triage.jsonl: the model's fields plus everything decided by code."""

    model_config = ConfigDict(extra="forbid")

    id: str
    status: Literal["ok", "failed"]
    # None only when status == "failed" (the model call never produced valid output).
    category: Category | None
    urgency: Urgency | None
    summary: str | None
    details: Details
    # Details the model returned that failed the format or quote check. Kept for audit and the eval.
    dropped_details: list[DroppedDetail] = Field(default_factory=list)
    route_to: str
    needs_human: bool
    escalation_reasons: list[str] = Field(default_factory=list)
    attempts: int = Field(ge=0, le=2)
    error: str | None = None
    model_used: str | None = None  # the model that answered (differs from the requested one after a fallback)

    @model_validator(mode="after")
    def check_consistency(self) -> TriageResult:
        if self.status == "ok" and (self.category is None or self.urgency is None or self.summary is None):
            raise ValueError("status 'ok' needs category, urgency and summary")
        if self.status == "failed" and not self.needs_human:
            raise ValueError("a failed classification must go to a human")
        if self.needs_human and not self.escalation_reasons:
            raise ValueError("needs_human is True but no escalation_reasons given")
        if not self.needs_human and self.escalation_reasons:
            raise ValueError("escalation_reasons given but needs_human is False")
        return self


class LiveEntry(BaseModel):
    """One line of out/live.jsonl: an email triaged live with `--single`, and its result.

    Live emails are unlabelled. They are shown in out/queue.html with a "Live" tag but
    are never written to data/ and never read by the eval.
    """

    model_config = ConfigDict(extra="forbid")

    recorded_at: str
    email: Email
    result: TriageResult

    @model_validator(mode="after")
    def ids_match(self) -> LiveEntry:
        if self.email.id != self.result.id:
            raise ValueError("email and result ids differ")
        return self
