"""Shared paths, the Japanese test, and control-code masking."""
from __future__ import annotations

import io
import os
import re
import sys

# The console here is cp1252; every entry point rewraps stdout or dies on the
# first Japanese character it prints.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GAME = r"c:\Users\sw\Desktop\Games\ひと夏の思い出"
EXPORT = os.path.join(GAME, "AssetRipper_export_20260829_001509", "ExportedProject", "Assets")

DIALOGUE_DB = os.path.join(EXPORT, "MonoBehaviour", "Dialogue Database.asset")
SCENE = os.path.join(EXPORT, "_Project", "Scenes", "Release.unity")
STRINGLITERAL = os.path.join(PROJECT, "RE", "dump", "stringliteral.json")

WORKSPACE = os.path.join(PROJECT, "workspace")
UNITS = os.path.join(WORKSPACE, "units.json")
GLOSSARY = os.path.join(WORKSPACE, "glossary.json")
STORE = os.path.join(WORKSPACE, "translations.json")

JP_RE = re.compile(r"[぀-ヿ一-鿿ｦ-ﾟ]")


def has_jp(s: object) -> bool:
    return isinstance(s, str) and bool(JP_RE.search(s))


# --- control-code masking -------------------------------------------------
#
# TMP rich text and the Dialogue System's own markup must survive translation
# byte-identical. Each code becomes a sentinel; the set is compared before and
# after, and a mismatch is a hard failure, never a silent repair.
#
# WORD_INSERT codes resolve to a noun at runtime, so English needs a space
# around them where Japanese needs none. Everything else is decoration and must
# stay tight against its neighbours.

TAG_RE = re.compile(
    r"""(
        <\s*/?\s*(?:b|i|u|s|size|color|sprite|link|align|font|mark|
                    voffset|cspace|line-height|indent|pos|space|width|
                    style|gradient|rotate|nobr|noparse|sup|sub|lowercase|
                    uppercase|smallcaps|allcaps|alpha|material|br)
         [^<>]*>
      | \[[a-zA-Z][a-zA-Z0-9_]*(?:=[^\]]*)?\]      # Dialogue System [var=...] / [pic=1]
      | \{[A-Za-z0-9_]+\}                          # {0} / {name}
      | \\n | \\r
    )""",
    re.VERBOSE,
)

# Codes that expand to a WORD at runtime -> pad with a space in English.
WORD_INSERT_RE = re.compile(r"^(?:\{[A-Za-z0-9_]+\}|\[var=[^\]]*\]|\[lua\([^)]*\)\])$")


def mask(text: str) -> tuple[str, dict[str, str]]:
    """Replace every control code with a sentinel. Returns (masked, mapping)."""
    codes: dict[str, str] = {}

    def sub(m: re.Match) -> str:
        key = f"\u27e6{len(codes)}\u27e7"
        codes[key] = m.group(0)
        return key

    return TAG_RE.sub(sub, text), codes


def unmask(text: str, codes: dict[str, str]) -> str:
    for key, code in codes.items():
        text = text.replace(key, code)
    return text


def placeholders(text: str) -> list[str]:
    """The sentinel multiset, in order. Compared source vs translation."""
    return re.findall(r"\u27e6\d+\u27e7", text)


def is_word_insert(code: str) -> bool:
    return bool(WORD_INSERT_RE.match(code))
