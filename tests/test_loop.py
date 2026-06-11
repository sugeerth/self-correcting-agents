"""Tests for the self-correction loop and trace serialization."""

from __future__ import annotations

import io
import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from selfcorrect.loop import SelfCorrectingAgent
from selfcorrect.trace import TraceWriter, pretty_print_run, run_result_to_dict
from selfcorrect.types import Attempt, Feedback, Task, Violation

TASK = Task(id="t1", prompt="a raw document")

# A script item is: an output dict, None (engine returns Attempt with no
# output), or an Exception instance (engine raises).
ScriptItem = dict[str, Any] | Exception | None


class FakeEngine:
    """Scripted engine that records what the loop showed it."""

    def __init__(self, script: list[ScriptItem], name: str = "fake") -> None:
        self.script = script
        self.name = name
        self.history_lengths: list[int] = []
        self.seen_feedback_items: list[Any] = []

    def generate(self, task: Task, feedback_history: Sequence[list[Feedback]]) -> Attempt:
        self.history_lengths.append(len(feedback_history))
        self.seen_feedback_items.extend(
            item for batch in feedback_history for item in batch
        )
        step = self.script[len(self.history_lengths) - 1]
        if isinstance(step, Exception):
            raise step
        return Attempt(index=0, output=step, engine=self.name, latency_s=0.1)


class StubValidator:
    """Emits output['errors'] ERROR violations; zero means valid."""

    name = "stub"

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        return [
            Violation(
                code=f"E{i}",
                field=f"field_{i}",
                message=f"problem {i}",
                expected="good",
                actual="bad",
            )
            for i in range(int(output.get("errors", 0)))
        ]


class StubCritic:
    """One Feedback per Violation."""

    def critique(
        self, output: dict[str, Any], violations: Sequence[Violation]
    ) -> list[Feedback]:
        return [Feedback(v.code, v.field, f"please fix {v.code}") for v in violations]


def make_agent(
    script: list[ScriptItem], max_attempts: int = 3, name: str = "fake"
) -> tuple[FakeEngine, SelfCorrectingAgent]:
    engine = FakeEngine(script, name=name)
    agent = SelfCorrectingAgent(engine, StubValidator(), StubCritic(), max_attempts=max_attempts)
    return engine, agent


def test_success_on_third_attempt() -> None:
    script: list[ScriptItem] = [{"errors": 2}, {"errors": 1}, {"errors": 0, "tag": "good"}]
    engine, agent = make_agent(script)
    result = agent.run(TASK)
    assert result.success is True
    assert result.final_output == {"errors": 0, "tag": "good"}
    assert len(result.attempts) == 3
    assert [a.index for a in result.attempts] == [1, 2, 3]
    assert result.attempts[2].is_valid


def test_engine_sees_growing_feedback_history() -> None:
    script: list[ScriptItem] = [{"errors": 2}, {"errors": 1}, {"errors": 0}]
    engine, agent = make_agent(script)
    agent.run(TASK)
    assert engine.history_lengths == [0, 1, 2]


def test_engine_only_ever_sees_feedback_never_violations() -> None:
    script: list[ScriptItem] = [{"errors": 2}, {"errors": 1}, {"errors": 0}]
    engine, agent = make_agent(script)
    agent.run(TASK)
    assert engine.seen_feedback_items, "engine should have received feedback"
    assert all(isinstance(item, Feedback) for item in engine.seen_feedback_items)
    assert not any(isinstance(item, Violation) for item in engine.seen_feedback_items)


def test_max_attempts_one_is_self_correction_off() -> None:
    engine, agent = make_agent([{"errors": 1}], max_attempts=1)
    result = agent.run(TASK)
    assert engine.history_lengths == [0]  # exactly one generate call
    assert result.success is False
    assert result.num_attempts == 1
    # Critic runs even for the last failed attempt (OFF/ON traces identical).
    assert result.attempts[0].feedback


def test_run_max_attempts_overrides_constructor() -> None:
    engine, agent = make_agent([{"errors": 1}, {"errors": 1}, {"errors": 0}], max_attempts=3)
    result = agent.run(TASK, max_attempts=2)
    assert len(engine.history_lengths) == 2
    assert result.success is False


