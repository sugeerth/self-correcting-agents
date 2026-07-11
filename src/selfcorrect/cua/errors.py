"""Computer-use error catalog for the SimulatedEngine.

Each inject function corrupts the 'actions' list of a deep-copied ground-truth
dict with a realistic computer-use mistake. Functions are defensive: if a
corruption's pattern is absent from the gold actions, they degrade to no-ops
(the planner may then inject nothing for that task — that is fine and keeps
first-shot rates realistic).
"""

from __future__ import annotations

import random
import re
from typing import Any

from selfcorrect.cua.ui import FLIGHTS
from selfcorrect.engines.simulated import ErrorCatalog, ErrorSpec, SimulatedEngine
from selfcorrect.types import Task

# Same tuning contract as the other catalogs: most tasks clean or one error
# first-shot, targeted feedback repairs nearly everything within 3 attempts.
# (Tuned empirically at seed 42: OFF 50%, ON 90%, i.e. a 40pp lift.)
K_WEIGHTS: dict[int, float] = {0: 0.35, 1: 0.45, 2: 0.15, 3: 0.05}
UNFIXABLE_P: float = 0.12

#: Misspellings that never collide with a real element name on any page.
_TYPO_TARGETS = {
    "search": "serach",
    "pay": "pai",
    "name": "nmae",
    "email": "emial",
    "date": "dtae",
    "insurance": "insurence",
    "passengers": "passangers",
    "choose_morning": "chose_morning",
    "choose_evening": "chose_evening",
    "choose_redeye": "chose_redeye",
}


def _actions(out: dict[str, Any]) -> list[dict[str, Any]]:
    value = out.get("actions")
    return value if isinstance(value, list) else []


def _shift_date(date: str) -> str:
    """An off-by-one-day slip; unparseable dates come back unchanged (no-op)."""
    match = re.fullmatch(r"(\d{4}-\d{2}-)(\d{2})", date)
    if match is None:
        return date
    day = int(match.group(2))
    return f"{match.group(1)}{day - 1 if day > 27 else day + 1:02d}"


def _inject_skip_type_action(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Forget to fill in a traveler field — 'pay' then fails its precondition."""
    actions = _actions(out)
    for i, action in enumerate(actions):
        if action.get("do") == "type" and action.get("target") in ("name", "email"):
            del actions[i]
            break
    return out


def _inject_wrong_field_value(
    out: dict[str, Any], task: Task, rng: random.Random
) -> dict[str, Any]:
    """Type the wrong departure date — the booking completes, off by one day."""
    for action in reversed(_actions(out)):
        value = action.get("value")
        if action.get("do") == "type" and action.get("target") == "date" and isinstance(value, str):
            action["value"] = _shift_date(value)
            break
    return out


def _inject_wrong_flight_button(
    out: dict[str, Any], task: Task, rng: random.Random
) -> dict[str, Any]:
    """Click a different choose_* button — right page, wrong flight."""
    for action in _actions(out):
        target = action.get("target", "")
        if action.get("do") == "click" and isinstance(target, str) and target.startswith("choose_"):
            flight = target.removeprefix("choose_")
            if flight in FLIGHTS:
                wrong = FLIGHTS[(FLIGHTS.index(flight) + 1) % len(FLIGHTS)]
                action["target"] = f"choose_{wrong}"
            break
    return out


def _inject_premature_pay(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Click 'pay' the moment checkout appears, before typing the details."""
    actions = _actions(out)
    pay_idx = next(
        (i for i, a in enumerate(actions) if a.get("do") == "click" and a.get("target") == "pay"),
        None,
    )
    choose_idx = next(
        (
            i
            for i, a in enumerate(actions)
            if a.get("do") == "click" and str(a.get("target", "")).startswith("choose_")
        ),
        None,
    )
    if pay_idx is None or choose_idx is None or pay_idx <= choose_idx + 1:
        return out
    pay = actions.pop(pay_idx)
    actions.insert(choose_idx + 1, pay)
    return out


def _inject_typo_target(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    """Misspell one action's target — the element then cannot be found."""
    actions = _actions(out)
    candidates = [i for i, a in enumerate(actions) if a.get("target") in _TYPO_TARGETS]
    if not candidates:
        return out
    index = candidates[rng.randrange(len(candidates))]
    actions[index]["target"] = _TYPO_TARGETS[actions[index]["target"]]
    return out


CATALOG = ErrorCatalog(
    specs=(
        ErrorSpec(
            name="skip_type_action",
            inject=_inject_skip_type_action,
            fixed_by=frozenset({"PRECONDITION_FAILED"}),
            repair_p=0.95,
            weight=1.2,
        ),
        ErrorSpec(
            name="wrong_field_value",
            inject=_inject_wrong_field_value,
            fixed_by=frozenset({"WRONG_BOOKING"}),
            repair_p=0.9,
            weight=1.0,
        ),
        ErrorSpec(
            name="wrong_flight_button",
            inject=_inject_wrong_flight_button,
            fixed_by=frozenset({"WRONG_BOOKING"}),
            repair_p=0.9,
            weight=0.8,
        ),
        ErrorSpec(
            name="premature_pay",
            inject=_inject_premature_pay,
            fixed_by=frozenset({"PRECONDITION_FAILED"}),
            repair_p=0.95,
            weight=0.8,
        ),
        ErrorSpec(
            name="typo_target",
            inject=_inject_typo_target,
            fixed_by=frozenset({"UNKNOWN_TARGET", "INVALID_ACTION"}),
            repair_p=0.95,
            weight=1.0,
        ),
    ),
    k_weights=K_WEIGHTS,
    unfixable_p=UNFIXABLE_P,
)


def build_simulated_engine(
    ground_truth: dict[str, dict[str, Any]], seed: int = 42
) -> SimulatedEngine:
    return SimulatedEngine(CATALOG, ground_truth, seed=seed)
