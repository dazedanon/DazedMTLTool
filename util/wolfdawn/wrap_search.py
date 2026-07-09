"""Search translated WolfDawn JSON for text to fix wrapping.

Paste in-game text, open the matching line, then wrap that line or every
overflowing line in the same group:

* database sheet / names category / Game.dat file
* map / CommonEvent: group = ``speaker_src`` format (spoken / ui / …) across
  all map + CommonEvent JSON; shared width/font remembered per format

Dialogue lines with ``speaker_src`` ``literal_line1`` / ``literal_line1_lowconf``
keep the nameplate on its own first line (``Celria\\n…``); only the body is
reflowed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import util.dazedwrap as dazedwrap
from util.wolfdawn.selective_wrap import line_needs_wrap, wrap_line_text

WRAP_PROFILE_NAME = "wrap_profile.json"
DEFAULT_WRAP_WIDTH = 36
# Legacy single-bucket key (migrated to spoken format on read).
DIALOGUE_PROFILE_KEY = "__dialogue__"

_APOSTROPHE_NORMALIZE = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "'",
        "\u02bc": "'",
        "`": "'",
    }
)


def wrap_format_key(speaker_src: str | None) -> str:
    """Profile key for shared wrap geometry by WolfDawn ``speaker_src``.

    Same detection class ≈ same on-screen box across maps/CommonEvent.
    ``literal_line1`` and ``literal_line1_lowconf`` share one spoken-dialogue
    bucket; other tags (``ui``, ``narration``, ``choice``, …) each get their own.
    """
    src = str(speaker_src or "").strip().lower() or "default"
    if src in ("literal_line1", "literal_line1_lowconf"):
        return "__format:spoken__"
    safe = re.sub(r"[^a-z0-9_]+", "_", src).strip("_") or "default"
    return f"__format:{safe}__"


def wrap_format_label(speaker_src: str | None) -> str:
    """Short UI label for the format bucket of *speaker_src*."""
    key = wrap_format_key(speaker_src)
    if key == "__format:spoken__":
        return "spoken dialogue (Name\\nbody)"
    tag = key.removeprefix("__format:").removesuffix("__")
    return f"format:{tag}"


@dataclass
class WrapHit:
    """One searchable line in translated JSON."""

    json_file: str
    kind: str
    sheet_name: str
    row: int | None
    field_name: str
    text: str
    max_line_len: int
    scene_index: int | None = None
    line_index: int | None = None
    map_file: str | None = None

    @property
    def hit_id(self) -> dict[str, Any]:
        """Stable locator stored in the UI."""
        loc: dict[str, Any] = {
            "json_file": self.json_file,
            "kind": self.kind,
            "sheet_name": self.sheet_name,
            "field_name": self.field_name,
        }
        if self.row is not None:
            loc["row"] = self.row
        if self.kind == "names" and self.row is not None:
            loc["name_index"] = self.row
        if self.scene_index is not None:
            loc["scene_index"] = self.scene_index
        if self.line_index is not None:
            loc["line_index"] = self.line_index
        return loc

    def summary(self, width: int = 0) -> str:
        overflow = ""
        if width > 0 and self.max_line_len > width:
            overflow = " · overflow"
        elif self.max_line_len:
            overflow = f" · {self.max_line_len} chars"
        preview = self.text.replace("\n", " ").replace("\r", " ").strip()
        if len(preview) > 120:
            preview = preview[:120] + "…"
        if self.kind == "db":
            loc = f"row {self.row} · {self.field_name}"
        elif self.kind == "names":
            loc = f"entry #{self.row}"
        elif self.kind == "gamedat":
            loc = self.field_name or f"line {self.line_index}"
        else:
            loc = self.field_name or self.map_file or self.json_file
        # Translated text first so it stays visible even if the row is short;
        # metadata is secondary.
        return (
            f"{preview}\n"
            f"{self.sheet_name} · {self.json_file} · {loc}{overflow}"
        )


def wrap_profile_path(work_dir: str | Path) -> Path:
    return Path(work_dir) / WRAP_PROFILE_NAME


def load_wrap_profile(work_dir: str | Path) -> dict[str, Any]:
    path = wrap_profile_path(work_dir)
    if not path.is_file():
        return {"default_width": DEFAULT_WRAP_WIDTH, "sheets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"default_width": DEFAULT_WRAP_WIDTH, "sheets": {}}
        data.setdefault("default_width", DEFAULT_WRAP_WIDTH)
        data.setdefault("sheets", {})
        return data
    except Exception:
        return {"default_width": DEFAULT_WRAP_WIDTH, "sheets": {}}


def save_wrap_profile(work_dir: str | Path, profile: dict[str, Any]) -> None:
    path = wrap_profile_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def get_sheet_width(
    profile: dict[str, Any],
    sheet_name: str,
    *,
    default: int | None = None,
) -> int:
    sheets = profile.get("sheets") or {}
    entry = sheets.get(sheet_name)
    if isinstance(entry, dict) and entry.get("width"):
        try:
            return int(entry["width"])
        except (TypeError, ValueError):
            pass
    if default is not None:
        return default
    try:
        return int(profile.get("default_width") or DEFAULT_WRAP_WIDTH)
    except (TypeError, ValueError):
        return DEFAULT_WRAP_WIDTH


def set_sheet_width(
    work_dir: str | Path,
    sheet_name: str,
    width: int,
    *,
    json_file: str,
    max_lines: int | None = None,
) -> None:
    profile = load_wrap_profile(work_dir)
    sheets = profile.setdefault("sheets", {})
    entry = sheets.get(sheet_name)
    if not isinstance(entry, dict):
        entry = {}
        sheets[sheet_name] = entry
    entry["width"] = int(width)
    entry["json_file"] = json_file
    if max_lines is not None and int(max_lines) > 0:
        entry["max_lines"] = int(max_lines)
    elif "max_lines" in entry and max_lines == 0:
        entry.pop("max_lines", None)
    profile["default_width"] = profile.get("default_width", DEFAULT_WRAP_WIDTH)
    save_wrap_profile(work_dir, profile)


def get_sheet_max_lines(
    profile: dict[str, Any],
    sheet_name: str,
    *,
    default: int = 0,
) -> int:
    sheets = profile.get("sheets") or {}
    entry = sheets.get(sheet_name)
    if isinstance(entry, dict) and entry.get("max_lines") is not None:
        try:
            return int(entry["max_lines"])
        except (TypeError, ValueError):
            pass
    return default


def get_format_geometry(
    profile: dict[str, Any],
    speaker_src: str | None,
) -> dict[str, int]:
    """Return shared wrap settings for this ``speaker_src`` format bucket."""
    sheets = profile.get("sheets") or {}
    key = wrap_format_key(speaker_src)
    entry = sheets.get(key)
    # Migrate legacy single dialogue bucket → spoken format only.
    if not isinstance(entry, dict) and key == "__format:spoken__":
        entry = sheets.get(DIALOGUE_PROFILE_KEY)
    out: dict[str, int] = {}
    if not isinstance(entry, dict):
        return out
    for field in ("width", "max_lines", "font"):
        if entry.get(field) is None:
            continue
        try:
            out[field] = int(entry[field])
        except (TypeError, ValueError):
            continue
    return out


def set_format_geometry(
    work_dir: str | Path,
    speaker_src: str | None,
    *,
    width: int | None = None,
    max_lines: int | None = None,
    font: int | None = None,
) -> None:
    """Persist wrap settings for one ``speaker_src`` format (map + CommonEvent)."""
    profile = load_wrap_profile(work_dir)
    sheets = profile.setdefault("sheets", {})
    key = wrap_format_key(speaker_src)
    entry = sheets.get(key)
    if not isinstance(entry, dict):
        entry = {"json_file": key, "speaker_src": str(speaker_src or "")}
        sheets[key] = entry
    if width is not None and int(width) > 0:
        entry["width"] = int(width)
    if max_lines is not None:
        if int(max_lines) > 0:
            entry["max_lines"] = int(max_lines)
        else:
            entry.pop("max_lines", None)
    if font is not None:
        if int(font) > 0:
            entry["font"] = int(font)
        else:
            entry.pop("font", None)
    entry["speaker_src"] = str(speaker_src or "")
    save_wrap_profile(work_dir, profile)


# Back-compat aliases (spoken / legacy __dialogue__).
def get_dialogue_geometry(profile: dict[str, Any]) -> dict[str, int]:
    return get_format_geometry(profile, "literal_line1")


def set_dialogue_geometry(
    work_dir: str | Path,
    *,
    width: int | None = None,
    max_lines: int | None = None,
    font: int | None = None,
) -> None:
    set_format_geometry(
        work_dir,
        "literal_line1",
        width=width,
        max_lines=max_lines,
        font=font,
    )


def split_nameplate_body(
    text: str,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> tuple[str, str, str]:
    """Split ``Name\\nbody`` dialogue into ``(prefix, nameplate, body)``.

    Uses WolfDawn ``speaker_src`` (``literal_line1`` / ``literal_line1_lowconf``)
    when enabled. Falls back to matching the ``speaker`` field to line 1.
    When there is no nameplate, returns ``("", "", text)``.
    """
    from util import speakers as wolf_speakers

    if not isinstance(text, str) or not text:
        return "", "", text if isinstance(text, str) else ""

    # Normalize newlines so ``\\r\\n`` nameplates still split cleanly.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    src = str(speaker_src or "")
    if wolf_speakers.is_firstline_enabled(src):
        parts = wolf_speakers.split_source(text, src)
        if parts is not None:
            prefix, line1, body = parts
            return prefix, line1, body

    name = str(speaker or "").strip()
    if name and "\n" in text:
        prefix, rest = wolf_speakers.split_window_prefix(text)
        line1, body = rest.split("\n", 1)
        # Match plain name or ``\\f[N]Name`` nameplate to the speaker field.
        plate_core = re.sub(r"^(\\f\[\d+\])+", "", line1).strip()
        if plate_core == name or line1.strip() == name:
            return prefix, line1, body
    return "", "", text


def join_nameplate_body(prefix: str, nameplate: str, body: str) -> str:
    """Reassemble a nameplate dialogue line."""
    if nameplate:
        return f"{prefix}{nameplate}\n{body}"
    return f"{prefix}{body}"


def _reject_empty_body_result(original: str, new_text: str) -> str:
    """Never allow wrap/font passes to drop a previously non-empty body.

    A past group-wrap bug left thousands of spoken lines as ``\\f[N]Name\\n`` with
    an empty body. Refuse that class of result and keep *original*.
    """
    if not isinstance(original, str) or not isinstance(new_text, str):
        return original if isinstance(original, str) else new_text
    if "\n" not in original:
        return new_text
    old_body = original.split("\n", 1)[1]
    if not old_body.strip():
        return new_text
    if "\n" not in new_text:
        return original
    new_body = new_text.split("\n", 1)[1]
    if not new_body.strip():
        return original
    return new_text


def wrap_preserving_nameplate(
    text: str,
    width: int,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> str:
    """Word-wrap *text*, keeping a leading speaker nameplate on its own line."""
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return text if isinstance(text, str) else ""
    prefix, nameplate, body = split_nameplate_body(
        text, speaker_src=speaker_src, speaker=speaker
    )
    if not nameplate:
        return wrap_line_text(text, width)
    if not body.strip():
        return text
    wrapped_body = wrap_line_text(body, width)
    if not wrapped_body.strip() and body.strip():
        return text
    return _reject_empty_body_result(
        text, join_nameplate_body(prefix, nameplate, wrapped_body)
    )


def line_needs_wrap_preserving_nameplate(
    text: str,
    width: int,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> bool:
    """Overflow check that ignores the nameplate line (body only when present)."""
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return False
    prefix, nameplate, body = split_nameplate_body(
        text, speaker_src=speaker_src, speaker=speaker
    )
    check = body if nameplate else text
    return line_needs_wrap(check, width)


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().translate(_APOSTROPHE_NORMALIZE).split())


def _normalize_match_text(text: str) -> str:
    return text.lower().translate(_APOSTROPHE_NORMALIZE)


def _text_matches(text: str, query_norm: str) -> bool:
    if not query_norm or not isinstance(text, str):
        return False
    hay = _normalize_match_text(text)
    if query_norm in hay:
        return True
    # In-game UI often hides line breaks; allow matching across newlines.
    collapsed = " ".join(hay.split())
    return query_norm in collapsed


def _iter_search_dirs(
    translated_dir: Path,
    files_dir: Path | None,
    extra_dirs: Sequence[str | Path] | None = None,
) -> list[Path]:
    dirs: list[Path] = []
    for candidate in (translated_dir, files_dir, *(extra_dirs or ())):
        if candidate is None:
            continue
        p = Path(candidate)
        if p.is_dir() and p not in dirs:
            dirs.append(p)
    return dirs


def search_translated_text(
    query: str,
    translated_dir: str | Path,
    *,
    files_dir: str | Path | None = None,
    extra_dirs: Sequence[str | Path] | None = None,
    limit: int = 50,
) -> list[WrapHit]:
    """Find lines containing *query* in translated, files/, and optional extra dirs."""
    if not query.strip():
        return []
    q = _normalize_query(query)
    hits: list[WrapHit] = []
    tdir = Path(translated_dir)
    fdir = Path(files_dir) if files_dir else tdir.parent / "files"
    seen: set[tuple] = set()

    for base in _iter_search_dirs(tdir, fdir, extra_dirs):
        for path in sorted(base.glob("*.json")):
            doc = _load_json(path)
            if not doc:
                continue
            kind = doc.get("kind")
            jf = path.name

            if kind == "db":
                for group in doc.get("groups") or []:
                    sheet = str(group.get("typeName") or "")
                    for line in group.get("lines") or []:
                        text = line.get("text")
                        if not _text_matches(text, q):
                            continue
                        row = line.get("row")
                        field = str(line.get("fieldName") or "")
                        key = (jf, sheet, row, field)
                        if key in seen:
                            continue
                        seen.add(key)
                        hits.append(
                            WrapHit(
                                json_file=jf,
                                kind="db",
                                sheet_name=sheet,
                                row=int(row) if row is not None else None,
                                field_name=field,
                                text=str(text),
                                max_line_len=dazedwrap.max_line_visible_length(str(text)),
                            )
                        )
            elif kind == "names":
                for idx, entry in enumerate(doc.get("names") or []):
                    if not isinstance(entry, dict):
                        continue
                    text = entry.get("text")
                    source = entry.get("source")
                    # Match translated text (preferred) or JP source so either side finds the row.
                    if not (_text_matches(text, q) or _text_matches(source, q)):
                        continue
                    note = str(entry.get("note") or "names.json")
                    display = str(text) if isinstance(text, str) and text.strip() else str(source or "")
                    key = (jf, "names", idx)
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append(
                        WrapHit(
                            json_file=jf,
                            kind="names",
                            sheet_name=note,
                            row=idx,
                            field_name=f"entry {idx}",
                            text=display,
                            max_line_len=dazedwrap.max_line_visible_length(display),
                        )
                    )
            elif kind == "gamedat":
                for li, line in enumerate(doc.get("lines") or []):
                    if not isinstance(line, dict):
                        continue
                    text = line.get("text")
                    if not _text_matches(text, q):
                        continue
                    key = (jf, "gamedat", li)
                    if key in seen:
                        continue
                    seen.add(key)
                    field = str(line.get("key") or line.get("fieldName") or f"line {li}")
                    hits.append(
                        WrapHit(
                            json_file=jf,
                            kind="gamedat",
                            sheet_name="Game.dat",
                            row=li,
                            field_name=field,
                            text=str(text),
                            max_line_len=dazedwrap.max_line_visible_length(str(text)),
                            line_index=li,
                        )
                    )
            elif kind in ("map", "common"):
                label = doc.get("file") or jf
                sheet = "CommonEvent" if kind == "common" else str(label)
                for si, scene in enumerate(doc.get("scenes") or []):
                    for li, line in enumerate(scene.get("lines") or []):
                        text = line.get("text")
                        if not _text_matches(text, q):
                            continue
                        key = (jf, si, li)
                        if key in seen:
                            continue
                        seen.add(key)
                        speaker = str(line.get("speaker") or "")
                        hits.append(
                            WrapHit(
                                json_file=jf,
                                kind=kind,
                                sheet_name=sheet,
                                row=scene.get("event"),
                                field_name=speaker or f"scene {si} line {li}",
                                text=str(text),
                                max_line_len=dazedwrap.max_line_visible_length(str(text)),
                                scene_index=si,
                                line_index=li,
                                map_file=str(label) if kind == "map" else None,
                            )
                        )
            if len(hits) >= limit:
                return hits
    return hits


def wrap_preview_info(
    text: str,
    width: int,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> dict[str, Any]:
    """Return wrapped text and metrics for the Step 7 live preview."""
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return {
            "wrapped": text if isinstance(text, str) else "",
            "needs_wrap": False,
            "longest": 0,
            "input_line_count": 0,
            "output_line_count": 0,
            "line_stats": [],
        }
    wrapped = wrap_preserving_nameplate(
        text, width, speaker_src=speaker_src, speaker=speaker
    )
    _, nameplate, body = split_nameplate_body(
        text, speaker_src=speaker_src, speaker=speaker
    )
    # Metrics / overflow are about the dialogue body (nameplate is outside the box).
    measure_in = body if nameplate else text
    measure_out = (
        split_nameplate_body(wrapped, speaker_src=speaker_src, speaker=speaker)[2]
        if nameplate
        else wrapped
    )
    norm_in = measure_in.replace("\r\n", "\n").replace("\r", "\n")
    norm_out = measure_out.replace("\r\n", "\n").replace("\r", "\n")
    in_lines = norm_in.split("\n") if norm_in else [""]
    out_lines = norm_out.split("\n") if norm_out else [""]
    line_stats: list[dict[str, Any]] = []
    for i, line in enumerate(in_lines):
        vis = dazedwrap.max_line_visible_length(line)
        line_stats.append(
            {
                "line": i + 1,
                "visible": vis,
                "overflow": max(0, vis - width),
                "needs_wrap": vis > width,
            }
        )
    longest = max((s["visible"] for s in line_stats), default=0)
    needs_wrap = wrapped != text or any(s["needs_wrap"] for s in line_stats)
    return {
        "wrapped": wrapped,
        "needs_wrap": needs_wrap,
        "longest": longest,
        "input_line_count": len(in_lines),
        "output_line_count": len(out_lines),
        "line_stats": line_stats,
        "nameplate": nameplate,
    }


def wrap_preview_summary(
    text: str,
    width: int,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> str:
    """One-line status for the preview header."""
    info = wrap_preview_info(
        text, width, speaker_src=speaker_src, speaker=speaker
    )
    if not isinstance(text, str) or not text.strip():
        return ""
    longest = int(info["longest"])
    plate = f" (nameplate kept)" if info.get("nameplate") else ""
    if not info["needs_wrap"]:
        return (
            f"Fits at width {width} (longest body line {longest} visible chars)"
            f"{plate}."
        )
    return (
        f"Will wrap body to {info['output_line_count']} line(s) at width {width} "
        f"(longest body line {longest} visible chars){plate}."
    )


# Approximate System DB Type 12 colours for preview only (games-specific in real Wolf).
_WOLF_PREVIEW_COLORS: dict[int, str] = {
    0: "#d4d4d4",
    1: "#ff6b6b",
    2: "#4ecdc4",
    3: "#ffe66d",
    4: "#95e1a3",
    5: "#a78bfa",
    6: "#f9a8d4",
    7: "#67e8f9",
    8: "#fdba74",
    9: "#86efac",
    10: "#f87171",
    13: "#c4b5fd",  # common ruby colour slot
    16: "#fbbf24",
    18: "#f472b6",
    19: "#c8b89a",  # body / restore (cafe-style games)
    20: "#93c5fd",
    21: "#f0c040",  # emphasis / place names
}

_WOLF_PREVIEW_TOKEN_RE = re.compile(
    r"\\c\[(\d+)\]|"
    r"\\f\[(\d+)\]|"
    r"\\r\[[^\]]*\]|"
    r"\\[A-Za-z]+\[[^\]]*\]|"
    r"\\."
)


def wolf_preview_color(index: int, *, default: str = "#d4d4d4") -> str:
    """Return a CSS hex colour for Wolf ``\\c[index]`` (preview approximation)."""
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return default
    if idx in _WOLF_PREVIEW_COLORS:
        return _WOLF_PREVIEW_COLORS[idx]
    # Stable distinct hue for unknown System DB slots.
    hue = (idx * 47) % 360
    return f"hsl({hue}, 55%, 68%)"


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_wolf_text_html(
    text: str,
    *,
    default_color: str = "#d4d4d4",
    default_font_px: int = 18,
) -> str:
    """Render Wolf text as HTML, applying ``\\c`` / ``\\f`` and hiding other codes.

    Used by the Step 7 wrap preview so emphasis like
    ``\\c[21]\\f[20]cafe\\c[19]\\f[18]`` shows as larger coloured glyphs instead
    of raw escape sequences. Colours are approximate (System DB Type 12 is
    per-game).
    """
    if not isinstance(text, str) or not text:
        return ""
    color = default_color
    font_px = max(8, int(default_font_px))
    parts: list[str] = []
    last = 0

    def _flush(literal: str) -> None:
        if not literal:
            return
        parts.append(
            f'<span style="color:{color};font-size:{font_px}px">'
            f"{_html_escape(literal)}</span>"
        )

    for m in _WOLF_PREVIEW_TOKEN_RE.finditer(text):
        if m.start() > last:
            _flush(text[last : m.start()])
        raw = m.group(0)
        if raw.startswith(r"\c[") and m.group(1) is not None:
            color = wolf_preview_color(int(m.group(1)), default=default_color)
        elif raw.startswith(r"\f[") and m.group(2) is not None:
            font_px = max(8, int(m.group(2)))
        # Other codes (\\r, \\^, \\cdb, …) are omitted from the visual preview.
        last = m.end()
    if last < len(text):
        _flush(text[last:])
    return "".join(parts)


def format_wrap_preview_html(
    text: str,
    width: int,
    *,
    body_font: int | None = None,
    speaker_src: str = "",
    speaker: str = "",
) -> str:
    """Rich HTML wrap preview: line gutters + simulated ``\\c`` / ``\\f`` styling.

    When *body_font* is set, proportionally scale every ``\\f[N]`` (and ensure a
    leading body size) before wrapping/rendering - same as Manual wrap would do.
    Nameplate lines stay on their own first row in the preview.
    """
    from util.wolfdawn import codes as wolf_codes

    preview_text = text if isinstance(text, str) else ""
    plate_kw = {"speaker_src": speaker_src, "speaker": speaker}
    prefix, nameplate, body = split_nameplate_body(preview_text, **plate_kw)
    work = body if nameplate else preview_text
    if body_font is not None and int(body_font) > 0 and work.strip():
        work, _ = wolf_codes.scale_font_sizes(work, int(body_font))
        preview_text = (
            join_nameplate_body(prefix, nameplate, work) if nameplate else work
        )

    info = wrap_preview_info(preview_text, width, **plate_kw)
    wrapped = info.get("wrapped") or ""
    if not wrapped:
        return ""

    default_px = (
        int(body_font)
        if body_font is not None and int(body_font) > 0
        else wolf_codes.infer_base_font_size(work if nameplate else preview_text, default=18)
    )
    lines = wrapped.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows: list[str] = []
    for i, line in enumerate(lines):
        is_nameplate = bool(nameplate) and i == 0 and line == nameplate
        vis = dazedwrap.max_line_visible_length(line)
        # Nameplate sits outside the message box - never flag as overflow.
        overflow = (not is_nameplate) and vis > width > 0
        gutter_color = "#ce9178" if overflow else ("#c8b89a" if is_nameplate else "#858585")
        marker = "⚠" if overflow else ("◆" if is_nameplate else "&nbsp;")
        gutter = (
            f'<span style="color:{gutter_color};font-family:monospace;font-size:11px">'
            f"{marker} {i + 1:2d} ({vis:2d})&nbsp;&nbsp;</span>"
        )
        body_html = render_wolf_text_html(
            line, default_color="#d4d4d4", default_font_px=default_px
        )
        rows.append(
            f'<div style="white-space:pre-wrap;line-height:1.35;margin:0 0 2px 0">'
            f"{gutter}{body_html}</div>"
        )
    return (
        '<div style="font-family:\'Segoe UI\',\'Noto Sans\',sans-serif;'
        'background-color:transparent">'
        + "".join(rows)
        + "</div>"
    )


def locate_line(doc: dict[str, Any], hit_id: dict[str, Any]) -> dict[str, Any] | None:
    """Return the live line dict for *hit_id* inside *doc*."""
    kind = hit_id.get("kind")
    if kind == "db":
        sheet = hit_id.get("sheet_name")
        row = hit_id.get("row")
        field = hit_id.get("field_name")
        for group in doc.get("groups") or []:
            if str(group.get("typeName") or "") != sheet:
                continue
            for line in group.get("lines") or []:
                if line.get("row") == row and str(line.get("fieldName") or "") == field:
                    return line
        return None
    if kind in ("map", "common"):
        si = hit_id.get("scene_index")
        li = hit_id.get("line_index")
        scenes = doc.get("scenes") or []
        if si is None or li is None or si >= len(scenes):
            return None
        lines = scenes[si].get("lines") or []
        if li >= len(lines):
            return None
        return lines[li]
    if kind == "names":
        idx = hit_id.get("name_index", hit_id.get("row"))
        names = doc.get("names") or []
        if idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(names):
            return None
        entry = names[idx]
        return entry if isinstance(entry, dict) else None
    if kind == "gamedat":
        li = hit_id.get("line_index", hit_id.get("row"))
        lines = doc.get("lines") or []
        if li is None or not isinstance(li, int) or li < 0 or li >= len(lines):
            return None
        line = lines[li]
        return line if isinstance(line, dict) else None
    return None


def load_hit_from_id(
    translated_dir: str | Path,
    hit_id: dict[str, Any],
    *,
    files_dir: str | Path | None = None,
    extra_dirs: Sequence[str | Path] | None = None,
) -> tuple[Path | None, dict[str, Any] | None, dict[str, Any] | None]:
    """Load JSON path, document, and line dict for *hit_id*."""
    jf = hit_id.get("json_file")
    if not jf:
        return None, None, None
    tdir = Path(translated_dir)
    fdir = Path(files_dir) if files_dir else None
    for base in _iter_search_dirs(tdir, fdir, extra_dirs):
        path = base / str(jf)
        if not path.is_file():
            continue
        doc = _load_json(path)
        if not doc:
            continue
        line = locate_line(doc, hit_id)
        if line is not None:
            return path, doc, line
    return None, None, None


def save_document(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(doc, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )


def wrap_line_in_doc(line: dict[str, Any], width: int) -> bool:
    """Wrap one line's ``text``; return True if changed."""
    text = line.get("text")
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return False
    new_text = wrap_preserving_nameplate(
        text,
        width,
        speaker_src=str(line.get("speaker_src") or ""),
        speaker=str(line.get("speaker") or ""),
    )
    if new_text == text:
        return False
    line["text"] = new_text
    return True


