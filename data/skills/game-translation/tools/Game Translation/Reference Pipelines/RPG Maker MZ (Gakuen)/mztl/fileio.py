#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fileio.py - read and re-render a game data file in ITS OWN conventions.

RPG Maker ships `Map001.json` as a single minified line and some files with a
UTF-8 BOM. `json.dump` defaults turn a three-string fix into a whole-file diff,
which breaks binary patch distribution and makes review impossible. So the
serialization shape is sniffed on read and replayed on write:

    * BOM present / absent
    * indent: None (minified, `separators=(",",":")`) or the exact string
    * CRLF vs LF
    * trailing newline

`ensure_ascii=False` always, or the file inflates into `\\uXXXX` escapes and
quadruples in size.
"""

import io
import os
import json
import stat
import tempfile
import time
import re


class Rendered(object):
    __slots__ = ("bom", "indent", "crlf", "trailing_nl", "separators")

    def __init__(self, bom, indent, crlf, trailing_nl):
        self.bom = bom
        self.indent = indent
        self.crlf = crlf
        self.trailing_nl = trailing_nl
        self.separators = (",", ":") if indent is None else None


_INDENT_RE = re.compile(r"\n([ \t]+)[\"\[\]{}]")


def load(path):
    """Returns (data, Rendered)."""
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    decoded = raw.decode("utf-8-sig")
    m = _INDENT_RE.search(decoded)
    if m:
        ws = m.group(1)
        indent = ws if "\t" in ws else len(ws)
    else:
        indent = None
    crlf = "\r\n" in decoded
    trailing_nl = decoded.endswith("\n") or decoded.endswith("\r\n")
    return json.loads(decoded), Rendered(bom, indent, crlf, trailing_nl)


def dumps(data, r):
    s = json.dumps(data, ensure_ascii=False, indent=r.indent,
                   separators=r.separators)
    if r.trailing_nl:
        s += "\n"
    if r.crlf:
        s = s.replace("\n", "\r\n")
    return s


def save(path, data, r):
    """Atomic write, in the destination directory, re-parsed before it lands.

    A malformed render must never reach the game folder even for an instant:
    an interrupted write that leaves a data file truncated means the game will
    not boot."""
    if os.path.islink(path):
        raise IOError("refusing to write through a symlink: %s" % path)
    if os.path.exists(path) and not os.path.isfile(path):
        raise IOError("not a regular file: %s" % path)
    text = dumps(data, r)
    payload = text.encode("utf-8")
    if r.bom:
        payload = b"\xef\xbb\xbf" + payload

    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".",
                               suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        # Prove the render parses before it can be seen by the game.
        with io.open(tmp, encoding="utf-8-sig") as f:
            json.load(f)
        if os.path.exists(path):
            try:
                os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
            except OSError:
                pass
        _replace_retry(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _replace_retry(src, dst, attempts=5):
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.1 * (i + 1))
