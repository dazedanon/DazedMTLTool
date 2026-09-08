"""Build the drop-in English patch, or a full loose copy, or a repacked asar.

Three delivery modes, in order of how much they touch:

``patch``  (default) writes ``resources/app/`` holding a ~90 KB loader shim plus
           ``override/`` with only the translated files. Electron prefers a loose
           ``resources/app`` over ``app.asar``, and the shim loads ``index.html``
           from inside the archive and intercepts ``file://`` for the overridden
           paths. Uninstall = delete ``resources/app``.
``full``   extracts the whole archive to ``resources/app/`` and copies the
           translated files over it. 745 MB, no engine trickery. Use this if the
           shim ever misbehaves.
``asar``   repacks a new ``app.asar`` for redistribution.
"""
from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

CHUNK = 8 * 1024 * 1024


def _read_header(archive: Path) -> tuple[dict, int]:
    with archive.open("rb") as fh:
        head = fh.read(8)
        header_size = struct.unpack_from("<I", head, 4)[0]
        pickle = fh.read(header_size)
    json_size = struct.unpack_from("<I", pickle, 4)[0]
    return json.loads(pickle[8:8 + json_size].rstrip(b"\0").decode("utf-8")), 8 + header_size


def _walk(node: dict, prefix: str = ""):
    for name, entry in node.get("files", {}).items():
        rel = f"{prefix}/{name}" if prefix else name
        if "files" in entry:
            yield from _walk(entry, rel)
        else:
            yield rel, entry


#: injected right before </body>, after every engine script in <head>, so it can
#: patch the prototypes before kag.init() clones them at DOM ready
SAVE_COMPAT = "save_compat.js"
SAVE_COMPAT_REL = "data/others/" + SAVE_COMPAT
SAVE_TEXT = "save_text.js"
SAVE_TEXT_REL = "data/others/" + SAVE_TEXT
SCRIPT_TAG = (
    f'<script type="text/javascript" src="./{SAVE_TEXT_REL}"></script>\n'
    f'<script type="text/javascript" src="./{SAVE_COMPAT_REL}"></script>'
)


def add_save_compat(app_root: Path, override: Path, patch_src: Path,
                    translated: Path | None = None) -> int:
    """Ship the loader fix that keeps player saves working across updates.

    A save stores an *index* into the parsed scenario, which every added or
    removed tag invalidates - so without this, each patch release would cost
    players their saves. See ``patch_src/save_compat.js`` for the mechanism.

    Delivered as two ordinary override files, so the shim's existing path
    interception does the work: the script itself, and an ``index.html`` that is
    the game's own with one line added.
    """
    source = patch_src / SAVE_COMPAT
    original = app_root / "index.html"
    if not source.exists() or not original.exists():
        return 0

    target = override / SAVE_COMPAT_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    # the build's own copy of the text a save keeps its own version of
    if translated is not None:
        from . import savetext
        (override / SAVE_TEXT_REL).write_text(
            savetext.build(translated / "data" / "scenario"), encoding="utf-8")

    html = original.read_text(encoding="utf-8")
    if SAVE_COMPAT not in html:
        if "</body>" not in html:
            raise SystemExit("index.html has no </body> - cannot install save_compat")
        html = html.replace("</body>", SCRIPT_TAG + "\n</body>", 1)
    (override / "index.html").write_text(html, encoding="utf-8")
    return 2


