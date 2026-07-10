"""Domain registry: every domain plug-in behind one uniform interface.

A ``Domain`` bundles everything the CLI and benchmark need from a plug-in:
corpus loading, validator/critic construction, a simulated-engine factory,
field-accuracy scoring, and presentation strings. Domain package imports are
lazy (inside ``get_domain``) so importing the core never pulls in a domain
package — the same boundary the engine registry keeps, enforced by tests.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from selfcorrect.types import Critic, Engine, Task, Validator

#: Valid values for get_domain(name) / the CLI --domain flag.
DOMAIN_NAMES: tuple[str, ...] = ("invoices",)


@dataclass(frozen=True)
class Domain:
    """One domain plug-in, as seen by the CLI and the benchmark."""

    name: str  # registry key / CLI value
    title: str  # results.md heading, e.g. "invoice extraction"
    unit: str  # what one task is, e.g. "invoices"
    default_demo_task: str  # a task that repairs before max_attempts (verified)
    load_tasks: Callable[[], list[Task]]
    load_ground_truth: Callable[[], dict[str, dict[str, Any]]]
    build_validator: Callable[[], Validator]
    build_critic: Callable[[], Critic]
    build_simulated_engine: Callable[[int], Engine]  # seed -> engine
    field_names: tuple[str, ...]  # accuracy columns, in report order
    field_accuracy: Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, float]]
    describe_row: Callable[[dict[str, Any]], str]  # one list-corpus line per ground truth


def get_domain(name: str) -> Domain:
    """Look up a domain plug-in by name (imports it lazily)."""
    if name == "invoices":
        from selfcorrect.invoices import DOMAIN

        return DOMAIN
    raise ValueError(f"Unknown domain {name!r}; valid domains: {', '.join(DOMAIN_NAMES)}")
