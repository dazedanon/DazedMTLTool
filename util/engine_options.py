"""Validated engine options without importing translation SDKs or Qt."""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

from util.config_integration import ConfigIntegration
from util.id_ranges import normalize_id_ranges
from util.paths import PROJECT_ROOT

_CSV_PRESET_COMMON = {"SOURCE_COLUMN": 0, "TARGET_COLUMN": 1, "SPEAKER_COLUMN": -1,
                      "SKIP_HEADER_ROW": False, "USE_TARGET_IF_NOT_EMPTY": False,
                      "SKIP_IF_TARGET_TRANSLATED": False, "WRITE_TO_NEXT_COLUMN": False,
                      "PARSE_NAME_TAGS": False, "PARSE_M_MARKERS": False,
                      "REMOVE_FURIGANA": False, "SKIP_COMMENT_ROWS": False}
ENGINE_PRESETS = {"csv": {
    "Translator++": {**_CSV_PRESET_COMMON, "SKIP_HEADER_ROW": True, "USE_TARGET_IF_NOT_EMPTY": True},
    "Simple two-column": dict(_CSV_PRESET_COMMON),
    "Speaker & text": {**_CSV_PRESET_COMMON, "SOURCE_COLUMN": 9, "TARGET_COLUMN": 9, "SPEAKER_COLUMN": 2, "REMOVE_FURIGANA": True},
}}

ENGINE_OPTION_KEYS = {
    "csv": ("CSV_DELIMITER", "SOURCE_COLUMN", "TARGET_COLUMN", "SPEAKER_COLUMN", "SKIP_HEADER_ROW",
            "USE_TARGET_IF_NOT_EMPTY", "SKIP_IF_TARGET_TRANSLATED", "WRITE_TO_NEXT_COLUMN", "PARSE_NAME_TAGS",
            "PARSE_M_MARKERS", "REMOVE_FURIGANA", "SKIP_COMMENT_ROWS"),
    "wolf": ("CODE101", "CODE102", "CODE150", "CODE122", "CODE210", "CODE300", "CODE250", "SCENARIOFLAG",
             "OPTIONSFLAG", "NPCFLAG", "DBNAMEFLAG", "DBVALUEFLAG", "ITEMFLAG", "STATEFLAG", "ENEMYFLAG",
             "ARMORFLAG", "WEAPONFLAG", "SKILLFLAG"),
    "srpg": ("FIXTEXTWRAP", "IGNORETLTEXT"),
}
ENGINE_LABELS = {"rpgmakermvmz": "RPG Maker MV/MZ", "csv": "CSV", "wolf": "Wolf RPG (legacy)", "srpg": "SRPG Studio"}
LABELS = {
    "FIRSTLINESPEAKERS": "First dialogue line contains the speaker", "INLINE401SPEAKERS": "Detect inline speaker names",
    "FACENAME101": "Detect names from face images", "AUTONAMEPOPUP101": "Use AutoNamePopup face mapping",
    "NAMES": "Collect character names", "BRFLAG": "Use <br> line breaks", "FIXTEXTWRAP": "Rewrap translated text",
    "IGNORETLTEXT": "Skip already translated text", "PRESERVEORIGINAL": "Preserve original source fields",
    "TLSYSTEMVARIABLES": "Translate variable names", "TLSYSTEMSWITCHES": "Translate switch names",
    "JOIN408": "Join comment continuation lines", "SPEAKERS408": "Collect comment speakers",
    "CODE101": "Speaker names (101)", "CODE401": "Dialogue (401)", "CODE405": "Scrolling text (405)",
    "CODE102": "Choices (102)", "CODE408": "Supported comment continuations (408)",
    "CODE122": "Text variables (122)", "CODE122_VAR_RANGES": "Variable IDs and inclusive ranges",
    "CODE122_VAR_MIN": "Legacy variable range start", "CODE122_VAR_MAX": "Legacy variable range end",
    "CODE355655": "Script text (355 / 655)", "CODE357": "Plugin picture text (357)", "CODE657": "Extended picture text (657)",
    "CODE356": "Plugin commands (356)", "CODE320": "Character name changes (320)", "CODE324": "Nickname changes (324)",
    "CODE325": "Profile changes (325)", "CODE111": "Conditional branch text (111)", "CODE108": "Supported comments (108)",
    "ENABLED_PLUGINS_357": "Enabled plugin text handlers", "ENABLED_PATTERNS_355655": "Enabled script text handlers",
    "CSV_DELIMITER": "Delimiter", "SOURCE_COLUMN": "Source column", "TARGET_COLUMN": "Target column",
    "SPEAKER_COLUMN": "Speaker column (0 disables)", "PARSE_NAME_TAGS": "Parse :name[] tags", "PARSE_M_MARKERS": "Parse \\M markers",
    "SCENARIOFLAG": "Scenario database", "OPTIONSFLAG": "Options database", "NPCFLAG": "NPC database", "DBNAMEFLAG": "Database names",
    "DBVALUEFLAG": "Database values", "ITEMFLAG": "Items", "STATEFLAG": "States", "ENEMYFLAG": "Enemies",
    "ARMORFLAG": "Armor", "WEAPONFLAG": "Weapons", "SKILLFLAG": "Skills",
}


