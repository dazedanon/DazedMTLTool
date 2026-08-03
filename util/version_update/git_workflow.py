"""Git-backed game version updates with exact file-tree preservation.

This module deliberately knows nothing about RPG Maker or any other engine.
Official game folders become Git trees, official releases become commits on the
``original`` branch, and those commits are cherry-picked into ``translation``.
No game file is parsed or reconstructed.
"""

from __future__ import annotations

import os
import json
import re
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping

import jsbeautifier


ORIGINAL_BRANCH = "original"
TRANSLATION_BRANCH = "translation"
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

    @property
    def ready(self) -> bool:
        return bool(
            self.repo_root
            and self.original_exists
            and self.translation_exists
            and self.current_branch == TRANSLATION_BRANCH
            and self.worktree_clean
            and not self.pending_cherry_pick
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

    @property
    def complete(self) -> bool:
        return self.translation_commit is not None and not self.pending_conflicts


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

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return self.added_paths + self.modified_paths + self.deleted_paths

    @property
    def translation_change_paths(self) -> tuple[str, ...]:
        already_present = set(self.already_present_paths)
        return tuple(path for path in self.changed_paths if path not in already_present)

    @property
    def content_change_expected(self) -> bool:
        return bool(self.translation_change_paths)


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
    translation_commit = _ref_commit(repo, TRANSLATION_BRANCH)
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
            repo, TRANSLATION_BRANCH, translation_commit
        ),
        worktree_clean=not bool(status),
        pending_cherry_pick=_cherry_pick_path(repo).exists(),
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


def _ensure_local_excludes(repo: Path) -> None:
    """Keep removed legacy updater metadata out of the exact game branches."""
    common_text = _run_git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    common = Path(common_text)
    if not common.is_absolute():
        common = repo / common
    exclude = common.resolve() / "info" / "exclude"
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


def _ensure_translation_branch(repo: Path, head: str) -> None:
    translation = _ref_commit(repo, TRANSLATION_BRANCH)
    current = _run_git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False)
    current_name = current.stdout.strip()
    if translation and current_name != TRANSLATION_BRANCH:
        raise GitWorkflowError(
            "The translation branch exists but is not checked out. Switch to translation first."
        )
    if not translation:
        _run_git(repo, "update-ref", f"refs/heads/{TRANSLATION_BRANCH}", head)
        _run_git(repo, "symbolic-ref", "HEAD", f"refs/heads/{TRANSLATION_BRANCH}")


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
        gitignore_installed = _install_gameupdate_gitignore(translated)
        _ensure_translation_branch(repo, head_commit)
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
        f"refs/heads/{TRANSLATION_BRANCH}",
        translation_commit,
    )
    _run_git(repo, "symbolic-ref", "HEAD", f"refs/heads/{TRANSLATION_BRANCH}")
    _run_git(repo, "read-tree", translation_commit)
    if _run_git(repo, "status", "--porcelain=v1", "-z").stdout:
        raise GitWorkflowError(
            "Git baseline was created, but the translated worktree does not match it"
        )
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
    translated_game: str | Path, version: str | None = None
) -> BootstrapResult:
    """Attach a clean current translated tree to an existing original branch."""
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit:
        raise GitWorkflowError("The original branch must exist first")
    if status.translation_exists:
        raise GitWorkflowError("The translation branch already exists")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before reconciliation")
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
        f"refs/heads/{TRANSLATION_BRANCH}",
        translation_commit,
    )
    _run_git(
        status.repo_root,
        "symbolic-ref",
        "HEAD",
        f"refs/heads/{TRANSLATION_BRANCH}",
    )
    _run_git(status.repo_root, "read-tree", translation_commit)
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


def checkout_translation_branch(translated_game: str | Path) -> RepositoryStatus:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.translation_exists:
        raise GitWorkflowError("The translation branch does not exist")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current changes before switching branches")
    _run_git(status.repo_root, "checkout", TRANSLATION_BRANCH)
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
        f"refs/heads/{TRANSLATION_BRANCH}",
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
        raise GitWorkflowError("The translation branch has no commit to update")
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


