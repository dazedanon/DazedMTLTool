"""The game-scoped post-update translation handoff shared by both interfaces."""
from pathlib import Path
from util.skills import load_clipboard_skill
from .git_workflow import inspect_repository


def post_update_handoff(selected):
    game_root = Path(selected).expanduser().resolve()
    status = inspect_repository(game_root)
    if not (
        status.repo_root
        and status.original_exists
        and status.translation_exists
        and status.current_branch == status.translation_branch
        and not status.pending_cherry_pick
        and not status.asset_sync_pending
        and status.applied_update_version
    ):
        raise ValueError(
            "Finish the official update on the registered translated branch before copying this skill."
        )

    version = status.applied_update_version
    metadata = game_root / ".dazedtl"
    skills = metadata / "skills"
    replacements = {
        "{{GAME_ROOT}}": str(game_root),
        "{{VERSION}}": version,
        "{{GLOSSARY_FILE}}": str(metadata / "glossary.txt"),
        "{{GAME_SKILL_FILE}}": str(skills / "game.md"),
        "{{QUIRKS_FILE}}": str(skills / "quirks.md"),
        "{{GAME_SKILLS_DIR}}": str(skills),
    }
    prompt = load_clipboard_skill("post_update_translation.md")
    invalid = [token for token in replacements if token not in prompt]
    if invalid:
        raise ValueError(
            "Post-update translation skill has invalid placeholder(s): "
            + ", ".join(invalid)
        )
    for token, value in replacements.items():
        prompt = prompt.replace(token, value)

    return {"version": version, "prompt": prompt}
