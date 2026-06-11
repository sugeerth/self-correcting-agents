"""Minimal walkthrough: build a self-correcting agent and watch it repair itself.

Run with:  python3 examples/run_demo.py
Everything is stdlib + selfcorrect; the simulated engine needs no API key.
"""

from selfcorrect.engines import get_engine
from selfcorrect.invoices import build_critic, build_validator, load_tasks
from selfcorrect.loop import SelfCorrectingAgent
from selfcorrect.trace import pretty_print_run


def main() -> None:
    # 1. An engine produces candidate extractions. The simulated engine
    #    deterministically injects realistic faults (seed-reproducible).
    engine = get_engine("simulated", seed=42)

    # 2. Validator + critic close the loop: the validator emits structured
    #    violations, the critic turns them into natural-language feedback.
    agent = SelfCorrectingAgent(
        engine,
        build_validator(),
        build_critic(),
        max_attempts=3,
    )

    # 3. Run one corpus invoice and print the attempt-by-attempt trace:
    #    attempt 1 fails validation, the feedback is applied, attempt 2 passes.
    task = next(t for t in load_tasks() if t.id == "inv_021")
    result = agent.run(task)
    pretty_print_run(result)


if __name__ == "__main__":
    main()