def test_exhaustion_returns_best_output_fewest_errors_ties_latest() -> None:
    script: list[ScriptItem] = [
        {"errors": 1, "tag": "first"},
        {"errors": 3, "tag": "worst"},
        {"errors": 1, "tag": "latest"},
    ]
    engine, agent = make_agent(script)
    result = agent.run(TASK)
    assert result.success is False
    assert result.final_output is not None
    assert result.final_output["tag"] == "latest"  # tie on 1 error -> latest wins
    assert len(result.attempts) == 3


def test_exhaustion_with_no_output_returns_none() -> None:
    engine, agent = make_agent([None, None], max_attempts=2)
    result = agent.run(TASK)
    assert result.success is False
    assert result.final_output is None
    codes = [v.code for a in result.attempts for v in a.violations]
    assert codes == ["GENERATION_FAILED", "GENERATION_FAILED"]
    assert result.attempts[0].violations[0].message == "engine returned no output"


def test_engine_raises_then_recovers() -> None:
    script: list[ScriptItem] = [RuntimeError("boom"), {"errors": 0, "tag": "fixed"}]
    engine, agent = make_agent(script)
    result = agent.run(TASK)
    assert result.success is True
    assert result.final_output == {"errors": 0, "tag": "fixed"}
    assert len(result.attempts) == 2
    first = result.attempts[0]
    assert first.index == 1
    assert first.output is None
    assert first.engine == "fake"
    assert [v.code for v in first.violations] == ["GENERATION_FAILED"]
    assert first.violations[0].field == "<root>"
    assert "boom" in first.violations[0].message
    # The failure was critiqued, so attempt 2 saw one batch of feedback.
    assert engine.history_lengths == [0, 1]


def _run_result(name: str = "fake") -> Any:
    script: list[ScriptItem] = [
        {"errors": 1, "amount": Decimal("10.50")},
        {"errors": 0, "amount": Decimal("99.99")},
    ]
    _, agent = make_agent(script, name=name)
    return agent.run(TASK)


def test_run_result_to_dict_round_trips_through_json() -> None:
    result = _run_result(name="simulated")
    d = run_result_to_dict(result)
    assert json.loads(json.dumps(d)) == d
    assert d["task_id"] == "t1"
    assert d["success"] is True
    assert d["num_attempts"] == 2
    assert isinstance(d["total_latency_s"], float)
    assert isinstance(d["total_cost_usd"], float)
    assert d["engines"] == ["simulated"]
    assert d["simulated"] is True
    assert d["attempts"][0]["violations"][0]["severity"] == "error"
    assert d["attempts"][0]["output"]["amount"] == "10.50"  # Decimal -> str
    assert d["final_output"]["amount"] == "99.99"


def test_run_result_dict_simulated_false_for_other_engines() -> None:
    d = run_result_to_dict(_run_result(name="hermes:hermes3"))
    assert d["simulated"] is False
    assert d["engines"] == ["hermes:hermes3"]


def test_trace_writer_one_parseable_line_per_result(tmp_path: Path) -> None:
    path = tmp_path / "traces" / "run.jsonl"
    first = _run_result()
    second = _run_result()
    with TraceWriter(path) as writer:
        writer.write(first)
        writer.write(second)
    with TraceWriter(path) as writer:  # reopening appends
        writer.write(first)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    parsed = [json.loads(line) for line in lines]
    assert [p["task_id"] for p in parsed] == ["t1", "t1", "t1"]
    assert parsed[0] == run_result_to_dict(first)


def test_pretty_print_run_renders_demo_blocks() -> None:
    script: list[ScriptItem] = [
        {"errors": 1, "note": "x" * 300},
        {"errors": 0, "note": "ok"},
    ]
    _, agent = make_agent(script, name="simulated")
    result = agent.run(TASK)
    buffer = io.StringIO()
    pretty_print_run(result, file=buffer)
    text = buffer.getvalue()
    assert "Attempt 1/2 — engine: simulated — 0.10s" in text
    assert "CODE" in text and "FIELD" in text and "EXPECTED -> ACTUAL" in text
    assert "Feedback to agent:" in text
    assert "VALID after 2 attempt(s)" in text
    assert all(len(line) <= 100 for line in text.splitlines())


def test_pretty_print_run_failed_verdict() -> None:
    _, agent = make_agent([{"errors": 1}], max_attempts=1)
    result = agent.run(TASK)
    buffer = io.StringIO()
    pretty_print_run(result, file=buffer)
    assert "FAILED after 1 attempt(s) — returning best attempt" in buffer.getvalue()
