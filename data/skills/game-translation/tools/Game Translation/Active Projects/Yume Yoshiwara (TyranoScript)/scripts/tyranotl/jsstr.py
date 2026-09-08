"""Scan JavaScript source for string literals, with their spans.

Used in three places: ``[iscript]`` blocks inside ``.ks`` files, ``exp=``/``cond=``
attribute values, and the handful of engine ``.js`` files that hold player-facing
text. Comments are masked out first so a Japanese ``// comment`` is never mistaken
for a literal.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

STRING_RE = re.compile(
    r"\"(?:[^\"\\\n]|\\.)*\""
    r"|'(?:[^'\\\n]|\\.)*'"
    r"|`(?:[^`\\]|\\.)*`"
)

LINE_COMMENT_RE = re.compile(r"//[^\n]*")
BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)

ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", "\"": "\"", "'": "'", "`": "`", "/": "/", "0": "\0"}


@dataclass(frozen=True)
class JsString:
    quote: str
    value: str      # decoded
    raw: str        # as written, without the quotes
    start: int      # offset of the first character *inside* the quotes
    end: int        # offset just past the last character inside the quotes


def _blank_comments(source: str) -> str:
    """Replace comment bodies with spaces, preserving every offset.

    Runs a small scanner rather than a plain regex sub so that a ``//`` inside a
    string literal (``"https://..."``) does not start a comment.
    """
    out = list(source)
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in "\"'`":
            m = STRING_RE.match(source, i)
            if m:
                i = m.end()
                continue
            i += 1
            continue
        if ch == "/" and i + 1 < n:
            nxt = source[i + 1]
            if nxt == "/":
                m = LINE_COMMENT_RE.match(source, i)
                if m:
                    for k in range(m.start(), m.end()):
                        out[k] = " "
                    i = m.end()
                    continue
            elif nxt == "*":
                m = BLOCK_COMMENT_RE.match(source, i)
                if m:
                    for k in range(m.start(), m.end()):
                        out[k] = "\n" if source[k] == "\n" else " "
                    i = m.end()
                    continue
        i += 1
    return "".join(out)


def decode(raw: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch == "\\" and i + 1 < len(raw):
            nxt = raw[i + 1]
            if nxt == "u" and raw[i + 2:i + 3] == "{":
                close = raw.find("}", i + 3)
                if close != -1:
                    out.append(chr(int(raw[i + 3:close], 16)))
                    i = close + 1
                    continue
            if nxt == "u" and len(raw) >= i + 6:
                out.append(chr(int(raw[i + 2:i + 6], 16)))
                i += 6
                continue
            if nxt == "x" and len(raw) >= i + 4:
                out.append(chr(int(raw[i + 2:i + 4], 16)))
                i += 4
                continue
            out.append(ESCAPES.get(nxt, nxt))
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def encode(value: str, quote: str) -> str:
    out: list[str] = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == quote:
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return "".join(out)


def scan(source: str, offset: int = 0) -> list[JsString]:
    masked = _blank_comments(source)
    found: list[JsString] = []
    for m in STRING_RE.finditer(masked):
        raw = source[m.start() + 1:m.end() - 1]
        found.append(JsString(
            quote=source[m.start()],
            value=decode(raw),
            raw=raw,
            start=offset + m.start() + 1,
            end=offset + m.end() - 1,
        ))
    return found
