"""Generic seeded fault-injection engine.

SimulatedEngine knows nothing about any domain: it deep-copies a ground-truth
dict and applies corruption functions drawn from an ErrorCatalog. Every output
is a pure function of (seed, task.id, feedback_history) — the error plan is
recomputed on each call and repair rounds are replayed from the history alone,
so the engine is completely stateless and runs are byte-for-byte reproducible.
"""

from __future__ import annotations

import copy
import json
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from selfcorrect.types import Attempt, Feedback, Task


@dataclass(frozen=True)
class ErrorSpec:
    """One injectable error: a corruption function plus repair semantics.

    `inject` is pure: it receives a deep copy of the ground truth and returns
    the corrupted copy. Repair matching keys on Feedback.violation_code only.
    """

    name: str
    inject: Callable[[dict[str, Any], Task, random.Random], dict[str, Any]]
    fixed_by: frozenset[str]  # violation codes whose Feedback can repair it
    repair_p: float  # P(repaired | matching feedback, task fixable)
    weight: float = 1.0  # selection weight within the catalog
    affects_validity: bool = True  # False => invisible to validators


@dataclass(frozen=True)
class ErrorCatalog:
    """A pool of injectable errors plus the per-task error-count distribution."""

    specs: tuple[ErrorSpec, ...]
    k_weights: Mapping[int, float]  # number of injected errors -> weight
    unfixable_p: float  # P(a task ignores all feedback)


class SimulatedEngine:
    """Deterministic fault-injection engine over a ground-truth corpus.

    Stateless across calls: each generate() recomputes the task's error plan
    from (seed, task.id) and replays repair rounds from feedback_history.
    """

    name = "simulated"

    def __init__(
        self,
        catalog: ErrorCatalog,
        ground_truth: Mapping[str, dict[str, Any]],
        seed: int = 42,
    ) -> None:
        self._catalog = catalog
        self._ground_truth = ground_truth
        self._seed = seed

    def generate(self, task: Task, feedback_history: Sequence[list[Feedback]]) -> Attempt:
        """Return ground truth corrupted by this task's surviving errors."""
        planned, is_unfixable = self._plan(task)
        index = len(feedback_history) + 1
        surviving = self._surviving(task, planned, is_unfixable, feedback_history)
        output: dict[str, Any] = copy.deepcopy(self._ground_truth[task.id])
        for spec in sorted(surviving, key=lambda s: s.name):
            rng = random.Random(f"{self._seed}:{task.id}:inject:{spec.name}")
            output = spec.inject(output, task, rng)
        raw_text = json.dumps(output)
        telemetry = random.Random(f"{self._seed}:{task.id}:{index}:telemetry")
        return Attempt(
            index=index,
            output=output,
            raw_text=raw_text,
            latency_s=0.3 + telemetry.random() * 1.0,
            input_tokens=len(task.prompt) // 4,
            output_tokens=len(raw_text) // 4,
            cost_usd=0.0,
            engine=self.name,
        )

    def _plan(self, task: Task) -> tuple[list[ErrorSpec], bool]:
        """The task's error plan: a pure function of (seed, task.id)."""
        rng = random.Random(f"{self._seed}:{task.id}:plan")
        ks = sorted(self._catalog.k_weights)
        k = rng.choices(ks, weights=[self._catalog.k_weights[x] for x in ks], k=1)[0]
        pool = sorted(self._catalog.specs, key=lambda s: s.name)
        chosen: list[ErrorSpec] = []
        for _ in range(min(k, len(pool))):
            chosen.append(pool.pop(_weighted_index(pool, rng)))
        is_unfixable = rng.random() < self._catalog.unfixable_p
        return chosen, is_unfixable

    def _surviving(
        self,
        task: Task,
        planned: list[ErrorSpec],
        is_unfixable: bool,
        feedback_history: Sequence[list[Feedback]],
    ) -> list[ErrorSpec]:
        """Replay repair rounds 1..len(feedback_history) over the planned errors."""
        active = list(planned)
        for round_no, round_feedback in enumerate(feedback_history, start=1):
            survivors: list[ErrorSpec] = []
            for spec in active:
                addressed = any(fb.violation_code in spec.fixed_by for fb in round_feedback)
                if addressed and not is_unfixable:
                    roll = random.Random(f"{self._seed}:{task.id}:{round_no}:{spec.name}")
                    if roll.random() < spec.repair_p:
                        continue  # repaired this round
                survivors.append(spec)
            active = survivors
        return active


def _weighted_index(pool: Sequence[ErrorSpec], rng: random.Random) -> int:
    """Index into pool drawn proportionally to spec.weight."""
    total = sum(spec.weight for spec in pool)
    threshold = rng.random() * total
    acc = 0.0
    for i, spec in enumerate(pool):
        acc += spec.weight
        if threshold < acc:
            return i
    return len(pool) - 1  # float round-off guard
