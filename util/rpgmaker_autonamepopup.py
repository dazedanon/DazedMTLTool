"""Read AutoNamePopup's declared face/index names without executing JavaScript."""

from __future__ import annotations

import json
from pathlib import Path

from util.rpgmaker_plugin_registry import plugin_entries


def parse_name_keys(content: str) -> dict[tuple[str, int], str]:
    """Decode RPG Maker's nested struct JSON and the plugin's expression ranges.

    Only explicit nameKeys are used. Actor face guesses and runtime plugin
    commands are deliberately outside this static mapping.
    """
    mapping = {}
    for plugin in plugin_entries(content):
        if plugin.get("name") != "AutoNamePopup" or plugin.get("status") is not True:
            continue
        params = plugin.get("parameters") or {}
        if not isinstance(params, dict):
            raise ValueError("AutoNamePopup parameters must be an object")
        entries = params.get("nameKeys") or "[]"
        entries = json.loads(entries) if isinstance(entries, str) else entries
        if not isinstance(entries, list):
            raise ValueError("AutoNamePopup nameKeys must be an array")
        for entry in entries:
            entry = json.loads(entry) if isinstance(entry, str) else entry
            if not isinstance(entry, dict):
                raise ValueError("AutoNamePopup nameKeys must contain objects")
            face, name = entry.get("faceName"), entry.get("name")
            if not isinstance(face, str) or not isinstance(name, str):
                continue
            index = int(entry.get("faceIndex") or 0)
            count = int(entry.get("facialExpressions") or 0)
            if count <= 0:
                field = "actorFacialExpressions" if count == -1 else "characterFacialExpressions"
                count = int(params.get(field) or 1)
            if not face or index < 0 or count < 1 or index + count > 8:
                continue
            for offset in range(count):
                # Later declarations override earlier ones, as in the plugin.
                mapping[face, index + offset] = name
    return mapping


def load_name_keys(game_root: str) -> dict[tuple[str, int], str]:
    """Read the active game registry, or a manually supplied files/plugins.js."""
    paths = (
        (Path(game_root) / "www/js/plugins.js", Path(game_root) / "js/plugins.js")
        if game_root else (Path("files/plugins.js"),)
    )
    for path in paths:
        if path.is_file():
            return parse_name_keys(path.read_text(encoding="utf-8-sig"))
    return {}
