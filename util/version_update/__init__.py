"""Safe three-way migration of translated games to newer official versions."""

from .models import (
    ApplyResult,
    ConflictResolution,
    FileKind,
    RecoveryStatus,
    UpdateAction,
    UpdateDecision,
    UpdatePlan,
)
from .git_source import GitOriginalSource, discover_original_source
from .service import (
    PROFILE_GENERIC,
    PROFILE_RPGMAKER_MVMZ,
    VersionUpdateError,
    apply_in_place_update,
    apply_staged_update,
    detect_update_profile,
    scan_version_update,
)

__all__ = [
    "ApplyResult",
    "ConflictResolution",
    "FileKind",
    "GitOriginalSource",
    "PROFILE_GENERIC",
    "PROFILE_RPGMAKER_MVMZ",
    "RecoveryStatus",
    "UpdateAction",
    "UpdateDecision",
    "UpdatePlan",
    "VersionUpdateError",
    "apply_in_place_update",
    "apply_staged_update",
    "detect_update_profile",
    "discover_original_source",
    "scan_version_update",
]
