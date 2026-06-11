"""Invoice extraction: the flagship domain plug-in.

This is the ONLY package that knows about invoices. The core loop,
engines, and validators machinery are domain-agnostic.
"""

from __future__ import annotations

from typing import Any

from selfcorrect.types import Critic, Task, Validator


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
