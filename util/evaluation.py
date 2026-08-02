"""Provider-neutral Japanese-to-English translation evaluation workflow.

The evaluator deliberately does not use ``log/translation_cache.json`` or the
normal active ``.env`` credential. One immutable logical request manifest is
adapted to each provider. Prepared and active work lives under
``log/evaluation_work/``; only completed runs are archived under
``log/evaluations/``.
"""

from __future__ import annotations

import copy
import csv
import hashlib
import json
import os
import random
import re
import shutil
import tempfile
import threading
import time
import zipfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

from util import batch_providers as batch_api
from util.paths import read_active_glossary, read_game_glossary
from util.project_scanner import find_data_folder
from util.sfx_reference import sfx_reference_identity
from util.skills import load_system_prompt
from util.translation import (
    buildClaudeRequest,
    buildOpenAIRequest,
    createContextParts,
    countTokens,
    extractTranslation,
    getPricingConfig,
    protect_script_codes,
    restore_script_codes,
    TranslationConfig,
    validate_control_codes,
    validate_placeholders,
    validate_translation_content,
    translation_content_warnings,
)


EVALUATION_VERSION = 5
EVALUATION_ARCHIVE_VERSION = 1
MANIFEST_HASH_VERSION = 2
ARTIFACT_BINDING_VERSION = 5
DEFAULT_SAMPLE_SIZE = 10
DEFAULT_BATCH_SIZE = DEFAULT_SAMPLE_SIZE  # Backward-compatible public alias.
DEFAULT_SEGMENTS = 360
DEFAULT_STABILITY_SEGMENTS = 120
DEFAULT_STABILITY_SAMPLES = 12
DEFAULT_REPETITIONS = 3
DEFAULT_BUDGET_USD = 10.0
MAX_SAVED_EVALUATIONS = 50
EVALUATION_ARCHIVE_DIR = "evaluations"
EVALUATION_WORK_DIR = "evaluation_work"
REVIEW_SYSTEM_PROMPT_FILENAME = "review_system_prompt.md"
REVIEW_GLOSSARY_FILENAME = "review_glossary.txt"
REVIEW_SFX_REFERENCE_FILENAME = "review_sfx_reference.txt"
REVIEW_QUALITY_METRICS = (
    "meaning_accuracy",
    "glossary_prompt",
    "natural_contextual",
)
MAX_OUTPUT_TOKENS_PER_REQUEST = 4096
LIVE_REQUEST_MAX_ATTEMPTS = 3
ATOMIC_REPLACE_MAX_ATTEMPTS = 8
ATOMIC_REPLACE_INITIAL_DELAY_SECONDS = 0.05
ATOMIC_REPLACE_MAX_DELAY_SECONDS = 0.5
JAPANESE_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]")
LANGUAGE_REGEX = r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+"

DEFAULT_CANDIDATES = (
    {"provider": "openai", "endpoint": "https://api.openai.com/v1", "model": "gpt-5.6-terra", "label": "GPT-5.6 Terra", "execution": "batch"},
    {"provider": "gemini", "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/", "model": "gemini-3.6-flash", "label": "Gemini 3.6 Flash", "execution": "batch"},
    {"provider": "anthropic", "endpoint": "https://api.anthropic.com", "model": "claude-sonnet-5", "label": "Claude Sonnet 5", "execution": "batch"},
)

_DATABASE_FIELDS = {
    "Actors.json": ("name", "nickname", "profile"),
    "Armors.json": ("name", "description"),
    "Classes.json": ("name",),
    "Enemies.json": ("name",),
    "Items.json": ("name", "description"),
    "MapInfos.json": ("name",),
    "Skills.json": ("name", "description", "message1", "message2", "message3", "message4"),
    "States.json": ("name", "message1", "message2", "message3", "message4"),
    "Weapons.json": ("name", "description"),
}
CONTENT_SOURCE_GROUPS = (
    ("events", "Dialogue and events", (
        ("map_events", "Map files (events/dialogue)"),
        ("common_events", "Common Events"),
        ("troop_events", "Troop/battle events"),
    )),
    ("database", "Database", (
        ("actors", "Actors"),
        ("classes", "Classes"),
        ("skills", "Skills"),
        ("items", "Items"),
        ("weapons", "Weapons"),
        ("armors", "Armors"),
        ("enemies", "Enemies"),
        ("states", "States"),
        ("map_names", "Map names"),
    )),
)
EVENT_CONTENT_SOURCES = ("map_events", "common_events", "troop_events")
DATABASE_CONTENT_SOURCES = tuple(
    source_id for group_id, _label, sources in CONTENT_SOURCE_GROUPS
    if group_id == "database" for source_id, _source_label in sources
)
ALL_CONTENT_SOURCES = EVENT_CONTENT_SOURCES + DATABASE_CONTENT_SOURCES
CONTENT_PRESET_SOURCES = {
    "balanced": ALL_CONTENT_SOURCES,
    "events": EVENT_CONTENT_SOURCES,
    "database": DATABASE_CONTENT_SOURCES,
}
_DATABASE_SOURCE_CATEGORIES = {
    "Actors.json": "actors",
    "Armors.json": "armors",
    "Classes.json": "classes",
    "Enemies.json": "enemies",
    "Items.json": "items",
    "MapInfos.json": "map_names",
    "Skills.json": "skills",
    "States.json": "states",
    "Weapons.json": "weapons",
}
_CORPUS_CAPTURE_LOCK = threading.RLock()


def _is_evaluation_data_folder(folder: Path) -> bool:
    """Return whether *folder* contains RPG Maker MV/MZ JSON we can evaluate."""
    if not folder.is_dir():
        return False
    supported = {name.casefold() for name in _DATABASE_FIELDS}
    supported.update({"commonevents.json", "troops.json"})
    try:
        return any(
            child.is_file()
            and (
                child.name.casefold() in supported
                or bool(re.fullmatch(r"map\d+\.json", child.name, re.IGNORECASE))
            )
            for child in folder.iterdir()
        )
    except PermissionError:
        return False


def resolve_rpgmaker_data_dir(selected_dir: str | Path) -> Path:
    """Resolve an MV/MZ game folder (or direct JSON folder) for evaluation.

    RPG Maker MZ normally stores JSON under ``data/`` and MV deployments use
    ``www/data/``. Direct JSON folders remain accepted for compatibility with
    the tool's existing ``files/`` workflow.
    """
    raw_selection = str(selected_dir).strip()
    if not raw_selection:
        raise ValueError("Select an RPG Maker MV/MZ game folder.")
    selected = Path(raw_selection).expanduser()
    if not selected.is_dir():
        raise FileNotFoundError(f"RPG Maker game folder does not exist: {selected}")
    selected = selected.resolve()
    if _is_evaluation_data_folder(selected):
        return selected

    detected, engine = find_data_folder(selected)
    if detected is not None and engine in {"MVMZ", "UNKNOWN"}:
        detected = detected.resolve()
        if _is_evaluation_data_folder(detected):
            return detected

    raise ValueError(
        "No supported RPG Maker MV/MZ JSON data was found. Select the game "
        "folder containing data/ or www/data/, or select that JSON data folder "
        "directly. RPG Maker XP, VX, and VX Ace data files are not supported "
        "by Evaluation."
    )


def resolve_evaluation_game_root(
    selected_dir: str | Path,
    *,
    fallback_game_root: str | Path | None = None,
) -> Path | None:
    """Resolve the game root whose normal translation context Evaluation uses.

    An explicitly selected game root wins. Standard direct ``data`` and
    ``www/data`` selections are mapped back to their game root. The tool's
    extracted ``files`` directory has no reliable parent relationship to the
    game, so it uses the workflow's configured game root when supplied.
    """
    selected = Path(str(selected_dir).strip()).expanduser().resolve()
    data_dir = resolve_rpgmaker_data_dir(selected)
    if selected != data_dir:
        return selected

    if selected.name.casefold() == "data":
        parent = selected.parent
        return parent.parent if parent.name.casefold() == "www" else parent

    if (selected / "glossary.txt").is_file() or (selected / "skills").is_dir():
        return selected

    fallback_text = str(fallback_game_root or "").strip()
    if not fallback_text:
        return None
    fallback = Path(fallback_text).expanduser().resolve()
    if not fallback.is_dir():
        return None
    try:
        resolve_rpgmaker_data_dir(fallback)
    except (FileNotFoundError, ValueError):
        return None
    return fallback


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    payload = value if isinstance(value, bytes) else _json_bytes(value)
    return hashlib.sha256(payload).hexdigest()


def _manifest_digest(manifest: dict) -> str:
    """Return the stable digest stored with a frozen evaluation manifest."""
    return _sha256({
        key: value
        for key, value in manifest.items()
        if key not in {"created_at", "manifest_sha256"}
    })


def _validate_manifest_integrity(state: dict, manifest: dict) -> None:
    """Reject changed modern manifests while accepting pre-hash legacy runs."""
    state_hash = state.get("manifest_sha256")
    manifest_hash = manifest.get("manifest_sha256")
    versions = []
    for value in (state.get("version"), manifest.get("version")):
        try:
            if value is not None:
                versions.append(int(value))
        except (TypeError, ValueError):
            raise ValueError("Evaluation manifest integrity check failed: invalid version")
    requires_hashes = any(version >= MANIFEST_HASH_VERSION for version in versions)
    if state_hash is None and manifest_hash is None:
        if requires_hashes:
            raise ValueError(
                "Evaluation manifest integrity check failed: a modern run is "
                "missing its saved manifest hash"
            )
        return
    saved_hashes = [
        value for value in (state_hash, manifest_hash) if value is not None
    ]
    if any(
        not isinstance(value, str)
        or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in saved_hashes
    ):
        raise ValueError(
            "Evaluation manifest integrity check failed: saved hash is invalid"
        )
    if len(saved_hashes) == 2 and state_hash != manifest_hash:
        raise ValueError(
            "Evaluation manifest integrity check failed: state and manifest "
            "hashes differ"
        )
    if _manifest_digest(manifest) != saved_hashes[0]:
        raise ValueError(
            "Evaluation manifest integrity check failed: manifest contents "
            "have changed"
        )


def _requires_artifact_binding(state: dict, manifest: dict) -> bool:
    for value in (state.get("version"), manifest.get("version")):
        try:
            if value is not None and int(value) >= ARTIFACT_BINDING_VERSION:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _candidate_artifact_identity(candidate: dict, manifest: dict) -> dict[str, str]:
    return {
        "candidate_id": str(candidate.get("id") or ""),
        "model": str(candidate.get("model") or ""),
        "provider": str(candidate.get("provider") or ""),
        "execution": str(candidate.get("execution") or "batch"),
        "endpoint": str(candidate.get("endpoint") or ""),
        "manifest_sha256": str(
            manifest.get("manifest_sha256") or _manifest_digest(manifest)
        ),
    }


def _validate_result_artifact(
    candidate: dict, result: dict, state: dict, manifest: dict,
) -> None:
    """Verify a result belongs to this candidate and frozen request manifest."""
    if not isinstance(result, dict):
        raise ValueError("Evaluation result artifact is invalid")
    expected = _candidate_artifact_identity(candidate, manifest)
    required = _requires_artifact_binding(state, manifest)
    for field, expected_value in expected.items():
        actual = result.get(field)
        if actual is None and not required:
            continue
        if str(actual or "") != expected_value:
            raise ValueError(
                f"Evaluation result for {candidate.get('label') or candidate.get('id')} "
                f"has the wrong {field.replace('_', ' ')}"
            )

    executions = result.get("executions")
    if not isinstance(executions, dict):
        raise ValueError("Evaluation result artifact has invalid executions")
    expected_executions = {
        str(item["id"]): item for item in manifest.get("executions") or []
    }
    requests = _request_lookup(manifest)
    for execution_id, artifact in executions.items():
        expected_execution = expected_executions.get(str(execution_id))
        if expected_execution is None or not isinstance(artifact, dict):
            raise ValueError(
                f"Evaluation result contains an unknown execution {execution_id!r}"
            )
        request_id = str(expected_execution["logical_request_id"])
        request = requests.get(request_id)
        expected_fields = {
            "logical_request_id": request_id,
            "repetition": expected_execution["repetition"],
            "logical_hash": (request or {}).get("logical_hash"),
        }
        for field, expected_value in expected_fields.items():
            actual = artifact.get(field)
            if actual is None and not required:
                continue
            if actual != expected_value:
                raise ValueError(
                    f"Evaluation result execution {execution_id!r} has the wrong "
                    f"{field.replace('_', ' ')}"
                )
        if request is not None:
            lines = artifact.get("lines")
            if not isinstance(lines, list):
                raise ValueError(
                    f"Evaluation result execution {execution_id!r} has invalid lines"
                )
            actual_segments = [
                str(line.get("segment_id") or "")
                for line in lines if isinstance(line, dict)
            ]
            if len(actual_segments) != len(lines) or actual_segments != [
                str(segment_id) for segment_id in request.get("segment_ids") or []
            ]:
                raise ValueError(
                    f"Evaluation result execution {execution_id!r} has the wrong segments"
                )


def _is_retryable_replace_error(exc: OSError) -> bool:
    """Return whether a replace may succeed after a transient file lock clears."""
    return isinstance(exc, PermissionError) or getattr(exc, "winerror", None) in {
        5,   # ERROR_ACCESS_DENIED
        32,  # ERROR_SHARING_VIOLATION
        33,  # ERROR_LOCK_VIOLATION
    }


def _replace_with_retry(temporary: Path, path: Path) -> None:
    delay = ATOMIC_REPLACE_INITIAL_DELAY_SECONDS
    for attempt in range(1, ATOMIC_REPLACE_MAX_ATTEMPTS + 1):
        try:
            os.replace(temporary, path)
            return
        except OSError as exc:
            if (
                not _is_retryable_replace_error(exc)
                or attempt == ATOMIC_REPLACE_MAX_ATTEMPTS
            ):
                raise
            time.sleep(delay)
            delay = min(delay * 2, ATOMIC_REPLACE_MAX_DELAY_SECONDS)


