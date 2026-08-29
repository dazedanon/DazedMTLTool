"""Local reference-translation registry and exact-match index.

Reference projects are advisory evidence for Setup and QA.  DazedTL never
writes to them: it reads either a translated data folder containing
``_original`` values or an explicit Japanese/English pair of normalized JSON
folders.  Absolute paths and generated indexes stay in the project's ignored
``.dazedtl`` state.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from util.paths import GAME_METADATA_RELATIVE, ensure_game_tool_gitignore
from util.project_scanner import (
    detect_wolf_layout,
    find_data_folder,
    wolf_has_maps,
    wolf_maps_dir,
    wolf_repair_nested_data_dir,
    wolf_unpack_out_dir,
)
from util.rpgmaker_qa_manifest import build_manifest


REGISTRY_SCHEMA = "dazedtl-reference-games-v1"
INDEX_SCHEMA = "dazedtl-reference-index-v1"
OVERLAP_SCHEMA = "dazedtl-reference-overlaps-v1"
REGISTRY_RELATIVE = GAME_METADATA_RELATIVE / "reference-games.json"
INDEX_RELATIVE = GAME_METADATA_RELATIVE / "reference-index.json"
OVERLAP_RELATIVE = GAME_METADATA_RELATIVE / "reference-overlaps.json"
REFERENCE_DATA_RELATIVE = GAME_METADATA_RELATIVE / "reference-data"

_JAPANESE_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]")
_MESSAGE_FOLLOWERS = {101: 401, 105: 405, 108: 408, 355: 655}
_WOLF_BINARY_SUFFIXES = frozenset({".dat", ".mps", ".project", ".txt", ".wolf"})


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_object(path: Path) -> dict[str, Any]:
    value = _read_json(path)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _data_dir(value: str | Path, label: str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise ValueError(f"{label} cannot be a symbolic link: {raw}")
    path = raw.resolve()
    if not path.is_dir():
        raise ValueError(f"{label} does not exist: {path}")
    files = list(_json_files(path))
    if not files:
        raise ValueError(f"{label} has no JSON files: {path}")
    return path


def _json_files(data_root: Path) -> Iterable[Path]:
    for path in sorted(data_root.glob("*.json"), key=lambda item: item.name.casefold()):
        if path.is_symlink():
            raise ValueError(f"Unsafe symbolic-link JSON file: {path}")
        if path.is_file():
            yield path


def _empty_registry() -> dict[str, Any]:
    return {"schema": REGISTRY_SCHEMA, "references": []}


def load_registry(game_root: str | Path) -> dict[str, Any]:
    root = Path(game_root).expanduser().resolve()
    path = root / REGISTRY_RELATIVE
    if not path.exists():
        return _empty_registry()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Unsafe reference registry path: {path}")
    value = _read_object(path)
    if value.get("schema") != REGISTRY_SCHEMA:
        raise ValueError(f"Unsupported reference registry schema in {path}")
    references = value.get("references")
    if not isinstance(references, list):
        raise ValueError(f"Invalid reference registry in {path}")
    normalized = []
    for entry in references:
        if not isinstance(entry, dict):
            raise ValueError(f"Invalid reference entry in {path}")
        mode = entry.get("mode")
        if mode not in {"embedded", "paired"}:
            raise ValueError(f"Invalid reference mode in {path}: {mode!r}")
        title = str(entry.get("title") or "").strip()
        source = str(entry.get("source_data") or "").strip()
        translated = str(entry.get("translated_data") or "").strip()
        identifier = str(entry.get("id") or "").strip()
        if not title or not translated or not identifier:
            raise ValueError(f"Incomplete reference entry in {path}")
        if mode == "paired" and not source:
            raise ValueError(f"Paired reference is missing source_data in {path}")
        normalized.append(
            {
                "id": identifier,
                "title": title,
                "mode": mode,
                "source_data": source,
                "translated_data": translated,
            }
        )
    return {"schema": REGISTRY_SCHEMA, "references": normalized}


def save_registry(game_root: str | Path, references: list[dict[str, Any]]) -> dict[str, Any]:
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Game folder does not exist: {root}")
    ensure_game_tool_gitignore(root)
    registry = {"schema": REGISTRY_SCHEMA, "references": references}
    _atomic_write_json(root / REGISTRY_RELATIVE, registry)
    return load_registry(root)


def add_embedded_reference(game_root: str | Path, title: str, translated_data: str | Path) -> dict[str, Any]:
    translated = _data_dir(translated_data, "Translated reference data folder")
    manifest = build_manifest(translated, "release")
    if not manifest.get("records"):
        raise ValueError("The selected folder has no supported DazedTL _original translations. Use a Japanese / English pair instead.")
    return _upsert_reference(
        game_root,
        title,
        mode="embedded",
        source_data="",
        translated_data=translated,
    )


def add_paired_reference(
    game_root: str | Path,
    title: str,
    source_data: str | Path,
    translated_data: str | Path,
) -> dict[str, Any]:
    source = _data_dir(source_data, "Japanese reference data folder")
    translated = _data_dir(translated_data, "English reference data folder")
    if source == translated:
        raise ValueError("Japanese and English reference folders must differ")
    return _upsert_reference(
        game_root,
        title,
        mode="paired",
        source_data=source,
        translated_data=translated,
    )


def _upsert_reference(
    game_root: str | Path,
    title: str,
    *,
    mode: str,
    source_data: str | Path,
    translated_data: str | Path,
) -> dict[str, Any]:
    clean_title = str(title).strip()
    if not clean_title:
        raise ValueError("Reference title cannot be empty")
    game = Path(game_root).expanduser().resolve()
    reference_paths = [Path(translated_data).expanduser().resolve()]
    if mode == "paired":
        reference_paths.append(Path(source_data).expanduser().resolve())
    cache_root = (game / REFERENCE_DATA_RELATIVE).resolve()
    if any((path == game or game in path.parents) and not (path == cache_root or cache_root in path.parents) for path in reference_paths):
        raise ValueError("A reference game must be outside the current game folder")
    source = str(source_data)
    translated = str(translated_data)
    identifier = _sha256(f"{mode}\0{source}\0{translated}")[:16]
    registry = load_registry(game)
    references = [entry for entry in registry["references"] if entry["id"] != identifier]
    references.append(
        {
            "id": identifier,
            "title": clean_title,
            "mode": mode,
            "source_data": source,
            "translated_data": translated,
        }
    )
    references.sort(key=lambda entry: (entry["title"].casefold(), entry["id"]))
    return save_registry(game, references)


def remove_reference(game_root: str | Path, identifier: str) -> dict[str, Any]:
    registry = load_registry(game_root)
    references = [entry for entry in registry["references"] if entry["id"] != identifier]
    if len(references) == len(registry["references"]):
        raise ValueError(f"Unknown reference id: {identifier}")
    return save_registry(game_root, references)


def _folder_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in _json_files(path):
        digest.update(file_path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(file_path.read_bytes()).digest())
    return digest.hexdigest()


def _paths_fingerprint(root: Path, paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(set(paths), key=lambda item: item.as_posix().casefold()):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            relative = path.name
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _has_json(path: Path) -> bool:
    return path.is_dir() and any(_json_files(path))


def inspect_reference_game(game_or_data: str | Path) -> dict[str, Any]:
    """Detect a supported game root or an already-normalized JSON folder."""
    raw = Path(game_or_data).expanduser()
    if raw.is_symlink():
        raise ValueError(f"Reference game cannot be a symbolic link: {raw}")
    root = raw.resolve()
    if not root.is_dir():
        raise ValueError(f"Reference game folder does not exist: {root}")
    if _has_json(root):
        return {
            "root": root,
            "engine": "NORMALIZED",
            "data": root,
            "fingerprint": _folder_fingerprint(root),
        }
    for name, engine in (("ace_json", "ACE"), ("JSON", "ACE"), ("wolf_json", "WOLF")):
        candidate = root / name
        if _has_json(candidate):
            return {
                "root": root,
                "engine": engine,
                "data": candidate,
                "fingerprint": _folder_fingerprint(candidate),
            }

    data, engine = find_data_folder(root)
    if engine == "MVMZ" and data is not None:
        return {
            "root": root,
            "engine": engine,
            "data": data.resolve(),
            "fingerprint": _folder_fingerprint(data.resolve()),
        }
    if engine == "ACE" and data is not None:
        files = [path for path in data.iterdir() if path.is_file() and path.suffix.casefold() in {".rvdata", ".rvdata2"}]
        return {
            "root": root,
            "engine": engine,
            "data": data.resolve(),
            "fingerprint": _paths_fingerprint(root, files),
        }
    archives = sorted(root.glob("Game.rgss*"))
    if archives:
        return {
            "root": root,
            "engine": "ACE",
            "data": None,
            "fingerprint": _paths_fingerprint(root, archives),
        }
    if engine == "WOLF":
        inputs = [path for path in root.rglob("*") if path.is_file() and path.suffix.casefold() in _WOLF_BINARY_SUFFIXES]
        return {
            "root": root,
            "engine": engine,
            "data": data.resolve() if data is not None else None,
            "fingerprint": _paths_fingerprint(root, inputs),
        }
    raise ValueError("Unsupported reference folder. Choose an RPG Maker MV/MZ, RPG Maker Ace, WOLF RPG game root, or a normalized JSON folder.")


def _copy_json(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    count = 0
    for path in _json_files(source):
        shutil.copy2(path, destination / path.name)
        count += 1
    if not count:
        raise ValueError(f"No normalized JSON files were produced from {source}")


def _run_checked(command: list[str], cwd: Path, label: str, log_fn: Callable[[str], None]) -> None:
    log_fn(f"{label}: preparing {cwd.name} …")
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"{label} could not start: {exc}") from exc
    if result.stdout.strip():
        for line in result.stdout.rstrip().splitlines():
            log_fn(f"  {line}")
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed with exit code {result.returncode}")


def _find_ace_binary_root(staging: Path) -> Path:
    candidates = [staging]
    candidates.extend(path.parent for path in staging.rglob("Data") if path.is_dir())
    for candidate in candidates:
        data = candidate / "Data"
        if data.is_dir() and any(path.suffix.casefold() in {".rvdata", ".rvdata2"} for path in data.iterdir() if path.is_file()):
            return candidate
    raise RuntimeError("Ace decryption did not produce a Data folder with rvdata files")


def _materialize_ace(info: dict[str, Any], destination: Path, log_fn: Callable[[str], None]) -> None:
    from util.ace.update_tools import (
        ace_tool_path,
        build_decrypter_command,
        ensure_ace_tools,
    )

    if not ensure_ace_tools(log_fn=log_fn):
        raise RuntimeError("The bundled RPG Maker Ace preparation tools are unavailable")
    with tempfile.TemporaryDirectory(prefix="dazedtl-reference-ace-") as temporary:
        staging = Path(temporary)
        source_data = info.get("data")
        if source_data is not None:
            shutil.copytree(Path(source_data), staging / "Data")
        else:
            archives = sorted(Path(info["root"]).glob("Game.rgss*"))
            if not archives:
                raise RuntimeError("Encrypted Ace reference has no Game.rgss archive")
            for archive in archives:
                shutil.copy2(archive, staging / archive.name)
            _run_checked(build_decrypter_command(staging), staging, "RPG Maker decrypter", log_fn)
        conversion_root = _find_ace_binary_root(staging)
        rv2json = ace_tool_path("RV2JSON.exe")
        _run_checked([str(rv2json), "-c"], conversion_root, "RV2JSON", log_fn)
        candidates = [conversion_root / "ace_json", conversion_root / "JSON"]
        candidates.extend(path for path in conversion_root.iterdir() if path.is_dir() and _has_json(path))
        produced = next((path for path in candidates if _has_json(path)), None)
        if produced is None:
            raise RuntimeError("RV2JSON completed but produced no JSON data folder")
        _copy_json(produced, destination)


def _wolf_extract_documents(data_dir: Path, destination: Path, log_fn: Callable[[str], None]) -> None:
    from util import wolfdawn

    layout = detect_wolf_layout(data_dir.parent if data_dir.name == "Data" else data_dir)
    basic = Path(layout.get("basic_data") or data_dir)
    maps = wolf_maps_dir(data_dir)
    destination.mkdir(parents=True, exist_ok=True)
    inputs: list[tuple[Path, str]] = []
    for source, output in (
        (basic / "CommonEvent.dat", "CommonEvent.dat.json"),
        (basic / "DataBase.project", "DataBase.project.json"),
        (basic / "CDataBase.project", "CDataBase.project.json"),
        (basic / "SysDatabase.project", "SysDatabase.project.json"),
        (basic / "Game.dat", "Game.dat.json"),
    ):
        if source.is_file():
            inputs.append((source, output))
    inputs.extend((path, f"{path.name}.json") for path in sorted(maps.glob("*.mps")))
    evtext = data_dir / "Evtext"
    if evtext.is_dir() and any(evtext.glob("*.txt")):
        inputs.append((evtext, "Evtext.json"))
    for source, output in inputs:
        log_fn(f"WolfDawn: extracting {source.name} …")
        result = wolfdawn.strings_extract(str(source), str(destination / output), log_fn=log_fn)
        if not result.ok:
            raise RuntimeError(f"WolfDawn could not extract {source}")
    names = destination / "names.json"
    result = wolfdawn.names_extract(str(data_dir), str(names), log_fn=log_fn)
    if not result.ok:
        raise RuntimeError("WolfDawn could not extract the reference name list")
    if not any(_json_files(destination)):
        raise RuntimeError("WolfDawn produced no normalized reference JSON")


def _materialize_wolf(info: dict[str, Any], destination: Path, log_fn: Callable[[str], None]) -> None:
    root = Path(info["root"])
    layout = detect_wolf_layout(root)
    data_dir = layout.get("data_dir")
    gaps = layout.get("unpack_gaps") or []
    if data_dir is not None and not gaps:
        _wolf_extract_documents(Path(data_dir), destination, log_fn)
        return

    from util import wolfdawn

    archives = layout.get("archives") or []
    if not archives:
        raise RuntimeError("WOLF reference has no usable Data folder or archives")
    with tempfile.TemporaryDirectory(prefix="dazedtl-reference-wolf-") as temporary:
        staging = Path(temporary)
        staged_archives = []
        for archive in archives:
            archive = Path(archive)
            relative = Path("Data") / archive.name if archive.parent.name == "Data" else Path(archive.name)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(archive, target)
            staged_archives.append(target)
        for archive in staged_archives:
            result = wolfdawn.unpack_all(
                [str(archive)],
                str(wolf_unpack_out_dir(staging, archive)),
                log_fn=log_fn,
                progress_total=1,
            )
            if not result.ok:
                raise RuntimeError(f"WolfDawn could not unpack {archive.name}")
        wolf_repair_nested_data_dir(staging)
        prepared = detect_wolf_layout(staging)
        data_dir = prepared.get("data_dir")
        if data_dir is None or not wolf_has_maps(data_dir) and not prepared.get("basic_data"):
            raise RuntimeError("WolfDawn unpacking produced no usable Data folder")
        _wolf_extract_documents(Path(data_dir), destination, log_fn)


def _materialize_reference_game(info: dict[str, Any], destination: Path, log_fn: Callable[[str], None]) -> None:
    engine = info["engine"]
    if engine in {"NORMALIZED", "MVMZ"} or info.get("data") is not None and _has_json(Path(info["data"])):
        _copy_json(Path(info["data"]), destination)
    elif engine == "ACE":
        _materialize_ace(info, destination, log_fn)
    elif engine == "WOLF":
        _materialize_wolf(info, destination, log_fn)
    else:
        raise ValueError(f"Unsupported reference engine: {engine}")


def add_game_pair_reference(
    game_root: str | Path,
    title: str,
    japanese_game: str | Path,
    english_game: str | Path,
    *,
    log_fn: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Detect, normalize, cache, and register a Japanese/English game pair."""
    current = Path(game_root).expanduser().resolve()
    japanese = inspect_reference_game(japanese_game)
    english = inspect_reference_game(english_game)
    if japanese["root"] == english["root"]:
        raise ValueError("Choose separate Japanese and English game folders")
    if japanese["engine"] != english["engine"] and "NORMALIZED" not in {
        japanese["engine"],
        english["engine"],
    }:
        raise ValueError(f"Reference engine mismatch: {japanese['engine']} and {english['engine']}")
    logger = log_fn or (lambda _message: None)
    cache_key = _sha256(
        "\0".join(
            (
                str(japanese["root"]),
                japanese["fingerprint"],
                str(english["root"]),
                english["fingerprint"],
            )
        )
    )[:20]
    cache_parent = current / REFERENCE_DATA_RELATIVE
    cache_parent.mkdir(parents=True, exist_ok=True)
    target = cache_parent / cache_key
    source_data = target / "source"
    translated_data = target / "translated"
    if target.is_symlink():
        raise ValueError(f"Unsafe reference cache path: {target}")
    if not (_has_json(source_data) and _has_json(translated_data)):
        staging = Path(tempfile.mkdtemp(prefix=f".{cache_key}.", dir=cache_parent))
        try:
            logger(f"Preparing Japanese {japanese['engine']} reference data …")
            _materialize_reference_game(japanese, staging / "source", logger)
            logger(f"Preparing English {english['engine']} reference data …")
            _materialize_reference_game(english, staging / "translated", logger)
            _atomic_write_json(
                staging / "manifest.json",
                {
                    "schema": "dazedtl-reference-pair-cache-v1",
                    "japanese_root": str(japanese["root"]),
                    "japanese_engine": japanese["engine"],
                    "japanese_fingerprint": japanese["fingerprint"],
                    "english_root": str(english["root"]),
                    "english_engine": english["engine"],
                    "english_fingerprint": english["fingerprint"],
                },
            )
            if target.exists():
                raise RuntimeError(f"Reference cache target appeared unexpectedly: {target}")
            staging.rename(target)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
    ensure_game_tool_gitignore(current)
    return add_paired_reference(current, title, source_data, translated_data)


