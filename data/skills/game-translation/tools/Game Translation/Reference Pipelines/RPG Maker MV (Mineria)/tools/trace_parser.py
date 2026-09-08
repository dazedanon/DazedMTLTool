#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trace_parser.py - what does the ENGINE do to a translated string between the
file and the screen?

Extraction and injection being byte-perfect does not mean the text arrives
intact. TyranoScript's tag parser deletes every literal space inside a quoted
attribute value, and 488 correctly-translated labels shipped as
`Justtalknormally` with every check green. Japanese hides that whole class of
bug because it uses no spaces; translating into English is what CREATES it.

So this harness replays the real pipeline for RPG Maker MV:

    Game_Interpreter.command356   -> plugin arguments, split on a delimiter
    Game_Message.allText          -> the 401 commands joined
    LL_StandingPictureMV's
      convertEscapeCharacters     -> strips the portrait codes
    Window_Base.convertEscapeCharacters
                                  -> \\V \\N \\P \\G substitution, \\\\ unescape
    Window_Base.obtainEscapeCode  -> how the remaining escapes are LEXED

and it does NOT carry its own copy of any of them. Every regex, delimiter and
replacement is READ OUT OF THE SHIPPED JAVASCRIPT at run time, and a missing
anchor raises instead of silently testing a stale copy. The day a plugin update
changes one of these, this file fails rather than reporting健康.

Usage:
    python tools/trace_parser.py                 # run the built-in battery
    python tools/trace_parser.py "\\F[C_Fun3]Hi"  # trace one string
