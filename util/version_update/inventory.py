"""Read-only, path-safe inventories for game version updates."""

from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from pathlib import Path
from typing import Callable

from .models import FileKind, InventoryEntry


ProgressCallback = Callable[[int, int, str], None]

TEXT_SUFFIXES = frozenset(
    {
        ".bat",
        ".cfg",
        ".conf",
        ".css",
        ".csv",
        ".env",
        ".htm",
        ".html",
        ".ini",
        ".js",
        ".json5",
        ".md",
        ".ps1",
        ".py",
        ".rb",
        ".rpy",
        ".sh",
        ".toml",
        ".ts",
        ".tsx",
        ".txt",
        ".xml",
        ".yaml",
        ".yml",
    }
)

SKIP_PARTS = frozenset({".git", ".svn", ".hg", "__pycache__", "__MACOSX"})
SKIP_ROOT_DIRECTORIES = frozenset(
    {".dazedtl", ".agents", ".codex", "skills", "gameupdate"}
)
SKIP_FILE_NAMES = frozenset(
    {
        ".gitignore",
        ".gitattributes",
        ".gitmodules",
        ".gitkeep",
        ".hgignore",
        ".svnignore",
        ".editorconfig",
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        "GameUpdate.bat",
        "GameUpdate_linux.sh",
        "UberWolfCli.exe",
        "UberWolfCli.LICENSE.txt",
    }
)


class InventoryError(RuntimeError):
    """Raised when a folder cannot be safely inventoried."""


def classify_file(path: Path) -> FileKind:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return FileKind.JSON
    if suffix in TEXT_SUFFIXES or path.name in {"Game.ini", ".gitignore"}:
        return FileKind.TEXT
    return FileKind.BINARY


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_json_sha256(path: Path) -> str | None:
    """Hash JSON values independently of whitespace and object-key ordering."""
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        canonical = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return hashlib.sha256(canonical).hexdigest()


def _collision_key(relative_path: str) -> str:
    return unicodedata.normalize("NFC", relative_path).casefold()


def _all_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        safe_dirnames = []
        for name in sorted(dirnames):
            path = current_path / name
            if name in SKIP_PARTS or (
                current_path == root and name in SKIP_ROOT_DIRECTORIES
            ):
                continue
            if path.is_symlink():
                raise InventoryError(
                    f"Symbolic-link directories are not supported in Version Update: "
                    f"{path.relative_to(root).as_posix()}"
                )
            safe_dirnames.append(name)
        dirnames[:] = safe_dirnames
        for name in sorted(filenames):
            path = current_path / name
            if name in SKIP_FILE_NAMES or name.startswith("._"):
                continue
            if path.is_symlink():
                raise InventoryError(
                    f"Symbolic-link files are not supported in Version Update: "
                    f"{path.relative_to(root).as_posix()}"
                )
            if path.is_file():
                files.append(path)
    return files


def inventory_root(
    root: str | Path, *, progress: ProgressCallback | None = None
) -> dict[str, InventoryEntry]:
    resolved = Path(root).expanduser().resolve()
    if not resolved.is_dir():
        raise InventoryError(f"Game folder not found: {resolved}")
    if resolved.parent == resolved:
        raise InventoryError("A filesystem root cannot be used as a game folder")

    files = _all_files(resolved)
    entries: dict[str, InventoryEntry] = {}
    collision_paths: dict[str, str] = {}
    for index, path in enumerate(files, start=1):
        relative = path.relative_to(resolved).as_posix()
        collision_key = _collision_key(relative)
        existing = collision_paths.get(collision_key)
        if existing is not None and existing != relative:
            raise InventoryError(
                "Paths collide on a case-insensitive or Unicode-normalizing filesystem: "
                f"{existing!r} and {relative!r}"
            )
        collision_paths[collision_key] = relative
        if progress:
            progress(index, len(files), relative)
        stat = path.stat()
        entries[relative] = InventoryEntry(
            relative_path=relative,
            sha256=sha256_file(path),
            size=stat.st_size,
            kind=classify_file(path),
            semantic_sha256=(
                semantic_json_sha256(path) if path.suffix.lower() == ".json" else None
            ),
            source_path=path,
        )
    return entries


def inventory_fingerprint(entries: dict[str, InventoryEntry]) -> str:
    digest = hashlib.sha256()
    for relative, entry in sorted(entries.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def assert_inventory_unchanged(
    expected: dict[str, InventoryEntry], root: str | Path, *, label: str
) -> None:
    actual = inventory_root(root)
    expected_hashes = {path: entry.sha256 for path, entry in expected.items()}
    actual_hashes = {path: entry.sha256 for path, entry in actual.items()}
    if actual_hashes != expected_hashes:
        changed = sorted(set(expected_hashes) ^ set(actual_hashes))
        if not changed:
            changed = sorted(
                path
                for path in expected_hashes
                if expected_hashes[path] != actual_hashes.get(path)
            )
        preview = ", ".join(changed[:5]) or "one or more files"
        raise InventoryError(
            f"{label} changed after the scan ({preview}). Scan the update again."
        )
