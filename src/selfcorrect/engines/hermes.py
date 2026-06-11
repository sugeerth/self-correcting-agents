"""Free local engine: NousResearch Hermes 3 served by the Ollama HTTP API.

Stdlib-only (urllib.request, json, time). Ollama's /api/chat is stateless per
call, so prior repair rounds are NOT replayed as a full assistant/user
transcript (we do not retain the assistant's raw turns in the Engine
protocol). Instead each generate() sends the original system+user pair plus
ONE trailing user message that carries ALL accumulated repair instructions
from feedback_history, rendered with build_repair_prompt. The engine keeps a
small per-task map of the last raw model output so the repair message can
show the JSON being corrected.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any

from selfcorrect.invoices.prompts import (
    INVOICE_JSON_SCHEMA,
    build_repair_prompt,
    build_system_prompt,
    build_user_prompt,
)
from selfcorrect.types import Attempt, Feedback, Task

_OLLAMA_HELP = (
    "Ollama is not running at {base_url}. Install it from https://ollama.com, "
    "then run: ollama pull hermes3 — see README section 'Hermes (free local model)'."
)


class HermesEngine:
    """Engine backed by a local Ollama server (default model: hermes3).

    Construction is pure — no network I/O happens until generate().
    """

    def __init__(
        self,
        model: str = "hermes3",
        base_url: str = "http://localhost:11434",
        timeout: float = 120.0,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.name = f"hermes:{model}"
        self._last_raw: dict[str, str] = {}  # task.id -> last raw model content

    def generate(self, task: Task, feedback_history: Sequence[list[Feedback]]) -> Attempt:
        """One extraction attempt; repair instructions folded into a final user turn."""
        messages: list[dict[str, str]] = [
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": build_user_prompt(task)},
        ]
        if feedback_history:
            instructions = [fb.instruction for fb_round in feedback_history for fb in fb_round]
            prior = self._last_raw.get(task.id, "(previous JSON unavailable)")
            messages.append({"role": "user", "content": build_repair_prompt(prior, instructions)})

        body: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": INVOICE_JSON_SCHEMA,
            "options": {"temperature": 0},
        }
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                resp = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # server reachable but request failed
            raise RuntimeError(
                f"Ollama at {self.base_url} returned HTTP {exc.code}; "
                f"is the model pulled? Run: ollama pull {self.model}"
            ) from exc
        except (urllib.error.URLError, ConnectionError) as exc:
            raise RuntimeError(_OLLAMA_HELP.format(base_url=self.base_url)) from exc
        latency = time.perf_counter() - start

        content = resp.get("message", {}).get("content", "")
        self._last_raw[task.id] = content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            parsed = None
        output = parsed if isinstance(parsed, dict) else None

        return Attempt(
            index=0,  # the loop owns index
            output=output,
            raw_text=content,
            latency_s=latency,
            input_tokens=int(resp.get("prompt_eval_count", 0) or 0),
            output_tokens=int(resp.get("eval_count", 0) or 0),
            cost_usd=0.0,
            engine=self.name,
        )
