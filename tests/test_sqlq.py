"""The text-to-SQL domain: validator tiers, corpus integrity, and loop lift."""

from __future__ import annotations

import pytest

from selfcorrect.domains import get_domain
from selfcorrect.loop import SelfCorrectingAgent
from selfcorrect.sqlq.loader import load_checks
from selfcorrect.sqlq.rules import build_sql_validator


@pytest.fixture(scope="module")
def domain():
    return get_domain("sqlq")


@pytest.fixture(scope="module")
def validator():
    return build_sql_validator()


def _codes(validator, output) -> list[str]:
    return [v.code for v in validator.validate(output)]


# ---------------------------------------------------------------- corpus


def test_every_gold_query_passes_its_own_validator(domain, validator) -> None:
    for gt in domain.load_ground_truth().values():
        assert validator.validate(gt) == [], gt["task_id"]


def test_tasks_and_ground_truth_agree(domain) -> None:
    tasks = domain.load_tasks()
    truth = domain.load_ground_truth()
    assert {t.id for t in tasks} == set(truth)
    for task in tasks:
        assert task.id in task.prompt  # the prompt tells the model its task_id


def test_default_demo_task_repairs_within_budget(domain) -> None:
    agent = SelfCorrectingAgent(
        domain.build_simulated_engine(42),
        domain.build_validator(),
        domain.build_critic(),
        max_attempts=3,
    )
    tasks = {t.id: t for t in domain.load_tasks()}
    result = agent.run(tasks[domain.default_demo_task])
    assert result.success and result.num_attempts == 2


# ---------------------------------------------------------------- validator tiers


def test_missing_and_mistyped_fields(validator) -> None:
    assert _codes(validator, {}) == ["MISSING_FIELD", "MISSING_FIELD"]
    assert _codes(validator, {"task_id": 3, "sql": "SELECT 1"}) == ["WRONG_TYPE"]


def test_unknown_task_id(validator) -> None:
    assert _codes(validator, {"task_id": "sql_999", "sql": "SELECT 1"}) == ["UNKNOWN_TASK"]


def test_writes_and_multi_statements_are_rejected(validator) -> None:
    for sql in (
        "DELETE FROM orders",
        "SELECT 1; SELECT 2",
        "UPDATE orders SET status = 'x'",
    ):
        assert _codes(validator, {"task_id": "sql_001", "sql": sql}) == ["NOT_A_SELECT"], sql


def test_sql_error_is_reported_with_the_engine_message(validator) -> None:
    violations = validator.validate({"task_id": "sql_001", "sql": "SELECT nope FROM customers"})
    assert [v.code for v in violations] == ["SQL_ERROR"]
    assert "nope" in (violations[0].actual or "")


def test_wrong_columns_rows_and_values_are_distinguished(validator) -> None:
    cases = {
        # right data, wrong column name -> MISSING_COLUMNS
        "SELECT name AS n FROM customers WHERE country = 'DE' ORDER BY name": "MISSING_COLUMNS",
        # missing WHERE -> too many rows
        "SELECT name FROM customers ORDER BY name": "WRONG_ROW_COUNT",
        # right shape, wrong rows -> WRONG_RESULT
        "SELECT name FROM customers WHERE country = 'TR' UNION SELECT name FROM customers "
        "WHERE country = 'US' ORDER BY name": "WRONG_RESULT",
    }
    for sql, expected_code in cases.items():
        assert _codes(validator, {"task_id": "sql_001", "sql": sql}) == [expected_code], sql


def test_checks_never_contain_gold_sql(domain) -> None:
    """The in-loop verifier holds derived checks, not the answers."""
    for checks in load_checks().values():
        assert not hasattr(checks, "sql")
        assert isinstance(checks.checksum, str) and len(checks.checksum) == 16


# ---------------------------------------------------------------- loop lift


def test_self_correction_lift_on_sqlq(domain) -> None:
    """Same bounds contract as the invoice bench: ON beats OFF by >= 15pp."""
    rates = {}
    for label, max_attempts in (("off", 1), ("on", 3)):
        agent = SelfCorrectingAgent(
            domain.build_simulated_engine(42),
            domain.build_validator(),
            domain.build_critic(),
            max_attempts=max_attempts,
        )
        results = [agent.run(t) for t in domain.load_tasks()]
        rates[label] = sum(r.success for r in results) / len(results)
    assert rates["on"] - rates["off"] >= 0.15
    assert rates["on"] >= 0.85


def test_determinism_same_seed_same_outputs(domain) -> None:
    def run_all():
        agent = SelfCorrectingAgent(
            domain.build_simulated_engine(7),
            domain.build_validator(),
            domain.build_critic(),
            max_attempts=3,
        )
        return [(r.task_id, r.success, r.num_attempts) for r in map(agent.run, domain.load_tasks())]

    assert run_all() == run_all()
