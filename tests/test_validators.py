"""Tests for generic validators, invoice schema, and invoice business rules."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from selfcorrect.invoices.rules import (
    AmountSignValidator,
    CurrencyValidator,
    DatePlausibilityValidator,
    LineItemMathValidator,
    LineItemsSumValidator,
    TotalsValidator,
    build_invoice_validator,
)
from selfcorrect.invoices.schema import InvoiceSchemaValidator
from selfcorrect.types import Severity, Validator, Violation
from selfcorrect.validators import CompositeValidator, RequiredFieldsValidator, as_decimal


def good_invoice() -> dict[str, Any]:
    """A fully-correct invoice; sums and totals are exact."""
    return {
        "vendor": "Acme Corp",
        "date": "2024-06-10",
        "currency": "USD",
        "line_items": [
            {"description": "Widget", "quantity": 2, "unit_price": 29.99, "amount": 59.98},
            {"description": "Gadget", "quantity": 1, "unit_price": 100.00, "amount": 100.00},
        ],
        "subtotal": 159.98,
        "tax": 12.80,
        "total": 172.78,
    }


def codes(violations: list[Violation]) -> list[str]:
    return [v.code for v in violations]


def errors(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity is Severity.ERROR]


# --------------------------------------------------------------------------- as_decimal


def test_as_decimal_parses_numbers() -> None:
    assert as_decimal(3) == Decimal("3")
    assert as_decimal(3.5) == Decimal("3.5")
    assert as_decimal("2.50") == Decimal("2.50")
    assert as_decimal(Decimal("1.23")) == Decimal("1.23")


def test_as_decimal_rejects_bool_none_and_garbage() -> None:
    assert as_decimal(True) is None
    assert as_decimal(False) is None
    assert as_decimal(None) is None
    assert as_decimal("abc") is None
    assert as_decimal(object()) is None
    assert as_decimal(float("nan")) is None
    assert as_decimal(float("inf")) is None


# ----------------------------------------------------------- generic field validators


def test_required_fields_missing_and_wrong_type() -> None:
    validator = RequiredFieldsValidator({"name": str, "count": (int, float)})
    assert validator.name == "required_fields"

    violations = validator.validate({"count": "five"})
    assert codes(violations) == ["MISSING_FIELD", "WRONG_TYPE"]
    assert violations[0].field == "name"
    assert violations[1].field == "count"
    assert violations[1].expected == "int|float"
    assert violations[1].actual == "str"

    assert validator.validate({"name": "x", "count": 5}) == []


def test_required_fields_bool_is_not_a_number() -> None:
    validator = RequiredFieldsValidator({"count": (int, float)})
    violations = validator.validate({"count": True})
    assert codes(violations) == ["WRONG_TYPE"]
    assert violations[0].actual == "bool"


def test_required_fields_bool_allowed_when_explicit() -> None:
    validator = RequiredFieldsValidator({"flag": bool})
    assert validator.validate({"flag": True}) == []


def test_composite_concatenates_in_order() -> None:
    first = RequiredFieldsValidator({"a": str})
    second = RequiredFieldsValidator({"b": int})
    composite = CompositeValidator([first, second])
    assert composite.name == "composite"
    violations = composite.validate({})
    assert [v.field for v in violations] == ["a", "b"]
    assert codes(violations) == ["MISSING_FIELD", "MISSING_FIELD"]


# --------------------------------------------------------------------- invoice schema


def test_schema_clean_on_good_invoice() -> None:
    assert InvoiceSchemaValidator().validate(good_invoice()) == []


def test_schema_missing_top_level_field() -> None:
    invoice = good_invoice()
    del invoice["vendor"]
    violations = InvoiceSchemaValidator().validate(invoice)
    assert codes(violations) == ["MISSING_FIELD"]
    assert violations[0].field == "vendor"


def test_schema_bool_is_not_a_number() -> None:
    invoice = good_invoice()
    invoice["subtotal"] = True
    violations = InvoiceSchemaValidator().validate(invoice)
    assert codes(violations) == ["WRONG_TYPE"]
    assert violations[0].field == "subtotal"
    assert violations[0].actual == "bool"


def test_schema_empty_line_items() -> None:
    invoice = good_invoice()
    invoice["line_items"] = []
    violations = InvoiceSchemaValidator().validate(invoice)
    assert codes(violations) == ["EMPTY_LINE_ITEMS"]
    assert violations[0].field == "line_items"


def test_schema_line_item_field_paths() -> None:
    invoice = good_invoice()
    invoice["line_items"][0]["quantity"] = True
    del invoice["line_items"][1]["amount"]
    violations = InvoiceSchemaValidator().validate(invoice)
    by_field = {v.field: v.code for v in violations}
    assert by_field == {
        "line_items[0].quantity": "WRONG_TYPE",
        "line_items[1].amount": "MISSING_FIELD",
    }


def test_schema_non_dict_line_item() -> None:
    invoice = good_invoice()
    invoice["line_items"][1] = "oops"
    violations = InvoiceSchemaValidator().validate(invoice)
    assert codes(violations) == ["WRONG_TYPE"]
    assert violations[0].field == "line_items[1]"


def test_schema_date_unparseable_only_for_strings() -> None:
    invoice = good_invoice()
    invoice["date"] = "June 10, 2024"
    violations = InvoiceSchemaValidator().validate(invoice)
    assert codes(violations) == ["DATE_UNPARSEABLE"]
    assert violations[0].field == "date"

    invoice["date"] = 20240610  # non-str: WRONG_TYPE only, no DATE_UNPARSEABLE
    violations = InvoiceSchemaValidator().validate(invoice)
    assert codes(violations) == ["WRONG_TYPE"]


# --------------------------------------------------------------------- business rules


def test_each_rule_silent_on_good_invoice() -> None:
    rules = [
        CurrencyValidator(),
        AmountSignValidator(),
        LineItemMathValidator(),
        LineItemsSumValidator(),
        TotalsValidator(),
        DatePlausibilityValidator(),
    ]
    for rule in rules:
        assert rule.validate(good_invoice()) == [], rule.name


def test_currency_invalid_fires_and_skips() -> None:
    invoice = good_invoice()
    invoice["currency"] = "ZZZ"
    violations = CurrencyValidator().validate(invoice)
    assert codes(violations) == ["CURRENCY_INVALID"]
    assert violations[0].actual == "ZZZ"

    invoice["currency"] = "EUR"
    assert CurrencyValidator().validate(invoice) == []

    del invoice["currency"]
    assert CurrencyValidator().validate(invoice) == []

    invoice["currency"] = 42  # non-str: schema's problem, rule skips
    assert CurrencyValidator().validate(invoice) == []


def test_negative_amounts_fire_with_paths() -> None:
    invoice = good_invoice()
    invoice["tax"] = -1.50
    invoice["line_items"][0]["quantity"] = -2
    violations = AmountSignValidator().validate(invoice)
    assert {v.field for v in violations} == {"line_items[0].quantity", "tax"}
    assert set(codes(violations)) == {"NEGATIVE_AMOUNT"}
    for violation in violations:
        assert violation.expected is not None
        assert violation.actual is not None


def test_amount_sign_skips_bool_and_missing() -> None:
    invoice = good_invoice()
    invoice["tax"] = True
    del invoice["line_items"][0]["amount"]
    assert AmountSignValidator().validate(invoice) == []


def test_line_item_math_tolerance_edges() -> None:
    invoice = good_invoice()
    item = {"description": "W", "quantity": 2, "unit_price": 5.00, "amount": 10.01}
    invoice["line_items"] = [item]
    assert LineItemMathValidator().validate(invoice) == []  # off by exactly 0.01: passes

    item["amount"] = 10.02  # off by 0.02: fails
    violations = LineItemMathValidator().validate(invoice)
    assert codes(violations) == ["LINE_ITEM_MATH"]
    assert violations[0].field == "line_items[0].amount"
    assert violations[0].expected is not None
    assert violations[0].actual == "10.02"


def test_line_item_math_skips_unparseable() -> None:
    invoice = good_invoice()
    invoice["line_items"][0]["quantity"] = "two"
    del invoice["line_items"][1]["amount"]
    assert LineItemMathValidator().validate(invoice) == []


def test_line_items_sum_tolerance_and_convention() -> None:
    invoice = good_invoice()  # item amounts sum to 159.98
    invoice["subtotal"] = 159.99  # off by exactly 0.01: passes
    assert LineItemsSumValidator().validate(invoice) == []

    invoice["subtotal"] = 160.00  # off by 0.02: fails
    violations = LineItemsSumValidator().validate(invoice)
    assert codes(violations) == ["LINE_ITEMS_SUM"]
    assert violations[0].field == "subtotal"
    assert violations[0].expected == str(as_decimal(160.00))  # stated subtotal
    assert violations[0].actual == "159.98"  # computed sum


def test_line_items_sum_skips_when_inputs_unusable() -> None:
    invoice = good_invoice()
    del invoice["line_items"][0]["amount"]
    assert LineItemsSumValidator().validate(invoice) == []

    invoice = good_invoice()
    del invoice["subtotal"]
    assert LineItemsSumValidator().validate(invoice) == []


def test_totals_tolerance_edges() -> None:
    invoice = good_invoice()  # subtotal + tax = 172.78
    invoice["total"] = 172.79  # off by exactly 0.01: passes
    assert TotalsValidator().validate(invoice) == []

    invoice["total"] = 172.80  # off by 0.02: fails
    violations = TotalsValidator().validate(invoice)
    assert codes(violations) == ["TOTAL_MISMATCH"]
    assert violations[0].field == "total"
    assert violations[0].expected == "172.78"


def test_totals_skips_when_input_missing() -> None:
    invoice = good_invoice()
    del invoice["tax"]
    invoice["total"] = 999.99
    assert TotalsValidator().validate(invoice) == []


def test_date_plausibility_warns_outside_2000_2030() -> None:
    for bad_date in ("1999-12-31", "2031-01-01"):
        invoice = good_invoice()
        invoice["date"] = bad_date
        violations = DatePlausibilityValidator().validate(invoice)
        assert codes(violations) == ["DATE_IMPLAUSIBLE"]
        assert violations[0].severity is Severity.WARNING
        assert violations[0].field == "date"

    invoice = good_invoice()
    invoice["date"] = "not-a-date"  # unparseable: schema's job, rule skips
    assert DatePlausibilityValidator().validate(invoice) == []


# ----------------------------------------------------------------- composed validator


def test_build_invoice_validator_clean_on_good_invoice() -> None:
    validator = build_invoice_validator()
    assert isinstance(validator, Validator)
    violations = validator.validate(good_invoice())
    assert errors(violations) == []
    assert violations == []


def test_no_cascade_on_empty_output() -> None:
    violations = build_invoice_validator().validate({})
    assert set(codes(violations)) == {"MISSING_FIELD"}
    assert len(violations) == 7  # one per top-level field, nothing else


def test_no_cascade_on_mistyped_fields() -> None:
    invoice = good_invoice()
    invoice["subtotal"] = True  # bool: WRONG_TYPE, and rules must not do math on it
    invoice["line_items"] = "nope"
    invoice["date"] = 19990101  # non-str: no DATE_UNPARSEABLE / DATE_IMPLAUSIBLE
    violations = build_invoice_validator().validate(invoice)
    assert set(codes(violations)) == {"WRONG_TYPE"}
    assert {v.field for v in violations} == {"subtotal", "line_items", "date"}
