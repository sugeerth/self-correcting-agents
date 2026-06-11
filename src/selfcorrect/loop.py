"""The self-correction loop: generate -> validate -> critique -> repair.

Architectural invariant: the engine only ever sees Feedback (natural-language
repair guidance), never raw Violations. Validators speak in structured
violations; the critic translates them; the engine consumes the translation.
"""

from __future__ import annotations

from typing import Any

from selfcorrect.types import (
    Attempt,
    Critic,
    Engine,
    Feedback,
    RunResult,
    Task,
    Validator,
    Violation,
)

GENERATION_FAILED = "GENERATION_FAILED"


def _best_output(attempts: list[Attempt]) -> dict[str, Any] | None:
    """Output of the attempt with the fewest ERROR violations (ties: latest)."""
    best: Attempt | None = None
    for attempt in attempts:
        if attempt.output is None:
            continue
        if best is None or attempt.error_count <= best.error_count:
            best = attempt
    return None if best is None else best.output


class SelfCorrectingAgent:
    """Composes an Engine, Validator, and Critic into a bounded repair loop."""

    def __init__(
        self,
        engine: Engine,
        validator: Validator,
        critic: Critic,
        max_attempts: int = 3,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        self.engine = engine
        self.validator = validator
        self.critic = critic
        self.max_attempts = max_attempts

    def run(self, task: Task, max_attempts: int | None = None) -> RunResult:
        """Run up to `max_attempts` generate -> validate -> critique cycles.

        Returns on the first valid attempt; on exhaustion returns the best
        attempt's output (fewest ERROR violations, ties broken by latest).
        The critic runs for every failed attempt, including the last, so
        correction-OFF and correction-ON traces stay structurally identical.
        """
        n = max_attempts or self.max_attempts
        feedback_history: list[list[Feedback]] = []
        attempts: list[Attempt] = []
        for index in range(1, n + 1):
            attempt = self._generate(task, feedback_history, index)
            attempts.append(attempt)
            if attempt.is_valid:
                return RunResult(
                    task_id=task.id,
                    success=True,
                    final_output=attempt.output,
                    attempts=attempts,
                )
            attempt.feedback = self.critic.critique(attempt.output or {}, attempt.violations)
            feedback_history.append(attempt.feedback)
        return RunResult(
            task_id=task.id,
            success=False,
            final_output=_best_output(attempts),
            attempts=attempts,
        )

    def _generate(
        self, task: Task, feedback_history: list[list[Feedback]], index: int
    ) -> Attempt:
        """One engine call, validated. Engine exceptions become violations."""
        try:
            attempt = self.engine.generate(task, feedback_history)
        except Exception as exc:  # engine failure must not crash the loop
            return Attempt(
                index=index,
                output=None,
                engine=getattr(self.engine, "name", "?"),
                violations=[Violation(GENERATION_FAILED, "<root>", str(exc))],
            )
        attempt.index = index
        if attempt.output is not None:
            attempt.violations = self.validator.validate(attempt.output)
        else:
            attempt.violations = [
                Violation(GENERATION_FAILED, "<root>", "engine returned no output")
            ]
        return attempt
