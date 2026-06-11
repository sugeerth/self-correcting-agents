"""Trace serialization and rendering: JSONL traces plus the demo printout.

All `*_to_dict` helpers return JSON-safe structures (Severity -> .value,
Decimal -> str) that round-trip through json.dumps/loads unchanged.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, TextIO

from selfcorrect.types import Attempt, Feedback, RunResult, Violation

_WIDTH = 98  # every printed line stays <= 100 chars
_RULE_HEAVY = "━" * 72
_RULE_LIGHT = "─" * 72


def _json_safe(value: Any) -> Any:
    """Recursively convert a value into JSON-native types."""
    if isinstance(value, Enum):  # before str: Severity is a str-Enum
        return _json_safe(value.value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, str | int | float):
        return value
    return str(value)


def violation_to_dict(violation: Violation) -> dict[str, Any]:
    return {
        "code": violation.code,
        "field": violation.field,
        "message": violation.message,
        "severity": violation.severity.value,
        "expected": violation.expected,
        "actual": violation.actual,
    }


def feedback_to_dict(feedback: Feedback) -> dict[str, Any]:
    return {
        "violation_code": feedback.violation_code,
        "field": feedback.field,
        "instruction": feedback.instruction,
    }


def attempt_to_dict(attempt: Attempt) -> dict[str, Any]:
    return {
        "index": attempt.index,
        "engine": attempt.engine,
        "output": _json_safe(attempt.output),
        "raw_text": attempt.raw_text,
        "violations": [violation_to_dict(v) for v in attempt.violations],
        "feedback": [feedback_to_dict(f) for f in attempt.feedback],
        "latency_s": attempt.latency_s,
        "input_tokens": attempt.input_tokens,
        "output_tokens": attempt.output_tokens,
        "cost_usd": attempt.cost_usd,
        "is_valid": attempt.is_valid,
    }


def run_result_to_dict(result: RunResult) -> dict[str, Any]:
    """JSON-safe summary + full attempt trace for one run."""
    engines: list[str] = []  # unique, first-occurrence order (deterministic)
    for attempt in result.attempts:
        if attempt.engine not in engines:
            engines.append(attempt.engine)
    return {
        "task_id": result.task_id,
        "success": result.success,
        "num_attempts": result.num_attempts,
        "total_latency_s": result.total_latency_s,
        "total_cost_usd": result.total_cost_usd,
        "engines": engines,
        "simulated": all(a.engine == "simulated" for a in result.attempts),
        "final_output": _json_safe(result.final_output),
        "attempts": [attempt_to_dict(a) for a in result.attempts],
    }


class TraceWriter:
    """Context manager appending one JSON line per RunResult to a file."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = Path(path)
        self._file: TextIO | None = None

    def __enter__(self) -> TraceWriter:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

    def write(self, result: RunResult) -> None:
        """Append one JSONL record for `result`."""
        if self._file is None:
            raise RuntimeError("TraceWriter must be entered as a context manager before write()")
        self._file.write(json.dumps(run_result_to_dict(result)) + "\n")
        self._file.flush()


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: max(limit - 1, 1)] + "…"


def _render_value(value: Any) -> str:
    safe = _json_safe(value)
    return safe if isinstance(safe, str) else json.dumps(safe)


def _print_output(output: dict[str, Any] | None, file: TextIO) -> None:
    if output is None:
        print("  output: <none — generation failed>", file=file)
        return
    print("  output:", file=file)
    for key, value in output.items():
        limit = max(20, _WIDTH - len(str(key)) - 6)
        print(f"    {key}: {_truncate(_render_value(value), limit)}", file=file)


def _print_violations(violations: list[Violation], file: TextIO) -> None:
    if not violations:
        print("  violations: none", file=file)
        return
    rows: list[tuple[str, str, str]] = []
    for v in violations:
        if v.expected is None and v.actual is None:
            detail = v.message
        else:
            detail = f"{v.expected or '?'} -> {v.actual or '?'}"
        rows.append((_truncate(v.code, 24), _truncate(v.field, 28), detail))
    code_w = max(len("CODE"), *(len(r[0]) for r in rows))
    field_w = max(len("FIELD"), *(len(r[1]) for r in rows))
    detail_w = max(len("EXPECTED -> ACTUAL"), _WIDTH - code_w - field_w - 10)
    print(f"  {'CODE':<{code_w}} │ {'FIELD':<{field_w}} │ EXPECTED -> ACTUAL", file=file)
    print(f"  {'─' * code_w}─┼─{'─' * field_w}─┼─{'─' * 18}", file=file)
    for code, fld, detail in rows:
        print(f"  {code:<{code_w}} │ {fld:<{field_w}} │ {_truncate(detail, detail_w)}", file=file)


def _print_feedback(feedback: list[Feedback], file: TextIO) -> None:
    if not feedback:
        return
    print("  Feedback to agent:", file=file)
    for item in feedback:
        lines = textwrap.wrap(item.instruction, width=_WIDTH - 6) or [""]
        print(f"    • {lines[0]}", file=file)
        for line in lines[1:]:
            print(f"      {line}", file=file)


def pretty_print_run(result: RunResult, file: TextIO = sys.stdout) -> None:
    """Render a full run as a readable attempt-by-attempt trace."""
    print(_RULE_HEAVY, file=file)
    print(f"Task: {result.task_id}", file=file)
    for attempt in result.attempts:
        print(_RULE_LIGHT, file=file)
        engine = _truncate(attempt.engine or "?", 40)
        print(
            f"Attempt {attempt.index}/{result.num_attempts} — engine: {engine}"
            f" — {attempt.latency_s:.2f}s",
            file=file,
        )
        _print_output(attempt.output, file)
        _print_violations(attempt.violations, file)
        _print_feedback(attempt.feedback, file)
    print(_RULE_LIGHT, file=file)
    if result.success:
        print(f"VALID after {result.num_attempts} attempt(s)", file=file)
    else:
        print(
            f"FAILED after {result.num_attempts} attempt(s) — returning best attempt",
            file=file,
        )
    print(_RULE_HEAVY, file=file)