def _entry_fingerprint(entry: dict[str, Any]) -> dict[str, Any]:
    translated = _data_dir(entry["translated_data"], "Translated reference data folder")
    result = {
        "id": entry["id"],
        "translated_data": str(translated),
        "translated_sha256": _folder_fingerprint(translated),
    }
    if entry["mode"] == "paired":
        source = _data_dir(entry["source_data"], "Japanese reference data folder")
        result.update({"source_data": str(source), "source_sha256": _folder_fingerprint(source)})
    return result


def _embedded_pairs(entry: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    data = _data_dir(entry["translated_data"], "Translated reference data folder")
    manifest = build_manifest(data, "release")
    for record in manifest.get("records") or []:
        source = str(record.get("source") or "")
        translation = str(record.get("live") or "")
        if source and translation and source != translation and _JAPANESE_RE.search(source):
            locator = f"{record.get('file', '')}#{record.get('source_pointer', '')}"
            yield source, translation, locator


def _is_command_list(value: list[Any]) -> bool:
    return bool(value) and all(isinstance(item, dict) and isinstance(item.get("code"), int) for item in value)


def _strings(value: Any, path: tuple[Any, ...] = ()) -> Iterable[tuple[str, str]]:
    """Yield stable logical paths for normalized RPG Maker JSON strings."""
    if isinstance(value, str):
        if value.strip():
            yield "/" + "/".join(str(part) for part in path), value
        return
    if isinstance(value, list):
        if _is_command_list(value):
            yield from _command_strings(value, path)
        else:
            for index, child in enumerate(value):
                yield from _strings(child, path + (index,))
        return
    if isinstance(value, dict):
        for key in sorted(value):
            if key == "_original":
                continue
            yield from _strings(value[key], path + (key,))


def _command_strings(commands: list[dict[str, Any]], path: tuple[Any, ...]) -> Iterable[tuple[str, str]]:
    ordinals: dict[int, int] = defaultdict(int)
    index = 0
    while index < len(commands):
        command = commands[index]
        code = int(command["code"])
        ordinal = ordinals[code]
        ordinals[code] += 1
        parameters = command.get("parameters")
        base = path + (f"command-{code}", ordinal)
        follower = _MESSAGE_FOLLOWERS.get(code)
        if follower is not None:
            lines = []
            cursor = index + 1
            while cursor < len(commands) and commands[cursor].get("code") == follower:
                child_parameters = commands[cursor].get("parameters")
                if isinstance(child_parameters, list) and child_parameters:
                    if isinstance(child_parameters[0], str):
                        lines.append(child_parameters[0])
                cursor += 1
            if lines:
                yield "/" + "/".join(str(part) for part in base + ("text",)), "\n".join(lines)
                index = cursor
                continue
        if code == 102 and isinstance(parameters, list) and parameters:
            choices = parameters[0]
            if isinstance(choices, list):
                for choice_index, choice in enumerate(choices):
                    if isinstance(choice, str) and choice.strip():
                        logical = base + ("choice", choice_index)
                        yield "/" + "/".join(str(part) for part in logical), choice
        if isinstance(parameters, (list, dict)):
            yield from _strings(parameters, base + ("parameters",))
        index += 1


def _paired_pairs(entry: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    source_root = _data_dir(entry["source_data"], "Japanese reference data folder")
    translated_root = _data_dir(entry["translated_data"], "English reference data folder")
    translated_files = {path.name: path for path in _json_files(translated_root)}
    for source_path in _json_files(source_root):
        translated_path = translated_files.get(source_path.name)
        if translated_path is None:
            continue
        source_entries = dict(_strings(_read_json(source_path)))
        translated_entries = dict(_strings(_read_json(translated_path)))
        for logical_path, source in source_entries.items():
            translation = translated_entries.get(logical_path)
            if translation and source != translation and _JAPANESE_RE.search(source):
                yield source, translation, f"{source_path.name}#{logical_path}"


def _reference_pairs(entry: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    if entry["mode"] == "embedded":
        yield from _embedded_pairs(entry)
    else:
        yield from _paired_pairs(entry)


def build_index(game_root: str | Path, *, force: bool = False) -> dict[str, Any]:
    root = Path(game_root).expanduser().resolve()
    registry = load_registry(root)
    registry_sha256 = _sha256(_canonical_bytes(registry))
    fingerprints = [_entry_fingerprint(entry) for entry in registry["references"]]
    index_path = root / INDEX_RELATIVE
    if not force and index_path.is_file() and not index_path.is_symlink():
        cached = _read_object(index_path)
        if (
            cached.get("schema") == INDEX_SCHEMA
            and cached.get("registry_sha256") == registry_sha256
            and cached.get("source_fingerprints") == fingerprints
        ):
            return cached

    aggregate: dict[str, dict[tuple[str, str], dict[str, Any]]] = defaultdict(dict)
    game_summaries = []
    for entry in registry["references"]:
        pair_count = 0
        for source, translation, locator in _reference_pairs(entry):
            key = (entry["id"], translation)
            row = aggregate[source].setdefault(
                key,
                {
                    "reference_id": entry["id"],
                    "title": entry["title"],
                    "translation": translation,
                    "occurrences": 0,
                    "examples": [],
                },
            )
            row["occurrences"] += 1
            if len(row["examples"]) < 3 and locator not in row["examples"]:
                row["examples"].append(locator)
            pair_count += 1
        game_summaries.append(
            {
                "id": entry["id"],
                "title": entry["title"],
                "mode": entry["mode"],
                "pair_count": pair_count,
            }
        )
    matches = {
        source: sorted(
            rows.values(),
            key=lambda row: (row["title"].casefold(), row["translation"]),
        )
        for source, rows in sorted(aggregate.items())
    }
    index = {
        "schema": INDEX_SCHEMA,
        "registry_sha256": registry_sha256,
        "source_fingerprints": fingerprints,
        "games": game_summaries,
        "source_count": len(matches),
        "matches": matches,
    }
    index["content_sha256"] = _sha256(_canonical_bytes(index))
    ensure_game_tool_gitignore(root)
    _atomic_write_json(index_path, index)
    return index


def sources_from_data(data_root: str | Path) -> set[str]:
    data = _data_dir(data_root, "Current game data folder")
    sources: set[str] = set()
    try:
        manifest = build_manifest(data, "release")
    except (KeyError, TypeError, ValueError):
        manifest = {"records": []}
    for record in manifest.get("records") or []:
        source = str(record.get("source") or "")
        if source and _JAPANESE_RE.search(source):
            sources.add(source)
    if sources:
        return sources
    for path in _json_files(data):
        document = _read_json(path)
        sources.update(value for _logical, value in _strings(document) if _JAPANESE_RE.search(value))
    return sources


def reference_context(
    game_root: str | Path,
    current_sources: Iterable[str],
    *,
    force: bool = False,
) -> dict[str, Any]:
    root = Path(game_root).expanduser().resolve()
    registry = load_registry(root)
    if not registry["references"]:
        pack = {
            "schema": OVERLAP_SCHEMA,
            "status": "not-configured",
            "games": [],
            "source_count": 0,
            "matches": {},
        }
        pack["content_sha256"] = _sha256(_canonical_bytes(pack))
        return pack
    index = build_index(root, force=force)
    wanted = set(str(source) for source in current_sources)
    matches = {source: rows for source, rows in index["matches"].items() if source in wanted}
    pack = {
        "schema": OVERLAP_SCHEMA,
        "status": "ready",
        "index_sha256": index["content_sha256"],
        "games": index["games"],
        "source_count": len(matches),
        "matches": matches,
    }
    pack["content_sha256"] = _sha256(_canonical_bytes(pack))
    return pack


def prepare_overlaps(game_root: str | Path, data_root: str | Path, *, force: bool = False) -> dict[str, Any]:
    root = Path(game_root).expanduser().resolve()
    pack = reference_context(root, sources_from_data(data_root), force=force)
    if load_registry(root)["references"]:
        ensure_game_tool_gitignore(root)
        _atomic_write_json(root / OVERLAP_RELATIVE, pack)
    return pack


def setup_reference_note(game_root: str | Path, data_root: str | Path) -> str:
    """Build the overlap artifact and return a compact prompt attachment."""
    root = Path(game_root).expanduser().resolve()
    pack = prepare_overlaps(root, data_root)
    if pack["status"] == "not-configured":
        return ""
    titles = ", ".join(game["title"] for game in pack["games"])
    overlap_path = root / OVERLAP_RELATIVE
    return (
        "<reference_translations>\n"
        f"Configured reference games: {titles}\n"
        f"Exact Japanese-source overlaps: {pack['source_count']}\n"
        f"Read the local evidence file: {overlap_path}\n"
        "Treat reference translations as advisory evidence. The current game's "
        "meaning and glossary remain authoritative; investigate conflicts instead "
        "of blindly copying old wording.\n"
        "</reference_translations>"
    )
