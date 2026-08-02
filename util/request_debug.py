"""Bounded, opt-in provider request diagnostics.

These logs contain complete prompts, so callers must explicitly enable them.
Keeping the file handling here prevents provider routing code from also owning
rotation and serialization policy.
"""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path


_LOG_LOCK = threading.RLock()
_TRUE_VALUES = {"1", "true", "yes", "on"}


def usage_to_dict(usage) -> dict:
    """Extract portable token counts from provider usage objects."""
    if not usage:
        return {}

    result = {}
    for field in (
        "prompt_tokens",
        "completion_tokens",
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    ):
        value = getattr(usage, field, None)
        if value is not None:
            result[field] = value

    extra = getattr(usage, "model_extra", None)
    if isinstance(extra, dict):
        for field in ("cache_read_input_tokens", "cache_creation_input_tokens"):
            value = extra.get(field)
            if value is not None and field not in result:
                result[field] = value
    return result


def enabled(*, legacy_enabled: bool = False) -> bool:
    """Return whether sensitive request diagnostics were explicitly enabled."""
    value = os.getenv("debugRequestLogs")
    if value is None:
        return bool(legacy_enabled)
    return value.strip().lower() in _TRUE_VALUES


def append_rotating(path: Path, text: str, *, max_bytes: int, backups: int) -> None:
    """Append text while retaining at most ``backups`` rotated files."""
    with _LOG_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded_size = len(text.encode("utf-8"))
        current_size = path.stat().st_size if path.is_file() else 0
        if current_size and current_size + encoded_size > max_bytes:
            oldest = path.with_name(f"{path.name}.{backups}")
            oldest.unlink(missing_ok=True)
            for index in range(backups - 1, 0, -1):
                source = path.with_name(f"{path.name}.{index}")
                if source.is_file():
                    source.replace(path.with_name(f"{path.name}.{index + 1}"))
            path.replace(path.with_name(f"{path.name}.1"))
        with open(path, "a", encoding="utf-8") as debug_file:
            debug_file.write(text)
            debug_file.flush()


def write_request(
    provider,
    request_payload,
    usage,
    *,
    legacy_enabled: bool,
    max_bytes: int,
    backups: int,
    path: Path = Path("log/request_debug.log"),
) -> None:
    """Serialize one exact provider request when diagnostics are enabled."""
    if not enabled(legacy_enabled=legacy_enabled):
        return

    try:
        payload_text = json.dumps(
            request_payload, indent=2, ensure_ascii=False, default=str
        )
        usage_text = json.dumps(
            usage_to_dict(usage), indent=2, ensure_ascii=False, default=str
        )
        entry = (
            "\n=== API Request ===\n"
            f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Provider: {provider}\n"
            "Usage:\n"
            f"{usage_text}\n"
            "Payload:\n"
            f"{payload_text}\n"
        )
        append_rotating(path, entry, max_bytes=max_bytes, backups=backups)
    except Exception:
        # Request diagnostics must never break a translation request.
        pass
