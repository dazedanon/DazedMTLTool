"""Git-backed game version updates with exact file-tree preservation.

This module deliberately knows nothing about RPG Maker or any other engine.
Official game folders become Git trees, official releases become commits on the
``original`` branch, and those commits are cherry-picked into the repository's
configured translated branch.
No game file is parsed or reconstructed.
"""

from __future__ import annotations

import os
import hashlib
import json
import re
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

import jsbeautifier


ORIGINAL_BRANCH = "original"
TRANSLATION_BRANCH = "main"
_LEGACY_TRANSLATION_BRANCH = "translation"
_TRANSLATION_BRANCH_CONFIG = "dazedtl.translationBranch"
VERSION_TRAILER = "DazedTL-Version"
_TOOL_NAME = "DazedMTLTool"
_TOOL_EMAIL = "local@dazedmtl.invalid"
_GAMEUPDATE_GITIGNORE = Path(__file__).resolve().parents[2] / "gameupdate" / ".gitignore"
_ZERO_OID = "0" * 40
_VERSION_LINE = re.compile(r"^DazedTL-Version:\s*(.+?)\s*$", re.MULTILINE)
_VERSION_HINT = re.compile(
    r"(?i)(?:\bversion\b|\bver\.?|\bv|update(?:d)?(?:\s+original)?\s+game\s+files\s+to)"
    r"[\s:._-]*(\d+(?:\.\d+)+)"
)
_IMAGE_EXTENSIONS = frozenset(
    {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".png_", ".rpgmvp", ".webp"}
)
_AUDIO_EXTENSIONS = frozenset(
    {
        ".aac",
        ".flac",
        ".m4a",
        ".m4a_",
        ".mid",
        ".midi",
        ".mp3",
        ".ogg",
        ".ogg_",
        ".opus",
        ".rpgmvm",
        ".rpgmvo",
        ".wav",
        ".wma",
    }
)
_VIDEO_EXTENSIONS = frozenset(
    {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".ogv", ".webm", ".webm_", ".wmv"}
)
_FONT_EXTENSIONS = frozenset({".eot", ".otf", ".ttf", ".woff", ".woff2"})
_ASSET_MANIFEST_FORMAT = 1
_TOOL_RESOURCE_DIRECTORIES = frozenset(
    {
        ".agents",
        ".codex",
        ".dazedtl",
        "dazedtl_images",
        "dictionaries",
        "docs",
        "documentation",
        "gameupdate",
        "prompts",
        "skills",
    }
)
_LOCAL_ONLY_DIRECTORIES = frozenset(
    {
        ".dazedtl",
        "cache",
        "caches",
        "crash",
        "crashes",
        "log",
        "logs",
        "save",
        "saves",
        "screenshots",
        "temp",
        "tmp",
    }
)
_NON_GAME_RESOURCE_EXTENSIONS = frozenset(
    {".adoc", ".bdic", ".markdown", ".md", ".rst"}
)
_LOCAL_ONLY_FILENAMES = frozenset(
    {
        "cg.dat",
        "kabe3_save.dat",
        "kabe3_system.dat",
        "previous_patch_sha.txt",
        "psbpack.dat",
        "scene.dat",
    }
)
_TOOL_OWNED_ROOT_FILES = frozenset(
    {
        ".gitattributes",
        ".gitignore",
        "gameupdate.bat",
        "gameupdate_linux.sh",
        "patch-config.example.txt",
        "patch-config.txt",
        "readme.md",
        "uberwolfcli.exe",
        "uberwolfcli.license.txt",
    }
)


class GitWorkflowError(RuntimeError):
    """Raised when an exact Git workflow operation cannot complete safely."""


@dataclass(frozen=True)
class RepositoryStatus:
    selected_root: Path
    repo_root: Path | None
    game_prefix: str
    current_branch: str | None
    original_exists: bool
    original_commit: str | None
    original_version: str | None
    translation_exists: bool
    translation_commit: str | None
    translation_version: str | None
    worktree_clean: bool
    pending_cherry_pick: bool
    git_available: bool = True
    asset_sync_pending: bool = False
    asset_manifest_available: bool = False
    translation_branch: str | None = None

    @property
    def ready(self) -> bool:
        return bool(
            self.repo_root
            and self.original_exists
            and self.translation_exists
            and self.current_branch == self.translation_branch
            and self.worktree_clean
            and not self.pending_cherry_pick
            and not self.asset_sync_pending
        )


@dataclass(frozen=True)
class BootstrapResult:
    repo_root: Path
    original_commit: str
    translation_commit: str
    version: str
    formatted_json_paths: tuple[str, ...] = ()
    json_warnings: tuple[str, ...] = ()
    ignored_paths: tuple[str, ...] = ()
    gitignore_installed: bool = False


@dataclass(frozen=True)
class UpdateResult:
    repo_root: Path
    original_commit: str
    translation_commit: str | None
    version: str
    official_won_paths: tuple[str, ...] = ()
    pending_conflicts: tuple[str, ...] = ()
    content_changed: bool = True
    already_present_paths: tuple[str, ...] = ()
    external_changes: tuple[UpdateExternalChange, ...] = ()

    @property
    def complete(self) -> bool:
        return self.translation_commit is not None and not self.pending_conflicts


@dataclass(frozen=True)
class UpdateFileChange:
    path: str
    change: str
    added_lines: int | None
    deleted_lines: int | None
    is_image: bool = False
    translation_changed: bool = False
    already_present: bool = False
    whole_file_replaced: bool = False
    result: str = ""


@dataclass(frozen=True)
class UpdateImageChange:
    path: str
    change: str
    tracked: bool
    warning: bool
    result: str


@dataclass(frozen=True)
class UpdateExternalChange:
    path: str
    change: str
    category: str
    already_present: bool
    size_bytes: int
    result: str


@dataclass(frozen=True)
class UpdatePreview:
    repo_root: Path
    source_root: Path
    version: str
    original_commit: str
    translation_commit: str
    proposed_tree: str
    added_paths: tuple[str, ...]
    modified_paths: tuple[str, ...]
    deleted_paths: tuple[str, ...]
    overlapping_paths: tuple[str, ...]
    already_present_paths: tuple[str, ...]
    formatted_json_paths: tuple[str, ...]
    json_warnings: tuple[str, ...]
    ignored_paths: tuple[str, ...]
    file_changes: tuple[UpdateFileChange, ...] = ()
    image_changes: tuple[UpdateImageChange, ...] = ()
    external_changes: tuple[UpdateExternalChange, ...] = ()
    proposed_asset_manifest: str = ""
    baseline_asset_manifest: str = ""
    asset_manifest_available: bool = True
    baseline_source_root: Path | None = None
    preserved_translation_asset_paths: tuple[str, ...] = ()

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return self.added_paths + self.modified_paths + self.deleted_paths

    @property
    def translation_change_paths(self) -> tuple[str, ...]:
        already_present = set(self.already_present_paths)
        return tuple(path for path in self.changed_paths if path not in already_present)

    @property
    def content_change_expected(self) -> bool:
        return bool(
            self.translation_change_paths
            or any(not change.already_present for change in self.external_changes)
        )


@dataclass(frozen=True)
class _SourceFile:
    path: Path
    relative: str
    mode: str
    normalized_text: str | None = None
    json_warning: str | None = None


@dataclass(frozen=True)
class _TreeBuild:
    tree: str
    formatted_json_paths: tuple[str, ...]
    json_warnings: tuple[str, ...]
    ignored_paths: tuple[str, ...]


@dataclass(frozen=True)
class _AssetManifestEntry:
    sha256: str
    size: int
    mode: str


