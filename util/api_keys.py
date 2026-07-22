"""Named API key vault for Config.

Secrets live in ``data/api_keys.json`` (user-local). The active secret is also
mirrored to ``.env`` ``key=`` so translation and subprocesses keep working.

Each named entry may optionally include an ``endpoint`` (API base URL). When the
active key has one, it is mirrored to ``.env`` ``api=`` as well.
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


def _normalize_entry(raw: Any) -> dict[str, str]:
    """Accept legacy plain-string secrets or ``{secret, endpoint}`` objects."""
    if isinstance(raw, str):
        return {"secret": raw, "endpoint": ""}
    if isinstance(raw, dict):
        secret = raw.get("secret", raw.get("key", ""))
        endpoint = raw.get("endpoint", raw.get("api", ""))
        return {
            "secret": "" if secret is None else str(secret),
            "endpoint": ("" if endpoint is None else str(endpoint)).strip(),
        }
    return {"secret": "", "endpoint": ""}


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
    cleaned: dict[str, dict[str, str]] = {}
    for name, raw in keys.items():
        if not isinstance(name, str) or not name.strip():
            continue
        entry = _normalize_entry(raw)
        if not entry["secret"]:
            continue
        cleaned[name.strip()] = entry
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
    keys_out: dict[str, dict[str, str]] = {}
    for name, raw in dict(vault.get("keys") or {}).items():
        entry = _normalize_entry(raw)
        if not entry["secret"]:
            continue
        keys_out[str(name)] = {
            "secret": entry["secret"],
            "endpoint": entry["endpoint"],
        }
    payload = {
        "active": str(vault.get("active") or ""),
        "keys": keys_out,
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


def get_entry(name: str, path: Path | None = None) -> dict[str, str] | None:
    keys = load_vault(path).get("keys") or {}
    entry = keys.get(name)
    if entry is None:
        return None
    return _normalize_entry(entry)


def get_active_secret(path: Path | None = None) -> str:
    vault = load_vault(path)
    active = vault.get("active") or ""
    keys = vault.get("keys") or {}
    if active and active in keys:
        return _normalize_entry(keys[active])["secret"]
    return ""


def get_secret(name: str, path: Path | None = None) -> str | None:
    entry = get_entry(name, path)
    if entry is None:
        return None
    return entry["secret"]


def get_endpoint(name: str, path: Path | None = None) -> str | None:
    """Return the optional endpoint for *name*, or None if the key is unknown."""
    entry = get_entry(name, path)
    if entry is None:
        return None
    return entry["endpoint"]


def get_active_endpoint(path: Path | None = None) -> str:
    vault = load_vault(path)
    active = vault.get("active") or ""
    if not active:
        return ""
    return get_endpoint(active, path) or ""


def upsert_key(
    name: str,
    secret: str,
    *,
    endpoint: str = "",
    make_active: bool = True,
    path: Path | None = None,
    keep_secret_if_blank: bool = False,
) -> dict[str, Any]:
    """Create or replace a named key. Optionally make it active.

    When *keep_secret_if_blank* is true and *secret* is empty, an existing
    entry's secret is preserved (useful for editing endpoint only).
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("Key name is required")
    secret = (secret or "").strip()
    endpoint = (endpoint or "").strip()
    vault = load_vault(path)
    existing = vault["keys"].get(name)
    if not secret:
        if keep_secret_if_blank and existing:
            secret = _normalize_entry(existing)["secret"]
        else:
            raise ValueError("API key secret is required")
    vault["keys"][name] = {"secret": secret, "endpoint": endpoint}
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

    When the active key has an endpoint, also write ``api=``.
    Returns the secret that was written (may be empty).
    """
    from dotenv import set_key

    secret = get_active_secret(vault_path)
    endpoint = get_active_endpoint(vault_path)
    target = env_path or ENV_PATH
    if not target.exists():
        target.touch()
    set_key(target, "key", secret)
    os.environ["key"] = secret
    if endpoint:
        set_key(target, "api", endpoint)
        os.environ["api"] = endpoint
    return secret


def migrate_from_env_if_empty(
    *,
    vault_path: Path | None = None,
    env_path: Path | None = None,
    env_key: str | None = None,
    env_api: str | None = None,
) -> dict[str, Any]:
    """If the vault has no keys, import ``key`` / ``api`` from ``.env`` as ``Default``.

    ``env_key`` / ``env_api`` override reading from disk (useful in tests).
    """
    vault = load_vault(vault_path)
    if vault["keys"]:
        return vault

    secret = env_key
    endpoint = env_api
    if secret is None or endpoint is None:
        from dotenv import dotenv_values

        target = env_path or ENV_PATH
        values = dotenv_values(target) if target.is_file() else {}
        if secret is None:
            secret = (values.get("key") or os.getenv("key") or "").strip()
        if endpoint is None:
            endpoint = (values.get("api") or os.getenv("api") or "").strip()
    else:
        secret = str(secret).strip()
        endpoint = str(endpoint or "").strip()

    if not secret or secret.startswith("<"):
        return vault

    return upsert_key(
        DEFAULT_KEY_NAME,
        secret,
        endpoint=endpoint or "",
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