def count_soft_lines(text: str) -> int:
    """Number of soft-wrapped lines in *text* (at least 1 for non-empty)."""
    if not isinstance(text, str) or not text:
        return 0
    norm = text.replace("\r\n", "\n").replace("\r", "\n")
    return max(1, len(norm.split("\n")))


def count_body_soft_lines(
    text: str,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> int:
    """Soft line count for the message body (excludes nameplate when present)."""
    _, nameplate, body = split_nameplate_body(
        text, speaker_src=speaker_src, speaker=speaker
    )
    return count_soft_lines(body if nameplate else text)


def fit_text_to_box(
    text: str,
    width: int,
    *,
    max_lines: int | None = None,
    min_font: int = 8,
    box_font: int | None = None,
    speaker_src: str = "",
    speaker: str = "",
) -> tuple[str, bool]:
    """Reflow *text* to *width*, then shrink ``\\f[N]`` until it fits *max_lines*.

    Used by Relayout for DB / dialogue sheets. ``max_lines`` ``None``/``0`` means
    wrap only (no font shrink).

    Wolf message boxes are a fixed pixel width. Shrinking ``\\f[N]`` lets more
    halfwidth cells fit on a line, so each shrink pass reflows at
    ``round(width * box_font / current_font)`` (same idea as ``wolf relayout`` /
    ``desc-relayout``). *box_font* defaults to the text's current body size
    (or 18 when there is no ``\\f`` yet).

    Nameplate lines (``Celria\\n…``) are kept intact; only the body is reflowed
    and counted toward *max_lines*.
    """
    return _fit_text_to_box_impl(
        text,
        width,
        max_lines=max_lines,
        min_font=min_font,
        box_font=box_font,
        speaker_src=speaker_src,
        speaker=speaker,
    )


def _fit_text_to_box_impl(
    text: str,
    width: int,
    *,
    max_lines: int | None = None,
    min_font: int = 8,
    box_font: int | None = None,
    speaker_src: str = "",
    speaker: str = "",
) -> tuple[str, bool]:
    from util.wolfdawn import codes as wolf_codes

    if not isinstance(text, str) or not text.strip() or width <= 0:
        return text if isinstance(text, str) else "", False

    plate_kw = {"speaker_src": speaker_src, "speaker": speaker}
    prefix, nameplate, body = split_nameplate_body(text, **plate_kw)
    work = body if nameplate else text
    if nameplate and not body.strip():
        # Already wiped / nameplate-only - do not invent or further destroy.
        return text, False

    limit = int(max_lines) if max_lines is not None else 0
    sizes = wolf_codes.detect_font_sizes(work)
    if box_font is not None and int(box_font) > 0:
        native = int(box_font)
    elif sizes:
        native = wolf_codes.infer_base_font_size(work)
    else:
        native = 18
    native = max(1, native)
    min_font = max(1, int(min_font))

    def _effective_width(current_font: int) -> int:
        cur = max(1, int(current_font))
        return max(1, int(round(width * native / cur)))

    current = wolf_codes.infer_base_font_size(work, default=native) if sizes else native
    new_body = wrap_line_text(work, _effective_width(current) if sizes else width)
    if nameplate and work.strip() and not new_body.strip():
        return text, False
    if limit <= 0:
        new_text = (
            join_nameplate_body(prefix, nameplate, new_body) if nameplate else new_body
        )
        new_text = _reject_empty_body_result(text, new_text)
        return new_text, new_text != text

    if not sizes and count_soft_lines(new_body) > limit:
        new_body, _ = wolf_codes.scale_font_sizes(new_body, native)
        current = native
        new_body = wrap_line_text(new_body, _effective_width(current))

    guard = 0
    while count_soft_lines(new_body) > limit and guard < 64:
        guard += 1
        current = wolf_codes.infer_base_font_size(new_body, default=current)
        if current <= min_font:
            break
        target = current - 1
        new_body, _ = wolf_codes.scale_font_sizes(new_body, target)
        current = target
        new_body = wrap_line_text(new_body, _effective_width(current))

    if nameplate and work.strip() and not new_body.strip():
        return text, False
    new_text = join_nameplate_body(prefix, nameplate, new_body) if nameplate else new_body
    new_text = _reject_empty_body_result(text, new_text)
    return new_text, new_text != text


def apply_relayout_to_line_dict(
    line: dict[str, Any],
    width: int,
    *,
    max_lines: int | None = None,
    min_font: int = 8,
    box_font: int | None = None,
) -> bool:
    """Apply Relayout fit to one ``{text}`` leaf. Returns True if changed."""
    from util.wolfdawn import codes as wolf_codes

    text = line.get("text")
    if not isinstance(text, str) or not text.strip() or width <= 0:
        return False
    native = box_font
    if native is None:
        source = line.get("source")
        if isinstance(source, str) and wolf_codes.detect_font_sizes(source):
            native = wolf_codes.infer_base_font_size(source)
    new_text, changed = fit_text_to_box(
        text,
        width,
        max_lines=max_lines,
        min_font=min_font,
        box_font=native,
        speaker_src=str(line.get("speaker_src") or ""),
        speaker=str(line.get("speaker") or ""),
    )
    if not changed:
        return False
    line["text"] = new_text
    return True


def apply_manual_font_and_wrap(
    text: str,
    width: int,
    *,
    font: int | None = None,
    old_base: int | None = None,
    only_overflow_or_fonts: bool = False,
    speaker_src: str = "",
    speaker: str = "",
) -> tuple[str, bool]:
    """Scale body ``\\f`` (keeping emphasis ratios), then reflow to *width*.

    Always reflows when the wrap layout would differ from the current text
    (same as the live preview). Soft ``\\n`` breaks that already "fit" per line
    are collapsed and rebuilt so Manual Wrap matches what the preview shows.
    Nameplate lines (``Celria\\n…``) stay on their own first line.

    When *only_overflow_or_fonts* is True (group wrap), skip short plain lines
    that already match the target layout and have no ``\\f[N]``.

    Returns ``(new_text, changed)``.
    """
    from util.wolfdawn import codes as wolf_codes

    if not isinstance(text, str) or not text.strip():
        return text, False

    plate_kw = {"speaker_src": speaker_src, "speaker": speaker}
    prefix, nameplate, body = split_nameplate_body(text, **plate_kw)
    work = body if nameplate else text
    if nameplate and not body.strip():
        return text, False

    has_f = bool(wolf_codes.detect_font_sizes(work))
    overflows = width > 0 and line_needs_wrap(work, width)
    wrapped_as_is = (
        wrap_preserving_nameplate(text, width, **plate_kw) if width > 0 else text
    )
    layout_differs = width > 0 and wrapped_as_is != text

    if only_overflow_or_fonts and not has_f and not overflows and not layout_differs:
        return text, False

    new_work = work
    apply_font = (
        font is not None
        and int(font) > 0
        and (has_f or overflows or layout_differs or not only_overflow_or_fonts)
    )
    if apply_font:
        new_work, _ = wolf_codes.scale_font_sizes(
            new_work, int(font), old_base=old_base
        )

    if width > 0:
        wrapped = wrap_line_text(new_work, width)
        if wrapped != new_work:
            new_work = wrapped

    if nameplate and work.strip() and not str(new_work).strip():
        return text, False

    new_text = (
        join_nameplate_body(prefix, nameplate, new_work) if nameplate else new_work
    )
    new_text = _reject_empty_body_result(text, new_text)
    return new_text, new_text != text


def wrap_hit_manual(
    path: Path,
    doc: dict[str, Any],
    hit_id: dict[str, Any],
    width: int,
    *,
    font: int | None = None,
) -> bool:
    """Apply manual font scale + wrap to one hit line."""
    line = locate_line(doc, hit_id)
    if line is None:
        return False
    text = line.get("text")
    if not isinstance(text, str):
        return False
    new_text, changed = apply_manual_font_and_wrap(
        text,
        width,
        font=font,
        speaker_src=str(line.get("speaker_src") or ""),
        speaker=str(line.get("speaker") or ""),
    )
    if not changed:
        return False
    line["text"] = new_text
    save_document(path, doc)
    return True


def wrap_overflow_manual_in_scope(
    path: Path,
    doc: dict[str, Any],
    hit: WrapHit | dict[str, Any],
    width: int,
    *,
    font: int | None = None,
    translated_dir: Path | None = None,
) -> int:
    """Manual wrap (+ optional proportional font) for every line in *hit*'s group."""
    kind, sheet_name = _hit_kind_and_sheet(hit, doc)

    if kind == "names":
        return _wrap_manual_in_names_category(path, doc, sheet_name, width, font=font)
    if kind == "db":
        return _wrap_manual_in_db_sheet(path, doc, sheet_name, width, font=font)
    if kind in ("map", "common"):
        speaker_src = _hit_speaker_src(hit, doc)
        if translated_dir is not None:
            return wrap_overflow_manual_in_dialogue_format(
                translated_dir, speaker_src, width, font=font
            )
        return _wrap_manual_in_event_format(
            path, doc, speaker_src, width, font=font
        )
    if kind == "gamedat":
        return _wrap_manual_in_gamedat(path, doc, width, font=font)
    return 0


def _apply_manual_to_line_dict(
    line: dict[str, Any],
    width: int,
    *,
    font: int | None,
) -> bool:
    text = line.get("text")
    if not isinstance(text, str) or not text.strip():
        return False
    new_text, changed = apply_manual_font_and_wrap(
        text,
        width,
        font=font,
        only_overflow_or_fonts=True,
        speaker_src=str(line.get("speaker_src") or ""),
        speaker=str(line.get("speaker") or ""),
    )
    if not changed:
        return False
    line["text"] = new_text
    return True


def _wrap_manual_in_names_category(
    path: Path,
    doc: dict[str, Any],
    category: str,
    width: int,
    *,
    font: int | None = None,
) -> int:
    if doc.get("kind") != "names":
        return 0
    changed = 0
    for entry in doc.get("names") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("note") or "") != category:
            continue
        if _apply_manual_to_line_dict(entry, width, font=font):
            changed += 1
    if changed:
        save_document(path, doc)
    return changed


