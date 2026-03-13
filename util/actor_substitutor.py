"""
Actor Variable Substitutor

RPGMaker uses \\n[X] (stored as \\n[X] in JSON, single backslash after json.load)
to pull actor names dynamically at runtime.  This module:

  1. Builds a map of  actor_id -> name  from Actors.json
     (prefers translated/Actors.json over files/Actors.json so the AI
      receives the target-language name in context)

  2. substitute_in_files()  – walks every .json file inside `files/`,
     replaces  \\n[X]  with the actor's name, writes the file back.
     Returns per-file statistics.

  3. restore_in_translated() – walks every .json file inside `translated/`,
     replaces the substituted name back with  \\n[X].
     Returns per-file statistics.

The rename-able protagonist case is handled automatically: substitute the
default/translated name for context during translation, then restore the
\\n[X] variable so the player's custom name still works at runtime.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

# Pattern that matches \n[X] after json.load() (single literal backslash)
_VAR_RE = re.compile(r"\\n\[(\d+)\]", re.IGNORECASE)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_actor_map(
    files_dir: str | Path = "files",
    translated_dir: str | Path = "translated",
) -> dict[int, str]:
    """Return {actor_id: name}.

    Prefers translated/Actors.json (English names) over files/Actors.json.
    """
    for candidates in (
        Path(translated_dir) / "Actors.json",
        Path(files_dir) / "Actors.json",
    ):
        if candidates.is_file():
            try:
                with open(candidates, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
                actor_map: dict[int, str] = {}
                for entry in data:
                    if not entry or not isinstance(entry, dict):
                        continue
                    actor_id = entry.get("id")
                    name = (entry.get("name") or "").strip()
                    if actor_id is not None and name:
                        actor_map[int(actor_id)] = name
                if actor_map:
                    return actor_map
            except Exception:
                continue
    return {}


def substitute_in_files(
    files_dir: str | Path = "files",
    actor_map: Optional[dict[int, str]] = None,
    translated_dir: str | Path = "translated",
) -> dict:
    """Replace \\n[X] with actor names in all .json files inside *files_dir*.

    If *actor_map* is None it is built automatically via load_actor_map().
    Returns a summary dict:
      {
        "files_modified": int,
        "total_substitutions": int,
        "variables_found": {actor_id: name, ...},
        "errors": [str, ...]
      }
    """
    files_dir = Path(files_dir)
    if actor_map is None:
        actor_map = load_actor_map(files_dir, translated_dir)

    stats = {
        "files_modified": 0,
        "total_substitutions": 0,
        "variables_found": {},
        "errors": [],
    }

    for fp in sorted(files_dir.glob("*.json")):
        try:
            original = fp.read_text(encoding="utf-8-sig")
            data = json.loads(original)
            count = [0]
            found: dict[int, str] = {}

            new_data = _walk(data, actor_map, count, found, substitute=True)

            if count[0] > 0:
                stats["total_substitutions"] += count[0]
                stats["files_modified"] += 1
                stats["variables_found"].update(found)
                out = json.dumps(new_data, ensure_ascii=False, indent=4)
                fp.write_text(out + "\n", encoding="utf-8")
        except Exception as exc:
            stats["errors"].append(f"{fp.name}: {exc}")

    return stats


def restore_in_translated(
    translated_dir: str | Path = "translated",
    actor_map: Optional[dict[int, str]] = None,
    files_dir: str | Path = "files",
) -> dict:
    """Replace actor names back with \\n[X] in all .json files inside *translated_dir*.

    If *actor_map* is None it is built via load_actor_map() which prefers
    translated/Actors.json (the already-translated names).

    Returns a summary dict with the same shape as substitute_in_files().
    """
    translated_dir = Path(translated_dir)
    if actor_map is None:
        actor_map = load_actor_map(files_dir, translated_dir)

    # Build reverse map: name (lowercased) → "\\n[X]"
    # We match case-insensitively so the AI's casing doesn't break restore.
    # We keep the original-case name for display in stats.
    reverse: dict[str, tuple[str, int]] = {}  # lower_name -> (var_string, actor_id)
    for aid, name in actor_map.items():
        if name:
            reverse[name.lower()] = (f"\\n[{aid}]", aid)

    stats = {
        "files_modified": 0,
        "total_substitutions": 0,
        "variables_found": {},
        "errors": [],
    }

    for fp in sorted(translated_dir.glob("*.json")):
        # Never restore inside Actors.json itself — that file has the names
        # as first-class translated data, not as variable stand-ins.
        if fp.name == "Actors.json":
            continue
        try:
            data = json.loads(fp.read_text(encoding="utf-8-sig"))
            count = [0]
            found: dict[int, str] = {}

            new_data = _walk_restore(data, reverse, count, found)

            if count[0] > 0:
                stats["total_substitutions"] += count[0]
                stats["files_modified"] += 1
                stats["variables_found"].update(found)
                out = json.dumps(new_data, ensure_ascii=False, indent=4)
                fp.write_text(out + "\n", encoding="utf-8")
        except Exception as exc:
            stats["errors"].append(f"{fp.name}: {exc}")

    return stats


def scan_variables(
    files_dir: str | Path = "files",
) -> dict[int, int]:
    """Scan *files_dir* and return {actor_id: occurrence_count} without modifying files."""
    counts: dict[int, int] = {}
    for fp in Path(files_dir).glob("*.json"):
        try:
            text = fp.read_text(encoding="utf-8-sig")
            # Search in raw JSON text (\\n[ in file = single \n[ after parse)
            # The raw JSON file stores it as \\n[X] so we search that directly:
            for m in re.finditer(r"\\\\n\[(\d+)\]", text):
                aid = int(m.group(1))
                counts[aid] = counts.get(aid, 0) + 1
        except Exception:
            pass
    return counts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sub_string(s: str, actor_map: dict[int, str], count: list, found: dict) -> str:
    def replace(m: re.Match) -> str:
        aid = int(m.group(1))
        name = actor_map.get(aid)
        if name:
            count[0] += 1
            found[aid] = name
            return name
        return m.group(0)
    return _VAR_RE.sub(replace, s)


def _restore_string(s: str, reverse: dict[str, tuple[str, int]], count: list, found: dict) -> str:
    """Replace actor names with \\n[X] in a translated string."""
    # We need to handle the fact that names can be substrings of other words.
    # Build a single regex alternation sorted by length (longest first) to
    # prevent short names like "Al" matching inside "Alicia".
    if not reverse:
        return s
    pattern = re.compile(
        "|".join(re.escape(name) for name in sorted(reverse.keys(), key=len, reverse=True)),
        re.IGNORECASE,
    )

    def replace(m: re.Match) -> str:
        lower_matched = m.group(0).lower()
        entry = reverse.get(lower_matched)
        if entry:
            var_str, aid = entry
            count[0] += 1
            found[aid] = m.group(0)
            return var_str
        return m.group(0)

    return pattern.sub(replace, s)


def _walk(obj, actor_map, count, found, substitute: bool):
    if isinstance(obj, str):
        return _sub_string(obj, actor_map, count, found)
    if isinstance(obj, list):
        return [_walk(item, actor_map, count, found, substitute) for item in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, actor_map, count, found, substitute) for k, v in obj.items()}
    return obj


def _walk_restore(obj, reverse, count, found):
    if isinstance(obj, str):
        return _restore_string(obj, reverse, count, found)
    if isinstance(obj, list):
        return [_walk_restore(item, reverse, count, found) for item in obj]
    if isinstance(obj, dict):
        return {k: _walk_restore(v, reverse, count, found) for k, v in obj.items()}
    return obj
