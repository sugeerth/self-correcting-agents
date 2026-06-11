"""Reproducibility: identical configs must yield identical payloads and traces."""

from __future__ import annotations

import io
from pathlib import Path

from selfcorrect.bench import BenchConfig, run_benchmark


def _run(cfg: BenchConfig) -> tuple[dict, bytes, bytes]:
    payload = run_benchmark(cfg, file=io.StringIO())
    traces = (cfg.out_dir / "traces.jsonl").read_bytes()
    results = (cfg.out_dir / "results.json").read_bytes()
    return payload, traces, results


def test_run_benchmark_twice_is_identical(tmp_path: Path) -> None:
    cfg = BenchConfig(seed=42, max_attempts=3, ablation=True, out_dir=tmp_path / "bench")
    first_payload, first_traces, first_results = _run(cfg)
    second_payload, second_traces, second_results = _run(cfg)
    assert first_payload == second_payload
    assert first_traces == second_traces  # byte-identical, not just re-parsed-equal
    assert first_results == second_results


def test_different_seed_changes_the_payload(tmp_path: Path) -> None:
    base = BenchConfig(seed=42, out_dir=tmp_path / "a")
    other = BenchConfig(seed=7, out_dir=tmp_path / "b")
    payload_a = run_benchmark(base, file=io.StringIO())
    payload_b = run_benchmark(other, file=io.StringIO())
    configs_a = [cfg["tasks"] for cfg in payload_a["configurations"]]
    configs_b = [cfg["tasks"] for cfg in payload_b["configurations"]]
    assert configs_a != configs_b  # per-task outcomes shift with the seed