def _wrap_manual_in_db_sheet(
    path: Path,
    doc: dict[str, Any],
    sheet_name: str,
    width: int,
    *,
    font: int | None = None,
) -> int:
    if doc.get("kind") != "db":
        return 0
    changed = 0
    for group in doc.get("groups") or []:
        if str(group.get("typeName") or "") != sheet_name:
            continue
        for line in group.get("lines") or []:
            if _apply_manual_to_line_dict(line, width, font=font):
                changed += 1
    if changed:
        save_document(path, doc)
    return changed


def _wrap_manual_in_event_format(
    path: Path,
    doc: dict[str, Any],
    speaker_src: str,
    width: int,
    *,
    font: int | None = None,
) -> int:
    """Manual-wrap overflowing lines in one file that share *speaker_src*'s format."""
    if doc.get("kind") not in ("map", "common"):
        return 0
    want = wrap_format_key(speaker_src)
    changed = 0
    for scene in doc.get("scenes") or []:
        for line in scene.get("lines") or []:
            if wrap_format_key(str(line.get("speaker_src") or "")) != want:
                continue
            if _apply_manual_to_line_dict(line, width, font=font):
                changed += 1
    if changed:
        save_document(path, doc)
    return changed


def wrap_overflow_manual_in_dialogue_format(
    translated_dir: str | Path,
    speaker_src: str,
    width: int,
    *,
    font: int | None = None,
) -> int:
    """Manual-wrap matching-format lines across all map/CommonEvent JSON."""
    root = Path(translated_dir)
    if not root.is_dir() or width <= 0:
        return 0
    total = 0
    for path in sorted(root.glob("*.json")):
        doc = _load_json(path)
        if not isinstance(doc, dict) or doc.get("kind") not in ("map", "common"):
            continue
        total += _wrap_manual_in_event_format(
            path, doc, speaker_src, width, font=font
        )
    return total


