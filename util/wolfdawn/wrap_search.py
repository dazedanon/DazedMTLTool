"""Search translated WolfDawn JSON for text to fix wrapping.

Paste in-game text, open the matching line, then wrap that line or every
overflowing line in the same group (database sheet, names category, map /
CommonEvent file, or Game.dat).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

import util.dazedwrap as dazedwrap
from util.wolfdawn.db_classify import group_key, json_file_from_doc
from util.wolfdawn.selective_wrap import line_needs_wrap, wrap_line_text

WRAP_PROFILE_NAME = "wrap_profile.json"
DEFAULT_WRAP_WIDTH = 36

_APOSTROPHE_NORMALIZE = str.maketrans(
    {
        "\u2019": "'",
        "\u2018": "'",
        "\u02bc": "'",
        "`": "'",
    }
)


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


@dataclass
class SheetOverflowSummary:
    json_file: str
    sheet_name: str
    line_count: int
    overflow_count: int
    tier: str = ""
    kind: str = "db"

    @property
    def key(self) -> str:
        if self.kind == "names":
            return f"{self.json_file}|names|{self.sheet_name}"
        return group_key(self.json_file, self.sheet_name)


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


def wrap_preview_info(text: str, width: int) -> dict[str, Any]:
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
    wrapped = wrap_line_text(text, width)
    norm_in = text.replace("\r\n", "\n").replace("\r", "\n")
    norm_out = wrapped.replace("\r\n", "\n").replace("\r", "\n")
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
    }


def format_wrap_preview(text: str, width: int) -> str:
    """Multiline preview with per-line visible character counts."""
    info = wrap_preview_info(text, width)
    if not info["wrapped"]:
        return ""
    lines = info["wrapped"].replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parts: list[str] = []
    for i, line in enumerate(lines):
        vis = dazedwrap.max_line_visible_length(line)
        marker = "⚠" if vis > width else " "
        parts.append(f"{marker} {i + 1:2d} ({vis:2d})  {line}")
    return "\n".join(parts)


def wrap_preview_summary(text: str, width: int) -> str:
    """One-line status for the preview header."""
    info = wrap_preview_info(text, width)
    if not isinstance(text, str) or not text.strip():
        return ""
    longest = int(info["longest"])
    if not info["needs_wrap"]:
        return f"Fits at width {width} (longest line {longest} visible chars)."
    return (
        f"Will wrap to {info['output_line_count']} line(s) at width {width} "
        f"(longest input line {longest} visible chars)."
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
) -> str:
    """Rich HTML wrap preview: line gutters + simulated ``\\c`` / ``\\f`` styling.

    When *body_font* is set, proportionally scale every ``\\f[N]`` (and ensure a
    leading body size) before wrapping/rendering - same as Manual wrap would do.
    """
    from util.wolfdawn import codes as wolf_codes

    preview_text = text if isinstance(text, str) else ""
    if body_font is not None and int(body_font) > 0 and preview_text.strip():
        preview_text, _ = wolf_codes.scale_font_sizes(preview_text, int(body_font))

    info = wrap_preview_info(preview_text, width)
    wrapped = info.get("wrapped") or ""
    if not wrapped:
        return ""

    body = (
        int(body_font)
        if body_font is not None and int(body_font) > 0
        else wolf_codes.infer_base_font_size(preview_text, default=18)
    )
    lines = wrapped.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows: list[str] = []
    for i, line in enumerate(lines):
        vis = dazedwrap.max_line_visible_length(line)
        overflow = vis > width > 0
        gutter_color = "#ce9178" if overflow else "#858585"
        marker = "⚠" if overflow else "&nbsp;"
        gutter = (
            f'<span style="color:{gutter_color};font-family:monospace;font-size:11px">'
            f"{marker} {i + 1:2d} ({vis:2d})&nbsp;&nbsp;</span>"
        )
        body_html = render_wolf_text_html(
            line, default_color="#d4d4d4", default_font_px=body
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


def split_line_at_visible_width(line: str, width: int) -> tuple[int, int]:
    """Return ``(fit_end, line_len)`` char indices in *line* for UI highlighting."""
    line_len = len(line)
    if not line or width <= 0:
        return (line_len, line_len)
    fit_end = dazedwrap.visible_word_wrap_end_index(line, width)
    return (min(fit_end, line_len), line_len)


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
    new_text = wrap_line_text(text, width)
    if new_text == text:
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
) -> tuple[str, bool]:
    """Scale body ``\\f`` (keeping emphasis ratios), then wrap to *width*.

    When *only_overflow_or_fonts* is True (group wrap), skip lines that already
    fit and have no ``\\f[N]`` so short UI labels are not given a forced font.

    Returns ``(new_text, changed)``.
    """
    from util.wolfdawn import codes as wolf_codes

    if not isinstance(text, str) or not text.strip():
        return text, False
    new_text = text
    has_f = bool(wolf_codes.detect_font_sizes(new_text))
    needs_wrap = width > 0 and line_needs_wrap(new_text, width)
    if only_overflow_or_fonts and not has_f and not needs_wrap:
        return text, False
    if font is not None and int(font) > 0 and (has_f or needs_wrap or not only_overflow_or_fonts):
        new_text, _ = wolf_codes.scale_font_sizes(
            new_text, int(font), old_base=old_base
        )
        needs_wrap = width > 0 and line_needs_wrap(new_text, width)
    if needs_wrap:
        new_text = wrap_line_text(new_text, width)
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
    new_text, changed = apply_manual_font_and_wrap(text, width, font=font)
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
) -> int:
    """Manual wrap (+ optional proportional font) for every line in *hit*'s group."""
    if isinstance(hit, WrapHit):
        kind, sheet_name = hit.kind, hit.sheet_name
    else:
        kind = str(hit.get("kind") or doc.get("kind") or "")
        sheet_name = str(hit.get("sheet_name") or "")

    if kind == "names":
        return _wrap_manual_in_names_category(path, doc, sheet_name, width, font=font)
    if kind == "db":
        return _wrap_manual_in_db_sheet(path, doc, sheet_name, width, font=font)
    if kind in ("map", "common"):
        return _wrap_manual_in_event_file(path, doc, width, font=font)
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
        text, width, font=font, only_overflow_or_fonts=True
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


