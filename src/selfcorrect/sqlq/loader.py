"""The text-to-SQL corpus: questions, gold queries, and acceptance checks.

Each task asks for a single SELECT over the fixture database and must return
``{"task_id": ..., "sql": ...}``. Acceptance checks (expected column names,
row count, and a result checksum) are computed ONCE here by executing the
gold query against the fixture DB — the validator then holds only the checks,
never the gold SQL, so in-loop validation stays a genuine verifier rather
than an answer oracle.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from functools import cache
from typing import Any

from selfcorrect.sqlq.database import SCHEMA_SQL, connect
from selfcorrect.types import Task

_PROMPT_TEMPLATE = """\
Write one SQLite SELECT statement that answers the question below, then return
JSON: {{"task_id": "{task_id}", "sql": "<your query>"}}.

Question: {question}

Schema:
{schema}
"""

#: (task_id, question, gold SQL). Column aliases pin the expected result names.
_CORPUS: tuple[tuple[str, str, str], ...] = (
    (
        "sql_001",
        "List the names of all customers from Germany (country code 'DE'), alphabetically.",
        "SELECT name FROM customers WHERE country = 'DE' ORDER BY name",
    ),
    (
        "sql_002",
        "How many orders were delivered? Return one column named delivered_count.",
        "SELECT COUNT(*) AS delivered_count FROM orders WHERE status = 'delivered'",
    ),
    (
        "sql_003",
        "List product names in the 'electronics' category costing more than 100, "
        "most expensive first.",
        "SELECT name FROM products WHERE category = 'electronics' AND price > 100 "
        "ORDER BY price DESC",
    ),
    (
        "sql_004",
        "What is the total quantity of items ever ordered? One column named total_quantity.",
        "SELECT SUM(quantity) AS total_quantity FROM order_items",
    ),
    (
        "sql_005",
        "For each order status, how many orders have it? Columns: status, order_count; "
        "sort by status.",
        "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status ORDER BY status",
    ),
    (
        "sql_006",
        "Which customers placed at least two orders? Columns: name, order_count; "
        "sort by name.",
        "SELECT c.name AS name, COUNT(o.id) AS order_count FROM customers c "
        "JOIN orders o ON o.customer_id = c.id GROUP BY c.id HAVING COUNT(o.id) >= 2 "
        "ORDER BY c.name",
    ),
    (
        "sql_007",
        "What is the revenue (price times quantity) of order 14? One column named revenue.",
        "SELECT SUM(p.price * oi.quantity) AS revenue FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id WHERE oi.order_id = 14",
    ),
    (
        "sql_008",
        "List the distinct countries of customers who have a cancelled order, alphabetically. "
        "One column named country.",
        "SELECT DISTINCT c.country AS country FROM customers c "
        "JOIN orders o ON o.customer_id = c.id WHERE o.status = 'cancelled' ORDER BY c.country",
    ),
    (
        "sql_009",
        "Which product appears in the most orders? Columns: name, order_count "
        "(ties broken alphabetically, return only the top one).",
        "SELECT p.name AS name, COUNT(DISTINCT oi.order_id) AS order_count FROM products p "
        "JOIN order_items oi ON oi.product_id = p.id GROUP BY p.id "
        "ORDER BY order_count DESC, p.name LIMIT 1",
    ),
    (
        "sql_010",
        "Total revenue per product category. Columns: category, revenue; sort by category.",
        "SELECT p.category AS category, SUM(p.price * oi.quantity) AS revenue FROM products p "
        "JOIN order_items oi ON oi.product_id = p.id GROUP BY p.category ORDER BY p.category",
    ),
    (
        "sql_011",
        "Names of customers who signed up in 2023 and have at least one order, alphabetically.",
        "SELECT DISTINCT c.name AS name FROM customers c "
        "JOIN orders o ON o.customer_id = c.id WHERE c.signup_year = 2023 ORDER BY c.name",
    ),
    (
        "sql_012",
        "How many orders were placed in March 2024? One column named march_orders.",
        "SELECT COUNT(*) AS march_orders FROM orders "
        "WHERE order_date >= '2024-03-01' AND order_date < '2024-04-01'",
    ),
)


@dataclass(frozen=True)
class Checks:
    """Executable acceptance criteria for one task's result."""

    columns: tuple[str, ...]
    row_count: int
    checksum: str  # sha1 over the sorted, stringified result rows


def run_select(conn: sqlite3.Connection, sql: str) -> tuple[tuple[str, ...], list[tuple]]:
    """Execute a SELECT, returning (column names, rows). Raises sqlite3.Error."""
    cursor = conn.execute(sql)
    columns = tuple(d[0] for d in cursor.description or ())
    return columns, cursor.fetchall()


def result_checksum(rows: list[tuple]) -> str:
    """Order-insensitive checksum of a result set."""
    canon = "\n".join(sorted(repr(tuple(row)) for row in rows))
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


@cache
def load_checks() -> dict[str, Checks]:
    """Acceptance checks per task, computed from the gold queries once."""
    conn = connect()
    checks: dict[str, Checks] = {}
    try:
        for task_id, _question, gold_sql in _CORPUS:
            columns, rows = run_select(conn, gold_sql)
            checks[task_id] = Checks(
                columns=columns, row_count=len(rows), checksum=result_checksum(rows)
            )
    finally:
        conn.close()
    return checks


def load_tasks() -> list[Task]:
    return [
        Task(
            id=task_id,
            prompt=_PROMPT_TEMPLATE.format(task_id=task_id, question=question, schema=SCHEMA_SQL),
        )
        for task_id, question, _gold_sql in _CORPUS
    ]


def load_ground_truth() -> dict[str, dict[str, Any]]:
    return {task_id: {"task_id": task_id, "sql": gold} for task_id, _q, gold in _CORPUS}
