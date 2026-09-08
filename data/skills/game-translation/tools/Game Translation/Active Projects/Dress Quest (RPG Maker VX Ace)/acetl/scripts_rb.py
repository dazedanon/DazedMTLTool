#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
scripts_rb.py - the SECOND track: Japanese baked into the RGSS3 scripts.

RPG Maker MV keeps its UI text in `plugins.js` parameters. VX Ace keeps it in
Ruby source, inside `Data\Scripts.rvdata2`: an array of
`[id, name, Zlib-deflated UTF-8 source]`, 143 sections in this game. `Vocab`
alone holds 50 player-visible strings ("購入する", "%sは倒れた！"), and the
custom menus add more.

TWO TRACKS, NEVER MIXED
    `Data\*.rvdata2` flows store -> inject -> `out\Data`. The scripts are
    edited THROUGH THIS LEDGER and written back into `Scripts.rvdata2`. Mixing
    them means an inject silently reverts a script edit, or a script edit is
    lost on the next inject. Everything here reads and writes only
    `Scripts.rvdata2`.

SAFETY
    * Only sections whose source actually changes are recompressed; every other
      section keeps its original deflate bytes, so the file stays byte-identical
      outside the edit.
    * A replacement is applied only when the recorded literal still occurs on
      the recorded line, ELSE IT IS REFUSED. A ledger that has drifted from the
      source is how a patch corrupts a script.
    * Ruby syntax is checked after the edit as far as Python can: balanced
      quotes on the line, no newline injected, and the section still decodes.
    * `translate` defaults to FALSE on every entry. A literal is translated only
      after a human has looked at the audit and said so, because a `when` or
      `==` operand, a hash key, a filename or a save-data key looks exactly like
      a label and breaks silently.
