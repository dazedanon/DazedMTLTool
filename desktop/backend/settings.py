"""Desktop preferences and the existing credential vault, scoped to one profile."""
from __future__ import annotations

import json
import math
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from util import api_keys
from util.engine_options import ENGINE_PRESETS, engine_options, validate_engine_options
from util.paths import PROJECT_ROOT
from .project import atomic_json


def field(key, label, group, default, *, minimum=None, maximum=None, choices=None, help=""):
    kind = "boolean" if isinstance(default, bool) else "integer" if isinstance(default, int) else "number" if isinstance(default, float) else "string"
    result = {"key": key, "label": label, "group": group, "default": default, "type": "select" if choices else kind, "help": help}
    if minimum is not None:
        result.update(min=minimum, max=maximum)
    if choices:
        result["choices"] = choices
    return result


FIELDS = (
    field("api", "API endpoint", "Provider", "", help="Leave blank for the provider's default endpoint."),
    field("API_PROVIDER", "Provider protocol", "Provider", "openai", choices=["openai", "anthropic", "gemini", "mistral"]),
    field("model", "Model", "Provider", "gpt-4.1"),
    field("organization", "Organization", "Provider", ""),
    field("language", "Target language", "Translation", "English"),
    field("timeout", "Request timeout (seconds)", "Translation", 90, minimum=30, maximum=300),
    field("width", "Dialogue width", "Formatting", 60, minimum=20, maximum=200),
    field("faceWidth", "Dialogue with face image", "Formatting", 50, minimum=10, maximum=200),
    field("listWidth", "List width", "Formatting", 100, minimum=20, maximum=200),
    field("noteWidth", "Note width", "Formatting", 75, minimum=20, maximum=200),
    field("convertQuotes", "Convert Japanese quotation marks", "Formatting", True),
    field("useSfxReference", "Use the sound-effect reference", "Formatting", True),
    field("fileThreads", "Concurrent files", "Performance", 1, minimum=1, maximum=10),
    field("threads", "Requests per file", "Performance", 1, minimum=1, maximum=20),
    field("batchsize", "Text entries per request", "Performance", 30, minimum=1, maximum=100),
    field("frequency_penalty", "Frequency penalty", "Performance", 0.05, minimum=0, maximum=2),
    field("input_cost", "Input cost per million tokens ($)", "Pricing", 2.0, minimum=0, maximum=100),
    field("output_cost", "Output cost per million tokens ($)", "Pricing", 8.0, minimum=0, maximum=100),
    field("openaiBatchTokenLimit", "OpenAI batch input-token limit", "Batch & provider options", 600000, minimum=1, maximum=2000000000),
    field("batchPollInterval", "Batch polling interval (seconds)", "Batch & provider options", 60, minimum=1, maximum=3600),
    field("GEMINI_THINKING_BUDGET", "Gemini thinking budget", "Batch & provider options", "", help="Blank uses the model default; -1 enables dynamic thinking where supported."),
    field("mistralReqPerSec", "Mistral initial requests per second", "Batch & provider options", 0.5, minimum=0.05, maximum=1000000),
    field("mistralTokPerMin", "Mistral initial tokens per minute", "Batch & provider options", 50000, minimum=1, maximum=2000000000),
    field("mistralTokenHeadroom", "Mistral token headroom", "Batch & provider options", 4000, minimum=0, maximum=2000000000),
    field("wolfDbIncludeGroups", "WOLF database groups", "Advanced engine scope", "", help="Optional JSON array of group keys; use Guided workflow for the game-specific picker."),
    field("wolfDbIncludeTiers", "WOLF database tiers", "Advanced engine scope", "", help="Optional JSON array of tier names. Blank includes all tiers."),
    field("font_scale", "Interface scale", "Application", 1.0, minimum=0.5, maximum=3),
    field("translationCompletionAlert", "Notify when translation finishes", "Application", False),
    field("gameUpdateForge", "GameUpdate forge", "Game updates", "gitlab", choices=["gitlab", "gitea", "github"]),
    field("gameUpdateHost", "GameUpdate host", "Game updates", "gitgud.io"),
    field("gameUpdateUsername", "GameUpdate username", "Game updates", ""),
    field("gameUpdateBranch", "GameUpdate branch", "Game updates", "main"),
    field("tlEditorCmd", "Playtest editor", "Playtest", "auto"),
    field("tlHotkey", "TL Inspector hotkey", "Playtest", "F9"),
    field("forgeHotkey", "Forge hotkey", "Playtest", "F10"),
    field("playtestUiScale", "Playtest overlay scale", "Playtest", "auto"),
)


def validate_endpoint(value):
    if value:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.fragment:
            raise ValueError("Enter an HTTP or HTTPS endpoint without embedded credentials.")
    return value


