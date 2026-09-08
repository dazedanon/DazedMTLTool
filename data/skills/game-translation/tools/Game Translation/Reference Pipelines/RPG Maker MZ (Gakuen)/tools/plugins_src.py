#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
plugins_src.py - the FOURTH text track: Japanese hardcoded in plugin SOURCE.

The three tracks the pipeline already had all produce units, and every check is
per-unit, so anything with no unit is structurally invisible:

    data/*.json        -> units          extract/inject
    js/plugins.js      -> parameters     plugins_js.py
    SkillTreeConfig.js -> a JS config    skilltree_config.py
    js/plugins/*.js    -> THIS FILE      string literals inside plugin code

A player found this track by walking into the casino: `Tatsu_HighAndLowVerMZ`,
`Tatsu_PokerGames` and `Tatsu_BlackJack` draw their entire UI from literals in
their own source, so three whole minigames shipped in Japanese while every
check in the pipeline reported 100%.

WHY THIS IS NOT JUST "TRANSLATE THE JAPANESE STRINGS"

A plugin's Japanese literals are a mix of text it DRAWS and text it MATCHES,
and the two are indistinguishable without reading the code:

    if (name === "普通")                 <- a font call name the author types
    this.addCommand("大きい", "high")      <- drawn on a button

Translating the first breaks font switching with no error. So the ledger stores
an explicit English string per literal and NOTHING is translated by pattern.
Entries come from a triage+refutation pass, and the deterministic guards below
are what make it safe to re-apply.

GUARDS

  * every replacement is verified by PARSING the patched file and reading the
    literal's decoded value back - not merely "the file still parses". A stray
    quote or a mangled escape changes the string the game sees without ever
    being a syntax error.
  * a literal that also appears in a data/ note, a plugin command argument or a
    plugins.js parameter is refused outright: that is what a lookup key looks
    like.
  * applying is idempotent and re-runnable from a pristine js/ - it matches on
    the JAPANESE body, so a second run finds nothing to do.
"""
import argparse
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from js_strings import literals, JP                       # noqa: E402

LEDGER = "plugins_src.json"

_SIMPLE = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
           "v": "\v", "0": "\0", "\\": "\\", "'": "'", '"': '"', "`": "`",
           "\n": ""}


def decode(body):
    """Decode a JS string-literal body to the value the engine sees."""
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c != "\\" or i + 1 >= n:
            out.append(c)
            i += 1
            continue
        d = body[i + 1]
        if d == "u":
            if i + 2 < n and body[i + 2] == "{":
                j = body.index("}", i + 3)
                out.append(chr(int(body[i + 3:j], 16)))
                i = j + 1
            else:
                out.append(chr(int(body[i + 2:i + 6], 16)))
                i += 6
        elif d == "x":
            out.append(chr(int(body[i + 2:i + 4], 16)))
            i += 4
        elif d in _SIMPLE:
            out.append(_SIMPLE[d])
            i += 2
        else:
            # An unknown escape is just the character - `\C` is `C`. Preserving
            # this exactly is why RPG Maker control codes must be written `\\C`.
            out.append(d)
            i += 2
    return "".join(out)


def escape_for(body, quote):
    """Make `body` safe to sit inside `quote` without changing its value."""
    if "\n" in body or "\r" in body:
        raise ValueError("raw newline in replacement - escape it as \\n")
    out, i, n = [], 0, len(body)
    while i < n:
        c = body[i]
        if c == "\\" and i + 1 < n:
            out.append(body[i:i + 2])
            i += 2
            continue
        if c == quote:
            out.append("\\" + c)
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------


def _key_set(root, jp_data=None):
    r"""Every string that is a LOOKUP KEY somewhere, as an EXACT-match set.

    Exact, not substring. A blob + `in` test looks equivalent and is not: it
    condemned `所持金` ("Money", drawn by YKP_ShopManager) because an unrelated
    plugin declares a notetag named `所持金消費` that merely CONTAINS it. Short
    strings are exactly the ones that are UI labels, so a substring test fails
    hardest where it matters most.
    """
    import glob
    import re
    keys = set()
    tagname = re.compile(r"<([^<>:]+)[:>]")

    def add(v):
        if isinstance(v, str) and v.strip():
            keys.add(v.strip())

    def add_json(v):
        """Plugin params and command args nest JSON inside strings, N deep."""
        add(v)
        if isinstance(v, str) and v[:1] in "[{\"":
            try:
                add_json(json.loads(v))
            except ValueError:
                pass
        elif isinstance(v, list):
            for x in v:
                add_json(x)
        elif isinstance(v, dict):
            for k, x in v.items():
                add(k)
                add_json(x)

    def visit(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "note" and isinstance(v, str):
                    # The NAME is the key; the value is often drawn text.
                    for m in tagname.finditer(v):
                        add(m.group(1))
                elif (k == "parameters" and isinstance(v, list)
                      and o.get("code") in (356, 357)):
                    for x in v:
                        add_json(x)
                visit(v)
        elif isinstance(o, list):
            for v in o:
                visit(v)

    for p in glob.glob(os.path.join(root, "data", "*.json")):
        try:
            visit(json.load(open(p, encoding="utf-8")))
        except ValueError:
            pass

    t = open(os.path.join(root, "js", "plugins.js"), encoding="utf-8-sig").read()
    arr = json.loads(re.search(r"\$plugins\s*=\s*(\[.*\])\s*;", t, re.S).group(1))
    for pl in arr:
        for k, v in (pl.get("parameters") or {}).items():
            add(k)
            add_json(v)

    # DATABASE NAMES are the place a key hides that a note scan cannot see: a
    # skill name lives in Skills.json `name`, and SkillTree matches on it.
    #
    # This must read the PRISTINE Japanese database. Against the patched data/
    # the names are already English, so a Japanese literal never matches and
    # the guard passes everything while looking like it ran.
    if jp_data:
        for q in glob.glob(os.path.join(jp_data, "*.json")):
            b = os.path.basename(q)
            if b.startswith("Map") and b != "MapInfos.json":
                continue
            try:
                d = json.load(open(q, encoding="utf-8"))
            except ValueError:
                continue
            if isinstance(d, list):
                for o in d:
                    if isinstance(o, dict):
                        add(o.get("name"))
    return keys


def _parses(text):
    try:
        import esprima
    except ImportError:
        return None
    try:
        esprima.parseScript(text, tolerant=False)
        return True
    except Exception as e:
        print("     %s" % e)
        return False


def apply(root, ledger_path, backup=True, jp_data=None):
    led = json.load(open(ledger_path, encoding="utf-8"))
    keys = _key_set(root, jp_data)
    if not jp_data:
        print("  (no --jp-data: the database-name key guard is INACTIVE)")
    written = skipped = 0
    refused = []

    for plugin, entries in sorted(led.get("plugins", {}).items()):
        path = os.path.join(root, "js", "plugins", plugin + ".js")
        if not os.path.exists(path):
            print("  ! missing js/plugins/%s.js" % plugin)
            continue
        src = open(path, encoding="utf-8-sig").read()
        want = {}
        for e in entries:
            jp, en = e["jp"], e["en"]
            if jp.strip() in keys:
                refused.append((plugin, jp, "appears as a lookup key"))
                continue
            if jp in want and want[jp] != en:
                refused.append((plugin, jp, "two different replacements"))
                continue
            want[jp] = en

        # Right to left, so every earlier offset stays valid.
        hits = [(q, body, a, b) for q, body, a, b in literals(src)
                if body in want]
        if not hits:
            skipped += len(want)
            continue
        out = src
        for q, body, a, b in sorted(hits, key=lambda h: -h[2]):
            try:
                rep = escape_for(want[body], q)
            except ValueError as ex:
                refused.append((plugin, body, str(ex)))
                continue
            out = out[:a] + q + rep + q + out[b:]

        if _parses(out) is False:
            print("  ! %s DOES NOT PARSE after patching - not written" % plugin)
            continue

        # The real gate: read every replaced literal back and confirm it now
        # DECODES to the intended value. A mangled escape is not a syntax error.
        got = {decode(body) for _q, body, _a, _b in literals(out)}
        bad = [jp for jp, en in want.items()
               if decode(en) not in got and any(
                   decode(b) == decode(jp) for _q, b, _a, _b in literals(src))]
        if bad:
            print("  ! %s: %d replacement(s) did not read back - not written"
                  % (plugin, len(bad)))
            for jp in bad[:5]:
                print("      %s" % jp[:60])
            continue

        if out == src:
            skipped += len(want)
            continue
        if backup:
            shutil.copy2(path, path + ".bak_src")
        with io.open(path, "w", encoding="utf-8", newline="") as f:
            f.write(out)
        n = len(hits)
        written += n
        print("  %-40s %3d literal(s)" % (plugin, n))

    for plugin, jp, why in refused:
        print("  ! REFUSED %-28s %-28s %s" % (plugin, jp[:28], why))
    print("plugins/*.js: wrote %d literal(s), %d already English, %d refused"
          % (written, skipped, len(refused)))
    return 0 if not refused else 1


def check(root, ledger_path):
    """Report any enabled plugin source still holding Japanese we know about."""
    led = json.load(open(ledger_path, encoding="utf-8"))
    left = 0
    for plugin, entries in sorted(led.get("plugins", {}).items()):
        path = os.path.join(root, "js", "plugins", plugin + ".js")
        if not os.path.exists(path):
            continue
        bodies = {b for _q, b, _a, _b in literals(open(path, encoding="utf-8-sig").read())}
        for e in entries:
            if e["jp"] in bodies:
                left += 1
                print("  STILL JP  %-34s %s" % (plugin, e["jp"][:50]))
    print("plugins/*.js: %d ledger entr%s still Japanese"
          % (left, "y" if left == 1 else "ies"))
    return 1 if left else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("apply", "check"))
    ap.add_argument("--game", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--jp-data", default=None,
                    help="pristine JAPANESE data/ dir; without it the "
                         "database-name key guard cannot fire")
    a = ap.parse_args()
    if a.action == "apply":
        return apply(a.game, a.ledger, jp_data=a.jp_data)
    return check(a.game, a.ledger)


if __name__ == "__main__":
    sys.exit(main())
