"""Opt-in desktop settings for external helpers; credentials stay in Python."""
from pathlib import Path
import os

from .settings import SettingsStore, validate_values


def public_values(workspace):
    store = SettingsStore(Path(workspace).expanduser().resolve(strict=True))
    values = validate_values(store.read()["values"])
    from util.api_keys import load_vault
    vault = load_vault(store.vault_path)
    entry = vault["keys"].get(vault["active"])
    if entry and entry["endpoint"]:
        values["api"] = entry["endpoint"]
    return values


def configure(workspace):
    workspace = Path(workspace).expanduser().resolve(strict=True)
    store = SettingsStore(workspace)
    from util import api_keys
    api_keys.API_KEYS_PATH = store.vault_path
    values = public_values(workspace)
    vault = api_keys.load_vault(store.vault_path)
    if vault["active"] in vault["keys"]:
        values = store.runtime()
    os.environ.pop("key", None)
    os.environ.pop("API_KEY_OPTIONAL", None)
    os.environ.update({key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in values.items()})
    os.environ.update(DAZEDTL_DESKTOP_WORKSPACE=str(workspace), PYTHON_DOTENV_DISABLED="1")
    return values
