"""Build public game archives without translator and playtest artifacts."""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ProgressCallback = Callable[[int, int, str], None]


class ReleasePackageError(RuntimeError):
    """Raised when a safe public-release archive cannot be produced."""


@dataclass(frozen=True)
class ReleasePackageResult:
    output_path: Path
    files_added: int
    bytes_added: int
    excluded_entries: int


# These are never game payloads and should be ignored wherever they occur.
_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".dazedtl",
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)

# DazedTL creates these at the game root while translating or playtesting.
_EXCLUDED_ROOT_DIR_NAMES = frozenset(
    {
        ".agents",
        ".claude",
        ".codex",
        ".cursor",
        ".github",
        ".gitlab",
        ".idea",
        ".vscode",
        "ace_json",
        "docs",
        "documentation",
        "files",
        "log",
        "logs",
        "save",
        "saves",
        "scripts",
        "skills",
        "test",
        "tests",
        "translated",
        "wolf_json",
    }
)

_EXCLUDED_ROOT_FILE_NAMES = frozenset(
    {
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        ".pre-commit-config.yaml",
        "readme.md",
        "requirements.txt",
        "todo.md",
        "translation_quirks.txt",
        "glossary.txt",
        "vocab.txt",
    }
)

_EXCLUDED_FILE_NAMES = frozenset(
    {
        ".ds_store",
        ".editorconfig",
        ".gitattributes",
        ".gitignore",
        "desktop.ini",
        "patch2.ps1",
        "patch2.sh",
        "previous_patch_sha.txt",
        "thumbs.db",
    }
)

_UPDATER_ROOT_FILE_NAMES = frozenset(
    {
        "gameupdate.bat",
        "gameupdate_linux.sh",
        "uberwolfcli.exe",
        "uberwolfcli.license.txt",
    }
)

_ROOT_DOCUMENT_SUFFIXES = frozenset({".doc", ".docx", ".markdown", ".md", ".pdf", ".rst"})
_BACKUP_SUFFIXES = (".bak", ".backup", ".orig", ".tmp")


def default_release_zip_path(game_root: str | Path) -> Path:
    """Return a release path beside *game_root*, never inside it."""
    root = Path(game_root).expanduser().resolve()
    name = root.name or "game"
    return root.parent / f"{name}-public.zip"


def normalize_release_zip_path(output_path: str | Path) -> Path:
    output = Path(output_path).expanduser()
    if output.suffix.casefold() != ".zip":
        output = output.with_name(output.name + ".zip")
    return output.resolve()


def _is_updater_path(relative: Path) -> bool:
    parts = tuple(part.casefold() for part in relative.parts)
    if not parts:
        return False
    if parts[0] == "gameupdate":
        return True
    return len(parts) == 1 and parts[0] in _UPDATER_ROOT_FILE_NAMES


def exclusion_reason(relative: str | Path, *, is_dir: bool = False) -> str | None:
    """Return why a game-relative path is omitted, or ``None`` when it ships."""
    relative = Path(relative)
    parts = tuple(part.casefold() for part in relative.parts)
    if not parts:
        return None

    if any(part in _EXCLUDED_DIR_NAMES for part in parts):
        return "tool metadata or cache"

    name = parts[-1]
    if name.startswith(".env"):
        return "private environment configuration"
    if name in _EXCLUDED_FILE_NAMES:
        return "tool-generated or temporary file"

    # Player updater files are the explicit exception to translator-artifact
    # filtering. VCS/cache directories and updater runtime state were handled above.
    if _is_updater_path(relative):
        return None

    if len(parts) == 1:
        if is_dir and name in _EXCLUDED_ROOT_DIR_NAMES:
            return "translator workspace"
        if not is_dir:
            if name in _EXCLUDED_ROOT_FILE_NAMES:
                return "translator configuration or documentation"
            if relative.suffix.casefold() in _ROOT_DOCUMENT_SUFFIXES:
                return "root documentation file"
            if name.startswith("save") or relative.suffix.casefold() in {".rpgsave", ".sav"}:
                return "local save data"

    if not is_dir and name.endswith(_BACKUP_SUFFIXES):
        return "backup or temporary file"

    return None


def _iter_release_files(root: Path) -> tuple[list[tuple[Path, Path]], int]:
    files: list[tuple[Path, Path]] = []
    excluded = 0
    for current, dir_names, file_names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept_dirs: list[str] = []
        for name in sorted(dir_names, key=str.casefold):
            path = current_path / name
            relative = path.relative_to(root)
            if path.is_symlink() or exclusion_reason(relative, is_dir=True):
                excluded += 1
            else:
                kept_dirs.append(name)
        dir_names[:] = kept_dirs

        for name in sorted(file_names, key=str.casefold):
            path = current_path / name
            relative = path.relative_to(root)
            if path.is_symlink() or exclusion_reason(relative):
                excluded += 1
                continue
            files.append((path, relative))
    return files, excluded


def _archive_name(root: Path, relative: Path) -> str:
    return (Path(root.name or "game") / relative).as_posix()


def create_release_zip(
    game_root: str | Path,
    output_path: str | Path,
    *,
    progress: ProgressCallback | None = None,
) -> ReleasePackageResult:
    """Create an atomic public-release ZIP and leave the source game untouched."""
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise ReleasePackageError(f"Game folder not found: {root}")
    if root.parent == root:
        raise ReleasePackageError("A filesystem root cannot be packaged as a game folder")

    output = normalize_release_zip_path(output_path)
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise ReleasePackageError("Save the public ZIP outside the game folder")
    if output.exists() and output.is_dir():
        raise ReleasePackageError(f"Release path is a directory: {output}")

    output.parent.mkdir(parents=True, exist_ok=True)
    files, excluded = _iter_release_files(root)
    total = len(files)
    if not total:
        raise ReleasePackageError("No releasable game files were found")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    files_added = 0
    bytes_added = 0
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for index, (source, relative) in enumerate(files, start=1):
                if progress:
                    progress(index, total, relative.as_posix())
                arcname = _archive_name(root, relative)
                archive.write(source, arcname=arcname)
                bytes_added += source.stat().st_size
                files_added += 1
        os.replace(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return ReleasePackageResult(
        output_path=output,
        files_added=files_added,
        bytes_added=bytes_added,
        excluded_entries=excluded,
    )
