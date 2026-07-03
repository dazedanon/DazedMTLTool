"""Speaker utilities shared across engine modules.

One home for everything speaker-related so ``util/`` does not sprawl:

* **Prefix parsing** - the ``[Speaker]: line`` convention the shared prompt uses.
  Widely imported by the engine modules to strip the tag off translated text.
* **RPG Maker MV/MZ format detection** - :func:`detect_speaker_format` scans a
  project's map/common-event JSON to recommend which speaker flags to enable.
* **WOLF first-line reshaping** - WolfDawn bakes some speaker names into line 1
  of the source; these helpers reshape those lines into ``[Speaker]: line`` for
  translation and restore WOLF's native ``Speaker\nline`` layout afterwards.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from util.paths import DATA_DIR

# ============================================================================
# [Speaker]: prefix parsing
# ----------------------------------------------------------------------------
# Handles RPG Maker control codes inside speaker brackets, e.g.
# ``[\\C[10]Hp Drink\\C[0]]: dialogue`` where inner ``[10]`` must not end the
# match early.
# ============================================================================

# Inner text of [Speaker] - allows \C[n], \c[n], \i[n], \n[actorId], etc.
# The control-code branch (\X[...]) keeps the inner [..] from ending the bracket early.
SPEAKER_BRACKET_INNER = r"(?:\\[A-Za-z]+\[[^\]]*\]|[^\]\n])+"

# A bare [Speaker]: / [Speaker]| / [Speaker]： prefix.
_PREFIX_PATTERN = rf"^\[{SPEAKER_BRACKET_INNER}\]\s*[|:：]\s*"
SPEAKER_PREFIX_RE = re.compile(_PREFIX_PATTERN, re.IGNORECASE)

SPEAKER_TAG_RE = re.compile(
    rf"^\[({SPEAKER_BRACKET_INNER})\]",
    re.IGNORECASE,
)

# Dialogue body after an optional [Speaker]: prefix (text.py lineTextRegex, etc.)
SPEAKER_PREFIX_OPTIONAL_RE = re.compile(
    rf"(?:{_PREFIX_PATTERN})?(.+)",
    re.IGNORECASE,
)


def strip_speaker_prefix(text: str) -> str:
    """Remove a leading ``[Speaker]:`` / ``[Speaker]|`` / ``[Speaker]：`` prefix."""
    if not text:
        return text
    return SPEAKER_PREFIX_RE.sub("", text, count=1)


def extract_dialogue_after_speaker(text: str) -> str | None:
    """Return dialogue body after an optional ``[Speaker]:`` prefix, or ``None``."""
    if not text:
        return None
    m = SPEAKER_PREFIX_OPTIONAL_RE.match(text)
    return m.group(1) if m else None


# ============================================================================
# RPG Maker MV/MZ speaker format detection
# ----------------------------------------------------------------------------
# Mirrors the detection priority of rpgmakermvmz.py searchCodes() exactly:
#
#   Pass 1 - scan 401/405 codes in order:
#     1. \\n<Name> / \\k<Name> inline nametag codes   (always active, no flag needed)
#     2. 【Name】 alone on a 401 line                  (always active, no flag needed)
#     3. 【Name】dialogue on same 401 line             (always active, no flag needed)
#     4. Name「dialogue」 inline quote                 -> INLINE401SPEAKERS
#     5. Short 401 (<40 chars) followed by 401 whose
#        text starts with 「 " ( （ * [               -> FIRSTLINESPEAKERS
#
#   Pass 2 - only if Pass 1 produced no reliable hits:
#     6. 101 code param[0] is a non-empty name string  -> FACENAME101
# ============================================================================

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


# ============================================================================
# WOLF (WolfDawn) first-line speaker reshaping
# ----------------------------------------------------------------------------
# WolfDawn attributes a speaker to every extracted line (``speaker`` /
# ``speaker_src`` fields). For the two "first-line" formats the speaker name is
# baked into line 1 of the ``source`` text, e.g.::
#
#     "市民\nおぉっ！来た！帰ってきたぞ！"        speaker_src = literal_line1_lowconf
#     "セルリア\nほーら、ローザも手を振って。"    speaker_src = literal_line1
#
# When translating we reshape those into ``[Speaker]: body`` (the prompt already
# knows to translate the tag) and, on write-back, restore WOLF's native
# ``Speaker\nbody`` layout so injection stays byte-faithful. Which formats are
# reshaped is configurable (``data/wolf_speakers.json``) so the workflow can
# toggle the high-confidence nameplate and the low-confidence guess separately.
# ============================================================================

# speaker_src values whose name is baked into line 1 of the source text.
FIRSTLINE_SRCS = ("literal_line1", "literal_line1_lowconf")

# Default: reshape both first-line formats. WolfDawn already gates the
# low-confidence one (short line 1, no control codes, no sentence punctuation),
# so it is safe enough to enable by default.
DEFAULT_CONFIG = {
    "literal_line1": True,
    "literal_line1_lowconf": True,
}

CONFIG_PATH = DATA_DIR / "wolf_speakers.json"

# Optional leading window-option prefix (``@<option>\n``) that WolfDawn keeps in
# the raw source; preserved verbatim so the reshaped/restored text still matches.
_WINDOW_PREFIX_RE = re.compile(r"^@[^\n]*\n")


def load_config() -> dict:
    """Return the WOLF speaker-format config, filling in defaults for missing keys."""
    cfg = dict(DEFAULT_CONFIG)
    try:
        if CONFIG_PATH.is_file():
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                for key in DEFAULT_CONFIG:
                    if key in data:
                        cfg[key] = bool(data[key])
    except Exception:
        pass
    return cfg


def save_config(config: dict) -> None:
    """Persist the WOLF speaker-format config (only known keys are written)."""
    out = {key: bool(config.get(key, DEFAULT_CONFIG[key])) for key in DEFAULT_CONFIG}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(out, indent=4), encoding="utf-8")


def is_firstline_enabled(speaker_src: str, config: dict | None = None) -> bool:
    """True if *speaker_src* is a first-line format that is enabled in *config*."""
    if speaker_src not in FIRSTLINE_SRCS:
        return False
    cfg = config if config is not None else DEFAULT_CONFIG
    return bool(cfg.get(speaker_src, DEFAULT_CONFIG.get(speaker_src, False)))


def split_source(source: str, speaker_src: str, config: dict | None = None):
    """Split a first-line-speaker source into (prefix, speaker, body).

    Returns ``None`` when the line is not an enabled first-line-speaker format or
    cannot be split (no body after the name).
    """
    if not isinstance(source, str) or not is_firstline_enabled(speaker_src, config):
        return None
    prefix = ""
    rest = source
    m = _WINDOW_PREFIX_RE.match(source)
    if m:
        prefix = m.group(0)
        rest = source[m.end():]
    if "\n" not in rest:
        return None
    line1, body = rest.split("\n", 1)
    if not line1.strip():
        return None
    return prefix, line1, body


def to_prefixed(speaker: str, body: str) -> str:
    """Build the ``[Speaker]: body`` transport string sent to the model."""
    return f"[{speaker}]: {body}"


def parse_prefixed(text: str):
    """Parse a translated ``[Speaker]: body`` string.

    Returns (speaker, body). ``speaker`` is ``None`` when the model did not emit a
    ``[Speaker]:`` prefix, in which case ``body`` is the whole string.
    """
    if not isinstance(text, str):
        return None, text
    m = SPEAKER_TAG_RE.match(text)
    if not m:
        return None, text
    return m.group(1).strip(), strip_speaker_prefix(text)


def restore_source(prefix: str, speaker: str, body: str) -> str:
    """Rebuild WOLF's native ``Speaker\nbody`` layout (with any window prefix)."""
    return f"{prefix}{speaker}\n{body}"
