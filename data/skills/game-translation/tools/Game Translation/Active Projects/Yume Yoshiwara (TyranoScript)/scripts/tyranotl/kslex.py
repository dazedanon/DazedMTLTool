"""A byte-faithful reader for TyranoScript ``.ks`` files.

The whole pipeline injects by replacing character spans inside the original
line, so this module never normalises anything: line separators are carried per
line (the project mixes CRLF and LF across files) and no BOM is added or removed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import codes

LINE_SPLIT_RE = re.compile(r"(\r\n|\r|\n)")

ATTR_RE = re.compile(r"([\w.\-]+)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s\]]+)")


@dataclass(frozen=True)
class Attr:
    name: str
    raw: str
    value: str
    quote: str
    #: absolute offsets of ``value`` inside the containing line
    start: int
    end: int


@dataclass(frozen=True)
class Tag:
    name: str
    start: int
    end: int
    attrs: tuple[Attr, ...]


@dataclass
class Line:
    number: int          # 1-based
    text: str            # without the separator
    sep: str             # "\r\n", "\n", "\r" or ""
    kind: str            # comment | label | at | tag | text | blank
    tags: tuple[Tag, ...] = field(default_factory=tuple)


@dataclass
class Script:
    path: Path
    rel: str
    lines: list[Line]
    encoding: str = "utf-8"

    def render(self) -> str:
        return "".join(line.text + line.sep for line in self.lines)


def parse_attrs(body: str, base: int) -> tuple[Attr, ...]:
    out: list[Attr] = []
    for m in ATTR_RE.finditer(body):
        raw = m.group(2)
        if raw[:1] in ("\"", "'") and raw[-1:] == raw[:1] and len(raw) >= 2:
            quote, value = raw[0], raw[1:-1]
            start = base + m.start(2) + 1
            end = base + m.end(2) - 1
        else:
            quote, value = "", raw
            start = base + m.start(2)
            end = base + m.end(2)
        out.append(Attr(m.group(1), raw, value, quote, start, end))
    return tuple(out)


AT_RE = re.compile(r"^\s*@(\w+)(.*)$")


def scan_tags(text: str) -> tuple[Tag, ...]:
    out: list[Tag] = []
    for m in codes.TAG_RE.finditer(text):
        body_start = m.start(2)
        out.append(Tag(m.group(1), m.start(), m.end(), parse_attrs(m.group(2), body_start)))
    if not out:
        # "@jump storage=..." is the bracket-free form of the same tag.
        at = AT_RE.match(text)
        if at:
            out.append(Tag(at.group(1), at.start(), at.end(),
                           parse_attrs(at.group(2), at.start(2))))
    return tuple(out)


def classify(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "blank"
    if stripped.startswith(";"):
        return "comment"
    if stripped.startswith("*"):
        return "label"
    if stripped.startswith("@"):
        return "at"
    if stripped.startswith("["):
        # A tag line may still trail message text: "[cm]Hello[p]".
        return "tag"
    return "text"


def read(path: Path, rel: str) -> Script:
    data = path.read_bytes()
    encoding = "utf-8"
    try:
        raw = data.decode(encoding)
    except UnicodeDecodeError:
        encoding = "cp932"
        raw = data.decode(encoding)
    parts = LINE_SPLIT_RE.split(raw)
    lines: list[Line] = []
    number = 0
    for index in range(0, len(parts), 2):
        body = parts[index]
        sep = parts[index + 1] if index + 1 < len(parts) else ""
        if body == "" and sep == "" and index + 1 >= len(parts):
            break  # trailing empty chunk produced by a final separator
        number += 1
        lines.append(Line(number, body, sep, classify(body), scan_tags(body)))
    return Script(path, rel, lines, encoding)


PLUGIN_TAG_RE = re.compile(r'\[plugin\s+name\s*=\s*"?([\w\-]+)"?')
GETSCRIPT_RE = re.compile(r"""getScript\(\s*['"]([^'"]+)['"]""")


def iter_scripts(root: Path, extra: list[str] | None = None) -> list[Script]:
    scripts: list[Script] = []
    for path in sorted((root / "data/scenario").rglob("*.ks")):
        scripts.append(read(path, path.relative_to(root).as_posix()))
    for rel in extra or []:
        path = root / rel
        if path.exists():
            scripts.append(read(path, rel))
    return scripts


def loaded_plugins(scripts: list[Script]) -> tuple[set[str], set[str]]:
    """Which plugins the game actually pulls in, and any bare ``getScript`` paths.

    A plugin folder that ships with the project but is never referenced (this
    game carries seven of them, including a whole "新しいフォルダー") holds no
    player-facing text and must not be translated or injected.
    """
    names: set[str] = set()
    scripts_loaded: set[str] = set()
    for script in scripts:
        for line in script.lines:
            if line.kind == "comment":
                continue
            for m in PLUGIN_TAG_RE.finditer(line.text):
                names.add(m.group(1))
            for m in GETSCRIPT_RE.finditer(line.text):
                scripts_loaded.add(m.group(1))
    return names, scripts_loaded


def iscript_ranges(script: Script) -> list[tuple[int, int]]:
    """Index ranges (half-open, into ``script.lines``) of ``[iscript]`` bodies."""
    ranges: list[tuple[int, int]] = []
    open_at: int | None = None
    for index, line in enumerate(script.lines):
        lowered = line.text.strip().lower()
        if open_at is None and lowered.startswith("[iscript]"):
            open_at = index + 1
        elif open_at is not None and lowered.startswith("[endscript]"):
            ranges.append((open_at, index))
            open_at = None
    if open_at is not None:
        ranges.append((open_at, len(script.lines)))
    return ranges


def label_at(script: Script, index: int) -> str:
    for probe in range(index, -1, -1):
        line = script.lines[probe]
        if line.kind == "label":
            return line.text.strip().lstrip("*").split("|")[0].strip()
    return "(top)"
