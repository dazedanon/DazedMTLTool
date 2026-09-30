"""Qt-free source update protocol, including the legacy archive protections."""
from __future__ import annotations
import json
import ntpath
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from util.paths import APP_NAME, PROJECT_ROOT, LAST_UPDATE_SHA_PATH
from util.signals import TaskSignal

@dataclass(frozen=True)
class UpdateSource:
    """One public mirror capable of resolving and downloading a tool build."""

    name: str
    branch_url: str
    archive_url: str
    sha_path: tuple[str, ...]


class UpdateCandidate(str):
    """A commit SHA paired with the mirror that resolved it."""

    source: UpdateSource

    def __new__(cls, sha: str, source: UpdateSource):
        value = str.__new__(cls, sha)
        value.source = source
        return value


class SourceUpdater:
    """Downloads and applies a tool update from the first healthy mirror."""

    REPO_HOST = "https://git.dazedtl.dev"
    REPO_OWNER = "dazed"
    REPO_SLUG = "dazed-mtl-tool"
    REPO_BRANCH = "main"
    UPDATE_SOURCES = (
        UpdateSource(
            "GitHub",
            "https://api.github.com/repos/dazedanon/DazedMTLTool/branches/{branch}",
            "https://github.com/dazedanon/DazedMTLTool/archive/{sha}.zip",
            ("commit", "sha"),
        ),
        UpdateSource(
            "GitGud",
            "https://gitgud.io/api/v4/projects/DazedAnon%2FDazedMTLTool/repository/branches/{branch}",
            "https://gitgud.io/DazedAnon/DazedMTLTool/-/archive/{sha}/DazedMTLTool-{sha}.zip",
            ("commit", "id"),
        ),
        UpdateSource(
            "git.dazedtl.dev",
            "https://git.dazedtl.dev/api/v1/repos/dazed/DazedTL/branches/{branch}",
            "https://git.dazedtl.dev/dazed/DazedTL/archive/{sha}.zip",
            ("commit", "id"),
        ),
    )
    # Gitea names the archive top folder after the repo display name (currently
    # "dazedtl"). Resolve dynamically so a rename cannot silently no-op again.
    ARCHIVE_ROOT = "dazedtl"
    SHA_FILE = str(LAST_UPDATE_SHA_PATH)
    ARCHIVE_SHA_FILE = str(PROJECT_ROOT / ".git_archival.txt")

    # Top-level paths that should never be touched during update
    PROTECTED_TOP = {
        ".agents",
        ".codex",
        ".cursor",
        ".env",
        ".git",
        ".venv",
        ".tmp-ui",
        ".github",
        ".vscode",
        "venv",
        "log",
        "files",
        "translated",
        "fonts",
    }

    # User-local files under data/ that must not be overwritten.
    # Shipped defaults (translation_contexts.json, skills/*.md, help/*, glossary_base.txt, …)
    # are intentionally updated so tool releases refresh prompts, Guide docs, and contexts.
    PROTECTED_DATA_FILES = frozenset({
        "data/vocab.txt",
        "data/last_update_sha.txt",
        "data/wolf_speakers.json",
        "data/wolf_safe_notes.json",
        "data/api_keys.json",
    })

    # GitLab zip archives do not preserve Unix execute bits; restore after apply.
    EXECUTABLE_SUFFIXES = {".sh", ".desktop", ".command"}


    STAGES = ("Downloading", "Extracting", "Applying")

    def __init__(self, parent=None, candidate: UpdateCandidate | None = None):
        self.progress = TaskSignal()
        self.finished = TaskSignal()
        self._candidate = candidate

    @classmethod
    def should_install(cls, rel: Path) -> bool:
        """Return True when *rel* (path relative to archive root) may be copied."""
        parts = rel.parts
        if not parts:
            return False
        if parts[0] in cls.PROTECTED_TOP:
            return False
        if parts[0].startswith('.env') and parts[0] != '.env.example':
            return False
        if any(part in {'node_modules', '__pycache__', '.venv', 'venv'} for part in parts):
            return False
        if parts[:2] in {('data', 'models'), ('data', 'libs'), ('desktop', 'out'), ('desktop', 'test-results')}:
            return False
        if rel.as_posix() in cls.PROTECTED_DATA_FILES:
            return False
        return True

    @classmethod
    def should_install_to_root(cls, rel: Path, root: Path) -> bool:
        """Return True when *rel* may be copied into the selected install root.

        Git expands ``.git_archival.txt`` while creating a source archive. Keep
        that expanded file in archive-only installs, but do not copy it back
        into a live checkout where it would dirty the worktree on every update.
        """
        if not cls.should_install(rel):
            return False
        if rel.as_posix() == ".git_archival.txt" and (root / ".git").exists():
            return False
        return True

    @classmethod
    def resolve_archive_root(cls, extract_dir: Path) -> Path:
        """Locate the single top-level folder inside an extracted archive.

        Prefers ``ARCHIVE_ROOT`` when present; otherwise accepts exactly one
        subdirectory (Gitea zip layout). Raises if the layout is unexpected.
        """
        preferred = extract_dir / cls.ARCHIVE_ROOT
        if preferred.is_dir():
            return preferred
        dirs = sorted(p for p in extract_dir.iterdir() if p.is_dir())
        if len(dirs) == 1:
            return dirs[0]
        found = [p.name for p in dirs]
        raise FileNotFoundError(
            f"Could not find update archive root under {extract_dir} "
            f"(expected {cls.ARCHIVE_ROOT!r}; found {found})"
        )

    @staticmethod
    def _fmt_bytes(num: int) -> str:
        if num >= 1024 * 1024:
            return f"{num / (1024 * 1024):.1f} MB"
        if num >= 1024:
            return f"{num / 1024:.0f} KB"
        return f"{num} B"

    # ------------------------------------------------------------------ #

    def run(self):
        try:
            latest_sha = self._candidate or self._fetch_latest_sha()
            current_sha = self._read_stored_sha()

            if latest_sha == current_sha:
                self.finished.emit(True, "already_up_to_date")
                return

            self._download_and_apply(latest_sha)

        except Exception as exc:
            self.finished.emit(False, str(exc))

    @classmethod
    def branch_api_url(cls, source: UpdateSource | None = None) -> str:
        source = source or cls.UPDATE_SOURCES[0]
        return source.branch_url.format(branch=cls.REPO_BRANCH)

    @classmethod
    def archive_zip_url(
        cls,
        source: UpdateSource | None = None,
        sha: str | None = None,
    ) -> str:
        source = source or cls.UPDATE_SOURCES[0]
        return source.archive_url.format(
            branch=cls.REPO_BRANCH,
            sha=sha or cls.REPO_BRANCH,
        )

    @classmethod
    def _fetch_source_sha(cls, source: UpdateSource) -> str:
        req = urllib.request.Request(
            cls.branch_api_url(source), headers={"User-Agent": APP_NAME}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
        value = payload
        for key in source.sha_path:
            value = value[key]
        sha = str(value).strip()
        if re.fullmatch(r"[0-9a-fA-F]{40,64}", sha) is None:
            raise ValueError(f"{source.name} returned an invalid commit SHA")
        return sha.lower()

    @classmethod
    def fetch_latest_sha(cls) -> UpdateCandidate:
        errors = []
        for source in cls.UPDATE_SOURCES:
            try:
                return UpdateCandidate(cls._fetch_source_sha(source), source)
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        raise RuntimeError(
            "Could not reach any update source. " + " | ".join(errors)
        )

    @staticmethod
    def _read_archive_sha(path: Path) -> str:
        """Read an expanded git-archive commit ID, or return an empty string."""
        if not path.is_file():
            return ""
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                key, separator, value = line.partition(":")
                candidate = value.strip()
                if (
                    separator
                    and key.strip() == "node"
                    and re.fullmatch(r"[0-9a-fA-F]{40,64}", candidate)
                ):
                    return candidate
        except OSError:
            pass
        return ""

    @staticmethod
    def _read_git_sha(root: Path) -> str:
        """Read HEAD from a live checkout, or return an empty string."""
        # Do not let Git discover an unrelated repository above an extracted
        # DazedTL folder. Worktrees use a .git file, so ``exists`` covers both.
        if not (root / ".git").exists():
            return ""
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        candidate = result.stdout.strip()
        if result.returncode == 0 and re.fullmatch(
            r"[0-9a-fA-F]{40,64}", candidate
        ):
            return candidate.lower()
        return ""

    @classmethod
    def read_installed_sha(cls) -> str:
        """Return the installed SHA from runtime, archive, or Git metadata."""
        runtime_path = Path(cls.SHA_FILE)
        if runtime_path.is_file():
            try:
                runtime_sha = runtime_path.read_text(encoding="utf-8").strip()
                if runtime_sha:
                    return runtime_sha
            except OSError:
                pass
        archive_path = Path(cls.ARCHIVE_SHA_FILE)
        archive_sha = cls._read_archive_sha(archive_path)
        if archive_sha:
            return archive_sha
        return cls._read_git_sha(archive_path.parent)

    # ------------------------------------------------------------------ #

    def _fetch_latest_sha(self):
        return self.fetch_latest_sha()

    def _read_stored_sha(self):
        return self.read_installed_sha()

    @staticmethod
    def _filesystem_path(path: str | Path) -> Path:
        """Use extended Windows paths without requiring a machine-wide opt-in.

        Prefix the base before appending archive members: bundled skill paths
        plus the temporary directory and archive SHA can exceed MAX_PATH.
        """
        if sys.platform != "win32":
            return Path(path)
        absolute = ntpath.abspath(path)
        if absolute.startswith("\\\\?\\"):
            return Path(absolute)
        if absolute.startswith("\\\\"):
            absolute = "UNC\\" + absolute[2:]
        return Path("\\\\?\\" + absolute)

    def _download_archive(self, zip_path: Path, candidate: UpdateCandidate):
        start_index = self.UPDATE_SOURCES.index(candidate.source)
        errors = []
        for index, source in enumerate(self.UPDATE_SOURCES[start_index:]):
            try:
                if index and self._fetch_source_sha(source) != str(candidate):
                    raise RuntimeError(
                        "mirror has not synchronized the selected commit"
                    )
                req = urllib.request.Request(
                    self.archive_zip_url(source, str(candidate)),
                    headers={"User-Agent": APP_NAME},
                )
                with urllib.request.urlopen(req, timeout=120) as resp, open(
                    zip_path, "wb"
                ) as fh:
                    total = int(resp.headers.get("Content-Length", 0) or 0)
                    downloaded = 0
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        fh.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(70, int(downloaded * 70 / total))
                            detail = (
                                f"{source.name}: {self._fmt_bytes(downloaded)} "
                                f"of {self._fmt_bytes(total)}"
                            )
                        else:
                            pct = -1
                            detail = (
                                f"{source.name}: "
                                f"{self._fmt_bytes(downloaded)} downloaded"
                            )
                        self.progress.emit("Downloading", pct, detail)
                return
            except Exception as exc:
                errors.append(f"{source.name}: {exc}")
        raise RuntimeError(
            "Could not download the selected update. " + " | ".join(errors)
        )

    def _download_and_apply(self, latest_sha):
        # Give TemporaryDirectory the extended base as well, so its cleanup
        # can remove deep extracted files after either success or failure.
        temp_base = self._filesystem_path(tempfile.gettempdir())
        with tempfile.TemporaryDirectory(dir=temp_base) as tmp_dir:
            tmp = Path(tmp_dir)
            zip_path = tmp / "update.zip"

            self.progress.emit(
                "Downloading",
                -1,
                f"Fetching archive from {latest_sha.source.name}",
            )
            self._download_archive(zip_path, latest_sha)

            self.progress.emit("Extracting", 75, "Unpacking update archive…")
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)

            extracted = self.resolve_archive_root(tmp)
            root = self._filesystem_path(PROJECT_ROOT).resolve()

            install_files = [
                src
                for src in extracted.rglob("*")
                if src.is_file()
                and self.should_install_to_root(
                    src.relative_to(extracted),
                    root,
                )
            ]
            if not install_files:
                raise RuntimeError(
                    "Update archive contained no installable files "
                    f"(root={extracted.name!r})"
                )

            total_files = len(install_files)
            self.progress.emit("Applying", 85, "Installing updated files…")
            for index, src in enumerate(install_files, start=1):
                rel = src.relative_to(extracted)
                dst = root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                if dst.suffix in self.EXECUTABLE_SUFFIXES:
                    mode = dst.stat().st_mode | 0o111
                    dst.chmod(mode)
                pct = 85 + int(index * 15 / total_files)
                self.progress.emit("Applying", min(100, pct), str(rel))

        self._filesystem_path(self.SHA_FILE).write_text(latest_sha)
        self.finished.emit(True, f"updated:{latest_sha[:8]}")


def check_tool_update():
    latest = SourceUpdater.fetch_latest_sha()
    return latest if latest != SourceUpdater.read_installed_sha() else None
