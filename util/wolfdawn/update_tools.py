"""Check for and apply WolfDawn ``wolf`` binary updates (maintainer-only upstream fetch).

End users receive prebuilt binaries under ``util/wolfdawn/bin/<platform>/`` via
DazedTL updates. Maintainers refresh them with ``--refresh-all`` or ``--force``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Sequence

from util.wolfdawn import (
    WolfDawnError,
    _latest_release_asset,
    _platform_dir,
    bundled_binary_path,
    download_wolf_binary,
)
from util.wolfdawn.build_tools import (
    build_and_install_platforms,
    upstream_commit,
)

_PKG_ROOT = Path(__file__).resolve().parent
VERSION_FILE = _PKG_ROOT / ".wolf_version.json"
BUNDLED_PLATFORMS: tuple[str, ...] = ("linux", "windows")


def _load_versions() -> dict:
    if not VERSION_FILE.is_file():
        return {}
    try:
        return json.loads(VERSION_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_versions(data: dict) -> None:
    VERSION_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _log(msg: str, log_fn) -> None:
    if log_fn:
        log_fn(msg)
    else:
        print(msg, flush=True)


def _platform_versions() -> dict[str, str]:
    versions = _load_versions()
    platforms = versions.get("platforms")
    if isinstance(platforms, dict):
        return {str(k): str(v) for k, v in platforms.items() if v}
    tag = versions.get("tag", "")
    if tag:
        return {p: str(tag) for p in BUNDLED_PLATFORMS}
    commit = versions.get("commit", "")
    if commit:
        return {p: str(commit) for p in BUNDLED_PLATFORMS}
    return {}


def _local_version(platform: str) -> str:
    return _platform_versions().get(platform, "")


def _refresh_from_release(platform: str, log_fn=print) -> str | None:
    asset = _latest_release_asset(platform)
    if not asset:
        return None
    tag, _ = asset
    try:
        download_wolf_binary(platform=platform, log_fn=log_fn)
    except WolfDawnError as exc:
        _log(f"Warning: release download failed for {platform} ({exc}).", log_fn)
        return None
    return tag


def refresh_wolfdawn_binary(
    platform: str | None = None,
    *,
    platforms: Sequence[str] | None = None,
    log_fn=print,
) -> bool:
    """Refresh WolfDawn binaries, trying source builds first."""
    targets = tuple(platforms or (platform or _platform_dir(),))
    try:
        upstream = upstream_commit()
    except Exception as exc:
        _log(f"ERROR: could not contact WolfDawn upstream ({exc})", log_fn)
        return False

    _log(f"Upstream WolfDawn commit: {upstream[:12]}", log_fn)
    source_results = build_and_install_platforms(
        tuple(p for p in targets if p in BUNDLED_PLATFORMS),
        log_fn=log_fn,
    )

    ok = True
    versions = _load_versions()
    versions["commit"] = upstream
    platform_versions = versions.setdefault("platforms", {})
    if not isinstance(platform_versions, dict):
        platform_versions = {}
        versions["platforms"] = platform_versions

    for plat in targets:
        if source_results.get(plat):
            platform_versions[plat] = upstream
            _log(f"WolfDawn updated from source ({plat}, {upstream[:12]})", log_fn)
            continue

        tag = _refresh_from_release(plat, log_fn=log_fn)
        if tag:
            platform_versions[plat] = tag
            _log(f"WolfDawn updated from release ({plat}, {tag})", log_fn)
            continue

        if bundled_binary_path(plat).is_file():
            _log(f"Keeping existing offline WolfDawn binary ({plat}).", log_fn)
            if plat not in platform_versions:
                platform_versions[plat] = _local_version(plat) or "offline"
            continue

        _log(f"ERROR: no WolfDawn binary available for '{plat}'.", log_fn)
        ok = False

    _save_versions(versions)
    return ok


def ensure_wolfdawn_binary(force: bool = False, log_fn=print) -> bool:
    """Ensure the bundled ``wolf`` binary is present (no upstream fetch by default)."""
    platform = _platform_dir()
    bundled = bundled_binary_path(platform)

    if force:
        if refresh_wolfdawn_binary(platforms=BUNDLED_PLATFORMS, log_fn=log_fn):
            return bundled_binary_path(platform).is_file()
        if bundled.is_file():
            _log("Warning: WolfDawn update failed; using bundled copy.", log_fn)
            return True
        _log("ERROR: WolfDawn update failed.", log_fn)
        return False

    if bundled.is_file():
        return True
    _log(
        f"ERROR: no bundled WolfDawn binary for '{platform}' at {bundled}. "
        "Update DazedTL to receive a prebuilt wolf binary.",
        log_fn,
    )
    return False


def main() -> int:
    if "--refresh-all" in sys.argv:
        return 0 if refresh_wolfdawn_binary(platforms=BUNDLED_PLATFORMS) else 1
    force = "--force" in sys.argv or "-f" in sys.argv
    return 0 if ensure_wolfdawn_binary(force=force) else 1


if __name__ == "__main__":
    raise SystemExit(main())
