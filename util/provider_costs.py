"""Small provider-specific pricing rules shared by batch workflows."""

from __future__ import annotations

import re


def _openai_model_at_least(model: str, major: int, minor: int) -> bool:
    match = re.search(
        r"(?:^|/)gpt-(\d+)\.(\d+)(?:\D|$)",
        str(model or "").lower(),
    )
    if not match:
        return False
    return (int(match.group(1)), int(match.group(2))) >= (major, minor)


def cache_write_multiplier(provider: str, model: str) -> float:
    """Return cache-write price as a multiple of regular input pricing.

    Anthropic requests use the explicit one-hour cache TTL, whose writes cost
    twice regular input. OpenAI introduced separately billed cache writes for
    GPT-5.6 and later model families at 1.25 times regular input.
    """
    normalized_provider = str(provider or "").strip().lower()
    if normalized_provider == "anthropic":
        return 2.0
    if normalized_provider == "openai" and _openai_model_at_least(model, 5, 6):
        return 1.25
    return 1.0


def has_billed_cache_writes(provider: str, model: str) -> bool:
    """Return whether cache writes have a distinct price for this route."""
    return cache_write_multiplier(provider, model) != 1.0
