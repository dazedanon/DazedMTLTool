"""
Speaker Format Detector for RPGMaker MV/MZ

Mirrors the detection priority of rpgmakermvmz.py searchCodes() exactly:

  Pass 1 — scan 401/405 codes in order:
    1. \\n<Name> / \\k<Name> inline nametag codes   (always active, no flag needed)
    2. 【Name】 alone on a 401 line                  (always active, no flag needed)
    3. 【Name】dialogue on same 401 line             (always active, no flag needed)
    4. Name「dialogue」 inline quote                 -> INLINE401SPEAKERS
    5. Short 401 (<40 chars) followed by 401 whose
       text starts with 「 " ( （ * [               -> FIRSTLINESPEAKERS

  Pass 2 — only if Pass 1 produced no reliable hits:
    6. 101 code param[0] is a non-empty name string  -> FACENAME101

Returns the best mode and confidence scores.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ── Regexes matching rpgmakermvmz.py exactly ────────────────────────────────

# \\n<Name> / \\k<Name> nametag codes (always active in module)
_NAMETAG_RE = re.compile(
    r"[\\]+[kKnN][wWcCrRrEe]?[\[<](?:[\\]*\w\[\d+\])?(.*?)(?:[\\]*\w\[\d+\])?[>]"
)

# 【Name】 alone on the line (with optional trailing control codes)
_BRACKET_ALONE_RE = re.compile(
    r"^\s*【[^】]+】(?:\s*|(?:[\\]+[A-Za-z]+(?:\[(?:[^\[\]]|\[[^\]]*\])*\])+\s*)*)$"
)

# 【Name】dialogue on the same line
_BRACKET_INLINE_RE = re.compile(r"^\s*【([^】]+)】(.+)", re.DOTALL)

# Inline quote: Name「dialogue…
_INLINE_QUOTE_RE = re.compile(r"^([^\s「」。、！？…\\\n]{1,20})「")

# Dialogue starters that follow a FIRSTLINESPEAKERS name line
_DIALOGUE_STARTERS = ("「", '"', "(", "（", "*", "[")

# Minimum hits to trust a result
_MIN_HITS = 3


def detect_speaker_format(
    files_dir: str | Path = "files",
    sample_size: int = 20,
) -> dict:
    """Scan up to *sample_size* map files and determine the speaker format.

    Returns:
    {
        "best_mode": "INLINE401SPEAKERS" | "FIRSTLINESPEAKERS" | "FACENAME101"
                     | "ALWAYS_ON" | "NONE",
        "scores": {
            "nametag_codes":     int,   # \\n<Name> hits — always handled, no flag
            "bracket_401":       int,   # 【Name】 hits  — always handled, no flag
            "INLINE401SPEAKERS": int,
            "FIRSTLINESPEAKERS": int,
            "FACENAME101":       int,
        },
        "total_401_groups": int,
        "files_scanned": int,
        "recommended_config": {
            "INLINE401SPEAKERS": bool,
            "FIRSTLINESPEAKERS": bool,
            "FACENAME101":       bool,
        },
        "confidence": "high" | "medium" | "low",
        "note": str,
    }
    """
    files_dir = Path(files_dir)
    scores = {
        "nametag_codes":     0,
        "bracket_401":       0,
        "INLINE401SPEAKERS": 0,
        "FIRSTLINESPEAKERS": 0,
        "FACENAME101":       0,
    }
    total_groups = 0
    files_scanned = 0

    # Collect map files (Maps only, not MapInfos), largest first for better signal
    map_files = sorted(
        [p for p in files_dir.glob("Map[0-9]*.json") if p.is_file()],
        key=lambda p: p.stat().st_size,
        reverse=True,
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
                _score_command_list(entry.get("list") or [], scores)
        except Exception:
            pass

    # ── Decision: 401-based patterns first, FACENAME101 only as fallback ────
    always_on_hits = scores["nametag_codes"] + scores["bracket_401"]
    inline_hits    = scores["INLINE401SPEAKERS"]
    first_hits     = scores["FIRSTLINESPEAKERS"]
    face_hits      = scores["FACENAME101"]
    total_401_hits = always_on_hits + inline_hits + first_hits

    recommended = {
        "INLINE401SPEAKERS": False,
        "FIRSTLINESPEAKERS": False,
        "FACENAME101":       False,
    }

    if total_401_hits >= _MIN_HITS:
        if always_on_hits >= _MIN_HITS and always_on_hits >= inline_hits and always_on_hits >= first_hits:
            best_mode  = "ALWAYS_ON"
            confidence = "high" if always_on_hits > (inline_hits + first_hits) else "medium"
            note = (
                f"Speakers detected via \\\\n<Name> codes or 【Name】 brackets "
                f"({always_on_hits} hits) — no extra flags needed. "
                f"INLINE={inline_hits}, FIRSTLINE={first_hits}. "
                f"Scanned {files_scanned} file(s), {total_groups} dialogue group(s)."
            )
        elif inline_hits >= first_hits:
            best_mode  = "INLINE401SPEAKERS"
            recommended["INLINE401SPEAKERS"] = True
            confidence = "high" if inline_hits > first_hits * 2 else "medium"
            note = (
                f"INLINE401SPEAKERS: {inline_hits} hits "
                f"(FIRSTLINESPEAKERS: {first_hits}, always-on: {always_on_hits}). "
                f"Scanned {files_scanned} file(s), {total_groups} dialogue group(s)."
            )
        else:
            best_mode  = "FIRSTLINESPEAKERS"
            recommended["FIRSTLINESPEAKERS"] = True
            confidence = "high" if first_hits > inline_hits * 2 else "medium"
            note = (
                f"FIRSTLINESPEAKERS: {first_hits} hits "
                f"(INLINE401SPEAKERS: {inline_hits}, always-on: {always_on_hits}). "
                f"Scanned {files_scanned} file(s), {total_groups} dialogue group(s)."
            )
    elif face_hits >= _MIN_HITS:
        best_mode  = "FACENAME101"
        recommended["FACENAME101"] = True
        confidence = "high" if face_hits > _MIN_HITS * 2 else "medium"
        note = (
            f"No 401-based speaker pattern found (401 hits: {total_401_hits}). "
            f"FACENAME101 recommended based on {face_hits} 101-code name hits. "
            f"Scanned {files_scanned} file(s), {total_groups} dialogue group(s)."
        )
    else:
        best_mode  = "NONE"
        confidence = "low"
        note = (
            f"No reliable speaker pattern detected "
            f"(401 hits: {total_401_hits}, FACENAME101 hits: {face_hits}). "
            f"Scanned {files_scanned} file(s), {total_groups} dialogue group(s). "
            "Check speaker settings manually."
        )

    return {
        "best_mode":          best_mode,
        "scores":             scores,
        "total_401_groups":   total_groups,
        "files_scanned":      files_scanned,
        "recommended_config": recommended,
        "confidence":         confidence,
        "note":               note,
    }


# ── Internal helpers ─────────────────────────────────────────────────────────

def _score_command_list(cmd_list: list, scores: dict) -> None:
    """Walk a command list and score speaker patterns in module priority order."""
    if not cmd_list:
        return

    i = 0
    while i < len(cmd_list):
        cmd    = cmd_list[i]
        code   = cmd.get("code")
        params = cmd.get("parameters") or []

        # ── 101: Show Text / face name ────────────────────────────────────────
        if code == 101:
            # FACENAME101: param[0] is a non-empty face-name string
            face = params[0] if params else ""
            if isinstance(face, str) and face.strip():
                scores["FACENAME101"] += 1
            i += 1
            continue

        # ── 401 / 405: dialogue line ──────────────────────────────────────────
        if code in (401, 405):
            text = (params[0] if params else "") or ""

            # 1. \\n<Name> nametag codes (always active — no flag needed)
            if _NAMETAG_RE.search(text):
                scores["nametag_codes"] += 1
                i += 1
                continue  # module strips the nametag before further processing

            # 2+3. 【Name】 alone on line, or 【Name】dialogue inline (always active)
            if _BRACKET_ALONE_RE.match(text) or _BRACKET_INLINE_RE.match(text):
                scores["bracket_401"] += 1
                i += 1
                continue

            # 4. INLINE401SPEAKERS: Name「dialogue
            if _INLINE_QUOTE_RE.match(text):
                scores["INLINE401SPEAKERS"] += 1
                i += 1
                continue

            # 5. FIRSTLINESPEAKERS: short line followed by 401 starting with
            #    a dialogue-starter character
            if (
                len(text) < 40
                and _has_japanese(text)
                and not any(text.lstrip().startswith(s) for s in _DIALOGUE_STARTERS)
            ):
                j = i + 1
                while j < len(cmd_list) and cmd_list[j].get("code") == -1:
                    j += 1
                if j < len(cmd_list) and cmd_list[j].get("code") in (401, 405):
                    next_params   = cmd_list[j].get("parameters") or []
                    next_text     = (next_params[0] if next_params else "") or ""
                    # Strip leading RPGMaker control codes before checking starter
                    next_stripped = re.sub(
                        r"^(?:[\\]+[^cCnNiIkKvVSs{}]+?\[[\d\w\W]+?\]?\])+",
                        "", next_text,
                    ).lstrip()
                    if next_stripped and next_stripped[0] in _DIALOGUE_STARTERS:
                        scores["FIRSTLINESPEAKERS"] += 1

            i += 1
            continue

        i += 1


_JP_RE = re.compile(
    r"[\u3000-\u303F\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uF900-\uFAFF\uFF61-\uFF9F]"
)


def _has_japanese(text: str) -> bool:
    return bool(_JP_RE.search(text))
