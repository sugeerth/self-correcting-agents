"""Import-cleanliness and optional-dependency tests, run in fresh subprocesses.

Each check spawns a new interpreter so sys.modules reflects exactly what the
code under test imports — nothing leaks in from pytest or sibling tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(code: str) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    env["PYTHONPATH"] = str(PROJECT_ROOT / "src")
    return subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


# (a) Zero-dep + core/domain boundary: importing the core must not pull in
# the anthropic/pydantic SDKs nor the invoices domain package.
# selfcorrect.loop is imported when present (it is built by a sibling module;
# the guard keeps this test meaningful both before and after integration).
CORE_BOUNDARY = """
import importlib.util
import sys

import selfcorrect
import selfcorrect.engines

if importlib.util.find_spec("selfcorrect.loop") is not None:
    import selfcorrect.loop

assert "anthropic" not in sys.modules, "anthropic leaked into the core import"
assert "pydantic" not in sys.modules, "pydantic leaked into the core import"
assert "selfcorrect.invoices" not in sys.modules, "domain package leaked into the core import"
assert "selfcorrect.sqlq" not in sys.modules, "domain package leaked into the core import"
"""

# (b) get_engine('anthropic') must fail loudly with an actionable message,
# whichever guard trips first (missing extra vs missing API key).
ANTHROPIC_GUARD = """
from selfcorrect.engines import get_engine

try:
    get_engine("anthropic")
except RuntimeError as exc:
    message = str(exc)
    assert "selfcorrect[anthropic]" in message or "ANTHROPIC_API_KEY" in message, message
else:
    raise SystemExit("expected RuntimeError from get_engine('anthropic')")
"""

# (c) Unknown engine names raise ValueError listing the valid names.
UNKNOWN_ENGINE = """
from selfcorrect.engines import get_engine

try:
    get_engine("nope")
except ValueError as exc:
    message = str(exc)
    for valid in ("simulated", "hermes", "anthropic"):
        assert valid in message, message
else:
    raise SystemExit("expected ValueError from get_engine('nope')")
"""

# (d) HermesEngine construction is pure (no network in __init__); generate()
# against a guaranteed-closed port raises a RuntimeError mentioning Ollama.
HERMES_OFFLINE = """
from selfcorrect.engines.hermes import HermesEngine
from selfcorrect.types import Task

engine = HermesEngine(base_url="http://localhost:9", timeout=2.0)  # pure: no I/O yet
assert engine.name == "hermes:hermes3", engine.name

task = Task(id="t1", prompt="INVOICE\\nVendor: Acme\\nTotal: $10.00")
try:
    engine.generate(task, [])
except RuntimeError as exc:
    assert "Ollama" in str(exc), str(exc)
else:
    raise SystemExit("expected RuntimeError from generate() against a closed port")
"""


def test_core_import_is_zero_dep_and_domain_free() -> None:
    proc = _run(CORE_BOUNDARY)
    assert proc.returncode == 0, proc.stderr


def test_get_engine_anthropic_raises_actionable_runtime_error() -> None:
    proc = _run(ANTHROPIC_GUARD)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_get_engine_unknown_name_raises_value_error() -> None:
    proc = _run(UNKNOWN_ENGINE)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_hermes_engine_pure_init_and_offline_error() -> None:
    proc = _run(HERMES_OFFLINE)
    assert proc.returncode == 0, proc.stderr or proc.stdout
