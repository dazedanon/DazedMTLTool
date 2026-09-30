"""Read-only game inspection and isolated, immutable prototype snapshots."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

from util.project_preparation import rpgmaker_layout
from util.rpgmaker_qa_manifest import pointer, resolve_pointer, _mechanical_evidence
from util.runtime_text import protect_script_codes, validate_control_codes

JAPANESE = re.compile(r"[ぁ-ゔァ-ヴ一-龠]")
DATABASES = {"Actors.json", "Items.json", "Weapons.json", "Armors.json", "Skills.json", "States.json", "Classes.json", "Enemies.json"}
FIELDS = {"name", "nickname", "description", "profile", "message1", "message2", "message3", "message4"}


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def extract_records(filename: str, document) -> list[dict]:
    """Bounded prototype scope: database fields and dialogue/choice commands.

    Deliberately excludes notes, scripts, plugin parameters and variable code.
    Full adapter parity remains a later migration milestone.
    """
    result = []

    def add(parts, text, category):
        if isinstance(text, str) and JAPANESE.search(text) and len(text) <= 512:
            location = pointer(parts)
            result.append({"id": digest(f"{filename}:{location}:{text}".encode())[:24],
                           "file": filename, "pointer": location, "source": text, "category": category})

    if filename in DATABASES and isinstance(document, list):
        for index, record in enumerate(document):
            if isinstance(record, dict):
                for field in sorted(FIELDS & record.keys()):
                    add((index, field), record[field], "database")

    def events(value, parts=()):
        if isinstance(value, dict):
            params = value.get("parameters")
            if isinstance(params, list):
                if value.get("code") in {401, 405} and params:
                    add(parts + ("parameters", 0), params[0], "dialogue")
                elif value.get("code") == 102 and params and isinstance(params[0], list):
                    for index, choice in enumerate(params[0]):
                        add(parts + ("parameters", 0, index), choice, "dialogue")
            for key, child in value.items():
                if key != "_original":
                    events(child, parts + (key,))
        elif isinstance(value, list):
            for index, child in enumerate(value):
                events(child, parts + (index,))

    if filename in {"CommonEvents.json", "Troops.json"} or re.fullmatch(r"Map\d+\.json", filename):
        events(document)
    return result


def inspect_snapshot(root: Path) -> dict:
    layout = rpgmaker_layout(root)
    if not layout or layout["engine"] != "MVMZ":
        raise ValueError("Snapshot review supports RPG Maker MV/MZ JSON projects. Open WOLF or Ace games in Guided workflow.")
    data = layout["data_path"]
    records, files = [], []
    for path in sorted(data.glob("*.json")):
        if path.is_symlink():
            raise ValueError("A source data file is a symbolic link.")
        raw = path.read_bytes()
        document = json.loads(raw.decode("utf-8-sig"))
        extracted = extract_records(path.name, document)
        files.append({"name": path.name, "sha256": digest(raw), "entries": len(extracted)})
        records.extend(extracted)
    return {"engine": "RPG Maker MV/MZ", "data_relative": data.relative_to(root).as_posix(),
            "files": files, "records": records}


def snapshot(source: Path, destination: Path, *, original: bool) -> dict:
    """Copy only data/config inputs; neither check out a branch nor execute game code."""
    source = source.expanduser().resolve(strict=True)
    if not source.is_dir():
        raise ValueError("Choose a game folder.")
    selected = {}
    revision = "working files"
    if original:
        def git(*args):
            return subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True, timeout=30).stdout
        revision = git("rev-parse", "--verify", "refs/heads/original^{commit}").decode().strip()
        for entry in git("ls-tree", "-rz", revision).split(b"\0"):
            if not entry:
                continue
            info, raw_name = entry.split(b"\t", 1)
            mode, kind, oid = info.decode().split()
            name = raw_name.decode("utf-8")
            path = Path(name)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("Unsafe path in Git source.")
            keep = (re.fullmatch(r"(?:www/)?(?:data|Data)/[^/]+\.json", name)
                    or name in {"js/plugins.js", "www/js/plugins.js", "package.json"})
            if keep:
                if mode not in {"100644", "100755"} or kind != "blob":
                    raise ValueError("Only regular source files can be snapshotted.")
                selected[name] = oid
        if not selected:
            raise ValueError("The original branch contains no supported RPG Maker JSON data.")
        # One cat-file process instead of one Git process per map.
        request = "".join(oid + "\n" for oid in selected.values()).encode()
        output = subprocess.run(["git", "-C", str(source), "cat-file", "--batch"], input=request,
                                capture_output=True, check=True, timeout=60).stdout
        offset = 0
        for name in selected:
            end = output.index(b"\n", offset)
            _oid, kind, size = output[offset:end].split()
            if kind != b"blob":
                raise ValueError("Invalid source blob.")
            size = int(size)
            raw = output[end + 1:end + 1 + size]
            if len(raw) != size:
                raise ValueError("Incomplete source snapshot.")
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            offset = end + 2 + size
    else:
        layout = rpgmaker_layout(source)
        if not layout or layout["engine"] != "MVMZ":
            raise ValueError("Choose an RPG Maker MV/MZ game folder.")
        paths = [*layout["data_path"].glob("*.json"), layout["plugins_js"]]
        for path in paths:
            if path.is_symlink() or not path.resolve().is_relative_to(source):
                raise ValueError("Source paths must stay inside the selected game.")
            target = destination / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
    inventory = inspect_snapshot(destination)
    inventory.update({"source": str(source), "revision": revision})
    return inventory


def apply_record(document, record, text):
    if resolve_pointer(document, record["pointer"]) != record["source"]:
        raise ValueError("Source text changed; rebuild this run's plan.")
    parent, _, encoded = record["pointer"].rpartition("/")
    owner = resolve_pointer(document, parent)
    key = encoded.replace("~1", "/").replace("~0", "~")
    owner[int(key) if isinstance(owner, list) else key] = text


def review_flags(source: str, text: str, code=None) -> list[str]:
    flags = [flag for flag in _mechanical_evidence(source, text, code)["flags"] if flag != "runtime-token-mismatch"]
    _protected, replacements = protect_script_codes(source)
    valid, _reasons = validate_control_codes(source, text, {0: replacements})
    if not valid:
        flags.append("runtime-token-mismatch")
    return flags
