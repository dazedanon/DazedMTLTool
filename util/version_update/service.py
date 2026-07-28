"""Planning and staged application for translated game version updates."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable

from .baseline import (
    BaselineError,
    LoadedBaseline,
    load_baseline,
    load_baseline_fingerprint,
    save_baseline,
    save_baseline_inventory,
)
from .git_source import (
    GitSourceError,
    discover_original_source,
    export_original_source,
)
from .inventory import (
    assert_inventory_unchanged,
    classify_file,
    inventory_fingerprint,
    inventory_root,
    sha256_file,
)
from .models import (
    ApplyResult,
    ConflictResolution,
    FileKind,
    InventoryEntry,
    RecoveryStatus,
    UpdateAction,
    UpdateDecision,
    UpdatePlan,
)
from .rpgmaker import (
    count_changed_japanese_source_bytes,
    count_japanese_source_bytes,
    count_preserved_translation_bytes,
    is_plugins_manifest_path,
    is_supported_json_path,
    merge_json_bytes,
    merge_plugins_js_bytes,
)
from .text_merge import merge_text_bytes


PROFILE_AUTO = "auto"
PROFILE_GENERIC = "generic"
PROFILE_RPGMAKER_MVMZ = "rpgmaker-mvmz"
PROFILE_RPGMAKER_ACE = "rpgmaker-ace"
PROFILE_WOLF = "wolf"
MAX_RETAINED_RUNS = 8

ScanProgress = Callable[[str, int, int, str], None]
ApplyProgress = Callable[[int, int, str], None]

AUDIO_SUFFIXES = (
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
    ".rpgmvo",
    ".wav",
)
IMAGE_SUFFIXES = (
    ".avif",
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".png_",
    ".rpgmvp",
    ".webp",
)


class VersionUpdateError(RuntimeError):
    """Raised when a version update cannot be safely scanned or applied."""


def detect_update_profile(game_root: str | Path) -> tuple[str, str]:
    root = Path(game_root).expanduser().resolve()
    for data_path in (root / "www" / "data", root / "data", root / "Data"):
        if data_path.is_dir() and (
            (data_path / "System.json").is_file()
            or (data_path / "Actors.json").is_file()
            or any(data_path.glob("Map[0-9][0-9][0-9].json"))
        ):
            markers = [
                name
                for name in ("System.json", "Actors.json")
                if (data_path / name).is_file()
            ]
            if not markers:
                markers = ["MapNNN.json"]
            return (
                PROFILE_RPGMAKER_MVMZ,
                f"RPG Maker JSON data detected at {data_path} ({', '.join(markers)})",
            )
    ace_data = root / "Data"
    if ace_data.is_dir() and (
        any(ace_data.glob("*.rvdata2")) or any(ace_data.glob("*.rvdata"))
    ):
        return PROFILE_RPGMAKER_ACE, f"RPG Maker Ace data detected at {ace_data}"
    wolf_data = root / "Data"
    wolf_detected = (
        any(root.glob("*.wolf"))
        or (wolf_data.is_dir() and any(wolf_data.glob("*.wolf")))
        or (wolf_data / "BasicData" / "CommonEvent.dat").is_file()
        or (wolf_data / "CommonEvent.dat").is_file()
        or (wolf_data.is_dir() and any(wolf_data.glob("*.mps")))
        or ((wolf_data / "MapData").is_dir() and any((wolf_data / "MapData").glob("*.mps")))
    )
    if wolf_detected:
        return PROFILE_WOLF, "WOLF RPG archives or loose Data folder detected"
    return PROFILE_GENERIC, "No supported semantic engine markers found; files-only mode"


def _protected_local_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    parts_lower = tuple(part.lower() for part in path.parts)
    if any(part in {"save", "saves"} for part in parts_lower):
        return True
    name = path.name.lower()
    if name.endswith((".rpgsave", ".sav")) or (
        name.startswith("save") and name.endswith(".rvdata2")
    ):
        return True
    return relative.casefold() == "gameupdate/previous_patch_sha.txt"


def _has_suffix(relative: str, suffixes: tuple[str, ...]) -> bool:
    return relative.casefold().endswith(suffixes)


def _is_audio_path(relative: str) -> bool:
    return _has_suffix(relative, AUDIO_SUFFIXES)


def _is_image_path(relative: str) -> bool:
    return _has_suffix(relative, IMAGE_SUFFIXES)


def _marked_translated_images(current_root: Path) -> set[str]:
    """Return images explicitly managed as translation patches."""
    marked: set[str] = set()
    backup_root = current_root / ".dazedtl" / "image_backups"
    if backup_root.is_dir():
        for path in backup_root.rglob("*"):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(backup_root).as_posix()
            if _is_image_path(relative):
                marked.add(relative)

    ignore_path = current_root / ".gitignore"
    try:
        ignore_lines = ignore_path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        ignore_lines = []
    for raw in ignore_lines:
        line = raw.strip()
        if not line.startswith("!"):
            continue
        relative = line[1:].lstrip("/").replace("\\ ", " ")
        if relative.endswith("/") or any(char in relative for char in "*?["):
            continue
        if _is_image_path(relative):
            marked.add(PurePosixPath(relative).as_posix())
    return marked


def _restore_git_image_baselines(
    current_root: Path,
    old_root: Path,
    old_inventory: dict[str, InventoryEntry],
    candidate_paths: set[str],
) -> set[str]:
    """Overlay pre-translation image backups into a temporary Git old tree."""
    backup_root = current_root / ".dazedtl" / "image_backups"
    if not backup_root.is_dir():
        return set()
    restored: set[str] = set()
    for relative in sorted(candidate_paths):
        if not _is_image_path(relative):
            continue
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts:
            continue
        backup = backup_root.joinpath(*pure.parts)
        if not backup.is_file() or backup.is_symlink():
            continue
        target = old_root.joinpath(*pure.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(backup, target)
        stat = target.stat()
        old_inventory[relative] = InventoryEntry(
            relative_path=relative,
            sha256=sha256_file(target),
            size=stat.st_size,
            kind=classify_file(target),
            source_path=target,
        )
        restored.add(relative)
    return restored


def _read(entry: InventoryEntry | None, *, label: str) -> bytes:
    if entry is None or entry.source_path is None or not entry.source_path.is_file():
        raise VersionUpdateError(f"{label} content is unavailable for three-way merging")
    return entry.source_path.read_bytes()


def _same(left: InventoryEntry | None, right: InventoryEntry | None) -> bool:
    if left is None or right is None:
        return False
    if (
        left.kind == right.kind == FileKind.JSON
        and left.semantic_sha256
        and right.semantic_sha256
    ):
        return left.semantic_sha256 == right.semantic_sha256
    return left.sha256 == right.sha256


def _same_state(left: InventoryEntry | None, right: InventoryEntry | None) -> bool:
    return (left is None and right is None) or _same(left, right)


def _mark_recovery_status(decision: UpdateDecision) -> None:
    """Classify evidence without claiming partial local edits are proven reverts."""
    if _same_state(decision.old, decision.new):
        return
    if _same_state(decision.current, decision.old):
        decision.recovery_status = RecoveryStatus.DEFINITE_REVERT
    elif _same_state(decision.current, decision.new):
        decision.recovery_status = RecoveryStatus.ALREADY_PRESENT
    else:
        decision.recovery_status = RecoveryStatus.POSSIBLE_REVERT


def _chosen_kind(*entries: InventoryEntry | None) -> FileKind:
    for entry in entries:
        if entry is not None:
            return entry.kind
    return FileKind.BINARY


def _both_changed_decision(
    relative: str,
    old: InventoryEntry,
    current: InventoryEntry,
    new: InventoryEntry,
    profile_id: str,
) -> UpdateDecision:
    if (
        profile_id == PROFILE_RPGMAKER_MVMZ
        and old.kind in {FileKind.TEXT, FileKind.JSON}
        and current.kind in {FileKind.TEXT, FileKind.JSON}
        and new.kind in {FileKind.TEXT, FileKind.JSON}
        and is_plugins_manifest_path(relative)
    ):
        try:
            merged = merge_plugins_js_bytes(
                _read(old, label=f"old {relative}"),
                _read(current, label=f"current {relative}"),
                _read(new, label=f"new {relative}"),
            )
        except (OSError, ValueError, VersionUpdateError) as exc:
            return UpdateDecision(
                relative,
                UpdateAction.CONFLICT,
                _chosen_kind(new, current, old),
                f"semantic plugins.js merge failed: {exc}",
                old,
                current,
                new,
            )
        details = [f"{issue.path}: {issue.reason}" for issue in merged.issues]
        common = dict(
            relative_path=relative,
            kind=_chosen_kind(new, current, old),
            old=old,
            current=current,
            new=new,
            generated_content=merged.content,
            needs_translation=merged.needs_translation,
            preserved_translations=merged.preserved_translations,
            details=details,
        )
        if merged.conflicts:
            return UpdateDecision(
                action=UpdateAction.CONFLICT,
                reason="plugin settings have ambiguous both-changed values",
                needs_review=True,
                **common,
            )
        return UpdateDecision(
            action=UpdateAction.MERGE_SEMANTIC,
            reason="merged plugins by name while preserving new order and safe local settings",
            needs_review=bool(merged.issues),
            **common,
        )
    if (
        profile_id == PROFILE_RPGMAKER_MVMZ
        and old.kind == current.kind == new.kind == FileKind.JSON
        and is_supported_json_path(relative)
    ):
        try:
            merged = merge_json_bytes(
                _read(old, label=f"old {relative}"),
                _read(current, label=f"current {relative}"),
                _read(new, label=f"new {relative}"),
            )
        except (OSError, ValueError, VersionUpdateError) as exc:
            return UpdateDecision(
                relative,
                UpdateAction.CONFLICT,
                FileKind.JSON,
                f"semantic JSON merge failed: {exc}",
                old,
                current,
                new,
            )
        details = [f"{issue.path}: {issue.reason}" for issue in merged.issues]
        if merged.conflicts:
            return UpdateDecision(
                relative_path=relative,
                action=UpdateAction.CONFLICT,
                kind=FileKind.JSON,
                reason="RPG Maker data has ambiguous both-changed values",
                old=old,
                current=current,
                new=new,
                generated_content=merged.content,
                needs_review=True,
                needs_translation=merged.needs_translation,
                preserved_translations=merged.preserved_translations,
                details=details,
            )
        return UpdateDecision(
            relative_path=relative,
            action=UpdateAction.MERGE_SEMANTIC,
            kind=FileKind.JSON,
            reason="merged RPG Maker structure and preserved unchanged translations",
            old=old,
            current=current,
            new=new,
            generated_content=merged.content,
            needs_translation=merged.needs_translation,
            preserved_translations=merged.preserved_translations,
            details=details,
        )

    if old.kind in {FileKind.TEXT, FileKind.JSON} and current.kind in {
        FileKind.TEXT,
        FileKind.JSON,
    } and new.kind in {FileKind.TEXT, FileKind.JSON}:
        try:
            merged = merge_text_bytes(
                _read(old, label=f"old {relative}"),
                _read(current, label=f"current {relative}"),
                _read(new, label=f"new {relative}"),
            )
        except (OSError, VersionUpdateError) as exc:
            return UpdateDecision(
                relative,
                UpdateAction.CONFLICT,
                _chosen_kind(new, current, old),
                f"text merge failed: {exc}",
                old,
                current,
                new,
            )
        if merged.content is not None:
            if new.kind == FileKind.JSON:
                try:
                    json.loads(merged.content.decode("utf-8-sig"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    return UpdateDecision(
                        relative_path=relative,
                        action=UpdateAction.CONFLICT,
                        kind=FileKind.JSON,
                        reason=f"clean line merge did not produce valid JSON: {exc}",
                        old=old,
                        current=current,
                        new=new,
                    )
            return UpdateDecision(
                relative_path=relative,
                action=UpdateAction.MERGE_TEXT,
                kind=_chosen_kind(new, current, old),
                reason="clean three-way text merge; review before release",
                old=old,
                current=current,
                new=new,
                generated_content=merged.content,
                needs_review=True,
            )
        return UpdateDecision(
            relative_path=relative,
            action=UpdateAction.CONFLICT,
            kind=_chosen_kind(new, current, old),
            reason="translator and upstream text edits overlap",
            old=old,
            current=current,
            new=new,
            details=merged.conflicts,
        )

    return UpdateDecision(
        relative_path=relative,
        action=UpdateAction.CONFLICT,
        kind=_chosen_kind(new, current, old),
        reason="binary file changed in both the translation and official update",
        old=old,
        current=current,
        new=new,
    )


def _decision_for_path(
    relative: str,
    old: InventoryEntry | None,
    current: InventoryEntry | None,
    new: InventoryEntry | None,
    profile_id: str,
    translated_images: set[str],
) -> UpdateDecision:
    kind = _chosen_kind(new, current, old)
    if _protected_local_path(relative):
        return UpdateDecision(
            relative,
            UpdateAction.PROTECT_CURRENT,
            kind,
            "protected local save/update state is not replaced",
            old,
            current,
            new,
        )

    if _is_audio_path(relative):
        if new is None:
            return UpdateDecision(
                relative,
                UpdateAction.DELETE,
                kind,
                "audio follows the new official version and was removed upstream",
                old,
                current,
                new,
            )
        if current is None:
            return UpdateDecision(
                relative,
                UpdateAction.ADD_NEW,
                kind,
                "new official audio file",
                old,
                current,
                new,
            )
        if _same(current, new):
            return UpdateDecision(
                relative,
                UpdateAction.KEEP,
                kind,
                "audio already matches the new official version",
                old,
                current,
                new,
            )
        return UpdateDecision(
            relative,
            UpdateAction.USE_NEW,
            kind,
            "audio is not translated; use the new official version",
            old,
            current,
            new,
        )

    if _is_image_path(relative) and old is None and relative not in translated_images:
        if new is None:
            return UpdateDecision(
                relative,
                UpdateAction.DELETE,
                kind,
                "untranslated image follows the new official version and was removed",
                old,
                current,
                new,
            )
        if current is None:
            return UpdateDecision(
                relative,
                UpdateAction.ADD_NEW,
                kind,
                "new official image file",
                old,
                current,
                new,
            )
        if _same(current, new):
            return UpdateDecision(
                relative,
                UpdateAction.KEEP,
                kind,
                "untranslated image already matches the new official version",
                old,
                current,
                new,
            )
        return UpdateDecision(
            relative,
            UpdateAction.USE_NEW,
            kind,
            "image is not marked as translated; use the new official version",
            old,
            current,
            new,
        )

    if old is None:
        if current is None and new is not None:
            return UpdateDecision(
                relative,
                UpdateAction.ADD_NEW,
                kind,
                "new upstream file",
                old,
                current,
                new,
            )
        if current is not None and new is None:
            return UpdateDecision(
                relative,
                UpdateAction.PRESERVE_ADDED,
                kind,
                "translator-added file",
                old,
                current,
                new,
            )
        if current is not None and new is not None:
            if _same(current, new):
                return UpdateDecision(
                    relative,
                    UpdateAction.KEEP,
                    kind,
                    "same file added on both sides",
                    old,
                    current,
                    new,
                )
            return UpdateDecision(
                relative,
                UpdateAction.CONFLICT,
                kind,
                "translator-added file collides with a new upstream file",
                old,
                current,
                new,
            )
        return UpdateDecision(
            relative,
            UpdateAction.KEEP,
            kind,
            "absent from all inputs",
            old,
            current,
            new,
        )

    if current is None and new is None:
        return UpdateDecision(
            relative,
            UpdateAction.KEEP,
            kind,
            "already absent from both newer trees",
            old,
            current,
            new,
        )
    if current is None:
        if _same(old, new):
            return UpdateDecision(
                relative,
                UpdateAction.DELETE,
                kind,
                "translator removed unchanged official file",
                old,
                current,
                new,
            )
        return UpdateDecision(
            relative,
            UpdateAction.CONFLICT,
            kind,
            "translator removed a file that changed upstream",
            old,
            current,
            new,
        )
    if new is None:
        if _same(old, current):
            return UpdateDecision(
                relative,
                UpdateAction.DELETE,
                kind,
                "file deleted upstream",
                old,
                current,
                new,
            )
        return UpdateDecision(
            relative,
            UpdateAction.CONFLICT,
            kind,
            "upstream deleted a translator-modified file",
            old,
            current,
            new,
        )

    if _same(current, new):
        return UpdateDecision(
            relative,
            UpdateAction.KEEP,
            kind,
            "current and new files already match",
            old,
            current,
            new,
        )
    current_changed = not _same(old, current)
    new_changed = not _same(old, new)
    if not current_changed and not new_changed:
        return UpdateDecision(
            relative,
            UpdateAction.KEEP,
            kind,
            "unchanged file",
            old,
            current,
            new,
        )
    if current_changed and not new_changed:
        return UpdateDecision(
            relative,
            UpdateAction.PRESERVE_TRANSLATED,
            kind,
            "official source is unchanged; preserve translator version",
            old,
            current,
            new,
        )
    if not current_changed and new_changed:
        return UpdateDecision(
            relative,
            UpdateAction.USE_NEW,
            kind,
            "file changed only upstream",
            old,
            current,
            new,
        )
    return _both_changed_decision(relative, old, current, new, profile_id)


def _apply_recommended_resolution(decision: UpdateDecision) -> None:
    """Make every scanned conflict safe and actionable under upstream-first policy."""
    if decision.action != UpdateAction.CONFLICT:
        return
    recommendation = (
        ConflictResolution.USE_PROPOSED
        if decision.generated_content is not None
        else ConflictResolution.USE_NEW
    )
    decision.recommended_resolution = recommendation
    decision.resolution = recommendation
    decision.resolution_is_automatic = True
    decision.needs_review = True


def _resolve_profile(
    current_root: Path, new_root: Path, requested: str, baseline_profile: str | None
) -> str:
    current_profile, _ = detect_update_profile(current_root)
    new_profile, _ = detect_update_profile(new_root)
    if requested != PROFILE_AUTO:
        profile = requested
    elif new_profile != PROFILE_GENERIC:
        profile = new_profile
    elif current_profile != PROFILE_GENERIC:
        profile = current_profile
    else:
        profile = baseline_profile or PROFILE_GENERIC

    known = {PROFILE_RPGMAKER_MVMZ, PROFILE_RPGMAKER_ACE, PROFILE_WOLF}
    detected_known = {item for item in (current_profile, new_profile) if item in known}
    if len(detected_known) > 1:
        raise VersionUpdateError(
            f"Current and new folders appear to use different engines: {sorted(detected_known)}"
        )
    if profile in {PROFILE_RPGMAKER_ACE, PROFILE_WOLF}:
        raise VersionUpdateError(
            f"{profile} is detected but semantic archive normalization is not implemented yet"
        )
    packed_detected = detected_known & {PROFILE_RPGMAKER_ACE, PROFILE_WOLF}
    if packed_detected:
        raise VersionUpdateError(
            f"Packed engine {sorted(packed_detected)[0]} cannot use Generic / Files Only mode"
        )
    if profile not in {PROFILE_GENERIC, PROFILE_RPGMAKER_MVMZ}:
        raise VersionUpdateError(f"Unsupported Version Update profile: {profile}")
    return profile


def _previous_update_report(current_root: Path, new_fingerprint: str) -> dict | None:
    runs_root = current_root / ".dazedtl" / "version_update" / "runs"
    if not runs_root.is_dir():
        return None
    for report_path in sorted(runs_root.glob("*/report.json"), reverse=True):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fingerprints = report.get("fingerprints")
        if not isinstance(fingerprints, dict):
            continue
        if fingerprints.get("new_official") != new_fingerprint:
            continue
        if fingerprints.get("old_official") == new_fingerprint:
            continue
        return report
    return None


def _recover_reapply_source(
    current_root: Path,
    baseline: LoadedBaseline,
    *,
    image_candidates: set[str],
    progress: ScanProgress | None,
) -> tuple[
    Path | None,
    dict[str, InventoryEntry],
    bool,
    bool,
    str,
    str,
    str,
    list[object],
]:
    report = _previous_update_report(current_root, baseline.fingerprint)
    if report is None:
        raise VersionUpdateError(
            "Audit/reapply needs the report from the update that introduced this official "
            "version. Select the previous clean official folder in Old official and scan again."
        )
    fingerprints = report.get("fingerprints") or {}
    old_fingerprint = str(fingerprints.get("old_official") or "")
    old_version = str(report.get("old_version") or "previous version")
    new_version = str(
        report.get("new_version") or baseline.version_label or "current version"
    )
    if not old_fingerprint:
        raise VersionUpdateError(
            "The previous update report does not identify its old official source. Select the "
            "previous clean official folder in Old official and scan again."
        )

    try:
        previous = load_baseline_fingerprint(current_root, old_fingerprint)
    except BaselineError:
        previous = None
    if previous is not None:
        return (
            None,
            previous.inventory,
            True,
            False,
            "Saved prior official baseline (audit/reapply)",
            old_version,
            new_version,
            [],
        )

    try:
        git_source = discover_original_source(current_root)
    except GitSourceError as exc:
        raise VersionUpdateError(
            "Audit/reapply could not inspect the Git original branch. Select the previous "
            f"clean official folder in Old official: {exc}"
        ) from exc
    if git_source is None:
        raise VersionUpdateError(
            "Audit/reapply could not find the prior official source. Select the previous clean "
            "official folder in Old official and scan again."
        )
    if progress:
        progress("old", 0, 0, f"Verifying {git_source.label} for audit/reapply")
    try:
        old_path, temporary = export_original_source(git_source)
        old_inventory = inventory_root(
            old_path,
            progress=(
                lambda i, n, p: progress("old", i, n, p) if progress else None
            ),
        )
    except (GitSourceError, OSError) as exc:
        raise VersionUpdateError(
            f"Audit/reapply could not export {git_source.label}: {exc}"
        ) from exc
    if report.get("used_git_original"):
        _restore_git_image_baselines(
            current_root,
            old_path,
            old_inventory,
            image_candidates,
        )
    if inventory_fingerprint(old_inventory) != old_fingerprint:
        temporary.cleanup()
        raise VersionUpdateError(
            f"{git_source.label} does not match the prior official source recorded by the "
            "update report. Select the matching clean old official folder explicitly."
        )
    return (
        old_path,
        old_inventory,
        False,
        True,
        f"{git_source.label} (audit/reapply)",
        old_version,
        new_version,
        [temporary],
    )


def scan_version_update(
    current_root: str | Path,
    new_root: str | Path,
    *,
    old_root: str | Path | None = None,
    old_version: str = "",
    new_version: str = "",
    profile_id: str = PROFILE_AUTO,
    audit_reapply: bool | None = None,
    progress: ScanProgress | None = None,
) -> UpdatePlan:
    requested_old_version = old_version.strip()
    requested_new_version = new_version.strip()
    current_path = Path(current_root).expanduser().resolve()
    new_path = Path(new_root).expanduser().resolve()
    if current_path == new_path:
        raise VersionUpdateError("Current translated and new official folders must be different")
    if _is_nested(current_path, new_path) or _is_nested(new_path, current_path):
        raise VersionUpdateError("Current translated and new official folders cannot be nested")

    used_saved_baseline = False
    used_git_original = False
    baseline_profile = None
    baseline: LoadedBaseline | None = None
    old_source_label = "Old official folder"
    temporary_resources = []
    if old_root:
        old_path = Path(old_root).expanduser().resolve()
        if old_path in {current_path, new_path}:
            raise VersionUpdateError("Old, current, and new game folders must be different")
        if any(
            _is_nested(old_path, other) or _is_nested(other, old_path)
            for other in (current_path, new_path)
        ):
            raise VersionUpdateError("Old, current, and new game folders cannot be nested")
        if progress:
            progress("old", 0, 0, "Inventorying old official game")
        old_inventory = inventory_root(
            old_path,
            progress=(lambda i, n, p: progress("old", i, n, p)) if progress else None,
        )
    else:
        old_path = None
        try:
            baseline = load_baseline(current_path)
        except BaselineError as exc:
            registered_fingerprint = ""
            project_path = (
                current_path / ".dazedtl" / "version_update" / "project.json"
            )
            if project_path.is_file():
                try:
                    registered_project = json.loads(
                        project_path.read_text(encoding="utf-8")
                    )
                    registered_fingerprint = str(
                        registered_project["active_source_fingerprint"]
                    )
                    if not registered_fingerprint:
                        raise ValueError("active source fingerprint is empty")
                    baseline_profile = str(
                        registered_project.get("profile") or "generic"
                    )
                    old_version = requested_old_version or str(
                        registered_project.get("version_label") or ""
                    )
                except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as project_exc:
                    raise VersionUpdateError(
                        "A Version Update baseline is registered but its project metadata is "
                        f"invalid. Select the matching clean Old official folder: {project_exc}"
                    ) from project_exc
            try:
                git_source = discover_original_source(current_path)
            except GitSourceError as git_exc:
                raise VersionUpdateError(
                    "No saved baseline is available, and the Git original branch "
                    f"could not be inspected: {git_exc}"
                ) from git_exc
            if git_source is None:
                raise VersionUpdateError(
                    "Select the old official game once, or add an original branch to "
                    f"this game's Git repository: {exc}"
                ) from exc
            if progress:
                progress(
                    "old",
                    0,
                    0,
                    f"Exporting {git_source.label} without checking it out",
                )
            try:
                old_path, temporary = export_original_source(git_source)
                old_inventory = inventory_root(
                    old_path,
                    progress=(
                        lambda i, n, p: progress("old", i, n, p)
                        if progress
                        else None
                    ),
                )
                if (
                    registered_fingerprint
                    and inventory_fingerprint(old_inventory) != registered_fingerprint
                ):
                    temporary.cleanup()
                    raise VersionUpdateError(
                        "The saved baseline is damaged, and the Git original branch does not "
                        "match the registered active official version. Select that matching "
                        f"clean version in Old official: {exc}"
                    )
            except (GitSourceError, OSError) as git_exc:
                raise VersionUpdateError(
                    f"Could not use {git_source.label} as the old official game: {git_exc}"
                ) from git_exc
            temporary_resources.append(temporary)
            used_git_original = True
            old_source_label = git_source.label
        else:
            old_inventory = baseline.inventory
            baseline_profile = baseline.profile_id
            old_version = old_version or baseline.version_label
            used_saved_baseline = True
            old_source_label = "Saved official baseline"

    if progress:
        progress("current", 0, 0, "Inventorying current translated game")
    current_inventory = inventory_root(
        current_path,
        progress=(lambda i, n, p: progress("current", i, n, p)) if progress else None,
    )
    if progress:
        progress("new", 0, 0, "Inventorying new official game")
    new_inventory = inventory_root(
        new_path,
        progress=(lambda i, n, p: progress("new", i, n, p)) if progress else None,
    )
    official_version_already_applied = bool(
        baseline and baseline.fingerprint == inventory_fingerprint(new_inventory)
    )
    reapply_active = False
    recovery_error = ""
    if (
        official_version_already_applied
        and audit_reapply is not False
        and baseline is not None
    ):
        try:
            (
                old_path,
                old_inventory,
                used_saved_baseline,
                used_git_original,
                old_source_label,
                recovered_old_version,
                recovered_new_version,
                recovered_resources,
            ) = _recover_reapply_source(
                current_path,
                baseline,
                image_candidates=set(current_inventory) | set(new_inventory),
                progress=progress,
            )
        except VersionUpdateError as exc:
            if audit_reapply is True:
                raise
            recovery_error = str(exc)
        else:
            temporary_resources.extend(recovered_resources)
            old_version = requested_old_version or recovered_old_version
            new_version = requested_new_version or recovered_new_version
            reapply_active = True
    translated_images = _marked_translated_images(current_path)
    if used_git_original and old_path is not None:
        image_candidates = set(current_inventory) | set(new_inventory)
        restored_images = _restore_git_image_baselines(
            current_path,
            old_path,
            old_inventory,
            image_candidates,
        )
        translated_images.update(restored_images)
        if restored_images and progress:
            progress(
                "old",
                len(restored_images),
                len(restored_images),
                f"Loaded {len(restored_images)} pre-translation image backup(s)",
            )
    profile = _resolve_profile(current_path, new_path, profile_id, baseline_profile)

    all_paths = sorted(set(old_inventory) | set(current_inventory) | set(new_inventory))
    normalized_paths: dict[str, set[str]] = {}
    for relative in all_paths:
        key = unicodedata.normalize("NFC", relative).casefold()
        normalized_paths.setdefault(key, set()).add(relative)
    cross_version_collisions = [
        sorted(paths) for paths in normalized_paths.values() if len(paths) > 1
    ]
    if cross_version_collisions:
        examples = " and ".join(repr(path) for path in cross_version_collisions[0])
        raise VersionUpdateError(
            "A path changed only by case or Unicode normalization between versions: "
            f"{examples}. Rename it consistently before updating."
        )
    decisions: list[UpdateDecision] = []
    for index, relative in enumerate(all_paths, start=1):
        if progress:
            progress("plan", index, len(all_paths), relative)
        decision = _decision_for_path(
            relative,
            old_inventory.get(relative),
            current_inventory.get(relative),
            new_inventory.get(relative),
            profile,
            translated_images,
        )
        if profile == PROFILE_RPGMAKER_MVMZ and is_supported_json_path(relative):
            try:
                if decision.action == UpdateAction.ADD_NEW:
                    decision.needs_translation = count_japanese_source_bytes(
                        _read(decision.new, label=f"new {relative}")
                    )
                elif decision.action == UpdateAction.USE_NEW:
                    decision.needs_translation = count_changed_japanese_source_bytes(
                        _read(decision.old, label=f"old {relative}"),
                        _read(decision.new, label=f"new {relative}"),
                    )
                elif decision.action == UpdateAction.PRESERVE_TRANSLATED:
                    decision.preserved_translations = count_preserved_translation_bytes(
                        _read(decision.old, label=f"old {relative}"),
                        _read(decision.current, label=f"current {relative}"),
                    )
            except (OSError, VersionUpdateError):
                pass
        _apply_recommended_resolution(decision)
        if reapply_active:
            _mark_recovery_status(decision)
        decisions.append(decision)
    return UpdatePlan(
        old_root=old_path,
        current_root=current_path,
        new_root=new_path,
        profile_id=profile,
        old_version=old_version or "old version",
        new_version=new_version or "new version",
        old_inventory=old_inventory,
        current_inventory=current_inventory,
        new_inventory=new_inventory,
        decisions=decisions,
        used_saved_baseline=used_saved_baseline,
        used_git_original=used_git_original,
        old_source_label=old_source_label,
        official_version_already_applied=official_version_already_applied,
        audit_reapply=reapply_active,
        recovery_error=recovery_error,
        temporary_resources=temporary_resources,
    )


def _safe_target(root: Path, relative: str) -> Path:
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise VersionUpdateError(f"Unsafe relative update path: {relative!r}")
    target = root.joinpath(*pure.parts)
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError as exc:
        raise VersionUpdateError(f"Update path escapes the destination: {relative!r}") from exc
    return target


def _new_run_directory(metadata_root: Path) -> Path:
    runs_root = metadata_root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    for counter in range(1000):
        name = base if counter == 0 else f"{base}-{counter}"
        candidate = runs_root / name
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate
    raise VersionUpdateError("Could not allocate a unique Version Update report directory")


def _prune_update_history(
    game_root: Path,
    *,
    keep_run: Path,
    max_runs: int = MAX_RETAINED_RUNS,
) -> None:
    """Bound owned history while retaining every baseline referenced by kept reports."""
    metadata = game_root / ".dazedtl" / "version_update"
    runs_root = metadata / "runs"
    run_dirs: list[Path] = []
    if runs_root.is_dir():
        for child in runs_root.iterdir():
            if child.is_symlink():
                raise VersionUpdateError(
                    f"Version Update history contains an unsafe symbolic link: {child}"
                )
            if child.is_dir():
                run_dirs.append(child)

    def run_sort_key(run_dir: Path) -> tuple[str, str]:
        try:
            report = json.loads(run_dir.joinpath("report.json").read_text(encoding="utf-8"))
            applied_at = str(report.get("applied_at") or "")
        except (OSError, json.JSONDecodeError, TypeError):
            applied_at = ""
        return applied_at, run_dir.name

    keep_count = max(1, max_runs)
    ordered = sorted(run_dirs, key=run_sort_key, reverse=True)
    kept = [keep_run]
    kept.extend(
        [path for path in ordered if path != keep_run][: keep_count - 1]
    )
    kept_set = set(kept)
    for run_dir in run_dirs:
        if run_dir not in kept_set:
            shutil.rmtree(run_dir)

    referenced_fingerprints: set[str] = set()
    try:
        project = json.loads(metadata.joinpath("project.json").read_text(encoding="utf-8"))
        active = project.get("active_source_fingerprint")
        if isinstance(active, str) and active:
            referenced_fingerprints.add(active)
    except (OSError, json.JSONDecodeError, TypeError):
        pass
    for run_dir in kept:
        try:
            report = json.loads(run_dir.joinpath("report.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        fingerprints = report.get("fingerprints")
        if not isinstance(fingerprints, dict):
            continue
        for key in ("old_official", "new_official"):
            value = fingerprints.get(key)
            if isinstance(value, str) and value:
                referenced_fingerprints.add(value)

    baselines_root = metadata / "baselines"
    if baselines_root.is_dir():
        for child in baselines_root.iterdir():
            if child.is_symlink():
                raise VersionUpdateError(
                    f"Version Update baselines contain an unsafe symbolic link: {child}"
                )
            if child.is_dir() and child.name not in referenced_fingerprints:
                shutil.rmtree(child)


def _copy_entry(entry: InventoryEntry | None, target: Path) -> None:
    if entry is None or entry.source_path is None or not entry.source_path.is_file():
        raise VersionUpdateError(f"Source content is unavailable for {target.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(entry.source_path, target)


def _apply_decision(decision: UpdateDecision, stage: Path) -> tuple[int, int, int]:
    target = _safe_target(stage, decision.relative_path)
    if decision.action in {
        UpdateAction.KEEP,
        UpdateAction.PRESERVE_TRANSLATED,
        UpdateAction.PRESERVE_ADDED,
        UpdateAction.PROTECT_CURRENT,
    }:
        return 0, 0, 1
    if decision.action in {UpdateAction.USE_NEW, UpdateAction.ADD_NEW}:
        _copy_entry(decision.new, target)
        return 1, 0, 0
    if decision.action == UpdateAction.DELETE:
        if target.exists():
            if target.is_dir():
                raise VersionUpdateError(f"Expected a file but found a directory: {target}")
            target.unlink()
            return 0, 1, 0
        return 0, 0, 1
    if decision.action in {UpdateAction.MERGE_TEXT, UpdateAction.MERGE_SEMANTIC}:
        if decision.generated_content is None:
            raise VersionUpdateError(
                f"Generated merge content is missing: {decision.relative_path}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(decision.generated_content)
        return 1, 0, 0
    if decision.action != UpdateAction.CONFLICT or decision.resolution is None:
        raise VersionUpdateError(f"Unresolved conflict: {decision.relative_path}")
    if decision.resolution == ConflictResolution.KEEP_CURRENT:
        if decision.current is None and target.exists():
            target.unlink()
            return 0, 1, 0
        return 0, 0, 1
    if decision.resolution == ConflictResolution.USE_NEW:
        if decision.new is None:
            if target.exists():
                target.unlink()
                return 0, 1, 0
            return 0, 0, 1
        _copy_entry(decision.new, target)
        return 1, 0, 0
    if decision.resolution == ConflictResolution.USE_PROPOSED:
        if decision.generated_content is None:
            raise VersionUpdateError(f"No proposed merge exists for {decision.relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(decision.generated_content)
        return 1, 0, 0
    if decision.resolution == ConflictResolution.USE_MERGED_FILE:
        if decision.merged_file is None or not decision.merged_file.is_file():
            raise VersionUpdateError(f"Reviewed merged file is missing: {decision.relative_path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(decision.merged_file, target)
        return 1, 0, 0
    raise VersionUpdateError(f"Unknown conflict resolution for {decision.relative_path}")


def _validate_applied_decision(decision: UpdateDecision, stage: Path) -> None:
    """Verify the staged file is exactly the result selected by the plan."""
    target = _safe_target(stage, decision.relative_path)
    expected_entry: InventoryEntry | None = None
    expected_content: bytes | None = None
    expected_file: Path | None = None

    if decision.action in {
        UpdateAction.KEEP,
        UpdateAction.PRESERVE_TRANSLATED,
        UpdateAction.PRESERVE_ADDED,
        UpdateAction.PROTECT_CURRENT,
    }:
        expected_entry = decision.current
    elif decision.action in {UpdateAction.USE_NEW, UpdateAction.ADD_NEW}:
        expected_entry = decision.new
    elif decision.action == UpdateAction.DELETE:
        pass
    elif decision.action in {UpdateAction.MERGE_TEXT, UpdateAction.MERGE_SEMANTIC}:
        expected_content = decision.generated_content
    elif decision.action == UpdateAction.CONFLICT:
        if decision.resolution == ConflictResolution.KEEP_CURRENT:
            expected_entry = decision.current
        elif decision.resolution == ConflictResolution.USE_NEW:
            expected_entry = decision.new
        elif decision.resolution == ConflictResolution.USE_PROPOSED:
            expected_content = decision.generated_content
        elif decision.resolution == ConflictResolution.USE_MERGED_FILE:
            expected_file = decision.merged_file

    expects_file = any(
        value is not None for value in (expected_entry, expected_content, expected_file)
    )
    if not expects_file:
        if target.exists():
            raise VersionUpdateError(
                f"Staged validation expected {decision.relative_path} to be absent"
            )
        return
    if not target.is_file() or target.is_symlink():
        raise VersionUpdateError(
            f"Staged validation could not find a safe file for {decision.relative_path}"
        )
    if expected_entry is not None:
        stat = target.stat()
        if stat.st_size != expected_entry.size or sha256_file(target) != expected_entry.sha256:
            raise VersionUpdateError(
                f"Staged file does not match the selected source: {decision.relative_path}"
            )
    elif expected_content is not None:
        if target.read_bytes() != expected_content:
            raise VersionUpdateError(
                f"Staged generated merge is incomplete: {decision.relative_path}"
            )
    elif expected_file is not None:
        if not expected_file.is_file() or sha256_file(target) != sha256_file(expected_file):
            raise VersionUpdateError(
                f"Staged reviewed merge changed while applying: {decision.relative_path}"
            )


def _validate_staged_structure(plan: UpdatePlan, stage: Path) -> None:
    """Perform engine-aware structural checks without claiming to launch the game."""
    if plan.profile_id != PROFILE_RPGMAKER_MVMZ:
        return
    detected_profile, _reason = detect_update_profile(stage)
    if detected_profile != PROFILE_RPGMAKER_MVMZ:
        raise VersionUpdateError(
            "The staged output no longer has a valid RPG Maker MV/MZ data layout"
        )
    for decision in plan.decisions:
        if not is_supported_json_path(decision.relative_path):
            continue
        target = _safe_target(stage, decision.relative_path)
        if not target.exists():
            continue
        try:
            json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VersionUpdateError(
                f"Staged RPG Maker JSON is invalid: {decision.relative_path}: {exc}"
            ) from exc


def _is_nested(path: Path, possible_parent: Path) -> bool:
    try:
        path.relative_to(possible_parent)
        return True
    except ValueError:
        return False


def apply_staged_update(
    plan: UpdatePlan,
    output_root: str | Path,
    *,
    progress: ApplyProgress | None = None,
    include_vcs_metadata: bool = False,
) -> ApplyResult:
    if plan.official_version_already_applied and not plan.audit_reapply:
        raise VersionUpdateError(
            "This official version was already applied. Run an Audit/reapply scan first if "
            "you need to restore official changes that were later reverted."
        )
    if plan.blocking_conflicts:
        raise VersionUpdateError(
            f"Resolve {len(plan.blocking_conflicts)} conflict(s) before creating the update"
        )
    output = Path(output_root).expanduser().resolve()
    if output.exists():
        raise VersionUpdateError(f"Output folder already exists: {output}")
    for source in (plan.current_root, plan.new_root, plan.old_root):
        if source is None:
            continue
        if output == source or _is_nested(output, source) or _is_nested(source, output):
            raise VersionUpdateError("Output folder must be separate from all input folders")

    assert_inventory_unchanged(plan.current_inventory, plan.current_root, label="Current game")
    assert_inventory_unchanged(plan.new_inventory, plan.new_root, label="New official game")
    if plan.old_root is not None:
        assert_inventory_unchanged(plan.old_inventory, plan.old_root, label="Old official game")

    output.parent.mkdir(parents=True, exist_ok=True)
    required_bytes = sum(entry.size for entry in plan.current_inventory.values())
    required_bytes += sum(
        entry.size
        for entry in plan.new_inventory.values()
        if entry.kind in {FileKind.JSON, FileKind.TEXT}
    )
    required_bytes = int(required_bytes * 1.05) + 16 * 1024 * 1024
    free_bytes = shutil.disk_usage(output.parent).free
    if free_bytes < required_bytes:
        raise VersionUpdateError(
            "Not enough free disk space to stage the updated game and its source baseline "
            f"(need about {required_bytes / (1024 ** 3):.2f} GiB; "
            f"{free_bytes / (1024 ** 3):.2f} GiB available)"
        )
    stage = Path(
        tempfile.mkdtemp(prefix=f".{output.name}.version-update-", dir=output.parent)
    )
    files_written = files_deleted = files_preserved = 0
    try:
        shutil.rmtree(stage)
        ignored_names = (
            ("__pycache__",)
            if include_vcs_metadata
            else (".git", ".svn", ".hg", "__pycache__")
        )
        shutil.copytree(
            plan.current_root,
            stage,
            symlinks=True,
            ignore=shutil.ignore_patterns(*ignored_names),
        )
        total = len(plan.decisions)
        for index, decision in enumerate(plan.decisions, start=1):
            if progress:
                progress(index, total, decision.relative_path)
            written, deleted, preserved = _apply_decision(decision, stage)
            _validate_applied_decision(decision, stage)
            files_written += written
            files_deleted += deleted
            files_preserved += preserved

        _validate_staged_structure(plan, stage)
        saved_old = save_baseline_inventory(
            stage,
            plan.old_inventory,
            profile_id=plan.profile_id,
            version_label=plan.old_version,
            activate=False,
        )
        saved_new = save_baseline(
            stage,
            plan.new_root,
            profile_id=plan.profile_id,
            version_label=plan.new_version,
        )
        try:
            verified_old = load_baseline_fingerprint(stage, saved_old.fingerprint)
            verified_active = load_baseline(stage)
        except BaselineError as exc:
            raise VersionUpdateError(
                f"The staged recovery history could not be verified: {exc}"
            ) from exc
        if (
            verified_old.fingerprint != saved_old.fingerprint
            or verified_active.fingerprint != saved_new.fingerprint
        ):
            raise VersionUpdateError(
                "The staged recovery history does not match the planned official sources"
            )
        metadata_root = stage / ".dazedtl" / "version_update"
        run_dir = _new_run_directory(metadata_root)
        report = plan.to_dict()
        report["applied_at"] = datetime.now(timezone.utc).isoformat()
        report["output_root"] = str(output)
        report["apply"] = {
            "files_written": files_written,
            "files_deleted": files_deleted,
            "files_preserved": files_preserved,
            "retained_run_limit": MAX_RETAINED_RUNS,
        }
        report_path_in_stage = run_dir / "report.json"
        report_path_in_stage.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        summary = plan.summary()
        markdown_lines = [
            "# Version Update Report",
            "",
            f"- Update: {plan.old_version} → {plan.new_version}",
            f"- Profile: {plan.profile_id}",
            f"- Files written: {files_written:,}",
            f"- Files deleted: {files_deleted:,}",
            f"- Files preserved: {files_preserved:,}",
            f"- Translated segments preserved: {summary['preserved_translations']:,}",
            f"- Segments needing translation: {summary['needs_translation']:,}",
            "",
            "## Decisions",
            "",
            "| Action | Path | Reason |",
            "|---|---|---|",
        ]
        for decision in plan.decisions:
            safe_path = decision.relative_path.replace("|", "\\|")
            safe_reason = decision.reason.replace("|", "\\|").replace("\n", " ")
            markdown_lines.append(
                f"| {decision.action.value} | `{safe_path}` | {safe_reason} |"
            )
        markdown_path_in_stage = run_dir / "report.md"
        markdown_path_in_stage.write_text(
            "\n".join(markdown_lines) + "\n", encoding="utf-8"
        )
        _prune_update_history(stage, keep_run=run_dir)
        os.replace(stage, output)
        report_path = output / markdown_path_in_stage.relative_to(stage)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    summary = plan.summary()
    result = ApplyResult(
        output_root=output,
        report_path=report_path,
        files_written=files_written,
        files_deleted=files_deleted,
        files_preserved=files_preserved,
        needs_translation=summary["needs_translation"],
        preserved_translations=summary["preserved_translations"],
    )
    plan.cleanup_temporary_resources()
    return result


def _available_sibling(parent: Path, name: str) -> Path:
    candidate = parent / name
    counter = 2
    while candidate.exists():
        candidate = parent / f"{name} ({counter})"
        counter += 1
    return candidate


def apply_in_place_update(
    plan: UpdatePlan,
    *,
    progress: ApplyProgress | None = None,
) -> ApplyResult:
    """Stage a complete update, then atomically swap it with the translated game.

    The previous translated folder is retained as a sibling rollback backup. The
    live folder is not renamed until the same-volume staged copy is complete.
    """
    current = plan.current_root.expanduser().resolve()
    if not current.is_dir():
        raise VersionUpdateError(f"Current translated game folder not found: {current}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safe_version = "".join(
        character if character.isalnum() or character in " ._-" else "-"
        for character in plan.old_version
    ).strip(" .-") or "previous"
    stage_output = _available_sibling(
        current.parent, f".{current.name}.in-place-update-{timestamp}"
    )
    backup = _available_sibling(
        current.parent, f"{current.name} Backup {safe_version} {timestamp}"
    )

    staged = apply_staged_update(
        plan,
        stage_output,
        progress=progress,
        include_vcs_metadata=True,
    )
    try:
        assert_inventory_unchanged(
            plan.current_inventory,
            plan.current_root,
            label="Current game",
        )
    except Exception:
        shutil.rmtree(stage_output, ignore_errors=True)
        raise
    json_report = staged.report_path.with_suffix(".json")
    try:
        report = json.loads(json_report.read_text(encoding="utf-8"))
        report["output_root"] = str(current)
        report.setdefault("apply", {})["mode"] = "in_place"
        report["apply"]["backup_root"] = str(backup)
        json_report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError) as exc:
        shutil.rmtree(stage_output, ignore_errors=True)
        raise VersionUpdateError(f"Could not finalize the in-place update report: {exc}") from exc

    current_moved = False
    try:
        os.replace(current, backup)
        current_moved = True
        os.replace(stage_output, current)
    except Exception as exc:
        if current_moved and backup.exists() and not current.exists():
            try:
                os.replace(backup, current)
            except Exception as rollback_exc:
                raise VersionUpdateError(
                    "The folder swap failed and automatic rollback also failed. "
                    f"Restore the translated game manually from {backup}: {rollback_exc}"
                ) from exc
        shutil.rmtree(stage_output, ignore_errors=True)
        raise VersionUpdateError(
            f"The in-place folder swap failed; the original translation was restored: {exc}"
        ) from exc

    report_path = current / staged.report_path.relative_to(stage_output)
    return ApplyResult(
        output_root=current,
        report_path=report_path,
        files_written=staged.files_written,
        files_deleted=staged.files_deleted,
        files_preserved=staged.files_preserved,
        needs_translation=staged.needs_translation,
        preserved_translations=staged.preserved_translations,
        backup_root=backup,
    )
