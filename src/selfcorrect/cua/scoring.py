"""Computer-use field-accuracy scoring against the gold action list.

Unlike in-loop validation (which only sees derived expected records), the
benchmark legitimately knows the gold actions — it executes both the gold and
the candidate action lists fresh and compares the resulting app state, giving
partial credit per booking facet even when the flow stalls before 'done'.
"""

from __future__ import annotations

from typing import Any

from selfcorrect.cua.rules import shape_violations
from selfcorrect.cua.ui import run_actions

#: Accuracy columns, in report order.
FIELD_NAMES: tuple[str, ...] = ("completed", "route", "flight", "traveler")

_ROUTE_KEYS = ("from", "to", "date", "passengers")
_TRAVELER_KEYS = ("name", "email", "insurance")


def field_accuracy(output: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, float]:
    """Execution accuracy of one final output against the gold action list."""
    scores = {name: 0.0 for name in FIELD_NAMES}
    if not isinstance(output, dict) or shape_violations(output):
        return scores
    expected = run_actions(truth["actions"]).booking or {}
    result = run_actions(output["actions"])
    record = result.record
    scores["completed"] = float(result.booking is not None)
    scores["route"] = float(all(record[key] == expected.get(key) for key in _ROUTE_KEYS))
    scores["flight"] = float(record["flight"] == expected.get("flight"))
    scores["traveler"] = float(all(record[key] == expected.get(key) for key in _TRAVELER_KEYS))
    return scores


def describe_row(gt: dict[str, Any]) -> str:
    """One list-corpus line, e.g. 'BER→LIS 2026-08-14 ×2 morning +insurance'."""
    record = run_actions(gt["actions"]).booking or {}
    line = (
        f"{record.get('from', '?')}→{record.get('to', '?')} {record.get('date', '?')} "
        f"×{record.get('passengers', '?')} {record.get('flight', '?')}"
    )
    return line + (" +insurance" if record.get("insurance") else "")