def _wrap_manual_in_gamedat(
    path: Path,
    doc: dict[str, Any],
    width: int,
    *,
    font: int | None = None,
) -> int:
    if doc.get("kind") != "gamedat":
        return 0
    changed = 0
    for line in doc.get("lines") or []:
        if _apply_manual_to_line_dict(line, width, font=font):
            changed += 1
    if changed:
        save_document(path, doc)
    return changed


@dataclass
class ScopeStats:
    """Line counts for the wrap group containing one search hit."""

    label: str
    total: int
    overflow: int


def _hit_kind_and_sheet(hit: WrapHit | dict[str, Any], doc: dict[str, Any] | None = None) -> tuple[str, str]:
    if isinstance(hit, WrapHit):
        return hit.kind, hit.sheet_name
    kind = str(hit.get("kind") or (doc or {}).get("kind") or "")
    sheet = str(hit.get("sheet_name") or "")
    return kind, sheet


def _hit_scene_index(hit: WrapHit | dict[str, Any]) -> int | None:
    if isinstance(hit, WrapHit):
        return hit.scene_index
    raw = hit.get("scene_index")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _hit_speaker_src(
    hit: WrapHit | dict[str, Any],
    doc: dict[str, Any] | None = None,
) -> str:
    """Best-effort ``speaker_src`` for a wrap hit (from live line when possible)."""
    if doc is not None:
        hit_id = hit.hit_id if isinstance(hit, WrapHit) else hit
        if isinstance(hit_id, dict):
            line = locate_line(doc, hit_id)
            if isinstance(line, dict) and line.get("speaker_src") is not None:
                return str(line.get("speaker_src") or "")
    if isinstance(hit, dict) and hit.get("speaker_src") is not None:
        return str(hit.get("speaker_src") or "")
    return ""


