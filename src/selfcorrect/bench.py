"""Benchmark: self-correction OFF vs ON (vs a generic-critic ablation).

Runs the selected domain's full corpus through the loop under each
configuration and reports validity, field accuracy against ground truth,
attempt histograms, latency, and cost. Artifacts (results.json, results.md,
attempts.svg, traces.jsonl) land in ``BenchConfig.out_dir``. Everything is a
pure function of the config, so identical configs produce identical payloads
and traces. What "field accuracy" means is domain knowledge and comes from
the ``Domain`` plug-in (see selfcorrect.domains).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from selfcorrect.critic import GenericCritic
from selfcorrect.domains import Domain, get_domain
from selfcorrect.engines import get_engine
from selfcorrect.loop import SelfCorrectingAgent
from selfcorrect.trace import TraceWriter
from selfcorrect.types import Critic, Engine, RunResult, Task, Validator

_SVG_COLORS = ("#4c78a8", "#f58518", "#54a24b")


@dataclass
class BenchConfig:
    """Knobs for one benchmark invocation."""

    seed: int = 42
    max_attempts: int = 3
    ablation: bool = False
    out_dir: Path = Path("bench_out")
    engine: str = "simulated"
    domain: str = "invoices"


# ---------------------------------------------------------------- one config


def _histogram(results: list[RunResult], buckets: list[str]) -> dict[str, int]:
    counts = {bucket: 0 for bucket in buckets}
    for result in results:
        counts[str(result.num_attempts) if result.success else "failed"] += 1
    return counts


def _aggregate_accuracy(
    rows: list[dict[str, Any]], field_names: tuple[str, ...]
) -> dict[str, float]:
    per_field = {
        name: sum(row["field_accuracy"][name] for row in rows) / len(rows) for name in field_names
    }
    per_field["macro_avg"] = sum(per_field[name] for name in field_names) / len(field_names)
    return per_field


def _run_configuration(
    name: str,
    engine: Engine,
    validator: Validator,
    critic: Critic,
    tasks: list[Task],
    ground_truth: dict[str, dict[str, Any]],
    field_names: tuple[str, ...],
    field_accuracy: Callable[[dict[str, Any] | None, dict[str, Any]], dict[str, float]],
    max_attempts: int,
    buckets: list[str],
    traces: TraceWriter,
) -> dict[str, Any]:
    """Run every task once under one configuration and aggregate the metrics."""
    agent = SelfCorrectingAgent(engine, validator, critic, max_attempts=max_attempts)
    results: list[RunResult] = []
    rows: list[dict[str, Any]] = []
    for task in tasks:
        result = agent.run(task)
        traces.write(result)
        results.append(result)
        rows.append(
            {
                "task_id": task.id,
                "success": result.success,
                "num_attempts": result.num_attempts,
                "field_accuracy": field_accuracy(result.final_output, ground_truth[task.id]),
                "latency_s": result.total_latency_s,
                "cost_usd": result.total_cost_usd,
            }
        )
    n = len(results)
    metrics = {
        "fully_valid_rate": sum(r.success for r in results) / n,
        "field_accuracy": _aggregate_accuracy(rows, field_names),
        "attempts_histogram": _histogram(results, buckets),
        "mean_attempts": sum(r.num_attempts for r in results) / n,
        "total_latency_s": sum(r.total_latency_s for r in results),
        "total_cost_usd": sum(r.total_cost_usd for r in results),
    }
    return {"name": name, "max_attempts": max_attempts, "metrics": metrics, "tasks": rows}


# ---------------------------------------------------------------- artifacts


def _render_markdown(payload: dict[str, Any]) -> str:
    engine = payload["engine_name"]
    if payload["simulated"]:
        disclaimer = (
            f"**All numbers below come from the `{engine}` engine — a deterministic "
            "fault-injection simulation, not a live LLM.**"
        )
    else:
        disclaimer = f"**All numbers below come from live `{engine}` runs.**"
    configs = payload["configurations"]
    lines = [
        f"# Self-correction benchmark — {payload['domain_title']}",
        "",
        disclaimer,
        "",
        f"Corpus: {payload['num_tasks']} {payload['domain_unit']} · "
        f"seed {payload['config']['seed']} · "
        f"max attempts {payload['config']['max_attempts']}",
        "",
        "## Summary",
        "",
        "| configuration | fully valid | mean attempts | total latency (s) | total cost ($) |",
        "|---|---:|---:|---:|---:|",
    ]
    for cfg in configs:
        m = cfg["metrics"]
        lines.append(
            f"| {cfg['name']} | {m['fully_valid_rate']:.1%} | {m['mean_attempts']:.2f} "
            f"| {m['total_latency_s']:.1f} | {m['total_cost_usd']:.4f} |"
        )
    lines += ["", "## Field accuracy vs ground truth", ""]
    header = "| field | " + " | ".join(cfg["name"] for cfg in configs) + " |"
    lines += [header, "|---|" + "---:|" * len(configs)]
    for field_name in (*payload["field_names"], "macro_avg"):
        cells = " | ".join(f"{cfg['metrics']['field_accuracy'][field_name]:.1%}" for cfg in configs)
        lines.append(f"| {field_name} | {cells} |")
    lines += ["", "## Attempts to converge", ""]
    buckets = list(configs[0]["metrics"]["attempts_histogram"])
    lines += [
        "| configuration | " + " | ".join(buckets) + " |",
        "|---|" + "---:|" * len(buckets),
    ]
    for cfg in configs:
        hist = cfg["metrics"]["attempts_histogram"]
        lines.append(f"| {cfg['name']} | " + " | ".join(str(hist[b]) for b in buckets) + " |")
    lines += ["", "![attempts histogram](attempts.svg)", ""]
    return "\n".join(lines)


def _render_attempts_svg(payload: dict[str, Any]) -> str:
    """Grouped bar chart of the attempts histogram. Hand-rolled, no deps."""
    configs = payload["configurations"]
    buckets = list(configs[0]["metrics"]["attempts_histogram"])
    bar_w, gap, group_pad, left, top, chart_h = 26, 4, 28, 50, 56, 170
    group_w = len(configs) * (bar_w + gap) + group_pad
    width = left + len(buckets) * group_w + 20
    height = top + chart_h + 40
    peak = max(
        (cfg["metrics"]["attempts_histogram"][b] for cfg in configs for b in buckets),
        default=1,
    )
    peak = max(peak, 1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'font-family="Menlo, monospace" font-size="12">',
        f'<text x="{left}" y="20" font-size="14" font-weight="bold">'
        "Attempts to converge (count of tasks)</text>",
        f'<line x1="{left}" y1="{top + chart_h}" x2="{width - 10}" y2="{top + chart_h}" '
        'stroke="#333"/>',
    ]
    for i, cfg in enumerate(configs):  # legend
        x = left + i * 150
        parts.append(f'<rect x="{x}" y="30" width="12" height="12" fill="{_SVG_COLORS[i]}"/>')
        parts.append(f'<text x="{x + 16}" y="41">{cfg["name"]}</text>')
    for b_idx, bucket in enumerate(buckets):
        gx = left + b_idx * group_w
        for c_idx, cfg in enumerate(configs):
            count = cfg["metrics"]["attempts_histogram"][bucket]
            h = round(chart_h * count / peak)
            x = gx + c_idx * (bar_w + gap)
            y = top + chart_h - h
            parts.append(
                f'<rect x="{x}" y="{y}" width="{bar_w}" height="{h}" fill="{_SVG_COLORS[c_idx]}"/>'
            )
            parts.append(
                f'<text x="{x + bar_w // 2}" y="{y - 4}" text-anchor="middle">{count}</text>'
            )
        label_x = gx + (len(configs) * (bar_w + gap)) // 2
        label = bucket if bucket == "failed" else f"{bucket} attempt(s)"
        parts.append(
            f'<text x="{label_x}" y="{top + chart_h + 18}" text-anchor="middle">{label}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def _print_summary(payload: dict[str, Any], file: TextIO) -> None:
    """Aligned stdout table with ASCII bars (the terminal artifact)."""
    configs = payload["configurations"]
    engine = payload["engine_name"]
    kind = "deterministic fault-injection simulation" if payload["simulated"] else "live engine"
    print(
        f"Benchmark over {payload['num_tasks']} {payload['domain_unit']} — "
        f"engine: {engine} ({kind})",
        file=file,
    )
    print(file=file)
    name_w = max(len(cfg["name"]) for cfg in configs)
    header = f"{'configuration':<{name_w}}  {'valid':>7}  {'mean att':>8}  valid-rate"
    print(header, file=file)
    print("-" * (len(header) + 22), file=file)
    for cfg in configs:
        m = cfg["metrics"]
        bar = "#" * round(m["fully_valid_rate"] * 30)
        print(
            f"{cfg['name']:<{name_w}}  {m['fully_valid_rate']:>7.1%}  "
            f"{m['mean_attempts']:>8.2f}  {bar:<30}",
            file=file,
        )
    print(file=file)
    buckets = list(configs[0]["metrics"]["attempts_histogram"])
    print("attempts histogram (tasks per bucket):", file=file)
    for cfg in configs:
        hist = cfg["metrics"]["attempts_histogram"]
        cells = "  ".join(f"{b}:{hist[b]:>2} {'#' * hist[b]:<24}" for b in buckets)
        print(f"  {cfg['name']:<{name_w}}  {cells}".rstrip(), file=file)
    print(file=file)


# ---------------------------------------------------------------- entrypoint


def run_benchmark(cfg: BenchConfig, file: TextIO = sys.stdout) -> dict[str, Any]:
    """Run OFF/ON (and the ablation) over the corpus; write artifacts; return payload."""
    domain: Domain = get_domain(cfg.domain)
    if cfg.engine == "simulated":
        engine = domain.build_simulated_engine(cfg.seed)
    else:
        engine = get_engine(cfg.engine, seed=cfg.seed)
    validator = domain.build_validator()
    critic = domain.build_critic()
    tasks = domain.load_tasks()
    ground_truth = domain.load_ground_truth()
    buckets = [str(i) for i in range(1, cfg.max_attempts + 1)] + ["failed"]

    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    traces_path = cfg.out_dir / "traces.jsonl"
    traces_path.unlink(missing_ok=True)  # rebuild from scratch: appends must not stack

    plan = [("off", critic, 1), ("on", critic, cfg.max_attempts)]
    if cfg.ablation:
        plan.append(("on_generic", GenericCritic(), cfg.max_attempts))
    configurations: list[dict[str, Any]] = []
    with TraceWriter(traces_path) as traces:
        for name, run_critic, max_attempts in plan:
            configurations.append(
                _run_configuration(
                    name,
                    engine,
                    validator,
                    run_critic,
                    tasks,
                    ground_truth,
                    domain.field_names,
                    domain.field_accuracy,
                    max_attempts,
                    buckets,
                    traces,
                )
            )

    payload: dict[str, Any] = {
        "config": {
            "seed": cfg.seed,
            "max_attempts": cfg.max_attempts,
            "ablation": cfg.ablation,
            "engine": cfg.engine,
            "domain": cfg.domain,
            "out_dir": str(cfg.out_dir),
        },
        "engine_name": engine.name,
        "simulated": engine.name == "simulated",
        "domain_title": domain.title,
        "domain_unit": domain.unit,
        "field_names": list(domain.field_names),
        "num_tasks": len(tasks),
        "configurations": configurations,
    }
    (cfg.out_dir / "results.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (cfg.out_dir / "results.md").write_text(_render_markdown(payload), encoding="utf-8")
    (cfg.out_dir / "attempts.svg").write_text(_render_attempts_svg(payload), encoding="utf-8")
    _print_summary(payload, file)
    print(
        f"artifacts: {cfg.out_dir}/results.json, results.md, attempts.svg, traces.jsonl", file=file
    )
    return payload
