"""Order number format, quote check and output parsing, using fixed example outputs (no API calls)."""

import json

import pytest

from triage.schema import (
    DROP_INVALID_ORDER_NUMBER,
    DROP_NOT_IN_EMAIL,
    Details,
    DroppedDetail,
    Email,
    ModelOutput,
)
from triage.validate import (
    ValidationFailure,
    appears_in,
    canonical_order_numbers,
    check_details,
    check_order_numbers,
    find_order_numbers,
    normalize,
    parse_output,
    quote_check,
)

EMAIL = Email(
    id="t1",
    sender="Martin Hale <m.hale@example.com>",
    subject="Where's my order #100048213?",
    body=(
        "Hi, I bought a Strata pull buggy at the Richmond store and it hasn’t arrived.\n"
        "The   tracking says\n'in transit'.\n\nMartin"
    ),
)

SHORT_EMAIL = Email(id="t2", sender="dkowalski88@example.com", subject="", body="order??")

TYPO_EMAIL = Email(
    id="t3",
    sender="Josh <josh@example.com>",
    subject="Order update?",
    body="My order number is #10046249 I think. Receipt 204417765. Card ends 4471.",
)


def details(**values) -> Details:
    return Details.empty().model_copy(update=values)


def dropped(field: str, value: str, reason: str) -> DroppedDetail:
    return DroppedDetail(field=field, value=value, reason=reason)


# --- normalize / appears_in --------------------------------------------------


def test_normalize_case_whitespace_and_typographic_quotes():
    assert normalize("  Hasn’t   ARRIVED\n– ok ") == "hasn't arrived - ok"


@pytest.mark.parametrize(
    "span",
    [
        "#100048213",
        "100048213",  # the # is optional
        "Strata pull buggy",
        "strata PULL buggy",  # case ignored
        "Richmond store",
        "Richmond",
        "hasn't arrived",  # straight quote matches the email's curly one
        "tracking says 'in transit'",  # spans a line break and a run of spaces
    ],
)
def test_appears_in_accepts_word_for_word_spans(span):
    assert appears_in(span, f"{EMAIL.subject}\n{EMAIL.body}")


@pytest.mark.parametrize(
    "span",
    [
        "Richm",  # partial word
        "10004821",  # part of a number
        "order 100048213",  # email says "order #100048213"
        "Strata buggy",  # words dropped from the middle
        "Geelong store",  # not in the email at all
        "",
        "   ",
    ],
)
def test_appears_in_rejects_anything_else(span):
    assert not appears_in(span, f"{EMAIL.subject}\n{EMAIL.body}")


# --- Order number format -----------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        ("#100046249", ["100046249"]),
        ("100046249", ["100046249"]),
        ("  #100046249 ", ["100046249"]),
        ("Order #100046249", ["100046249"]),
        ("order no. 199999999", ["199999999"]),
        # Two orders in one entry: both kept, so a lumped answer doesn't lose an order.
        ("#100043249 and #100085626", ["100043249", "100085626"]),
        ("100046249 or 100046250", ["100046249", "100046250"]),
        ("100046249, #100046249", ["100046249"]),  # repeated: kept once
    ],
)
def test_valid_order_numbers_are_made_canonical(value, expected):
    assert canonical_order_numbers(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "#10046249",  # 8 digits
        "1000462491",  # 10 digits
        "200046249",  # starts with 2
        "000046249",  # starts with 0
        "4471",  # card number
        "#1",  # "#1 on Google"
        "R-204417765",  # receipt number, starts with 2
        "100046249/2",  # extra digits
        "100046249 and 4471",  # a valid number plus stray digits
        "1 000 46249",  # split up
        "",
    ],
)
def test_anything_else_is_not_an_order_number(value):
    assert canonical_order_numbers(value) is None


def test_find_order_numbers_in_text():
    text = "Orders #100046249 and 100046250, again #100046249. Not 10046249, 2000462491 or 1000462491."
    assert find_order_numbers(text) == ["100046249", "100046250"]


def test_find_order_numbers_ignores_near_misses():
    assert find_order_numbers(f"{TYPO_EMAIL.subject}\n{TYPO_EMAIL.body}") == []


def test_check_order_numbers_canonicalizes_valid_values():
    kept, dropped_list = check_order_numbers(details(order_numbers=["#100048213"]))
    assert kept.order_numbers == ["100048213"]
    assert dropped_list == []


def test_check_order_numbers_drops_invalid_format_with_reason():
    kept, dropped_list = check_order_numbers(details(order_numbers=["#10046249"], store="Richmond"))
    assert kept.order_numbers == []
    assert kept.store == "Richmond"  # other fields untouched
    assert dropped_list == [dropped("order_numbers", "#10046249", DROP_INVALID_ORDER_NUMBER)]


def test_check_order_numbers_keeps_valid_entries_and_drops_bad_ones_individually():
    kept, dropped_list = check_order_numbers(details(order_numbers=["#100043249", "4471", "100085626"]))
    assert kept.order_numbers == ["100043249", "100085626"]
    assert dropped_list == [dropped("order_numbers", "4471", DROP_INVALID_ORDER_NUMBER)]


def test_check_order_numbers_removes_repeats_across_entries():
    kept, _ = check_order_numbers(details(order_numbers=["#100048213", "Order 100048213"]))
    assert kept.order_numbers == ["100048213"]


# --- quote_check -------------------------------------------------------------


def test_genuine_details_are_kept():
    found = details(order_numbers=["100048213"], store="Richmond store", product="Strata pull buggy", customer_name="Martin")
    kept, dropped_list = quote_check(found, EMAIL)
    assert kept == found
    assert dropped_list == []