def _display_path(path: str, game_prefix: str) -> str:
    prefix = f"{game_prefix}/" if game_prefix else ""
    return path[len(prefix) :] if prefix and path.startswith(prefix) else path


def preview_official_update(
    translated_game: str | Path,
    new_official_game: str | Path,
    version: str,
) -> UpdatePreview:
    """Build a non-ref preview of the normalized official release tree."""
    game = Path(translated_game).expanduser().resolve()
    version = _validate_version(version)
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit or not status.translation_commit:
        raise GitWorkflowError("Register both branches before previewing an update")
    if status.current_branch != TRANSLATION_BRANCH:
        raise GitWorkflowError("Switch to the translation branch before previewing")
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
    official_changes = _diff_status(
        status.repo_root, status.original_commit, build.tree, status.game_prefix
    )
    translation_changes = _diff_status(
        status.repo_root,
        status.original_commit,
        status.translation_commit,
        status.game_prefix,
    )
    overlap = sorted(set(official_changes) & set(translation_changes))
    already_present = tuple(
        sorted(
            path
            for path in official_changes
            if _tree_entry(status.repo_root, build.tree, path)
            == _tree_entry(status.repo_root, status.translation_commit, path)
        )
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
) -> UpdateResult:
    game = Path(translated_game).expanduser().resolve()
    version = _validate_version(version)
    status = inspect_repository(game)
    if not status.repo_root or not status.original_commit:
        raise GitWorkflowError("Register the original game before applying an update")
    if status.current_branch != TRANSLATION_BRANCH:
        raise GitWorkflowError("Switch to the translation branch before updating")
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
            "The translation branch changed after preview. Run the preview again before applying."
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
    if expected_tree is not None and new_tree.tree != expected_tree:
        raise GitWorkflowError(
            "The official folder changed after preview. Run the preview again before applying."
        )
    old_tree = _run_git(
        repo, "rev-parse", f"{status.original_commit}^{{tree}}"
    ).stdout.strip()
    if new_tree.tree == old_tree:
        if status.original_version == version:
            raise GitWorkflowError("That official game version is already registered")
        subject = f"patch: record original game version {version}"
    else:
        subject = f"patch: update original game files to {version}"
    original_commit = _commit_tree(
        repo,
        new_tree.tree,
        _message(subject, version),
        (status.original_commit,),
    )
    _run_git(
        repo,
        "update-ref",
        f"refs/heads/{ORIGINAL_BRANCH}",
        original_commit,
        status.original_commit,
    )
    return _cherry_pick(game, original_commit, version, auto_resolve=auto_resolve)


def apply_registered_original(
    translated_game: str | Path, *, auto_resolve: bool = True
) -> UpdateResult:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.original_commit or not status.original_version:
        raise GitWorkflowError("The original branch has no recorded version to apply")
    if status.current_branch != TRANSLATION_BRANCH:
        raise GitWorkflowError("Switch to the translation branch before updating")
    if status.pending_cherry_pick:
        raise GitWorkflowError("Finish or abort the pending cherry-pick first")
    if not status.worktree_clean:
        raise GitWorkflowError("Commit current translation changes before updating")
    if status.translation_version == status.original_version:
        raise GitWorkflowError("The translation branch already has this original version")
    return _cherry_pick(
        game,
        status.original_commit,
        status.original_version,
        auto_resolve=auto_resolve,
    )


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
    return UpdateResult(
        status.repo_root, original_commit, translated_commit, version, won
    )


def abort_update(translated_game: str | Path) -> RepositoryStatus:
    game = Path(translated_game).expanduser().resolve()
    status = inspect_repository(game)
    if not status.repo_root or not status.pending_cherry_pick:
        raise GitWorkflowError("There is no pending cherry-pick to abort")
    _run_git(status.repo_root, "cherry-pick", "--abort")
    return inspect_repository(game)