def _scene_group_label(doc: dict[str, Any] | None, hit: WrapHit | dict[str, Any]) -> str:
    """Deprecated scene label; prefer format label for map/common groups."""
    kind, sheet = _hit_kind_and_sheet(hit, doc)
    si = _hit_scene_index(hit)
    scene: dict[str, Any] | None = None
    if doc is not None and si is not None:
        scenes = doc.get("scenes") or []
        if 0 <= si < len(scenes) and isinstance(scenes[si], dict):
            scene = scenes[si]
    event_id = None
    name = ""
    if scene is not None:
        event_id = scene.get("event")
        name = str(scene.get("name") or "").strip()
    elif isinstance(hit, WrapHit) and hit.row is not None:
        event_id = hit.row
    elif isinstance(hit, dict) and hit.get("row") is not None:
        event_id = hit.get("row")

    parts: list[str] = []
    if kind == "common":
        parts.append("CommonEvent")
    elif sheet:
        parts.append(sheet)
    if event_id is not None:
        parts.append(f"event {event_id}")
    if name:
        parts.append(name)
    elif si is not None and event_id is None:
        parts.append(f"scene {si}")
    return " · ".join(parts) if parts else (sheet or "event")


def scope_label(hit: WrapHit | dict[str, Any], doc: dict[str, Any] | None = None) -> str:
    """Human-readable group name for status messages."""
    kind, sheet = _hit_kind_and_sheet(hit, doc)
    jf = ""
    if isinstance(hit, WrapHit):
        jf = hit.json_file
    else:
        jf = str(hit.get("json_file") or "")
    if kind == "db":
        return f"sheet {sheet}"
    if kind == "names":
        return f"category {sheet}"
    if kind == "gamedat":
        return "Game.dat"
    if kind in ("map", "common"):
        return wrap_format_label(_hit_speaker_src(hit, doc))
    return sheet or jf