def patch(game_root: Path, translated: Path, patch_src: Path, app_root: Path,
          images: Path | None = None) -> dict:
    """Write ``resources/app`` = shim + override tree.

    Translated images go into the same override tree as the scripts: the loader
    shim swaps any path it finds there, so a redrawn PNG needs no extra wiring.
    """
    app_dir = game_root / "resources" / "app"
    override = app_dir / "override"
    if override.exists():
        shutil.rmtree(override)
    app_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(patch_src / "main.js", app_dir / "main.js")

    original = app_root / "package.json"
    if not original.exists():
        raise SystemExit(f"{original} missing - run `tl.py unpack` first")
    source_package = json.loads(original.read_text(encoding="utf-8"))
    # `name` must stay identical: Electron derives app.getPath('userData') from
    # it, and TyranoScript keys its save-tamper hash off the exe path + projectID.
    package = {
        "name": source_package["name"],
        "version": source_package.get("version", "1.0.0"),
        "description": "English translation patch",
        "main": "main.js",
        "window": source_package["window"],
    }
    (app_dir / "package.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=1), encoding="utf-8")

    count = images_count = 0
    for source, tally in ((translated, "scripts"), (images, "images")):
        if source is None or not source.exists():
            continue
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            target = override / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            if tally == "images":
                images_count += 1
            else:
                count += 1
    count += add_save_compat(app_root, override, patch_src, translated)

    return {"mode": "patch", "app_dir": str(app_dir),
            "script_files": count, "image_files": images_count}


def full(game_root: Path, translated: Path, images: Path | None = None) -> dict:
    archive = game_root / "resources" / "app.asar"
    app_dir = game_root / "resources" / "app"
    header, data_offset = _read_header(archive)
    entries = sorted(_walk(header), key=lambda t: int(t[1].get("offset", "0")))

    extracted = 0
    with archive.open("rb") as fh:
        for rel, entry in entries:
            out = app_dir / rel
            if out.exists():
                continue
            size = int(entry.get("size", 0))
            fh.seek(data_offset + int(entry.get("offset", "0")))
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("wb") as dst:
                left = size
                while left:
                    buf = fh.read(min(CHUNK, left))
                    dst.write(buf)
                    left -= len(buf)
            extracted += 1

    copied = 0
    for source in (translated, images):
        if source is None or not source.exists():
            continue
        for path in sorted(source.rglob("*")):
            if path.is_file():
                target = app_dir / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                copied += 1
    return {"mode": "full", "app_dir": str(app_dir), "extracted": extracted, "copied": copied}


def repack_asar(game_root: Path, translated: Path, out_path: Path,
                images: Path | None = None) -> dict:
    """Stream a new archive: original bytes for untouched files, new bytes for ours."""
    archive = game_root / "resources" / "app.asar"
    header, data_offset = _read_header(archive)

    replacements: dict[str, Path] = {}
    for source in (translated, images):
        if source is None or not source.exists():
            continue
        for path in sorted(source.rglob("*")):
            if path.is_file():
                replacements[path.relative_to(source).as_posix()] = path

    entries = list(_walk(header))
    # Capture the source offsets before rewriting them - the header is mutated
    # in place and the copy loop still has to read from the old positions.
    original = {rel: int(entry.get("offset", "0")) for rel, entry in entries}

    order: list[tuple[str, dict, Path | None]] = []
    offset = 0
    for rel, entry in entries:
        source = replacements.get(rel)
        size = source.stat().st_size if source else int(entry.get("size", 0))
        entry["size"] = size
        entry["offset"] = str(offset)
        entry.pop("integrity", None)
        order.append((rel, entry, source))
        offset += size

    blob = json.dumps(header, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    padded = blob + b"\0" * ((4 - len(blob) % 4) % 4)
    pickle = struct.pack("<I", len(padded) + 8) + struct.pack("<I", len(blob)) + padded
    head = struct.pack("<I", 4) + struct.pack("<I", len(pickle))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    written = swapped = 0
    with out_path.open("wb") as dst, archive.open("rb") as src:
        dst.write(head)
        dst.write(pickle)
        for rel, entry, source in order:
            if source is not None:
                dst.write(source.read_bytes())
                swapped += 1
            else:
                src.seek(data_offset + original[rel])
                left = int(entry["size"])
                while left:
                    buf = src.read(min(CHUNK, left))
                    if not buf:
                        raise SystemExit(f"unexpected EOF copying {rel}")
                    dst.write(buf)
                    left -= len(buf)
            written += 1
    return {"mode": "asar", "out": str(out_path), "files": written, "replaced": swapped}


def verify_asar(rebuilt: Path, original: Path, translated: Path,
                images: Path | None = None) -> list[str]:
    """Read the new archive back and compare every file against its true source.

    A repack that shifts one offset still produces an archive that opens fine and
    quietly serves the wrong bytes, so every entry is read out again and diffed.
    """
    problems: list[str] = []
    new_header, new_data = _read_header(rebuilt)
    old_header, old_data = _read_header(original)
    old_entries = dict(_walk(old_header))
    new_entries = dict(_walk(new_header))

    with rebuilt.open("rb") as new_fh, original.open("rb") as old_fh:
        for rel, entry in new_entries.items():
            size = int(entry.get("size", 0))
            new_fh.seek(new_data + int(entry.get("offset", "0")))
            got = new_fh.read(size)
            if len(got) != size:
                problems.append(f"{rel}: truncated ({len(got)} of {size})")
                continue

            replacement = translated / rel
            if not replacement.is_file() and images is not None:
                replacement = images / rel
            if replacement.is_file():
                want = replacement.read_bytes()
            else:
                old = old_entries.get(rel)
                if old is None:
                    problems.append(f"{rel}: not present in the original archive")
                    continue
                old_fh.seek(old_data + int(old.get("offset", "0")))
                want = old_fh.read(int(old.get("size", 0)))
            if got != want:
                problems.append(f"{rel}: {len(got)} bytes differ from source")

    problems.extend(f"{rel}: dropped from the archive"
                    for rel in sorted(set(old_entries) - set(new_entries)))
    return problems