def _atomic_write_text_exact(path: Path, value: str) -> None:
    """Write text through a unique sibling and atomically replace the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        stream = os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")
        descriptor = -1  # The stream now owns and closes the descriptor.
        with stream:
            stream.write(value)
        _replace_with_retry(temporary, path)
    finally:
        if descriptor != -1:
            os.close(descriptor)
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            # Do not hide the original write/replace error if a scanner still
            # has the abandoned temporary file open.
            pass


def _atomic_write_json(path: Path, value: Any) -> None:
    _atomic_write_text_exact(
        path,
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
    )


def _atomic_write_text(path: Path, value: str) -> None:
    _atomic_write_text_exact(path, value.rstrip() + "\n")


def _read_json(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected an object in {path}")
    return data


def _normalize_history(history: Any) -> list[str]:
    if isinstance(history, list):
        return [str(item) for item in history if str(item).strip()]
    if history is None or not str(history).strip():
        return []
    return [str(history)]


def pricing_for(model: str, *, on_date: date | None = None) -> dict[str, float]:
    """Return provider Batch API rates per million tokens.

    Pinned evaluation models use audited rates; other models use the tool's
    live pricing catalog or provider-family fallback with the batch discount.
    """
    model_l = str(model or "").lower()
    today = on_date or date.today()
    if "gpt-5.6-terra" in model_l:
        return {"input": 1.25, "cached_input": 0.125, "output": 7.50}
    if "gemini-3.6-flash" in model_l:
        return {"input": 0.75, "cached_input": 0.075, "output": 3.75}
    if "claude-sonnet-5" in model_l:
        if today < date(2026, 9, 1):
            return {"input": 1.00, "cached_input": 0.10, "output": 5.00}
        return {"input": 1.50, "cached_input": 0.15, "output": 7.50}
    # The normal pricing resolver combines the live LiteLLM catalog with the
    # tool's provider-family fallbacks. Evaluation jobs use provider Batch APIs,
    # so apply the standard 50% batch discount here.
    pricing = getPricingConfig(model)
    input_rate = float(pricing["inputAPICost"]) * 0.50
    output_rate = float(pricing["outputAPICost"]) * 0.50
    if input_rate <= 0 or output_rate <= 0:
        raise ValueError(f"No usable pricing is available for model {model!r}")
    return {
        "input": input_rate,
        "cached_input": input_rate * 0.10,
        "output": output_rate,
    }


def _event_source_category(filename: str) -> str:
    if re.fullmatch(r"Map\d+\.json", filename, re.IGNORECASE):
        return "map_events"
    if filename.casefold() == "commonevents.json":
        return "common_events"
    if filename.casefold() == "troops.json":
        return "troop_events"
    raise ValueError(f"Unsupported RPG Maker event source {filename!r}")


def _capture_page_data(
    page: dict | list,
    filename: str,
    location: dict,
    *,
    glossary: str | None = None,
) -> list[dict]:
    """Capture the exact groups the RPG Maker event parser would translate."""
    import modules.rpgmakermvmz as rpgmaker

    captured: list[tuple[list[str], list[str]]] = []

    def capture(text, history, *_args, **_kwargs):
        if isinstance(text, list):
            captured.append((copy.deepcopy(text), _normalize_history(history)))
        return [copy.deepcopy(text), [0, 0]]

    with _CORPUS_CAPTURE_LOCK:
        original_translate = rpgmaker.translateAI
        original_names = list(rpgmaker.NAMESLIST)
        original_collected = list(rpgmaker.SPEAKER_COLLECTED)
        original_speaker_mode = rpgmaker.SPEAKER_PARSE_MODE
        original_preflight_mode = rpgmaker.PREFLIGHT_COUNT_MODE
        original_mismatches = list(rpgmaker.MISMATCH)
        original_pbar = rpgmaker.PBAR
        original_vocab = rpgmaker.VOCAB
        original_config_vocab = rpgmaker.TRANSLATION_CONFIG.vocab
        original_vocab_source = rpgmaker._speakerVocabSource
        original_vocab_exact = dict(rpgmaker._speakerVocabExact)
        original_vocab_pairs = list(rpgmaker._speakerVocabCharacterPairs)
        with rpgmaker._speakerCacheLock:
            original_speaker_cache = dict(rpgmaker._speakerCache)
        rpgmaker.translateAI = capture
        rpgmaker.SPEAKER_PARSE_MODE = False
        rpgmaker.PREFLIGHT_COUNT_MODE = False
        rpgmaker.NAMESLIST[:] = []
        rpgmaker.SPEAKER_COLLECTED[:] = []
        with rpgmaker._speakerCacheLock:
            rpgmaker._speakerCache.clear()
        if glossary is not None:
            rpgmaker.VOCAB = glossary
            rpgmaker.TRANSLATION_CONFIG.vocab = glossary
            rpgmaker._speakerVocabSource = None
            rpgmaker._speakerVocabExact = {}
            rpgmaker._speakerVocabCharacterPairs = []
        try:
            rpgmaker.searchCodes(copy.deepcopy(page), None, [], filename)
        finally:
            rpgmaker.translateAI = original_translate
            rpgmaker.NAMESLIST[:] = original_names
            rpgmaker.SPEAKER_COLLECTED[:] = original_collected
            rpgmaker.SPEAKER_PARSE_MODE = original_speaker_mode
            rpgmaker.PREFLIGHT_COUNT_MODE = original_preflight_mode
            rpgmaker.MISMATCH[:] = original_mismatches
            rpgmaker.PBAR = original_pbar
            rpgmaker.VOCAB = original_vocab
            rpgmaker.TRANSLATION_CONFIG.vocab = original_config_vocab
            rpgmaker._speakerVocabSource = original_vocab_source
            rpgmaker._speakerVocabExact = original_vocab_exact
            rpgmaker._speakerVocabCharacterPairs = original_vocab_pairs
            with rpgmaker._speakerCacheLock:
                rpgmaker._speakerCache.clear()
                rpgmaker._speakerCache.update(original_speaker_cache)

    segments: list[dict] = []
    for call_index, (items, initial_history) in enumerate(captured):
        location_key = ":".join(f"{key}-{value}" for key, value in location.items())
        scene_id = f"{filename}:{location_key}:call-{call_index + 1}"
        for item_index, item in enumerate(items):
            source = str(item)
            if not JAPANESE_RE.search(source):
                continue
            stratum = "code_heavy" if "\\" in source else "event_text"
            segments.append({
                "id": f"{scene_id}:item-{item_index + 1}",
                "scene_id": scene_id,
                "stratum": stratum,
                "source_category": _event_source_category(filename),
                "source": source,
                "initial_history": initial_history,
                "source_location": {
                    "file": filename,
                    **location,
                    "translation_call": call_index + 1,
                    "item": item_index + 1,
                },
            })
    return segments


def _source_field(record: dict, field: str) -> Any:
    original = record.get("_original")
    if isinstance(original, dict) and isinstance(original.get(field), str):
        return original[field]
    return record.get(field)


def _database_segments(files_dir: Path) -> list[dict]:
    segments: list[dict] = []
    for filename, fields in _DATABASE_FIELDS.items():
        path = files_dir / filename
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        for index, record in enumerate(data):
            if not isinstance(record, dict):
                continue
            record_id = record.get("id", index)
            for field in fields:
                source = _source_field(record, field)
                if not isinstance(source, str) or not JAPANESE_RE.search(source):
                    continue
                scene_id = f"{filename}:record-{record_id}"
                segments.append({
                    "id": f"{scene_id}:{field}",
                    "scene_id": scene_id,
                    "stratum": "database",
                    "source_category": _DATABASE_SOURCE_CATEGORIES[filename],
                    "source": source,
                    "initial_history": [],
                    "source_location": {
                        "file": filename,
                        "record_id": record_id,
                        "field": field,
                    },
                })
    return segments


def _event_segments(files_dir: Path, *, glossary: str | None = None) -> list[dict]:
    segments: list[dict] = []
    map_pattern = re.compile(r"^Map\d+\.json$", re.IGNORECASE)
    for path in sorted(files_dir.glob("*.json"), key=lambda item: item.name.casefold()):
        filename = path.name
        if not map_pattern.match(filename) and filename not in {
            "CommonEvents.json", "Troops.json"
        }:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read RPG Maker JSON file {filename}: {exc}") from exc

        if map_pattern.match(filename):
            events = data.get("events", []) if isinstance(data, dict) else []
            for event_index, event in enumerate(events or []):
                if not isinstance(event, dict):
                    continue
                event_id = event.get("id", event_index)
                for page_index, page in enumerate(event.get("pages", []) or []):
                    if isinstance(page, (dict, list)):
                        segments.extend(_capture_page_data(
                            page, filename,
                            {"event": event_id, "page": page_index + 1},
                            glossary=glossary,
                        ))
            display_name = data.get("displayName") if isinstance(data, dict) else None
            if isinstance(display_name, str) and JAPANESE_RE.search(display_name):
                segments.append({
                    "id": f"{filename}:displayName",
                    "scene_id": f"{filename}:metadata",
                    "stratum": "database",
                    "source_category": "map_names",
                    "source": display_name,
                    "initial_history": [],
                    "source_location": {"file": filename, "field": "displayName"},
                })
        elif filename == "CommonEvents.json" and isinstance(data, list):
            for index, event in enumerate(data):
                if isinstance(event, dict) and isinstance(event.get("list"), list):
                    segments.extend(_capture_page_data(
                        event, filename, {"common_event": event.get("id", index)},
                        glossary=glossary,
                    ))
        elif filename == "Troops.json" and isinstance(data, list):
            for troop_index, troop in enumerate(data):
                if not isinstance(troop, dict):
                    continue
                for page_index, page in enumerate(troop.get("pages", []) or []):
                    if isinstance(page, (dict, list)):
                        segments.extend(_capture_page_data(
                            page, filename,
                            {"troop": troop.get("id", troop_index), "page": page_index + 1},
                            glossary=glossary,
                        ))
    return segments


def scan_corpus(files_dir: str | Path, *, glossary: str | None = None) -> list[dict]:
    """Extract eligible Japanese text from any RPG Maker MV/MZ JSON folder."""
    root = Path(files_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"RPG Maker folder does not exist: {root}")
    segments = _event_segments(root, glossary=glossary) + _database_segments(root)
    unique: dict[str, dict] = {}
    for segment in segments:
        unique.setdefault(segment["id"], segment)
    return list(unique.values())


def normalize_content_selection(selection: dict | None = None) -> dict:
    """Return a validated, manifest-safe benchmark content selection."""
    raw = dict(selection or {})
    preset = str(raw.get("preset") or "balanced").strip().lower()
    if preset not in {*CONTENT_PRESET_SOURCES, "custom"}:
        raise ValueError(f"Unknown benchmark content preset {preset!r}")
    if preset == "custom":
        requested = raw.get("sources") or []
        sources = list(dict.fromkeys(str(value) for value in requested))
    else:
        sources = list(CONTENT_PRESET_SOURCES[preset])
    unknown = sorted(set(sources) - set(ALL_CONTENT_SOURCES))
    if unknown:
        raise ValueError("Unknown benchmark content sources: " + ", ".join(unknown))
    if not sources:
        raise ValueError("Select at least one benchmark content source")
    map_files = sorted({
        Path(str(value)).name
        for value in raw.get("map_files") or []
        if re.fullmatch(r"Map\d+\.json", Path(str(value)).name, re.IGNORECASE)
    }, key=str.casefold)
    if "map_events" not in sources:
        map_files = []
    return {
        "preset": preset,
        "sources": sources,
        "map_files": map_files,
        "include_code_heavy": bool(raw.get("include_code_heavy", True)),
    }


def _filter_corpus(pool: Iterable[dict], selection: dict) -> list[dict]:
    sources = set(selection["sources"])
    map_files = {name.casefold() for name in selection.get("map_files") or []}
    include_code_heavy = bool(selection.get("include_code_heavy", True))
    selected: list[dict] = []
    for item in pool:
        category = item.get("source_category")
        if category not in sources:
            continue
        if not include_code_heavy and item.get("stratum") == "code_heavy":
            continue
        filename = str((item.get("source_location") or {}).get("file") or "")
        if category == "map_events" and map_files and filename.casefold() not in map_files:
            continue
        selected.append(item)
    return selected


def corpus_fingerprint(pool: Iterable[dict]) -> str:
    """Fingerprint source identity and text so sampling varies stably by game."""
    return _sha256(sorted(
        (
            str(item.get("id") or ""),
            str(item.get("source") or ""),
            str(item.get("source_category") or ""),
        )
        for item in pool
    ))


def content_inventory(files_dir: str | Path, *, _pool: list[dict] | None = None) -> dict:
    """Return eligible-line counts for benchmark source-selection controls."""
    pool = list(_pool) if _pool is not None else scan_corpus(files_dir)
    source_counts = {
        source_id: sum(1 for item in pool if item.get("source_category") == source_id)
        for source_id in ALL_CONTENT_SOURCES
    }
    map_files = sorted({
        str(item["source_location"]["file"])
        for item in pool if item.get("source_category") == "map_events"
    }, key=str.casefold)
    return {
        "eligible_segments": len(pool),
        "eligible_scenes": len({item["scene_id"] for item in pool}),
        "eligible_files": len({item["source_location"]["file"] for item in pool}),
        "source_counts": source_counts,
        "map_files": {
            filename: sum(
                1 for item in pool
                if item.get("source_category") == "map_events"
                and item["source_location"]["file"] == filename
            )
            for filename in map_files
        },
        "code_heavy_source_counts": {
            source_id: sum(
                1 for item in pool
                if item.get("source_category") == source_id
                and item.get("stratum") == "code_heavy"
            )
            for source_id in ALL_CONTENT_SOURCES
        },
        "map_file_code_heavy_counts": {
            filename: sum(
                1 for item in pool
                if item.get("source_category") == "map_events"
                and item["source_location"]["file"] == filename
                and item.get("stratum") == "code_heavy"
            )
            for filename in map_files
        },
        "code_heavy_segments": sum(
            1 for item in pool if item.get("stratum") == "code_heavy"
        ),
        "corpus_sha256": corpus_fingerprint(pool),
    }


def _balanced_take(items: Iterable[dict], count: int,
                   *, excluded: set[str] | None = None,
                   per_scene: int = 12, sampling_seed: str = "") -> list[dict]:
    """Take a deterministic file- and scene-balanced subset with local context."""
    if count <= 0:
        return []
    excluded = excluded or set()
    groups: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for item in items:
        if item["id"] in excluded:
            continue
        filename = str((item.get("source_location") or {}).get("file") or "")
        groups[filename][item["scene_id"]].append(item)
    file_order = sorted(
        groups,
        key=lambda filename: (
            0 if any(
                len(scene_items) >= per_scene
                for scene_items in groups[filename].values()
            ) else 1,
            _sha256(f"{sampling_seed}:file:{filename}"),
        ),
    )
    scene_order = {
        filename: sorted(
            groups[filename],
            key=lambda scene: (
                0 if len(groups[filename][scene]) >= per_scene else 1,
                _sha256(f"{sampling_seed}:file:{filename}:scene:{scene}"),
            ),
        )
        for filename in file_order
    }
    selected: list[dict] = []
    scene_positions = {filename: 0 for filename in file_order}
    item_offsets = {
        (filename, scene): 0
        for filename in file_order for scene in scene_order[filename]
    }
    while len(selected) < count:
        progressed = False
        for filename in file_order:
            scenes = scene_order[filename]
            available_scene = None
            for _attempt in range(len(scenes)):
                position = scene_positions[filename] % len(scenes)
                scene_positions[filename] += 1
                candidate = scenes[position]
                if (
                    item_offsets[(filename, candidate)]
                    < len(groups[filename][candidate])
                ):
                    available_scene = candidate
                    break
            if available_scene is None:
                continue
            offset = item_offsets[(filename, available_scene)]
            scene_items = groups[filename][available_scene]
            take = min(
                per_scene,
                len(scene_items) - offset,
                count - len(selected),
            )
            selected.extend(scene_items[offset:offset + take])
            item_offsets[(filename, available_scene)] += take
            progressed = progressed or take > 0
            if len(selected) >= count:
                break
        if not progressed:
            break
    return selected


def build_corpus(files_dir: str | Path, *, target_segments: int = DEFAULT_SEGMENTS,
                 content_selection: dict | None = None,
                 sampling_seed: str | None = None,
                 sample_size: int = DEFAULT_SAMPLE_SIZE,
                 _pool: list[dict] | None = None) -> list[dict]:
    """Build a deterministic, game-specific RPG Maker benchmark corpus."""
    root = Path(files_dir)
    if target_segments < 60:
        raise ValueError("Evaluation corpus must contain at least 60 segments")
    if sample_size < 1:
        raise ValueError("Sample size must be at least 1")
    pool = list(_pool) if _pool is not None else scan_corpus(root)
    selection = normalize_content_selection(content_selection)
    eligible = _filter_corpus(pool, selection)
    if len(eligible) < 60:
        raise ValueError(
            f"The selected content contains only {len(eligible)} eligible Japanese "
            "lines; select more sources because at least 60 are required"
        )
    selected_target = min(target_segments, len(eligible))
    seed = sampling_seed or corpus_fingerprint(pool)
    if selection["preset"] == "balanced":
        code = [item for item in eligible if item["stratum"] == "code_heavy"]
        database = [item for item in eligible if item["stratum"] == "database"]
        event_text = [item for item in eligible if item["stratum"] == "event_text"]
        quotas = {
            "code_heavy": round(selected_target * 0.15),
            "database": round(selected_target * 0.20),
        }
        quotas["event_text"] = selected_target - sum(quotas.values())
        selected: list[dict] = []
        selected.extend(_balanced_take(
            event_text, quotas["event_text"], per_scene=sample_size,
            sampling_seed=seed,
        ))
        selected.extend(_balanced_take(
            database, quotas["database"], per_scene=sample_size,
            sampling_seed=seed,
        ))
        used = {item["id"] for item in selected}
        selected.extend(_balanced_take(
            code, quotas["code_heavy"], excluded=used,
            per_scene=sample_size, sampling_seed=seed,
        ))
    else:
        selected = _balanced_take(
            eligible, selected_target, per_scene=sample_size, sampling_seed=seed
        )
    if len(selected) < selected_target:
        used = {item["id"] for item in selected}
        selected.extend(
            _balanced_take(
                eligible, selected_target - len(selected), excluded=used,
                per_scene=sample_size, sampling_seed=seed,
            )
        )
    return selected[:selected_target]


def _assign_review_samples(
    segments: list[dict], pool: list[dict], sample_size: int
) -> list[dict]:
    """Group selected lines into ordered, same-scene review samples."""
    if sample_size < 1:
        raise ValueError("Sample size must be at least 1")
    selected_ids = {segment["id"] for segment in segments}
    selected_scene_order = list(dict.fromkeys(
        segment["scene_id"] for segment in segments
    ))
    full_by_scene: dict[str, list[dict]] = defaultdict(list)
    for segment in pool:
        full_by_scene[segment["scene_id"]].append(segment)

    grouped: list[dict] = []
    sample_index = 0
    for scene_id in selected_scene_order:
        full_scene = full_by_scene.get(scene_id, [])
        selected_scene = [
            segment for segment in full_scene if segment["id"] in selected_ids
        ]
        if not selected_scene:
            continue
        full_positions = {
            segment["id"]: index for index, segment in enumerate(full_scene)
        }
        chunks: list[list[dict]] = []
        chunk: list[dict] = []
        previous_position: int | None = None
        for segment in selected_scene:
            position = full_positions[segment["id"]]
            if chunk and (
                (
                    previous_position is not None
                    and position != previous_position + 1
                )
                or len(chunk) >= sample_size
            ):
                chunks.append(chunk)
                chunk = []
            chunk.append(segment)
            previous_position = position
        if chunk:
            chunks.append(chunk)

        for chunk in chunks:
            sample_index += 1
            first_position = full_positions.get(chunk[0]["id"], 0)
            if first_position == 0:
                history = _normalize_history(chunk[0].get("initial_history"))
            else:
                # Production batch translation carries only the immediately
                # preceding source chunk, capped by maxHistory (10). Using a
                # fixed ten lines here gave custom samples below ten lines
                # progressively more context than the real workflow.
                history_size = min(sample_size, 10)
                history = [
                    segment["source"]
                    for segment in full_scene[
                        max(0, first_position - history_size):first_position
                    ]
                ]
            sample_id = f"sample-{sample_index:04d}"
            for line_index, segment in enumerate(chunk, start=1):
                item = copy.deepcopy(segment)
                item["review_sample_id"] = sample_id
                item["review_line_number"] = line_index
                item["review_history"] = history
                grouped.append(item)
    return grouped


def _build_logical_requests(segments: list[dict], system_prompt: str,
                            glossary: str, batch_size: int,
                            use_sfx_reference: bool = True) -> list[dict]:
    config = TranslationConfig(
        language="English",
        prompt=system_prompt,
        vocab=glossary,
        batchSize=batch_size,
        useSfxReference=use_sfx_reference,
    )
    by_group: dict[str, list[dict]] = defaultdict(list)
    group_order: list[str] = []
    for segment in segments:
        group = segment.get("review_sample_id") or segment["scene_id"]
        if group not in by_group:
            group_order.append(group)
        by_group[group].append(segment)

    requests: list[dict] = []
    request_index = 0
    for group in group_order:
        items = by_group[group]
        scene = items[0]["scene_id"]
        previous_source: list[str] = []
        for offset in range(0, len(items), batch_size):
            chunk = items[offset:offset + batch_size]
            protected: list[str] = []
            replacements: list[dict[str, str]] = []
            for segment in chunk:
                protected_text, mapping = protect_script_codes(segment["source"])
                protected.append(protected_text)
                replacements.append(mapping)
            payload = json.dumps(
                {f"Line{i + 1}": text for i, text in enumerate(protected)},
                ensure_ascii=False,
                indent=4,
            )
            if offset == 0:
                history = _normalize_history(
                    chunk[0].get(
                        "review_history", chunk[0].get("initial_history")
                    )
                )
            else:
                history = previous_source[-10:]
            static_system, matched_glossary, matched_sfx, user = createContextParts(
                config, payload, "json", history
            )
            logical = {
                "system": static_system,
                "glossary": matched_glossary,
                "sfx_reference": matched_sfx,
                "history": history,
                "user": user,
                "schema_line_count": len(chunk),
            }
            request_index += 1
            requests.append({
                "id": f"logical-{request_index:04d}",
                "review_sample_id": chunk[0].get("review_sample_id"),
                "scene_id": scene,
                "stratum": chunk[0]["stratum"],
                "segment_ids": [segment["id"] for segment in chunk],
                "sources": [segment["source"] for segment in chunk],
                "protected_sources": protected,
                "replacements": replacements,
                **logical,
                "logical_hash": _sha256(logical),
            })
            previous_source.extend(segment["source"] for segment in chunk)
    return requests


def _validate_request_output_capacity(requests: list[dict]) -> None:
    """Reject samples whose expected translation cannot fit the provider cap."""
    oversized: list[tuple[str, int, int]] = []
    for request in requests:
        dynamic_context = request["glossary"] + request.get("sfx_reference", "")
        _input_tokens, expected_output = countTokens(
            request["system"] + dynamic_context,
            request["user"],
            request["history"],
        )
        if expected_output > MAX_OUTPUT_TOKENS_PER_REQUEST:
            oversized.append((
                request["id"],
                len(request.get("segment_ids") or []),
                expected_output,
            ))
    if oversized:
        request_id, line_count, expected_output = max(
            oversized, key=lambda item: item[2]
        )
        raise ValueError(
            "Lines per sample is too high for the fixed "
            f"{MAX_OUTPUT_TOKENS_PER_REQUEST:,}-token response limit. "
            f"{request_id} contains {line_count:,} lines and is estimated to need "
            f"about {expected_output:,} output tokens. Reduce Lines per sample and "
            "prepare the benchmark again."
        )


def _stability_request_ids(
    requests: list[dict], target_segments: int, target_samples: int | None = None
) -> list[str]:
    if target_samples is not None and target_samples <= 0:
        return []
    if target_samples is None and target_segments <= 0:
        return []
    by_stratum: dict[str, list[dict]] = defaultdict(list)
    for request in requests:
        by_stratum[request["stratum"]].append(request)
    order = list(by_stratum)
    offsets = {key: 0 for key in order}
    selected: list[str] = []
    line_count = 0
    while (
        len(selected) < target_samples
        if target_samples is not None
        else line_count < target_segments
    ):
        progressed = False
        for key in order:
            offset = offsets[key]
            if offset >= len(by_stratum[key]):
                continue
            request = by_stratum[key][offset]
            offsets[key] += 1
            selected.append(request["id"])
            line_count += len(request["segment_ids"])
            progressed = True
            if (
                target_samples is not None and len(selected) >= target_samples
            ) or (
                target_samples is None and line_count >= target_segments
            ):
                break
        if not progressed:
            break
    return selected


def build_manifest(files_dir: str | Path, *, target_segments: int = DEFAULT_SEGMENTS,
                   stability_segments: int = DEFAULT_STABILITY_SEGMENTS,
                   stability_samples: int | None = None,
                   repetitions: int = DEFAULT_REPETITIONS,
                   batch_size: int = DEFAULT_SAMPLE_SIZE,
                   content_selection: dict | None = None,
                   system_prompt: str | None = None,
                   glossary: str | None = None,
                   game_root: str | Path | None = None,
                   use_sfx_reference: bool | None = None) -> dict:
    if repetitions < 1:
        raise ValueError("Repetitions must be at least 1")
    if batch_size < 1:
        raise ValueError("Sample size must be at least 1")
    if stability_samples is not None and stability_samples < 0:
        raise ValueError("Repeated sample count cannot be negative")
    if stability_samples and repetitions < 2:
        raise ValueError("Repeated samples require at least 2 runs")
    data_dir = resolve_rpgmaker_data_dir(files_dir)
    context_root = (
        Path(game_root).expanduser().resolve()
        if game_root is not None and str(game_root).strip()
        else resolve_evaluation_game_root(files_dir)
    )
    if context_root is not None and not context_root.is_dir():
        raise FileNotFoundError(f"RPG Maker game folder does not exist: {context_root}")
    system = (
        load_system_prompt(context_root)
        if system_prompt is None
        else system_prompt
    )
    active_glossary = (
        read_game_glossary(context_root)
        if glossary is None and context_root is not None
        else read_active_glossary()
        if glossary is None
        else glossary
    )
    all_segments = scan_corpus(data_dir, glossary=active_glossary)
    selection = normalize_content_selection(content_selection)
    eligible_segments = _filter_corpus(all_segments, selection)
    inventory = content_inventory(data_dir, _pool=all_segments)
    sampling_seed = inventory["corpus_sha256"]
    selected_segments = build_corpus(
        data_dir,
        target_segments=target_segments,
        content_selection=selection,
        sampling_seed=sampling_seed,
        sample_size=batch_size,
        _pool=all_segments,
    )
    segments = _assign_review_samples(
        selected_segments, eligible_segments, batch_size
    )
    if use_sfx_reference is None:
        use_sfx_reference = os.getenv(
            "useSfxReference", "true"
        ).strip().lower() in ("true", "1", "yes")
    requests = _build_logical_requests(
        segments, system, active_glossary, batch_size, use_sfx_reference
    )
    _validate_request_output_capacity(requests)
    stability_ids = _stability_request_ids(
        requests, stability_segments, stability_samples
    )
    stability_line_count = sum(
        len(request["segment_ids"])
        for request in requests if request["id"] in stability_ids
    )
    executions: list[dict] = []
    for repetition in range(1, repetitions + 1):
        eligible = requests if repetition == 1 else [
            request for request in requests if request["id"] in stability_ids
        ]
        for request in eligible:
            executions.append({
                "id": f"rep-{repetition}:{request['id']}",
                "logical_request_id": request["id"],
                "repetition": repetition,
            })
    manifest = {
        "version": EVALUATION_VERSION,
        "created_at": _utc_now(),
        "source_dir": str(data_dir),
        "game_root": str(context_root) if context_root is not None else "",
        "target_language": "English",
        "batch_size": batch_size,
        "sample_size": batch_size,
        "requested_segments": target_segments,
        "content_selection": selection,
        "corpus_sha256": inventory["corpus_sha256"],
        "sampling_seed": sampling_seed,
        "requested_stability_segments": stability_segments,
        "requested_stability_samples": stability_samples,
        "target_segments": len(segments),
        "review_samples": len(requests),
        "stability_samples": len(stability_ids),
        "stability_target_segments": stability_line_count,
        "repetitions": repetitions,
        "system_prompt_sha256": _sha256(system.encode("utf-8")),
        "glossary_sha256": _sha256(active_glossary.encode("utf-8")),
        "sfx_reference_enabled": bool(use_sfx_reference),
        "sfx_reference_identity": (
            sfx_reference_identity() if use_sfx_reference else {}
        ),
        "selected_segment_ids": [segment["id"] for segment in segments],
        "segments": segments,
        "logical_requests": requests,
        "stability_request_ids": stability_ids,
        "executions": executions,
        "corpus_summary": {
            "eligible_segments": len(eligible_segments),
            "available_segments": len(all_segments),
            "selected_segments": len(segments),
            "selected_scenes": len({item["scene_id"] for item in segments}),
            "review_samples": len(requests),
            "repeated_samples": len(stability_ids),
            "eligible_files": len({
                item["source_location"]["file"] for item in eligible_segments
            }),
            "selected_files": len({
                item["source_location"]["file"] for item in segments
            }),
            "selected_categories": dict(sorted({
                    key: sum(1 for item in segments if item["source_category"] == key)
                    for key in {item["source_category"] for item in segments}
                }.items())),
            "content_inventory": inventory,
        },
    }
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    return manifest


def _request_lookup(manifest: dict) -> dict[str, dict]:
    return {request["id"]: request for request in manifest["logical_requests"]}


def estimate_candidate(manifest: dict, candidate: dict) -> dict:
    requests = _request_lookup(manifest)
    input_tokens = 0
    output_tokens = 0
    for execution in manifest["executions"]:
        request = requests[execution["logical_request_id"]]
        dynamic_context = request["glossary"] + request.get("sfx_reference", "")
        counted_input, counted_output = countTokens(
            request["system"] + dynamic_context,
            request["user"],
            request["history"],
        )
        input_tokens += counted_input
        output_tokens += counted_output

    tokenizer_factor = 1.30 if candidate.get("provider") == "anthropic" else 1.10
    thinking_factor = 1.10 if candidate.get("provider") == "gemini" else 1.0
    estimated_input = round(input_tokens * tokenizer_factor)
    estimated_output = min(
        round(output_tokens * tokenizer_factor * thinking_factor),
        len(manifest["executions"]) * MAX_OUTPUT_TOKENS_PER_REQUEST,
    )
    rates = _candidate_rates(candidate)
    raw_cost = (
        estimated_input * rates["input"]
        + estimated_output * rates["output"]
    ) / 1_000_000
    automatic_attempts = (
        LIVE_REQUEST_MAX_ATTEMPTS
        if candidate.get("execution", "batch") == "live"
        else 1
    )
    single_attempt_ceiling = (
        estimated_input * 1.25 * rates["input"]
        + len(manifest["executions"])
        * MAX_OUTPUT_TOKENS_PER_REQUEST
        * rates["output"]
    ) / 1_000_000
    maximum_cost = single_attempt_ceiling * automatic_attempts
    likely_upper_cost = min(raw_cost * 1.25, single_attempt_ceiling)
    return {
        "input_tokens": estimated_input,
        "output_tokens": estimated_output,
        "cost_usd": likely_upper_cost,
        "maximum_cost_usd": maximum_cost,
        "automatic_attempts": automatic_attempts,
        "output_token_cap_per_request": MAX_OUTPUT_TOKENS_PER_REQUEST,
        "rates": rates,
        "method": (
            f"provider-neutral {candidate.get('execution', 'batch')} likely "
            "upper bound with tokenizer/thinking and 25% contingency; "
            f"theoretical ceiling includes {automatic_attempts} automatic "
            f"attempt{'s' if automatic_attempts != 1 else ''}"
        ),
    }


def _validate_candidate_budget(candidate: dict, budget_usd: float) -> None:
    estimate = candidate["estimate"]
    if estimate["cost_usd"] > budget_usd * 0.80:
        raise ValueError(
            f"{candidate['label']} has a likely upper bound of "
            f"${estimate['cost_usd']:.2f}; "
            f"the safe pre-submit limit is ${budget_usd * 0.80:.2f}"
        )
    if estimate["maximum_cost_usd"] > budget_usd:
        raise ValueError(
            f"{candidate['label']} has a theoretical ceiling of "
            f"${estimate['maximum_cost_usd']:.2f}, including "
            f"{estimate.get('automatic_attempts', 1)} automatic "
            f"attempt(s); budget is ${budget_usd:.2f}"
        )


def refresh_run_estimates(run_dir: str | Path) -> tuple[dict, dict]:
    """Refresh every unpaid estimate and enforce the saved budget."""
    root = Path(run_dir)
    state, manifest = load_run(root)
    budget_usd = float(
        state.get("budget_usd_per_model", DEFAULT_BUDGET_USD)
        or DEFAULT_BUDGET_USD
    )
    state.setdefault("budget_usd_per_model", budget_usd)
    changed = False
    for candidate in state.get("candidates") or []:
        if candidate.get("batch_id") or candidate.get("status") in {
            "completed", "failed", "submitted",
        }:
            continue
        candidate["estimate"] = estimate_candidate(manifest, candidate)
        _validate_candidate_budget(candidate, budget_usd)
        changed = True
    if changed:
        state["updated_at"] = _utc_now()
        _atomic_write_json(root / "state.json", state)
    return state, manifest


def _candidate_rates(candidate: dict) -> dict[str, float]:
    endpoint = str(candidate.get("endpoint") or "").lower()
    is_local = any(
        marker in endpoint
        for marker in ("localhost", "127.0.0.1", "[::1]", "0.0.0.0")
    )
    if candidate.get("keyless") or is_local:
        # Local inference has no provider token invoice. Electricity/hardware
        # costs are outside this API-budget guard.
        return {"input": 0.0, "cached_input": 0.0, "output": 0.0}
    rates = pricing_for(candidate["model"])
    if candidate.get("execution", "batch") == "live":
        # pricing_for returns provider Batch API rates. Live endpoints use the
        # undiscounted rates from the same pricing source.
        return {name: value * 2.0 for name, value in rates.items()}
    return rates


def _validate_candidates(candidates: list[dict]) -> None:
    if len(candidates) < 2:
        raise ValueError("Add at least two models to compare")
    supported = {"openai", "gemini", "anthropic"}
    seen: set[tuple[str, str, str, str]] = set()
    for candidate in candidates:
        provider = candidate.get("provider")
        if provider not in supported:
            raise ValueError(f"Unsupported batch provider {provider!r}")
        execution = str(candidate.get("execution") or "batch").lower()
        if execution not in {"batch", "live"}:
            raise ValueError(f"Unsupported evaluation mode {execution!r}")
        endpoint = str(candidate.get("endpoint") or "").strip()
        if not endpoint:
            raise ValueError(f"API URL is required for {provider}")
        if not str(candidate.get("model") or "").strip():
            raise ValueError(f"Model is required for {provider}")
        identity = (
            str(provider),
            endpoint.casefold(),
            str(candidate.get("key_name") or ""),
            str(candidate["model"]).strip().casefold(),
        )
        if identity in seen:
            raise ValueError(
                f"Duplicate comparison entry: {candidate['model']} ({provider})"
            )
        seen.add(identity)
        _candidate_rates(candidate)


def _evaluation_storage_roots(project_root: str | Path) -> tuple[Path, Path]:
    log_root = Path(project_root).resolve() / "log"
    return log_root / EVALUATION_ARCHIVE_DIR, log_root / EVALUATION_WORK_DIR


def _unique_run_path(root: Path, run_id: str, *other_roots: Path) -> Path:
    candidate = root / run_id
    suffix = 1
    while candidate.exists() or any((other / candidate.name).exists() for other in other_roots):
        candidate = root / f"{run_id}-{suffix}"
        suffix += 1
    return candidate


def _safe_run_directories(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        return []
    return [
        child for child in root.iterdir()
        if child.is_dir() and not child.is_symlink()
        and (child / "state.json").is_file()
        and (child / "manifest.json").is_file()
    ]


def _retention_timestamp(run_dir: Path, state: dict) -> str:
    return str(
        state.get("archived_at")
        or state.get("updated_at")
        or state.get("created_at")
        or datetime.fromtimestamp(
            run_dir.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat()
    )


def prune_completed_evaluations(
    project_root: str | Path, *, limit: int = MAX_SAVED_EVALUATIONS
) -> list[Path]:
    """Delete completed archives beyond *limit*, oldest first."""
    if limit < 1:
        raise ValueError("Completed evaluation retention must be at least 1")
    archive_root, _work_root = _evaluation_storage_roots(project_root)
    completed: list[tuple[str, str, Path]] = []
    for run_dir in _safe_run_directories(archive_root):
        try:
            state, _manifest = load_run(run_dir)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if state.get("status") == "completed":
            completed.append((_retention_timestamp(run_dir, state), run_dir.name, run_dir))
    completed.sort(reverse=True)
    removed: list[Path] = []
    archive_boundary = archive_root.resolve()
    for _timestamp, _name, run_dir in completed[limit:]:
        resolved = run_dir.resolve()
        if resolved.parent != archive_boundary or run_dir.is_symlink():
            continue
        shutil.rmtree(resolved)
        removed.append(resolved)
    return removed


def maintain_evaluation_storage(project_root: str | Path) -> dict:
    """Migrate legacy active runs out of the archive and enforce retention."""
    archive_root, work_root = _evaluation_storage_roots(project_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    discarded: list[Path] = []
    for run_dir in list(archive_root.iterdir()):
        if not run_dir.is_dir() or run_dir.is_symlink():
            continue
        target = _unique_run_path(work_root, run_dir.name)
        if not (run_dir / "state.json").is_file() or not (
            run_dir / "manifest.json"
        ).is_file():
            if not any(run_dir.iterdir()):
                run_dir.rmdir()
                discarded.append(run_dir)
                continue
            run_dir.rename(target)
            moved.append((run_dir, target))
            continue
        try:
            state, _manifest = load_run(run_dir)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            run_dir.rename(target)
            moved.append((run_dir, target))
            continue
        if state.get("status") == "completed":
            continue
        state["managed_storage"] = True
        state["storage"] = "working"
        state["run_id"] = target.name
        _atomic_write_json(run_dir / "state.json", state)
        run_dir.rename(target)
        moved.append((run_dir, target))
    for run_dir in list(work_root.iterdir()):
        if (
            run_dir.is_dir()
            and not run_dir.is_symlink()
            and not any(run_dir.iterdir())
        ):
            run_dir.rmdir()
            discarded.append(run_dir)
    legacy_pointer = archive_root / "latest.json"
    if legacy_pointer.is_file() and not legacy_pointer.is_symlink():
        legacy_pointer.unlink()
    removed = prune_completed_evaluations(project_root)
    return {"moved": moved, "removed": removed, "discarded": discarded}


def locate_run(project_root: str | Path, run_id: str) -> Path | None:
    """Locate a managed working or completed run by its stable ID."""
    archive_root, work_root = _evaluation_storage_roots(project_root)
    for root in (archive_root, work_root):
        candidate = root / str(run_id)
        if (
            candidate.is_dir()
            and not candidate.is_symlink()
            and candidate.parent.resolve() == root.resolve()
            and (candidate / "state.json").is_file()
        ):
            return candidate
    return None


def _archive_completed_run(root: Path, state: dict) -> Path:
    if state.get("status") != "completed" or not state.get("managed_storage"):
        return root
    if root.parent.name != EVALUATION_WORK_DIR or root.parent.parent.name != "log":
        return root
    project_root = root.parent.parent.parent
    archive_root, work_root = _evaluation_storage_roots(project_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    target = _unique_run_path(archive_root, root.name)
    state["run_id"] = target.name
    state["storage"] = "completed"
    state["archived_at"] = _utc_now()
    state["updated_at"] = state["archived_at"]
    _atomic_write_json(root / "state.json", state)
    root.rename(target)
    prune_completed_evaluations(project_root)
    return target


def _discard_superseded_prepared_runs(project_root: str | Path) -> list[Path]:
    """Discard stale, never-submitted preparations before creating a new one."""
    _archive_root, work_root = _evaluation_storage_roots(project_root)
    removed: list[Path] = []
    work_boundary = work_root.resolve()
    for run_dir in _safe_run_directories(work_root):
        try:
            state, _manifest = load_run(run_dir)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        if state.get("status") != "prepared":
            continue
        resolved = run_dir.resolve()
        if resolved.parent != work_boundary or run_dir.is_symlink():
            continue
        shutil.rmtree(resolved)
        removed.append(resolved)
    return removed


def prepare_run(project_root: str | Path, files_dir: str | Path,
                candidates: list[dict], *, target_segments: int = DEFAULT_SEGMENTS,
                stability_segments: int = DEFAULT_STABILITY_SEGMENTS,
                stability_samples: int | None = None,
                repetitions: int = DEFAULT_REPETITIONS,
                batch_size: int = DEFAULT_SAMPLE_SIZE,
                content_selection: dict | None = None,
                budget_usd: float = DEFAULT_BUDGET_USD,
                game_root: str | Path | None = None,
                output_root: str | Path | None = None) -> tuple[Path, dict]:
    _validate_candidates(candidates)
    if budget_usd <= 0:
        raise ValueError("Budget must be greater than zero")
    manifest = build_manifest(
        files_dir,
        target_segments=target_segments,
        stability_segments=stability_segments,
        stability_samples=stability_samples,
        repetitions=repetitions,
        batch_size=batch_size,
        content_selection=content_selection,
        game_root=game_root,
    )
    clean_candidates = []
    for index, candidate in enumerate(candidates, start=1):
        clean = {
            "id": f"candidate-{index}",
            "provider": candidate["provider"],
            "model": candidate["model"],
            "label": candidate.get("label") or candidate["model"],
            "key_name": candidate.get("key_name", ""),
            "endpoint": candidate.get("endpoint", ""),
            "keyless": bool(candidate.get("keyless", False)),
            "execution": str(candidate.get("execution") or "batch").lower(),
            "status": "prepared",
        }
        clean["estimate"] = estimate_candidate(manifest, clean)
        _validate_candidate_budget(clean, budget_usd)
        clean_candidates.append(clean)

    project = Path(project_root).resolve()
    managed_storage = output_root is None
    if managed_storage:
        maintain_evaluation_storage(project)
        archive_root, runs_root = _evaluation_storage_roots(project)
        _discard_superseded_prepared_runs(project)
    else:
        runs_root = Path(output_root)
        archive_root = runs_root
    run_id = (
        datetime.now().strftime("%Y%m%d-%H%M%S")
        + "-" + manifest["manifest_sha256"][:8]
    )
    run_dir = _unique_run_path(runs_root, run_id, archive_root)
    run_dir.mkdir(parents=True)

    state = {
        "version": EVALUATION_VERSION,
        "run_id": run_dir.name,
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "prepared",
        "managed_storage": managed_storage,
        "storage": "working" if managed_storage else "custom",
        "budget_usd_per_model": budget_usd,
        "manifest_sha256": manifest["manifest_sha256"],
        "corpus_summary": manifest["corpus_summary"],
        "candidates": clean_candidates,
    }
    _atomic_write_json(run_dir / "manifest.json", manifest)
    _atomic_write_json(run_dir / "state.json", state)
    return run_dir, state


def _summary_has_no_successes(summary: dict) -> bool:
    expected = int(summary.get("expected_requests", 0) or 0)
    received = int(summary.get("received_requests", 0) or 0)
    if expected <= 0:
        return False
    # New summaries distinguish transport success from usable output. A model
    # returning malformed or wholly invalid text must not be archived as a
    # completed 0% evaluation merely because an HTTP response arrived.
    if "valid_segments" in summary:
        return int(summary.get("valid_segments", 0) or 0) == 0
    return received == 0


def _no_successes_reason(summary: dict) -> str:
    expected = int(summary.get("expected_requests", 0) or 0)
    received = int(summary.get("received_requests", 0) or 0)
    total_segments = int(summary.get("total_segments", 0) or 0)
    if received > 0 and "valid_segments" in summary:
        return (
            f"No valid translated segments were produced (0/{total_segments}) "
            f"from {received}/{expected} received requests."
        )
    error_count = len(summary.get("provider_errors") or [])
    return (
        f"No successful requests were received (0/{expected}). "
        f"The provider reported {error_count} request errors."
    )


def load_run(run_dir: str | Path) -> tuple[dict, dict]:
    root = Path(run_dir)
    state = _read_json(root / "state.json")
    manifest = _read_json(root / "manifest.json")
    _validate_manifest_integrity(state, manifest)
    # Runs created before failed-result states were introduced may say
    # "completed" even though a terminal provider batch returned zero rows.
    # Normalize those records in memory so old runs are safe immediately,
    # without rewriting archived evaluation artifacts during a read.
    for candidate in state.get("candidates") or []:
        summary = candidate.get("summary") or {}
        if _summary_has_no_successes(summary):
            candidate["status"] = "failed"
            candidate["failure_reason"] = _no_successes_reason(summary)
    candidate_statuses = [
        candidate.get("status") for candidate in state.get("candidates") or []
    ]
    if (
        candidate_statuses
        and all(status in {"completed", "failed"} for status in candidate_statuses)
        and any(status == "failed" for status in candidate_statuses)
    ):
        state["status"] = "failed"
    return state, manifest


def latest_run(project_root: str | Path) -> Path | None:
    """Return the newest visible run using the saved-history ordering."""
    runs = list_runs(project_root)
    return Path(runs[0]["run_dir"]) if runs else None


def run_history_entry(run_dir: str | Path) -> dict:
    """Build display metadata for a managed evaluation run."""
    root = Path(run_dir)
    state, manifest = load_run(root)
    candidates = state.get("candidates") or []
    summary = state.get("corpus_summary") or manifest.get("corpus_summary") or {}
    human = state.get("human_review") or {}
    reviewed_samples = int(human.get("reviewed", 0) or 0)
    reviewed_lines = int(human.get("reviewed_lines", reviewed_samples) or 0)
    eligible_review_samples = 0
    blind_key_path = root / "blind_key.json"
    if blind_key_path.is_file():
        try:
            eligible_review_samples = len(_read_json(blind_key_path))
        except (OSError, ValueError, json.JSONDecodeError):
            pass
    created_at = str(state.get("created_at") or "")
    if not created_at:
        created_at = datetime.fromtimestamp(
            root.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat()
    return {
        "run_dir": root.resolve(),
        "run_id": str(state.get("run_id") or root.name),
        "created_at": created_at,
        "updated_at": str(state.get("updated_at") or created_at),
        "status": str(state.get("status") or "unknown"),
        "models": [str(item.get("model") or "") for item in candidates],
        "modes": [str(item.get("execution") or "batch") for item in candidates],
        "selected_segments": int(summary.get("selected_segments", 0) or 0),
        "source_name": Path(str(manifest.get("source_dir") or "")).name,
        "reviewed": reviewed_samples,
        "reviewed_samples": reviewed_samples,
        "reviewed_lines": reviewed_lines,
        "review_complete": bool(
            eligible_review_samples
            and reviewed_samples == eligible_review_samples
        ),
    }


def list_runs(project_root: str | Path) -> list[dict]:
    """Return resumable working runs and completed archives."""
    maintain_evaluation_storage(project_root)
    archive_root, work_root = _evaluation_storage_roots(project_root)
    runs: list[dict] = []
    visible_statuses = {
        archive_root: {"completed"},
        work_root: {
            "prepared", "submitted", "partially_submitted", "imported_paused",
            "failed",
        },
    }
    for runs_root, statuses in visible_statuses.items():
        for run_dir in _safe_run_directories(runs_root):
            try:
                state, manifest = load_run(run_dir)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
            if state.get("status") not in statuses:
                continue
            runs.append(run_history_entry(run_dir))
    return sorted(
        runs,
        key=lambda item: (item["created_at"], item["run_id"]),
        reverse=True,
    )


def export_run_archive(
    run_dir: str | Path, output_path: str | Path
) -> Path:
    """Export one complete evaluation without API secrets."""
    root = Path(run_dir).resolve()
    state, _manifest = load_run(root)
    output = Path(output_path)
    if output.suffix.lower() not in {".dazedeval", ".zip"}:
        output = output.with_suffix(".dazedeval")
    output.parent.mkdir(parents=True, exist_ok=True)

    relative_files: list[Path] = []
    for optional in (
        "blind_key.json", "blind_review.csv",
        REVIEW_SYSTEM_PROMPT_FILENAME, REVIEW_GLOSSARY_FILENAME,
        REVIEW_SFX_REFERENCE_FILENAME,
    ):
        if (root / optional).is_file():
            relative_files.append(Path(optional))
    for candidate in state.get("candidates") or []:
        result_file = Path(str(candidate.get("result_file") or ""))
        if (
            len(result_file.parts) == 2
            and not result_file.is_absolute()
            and result_file.parts[0] == "results"
            and ".." not in result_file.parts
            and result_file.suffix.lower() == ".json"
            and (root / result_file).is_file()
        ):
            relative_files.append(result_file)
        candidate_id = str(candidate.get("id") or "")
        live_checkpoint = Path("results") / f"{candidate_id}.live.partial.json"
        if (
            candidate.get("status") == "running_live"
            and bool(re.fullmatch(r"[A-Za-z0-9._-]+", candidate_id))
            and candidate_id not in {".", ".."}
            and (root / live_checkpoint).is_file()
        ):
            # Active live evaluations are intentionally exportable. Preserve
            # their paid-request checkpoint so an imported run resumes only
            # the unfinished requests instead of replaying completed calls.
            relative_files.append(live_checkpoint)

    metadata = {
        "archive_version": EVALUATION_ARCHIVE_VERSION,
        "evaluation_version": state.get("version", EVALUATION_VERSION),
        "run_id": state.get("run_id", root.name),
        "exported_at": _utc_now(),
        "contains_api_secrets": False,
    }

    def without_secrets(value: Any) -> Any:
        if isinstance(value, dict):
            sensitive = {
                "api_key", "apikey", "secret", "credentials",
                "authorization", "access_token", "refresh_token",
            }
            return {
                str(key): without_secrets(item)
                for key, item in value.items()
                if str(key).casefold() not in sensitive
            }
        if isinstance(value, list):
            return [without_secrets(item) for item in value]
        return value

    with zipfile.ZipFile(
        output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as archive:
        archive.writestr(
            "evaluation_export.json",
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        )
        archive.writestr(
            "manifest.json",
            json.dumps(
                without_secrets(_read_json(root / "manifest.json")),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
        )
        archive.writestr(
            "state.json",
            json.dumps(
                without_secrets(_read_json(root / "state.json")),
                ensure_ascii=False,
                indent=2,
            ) + "\n",
        )
        for relative in dict.fromkeys(relative_files):
            archive.write(root / relative, relative.as_posix())
    return output


def _validated_archive_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if not infos or len(infos) > 2_000:
        raise ValueError("Evaluation archive has an invalid number of files")
    allowed_root = {
        "evaluation_export.json", "manifest.json", "state.json",
        "blind_key.json", "blind_review.csv",
        REVIEW_SYSTEM_PROMPT_FILENAME, REVIEW_GLOSSARY_FILENAME,
        REVIEW_SFX_REFERENCE_FILENAME,
    }
    total_size = 0
    accepted: list[zipfile.ZipInfo] = []
    seen_names: set[str] = set()
    for info in infos:
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        if (
            path.is_absolute()
            or ".." in path.parts
            or not path.parts
            or "\\" in info.filename
        ):
            raise ValueError("Evaluation archive contains an unsafe path")
        unix_mode = info.external_attr >> 16
        if unix_mode and (unix_mode & 0o170000) == 0o120000:
            raise ValueError("Evaluation archive may not contain symbolic links")
        allowed = info.filename in allowed_root or (
            len(path.parts) == 2
            and path.parts[0] == "results"
            and path.suffix.lower() == ".json"
        )
        if not allowed:
            raise ValueError(f"Unexpected file in evaluation archive: {info.filename}")
        if info.filename in seen_names:
            raise ValueError(f"Duplicate file in evaluation archive: {info.filename}")
        seen_names.add(info.filename)
        if info.file_size > 128 * 1024 * 1024:
            raise ValueError(f"Evaluation archive file is too large: {info.filename}")
        total_size += info.file_size
        if total_size > 512 * 1024 * 1024:
            raise ValueError("Evaluation archive expands beyond the safe size limit")
        accepted.append(info)
    names = {info.filename for info in accepted}
    required = {"evaluation_export.json", "manifest.json", "state.json"}
    if not required.issubset(names):
        raise ValueError("Evaluation archive is missing required files")
    return accepted


def import_run_archive(
    project_root: str | Path, archive_path: str | Path
) -> Path:
    """Safely import an exported evaluation as a new, non-overwriting run."""
    archive_file = Path(archive_path)
    maintain_evaluation_storage(project_root)
    archive_root, work_root = _evaluation_storage_roots(project_root)
    archive_root.mkdir(parents=True, exist_ok=True)
    work_root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_file, "r") as archive:
        infos = _validated_archive_members(archive)
        metadata = json.loads(archive.read("evaluation_export.json"))
        state = json.loads(archive.read("state.json"))
        manifest = json.loads(archive.read("manifest.json"))
        if not all(isinstance(item, dict) for item in (metadata, state, manifest)):
            raise ValueError("Evaluation archive metadata is invalid")
        if int(metadata.get("archive_version", 0) or 0) != EVALUATION_ARCHIVE_VERSION:
            raise ValueError("Unsupported evaluation archive version")
        _validate_manifest_integrity(state, manifest)
        archive_names = {info.filename for info in infos}
        candidates = state.get("candidates") or []
        if not isinstance(candidates, list):
            raise ValueError("Evaluation archive candidate list is invalid")
        result_names: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError("Evaluation archive candidate is invalid")
            result_name = str(candidate.get("result_file") or "")
            if not result_name:
                continue
            result_path = PurePosixPath(result_name)
            if (
                len(result_path.parts) != 2
                or result_path.parts[0] != "results"
                or ".." in result_path.parts
                or result_path.suffix.lower() != ".json"
                or result_path.as_posix() not in archive_names
            ):
                raise ValueError("Evaluation archive contains an unsafe result path")
            if result_path.as_posix() in result_names:
                raise ValueError(
                    "Evaluation archive assigns one result file to multiple candidates"
                )
            result_names.add(result_path.as_posix())
            try:
                result = json.loads(archive.read(result_path.as_posix()))
            except (KeyError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("Evaluation archive result file is invalid") from exc
            _validate_result_artifact(candidate, result, state, manifest)

        requires_credentials = False
        for candidate in candidates:
            # Credential names are local authority, not portable evaluation
            # data. Never let an archive select a secret from this machine.
            candidate["key_name"] = ""
            candidate["keyless"] = False
            if candidate.get("status") not in {"completed", "failed"}:
                requires_credentials = True
        if requires_credentials:
            state["credential_binding_required"] = True
        else:
            state.pop("credential_binding_required", None)

        original_id = str(state.get("run_id") or metadata.get("run_id") or "imported")
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "-", original_id).strip(".-")
        safe_id = safe_id or "imported-evaluation"
        if state.get("status") in {"submitted", "partially_submitted"}:
            state["imported_original_status"] = state["status"]
            state["status"] = "imported_paused"
        completed = state.get("status") == "completed"
        target_root = archive_root if completed else work_root
        other_root = work_root if completed else archive_root
        target = _unique_run_path(target_root, safe_id, other_root)

        with tempfile.TemporaryDirectory(
            prefix=".evaluation-import-", dir=target_root
        ) as temporary:
            staging = Path(temporary)
            for info in infos:
                if info.filename == "evaluation_export.json":
                    continue
                destination = staging.joinpath(*PurePosixPath(info.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(archive.read(info))
            state["imported_from_run_id"] = original_id
            state["imported_at"] = _utc_now()
            state["run_id"] = target.name
            state["managed_storage"] = True
            state["storage"] = "completed" if completed else "working"
            if completed:
                state["archived_at"] = state["imported_at"]
            _atomic_write_json(staging / "state.json", state)
            staging.rename(target)

    if completed:
        prune_completed_evaluations(project_root)
    return target


def bind_imported_credentials(
    run_dir: str | Path, bindings: dict[str, dict],
) -> dict:
    """Persist deliberate local key selections for an imported active run."""
    root = Path(run_dir)
    state, _manifest = load_run(root)
    if not state.get("credential_binding_required"):
        return state
    for candidate in state.get("candidates") or []:
        if candidate.get("status") in {"completed", "failed"}:
            continue
        binding = bindings.get(str(candidate.get("id") or ""))
        if not isinstance(binding, dict):
            raise ValueError(
                f"Select a local API key for {candidate.get('label') or candidate.get('id')}"
            )
        key_name = str(binding.get("key_name") or "").strip()
        saved_endpoint = str(binding.get("endpoint") or "").strip().rstrip("/")
        candidate_endpoint = str(candidate.get("endpoint") or "").strip().rstrip("/")
        if not key_name:
            raise ValueError(
                f"Select a local API key for {candidate.get('label') or candidate.get('id')}"
            )
        if not saved_endpoint or saved_endpoint != candidate_endpoint:
            raise ValueError(
                f"The selected key for {candidate.get('label') or candidate.get('id')} "
                "must be saved for that exact API URL"
            )
        candidate["key_name"] = key_name
        candidate["keyless"] = bool(binding.get("keyless", False))
    state.pop("credential_binding_required", None)
    state["credentials_bound_at"] = _utc_now()
    state["updated_at"] = state["credentials_bound_at"]
    _atomic_write_json(root / "state.json", state)
    return state


def resume_imported_run(run_dir: str | Path) -> dict:
    """Explicitly unpause an imported provider job before network polling."""
    root = Path(run_dir)
    state, _manifest = load_run(root)
    if state.get("credential_binding_required"):
        raise ValueError(
            "Select and bind local API keys before reconnecting this imported run"
        )
    if state.get("status") != "imported_paused":
        return state
    original = str(state.get("imported_original_status") or "submitted")
    state["status"] = (
        original if original in {"submitted", "partially_submitted"} else "submitted"
    )
    state["updated_at"] = _utc_now()
    _atomic_write_json(root / "state.json", state)
    return state


def sync_run_history(run_dir: str | Path) -> int:
    """Register existing evaluation provider jobs in shared Batch History."""
    state, manifest = load_run(run_dir)
    from util.batch_history import upsert_history_entry

    synced = 0
    for candidate in state.get("candidates", []):
        batch_id = candidate.get("batch_id")
        if not batch_id:
            continue
        summary = candidate.get("summary") or {}
        local_status = (
            "failed" if candidate.get("status") == "failed"
            else "fetched" if candidate.get("status") == "completed"
            else "ended" if candidate.get("api_status") in {"completed", "ended"}
            else "submitted"
        )
        upsert_history_entry(
            batch_id,
            status=local_status,
            api_status=candidate.get("api_status") or "in_progress",
            provider=candidate.get("provider"),
            model=candidate.get("model"),
            request_count=len(candidate.get("custom_ids") or {}),
            custom_ids=candidate.get("custom_ids") or {},
            cost_estimate=candidate.get("estimate"),
            actual_cost=summary.get("actual_cost_usd"),
            usage=summary.get("usage"),
            file_set=[Path(manifest["source_dir"]).name],
            notes=f"Evaluation {state['run_id']}",
            workflow="evaluation",
            run_id=state["run_id"],
            candidate_id=candidate.get("id"),
            key_name=candidate.get("key_name", ""),
            endpoint=candidate.get("endpoint", ""),
        )
        synced += 1
    return synced


def _provider_params(candidate: dict, request: dict) -> dict:
    provider = candidate["provider"]
    dynamic_context = request["glossary"] + request.get("sfx_reference", "")
    if provider == "anthropic":
        params = buildClaudeRequest(
            request["system"], request["user"], request["history"], "json",
            candidate["model"], request["schema_line_count"],
            vocab_text=dynamic_context,
        )
        # Translation does not need expensive adaptive reasoning. More
        # importantly, this matches GPT reasoning=none and Gemini=minimal.
        params["thinking"] = {"type": "disabled"}
        params["max_tokens"] = MAX_OUTPUT_TOKENS_PER_REQUEST
        return params

    params = buildOpenAIRequest(
        request["system"], request["user"], request["history"], 0.0, "json",
        candidate["model"], request["schema_line_count"],
        vocab_text=dynamic_context, api_provider=provider,
    )
    if provider == "gemini":
        # Gemini's OpenAI-compatible Batch API accepts reasoning_effort
        # directly. Do not emit a top-level ``google`` extension: the batch
        # file validator rejects that transport-internal shape.
        params.pop("temperature", None)
        params.pop("extra_body", None)
        params["reasoning_effort"] = "minimal"
        params["max_tokens"] = MAX_OUTPUT_TOKENS_PER_REQUEST
    else:
        params["max_completion_tokens"] = MAX_OUTPUT_TOKENS_PER_REQUEST
        if (
            candidate.get("execution") == "live"
            and "api.openai.com" not in str(candidate.get("endpoint") or "").lower()
        ):
            # Most local/OpenAI-compatible chat servers implement max_tokens,
            # while current official OpenAI models use max_completion_tokens.
            params["max_tokens"] = params.pop("max_completion_tokens")
    return params


def _clients(candidate: dict, secret: str, *, max_retries: int | None = None):
    provider = candidate["provider"]
    client = batch_api.get_client(
        provider,
        api_key=secret,
        api_url=candidate.get("endpoint") or None,
        max_retries=max_retries,
    )
    google_client = (
        batch_api._google_client(secret) if provider == "gemini" else None
    )
    return client, google_client


def _complete_candidate(
    root: Path, manifest: dict, candidate: dict, raw_results: dict,
    errors: list, usage: dict,
) -> dict:
    """Process either live or batch output through one scoring path."""
    candidate_id = str(candidate.get("id") or "")
    if (
        not re.fullmatch(r"[A-Za-z0-9._-]+", candidate_id)
        or candidate_id in {".", ".."}
    ):
        raise ValueError(f"Unsafe evaluation candidate id {candidate_id!r}")
    processed, summary = _process_results(manifest, raw_results, errors)
    summary["usage"] = usage
    summary["actual_cost_usd"] = _price_usage(candidate, usage)
    summary["stability"] = _stability_score(manifest, processed)
    result_path = root / "results" / f"{candidate_id}.json"
    _atomic_write_json(result_path, {
        **_candidate_artifact_identity(candidate, manifest),
        "summary": summary,
        "executions": processed,
    })
    candidate["status"] = (
        "failed" if _summary_has_no_successes(summary) else "completed"
    )
    candidate["api_status"] = "completed"
    candidate["completed_at"] = _utc_now()
    candidate["result_file"] = str(result_path.relative_to(root))
    candidate["summary"] = summary
    if candidate["status"] == "failed":
        candidate["failure_reason"] = _no_successes_reason(summary)
    else:
        candidate.pop("failure_reason", None)
    return summary


def _run_completion_status(candidates: list[dict]) -> str:
    """Return the aggregate state after all currently available work is processed."""
    statuses = [candidate.get("status") for candidate in candidates]
    if any(status in {"prepared", "running_live"} for status in statuses):
        return "partially_submitted" if any(
            status != "prepared" for status in statuses
        ) else "prepared"
    if any(status == "submitted" for status in statuses):
        return "submitted"
    if statuses and all(status == "completed" for status in statuses):
        return "completed"
    if statuses and all(status in {"completed", "failed"} for status in statuses):
        return "failed"
    return "partially_submitted"


def _is_retryable_live_error(exc: Exception) -> bool:
    """Return whether a live transport failure should remain resumable."""
    status = getattr(exc, "status_code", None)
    if status is None:
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status in {408, 409, 425, 429} or (status is not None and status >= 500):
        return True
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    name = type(exc).__name__.casefold()
    message = str(exc).casefold()
    return (
        any(marker in name for marker in ("connection", "timeout", "ratelimit"))
        or any(
            marker in message
            for marker in (
                "timed out", "timeout", "temporarily unavailable",
                "connection reset", "connection aborted", "connection refused",
                "rate limit", "too many requests", " 429", "429 ",
            )
        )
    )


def _execute_live_candidate(
    root: Path, state: dict, manifest: dict, candidate: dict,
    requests: dict[str, dict], secret: str, log: Callable[[str], None],
    should_stop: Callable[[], bool] | None = None,
) -> tuple[bool, Path]:
    # The evaluator owns the retry/checkpoint policy. Disable the SDKs' hidden
    # retries so LIVE_REQUEST_MAX_ATTEMPTS is the actual network-attempt cap.
    client, _google_client = _clients(candidate, secret, max_retries=0)
    candidate_id = str(candidate.get("id") or "")
    if (
        not re.fullmatch(r"[A-Za-z0-9._-]+", candidate_id)
        or candidate_id in {".", ".."}
    ):
        raise ValueError(f"Unsafe evaluation candidate id {candidate_id!r}")
    checkpoint_path = (
        root / "results" / f"{candidate_id}.live.partial.json"
    )
    empty_usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }
    executions = manifest["executions"]
    execution_ids = {execution["id"] for execution in executions}
    raw_results: dict[str, dict] = {}
    errors: list[list[str]] = []
    usage = dict(empty_usage)
    if checkpoint_path.is_file():
        checkpoint = _read_json(checkpoint_path)
        expected_identity = _candidate_artifact_identity(candidate, manifest)
        require_identity = _requires_artifact_binding(state, manifest)
        for field, expected_value in expected_identity.items():
            actual = checkpoint.get(field)
            if actual is None and not require_identity:
                continue
            if str(actual or "") != expected_value:
                raise ValueError(
                    f"Live evaluation checkpoint does not belong to "
                    f"{candidate['label']}: wrong {field.replace('_', ' ')}"
                )
        saved_results = checkpoint.get("raw_results")
        saved_errors = checkpoint.get("errors")
        saved_usage = checkpoint.get("usage")
        if (
            not isinstance(saved_results, dict)
            or not isinstance(saved_errors, list)
            or not isinstance(saved_usage, dict)
        ):
            raise ValueError(
                f"Live evaluation checkpoint is corrupt: {checkpoint_path}"
            )
        raw_results = dict(saved_results)
        errors = [
            [str(item[0]), str(item[1])]
            for item in saved_errors
            if isinstance(item, (list, tuple)) and len(item) == 2
        ]
        if len(errors) != len(saved_errors):
            raise ValueError(
                f"Live evaluation checkpoint has invalid errors: {checkpoint_path}"
            )
        usage = {
            key: int(saved_usage.get(key, 0) or 0)
            for key in empty_usage
        }
    completed_ids = set(raw_results) | {item[0] for item in errors}
    if not completed_ids.issubset(execution_ids):
        raise ValueError(
            f"Live evaluation checkpoint has unknown requests: {checkpoint_path}"
        )

    total = len(executions)
    candidate["status"] = "running_live"
    candidate["live_completed_requests"] = len(completed_ids)
    candidate["live_total_requests"] = total
    candidate.setdefault("live_started_at", _utc_now())
    state["status"] = "partially_submitted"
    state["updated_at"] = _utc_now()
    _atomic_write_json(root / "state.json", state)
    if completed_ids:
        log(
            f"Resuming {candidate['label']} after {len(completed_ids)}/{total} "
            "checkpointed live requests…"
        )
    else:
        log(f"Running {total} live requests for {candidate['label']}…")

    for index, execution in enumerate(executions, start=1):
        execution_id = execution["id"]
        if execution_id in completed_ids:
            continue
        if should_stop is not None and should_stop():
            log(
                f"{candidate['label']}: paused after "
                f"{len(completed_ids)}/{total} live requests"
            )
            return False, checkpoint_path
        request = requests[execution["logical_request_id"]]
        try:
            result = None
            for attempt in range(1, LIVE_REQUEST_MAX_ATTEMPTS + 1):
                try:
                    result = batch_api.execute_live_request(
                        candidate["provider"],
                        _provider_params(candidate, request),
                        client=client,
                    )
                    candidate.pop("live_retryable_error", None)
                    break
                except Exception as exc:
                    if not _is_retryable_live_error(exc):
                        raise
                    if attempt < LIVE_REQUEST_MAX_ATTEMPTS:
                        delay = 2 ** (attempt - 1)
                        log(
                            f"{candidate['label']} live request {index}/{total} "
                            f"hit a temporary error; retrying in {delay}s "
                            f"({attempt}/{LIVE_REQUEST_MAX_ATTEMPTS}): {exc}"
                        )
                        if should_stop is not None and should_stop():
                            return False, checkpoint_path
                        time.sleep(delay)
                        if should_stop is not None and should_stop():
                            return False, checkpoint_path
                        continue

                    candidate["live_retryable_error"] = str(exc)[:500]
                    state["updated_at"] = _utc_now()
                    _atomic_write_json(root / "state.json", state)
                    log(
                        f"{candidate['label']} live request {index}/{total} remains "
                        "temporarily unavailable after retries. The evaluation was "
                        "paused so Submit can retry this request later."
                    )
                    return False, checkpoint_path

            if result is None:
                return False, checkpoint_path
            raw_results[execution_id] = result
            cached = int(result.get("cache_read_input_tokens", 0) or 0)
            cache_write = int(
                result.get("cache_creation_input_tokens", 0) or 0
            )
            usage["input_tokens"] += max(
                0, int(result.get("prompt_tokens", 0) or 0)
                - cached - cache_write
            )
            usage["output_tokens"] += int(
                result.get("completion_tokens", 0) or 0
            )
            usage["cache_read_input_tokens"] += cached
            usage["cache_creation_input_tokens"] += cache_write
            usage["thinking_tokens"] += int(
                result.get("thinking_tokens", 0) or 0
            )
        except Exception as exc:
            errors.append([execution_id, str(exc)[:500]])
            log(f"{candidate['label']} live request {index}/{total} failed: {exc}")
        completed_ids.add(execution_id)
        candidate["live_completed_requests"] = len(completed_ids)
        state["updated_at"] = _utc_now()
        _atomic_write_json(checkpoint_path, {
            **_candidate_artifact_identity(candidate, manifest),
            "updated_at": state["updated_at"],
            "raw_results": raw_results,
            "errors": errors,
            "usage": usage,
        })
        _atomic_write_json(root / "state.json", state)
        if len(completed_ids) == total or len(completed_ids) % 5 == 0:
            log(
                f"{candidate['label']}: {len(completed_ids)}/{total} "
                "live requests finished"
            )

    summary = _complete_candidate(
        root, manifest, candidate, raw_results, errors, usage
    )
    candidate.pop("live_completed_requests", None)
    candidate.pop("live_total_requests", None)
    candidate.pop("live_started_at", None)
    log(
        f"{candidate['label']}: live results processed "
        f"({summary['valid_rate']:.1%} valid)"
    )
    return True, checkpoint_path


@contextmanager
def _evaluation_submit_lock(run_dir: Path):
    """Prevent two processes from submitting paid work for the same run."""
    lock_path = run_dir / ".submit.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        lock_file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError(
                "This evaluation run is already being submitted by another "
                "DazedTL process. Close the other process or wait for it to finish."
            ) from None
        try:
            yield
        finally:
            lock_file.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def submit_run(run_dir: str | Path, credentials: dict[str, str],
               log: Callable[[str], None] | None = None,
               should_stop: Callable[[], bool] | None = None) -> dict:
    root = Path(run_dir)
    with _evaluation_submit_lock(root):
        return _submit_run_unlocked(root, credentials, log, should_stop)


def _submit_run_unlocked(run_dir: str | Path, credentials: dict[str, str],
                         log: Callable[[str], None] | None = None,
                         should_stop: Callable[[], bool] | None = None) -> dict:
    root = Path(run_dir)
    # Estimates can become stale while a prepared/imported run waits (pricing
    # changes, or a newer release strengthens retry accounting). Recalculate
    # and enforce the budget at the paid boundary, not only during preparation.
    state, manifest = refresh_run_estimates(root)
    if state.get("credential_binding_required"):
        raise ValueError(
            "Select and bind local API keys before submitting this imported run"
        )
    if state["status"] not in {"prepared", "partially_submitted"}:
        raise ValueError(f"Run cannot be submitted from state {state['status']!r}")
    requests = _request_lookup(manifest)
    log = log or (lambda _message: None)

    for candidate in state["candidates"]:
        if should_stop is not None and should_stop():
            break
        if candidate.get("batch_id") or candidate.get("status") in {
            "completed", "failed",
        }:
            continue
        secret = str(credentials.get(candidate["id"]) or "").strip()
        if not secret and not candidate.get("keyless"):
            raise ValueError(f"No API key is available for {candidate['label']}")
        if candidate.get("execution", "batch") == "live":
            completed, checkpoint_path = _execute_live_candidate(
                root, state, manifest, candidate, requests, secret, log,
                should_stop=should_stop,
            )
            state["updated_at"] = _utc_now()
            _atomic_write_json(root / "state.json", state)
            if completed:
                try:
                    checkpoint_path.unlink(missing_ok=True)
                except OSError as exc:
                    log(f"Could not remove completed live checkpoint: {exc}")
            else:
                break
            continue

        custom_ids: dict[str, str] = {}
        batch_requests: list[dict] = []
        for index, execution in enumerate(manifest["executions"], start=1):
            custom_id = f"eval-{index:06d}"
            execution_id = execution["id"]
            request = requests[execution["logical_request_id"]]
            custom_ids[custom_id] = execution_id
            batch_requests.append({
                "custom_id": custom_id,
                "params": _provider_params(candidate, request),
            })
        log(f"Submitting {len(batch_requests)} requests to {candidate['label']}…")
        client, google_client = _clients(candidate, secret)
        submitted = batch_api.submit_batch(
            candidate["provider"], batch_requests,
            client=client, google_client=google_client,
        )
        candidate.update({
            "batch_id": submitted["id"],
            "input_file_id": submitted.get("input_file_id", ""),
            "custom_ids": custom_ids,
            "status": "submitted",
            "submitted_at": _utc_now(),
        })
        state["status"] = "partially_submitted"
        state["updated_at"] = _utc_now()
        _atomic_write_json(root / "state.json", state)
        try:
            from util.batch_history import upsert_history_entry

            upsert_history_entry(
                submitted["id"],
                status="submitted",
                api_status="in_progress",
                provider=candidate["provider"],
                model=candidate["model"],
                request_count=len(custom_ids),
                custom_ids=custom_ids,
                cost_estimate=candidate["estimate"],
                file_set=[Path(manifest["source_dir"]).name],
                notes=f"Evaluation {state['run_id']}",
                workflow="evaluation",
                run_id=state["run_id"],
                candidate_id=candidate["id"],
                key_name=candidate.get("key_name", ""),
                endpoint=candidate.get("endpoint", ""),
            )
        except Exception as exc:
            log(f"Batch History registration failed: {exc}")
        log(f"{candidate['label']}: {submitted['id']}")

    state["status"] = _run_completion_status(state["candidates"])
    state["updated_at"] = _utc_now()
    _atomic_write_json(root / "state.json", state)
    _archive_completed_run(root, state)
    return state


def _normalized_translation(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip()).casefold()


def _price_usage(candidate: dict, usage: dict) -> float:
    rates = _candidate_rates(candidate)
    regular = int(usage.get("input_tokens", 0) or 0)
    cached = int(usage.get("cache_read_input_tokens", 0) or 0)
    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    output = int(usage.get("output_tokens", 0) or 0)
    thinking = int(usage.get("thinking_tokens", 0) or 0)
    return (
        regular * rates["input"]
        + cached * rates["cached_input"]
        + cache_write * rates["input"] * 2.0
        + (output + thinking) * rates["output"]
    ) / 1_000_000


def _process_results(manifest: dict, raw_results: dict,
                     provider_errors: list) -> tuple[dict, dict]:
    request_by_id = _request_lookup(manifest)
    execution_by_id = {item["id"]: item for item in manifest["executions"]}
    processed: dict[str, dict] = {}
    valid_segments = 0
    warning_segments = 0
    total_segments = sum(
        len(request_by_id[execution["logical_request_id"]]["segment_ids"])
        for execution in manifest["executions"]
    )
    validation_failures = 0

    for execution_id, raw in raw_results.items():
        execution = execution_by_id.get(execution_id)
        if not execution:
            continue
        request = request_by_id[execution["logical_request_id"]]
        translations = extractTranslation(raw.get("text", ""), True)
        issues: list[str] = []
        if not isinstance(translations, list):
            translations = []
            issues.append("Response was not parseable JSON")
        if len(translations) != len(request["segment_ids"]):
            issues.append(
                f"Line count differs ({len(request['segment_ids'])} expected, "
                f"{len(translations)} returned)"
            )

        lines: list[dict] = []
        for index, segment_id in enumerate(request["segment_ids"]):
            source = request["sources"][index]
            protected_source = request["protected_sources"][index]
            replacements = request["replacements"][index]
            raw_translation = translations[index] if index < len(translations) else ""
            line_issues: list[str] = list(issues)
            placeholders_ok, missing, extra = validate_placeholders(
                protected_source, raw_translation, replacements
            )
            if not placeholders_ok:
                line_issues.append(
                    "Placeholder mismatch: " + ", ".join((*missing, *extra))
                )
            restored = restore_script_codes(raw_translation, replacements)
            controls_ok, control_issues = validate_control_codes(
                [source], [restored], {0: replacements}
            )
            if not controls_ok:
                line_issues.extend(control_issues)
            content_ok, _indices, content_issues = validate_translation_content(
                [protected_source], [raw_translation], LANGUAGE_REGEX
            )
            if not content_ok:
                line_issues.extend(content_issues)
            _warning_indices, line_warnings = translation_content_warnings(
                [protected_source], [raw_translation], LANGUAGE_REGEX
            )
            if line_warnings:
                warning_segments += 1
            if not line_issues:
                valid_segments += 1
            else:
                validation_failures += 1
            lines.append({
                "segment_id": segment_id,
                "source": source,
                "translation": restored,
                "valid": not line_issues,
                "issues": line_issues,
                "warnings": line_warnings,
            })
        processed[execution_id] = {
            "logical_request_id": execution["logical_request_id"],
            "repetition": execution["repetition"],
            "logical_hash": request["logical_hash"],
            "request_issues": issues,
            "lines": lines,
            "usage": {
                key: raw.get(key, 0)
                for key in (
                    "prompt_tokens", "completion_tokens",
                    "cache_read_input_tokens", "cache_creation_input_tokens",
                    "thinking_tokens",
                )
            },
        }

    expected_requests = len(manifest["executions"])
    missing_requests = max(0, expected_requests - len(processed))
    # Entirely missing requests count as invalid too; otherwise a provider
    # could receive an artificially high validity rate by returning less data.
    validation_failures = total_segments - valid_segments
    summary = {
        "expected_requests": expected_requests,
        "received_requests": len(processed),
        "missing_requests": missing_requests,
        "provider_errors": provider_errors,
        "total_segments": total_segments,
        "valid_segments": valid_segments,
        "warning_segments": warning_segments,
        "validation_failures": validation_failures,
        "valid_rate": (valid_segments / total_segments) if total_segments else 0.0,
    }
    return processed, summary


def _stability_score(manifest: dict, processed: dict) -> dict:
    request_by_id = _request_lookup(manifest)
    values: dict[str, list[str]] = defaultdict(list)
    sample_values: dict[str, list[tuple[str, ...]]] = defaultdict(list)
    for execution_id, result in processed.items():
        request = request_by_id[result["logical_request_id"]]
        if request["id"] not in manifest["stability_request_ids"]:
            continue
        valid_by_segment: dict[str, str] = {}
        for line in result["lines"]:
            if line["valid"]:
                normalized = _normalized_translation(line["translation"])
                values[line["segment_id"]].append(normalized)
                valid_by_segment[line["segment_id"]] = normalized
        if (
            len(result["lines"]) == len(request["segment_ids"])
            and len(valid_by_segment) == len(request["segment_ids"])
            and set(valid_by_segment) == set(request["segment_ids"])
        ):
            sample_values[request["id"]].append(tuple(
                valid_by_segment[segment_id]
                for segment_id in request["segment_ids"]
            ))
    required = manifest["repetitions"]
    stable = sum(
        1 for translations in values.values()
        if len(translations) == required and len(set(translations)) == 1
    )
    eligible = sum(1 for translations in values.values() if len(translations) == required)
    stable_samples = sum(
        1 for translations in sample_values.values()
        if len(translations) == required and len(set(translations)) == 1
    )
    eligible_samples = sum(
        1 for translations in sample_values.values()
        if len(translations) == required
    )
    return {
        "segments_with_all_repetitions": eligible,
        "exactly_stable_segments": stable,
        "exact_stability_rate": (stable / eligible) if eligible else 0.0,
        "samples_with_all_repetitions": eligible_samples,
        "exactly_stable_samples": stable_samples,
        "exact_sample_stability_rate": (
            stable_samples / eligible_samples if eligible_samples else 0.0
        ),
    }


def refresh_run(run_dir: str | Path, credentials: dict[str, str],
                log: Callable[[str], None] | None = None) -> dict:
    root = Path(run_dir)
    state, manifest = load_run(root)
    log = log or (lambda _message: None)
    if state.get("credential_binding_required"):
        raise ValueError(
            "Select and bind local API keys before refreshing this imported run"
        )
    if state["status"] == "prepared":
        return state

    for candidate in state["candidates"]:
        batch_id = candidate.get("batch_id")
        if not batch_id:
            continue
        if candidate.get("status") in {"completed", "failed"}:
            continue
        secret = str(credentials.get(candidate["id"]) or "").strip()
        if not secret and not candidate.get("keyless"):
            raise ValueError(f"No API key is available for {candidate['label']}")
        client, google_client = _clients(candidate, secret)
        status = batch_api.retrieve_batch(candidate["provider"], batch_id, client=client)
        candidate["api_status"] = status["api_status"]
        candidate["counts"] = status["counts"]
        try:
            from util.batch_history import upsert_history_entry

            upsert_history_entry(
                batch_id,
                api_status=status["api_status"],
                request_counts=status["counts"],
                status="ended" if status["ended"] else "submitted",
            )
        except Exception as exc:
            log(f"Batch History update failed: {exc}")
        log(f"{candidate['label']}: {status['api_status']}")
        if not status["ended"]:
            candidate["status"] = "submitted"
            continue

        raw_results, errors, usage = batch_api.download_results(
            candidate["provider"], batch_id, candidate["custom_ids"],
            client=client, google_client=google_client,
        )
        summary = _complete_candidate(
            root, manifest, candidate, raw_results, errors, usage
        )
        # Preserve the provider's terminal wording for Batch History while the
        # evaluator UI presents the locally processed state as Completed.
        candidate["api_status"] = status["api_status"]
        try:
            from util.batch_history import upsert_history_entry

            upsert_history_entry(
                batch_id,
                status=(
                    "failed" if candidate.get("status") == "failed" else "fetched"
                ),
                api_status=status["api_status"],
                usage=usage,
                actual_cost=summary["actual_cost_usd"],
                notes=f"Evaluation {state['run_id']} results fetched",
            )
        except Exception as exc:
            log(f"Batch History result update failed: {exc}")

    state["status"] = _run_completion_status(state["candidates"])
    state["updated_at"] = _utc_now()
    _atomic_write_json(root / "state.json", state)
    _archive_completed_run(root, state)
    return state


def _candidate_results(
    run_dir: Path, state: dict, manifest: dict,
    candidate_ids: list[str] | None = None,
) -> dict[str, dict]:
    selected = set(candidate_ids) if candidate_ids is not None else None
    results = {}
    paths: set[str] = set()
    for candidate in state["candidates"]:
        if selected is not None and candidate["id"] not in selected:
            continue
        relative = str(candidate.get("result_file") or "")
        if not relative:
            continue
        result_path = Path(relative)
        if (
            len(result_path.parts) != 2
            or result_path.parts[0] != "results"
            or ".." in result_path.parts
            or result_path.suffix.lower() != ".json"
        ):
            raise ValueError("Evaluation candidate has an unsafe result path")
        normalized = result_path.as_posix()
        if normalized in paths:
            raise ValueError(
                "Evaluation candidates cannot share the same result file"
            )
        paths.add(normalized)
        result = _read_json(run_dir / result_path)
        _validate_result_artifact(candidate, result, state, manifest)
        results[candidate["id"]] = result
    return results


def _review_candidate_ids(state: dict, candidate_ids: list[str] | None) -> list[str]:
    """Validate and normalize a requested blind-review candidate subset."""
    known = [str(candidate["id"]) for candidate in state.get("candidates") or []]
    if candidate_ids is None:
        selected = known
    else:
        requested = [str(candidate_id) for candidate_id in candidate_ids]
        if len(requested) != len(set(requested)):
            raise ValueError("Blind review model selection contains duplicates")
        unknown = sorted(set(requested) - set(known))
        if unknown:
            raise ValueError(
                "Blind review model selection contains unknown candidates: "
                + ", ".join(unknown)
            )
        selected = [candidate_id for candidate_id in known if candidate_id in requested]
    if len(selected) < 2:
        raise ValueError("Select at least two models for a blind review")
    return selected


def blind_review_candidates(run_dir: str | Path) -> list[dict]:
    """Return candidate availability for the blind-review model selector."""
    root = Path(run_dir)
    state, manifest = load_run(root)
    if state.get("status") not in {"completed", "failed"}:
        raise ValueError("All comparison models must finish before blind export")
    choices = []
    for candidate in state.get("candidates") or []:
        candidate_id = str(candidate["id"])
        valid_primary = 0
        reason = ""
        try:
            result = _candidate_results(
                root, state, manifest, [candidate_id]
            ).get(candidate_id)
            if result is None:
                raise ValueError("result file is missing")
            for execution in (result.get("executions") or {}).values():
                if execution.get("repetition") != 1:
                    continue
                valid_primary += sum(
                    1 for line in execution.get("lines") or []
                    if line.get("valid", True) and line.get("segment_id")
                )
            if not valid_primary:
                reason = "No valid primary translations"
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            reason = str(exc)
        available = valid_primary > 0
        choices.append({
            "id": candidate_id,
            "label": str(
                candidate.get("label") or candidate.get("model") or candidate_id
            ),
            "status": str(candidate.get("status") or "unknown"),
            "valid_primary": valid_primary,
            "available": available,
            "selected_by_default": (
                available and candidate.get("status") == "completed"
            ),
            "reason": reason,
        })
    return choices


def _blind_review_data(
    root: Path, state: dict, manifest: dict,
    candidate_ids: list[str] | None = None,
) -> tuple[
    dict[str, dict], dict[str, dict[str, str]], list[dict], dict,
]:
    """Collect valid primary outputs and calculate export coverage."""
    candidate_ids = _review_candidate_ids(state, candidate_ids)
    candidates = [
        candidate for candidate in state.get("candidates") or []
        if candidate["id"] in candidate_ids
    ]
    results = _candidate_results(root, state, manifest, candidate_ids)
    if set(results) != set(candidate_ids):
        missing = [
            candidate.get("label") or candidate.get("model") or candidate["id"]
            for candidate in candidates if candidate["id"] not in results
        ]
        raise ValueError(
            "Cannot export blind review: missing result files for "
            + ", ".join(missing)
            + "."
        )

    primary: dict[str, dict[str, str]] = defaultdict(dict)
    valid_primary = {candidate_id: 0 for candidate_id in candidate_ids}
    for candidate_id, result in results.items():
        for execution in (result.get("executions") or {}).values():
            if execution.get("repetition") != 1:
                continue
            for line in execution.get("lines") or []:
                if not line.get("valid", True):
                    continue
                segment_id = line.get("segment_id")
                if not segment_id:
                    continue
                primary[segment_id][candidate_id] = line.get("translation", "")
                valid_primary[candidate_id] += 1

    failed = []
    for candidate in candidates:
        candidate_id = candidate["id"]
        summary = candidate.get("summary") or results[candidate_id].get("summary") or {}
        expected = int(summary.get("expected_requests", 0) or 0)
        received = int(summary.get("received_requests", 0) or 0)
        errors = summary.get("provider_errors") or []
        if expected > 0 and received == 0:
            label = candidate.get("label") or candidate.get("model") or candidate_id
            detail = f"{label}: 0/{expected} requests received"
            if errors:
                detail += f", {len(errors)} provider errors"
                first_error = str(errors[0][1] if isinstance(errors[0], (list, tuple)) and len(errors[0]) > 1 else errors[0])
                if first_error:
                    detail += f" (first error: {first_error})"
            failed.append(detail)
        elif valid_primary[candidate_id] == 0:
            label = candidate.get("label") or candidate.get("model") or candidate_id
            failed.append(f"{label}: no valid primary translations")
    if failed:
        raise ValueError(
            "Cannot export blind review because one or more candidates produced "
            "no usable results: " + "; ".join(failed)
        )

    eligible = [
        segment for segment in manifest.get("segments") or []
        if set(primary.get(segment["id"], {})) == set(candidate_ids)
    ]
    eligible_ids = {segment["id"] for segment in eligible}
    segment_by_id = {
        segment["id"]: segment for segment in manifest.get("segments") or []
    }
    logical_requests = manifest.get("logical_requests") or [
        {
            "id": segment["id"],
            "scene_id": segment["scene_id"],
            "stratum": segment["stratum"],
            "segment_ids": [segment["id"]],
            "sources": [segment["source"]],
        }
        for segment in manifest.get("segments") or []
    ]
    review_samples = []
    for request in logical_requests:
        segment_ids = list(request.get("segment_ids") or [])
        if not segment_ids or not all(
            segment_id in eligible_ids for segment_id in segment_ids
        ):
            continue
        sample_segments = [segment_by_id[segment_id] for segment_id in segment_ids]
        review_samples.append({
            "id": str(request.get("id") or sample_segments[0]["id"]),
            "scene_id": str(
                request.get("scene_id") or sample_segments[0]["scene_id"]
            ),
            "stratum": str(
                request.get("stratum") or sample_segments[0]["stratum"]
            ),
            "segment_ids": segment_ids,
            "sources": list(request.get("sources") or [
                segment["source"] for segment in sample_segments
            ]),
        })
    total = len(manifest.get("segments") or [])
    coverage = {
        "total_segments": total,
        "eligible_segments": len(eligible),
        "excluded_segments": total - len(eligible),
        "total_samples": len(logical_requests),
        "eligible_samples": len(review_samples),
        "excluded_samples": len(logical_requests) - len(review_samples),
        "valid_primary_by_candidate": valid_primary,
        "candidate_ids": candidate_ids,
    }
    if not eligible:
        raise ValueError(
            "Cannot export blind review: none of the "
            f"{total} segments has a valid primary translation from every candidate."
        )
    if not review_samples:
        raise ValueError(
            "Cannot export blind review: no complete multi-line sample has a "
            "valid primary translation from every candidate."
        )
    return results, primary, review_samples, coverage


def blind_review_coverage(
    run_dir: str | Path, candidate_ids: list[str] | None = None,
) -> dict:
    """Return the samples and lines a blind export would contain."""
    root = Path(run_dir)
    state, manifest = load_run(root)
    if state.get("status") not in {"completed", "failed"}:
        raise ValueError("All comparison models must finish before blind export")
    _results, _primary, _eligible, coverage = _blind_review_data(
        root, state, manifest, candidate_ids
    )
    return coverage


def _blind_label(index: int) -> str:
    """Return spreadsheet-style labels: A..Z, AA..AZ, BA..."""
    label = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("A") + remainder) + label
    return label


def export_blind_review_context(
    run_dir: str | Path, output_dir: str | Path | None = None
) -> tuple[Path, Path, Path]:
    """Write model-blind snapshots of the exact translation review context."""
    root = Path(run_dir)
    _state, manifest = load_run(root)
    requests = manifest.get("logical_requests") or []
    systems = list(dict.fromkeys(
        str(request.get("system") or "").strip()
        for request in requests
        if str(request.get("system") or "").strip()
    ))
    system_text = "\n\n".join(systems)
    if not system_text:
        raise ValueError("Evaluation manifest has no translation system prompt")

    glossary_lines: list[str] = []
    seen_lines: set[str] = set()
    for request in requests:
        for line in str(request.get("glossary") or "").splitlines():
            normalized = line.rstrip()
            if normalized in seen_lines:
                continue
            seen_lines.add(normalized)
            glossary_lines.append(normalized)
    glossary_text = "\n".join(glossary_lines).strip()
    if not glossary_text:
        glossary_text = "(No glossary entries matched the reviewed source text.)"

    sfx_lines: list[str] = []
    seen_sfx_lines: set[str] = set()
    for request in requests:
        for line in str(request.get("sfx_reference") or "").splitlines():
            normalized = line.rstrip()
            if normalized in seen_sfx_lines:
                continue
            seen_sfx_lines.add(normalized)
            sfx_lines.append(normalized)
    sfx_text = "\n".join(sfx_lines).strip()
    if not sfx_text:
        sfx_text = (
            "(No Japanese SFX reference entries matched the reviewed source text.)"
        )

    destination = Path(output_dir) if output_dir is not None else root
    system_path = destination / REVIEW_SYSTEM_PROMPT_FILENAME
    glossary_path = destination / REVIEW_GLOSSARY_FILENAME
    sfx_path = destination / REVIEW_SFX_REFERENCE_FILENAME
    _atomic_write_text(system_path, system_text)
    _atomic_write_text(glossary_path, glossary_text)
    _atomic_write_text(sfx_path, sfx_text)
    return system_path.resolve(), glossary_path.resolve(), sfx_path.resolve()


def export_blind_review(
    run_dir: str | Path, output_path: str | Path | None = None,
    candidate_ids: list[str] | None = None,
) -> Path:
    root = Path(run_dir)
    state, manifest = load_run(root)
    if state.get("status") not in {"completed", "failed"}:
        raise ValueError("All comparison models must finish before blind export")
    candidate_ids = _review_candidate_ids(state, candidate_ids)
    _results, primary, review_samples, _coverage = _blind_review_data(
        root, state, manifest, candidate_ids
    )

    output = Path(output_path) if output_path else root / "blind_review.csv"
    key: dict[str, dict[str, str]] = {}
    blind_labels = [_blind_label(index) for index in range(len(candidate_ids))]
    quality_fields = [f"{metric}_ranking" for metric in REVIEW_QUALITY_METRICS]
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=(
            "sample_id", "scene_id", "stratum", "line_count", "segment_ids",
            "source",
            *blind_labels, *quality_fields, "ranking", "notes",
        ))
        writer.writeheader()
        for sample in review_samples:
            shuffled = list(candidate_ids)
            random.Random(f"{state['run_id']}:{sample['id']}").shuffle(shuffled)
            labels = {
                label: candidate_id
                for label, candidate_id in zip(blind_labels, shuffled)
            }
            key[sample["id"]] = labels
            writer.writerow({
                "sample_id": sample["id"],
                "scene_id": sample["scene_id"],
                "stratum": sample["stratum"],
                "line_count": len(sample["segment_ids"]),
                "segment_ids": json.dumps(sample["segment_ids"], ensure_ascii=False),
                "source": json.dumps(sample["sources"], ensure_ascii=False, indent=2),
                **{
                    label: json.dumps([
                        primary[segment_id][candidate_id]
                        for segment_id in sample["segment_ids"]
                    ], ensure_ascii=False, indent=2)
                    for label, candidate_id in labels.items()
                },
                **{field: "" for field in quality_fields},
                "ranking": "",
                "notes": "",
            })
    canonical_review = root / "blind_review.csv"
    if output.resolve() != canonical_review.resolve():
        shutil.copyfile(output, canonical_review)
    export_blind_review_context(root, output.parent)
    if output.parent.resolve() != root.resolve():
        export_blind_review_context(root, root)
    _atomic_write_json(root / "blind_key.json", key)
    return output


def _parse_blind_ranking(value: str, labels: list[str]) -> list[list[str]]:
    """Parse a complete blinded ranking such as ``A=B>C``.

    ``>`` separates ordered tiers and ``=`` joins candidates tied within a
    tier. Every randomized label must occur exactly once. Legacy ``TIE`` and
    ``=`` values mean that every candidate is tied.
    """
    ranking = "".join(str(value or "").upper().split())
    if ranking in {"TIE", "="}:
        return [list(labels)]
    if not ranking:
        return []
    tiers = [tier.split("=") for tier in ranking.split(">")]
    flattened = [label for tier in tiers for label in tier]
    if (
        any(not tier or any(not label for label in tier) for tier in tiers)
        or len(flattened) != len(labels)
        or len(set(flattened)) != len(flattened)
        or set(flattened) != set(labels)
    ):
        expected = ">".join(labels)
        raise ValueError(
            f"Invalid ranking {value!r}; use every label exactly once "
            f"(for example {expected} or {'='.join(labels)})"
        )
    return tiers


def _ranking_points(tiers: list[list[str]]) -> dict[str, float]:
    """Award fixed-sum Borda points, averaging positions occupied by ties."""
    candidate_count = sum(len(tier) for tier in tiers)
    points: dict[str, float] = {}
    position = 0
    for tier in tiers:
        occupied = range(position, position + len(tier))
        award = sum(candidate_count - 1 - index for index in occupied) / len(tier)
        for label in tier:
            points[label] = award
        position += len(tier)
    return points


def import_blind_review(run_dir: str | Path, review_path: str | Path) -> dict:
    root = Path(run_dir)
    state, manifest = load_run(root)
    key = _read_json(root / "blind_key.json")
    keyed_candidates = {
        str(candidate_id)
        for labels in key.values() if isinstance(labels, dict)
        for candidate_id in labels.values()
    }
    candidate_ids = [
        str(candidate["id"]) for candidate in state.get("candidates") or []
        if str(candidate["id"]) in keyed_candidates
    ]
    _results, primary, review_samples, _coverage = _blind_review_data(
        root, state, manifest, candidate_ids
    )
    expected_samples = {
        str(sample["id"]): sample for sample in review_samples
    }
    expected_line_counts = {
        str(request.get("id")): len(request.get("segment_ids") or [])
        for request in manifest.get("logical_requests") or []
        if request.get("id")
    }
    expected_line_counts.update({
        str(segment.get("id")): 1
        for segment in manifest.get("segments") or []
        if segment.get("id")
    })
    wins = {candidate["id"]: 0 for candidate in state["candidates"]}
    points = {candidate["id"]: 0.0 for candidate in state["candidates"]}
    first_place = {candidate["id"]: 0 for candidate in state["candidates"]}
    ties = 0
    partial_ties = 0
    reviewed = 0
    reviewed_lines = 0
    seen_samples: set[str] = set()
    quality_points = {
        metric: {candidate["id"]: 0.0 for candidate in state["candidates"]}
        for metric in REVIEW_QUALITY_METRICS
    }
    quality_first_place = {
        metric: {candidate["id"]: 0 for candidate in state["candidates"]}
        for metric in REVIEW_QUALITY_METRICS
    }
    with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = set(reader.fieldnames or [])
        quality_fields = {
            metric: f"{metric}_ranking" for metric in REVIEW_QUALITY_METRICS
        }
        has_quality_rankings = any(
            field in fieldnames for field in quality_fields.values()
        )
        if has_quality_rankings:
            missing_fields = sorted(set(quality_fields.values()) - fieldnames)
            if missing_fields:
                raise ValueError(
                    "Reviewed CSV is missing quality ranking columns: "
                    + ", ".join(missing_fields)
                )
        for row in reader:
            ranking_value = str(row.get("ranking") or "").strip()
            legacy_winner = str(row.get("winner") or "").strip().upper()
            if not ranking_value and not legacy_winner:
                continue
            review_id = str(
                row.get("sample_id") or row.get("segment_id") or ""
            )
            if review_id in seen_samples:
                raise ValueError(f"Duplicate reviewed sample {review_id!r}")
            labels_to_candidates = key.get(review_id) or {}
            labels = list(labels_to_candidates)
            if not labels or any(
                candidate_id not in wins
                for candidate_id in labels_to_candidates.values()
            ):
                raise ValueError(f"Unknown reviewed sample {review_id!r}")

            # Rankings are meaningful only when the reviewer saw the exact
            # frozen source and candidate outputs that were exported. CSV and
            # spreadsheet tools may rewrite cells, so validate every protected
            # field against the run artifacts before attributing a score.
            sample = expected_samples.get(review_id)
            if sample is None:
                raise ValueError(f"Unknown reviewed sample {review_id!r}")

            def _review_json(field: str):
                value = str(row.get(field) or "").strip()
                try:
                    return json.loads(value)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"Protected review field {field!r} is invalid for "
                        f"sample {review_id!r}"
                    ) from exc

            protected_scalars = {
                "scene_id": str(sample["scene_id"]),
                "stratum": str(sample["stratum"]),
            }
            for field, expected_value in protected_scalars.items():
                if str(row.get(field) or "") != expected_value:
                    raise ValueError(
                        f"Protected review field {field!r} changed for "
                        f"sample {review_id!r}"
                    )
            if _review_json("segment_ids") != list(sample["segment_ids"]):
                raise ValueError(
                    f"Protected segment IDs changed for sample {review_id!r}"
                )
            if _review_json("source") != list(sample["sources"]):
                raise ValueError(
                    f"Protected source text changed for sample {review_id!r}"
                )
            for label, candidate_id in labels_to_candidates.items():
                expected_translations = [
                    primary[segment_id][candidate_id]
                    for segment_id in sample["segment_ids"]
                ]
                if _review_json(label) != expected_translations:
                    raise ValueError(
                        f"Protected candidate text {label!r} changed for "
                        f"sample {review_id!r}"
                    )
            try:
                if ranking_value:
                    tiers = _parse_blind_ranking(ranking_value, labels)
                elif legacy_winner in {"TIE", "="}:
                    tiers = [labels]
                else:
                    if legacy_winner not in labels_to_candidates:
                        raise ValueError(f"Invalid winner {legacy_winner!r}")
                    remaining = [
                        label for label in labels if label != legacy_winner
                    ]
                    tiers = [[legacy_winner]]
                    if remaining:
                        tiers.append(remaining)
            except ValueError as exc:
                raise ValueError(
                    f"{exc} for sample {review_id!r}"
                ) from exc

            expected_line_count = expected_line_counts.get(review_id, 1)
            line_count_value = str(row.get("line_count") or "").strip()
            try:
                line_count = (
                    int(line_count_value)
                    if line_count_value else expected_line_count
                )
            except ValueError as exc:
                raise ValueError(
                    f"Invalid line count {line_count_value!r} for sample "
                    f"{review_id!r}"
                ) from exc
            if line_count < 1:
                raise ValueError(
                    f"Invalid line count {line_count!r} for sample {review_id!r}"
                )
            if line_count != expected_line_count:
                raise ValueError(
                    f"Protected line count changed for sample {review_id!r}: "
                    f"expected {expected_line_count}, found {line_count}"
                )

            if has_quality_rankings:
                for metric, field in quality_fields.items():
                    try:
                        metric_tiers = _parse_blind_ranking(
                            str(row.get(field) or ""), labels
                        )
                    except ValueError as exc:
                        raise ValueError(
                            f"Invalid {field} for sample {review_id!r}: {exc}"
                        ) from exc
                    if not metric_tiers:
                        raise ValueError(
                            f"Missing {field} for sample {review_id!r}"
                        )
                    for label, award in _ranking_points(metric_tiers).items():
                        candidate_id = labels_to_candidates[label]
                        quality_points[metric][candidate_id] += award * line_count
                    for label in metric_tiers[0]:
                        quality_first_place[metric][labels_to_candidates[label]] += 1

            row_points = _ranking_points(tiers)
            for label, award in row_points.items():
                points[labels_to_candidates[label]] += award * line_count
            for label in tiers[0]:
                first_place[labels_to_candidates[label]] += 1
            if len(tiers[0]) == 1:
                wins[labels_to_candidates[tiers[0][0]]] += 1
            if len(tiers) == 1:
                ties += 1
            elif any(len(tier) > 1 for tier in tiers):
                partial_ties += 1
            seen_samples.add(review_id)
            reviewed += 1
            reviewed_lines += line_count
    points = {
        candidate_id: int(score) if score.is_integer() else score
        for candidate_id, score in points.items()
    }
    if has_quality_rankings:
        quality_points = {
            metric: {
                candidate_id: int(score) if score.is_integer() else score
                for candidate_id, score in scores.items()
            }
            for metric, scores in quality_points.items()
        }
    else:
        quality_points = {}
        quality_first_place = {}
    human = {
        "reviewed": reviewed,
        "reviewed_lines": reviewed_lines,
        "ties": ties,
        "partial_ties": partial_ties,
        "wins": wins,
        "first_place": first_place,
        "points": points,
        "quality_points": quality_points,
        "quality_first_place": quality_first_place,
        "reviewed_candidate_ids": candidate_ids,
        "scoring": "fixed-sum-borda-average-per-line-v2",
        "imported_at": _utc_now(),
    }
    review_source = Path(review_path)
    canonical_review = root / "blind_review.csv"
    if review_source.resolve() != canonical_review.resolve():
        shutil.copyfile(review_source, canonical_review)
    state["human_review"] = human
    state["updated_at"] = _utc_now()
    _atomic_write_json(root / "state.json", state)
    return human


def context_audit(manifest: dict) -> dict:
    """Return manifest invariants used by the UI and automated tests."""
    hashes = [request["logical_hash"] for request in manifest["logical_requests"]]
    return {
        "manifest_sha256": manifest["manifest_sha256"],
        "logical_requests": len(hashes),
        "unique_logical_hashes": len(set(hashes)),
        "segments": len(manifest["segments"]),
        "executions": len(manifest["executions"]),
        "all_have_system": all(bool(r["system"].strip()) for r in manifest["logical_requests"]),
        "all_have_source": all(bool(r["sources"]) for r in manifest["logical_requests"]),
        "history_limit_ok": all(len(r["history"]) <= 10 for r in manifest["logical_requests"]),
    }
