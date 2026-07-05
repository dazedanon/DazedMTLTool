"""Download / update RPG Maker Ace tools from upstream GitHub releases.

RV2JSON.exe     — https://github.com/Sinflower/RV2JSON (bin/RV2JSON.exe)
Decrypter CLI   — https://github.com/uuksu/RPGMakerDecrypter (release asset)

End users receive curated copies via the offline bundle (``util/ace/offline/``)
shipped with DazedMTLTool updates. Upstream fetches are maintainer-only
(``--refresh-offline`` or ``--force``).
"""

from __future__ import annotations

import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ACE_DIR = Path(__file__).resolve().parent
OFFLINE_DIR = ACE_DIR / "offline"
VERSION_FILE = ACE_DIR / ".tools_version.json"

RV2JSON_REPO = "Sinflower/RV2JSON"
RV2JSON_REMOTE = "bin/RV2JSON.exe"
RV2JSON_LOCAL = ACE_DIR / "RV2JSON.exe"

DECRYPTER_REPO = "uuksu/RPGMakerDecrypter"
DECRYPTER_ASSET = "RPGMakerDecrypter-cli.exe"
DECRYPTER_LOCAL = ACE_DIR / "RPGMakerDecrypter-cli.exe"
# Legacy name shipped in older DazedMTLTool commits (local only, not in git).
DECRYPTER_LEGACY = ACE_DIR / "RPGMakerDecrypter.exe"

USER_AGENT = "DazedMTLTool"


def _load_versions() -> dict:
    if not VERSION_FILE.is_file():
        return {}
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_versions(data: dict) -> None:
    ACE_DIR.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _github_json(url: str) -> dict | list:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=600) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)


def _seed_from_offline(local: Path, offline_name: str, log_fn) -> bool:
    """Copy a bundled offline exe into the active path when the bundle exists."""
    src = OFFLINE_DIR / offline_name
    if not src.is_file():
        return local.is_file()
    local.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, local)
    if log_fn:
        _log(f"Synced {offline_name} from offline bundle", log_fn)
    return True


def _rv2json_upstream() -> tuple[str, str]:
    """Return (blob_sha, download_url) for RV2JSON.exe on main."""
    url = f"https://api.github.com/repos/{RV2JSON_REPO}/contents/{RV2JSON_REMOTE}?ref=main"
    info = _github_json(url)
    sha = info.get("sha", "")
    dl = info.get("download_url") or ""
    if not sha or not dl:
        raise RuntimeError(f"Could not resolve {RV2JSON_REPO}/{RV2JSON_REMOTE}")
    return sha, dl


def _decrypter_upstream() -> tuple[str, str]:
    """Return (release_tag, browser_download_url) for the Windows CLI decrypter."""
    url = f"https://api.github.com/repos/{DECRYPTER_REPO}/releases/latest"
    release = _github_json(url)
    tag = release.get("tag_name") or release.get("name") or "latest"
    for asset in release.get("assets") or []:
        if asset.get("name") == DECRYPTER_ASSET:
            dl = asset.get("browser_download_url") or ""
            if dl:
                return tag, dl
    raise RuntimeError(f"No {DECRYPTER_ASSET} asset in latest {DECRYPTER_REPO} release")


def _fetch_rv2json_upstream(force: bool, log_fn=print) -> bool:
    """Download RV2JSON.exe from upstream (maintainer-only)."""
    versions = _load_versions()
    try:
        remote_sha, download_url = _rv2json_upstream()
    except Exception as exc:
        if RV2JSON_LOCAL.is_file():
            _log(f"Warning: Could not check RV2JSON update ({exc}); using local copy.", log_fn)
            return True
        _log(f"ERROR: RV2JSON unavailable ({exc}).", log_fn)
        return False

    local_sha = versions.get("rv2json_sha", "")
    if RV2JSON_LOCAL.is_file() and not force and local_sha == remote_sha:
        return True

    _log(f"Downloading RV2JSON.exe ({RV2JSON_REPO})...", log_fn)
    try:
        _download(download_url, RV2JSON_LOCAL)
    except Exception as exc:
        if RV2JSON_LOCAL.is_file():
            _log(f"Warning: RV2JSON update failed ({exc}); keeping existing copy.", log_fn)
            return True
        _log(f"ERROR: RV2JSON download failed: {exc}", log_fn)
        return False

    versions["rv2json_sha"] = remote_sha
    _save_versions(versions)
    _log("RV2JSON.exe ready", log_fn)
    return True


def _fetch_decrypter_upstream(force: bool, log_fn=print) -> bool:
    """Download RPGMakerDecrypter CLI from upstream (maintainer-only)."""
    if DECRYPTER_LOCAL.is_file():
        pass  # prefer CLI (offline bundle or download)
    elif DECRYPTER_LEGACY.is_file():
        _log("Using legacy RPGMakerDecrypter.exe (local).", log_fn)
        return True

    versions = _load_versions()
    try:
        tag, download_url = _decrypter_upstream()
    except Exception as exc:
        if DECRYPTER_LOCAL.is_file() or DECRYPTER_LEGACY.is_file():
            _log(f"Warning: Could not check decrypter update ({exc}); using local copy.", log_fn)
            return True
        _log(f"ERROR: Decrypter unavailable ({exc}).", log_fn)
        return False

    local_tag = versions.get("decrypter_tag", "")
    if DECRYPTER_LOCAL.is_file() and not force and local_tag == tag:
        return True

    _log(f"Downloading {DECRYPTER_ASSET} ({DECRYPTER_REPO} {tag})...", log_fn)
    try:
        _download(download_url, DECRYPTER_LOCAL)
    except Exception as exc:
        if DECRYPTER_LOCAL.is_file() or DECRYPTER_LEGACY.is_file():
            _log(f"Warning: Decrypter update failed ({exc}); keeping existing copy.", log_fn)
            return True
        _log(f"ERROR: Decrypter download failed: {exc}", log_fn)
        return False

    versions["decrypter_tag"] = tag
    _save_versions(versions)
    _log("RPG Maker decrypter CLI ready", log_fn)
    return True