def scope_stats(
    doc: dict[str, Any],
    hit: WrapHit | dict[str, Any],
    width: int,
) -> ScopeStats:
    """Count lines and overflows in the same group as *hit*."""
    kind, sheet_name = _hit_kind_and_sheet(hit, doc)

    total = 0
    overflow = 0

    if kind == "db":
        for group in doc.get("groups") or []:
            if str(group.get("typeName") or "") != sheet_name:
                continue
            for line in group.get("lines") or []:
                text = line.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                total += 1
                if line_needs_wrap(text, width):
                    overflow += 1
            break
    elif kind == "names":
        for entry in doc.get("names") or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("note") or "") != sheet_name:
                continue
            text = entry.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            total += 1
            if line_needs_wrap(text, width):
                overflow += 1
    elif kind in ("map", "common"):
        want = wrap_format_key(_hit_speaker_src(hit, doc))
        for scene in doc.get("scenes") or []:
            for line in scene.get("lines") or []:
                if wrap_format_key(str(line.get("speaker_src") or "")) != want:
                    continue
                text = line.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                total += 1
                if line_needs_wrap_preserving_nameplate(
                    text,
                    width,
                    speaker_src=str(line.get("speaker_src") or ""),
                    speaker=str(line.get("speaker") or ""),
                ):
                    overflow += 1
    elif kind == "gamedat":
        for line in doc.get("lines") or []:
            if not isinstance(line, dict):
                continue
            text = line.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            total += 1
            if line_needs_wrap(text, width):
                overflow += 1

    return ScopeStats(label=scope_label(hit, doc), total=total, overflow=overflow)


