"""
Speaker Format Detector for RPGMaker MV/MZ

Scans map / event files and scores three detection modes:

  INLINE401SPEAKERS  – 401 lines contain  Name「dialogue」
  FIRSTLINESPEAKERS  – a short (< 40 char) 401 followed by 401/405 starting
                        with  「  "  (  （  *  [
  FACENAME101        – a 101 code (Show Text / face cmd) immediately precedes
                       a 401 block

Returns the best mode and confidence scores for each.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# Regex used to detect inline quote speaker: "Name「..." at start of 401 text
_INLINE_RE = re.compile(r"^([^\s「」。、！？…\\\n]{1,20})「")

# Characters that signal the next 401 is dialogue (first-line speaker heuristic)
_DIALOGUE_STARTERS = ("「", '"', "(", "（", "*", "[")

# Minimum number of qualifying events to consider a result reliable
_MIN_HITS = 3


def detect_speaker_format(
    files_dir: str | Path = "files",
    sample_size: int = 20,
) -> dict:
    """Scan up to *sample_size* map files and score speaker detection modes.

    Returns:
    {
        "best_mode": "INLINE401SPEAKERS" | "FIRSTLINESPEAKERS" | "FACENAME101" | "NONE",
        "scores": {
            "INLINE401SPEAKERS":  int,   # raw hit count
            "FIRSTLINESPEAKERS":  int,
            "FACENAME101":        int,
        },
        "total_401_groups": int,   # total dialogue groups examined
        "files_scanned": int,
        "recommended_config": {    # ready to apply to rpgmakermvmz.py
            "FIRSTLINESPEAKERS": bool,
            "INLINE401SPEAKERS": bool,
            "FACENAME101":       bool,
        },
        "confidence": "high" | "medium" | "low",
        "note": str,               # human-readable explanation
    }
    """
    files_dir = Path(files_dir)
    scores = {
        "INLINE401SPEAKERS": 0,
        "FIRSTLINESPEAKERS": 0,
        "FACENAME101": 0,
    }
    total_groups = 0
    files_scanned = 0

    # Collect map files (Maps only, not MapInfos)
    map_files = sorted(
        [p for p in files_dir.glob("Map[0-9]*.json") if p.is_file()],
        key=lambda p: p.stat().st_size,
        reverse=True,  # scan larger maps first for better signal
    )[:sample_size]

    for fp in map_files:
        try:
            with open(fp, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except Exception:
            continue

        files_scanned += 1
        events = data.get("events") or []
        for evt in events:
            if not evt:
                continue
            for page in evt.get("pages") or []:
                cmd_list = (page or {}).get("list") or []
                _score_command_list(cmd_list, scores)
                # Count 401 groups
                i = 0
                while i < len(cmd_list):
                    if cmd_list[i].get("code") in (401, 405):
                        total_groups += 1
                        while i < len(cmd_list) and cmd_list[i].get("code") in (401, 405, -1):
                            i += 1
                        continue
                    i += 1

    # Also scan CommonEvents
    ce_path = files_dir / "CommonEvents.json"
    if ce_path.is_file():
        try:
            with open(ce_path, "r", encoding="utf-8-sig") as fh:
                ce_data = json.load(fh)
            files_scanned += 1
            for entry in ce_data or []:
                if not entry:
                    continue
                cmd_list = entry.get("list") or []
                _score_command_list(cmd_list, scores)
        except Exception:
            pass

    # Determine best mode
    best = max(scores, key=lambda k: scores[k])
    best_score = scores[best]
    second_best = sorted(scores.values(), reverse=True)[1]

    if best_score < _MIN_HITS:
        best_mode = "NONE"
        confidence = "low"
        note = (
            f"No strong speaker pattern detected "
            f"(scanned {files_scanned} file(s), {total_groups} dialogue group(s)). "
            "Consider checking speaker settings manually."
        )
    elif best_score > second_best * 2:
        best_mode = best
        confidence = "high"
        note = (
            f"Strong signal for {best} "
            f"({best_score} hits vs {second_best} for next best, "
            f"{total_groups} dialogue group(s) in {files_scanned} file(s))."
        )
    else:
        best_mode = best
        confidence = "medium"
        note = (
            f"Moderate signal for {best} "
            f"({best_score} hits, {second_best} for next-best mode). "
            "Review a sample of dialogue manually to confirm."
        )

    recommended = {
        "FIRSTLINESPEAKERS": best_mode == "FIRSTLINESPEAKERS",
        "INLINE401SPEAKERS": best_mode == "INLINE401SPEAKERS",
        "FACENAME101":       best_mode == "FACENAME101",
    }

    return {
        "best_mode": best_mode,
        "scores": scores,
        "total_401_groups": total_groups,
        "files_scanned": files_scanned,
        "recommended_config": recommended,
        "confidence": confidence,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _score_command_list(cmd_list: list, scores: dict) -> None:
    """Walk a command list and increment scores for detected patterns."""
    if not cmd_list:
        return

    last_101_face: str | None = None  # face name from most recent 101 cmd

    i = 0
    while i < len(cmd_list):
        cmd = cmd_list[i]
        code = cmd.get("code")
        params = cmd.get("parameters") or []

        # ---- 101: Show Text (face) ----
        if code == 101:
            # params[0] = face name, params[1] = face index
            last_101_face = (params[0] if params else None) or ""
            i += 1
            continue

        # ---- 401 / 405: dialogue line ----
        if code in (401, 405):
            text = (params[0] if params else "") or ""

            # Score INLINE401SPEAKERS
            if _INLINE_RE.match(text):
                scores["INLINE401SPEAKERS"] += 1

            # Score FACENAME101 — if face was set right before this block
            if last_101_face is not None:
                scores["FACENAME101"] += 1
                last_101_face = None  # only count once per block

            # Score FIRSTLINESPEAKERS — short line with no dialogue starters,
            # followed by a 401/405 that starts with a dialogue starter
            if (
                len(text) < 40
                and not any(text.lstrip().startswith(s) for s in _DIALOGUE_STARTERS)
                and _has_japanese(text)
            ):
                j = i + 1
                while j < len(cmd_list) and cmd_list[j].get("code") == -1:
                    j += 1
                if j < len(cmd_list) and cmd_list[j].get("code") in (401, 405):
                    next_text = ((cmd_list[j].get("parameters") or [""])[0]) or ""
                    if next_text.lstrip().startswith(_DIALOGUE_STARTERS):
                        scores["FIRSTLINESPEAKERS"] += 1

            i += 1
            continue

        # Any non-dialogue code resets the face context
        if code not in (-1,):
            last_101_face = None

        i += 1


_JP_RE = re.compile(r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]")


def _has_japanese(text: str) -> bool:
    return bool(_JP_RE.search(text))
