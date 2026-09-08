#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
translate_scripts.py - the second track's translation pass.

`tl.py scripts refresh` finds every Japanese literal in `Data\Scripts.rvdata2`
and marks all of them `translate: false`, because a `when` operand, a hash key,
a filename or a save-data key looks exactly like a label and breaks silently.
This is the pass that decides which ones are labels, and translates those.

It exists because the default is "no": after the main run, the game still
showed Japanese on the volume-config screen and in four extra stat rows on the
status screen, both of them hardcoded in this game's own RGSS3 source.

TWO GATES BEFORE ANYTHING IS WRITTEN
  * the model must classify a literal as DISPLAY and say where it is drawn;
  * a static check must not find the same literal used as a `when`/`==`
    operand, a hash key, a `Cache.` argument or a filename ANYWHERE in the
    scripts. Either gate can veto; only both together approve.

`Window_NameInput` is excluded wholesale: its 234 literals are the kana palette
of the name-entry keyboard, and this game contains zero code-303 commands, so
the screen is unreachable. Translating a kana palette into Latin letters would
be a visible defect on a screen nobody can open.

    python tools/translate_scripts.py                # audit, print, write nothing
    python tools/translate_scripts.py --apply        # write en + translate=true
"""

import os
import re
import sys
import json
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import (store, config, parse, measure, scripts_rb,     # noqa: E402
                   client as C)
from acetl import requests as R                                   # noqa: E402

SKIP_SECTIONS = {"Window_NameInput", "Window_NameEdit"}

# Per-script width budgets in half-width cells, read off each window's own
# `window_width` and `standard_padding`. These windows draw with `draw_text`
# and NO wrapping, so a translation past the budget is simply cut off.
#
#   わーるどまっぷ   info window = Graphics.width - command window 140,
#                    minus 24 padding = 476 px = 47 cells, and each EXPLAN
#                    element is one un-wrapped row
#   アイテム合成     window_width 304 -> 280 px = 28 cells
#   ステータス着せ替え a stat label column, measured against the stock labels
WIDTH_BUDGET = {
    "わーるどまっぷ": 46,
    "アイテム合成": 27,
    "ステータス着せ替え": 14,
    "音量調整": 30,
    "回想": 20,
    "ダメージポップアップ": 12,
}
DEFAULT_BUDGET = 40


def budget_for(entry):
    """Cells this literal may occupy, per LINE.

    A per-script number is right for a column of labels and wrong for the one
    help string in the same script that spans the full screen, so an entry may
    carry its own `budget` - the same escape hatch shape as a per-unit waiver,
    and just as visible in the ledger."""
    return entry.get("budget") or WIDTH_BUDGET.get(entry["name"], DEFAULT_BUDGET)


def widest_line(m, text):
    """A Ruby literal can hold an ESCAPED newline - backslash then `n`, two
    source characters - and each side of it is its own drawn row. Splitting on
    a real newline instead measures the volume screen's two-line help text as
    one 83-cell line that no window could hold."""
    if not text:
        return 0
    return max(m.cells(part) for part in text.split(chr(92) + "n"))

SYSTEM = """\
You are localizing an adult Japanese RPG Maker VX Ace game into English. \
These strings are Ruby string literals taken from the game's own RGSS3 \
scripts, each with the source line it sits on.

For each one decide whether it is DISPLAY text - something a player reads on \
screen - or NOT. Not-display means: a hash key, a `when`/`==` operand, a \
filename or asset name, a font name, a save-data key, a debug or console \
string, or a comment. When you are not sure, answer display=false: a wrong \
"false" leaves one label in Japanese, a wrong "true" can break the script \
with no error.

Translate the display ones into terse English UI text. These are labels in \
narrow windows, so keep them SHORT - a stat row, a button, a window title. Use \
RPG Maker's own English where it exists (Evasion, Hit, Critical, M.Evasion, \
"To Next Level"). Keep every `%s`, `%d`, `\\\\G`, `#{...}` and escape exactly \
as written and in the same order. Never introduce a double quote.

