"""Capture and apply translation-engine settings that must survive batch resumes."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from util.id_ranges import normalize_id_ranges


RPGMAKER_PROFILE_ENGINE = "rpgmakermvmz"
RPGMAKER_PROFILE_VERSION = 1


def is_rpgmaker_mvmz(module_name: str) -> bool:
    normalized = str(module_name or "").casefold()
    return "mv/mz" in normalized or "rpg maker" in normalized


def capture_batch_runtime_profile(
    module_name: str,
    project_root: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return a JSON-safe snapshot of settings that define batch requests."""
    if not is_rpgmaker_mvmz(module_name):
        return None

    from gui.config_integration import ConfigIntegration

    integration = ConfigIntegration()
    if project_root is not None:
        integration.modules_dir = Path(project_root) / "modules"
    config = integration.read_current_config()
    plugin_config = integration.read_plugin_config()
    return {
        "engine": RPGMAKER_PROFILE_ENGINE,
        "version": RPGMAKER_PROFILE_VERSION,
        "config": dict(sorted(config.items())),
        "enabled_plugins_357": sorted(
            plugin_config.get("ENABLED_PLUGINS_357", set())
        ),
        "enabled_patterns_355655": sorted(
            plugin_config.get("ENABLED_PATTERNS_355655", set())
        ),
    }


def normalize_batch_runtime_profile(profile: Any) -> dict[str, Any] | None:
    """Validate and normalize a persisted profile without importing an engine."""
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise ValueError("Batch runtime profile is not an object")
    if profile.get("engine") != RPGMAKER_PROFILE_ENGINE:
        raise ValueError("Batch runtime profile targets an unsupported engine")
    if int(profile.get("version", 0) or 0) != RPGMAKER_PROFILE_VERSION:
        raise ValueError("Batch runtime profile version is unsupported")

    raw_config = profile.get("config")
    if not isinstance(raw_config, dict) or not raw_config:
        raise ValueError("Batch runtime profile has no RPG Maker configuration")
    config: dict[str, bool | int | str] = {}
    for key, value in raw_config.items():
        if not isinstance(key, str):
            raise ValueError("Batch runtime profile contains an invalid setting name")
        if key == "CODE122_VAR_RANGES":
            if not isinstance(value, str):
                raise ValueError(f"Batch runtime setting {key} has an invalid value")
            config[key] = normalize_id_ranges(value) if value.strip() else ""
            continue
        if not isinstance(value, (bool, int)):
            raise ValueError(f"Batch runtime setting {key} has an invalid value")
        config[key] = value

    def _names(key: str) -> list[str]:
        values = profile.get(key, [])
        if not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise ValueError(f"Batch runtime profile field {key} is invalid")
        return sorted(set(values))

    return {
        "engine": RPGMAKER_PROFILE_ENGINE,
        "version": RPGMAKER_PROFILE_VERSION,
        "config": dict(sorted(config.items())),
        "enabled_plugins_357": _names("enabled_plugins_357"),
        "enabled_patterns_355655": _names("enabled_patterns_355655"),
    }


def apply_batch_runtime_profile(module: Any, profile: Any) -> None:
    """Apply a validated profile to an already imported engine module."""
    normalized = normalize_batch_runtime_profile(profile)
    if normalized is None:
        return
    for key, value in normalized["config"].items():
        if hasattr(module, key):
            setattr(module, key, value)
    module.ENABLED_PLUGINS_357 = set(normalized["enabled_plugins_357"])
    module.ENABLED_PATTERNS_355655 = set(normalized["enabled_patterns_355655"])


def copy_batch_runtime_profile(profile: Any) -> dict[str, Any] | None:
    """Return a detached, normalized profile suitable for JSON metadata."""
    normalized = normalize_batch_runtime_profile(profile)
    return copy.deepcopy(normalized) if normalized is not None else None
