"""Build WolfDawn ``wolf`` binaries from upstream source (temporary shallow clone)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

from util.wolfdawn import (
    WolfDawnError,
    _DOWNLOAD_UA,
    _GITGUD_HOST,
    bundled_binary_path,
)

WOLFDAWN_PROJECT = "zero64801/wolfdawn"
WOLFDAWN_BRANCH = "master"
GITGUD_API = "https://gitgud.io/api/v4"
CLONE_URL = f"{_GITGUD_HOST}/{WOLFDAWN_PROJECT}.git"

_BUILD_TARGETS: dict[str, dict[str, str | None]] = {
    "linux": {"triple": None, "exe": "wolf"},
    "windows": {"triple": "x86_64-pc-windows-gnu", "exe": "wolf.exe"},
}


def _platform_dir() -> str:
    import sys

    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)


def _project_id() -> str:
    return urllib.parse.quote(WOLFDAWN_PROJECT, safe="")


def upstream_commit() -> str:
    url = f"{GITGUD_API}/projects/{_project_id()}/repository/commits/{WOLFDAWN_BRANCH}"
    req = urllib.request.Request(url, headers={"User-Agent": _DOWNLOAD_UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    commit = data.get("id") or data.get("sha") or ""
    if not commit:
        raise RuntimeError(f"Could not resolve upstream commit for {WOLFDAWN_PROJECT}")
    return commit


def _cargo_available() -> bool:
    return shutil.which("cargo") is not None


def _git_available() -> bool:
    return shutil.which("git") is not None


def _mingw_linker_available() -> bool:
    return bool(shutil.which("x86_64-w64-mingw32-gcc"))


def buildable_from_source(platform: str) -> bool:
    """Return True when ``platform`` can plausibly be built on this machine."""
    if not _cargo_available():
        return False
    host = _platform_dir()
    if platform == host:
        return True
    if platform == "windows" and host == "linux":
        return _mingw_linker_available()
    return False


def _run(cmd: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None, log_fn=None) -> bool:
    _log(f"$ {' '.join(cmd)}", log_fn)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        _log(f"ERROR: {exc}", log_fn)
        return False
    if proc.stdout.strip():
        for line in proc.stdout.strip().splitlines()[-8:]:
            _log(line, log_fn)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if err:
            for line in err.splitlines()[-8:]:
                _log(line, log_fn)
        return False
    return True


def _ensure_rust_target(triple: str | None, log_fn) -> bool:
    if not triple:
        return True
    return _run(["rustup", "target", "add", triple], log_fn=log_fn)


def clone_source(dest: Path, log_fn=print) -> bool:
    """Shallow-clone WolfDawn ``master`` into ``dest``."""
    if not _git_available():
        _log("ERROR: git not found; cannot clone WolfDawn source.", log_fn)
        return False
    if dest.exists():
        shutil.rmtree(dest)
    return _run(
        ["git", "clone", "--depth", "1", "--branch", WOLFDAWN_BRANCH, CLONE_URL, str(dest)],
        log_fn=log_fn,
    )


def _artifact_path(source_dir: Path, platform: str) -> Path:
    spec = _BUILD_TARGETS[platform]
    triple = spec["triple"]
    exe = spec["exe"]
    if triple:
        return source_dir / "target" / triple / "release" / exe
    return source_dir / "target" / "release" / exe


def build_platform(source_dir: Path, platform: str, log_fn=print) -> Path | None:
    """Compile ``wolf`` for ``platform`` inside an existing source checkout."""
    if platform not in _BUILD_TARGETS:
        _log(f"ERROR: unsupported WolfDawn build platform '{platform}'.", log_fn)
        return None
    if not buildable_from_source(platform):
        _log(f"Skipping source build for '{platform}' on this machine.", log_fn)
        return None

    spec = _BUILD_TARGETS[platform]
    triple = spec["triple"]
    if not _ensure_rust_target(triple, log_fn):
        return None

    cmd = ["cargo", "build", "--release", "-p", "wolf-cli"]
    if triple:
        cmd += ["--target", triple]
    target_dir = source_dir / "target"
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(target_dir)
    if not _run(cmd, cwd=source_dir, env=env, log_fn=log_fn):
        return None

    built = _artifact_path(source_dir, platform)
    if not built.is_file():
        _log(f"ERROR: expected build output missing: {built}", log_fn)
        return None
    return built


def install_built_binary(artifact: Path, platform: str, log_fn=print) -> Path:
    """Copy a built ``wolf`` executable into the bundled offline path."""
    dest = bundled_binary_path(platform)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(artifact, dest)
    try:
        dest.chmod(0o755)
    except OSError:
        pass
    _log(f"Installed source-built WolfDawn binary at {dest}", log_fn)
    return dest


def build_and_install_platform(source_dir: Path, platform: str, log_fn=print) -> bool:
    artifact = build_platform(source_dir, platform, log_fn=log_fn)
    if artifact is None:
        return False
    install_built_binary(artifact, platform, log_fn=log_fn)
    return True


def build_and_install_platforms(
    platforms: tuple[str, ...] = ("linux", "windows"),
    log_fn=print,
) -> dict[str, bool]:
    """Clone upstream source to a temp dir, build each platform, install successes."""
    results = {platform: False for platform in platforms}
    buildable = [p for p in platforms if buildable_from_source(p)]
    if not buildable:
        _log("No WolfDawn platforms can be built from source on this machine.", log_fn)
        return results
    if not _cargo_available():
        _log("cargo not found; skipping WolfDawn source builds.", log_fn)
        return results

    _log(f"Cloning WolfDawn ({WOLFDAWN_BRANCH}) for source build…", log_fn)
    with tempfile.TemporaryDirectory(prefix="wolfdawn-src-") as tmp:
        source_dir = Path(tmp) / "wolfdawn"
        if not clone_source(source_dir, log_fn=log_fn):
            return results
        for platform in buildable:
            results[platform] = build_and_install_platform(source_dir, platform, log_fn=log_fn)
    return results
