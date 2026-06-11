"""Business-rule validators for extracted invoices.

Anti-cascade contract: every rule silently skips when its inputs are
missing, mistyped, or unparseable — :class:`InvoiceSchemaValidator`
already flagged those, so rules never pile noise on schema errors.

All money math uses ``Decimal(str(x))`` with tolerance 0.01 (a stated
figure may be off by at most 0.01 before a violation fires). Every
violation carries stringified ``expected``/``actual`` values.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any

from selfcorrect.invoices.schema import InvoiceSchemaValidator
from selfcorrect.types import Severity, Validator, Violation
from selfcorrect.validators import CompositeValidator, as_decimal

TOLERANCE = Decimal("0.01")

#: Frozen allowlist of 40 common ISO-4217 currency codes.
ISO_4217_CODES: frozenset[str] = frozenset(
    {
        "AED", "ARS", "AUD", "BRL", "CAD", "CHF", "CLP", "CNY", "COP", "CZK",
        "DKK", "EGP", "EUR", "GBP", "HKD", "HUF", "IDR", "ILS", "INR", "JPY",
        "KRW", "MXN", "MYR", "NGN", "NOK", "NZD", "PEN", "PHP", "PLN", "RON",
        "RUB", "SAR", "SEK", "SGD", "THB", "TRY", "TWD", "USD", "VND", "ZAR",
    }
)

_MIN_PLAUSIBLE_YEAR = 2000
_MAX_PLAUSIBLE_YEAR = 2030


def _dict_items(output: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """Indexed line items that are dicts; anything else is schema's problem."""
    items = output.get("line_items")
    if not isinstance(items, list):
        return []
    return [(i, item) for i, item in enumerate(items) if isinstance(item, dict)]


class CurrencyValidator:
    """CURRENCY_INVALID when ``currency`` (a str) is not a known ISO-4217 code."""

    name = "currency"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        currency = output.get("currency")
        if not isinstance(currency, str) or currency in ISO_4217_CODES:
            return []
        return [
            Violation(
                code="CURRENCY_INVALID",
                field="currency",
                message=f"'{currency}' is not a recognized ISO-4217 currency code.",
                expected="an ISO-4217 code such as USD",
                actual=currency,
            )
        ]


class AmountSignValidator:
    """NEGATIVE_AMOUNT for any quantity/unit_price/amount/subtotal/tax/total < 0."""

    name = "amount_sign"

    _ITEM_KEYS = ("quantity", "unit_price", "amount")
    _TOTAL_KEYS = ("subtotal", "tax", "total")

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations: list[Violation] = []
        for index, item in _dict_items(output):
            for key in self._ITEM_KEYS:
                violation = self._check(f"line_items[{index}].{key}", item.get(key))
                if violation is not None:
                    violations.append(violation)
        for key in self._TOTAL_KEYS:
            violation = self._check(key, output.get(key))
            if violation is not None:
                violations.append(violation)
        return violations

    @staticmethod
    def _check(path: str, value: object) -> Violation | None:
        number = as_decimal(value)
        if number is None or number >= 0:
            return None
        return Violation(
            code="NEGATIVE_AMOUNT",
            field=path,
            message=f"{path} must not be negative, got {number}.",
            expected=">= 0",
            actual=str(number),
        )


class LineItemMathValidator:
    """LINE_ITEM_MATH when ``quantity * unit_price`` differs from ``amount`` by > 0.01.

    Reported at ``line_items[i].amount`` with expected=computed product,
    actual=stated amount.
    """

    name = "line_item_math"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations: list[Violation] = []
        for index, item in _dict_items(output):
            quantity = as_decimal(item.get("quantity"))
            unit_price = as_decimal(item.get("unit_price"))
            amount = as_decimal(item.get("amount"))
            if quantity is None or unit_price is None or amount is None:
                continue
            computed = quantity * unit_price
            if abs(computed - amount) > TOLERANCE:
                path = f"line_items[{index}].amount"
                violations.append(
                    Violation(
                        code="LINE_ITEM_MATH",
                        field=path,
                        message=f"{path} is {amount} but quantity * unit_price = {computed}.",
                        expected=str(computed),
                        actual=str(amount),
                    )
                )
        return violations


class LineItemsSumValidator:
    """LINE_ITEMS_SUM when line-item amounts do not sum to ``subtotal`` (> 0.01 off).

    Convention: ``expected`` = the STATED subtotal, ``actual`` = the COMPUTED
    sum of line-item amounts. Critic templates use both figures. Skips
    entirely if any item amount or the subtotal is missing/unparseable.
    """

    name = "line_items_sum"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        items = output.get("line_items")
        if not isinstance(items, list) or not items:
            return []
        computed = Decimal("0")
        for item in items:
            if not isinstance(item, dict):
                return []
            amount = as_decimal(item.get("amount"))
            if amount is None:
                return []
            computed += amount
        stated = as_decimal(output.get("subtotal"))
        if stated is None or abs(computed - stated) <= TOLERANCE:
            return []
        return [
            Violation(
                code="LINE_ITEMS_SUM",
                field="subtotal",
                message=f"subtotal is {stated} but line-item amounts sum to {computed}.",
                expected=str(stated),
                actual=str(computed),
            )
        ]


class TotalsValidator:
    """TOTAL_MISMATCH when ``subtotal + tax`` differs from ``total`` by > 0.01."""

    name = "totals"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        subtotal = as_decimal(output.get("subtotal"))
        tax = as_decimal(output.get("tax"))
        total = as_decimal(output.get("total"))
        if subtotal is None or tax is None or total is None:
            return []
        computed = subtotal + tax
        if abs(computed - total) <= TOLERANCE:
            return []
        return [
            Violation(
                code="TOTAL_MISMATCH",
                field="total",
                message=f"total is {total} but subtotal + tax = {computed}.",
                expected=str(computed),
                actual=str(total),
            )
        ]


class DatePlausibilityValidator:
    """WARNING-level DATE_IMPLAUSIBLE when the ISO date year is outside 2000-2030."""

    name = "date_plausibility"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        raw = output.get("date")
        if not isinstance(raw, str):
            return []
        try:
            parsed = datetime.date.fromisoformat(raw)
        except ValueError:
            return []  # DATE_UNPARSEABLE is schema's job
        if _MIN_PLAUSIBLE_YEAR <= parsed.year <= _MAX_PLAUSIBLE_YEAR:
            return []
        return [
            Violation(
                code="DATE_IMPLAUSIBLE",
                field="date",
                message=f"date {raw} has an implausible year ({parsed.year}).",
                severity=Severity.WARNING,
                expected=f"a year between {_MIN_PLAUSIBLE_YEAR} and {_MAX_PLAUSIBLE_YEAR}",
                actual=raw,
            )
        ]


def build_invoice_validator() -> Validator:
    """The full invoice stack: schema validation first, then every business rule."""
    return CompositeValidator(
        [
            InvoiceSchemaValidator(),
            CurrencyValidator(),
            AmountSignValidator(),
            LineItemMathValidator(),
            LineItemsSumValidator(),
            TotalsValidator(),
            DatePlausibilityValidator(),
        ],
        name="invoice",
    )
