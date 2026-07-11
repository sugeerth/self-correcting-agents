# self-correcting-agents

[![CI](https://github.com/sugeerth/self-correcting-agents/actions/workflows/ci.yml/badge.svg)](https://github.com/sugeerth/self-correcting-agents/actions/workflows/ci.yml)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

Agents that catch and fix their own mistakes: a **generate → validate → critique → repair**
loop with zero runtime dependencies, demonstrated on structured invoice extraction.

📖 **Blog post:** [Self-Correcting Agents: Teaching an Agent to Catch and Fix Its Own Mistakes](https://sugeerth.github.io/self-correcting-agents/) ([markdown](docs/index.md))

```
 input ───────► [ GENERATE ] ───► candidate ───► [ VALIDATE ] ──ok──► output
                     ▲                                 │ fail
                     │                                 ▼
               repair prompt ◄──── [ CRITIQUE ] ◄── violations
               (bounded: max N attempts, then fail loudly with the best attempt)
```

## 60-second quickstart (free, no API keys)

```bash
git clone https://github.com/sugeerth/self-correcting-agents
cd self-correcting-agents
uv run python -m selfcorrect demo --task inv_004   # watch one invoice get caught and repaired
uv run python -m selfcorrect bench --ablation      # full benchmark -> bench_out/
```

The default engine is a **deterministic fault-injection simulation**: a flawed extractor
that makes realistic, feedback-addressable mistakes. It runs anywhere, costs nothing, and
is fully reproducible (seeded) — so the benchmark measures the *mechanics* of
self-correction, not any particular model's quality.

<details>
<summary><b>What the demo prints</b> — one invoice caught and repaired (click to expand)</summary>

```text
Task: inv_004
────────────────────────────────────────────────────────────────────────
Attempt 1/2 — engine: simulated
  ...
  CODE           │ FIELD    │ EXPECTED -> ACTUAL
  ───────────────┼──────────┼───────────────────
  LINE_ITEMS_SUM │ subtotal │ 31438.02 -> 17427.84
  TOTAL_MISMATCH │ total    │ 37725.62 -> 700.26
  Feedback to agent:
    • Line item amounts sum to 17427.84 but the stated subtotal is 31438.02. You likely
      missed a line item or misread one amount — re-scan the items section...
    • The extracted total (700.26) does not equal subtotal + tax (37725.62). Invoices
      often show several candidate amounts... pick the final payable total.
────────────────────────────────────────────────────────────────────────
Attempt 2/2 — engine: simulated
  ...
  violations: none
────────────────────────────────────────────────────────────────────────
VALID after 2 attempt(s)
```

The other path matters too: `--task inv_021` draws an *unfixable* fault plan and shows
the loop failing loudly after 3 bounded attempts with its best attempt attached — no
infinite retries, no silent bad output.

</details>

## What the loop buys you

24-invoice corpus, seed 42, max 3 attempts — **simulated engine** (see disclaimer above):

| configuration | fully valid | mean attempts |
|---|---:|---:|
| self-correction OFF | 58.3% | 1.00 |
| self-correction ON (targeted critic) | **95.8%** | 1.50 |
| ablation: generic "please fix it" critic | 58.3% | 1.83 |

The ablation is the headline: the same retry budget with *untargeted* feedback fixes
nothing — the lift comes from structured violations rendered into specific repair
instructions, not from retrying harder. Full tables: run the bench, or see the
[blog post](https://sugeerth.github.io/self-correcting-agents/).

![attempts histogram](bench_out/attempts.svg)

## Architecture

| piece | file | job |
|---|---|---|
| `Engine` | `src/selfcorrect/engines/` | produce a candidate, given the task + prior feedback |
| `Validator` | `src/selfcorrect/validators.py`, `invoices/rules.py` | deterministic checks → structured `Violation`s (Decimal money math, schema, business rules) |
| `Critic` | `src/selfcorrect/critic.py` | violations → targeted natural-language repair instructions (rule-based templates by default) |
| loop | `src/selfcorrect/loop.py` | bounded retry orchestration + full per-attempt trace |
| bench | `src/selfcorrect/bench.py` | OFF vs ON vs ablation; results.json / results.md / SVG |

The core (`types`, `loop`, `validators`, `critic`, `engines/simulated`) is **domain-agnostic**;
everything invoice-specific lives in `selfcorrect/invoices/` as a plug-in (schema, business
rules, feedback templates, error catalog, corpus). Tests enforce the boundary.

## Proof it generalizes: a second domain

"The core is domain-agnostic" is only a claim until a second domain runs through it
untouched. `selfcorrect/sqlq/` is **text-to-SQL** over a fixture sqlite database
(stdlib only): the validator executes the candidate query and checks it against
per-task acceptance criteria — expected columns, row count, and a result checksum —
derived once from the gold queries, so in-loop validation verifies without ever
seeing the answer.

```bash
uv run python -m selfcorrect demo  --domain sqlq          # watch a query get repaired
uv run python -m selfcorrect bench --domain sqlq --ablation --out bench_out_sqlq
```

12 queries, seed 42, max 3 attempts — simulated engine, same disclaimer as above:

| configuration | fully valid | mean attempts |
|---|---:|---:|
| self-correction OFF | 25.0% | 1.00 |
| self-correction ON (targeted critic) | **91.7%** | 1.92 |
| ablation: generic "please fix it" critic | 25.0% | 2.50 |

Same shape as the invoice result, new domain, zero changes to the loop, CLI, or
benchmark: the generic critic exactly matches OFF — the lift is targeted feedback,
not retries. (The one ON failure is a two-error task whose deterministic repair
roll misses — bounded failure, reported loudly.) Full tables: `bench_out_sqlq/`.

## Engines

| engine | cost | needs | use |
|---|---|---|---|
| `simulated` (default) | $0 | nothing | CI, reproducible benchmarks, demos |
| `hermes` | $0 | [Ollama](https://ollama.com) + `ollama pull hermes3` | real local LLM (NousResearch Hermes 3 8B) |
| `anthropic` | API usage | `pip install "selfcorrect[anthropic]"` + `ANTHROPIC_API_KEY` | Claude — worker `claude-opus-4-8`, critic `claude-haiku-4-5` |

### Hermes (free local model)

```bash
# one-time: install Ollama from https://ollama.com, then
ollama pull hermes3
uv run python -m selfcorrect demo --engine hermes --task inv_004
uv run python -m selfcorrect bench --engine hermes
```

Hermes 3 is structured-output trained; the engine constrains generation with a JSON
schema via Ollama's `format` parameter and talks to `localhost:11434` using only the
standard library.

### Claude (Anthropic API)

```python
from selfcorrect import SelfCorrectingAgent
from selfcorrect.engines import get_engine
from selfcorrect.invoices import build_critic, build_validator, load_tasks

agent = SelfCorrectingAgent(
    engine=get_engine("anthropic"),  # claude-opus-4-8 via structured outputs
    validator=build_validator(),
    critic=build_critic(),
    max_attempts=3,
)
result = agent.run(load_tasks()[3])
```

## Repository layout

```
src/selfcorrect/        the framework (zero runtime dependencies)
  engines/              simulated | hermes (Ollama) | anthropic (optional extra)
  invoices/             flagship domain plug-in: schema, rules, templates, corpus, catalog
  sqlq/                 second domain plug-in: text-to-SQL over a fixture sqlite DB
tests/                  92 tests: unit, determinism, e2e lift bounds, import-boundary
examples/run_demo.py    scripted walkthrough
docs/                   the blog post (GitHub Pages)
```

## Development

```bash
uv sync --dev
uv run pytest -q          # 92 tests, no network
uv run ruff check src tests examples
```

## License

MIT — see [LICENSE](LICENSE).
