"""Prompt construction for the invoice-extraction LLM engines (Hermes, Anthropic).

Stdlib-only. The JSON schema here is the single source of truth for what an
extraction must look like on the wire; engines pass it to their respective
structured-output mechanisms.
"""

from __future__ import annotations

from typing import Any

from selfcorrect.types import Task

#: JSON Schema for one extracted invoice. All fields required; no extras allowed.
INVOICE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "date": {"type": "string"},
        "currency": {"type": "string"},
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "quantity": {"type": "number"},
                    "unit_price": {"type": "number"},
                    "amount": {"type": "number"},
                },
                "required": ["description", "quantity", "unit_price", "amount"],
                "additionalProperties": False,
            },
        },
        "subtotal": {"type": "number"},
        "tax": {"type": "number"},
        "total": {"type": "number"},
    },
    "required": ["vendor", "date", "currency", "line_items", "subtotal", "tax", "total"],
    "additionalProperties": False,
}


def build_system_prompt() -> str:
    """Expert invoice-extraction instructions shared by all LLM engines."""
    return (
        "You are an expert invoice-extraction system. Read the invoice document the "
        "user provides and extract EXACTLY these fields as a single JSON object: "
        "vendor, date, currency, line_items (each with description, quantity, "
        "unit_price, amount), subtotal, tax, total.\n"
        "Rules:\n"
        "- date MUST be an ISO 8601 calendar date: YYYY-MM-DD.\n"
        "- currency MUST be a 3-letter ISO 4217 code (e.g. USD, EUR, GBP).\n"
        "- quantities and all monetary values are plain JSON numbers - never strings, "
        "never currency symbols, never thousands separators.\n"
        "- Include EVERY line item that appears in the document, in document order.\n"
        "- total is the final payable amount of the invoice.\n"
        "- Output the JSON object only: no prose, no markdown fences, no comments."
    )


def build_user_prompt(task: Task) -> str:
    """The raw document wrapped in unambiguous delimiters."""
    return (
        "Extract the invoice fields from the document between the markers below.\n\n"
        "<<<INVOICE_DOCUMENT\n"
        f"{task.prompt}\n"
        "INVOICE_DOCUMENT>>>\n\n"
        "Return the JSON object only."
    )


def build_repair_prompt(prior_output_json: str, instructions: list[str]) -> str:
    """A repair turn: numbered critic instructions plus the prior JSON to correct."""
    numbered = "\n".join(f"{i}. {text}" for i, text in enumerate(instructions, start=1))
    return (
        "Your previous extraction had these problems:\n"
        f"{numbered}\n\n"
        "Here is your previous JSON:\n"
        f"{prior_output_json}\n\n"
        "Return the corrected COMPLETE JSON object only."
    )
