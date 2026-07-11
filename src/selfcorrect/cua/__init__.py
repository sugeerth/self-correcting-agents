"""Computer use: the third domain plug-in.

Exists to prove the core generalizes past extraction and code generation:
the loop, engines, CLI, and benchmark run this domain untouched. Everything
UI-specific — the TripBooker state machine, booking corpus, executing
validator, repair templates, error catalog, and per-facet scoring — lives in
this package.
"""

from __future__ import annotations

from typing import Any

from selfcorrect.domains import Domain
from selfcorrect.types import Critic, Engine, Task, Validator


def build_validator() -> Validator:
    """Shape + task routing + UI execution + booking-record end assertions."""
    from selfcorrect.cua.rules import build_cua_validator

    return build_cua_validator()


def build_critic() -> Critic:
    """TemplateCritic loaded with the computer-use repair templates."""
    from selfcorrect.critic import TemplateCritic
    from selfcorrect.cua.feedback_templates import TEMPLATES

    return TemplateCritic(TEMPLATES)


def load_tasks() -> list[Task]:
    from selfcorrect.cua.loader import load_tasks as _load

    return _load()


def load_ground_truth() -> dict[str, dict[str, Any]]:
    from selfcorrect.cua.loader import load_ground_truth as _load

    return _load()


def build_simulated_engine(seed: int = 42) -> Engine:
    """The seeded fault-injection engine over the gold action lists."""
    from selfcorrect.cua.errors import build_simulated_engine as _build

    return _build(load_ground_truth(), seed=seed)


def _domain() -> Domain:
    from selfcorrect.cua.scoring import FIELD_NAMES, describe_row, field_accuracy

    return Domain(
        name="cua",
        title="computer use",
        unit="flows",
        default_demo_task="cua_003",  # repairs on attempt 2 under seed 42 (verified)
        load_tasks=load_tasks,
        load_ground_truth=load_ground_truth,
        build_validator=build_validator,
        build_critic=build_critic,
        build_simulated_engine=build_simulated_engine,
        field_names=FIELD_NAMES,
        field_accuracy=field_accuracy,
        describe_row=describe_row,
    )


#: This plug-in, packaged for the registry (selfcorrect.domains.get_domain).
DOMAIN = _domain()
