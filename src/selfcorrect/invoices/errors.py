"""Invoice error catalog for the SimulatedEngine.

Each inject function corrupts a deep copy of the standard invoice dict:
{vendor, date, currency, line_items[{description, quantity, unit_price,
amount}], subtotal, tax, total}. Functions are defensive: missing fields,
short line-item lists, and non-numeric values degrade to no-ops rather
than raising.
"""

from __future__ import annotations

import random
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from selfcorrect.engines.simulated import ErrorCatalog, ErrorSpec, SimulatedEngine
from selfcorrect.types import Task

# Tuning constants. The benchmark lift bounds in tests/test_bench_e2e.py
# (valid_ON - valid_OFF >= 0.15; generic-critic ablation strictly between)
# depend on these: target ~60-70% of tasks clean first-shot, >=95% valid
# within 3 attempts under the template critic.
K_WEIGHTS: dict[int, float] = {0: 0.58, 1: 0.24, 2: 0.13, 3: 0.05}
UNFIXABLE_P: float = 0.20

_TOLERANCE = Decimal("0.01")
_INVALID_CURRENCY_TOKENS = ("EU", "US DOLLAR", "EURO", "DOLLARS")


def _is_number(value: object) -> bool:
    """True for int/float but not bool (bool is an int subclass)."""
    return isinstance(value, int | float) and not isinstance(value, bool)


def _money_close(a: object, b: object) -> bool:
    """Decimal comparison with one-cent tolerance; non-numbers never match."""
    if not (_is_number(a) and _is_number(b)):
        return False
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) <= _TOLERANCE
    except InvalidOperation:  # pragma: no cover - inf/nan guard
        return False


def _line_items(out: dict[str, Any]) -> list[dict[str, Any]]:
    """The line_items list filtered down to dict entries (possibly empty)."""
    items = out.get("line_items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def _inject_wrong_total_picked(
    out: dict[str, Any], task: Task, rng: random.Random
) -> dict[str, Any]:
    """Replace total with another salient number from the document."""
    total = out.get("total")
    candidates: list[Any] = []
    if _is_number(out.get("subtotal")):
        candidates.append(out["subtotal"])
    for item in _line_items(out):
        if _is_number(item.get("amount")):
            candidates.append(item["amount"])
    delta = round(rng.uniform(1.0, 50.0), 2)
    noisy = round(float(total) + delta, 2) if _is_number(total) else delta
    candidates.append(noisy)
    distinct = [c for c in candidates if not _money_close(c, total)]
    out["total"] = rng.choice(distinct) if distinct else noisy
    return out


