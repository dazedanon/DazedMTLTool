"""Independent verifier for deterministic RPG Maker QA manifests.

The verifier intentionally does not import the inventory builder.  It rescans
the JSON corpus, rediscovers preserved-source leaves, resolves every recorded
pointer, and recomputes identities, speakers, clusters, ordering, and hashes.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA = "rpgmaker-qa-manifest-v1"
DIALOGUE = {101, 102, 401, 405}
RISKY = {108, 111, 122, 320, 324, 325, 355, 356, 357, 408, 655, 657}
DATABASE = {
    "Actors.json",
    "Armors.json",
    "Classes.json",
    "Enemies.json",
    "Items.json",
    "MapInfos.json",
    "Skills.json",
    "States.json",
    "System.json",
    "Weapons.json",
}
SCALAR_PARAMETER = {108: 0, 122: 4, 320: 1, 324: 1, 325: 1, 355: 0, 356: 0, 408: 0, 655: 0, 657: 0}
CODE357_TEXT_ARGUMENTS = {
    "LL_InfoPopupWIndow": ("messageText",),
    "QuestSystem": ("DetailNote",),
    "BalloonInBattle": ("text",),
    "MNKR_CommonPopupCoreMZ": ("text",),
    "DestinationWindow": ("destination",),
    "_TMLogWindowMZ": ("text",),
    "TorigoyaMZ_NotifyMessage": ("message",),
    "SoR_GabWindow": ("arg1",),
    "DarkPlasma_CharacterText": ("text",),
    "DTextPicture": ("text",),
    "TextPicture": ("text",),
    "TRP_SkitMZ": ("name",),
    "LogMessage": ("text",),
    "LogWindow": ("text",),
    "BattleLogOutput": ("message",),
    "TorigoyaMZ_NotifyMessage_CommandMessage": ("message",),
    "NUUN_SaveScreen": ("AnyName",),
    "build/ARPG_Core": ("Text", "SkillByName"),
    "EventLabel": ("text",),
    "KN_MapBattle": ("enemyName",),
    "KN_Shop": ("goodsType",),
    "KN_StillManager": ("label",),
    "Mano_CurrencyUnit": ("unit",),
    "SceneGlossary": ("category",),
}
_RUNTIME_TOKEN_RE = re.compile(
    r"\\(?:[A-Za-z]+\[[^\]\r\n]*\]|[{}.!|^><])"
    r"|__PROTECTED_\d+__"
    r"|%(?:\d+\$)?[-+#0 ]*(?:\d+|\*)?(?:\.\d+)?[A-Za-z]"
)
_JAPANESE_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]")
_VISIBLE_NUMBER_RE = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?(?![\w])")


def _hash(value: bytes | str) -> str:
    return hashlib.sha256(value.encode("utf-8") if isinstance(value, str) else value).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _pointer(parts: tuple[object, ...]) -> str:
    def encode(value: object) -> str:
        return str(value).replace("~", "~0").replace("/", "~1")

    return "" if not parts else "/" + "/".join(encode(part) for part in parts)


def _resolve(document: Any, pointer: str) -> Any:
    value = document
    if pointer:
        if not pointer.startswith("/"):
            raise KeyError(pointer)
        for encoded in pointer[1:].split("/"):
            key = encoded.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def _leaves(value: Any, parts: tuple[object, ...] = ()):
    if isinstance(value, str):
        if value.strip():
            yield parts, value
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _leaves(child, parts + (index,))
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _leaves(value[key], parts + (key,))


def _classify(filename: str, value: dict[str, Any]) -> str:
    code = value.get("code") if isinstance(value.get("code"), int) else None
    event_file = filename in {"CommonEvents.json", "Troops.json"} or bool(
        re.fullmatch(r"Map\d+\.json", filename)
    )
    if event_file and code in DIALOGUE:
        return "dialogue"
    if event_file and code in RISKY:
        return "risky-codes"
    if code is None and filename in DATABASE:
        return "database"
    return "other"


def _inventory(document: Any, filename: str, focus: str) -> list[tuple[str, str, str]]:
    found: list[tuple[str, str, str]] = []

    def visit(value: Any, parts: tuple[object, ...]) -> None:
        if isinstance(value, dict):
            if "_original" in value:
                classification = _classify(filename, value)
                if focus == "release" or focus == classification:
                    for child_path, source in _leaves(value["_original"]):
                        found.append(
                            (
                                filename,
                                _pointer(parts + ("_original",) + child_path),
                                source,
                            )
                        )
            for key in sorted(value):
                if key != "_original":
                    visit(value[key], parts + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, parts + (index,))

    visit(document, ())
    return found


def _empty_original_owners(document: Any, filename: str, focus: str) -> set[str]:
    found: set[str] = set()

    def visit(value: Any, parts: tuple[object, ...]) -> None:
        if isinstance(value, dict):
            if "_original" in value:
                classification = _classify(filename, value)
                if focus == "release" or focus == classification:
                    if not list(_leaves(value["_original"])):
                        found.add(_pointer(parts + ("_original",)))
            for key in sorted(value):
                if key != "_original":
                    visit(value[key], parts + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, parts + (index,))

    visit(document, ())
    return found


def _decode_pointer(json_pointer: str) -> list[str]:
    return [
        item.replace("~1", "/").replace("~0", "~")
        for item in json_pointer.split("/")[1:]
    ]


def _mechanical(source: str, live: str) -> dict[str, Any]:
    source_tokens = _RUNTIME_TOKEN_RE.findall(source)
    live_tokens = _RUNTIME_TOKEN_RE.findall(live)
    source_numbers = _VISIBLE_NUMBER_RE.findall(_RUNTIME_TOKEN_RE.sub("", source))
    live_numbers = _VISIBLE_NUMBER_RE.findall(_RUNTIME_TOKEN_RE.sub("", live))
    flags = []
    if not live.strip():
        flags.append("empty-live")
    if source == live:
        flags.append("unchanged-source")
    if _JAPANESE_RE.search(live):
        flags.append("source-language-residue")
    if Counter(source_tokens) != Counter(live_tokens):
        flags.append("runtime-token-mismatch")
    if source_numbers != live_numbers and (source_numbers or live_numbers):
        flags.append("visible-number-mismatch")
    if len(source) >= 8 and len(live) >= 1:
        ratio = len(live) / len(source)
        if ratio < 0.35 or ratio > 3.0:
            flags.append("suspicious-length-ratio")
    return {
        "flags": flags,
        "source_runtime_tokens": source_tokens,
        "live_runtime_tokens": live_tokens,
        "source_visible_numbers": source_numbers,
        "live_visible_numbers": live_numbers,
    }


def _expected_live_pointers(document: Any, record: dict[str, Any]) -> list[str]:
    source_parts = _decode_pointer(record["source_pointer"])
    original_at = source_parts.index("_original")
    owner_parts = source_parts[:original_at]
    relative = source_parts[original_at + 1 :]
    owner = _resolve(document, _pointer(tuple(owner_parts)))
    original = owner.get("_original")
    code = owner.get("code") if isinstance(owner.get("code"), int) else None

    if isinstance(original, (dict, list)):
        if code == 102:
            live_parts = owner_parts + ["parameters", "0", relative[0]]
        elif code == 357 and (not relative or relative[0] != "parameters"):
            live_parts = owner_parts + ["parameters", "3"] + relative
        elif relative and relative[0] == "parameters":
            live_parts = owner_parts + relative
        else:
            live_parts = owner_parts + relative
        return [_pointer(tuple(live_parts))]
    if code == 101:
        params = owner.get("parameters") or []
        if len(params) > 4 and isinstance(params[4], str):
            index = 4
        elif 0 < len(params) < 4 and isinstance(params[0], str):
            index = 0
        else:
            raise ValueError("code 101 has no supported visible-name field")
        return [_pointer(tuple(owner_parts + ["parameters", str(index)]))]
    if code in (401, 405, 408):
        index = int(owner_parts[-1])
        command_list = _resolve(document, _pointer(tuple(owner_parts[:-1])))
        paths = [owner_parts + ["parameters", "0"]]
        cursor = index + 1
        while cursor < len(command_list):
            command = command_list[cursor]
            if not isinstance(command, dict) or command.get("code") != code:
                break
            if "_original" in command:
                break
            paths.append(owner_parts[:-1] + [str(cursor), "parameters", "0"])
            cursor += 1
        return [_pointer(tuple(item)) for item in paths]
    if code == 108:
        index = int(owner_parts[-1])
        command_list = _resolve(document, _pointer(tuple(owner_parts[:-1])))
        paths = [owner_parts + ["parameters", "0"]]
        cursor = index + 1
        while cursor < len(command_list):
            command = command_list[cursor]
            if not isinstance(command, dict) or command.get("code") != 408:
                break
            if "_original" in command:
                break
            paths.append(owner_parts[:-1] + [str(cursor), "parameters", "0"])
            cursor += 1
        return [_pointer(tuple(item)) for item in paths]
    if code == 355:
        index = int(owner_parts[-1])
        command_list = _resolve(document, _pointer(tuple(owner_parts[:-1])))
        paths = [owner_parts + ["parameters", "0"]]
        cursor = index + 1
        while cursor < len(command_list):
            command = command_list[cursor]
            if not isinstance(command, dict) or command.get("code") != 655:
                break
            if "_original" in command:
                break
            paths.append(owner_parts[:-1] + [str(cursor), "parameters", "0"])
            cursor += 1
        return [_pointer(tuple(item)) for item in paths]
    if code == 357:
        params = owner.get("parameters") or []
        header = params[0] if params and isinstance(params[0], str) else ""
        arguments = params[3] if len(params) > 3 and isinstance(params[3], dict) else {}
        candidates = sorted(
            {
                key
                for plugin, keys in CODE357_TEXT_ARGUMENTS.items()
                if plugin in header
                for key in keys
                if isinstance(arguments.get(key), str)
            }
        )
        if len(candidates) != 1:
            raise ValueError("code 357 scalar source has ambiguous live argument")
        return [_pointer(tuple(owner_parts + ["parameters", "3", candidates[0]]))]
    if code in SCALAR_PARAMETER:
        return [
            _pointer(tuple(owner_parts + ["parameters", str(SCALAR_PARAMETER[code])]))
        ]
    raise ValueError("unsupported live mapping")


def _speaker_from_document(document: Any, source_pointer: str, code: int) -> dict[str, str]:
    segments = source_pointer.split("/")[1:]
    decoded = [part.replace("~1", "/").replace("~0", "~") for part in segments]
    original_at = decoded.index("_original")
    command_path = decoded[:original_at]
    if not command_path or not command_path[-1].isdigit():
        return {"display_name": "", "face_name": "", "provenance": "none"}
    index = int(command_path[-1])
    command_list = _resolve(document, _pointer(tuple(command_path[:-1])))
    owner = index if code == 101 else -1
    if code in (401, 102):
        owner = index - 1
        while owner >= 0:
            prior = command_list[owner]
            if not isinstance(prior, dict) or prior.get("code") != 401:
                break
            owner -= 1
        if (
            owner < 0
            or not isinstance(command_list[owner], dict)
            or command_list[owner].get("code") != 101
        ):
            owner = -1
    if owner < 0:
        return {"display_name": "", "face_name": "", "provenance": "none"}
    params = command_list[owner].get("parameters") or []
    if len(params) > 4:
        face = params[0] if params and isinstance(params[0], str) else ""
        display = params[4] if isinstance(params[4], str) else ""
    elif 0 < len(params) < 4:
        face = ""
        display = params[0] if isinstance(params[0], str) else ""
    else:
        face = params[0] if params and isinstance(params[0], str) else ""
        display = ""
    display = re.sub(r"^(?:[\\]+[cC]\[\d+\]\s*)+", "", display.strip())
    bracketed = re.match(r"^【\s*([^】]+?)\s*】", display)
    display = (
        bracketed.group(1).strip()
        if bracketed
        else re.split(r"[\\]", display, maxsplit=1)[0].strip()
    )
    return {
        "display_name": display,
        "face_name": face,
        "provenance": "code-101" if owner == index else "adjacent-code-101",
    }


def verify_manifest(data_root: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if manifest.get("schema") != SCHEMA:
        errors.append(f"unsupported schema: {manifest.get('schema')!r}")
    expected_contract = {
        "extractor": "dazedtl-rpgmaker-qa-extractor-v1",
        "path_grammar": "rfc6901-json-pointer-v1",
        "ordering": "sha256-rpgmaker-qa-focus-v1",
        "normalization": "exact-utf8-no-normalization-v1",
        "length_thresholds": {"short_max": 20, "medium_max": 60},
    }
    for key, expected in expected_contract.items():
        if manifest.get(key) != expected:
            errors.append(f"manifest {key} contract mismatch")
    extractor_path = Path(__file__).with_name("rpgmaker_qa_manifest.py")
    if manifest.get("extractor_source_sha256") != _hash(extractor_path.read_bytes()):
        errors.append("extractor source SHA-256 mismatch")
    focus = manifest.get("focus")
    if focus not in {"database", "risky-codes", "dialogue", "release"}:
        errors.append(f"invalid focus: {focus!r}")

    claimed_hash = manifest.get("content_sha256")
    unhashed = dict(manifest)
    unhashed.pop("content_sha256", None)
    actual_hash = _hash(_canonical(unhashed))
    if claimed_hash != actual_hash:
        errors.append("manifest content_sha256 mismatch")

    root = Path(data_root).expanduser().resolve()
    documents: dict[str, Any] = {}
    actual_files = []
    expected_sources: list[tuple[str, str, str]] = []
    expected_empty_originals: set[tuple[str, str]] = set()
    parse_error_files: set[str] = set()
    json_paths = sorted(
        (item for item in root.rglob("*.json") if item.is_file()),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in json_paths:
        filename = path.relative_to(root).as_posix()
        raw = path.read_bytes()
        actual_files.append({"path": filename, "sha256": _hash(raw)})
        try:
            document = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            parse_error_files.add(filename)
            continue
        documents[filename] = document
        if focus in {"database", "risky-codes", "dialogue", "release"}:
            expected_sources.extend(
                (filename, pointer, source)
                for _old, pointer, source in _inventory(document, path.name, focus)
            )
            expected_empty_originals.update(
                (filename, pointer)
                for pointer in _empty_original_owners(document, path.name, focus)
            )
    if manifest.get("files") != actual_files:
        errors.append("file list or file SHA-256 values do not match the data folder")
    reported_parse_errors = {
        item.get("file")
        for item in manifest.get("unresolved", [])
        if str(item.get("reason", "")).startswith("parse-error:")
    }
    if reported_parse_errors != parse_error_files:
        errors.append("parse-error inventory mismatch")
    reported_empty_originals = {
        (item.get("file"), item.get("source_pointer"))
        for item in manifest.get("unresolved", [])
        if item.get("reason") == "empty-or-non-string-original"
    }
    if reported_empty_originals != expected_empty_originals:
        errors.append("empty/non-string original inventory mismatch")
    if manifest.get("unresolved"):
        errors.append("manifest contains unresolved source shapes")

    record_sources = [
        (item.get("file"), item.get("source_pointer"), item.get("source"))
        for item in manifest.get("records", [])
    ]
    unresolved_sources = []
    unresolved_lookup = {
        (item.get("file"), item.get("source_pointer"))
        for item in manifest.get("unresolved", [])
        if item.get("source_pointer")
    }
    for filename, pointer, source in expected_sources:
        if (filename, pointer) in unresolved_lookup:
            unresolved_sources.append((filename, pointer, source))
    accounted = record_sources + unresolved_sources
    if Counter(accounted) != Counter(expected_sources):
        missing = Counter(expected_sources) - Counter(accounted)
        extra = Counter(accounted) - Counter(expected_sources)
        errors.append(
            f"source coverage mismatch: {sum(missing.values())} missing, "
            f"{sum(extra.values())} extra"
        )

    for record in manifest.get("records", []):
        identity = record.get("identity", "<missing identity>")
        try:
            document = documents[record["file"]]
            source = _resolve(document, record["source_pointer"])
            if source != record.get("source"):
                raise ValueError("source bytes changed")
            source_hash = _hash(source)
            if source_hash != record.get("source_sha256"):
                raise ValueError("source SHA-256 mismatch")
            expected_identity = (
                f"{record['file']}#{record['source_pointer']}@{source_hash}"
            )
            if identity != expected_identity:
                raise ValueError("identity mismatch")
            source_parts = _decode_pointer(record["source_pointer"])
            owner_parts = source_parts[: source_parts.index("_original")]
            owner = _resolve(document, _pointer(tuple(owner_parts)))
            actual_code = owner.get("code") if isinstance(owner.get("code"), int) else None
            if record.get("event_code") != actual_code:
                raise ValueError("event code mismatch")
            if record.get("live_pointers") != _expected_live_pointers(document, record):
                raise ValueError("live pointer mapping mismatch")
            live_values = [_resolve(document, item) for item in record["live_pointers"]]
            if not all(isinstance(item, str) for item in live_values):
                raise ValueError("live counterpart is not a string")
            live = "\n".join(live_values)
            if record.get("live_transform") == "quoted-string":
                match = re.search(r"['\"`](.*)['\"`]", live)
                if not match:
                    raise ValueError("quoted live string is missing")
                live = match.group(1)
            elif record.get("live_transform") != "identity":
                raise ValueError("unknown live transform")
            if live != record.get("live"):
                raise ValueError("live text changed")
            code = actual_code
            classification = _classify(record["file"], {"code": code})
            if "/" in record["file"]:
                classification = _classify(
                    record["file"].rsplit("/", 1)[-1], {"code": code}
                )
            if classification != record.get("classification"):
                raise ValueError("classification mismatch")
            original = owner.get("_original")
            if isinstance(original, (dict, list)):
                expected_mapping = "direct"
            elif code in (401, 405, 408):
                expected_mapping = f"joined-contiguous-{code}"
            elif code == 108:
                expected_mapping = "joined-comment-108-408"
            elif code == 355:
                expected_mapping = "joined-script-355-655"
            elif code == 357:
                expected_mapping = "code-357-argument"
            else:
                expected_mapping = "direct"
            if record.get("mapping") != expected_mapping:
                raise ValueError("mapping strategy mismatch")
            expected_shape = {
                101: "name-box",
                102: "choice",
                401: "message",
                405: "scrolling-text",
            }.get(code, "event-command" if code is not None else classification)
            if record.get("display_shape") != expected_shape:
                raise ValueError("display shape mismatch")
            if record.get("source_char_length") != len(source):
                raise ValueError("source length mismatch")
            if record.get("live_char_length") != len(live):
                raise ValueError("live length mismatch")
            expected_band = "short" if len(live) <= 20 else "medium" if len(live) <= 60 else "long"
            if record.get("length_band") != expected_band:
                raise ValueError("length band mismatch")
            if record.get("mechanical") != _mechanical(source, live):
                raise ValueError("mechanical evidence mismatch")
            if classification == "database":
                relative = source_parts[source_parts.index("_original") + 1 :]
                expected_entity = {
                    "id": owner.get("id"),
                    "name": owner.get("name") if isinstance(owner.get("name"), str) else None,
                    "field": "/".join(relative),
                }
                if record.get("database_entity") != expected_entity:
                    raise ValueError("database entity facet mismatch")
            elif "database_entity" in record:
                raise ValueError("unexpected database entity facet")
            if classification == "risky-codes":
                params = owner.get("parameters") or []
                expected_risky = {
                    "plugin_header": params[0]
                    if code == 357 and params and isinstance(params[0], str)
                    else None,
                    "actor_id": params[0]
                    if code in {320, 324, 325} and params
                    else None,
                    "visibility": "requires-runtime-evidence",
                }
                if record.get("risky_context") != expected_risky:
                    raise ValueError("risky context facet mismatch")
            elif "risky_context" in record:
                raise ValueError("unexpected risky context facet")
            if code == 102:
                command_index = int(owner_parts[-1])
                command_list = _resolve(document, _pointer(tuple(owner_parts[:-1])))
                params = owner.get("parameters") or []
                indent = owner.get("indent")
                branches = []
                cursor = command_index + 1
                while cursor < len(command_list):
                    branch = command_list[cursor]
                    if not isinstance(branch, dict):
                        cursor += 1
                        continue
                    if branch.get("code") == 404 and branch.get("indent") == indent:
                        break
                    if branch.get("code") == 402 and branch.get("indent") == indent:
                        branch_params = branch.get("parameters") or []
                        branches.append(
                            {
                                "index": branch_params[0] if branch_params else None,
                                "label": branch_params[1] if len(branch_params) > 1 else None,
                            }
                        )
                    cursor += 1
                expected_choice = {
                    "cancel_type": params[1] if len(params) > 1 else None,
                    "default_type": params[2] if len(params) > 2 else None,
                    "position_type": params[3] if len(params) > 3 else None,
                    "background": params[4] if len(params) > 4 else None,
                    "branches": branches,
                }
                if record.get("choice_context") != expected_choice:
                    raise ValueError("choice context mismatch")
            elif "choice_context" in record:
                raise ValueError("unexpected choice context")
            if code in DIALOGUE:
                speaker = _speaker_from_document(document, record["source_pointer"], code)
                if speaker != record.get("speaker"):
                    raise ValueError("speaker facet mismatch")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            errors.append(f"{identity}: {exc}")

    grouped: dict[tuple[str, str], list[str]] = {}
    for record in manifest.get("records", []):
        grouped.setdefault((record.get("source"), record.get("live")), []).append(
            record.get("identity")
        )
    clusters = []
    for (source, live), identities in grouped.items():
        identities.sort()
        clusters.append(
            {
                "representative": identities[0],
                "identities": identities,
                "source": source,
                "live": live,
            }
        )
    clusters.sort(key=lambda item: item["representative"])
    if clusters != manifest.get("clusters"):
        errors.append("cluster table mismatch")
    sequence = sorted(
        [item["representative"] for item in clusters],
        key=lambda identity: _hash(
            "rpgmaker-qa-focus-v1\0" + str(focus) + "\0" + identity
        ),
    )
    if sequence != manifest.get("review_sequence"):
        errors.append("review sequence mismatch")
    expected_counts = {
        "files": len(actual_files),
        "records": len(manifest.get("records", [])),
        "clusters": len(clusters),
        "unresolved": len(manifest.get("unresolved", [])),
    }
    if expected_counts != manifest.get("counts"):
        errors.append("counts mismatch")
    return {
        "schema": "rpgmaker-qa-validation-v1",
        "verifier_source_sha256": _hash(Path(__file__).read_bytes()),
        "manifest_sha256": claimed_hash,
        "valid": not errors,
        "errors": errors,
        "counts": expected_counts,
    }
