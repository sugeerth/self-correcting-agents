"""Benchmark: self-correction OFF vs ON (vs a generic-critic ablation).

Runs the full invoice corpus through the loop under each configuration and
reports validity, field accuracy against ground truth, attempt histograms,
latency, and cost. Artifacts (results.json, results.md, attempts.svg,
traces.jsonl) land in ``BenchConfig.out_dir``. Everything is a pure function
of the config, so identical configs produce identical payloads and traces.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, TextIO

from selfcorrect.critic import GenericCritic
from selfcorrect.engines import get_engine
from selfcorrect.invoices import build_critic, build_validator, load_ground_truth, load_tasks
from selfcorrect.loop import SelfCorrectingAgent
from selfcorrect.trace import TraceWriter
from selfcorrect.types import Critic, Engine, RunResult, Task, Validator
from selfcorrect.validators import as_decimal

_MONEY_TOLERANCE = Decimal("0.01")
_MONEY_FIELDS = ("subtotal", "tax", "total")
_FIELD_NAMES = (
    "vendor",
    "date",
    "currency",
    "subtotal",
    "tax",
    "total",
    "line_item_count",
    "line_item_fields",
)
_SVG_COLORS = ("#4c78a8", "#f58518", "#54a24b")


@dataclass
class BenchConfig:
    """Knobs for one benchmark invocation."""

    seed: int = 42
    max_attempts: int = 3
    ablation: bool = False
    out_dir: Path = Path("bench_out")
    engine: str = "simulated"


# ---------------------------------------------------------------- accuracy


def _text_match(expected: Any, actual: Any) -> bool:
    """Case- and whitespace-insensitive string equality."""
    if not (isinstance(expected, str) and isinstance(actual, str)):
        return False
    return expected.strip().casefold() == actual.strip().casefold()


def _money_match(expected: Any, actual: Any) -> bool:
    """Decimal equality within one cent; non-numbers never match."""
    e, a = as_decimal(expected), as_decimal(actual)
    return e is not None and a is not None and abs(e - a) <= _MONEY_TOLERANCE


def _exact_number_match(expected: Any, actual: Any) -> bool:
    e, a = as_decimal(expected), as_decimal(actual)
    return e is not None and a is not None and e == a


def _line_item_cells(out_items: list[Any], gt_items: list[dict[str, Any]]) -> float:
    """Fraction of per-cell matches, compared positionally against ground truth."""
    cells = 4 * len(gt_items)
    if cells == 0:  # cannot happen with this corpus, but stay safe
        return 1.0
    correct = 0
    for i, gt_item in enumerate(gt_items):
        candidate = out_items[i] if i < len(out_items) else None
        out_item: dict[str, Any] = candidate if isinstance(candidate, dict) else {}
        if _text_match(gt_item["description"], out_item.get("description")):
            correct += 1
        if _exact_number_match(gt_item["quantity"], out_item.get("quantity")):
            correct += 1
        for key in ("unit_price", "amount"):
            if _money_match(gt_item[key], out_item.get(key)):
                correct += 1
    return correct / cells


def _field_accuracy(output: dict[str, Any] | None, truth: dict[str, Any]) -> dict[str, float]:
    """Per-field accuracy of one final output against its ground truth."""
    if not isinstance(output, dict):
        return {name: 0.0 for name in _FIELD_NAMES}
    raw_items = output.get("line_items")
    out_items: list[Any] = raw_items if isinstance(raw_items, list) else []
    gt_items: list[dict[str, Any]] = truth["line_items"]
    scores = {
        "vendor": float(_text_match(truth["vendor"], output.get("vendor"))),
        "date": float(output.get("date") == truth["date"]),
        "currency": float(output.get("currency") == truth["currency"]),
        "line_item_count": float(len(out_items) == len(gt_items)),
        "line_item_fields": _line_item_cells(out_items, gt_items),
    }
    for key in _MONEY_FIELDS:
        scores[key] = float(_money_match(truth[key], output.get(key)))
    return {name: scores[name] for name in _FIELD_NAMES}


# ---------------------------------------------------------------- one config


def _histogram(results: list[RunResult], buckets: list[str]) -> dict[str, int]:
    counts = {bucket: 0 for bucket in buckets}
    for result in results:
        counts[str(result.num_attempts) if result.success else "failed"] += 1
    return counts


def _aggregate_accuracy(rows: list[dict[str, Any]]) -> dict[str, float]:
    per_field = {
        name: sum(row["field_accuracy"][name] for row in rows) / len(rows) for name in _FIELD_NAMES
    }
    per_field["macro_avg"] = sum(per_field[name] for name in _FIELD_NAMES) / len(_FIELD_NAMES)
    return per_field


def _run_configuration(
    name: str,
    engine: Engine,
    validator: Validator,
    critic: Critic,
    tasks: list[Task],
    ground_truth: dict[str, dict[str, Any]],
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
                "field_accuracy": _field_accuracy(result.final_output, ground_truth[task.id]),
                "latency_s": result.total_latency_s,
                "cost_usd": result.total_cost_usd,
            }
        )
    n = len(results)
    metrics = {
        "fully_valid_rate": sum(r.success for r in results) / n,
        "field_accuracy": _aggregate_accuracy(rows),
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
        "# Self-correction benchmark — invoice extraction",
        "",
        disclaimer,
        "",
        f"Corpus: {payload['num_tasks']} invoices · seed {payload['config']['seed']} · "
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
    for field_name in (*_FIELD_NAMES, "macro_avg"):
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
    print(f"Benchmark over {payload['num_tasks']} invoices — engine: {engine} ({kind})", file=file)
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
    engine = get_engine(cfg.engine, seed=cfg.seed)
    validator = build_validator()
    critic = build_critic()
    tasks = load_tasks()
    ground_truth = load_ground_truth()
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
            "out_dir": str(cfg.out_dir),
        },
        "engine_name": engine.name,
        "simulated": engine.name == "simulated",
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
