"""Schema validation in triage.schema, using fixed example outputs (no API calls)."""

import json

import pytest
from pydantic import ValidationError

from triage.schema import (
    SUMMARY_MAX_CHARS,
    Category,
    Details,
    DroppedDetail,
    Email,
    LabelDetails,
    ModelOutput,
    TriageResult,
    Urgency,
)


def model_output_dict(**overrides):
    data = {
        "category": "order_status",
        "urgency": "normal",
        "details": {
            "order_numbers": ["100048213"],
            "store": None,
            "product": None,
            "customer_name": "Priya",
        },
        "summary": "Wants to know where order #100048213 is.",
    }
    data.update(overrides)
    return data


def triage_result_dict(**overrides):
    data = {
        "id": "e01",
        "status": "ok",
        "category": "order_status",
        "urgency": "normal",
        "summary": "Wants to know where their order is.",
        "details": Details.empty().model_dump(),
        "route_to": "Online orders team",
        "needs_human": False,
        "escalation_reasons": [],
        "attempts": 1,
    }
    data.update(overrides)
    return data


# --- ModelOutput -------------------------------------------------------------


def test_valid_model_output_parses_from_json():
    out = ModelOutput.model_validate_json(json.dumps(model_output_dict()))
    assert out.category is Category.ORDER_STATUS
    assert out.urgency is Urgency.NORMAL
    assert out.details.order_numbers == ["100048213"]
    assert out.details.store is None


def test_unknown_category_rejected():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(model_output_dict(category="refund_request"))


def test_unknown_urgency_rejected():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(model_output_dict(urgency="critical"))


def test_model_cannot_set_needs_human():
    """The model's output schema has no needs_human field, so an extra field is rejected."""
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(model_output_dict(needs_human=False))


def test_model_cannot_set_route_to():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(model_output_dict(route_to="Spam bin"))


def test_overlong_summary_rejected():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(model_output_dict(summary="x" * (SUMMARY_MAX_CHARS + 1)))


def test_empty_summary_rejected():
    with pytest.raises(ValidationError):
        ModelOutput.model_validate(model_output_dict(summary="   "))


def test_multiline_summary_collapsed_to_one_line():
    out = ModelOutput.model_validate(model_output_dict(summary="Wants a refund.\n\n  Also asks  about points."))
    assert out.summary == "Wants a refund. Also asks about points."


# --- Details -----------------------------------------------------------------


def test_blank_details_become_none_and_values_are_trimmed():
    details = Details.model_validate(
        {"order_numbers": ["", " 100048213 ", "100048213"], "store": "   ", "product": "  TSR3 driver ", "customer_name": None}
    )
    assert details.order_numbers == ["100048213"]  # blank dropped, trimmed, repeat removed
    assert details.store is None
    assert details.product == "TSR3 driver"


def test_every_detail_field_must_be_present():
    """Required but nullable: the model must say null rather than leave a field out."""
    with pytest.raises(ValidationError):
        Details.model_validate({"order_numbers": ["100048213"]})


def test_extra_detail_field_rejected():
    data = Details.empty().model_dump() | {"email_address": "a@b.com"}
    with pytest.raises(ValidationError):
        Details.model_validate(data)


# --- Email -------------------------------------------------------------------


def test_email_parses():
    email = Email.model_validate_json(
        '{"id": "e01", "sender": "Priya <priya@example.com>", "subject": "Order", "body": "order??"}'
    )
    assert email.body == "order??"


def test_email_missing_body_rejected():
    with pytest.raises(ValidationError):
        Email.model_validate({"id": "e01", "sender": "x", "subject": "y"})


def test_email_empty_id_rejected():
    with pytest.raises(ValidationError):
        Email.model_validate({"id": "", "sender": "x", "subject": "y", "body": "z"})


# --- TriageResult invariants -------------------------------------------------


def test_routine_result_is_valid():
    result = TriageResult.model_validate(triage_result_dict())
    assert result.needs_human is False


def test_flagged_result_is_valid():
    result = TriageResult.model_validate(
        triage_result_dict(needs_human=True, escalation_reasons=["legal threat"])
    )
    assert result.escalation_reasons == ["legal threat"]


def test_needs_human_without_reasons_rejected():
    with pytest.raises(ValidationError):
        TriageResult.model_validate(triage_result_dict(needs_human=True, escalation_reasons=[]))


def test_reasons_without_needs_human_rejected():
    with pytest.raises(ValidationError):
        TriageResult.model_validate(triage_result_dict(needs_human=False, escalation_reasons=["legal threat"]))


def test_failed_result_may_have_no_category_but_must_go_to_human():
    failed = TriageResult.model_validate(
        triage_result_dict(
            status="failed",
            category=None,
            urgency=None,
            summary=None,
            needs_human=True,
            escalation_reasons=["classification failed"],
            attempts=2,
            error="refusal",
        )
    )
    assert failed.category is None

    with pytest.raises(ValidationError):
        TriageResult.model_validate(
            triage_result_dict(status="failed", category=None, urgency=None, summary=None, attempts=2)
        )


def test_ok_result_needs_category():
    with pytest.raises(ValidationError):
        TriageResult.model_validate(triage_result_dict(category=None))


def test_attempts_capped_at_two():
    with pytest.raises(ValidationError):
        TriageResult.model_validate(triage_result_dict(attempts=3))


# --- Order number format in labels and dropped details -----------------------


def test_model_is_told_the_order_number_format():
    """The JSON schema the model sees describes the format, so it can skip other numbers."""
    schema = ModelOutput.model_json_schema()
    description = schema["$defs"]["Details"]["properties"]["order_numbers"]["description"]
    assert "9 digits starting with 1" in description


def test_label_order_numbers_must_be_canonical():
    LabelDetails(order_numbers=["100046249", "100046250"], store=None, product=None)
    for bad in (["#100046249"], ["46249"], ["200046249"], ["100046249", "100046249"]):
        with pytest.raises(ValidationError):
            LabelDetails(order_numbers=bad, store=None, product=None)


def test_dropped_detail_reason_is_restricted():
    DroppedDetail(field="order_numbers", value="#10046249", reason="not a valid order number")
    with pytest.raises(ValidationError):
        DroppedDetail(field="order_numbers", value="x", reason="looked wrong")


def test_triage_result_carries_dropped_details():
    result = TriageResult.model_validate(
        triage_result_dict(
            dropped_details=[{"field": "order_numbers", "value": "#10046249", "reason": "not a valid order number"}]
        )
    )
    assert result.dropped_details[0].reason == "not a valid order number"
