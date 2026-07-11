"""Export recorded self-correction runs for the in-browser demo.

Runs the real SelfCorrectingAgent (simulated engine, seed 42, max_attempts 3)
over every task in each requested domain and writes the full traces to
``docs/demo_data.js`` as ``window.DEMO_DATA = {...};`` — a plain JS file so
the demo page works from both file:// and GitHub Pages without fetch/CORS.

Usage:
    uv run python tools/export_demo_traces.py            # all registered domains
    uv run python tools/export_demo_traces.py invoices   # a subset

The script is domain-agnostic: it iterates ``selfcorrect.domains.DOMAIN_NAMES``
(or the names passed on argv) and knows nothing about any specific domain, so
re-running it picks up newly registered domains automatically.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from selfcorrect.domains import DOMAIN_NAMES, get_domain
from selfcorrect.loop import SelfCorrectingAgent
from selfcorrect.types import Attempt, RunResult

SEED = 42
MAX_ATTEMPTS = 3
PROMPT_MAX_CHARS = 500
OUTPUT_MAX_CHARS = 1200
OUT_PATH = Path(__file__).resolve().parent.parent / "docs" / "demo_data.js"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [truncated at {limit} chars]"


def _render_output(output: dict[str, Any] | None) -> str | None:
    """Pretty-print a candidate output, truncated to what the UI shows."""
    if output is None:
        return None
    rendered = json.dumps(output, indent=2, ensure_ascii=False, default=str)
    return _truncate(rendered, OUTPUT_MAX_CHARS)


def _export_attempt(attempt: Attempt) -> dict[str, Any]:
    return {
        "index": attempt.index,
        "valid": attempt.is_valid,
        "output": _render_output(attempt.output),
        "violations": [
            {
                "code": v.code,
                "field": v.field,
                "message": v.message,
                "expected": v.expected,
                "actual": v.actual,
            }
            for v in attempt.violations
        ],
        "feedback": [f.instruction for f in attempt.feedback],
    }


def _export_run(prompt: str, result: RunResult) -> dict[str, Any]:
    return {
        "id": result.task_id,
        "prompt": _truncate(prompt, PROMPT_MAX_CHARS),
        "success": result.success,
        "attempts": [_export_attempt(a) for a in result.attempts],
    }


def export_domain(name: str) -> dict[str, Any]:
    """Run the loop over every task in one domain and collect the traces."""
    domain = get_domain(name)
    agent = SelfCorrectingAgent(
        engine=domain.build_simulated_engine(SEED),
        validator=domain.build_validator(),
        critic=domain.build_critic(),
        max_attempts=MAX_ATTEMPTS,
    )
    tasks = domain.load_tasks()
    runs = [_export_run(task.prompt, agent.run(task)) for task in tasks]
    repaired = sum(1 for r in runs if r["success"] and len(r["attempts"]) > 1)
    print(
        f"  {name}: {len(runs)} tasks, "
        f"{sum(1 for r in runs if r['success'])} succeeded ({repaired} via repair)"
    )
    return {"name": domain.name, "title": domain.title, "tasks": runs}


def main(argv: list[str]) -> None:
    names = argv or list(DOMAIN_NAMES)
    print(f"Exporting demo traces (seed={SEED}, max_attempts={MAX_ATTEMPTS}) …")
    data = {
        "generated_with": {"seed": SEED, "max_attempts": MAX_ATTEMPTS, "engine": "simulated"},
        "domains": [export_domain(name) for name in names],
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    OUT_PATH.write_text(f"window.DEMO_DATA = {payload};\n", encoding="utf-8")
    print(f"Wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main(sys.argv[1:])
