"""Download / update Forge plugins from len's upstream repo (gitgud.io).

Upstream: https://gitgud.io/zero64801/forge-mvmz
Offline copies: util/forge/upstream/
Active plugins: util/forge/Forge_MZ.js, util/forge/Forge_MV.js
"""

from __future__ import annotations

import json
import shutil
import sys
import urllib.parse
import urllib.request
from pathlib import Path

_PKG_ROOT = Path(__file__).resolve().parent
UPSTREAM_DIR = _PKG_ROOT / "upstream"

PLUGIN_BY_ENGINE = {
    "MV": "Forge_MV",
    "MZ": "Forge_MZ",
}

FORGE_PROJECT = "zero64801/forge-mvmz"
FORGE_BRANCH = "master"
GITGUD_API = "https://gitgud.io/api/v4"
VERSION_FILE = _PKG_ROOT / ".forge_version.json"
USER_AGENT = "DazedMTLTool"


def bundled_plugin_path(engine: str) -> Path:
    name = PLUGIN_BY_ENGINE.get(engine)
    if not name:
        raise ValueError(f"Unsupported engine: {engine}")
    return _PKG_ROOT / f"{name}.js"


def upstream_plugin_path(engine: str) -> Path:
    return UPSTREAM_DIR / f"{PLUGIN_BY_ENGINE[engine]}.js"


def _load_versions() -> dict:
    if not VERSION_FILE.is_file():
        return {}
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_versions(data: dict) -> None:
    VERSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _api_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)


def _project_id() -> str:
    return urllib.parse.quote(FORGE_PROJECT, safe="")


def _upstream_commit() -> str:
    url = f"{GITGUD_API}/projects/{_project_id()}/repository/commits/{FORGE_BRANCH}"
    data = _api_json(url)
    commit = data.get("id") or data.get("sha") or ""
    if not commit:
        raise RuntimeError(f"Could not resolve upstream commit for {FORGE_PROJECT}")
    return commit


def _raw_file_url(filename: str) -> str:
    enc = urllib.parse.quote(filename, safe="")
    return (
        f"{GITGUD_API}/projects/{_project_id()}/repository/files/{enc}/raw"
        f"?ref={FORGE_BRANCH}"
    )


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)


def _seed_from_offline(engine: str, log_fn) -> bool:
    """Copy bundled offline copy into the active plugin path if missing."""
    dest = bundled_plugin_path(engine)
    if dest.is_file():
        return True
    offline = upstream_plugin_path(engine)
    if not offline.is_file():
        return False
    shutil.copy2(offline, dest)
    _log(f"Using offline bundled {dest.name}", log_fn)
    return True


def _fetch_plugin(engine: str, log_fn) -> None:
    name = PLUGIN_BY_ENGINE[engine]
    _log(f"Downloading {name}.js from {FORGE_PROJECT}...", log_fn)
    data = _download_bytes(_raw_file_url(f"{name}.js"))
    bundled_plugin_path(engine).write_bytes(data)
    UPSTREAM_DIR.mkdir(parents=True, exist_ok=True)
    upstream_plugin_path(engine).write_bytes(data)


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def refresh_forge_plugins(log_fn=print) -> bool:
    """Download len's latest Forge_MV.js and Forge_MZ.js."""
    try:
        commit = _upstream_commit()
    except Exception as exc:
        _log(f"ERROR: could not contact upstream ({exc})", log_fn)
        return False

    ok = True
    for engine in PLUGIN_BY_ENGINE:
        try:
            _fetch_plugin(engine, log_fn)
        except Exception as exc:
            _log(f"ERROR: download failed for {PLUGIN_BY_ENGINE[engine]} ({exc})", log_fn)
            ok = False

    if not ok:
        return False

    versions = _load_versions()
    versions["commit"] = commit
    versions["branch"] = FORGE_BRANCH
    _save_versions(versions)
    _log(f"Forge plugins updated ({commit[:12]})", log_fn)
    return True


def ensure_forge_plugins(force: bool = False, log_fn=print) -> bool:
    """Ensure Forge plugins are present; fetch upstream when missing or stale."""
    for engine in PLUGIN_BY_ENGINE:
        _seed_from_offline(engine, log_fn)

    missing = [e for e in PLUGIN_BY_ENGINE if not bundled_plugin_path(e).is_file()]
    versions = _load_versions()
    local_commit = versions.get("commit", "")

    need_fetch = bool(missing) or force
    if not need_fetch:
        try:
            need_fetch = _upstream_commit() != local_commit
        except Exception as exc:
            if missing:
                _log(f"ERROR: Forge upstream unavailable ({exc})", log_fn)
                return False
            _log(f"Warning: could not check Forge update ({exc}); using local copy.", log_fn)

    if need_fetch:
        if refresh_forge_plugins(log_fn=log_fn):
            return True
        return all(bundled_plugin_path(e).is_file() for e in PLUGIN_BY_ENGINE)

    return True


def main() -> int:
    if "--refresh-offline" in sys.argv:
        UPSTREAM_DIR.mkdir(parents=True, exist_ok=True)
        ok = refresh_forge_plugins()
        return 0 if ok else 1
    force = "--force" in sys.argv or "-f" in sys.argv
    return 0 if ensure_forge_plugins(force=force) else 1


if __name__ == "__main__":
    raise SystemExit(main())
