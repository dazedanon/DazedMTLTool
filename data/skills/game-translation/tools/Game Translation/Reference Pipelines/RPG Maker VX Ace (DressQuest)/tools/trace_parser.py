#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
trace_parser.py - what the ENGINE does to a translated string.

Extraction and injection being byte-perfect does not mean the text arrives
intact. Between the file and the screen, RGSS3 rewrites every backslash to
`\e`, substitutes four codes, lets this game's own script eat `\NAME[...]`, and
then LEXES what is left one escape at a time. Each of those stages can silently
change or delete part of a line that passed every text-level check.

This reads the rules OUT OF THE SHIPPED SCRIPTS rather than from a copy of
them, and raises if an anchor has moved - so it cannot certify a stale
understanding of the engine. Then it replays those rules over a string and
reports what a player would actually see.

    python tools/trace_parser.py                      # the standard probes
    python tools/trace_parser.py "Eris\G and \Helen"  # trace one string
"""

import os
import re
import sys
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import config                                  # noqa: E402
from acetl import rvmarshal as M                          # noqa: E402

BS = chr(92)
ESC = "\x1b"


class EngineRules(object):
    """The live rules, lifted out of `Data\\Scripts.rvdata2`."""

    def __init__(self, scripts_path):
        self.sources = {}
        arr = M.load_file(scripts_path)
        for row in arr.items:
            if not isinstance(row, M.RArray) or len(row.items) < 3:
                continue
            name = row.items[1].text() if isinstance(row.items[1], M.RString) else ""
            blob = row.items[2].data if isinstance(row.items[2], M.RString) else b""
            try:
                self.sources[name] = zlib.decompress(blob).decode("utf-8", "replace")
            except zlib.error:
                pass
        self.window_base = self._need("Window_Base")
        self.message = self._need("Window_Message")
        self.nameplate = self._find_nameplate()
        self._check_anchors()

    def _need(self, name):
        if name not in self.sources:
            raise SystemExit("ERROR: script section %r is gone - this tool is "
                             "reading a game it does not understand." % name)
        return self.sources[name]

    def _find_nameplate(self):
        for name, src in self.sources.items():
            if "convert_escape_characters" in src and "NAME" in src:
                if name not in ("Window_Base",):
                    return name, src
        return None, ""

    # -- anchors ----------------------------------------------------------
    # Literal snippets of the game's own Ruby, matched as substrings. Written
    # as literals rather than as regexes on purpose: a pattern that has to
    # escape a Ruby regex that is itself full of backslashes is a source of
    # false "the engine changed" alarms, and an anchor check that cries wolf
    # gets deleted.
    ANCHORS = [
        ("Window_Base", "gsub!(/" + BS + BS + "/)",
         "every backslash becomes \\e before anything else"),
        ("Window_Base", "gsub!(/" + BS + "eV" + BS + "[(" + BS + "d+)" + BS + "]/i)",
         "\\V[n] is substituted to a variable's value"),
        ("Window_Base", "gsub!(/" + BS + "eG/i)",
         "\\G is substituted to the currency unit"),
        ("Window_Base", "text.slice!(/^[" + BS + "$" + BS + "." + BS + "|"
         + BS + "^!><" + BS + "{" + BS + "}" + BS + BS + "]|^[A-Z]+/i)",
         "an escape is one punctuation char OR a RUN of letters"),
        ("__nameplate__", "eNAME" + BS + "[(.*?)" + BS + "]",
         "the name-plate code is consumed before drawing"),
    ]

    def _check_anchors(self):
        missing = []
        for section, snippet, why in self.ANCHORS:
            src = (self.nameplate[1] if section == "__nameplate__"
                   else self.sources.get(section, ""))
            if snippet not in src:
                missing.append("%s: %s" % (section, why))
        self.missing_anchors = missing

    # -- the pipeline -----------------------------------------------------
    def convert(self, text, variables=None, actor_names=None,
                currency="Ｇ"):
        """`Window_Base#convert_escape_characters`, plus this game's alias."""
        out = text.replace(BS, ESC)
        out = out.replace(ESC + ESC, BS)
        out = re.sub(ESC + r"V\[(\d+)\]",
                     lambda m: str((variables or {}).get(int(m.group(1)), 0)),
                     out, flags=re.I)
        out = re.sub(ESC + r"N\[(\d+)\]",
                     lambda m: (actor_names or {}).get(int(m.group(1)), ""),
                     out, flags=re.I)
        out = re.sub(ESC + r"P\[(\d+)\]",
                     lambda m: (actor_names or {}).get(int(m.group(1)), ""),
                     out, flags=re.I)
        out = re.sub(ESC + r"G", currency, out, flags=re.I)
        plate = None
        if self.nameplate[0]:
            m = re.search(ESC + r"NAME\[(.*?)\]", out, flags=re.I)
            if m:
                plate = m.group(1)
            out = re.sub(ESC + r"NAME\[(.*?)\]", "", out, flags=re.I)
        return out, plate

    _CODE_RE = re.compile(r"^[$.|^!><{}" + re.escape(BS) + r"]|^[A-Za-z]+")

    def draw(self, converted):
        """Replay the drawing loop: what reaches the screen, and what the
        lexer swallowed."""
        shown = []
        eaten = []
        i = 0
        while i < len(converted):
            c = converted[i]
            i += 1
            if c != ESC:
                shown.append(c)
                continue
            m = self._CODE_RE.match(converted[i:])
            code = m.group(0) if m else ""
            i += len(code)
            arg = ""
            am = re.match(r"^\[(\d+)\]", converted[i:])
            if am:
                arg = am.group(0)
                i += len(arg)
            eaten.append(code + arg)
        return "".join(shown), eaten


