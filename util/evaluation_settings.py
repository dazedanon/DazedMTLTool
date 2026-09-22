"""Model-aware generation settings for reproducible evaluation candidates."""

from __future__ import annotations

import re


DEFAULT_MAX_OUTPUT_TOKENS = 4096
MAX_OUTPUT_TOKEN_LIMIT = 128_000
SETTING_FIELDS = ("reasoning_effort", "effective_reasoning_effort", "max_output_tokens")
EFFORT_LABELS = {
    "none": "Off", "minimal": "Minimal", "low": "Low", "medium": "Medium",
    "high": "High", "xhigh": "Extra high", "max": "Maximum",
    "provider_default": "Provider default",
}


def reasoning_profile(candidate: dict) -> tuple[tuple[str, ...], str]:
    """Return supported efforts and the compatible low-cost default.

    Unknown models keep provider defaults instead of inheriting another
    model's API contract. Match aliases and dated snapshots, including routed IDs.
    Sources: developers.openai.com/api/docs/models and
    platform.claude.com/docs/en/build-with-claude/{effort,thinking-troubleshooting};
    ai.google.dev/gemini-api/docs/openai#thinking.
    """
    model = str(candidate.get("model") or "").lower().rsplit("/", 1)[-1]
    provider = candidate.get("provider")
    standard = ("low", "medium", "high")
    full = (*standard, "xhigh", "max")
    if provider == "anthropic":
        if re.match(r"claude-(?:opus-5-5(?:-|$)|fable-|mythos-)", model):
            levels = (*standard, "max") if "mythos-preview" in model else full
            return levels, "low"
        if re.match(r"claude-(?:opus-(?:5(?:-|$)|4-[78](?:-|$))|sonnet-5(?:-|$))", model):
            return ("none", *full), "none"
        if re.match(r"claude-(?:opus|sonnet)-4-6(?:-|$)", model):
            return ("none", *standard, "max"), "none"
        if re.match(r"claude-(?:opus|sonnet|haiku)-4(?:-|$)", model):
            # Legacy models require a manual thinking budget, not effort levels.
            return ("none",), "none"
    elif provider == "gemini":
        if re.match(r"gemini-(?:3[.-]|2\.5-)", model):
            levels = ("minimal", *standard)
            if model.startswith("gemini-2.5-flash"):
                levels = ("none", *levels)
            return levels, "minimal"
    elif provider == "openai":
        if re.match(r"gpt-6-astra(?:-|$)", model):
            return full, "low"
        if re.match(r"gpt-(?:6-(?:sol|luna)|5\.6-(?:sol|terra|luna))(?:-|$)", model):
            return ("none", *full), "none"
        if re.match(r"gpt-5\.[245](?:-\d{4}-\d{2}-\d{2})?$", model):
            return ("none", *standard, "xhigh"), "none"
        if re.match(r"gpt-5\.1(?:-\d{4}-\d{2}-\d{2})?$", model):
            return ("none", *standard), "none"
        if re.match(r"gpt-5(?:-(?:mini|nano))?(?:-\d{4}-\d{2}-\d{2})?$", model):
            return ("minimal", *standard), "minimal"
    return (), "provider_default"


def generation_settings(candidate: dict) -> dict:
    """Validate settings and resolve an auto choice, retaining a saved resolution."""
    levels, default = reasoning_profile(candidate)
    choice = candidate.get("reasoning_effort", "auto")
    if choice != "auto" and choice not in levels:
        raise ValueError(f"{candidate.get('model')}: unsupported reasoning effort {choice!r}")
    effective = candidate.get("effective_reasoning_effort", default if choice == "auto" else choice)
    allowed = levels or ("provider_default",)
    if effective not in allowed or (choice != "auto" and effective != choice):
        raise ValueError(f"{candidate.get('model')}: saved reasoning settings do not match this model")
    limit = candidate.get("max_output_tokens", DEFAULT_MAX_OUTPUT_TOKENS)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_OUTPUT_TOKEN_LIMIT:
        raise ValueError(f"Output token limit must be a whole number from 1 to {MAX_OUTPUT_TOKEN_LIMIT:,}")
    return {
        "reasoning_effort": choice,
        "effective_reasoning_effort": effective,
        "max_output_tokens": limit,
    }


def candidate_label(candidate: dict) -> str:
    """Distinguish model/effort comparisons while preserving legacy result labels."""
    label = str(candidate.get("label") or candidate.get("model") or candidate.get("id") or "")
    if any(field in candidate for field in SETTING_FIELDS):
        settings = generation_settings(candidate)
        effort = EFFORT_LABELS[settings["effective_reasoning_effort"]]
        label += f" / {effort} / {settings['max_output_tokens']:,} tokens"
    return label
