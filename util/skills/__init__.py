"""Skill and prompt loaders (editable files under ``data/skills/``)."""

from __future__ import annotations

from util.skills.contexts import ctx, reload_contexts
from util.skills.setup import load_clipboard_skill, load_project_setup, skills_dir
from util.skills.system import (
    custom_skill_path_for_game,
    game_skill_path_for_game,
    list_custom_skill_paths,
    load_system_prompt,
    migrate_game_skill_text,
    quirks_path_for_game,
    sanitize_custom_skill_stem,
)

__all__ = [
    "ctx",
    "custom_skill_path_for_game",
    "game_skill_path_for_game",
    "list_custom_skill_paths",
    "load_clipboard_skill",
    "load_project_setup",
    "load_system_prompt",
    "migrate_game_skill_text",
    "quirks_path_for_game",
    "reload_contexts",
    "sanitize_custom_skill_stem",
    "skills_dir",
]
