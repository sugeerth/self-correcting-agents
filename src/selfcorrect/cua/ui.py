"""TripBooker: a tiny declarative flight-booking UI, pure stdlib and deterministic.

This is the computer-use analogue of sqlq's fixture database — the environment
candidate action lists are executed against, both by the in-loop validator and
by benchmark scoring. Pages declare their elements, actions apply one at a
time, and execution stops at the first violation, exactly like a real UI
driver that cannot see past its first failed step.

The executor assumes shape-checked actions (see ``rules.shape_violations``):
every action is a dict with a valid ``do``/``target``, and ``type``/``select``
actions carry a string ``value``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from selfcorrect.types import Violation

#: Options of the one select element (passengers defaults to the first).
PASSENGER_OPTIONS: tuple[str, ...] = ("1", "2", "3", "4")

#: Flights offered on the results page (as ``choose_<flight>`` buttons).
FLIGHTS: tuple[str, ...] = ("morning", "evening", "redeye")

#: Booking-record keys, in the order WRONG_BOOKING mismatches are reported.
BOOKING_FIELDS: tuple[str, ...] = (
    "from",
    "to",
    "date",
    "passengers",
    "flight",
    "name",
    "email",
    "insurance",
)

#: page -> {target: element kind}. The whole UI, declaratively.
PAGES: dict[str, dict[str, str]] = {
    "search": {
        "from": "field",
        "to": "field",
        "date": "field",
        "passengers": "select",
        "search": "button",
    },
    "results": {
        "choose_morning": "button",
        "choose_evening": "button",
        "choose_redeye": "button",
        "back": "button",
    },
    "checkout": {
        "name": "field",
        "email": "field",
        "insurance": "checkbox",
        "pay": "button",
    },
    "done": {},
}

#: App reference embedded in every task prompt (the sqlq schema's counterpart).
UI_GUIDE = """\
Pages and elements:
- search: text fields 'from', 'to', 'date'; select 'passengers' (options 1-4, default 1);
  button 'search' (requires from/to/date filled in; goes to the results page)
- results: buttons 'choose_morning', 'choose_evening', 'choose_redeye' (pick that flight;
  goes to checkout); button 'back' (returns to search, keeping the typed values)
- checkout: text fields 'name', 'email'; checkbox 'insurance' (starts off; a click toggles);
  button 'pay' (requires a name and an email containing '@'; freezes the booking -> done)
Action format (applied in order; execution stops at the first invalid step):
  {"do": "type", "target": "<text field>", "value": "<text>"}
  {"do": "select", "target": "passengers", "value": "1".."4"}
  {"do": "click", "target": "<button or checkbox>"}"""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What executing one action list against a fresh TripBooker produced."""

    page: str  # page the run ended on
    booking: dict[str, Any] | None  # frozen record iff 'pay' succeeded
    record: dict[str, Any]  # state snapshot at the end (for partial-credit scoring)
    violation: Violation | None  # the first violation, if any


class TripBooker:
    """The app state machine: current page, form state, and the frozen booking."""

    def __init__(self) -> None:
        self.page = "search"
        self.fields: dict[str, str] = {"from": "", "to": "", "date": "", "name": "", "email": ""}
        self.passengers = PASSENGER_OPTIONS[0]
        self.insurance = False
        self.flight: str | None = None
        self.booking: dict[str, Any] | None = None

    @property
    def record(self) -> dict[str, Any]:
        """The would-be booking record for the current state."""
        return {
            "from": self.fields["from"],
            "to": self.fields["to"],
            "date": self.fields["date"],
            "passengers": self.passengers,
            "flight": self.flight,
            "name": self.fields["name"],
            "email": self.fields["email"],
            "insurance": self.insurance,
        }

    def apply(self, index: int, action: Mapping[str, Any]) -> Violation | None:
        """Apply one shape-checked action; return the violation that stops the run, if any."""
        do, target = action["do"], action["target"]
        elements = PAGES[self.page]
        kind = elements.get(target)
        if kind is None:
            available = ", ".join(sorted(elements)) or "none"
            return Violation(
                code="UNKNOWN_TARGET",
                field=f"actions[{index}].target",
                message=f"no element '{target}' on page '{self.page}'; "
                f"available targets: {available}",
                expected=f"an element of page '{self.page}' ({available})",
                actual=target,
            )
        if do == "type":
            return self._type(index, target, kind, action["value"])
        if do == "select":
            return self._select(index, target, kind, action["value"])
        return self._click(index, target, kind)

    def _type(self, index: int, target: str, kind: str, value: str) -> Violation | None:
        if kind != "field":
            return _invalid_action(index, "type", target, kind, "text fields")
        self.fields[target] = value
        return None

    def _select(self, index: int, target: str, kind: str, value: str) -> Violation | None:
        if kind != "select":
            return _invalid_action(index, "select", target, kind, "selects")
        if value not in PASSENGER_OPTIONS:
            options = ", ".join(PASSENGER_OPTIONS)
            return Violation(
                code="INVALID_ACTION",
                field=f"actions[{index}].value",
                message=f"'{value}' is not an option of select '{target}'; options: {options}",
                expected=f"one of: {options}",
                actual=value,
            )
        self.passengers = value
        return None

    def _click(self, index: int, target: str, kind: str) -> Violation | None:
        if kind in ("field", "select"):
            return _invalid_action(index, "click", target, kind, "buttons and checkboxes")
        if kind == "checkbox":
            self.insurance = not self.insurance
            return None
        if target == "search":
            return self._click_search(index)
        if target == "back":
            self.page = "search"
            return None
        if target == "pay":
            return self._click_pay(index)
        self.flight = target.removeprefix("choose_")
        self.page = "checkout"
        return None

    def _click_search(self, index: int) -> Violation | None:
        empty = [name for name in ("from", "to", "date") if not self.fields[name]]
        if empty:
            missing = ", ".join(empty)
            return Violation(
                code="PRECONDITION_FAILED",
                field=f"actions[{index}]",
                message=f"clicked 'search' but required fields are still empty: {missing}",
                expected="from, to and date filled in before searching",
                actual=f"empty: {missing}",
            )
        self.page = "results"
        return None

    def _click_pay(self, index: int) -> Violation | None:
        problems = []
        if not self.fields["name"]:
            problems.append("name is empty")
        if not self.fields["email"]:
            problems.append("email is empty")
        elif "@" not in self.fields["email"]:
            problems.append("email has no '@'")
        if problems:
            summary = "; ".join(problems)
            return Violation(
                code="PRECONDITION_FAILED",
                field=f"actions[{index}]",
                message=f"clicked 'pay' but traveler details are invalid: {summary}",
                expected="a non-empty name and an email containing '@'",
                actual=summary,
            )
        self.booking = dict(self.record)
        self.page = "done"
        return None


def run_actions(actions: Sequence[Mapping[str, Any]]) -> ExecutionResult:
    """Execute an action list against a fresh app, stopping at the first violation."""
    app = TripBooker()
    for index, action in enumerate(actions):
        violation = app.apply(index, action)
        if violation is not None:
            return ExecutionResult(
                page=app.page, booking=None, record=app.record, violation=violation
            )
    return ExecutionResult(page=app.page, booking=app.booking, record=app.record, violation=None)


def _invalid_action(index: int, do: str, target: str, kind: str, allowed: str) -> Violation:
    return Violation(
        code="INVALID_ACTION",
        field=f"actions[{index}].do",
        message=f"'{do}' does not apply to the {kind} '{target}' — '{do}' only works on {allowed}",
        expected=f"'{do}' on {allowed}",
        actual=f"{do} on {kind} '{target}'",
    )
