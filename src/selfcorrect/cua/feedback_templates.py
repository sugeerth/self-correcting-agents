"""Per-violation-code repair templates for the computer-use domain.

Rendered by ``TemplateCritic`` with ``{field}``, ``{expected}``, ``{actual}``,
and ``{message}``. Each template says WHAT failed and HOW to steer the next
attempt — the same targeted-vs-generic contrast the other domains measure.
"""

from __future__ import annotations

TEMPLATES: dict[str, str] = {
    "MISSING_FIELD": (
        "Your output is missing '{field}'. Return JSON with 'task_id' (copied from the "
        "prompt) and 'actions' (the list of UI steps); every 'type' and 'select' action "
        "also needs a 'value' string."
    ),
    "WRONG_TYPE": (
        "The field '{field}' is malformed: expected {expected}, got {actual}. Each action "
        "is an object whose 'do' is 'type', 'click' or 'select', whose 'target' names an "
        "element, and whose 'value' (for type/select) is a plain string."
    ),
    "UNKNOWN_TASK": (
        "The task_id you returned ({actual}) does not match the prompt. Copy the task_id "
        "verbatim from the prompt into your output."
    ),
    "UNKNOWN_TARGET": (
        "No element '{actual}' exists on the current page — {message}. Check the spelling "
        "of the target and that the preceding actions actually navigate to the page "
        "that has it."
    ),
    "INVALID_ACTION": (
        "The verb does not fit the element: {message}. Use 'type' on text fields, "
        "'select' on the passengers dropdown, and 'click' on buttons and checkboxes."
    ),
    "PRECONDITION_FAILED": (
        "A button was clicked before it was ready: {message}. Fill in the required "
        "fields with 'type' actions BEFORE clicking that button."
    ),
    "NOT_COMPLETED": (
        "The action list ends on page '{actual}' without finishing the booking. Continue "
        "the flow — fill the search form, click 'search', choose a flight, type the "
        "traveler details, and click 'pay' — until the done page is reached."
    ),
    "WRONG_BOOKING": (
        "The booking completed, but '{field}' is wrong: expected {expected}, got {actual}. "
        "Re-read the goal and fix the action that sets '{field}' (the typed value, the "
        "selected option, or which button you click)."
    ),
}