def _run_git(
    cwd: Path,
    *args: str,
    check: bool = True,
    input_text: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(cwd), *args]
    process_env = os.environ.copy()
    if env:
        process_env.update(env)
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            input=input_text,
            env=process_env,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise GitWorkflowError("Git is not installed or is not available on PATH") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitWorkflowError(f"Git operation failed: {exc}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise GitWorkflowError(detail)
    return result


def _ref_commit(repo: Path, ref: str) -> str | None:
    result = _run_git(
        repo,
        "rev-parse",
        "--verify",
        "--quiet",
        f"refs/heads/{ref}^{{commit}}",
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _validate_branch_name(repo: Path, branch: str) -> str:
    value = branch.strip()
    valid = _run_git(repo, "check-ref-format", "--branch", value, check=False)
    if not value or valid.returncode != 0:
        raise GitWorkflowError(f"The configured translated branch is invalid: {branch!r}")
    if value == ORIGINAL_BRANCH:
        raise GitWorkflowError("The original branch cannot also be the translated branch")
    return value


def _configured_translation_branch(repo: Path) -> str | None:
    configured = _run_git(
        repo, "config", "--local", "--get", _TRANSLATION_BRANCH_CONFIG, check=False
    )
    if configured.returncode == 0 and configured.stdout.strip():
        return _validate_branch_name(repo, configured.stdout.strip())
    if _ref_commit(repo, _LEGACY_TRANSLATION_BRANCH):
        return _LEGACY_TRANSLATION_BRANCH
    return None


def _set_translation_branch(repo: Path, branch: str) -> str:
    value = _validate_branch_name(repo, branch)
    _run_git(repo, "config", "--local", _TRANSLATION_BRANCH_CONFIG, value)
    return value


def _version_from_history(repo: Path, ref: str, commit: str | None) -> str | None:
    if not commit:
        return None
    messages = _run_git(repo, "log", "-n", "100", "--format=%B%x00", ref).stdout
    for message in messages.split("\x00"):
        match = _VERSION_LINE.search(message)
        if match:
            return match.group(1).strip()

    tags = _run_git(repo, "tag", "--points-at", commit, check=False).stdout.splitlines()
    tagged = [tag.strip() for tag in tags if _VERSION_HINT.search(tag.strip())]
    if tagged:
        match = _VERSION_HINT.search(sorted(tagged)[-1])
        if match:
            return match.group(1)

    subject = _run_git(repo, "log", "-1", "--format=%s", ref).stdout.strip()
    match = _VERSION_HINT.search(subject)
    return match.group(1) if match else None


def _repository_for(selected: Path) -> tuple[Path, str] | None:
    result = _run_git(selected, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        return None
    repo = Path(result.stdout.strip()).resolve()
    try:
        relative = selected.resolve().relative_to(repo)
    except ValueError as exc:
        raise GitWorkflowError("Selected game folder is outside its Git repository") from exc
    prefix = "" if relative == Path(".") else relative.as_posix()
    return repo, prefix


def _cherry_pick_path(repo: Path) -> Path:
    result = _run_git(repo, "rev-parse", "--git-path", "CHERRY_PICK_HEAD")
    path = Path(result.stdout.strip())
    return path if path.is_absolute() else repo / path


def inspect_repository(game_root: str | Path) -> RepositoryStatus:
    selected = Path(game_root).expanduser().resolve()
    if not selected.is_dir():
        return RepositoryStatus(
            selected, None, "", None, False, None, None, False, None, None, False, False
        )
    found = _repository_for(selected)
    if found is None:
        return RepositoryStatus(
            selected, None, "", None, False, None, None, False, None, None, True, False
        )
    repo, prefix = found
    branch_result = _run_git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    current_branch = branch_result.stdout.strip() or None
    original_commit = _ref_commit(repo, ORIGINAL_BRANCH)
    translation_branch = _configured_translation_branch(repo)
    translation_commit = (
        _ref_commit(repo, translation_branch) if translation_branch else None
    )
    status = _run_git(repo, "status", "--porcelain=v1", "-z").stdout
    return RepositoryStatus(
        selected_root=selected,
        repo_root=repo,
        game_prefix=prefix,
        current_branch=current_branch,
        original_exists=original_commit is not None,
        original_commit=original_commit,
        original_version=_version_from_history(repo, ORIGINAL_BRANCH, original_commit),
        translation_exists=translation_commit is not None,
        translation_commit=translation_commit,
        translation_version=_version_from_history(
            repo, translation_branch or TRANSLATION_BRANCH, translation_commit
        ),
        worktree_clean=not bool(status),
        pending_cherry_pick=_cherry_pick_path(repo).exists(),
        asset_sync_pending=_asset_state_path(
            repo, prefix, "pending-assets"
        ).exists(),
        asset_manifest_available=_asset_state_path(
            repo, prefix, "official-assets"
        ).exists(),
        translation_branch=translation_branch,
    )


def _validate_version(version: str) -> str:
    value = version.strip()
    if not value:
        raise GitWorkflowError("A version label is required")
    if "\n" in value or "\r" in value:
        raise GitWorkflowError("Version labels must fit on one line")
    return value


def _validate_source(source: str | Path, destination: Path) -> Path:
    root = Path(source).expanduser().resolve()
    if not root.is_dir():
        raise GitWorkflowError(f"Official game folder not found: {root}")
    if root == destination or destination in root.parents or root in destination.parents:
        raise GitWorkflowError(
            "Official and translated game folders must be separate and cannot be nested"
        )
    return root


def _canonical_json(source_text: str) -> str:
    duplicate_keys: set[str] = set()

    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                duplicate_keys.add(key)
            result[key] = value
        return result

    def reject_constant(value: str):
        raise ValueError(f"non-standard numeric constant {value}")

    document = json.loads(
        source_text,
        object_pairs_hook=object_pairs,
        parse_constant=reject_constant,
    )
    if duplicate_keys:
        names = ", ".join(sorted(duplicate_keys)[:5])
        raise ValueError(f"duplicate object key(s): {names}")
    canonical = json.dumps(document, indent=4, ensure_ascii=False, allow_nan=False)
    canonical.encode("utf-8")
    return canonical


def _canonical_plugins_js(source_text: str) -> str | None:
    """Use the same RPG Maker plugins.js formatting as the Prepare workflow."""
    if not re.search(r"\bvar\s+\$plugins\s*=", source_text):
        return None
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.indent_char = " "
    options.max_preserve_newlines = 2
    options.preserve_newlines = True
    options.end_with_newline = True
    return jsbeautifier.beautify(source_text, options)


def _source_files(source: Path, *, format_json: bool) -> list[_SourceFile]:
    files: list[_SourceFile] = []
    for candidate in sorted(source.rglob("*"), key=lambda path: path.as_posix()):
        relative = candidate.relative_to(source)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if candidate.is_symlink():
            raise GitWorkflowError(
                f"Symbolic links are not supported in game trees: {relative.as_posix()}"
            )
        if candidate.is_dir():
            continue
        if not candidate.is_file():
            raise GitWorkflowError(
                f"Unsupported filesystem entry in game tree: {relative.as_posix()}"
            )
        rel_text = relative.as_posix()
        if any(character in rel_text for character in ("\n", "\r", "\t")):
            raise GitWorkflowError(f"Unsupported control character in path: {rel_text!r}")
        executable_bits = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        mode = "100755" if candidate.stat().st_mode & executable_bits else "100644"
        normalized_text = None
        warning = None
        if format_json and candidate.suffix.casefold() == ".json":
            try:
                source_text = candidate.read_text(encoding="utf-8")
                canonical = _canonical_json(source_text)
                if canonical != source_text:
                    normalized_text = canonical
            except Exception as exc:  # formatting is optional; preserve source bytes
                warning = f"{rel_text}: JSON formatting skipped ({exc})"
        elif format_json and candidate.name.casefold() == "plugins.js":
            try:
                source_text = candidate.read_text(encoding="utf-8")
                canonical = _canonical_plugins_js(source_text)
                if canonical is not None and canonical != source_text:
                    normalized_text = canonical
            except Exception as exc:  # preserve source bytes and warn visibly
                warning = f"{rel_text}: plugins.js formatting skipped ({exc})"
        files.append(_SourceFile(candidate, rel_text, mode, normalized_text, warning))
    return files


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git_common_dir(repo: Path) -> Path:
    common_text = _run_git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    common = Path(common_text)
    if not common.is_absolute():
        common = repo / common
    return common.resolve()


def _asset_state_path(repo: Path, game_prefix: str, name: str) -> Path:
    key = hashlib.sha256(game_prefix.encode("utf-8")).hexdigest()[:16]
    return _git_common_dir(repo) / "dazedtl" / "version-update" / f"{key}-{name}.json"


def _manifest_payload(
    manifest: Mapping[str, _AssetManifestEntry],
) -> dict[str, dict[str, str | int]]:
    return {
        path: {"sha256": entry.sha256, "size": entry.size, "mode": entry.mode}
        for path, entry in sorted(manifest.items())
    }


def _manifest_digest(manifest: Mapping[str, _AssetManifestEntry]) -> str:
    encoded = json.dumps(
        _manifest_payload(manifest),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass
        raise


def _validate_manifest_path(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise GitWorkflowError(f"Asset manifest contains an unsafe path: {path!r}")
    if any(character in path for character in ("\n", "\r", "\t")):
        raise GitWorkflowError(f"Asset manifest contains an unsafe path: {path!r}")


def _load_asset_manifest(
    repo: Path, game_prefix: str
) -> dict[str, _AssetManifestEntry] | None:
    path = _asset_state_path(repo, game_prefix, "official-assets")
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        if document.get("format") != _ASSET_MANIFEST_FORMAT:
            raise ValueError("unsupported format")
        raw_files = document["files"]
        if not isinstance(raw_files, dict):
            raise ValueError("files must be an object")
        manifest = {}
        for relative, raw in raw_files.items():
            if not isinstance(relative, str) or not isinstance(raw, dict):
                raise ValueError("invalid file entry")
            _validate_manifest_path(relative)
            sha256 = raw.get("sha256")
            size = raw.get("size")
            mode = raw.get("mode")
            if (
                not isinstance(sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", sha256)
                or not isinstance(size, int)
                or size < 0
                or mode not in {"100644", "100755"}
            ):
                raise ValueError(f"invalid metadata for {relative}")
            manifest[relative] = _AssetManifestEntry(sha256, size, mode)
        return manifest
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise GitWorkflowError(f"Official asset manifest is invalid: {path}") from exc


def _save_asset_manifest(
    repo: Path,
    game_prefix: str,
    version: str,
    original_commit: str,
    manifest: Mapping[str, _AssetManifestEntry],
) -> None:
    _write_json_atomic(
        _asset_state_path(repo, game_prefix, "official-assets"),
        {
            "format": _ASSET_MANIFEST_FORMAT,
            "version": version,
            "original_commit": original_commit,
            "files": _manifest_payload(manifest),
        },
    )


def _save_pending_asset_plan(
    repo: Path,
    game_prefix: str,
    source: Path,
    version: str,
    original_commit: str,
    manifest_digest: str,
) -> None:
    _write_json_atomic(
        _asset_state_path(repo, game_prefix, "pending-assets"),
        {
            "format": _ASSET_MANIFEST_FORMAT,
            "source": str(source),
            "version": version,
            "original_commit": original_commit,
            "manifest_digest": manifest_digest,
        },
    )


def _load_pending_asset_plan(
    repo: Path, game_prefix: str
) -> dict[str, str] | None:
    path = _asset_state_path(repo, game_prefix, "pending-assets")
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        required = ("source", "version", "original_commit", "manifest_digest")
        if document.get("format") != _ASSET_MANIFEST_FORMAT or any(
            not isinstance(document.get(key), str) or not document[key]
            for key in required
        ):
            raise ValueError("invalid pending asset plan")
        if not re.fullmatch(r"[0-9a-f]{64}", document["manifest_digest"]):
            raise ValueError("invalid manifest digest")
        return {key: document[key] for key in required}
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise GitWorkflowError(f"Pending asset update is invalid: {path}") from exc


def _clear_pending_asset_plan(repo: Path, game_prefix: str) -> None:
    try:
        _asset_state_path(repo, game_prefix, "pending-assets").unlink()
    except FileNotFoundError:
        pass


def _ensure_local_excludes(repo: Path) -> None:
    """Keep removed legacy updater metadata out of the exact game branches."""
    exclude = _git_common_dir(repo) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text("utf-8", errors="replace") if exclude.exists() else ""
    rule = ".dazedtl/version_update/"
    if rule not in {line.strip() for line in existing.splitlines()}:
        with exclude.open("a", encoding="utf-8") as handle:
            if existing and not existing.endswith("\n"):
                handle.write("\n")
            handle.write(f"{rule}\n")


def _install_gameupdate_gitignore(game_root: Path) -> bool:
    """Install the bundled ignore policy without discarding project rules."""
    try:
        template = _GAMEUPDATE_GITIGNORE.read_bytes()
    except OSError as exc:
        raise GitWorkflowError(
            f"Bundled GameUpdate .gitignore is unavailable: {_GAMEUPDATE_GITIGNORE}"
        ) from exc
    if not template.strip():
        raise GitWorkflowError("Bundled GameUpdate .gitignore is empty")

    destination = game_root / ".gitignore"
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise GitWorkflowError("The game .gitignore must be a regular file")
    existing = destination.read_bytes() if destination.exists() else b""

    def normalized(value: bytes) -> bytes:
        return value.replace(b"\r\n", b"\n").strip()

    if normalized(template) in normalized(existing):
        return False
    combined = template.rstrip(b"\r\n") + b"\n"
    if existing:
        combined += b"\n# Existing project rules\n" + existing

    original_mode = destination.stat().st_mode if destination.exists() else 0o100644
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".gitignore.dazedtl-", dir=game_root
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(combined)
        os.chmod(temporary_name, stat.S_IMODE(original_mode))
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass
        raise
    return True


def _reject_original_checked_out_elsewhere(repo: Path) -> None:
    listing = _run_git(repo, "worktree", "list", "--porcelain").stdout
    for block in listing.strip().split("\n\n"):
        fields = dict(
            line.split(" ", 1)
            for line in block.splitlines()
            if " " in line
        )
        if fields.get("branch") == f"refs/heads/{ORIGINAL_BRANCH}":
            raise GitWorkflowError(
                "The original branch is checked out in another Git worktree. "
                "Close or switch that worktree before updating it."
            )


def _temporary_index() -> tuple[str, dict[str, str]]:
    descriptor, name = tempfile.mkstemp(prefix="dazedtl-git-index-")
    os.close(descriptor)
    os.unlink(name)
    return name, {"GIT_INDEX_FILE": name}


def _prefixed(prefix: str, relative: str) -> str:
    return f"{prefix}/{relative}" if prefix else relative


def _ignored_paths(
    repo: Path, files: list[_SourceFile], game_prefix: str
) -> set[str]:
    if not files:
        return set()
    virtual_paths = [_prefixed(game_prefix, entry.relative) for entry in files]
    result = _run_git(
        repo,
        "check-ignore",
        "--no-index",
        "-z",
        "--stdin",
        check=False,
        input_text="\x00".join(virtual_paths) + "\x00",
    )
    if result.returncode not in {0, 1}:
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitWorkflowError(detail or "Could not evaluate Git ignore rules")
    ignored_virtual = {path for path in result.stdout.split("\x00") if path}
    return {
        entry.relative
        for entry, virtual in zip(files, virtual_paths)
        if virtual in ignored_virtual
    }


def _build_ignored_asset_manifest(
    source: Path, ignored_paths: Iterable[str]
) -> dict[str, _AssetManifestEntry]:
    ignored = set(ignored_paths)
    manifest = {}
    for entry in _source_files(source, format_json=False):
        if (
            entry.relative not in ignored
            or _is_local_only_asset(entry.relative)
            or _is_tool_owned_path(entry.relative)
        ):
            continue
        file_stat = entry.path.stat()
        manifest[entry.relative] = _AssetManifestEntry(
            _hash_file(entry.path), file_stat.st_size, entry.mode
        )
    return manifest


def _asset_manifest_for_source(
    repo: Path, source: Path, game_prefix: str
) -> dict[str, _AssetManifestEntry]:
    files = _source_files(source, format_json=False)
    ignored = _ignored_paths(repo, files, game_prefix)
    return {
        entry.relative: _AssetManifestEntry(
            _hash_file(entry.path), entry.path.stat().st_size, entry.mode
        )
        for entry in files
        if entry.relative in ignored
        and not _is_local_only_asset(entry.relative)
        and not _is_tool_owned_path(entry.relative)
    }


def _validate_official_asset_baseline(
    repo: Path,
    game: Path,
    source_value: str | Path,
    game_prefix: str,
    original_commit: str,
) -> tuple[Path, dict[str, _AssetManifestEntry], str]:
    source = _validate_source(source_value, game)
    build = _write_tree_from_folder(
        repo,
        source,
        game_prefix=game_prefix,
        base_commit=original_commit,
    )
    build = _preserve_tool_owned_paths(
        repo, build, original_commit, game_prefix
    )
    differences = _diff_status(repo, original_commit, build.tree, game_prefix)
    differences.pop(_prefixed(game_prefix, ".gitignore"), None)
    significant = {
        path: change
        for path, change in differences.items()
        if not _is_legacy_baseline_migration(path, change, game_prefix)
    }
    if significant:
        examples = ", ".join(
            f"{change} {_display_path(path, game_prefix)}"
            for path, change in sorted(significant.items())[:5]
        )
        if len(significant) > 5:
            examples += f", and {len(significant) - 5} more"
        raise GitWorkflowError(
            "The previous official folder does not match the registered original "
            "branch. Select the clean game folder for the currently registered version. "
            f"Mismatched tracked game files: {examples}."
        )
    return (
        source,
        _build_ignored_asset_manifest(source, build.ignored_paths),
        build.tree,
    )


def _is_legacy_baseline_migration(
    path: str, change: str, game_prefix: str
) -> bool:
    """Identify differences caused by old updater and ignore-rule layouts.

    Older projects sometimes committed the GameUpdate bundle on ``original``
    and added selected translated binary paths only after that branch was
    created.  A clean baseline legitimately removes the former and introduces
    pristine copies for the latter.  Modified or removed game assets are never
    accepted here because they can indicate a different official version.
    """
    relative = _display_path(path, game_prefix)
    if _is_tool_owned_path(relative):
        return True
    return change == "A" and _asset_category(relative) != "Other asset"


def _is_tool_owned_path(relative: str) -> bool:
    pure = PurePosixPath(relative)
    lowered = tuple(part.casefold() for part in pure.parts)
    return bool(
        (
            len(lowered) == 1
            and lowered[0] in _TOOL_OWNED_ROOT_FILES
        )
        or (
            lowered
            and lowered[0] in _TOOL_RESOURCE_DIRECTORIES
        )
    )


def _is_local_only_asset(path: str) -> bool:
    pure = PurePosixPath(path)
    lowered_parts = tuple(part.casefold() for part in pure.parts)
    if lowered_parts and lowered_parts[0] in _TOOL_RESOURCE_DIRECTORIES:
        return True
    if any(part in _LOCAL_ONLY_DIRECTORIES for part in lowered_parts[:-1]):
        return True
    if lowered_parts[:2] == ("wolf_json", "originals"):
        return True
    name = lowered_parts[-1]
    return bool(
        name in _LOCAL_ONLY_FILENAMES
        or name.startswith("save")
        or name.startswith("bsxscript_")
        or Path(name).suffix in _NON_GAME_RESOURCE_EXTENSIONS | {".log", ".tmp"}
    )


def _asset_category(path: str) -> str:
    extension = Path(path).suffix.casefold()
    if extension in _IMAGE_EXTENSIONS:
        return "Image"
    if extension in _AUDIO_EXTENSIONS:
        return "Audio"
    if extension in _VIDEO_EXTENSIONS:
        return "Video"
    if extension in _FONT_EXTENSIONS:
        return "Font"
    return "Other asset"


def _destination_matches(game: Path, path: str, entry: _AssetManifestEntry) -> bool:
    destination = game.joinpath(*PurePosixPath(path).parts)
    if destination.is_symlink():
        raise GitWorkflowError(f"Asset destination is a symbolic link: {path}")
    if not destination.exists():
        return False
    if not destination.is_file():
        raise GitWorkflowError(f"Asset destination is not a regular file: {path}")
    return destination.stat().st_size == entry.size and _hash_file(destination) == entry.sha256


def _external_asset_changes(
    game: Path,
    baseline: Mapping[str, _AssetManifestEntry] | None,
    proposed: Mapping[str, _AssetManifestEntry],
) -> tuple[UpdateExternalChange, ...]:
    changes = []
    if baseline is None:
        candidates = proposed.keys()
    else:
        candidates = {
            path
            for path in set(baseline) | set(proposed)
            if baseline.get(path) != proposed.get(path)
        }
    for path in sorted(candidates):
        _validate_manifest_path(path)
        old = baseline.get(path) if baseline is not None else None
        new = proposed.get(path)
        if new is None:
            change = "Removed"
            destination = game.joinpath(*PurePosixPath(path).parts)
            if destination.is_symlink():
                raise GitWorkflowError(f"Asset destination is a symbolic link: {path}")
            already_present = not destination.exists()
            size = old.size if old else 0
            result = (
                "Already absent; no removal needed"
                if already_present
                else "Will be removed outside Git"
            )
        else:
            already_present = _destination_matches(game, path, new)
            destination_exists = game.joinpath(*PurePosixPath(path).parts).exists()
            change = "Added" if old is None and not destination_exists else "Replaced"
            size = new.size
            result = (
                "Already present; no copy needed"
                if already_present
                else "Will be copied outside Git"
            )
            if baseline is None and already_present:
                continue
        changes.append(
            UpdateExternalChange(
                path=path,
                change=change,
                category=_asset_category(path),
                already_present=already_present,
                size_bytes=size,
                result=result,
            )
        )
    return tuple(changes)


def _asset_destination(game: Path, relative: str) -> Path:
    _validate_manifest_path(relative)
    pure = PurePosixPath(relative)
    current = game
    for part in pure.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise GitWorkflowError(f"Asset destination crosses a symbolic link: {relative}")
        if current.exists() and not current.is_dir():
            raise GitWorkflowError(f"Asset destination parent is not a directory: {relative}")
    destination = game.joinpath(*pure.parts)
    if destination.is_symlink():
        raise GitWorkflowError(f"Asset destination is a symbolic link: {relative}")
    if destination.exists() and not destination.is_file():
        raise GitWorkflowError(f"Asset destination is not a regular file: {relative}")
    return destination


def _sync_external_assets(
    repo: Path,
    game: Path,
    source: Path,
    changes: tuple[UpdateExternalChange, ...],
    proposed: Mapping[str, _AssetManifestEntry],
) -> tuple[UpdateExternalChange, ...]:
    pending = tuple(change for change in changes if not change.already_present)
    if not pending:
        return ()
    state_dir = _asset_state_path(repo, "", "sync-stage").parent
    state_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="asset-sync-", dir=state_dir) as temporary:
        stage_root = Path(temporary)
        staged: dict[str, Path] = {}
        backups: dict[str, Path | None] = {}
        destinations = {}
        for index, change in enumerate(pending):
            destination = _asset_destination(game, change.path)
            destinations[change.path] = destination
            if destination.exists():
                backup = stage_root / f"backup-{index}"
                shutil.copy2(destination, backup)
                backups[change.path] = backup
            else:
                backups[change.path] = None
            if change.change != "Removed":
                source_path = source.joinpath(*PurePosixPath(change.path).parts)
                if source_path.is_symlink() or not source_path.is_file():
                    raise GitWorkflowError(
                        f"Official asset is no longer a regular file: {change.path}"
                    )
                expected = proposed.get(change.path)
                if expected is None or not (
                    source_path.stat().st_size == expected.size
                    and _hash_file(source_path) == expected.sha256
                ):
                    raise GitWorkflowError(
                        f"Official asset changed during synchronization: {change.path}"
                    )
                staged_path = stage_root / f"new-{index}"
                shutil.copy2(source_path, staged_path)
                if not (
                    staged_path.stat().st_size == expected.size
                    and _hash_file(staged_path) == expected.sha256
                ):
                    raise GitWorkflowError(
                        f"Official asset could not be staged exactly: {change.path}"
                    )
                staged[change.path] = staged_path

        applied: list[str] = []
        try:
            for change in pending:
                destination = destinations[change.path]
                if change.change == "Removed":
                    if destination.exists():
                        destination.unlink()
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(staged[change.path], destination)
                applied.append(change.path)
        except Exception as exc:
            rollback_errors = []
            for relative in reversed(applied):
                destination = destinations[relative]
                backup = backups[relative]
                try:
                    if backup is None:
                        if destination.exists():
                            destination.unlink()
                    else:
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(backup, destination)
                except OSError as rollback_exc:
                    rollback_errors.append(f"{relative}: {rollback_exc}")
            detail = f"Could not synchronize official game assets: {exc}"
            if rollback_errors:
                detail += ". Rollback also failed for " + ", ".join(rollback_errors)
            raise GitWorkflowError(detail) from exc
    return pending


def _materialize_normalized_json(files: list[_SourceFile]) -> None:
    for entry in files:
        if entry.normalized_text is None:
            continue
        original_mode = entry.path.stat().st_mode
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{entry.path.name}.dazedformat-", dir=entry.path.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(entry.normalized_text)
            os.chmod(temporary_name, stat.S_IMODE(original_mode))
            os.replace(temporary_name, entry.path)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass
            raise


def _write_tree_from_folder(
    repo: Path,
    source: Path,
    *,
    game_prefix: str,
    base_commit: str | None,
    format_json: bool = True,
    materialize_json: bool = False,
) -> _TreeBuild:
    discovered_files = _source_files(source, format_json=format_json)
    managed_ignore = repo.joinpath(game_prefix, ".gitignore")
    if managed_ignore.is_file():
        discovered_files = [
            entry for entry in discovered_files if entry.relative != ".gitignore"
        ]
        discovered_files.append(
            _SourceFile(managed_ignore, ".gitignore", "100644")
        )
        discovered_files.sort(key=lambda entry: entry.relative)
    ignored = _ignored_paths(repo, discovered_files, game_prefix)
    files = [entry for entry in discovered_files if entry.relative not in ignored]
    if materialize_json:
        _materialize_normalized_json(files)
    index_name, index_env = _temporary_index()
    try:
        if base_commit:
            _run_git(repo, "read-tree", base_commit, env=index_env)
        else:
            _run_git(repo, "read-tree", "--empty", env=index_env)

        existing = _run_git(repo, "ls-files", "-z", env=index_env).stdout.split("\x00")
        prefix_marker = f"{game_prefix}/" if game_prefix else ""
        removals = [
            path
            for path in existing
            if path and (not game_prefix or path == game_prefix or path.startswith(prefix_marker))
        ]
        index_lines = [f"0 {_ZERO_OID}\t{path}" for path in removals]

        raw_files = [entry for entry in files if entry.normalized_text is None]
        raw_hashes: dict[str, str] = {}
        if raw_files:
            absolute_paths = "\n".join(str(entry.path) for entry in raw_files) + "\n"
            hashes = _run_git(
                repo,
                "hash-object",
                "-w",
                "--no-filters",
                "--stdin-paths",
                input_text=absolute_paths,
                timeout=600,
            ).stdout.splitlines()
            if len(hashes) != len(raw_files):
                raise GitWorkflowError("Git did not hash every file in the selected game")
            raw_hashes = {
                entry.relative: blob for entry, blob in zip(raw_files, hashes)
            }
        for entry in files:
            if entry.normalized_text is None:
                blob = raw_hashes[entry.relative]
            else:
                blob = _run_git(
                    repo,
                    "hash-object",
                    "-w",
                    "--no-filters",
                    "--stdin",
                    input_text=entry.normalized_text,
                ).stdout.strip()
            index_lines.append(
                f"{entry.mode} {blob}\t{_prefixed(game_prefix, entry.relative)}"
            )

        if index_lines:
            _run_git(
                repo,
                "update-index",
                "--index-info",
                input_text="\n".join(index_lines) + "\n",
                env=index_env,
                timeout=600,
            )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
        warnings = [
            entry.json_warning for entry in files if entry.json_warning is not None
        ]
        if not any(entry.path.name == ".gitignore" for entry in discovered_files):
            warnings.append(
                "No .gitignore was found in the selected game folder. Files not "
                "covered by repository or global exclude rules will be committed."
            )
        return _TreeBuild(
            tree=tree,
            formatted_json_paths=tuple(
                entry.relative for entry in files if entry.normalized_text is not None
            ),
            json_warnings=tuple(warnings),
            ignored_paths=tuple(sorted(ignored)),
        )
    finally:
        try:
            Path(index_name).unlink()
        except FileNotFoundError:
            pass


def _commit_tree(
    repo: Path,
    tree: str,
    message: str,
    parents: Iterable[str] = (),
) -> str:
    args = [
        "-c",
        f"user.name={_TOOL_NAME}",
        "-c",
        f"user.email={_TOOL_EMAIL}",
        "commit-tree",
        tree,
    ]
    for parent in parents:
        args.extend(["-p", parent])
    args.extend(["-m", message])
    return _run_git(repo, *args).stdout.strip()


def _message(subject: str, version: str) -> str:
    return f"{subject}\n\n{VERSION_TRAILER}: {version}"


def _ensure_translation_branch(repo: Path, head: str, branch: str) -> None:
    translation = _ref_commit(repo, branch)
    current = _run_git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    current_name = current.stdout.strip()
    if translation and current_name != branch:
        raise GitWorkflowError(
            f"The translated branch {branch!r} exists but is not checked out. Switch to it first."
        )
    if not translation:
        _run_git(repo, "update-ref", f"refs/heads/{branch}", head)
        _run_git(repo, "symbolic-ref", "HEAD", f"refs/heads/{branch}")


def bootstrap_repository(
    translated_game: str | Path,
    original_game: str | Path,
    version: str,
) -> BootstrapResult:
    translated = Path(translated_game).expanduser().resolve()
    if not translated.is_dir():
        raise GitWorkflowError(f"Translated game folder not found: {translated}")
    version = _validate_version(version)
    original = _validate_source(original_game, translated)
    found = _repository_for(translated)

    if found is None:
        if translated.joinpath(".git").exists():
            raise GitWorkflowError("The selected folder contains unusable Git metadata")
        # Validate both trees before creating any repository state.
        _source_files(original, format_json=True)
        _source_files(translated, format_json=True)
        gitignore_installed = _install_gameupdate_gitignore(translated)
        _run_git(translated, "init", "-b", TRANSLATION_BRANCH)
        repo, prefix = translated, ""
        translation_branch = TRANSLATION_BRANCH
        _ensure_local_excludes(repo)
        original_tree = _write_tree_from_folder(
            repo, original, game_prefix=prefix, base_commit=None
        )
        original_commit = _commit_tree(
            repo,
            original_tree.tree,
            _message(f"original: import clean game {version}", version),
        )
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{ORIGINAL_BRANCH}",
            original_commit,
        )
        translation_tree = _write_tree_from_folder(
            repo,
            translated,
            game_prefix=prefix,
            base_commit=original_commit,
            format_json=True,
            materialize_json=True,
        )
        translation_commit = _commit_tree(
            repo,
            translation_tree.tree,
            _message(f"translation: record translated game {version}", version),
            (original_commit,),
        )
    else:
        repo, prefix = found
        _ensure_local_excludes(repo)
        status = inspect_repository(translated)
        if status.pending_cherry_pick:
            raise GitWorkflowError("Finish or abort the pending cherry-pick first")
        if not status.worktree_clean:
            raise GitWorkflowError(
                "Commit or discard current Git changes before registering the original game"
            )
        if status.original_exists:
            raise GitWorkflowError("The original branch already exists")
        head = _run_git(repo, "rev-parse", "HEAD", check=False)
        if head.returncode != 0:
            raise GitWorkflowError(
                "Existing repositories must have at least one commit before reconciliation"
            )
        head_commit = head.stdout.strip()
        translation_branch = status.translation_branch or status.current_branch
        if not translation_branch or translation_branch == ORIGINAL_BRANCH:
            raise GitWorkflowError(
                "Check out the branch containing the translated game before reconciliation"
            )
        gitignore_installed = _install_gameupdate_gitignore(translated)
        _ensure_translation_branch(repo, head_commit, translation_branch)
        original_tree = _write_tree_from_folder(
            repo, original, game_prefix=prefix, base_commit=head_commit
        )
        original_commit = _commit_tree(
            repo,
            original_tree.tree,
            _message(f"original: import clean game {version}", version),
            (head_commit,),
        )
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{ORIGINAL_BRANCH}",
            original_commit,
        )
        translation_tree = _write_tree_from_folder(
            repo,
            translated,
            game_prefix=prefix,
            base_commit=head_commit,
            format_json=True,
            materialize_json=True,
        )
        translation_commit = _commit_tree(
            repo,
            translation_tree.tree,
            _message(f"translation: register original baseline {version}", version),
            (head_commit, original_commit),
        )

    _run_git(
        repo,
        "update-ref",
        f"refs/heads/{translation_branch}",
        translation_commit,
    )
    _run_git(repo, "symbolic-ref", "HEAD", f"refs/heads/{translation_branch}")
    _run_git(repo, "read-tree", translation_commit)
    if _run_git(repo, "status", "--porcelain=v1", "-z").stdout:
        raise GitWorkflowError(
            "Git baseline was created, but the translated worktree does not match it"
        )
    official_assets = _build_ignored_asset_manifest(
        original, original_tree.ignored_paths
    )
    _save_asset_manifest(
        repo, prefix, version, original_commit, official_assets
    )
    _set_translation_branch(repo, translation_branch)
    return BootstrapResult(
        repo,
        original_commit,
        translation_commit,
        version,
        translation_tree.formatted_json_paths,
        translation_tree.json_warnings,
        translation_tree.ignored_paths,
        gitignore_installed,
    )


def register_translation_branch(
    translated_game: str | Path,
    version: str | None = None,
    *,
    branch: str | None = None,
    replace: bool = False,
) -> BootstrapResult:
    """Register an existing local branch as the translated game branch."""
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit:
        raise GitWorkflowError("The original branch must exist first")
    if status.translation_exists and not replace:
        raise GitWorkflowError("The translated branch is already registered")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before reconciliation")
    translation_branch = _validate_branch_name(
        status.repo_root, branch or status.current_branch or ""
    )
    if branch and _ref_commit(status.repo_root, translation_branch) is None:
        raise GitWorkflowError(f"The translated branch does not exist: {translation_branch}")
    if status.current_branch != translation_branch:
        _run_git(status.repo_root, "checkout", translation_branch)
    head = _run_git(status.repo_root, "rev-parse", "HEAD", check=False)
    if head.returncode != 0:
        raise GitWorkflowError("The current translated branch has no commit to register")
    head_commit = head.stdout.strip()
    if head_commit == status.original_commit:
        raise GitWorkflowError(
            "The original branch itself is checked out. Select or commit the translated game state first."
        )
    resolved_version = _validate_version(version or status.original_version or "")
    _ensure_local_excludes(status.repo_root)
    gitignore_installed = _install_gameupdate_gitignore(game)
    translation_tree = _write_tree_from_folder(
        status.repo_root,
        game,
        game_prefix=status.game_prefix,
        base_commit=head_commit,
        format_json=True,
        materialize_json=True,
    )
    current_tree = _run_git(
        status.repo_root, "rev-parse", f"{head_commit}^{{tree}}"
    ).stdout.strip()
    current_version = _version_from_history(
        status.repo_root, translation_branch, head_commit
    )
    if translation_tree.tree == current_tree and current_version == resolved_version:
        translation_commit = head_commit
    else:
        translation_commit = _commit_tree(
            status.repo_root,
            translation_tree.tree,
            _message(
                f"translation: register translated game {resolved_version}",
                resolved_version,
            ),
            (head_commit, status.original_commit),
        )
    _run_git(
        status.repo_root,
        "update-ref",
        f"refs/heads/{translation_branch}",
        translation_commit,
    )
    _run_git(
        status.repo_root,
        "symbolic-ref", "HEAD", f"refs/heads/{translation_branch}",
    )
    _run_git(status.repo_root, "read-tree", translation_commit)
    _set_translation_branch(status.repo_root, translation_branch)
    return BootstrapResult(
        status.repo_root,
        status.original_commit,
        translation_commit,
        resolved_version,
        translation_tree.formatted_json_paths,
        translation_tree.json_warnings,
        translation_tree.ignored_paths,
        gitignore_installed,
    )


def local_branch_names(game_root: str | Path) -> tuple[str, ...]:
    """Return safe local branch choices for translated-branch registration."""
    status = inspect_repository(game_root)
    if not status.repo_root:
        return ()
    output = _run_git(
        status.repo_root,
        "for-each-ref",
        "--format=%(refname:short)",
        "refs/heads",
    ).stdout
    branches = []
    for raw in output.splitlines():
        branch = raw.strip()
        if not branch or branch == ORIGINAL_BRANCH:
            continue
        branches.append(_validate_branch_name(status.repo_root, branch))
    return tuple(sorted(set(branches)))


def record_version_metadata(
    translated_game: str | Path, version: str
) -> BootstrapResult:
    """Repair a complete legacy branch layout that lacks version trailers.

    The file trees are reused exactly.  Only no-content commits are added to
    the two branch tips so subsequent repository inspection can identify the
    registered baseline version.
    """
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Both original and translated branches must exist")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before reconciliation")
    resolved_version = _validate_version(version)
    repo = status.repo_root

    if status.current_branch != status.translation_branch:
        _run_git(repo, "checkout", status.translation_branch)
    _reject_original_checked_out_elsewhere(repo)

    original_commit = status.original_commit
    if not status.original_version:
        original_tree = _run_git(
            repo, "rev-parse", f"{original_commit}^{{tree}}"
        ).stdout.strip()
        original_commit = _commit_tree(
            repo,
            original_tree,
            _message(f"original: record version metadata {resolved_version}", resolved_version),
            (original_commit,),
        )
        _run_git(repo, "update-ref", f"refs/heads/{ORIGINAL_BRANCH}", original_commit)

    translation_commit = status.translation_commit
    if not status.translation_version:
        translation_tree = _run_git(
            repo, "rev-parse", f"{translation_commit}^{{tree}}"
        ).stdout.strip()
        translation_commit = _commit_tree(
            repo,
            translation_tree,
            _message(
                f"translation: record version metadata {resolved_version}",
                resolved_version,
            ),
            (translation_commit,),
        )
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{status.translation_branch}",
            translation_commit,
        )
        _run_git(repo, "reset", "--soft", translation_commit)

    return BootstrapResult(
        repo,
        original_commit,
        translation_commit,
        resolved_version,
    )


def checkout_translation_branch(translated_game: str | Path) -> RepositoryStatus:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.translation_exists:
        raise GitWorkflowError("The translated branch is not registered")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current changes before switching branches")
    _run_git(status.repo_root, "checkout", status.translation_branch)
    return inspect_repository(game)


def _validate_conflict_path(path: str, prefix: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise GitWorkflowError(f"Git reported an unsafe conflict path: {path!r}")
    if prefix and path != prefix and not path.startswith(f"{prefix}/"):
        raise GitWorkflowError(f"Update conflict escaped the selected game folder: {path}")


def conflict_paths(game_root: str | Path) -> tuple[str, ...]:
    status = inspect_repository(game_root)
    if not status.repo_root:
        return ()
    output = _run_git(
        status.repo_root,
        "diff",
        "--name-only",
        "--diff-filter=U",
        "-z",
        check=False,
    ).stdout
    return tuple(path for path in output.split("\x00") if path)


def _resolve_conflicts_with_official(repo: Path, prefix: str) -> tuple[str, ...]:
    paths = conflict_paths(repo)
    for path in paths:
        _validate_conflict_path(path, prefix)
        stage_records = _run_git(
            repo, "ls-files", "-u", "-z", "--", path
        ).stdout.split("\x00")
        stages: dict[int, tuple[str, str]] = {}
        for record in stage_records:
            if not record:
                continue
            metadata, _recorded_path = record.split("\t", 1)
            mode, object_id, stage_text = metadata.split(" ")
            stages[int(stage_text)] = (mode, object_id)

        if 3 not in stages:
            _run_git(repo, "rm", "-f", "--", path)
            continue

        if all(stage in stages for stage in (1, 2, 3)):
            official_mode, official_object = stages[3]
            merged = _run_git(
                repo,
                "merge-file",
                "--object-id",
                "--theirs",
                stages[2][1],
                stages[1][1],
                official_object,
                check=False,
            )
            merged_object = merged.stdout.strip()
            if merged.returncode == 0 and re.fullmatch(
                r"[0-9a-f]{40,64}", merged_object
            ):
                _run_git(
                    repo,
                    "update-index",
                    "--add",
                    "--cacheinfo",
                    f"{official_mode},{merged_object},{path}",
                )
                _run_git(repo, "checkout-index", "--force", "--", path)
                continue

            detail = merged.stderr.strip() or merged.stdout.strip()
            if "binary" not in detail.casefold():
                raise GitWorkflowError(
                    f"Could not resolve text conflict in {path} by Git hunk: "
                    + (detail or "git merge-file returned no merged object")
                )

        # Add/add conflicts and binary files cannot be combined safely by line.
        # The official file wins as the explicit fallback for those cases.
        _run_git(repo, "checkout", "--theirs", "--", path)
        _run_git(repo, "add", "--", path)
    remaining = conflict_paths(repo)
    if remaining:
        raise GitWorkflowError(
            "Some conflicts could not be resolved with the official version: "
            + ", ".join(remaining)
        )
    return paths


def _finish_cherry_pick(repo: Path, original_commit: str) -> str:
    env = {"GIT_EDITOR": "true"}
    continued = _run_git(
        repo,
        "-c",
        f"user.name={_TOOL_NAME}",
        "-c",
        f"user.email={_TOOL_EMAIL}",
        "cherry-pick",
        "--continue",
        check=False,
        env=env,
    )
    if continued.returncode != 0:
        combined = f"{continued.stdout}\n{continued.stderr}".lower()
        if "empty" in combined:
            aborted = _run_git(repo, "cherry-pick", "--abort", check=False)
            recovery = ""
            if aborted.returncode != 0:
                recovery = (
                    " The cherry-pick could not be restored automatically; use the "
                    "recovery controls before continuing."
                )
            raise GitWorkflowError(
                "The official patch unexpectedly produced no translation changes. "
                "No version marker was created." + recovery
            )
        else:
            detail = continued.stderr.strip() or continued.stdout.strip()
            raise GitWorkflowError(detail or "Could not finish cherry-pick")
    return _run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _tree_entry(repo: Path, ref: str, path: str) -> str:
    return _run_git(repo, "ls-tree", "-z", ref, "--", path).stdout


def _already_present_patch_paths(
    repo: Path,
    original_parent: str,
    original_commit: str,
    translation_commit: str,
    game_prefix: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    changed = tuple(
        sorted(_diff_status(repo, original_parent, original_commit, game_prefix))
    )
    already_present = tuple(
        path
        for path in changed
        if _tree_entry(repo, original_commit, path)
        == _tree_entry(repo, translation_commit, path)
    )
    return changed, already_present


def _record_already_present_version(
    repo: Path,
    translation_branch: str,
    translation_commit: str,
    original_commit: str,
    version: str,
    paths: tuple[str, ...],
    game_prefix: str,
) -> UpdateResult:
    tree = _run_git(repo, "rev-parse", f"{translation_commit}^{{tree}}").stdout.strip()
    message = _message(
        f"translation: record already-present original game version {version}", version
    )
    marker = _commit_tree(repo, tree, message, (translation_commit,))
    _run_git(
        repo,
        "update-ref",
        f"refs/heads/{translation_branch}",
        marker,
        translation_commit,
    )
    return UpdateResult(
        repo_root=repo,
        original_commit=original_commit,
        translation_commit=marker,
        version=version,
        content_changed=False,
        already_present_paths=tuple(
            _display_path(path, game_prefix) for path in paths
        ),
    )


def _cherry_pick(
    game_root: Path,
    original_commit: str,
    version: str,
    *,
    auto_resolve: bool,
) -> UpdateResult:
    status = inspect_repository(game_root)
    if not status.repo_root:
        raise GitWorkflowError("The translated game is not in a Git repository")
    repo = status.repo_root
    if not status.translation_commit:
        raise GitWorkflowError("The translated branch has no commit to update")
    parent = _run_git(repo, "rev-parse", f"{original_commit}^").stdout.strip()
    changed, already_present = _already_present_patch_paths(
        repo,
        parent,
        original_commit,
        status.translation_commit,
        status.game_prefix,
    )
    if len(already_present) == len(changed):
        return _record_already_present_version(
            repo,
            status.translation_branch,
            status.translation_commit,
            original_commit,
            version,
            already_present,
            status.game_prefix,
        )
    picked = _run_git(
        repo,
        "-c",
        f"user.name={_TOOL_NAME}",
        "-c",
        f"user.email={_TOOL_EMAIL}",
        "cherry-pick",
        original_commit,
        check=False,
    )
    if picked.returncode == 0:
        return UpdateResult(
            repo, original_commit, _run_git(repo, "rev-parse", "HEAD").stdout.strip(), version
        )

    conflicts = conflict_paths(game_root)
    if not conflicts:
        detail = picked.stderr.strip() or picked.stdout.strip()
        if "empty" in detail.lower():
            aborted = _run_git(repo, "cherry-pick", "--abort", check=False)
            recovery = ""
            if aborted.returncode != 0:
                recovery = (
                    " The cherry-pick could not be restored automatically; use the "
                    "recovery controls before continuing."
                )
            raise GitWorkflowError(
                "The official patch unexpectedly produced no translation changes. "
                "No version marker was created." + recovery
            )
        raise GitWorkflowError(detail or "Cherry-pick failed without file conflicts")
    if not auto_resolve:
        return UpdateResult(repo, original_commit, None, version, (), conflicts)
    won = _resolve_conflicts_with_official(repo, status.game_prefix)
    translation_commit = _finish_cherry_pick(repo, original_commit)
    return UpdateResult(repo, original_commit, translation_commit, version, won)


def _diff_status(
    repo: Path, left: str, right: str, game_prefix: str
) -> dict[str, str]:
    args = ["diff", "--name-status", "--no-renames", "-z", left, right]
    if game_prefix:
        args.extend(["--", game_prefix])
    tokens = [token for token in _run_git(repo, *args).stdout.split("\x00") if token]
    if len(tokens) % 2:
        raise GitWorkflowError("Git returned an invalid change preview")
    return {tokens[index + 1]: tokens[index] for index in range(0, len(tokens), 2)}


def _diff_numstat(
    repo: Path, left: str, right: str, game_prefix: str
) -> dict[str, tuple[int | None, int | None]]:
    args = ["diff", "--numstat", "--no-renames", "-z", left, right]
    if game_prefix:
        args.extend(["--", game_prefix])
    stats = {}
    for record in _run_git(repo, *args).stdout.split("\x00"):
        if not record:
            continue
        fields = record.split("\t", 2)
        if len(fields) != 3:
            raise GitWorkflowError("Git returned invalid line counts for the update preview")
        added, deleted, path = fields
        stats[path] = (
            None if added == "-" else int(added),
            None if deleted == "-" else int(deleted),
        )
    return stats


def _tree_files(
    repo: Path, ref: str, game_prefix: str
) -> dict[str, tuple[str, str]]:
    args = ["ls-tree", "-r", "-z", ref]
    if game_prefix:
        args.extend(["--", game_prefix])
    files = {}
    for record in _run_git(repo, *args).stdout.split("\x00"):
        if not record:
            continue
        metadata, path = record.split("\t", 1)
        mode, object_type, object_id = metadata.split()
        if object_type == "blob":
            files[path] = (mode, object_id)
    return files


def _preserve_tool_owned_paths(
    repo: Path,
    build: _TreeBuild,
    base_ref: str,
    game_prefix: str,
) -> _TreeBuild:
    """Keep updater infrastructure out of official game patches."""
    base_files = _tree_files(repo, base_ref, game_prefix)
    proposed_files = _tree_files(repo, build.tree, game_prefix)
    index_lines = []
    for path in sorted(set(base_files) | set(proposed_files)):
        if not _is_tool_owned_path(_display_path(path, game_prefix)):
            continue
        base = base_files.get(path)
        proposed = proposed_files.get(path)
        if base == proposed:
            continue
        if base is None:
            index_lines.append(f"0 {_ZERO_OID}\t{path}")
        else:
            mode, object_id = base
            index_lines.append(f"{mode} {object_id}\t{path}")

    if not index_lines:
        return build

    index_name, index_env = _temporary_index()
    try:
        _run_git(repo, "read-tree", build.tree, env=index_env)
        _run_git(
            repo,
            "update-index",
            "--index-info",
            input_text="\n".join(index_lines) + "\n",
            env=index_env,
        )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
        return replace(build, tree=tree)
    finally:
        try:
            Path(index_name).unlink()
        except FileNotFoundError:
            pass


def _preserve_unbased_translation_assets(
    repo: Path,
    build: _TreeBuild,
    original_commit: str,
    translation_commit: str,
    game_prefix: str,
) -> tuple[_TreeBuild, tuple[str, ...]]:
    """Exclude translated assets that have no authoritative original blob.

    Without a previous clean folder, comparing a translated image to the new
    official image cannot prove that the official asset changed. Keeping the
    path absent from both the original baseline and proposed official tree
    preserves the translated worktree copy instead of overwriting it on an
    unsupported guess.
    """
    original_files = _tree_files(repo, original_commit, game_prefix)
    translated_files = _tree_files(repo, translation_commit, game_prefix)
    proposed_files = _tree_files(repo, build.tree, game_prefix)
    index_lines = []
    preserved = []
    for path in translated_files:
        relative = _display_path(path, game_prefix)
        if (
            path not in original_files
            and path in proposed_files
            and not _is_tool_owned_path(relative)
            and _asset_category(relative) != "Other asset"
        ):
            index_lines.append(f"0 {_ZERO_OID}\t{path}")
            preserved.append(relative)

    if not index_lines:
        return build, ()

    index_name, index_env = _temporary_index()
    try:
        _run_git(repo, "read-tree", build.tree, env=index_env)
        _run_git(
            repo,
            "update-index",
            "--index-info",
            input_text="\n".join(index_lines) + "\n",
            env=index_env,
        )
        tree = _run_git(repo, "write-tree", env=index_env).stdout.strip()
        return replace(build, tree=tree), tuple(sorted(preserved))
    finally:
        try:
            Path(index_name).unlink()
        except FileNotFoundError:
            pass


def _replacement_outcome(
    repo: Path,
    official_change: str,
    translation_change: str | None,
    base: tuple[str, str] | None,
    translated: tuple[str, str] | None,
    official: tuple[str, str] | None,
    *,
    is_image: bool,
) -> tuple[bool, str]:
    if translation_change is None:
        if official_change == "A":
            return False, "New file"
        if official_change == "D":
            return False, "File removed"
        return False, "Image replaced" if is_image else "Official changes applied"

    if official_change == "D":
        return True, "Translated file removed"
    if official_change == "A" or translation_change == "D":
        noun = "image" if is_image else "file"
        return True, f"Translated {noun} replaced by official {noun}"

    if not base or not translated or not official:
        return True, "Translated file replaced by official file"
    if translated[1] == base[1]:
        return False, "Image replaced" if is_image else "Official changes applied"
    if translated[1] == official[1]:
        return False, "Official content already present; file metadata updated"
    merged = _run_git(
        repo,
        "merge-file",
        "--object-id",
        "--theirs",
        translated[1],
        base[1],
        official[1],
        check=False,
    )
    merged_object = merged.stdout.strip()
    if merged.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", merged_object):
        noun = "image" if is_image else "binary file"
        return True, f"Translated {noun} replaced by official {noun}"
    if merged_object == official[1]:
        return True, "Entire translated file replaced by official content"
    return False, "Merged with translation edits"


def _display_path(path: str, game_prefix: str) -> str:
    prefix = f"{game_prefix}/" if game_prefix else ""
    return path[len(prefix) :] if prefix and path.startswith(prefix) else path


def preview_official_update(
    translated_game: str | Path,
    new_official_game: str | Path,
    version: str,
    *,
    previous_official_game: str | Path | None = None,
) -> UpdatePreview:
    """Build a non-ref preview of the normalized official release tree."""
    game = Path(translated_game).expanduser().resolve()
    version = _validate_version(version)
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Register both branches before previewing an update")
    if status.current_branch != status.translation_branch:
        raise GitWorkflowError(
            f"Switch to the translated branch {status.translation_branch!r} before previewing"
        )
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before previewing")
    official = _validate_source(new_official_game, game)
    build = _write_tree_from_folder(
        status.repo_root,
        official,
        game_prefix=status.game_prefix,
        base_commit=status.original_commit,
    )
    build = _preserve_tool_owned_paths(
        status.repo_root,
        build,
        status.original_commit,
        status.game_prefix,
    )
    preserved_translation_assets = ()
    if previous_official_game is None:
        build, preserved_translation_assets = _preserve_unbased_translation_assets(
            status.repo_root,
            build,
            status.original_commit,
            status.translation_commit,
            status.game_prefix,
        )
    baseline_assets = _load_asset_manifest(status.repo_root, status.game_prefix)
    stored_asset_baseline = baseline_assets is not None
    baseline_source = None
    baseline_tree = _run_git(
        status.repo_root, "rev-parse", f"{status.original_commit}^{{tree}}"
    ).stdout.strip()
    if baseline_assets is None:
        if previous_official_game is not None:
            baseline_source, baseline_assets, baseline_tree = (
                _validate_official_asset_baseline(
                    status.repo_root,
                    game,
                    previous_official_game,
                    status.game_prefix,
                    status.original_commit,
                )
            )
        else:
            baseline_assets = _asset_manifest_for_source(
                status.repo_root,
                game,
                status.game_prefix,
            )
    proposed_assets = _build_ignored_asset_manifest(official, build.ignored_paths)
    external_changes = _external_asset_changes(
        game, baseline_assets, proposed_assets
    )
    official_changes = _diff_status(
        status.repo_root, baseline_tree, build.tree, status.game_prefix
    )
    translation_changes = _diff_status(
        status.repo_root,
        baseline_tree,
        status.translation_commit,
        status.game_prefix,
    )
    original_files = _tree_files(
        status.repo_root, baseline_tree, status.game_prefix
    )
    translated_files = _tree_files(
        status.repo_root, status.translation_commit, status.game_prefix
    )
    proposed_files = _tree_files(status.repo_root, build.tree, status.game_prefix)
    overlap = sorted(set(official_changes) & set(translation_changes))
    already_present = tuple(
        sorted(
            path
            for path in official_changes
            if proposed_files.get(path) == translated_files.get(path)
        )
    )
    line_stats = _diff_numstat(
        status.repo_root, baseline_tree, build.tree, status.game_prefix
    )
    file_changes = []
    for path in sorted(official_changes):
        display_path = _display_path(path, status.game_prefix)
        change_code = official_changes[path]
        is_image = Path(display_path).suffix.casefold() in _IMAGE_EXTENSIONS
        if path in already_present:
            whole_file_replaced = False
            result = "Already present; no game change"
        else:
            whole_file_replaced, result = _replacement_outcome(
                status.repo_root,
                change_code,
                translation_changes.get(path),
                original_files.get(path),
                translated_files.get(path),
                proposed_files.get(path),
                is_image=is_image,
            )
        added_lines, deleted_lines = line_stats.get(path, (None, None))
        file_changes.append(
            UpdateFileChange(
                path=display_path,
                change={"A": "Added", "D": "Removed"}.get(
                    change_code, "Modified"
                ),
                added_lines=added_lines,
                deleted_lines=deleted_lines,
                is_image=is_image,
                translation_changed=path in translation_changes,
                already_present=path in already_present,
                whole_file_replaced=whole_file_replaced,
                result=result,
            )
        )

    image_changes = []
    for tracked_change in file_changes:
        if not tracked_change.is_image or tracked_change.already_present:
            continue
        image_change = {
            "Added": "Added",
            "Removed": "Removed",
        }.get(tracked_change.change, "Replaced")
        warning = image_change in {"Removed", "Replaced"}
        if warning:
            result = (
                "⚠ Tracked translation image will be removed"
                if image_change == "Removed"
                else "⚠ Tracked translation image will be replaced"
            )
        else:
            result = "Tracked image will be added"
        image_changes.append(
            UpdateImageChange(
                path=tracked_change.path,
                change=image_change,
                tracked=True,
                warning=warning,
                result=result,
            )
        )
    image_changes.extend(
        UpdateImageChange(
            path=change.path,
            change=change.change,
            tracked=False,
            warning=False,
            result=change.result,
        )
        for change in external_changes
        if change.category == "Image"
    )

    def paths_for(code: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                _display_path(path, status.game_prefix)
                for path, change in official_changes.items()
                if change == code
            )
        )

    return UpdatePreview(
        repo_root=status.repo_root,
        source_root=official,
        version=version,
        original_commit=status.original_commit,
        translation_commit=status.translation_commit,
        proposed_tree=build.tree,
        added_paths=paths_for("A"),
        modified_paths=paths_for("M"),
        deleted_paths=paths_for("D"),
        overlapping_paths=tuple(
            _display_path(path, status.game_prefix) for path in overlap
        ),
        already_present_paths=tuple(
            _display_path(path, status.game_prefix) for path in already_present
        ),
        formatted_json_paths=build.formatted_json_paths,
        json_warnings=build.json_warnings,
        ignored_paths=build.ignored_paths,
        file_changes=tuple(file_changes),
        image_changes=tuple(image_changes),
        external_changes=external_changes,
        proposed_asset_manifest=_manifest_digest(proposed_assets),
        baseline_asset_manifest=_manifest_digest(baseline_assets),
        asset_manifest_available=stored_asset_baseline,
        baseline_source_root=baseline_source,
        preserved_translation_asset_paths=preserved_translation_assets,
    )


def _complete_pending_asset_plan(
    game: Path, result: UpdateResult
) -> UpdateResult:
    status = inspect_repository(game)
    if not status.repo_root:
        raise GitWorkflowError("The translated game is not in a Git repository")
    plan = _load_pending_asset_plan(status.repo_root, status.game_prefix)
    if plan is None:
        return result
    if (
        plan["original_commit"] != result.original_commit
        or plan["version"] != result.version
    ):
        raise GitWorkflowError(
            "The pending asset update does not match the registered original version"
        )
    source = _validate_source(plan["source"], game)
    proposed = _asset_manifest_for_source(
        status.repo_root, source, status.game_prefix
    )
    if _manifest_digest(proposed) != plan["manifest_digest"]:
        raise GitWorkflowError(
            "The official folder changed before its assets were synchronized. "
            "Restore that folder and finish the asset update."
        )
    baseline = _load_asset_manifest(status.repo_root, status.game_prefix)
    changes = _external_asset_changes(game, baseline, proposed)
    applied = _sync_external_assets(
        status.repo_root, game, source, changes, proposed
    )
    _save_asset_manifest(
        status.repo_root,
        status.game_prefix,
        result.version,
        result.original_commit,
        proposed,
    )
    _clear_pending_asset_plan(status.repo_root, status.game_prefix)
    return UpdateResult(
        repo_root=result.repo_root,
        original_commit=result.original_commit,
        translation_commit=result.translation_commit,
        version=result.version,
        official_won_paths=result.official_won_paths,
        pending_conflicts=result.pending_conflicts,
        content_changed=result.content_changed or bool(applied),
        already_present_paths=result.already_present_paths,
        external_changes=changes,
    )


def apply_official_update(
    translated_game: str | Path,
    new_official_game: str | Path,
    version: str,
    *,
    auto_resolve: bool = True,
    expected_tree: str | None = None,
    expected_original_commit: str | None = None,
    expected_translation_commit: str | None = None,
    expected_asset_manifest: str | None = None,
    previous_official_game: str | Path | None = None,
    expected_baseline_asset_manifest: str | None = None,
) -> UpdateResult:
    game = Path(translated_game).expanduser().resolve()
    version = _validate_version(version)
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Register both branches before applying an update")
    if status.current_branch != status.translation_branch:
        raise GitWorkflowError(
            f"Switch to the translated branch {status.translation_branch!r} before updating"
        )
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before updating")
    if expected_original_commit and status.original_commit != expected_original_commit:
        raise GitWorkflowError(
            "The original branch changed after preview. Run the preview again before applying."
        )
    if expected_translation_commit and status.translation_commit != expected_translation_commit:
        raise GitWorkflowError(
            "The translated branch changed after preview. Run the preview again before applying."
        )
    official = _validate_source(new_official_game, game)
    repo = status.repo_root
    _reject_original_checked_out_elsewhere(repo)
    new_tree = _write_tree_from_folder(
        repo,
        official,
        game_prefix=status.game_prefix,
        base_commit=status.original_commit,
    )
    new_tree = _preserve_tool_owned_paths(
        repo,
        new_tree,
        status.original_commit,
        status.game_prefix,
    )
    if previous_official_game is None:
        new_tree, _preserved_translation_assets = (
            _preserve_unbased_translation_assets(
                repo,
                new_tree,
                status.original_commit,
                status.translation_commit,
                status.game_prefix,
            )
        )
    proposed_assets = _build_ignored_asset_manifest(
        official, new_tree.ignored_paths
    )
    proposed_asset_digest = _manifest_digest(proposed_assets)
    baseline_assets = _load_asset_manifest(repo, status.game_prefix)
    baseline_was_missing = baseline_assets is None
    registered_tree = _run_git(
        repo, "rev-parse", f"{status.original_commit}^{{tree}}"
    ).stdout.strip()
    baseline_tree = registered_tree
    if baseline_assets is None:
        if previous_official_game is not None:
            _baseline_source, baseline_assets, baseline_tree = (
                _validate_official_asset_baseline(
                    repo,
                    game,
                    previous_official_game,
                    status.game_prefix,
                    status.original_commit,
                )
            )
        else:
            baseline_assets = _asset_manifest_for_source(
                repo,
                game,
                status.game_prefix,
            )
    baseline_asset_digest = _manifest_digest(baseline_assets)
    if expected_tree is not None and new_tree.tree != expected_tree:
        raise GitWorkflowError(
            "The official folder changed after preview. Run the preview again before applying."
        )
    if (
        expected_asset_manifest is not None
        and proposed_asset_digest != expected_asset_manifest
    ):
        raise GitWorkflowError(
            "The official assets changed after preview. Run the preview again before applying."
        )
    if (
        expected_baseline_asset_manifest is not None
        and baseline_asset_digest != expected_baseline_asset_manifest
    ):
        raise GitWorkflowError(
            "The previous official assets changed after preview. Run the preview again "
            "before applying."
        )
    baseline_parent = status.original_commit
    if baseline_tree != registered_tree:
        baseline_version = status.original_version or "unknown"
        baseline_parent = _commit_tree(
            repo,
            baseline_tree,
            _message(
                f"original: normalize legacy baseline {baseline_version}",
                baseline_version,
            ),
            (status.original_commit,),
        )
    if new_tree.tree == baseline_tree:
        if status.original_version == version:
            raise GitWorkflowError("That official game version is already registered")
        subject = f"patch: record original game version {version}"
    else:
        subject = f"patch: update original game files to {version}"
    original_commit = _commit_tree(
        repo,
        new_tree.tree,
        _message(subject, version),
        (baseline_parent,),
    )
    if baseline_was_missing:
        _save_asset_manifest(
            repo,
            status.game_prefix,
            status.original_version or "unknown",
            baseline_parent,
            baseline_assets,
        )
    _save_pending_asset_plan(
        repo,
        status.game_prefix,
        official,
        version,
        original_commit,
        proposed_asset_digest,
    )
    try:
        _run_git(
            repo,
            "update-ref",
            f"refs/heads/{ORIGINAL_BRANCH}",
            original_commit,
            status.original_commit,
        )
    except Exception:
        _clear_pending_asset_plan(repo, status.game_prefix)
        raise
    result = _cherry_pick(game, original_commit, version, auto_resolve=auto_resolve)
    return _complete_pending_asset_plan(game, result) if result.complete else result


def apply_registered_original(
    translated_game: str | Path, *, auto_resolve: bool = True
) -> UpdateResult:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.original_commit or not status.original_version:
        raise GitWorkflowError("The original branch has no recorded version to apply")
    if status.current_branch != status.translation_branch:
        raise GitWorkflowError(
            f"Switch to the translated branch {status.translation_branch!r} before updating"
        )
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before updating")
    if status.translation_version == status.original_version:
        if not status.asset_sync_pending:
            raise GitWorkflowError("The translated branch already has this original version")
        result = UpdateResult(
            status.repo_root,
            status.original_commit,
            status.translation_commit,
            status.original_version,
            content_changed=False,
        )
        return _complete_pending_asset_plan(game, result)
    result = _cherry_pick(
        game,
        status.original_commit,
        status.original_version,
        auto_resolve=auto_resolve,
    )
    return _complete_pending_asset_plan(game, result) if result.complete else result


def continue_with_official(translated_game: str | Path) -> UpdateResult:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.pending_cherry_pick:
        raise GitWorkflowError("There is no pending cherry-pick to continue")
    original_commit = _run_git(
        status.repo_root, "rev-parse", "CHERRY_PICK_HEAD"
    ).stdout.strip()
    version = _version_from_history(status.repo_root, original_commit, original_commit) or "unknown"
    won = _resolve_conflicts_with_official(status.repo_root, status.game_prefix)
    translated_commit = _finish_cherry_pick(status.repo_root, original_commit)
    result = UpdateResult(
        status.repo_root, original_commit, translated_commit, version, won
    )
    return _complete_pending_asset_plan(game, result)


def abort_update(translated_game: str | Path) -> RepositoryStatus:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.pending_cherry_pick:
        raise GitWorkflowError("There is no pending cherry-pick to abort")
    _run_git(status.repo_root, "cherry-pick", "--abort")
    return inspect_repository(game)
