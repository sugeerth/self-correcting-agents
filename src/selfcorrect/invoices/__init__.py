"""Invoice extraction: the flagship domain plug-in.

This is the ONLY package that knows about invoices. The core loop,
engines, and validators machinery are domain-agnostic.
"""

from __future__ import annotations

from typing import Any

from selfcorrect.domains import Domain
from selfcorrect.types import Critic, Engine, Task, Validator


def build_validator() -> Validator:
    """The composed invoice validation stack (schema + business rules)."""
    from selfcorrect.invoices.rules import build_invoice_validator

    return build_invoice_validator()


def build_critic() -> Critic:
    """TemplateCritic loaded with the invoice feedback templates."""
    from selfcorrect.critic import TemplateCritic
    from selfcorrect.invoices.feedback_templates import TEMPLATES

    return TemplateCritic(TEMPLATES)


def load_tasks() -> list[Task]:
    from selfcorrect.invoices.loader import load_tasks as _load

    return _load()


def load_ground_truth() -> dict[str, dict[str, Any]]:
    from selfcorrect.invoices.loader import load_ground_truth as _load

    return _load()


def build_simulated_engine(seed: int = 42) -> Engine:
    """The seeded fault-injection engine over the invoice ground truth."""
    from selfcorrect.invoices.errors import build_simulated_engine as _build

    return _build(load_ground_truth(), seed=seed)


def _domain() -> Domain:
    from selfcorrect.invoices.scoring import FIELD_NAMES, describe_row, field_accuracy

    return Domain(
        name="invoices",
        title="invoice extraction",
        unit="invoices",
        default_demo_task="inv_004",
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