def _line_needs_relayout(
    text: str,
    width: int,
    max_lines: int | None,
    *,
    speaker_src: str = "",
    speaker: str = "",
) -> bool:
    """True if width wrap or max-lines fit would change *text*."""
    plate_kw = {"speaker_src": speaker_src, "speaker": speaker}
    if line_needs_wrap_preserving_nameplate(text, width, **plate_kw):
        return True
    limit = int(max_lines) if max_lines is not None else 0
    if limit <= 0:
        return False
    wrapped = wrap_preserving_nameplate(text, width, **plate_kw)
    return (
        count_body_soft_lines(wrapped, **plate_kw) > limit or wrapped != text
    )


def _wrap_overflow_in_event_format(
    path: Path,
    doc: dict[str, Any],
    speaker_src: str,
    width: int,
    *,
    max_lines: int | None = None,
) -> int:
    """Wrap overflowing lines in one file that share *speaker_src*'s format."""
    if doc.get("kind") not in ("map", "common"):
        return 0
    want = wrap_format_key(speaker_src)
    changed = 0
    for scene in doc.get("scenes") or []:
        for line in scene.get("lines") or []:
            if wrap_format_key(str(line.get("speaker_src") or "")) != want:
                continue
            text = line.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            src = str(line.get("speaker_src") or "")
            spk = str(line.get("speaker") or "")
            if not _line_needs_relayout(
                text, width, max_lines, speaker_src=src, speaker=spk
            ):
                continue
            if apply_relayout_to_line_dict(line, width, max_lines=max_lines):
                changed += 1
    if changed:
        save_document(path, doc)
    return changed


