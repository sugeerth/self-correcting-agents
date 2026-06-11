"""SimulatedEngine: determinism, repair specificity, unfixables, statelessness.

Uses a small inline ground-truth fixture (exact arithmetic) — the committed
corpus files are not touched here.
"""

from __future__ import annotations

import copy
import json
import random
from decimal import Decimal
from typing import Any

from selfcorrect.engines.simulated import ErrorCatalog, ErrorSpec, SimulatedEngine
from selfcorrect.invoices.errors import build_simulated_engine
from selfcorrect.types import Engine, Feedback, Task

GROUND_TRUTH: dict[str, dict[str, Any]] = {
    "inv_a": {
        "vendor": "Acme Corp",
        "date": "2025-03-14",
        "currency": "USD",
        "line_items": [
            {"description": "Widget", "quantity": 2, "unit_price": 10.00, "amount": 20.00},
            {"description": "Gadget", "quantity": 1, "unit_price": 35.50, "amount": 35.50},
            {"description": "Gizmo", "quantity": 3, "unit_price": 4.25, "amount": 12.75},
        ],
        "subtotal": 68.25,
        "tax": 6.83,
        "total": 75.08,
    },
    "inv_b": {
        "vendor": "Blue River Supplies",
        "date": "2025-11-02",
        "currency": "EUR",
        "line_items": [
            {"description": "Paper", "quantity": 10, "unit_price": 3.20, "amount": 32.00},
            {"description": "Ink", "quantity": 2, "unit_price": 14.00, "amount": 28.00},
        ],
        "subtotal": 60.00,
        "tax": 4.80,
        "total": 64.80,
    },
    "inv_c": {  # single line item: exercises the 1-item guards
        "vendor": "Zed Consulting Group",
        "date": "2025-07-30",
        "currency": "GBP",
        "line_items": [
            {"description": "Consulting", "quantity": 1, "unit_price": 500.00, "amount": 500.00},
        ],
        "subtotal": 500.00,
        "tax": 25.00,
        "total": 525.00,
    },
}

TASKS = [Task(id=tid, prompt=f"Invoice document text for {tid}. " * 8) for tid in GROUND_TRUTH]

FEEDBACK_ROUNDS: list[list[Feedback]] = [
    [Feedback(violation_code="TOTAL_MISMATCH", field="total", instruction="Recompute the total.")],
    [
        Feedback(
            violation_code="LINE_ITEMS_SUM",
            field="line_items",
            instruction="Re-extract every line item.",
        )
    ],
]

MATCHING = [Feedback(violation_code="TOTAL_MISMATCH", field="total", instruction="Fix the total.")]
GENERIC = [Feedback(violation_code="GENERIC", field="", instruction="Please try harder.")]


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _money_differs(a: Any, b: Any) -> bool:
    return abs(Decimal(str(a)) - Decimal(str(b))) > Decimal("0.01")


def _three_attempts(engine: SimulatedEngine, task: Task) -> list[tuple[str, str]]:
    """(sorted-json, raw_text) for attempts 1..3 with the canned feedback."""
    signatures: list[tuple[str, str]] = []
    for n in range(3):
        attempt = engine.generate(task, FEEDBACK_ROUNDS[:n])
        assert attempt.output is not None
        assert attempt.index == n + 1
        signatures.append((_dumps(attempt.output), attempt.raw_text or ""))
    return signatures


def _break_total(out: dict[str, Any], task: Task, rng: random.Random) -> dict[str, Any]:
    out["total"] = round(float(out["total"]) + 100.0 + rng.random(), 2)
    return out


def _forced_catalog(unfixable_p: float = 0.0) -> ErrorCatalog:
    """Single always-injected error, repaired with certainty when addressed."""
    spec = ErrorSpec(
        name="break_total",
        inject=_break_total,
        fixed_by=frozenset({"TOTAL_MISMATCH"}),
        repair_p=1.0,
    )
    return ErrorCatalog(specs=(spec,), k_weights={1: 1.0}, unfixable_p=unfixable_p)


def test_satisfies_engine_protocol() -> None:
    engine = build_simulated_engine(GROUND_TRUTH)
    assert isinstance(engine, Engine)
    assert engine.name == "simulated"