"""

import io
import os
import re
import json
import zlib
import shutil
import datetime
import collections

from . import codes, store
from . import rvmarshal as M

LEDGER = "scripts_rb.json"

# A Ruby double- or single-quoted literal, non-greedy, escape-aware.
_LITERAL_RE = re.compile(r'"(?:\\.|[^"\\])*"' + r"|'(?:\\.|[^'\\])*'")
_COMMENT_RE = re.compile(r"(?<!\\)#")

# Contexts that mean "this string is read back as a key", i.e. never translate.
_KEY_CONTEXT_RE = re.compile(
    r"\bwhen\b|==|!=|\.include\?|\.index\(|\[\s*['\"]|=>\s*$|"
    r"Cache\.|\.png|\.ogg|\.wav|load_data|save_data|Font\.default_name|"
    r"\bfilename\b|\bpath\b|\brequire\b|\bcase\b")
# Contexts that mean "this string reaches the screen".
_DISPLAY_CONTEXT_RE = re.compile(
    r"draw_text|draw_text_ex|add_command|set_text|set_help_window_text|"
    r"\$game_message|\.text\s*=|Vocab|add_originals|refresh|"
    r"draw_item|help_window|\btext\b")


# --------------------------------------------------------------------------
# reading Scripts.rvdata2
# --------------------------------------------------------------------------
def load_sections(scripts_path):
    """[(index, id, name, source_text, raw_deflated_bytes)].

    `source_text` is None - not "" - when the blob does not inflate. This game
    ships 14 sections that are legitimately EMPTY (the `▼ モジュール` style
    separators), so "empty" and "broken" have to be distinguishable or a
    post-write integrity check condemns every one of them."""
    arr = M.load_file(scripts_path)
    out = []
    for i, row in enumerate(arr.items):
        if not isinstance(row, M.RArray) or len(row.items) < 3:
            continue
        sid = row.items[0]
        name = row.items[1].text() if isinstance(row.items[1], M.RString) else ""
        blob = row.items[2].data if isinstance(row.items[2], M.RString) else b""
        try:
            src = zlib.decompress(blob).decode("utf-8", "replace")
        except zlib.error:
            src = None
        out.append((i, sid, name, src, blob))
    return arr, out


def dump(cfg, out_dir, verbose=True):
    """Write every section to a .rb file, for reading and grepping."""
    _arr, sections = load_sections(cfg.scripts_file)
    os.makedirs(out_dir, exist_ok=True)
    for i, sid, name, src, _blob in sections:
        safe = re.sub(r'[<>:"/\\|?*]', "_", name) or "_"
        with io.open(os.path.join(out_dir, "%03d_%s.rb" % (i, safe)), "w",
                     encoding="utf-8", newline="\n") as f:
            f.write(src)
    if verbose:
        print("wrote %d script sections -> %s" % (len(sections), out_dir))
    return len(sections)


# --------------------------------------------------------------------------
# the ledger
# --------------------------------------------------------------------------
def _classify(line):
    stripped = line.strip()
    if stripped.startswith("#"):
        return "comment"
    if _KEY_CONTEXT_RE.search(line):
        return "key"
    if _DISPLAY_CONTEXT_RE.search(line):
        return "display"
    if re.match(r"^\s*[A-Z][A-Za-z0-9_]*\s*=\s*", line):
        # `ShopBuy = "購入する"` - a Vocab-style constant.
        return "display"
    return "unknown"


def _strip_comment(line):
    """Everything before an unquoted `#`."""
    out = []
    in_s = None
    i = 0
    while i < len(line):
        c = line[i]
        if in_s:
            if c == "\\":
                out.append(line[i:i + 2])
                i += 2
                continue
            if c == in_s:
                in_s = None
        elif c in "\"'":
            in_s = c
        elif c == "#":
            break
        out.append(c)
        i += 1
    return "".join(out)


def scan(cfg):
    """Every Japanese literal in every script section, with its context."""
    _arr, sections = load_sections(cfg.scripts_file)
    found = []
    for i, sid, name, src, _blob in sections:
        for ln, line in enumerate(src.split("\n"), 1):
            code_part = _strip_comment(line)
            for m in _LITERAL_RE.finditer(code_part):
                lit = m.group(0)
                inner = lit[1:-1]
                if not codes.has_jp(inner):
                    continue
                found.append({
                    "section": i, "name": name, "line": ln,
                    "literal": lit, "jp": inner, "en": "",
                    "kind": _classify(code_part),
                    "context": line.strip()[:120],
                    "translate": False,
                })
            if not code_part.strip() and codes.has_jp(line):
                pass                     # a pure comment: not a candidate
    return found


def refresh(cfg, store_dir, verbose=True):
    """Rebuild the ledger, keeping every `en`, `translate` and `note` already
    set by hand."""
    path = os.path.join(store_dir, LEDGER)
    old = {}
    if os.path.exists(path):
        for e in store.read_json(path).get("entries", []):
            old[(e["section"], e["line"], e["jp"])] = e

    entries = scan(cfg)
    kept = 0
    for e in entries:
        prev = old.get((e["section"], e["line"], e["jp"]))
        if prev:
            for k in ("en", "translate", "note", "width", "locked"):
                if prev.get(k) not in (None, "", False):
                    e[k] = prev[k]
            kept += 1
    store.write_json(path, {
        "meta": {"source": os.path.basename(cfg.scripts_file),
                 "generated": datetime.datetime.now().isoformat(timespec="seconds")},
        "entries": entries,
    })
    if verbose:
        by_kind = collections.Counter(e["kind"] for e in entries)
        print("scripts_rb: %d Japanese literal(s) across %d section(s)"
              % (len(entries), len({e["section"] for e in entries})))
        for k, n in by_kind.most_common():
            print("   %-8s %d" % (k, n))
        print("   %d carried over from the previous ledger" % kept)
        print("   nothing is translated until an entry has translate=true")
    return entries


def pending(store_dir):
    path = os.path.join(store_dir, LEDGER)
    if not os.path.exists(path):
        return []
    return [e for e in store.read_json(path).get("entries", [])
            if e.get("translate") and not (e.get("en") or "").strip()]


# --------------------------------------------------------------------------
# writing back
# --------------------------------------------------------------------------
def _ruby_literal(en, quote):
    """Build the replacement literal.

    `jp` and `en` in the ledger are SOURCE-LEVEL text - exactly the characters
    between the quotes, escapes included - because Vocab is full of strings
    like `お金を %s\\G 手に入れた！` where the `\\G` must survive as two
    characters of Ruby source. Re-escaping here would turn it into `\\\\G` and
    print a literal backslash in game. So nothing is rewritten; the string is
    only CHECKED, and an unescapable one is refused rather than mangled."""
    return quote + en + quote


def _literal_is_safe(en, quote):
    """An unescaped closing quote, a trailing lone backslash, or a `#{}` that
    would start interpolating - each would change what Ruby parses."""
    i = 0
    while i < len(en):
        c = en[i]
        if c == "\\":
            if i + 1 >= len(en):
                return "ends with a lone backslash"
            i += 2
            continue
        if c == quote:
            return "contains an unescaped %s" % quote
        if quote == '"' and en.startswith("#{", i):
            return "contains an unescaped #{ interpolation"
        i += 1
    if "\n" in en or "\r" in en:
        return "contains a newline"
    return ""


def check(cfg, store_dir, verbose=True):
    """Prove every ledger entry still matches the shipped source."""
    path = os.path.join(store_dir, LEDGER)
    if not os.path.exists(path):
        print("no ledger - run `scripts refresh` first")
        return 1
    entries = store.read_json(path).get("entries", [])
    _arr, sections = load_sections(cfg.scripts_file)
    src_by_index = {i: src for i, _sid, _n, src, _b in sections}
    stale = []
    for e in entries:
        src = src_by_index.get(e["section"])
        if src is None:
            stale.append((e, "section %d is gone" % e["section"]))
            continue
        lines = src.split("\n")
        if e["line"] > len(lines) or e["literal"] not in lines[e["line"] - 1]:
            stale.append((e, "literal not on line %d any more" % e["line"]))
    if verbose:
        print("scripts_rb check: %d entries, %d stale" % (len(entries), len(stale)))
        for e, why in stale[:20]:
            print("   ! %s:%d %s - %s" % (e["name"], e["line"], e["jp"][:30], why))
    return 1 if stale else 0


def apply(cfg, store_dir, dry_run=False, verbose=True):
    """Write every `translate: true` entry with an `en` into Scripts.rvdata2.

    In place, in the game folder, after a timestamped backup - this is the
    in-place track and it never flows through `out\\Data`."""
    path = os.path.join(store_dir, LEDGER)
    if not os.path.exists(path):
        print("no ledger - run `scripts refresh` first")
        return 1
    entries = [e for e in store.read_json(path).get("entries", [])
               if e.get("translate") and (e.get("en") or "").strip()]
    if not entries:
        print("nothing marked translate=true with an English string")
        return 0

    arr, sections = load_sections(cfg.scripts_file)
    by_section = collections.defaultdict(list)
    for e in entries:
        by_section[e["section"]].append(e)

    changed = collections.Counter()
    problems = []
    expected = {}                    # index -> the source text we intend
    for i, sid, name, src, _blob in sections:
        todo = by_section.get(i)
        if not todo:
            continue
        lines = src.split("\n")
        for e in sorted(todo, key=lambda x: -x["line"]):
            ln = e["line"] - 1
            if ln >= len(lines) or e["literal"] not in lines[ln]:
                problems.append("%s:%d %r no longer on that line - REFUSED"
                                % (name, e["line"], e["jp"][:30]))
                continue
            # An entry may carry `en_lines` instead of `en` when the literal
            # sits inside an array the engine draws ROW BY ROW - this game's
            # world map declares `EXPLAN[n] = [line1, line2]` and draws each
            # element on its own line, but the author only ever filled the
            # first. Substituting `"a", "b"` for the single literal fills both
            # without touching the brackets, so the edit stays a one-literal
            # replacement and every check below still applies.
            parts = e.get("en_lines") or [e["en"]]
            bad = [_literal_is_safe(p, e["literal"][0]) for p in parts]
            unsafe = next((b for b in bad if b), "")
            if unsafe:
                problems.append("%s:%d translation %s - REFUSED"
                                % (name, e["line"], unsafe))
                continue
            new_lit = ", ".join(_ruby_literal(p, e["literal"][0]) for p in parts)
            lines[ln] = lines[ln].replace(e["literal"], new_lit, 1)
            changed[i] += 1
        new_src = "\n".join(lines)
        expected[i] = new_src
        if not dry_run and changed.get(i):
            row = arr.items[i]
            blob = zlib.compress(new_src.encode("utf-8"), 9)
            row.items[2] = M.RString(blob, list(row.items[2].ivars))

    if verbose:
        print("scripts_rb apply%s" % (" (dry run)" if dry_run else ""))
        for i, n in changed.most_common():
            print("   %-40s %d string(s)" % (sections[i][2], n))
        print("   sections changed: %d   strings: %d"
              % (len(changed), sum(changed.values())))
        for p in problems:
            print("   ! " + p)
    if problems:
        print("REFUSED - fix the ledger (scripts refresh) and re-run")
        return 1
    if dry_run:
        return 0

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = cfg.scripts_file + ".bak_" + stamp
    shutil.copy2(cfg.scripts_file, backup)
    M.save_file(cfg.scripts_file, arr)
    # Read the file back and prove every section is EXACTLY what was intended:
    # the edited ones carry their new source, and every other one is unchanged
    # down to the character. "Does it inflate" is too weak a test - and, as
    # written first, too strong: it condemned the 14 legitimately empty
    # separator sections and rolled back a correct write.
    _arr2, after = load_sections(cfg.scripts_file)
    broken = []
    for i, _sid, name, src, _blob in after:
        want = expected.get(i)
        if src is None:
            broken.append("%s: does not inflate" % name)
        elif want is not None and src != want:
            broken.append("%s: content is not what was written" % name)
    if broken:
        shutil.copy2(backup, cfg.scripts_file)
        print("ROLLED BACK - %d section(s) failed the read-back: %s"
              % (len(broken), broken[:5]))
        return 1
    if verbose:
        print("   backup: %s" % os.path.basename(backup))
    return 0
