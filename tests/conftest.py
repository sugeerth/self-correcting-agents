"""Shared fixtures: the bundled invoice corpus and its ground truth."""

from __future__ import annotations

from typing import Any

import pytest

from selfcorrect.invoices import load_ground_truth, load_tasks
from selfcorrect.types import Task


@pytest.fixture(scope="session")
def corpus_tasks() -> list[Task]:
    """All 24 committed corpus invoices, sorted by id."""
    return load_tasks()


@pytest.fixture(scope="session")
def ground_truth() -> dict[str, dict[str, Any]]:
    """Ground-truth extraction for every corpus invoice, keyed by task id."""
    return load_ground_truth()
