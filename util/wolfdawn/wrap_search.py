"""Search translated WolfDawn JSON for text to fix wrapping.

Primary workflow: paste in-game text, find the database sheet and row, wrap at
the right width, re-inject. Sheet names match ``typeName`` in DB JSON and
``note`` in names.json (e.g. ``├■街の噂（MOB）``).
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
        overflow = f"  longest line: {self.max_line_len} chars"
        if width > 0 and self.max_line_len > width:
            overflow += " (overflow)"
        preview = self.text.replace("\n", " ")[:90]
        if len(self.text) > 90:
            preview += "…"
        if self.kind == "db":
            loc = f"row {self.row}  ·  {self.field_name}"
        elif self.kind == "names":
            loc = f"entry #{self.row}  ·  {self.field_name[:60]}"
        elif self.kind == "gamedat":
            loc = self.field_name or f"line {self.line_index}"
        else:
            loc = self.field_name or self.map_file or self.json_file
        return (
            f"Sheet: {self.sheet_name}  ·  {self.json_file}  ·  {loc}\n"
            f"  {preview}{overflow}"
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
) -> None:
    profile = load_wrap_profile(work_dir)
    sheets = profile.setdefault("sheets", {})
    sheets[sheet_name] = {"width": int(width), "json_file": json_file}
    profile["default_width"] = profile.get("default_width", DEFAULT_WRAP_WIDTH)
    save_wrap_profile(work_dir, profile)


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
                    if not _text_matches(text, q):
                        continue
                    note = str(entry.get("note") or "names.json")
                    source = str(entry.get("source") or "")[:80]
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
                            field_name=source or f"entry {idx}",
                            text=str(text),
                            max_line_len=dazedwrap.max_line_visible_length(str(text)),
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