def wrap_overflow_in_dialogue_format(
    translated_dir: str | Path,
    speaker_src: str,
    width: int,
    *,
    max_lines: int | None = None,
) -> int:
    """Relayout matching-format lines across all map/CommonEvent JSON."""
    root = Path(translated_dir)
    if not root.is_dir() or width <= 0:
        return 0
    total = 0
    for path in sorted(root.glob("*.json")):
        doc = _load_json(path)
        if not isinstance(doc, dict) or doc.get("kind") not in ("map", "common"):
            continue
        total += _wrap_overflow_in_event_format(
            path, doc, speaker_src, width, max_lines=max_lines
        )
    return total


def _wrap_overflow_in_gamedat(
    path: Path,
    doc: dict[str, Any],
    width: int,
    *,
    max_lines: int | None = None,
) -> int:
    if doc.get("kind") != "gamedat":
        return 0
    changed = 0
    for line in doc.get("lines") or []:
        if not isinstance(line, dict):
            continue
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if not _line_needs_relayout(text, width, max_lines):
            continue
        if apply_relayout_to_line_dict(line, width, max_lines=max_lines):
            changed += 1
    if changed:
        save_document(path, doc)
    return changed


def wrap_overflow_in_scope(
    path: Path,
    doc: dict[str, Any],
    hit: WrapHit | dict[str, Any],
    width: int,
    *,
    max_lines: int | None = None,
    translated_dir: Path | None = None,
) -> int:
    """Wrap overflowing lines in the same group as *hit*.

    For DB / gamedat, *max_lines* also shrinks ``\\f[N]`` until the soft line
    count fits. For map / CommonEvent, the group is the ``speaker_src`` format
    bucket (spoken / ui / …); when *translated_dir* is set, every map and
    CommonEvent JSON under it is included. Names categories ignore *max_lines*
    here - use ``wolf names-wrap`` via the GUI instead.
    """
    kind, sheet_name = _hit_kind_and_sheet(hit, doc)

    if kind == "names":
        return _wrap_overflow_in_names_category(path, doc, sheet_name, width)
    if kind == "db":
        return wrap_overflow_in_sheet(
            path, doc, sheet_name, width, kind="db", max_lines=max_lines
        )
    if kind in ("map", "common"):
        speaker_src = _hit_speaker_src(hit, doc)
        if translated_dir is not None:
            return wrap_overflow_in_dialogue_format(
                translated_dir, speaker_src, width, max_lines=max_lines
            )
        return _wrap_overflow_in_event_format(
            path, doc, speaker_src, width, max_lines=max_lines
        )
    if kind == "gamedat":
        return _wrap_overflow_in_gamedat(path, doc, width, max_lines=max_lines)
    return 0


def wrap_hit_in_file(
    path: Path,
    doc: dict[str, Any],
    hit_id: dict[str, Any],
    width: int,
    *,
    max_lines: int | None = None,
) -> bool:
    """Relayout one hit line (wrap + optional max-lines font shrink)."""
    line = locate_line(doc, hit_id)
    if line is None:
        return False
    if not apply_relayout_to_line_dict(line, width, max_lines=max_lines):
        return False
    save_document(path, doc)
    return True


def wrap_overflow_in_sheet(
    path: Path,
    doc: dict[str, Any],
    sheet_name: str,
    width: int,
    *,
    kind: str | None = None,
    max_lines: int | None = None,
) -> int:
    """Wrap every overflowing line in one DB sheet or names.json category."""
    doc_kind = kind or doc.get("kind")
    if doc_kind == "names":
        return _wrap_overflow_in_names_category(path, doc, sheet_name, width)
    if doc.get("kind") != "db":
        return 0
    changed = 0
    for group in doc.get("groups") or []:
        if str(group.get("typeName") or "") != sheet_name:
            continue
        for line in group.get("lines") or []:
            text = line.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if not _line_needs_relayout(text, width, max_lines):
                continue
            if apply_relayout_to_line_dict(line, width, max_lines=max_lines):
                changed += 1
    if changed:
        save_document(path, doc)
    return changed


def _wrap_overflow_in_names_category(
    path: Path,
    doc: dict[str, Any],
    category: str,
    width: int,
) -> int:
    """Wrap overflowing ``names[]`` entries sharing one ``note`` (category)."""
    if doc.get("kind") != "names":
        return 0
    changed = 0
    for entry in doc.get("names") or []:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("note") or "") != category:
            continue
        text = entry.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if not line_needs_wrap(text, width):
            continue
        if wrap_line_in_doc(entry, width):
            changed += 1
    if changed:
        save_document(path, doc)
    return changed
