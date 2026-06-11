"""Core types for the self-correction loop.

Everything in this module is domain-agnostic: tasks, attempts, violations,
feedback, and the three protocols (Engine, Validator, Critic) that the
loop composes. Domain knowledge (e.g. invoices) lives in plug-in modules.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class Severity(StrEnum):
    ERROR = "error"  # blocks validity
    WARNING = "warning"  # reported, does not block


@dataclass(frozen=True, slots=True)
class Task:
    """A unit of work: a raw document plus an identifier."""

    id: str
    prompt: str  # the raw document text
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Violation:
    """One validation failure, structured enough for a critic to act on."""

    code: str  # machine key, e.g. "TOTAL_MISMATCH"
    field: str  # dotted path, e.g. "total" or "line_items[2].amount"
    message: str  # human-readable
    severity: Severity = Severity.ERROR
    expected: str | None = None  # stringified for JSON-safety
    actual: str | None = None


@dataclass(frozen=True, slots=True)
class Feedback:
    """Targeted repair guidance derived from a Violation."""

    violation_code: str  # the structured hook (simulated engine keys on THIS)
    field: str
    instruction: str  # natural language (what an LLM/human reads)


@dataclass(slots=True)
class Attempt:
    """One generation attempt plus what the loop learned about it.

    Engines populate the generation fields (output, raw_text, latency_s,
    tokens, cost_usd, engine). The loop fills index, violations, feedback.
    """

    index: int  # 1-based; loop sets it
    output: dict[str, Any] | None  # candidate extraction; None on hard generate failure
    raw_text: str | None = None
    violations: list[Violation] = field(default_factory=list)
    feedback: list[Feedback] = field(default_factory=list)
    latency_s: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    engine: str = ""  # "simulated" | "hermes:hermes3" | "anthropic:claude-opus-4-8"

    @property
    def is_valid(self) -> bool:
        return self.output is not None and not any(
            v.severity is Severity.ERROR for v in self.violations
        )

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity is Severity.ERROR)


@dataclass(slots=True)
class RunResult:
    """Outcome of a full self-correction run on one task."""

    task_id: str
    success: bool
    final_output: dict[str, Any] | None  # last valid output, else best attempt (fewest ERRORs)
    attempts: list[Attempt]  # the full trace

    @property
    def num_attempts(self) -> int:
        return len(self.attempts)

    @property
    def total_latency_s(self) -> float:
        return sum(a.latency_s for a in self.attempts)

    @property
    def total_cost_usd(self) -> float:
        return sum(a.cost_usd for a in self.attempts)


@runtime_checkable
class Engine(Protocol):
    """Produces candidate outputs, optionally informed by prior feedback.

    feedback_history[i] is the feedback issued after attempt i+1 failed;
    len(feedback_history) == number of prior failed attempts. Engines must
    populate the generation fields of Attempt; the loop owns index,
    violations, and feedback.
    """

    name: str

    def generate(self, task: Task, feedback_history: Sequence[list[Feedback]]) -> Attempt: ...


@runtime_checkable
class Validator(Protocol):
    """Deterministically checks a candidate output, returning violations."""

    name: str

    def validate(self, output: dict[str, Any]) -> list[Violation]: ...


@runtime_checkable
class Critic(Protocol):
    """Turns violations into targeted, actionable feedback."""

    def critique(
        self, output: dict[str, Any], violations: Sequence[Violation]
    ) -> list[Feedback]: ...
