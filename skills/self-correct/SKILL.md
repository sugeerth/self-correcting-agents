---
name: self-correct
description: Wrap any structured-output task (data extraction, SQL/code generation, config/action synthesis) in a generate → validate → critique → repair loop with executable checks and bounded retries. Use when the user says /self-correct, asks to "make the output self-checking", wants validation-loop reliability on a generation task, or when a task has a checkable output contract (schema, tests, executable acceptance criteria).
---

# Self-Correct: generate → validate → critique → repair

Run the user's generation task inside a bounded repair loop where every retry is
driven by **executed checks** and **targeted, per-violation feedback**. Follow the
five phases below in order. Do not skip Phase 1 and do not reorder.

## Why this works (and what does not)

This protocol is the measured mechanic from the self-correcting-agents benchmark:

- Invoice extraction: 58.3% valid with no retries → **95.8%** with targeted feedback.
- Text-to-SQL: 25.0% → **91.7%** with targeted feedback.
- Ablation: a generic "please fix it" critic scored **58.3%** and **25.0%** —
  exactly identical to running no retries at all.

The targeted feedback IS the entire lift. Retries alone add nothing; retries with a
vague nudge add nothing. What repairs outputs is telling the generator precisely
WHAT is wrong, WHERE (a field path), and HOW to fix it, backed by expected/actual
values from an executed check. Every phase below exists to make that possible.

## Phase 1 — Derive the validator FIRST, before generating anything

Before producing a single line of output, write down the checks the output must
pass, and make each one **executable** — a command or script that returns
pass/fail with concrete values. Never a check that amounts to "reread the output
and judge it." Self-assessment is not validation.

Give every check three things:

1. A stable, SCREAMING_SNAKE **code** (e.g. `TOTAL_MISMATCH`, `TESTS_FAIL`,
   `MISSING_COLUMNS`). Codes must not change between attempts — they are the hook
   that links a failure to its repair instruction.
2. A **field path** locating the failure (`total`, `line_items[2].amount`,
   `tests/test_parser.py::test_empty`, `spec.containers[0].image`).
3. **Expected and actual** values, captured from the check's execution.

Pick checks from this menu by output type:

| Output type | Executable checks |
|---|---|
| JSON / structured data | Schema: required fields, types, enum membership. Cross-field invariants: sums, `subtotal + tax == total`, quantity × price == amount, date parseability, non-negative amounts. Run via a python script or `jq`. |
| SQL | Execute against the real database or a fixture copy. Assert: query runs without error, result columns match the requested names/order, row count is right, spot-check known values. |
| Code | Run the actual test suite (`pytest`, `npm test`), the typechecker (`mypy`, `tsc`), the linter. A test that exercises the new behavior beats all three. |
| Actions / configs | Dry-run or simulate (`kubectl apply --dry-run=server`, `terraform plan`, config-parse in a scratch process), then assert on the end state, not on the file looking plausible. |

Layer the checks: structural/schema checks first, then semantic invariants.
Semantic checks should skip when structural checks already failed for the same
field — one root cause, one violation, no noise cascade.

**The honesty rule (non-negotiable):** if NOTHING about the output can be checked
by executing something — no schema, no tests, no ground truth, no simulator —
say so explicitly, generate once, and stop. Do not run the loop and imply it
added reliability. A loop without an executable validator is theater.

## Phase 2 — Generate

Produce the candidate output normally, as you would without this skill. Do not
water down the attempt because a safety net exists, and do not show the validator
special deference in the output itself — generate to the task, not to the checks.

## Phase 3 — Validate by RUNNING the checks

Execute the Phase 1 checks with real tool calls — Bash, a python script, `jq`,
the test runner. Reading the output back and vibing that it looks right does not
count and is forbidden.

Collect every failure as a structured violation:

```json
{"code": "TOTAL_MISMATCH", "field": "total", "expected": "1085.00", "actual": "1130.00",
 "message": "total is 1130.00 but subtotal + tax = 1085.00"}
```

If there are zero error-level violations, the output is valid: present it and stop.

## Phase 4 — Critique: one targeted repair instruction per violation

For EACH violation, write one specific repair instruction that names WHAT is wrong,
WHERE it is (the field path), and HOW to fix it — including the expected and actual
values and, when you can infer it, the likely root cause. The generator on the next
attempt sees only these instructions, so they must carry everything needed to repair.