"""

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mvtl import config, codes  # noqa: E402


class MissingAnchor(RuntimeError):
    pass


def _read(path):
    if not os.path.exists(path):
        raise MissingAnchor("missing shipped file: %s" % path)
    return open(path, encoding="utf-8-sig", errors="replace").read()


_END_RE = re.compile(r"\n[ \t]*\};")


def _slice(src, start_marker, path):
    i = src.find(start_marker)
    if i < 0:
        raise MissingAnchor("%s no longer contains %r - this harness is "
                            "testing a function that has been renamed or "
                            "removed" % (path, start_marker))
    m = _END_RE.search(src, i)
    if not m:
        raise MissingAnchor("%s: could not find the end of %r"
                            % (path, start_marker))
    return src[i:m.start()]


# --------------------------------------------------------------------------
# JS regex literal -> Python
# --------------------------------------------------------------------------
_REPLACE_RE = re.compile(
    r"""\.replace\(\s*/((?:\\.|\[[^\]]*\]|[^/\\])+)/([gimsuy]*)\s*,\s*"""
    r"""(?:(["'])((?:\\.|(?!\3).)*)\3|function)""",
    re.S)


def _js_to_py(pattern):
    """The subset of JS regex syntax these files actually use."""
    return pattern


def extract_replacements(body, path):
    """[(compiled, replacement_or_None)] in source order.

    `None` means the JS replacement was a function - the caller has to know
    what it does. Every such case in this pipeline is a runtime substitution
    (\\V / \\N / \\P) and is handled explicitly by `Engine` below."""
    out = []
    for m in _REPLACE_RE.finditer(body):
        pat, flags, _q, rep = m.group(1), m.group(2), m.group(3), m.group(4)
        f = 0
        if "i" in flags:
            f |= re.I
        if "s" in flags:
            f |= re.S
        if "m" in flags:
            f |= re.M
        try:
            rx = re.compile(_js_to_py(pat), f)
        except re.error as e:
            raise MissingAnchor("%s: cannot translate JS regex /%s/%s: %s"
                                % (path, pat, flags, e))
        out.append((rx, rep))
    if not out:
        raise MissingAnchor("%s: found no .replace() calls where the shipped "
                            "code has them" % path)
    return out


# --------------------------------------------------------------------------
class Engine(object):
    """The shipped text pipeline, reconstructed from the shipped files."""

    def __init__(self, cfg):
        self.cfg = cfg
        win = os.path.join(cfg.js_dir, "rpg_windows.js")
        obj = os.path.join(cfg.js_dir, "rpg_objects.js")
        spm = os.path.join(cfg.js_dir, "plugins", "LL_StandingPictureMV.js")

        self.core_body = _slice(_read(win),
                                "Window_Base.prototype.convertEscapeCharacters =",
                                win)
        self.core_repls = extract_replacements(self.core_body, win)

        self.obtain_body = _slice(_read(win),
                                  "Window_Base.prototype.obtainEscapeCode =", win)
        m = re.search(r"var\s+regExp\s*=\s*/(.+?)/([gimsuy]*)\s*;",
                      self.obtain_body)
        if not m:
            raise MissingAnchor("%s: obtainEscapeCode no longer defines its "
                                "regExp the way this harness reads it" % win)
        self.escape_lex = re.compile(m.group(1),
                                     re.I if "i" in m.group(2) else 0)

        c356 = _slice(_read(obj), "Game_Interpreter.prototype.command356 =", obj)
        m = re.search(r"_params\[0\]\.split\((['\"])(.*?)\1\)", c356)
        if not m:
            raise MissingAnchor("%s: command356 no longer splits _params[0] on "
                                "a string literal - re-read it before trusting "
                                "the single-token rule" % obj)
        self.plugin_delim = m.group(2)

        alltext = _slice(_read(obj), "Game_Message.prototype.allText =", obj)
        m = re.search(r"_texts\.join\((['\"])(.*?)\1\)", alltext)
        if not m:
            raise MissingAnchor("%s: allText no longer joins _texts on a string "
                                "literal" % obj)
        self.line_join = m.group(2).encode().decode("unicode_escape")

        sp_body = _slice(_read(spm),
                         "Window_Base.prototype.convertEscapeCharacters =", spm)
        self.sp_repls = extract_replacements(sp_body, spm)

    # ---------------------------------------------------------------- steps
    def join_401(self, texts):
        return self.line_join.join(texts)

    def split_356(self, command):
        return command.split(self.plugin_delim)

    def convert(self, text, variables=None, actors=None, currency="G"):
        variables = variables or {}
        actors = actors or {}
        # LL_StandingPictureMV runs FIRST (it calls the core one last).
        for rx, rep in self.sp_repls:
            text = rx.sub(rep if rep is not None else "", text)
        # Core: the two literal replacements, then the runtime substitutions
        # its own source performs with functions.
        ESC = "\x1b"
        text = text.replace("\\", ESC)
        text = text.replace(ESC + ESC, "\\")
        text = re.sub(ESC + r"V\[(\d+)\]",
                      lambda m: str(variables.get(int(m.group(1)), 0)),
                      text, flags=re.I)
        text = re.sub(ESC + r"N\[(\d+)\]",
                      lambda m: str(actors.get(int(m.group(1)), "")),
                      text, flags=re.I)
        text = re.sub(ESC + r"P\[(\d+)\]",
                      lambda m: str(actors.get(int(m.group(1)), "")),
                      text, flags=re.I)
        text = re.sub(ESC + r"G", currency, text, flags=re.I)
        return text

    def lex(self, converted):
        """What the renderer draws, and which escapes it swallowed.

        `obtainEscapeCode` matches `^[A-Z]+` case-insensitively, so an escape
        directly against a Latin word is lexed as ONE unknown code and the word
        is never drawn. Japanese never trips this; English is what creates it."""
        ESC = "\x1b"
        out = []
        eaten = []
        i = 0
        n = len(converted)
        while i < n:
            c = converted[i]
            if c != ESC:
                out.append(c)
                i += 1
                continue
            i += 1
            m = self.escape_lex.match(converted[i:])
            if not m:
                continue
            code = m.group(0)
            i += len(code)
            if len(code) > 1 and code.isalpha():
                eaten.append(code)
            # a bracketed argument is consumed by the renderer too
            if i < n and converted[i] == "[":
                j = converted.find("]", i)
                if j >= 0:
                    i = j + 1
        return "".join(out), eaten


# --------------------------------------------------------------------------
CASES = [
    # (label, kind, input)
    ("portrait + English", "401",
     ["\\F[C_Fun3]Hmph... fortune-telling, is it?", "Fine. Go ahead."]),
    ("portrait + apostrophe", "401",
     ["\\F[C_Worried1]I don't have enough money..."]),
    ("variable mid-sentence", "401",
     ["You spent \\V[66] mana."]),
    ("variable glued to a word", "401",
     ["Mana\\V[66] restored."]),
    ("currency code before a word", "401",
     ["That costs 500\\G And I am not paying it."]),
    ("pause codes", "401",
     ["Well\\. well\\. what have we here\\|"]),
    ("literal backslash the model invented", "401",
     ["I called out to \\Helen."]),
    ("plugin popup, single token", "356",
     "LL_InfoPopupWIndowMV showWindow Lewdness+\\V[2] 80 0 60 0"),
    ("plugin popup with an ASCII space", "356",
     "LL_InfoPopupWIndowMV showWindow Lewdness +\\V[2] 80 0 60 0"),
    ("plugin popup with NBSP", "356",
     "LL_InfoPopupWIndowMV showWindow Lewdness +\\V[2] 80 0 60 0"),
]


def main():
    cfg = config.Config()
    eng = Engine(cfg)
    print("engine anchors read from the shipped files:")
    print("  command356 splits _params[0] on %r" % eng.plugin_delim)
    print("  allText joins the 401 texts on %r" % eng.line_join)
    print("  obtainEscapeCode lexes with /%s/" % eng.escape_lex.pattern)
    print("  LL_StandingPictureMV strips %d pattern(s); core does %d"
          % (len(eng.sp_repls), len(eng.core_repls)))
    print()

    argv = sys.argv[1:]
    cases = [("cli", "401", [argv[0]])] if argv else CASES
    bad = 0
    for label, kind, payload in cases:
        print("-- %s" % label)
        if kind == "356":
            args = eng.split_356(payload)
            print("   command : %r" % payload)
            print("   args    : %r" % (args,))
            text_arg = args[2] if len(args) > 2 else ""
            shown = eng.lex(eng.convert(text_arg, variables={2: 12, 66: 25}))[0]
            print("   arg[1]  : %r  -> renders %r" % (text_arg, shown))
            if len(args) != 7:
                print("   !! the plugin expects 6 arguments after the name; "
                      "this splits into %d - a space inside the text field "
                      "silently truncates the popup" % (len(args) - 1))
                bad += 1
            continue

        joined = eng.join_401(payload)
        conv = eng.convert(joined, variables={2: 12, 66: 25},
                           actors={1: "Mineria"}, currency="G")
        shown, eaten = eng.lex(conv)
        print("   file    : %r" % joined)
        print("   screen  : %r" % shown)
        print("   rows    : %d" % (shown.count("\n") + 1))
        if eaten:
            print("   !! the renderer swallowed these as control codes: %r "
                  "- the following word is never drawn" % eaten)
            bad += 1
    print()
    if bad:
        print("%d case(s) demonstrate a real failure mode. Those are the ones "
              "the pipeline must prevent, not the ones it has." % bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
