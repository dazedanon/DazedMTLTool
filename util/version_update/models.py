"""Data models for safe three-way game version updates."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


def _inventory_fingerprint(inventory: dict[str, "InventoryEntry"]) -> str:
    digest = hashlib.sha256()
    for relative, entry in sorted(inventory.items()):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


class FileKind(str, Enum):
    JSON = "json"
    TEXT = "text"
    BINARY = "binary"


class UpdateAction(str, Enum):
    KEEP = "keep"
    PRESERVE_TRANSLATED = "preserve_translated"
    USE_NEW = "use_new"
    ADD_NEW = "add_new"
    PRESERVE_ADDED = "preserve_added"
    DELETE = "delete"
    MERGE_TEXT = "merge_text"
    MERGE_SEMANTIC = "merge_semantic"
    PROTECT_CURRENT = "protect_current"
    CONFLICT = "conflict"


class ConflictResolution(str, Enum):
    USE_NEW = "use_new"
    KEEP_CURRENT = "keep_current"
    USE_PROPOSED = "use_proposed"
    USE_MERGED_FILE = "use_merged_file"


class RecoveryStatus(str, Enum):
    DEFINITE_REVERT = "definite_revert"
    POSSIBLE_REVERT = "possible_revert"
    ALREADY_PRESENT = "already_present"


@dataclass(frozen=True)
class InventoryEntry:
    relative_path: str
    sha256: str
    size: int
    kind: FileKind
    semantic_sha256: str | None = None
    source_path: Path | None = field(default=None, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "sha256": self.sha256,
            "size": self.size,
            "kind": self.kind.value,
            "semantic_sha256": self.semantic_sha256,
        }

    @classmethod
    def from_dict(
        cls, data: dict[str, Any], *, source_path: Path | None = None
    ) -> "InventoryEntry":
        return cls(
            relative_path=str(data["path"]),
            sha256=str(data["sha256"]),
            size=int(data["size"]),
            kind=FileKind(str(data["kind"])),
            semantic_sha256=(
                str(data["semantic_sha256"])
                if data.get("semantic_sha256")
                else None
            ),
            source_path=source_path,
        )


@dataclass
class UpdateDecision:
    relative_path: str
    action: UpdateAction
    kind: FileKind
    reason: str
    old: InventoryEntry | None = None
    current: InventoryEntry | None = None
    new: InventoryEntry | None = None
    generated_content: bytes | None = field(default=None, repr=False)
    needs_review: bool = False
    needs_translation: int = 0
    preserved_translations: int = 0
    details: list[str] = field(default_factory=list)
    resolution: ConflictResolution | None = None
    recommended_resolution: ConflictResolution | None = None
    resolution_is_automatic: bool = False
    merged_file: Path | None = field(default=None, repr=False)
    recovery_status: RecoveryStatus | None = None

    @property
    def blocking(self) -> bool:
        return self.action == UpdateAction.CONFLICT and self.resolution is None

    @property
    def translation_at_risk(self) -> bool:
        """Whether the chosen result drops a differing local file/change."""
        return (
            self.action == UpdateAction.CONFLICT
            and self.resolution == ConflictResolution.USE_NEW
            and self.current is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.relative_path,
            "action": self.action.value,
            "kind": self.kind.value,
            "reason": self.reason,
            "needs_review": self.needs_review,
            "needs_translation": self.needs_translation,
            "preserved_translations": self.preserved_translations,
            "details": list(self.details),
            "blocking": self.blocking,
            "resolution": self.resolution.value if self.resolution else None,
            "recommended_resolution": (
                self.recommended_resolution.value
                if self.recommended_resolution
                else None
            ),
            "resolution_is_automatic": self.resolution_is_automatic,
            "translation_at_risk": self.translation_at_risk,
            "recovery_status": (
                self.recovery_status.value if self.recovery_status else None
            ),
            "old": self.old.to_dict() if self.old else None,
            "current": self.current.to_dict() if self.current else None,
            "new": self.new.to_dict() if self.new else None,
        }


@dataclass
class UpdatePlan:
    old_root: Path | None
    current_root: Path
    new_root: Path
    profile_id: str
    old_version: str
    new_version: str
    old_inventory: dict[str, InventoryEntry]
    current_inventory: dict[str, InventoryEntry]
    new_inventory: dict[str, InventoryEntry]
    decisions: list[UpdateDecision]
    used_saved_baseline: bool = False
    used_git_original: bool = False
    old_source_label: str = "Old official folder"
    official_version_already_applied: bool = False
    audit_reapply: bool = False
    recovery_error: str = ""
    temporary_resources: list[Any] = field(default_factory=list, repr=False)

    @property
    def blocking_conflicts(self) -> list[UpdateDecision]:
        return [decision for decision in self.decisions if decision.blocking]

    def cleanup_temporary_resources(self) -> None:
        """Release temporary Git exports after the plan is applied or discarded."""
        resources, self.temporary_resources = self.temporary_resources, []
        for resource in resources:
            cleanup = getattr(resource, "cleanup", None)
            if callable(cleanup):
                cleanup()

    def summary(self) -> dict[str, int]:
        summary = {action.value: 0 for action in UpdateAction}
        for decision in self.decisions:
            summary[decision.action.value] += 1
        summary["blocking_conflicts"] = len(self.blocking_conflicts)
        summary["review_items"] = sum(
            decision.needs_review for decision in self.decisions
        )
        summary["automatic_resolutions"] = sum(
            decision.resolution_is_automatic for decision in self.decisions
        )
        summary["translation_at_risk"] = sum(
            decision.translation_at_risk for decision in self.decisions
        )
        summary["needs_translation"] = sum(
            decision.needs_translation for decision in self.decisions
        )
        summary["preserved_translations"] = sum(
            decision.preserved_translations for decision in self.decisions
        )
        summary["definite_reverts"] = sum(
            decision.recovery_status == RecoveryStatus.DEFINITE_REVERT
            for decision in self.decisions
        )
        summary["possible_reverts"] = sum(
            decision.recovery_status == RecoveryStatus.POSSIBLE_REVERT
            for decision in self.decisions
        )
        summary["official_changes_present"] = sum(
            decision.recovery_status == RecoveryStatus.ALREADY_PRESENT
            for decision in self.decisions
        )
        return summary

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "profile": self.profile_id,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "old_root": str(self.old_root) if self.old_root else None,
            "current_root": str(self.current_root),
            "new_root": str(self.new_root),
            "used_saved_baseline": self.used_saved_baseline,
            "used_git_original": self.used_git_original,
            "old_source": self.old_source_label,
            "official_version_already_applied": self.official_version_already_applied,
            "audit_reapply": self.audit_reapply,
            "recovery_error": self.recovery_error,
            "fingerprints": {
                "old_official": _inventory_fingerprint(self.old_inventory),
                "current_translated": _inventory_fingerprint(self.current_inventory),
                "new_official": _inventory_fingerprint(self.new_inventory),
            },
            "summary": self.summary(),
            "decisions": [decision.to_dict() for decision in self.decisions],
        }


@dataclass(frozen=True)
class ApplyResult:
    output_root: Path
    report_path: Path
    files_written: int
    files_deleted: int
    files_preserved: int
    needs_translation: int
    preserved_translations: int
    backup_root: Path | None = None
