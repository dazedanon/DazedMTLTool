"""Download / update Forge plugins from len's upstream repo (gitgud.io).

Upstream: https://gitgud.io/zero64801/forge-mvmz
CI builds a unified forge.js plugin (master branch artifacts) for MV and MZ.
The pre-rewrite MV plugin remains available as ``upstream/Forge_MV.js`` in
case the unified build needs to be rolled back.

Canonical offline copies: util/forge/upstream/

End users receive curated copies shipped with DazedTL updates.
Upstream fetches are maintainer-only (``--refresh-offline`` or ``--force``)
and refresh the unified plugin stored as ``Forge_MZ.js``.
"""

from __future__ import annotations

import json
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
USER_AGENT = "DazedTL"


def upstream_plugin_path(engine: str) -> Path:
    name = PLUGIN_BY_ENGINE.get(engine)
    if not name:
        raise ValueError(f"Unsupported engine: {engine}")
    return UPSTREAM_DIR / f"{name}.js"


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


def _project_id() -> str:
    return urllib.parse.quote(FORGE_PROJECT, safe="")


def _upstream_commit() -> str:
    url = f"{GITGUD_API}/projects/{_project_id()}/repository/commits/{FORGE_BRANCH}"
    data = _api_json(url)
    commit = data.get("id") or data.get("sha") or ""
    if not commit:
        raise RuntimeError(f"Could not resolve upstream commit for {FORGE_PROJECT}")
    return commit


def _artifact_url(filename: str) -> str:
    """Latest successful build_job artifact on the tracked branch."""
    return (
        f"https://gitgud.io/{FORGE_PROJECT}/-/jobs/artifacts/{FORGE_BRANCH}"
        f"/raw/{filename}?job=build_job"
    )


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)


def _fetch_plugins(log_fn) -> bytes:
    """Download the unified forge.js CI artifact."""
    _log(f"Downloading forge.js from {FORGE_PROJECT} ({FORGE_BRANCH} CI)...", log_fn)
    return _download_bytes(_artifact_url("forge.js"))


def _install_unified_bytes(data: bytes) -> None:
    """Write unified forge.js without overwriting the legacy MV fallback."""
    UPSTREAM_DIR.mkdir(parents=True, exist_ok=True)
    upstream_plugin_path("MZ").write_bytes(data)


def _download_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def refresh_forge_plugins(log_fn=print) -> bool:
    """Download len's latest unified forge.js for both supported engines."""
    try:
        commit = _upstream_commit()
    except Exception as exc:
        _log(f"ERROR: could not contact upstream ({exc})", log_fn)
        return False

    try:
        data = _fetch_plugins(log_fn)
    except Exception as exc:
        _log(f"ERROR: download failed for forge.js ({exc})", log_fn)
        return False

    if not data.strip().startswith(b"//"):
        _log("ERROR: forge.js download did not look like a plugin file.", log_fn)
        return False

    _install_unified_bytes(data)

    versions = _load_versions()
    versions["commit"] = commit
    versions["branch"] = FORGE_BRANCH
    _save_versions(versions)
    _log(
        f"Unified Forge plugin updated for MV and MZ ({commit[:12]}). "
        "The legacy MV plugin remains available as a fallback.",
        log_fn,
    )
    return True


def ensure_forge_plugins(force: bool = False, log_fn=print) -> bool:
    """Ensure Forge plugins are present from the offline bundle (no upstream fetch)."""
    missing = [e for e in PLUGIN_BY_ENGINE if not upstream_plugin_path(e).is_file()]
    if missing and not force:
        names = ", ".join(PLUGIN_BY_ENGINE[e] + ".js" for e in missing)
        _log(
            f"ERROR: Forge plugin(s) missing ({names}). "
            "Update DazedTL or ask the maintainer to refresh util/forge/upstream/.",
            log_fn,
        )
        return False

    if force:
        if refresh_forge_plugins(log_fn=log_fn):
            return True
        have_local = all(upstream_plugin_path(e).is_file() for e in PLUGIN_BY_ENGINE)
        if not have_local:
            _log("ERROR: Forge plugin update failed.", log_fn)
            return False
        _log("Warning: could not update Forge plugins; using local copy.", log_fn)

    return all(upstream_plugin_path(e).is_file() for e in PLUGIN_BY_ENGINE)


def main() -> int:
    if "--refresh-offline" in sys.argv:
        UPSTREAM_DIR.mkdir(parents=True, exist_ok=True)
        ok = refresh_forge_plugins()
        return 0 if ok else 1
    force = "--force" in sys.argv or "-f" in sys.argv
    return 0 if ensure_forge_plugins(force=force) else 1


if __name__ == "__main__":
    raise SystemExit(main())
