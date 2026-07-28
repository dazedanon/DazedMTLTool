"""Project-local official-source baselines for future two-folder updates."""

from __future__ import annotations

import json
import shutil
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath

from .inventory import (
    inventory_fingerprint,
    inventory_root,
    semantic_json_sha256,
    sha256_file,
)
from .models import FileKind, InventoryEntry


BASELINE_RELATIVE = Path(".dazedtl") / "version_update"


class BaselineError(RuntimeError):
    """Raised when saved baseline metadata is absent or invalid."""


@dataclass(frozen=True)
class LoadedBaseline:
    fingerprint: str
    version_label: str
    profile_id: str
    inventory: dict[str, InventoryEntry]


def _metadata_root(game_root: str | Path) -> Path:
    return Path(game_root).expanduser().resolve() / BASELINE_RELATIVE


def save_baseline(
    game_root: str | Path,
    official_root: str | Path,
    *,
    profile_id: str,
    version_label: str,
) -> LoadedBaseline:
    official = Path(official_root).expanduser().resolve()
    entries = inventory_root(official)
    return save_baseline_inventory(
        game_root,
        entries,
        profile_id=profile_id,
        version_label=version_label,
    )


def save_baseline_inventory(
    game_root: str | Path,
    entries: dict[str, InventoryEntry],
    *,
    profile_id: str,
    version_label: str,
    activate: bool = True,
) -> LoadedBaseline:
    """Persist an already-inventoried official source without hashing it again."""
    game = Path(game_root).expanduser().resolve()
    fingerprint = inventory_fingerprint(entries)
    metadata = _metadata_root(game)
    baseline_dir = metadata / "baselines" / fingerprint
    mergeable_dir = baseline_dir / "mergeable"
    mergeable_dir.mkdir(parents=True, exist_ok=True)

    manifest_entries = []
    loaded_entries: dict[str, InventoryEntry] = {}
    for relative, entry in sorted(entries.items()):
        saved_source = None
        if entry.kind in {FileKind.JSON, FileKind.TEXT} and entry.source_path:
            saved_source = mergeable_dir / Path(relative)
            saved_source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry.source_path, saved_source)
        manifest_entries.append(entry.to_dict())
        loaded_entries[relative] = InventoryEntry(
            relative_path=relative,
            sha256=entry.sha256,
            size=entry.size,
            kind=entry.kind,
            semantic_sha256=entry.semantic_sha256,
            source_path=saved_source,
        )

    manifest = {
        "schema_version": 1,
        "fingerprint": fingerprint,
        "version_label": version_label,
        "profile": profile_id,
        "entries": manifest_entries,
    }
    baseline_dir.joinpath("manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if activate:
        metadata.mkdir(parents=True, exist_ok=True)
        metadata.joinpath("project.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "active_source_fingerprint": fingerprint,
                    "version_label": version_label,
                    "profile": profile_id,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return LoadedBaseline(fingerprint, version_label, profile_id, loaded_entries)


def load_baseline(game_root: str | Path) -> LoadedBaseline:
    metadata = _metadata_root(game_root)
    project_path = metadata / "project.json"
    if not project_path.is_file():
        raise BaselineError("No Version Update baseline is registered for this game")
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
        fingerprint = str(project["active_source_fingerprint"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise BaselineError(f"Saved Version Update baseline is invalid: {exc}") from exc

    return load_baseline_fingerprint(game_root, fingerprint, project=project)


def load_baseline_fingerprint(
    game_root: str | Path,
    fingerprint: str,
    *,
    project: dict | None = None,
) -> LoadedBaseline:
    """Load a retained historical official-source baseline by fingerprint."""
    metadata = _metadata_root(game_root)
    manifest_path = metadata / "baselines" / fingerprint / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise BaselineError(
            f"Saved Version Update baseline {fingerprint[:10]} is unavailable: {exc}"
        ) from exc
    if str(manifest.get("fingerprint") or "") != fingerprint:
        raise BaselineError(
            f"Saved Version Update baseline {fingerprint[:10]} has the wrong fingerprint"
        )
    if manifest.get("schema_version") != 1:
        raise BaselineError(
            f"Saved Version Update baseline {fingerprint[:10]} uses an unsupported schema"
        )
    raw_entries = manifest.get("entries")
    if not isinstance(raw_entries, list):
        raise BaselineError("Saved Version Update baseline entries are invalid")

    mergeable_dir = manifest_path.parent / "mergeable"
    entries: dict[str, InventoryEntry] = {}
    normalized_paths: dict[str, str] = {}
    for raw in raw_entries:
        if not isinstance(raw, dict):
            raise BaselineError("Saved Version Update baseline contains an invalid entry")
        relative_value = raw.get("path")
        if not isinstance(relative_value, str):
            raise BaselineError("Saved Version Update baseline contains an invalid path")
        relative = relative_value
        pure = PurePosixPath(relative)
        if (
            not relative
            or pure.is_absolute()
            or ".." in pure.parts
            or pure.as_posix() != relative
        ):
            raise BaselineError(
                f"Saved Version Update baseline contains an unsafe path: {relative!r}"
            )
        collision_key = unicodedata.normalize("NFC", relative).casefold()
        previous_path = normalized_paths.get(collision_key)
        if previous_path is not None:
            raise BaselineError(
                "Saved Version Update baseline contains duplicate or colliding paths: "
                f"{previous_path!r} and {relative!r}"
            )
        normalized_paths[collision_key] = relative
        candidate = mergeable_dir.joinpath(*pure.parts)
        try:
            entry = InventoryEntry.from_dict(
                raw,
                source_path=(candidate if candidate.is_file() else None),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineError(
                f"Saved Version Update baseline entry is invalid for {relative}: {exc}"
            ) from exc
        if entry.size < 0 or len(entry.sha256) != 64:
            raise BaselineError(
                f"Saved Version Update baseline has invalid file metadata for {relative}"
            )
        try:
            bytes.fromhex(entry.sha256)
        except ValueError as exc:
            raise BaselineError(
                f"Saved Version Update baseline has an invalid hash for {relative}"
            ) from exc
        source_path = entry.source_path
        if entry.kind in {FileKind.JSON, FileKind.TEXT}:
            if source_path is None:
                raise BaselineError(
                    f"Saved Version Update baseline source is missing for {relative}"
                )
            try:
                source_path.resolve(strict=True).relative_to(mergeable_dir.resolve(strict=True))
            except (OSError, ValueError) as exc:
                raise BaselineError(
                    f"Saved Version Update baseline source escapes its folder: {relative}"
                ) from exc
            if source_path.is_symlink():
                raise BaselineError(
                    f"Saved Version Update baseline source is a symbolic link: {relative}"
                )
            if (
                source_path.stat().st_size != entry.size
                or sha256_file(source_path) != entry.sha256
            ):
                raise BaselineError(
                    f"Saved Version Update baseline source is corrupted for {relative}"
                )
        if (
            entry.kind == FileKind.JSON
            and source_path is not None
        ):
            semantic_hash = semantic_json_sha256(source_path)
            if entry.semantic_sha256 and semantic_hash != entry.semantic_sha256:
                raise BaselineError(
                    f"Saved Version Update baseline JSON is corrupted for {relative}"
                )
            if entry.semantic_sha256 is None:
                entry = replace(entry, semantic_sha256=semantic_hash)
        entries[relative] = entry
    calculated_fingerprint = inventory_fingerprint(entries)
    if calculated_fingerprint != fingerprint:
        raise BaselineError(
            f"Saved Version Update baseline {fingerprint[:10]} manifest was modified"
        )
    return LoadedBaseline(
        fingerprint=fingerprint,
        version_label=str(
            manifest.get("version_label")
            or (project or {}).get("version_label")
            or ""
        ),
        profile_id=str(
            manifest.get("profile") or (project or {}).get("profile") or "generic"
        ),
        inventory=entries,
    )