@lru_cache(maxsize=16)
def _literals(path_string, modified):
    values = {}
    for node in ast.parse(Path(path_string).read_text(encoding="utf-8")).body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "set" and not node.value.args:
                    values[target.id] = set()
    return values


def engine_options(code_root=PROJECT_ROOT):
    result = {}
    for engine, label in ENGINE_LABELS.items():
        path = Path(code_root) / "modules" / (engine + ".py")
        if not path.is_file():
            continue
        literals = _literals(str(path), path.stat().st_mtime_ns)
        if engine == "rpgmakermvmz":
            integration = ConfigIntegration()
            values = integration.read_current_config(path)
            values.update({key: sorted(value) for key, value in integration.read_plugin_config(path).items()})
        else:
            values = {key: literals[key] for key in ENGINE_OPTION_KEYS[engine] if key in literals}
        fields = []
        for key, value in values.items():
            kind = "boolean" if isinstance(value, bool) else "integer" if isinstance(value, int) else "choices" if isinstance(value, list) else "string"
            field = {"key": key, "label": LABELS.get(key, key.replace("_", " ").capitalize()), "type": kind, "default": value}
            if key in {"SOURCE_COLUMN", "TARGET_COLUMN", "SPEAKER_COLUMN"}:
                field.update(min=-1 if key == "SPEAKER_COLUMN" else 0, max=99, display_offset=1)
            elif kind == "integer":
                field.update(min=0, max=999999)
            if key == "CSV_DELIMITER":
                field.update(type="select", choices=[",", ";", "\t"])
            if key == "ENABLED_PLUGINS_357":
                field["choices"] = sorted(literals.get("HEADER_MAPPINGS_357", {}))
            if key == "ENABLED_PATTERNS_355655":
                field["choices"] = sorted(literals.get("PATTERNS_355655", {}))
            fields.append(field)
        result[engine] = {"label": label, "fields": fields}
    return result


def validate_engine_options(overrides, code_root=PROJECT_ROOT):
    schema = engine_options(code_root)
    if not isinstance(overrides, dict) or set(overrides) - schema.keys():
        raise ValueError("Unknown engine configuration.")
    result = {}
    for engine, values in overrides.items():
        fields = {field["key"]: field for field in schema[engine]["fields"]}
        if not isinstance(values, dict) or set(values) - fields.keys():
            raise ValueError("Unknown engine option.")
        result[engine] = {}
        for key, value in values.items():
            field = fields[key]
            kind = field["type"]
            valid = (kind == "boolean" and isinstance(value, bool)
                     or kind == "integer" and type(value) is int and field["min"] <= value <= field["max"]
                     or kind in {"string", "select"} and isinstance(value, str) and len(value) <= 16000
                     or kind == "choices" and isinstance(value, list) and all(isinstance(item, str) and item in field["choices"] for item in value))
            if not valid or kind == "select" and value not in field["choices"]:
                raise ValueError(f"Invalid value for {field['label']}.")
            if key == "CODE122_VAR_RANGES" and value.strip():
                value = normalize_id_ranges(value)
            result[engine][key] = sorted(set(value)) if kind == "choices" else value
    return result


def apply_engine_options(module, overrides):
    """Apply an already validated immutable job snapshot to its engine."""
    engine = module.__name__.split(".")[-1]
    for key, value in overrides.get(engine, {}).items():
        if not hasattr(module, key):
            raise ValueError(f"The installed engine no longer supports {key}; create a new run.")
        setattr(module, key, set(value) if key.startswith("ENABLED_") else value)
