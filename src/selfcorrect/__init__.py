"""selfcorrect — agents that catch and fix their own mistakes.

A zero-dependency generate -> validate -> critique -> repair loop.
"""

from selfcorrect.types import (
    Attempt,
    Critic,
    Engine,
    Feedback,
    RunResult,
    Severity,
    Task,
    Validator,
    Violation,
)

__version__ = "0.1.0"

__all__ = [
    "Attempt",
    "Critic",
    "Engine",
    "Feedback",
    "RunResult",
    "SelfCorrectingAgent",
    "Severity",
    "Task",
    "Validator",
    "Violation",
    "__version__",
]


def __getattr__(name: str):
    # Lazy import so `import selfcorrect` stays light and the core/domain
    # boundary tests (loop not yet written at scaffold time) hold.
    if name == "SelfCorrectingAgent":
        from selfcorrect.loop import SelfCorrectingAgent

        return SelfCorrectingAgent
    raise AttributeError(f"module 'selfcorrect' has no attribute {name!r}")
