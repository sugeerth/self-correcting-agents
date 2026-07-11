"""Invoice field-accuracy scoring against ground truth (moved from bench.py).

The benchmark is domain-agnostic; how to score one final output against its
ground truth is domain knowledge, so it lives here with the rest of the
invoice plug-in.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from selfcorrect.validators import as_decimal

_MONEY_TOLERANCE = Decimal("0.01")
_MONEY_FIELDS = ("subtotal", "tax", "total")

#: Accuracy columns, in report order.
FIELD_NAMES: tuple[str, ...] = (
    "vendor",
    "date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "line_item_count",
    "line_item_fields",
)


def _text_match(expected: Any, actual: Any) -> bool:
    """Case- and whitespace-insensitive string equality."""
    if not (isinstance(expected, str) and isinstance(actual, str)):
        return False
    return expected.strip().casefold() == actual.strip().casefold()


def _money_match(expected: Any, actual: Any) -> bool:
    """Decimal equality within one cent; non-numbers never match."""
    e, a = as_decimal(expected), as_decimal(actual)
    return e is not None and a is not None and abs(e - a) <= _MONEY_TOLERANCE


def _exact_number_match(expected: Any, actual: Any) -> bool:
    e, a = as_decimal(expected), as_decimal(actual)
    return e is not None and a is not None and e == a


def _line_item_cells(out_items: list[Any], gt_items: list[dict[str, Any]]) -> float:
    """Fraction of per-cell matches, compared positionally against ground truth."""
    cells = 4 * len(gt_items)
    if cells == 0:  # cannot happen with this corpus, but stay safe
        return 1.0
    correct = 0
    for i, gt_item in enumerate(gt_items):
        candidate = out_items[i] if i < len(out_items) else None
        out_item: dict[str, Any] = candidate if isinstance(candidate, dict) else {}
        if _text_match(gt_item["description"], out_item.get("description")):
            correct += 1
        if _exact_number_match(gt_item["quantity"], out_item.get("quantity")):
            correct += 1
        for key in ("unit_price", "amount"):
            if _money_match(gt_item[key], out_item.get(key)):
                correct += 1
    return correct / cells


def field_accuracy(output: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, float]:
    """Per-field accuracy of one final output against its ground truth."""
    if not isinstance(output, dict):
        return {name: 0.0 for name in FIELD_NAMES}
    raw_items = output.get("line_items")
    out_items: list[Any] = raw_items if isinstance(raw_items, list) else []
    gt_items: list[dict[str, Any]] = truth["line_items"]
    scores = {
        "vendor": float(_text_match(truth["vendor"], output.get("vendor"))),
        "date": float(output.get("date") == truth["date"]),
        "currency": float(output.get("currency") == truth["currency"]),
        "line_item_count": float(len(out_items) == len(gt_items)),
        "line_item_fields": _line_item_cells(out_items, gt_items),
    }
    for key in _MONEY_FIELDS:
        scores[key] = float(_money_match(truth[key], output.get(key)))
    return {name: scores[name] for name in FIELD_NAMES}


def describe_row(gt: dict[str, Any]) -> str:
    """One list-corpus line: vendor, date, currency, total."""
    return f"{gt['vendor']:<34.34} {gt['date']:<12} {gt['currency']:<4} {gt['total']:>12.2f}"
