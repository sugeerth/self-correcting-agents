"""The domain registry: lookup, the invoices plug-in contract, and errors."""

from __future__ import annotations

import pytest

from selfcorrect.domains import DOMAIN_NAMES, get_domain


def test_registry_names_resolve() -> None:
    for name in DOMAIN_NAMES:
        assert get_domain(name).name == name


def test_unknown_domain_is_a_value_error_naming_the_valid_ones() -> None:
    with pytest.raises(ValueError, match="invoices"):
        get_domain("nope")


def test_invoices_domain_contract() -> None:
    """Everything the CLI/bench consume is present and mutually consistent."""
    domain = get_domain("invoices")
    tasks = domain.load_tasks()
    truth = domain.load_ground_truth()
    assert {t.id for t in tasks} == set(truth)
    assert domain.default_demo_task in truth
    assert domain.field_names  # at least one accuracy column
    # A perfect output scores 1.0 on every field; a missing output scores 0.0.
    some_truth = truth[domain.default_demo_task]
    perfect = domain.field_accuracy(some_truth, some_truth)
    assert set(perfect) == set(domain.field_names)
    assert all(score == 1.0 for score in perfect.values())
    assert all(score == 0.0 for score in domain.field_accuracy(None, some_truth).values())
    assert domain.describe_row(some_truth)  # non-empty one-liner


def test_simulated_engine_comes_from_the_domain() -> None:
    domain = get_domain("invoices")
    engine = domain.build_simulated_engine(42)
    assert engine.name == "simulated"