def validate_values(values):
    schema = {item["key"]: item for item in FIELDS}
    if not isinstance(values, dict) or set(values) - schema.keys():
        raise ValueError("Unknown application setting.")
    result = {key: item["default"] for key, item in schema.items()}
    for key, value in values.items():
        item = schema[key]
        kind = item["type"]
        valid = (kind == "boolean" and isinstance(value, bool)
                 or kind == "integer" and type(value) is int
                 or kind == "number" and type(value) in {int, float} and math.isfinite(value)
                 or kind in {"string", "select"} and isinstance(value, str) and len(value) <= 2000 and "\x00" not in value)
        if not valid or "min" in item and not item["min"] <= value <= item["max"] or kind == "select" and value not in item["choices"]:
            raise ValueError(f"Invalid value for {item['label']}.")
        result[key] = value
    validate_endpoint(result["api"])
    for key in ("model", "language", "gameUpdateBranch"):
        if not result[key].strip():
            raise ValueError(f"{schema[key]['label']} is required.")
    thinking = result["GEMINI_THINKING_BUDGET"].strip()
    if thinking and not re.fullmatch(r"-1|\d+", thinking):
        raise ValueError("The thinking budget must be blank, -1, or a nonnegative integer.")
    result["faceWidth"] = min(result["width"], result["faceWidth"])
    for key in ('wolfDbIncludeGroups', 'wolfDbIncludeTiers'):
        if result[key].strip():
            try:
                selected = json.loads(result[key])
            except (TypeError, ValueError):
                raise ValueError(f"{schema[key]['label']} must be a JSON array of names.") from None
            if not isinstance(selected, list) or not all(isinstance(name, str) and name.strip() for name in selected):
                raise ValueError(f"{schema[key]['label']} must be a JSON array of names.")
    return result


