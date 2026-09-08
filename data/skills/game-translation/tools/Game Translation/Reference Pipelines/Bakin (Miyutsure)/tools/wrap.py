#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
wrap.py - the engine's OWN word wrap, reimplemented exactly.

Transcribed from `Yukar.Engine.MessageReader.MessageEntry.wordWrap` in this
build's `bakinengine.dll` (decompiled), not approximated. The point of copying
it faithfully is that any repair pass has to predict what the player will
actually see, and a "close enough" wrapper predicts the wrong line.

    public void wordWrap(TextDrawer textDrawer, int width, float textScale)
    {
        for (int i = 0; i < this.lineCount; i++)
            if (measure(i, 0, 32767).X > width)
            {
                int num = 1;
                for (;;)
                {
                    string line = this.getLine(i);
                    if (line.Length <= num) break;
                    int num2 = num;
                    while (this.isWord(line[num2 - 1]) && line.Length > num2) num2++;
                    if (line.Length > num2 && this.isNotGoodForPrefix(line[num2])) num2++;
                    num--;
                    float x = measure(i, num, num2 - num).X;
                    num++;
                    if (x > width) num2 = num;
                    if (measure(i, 0, num2).X > width)
                    { num--; this.splitByIndex(i, num); i++; num = 1; }
                    else num++;
                }
            }
    }

Three details that decide the output and are easy to get wrong:

* `isWord` counts `À`..`ߺ` (U+00C0..U+07FA) as word characters, so Latin-1
  accents, Greek, Cyrillic, Hebrew and Arabic bind into words. CJK does NOT,
  which is why Japanese wraps anywhere and English wraps on spaces.
* A SPACE is not a word character, so the break lands ON the space and
  `splitByIndex` moves it to the next line - the continuation begins with it.
  Nothing is dropped.
* A single word wider than the whole box is force-split mid-word by the
  `if (x > width) num2 = num;` fallback rather than overflowing.
"""


def is_word(ch):
    o = ord(ch)
    return (("a" <= ch <= "z") or ("A" <= ch <= "Z")
            or (0x00C0 <= o <= 0x07FA)
            or ("0" <= ch <= "9")
            or ch in ",.'\"(<)>[{]}")


def is_not_good_for_prefix(ch):
    return ch in "、。"


def wrap_line(line, width, measure):
    """Split one authored line the way the engine does. Returns [str, ...].

    `measure(s)` returns the rendered pixel width of `s`."""
    if not line or measure(line) <= width:
        return [line]
    lines = [line]
    i = 0
    while i < len(lines):
        if measure(lines[i]) <= width:
            i += 1
            continue
        num = 1
        while True:
            cur = lines[i]
            if len(cur) <= num:
                break
            num2 = num
            while is_word(cur[num2 - 1]) and len(cur) > num2:
                num2 += 1
            if len(cur) > num2 and is_not_good_for_prefix(cur[num2]):
                num2 += 1
            num -= 1
            x = measure(cur[num:num2])
            num += 1
            if x > width:
                num2 = num
            if measure(cur[:num2]) > width:
                num -= 1
                # splitByIndex keeps cur[:num] on this line and moves cur[num:]
                # to the next. No character is dropped, so the continuation
                # begins with the space that preceded the word.
                lines[i:i + 1] = [cur[:num], cur[num:]]
                i += 1
                num = 1
            else:
                num += 1
        i += 1
    return lines


def wrap_text(text, width, measure):
    """Every authored line wrapped in turn, as `ReadMessage` does."""
    out = []
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        out.extend(wrap_line(line, width, measure))
    return out


def orphans(rendered, width, measure, ratio=0.34):
    """Rendered lines that are a short TAIL of a wrap, not an authored line.

    An orphan is the classic 'layout the translation broke' defect: the author
    put a hard break where the Japanese fitted, the English is longer, the
    engine wraps it, and one or two words land alone. Nothing overflows, so
    every width check passes and the box still looks broken.

    Only a line PRODUCED by wrapping counts - an authored line that happens to
    be short is the author's beat, not our damage. `rendered` is the list from
    `wrap_line` for ONE authored line, so any element after the first is a
    wrap tail."""
    out = []
    for k, ln in enumerate(rendered):
        if k == 0:
            continue
        if measure(ln) <= width * ratio:
            out.append((k, ln))
    return out