Good: `In line_items[2].amount, quantity × unit_price should equal 210.00 but the
extracted amount is 21.00 — a digit was likely dropped; re-read that row.`

Useless: `The output failed validation. Please fix it.` — this is the ablation arm
that measured exactly zero lift. If you catch yourself writing feedback without a
field path and expected/actual values, stop and rewrite it.

## Phase 5 — Repair, bounded

Regenerate with the targeted feedback appended to the original task, then return to
Phase 3. Keep the checks IDENTICAL across attempts. **Maximum 3 attempts total** by
default (the user may set another bound; honor it).

On exhaustion, fail LOUDLY:

1. Present the best attempt — the one with the fewest error-level violations,
   ties broken by the latest.
2. List its surviving violations, with codes and expected/actual values.
3. State plainly that it did NOT pass validation.

Never silently return a failing candidate as if it succeeded. A loud failure with a
diagnosis is a good outcome; a quiet bad answer is the worst one.

## Worked example — invoice-style JSON extraction

Task: extract `{vendor, subtotal, tax, total, line_items[]}` from an invoice.

**Phase 1 — checks** (written before generating):

| Code | Check (executed via python) | Field |
|---|---|---|
| `MISSING_FIELD` | all required keys present | each key |
| `LINE_ITEMS_SUM` | Σ line_items[i].amount == subtotal (±0.01) | `subtotal` |
| `TOTAL_MISMATCH` | subtotal + tax == total (±0.01) | `total` |

**Phase 2 — attempt 1** extracts `subtotal: 1000.00, tax: 85.00, total: 1130.00`.

**Phase 3 — run the checks:** two pass; one fails:

```json
{"code": "TOTAL_MISMATCH", "field": "total", "expected": "1085.00", "actual": "1130.00"}
```

**Phase 4 — targeted feedback:**

> The extracted total (1130.00) does not equal subtotal + tax (1085.00). Invoices
> often show several candidate amounts ('balance due', 'amount before discount',
> 'grand total') — re-read the document and pick the final payable total.

**Phase 5 — attempt 2** re-reads the document, finds 1130.00 was the pre-discount
figure, returns `total: 1085.00`. All three checks pass when re-run. Done in 2
attempts.

## Mini example — generated code, pytest as validator

Task: implement `slugify(text)` in a repo with a test suite.

1. **Checks first:** `TESTS_FAIL` = `python3 -m pytest tests/test_slugify.py -x -q`
   exits 0; `TYPE_ERROR` = `mypy src/` exits 0. If no test covers the new behavior,
   write one now — before the implementation.
2. Generate the implementation.
3. Run pytest: `FAILED tests/test_slugify.py::test_unicode - assert 'cafe' == 'café'`.
4. Targeted feedback: `TESTS_FAIL at tests/test_slugify.py::test_unicode — expected
   'cafe', got 'café': accented characters are not being transliterated to ASCII;
   apply NFKD normalization and drop combining marks before lowercasing.`
5. Repair, rerun pytest and mypy. Green on attempt 2 → present. If still red after
   attempt 3 → show the best diff, the failing test output, and say it did not pass.

## Anti-patterns — do not do these

- **The self-assessment "validator."** Asking the model (or yourself) "is this
  right?" is not a check. If it doesn't execute, it doesn't validate.
- **Unbounded retry.** Looping until it passes burns budget and hides systematic
  failure. Three attempts, then fail loudly with the evidence.
- **Feedback without field paths.** "Something's wrong with the totals" repairs
  nothing. Every instruction names a field, an expected value, and an actual value.
- **Mutating the checks to make them pass.** Weakening a tolerance, deleting a
  failing test, or dropping a check mid-loop is Goodharting the validator. The
  checks are frozen at Phase 1; if a check turns out to be genuinely wrong, say so
  to the user and restart the loop from Phase 1 with the corrected check.
- **Validating only the happy path.** A validator that never fires is
  indistinguishable from no validator. Include at least one cross-field or
  behavioral check, not just "is it JSON."

## Evidence

Benchmark code, both domains (invoices, text-to-SQL), the generic-critic ablation,
and full run traces: https://github.com/sugeerth/self-correcting-agents
