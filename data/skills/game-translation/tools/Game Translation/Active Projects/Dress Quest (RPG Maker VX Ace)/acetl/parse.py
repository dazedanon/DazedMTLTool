#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
parse.py - turn a model reply into `{index: english}`.

Two failure modes account for essentially every unparseable reply on this kind
of corpus, and both are recoverable from the STORED result with no re-billing:

1. **An unescaped `"` inside a value.** Japanese eroge use an ASCII double
   quote as a dakuten on a slurred moan (`あ"っ`), and the model carries it into
   English. Repair rule: a `"` only CLOSES a value when the next non-space
   character is `,` `}` `]` or `:`. Anything else is literal text - escape it.

2. **Self-correction.** The reply emits a partial object, reconsiders in prose,
   then emits the real one: `{...}\n\nWait, I need all 53...\n\n{...}`. A
   first-`{`-to-last-`}` span swallows the prose. Extract every BALANCED
   top-level object and keep the one with the most keys.

Order matters: repair quotes first, because the brace scan depends on correct
string boundaries.
"""

import re
import json

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")
_DOUBLED_QUOTE_RE = re.compile(r':\s*""(?=[^",}\]\s])')

_SMART = str.maketrans({
    "“": '"', "”": '"', "＂": '"',
    "‘": "'", "’": "'", "‛": "'",
    "ʼ": "'", "＇": "'",
})


class ParseError(ValueError):
    pass


def parse(text):
    """Best-effort dict from a model reply. Raises ParseError if nothing
    survives.

    The RAW text is tried first, before any normalisation. Folding curly
    quotes is a repair for a reply that does not parse, and running it first
    BREAKS one that does: `{"1":"She said “yes”, then left"}` is valid JSON
    until “ ” become `"` `"`, at which point the value closes early and the
    line ships truncated at `She said "yes`. Normalise only what has already
    failed."""
    if not text:
        raise ParseError("empty response")
    s = _FENCE_RE.sub("", text.strip())
    if s[:1] == '"' and s[1:2] == "{" and s[-2:-1] == "}":
        s = s[1:-1]

    candidates = [s]
    folded = normalize_reply(s)
    if folded != s:
        candidates.append(folded)

    for candidate in candidates:
        for attempt in (_direct, _repaired, _balanced_best, _regex_fallback):
            try:
                out = attempt(candidate)
            except Exception:
                out = None
            if isinstance(out, dict) and out:
                return {str(k): v for k, v in out.items()}
    raise ParseError("could not parse: %r" % (text[:200],))


def _direct(s):
    return json.loads(s)


def _repaired(s):
    return json.loads(_repair(s))


def _repair(s):
    s = _TRAILING_COMMA_RE.sub(r"\1", s)
    # The lookahead is what stops this rule destroying a legitimate `:""`.
    s = _DOUBLED_QUOTE_RE.sub(':"', s)
    return _escape_inner_quotes(s)


def _escape_inner_quotes(s):
    out = []
    i = 0
    n = len(s)
    in_str = False
    while i < n:
        c = s[i]
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
            i += 1
            continue
        if c == "\\":
            out.append(s[i:i + 2])
            i += 2
            continue
        if c == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j >= n or s[j] in ",}]:":
                out.append('"')
                in_str = False
            else:
                out.append('\\"')
            i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _balanced_best(s):
    """Every balanced top-level object; keep the one with the most keys."""
    best = None
    depth = 0
    start = None
    in_str = False
    esc = False
    for i, c in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                blob = s[start:i + 1]
                for candidate in (blob, _repair(blob)):
                    try:
                        obj = json.loads(candidate)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and (best is None or len(obj) > len(best)):
                        best = obj
                    break
                start = None
    if best is None:
        raise ParseError("no balanced object")
    return best


_KV_RE = re.compile(r'"(\d+)"\s*:\s*"{1,2}((?:\\.|[^"\\])*)"')


def _regex_fallback(s):
    """Last resort for a blob that never parses: turns a truncated response
    into a PARTIAL-count failure the length check catches, not a total loss."""
    out = {}
    for m in _KV_RE.finditer(s):
        try:
            out[m.group(1)] = json.loads('"%s"' % m.group(2))
        except Exception:
            out[m.group(1)] = m.group(2)
    if not out:
        raise ParseError("regex fallback found nothing")
    return out


def normalize_reply(text):
    """Fold the smart quotes a model echoes, so json.loads is not defeated by
    typography."""
    return text.translate(_SMART) if isinstance(text, str) else text
