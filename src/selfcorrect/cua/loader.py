"""The computer-use corpus: booking goals, gold action lists, expected records.

Each task asks the agent to drive the TripBooker UI to a completed booking and
must return ``{"task_id": ..., "actions": [...]}``. Expected booking records
are computed ONCE here by EXECUTING the gold action lists against the app —
the validator then holds only the derived records, never the gold actions, so
in-loop validation stays a genuine verifier rather than an answer oracle
(exactly how sqlq derives acceptance checks from its gold queries).
"""

from __future__ import annotations

from functools import cache
from typing import Any

from selfcorrect.cua.ui import UI_GUIDE, run_actions
from selfcorrect.types import Task

_PROMPT_TEMPLATE = """\
Drive the TripBooker app to complete the booking below, then return
JSON: {{"task_id": "{task_id}", "actions": [<action>, ...]}}.

Goal: {goal}

App reference:
{ui_guide}
"""


def _gold(
    from_: str,
    to: str,
    date: str,
    flight: str,
    name: str,
    email: str,
    *,
    passengers: str | None = None,
    insurance: bool = False,
) -> tuple[dict[str, Any], ...]:
    """The canonical action list for a straight-through booking.

    ``passengers=None`` leaves the select untouched (the app defaults to "1").
    """
    actions: list[dict[str, Any]] = [
        {"do": "type", "target": "from", "value": from_},
        {"do": "type", "target": "to", "value": to},
        {"do": "type", "target": "date", "value": date},
    ]
    if passengers is not None:
        actions.append({"do": "select", "target": "passengers", "value": passengers})
    actions.append({"do": "click", "target": "search"})
    actions.append({"do": "click", "target": f"choose_{flight}"})
    actions.append({"do": "type", "target": "name", "value": name})
    actions.append({"do": "type", "target": "email", "value": email})
    if insurance:
        actions.append({"do": "click", "target": "insurance"})
    actions.append({"do": "click", "target": "pay"})
    return tuple(actions)


#: (task_id, goal, gold actions). Routes, dates, flights, passenger counts and
#: insurance all vary; cua_007 legitimately uses 'back' to revise the date.
_CORPUS: tuple[tuple[str, str, tuple[dict[str, Any], ...]], ...] = (
    (
        "cua_001",
        "Book a morning flight from BER to LIS on 2026-08-14 for 2 passengers under the "
        "name Ada Lovelace, email ada@lovelace.dev, with travel insurance.",
        _gold(
            "BER", "LIS", "2026-08-14", "morning", "Ada Lovelace", "ada@lovelace.dev",
            passengers="2", insurance=True,
        ),
    ),
    (
        "cua_002",
        "Book the red-eye from SFO to JFK on 2026-08-21 for 1 passenger under the name "
        "Grace Hopper, email grace@navy.mil, without travel insurance.",
        _gold("SFO", "JFK", "2026-08-21", "redeye", "Grace Hopper", "grace@navy.mil"),
    ),
    (
        "cua_003",
        "Book an evening flight from NRT to SIN on 2026-09-02 for 3 passengers under the "
        "name Alan Turing, email alan@bletchley.uk, without travel insurance.",
        _gold(
            "NRT", "SIN", "2026-09-02", "evening", "Alan Turing", "alan@bletchley.uk",
            passengers="3",
        ),
    ),
    (
        "cua_004",
        "Book a morning flight from LHR to DXB on 2026-08-30 for 4 passengers under the "
        "name Edsger Dijkstra, email ewd@tue.nl, with travel insurance.",
        _gold(
            "LHR", "DXB", "2026-08-30", "morning", "Edsger Dijkstra", "ewd@tue.nl",
            passengers="4", insurance=True,
        ),
    ),
    (
        "cua_005",
        "Book an evening flight from CDG to YUL on 2026-10-05 for 2 passengers under the "
        "name Margaret Hamilton, email margaret@apollo.org, without travel insurance.",
        _gold(
            "CDG", "YUL", "2026-10-05", "evening", "Margaret Hamilton", "margaret@apollo.org",
            passengers="2",
        ),
    ),
    (
        "cua_006",
        "Book a morning flight from OAK to SAN on 2026-08-18 for 1 passenger under the "
        "name Katherine Johnson, email katherine@nasa.gov, with travel insurance.",
        _gold(
            "OAK", "SAN", "2026-08-18", "morning", "Katherine Johnson", "katherine@nasa.gov",
            passengers="1", insurance=True,
        ),
    ),
    (
        "cua_007",
        "Search for a flight from SFO to NRT on 2026-09-01 for 2 passengers, then go back "
        "and change the date to 2026-09-03 before searching again; book the red-eye under "
        "the name Barbara Liskov, email liskov@mit.edu, without travel insurance.",
        (
            {"do": "type", "target": "from", "value": "SFO"},
            {"do": "type", "target": "to", "value": "NRT"},
            {"do": "type", "target": "date", "value": "2026-09-01"},
            {"do": "select", "target": "passengers", "value": "2"},
            {"do": "click", "target": "search"},
            {"do": "click", "target": "back"},
            {"do": "type", "target": "date", "value": "2026-09-03"},
            {"do": "click", "target": "search"},
            {"do": "click", "target": "choose_redeye"},
            {"do": "type", "target": "name", "value": "Barbara Liskov"},
            {"do": "type", "target": "email", "value": "liskov@mit.edu"},
            {"do": "click", "target": "pay"},
        ),
    ),
    (
        "cua_008",
        "Book the red-eye from MEX to BOG on 2026-11-11 for 3 passengers under the name "
        "Guido van Rossum, email guido@python.org, with travel insurance.",
        _gold(
            "MEX", "BOG", "2026-11-11", "redeye", "Guido van Rossum", "guido@python.org",
            passengers="3", insurance=True,
        ),
    ),
    (
        "cua_009",
        "Book an evening flight from SYD to AKL on 2026-12-24 for 4 passengers under the "
        "name Annie Easley, email annie@nasa.gov, without travel insurance.",
        _gold(
            "SYD", "AKL", "2026-12-24", "evening", "Annie Easley", "annie@nasa.gov",
            passengers="4",
        ),
    ),
    (
        "cua_010",
        "Book a morning flight from FRA to WAW on 2026-08-25 for 2 passengers under the "
        "name Radia Perlman, email radia@spanning.tree, with travel insurance.",
        _gold(
            "FRA", "WAW", "2026-08-25", "morning", "Radia Perlman", "radia@spanning.tree",
            passengers="2", insurance=True,
        ),
    ),
)


@cache
def load_expected_records() -> dict[str, dict[str, Any]]:
    """Expected booking record per task, derived from the gold actions once."""
    records: dict[str, dict[str, Any]] = {}
    for task_id, _goal, actions in _CORPUS:
        result = run_actions(actions)
        if result.violation is not None or result.booking is None:
            raise ValueError(f"gold action list for {task_id} does not complete the booking")
        records[task_id] = result.booking
    return records


def load_tasks() -> list[Task]:
    return [
        Task(
            id=task_id,
            prompt=_PROMPT_TEMPLATE.format(task_id=task_id, goal=goal, ui_guide=UI_GUIDE),
        )
        for task_id, goal, _actions in _CORPUS
    ]


def load_ground_truth() -> dict[str, dict[str, Any]]:
    return {
        task_id: {"task_id": task_id, "actions": [dict(action) for action in actions]}
        for task_id, _goal, actions in _CORPUS
    }
