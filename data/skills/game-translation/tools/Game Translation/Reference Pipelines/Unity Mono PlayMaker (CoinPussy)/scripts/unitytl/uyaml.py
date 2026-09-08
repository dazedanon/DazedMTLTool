#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
uyaml.py — minimal streaming reader for AssetRipper-exported Unity YAML.

A real YAML parser is unusable here: the exported scenes reach 93 MB, and Unity's
`!u!114 &13950` local tags need custom constructors. Everything this pipeline
needs is shape-restricted (flat mappings, scalar lists, and lists of flat
mappings at a known indent), so a line/indent scanner is both faster and safer.

Public surface:
    decode_scalar(raw)      YAML scalar -> str (handles both quote styles)
    iter_lines(path)        (lineno, indent, stripped) for each non-blank line
    Block                   an indent-delimited region of a file
    read_block(...)         parse one region into {field: value}
    hexbytes / hex_i32 / hex_u32   Unity's hex-blob array encodings
"""

import re

_ESCAPES = {
    "0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n",
    "v": "\v", "f": "\f", "r": "\r", "e": "\x1b", " ": " ", '"': '"',
    "/": "/", "\\": "\\", "N": "\x85", "_": "\xa0", "L": " ", "P": " ",
}


def _unescape_double(s: str) -> str:
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c != "\\":
            out.append(c)
            i += 1
            continue
        i += 1
        if i >= n:
            break
        e = s[i]
        if e == "x" or e == "u" or e == "U":
            width = {"x": 2, "u": 4, "U": 8}[e]
            hexpart = s[i + 1:i + 1 + width]
            try:
                out.append(chr(int(hexpart, 16)))
                i += 1 + width
                continue
            except ValueError:
                out.append(e)
                i += 1
                continue
        out.append(_ESCAPES.get(e, e))
        i += 1
    return "".join(out)


def decode_scalar(raw: str) -> str:
    """Decode a single-line YAML scalar as emitted by AssetRipper."""
    s = raw.strip()
    if not s:
        return ""
    if s[0] == '"':
        # Trailing content after the closing quote never occurs in these files.
        body = s[1:-1] if s.endswith('"') and len(s) > 1 else s[1:]
        return _unescape_double(body)
    if s[0] == "'":
        body = s[1:-1] if s.endswith("'") and len(s) > 1 else s[1:]
        return body.replace("''", "'")
    return s


def iter_lines(path):
    """Yield (lineno, indent, stripped_line) for every non-blank line."""
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n").rstrip("\r")
            if not line.strip():
                continue
            yield lineno, len(line) - len(line.lstrip(" ")), line.lstrip(" ")


def hexbytes(v: str) -> bytes:
    """Unity serializes byte blobs as a bare lowercase hex string (may be empty)."""
    s = (v or "").strip()
    if not s:
        return b""
    if len(s) % 2:
        s = s[:-1]
    try:
        return bytes.fromhex(s)
    except ValueError:
        return b""


def _ints(v: str, signed: bool):
    b = hexbytes(v)
    return [int.from_bytes(b[i:i + 4], "little", signed=signed)
            for i in range(0, len(b) - 3, 4)]


def hex_i32(v: str):
    return _ints(v, True)


def hex_u32(v: str):
    return _ints(v, False)


_KV_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?:\s(.*))?$")


class Block:
    """Fields of one indent-delimited YAML mapping.

    `fields[name]` is a str for a scalar, or a list for a sequence. Sequence
    items are strs for scalar sequences and dicts for mapping sequences; nested
    mappings deeper than the item's own level are dropped (nothing this pipeline
    reads lives there).
    """

    __slots__ = ("fields", "lineno")

    def __init__(self, lineno=0):
        self.fields = {}
        self.lineno = lineno

    def s(self, name, default=""):
        v = self.fields.get(name, default)
        return v if isinstance(v, str) else default

    def list(self, name):
        v = self.fields.get(name)
        return v if isinstance(v, list) else []

    def __repr__(self):
        return f"<Block line={self.lineno} fields={sorted(self.fields)}>"


def parse_block(lines, start, base_indent, lineno=0):
    """Parse the mapping whose fields sit at `base_indent`, starting at lines[start].

    `lines` is a list of (lineno, indent, text). Returns (Block, next_index) where
    next_index is the first line at indent < base_indent (i.e. outside the block).
    """
    blk = Block(lineno)
    i, n = start, len(lines)
    while i < n:
        _ln, indent, text = lines[i]
        if indent < base_indent:
            break
        if indent > base_indent:
            i += 1
            continue

        if text.startswith("- "):
            # Sequence item belonging to the *enclosing* mapping — caller's job.
            break

        m = _KV_RE.match(text)
        if not m:
            i += 1
            continue
        key, inline = m.group(1), m.group(2)
        i += 1

        if inline is not None and inline.strip() not in ("", "[]"):
            blk.fields[key] = inline
            continue
        if inline is not None and inline.strip() == "[]":
            blk.fields[key] = []
            continue

        # Either an empty scalar or a nested sequence/mapping on following lines.
        item_indent = base_indent
        if i < n and lines[i][1] >= base_indent and lines[i][2].startswith("- "):
            item_indent = lines[i][1]
        elif i < n and lines[i][1] > base_indent:
            # Nested mapping — skip it wholesale.
            deeper = lines[i][1]
            while i < n and lines[i][1] >= deeper:
                i += 1
            blk.fields.setdefault(key, "")
            continue
        else:
            blk.fields[key] = ""
            continue

        seq = []
        while i < n and lines[i][1] == item_indent and lines[i][2].startswith("- "):
            head = lines[i][2][2:]
            i += 1
            hm = _KV_RE.match(head)
            if hm and not head.startswith('"') and not head.startswith("'"):
                item = {}
                hkey, hval = hm.group(1), hm.group(2)
                item[hkey] = hval if hval is not None else ""
                sub_indent = item_indent + 2
                while i < n and lines[i][1] >= sub_indent:
                    if lines[i][1] == sub_indent:
                        sm = _KV_RE.match(lines[i][2])
                        if sm:
                            item[sm.group(1)] = sm.group(2) if sm.group(2) is not None else ""
                    i += 1
                seq.append(item)
            else:
                seq.append(head)
                # A scalar item can still be followed by deeper lines in odd exports.
                sub_indent = item_indent + 2
                while i < n and lines[i][1] >= sub_indent:
                    i += 1
        blk.fields[key] = seq
    return blk, i
