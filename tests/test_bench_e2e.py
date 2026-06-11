"""End-to-end benchmark bounds on the full simulated corpus (seed 42).

These are the headline numbers of the project: self-correction OFF must be
meaningfully imperfect, ON must fix almost everything, and the generic-critic
ablation must show that TARGETED feedback (not just retrying) does the work.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from selfcorrect.bench import BenchConfig, run_benchmark

NUM_TASKS = 24


@pytest.fixture(scope="module")
def bench(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    out_dir = tmp_path_factory.mktemp("bench")
    cfg = BenchConfig(seed=42, max_attempts=3, ablation=True, out_dir=out_dir)
    return run_benchmark(cfg), out_dir


def _rates(payload: dict[str, Any]) -> dict[str, float]:
    return {cfg["name"]: cfg["metrics"]["fully_valid_rate"] for cfg in payload["configurations"]}


def test_configurations_present_and_sized(bench: tuple[dict[str, Any], Path]) -> None:
    payload, _ = bench
    names = [cfg["name"] for cfg in payload["configurations"]]
    assert names == ["off", "on", "on_generic"]
    assert payload["num_tasks"] == NUM_TASKS
    assert payload["simulated"] is True
    for cfg in payload["configurations"]:
        assert len(cfg["tasks"]) == NUM_TASKS


def test_validity_bounds_and_lift(bench: tuple[dict[str, Any], Path]) -> None:
    payload, _ = bench
    rates = _rates(payload)
    assert 0.45 <= rates["off"] <= 0.80, rates
    assert rates["on"] >= 0.90, rates
    assert rates["on"] - rates["off"] >= 0.15, rates
    # Ablation: untargeted feedback must not beat targeted feedback, and the
    # engine has nothing to act on, so it cannot fall below correction-OFF.
    assert rates["off"] <= rates["on_generic"] < rates["on"], rates


def test_self_correction_improves_field_accuracy(bench: tuple[dict[str, Any], Path]) -> None:
    payload, _ = bench
    accuracy = {cfg["name"]: cfg["metrics"]["field_accuracy"] for cfg in payload["configurations"]}
    assert accuracy["on"]["macro_avg"] > accuracy["off"]["macro_avg"]
    for name, fields in accuracy.items():
        for field_name, value in fields.items():
            assert 0.0 <= value <= 1.0, (name, field_name, value)


def test_attempts_histograms_sum_to_corpus_size(bench: tuple[dict[str, Any], Path]) -> None:
    payload, _ = bench
    for cfg in payload["configurations"]:
        histogram = cfg["metrics"]["attempts_histogram"]
        assert set(histogram) == {"1", "2", "3", "failed"}
        assert sum(histogram.values()) == NUM_TASKS, (cfg["name"], histogram)
    off = payload["configurations"][0]["metrics"]["attempts_histogram"]
    assert off["2"] == off["3"] == 0  # OFF gets exactly one attempt


def test_mean_attempts_and_telemetry(bench: tuple[dict[str, Any], Path]) -> None:
    payload, _ = bench
    for cfg in payload["configurations"]:
        m = cfg["metrics"]
        assert cfg["max_attempts"] >= m["mean_attempts"] >= 1.0
        assert m["total_latency_s"] > 0.0
        assert m["total_cost_usd"] == 0.0  # simulated engine is free


def test_results_json_round_trips(bench: tuple[dict[str, Any], Path]) -> None:
    payload, out_dir = bench
    on_disk = json.loads((out_dir / "results.json").read_text(encoding="utf-8"))
    assert on_disk == payload
    assert json.loads(json.dumps(payload)) == payload


def test_artifacts_written(bench: tuple[dict[str, Any], Path]) -> None:
    _, out_dir = bench
    markdown = (out_dir / "results.md").read_text(encoding="utf-8")
    assert "deterministic fault-injection simulation" in markdown
    assert "| configuration |" in markdown
    svg = (out_dir / "attempts.svg").read_text(encoding="utf-8")
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    trace_lines = (out_dir / "traces.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(trace_lines) == 3 * NUM_TASKS  # off + on + on_generic
    for line in trace_lines:
        record = json.loads(line)
        assert record["simulated"] is True
