"""Per-violation-code repair templates for invoice extraction.

Each template is rendered by ``TemplateCritic`` with the placeholders
``{field}``, ``{expected}``, ``{actual}``, and ``{message}`` (``None``
values render as '?'). The text is what the engine reads on retry, so
every template explains both WHAT is wrong and HOW to find the fix in
the source document.
"""

from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "MISSING_FIELD": (
        "The required field '{field}' is missing from your output. Re-read the document "
        "and extract it ({expected}). Invoices label things inconsistently — check synonyms "
        "like 'invoice no.', 'bill date', or 'amount due' before concluding it is absent."
    ),
    "WRONG_TYPE": (
        "The field '{field}' has the wrong type: expected {expected} but got {actual}. "
        "Return it as the correct JSON type — numbers must be bare numerals with no currency "
        "symbols, thousands separators, or quotes, and never booleans."
    ),
    "EMPTY_LINE_ITEMS": (
        "'{field}' is empty, but every invoice bills at least one row. Re-scan the items "
        "table between the header and the totals section and extract every row with its "
        "description, quantity, unit_price, and amount."
    ),
    "DATE_UNPARSEABLE": (
        "The value of '{field}' ({actual}) is not a parseable date. Re-read the document and "
        "return it as {expected} (ISO YYYY-MM-DD). Watch for ambiguous day/month order and "
        "spelled-out months like '3rd Mar 2024'."
    ),
    "CURRENCY_INVALID": (
        "The currency in '{field}' ({actual}) is not a valid code. Return {expected} — a "
        "three-letter uppercase ISO 4217 code. Map symbols: '$' -> 'USD', '€' -> 'EUR', "
        "'£' -> 'GBP'."
    ),
    "NEGATIVE_AMOUNT": (
        "The field '{field}' is negative ({actual}), but invoice amounts must be "
        "non-negative. You may have misread a discount, credit memo, or a parenthesized "
        "number — re-read that figure and extract the actual charged amount."
    ),
    "LINE_ITEM_MATH": (
        "In '{field}', quantity × unit_price should equal {expected} but the extracted "
        "amount is {actual}. Re-read that row — a digit was likely misread, or unit_price "
        "and amount were swapped."
    ),
    "LINE_ITEMS_SUM": (
        "Line item amounts sum to {actual} but the stated subtotal is {expected}. You likely "
        "missed a line item or misread one amount — re-scan the items section and extract "
        "every row."
    ),
    "TOTAL_MISMATCH": (
        "The extracted total ({actual}) does not equal subtotal + tax ({expected}). Invoices "
        "often show several candidate amounts ('balance due', 'amount before discount', "
        "'grand total') — re-read the document and pick the final payable total."
    ),
    "GENERATION_FAILED": (
        "The previous attempt produced no usable output for '{field}' ({message}). Return "
        "ONLY one valid JSON object matching the invoice schema — no prose, no markdown "
        "fences, no trailing commas."
    ),
}
