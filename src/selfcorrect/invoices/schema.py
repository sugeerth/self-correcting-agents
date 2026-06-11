"""Structural validation of extracted invoice dicts.

Target shape::

    {"vendor": str, "date": "YYYY-MM-DD", "currency": "USD",
     "line_items": [{"description": str, "quantity": num,
                     "unit_price": num, "amount": num}],
     "subtotal": num, "tax": num, "total": num}

Numbers accept int|float but never bool. Business rules (math, signs,
currency codes, date plausibility) live in :mod:`selfcorrect.invoices.rules`.
"""

from __future__ import annotations

import datetime
from typing import Any

from selfcorrect.types import Violation
from selfcorrect.validators import TypeSpec, type_matches, type_name

_NUMBER: TypeSpec = (int, float)

_TOP_LEVEL_FIELDS: dict[str, TypeSpec] = {
    "vendor": str,
    "date": str,
    "currency": str,
    "line_items": list,
    "subtotal": _NUMBER,
    "tax": _NUMBER,
    "total": _NUMBER,
}

_LINE_ITEM_FIELDS: dict[str, TypeSpec] = {
    "description": str,
    "quantity": _NUMBER,
    "unit_price": _NUMBER,
    "amount": _NUMBER,
}


def _check_fields(
    mapping: dict[str, Any], fields: dict[str, TypeSpec], prefix: str = ""
) -> list[Violation]:
    """MISSING_FIELD / WRONG_TYPE checks; field paths get the given prefix."""
    violations: list[Violation] = []
    for key, spec in fields.items():
        path = f"{prefix}{key}"
        expected = type_name(spec)
        if key not in mapping:
            violations.append(
                Violation(
                    code="MISSING_FIELD",
                    field=path,
                    message=f"Required field '{path}' is missing.",
                    expected=expected,
                    actual=None,
                )
            )
        elif not type_matches(mapping[key], spec):
            actual = type(mapping[key]).__name__
            violations.append(
                Violation(
                    code="WRONG_TYPE",
                    field=path,
                    message=f"Field '{path}' should be {expected}, got {actual}.",
                    expected=expected,
                    actual=actual,
                )
            )
    return violations


class InvoiceSchemaValidator:
    """Field presence and types, line-item shape, ISO date parseability.

    Emits MISSING_FIELD, WRONG_TYPE (with paths like ``line_items[2].amount``),
    EMPTY_LINE_ITEMS, and DATE_UNPARSEABLE (only when ``date`` is a str;
    WRONG_TYPE already covers non-str dates).
    """

    name = "invoice_schema"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations = _check_fields(output, _TOP_LEVEL_FIELDS)
        violations.extend(self._check_line_items(output))
        violations.extend(self._check_date(output))
        return violations

    @staticmethod
    def _check_line_items(output: dict[str, Any]) -> list[Violation]:
        items = output.get("line_items")
        if not isinstance(items, list):
            return []  # missing / WRONG_TYPE already reported above
        if not items:
            return [
                Violation(
                    code="EMPTY_LINE_ITEMS",
                    field="line_items",
                    message="line_items must contain at least one item.",
                    expected="a non-empty list",
                    actual="[]",
                )
            ]
        violations: list[Violation] = []
        for index, item in enumerate(items):
            path = f"line_items[{index}]"
            if not isinstance(item, dict):
                violations.append(
                    Violation(
                        code="WRONG_TYPE",
                        field=path,
                        message=f"{path} should be dict, got {type(item).__name__}.",
                        expected="dict",
                        actual=type(item).__name__,
                    )
                )
                continue
            violations.extend(_check_fields(item, _LINE_ITEM_FIELDS, prefix=f"{path}."))
        return violations

    @staticmethod
    def _check_date(output: dict[str, Any]) -> list[Violation]:
        raw = output.get("date")
        if not isinstance(raw, str):
            return []  # missing / WRONG_TYPE already reported above
        try:
            datetime.date.fromisoformat(raw)
        except ValueError:
            return [
                Violation(
                    code="DATE_UNPARSEABLE",
                    field="date",
                    message=f"date '{raw}' is not a parseable ISO date.",
                    expected="YYYY-MM-DD",
                    actual=raw,
                )
            ]
        return []