def trace(rules, text, label=""):
    converted, plate = rules.convert(text)
    shown, eaten = rules.draw(converted)
    print("  %s" % (label or "trace"))
    print("     written : %r" % text)
    if plate is not None:
        print("     plate   : %r" % plate)
    print("     drawn   : %r" % shown)
    if eaten:
        print("     codes   : %s" % ", ".join(repr(e) for e in eaten))
    lost = [e for e in eaten
            if len(e) > 1 and e[0].isalpha() and e.upper() not in
            ("C", "I", "FS", "PX", "PY", "OW", "OC", "V", "N", "P", "G")]
    if lost:
        print("     !! the lexer swallowed %s as ONE unknown code - the word "
              "is never drawn" % ", ".join(repr(x) for x in lost))
    return shown, eaten


def main(argv=None):
    cfg = config.Config()
    rules = EngineRules(cfg.scripts_file)

    print("ENGINE RULES read from %s" % os.path.basename(cfg.scripts_file))
    print("  Window_Base            : %d chars" % len(rules.window_base))
    print("  Window_Message         : %d chars" % len(rules.message))
    print("  name-plate script      : %s" % (rules.nameplate[0] or "NOT FOUND"))
    if rules.missing_anchors:
        print("\n  !! ANCHORS MISSING - this game's engine no longer matches "
              "what the pipeline assumes:")
        for a in rules.missing_anchors:
            print("     - %s" % a)
        return 1
    print("  all %d anchors present\n" % len(rules.ANCHORS))

    if argv:
        for s in argv:
            trace(rules, s)
        return 0

    print("PROBES - each is a real failure class for THIS engine\n")
    trace(rules, BS + "NAME[Eris]Good morning.",
          "1. a translated name plate: the tag is eaten, the name is drawn "
          "elsewhere")
    trace(rules, "It costs 10" + BS + "G.",
          "2. the currency code, correctly padded")
    trace(rules, "It costs 10" + BS + "Gold.",
          "3. \\G has NO word boundary in the gsub - 'Gold' loses its G")
    trace(rules, BS + "Helen smiled.",
          "4. a backslash the model invented: obtain_escape_code takes ^[A-Z]+ "
          "case-insensitively, so the WHOLE word is swallowed")
    trace(rules, BS + "NAME[Eris [the Knight]]Hello.",
          "5. a ']' inside the name: the plate regex is non-greedy, so the "
          "rest leaks into the message body")
    print("\nEvery one of these passes a text-level check: no residual "
          "Japanese, no sentinel mismatch, clean JSON. Only replaying the "
          "engine's own rules finds them.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