def ensure_rv2json(force: bool = False, log_fn=print) -> bool:
    """Ensure RV2JSON.exe is present from the offline bundle (no upstream fetch)."""
    _seed_from_offline(RV2JSON_LOCAL, "RV2JSON.exe", log_fn)
    if force:
        return _fetch_rv2json_upstream(force=force, log_fn=log_fn)
    if RV2JSON_LOCAL.is_file():
        return True
    _log(
        f"ERROR: RV2JSON.exe not found. Update DazedMTLTool or ask the maintainer "
        f"to refresh util/ace/offline/RV2JSON.exe.",
        log_fn,
    )
    return False


def ensure_decrypter(force: bool = False, log_fn=print) -> bool:
    """Ensure the RPG Maker decrypter CLI is present from the offline bundle."""
    _seed_from_offline(DECRYPTER_LOCAL, DECRYPTER_ASSET, log_fn)
    if DECRYPTER_LOCAL.is_file():
        if not force:
            return True
    elif DECRYPTER_LEGACY.is_file() and not force:
        _log("Using legacy RPGMakerDecrypter.exe (local).", log_fn)
        return True

    if force:
        return _fetch_decrypter_upstream(force=force, log_fn=log_fn)

    if DECRYPTER_LOCAL.is_file() or DECRYPTER_LEGACY.is_file():
        return True
    _log(
        f"ERROR: {DECRYPTER_ASSET} not found. Update DazedMTLTool or ask the maintainer "
        f"to refresh util/ace/offline/{DECRYPTER_ASSET}.",
        log_fn,
    )
    return False


def seed_ace_tools(log_fn=None) -> None:
    """Sync runtime Ace tools from the offline bundle (no network)."""
    _seed_from_offline(RV2JSON_LOCAL, "RV2JSON.exe", log_fn)
    _seed_from_offline(DECRYPTER_LOCAL, DECRYPTER_ASSET, log_fn)


def ensure_ace_tools(force: bool = False, log_fn=print) -> bool:
    """Ensure both Ace tools are present (offline bundle; upstream only with force=True)."""
    ok_rv = ensure_rv2json(force=force, log_fn=log_fn)
    ok_dec = ensure_decrypter(force=force, log_fn=log_fn)
    return ok_rv and ok_dec


def ace_tool_path(name: str) -> Path:
    """Resolve a tool path under util/ace/."""
    if name == "RV2JSON.exe":
        return RV2JSON_LOCAL
    if name in ("RPGMakerDecrypter.exe", "RPGMakerDecrypter-cli.exe"):
        if DECRYPTER_LOCAL.is_file():
            return DECRYPTER_LOCAL
        if DECRYPTER_LEGACY.is_file():
            return DECRYPTER_LEGACY
        return DECRYPTER_LOCAL
    return ACE_DIR / name


def build_decrypter_command(game_root: Path) -> list[str]:
    """Build argv to decrypt Game.rgss* in game_root."""
    exe = ace_tool_path("RPGMakerDecrypter-cli.exe")
    if not exe.is_file():
        raise FileNotFoundError(
            f"No RPG Maker decrypter found in {ACE_DIR}. "
            "Run: python -m util.ace.update_tools"
        )
    rgss = sorted(game_root.glob("Game.rgss*"))
    if not rgss:
        raise FileNotFoundError(f"No Game.rgss* archive in {game_root}")
    # Legacy GUI exe ran with no args; CLI needs the archive path.
    if exe.name == DECRYPTER_LEGACY.name:
        return [str(exe)]
    return [str(exe), str(rgss[0])]


def refresh_offline_bundle(log_fn=print) -> bool:
    """Download upstream tools into util/ace/offline/ (for maintainers to commit)."""
    OFFLINE_DIR.mkdir(parents=True, exist_ok=True)
    ok = True
    try:
        _, rv_url = _rv2json_upstream()
        _log("Refreshing offline RV2JSON.exe...", log_fn)
        _download(rv_url, OFFLINE_DIR / "RV2JSON.exe")
    except Exception as exc:
        _log(f"ERROR: offline RV2JSON refresh failed: {exc}", log_fn)
        ok = False
    try:
        _, dec_url = _decrypter_upstream()
        _log(f"Refreshing offline {DECRYPTER_ASSET}...", log_fn)
        _download(dec_url, OFFLINE_DIR / DECRYPTER_ASSET)
    except Exception as exc:
        _log(f"ERROR: offline decrypter refresh failed: {exc}", log_fn)
        ok = False
    if ok:
        _log("Offline bundle refreshed in util/ace/offline/", log_fn)
    return ok


def main() -> int:
    if "--refresh-offline" in sys.argv:
        return 0 if refresh_offline_bundle() else 1
    force = "--force" in sys.argv or "-f" in sys.argv
    ok = ensure_ace_tools(force=force)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
