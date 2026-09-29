"""The Anthropic client, request settings, and the budget meter.

Two backends:
- replay: serves saved responses from a recording. No key, no network.
- live: calls the Claude API. Choosing it is the opt-in. It reads
  ANTHROPIC_API_KEY from .env (or the environment) and stops the run when the
  spend passes the budget.

Every request uses the same settings, defined once in request_settings().
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from anthropic import Anthropic, DefaultHttpxClient

from .replay import Recording, RecordingTransport, ReplayTransport

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 32_000
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per million tokens: input, output, cache read, 5-minute cache write.
# Opus 5.5 from the current price list. Fallback models are priced so a
# rerouted request is not undercounted.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-opus-5": (5.00, 25.00, 0.50, 6.25),
    "claude-opus-4-8": (5.00, 25.00, 0.50, 6.25),
}
HIGHEST = max(PRICES.values())

Backend = Literal["replay", "live"]


class BudgetExceeded(RuntimeError):
    pass


class MissingKey(RuntimeError):
    pass


def request_settings() -> dict[str, Any]:
    """Settings shared by every call. Changing any of these makes recordings stale."""
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": EFFORT},
        "cache_control": {"type": "ephemeral"},
        "betas": [FALLBACK_BETA],
        "fallbacks": "default",
    }


def strict_tools(definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**d, "strict": True} for d in definitions]


@dataclass
class Meter:
    """Totals tokens and dollars across a run. Raises once the budget is passed."""
    budget_usd: float | None = None
    calls: int = 0
    usd: float = 0.0
    tokens: dict[str, int] = field(default_factory=lambda: {
        "input": 0, "output": 0, "cache_read": 0, "cache_write": 0})
    models: dict[str, int] = field(default_factory=dict)
    refusals: int = 0

    def add(self, message: Any) -> float:
        usage = message.usage
        counts = {"input": usage.input_tokens or 0, "output": usage.output_tokens or 0,
                  "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
                  "cache_write": getattr(usage, "cache_creation_input_tokens", 0) or 0}
        price = PRICES.get(message.model, HIGHEST)
        cost = (counts["input"] * price[0] + counts["output"] * price[1]
                + counts["cache_read"] * price[2] + counts["cache_write"] * price[3]) / 1_000_000
        self.calls += 1
        self.usd += cost
        for key, value in counts.items():
            self.tokens[key] += value
        self.models[message.model] = self.models.get(message.model, 0) + 1
        if message.stop_reason == "refusal":
            self.refusals += 1
        if self.budget_usd is not None and self.usd > self.budget_usd:
            raise BudgetExceeded(f"Spent ${self.usd:.2f}, over the ${self.budget_usd:.2f} budget. The run stopped.")
        return cost

    def summary(self) -> dict[str, Any]:
        return {"calls": self.calls, "usd_estimate": round(self.usd, 4), "tokens": dict(self.tokens),
                "models": dict(self.models), "refusals": self.refusals}


def read_key(env_file: str | Path = ".env") -> str:
    path = Path(env_file)
    if path.exists():
        for line in path.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
                return value.strip().strip("'\"")
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    raise MissingKey("No API key found. Copy .env.example to .env and add ANTHROPIC_API_KEY. "
                     "Or use --backend replay, which needs no key.")


def make_client(backend: Backend, *, recording: str | Path | None = None,
                env_file: str | Path = ".env") -> Anthropic:
    """replay needs a recording path. live records only when a path is given."""
    if backend == "replay":
        if recording is None:
            raise ValueError("Replay needs a recording path.")
        transport = ReplayTransport(Recording.load(recording))
        return Anthropic(api_key="replay-mode-no-key", max_retries=0,
                         http_client=DefaultHttpxClient(transport=transport))
    if backend == "live":
        key = read_key(env_file)
        if recording is None:
            return Anthropic(api_key=key)
        transport = RecordingTransport(Recording(Path(recording), meta={"model": MODEL, "effort": EFFORT}))
        return Anthropic(api_key=key, http_client=DefaultHttpxClient(transport=transport))
    raise ValueError("backend must be 'replay' or 'live'.")
