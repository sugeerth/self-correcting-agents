"""Critics: turn structured Violations into natural-language repair Feedback.

Domain-agnostic. ``TemplateCritic`` renders per-code templates (the real
critic); ``GenericCritic`` is the ablation control that gives one
untargeted nudge regardless of what went wrong.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from selfcorrect.types import Feedback, Severity, Violation

_DEFAULT_GENERIC_TEMPLATE = (
    "The field '{field}' failed validation: {message} "
    "(expected: {expected}, actual: {actual}). Fix this field and return the corrected JSON."
)

GENERIC_FEEDBACK_INSTRUCTION = (
    "The output failed validation. Please fix it and return the corrected JSON."
)


class _SafeContext(dict[str, str]):
    """``format_map`` context that leaves unknown placeholders intact instead of raising."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _render(template: str, violation: Violation) -> str:
    """Render a template against a violation; ``None`` expected/actual become '?'."""
    context = _SafeContext(
        field=violation.field,
        expected=violation.expected if violation.expected is not None else "?",
        actual=violation.actual if violation.actual is not None else "?",
        message=violation.message,
    )
    return template.format_map(context)


class TemplateCritic:
    """Maps each ERROR violation to targeted repair guidance via per-code templates.

    Unknown violation codes fall back to ``generic_template``; WARNING-severity
    violations produce no feedback.
    """

    def __init__(
        self,
        templates: Mapping[str, str],
        generic_template: str = _DEFAULT_GENERIC_TEMPLATE,
    ) -> None:
        self._templates: dict[str, str] = dict(templates)
        self._generic_template = generic_template

    def critique(
        self, output: dict[str, Any], violations: Sequence[Violation]
    ) -> list[Feedback]:
        """One Feedback per ERROR violation, in violation order."""
        feedback: list[Feedback] = []
        for violation in violations:
            if violation.severity is not Severity.ERROR:
                continue
            template = self._templates.get(violation.code, self._generic_template)
            feedback.append(
                Feedback(
                    violation_code=violation.code,
                    field=violation.field,
                    instruction=_render(template, violation),
                )
            )
        return feedback


class GenericCritic:
    """Ablation control: a single untargeted nudge whenever any ERROR exists."""

    def critique(
        self, output: dict[str, Any], violations: Sequence[Violation]
    ) -> list[Feedback]:
        """Exactly one generic Feedback if any ERROR violation exists, else []."""
        if any(v.severity is Severity.ERROR for v in violations):
            return [
                Feedback(
                    violation_code="GENERIC",
                    field="<root>",
                    instruction=GENERIC_FEEDBACK_INSTRUCTION,
                )
            ]
        return []
