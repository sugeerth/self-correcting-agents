"""Engine registry.

ALL engine imports are lazy (inside get_engine) so importing
selfcorrect.engines never pulls in anthropic, pydantic, urllib-using
modules, or the selfcorrect.invoices domain package. This keeps the core
import zero-dependency and domain-free (enforced by tests).
"""

from __future__ import annotations

from typing import Any

from selfcorrect.types import Engine

#: Valid values for get_engine(name) / the CLI --engine flag.
ENGINE_NAMES: tuple[str, ...] = ("simulated", "hermes", "anthropic")


def get_engine(name: str, **kwargs: Any) -> Engine:
    """Build a ready-to-run engine by name.

    - 'simulated': deterministic seeded fault-injection over the invoice
      ground truth (kwargs: seed, default 42). Free, CI-safe.
    - 'hermes': local Ollama model (kwargs: model, base_url, timeout). Free.
    - 'anthropic': paid Anthropic adapter (kwargs: model); raises RuntimeError
      if the optional extra or ANTHROPIC_API_KEY is missing.
    """
    if name == "simulated":
        from selfcorrect.invoices import load_ground_truth
        from selfcorrect.invoices.errors import build_simulated_engine

        return build_simulated_engine(load_ground_truth(), seed=kwargs.get("seed", 42))
    if name == "hermes":
        from selfcorrect.engines.hermes import HermesEngine

        allowed = {k: v for k, v in kwargs.items() if k in ("model", "base_url", "timeout")}
        return HermesEngine(**allowed)
    if name == "anthropic":
        from selfcorrect.engines.anthropic_engine import AnthropicEngine

        allowed = {k: v for k, v in kwargs.items() if k in ("model",)}
        return AnthropicEngine(**allowed)  # its own RuntimeErrors propagate
    raise ValueError(f"Unknown engine {name!r}; valid engines: {', '.join(ENGINE_NAMES)}")