def test_invented_detail_is_dropped():
    kept, dropped_list = quote_check(details(product="Vantage V7 driver"), SHORT_EMAIL)
    assert kept.product is None
    assert dropped_list == [dropped("product", "Vantage V7 driver", DROP_NOT_IN_EMAIL)]


def test_mixed_kept_and_dropped():
    found = details(order_numbers=["100048213"], store="Geelong", product="AeroLite rangefinder")
    kept, dropped_list = quote_check(found, EMAIL)
    assert kept.order_numbers == ["100048213"]
    assert kept.store is None and kept.product is None
    assert dropped_list == [
        dropped("store", "Geelong", DROP_NOT_IN_EMAIL),
        dropped("product", "AeroLite rangefinder", DROP_NOT_IN_EMAIL),
    ]


def test_case_variant_is_kept_as_returned():
    kept, dropped_list = quote_check(details(store="RICHMOND store"), EMAIL)
    assert kept.store == "RICHMOND store"
    assert dropped_list == []


def test_customer_name_may_come_from_sender_line():
    kept, dropped_list = quote_check(details(customer_name="Martin Hale"), EMAIL)
    assert kept.customer_name == "Martin Hale"
    assert dropped_list == []


def test_detail_may_not_come_from_sender_address():
    """'dkowalski' appears in the sender address, but only customer_name may come from there."""
    kept, dropped_list = quote_check(details(product="dkowalski88"), SHORT_EMAIL)
    assert kept.product is None
    assert dropped_list == [dropped("product", "dkowalski88", DROP_NOT_IN_EMAIL)]


def test_nothing_extracted_nothing_dropped():
    kept, dropped_list = quote_check(Details.empty(), SHORT_EMAIL)
    assert kept == Details.empty()
    assert dropped_list == []


# --- check_details: format first, then quote ---------------------------------


def test_check_details_keeps_valid_order_number_in_canonical_form():
    kept, dropped_list = check_details(details(order_numbers=["#100048213"], store="Richmond"), EMAIL)
    assert kept.order_numbers == ["100048213"]
    assert kept.store == "Richmond"
    assert dropped_list == []


def test_check_details_drops_mistyped_order_number_as_invalid_format():
    """The customer wrote #10046249 (8 digits). It's in the email, but it isn't an order number."""
    kept, dropped_list = check_details(details(order_numbers=["#10046249"]), TYPO_EMAIL)
    assert kept.order_numbers == []
    assert dropped_list == [dropped("order_numbers", "#10046249", DROP_INVALID_ORDER_NUMBER)]


@pytest.mark.parametrize("value", ["204417765", "4471"])
def test_check_details_rejects_other_numbers_in_the_email(value):
    kept, dropped_list = check_details(details(order_numbers=[value]), TYPO_EMAIL)
    assert kept.order_numbers == []
    assert dropped_list == [dropped("order_numbers", value, DROP_INVALID_ORDER_NUMBER)]


def test_check_details_drops_invented_valid_format_number_as_not_in_email():
    """Right format, but the 'order??' email never mentions it: invented."""
    kept, dropped_list = check_details(details(order_numbers=["100046249"]), SHORT_EMAIL)
    assert kept.order_numbers == []
    assert dropped_list == [dropped("order_numbers", "100046249", DROP_NOT_IN_EMAIL)]


# --- parse_output ------------------------------------------------------------

VALID = {
    "category": "order_status",
    "urgency": "normal",
    "details": {"order_numbers": ["100048213"], "store": None, "product": None, "customer_name": None},
    "summary": "Wants to know where order #100048213 is.",
}


def test_parse_valid_output():
    result = parse_output(json.dumps(VALID))
    assert isinstance(result, ModelOutput)
    assert result.details.order_numbers == ["100048213"]


def test_parse_malformed_json_fails_without_raising():
    result = parse_output('{"category": "order_status", ')
    assert isinstance(result, ValidationFailure)
    assert result.error


def test_parse_bad_category_names_the_field():
    result = parse_output(json.dumps(VALID | {"category": "refund"}))
    assert isinstance(result, ValidationFailure)
    assert "category" in result.error


def test_parse_rejects_model_setting_needs_human():
    result = parse_output(json.dumps(VALID | {"needs_human": False}))
    assert isinstance(result, ValidationFailure)
    assert "needs_human" in result.error


def test_parse_error_message_is_short():
    junk = {"category": "x", "urgency": "y", "details": {}, "summary": ""}
    result = parse_output(json.dumps(junk))
    assert isinstance(result, ValidationFailure)
    assert len(result.error) <= 300


# --- Several order numbers (challenge email c03) ------------------------------

TWO_ORDERS = Email(
    id="t4",
    sender="David <david@example.com>",
    subject="Check updates for my orders",
    body="I put through a couple orders last week (#100043249 and #100085626). Any update?",
)


def test_check_details_keeps_every_order_number():
    kept, dropped_list = check_details(details(order_numbers=["100043249", "#100085626"]), TWO_ORDERS)
    assert kept.order_numbers == ["100043249", "100085626"]
    assert dropped_list == []


def test_check_details_splits_two_orders_given_as_one_entry():
    kept, dropped_list = check_details(details(order_numbers=["#100043249 and #100085626"]), TWO_ORDERS)
    assert kept.order_numbers == ["100043249", "100085626"]
    assert dropped_list == []


def test_one_invented_order_number_does_not_cost_the_real_ones():
    kept, dropped_list = check_details(
        details(order_numbers=["100043249", "100099999", "100085626"]), TWO_ORDERS
    )
    assert kept.order_numbers == ["100043249", "100085626"]
    assert dropped_list == [dropped("order_numbers", "100099999", DROP_NOT_IN_EMAIL)]
