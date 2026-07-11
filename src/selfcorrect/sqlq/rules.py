"""The text-to-SQL validator: shape, safety, executability, acceptance checks.

Violation codes, in check order (validation stops at the first failing tier
because later tiers are meaningless once an earlier one fails):

- MISSING_FIELD / WRONG_TYPE  output shape (task_id + sql strings)
- UNKNOWN_TASK                task_id is not in the corpus
- NOT_A_SELECT                anything but a single SELECT statement
- SQL_ERROR                   sqlite refused the query
- MISSING_COLUMNS             result column names differ from the expected set
- WRONG_ROW_COUNT             result has the wrong number of rows
- WRONG_RESULT                right shape, wrong values (checksum mismatch)
"""

from __future__ import annotations

import sqlite3
from typing import Any

from selfcorrect.sqlq.database import connect
from selfcorrect.sqlq.loader import Checks, load_checks, result_checksum, run_select
from selfcorrect.types import Violation

_FORBIDDEN_TOKENS = ("insert", "update", "delete", "drop", "alter", "create", "pragma", "attach")


def _shape_violations(output: dict[str, Any]) -> list[Violation]:
    violations = []
    for key in ("task_id", "sql"):
        value = output.get(key)
        if value is None:
            violations.append(
                Violation(
                    code="MISSING_FIELD",
                    field=key,
                    message=f"required field '{key}' is missing",
                    expected="a string",
                    actual="missing",
                )
            )
        elif not isinstance(value, str):
            violations.append(
                Violation(
                    code="WRONG_TYPE",
                    field=key,
                    message=f"'{key}' must be a string",
                    expected="str",
                    actual=type(value).__name__,
                )
            )
    return violations


def _select_only_violations(sql: str) -> list[Violation]:
    stripped = sql.strip().rstrip(";")
    lowered = stripped.casefold()
    is_select = lowered.startswith("select") or lowered.startswith("with")
    has_forbidden = any(token in lowered.split() for token in _FORBIDDEN_TOKENS)
    if is_select and ";" not in stripped and not has_forbidden:
        return []
    return [
        Violation(
            code="NOT_A_SELECT",
            field="sql",
            message="the query must be exactly one read-only SELECT statement",
            expected="a single SELECT",
            actual=stripped[:60] or "empty",
        )
    ]


class SqlValidator:
    """Validates one candidate against the fixture DB and its task's checks."""

    name = "sqlq"

    def __init__(self, checks: dict[str, Checks] | None = None) -> None:
        self._checks = checks if checks is not None else load_checks()

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations = _shape_violations(output)
        if violations:
            return violations
        checks = self._checks.get(output["task_id"])
        if checks is None:
            return [
                Violation(
                    code="UNKNOWN_TASK",
                    field="task_id",
                    message="task_id does not match any corpus task",
                    expected="a corpus task id",
                    actual=output["task_id"],
                )
            ]
        violations = _select_only_violations(output["sql"])
        if violations:
            return violations
        return self._execute_and_check(output["sql"], checks)

    def _execute_and_check(self, sql: str, checks: Checks) -> list[Violation]:
        conn = connect()
        try:
            columns, rows = run_select(conn, sql)
        except sqlite3.Error as exc:
            return [
                Violation(
                    code="SQL_ERROR",
                    field="sql",
                    message="sqlite rejected the query",
                    expected="a query that executes",
                    actual=str(exc),
                )
            ]
        finally:
            conn.close()
        if tuple(columns) != checks.columns:
            return [
                Violation(
                    code="MISSING_COLUMNS",
                    field="sql",
                    message="result columns do not match the question's requested columns",
                    expected=", ".join(checks.columns),
                    actual=", ".join(columns) or "none",
                )
            ]
        if len(rows) != checks.row_count:
            return [
                Violation(
                    code="WRONG_ROW_COUNT",
                    field="sql",
                    message="result has the wrong number of rows",
                    expected=str(checks.row_count),
                    actual=str(len(rows)),
                )
            ]
        if result_checksum(rows) != checks.checksum:
            return [
                Violation(
                    code="WRONG_RESULT",
                    field="sql",
                    message="result shape is right but the values are wrong",
                    expected=f"result checksum {checks.checksum}",
                    actual=result_checksum(rows),
                )
            ]
        return []


def build_sql_validator() -> SqlValidator:
    return SqlValidator()