def test_same_seed_byte_identical_across_attempts() -> None:
    a = build_simulated_engine(GROUND_TRUTH, seed=42)
    b = build_simulated_engine(GROUND_TRUTH, seed=42)
    for task in TASKS:
        assert _three_attempts(a, task) == _three_attempts(b, task)


def test_different_seeds_produce_different_outputs() -> None:
    # Forced catalog guarantees one rng-noised error per task, so the seed
    # must show up in the output.
    a = SimulatedEngine(_forced_catalog(), GROUND_TRUTH, seed=42)
    b = SimulatedEngine(_forced_catalog(), GROUND_TRUTH, seed=7)
    a_outputs = [_dumps(a.generate(task, []).output) for task in TASKS]
    b_outputs = [_dumps(b.generate(task, []).output) for task in TASKS]
    assert a_outputs != b_outputs


def test_invoice_catalog_seeds_diverge() -> None:
    a = build_simulated_engine(GROUND_TRUTH, seed=42)
    b = build_simulated_engine(GROUND_TRUTH, seed=7)
    a_outputs = [_dumps(a.generate(task, []).output) for task in TASKS]
    b_outputs = [_dumps(b.generate(task, []).output) for task in TASKS]
    assert a_outputs != b_outputs


def test_matching_feedback_repairs_error() -> None:
    engine = SimulatedEngine(_forced_catalog(), GROUND_TRUTH, seed=1)
    task = TASKS[0]
    first = engine.generate(task, [])
    assert first.output is not None
    assert _money_differs(first.output["total"], GROUND_TRUTH[task.id]["total"])
    second = engine.generate(task, [MATCHING])
    assert second.output is not None
    assert _dumps(second.output) == _dumps(GROUND_TRUTH[task.id])


def test_generic_feedback_does_not_repair() -> None:
    engine = SimulatedEngine(_forced_catalog(), GROUND_TRUTH, seed=1)
    task = TASKS[0]
    second = engine.generate(task, [GENERIC])
    assert second.output is not None
    assert _money_differs(second.output["total"], GROUND_TRUTH[task.id]["total"])


def test_unfixable_error_persists_despite_correct_feedback() -> None:
    engine = SimulatedEngine(_forced_catalog(unfixable_p=1.0), GROUND_TRUTH, seed=1)
    task = TASKS[0]
    second = engine.generate(task, [MATCHING])
    assert second.output is not None
    assert _money_differs(second.output["total"], GROUND_TRUTH[task.id]["total"])
    third = engine.generate(task, [MATCHING, MATCHING])
    assert third.output is not None
    assert _money_differs(third.output["total"], GROUND_TRUTH[task.id]["total"])


def test_attempt_one_is_independent_of_other_generations() -> None:
    fresh = build_simulated_engine(GROUND_TRUTH, seed=42)
    baseline = _dumps(fresh.generate(TASKS[0], []).output)
    busy = build_simulated_engine(GROUND_TRUTH, seed=42)
    for task in TASKS[1:]:
        busy.generate(task, [])
        busy.generate(task, FEEDBACK_ROUNDS[:1])
        busy.generate(task, FEEDBACK_ROUNDS[:2])
    assert _dumps(busy.generate(TASKS[0], []).output) == baseline
    # And ground truth itself was never mutated by any inject function.
    assert GROUND_TRUTH["inv_a"]["total"] == 75.08
    assert len(GROUND_TRUTH["inv_a"]["line_items"]) == 3


def test_ground_truth_not_mutated_by_forced_inject() -> None:
    pristine = copy.deepcopy(GROUND_TRUTH)
    engine = SimulatedEngine(_forced_catalog(), GROUND_TRUTH, seed=3)
    for task in TASKS:
        engine.generate(task, [])
        engine.generate(task, [GENERIC])
    assert _dumps(GROUND_TRUTH) == _dumps(pristine)


def test_telemetry_fields_populated() -> None:
    engine = build_simulated_engine(GROUND_TRUTH, seed=42)
    attempt = engine.generate(TASKS[0], [])
    assert attempt.engine == "simulated"
    assert attempt.cost_usd == 0.0
    assert 0.3 <= attempt.latency_s <= 1.3
    assert attempt.input_tokens == len(TASKS[0].prompt) // 4
    assert attempt.raw_text is not None
    assert attempt.output_tokens == len(attempt.raw_text) // 4
