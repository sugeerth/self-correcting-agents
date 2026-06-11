"""Load the committed invoice corpus and its ground truth as package data.

Both functions resolve files via ``importlib.resources`` so they work for
editable installs, wheels, and zipped packages alike (never ``__file__``).
"""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from selfcorrect.types import Task


def load_tasks() -> list[Task]:
    """All corpus invoices as Tasks (id = file stem, prompt = raw text), sorted by id."""
    corpus = files("selfcorrect.invoices") / "corpus"
    tasks = [
        Task(id=entry.name.removesuffix(".txt"), prompt=entry.read_text(encoding="utf-8"))
        for entry in corpus.iterdir()
        if entry.name.endswith(".txt")
    ]
    return sorted(tasks, key=lambda t: t.id)


def load_ground_truth() -> dict[str, dict[str, Any]]:
    """The ground-truth extraction for every corpus invoice, keyed by task id."""
    resource = files("selfcorrect.invoices") / "ground_truth.json"
    data: dict[str, dict[str, Any]] = json.loads(resource.read_text(encoding="utf-8"))
    return data
