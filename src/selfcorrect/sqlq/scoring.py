"""Text-to-SQL field-accuracy scoring against the gold query.

Unlike in-loop validation (which only sees acceptance checks), the benchmark
legitimately knows the gold SQL — execution accuracy against the gold result
is the standard text-to-SQL metric.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from selfcorrect.sqlq.database import connect
from selfcorrect.sqlq.loader import result_checksum, run_select

#: Accuracy columns, in report order.
FIELD_NAMES: tuple[str, ...] = ("executes", "result_columns", "result_rows")


def field_accuracy(output: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, float]:
    """Execution accuracy of one final output against the gold query."""
    scores = {name: 0.0 for name in FIELD_NAMES}
    sql = output.get("sql") if isinstance(output, dict) else None
    if not isinstance(sql, str):
        return scores
    conn = connect()
    try:
        gold_columns, gold_rows = run_select(conn, truth["sql"])
        try:
            columns, rows = run_select(conn, sql)
        except sqlite3.Error:
            return scores
    finally:
        conn.close()
    scores["executes"] = 1.0
    scores["result_columns"] = float(tuple(columns) == tuple(gold_columns))
    scores["result_rows"] = float(result_checksum(rows) == result_checksum(gold_rows))
    return scores


def describe_row(gt: dict[str, Any]) -> str:
    """One list-corpus line: the gold query, truncated."""
    sql = str(gt.get("sql", ""))
    return sql if len(sql) <= 64 else sql[:61] + "..."
