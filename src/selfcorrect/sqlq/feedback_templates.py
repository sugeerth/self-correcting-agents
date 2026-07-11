"""Per-violation-code repair templates for the text-to-SQL domain.

Rendered by ``TemplateCritic`` with ``{field}``, ``{expected}``, ``{actual}``,
and ``{message}``. Each template says WHAT failed and HOW to steer the next
attempt — the same targeted-vs-generic contrast the invoice domain measures.
"""

from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "MISSING_FIELD": (
        "Your output is missing the required field '{field}'. Return JSON with both "
        "'task_id' (copied from the prompt) and 'sql' (your SELECT statement)."
    ),
    "WRONG_TYPE": (
        "The field '{field}' must be a plain JSON string (got {actual}). Do not nest "
        "objects or return numbers — the query itself goes in 'sql' as one string."
    ),
    "UNKNOWN_TASK": (
        "The task_id you returned ({actual}) does not match the prompt. Copy the task_id "
        "verbatim from the prompt into your output."
    ),
    "NOT_A_SELECT": (
        "The query must be exactly one read-only SELECT (or WITH ... SELECT) statement — "
        "no semicolon-separated statements and no writes. Got: {actual}. Rewrite it as a "
        "single SELECT."
    ),
    "SQL_ERROR": (
        "sqlite rejected the query: {actual}. Check identifiers against the schema in the "
        "prompt — table and column names must match exactly — and re-check join syntax."
    ),
    "MISSING_COLUMNS": (
        "The result columns are wrong: expected exactly ({expected}) but the query returns "
        "({actual}). Select precisely the requested columns, using AS aliases to match the "
        "expected names, in that order."
    ),
    "WRONG_ROW_COUNT": (
        "The query runs but returns {actual} rows where {expected} are expected. Re-read "
        "the question's filters — a WHERE condition is probably missing, wrong, or an "
        "unrequested LIMIT is cutting rows off."
    ),
    "WRONG_RESULT": (
        "The result has the right shape but wrong values ({message}). Re-check the "
        "computation: the aggregate function, the join keys, and which column each "
        "condition filters on."
    ),
}
