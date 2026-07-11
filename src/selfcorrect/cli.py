"""Command-line interface: ``selfcorrect demo | bench | list-corpus``.

All heavy imports happen inside the subcommand handlers so ``--help`` stays
instant and the core/domain import boundary holds.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from selfcorrect.engines import ENGINE_NAMES

#: Seed-42 simulated plan for this task shows two violations (LINE_ITEMS_SUM +
#: TOTAL_MISMATCH) repaired on attempt 2. inv_021 draws the unfixable path and
#: demonstrates bounded failure instead — both verified against the current RNG
#: stream; re-verify if seeds, catalog, or corpus change.
DEFAULT_DEMO_TASK = "inv_004"


def _add_engine_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--seed", type=int, default=42, help="engine seed (default: 42)")
    parser.add_argument(
        "--max-attempts", type=int, default=3, help="repair budget per task (default: 3)"
    )
    parser.add_argument(
        "--engine",
        choices=ENGINE_NAMES,
        default="simulated",
        help="which engine generates extractions (default: simulated)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="selfcorrect",
        description="Self-correcting agents: generate -> validate -> critique -> repair.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run one invoice through the loop and print the trace")
    demo.add_argument(
        "--task",
        default=DEFAULT_DEMO_TASK,
        help=f"corpus task id (default: {DEFAULT_DEMO_TASK})",
    )
    _add_engine_args(demo)

    bench = sub.add_parser("bench", help="benchmark self-correction OFF vs ON over the corpus")
    _add_engine_args(bench)
    bench.add_argument("--out", type=Path, default=Path("bench_out"), help="artifact directory")
    bench.add_argument(
        "--ablation",
        action="store_true",
        help="also run the generic-critic ablation (untargeted feedback)",
    )

    sub.add_parser("list-corpus", help="list the bundled invoice corpus")
    return parser


def _cmd_demo(args: argparse.Namespace) -> int:
    from selfcorrect.engines import get_engine
    from selfcorrect.invoices import build_critic, build_validator, load_tasks
    from selfcorrect.loop import SelfCorrectingAgent
    from selfcorrect.trace import pretty_print_run

    tasks = {task.id: task for task in load_tasks()}
    if args.task not in tasks:
        ids = ", ".join(sorted(tasks))
        raise SystemExit(f"unknown task {args.task!r}; available: {ids}")
    agent = SelfCorrectingAgent(
        get_engine(args.engine, seed=args.seed),
        build_validator(),
        build_critic(),
        max_attempts=args.max_attempts,
    )
    result = agent.run(tasks[args.task])
    pretty_print_run(result)
    return 0 if result.success else 1


def _cmd_bench(args: argparse.Namespace) -> int:
    from selfcorrect.bench import BenchConfig, run_benchmark

    run_benchmark(
        BenchConfig(
            seed=args.seed,
            max_attempts=args.max_attempts,
            ablation=args.ablation,
            out_dir=args.out,
            engine=args.engine,
        )
    )
    return 0


def _cmd_list_corpus() -> int:
    from selfcorrect.invoices import load_ground_truth, load_tasks

    truth = load_ground_truth()
    print(f"{'task id':<10} {'vendor':<34} {'date':<12} {'cur':<4} {'total':>12}")
    print("-" * 76)
    for task in load_tasks():
        gt = truth[task.id]
        print(
            f"{task.id:<10} {gt['vendor']:<34.34} {gt['date']:<12} "
            f"{gt['currency']:<4} {gt['total']:>12.2f}"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    """The [project.scripts] entry point."""
    args = _build_parser().parse_args(argv)
    if args.command == "demo":
        return _cmd_demo(args)
    if args.command == "bench":
        return _cmd_bench(args)
    return _cmd_list_corpus()


if __name__ == "__main__":
    raise SystemExit(main())
