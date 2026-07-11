"""The computer-use validator: shape, task routing, execution, end assertions.

Violation codes, in check order (validation stops at the first failing tier
because later tiers are meaningless once an earlier one fails):

- MISSING_FIELD / WRONG_TYPE  output shape (task_id, actions, per-action do/target/value)
- UNKNOWN_TASK                task_id is not in the corpus
- UNKNOWN_TARGET              an action names an element not on the current page
- INVALID_ACTION              the verb does not apply to the element it targets
- PRECONDITION_FAILED         search/pay clicked before its required fields are valid
- NOT_COMPLETED               the flow never reached the done page
- WRONG_BOOKING               booking completed but a field differs from the goal
"""

from __future__ import annotations

from typing import Any

from selfcorrect.cua.loader import load_expected_records
from selfcorrect.cua.ui import BOOKING_FIELDS, run_actions
from selfcorrect.types import Violation

_VERBS = ("type", "click", "select")


def shape_violations(output: dict[str, Any]) -> list[Violation]:
    """Tier 1: {'task_id': str, 'actions': [well-formed action, ...]}.

    Action scanning stops at the first malformed action so feedback stays
    focused. Also reused by scoring to guard execution of arbitrary outputs.
    """
    violations: list[Violation] = []
    task_id = output.get("task_id")
    if task_id is None:
        violations.append(_missing("task_id", "a string"))
    elif not isinstance(task_id, str):
        violations.append(_wrong_type("task_id", "str", type(task_id).__name__))
    actions = output.get("actions")
    if actions is None:
        violations.append(_missing("actions", "a list of actions"))
    elif not isinstance(actions, list):
        violations.append(_wrong_type("actions", "list", type(actions).__name__))
    else:
        for index, action in enumerate(actions):
            bad = _action_shape(index, action)
            if bad:
                violations.extend(bad)
                break
    return violations


def _action_shape(index: int, action: Any) -> list[Violation]:
    path = f"actions[{index}]"
    if not isinstance(action, dict):
        return [_wrong_type(path, "an object with 'do' and 'target'", type(action).__name__)]
    violations: list[Violation] = []
    do = action.get("do")
    if do is None:
        violations.append(_missing(f"{path}.do", "'type', 'click' or 'select'"))
    elif do not in _VERBS:
        violations.append(_wrong_type(f"{path}.do", "'type', 'click' or 'select'", str(do)))
    target = action.get("target")
    if target is None:
        violations.append(_missing(f"{path}.target", "an element name"))
    elif not isinstance(target, str) or not target:
        violations.append(_wrong_type(f"{path}.target", "a non-empty string", repr(target)[:40]))
    if do in ("type", "select"):
        value = action.get("value")
        if value is None:
            violations.append(_missing(f"{path}.value", f"a string ('{do}' actions need one)"))
        elif not isinstance(value, str):
            violations.append(_wrong_type(f"{path}.value", "str", type(value).__name__))
    return violations


def _missing(field: str, expected: str) -> Violation:
    return Violation(
        code="MISSING_FIELD",
        field=field,
        message=f"required field '{field}' is missing",
        expected=expected,
        actual="missing",
    )


def _wrong_type(field: str, expected: str, actual: str) -> Violation:
    return Violation(
        code="WRONG_TYPE",
        field=field,
        message=f"'{field}' must be {expected}",
        expected=expected,
        actual=actual,
    )


class CuaValidator:
    """Executes one candidate action list and checks the resulting booking.

    Holds only per-task expected booking records (derived from the gold action
    lists at corpus load), keyed by the output's ``task_id`` routing key.
    """

    name = "cua"

    def __init__(self, expected: dict[str, dict[str, Any]] | None = None) -> None:
        self._expected = expected if expected is not None else load_expected_records()

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations = shape_violations(output)
        if violations:
            return violations
        expected = self._expected.get(output["task_id"])
        if expected is None:
            return [
                Violation(
                    code="UNKNOWN_TASK",
                    field="task_id",
                    message="task_id does not match any corpus task",
                    expected="a corpus task id",
                    actual=output["task_id"],
                )
            ]
        result = run_actions(output["actions"])
        if result.violation is not None:
            return [result.violation]
        if result.booking is None:
            return [
                Violation(
                    code="NOT_COMPLETED",
                    field="actions",
                    message=f"the flow ended on page '{result.page}' without completing "
                    "the booking",
                    expected="done",
                    actual=result.page,
                )
            ]
        for key in BOOKING_FIELDS:
            if result.booking[key] != expected[key]:
                return [
                    Violation(
                        code="WRONG_BOOKING",
                        field=key,
                        message=f"the completed booking's '{key}' does not match the goal",
                        expected=str(expected[key]),
                        actual=str(result.booking[key]),
                    )
                ]
        return []


def build_cua_validator() -> CuaValidator:
    return CuaValidator()
