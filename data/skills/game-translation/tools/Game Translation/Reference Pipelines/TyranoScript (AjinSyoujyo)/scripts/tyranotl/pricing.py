"""Published Claude rates and the four ways to run this job.

Rates are transcribed from Anthropic's pricing table (checked 2026-08-19), with
the five columns Anthropic publishes: base input, 5-minute cache write, 1-hour
cache write, cache hits/refreshes, output. **Do not quote these from memory in a
year's time** - re-read the pricing page and update this table.

The batch discount halves every column: the docs state the cache multipliers
"stack with other pricing modifiers, including the Batch API discount".
"""
from __future__ import annotations

import re

#: USD per 1M tokens. Longest key first when matching, so "claude-opus-4-8" is
#: never caught by a shorter "claude-opus-4" prefix.
PRICE_BY_MODEL: dict[str, dict[str, float]] = {
    "claude-fable-5":    {"in": 10.0, "w5m": 12.50, "w1h": 20.0, "read": 1.00, "out": 50.0},
    "claude-mythos-5":   {"in": 10.0, "w5m": 12.50, "w1h": 20.0, "read": 1.00, "out": 50.0},
    "claude-opus-5":     {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-8":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-7":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-6":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    # Sonnet 5 lists at $3/$15 with an introductory $2/$10 running through
    # 2026-08-31. The intro rate is what is billed today; swap it out after that.
    "claude-sonnet-5":   {"in": 2.0, "w5m": 2.50, "w1h": 4.0, "read": 0.20, "out": 10.0},
    "claude-sonnet-4-6": {"in": 3.0, "w5m": 3.75, "w1h": 6.0, "read": 0.30, "out": 15.0},
    "claude-haiku-4-5":  {"in": 1.0, "w5m": 1.25, "w1h": 2.0, "read": 0.10, "out": 5.0},
}

BATCH_DISCOUNT = 0.5

#: Output tokens per source token, measured at the end of a run.
#:
#:   CoinPussy   Sonnet 5, 5,680 units   2.36
#:   this game   Sonnet 5, 5,056 units   1.38   (134,638 out / 88,933 JP chars)
#:
#: The gap is scaffolding, not prose: CoinPussy's contract returned an object per
#: unit with speaker and notes fields, this one returns a bare id->string map.
#: Estimate with the ratio for the *output contract you are using*, not the game.
MEASURED_OUTPUT_RATIO = 1.4

#: Models that reject temperature/top_p/top_k with a 400.
NO_SAMPLING_RE = re.compile(r"(opus-(?:5|4-(?:[6-9]\b|[1-9]\d))|sonnet-5|fable-5|mythos-5)", re.I)

EFFORT_LEVELS = frozenset({"low", "medium", "high", "xhigh", "max"})


def price_for(model: str, batch: bool = False) -> dict[str, float]:
    lowered = (model or "").lower()
    rates = None
    for key in sorted(PRICE_BY_MODEL, key=len, reverse=True):
        if key in lowered:
            rates = PRICE_BY_MODEL[key]
            break
    if rates is None:
        rates = PRICE_BY_MODEL["claude-opus-5"]
    return dict(rates) if not batch else {k: v * BATCH_DISCOUNT for k, v in rates.items()}


def sampling_params(model: str) -> dict:
    return {} if NO_SAMPLING_RE.search(model or "") else {"temperature": 0}


def output_config(effort: str | None) -> dict:
    if effort and effort in EFFORT_LEVELS:
        return {"output_config": {"effort": effort}}
    return {}


def estimate_tokens(text: str) -> int:
    """Cheap proxy, per script. Japanese runs about one token per character;
    Latin runs about four characters per token, so a single ratio over a mixed
    prompt is badly wrong - the English rules-and-bible prefix came out 2.7x
    over-estimated before this was split (11,509 guessed vs 4,261 real).
    """
    jp = sum(1 for ch in text if "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿")
    return int(jp * 1.1 + (len(text) - jp) * 0.28) + 8


def four_ways(model: str, prefix_tokens: int, requests: int,
              variable_in: int, out_tokens: int) -> dict[str, float]:
    """Cost of the same job under batch/live x cached/uncached.

    ``prefix_tokens`` is the stable system prefix written once and re-read on
    every later request. Live runs use the 5-minute cache TTL (write 1.25x base),
    batch runs need the 1-hour TTL (2x base) because async requests are processed
    minutes apart and would miss a 5-minute window.
    """
    out: dict[str, float] = {}
    for mode, batch in (("batch", True), ("live", False)):
        rates = price_for(model, batch=batch)
        write_key = "w1h" if batch else "w5m"
        cached = (
            prefix_tokens * rates[write_key]
            + prefix_tokens * max(requests - 1, 0) * rates["read"]
            + variable_in * rates["in"]
            + out_tokens * rates["out"]
        ) / 1_000_000
        plain = (
            (prefix_tokens * requests + variable_in) * rates["in"]
            + out_tokens * rates["out"]
        ) / 1_000_000
        out[f"{mode}+cache"] = cached
        out[f"{mode} only"] = plain
    return out
