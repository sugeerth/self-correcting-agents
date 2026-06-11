"""Tests for TemplateCritic / GenericCritic and the invoice feedback templates."""

from __future__ import annotations

from selfcorrect.critic import GENERIC_FEEDBACK_INSTRUCTION, GenericCritic, TemplateCritic
from selfcorrect.invoices.feedback_templates import TEMPLATES
from selfcorrect.types import Severity, Violation

EXPECTED_CODES = {
    "MISSING_FIELD",
    "WRONG_TYPE",
    "EMPTY_LINE_ITEMS",
    "DATE_UNPARSEABLE",
    "CURRENCY_INVALID",
    "NEGATIVE_AMOUNT",
    "LINE_ITEM_MATH",
    "LINE_ITEMS_SUM",
    "TOTAL_MISMATCH",
    "GENERATION_FAILED",
}


def _violation(**overrides: object) -> Violation:
    base: dict[str, object] = {
        "code": "TOTAL_MISMATCH",
        "field": "total",
        "message": "total != subtotal + tax",
        "severity": Severity.ERROR,
        "expected": "108.00",
        "actual": "110.00",
    }
    base.update(overrides)
    return Violation(**base)  # type: ignore[arg-type]


class TestInvoiceTemplates:
    def test_all_expected_codes_have_templates(self) -> None:
        missing = EXPECTED_CODES - set(TEMPLATES)
        assert not missing, f"feedback_templates.TEMPLATES missing codes: {sorted(missing)}"

    def test_templates_are_nonempty_strings(self) -> None:
        for code in sorted(EXPECTED_CODES):
            assert isinstance(TEMPLATES[code], str) and TEMPLATES[code].strip()

    def test_every_template_renders_with_none_expected_actual(self) -> None:
        critic = TemplateCritic(TEMPLATES)
        for code in sorted(TEMPLATES):
            violations = [
                _violation(code=code, field="some.field", expected=None, actual=None)
            ]
            feedback = critic.critique({}, violations)
            assert len(feedback) == 1
            assert feedback[0].instruction  # rendered, did not raise


class TestTemplateCritic:
    def test_rendered_instruction_contains_expected_and_actual(self) -> None:
        critic = TemplateCritic(TEMPLATES)
        violations = [_violation(code="TOTAL_MISMATCH", expected="108.00", actual="110.00")]
        [feedback] = critic.critique({"total": 110.0}, violations)
        assert feedback.violation_code == "TOTAL_MISMATCH"
        assert feedback.field == "total"
        assert "108.00" in feedback.instruction
        assert "110.00" in feedback.instruction

    def test_line_items_sum_contains_figures(self) -> None:
        critic = TemplateCritic(TEMPLATES)
        violations = [
            _violation(
                code="LINE_ITEMS_SUM", field="subtotal", expected="450.00", actual="300.00"
            )
        ]
        [feedback] = critic.critique({}, violations)
        assert "450.00" in feedback.instruction
        assert "300.00" in feedback.instruction

    def test_none_values_render_as_question_mark(self) -> None:
        critic = TemplateCritic({"X": "expected={expected} actual={actual}"})
        [feedback] = critic.critique({}, [_violation(code="X", expected=None, actual=None)])
        assert feedback.instruction == "expected=? actual=?"

    def test_unknown_code_falls_back_to_generic_template(self) -> None:
        critic = TemplateCritic(TEMPLATES, generic_template="generic fix for {field}")
        violations = [_violation(code="NOT_A_REAL_CODE", field="weird.field")]
        [feedback] = critic.critique({}, violations)
        assert feedback.violation_code == "NOT_A_REAL_CODE"
        assert feedback.instruction == "generic fix for weird.field"

    def test_unknown_placeholder_keys_do_not_raise(self) -> None:
        critic = TemplateCritic({"X": "field={field} mystery={no_such_key}"})
        [feedback] = critic.critique({}, [_violation(code="X", field="f")])
        assert "field=f" in feedback.instruction
        assert "{no_such_key}" in feedback.instruction

    def test_warnings_produce_no_feedback(self) -> None:
        critic = TemplateCritic(TEMPLATES)
        violations = [_violation(severity=Severity.WARNING)]
        assert critic.critique({}, violations) == []

    def test_no_violations_produce_no_feedback(self) -> None:
        assert TemplateCritic(TEMPLATES).critique({}, []) == []

    def test_feedback_order_matches_violation_order(self) -> None:
        critic = TemplateCritic(TEMPLATES)
        violations = [
            _violation(code="MISSING_FIELD", field="invoice_number"),
            _violation(severity=Severity.WARNING, field="skipped"),
            _violation(code="NEGATIVE_AMOUNT", field="tax"),
        ]
        feedback = critic.critique({}, violations)
        assert [f.violation_code for f in feedback] == ["MISSING_FIELD", "NEGATIVE_AMOUNT"]
        assert [f.field for f in feedback] == ["invoice_number", "tax"]


class TestGenericCritic:
    def test_emits_exactly_one_generic_feedback_on_errors(self) -> None:
        critic = GenericCritic()
        violations = [
            _violation(code="TOTAL_MISMATCH"),
            _violation(code="MISSING_FIELD", field="invoice_number"),
        ]
        feedback = critic.critique({}, violations)
        assert len(feedback) == 1
        assert feedback[0].violation_code == "GENERIC"
        assert feedback[0].field == "<root>"
        assert feedback[0].instruction == GENERIC_FEEDBACK_INSTRUCTION
        assert feedback[0].instruction == (
            "The output failed validation. Please fix it and return the corrected JSON."
        )

    def test_warnings_only_produce_no_feedback(self) -> None:
        critic = GenericCritic()
        violations = [_violation(severity=Severity.WARNING)]
        assert critic.critique({}, violations) == []

    def test_no_violations_produce_no_feedback(self) -> None:
        assert GenericCritic().critique({}, []) == []
