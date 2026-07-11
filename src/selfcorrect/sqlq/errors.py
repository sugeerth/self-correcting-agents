"""Text-to-SQL error catalog for the SimulatedEngine.

Each inject function corrupts the 'sql' string of a deep-copied ground-truth
dict with a realistic text-to-SQL mistake. Functions are defensive: if a
corruption's pattern is absent from the gold query, they degrade to no-ops
(the planner may then inject nothing for that task — that is fine and keeps
first-shot rates realistic).
"""

from __future__ import annotations

import random
import re
from typing import Any

from selfcorrect.engines.simulated import ErrorCatalog, ErrorSpec, SimulatedEngine
from selfcorrect.types import Task

# Same tuning contract as the invoice catalog: most tasks clean or one error
# first-shot, targeted feedback repairs nearly everything within 3 attempts.
K_WEIGHTS: dict[int, float] = {0: 0.50, 1: 0.30, 2: 0.15, 3: 0.05}
UNFIXABLE_P: float = 0.15

_IDENTIFIER_TYPOS = (
    ("customers", "customer"),
    ("order_items", "order_item"),
    ("quantity", "qty"),
    ("order_date", "orderdate"),
)


def _sql(out: dict[str, Any]) -> str:
    value = out.get("sql")
    return value if isinstance(value, str) else ""


def _inject_drop_where(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Forget the WHERE clause — the classic under-constrained query."""
    sql = _sql(out)
    corrupted = re.sub(r"\s+WHERE\s+.*?(?=(\s+GROUP\b|\s+ORDER\b|\s+LIMIT\b|$))", "", sql, count=1)
    out["sql"] = corrupted
    return out


def _inject_identifier_typo(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Misremember a table or column name (first typo whose target is present)."""
    sql = _sql(out)
    for good, bad in _IDENTIFIER_TYPOS:
        pattern = rf"\b{good}\b"
        if re.search(pattern, sql):
            out["sql"] = re.sub(pattern, bad, sql, count=1)
            return out
    return out


def _inject_wrong_aggregate(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Swap the aggregate function (SUM<->COUNT confusions are endemic).

    Bare ``COUNT(*)`` is left alone: ``SUM(*)`` would be a syntax error, and
    this spec's repair semantics are value errors, not syntax errors.
    """
    sql = _sql(out)
    if re.search(r"\bSUM\(", sql):
        out["sql"] = re.sub(r"\bSUM\(", "COUNT(", sql, count=1)
    elif re.search(r"\bCOUNT\(DISTINCT\b", sql):
        out["sql"] = re.sub(r"\bCOUNT\(DISTINCT\b", "COUNT(", sql, count=1)
    elif re.search(r"\bCOUNT\((?!\*)", sql):
        out["sql"] = re.sub(r"\bCOUNT\((?!\*)", "SUM(", sql, count=1)
    return out


def _inject_stray_limit(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Append an unrequested LIMIT 1 (over-eager 'top result' habit)."""
    sql = _sql(out)
    if sql and not re.search(r"\bLIMIT\b", sql, flags=re.IGNORECASE):
        out["sql"] = sql + " LIMIT 1"
    return out


def _inject_drop_alias(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Drop the first AS alias, so the result column name no longer matches."""
    sql = _sql(out)
    out["sql"] = re.sub(r"\s+AS\s+\w+", "", sql, count=1)
    return out


CATALOG = ErrorCatalog(
    specs=(
        ErrorSpec(
            name="drop_where",
            inject=_inject_drop_where,
            fixed_by=frozenset({"WRONG_ROW_COUNT", "WRONG_RESULT"}),
            repair_p=0.95,
            weight=1.2,
        ),
        ErrorSpec(
            name="identifier_typo",
            inject=_inject_identifier_typo,
            fixed_by=frozenset({"SQL_ERROR"}),
            repair_p=0.95,
            weight=1.0,
        ),
        ErrorSpec(
            name="wrong_aggregate",
            inject=_inject_wrong_aggregate,
            fixed_by=frozenset({"WRONG_RESULT", "MISSING_COLUMNS", "SQL_ERROR"}),
            repair_p=0.9,
            weight=1.0,
        ),
        ErrorSpec(
            name="stray_limit",
            inject=_inject_stray_limit,
            fixed_by=frozenset({"WRONG_ROW_COUNT", "WRONG_RESULT"}),
            repair_p=0.95,
            weight=0.8,
        ),
        ErrorSpec(
            name="drop_alias",
            inject=_inject_drop_alias,
            fixed_by=frozenset({"MISSING_COLUMNS"}),
            repair_p=0.95,
            weight=0.8,
        ),
    ),
    k_weights=K_WEIGHTS,
    unfixable_p=UNFIXABLE_P,
)


def build_simulated_engine(
    ground_truth: dict[str, dict[str, Any]], seed: int = 42
) -> SimulatedEngine:
    return SimulatedEngine(CATALOG, ground_truth, seed=seed)
