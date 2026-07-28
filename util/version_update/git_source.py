"""Read an old official game tree from Git without changing the worktree."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


class GitSourceError(RuntimeError):
    """Raised when a Git branch cannot be used as an official source."""


@dataclass(frozen=True)
class GitOriginalSource:
    repo_root: Path
    game_prefix: str
    ref_name: str
    commit: str

    @property
    def short_commit(self) -> str:
        return self.commit[:10]

    @property
    def label(self) -> str:
        return f"Git {self.ref_name} ({self.short_commit})"


class TemporaryGitExport:
    """Lifetime handle for an exported branch tree."""

    def __init__(self):
        self.root: Path | None = Path(
            tempfile.mkdtemp(prefix="dazedtl-version-update-git-")
        )

    def cleanup(self) -> None:
        root, self.root = self.root, None
        if root is not None:
            shutil.rmtree(root, ignore_errors=True)

    def __del__(self):
        self.cleanup()


def _git(
    cwd: Path,
    *args: str,
    check: bool = True,
    timeout: int = 15,
) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *args],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GitSourceError(f"Could not inspect Git repository: {exc}") from exc
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "unknown Git error"
        raise GitSourceError(detail)
    return result


def discover_original_source(game_root: str | Path) -> GitOriginalSource | None:
    """Find an ``original`` ref containing the selected game folder."""
    game = Path(game_root).expanduser().resolve()
    if not game.is_dir():
        return None
    repo_result = _git(game, "rev-parse", "--show-toplevel", check=False)
    if repo_result.returncode != 0:
        return None
    repo = Path(repo_result.stdout.strip()).resolve()
    try:
        relative = game.relative_to(repo)
    except ValueError:
        return None
    prefix = "" if relative == Path(".") else relative.as_posix()

    candidates = (
        ("original", "refs/heads/original"),
        ("origin/original", "refs/remotes/origin/original"),
    )
    for display_name, full_ref in candidates:
        commit_result = _git(
            repo,
            "rev-parse",
            "--verify",
            "--quiet",
            f"{full_ref}^{{commit}}",
            check=False,
        )
        if commit_result.returncode != 0:
            continue
        commit = commit_result.stdout.strip()
        object_name = f"{commit}:" if not prefix else f"{commit}:{prefix}"
        type_result = _git(repo, "cat-file", "-t", object_name, check=False)
        if type_result.returncode == 0 and type_result.stdout.strip() == "tree":
            return GitOriginalSource(repo, prefix, display_name, commit)
    return None


def _safe_archive_target(export_root: Path, member_name: str) -> Path:
    pure = PurePosixPath(member_name)
    if pure.is_absolute() or not pure.parts or ".." in pure.parts:
        raise GitSourceError(f"Git archive contains an unsafe path: {member_name!r}")
    target = export_root.joinpath(*pure.parts)
    try:
        target.resolve(strict=False).relative_to(export_root.resolve())
    except ValueError as exc:
        raise GitSourceError(
            f"Git archive path escapes the temporary source: {member_name!r}"
        ) from exc
    return target


def _reject_gitlinks(source: GitOriginalSource) -> None:
    args = ["ls-tree", "-r", source.commit]
    if source.game_prefix:
        args.extend(["--", source.game_prefix])
    result = _git(source.repo_root, *args)
    for line in result.stdout.splitlines():
        if line.startswith("160000 "):
            raise GitSourceError(
                "The original branch contains a Git submodule inside the game folder. "
                "Select an exported old official folder instead."
            )


def _reject_lfs_pointers(game_root: Path) -> None:
    signature = b"version https://git-lfs.github.com/spec/v1"
    for path in game_root.rglob("*"):
        if path.is_file():
            try:
                with path.open("rb") as handle:
                    head = handle.read(len(signature))
            except OSError as exc:
                raise GitSourceError(f"Could not inspect exported Git file {path}: {exc}") from exc
            if head == signature:
                relative = path.relative_to(game_root).as_posix()
                raise GitSourceError(
                    "The original branch contains unresolved Git LFS pointers "
                    f"({relative}). Select a materialized old official folder instead."
                )


def export_original_source(
    source: GitOriginalSource,
) -> tuple[Path, TemporaryGitExport]:
    """Export a Git tree to temporary storage and return its game root."""
    _reject_gitlinks(source)
    temporary = TemporaryGitExport()
    if temporary.root is None:
        raise GitSourceError("Could not allocate temporary storage for Git original")
    export_root = temporary.root / "tree"
    export_root.mkdir()
    args = [
        "git",
        "-C",
        str(source.repo_root),
        "archive",
        "--format=tar",
        source.commit,
    ]
    if source.game_prefix:
        args.extend(["--", source.game_prefix])
    try:
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        temporary.cleanup()
        raise GitSourceError(f"Could not export Git original branch: {exc}") from exc

    try:
        stdout = process.stdout
        stderr_stream = process.stderr
        if stdout is None:
            raise GitSourceError("Git archive did not provide an output stream")
        with tarfile.open(fileobj=stdout, mode="r|") as archive:
            for member in archive:
                target = _safe_archive_target(export_root, member.name)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    source_file = archive.extractfile(member)
                    if source_file is None:
                        raise GitSourceError(
                            f"Could not read Git archive member: {member.name}"
                        )
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source_file, target.open("wb") as output:
                        shutil.copyfileobj(source_file, output)
                    target.chmod(member.mode & 0o777)
                else:
                    raise GitSourceError(
                        "Git original contains a symbolic link or unsupported entry: "
                        f"{member.name}"
                    )
        stderr = stderr_stream.read() if stderr_stream is not None else b""
        return_code = process.wait(timeout=30)
        stdout.close()
        if stderr_stream is not None:
            stderr_stream.close()
        if return_code != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            raise GitSourceError(detail or "Git archive failed")

        game_root = export_root
        if source.game_prefix:
            game_root = export_root.joinpath(*PurePosixPath(source.game_prefix).parts)
        if not game_root.is_dir():
            raise GitSourceError(
                f"Git {source.ref_name} does not contain the selected game folder"
            )
        _reject_lfs_pointers(game_root)
        return game_root, temporary
    except Exception:
        if process.poll() is None:
            process.kill()
        process.wait()
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        temporary.cleanup()
        raise
