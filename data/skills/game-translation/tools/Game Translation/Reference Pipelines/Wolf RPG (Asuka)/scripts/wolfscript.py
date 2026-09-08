"""Shared WOLF-decompile primitives used by the pipeline tools.

Keeps the control-code regex, escape/unescape, cell width, and depth-0 literal
parsing in one place so every tool tokenizes identically. Import from here; do
not re-implement per tool.
"""
import json as _json
import re
import sys
import unicodedata
from pathlib import Path


def die(msg, code=2):
    """Clean error + nonzero exit for bad user input (no raw traceback)."""
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as e:
        die(f"cannot read {path}: {e}")


def load_json(path):
    try:
        return _json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        die(f"cannot read {path}: {e}")
    except _json.JSONDecodeError as e:
        die(f"cannot parse {path}: {e}")

# Control codes, ruby first (payload translatable). NO trailing-letter lookahead
# on the single-letter branch on purpose: the char after \E or \n differs JP vs
# EN, and multiset comparison only works if both sides tokenize the same way.
WOLF_CODE_RE = re.compile(
    r"\\r\[[^\]]*\]"
    r"|\\[A-Za-z]+\[[^\]]*\]"
    r"|\\[A-Za-z]"
    r"|\\[.!^\\<>|]"
    r"|@\d+"
)
_RUBY_RE = re.compile(r"^\\r\[[^\]]*\]$")

# A single wscript Message line: `<indent>Message "<literal>"`
MSG_LINE_RE = re.compile(r'^(\s*)Message "((?:\\.|[^"\\])*)"\s*$')

# Display commands whose string literals reach the screen.
DISPLAY_CMDS = frozenset(
    {"Message", "Picture", "SetString", "choose", "case", "Choices", "StringCondition"})


def cells(s):
    """Rendered cell width (CJK/fullwidth = 2, else 1); control codes are zero."""
    vis = WOLF_CODE_RE.sub("", s)
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in vis)


def code_multiset(s):
    """Sorted must-preserve control codes. Ruby is droppable, so excluded."""
    return sorted(m for m in WOLF_CODE_RE.findall(s) if not _RUBY_RE.match(m))


def unescape(s):
    """wscript string literal -> raw text (mirrors WolfDawn's lexer)."""
    out, i, n = [], 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        nxt = s[i + 1] if i + 1 < n else None
        out.append({"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, "\\" + (nxt or "")))
        i += 1 if nxt is None else 2
    return "".join(out)


def escape(s):
    return (s.replace("\\", "\\\\").replace('"', '\\"')
             .replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t"))


def literal_spans(line):
    """(start, end) of depth-0 string literals (incl. quotes). Bracketed operand
    annotations sit at depth > 0 and are skipped, so DB lookup-name args and
    CSelf `[n "label"]` comments are never mistaken for display text."""
    spans, depth, i, n = [], 0, 0, len(line)
    while i < n:
        c = line[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth = max(0, depth - 1)
        elif c == '"':
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == '"':
                    break
                j += 1
            if depth == 0:
                spans.append((i, j + 1))
            i = j
        i += 1
    return spans


def command_name(line):
    """Leading command token of a wscript line, or '' for markers/comments."""
    t = line.strip()
    if not t or t.startswith("#") or t.startswith("}"):
        return ""
    return t.split(" ", 1)[0].split("(", 1)[0]


def iter_display_literals(text):
    """Yield (lineno, cmd, literal_text) for every depth-0 display literal.
    For Database commands only the FIRST literal (the written value) is display;
    the rest are type/data/field lookup names."""
    for lno, line in enumerate(text.splitlines(), 1):
        line = line.rstrip("\n")
        cmd = command_name(line)
        spans = literal_spans(line)
        if not spans:
            continue
        if cmd in DISPLAY_CMDS:
            idxs = range(len(spans))
        elif cmd == "Database":
            idxs = (0,)
        else:
            continue
        for k in idxs:
            a, b = spans[k]
            yield lno, cmd, unescape(line[a + 1:b - 1])


def db_types(db_json):
    """Normalize a db-json dict to its list of type dicts."""
    return db_json.get("types") if isinstance(db_json, dict) else db_json