class SettingsStore:
    def __init__(self, workspace, code_root=PROJECT_ROOT):
        self.root = Path(workspace) / "settings"
        self.path = self.root / "settings.json"
        self.vault_path = self.root / "api_keys.json"
        self.code_root = Path(code_root)

    def read(self):
        if not self.path.exists():
            return {"version": 1, "revision": 0, "values": validate_values({}), "engines": {}}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if value.get("version") != 1:
            raise ValueError("These preferences require a newer version of DazedTL.")
        return value

    def describe(self):
        from util.model_catalog import API_URL_PRESETS, ModelCatalogCore
        saved = self.read()
        vault = api_keys.load_vault(self.vault_path)
        schemas = engine_options(self.code_root)
        engines = {engine: {item["key"]: item["default"] for item in schema["fields"]} for engine, schema in schemas.items()}
        for engine, values in saved["engines"].items():
            engines.setdefault(engine, {}).update(values)
        draft_path = self.root / "draft.json"
        draft = json.loads(draft_path.read_text(encoding="utf-8")) if draft_path.is_file() else None
        return {**saved, "draft": draft, "presets": ENGINE_PRESETS, "values": {**validate_values({}), **saved["values"]}, "engines": engines,
                "fields": FIELDS, "engine_schemas": schemas, "endpoints": API_URL_PRESETS, "models": ModelCatalogCore.DEFAULTS,
                "active_key": vault["active"], "keys": [{"name": name, "endpoint": entry["endpoint"], "keyless": entry["keyless"],
                 "has_secret": bool(entry["secret"])} for name, entry in sorted(vault["keys"].items())]}

    def save(self, revision, values, engines):
        current = self.read()
        if type(revision) is not int or revision != current["revision"]:
            raise ValueError("Settings changed elsewhere. Reload before saving.")
        normalized = validate_values(values)
        normalized_engines = validate_engine_options(engines, self.code_root)
        atomic_json(self.path, {"version": 1, "revision": revision + 1, "values": normalized, "engines": normalized_engines})
        (self.root / "draft.json").unlink(missing_ok=True)
        return self.describe()

    def save_draft(self, revision, values, engines):
        # Drafts may hold incomplete numeric fields. They are never runtime
        # configuration until save() validates the whole document.
        if type(revision) is not int or revision < 0 or not isinstance(values, dict) or not isinstance(engines, dict):
            raise ValueError("Invalid settings draft.")
        if set(values) - {item["key"] for item in FIELDS}:
            raise ValueError("Unknown settings draft field.")
        schemas = engine_options(self.code_root)
        if set(engines) - schemas.keys() or any(not isinstance(value, dict) or set(value) - {item["key"] for item in schemas[key]["fields"]} for key, value in engines.items()):
            raise ValueError("Unknown engine draft field.")
        draft = {"revision": revision, "values": values, "engines": engines}
        if len(json.dumps(draft)) > 100000:
            raise ValueError("Settings draft is too large.")
        atomic_json(self.root / "draft.json", draft)
        return {"saved": True}

    def key_action(self, action, name, secret="", endpoint="", keyless=False):
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("Enter a credential name below 100 characters.")
        if action == "save":
            if not isinstance(secret, str) or len(secret) > 16000 or not isinstance(endpoint, str) or not isinstance(keyless, bool):
                raise ValueError("Invalid credential fields.")
            validate_endpoint(endpoint.strip())
            api_keys.upsert_key(name, secret, endpoint=endpoint, keyless=keyless, keep_secret_if_blank=True, path=self.vault_path)
        elif action == "select":
            api_keys.set_active(name, self.vault_path)
        elif action == "delete":
            api_keys.delete_key(name, self.vault_path)
        else:
            raise ValueError("Unknown credential action.")
        return self.describe()

    def runtime(self, values=None, key_name=None):
        """Private Python-only environment; never expose this through RPC."""
        config = validate_values(values if values is not None else self.read()["values"])
        vault = api_keys.load_vault(self.vault_path)
        selected = key_name if key_name is not None else vault["active"]
        entry = vault["keys"].get(selected)
        if not entry:
            raise ValueError("Select a saved API credential or a keyless local endpoint in Settings.")
        env = {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in config.items()}
        env["key"] = entry["secret"]
        env["API_KEY_OPTIONAL"] = "true" if entry["keyless"] else "false"
        if entry["endpoint"]:
            env["api"] = entry["endpoint"]
        return env

    def import_legacy(self, source, revision):
        """Copy explicit legacy settings into this profile without editing them."""
        from dotenv import dotenv_values
        folder = Path(source).expanduser().resolve(strict=True)
        path = folder / ".env"
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("Choose the existing DazedTL folder containing a regular .env file.")
        env = dotenv_values(path, interpolate=False)
        values = dict(self.read()["values"])
        for item in FIELDS:
            key = item["key"]
            if key not in env or env[key] is None:
                continue
            raw = env[key]
            try:
                values[key] = raw.casefold() in {"true", "1", "yes"} if item["type"] == "boolean" else int(raw) if item["type"] == "integer" else float(raw) if item["type"] == "number" else raw
            except (ValueError, TypeError):
                raise ValueError(f"The imported {item['label']} is invalid.") from None
        if "org" in env and "organization" not in env:
            values["organization"] = env["org"] or ""
        engines = {engine: {item["key"]: item["default"] for item in schema["fields"]} for engine, schema in engine_options(folder).items()}
        values = validate_values(values)
        engines = validate_engine_options(engines, self.code_root)
        if self.read()["revision"] != revision:
            raise ValueError("Settings changed elsewhere. Reload before importing.")
        legacy_vault_path = folder / "data/api_keys.json"
        if legacy_vault_path.is_symlink() or legacy_vault_path.exists() and legacy_vault_path.stat().st_size > 1_000_000:
            raise ValueError("The legacy credential vault is not a regular file below 1 MB.")
        imported = api_keys.load_vault(legacy_vault_path)
        if not imported["keys"] and env.get("key") and not env["key"].startswith("<"):
            imported = {"active": "Imported", "keys": {"Imported": {"secret": env["key"], "endpoint": values["api"], "keyless": False}}}
        existing = api_keys.load_vault(self.vault_path)
        # Existing names win: importing an old installation cannot replace a
        # key the user has already configured in this profile.
        for name, entry in imported["keys"].items():
            existing["keys"].setdefault(name, entry)
        existing["active"] = existing["active"] or imported["active"]
        api_keys.save_vault(existing, self.vault_path)
        return self.save(revision, values, engines)

    def transfer(self, action, source=""):
        saved = self.read()
        if action == "export":
            path = self.root / "exports" / ("dazedtl-settings-" + uuid.uuid4().hex[:10] + ".json")
            atomic_json(path, {"format": "dazedtl-settings", "version": 1,
                              "values": validate_values(saved["values"]),
                              "engines": validate_engine_options(saved["engines"], self.code_root)})
            return {"path": str(path)}
        if action != "import":
            raise ValueError("Choose settings import or export.")
        path = Path(source).expanduser()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
            raise ValueError("Choose a regular settings JSON or .env file below 1 MB.")
        if path.suffix.casefold() == ".json":
            value = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(value, dict):
                raise ValueError("Choose a supported DazedTL settings export.")
            if "format" in value:
                if value.get("format") != "dazedtl-settings" or value.get("version") != 1 or set(value) != {"format", "version", "values", "engines"}:
                    raise ValueError("Choose a supported DazedTL settings export.")
                values, engines = value["values"], value["engines"]
            else:
                # Qt's Save Project wrote the general settings as a flat JSON
                # object, including a key. Import only non-secret preferences.
                known = {field["key"] for field in FIELDS}
                if not set(value) & known or set(value) - known - {"key", "org"}:
                    raise ValueError("Choose a supported DazedTL project configuration.")
                values = {**saved["values"], **{key: item for key, item in value.items() if key in known}}
                if "org" in value and "organization" not in value:
                    values["organization"] = value["org"] or ""
                engines = saved["engines"]
        else:
            from dotenv import dotenv_values
            env = dotenv_values(path, interpolate=False)
            values = dict(saved["values"])
            for item in FIELDS:
                key = item["key"]
                if env.get(key) is not None:
                    raw = env[key]
                    try:
                        values[key] = raw.casefold() in {"true", "1", "yes"} if item["type"] == "boolean" else int(raw) if item["type"] == "integer" else float(raw) if item["type"] == "number" else raw
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"The imported {item['label']} is invalid.") from exc
            if "org" in env and "organization" not in env:
                values["organization"] = env["org"] or ""
            engines = saved["engines"]
        return {"revision": saved["revision"], "values": validate_values(values),
                "engines": validate_engine_options(engines, self.code_root)}
