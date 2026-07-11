"""The computer-use domain: validator tiers, corpus integrity, and loop lift."""

from __future__ import annotations

import pytest

from selfcorrect.cua.loader import load_expected_records
from selfcorrect.cua.rules import build_cua_validator
from selfcorrect.cua.ui import BOOKING_FIELDS, run_actions
from selfcorrect.domains import get_domain
from selfcorrect.loop import SelfCorrectingAgent


@pytest.fixture(scope="module")
def domain():
    return get_domain("cua")


@pytest.fixture(scope="module")
def validator():
    return build_cua_validator()


def _codes(validator, output) -> list[str]:
    return [v.code for v in validator.validate(output)]


def _gold(domain, task_id: str) -> dict:
    return domain.load_ground_truth()[task_id]


# ---------------------------------------------------------------- corpus


def test_every_gold_action_list_passes_its_own_validator(domain, validator) -> None:
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
    assert _codes(validator, {"task_id": 3, "actions": []}) == ["WRONG_TYPE"]
    assert _codes(validator, {"task_id": "cua_001", "actions": "click pay"}) == ["WRONG_TYPE"]


def test_malformed_actions_are_shape_violations(validator) -> None:
    base = {"task_id": "cua_001"}
    assert _codes(validator, {**base, "actions": ["click"]}) == ["WRONG_TYPE"]
    assert _codes(validator, {**base, "actions": [{"target": "search"}]}) == ["MISSING_FIELD"]
    assert _codes(validator, {**base, "actions": [{"do": "hover", "target": "search"}]}) == [
        "WRONG_TYPE"
    ]
    # a 'type' action without a value is malformed, not executed
    assert _codes(validator, {**base, "actions": [{"do": "type", "target": "from"}]}) == [
        "MISSING_FIELD"
    ]


def test_unknown_task_id(validator) -> None:
    assert _codes(validator, {"task_id": "cua_999", "actions": []}) == ["UNKNOWN_TASK"]


def test_unknown_target_names_the_page_and_its_elements(validator) -> None:
    output = {"task_id": "cua_001", "actions": [{"do": "click", "target": "pay"}]}
    violations = validator.validate(output)
    assert [v.code for v in violations] == ["UNKNOWN_TARGET"]
    assert "page 'search'" in violations[0].message
    for target in ("from", "to", "date", "passengers", "search"):
        assert target in violations[0].message


def test_invalid_action_verb_element_mismatches(validator) -> None:
    cases = [
        {"do": "type", "target": "search", "value": "x"},  # type on a button
        {"do": "click", "target": "from"},  # click on a text field
        {"do": "select", "target": "date", "value": "1"},  # select on a text field
        {"do": "select", "target": "passengers", "value": "9"},  # value not an option
    ]
    for action in cases:
        output = {"task_id": "cua_001", "actions": [action]}
        assert _codes(validator, output) == ["INVALID_ACTION"], action


def test_precondition_failures_at_search_and_pay(domain, validator) -> None:
    # search with nothing typed
    output = {"task_id": "cua_001", "actions": [{"do": "click", "target": "search"}]}
    violations = validator.validate(output)
    assert [v.code for v in violations] == ["PRECONDITION_FAILED"]
    assert "from" in (violations[0].actual or "")
    # pay with a mailless email: replace the gold email with one lacking '@'
    gold = _gold(domain, "cua_001")
    for action in gold["actions"]:
        if action.get("target") == "email":
            action["value"] = "ada.lovelace.dev"
    violations = validator.validate(gold)
    assert [v.code for v in violations] == ["PRECONDITION_FAILED"]
    assert "@" in (violations[0].actual or "")


def test_not_completed_names_the_stalled_page(domain, validator) -> None:
    gold = _gold(domain, "cua_002")
    gold["actions"] = [a for a in gold["actions"] if a.get("target") != "pay"]
    violations = validator.validate(gold)
    assert [v.code for v in violations] == ["NOT_COMPLETED"]
    assert violations[0].actual == "checkout"


def test_wrong_booking_reports_the_first_mismatched_field(domain, validator) -> None:
    # wrong date -> WRONG_BOOKING on 'date' with expected/actual set
    gold = _gold(domain, "cua_001")
    for action in gold["actions"]:
        if action.get("target") == "date":
            action["value"] = "2026-08-15"
    violations = validator.validate(gold)
    assert [v.code for v in violations] == ["WRONG_BOOKING"]
    assert violations[0].field == "date"
    assert violations[0].expected == "2026-08-14" and violations[0].actual == "2026-08-15"
    # wrong flight AND wrong insurance -> 'flight' wins (booking-field order)
    gold = _gold(domain, "cua_001")
    gold["actions"] = [a for a in gold["actions"] if a.get("target") != "insurance"]
    for action in gold["actions"]:
        if str(action.get("target", "")).startswith("choose_"):
            action["target"] = "choose_evening"
    violations = validator.validate(gold)
    assert [v.code for v in violations] == ["WRONG_BOOKING"]
    assert violations[0].field == "flight"


def test_executor_stops_at_the_first_violation() -> None:
    actions = [
        {"do": "click", "target": "pay"},  # unknown on the search page
        {"do": "click", "target": "nonsense"},  # never reached
        {"do": "type", "target": "from", "value": "BER"},  # never reached
    ]
    result = run_actions(actions)
    assert result.violation is not None and result.violation.code == "UNKNOWN_TARGET"
    assert "actions[0]" in result.violation.field
    assert result.record["from"] == ""  # the later type action was never applied


def test_expected_records_never_contain_gold_actions(domain) -> None:
    """The in-loop verifier holds derived booking records, not the answers."""
    for record in load_expected_records().values():
        assert set(record) == set(BOOKING_FIELDS)
        assert "actions" not in record


# ---------------------------------------------------------------- loop lift


def test_self_correction_lift_on_cua(domain) -> None:
    """Same bounds contract as the other domains: ON beats OFF by >= 15pp."""
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
