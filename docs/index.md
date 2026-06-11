---
layout: default
title: "Self-Correcting Agents: Teaching an Agent to Catch and Fix Its Own Mistakes"
description: "A generate → validate → critique → repair loop, benchmarked on invoice extraction — runs entirely free, no API keys."
---

*June 2026 · [source code on GitHub](https://github.com/sugeerth/self-correcting-agents) · everything below runs locally for $0.00*

## The problem: LLM outputs fail silently

When you put an LLM extraction step into a production pipeline, the failure mode is rarely a crash. It's a **plausible-looking wrong answer**: a JSON object with the right shape, the right field names — and a total that's actually the "amount before discount", a line item silently dropped, a European date parsed backwards. Nothing throws. The bad record flows into your ERP, your dashboard, your payment run, and you find out weeks later from an angry reconciliation report.

The standard answer is "add retries". But a naive retry re-rolls the dice with no new information. The agent that produced the wrong total doesn't know it produced the wrong total — so it usually produces it again.

**Self-correction** closes that gap: validate the output mechanically, turn each failure into *targeted* feedback, and let the agent repair its own answer — with a bounded number of attempts, so failure is loud instead of silent.

## The loop: generate → validate → critique → repair

[`selfcorrect`](https://github.com/sugeerth/self-correcting-agents) is a small, zero-dependency Python framework that implements exactly this loop:

```
 input ───────► [ GENERATE ] ───► candidate ───► [ VALIDATE ] ──ok──► output
                     ▲                                 │ fail
                     │                                 ▼
               repair prompt ◄──── [ CRITIQUE ] ◄── violations
               (bounded: max N attempts, then fail loudly with the best attempt)
```

Each stage maps to one small abstraction:

- **Engine** generates a candidate (`generate(task, feedback_history)`). Three implementations ship: a deterministic simulated engine, a free local LLM (Hermes 3 via Ollama), and Claude via the Anthropic API.
- **Validator** checks the candidate *deterministically* — schema, types, and business rules like "line items must sum to the subtotal" and "subtotal + tax must equal the total" (all money math in `Decimal`, never floats). It emits structured violations: code, field, expected, actual.
- **Critic** turns violations into natural-language repair instructions. The default critic is **rule-based** — a template per violation code. No second LLM call needed.
- **The loop** wires them together, records a full per-attempt trace, and stops at `max_attempts`.

A deliberate design boundary: the engine never sees raw violations, only the critic's feedback. Validation stays mechanical; communication with the model stays in one place.

## Use case: invoice extraction

Here is one of the harder documents in the benchmark corpus — a forwarded email with quoted-line noise, an EU-format date, and two **decoy amounts** that aren't the total:

```
> Invoice no: INV/838/2025
> Date: 2.2.2025
> All amounts in EUR.
>
> 6 x Industrial shelving unit, 5-tier @ 2335.03 EUR = 14010.18 EUR
> 12 x Safety goggles, anti-fog, 10-pack @ 1199.85 EUR = 14398.20 EUR
> 11 x Cat6 patch cable, 10m @ 63.66 EUR = 700.26 EUR
> 2 x Server rack rental, per month @ 1164.69 EUR = 2329.38 EUR
>
> Suggested deposit for next order: 4841.33 EUR
> Estimated annual spend: 5881.83 EUR
> Subtotal: 31438.02 EUR
> Tax @ 20%: 6287.60 EUR
> Balance due: 37725.62 EUR
```

**Attempt 1** drops the first line item and grabs a line amount as the total:

```json
{
  "vendor": "COPPERFIELD STATIONERS",
  "date": "2025-02-02",
  "currency": "EUR",
  "line_items": [
    {"description": "Safety goggles, anti-fog, 10-pack", "quantity": 12, "unit_price": 1199.85, "amount": 14398.20},
    {"description": "Cat6 patch cable, 10m",             "quantity": 11, "unit_price": 63.66,   "amount": 700.26},
    {"description": "Server rack rental, per month",     "quantity": 2,  "unit_price": 1164.69, "amount": 2329.38}
  ],
  "subtotal": 31438.02, "tax": 6287.60, "total": 700.26
}
```

This is the silent killer: perfectly shaped JSON, two materially wrong values. The validator catches both:

```
LINE_ITEMS_SUM   subtotal   expected 31438.02   actual 17427.84
TOTAL_MISMATCH   total      expected 37725.62   actual   700.26
```

The critic renders them as targeted feedback:

> Line item amounts sum to 17427.84 but the stated subtotal is 31438.02. You likely
> missed a line item or misread one amount — re-scan the items section and extract
> every row.
>
> The extracted total (700.26) does not equal subtotal + tax (37725.62). Invoices
> often show several candidate amounts ('balance due', 'amount before discount',
> 'grand total') — re-read the document and pick the final payable total.

**Attempt 2** restores the missing shelving line item and picks `37725.62` — every validator passes, and the loop returns a verified result. Try it yourself (free, no keys):

```
git clone https://github.com/sugeerth/self-correcting-agents && cd self-correcting-agents
uv run python -m selfcorrect demo --task inv_004
```

## Benchmark: does the loop actually pay for itself?

The repo ships a 24-invoice corpus (messy layouts, four date formats, decoy figures, OCR-ish noise) with exact ground truth, and a benchmark that runs three configurations: self-correction **OFF** (one attempt), **ON** (up to three attempts, targeted critic), and an ablation with a **generic critic** that only ever says *"the output failed validation, please fix it."*

> **Honest labeling:** the numbers below come from the repo's **deterministic fault-injection simulation** — a flawed-extractor engine that injects realistic, feedback-addressable errors. They measure the *mechanics* of self-correction (does targeted feedback convert retries into fixes?), reproducibly and for free — **not** the quality of any particular model. Re-run them with a real model via `--engine hermes` (free, local) and the same harness. Reproduce with: `uv run python -m selfcorrect bench --ablation`, seed 42.

| configuration | fully valid | mean attempts |
|---|---:|---:|
| self-correction OFF | 58.3% | 1.00 |
| self-correction ON (targeted critic) | **95.8%** | 1.50 |
| ablation: generic critic | 58.3% | 1.83 |

| attempts to converge | 1 | 2 | 3 | failed |
|---|---:|---:|---:|---:|
| ON (targeted critic) | 14 | 8 | 1 | 1 |

Three things worth noticing:

1. **The lift comes from the feedback, not the retries.** The generic-critic ablation gets the *same retry budget* and ends up exactly where single-shot started — 58.3% — while burning 1.8× the attempts. Retrying without telling the agent *what was wrong* is just paying more for the same answer.
2. **It doesn't reach 100%, and that's the honest part.** One task stays broken after three attempts: the loop fails *loudly*, returning its best attempt with the violations attached, ready for a human queue. That is the correct production behavior — bounded attempts, explicit failure.
3. **Validators can't see everything.** Field-level accuracy stays below validity even when everything "passes": a swapped day/month that lands on a real date sails through every arithmetic check. Self-correction raises the floor; it is not a substitute for ground-truth evaluation.

## Design decisions

**Rule-based critic before LLM critic.** Most extraction failures are *structural* — sums, types, formats — and a template keyed on the violation code produces better repair instructions than a second model call, for free, deterministically. An LLM critic earns its cost only for semantic failures that rules can't articulate. The framework supports both; start with rules.

**Bounded attempts, loud failure.** Repair yield decays fast — most fixes land on the first retry (8 of 10 here), a trickle on the second. `max_attempts=3` captures nearly all the value; beyond that you're paying latency for noise. When the budget runs out, return the best attempt *with its violations* — never silently ship it.

**When self-correction is NOT worth it:** open-ended generation with no checkable invariants (nothing to validate means nothing to critique); latency-critical paths that can't absorb a retry; and cases where the validator could just *fix* the output deterministically — if you can compute the correct total, write it, don't ask the model to.

## Plugging in real models

Everything above is engine-swappable. **Hermes 3 (free, local)** — install [Ollama](https://ollama.com), `ollama pull hermes3`, then:

```
uv run python -m selfcorrect bench --engine hermes
```

**Claude (Anthropic API)** — worker + cheap critic, behind an optional extra:

```python
from selfcorrect import SelfCorrectingAgent
from selfcorrect.engines import get_engine
from selfcorrect.invoices import build_critic, build_validator

agent = SelfCorrectingAgent(
    engine=get_engine("anthropic"),   # worker: claude-opus-4-8 (structured outputs)
    validator=build_validator(),      # critic rewriting available via claude-haiku-4-5
    critic=build_critic(),
    max_attempts=3,
)
```

(`pip install "selfcorrect[anthropic]"` and set `ANTHROPIC_API_KEY`.)

The validators, critic templates, corpus, benchmark, and trace tooling are identical across engines — which is the point. The loop is the infrastructure; the model is a plug-in.

---

*Code, corpus, benchmark, and tests: [github.com/sugeerth/self-correcting-agents](https://github.com/sugeerth/self-correcting-agents). MIT licensed. Issues and PRs welcome.*
