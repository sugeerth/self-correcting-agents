"""Generic, domain-agnostic validators and numeric parsing helpers.

Nothing here knows about invoices; domain packages compose these
building blocks into full validation stacks.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from selfcorrect.types import Validator, Violation

TypeSpec = type | tuple[type, ...]


def as_decimal(x: object) -> Decimal | None:
    """Parse a value as ``Decimal(str(x))``.

    Returns None for None, bool (a subclass of int, never a number here),
    unparseable values, and non-finite results (NaN/Infinity).
    """
    if x is None or isinstance(x, bool):
        return None
    try:
        value = Decimal(str(x))
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def type_name(spec: TypeSpec) -> str:
    """Human-readable name for a type spec, e.g. ``'int|float'``."""
    if isinstance(spec, tuple):
        return "|".join(t.__name__ for t in spec)
    return spec.__name__


def type_matches(value: object, spec: TypeSpec) -> bool:
    """``isinstance`` with the bool trap closed: bool only matches an explicit bool spec."""
    allowed = spec if isinstance(spec, tuple) else (spec,)
    if isinstance(value, bool):
        return bool in allowed
    return isinstance(value, allowed)


class CompositeValidator:
    """Runs child validators in order and concatenates their violations."""

    def __init__(self, validators: Sequence[Validator], name: str = "composite") -> None:
        self.name = name
        self._validators: tuple[Validator, ...] = tuple(validators)

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations: list[Violation] = []
        for validator in self._validators:
            violations.extend(validator.validate(output))
        return violations


class RequiredFieldsValidator:
    """Checks that required top-level fields are present with the right types.

    Emits MISSING_FIELD for absent keys and WRONG_TYPE on mismatches.
    bool never satisfies a numeric type spec unless bool is listed explicitly.
    """

    def __init__(self, fields: dict[str, TypeSpec], name: str = "required_fields") -> None:
        self.name = name
        self._fields = dict(fields)

    def validate(self, output: dict[str, Any]) -> list[Violation]:
        violations: list[Violation] = []
        for key, spec in self._fields.items():
            expected = type_name(spec)
            if key not in output:
                violations.append(
                    Violation(
                        code="MISSING_FIELD",
                        field=key,
                        message=f"Required field '{key}' is missing.",
                        expected=expected,
                        actual=None,
                    )
                )
            elif not type_matches(output[key], spec):
                actual = type(output[key]).__name__
                violations.append(
                    Violation(
                        code="WRONG_TYPE",
                        field=key,
                        message=f"Field '{key}' should be {expected}, got {actual}.",
                        expected=expected,
                        actual=actual,
                    )
                )
        return violations
