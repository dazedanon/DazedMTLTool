"""Skill and prompt loaders (editable files under ``data/skills/``)."""

from __future__ import annotations

from util.skills.contexts import ctx, reload_contexts
from util.skills.setup import load_project_setup, skills_dir
from util.skills.system import (
    game_skill_path_for_game,
    load_system_prompt,
    quirks_path_for_game,
)

__all__ = [
    "ctx",
    "game_skill_path_for_game",
    "load_project_setup",
    "load_system_prompt",
    "quirks_path_for_game",
    "reload_contexts",
    "skills_dir",
]
