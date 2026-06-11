"""Optional paid adapter: Anthropic worker (Opus 4.8) + critic (Haiku 4.5).

Import-guarded so this module imports cleanly when the `anthropic` / `pydantic`
SDKs are absent; constructing the classes then raises a RuntimeError pointing
at the optional extra. Install with: pip install 'selfcorrect[anthropic]'.

NOTE: claude-opus-4-8 rejects temperature/top_p/top_k with HTTP 400, so no
sampling parameters are ever sent.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from typing import Any

from selfcorrect.invoices.prompts import (
    build_repair_prompt,
    build_system_prompt,
    build_user_prompt,
)
from selfcorrect.types import Attempt, Feedback, Task, Violation

try:
    import anthropic
    from pydantic import BaseModel

    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

WORKER_MODEL = "claude-opus-4-8"
CRITIC_MODEL = "claude-haiku-4-5"
#: $ per MTok as (input, output).
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

if _AVAILABLE:

    class LineItemModel(BaseModel):
        description: str
        quantity: float
        unit_price: float
        amount: float

    class InvoiceModel(BaseModel):
        vendor: str
        date: str
        currency: str
        line_items: list[LineItemModel]
        subtotal: float
        tax: float
        total: float


def _require_sdk_and_key() -> None:
    if not _AVAILABLE:
        raise RuntimeError(
            "AnthropicEngine requires the optional extra: pip install 'selfcorrect[anthropic]'"
        )
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set; use the default simulated engine or hermes instead."
        )


def _cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    in_price, out_price = PRICING.get(model, PRICING[WORKER_MODEL])
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000


class AnthropicEngine:
    """Worker engine: structured extraction via client.messages.parse + Pydantic."""

    def __init__(self, model: str = WORKER_MODEL) -> None:
        _require_sdk_and_key()
        self.model = model
        self.name = f"anthropic:{model}"
        self._client = anthropic.Anthropic()
        self._last_json: dict[str, str] = {}  # task.id -> last output JSON we produced

    def generate(self, task: Task, feedback_history: Sequence[list[Feedback]]) -> Attempt:
        """One extraction attempt; each prior feedback round becomes a repair turn.

        Only the most recent repair turn embeds the engine's last JSON for this
        task; earlier turns carry a placeholder since their outputs are stale.
        """
        messages: list[dict[str, Any]] = [{"role": "user", "content": build_user_prompt(task)}]
        last = len(feedback_history) - 1
        for i, fb_round in enumerate(feedback_history):
            prior = (
                self._last_json.get(task.id, "(previous JSON unavailable)")
                if i == last
                else "(superseded by a later attempt)"
            )
            instructions = [fb.instruction for fb in fb_round]
            messages.append({"role": "user", "content": build_repair_prompt(prior, instructions)})

        start = time.perf_counter()
        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=2048,
                system=build_system_prompt(),
                messages=messages,
                output_format=InvoiceModel,
            )
        except anthropic.APIError as exc:  # never crash the loop on API failures
            return Attempt(
                index=0,
                output=None,
                raw_text=str(exc),
                latency_s=time.perf_counter() - start,
                engine=self.name,
            )
        latency = time.perf_counter() - start

        parsed = response.parsed_output
        output = parsed.model_dump() if parsed is not None else None
        raw_text = json.dumps(output) if output is not None else None
        if raw_text is not None:
            self._last_json[task.id] = raw_text
        input_tokens = int(response.usage.input_tokens)
        output_tokens = int(response.usage.output_tokens)

        return Attempt(
            index=0,  # the loop owns index
            output=output,
            raw_text=raw_text,
            latency_s=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=_cost_usd(self.model, input_tokens, output_tokens),
            engine=self.name,
        )


class AnthropicCritic:
    """LLM critic: Haiku rewrites Violations into terse repair instructions.

    Falls back to the rule-based TemplateCritic on ANY exception, so the
    self-correction loop never loses its feedback channel.
    """

    def __init__(self, model: str = CRITIC_MODEL) -> None:
        _require_sdk_and_key()
        self.model = model
        self._client = anthropic.Anthropic()

    def critique(
        self, output: dict[str, Any], violations: Sequence[Violation]
    ) -> list[Feedback]:
        try:
            return self._critique_llm(violations)
        except Exception:
            from selfcorrect.invoices import build_critic  # lazy: rule-based fallback

            return build_critic().critique(output, violations)

    def _critique_llm(self, violations: Sequence[Violation]) -> list[Feedback]:
        listed = "\n".join(
            f"{i}. [{v.code}] field={v.field}: {v.message}"
            f" (expected={v.expected!r}, actual={v.actual!r})"
            for i, v in enumerate(violations, start=1)
        )
        prompt = (
            "Rewrite each invoice-extraction validation failure below as ONE terse, "
            f"actionable repair instruction. Return exactly {len(violations)} lines, "
            f"numbered to match, and nothing else.\n\n{listed}"
        )
        response = self._client.messages.create(
            model=self.model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in response.content if b.type == "text")
        lines: list[str] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            head, sep, tail = line.partition(". ")
            lines.append(tail.strip() if sep and head.isdigit() else line)
        if len(lines) != len(violations):
            raise ValueError("critic returned a mismatched number of instructions")
        return [
            Feedback(violation_code=v.code, field=v.field, instruction=lines[i])
            for i, v in enumerate(violations)
        ]