Output ONLY a JSON object mapping each number, as a string, to \
{"display": true|false, "en": "<English, or empty when display is false>", \
"why": "<a few words: where it is drawn, or what reads it back>"}.
"""


def static_key_veto(literal, sources):
    """'' if nothing reads this literal back as a key, else the line that does.

    Every pattern requires the literal to BE the operand, in quotes. The first
    version used `when\\s+[^\\n]*LITERAL`, which matches any `when` that merely
    shares a line with the string - and this game writes
    `when 3 then name = "王都バロン"; desc = "..."`, so it vetoed fourteen
    correct world-map labels. A veto that fires on correct text is how the
    whole gate ends up switched off."""
    lit = re.escape(literal)
    q = r"['\"]"
    pats = [
        (r"when\s+" + q + lit + q, "used as a `when` operand"),
        (r"==\s*" + q + lit + q, "compared with =="),
        (q + lit + q + r"\s*==", "compared with =="),
        # A LOOKUP has a receiver immediately before the bracket (`h["k"]`,
        # `rows[0]["k"]`). An array LITERAL has `=`, `,`, `(` or a line start
        # there, and this game defines its world-map descriptions exactly that
        # way - without the lookbehind, fourteen paragraphs of on-screen prose
        # were vetoed as if they were keys.
        (r"(?<=[\w\)\]])\[\s*" + q + lit + q + r"\s*\]", "used as a hash key"),
        (r"Cache\.\w+\(\s*" + q + lit + q, "passed to Cache (an asset name)"),
        (r"include\?\(\s*" + q + lit + q, "used in include?"),
        (r"\bload_data\(\s*" + q + lit, "used as a filename"),
    ]
    for src in sources:
        for p, why in pats:
            m = re.search(p, src)
            if m:
                line = src[:m.start()].count("\n") + 1
                return "%s (line %d: %s)" % (why, line,
                                             m.group(0).strip()[:60])
    return ""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--game", default=None)
    ap.add_argument("--model", default=R.MODEL_DEFAULT)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)

    cfg = config.Config()
    if a.game:
        cfg.game_root = a.game

    path = os.path.join(a.store, "scripts_rb.json")
    led = store.read_json(path)
    entries = led["entries"]
    todo = [e for e in entries
            if not e.get("translate") and e["name"] not in SKIP_SECTIONS
            and e["kind"] != "comment"]
    if not todo:
        print("nothing new to classify - checking the widths of what is "
              "already approved")

    m = measure.reset(cfg.font_path())
    _arr, sections = scripts_rb.load_sections(cfg.scripts_file)
    sources = [s for _i, _sid, _n, s, _b in sections if s]

    body = ["Classify and translate each literal. Return ONLY the JSON object."]
    for i, e in enumerate(todo, 1):
        body.append("[%d] literal %s   in script %r line %d\n     source line: %s"
                    % (i, json.dumps(e["jp"], ensure_ascii=False), e["name"],
                       e["line"], e["context"]))
    user = "\n".join(body)

    cl = C.get_client()
    usage = C.Usage()
    obj = {}
    if todo:
        print("auditing %d literal(s) across %d script(s)"
              % (len(todo), len({e["name"] for e in todo})))
        msg = cl.messages.create(
            model=a.model,
            max_tokens=min(32000, max(4096, len(todo) * 120)),
            **R.sampling_params(a.model),
            **R.output_config("low"),
            system=[{"type": "text", "text": SYSTEM}],
            messages=[{"role": "user", "content": user}])
        usage.add(getattr(msg, "usage", None))
        raw = "".join(b.text for b in msg.content
                      if getattr(b, "type", "") == "text")
        obj = parse.parse(raw)

    approved = vetoed = rejected = 0
    for k, v in obj.items():
        try:
            e = todo[int(k) - 1]
        except (ValueError, IndexError):
            continue
        if not isinstance(v, dict) or not v.get("display"):
            rejected += 1
            e["note"] = "not display: %s" % (v.get("why", "") if isinstance(v, dict) else "?")
            continue
        en = (v.get("en") or "").strip()
        if not en:
            rejected += 1
            continue
        why_key = static_key_veto(e["jp"], sources)
        if why_key:
            vetoed += 1
            e["note"] = "VETOED: %s" % why_key
            print("   veto  %-14s %-20s %s" % (e["name"][:14], e["jp"][:20],
                                               why_key[:70]))
            continue
        unsafe = scripts_rb._literal_is_safe(en, e["literal"][0])
        if unsafe:
            vetoed += 1
            print("   veto  %-14s %r -> %r: %s" % (e["name"][:14], e["jp"], en, unsafe))
            continue
        approved += 1
        e["en"] = en
        e["note"] = v.get("why", "")
        e["width"] = [widest_line(m, e["jp"]), widest_line(m, en)]
        if a.apply:
            e["translate"] = True
        # The width pair is the only handle on a script string's box: nothing
        # here knows the window it is drawn in, so a translation much wider
        # than its source is flagged for the eye rather than silently shipped.
        grew = e["width"][1] > e["width"][0] * 1.25 + 4
        print("   ok%s  %-14s %-22s -> %-24s %2d>%2d %s"
              % ("!" if grew else " ", e["name"][:14], e["jp"][:22], en[:24],
                 e["width"][0], e["width"][1], v.get("why", "")[:26]))

    # Second pass: anything past its window's width is re-asked WITH the
    # budget stated, exactly as `tl.py tighten` does for message units. Asking
    # for brevity up front is weaker than naming the number.
    # Checked over the WHOLE ledger, not just this run's approvals: a width
    # budget added later has to be able to catch a string approved earlier.
    over = [e for e in entries
            if e.get("en") and e["name"] not in SKIP_SECTIONS
            and widest_line(m, e["en"]) > budget_for(e)]
    if over:
        print("\n%d translation(s) exceed their window - re-asking with the "
              "budget stated" % len(over))
        body = ["Each of these is too wide for the window it is drawn in, and "
                "that window does not wrap - the text is cut off. Rewrite each "
                "one SHORTER so it fits the stated budget in half-width "
                "characters, keeping the meaning. Return ONLY a JSON object "
                "mapping the number to the new English string."]
        for i, e in enumerate(over, 1):
            body.append("[%d] %s\n     current: %s  (%d cells, budget %d)"
                        % (i, json.dumps(e["jp"], ensure_ascii=False), e["en"],
                           widest_line(m, e["en"]), budget_for(e)))
        msg2 = cl.messages.create(
            model=a.model, max_tokens=max(2048, len(over) * 120),
            **R.sampling_params(a.model), **R.output_config("low"),
            system=[{"type": "text", "text": SYSTEM}],
            messages=[{"role": "user", "content": "\n".join(body)}])
        usage.add(getattr(msg2, "usage", None))
        raw2 = "".join(b.text for b in msg2.content
                       if getattr(b, "type", "") == "text")
        try:
            obj2 = parse.parse(raw2)
        except Exception as ex:
            obj2 = {}
            print("   ! could not parse the shortening pass: %s" % ex)
        for k, v in obj2.items():
            try:
                e = over[int(k) - 1]
            except (ValueError, IndexError):
                continue
            new = v if isinstance(v, str) else (v or {}).get("en", "")
            new = (new or "").strip()
            budget = budget_for(e)
            if not new or scripts_rb._literal_is_safe(new, e["literal"][0]):
                continue
            print("   %s %-12s %-30s -> %-30s %2d>%2d"
                  % ("fit " if widest_line(m, new) <= budget else "STILL",
                     e["name"][:12], e["en"][:30], new[:30],
                     widest_line(m, e["en"]), widest_line(m, new)))
            e["en"] = new
            e["width"] = [m.cells(e["jp"]), m.cells(new)]
        still = [e for e in over if widest_line(m, e["en"]) > budget_for(e)]
        if still:
            print("   !! %d still over budget - they WILL be cut off; edit "
                  "tl/scripts_rb.json by hand" % len(still))

    print("\napproved %d, vetoed %d, left as non-display %d"
          % (approved, vetoed, rejected))
    print(usage.report(a.model, batch=False, ttl="5m"))
    if a.apply:
        store.write_json(path, led)
        print("ledger written - now run:  python tl.py scripts apply")
    else:
        print("\naudit only - pass --apply to write the ledger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
