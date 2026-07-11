"""Command-line interface: ``selfcorrect demo | bench | list-corpus``.

All heavy imports happen inside the subcommand handlers so ``--help`` stays
instant and the core/domain import boundary holds.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from selfcorrect.domains import DOMAIN_NAMES
from selfcorrect.engines import ENGINE_NAMES


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--domain",
        choices=DOMAIN_NAMES,
        default="invoices",
        help="which domain plug-in to run (default: invoices)",
    )


def _add_engine_args(parser: argparse.ArgumentParser) -> None:
    _add_common_args(parser)
    parser.add_argument("--seed", type=int, default=42, help="engine seed (default: 42)")
    parser.add_argument(
        "--max-attempts", type=int, default=3, help="repair budget per task (default: 3)"
    )
    parser.add_argument(
        "--engine",
        choices=ENGINE_NAMES,
        default="simulated",
        help="which engine generates outputs (default: simulated)",
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="selfcorrect",
        description="Self-correcting agents: generate -> validate -> critique -> repair.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="run one task through the loop and print the trace")
    demo.add_argument(
        "--task",
        default=None,
        help="corpus task id (default: the domain's showcase task)",
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

    list_corpus = sub.add_parser("list-corpus", help="list the bundled corpus")
    _add_common_args(list_corpus)
    return parser


def _cmd_demo(args: argparse.Namespace) -> int:
    from selfcorrect.domains import get_domain
    from selfcorrect.engines import get_engine
    from selfcorrect.loop import SelfCorrectingAgent
    from selfcorrect.trace import pretty_print_run

    domain = get_domain(args.domain)
    task_id = args.task if args.task is not None else domain.default_demo_task
    tasks = {task.id: task for task in domain.load_tasks()}
    if task_id not in tasks:
        ids = ", ".join(sorted(tasks))
        raise SystemExit(f"unknown task {task_id!r}; available: {ids}")
    if args.engine == "simulated":
        engine = domain.build_simulated_engine(args.seed)
    else:
        engine = get_engine(args.engine, seed=args.seed)
    agent = SelfCorrectingAgent(
        engine,
        domain.build_validator(),
        domain.build_critic(),
        max_attempts=args.max_attempts,
    )
    result = agent.run(tasks[task_id])
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
            domain=args.domain,
        )
    )
    return 0


def _cmd_list_corpus(args: argparse.Namespace) -> int:
    from selfcorrect.domains import get_domain

    domain = get_domain(args.domain)
    truth = domain.load_ground_truth()
    print(f"{'task id':<10} description")
    print("-" * 76)
    for task in domain.load_tasks():
        print(f"{task.id:<10} {domain.describe_row(truth[task.id])}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """The [project.scripts] entry point."""
    args = _build_parser().parse_args(argv)
    if args.command == "demo":
        return _cmd_demo(args)
    if args.command == "bench":
        return _cmd_bench(args)
    return _cmd_list_corpus(args)


if __name__ == "__main__":
    raise SystemExit(main())
