"""Named API key vault for Config.

Secrets live in ``data/api_keys.json`` (user-local). The active secret is also
mirrored to ``.env`` ``key=`` so translation and subprocesses keep working.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from util.paths import DATA_DIR, ENV_PATH

API_KEYS_PATH = DATA_DIR / "api_keys.json"
DEFAULT_KEY_NAME = "Default"


def _empty_vault() -> dict[str, Any]:
    return {"active": "", "keys": {}}


def load_vault(path: Path | None = None) -> dict[str, Any]:
    """Load vault JSON. Returns ``{"active": "", "keys": {}}`` when missing/invalid."""
    vault_path = path or API_KEYS_PATH
    if not vault_path.is_file():
        return _empty_vault()
    try:
        data = json.loads(vault_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_vault()
    if not isinstance(data, dict):
        return _empty_vault()
    keys = data.get("keys")
    if not isinstance(keys, dict):
        keys = {}
    cleaned: dict[str, str] = {}
    for name, secret in keys.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if secret is None:
            continue
        cleaned[name.strip()] = str(secret)
    active = data.get("active") or ""
    if not isinstance(active, str):
        active = ""
    active = active.strip()
    if active and active not in cleaned:
        active = next(iter(cleaned), "")
    elif not active and cleaned:
        active = next(iter(cleaned))
    return {"active": active, "keys": cleaned}


def save_vault(vault: dict[str, Any], path: Path | None = None) -> None:
    """Write vault JSON with restrictive permissions when the OS allows."""
    vault_path = path or API_KEYS_PATH
    vault_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active": str(vault.get("active") or ""),
        "keys": dict(vault.get("keys") or {}),
    }
    tmp = vault_path.with_suffix(vault_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    tmp.replace(vault_path)
    try:
        os.chmod(vault_path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def list_names(path: Path | None = None) -> list[str]:
    """Return key names sorted case-insensitively."""
    vault = load_vault(path)
    return sorted(vault["keys"].keys(), key=lambda n: n.casefold())


def get_active_name(path: Path | None = None) -> str:
    return str(load_vault(path).get("active") or "")


def get_active_secret(path: Path | None = None) -> str:
    vault = load_vault(path)
    active = vault.get("active") or ""
    keys = vault.get("keys") or {}
    if active and active in keys:
        return str(keys[active])
    return ""


def get_secret(name: str, path: Path | None = None) -> str | None:
    keys = load_vault(path).get("keys") or {}
    if name not in keys:
        return None
    return str(keys[name])


def upsert_key(
    name: str,
    secret: str,
    *,
    make_active: bool = True,
    path: Path | None = None,
) -> dict[str, Any]:
    """Create or replace a named key. Optionally make it active."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Key name is required")
    secret = (secret or "").strip()
    if not secret:
        raise ValueError("API key secret is required")
    vault = load_vault(path)
    vault["keys"][name] = secret
    if make_active or not vault.get("active"):
        vault["active"] = name
    save_vault(vault, path)
    return vault


def delete_key(name: str, path: Path | None = None) -> dict[str, Any]:
    """Remove a named key. If it was active, pick another or clear active."""
    name = (name or "").strip()
    vault = load_vault(path)
    vault["keys"].pop(name, None)
    if vault.get("active") == name:
        vault["active"] = next(iter(sorted(vault["keys"], key=lambda n: n.casefold())), "")
    save_vault(vault, path)
    return vault


def set_active(name: str, path: Path | None = None) -> dict[str, Any]:
    """Set the active key by name. Raises if the name is unknown."""
    name = (name or "").strip()
    vault = load_vault(path)
    if name and name not in vault["keys"]:
        raise KeyError(f"Unknown API key: {name}")
    vault["active"] = name
    save_vault(vault, path)
    return vault


def sync_active_to_env(
    *,
    vault_path: Path | None = None,
    env_path: Path | None = None,
) -> str:
    """Write the active vault secret to ``.env`` ``key=`` and ``os.environ``.

    Returns the secret that was written (may be empty).
    """
    from dotenv import set_key

    secret = get_active_secret(vault_path)
    target = env_path or ENV_PATH
    if not target.exists():
        target.touch()
    set_key(target, "key", secret)
    os.environ["key"] = secret
    return secret


def migrate_from_env_if_empty(
    *,
    vault_path: Path | None = None,
    env_path: Path | None = None,
    env_key: str | None = None,
) -> dict[str, Any]:
    """If the vault has no keys, import ``key`` from ``.env`` as ``Default``.

    ``env_key`` overrides reading from disk (useful in tests).
    """
    vault = load_vault(vault_path)
    if vault["keys"]:
        return vault

    secret = env_key
    if secret is None:
        from dotenv import dotenv_values

        target = env_path or ENV_PATH
        values = dotenv_values(target) if target.is_file() else {}
        secret = (values.get("key") or os.getenv("key") or "").strip()
    else:
        secret = str(secret).strip()

    if not secret or secret.startswith("<"):
        return vault

    return upsert_key(
        DEFAULT_KEY_NAME,
        secret,
        make_active=True,
        path=vault_path,
    )


def ensure_vault(
    *,
    vault_path: Path | None = None,
    env_path: Path | None = None,
) -> dict[str, Any]:
    """Migrate from ``.env`` when needed and return the current vault."""
    return migrate_from_env_if_empty(vault_path=vault_path, env_path=env_path)
