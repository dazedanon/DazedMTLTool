#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_codes.py - the cases that are real failures someone hit, not coverage.

    python tests/test_codes.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mvtl import codes, wrap, measure, parse, config  # noqa: E402

OPEN, CLOSE = codes.PH_OPEN, codes.PH_CLOSE


def ph(n):
    return OPEN + str(n) + CLOSE


FAILS = []


def check(label, got, want):
    if got != want:
        FAILS.append("%s\n     got  %r\n     want %r" % (label, got, want))
        print("  FAIL %s" % label)
    else:
        print("  ok   %s" % label)


# --------------------------------------------------------------------------
print("word-insert padding")

# A number glued to a word is the failure ("Mana25"). Everything else is not.
check("insert glued to a word gains a space",
      codes.unmask_codes("Mana" + ph(0) + " restored.", {ph(0): r"\V[66]"}),
      r"Mana \V[66] restored.")
check("insert against punctuation does NOT gain a space",
      codes.unmask_codes(ph(0) + " recovered " + ph(1) + " " + ph(2) + "!",
                         {ph(0): "%1", ph(1): "%2", ph(2): "%3"}),
      "%1 recovered %2 %3!")
check("two adjacent inserts stay tight",
      codes.unmask_codes("Found " + ph(0) + ph(1) + "!",
                         {ph(0): "%1", ph(1): r"\G"}),
      r"Found %1\G!")
check("possessive stays tight",
      codes.unmask_codes(ph(0) + "'s turn", {ph(0): r"\N[1]"}),
      r"\N[1]'s turn")
check("a plus sign is not a word",
      codes.unmask_codes("Lewdness+" + ph(0), {ph(0): r"\V[2]"}),
      r"Lewdness+\V[2]")
check("a pause code is never padded",
      codes.unmask_codes("Wait" + ph(0) + " for it", {ph(0): "\\."}),
      "Wait\\. for it")
check("validation restore does not pad at all",
      codes.unmask_codes("Mana" + ph(0), {ph(0): r"\V[66]"}, pad_inserts=False),
      r"Mana\V[66]")

# --------------------------------------------------------------------------
print("\nportrait run")
check("leading portrait run is split off byte-exact",
      codes.split_portrait(r"\F[C_Fun3]Hmph... fortune-telling?"),
      (r"\F[C_Fun3]", "Hmph... fortune-telling?"))
check("a two-portrait run is one prefix",
      codes.split_portrait(r"\F[C_Aura]\FF[C_Angry2NHnormal]Tedious.")[0],
      r"\F[C_Aura]\FF[C_Angry2NHnormal]")
check("a line with no portrait is untouched",
      codes.split_portrait("Very well."), ("", "Very well."))
check("a portrait code MID-line is not a prefix",
      codes.split_portrait(r"Hello \F[C_Fun3] there"),
      ("", r"Hello \F[C_Fun3] there"))

# --------------------------------------------------------------------------
print("\nsource cleanup")
check("trailing ideographic space is padding and goes",
      codes.clean_source("ひにゃぁぁ！！　"),
      "ひにゃぁぁ！！")
check("interior ideographic space is a pacing gap and becomes a space",
      codes.clean_source("あっ　ああ"),
      "あっ ああ")

# --------------------------------------------------------------------------
print("\ntranslation cleanup")
check("a still-Japanese value is written back byte-exact",
      codes.clean_translation("アウレリオ「大丈夫ですか！」"),
      "アウレリオ「大丈夫ですか！」")
check("stranded small kana transliterate",
      codes.strip_residual_kana("Ogh゛っ❤"), "Ogh゛-❤")
check("a real miss is left for the retry queue",
      codes.strip_residual_kana("もうだめっ"),
      "もうだめっ")
check("censor mask survives the untranslated test",
      codes.has_untranslated_jp("sh〇t"), False)
check("kanji is a real miss",
      codes.has_untranslated_jp("the 魔王"), True)

# --------------------------------------------------------------------------
print("\nsingle-token plugin argument")
check("spaces become NBSP so command356's split survives",
      codes.to_single_token("Lewdness +" + ph(0)),
      "Lewdness +" + ph(0))

# --------------------------------------------------------------------------
print("\nmeasurement")
cfg = config.Config()
m = measure.reset(cfg.font_path)
if m.exact:
    check("half-width cell is 14.00px at fontSize 28", round(m.half_px, 2), 14.0)
    check("kanji is 2 cells", m.cells("魔"), 2)
    check("ellipsis is 2 cells (the font says so, not the table)",
          m.cells("…"), 2)
    check("NBSP is 1 cell", m.cells(" "), 1)
    check("a portrait code is 0 cells", m.cells(r"\F[C_Fun3]"), 0)
    check("a variable code budgets 4 cells", m.cells(r"\V[66]"), 4)
    check("the box is 70 cells", int(measure.CONTENTS_WIDTH // m.half_px), 70)
else:
    print("  SKIP (fontTools unavailable - measurement is approximate)")

# --------------------------------------------------------------------------
print("\nwrapping")
long_line = ("You stupid mutt - stealing from me and thinking you would just "
             "walk away with it. That takes real nerve, it really does.")
f = wrap.fit(long_line, 68, 4, m)
check("wraps inside the box", f.ok, True)
check("no line exceeds the width", f.widest <= 68, True)
f2 = wrap.fit(long_line * 3, 68, 4, m)
check("an over-tall result is reported, not silently clipped",
      f2.overflow_rows, True)
check("a sentinel is never split",
      ph(0) not in [x for x in wrap.fit(ph(0) + " " + "x" * 200, 20, None, m).text.split("\n") if OPEN in x and CLOSE not in x],
      True)

# --------------------------------------------------------------------------
print("\nresponse parsing")
check("plain JSON", parse.parse('{"1":"Hi","2":"There"}'), {"1": "Hi", "2": "There"})
check("fenced JSON", parse.parse('```json\n{"1":"Hi"}\n```'), {"1": "Hi"})
check("unescaped quote inside a value (the dakuten-as-quote case)",
      parse.parse('{"1":"Aa"h, enjoy the show?","2":"ok"}'),
      {"1": 'Aa"h, enjoy the show?', "2": "ok"})
check("self-correction keeps the bigger object",
      parse.parse('{"1":"a"}\n\nWait, I need all 3.\n\n{"1":"a","2":"b","3":"c"}'),
      {"1": "a", "2": "b", "3": "c"})
check("trailing comma", parse.parse('{"1":"a","2":"b",}'), {"1": "a", "2": "b"})
check("a legitimate empty string is not destroyed",
      parse.parse('{"1":"","2":"b"}'), {"1": "", "2": "b"})

# --------------------------------------------------------------------------
print("\nchoice condition splitting")
from mvtl.extract import split_choice_condition  # noqa: E402
check("a balanced prefix condition is peeled off",
      split_choice_condition("if(v[31]>=4)迷宮四階"),
      ("迷宮四階", "if(v[31]>=4)", ""))
check("a nested call is not truncated at the first paren",
      split_choice_condition("if($gameSwitches.value(1))Yes")[1],
      "if($gameSwitches.value(1))")
check("unbalanced input returns the label untouched",
      split_choice_condition("if(v[31]>=4迷宮"),
      ("if(v[31]>=4迷宮", "", ""))
check("a plain label is untouched",
      split_choice_condition("はい"), ("はい", "", ""))

# --------------------------------------------------------------------------
print("")
if FAILS:
    print("%d FAILURE(S)" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL TESTS PASS")