def _wrap_manual_in_event_file(
    path: Path,
    doc: dict[str, Any],
    width: int,
    *,
    font: int | None = None,
) -> int:
    if doc.get("kind") not in ("map", "common"):
        return 0
    changed = 0
    for scene in doc.get("scenes") or []:
        for line in scene.get("lines") or []:
            if _apply_manual_to_line_dict(line, width, font=font):
                changed += 1
    if changed:
        save_document(path, doc)
    return changed


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


def scope_label(hit: WrapHit | dict[str, Any]) -> str:
    """Human-readable group name for status messages."""
    if isinstance(hit, WrapHit):
        kind, sheet, jf = hit.kind, hit.sheet_name, hit.json_file
    else:
        kind = str(hit.get("kind") or "")
        sheet = str(hit.get("sheet_name") or "")
        jf = str(hit.get("json_file") or "")
    if kind == "db":
        return f"sheet {sheet}"
    if kind == "names":
        return f"category {sheet}"
    if kind == "gamedat":
        return "Game.dat"
    if kind == "common":
        return "CommonEvent"
    if kind == "map":
        return sheet or jf
    return sheet or jf


def scope_stats(
    doc: dict[str, Any],
    hit: WrapHit | dict[str, Any],
    width: int,
) -> ScopeStats:
    """Count lines and overflows in the same group as *hit*."""
    if isinstance(hit, WrapHit):
        kind, sheet_name = hit.kind, hit.sheet_name
    else:
        kind = str(hit.get("kind") or doc.get("kind") or "")
        sheet_name = str(hit.get("sheet_name") or "")

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
        for scene in doc.get("scenes") or []:
            for line in scene.get("lines") or []:
                text = line.get("text")
                if not isinstance(text, str) or not text.strip():
                    continue
                total += 1
                if line_needs_wrap(text, width):
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

    return ScopeStats(label=scope_label(hit), total=total, overflow=overflow)


def _wrap_overflow_in_event_file(path: Path, doc: dict[str, Any], width: int) -> int:
    """Wrap overflowing dialogue lines in one map or CommonEvent JSON file."""
    if doc.get("kind") not in ("map", "common"):
        return 0
    changed = 0
    for scene in doc.get("scenes") or []:
        for line in scene.get("lines") or []:
            text = line.get("text")
            if not isinstance(text, str) or not text.strip():
                continue
            if not line_needs_wrap(text, width):
                continue
            if wrap_line_in_doc(line, width):
                changed += 1
    if changed:
        save_document(path, doc)
    return changed


