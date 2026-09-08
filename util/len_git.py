"""Local Git setup for Len's assistant-driven flow, using the shared update backend."""

from dataclasses import asdict
from pathlib import Path

from util.len_translation import LenProject, _validate_project
from util.version_update import (
    GitWorkflowError, bootstrap_repository, inspect_repository,
    record_version_metadata, register_translation_branch,
)
from util.version_update.git_workflow import _preserve_game_files, _run_git


def _pending_operations(repo: Path) -> list[str]:
    pending = []
    for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer", "BISECT_LOG"):
        value = _run_git(repo, "rev-parse", "--git-path", name).stdout.strip()
        path = Path(value)
        if (path if path.is_absolute() else repo / path).exists():
            pending.append(name)
    return pending


def git_status(project: LenProject) -> dict:
    """Inspect without initializing Git, moving branches, or staging files."""
    _validate_project(project)
    status = inspect_repository(project.game_root)
    result = {key: str(value) if isinstance(value, Path) else value for key, value in asdict(status).items()}
    result["pending_operations"] = _pending_operations(status.repo_root) if status.repo_root else []
    result["preserve_game_files"] = _preserve_game_files(status.repo_root) if status.repo_root else True
    result["configured"] = bool(status.original_exists and status.translation_exists)
    result["available_original_refs"] = []
    if status.repo_root and not status.original_exists:
        refs = _run_git(status.repo_root, "for-each-ref", "--format=%(refname)", "refs/remotes").stdout.splitlines()
        result["available_original_refs"] = [ref for ref in refs if ref.endswith("/original")]
    return result


def setup_git(project: LenProject, *, original_game: Path | None = None, version: str | None = None,
              current_is_untranslated: bool = False) -> dict:
    """Use the selected untranslated game for fresh baselines, including normal tool preparation.

    Resume/QA must identify another source or explicitly attest that the current
    game remains untranslated. Merely selecting a resume stage is not that attestation.
    """
    before = git_status(project)
    repo = before["repo_root"]
    if repo and Path(repo) != project.game_root:
        raise GitWorkflowError(
            "The game is inside a parent repository. Review that repository's scope before setting up version tracking."
        )
    if before["pending_operations"] or before["asset_sync_pending"]:
        raise GitWorkflowError("Finish the pending Git or asset update before setting up Len's version tracking.")
    if repo and (not before["current_branch"] or before["current_branch"] == "original"):
        raise GitWorkflowError("Check out the intended translation branch before setup; existing branches will not be switched automatically.")
    if before["configured"]:
        if before["current_branch"] != before["translation_branch"]:
            raise GitWorkflowError("Check out the registered translation branch before resuming.")
        if version and before["translation_version"] and version.strip() != before["translation_version"]:
            raise GitWorkflowError("The requested version differs from the registered translation. Use Version Update for a new release.")
        if before["original_version"] and before["translation_version"]:
            return {"action": "reused", **before}
        if not version:
            raise GitWorkflowError("Supply --version to label the existing baselines.")
        record_version_metadata(project.game_root, version)
        action = "version-recorded"
    else:
        if repo and not before["worktree_clean"]:
            raise GitWorkflowError("Review and checkpoint current changes before registering a baseline; setup will not stage or discard them.")
        if not before["original_exists"] and before["available_original_refs"]:
            commits = {_run_git(Path(repo), "rev-parse", f"{ref}^{{commit}}").stdout.strip() for ref in before["available_original_refs"]}
            if len(commits) != 1:
                raise GitWorkflowError("Several existing original refs disagree. Select the intended baseline before setup.")
            # A clone already has these objects. Restore the local baseline
            # without fetching, pushing, changing remotes or inventing an original.
            _run_git(Path(repo), "update-ref", "refs/heads/original", commits.pop(), "0" * 40)
            before = git_status(project)
        if before["original_exists"]:
            if version and before["original_version"] and version.strip() != before["original_version"]:
                raise GitWorkflowError("The version differs from the existing original baseline. Use Version Update for a new release.")
            register_translation_branch(project.game_root, version, preserve_game_files=True)
            action = "registered"
        else:
            if not version:
                raise GitWorkflowError("Supply --version with the starting game's release label.")
            resuming = project.stage in {"continue", "qa"}
            if original_game is None and resuming and not current_is_untranslated:
                raise GitWorkflowError("Supply --original for an existing translation, or --current-is-untranslated after verifying that only preparation occurred.")
            original = original_game.expanduser().resolve() if original_game is not None else project.game_root
            if original == project.game_root and resuming and not current_is_untranslated:
                raise GitWorkflowError("Resume and QA require a separate clean original, or --current-is-untranslated after checking that translation has not begun.")
            bootstrap_repository(project.game_root, original, version, preserve_game_files=True)
            action = "created"
    return {"action": action, **git_status(project)}