def _inject_missed_line_item(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Drop one line item while keeping subtotal, so LINE_ITEMS_SUM fires."""
    items = out.get("line_items")
    if not isinstance(items, list) or not items:
        return out
    items.pop(rng.randrange(len(items)))
    return out


def _inject_date_format(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Rewrite the date as MM/DD/YYYY so DATE_UNPARSEABLE fires."""
    try:
        parsed = date.fromisoformat(str(out.get("date")))
    except (TypeError, ValueError):
        out["date"] = "03/14/2025"
        return out
    out["date"] = f"{parsed.month:02d}/{parsed.day:02d}/{parsed.year}"
    return out


def _inject_date_swapped(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Swap day and month (plausible but wrong); shift days when impossible."""
    try:
        parsed = date.fromisoformat(str(out.get("date")))
    except (TypeError, ValueError):
        return out
    if parsed.day <= 12 and parsed.day != parsed.month:
        out["date"] = parsed.replace(month=parsed.day, day=parsed.month).isoformat()
        return out
    shift = rng.choice((-5, -4, -3, -2, -1, 1, 2, 3, 4, 5))
    out["date"] = (parsed + timedelta(days=shift)).isoformat()
    return out


def _inject_currency_swap(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Replace currency with an invalid token so CURRENCY_INVALID fires."""
    out["currency"] = rng.choice(_INVALID_CURRENCY_TOKENS)
    return out


def _inject_tax_zeroed(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Zero the tax but keep the stated total, so TOTAL_MISMATCH fires."""
    if _is_number(out.get("tax")) and not _money_close(out.get("tax"), 0):
        out["tax"] = 0.0
    return out


def _transpose_adjacent_digits(text: str, rng: random.Random) -> str | None:
    """Swap one adjacent unequal digit pair; None if no such pair exists."""
    chars = list(text)
    spots = [
        i
        for i in range(len(chars) - 1)
        if chars[i].isdigit() and chars[i + 1].isdigit() and chars[i] != chars[i + 1]
    ]
    if not spots:
        return None
    i = rng.choice(spots)
    chars[i], chars[i + 1] = chars[i + 1], chars[i]
    return "".join(chars)


def _inject_digit_transposed(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Swap two digits in one line item amount (value guaranteed to change)."""
    items = [item for item in _line_items(out) if _is_number(item.get("amount"))]
    if not items:
        return out
    order = list(range(len(items)))
    rng.shuffle(order)
    for idx in order:
        original = Decimal(str(items[idx]["amount"]))
        swapped = _transpose_adjacent_digits(f"{original:.2f}", rng)
        if swapped is not None:
            items[idx]["amount"] = float(swapped)
            return out
    fallback = items[order[0]]  # e.g. all-equal digits like 11.11: shift instead
    fallback["amount"] = float(Decimal(str(fallback["amount"])) + Decimal("1.10"))
    return out


def _inject_vendor_garbled(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Truncate vendor to its first word or mangle its case (silent error)."""
    vendor = out.get("vendor")
    if not isinstance(vendor, str) or not vendor.strip():
        return out
    words = vendor.split()
    if len(words) > 1 and rng.random() < 0.5:
        out["vendor"] = words[0]
        return out
    out["vendor"] = vendor.upper() if vendor != vendor.upper() else vendor.lower()
    return out


INVOICE_ERROR_CATALOG = ErrorCatalog(
    specs=(
        ErrorSpec(
            name="wrong_total_picked",
            inject=_inject_wrong_total_picked,
            fixed_by=frozenset({"TOTAL_MISMATCH"}),
            repair_p=0.75,
            weight=1.0,
        ),
        ErrorSpec(
            name="missed_line_item",
            inject=_inject_missed_line_item,
            fixed_by=frozenset({"LINE_ITEMS_SUM"}),
            repair_p=0.50,
            weight=1.0,
        ),
        ErrorSpec(
            name="date_format",
            inject=_inject_date_format,
            fixed_by=frozenset({"DATE_UNPARSEABLE"}),
            repair_p=0.95,
            weight=0.5,
        ),
        ErrorSpec(
            name="date_swapped",
            inject=_inject_date_swapped,
            fixed_by=frozenset(),
            repair_p=0.0,
            weight=0.3,
            affects_validity=False,
        ),
        ErrorSpec(
            name="currency_swap",
            inject=_inject_currency_swap,
            fixed_by=frozenset({"CURRENCY_INVALID"}),
            repair_p=0.95,
            weight=0.7,
        ),
        ErrorSpec(
            name="tax_zeroed",
            inject=_inject_tax_zeroed,
            fixed_by=frozenset({"TOTAL_MISMATCH"}),
            repair_p=0.85,
            weight=0.7,
        ),
        ErrorSpec(
            name="digit_transposed",
            inject=_inject_digit_transposed,
            fixed_by=frozenset({"LINE_ITEM_MATH", "LINE_ITEMS_SUM"}),
            repair_p=0.50,
            weight=0.8,
        ),
        ErrorSpec(
            name="vendor_garbled",
            inject=_inject_vendor_garbled,
            fixed_by=frozenset(),
            repair_p=0.0,
            weight=0.5,
            affects_validity=False,
        ),
    ),
    k_weights=K_WEIGHTS,
    unfixable_p=UNFIXABLE_P,
)


def build_simulated_engine(
    ground_truth: Mapping[str, dict[str, Any]], seed: int = 42
) -> SimulatedEngine:
    """A SimulatedEngine wired with the invoice error catalog."""
    return SimulatedEngine(INVOICE_ERROR_CATALOG, ground_truth, seed=seed)