def _wrap_overflow_in_gamedat(path: Path, doc: dict[str, Any], width: int) -> int:
    if doc.get("kind") != "gamedat":
        return 0
    changed = 0
    for line in doc.get("lines") or []:
        if not isinstance(line, dict):
            continue
        text = line.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        if not line_needs_wrap(text, width):
            continue
        if wrap_line_in_doc(line, width):
            changed += 1
    if changed:
        save_document(path, doc)
    return changed


def wrap_overflow_in_scope(
    path: Path,
    doc: dict[str, Any],
    hit: WrapHit | dict[str, Any],
    width: int,
) -> int:
    """Wrap every overflowing line in the same group as *hit*."""
    if isinstance(hit, WrapHit):
        kind, sheet_name = hit.kind, hit.sheet_name
    else:
        kind = str(hit.get("kind") or doc.get("kind") or "")
        sheet_name = str(hit.get("sheet_name") or "")

    if kind == "names":
        return _wrap_overflow_in_names_category(path, doc, sheet_name, width)
    if kind == "db":
        return wrap_overflow_in_sheet(path, doc, sheet_name, width, kind="db")
    if kind in ("map", "common"):
        return _wrap_overflow_in_event_file(path, doc, width)
    if kind == "gamedat":
        return _wrap_overflow_in_gamedat(path, doc, width)
    return 0


def wrap_hit_in_file(
    path: Path,
    doc: dict[str, Any],
    hit_id: dict[str, Any],
    width: int,
) -> bool:
    line = locate_line(doc, hit_id)
    if line is None:
        return False
    if not wrap_line_in_doc(line, width):
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
            if not line_needs_wrap(text, width):
                continue
            if wrap_line_in_doc(line, width):
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


def _names_category_summaries(
    doc: dict[str, Any],
    *,
    json_file: str,
    width: int,
) -> list[SheetOverflowSummary]:
    counts: dict[str, int] = {}
    overflow: dict[str, int] = {}
    for entry in doc.get("names") or []:
        if not isinstance(entry, dict):
            continue
        note = str(entry.get("note") or "names.json")
        counts[note] = counts.get(note, 0) + 1
        text = entry.get("text")
        if isinstance(text, str) and line_needs_wrap(text, width):
            overflow[note] = overflow.get(note, 0) + 1
    return [
        SheetOverflowSummary(
            json_file=json_file,
            sheet_name=note,
            line_count=counts[note],
            overflow_count=overflow.get(note, 0),
            tier="names",
            kind="names",
        )
        for note in sorted(counts)
    ]


def sheet_overflow_summaries(
    translated_dir: str | Path,
    width: int,
    *,
    files_dir: str | Path | None = None,
) -> list[SheetOverflowSummary]:
    """Per DB sheet overflow counts at *width*."""
    from util.wolfdawn.db_classify import analyze_content_distribution, classify_db_document

    base = Path(translated_dir)
    if not base.is_dir():
        base = Path(files_dir) if files_dir else base
    dist = analyze_content_distribution(base)
    summaries: list[SheetOverflowSummary] = []

    for path in sorted(base.glob("*.project.json")):
        doc = _load_json(path)
        if not doc or doc.get("kind") != "db":
            continue
        jf = path.name
        for group in classify_db_document(doc, json_file=jf):
            overflow = 0
            for g in doc.get("groups") or []:
                if str(g.get("typeName") or "") != group.type_name:
                    continue
                for line in g.get("lines") or []:
                    text = line.get("text")
                    if isinstance(text, str) and line_needs_wrap(text, width):
                        overflow += 1
            summaries.append(
                SheetOverflowSummary(
                    json_file=jf,
                    sheet_name=group.type_name,
                    line_count=group.line_count,
                    overflow_count=overflow,
                    tier=group.tier,
                )
            )
    if not summaries:
        summaries = [
            SheetOverflowSummary(
                json_file=g.json_file,
                sheet_name=g.type_name,
                line_count=g.line_count,
                overflow_count=0,
                tier=g.tier,
            )
            for g in dist.groups
        ]

    seen_names: set[Path] = set()
    for search_base in _iter_search_dirs(base, Path(files_dir) if files_dir else None):
        names_path = search_base / "names.json"
        if not names_path.is_file() or names_path in seen_names:
            continue
        seen_names.add(names_path)
        doc = _load_json(names_path)
        if doc and doc.get("kind") == "names":
            summaries.extend(
                _names_category_summaries(doc, json_file="names.json", width=width)
            )
    return summaries
