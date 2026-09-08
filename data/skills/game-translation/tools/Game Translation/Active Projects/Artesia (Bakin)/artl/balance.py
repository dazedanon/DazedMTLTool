#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
balance.py - move a line break the engine chose badly, without changing a word.

The defect this repairs, which every width check passes:

    |You two look like you're arguing... don't you ever consider you're a  |
    |nuisance?                                                            |  <- orphan
    |You're louder than monkeys! Don't you have any pride as human beings? |

The author put a hard break between the two sentences, and it was right for the
Japanese. The English first sentence is longer, the engine wraps it greedily,
and one word lands alone. Nothing overflows, nothing is lost, and the box looks
machine-made.

WHY A PRE-WRAP IS SAFE HERE, when the skill warns against pre-wrapping a panel
that already word-wraps: `MessageEntry.wordWrap` only touches a line whose
measured width EXCEEDS the box -

    if (this.measureStringSingleLine(...).X > (float)width) { ...split... }

so a line that already fits is returned untouched. Break the text myself into
lines that each fit and the engine renders exactly those. Break it into lines
that do not fit and the engine wraps my breaks again, which is the failure the
warning is about. Every result here is therefore verified by re-running the
engine's own wrap over it and requiring the line list to come back identical.

THREE INVARIANTS, all enforced by `rebalance`:

  * the WORDS are untouched - only whitespace at the break points changes, and
    `same_words` proves it;
  * the LINE COUNT never changes. The message panel paginates at `maxLineNum`,
    so an extra line is an extra key press for the player. Balanced wrapping
    minimises raggedness for a GIVEN number of lines and never needs more than
    the greedy wrap used, so this is free;
  * a line containing ANY control code is left alone. Two independent reasons,
    either of which is sufficient:

      - `wordWrap` runs on lexed parts with the codes already stripped
        (ENGINE-CODES.md section 5), so a code contributes no width - but
        `\z[200]` sets `MessageParts.size` to 200%, which scales every part
        after it. That width is not knowable from the string, so a "balanced"
        split would be a guess wearing a measurement's clothes.
      - `\NPL[Sister Agatha]` has a SPACE inside its bracket. Splitting a line
        on whitespace would happily break the code in half.

    MEASURED: 31 of 84,048 translated dialogue bodies contain a code at all
    (23 `\z`, 7 `\$`, 1 mid-body `\NPL`), so the whole exclusion costs 0.04%
    of the corpus. Buying that back would mean modelling per-part font scaling
    to repair at most 31 cosmetic breaks. `rebalance_text` returns the skipped
    count so the number stays visible rather than becoming folklore.
"""

from . import wrap


def wrap_width(cfg, kind):
    """The width this kind is wrapped at, or None to leave the kind alone.

    Kept here rather than read inline so the audit and the injector cannot
    drift apart: a repair measured at one width and shipped at another is
    worse than no repair at all."""
    return (cfg.get("wrap_px") or {}).get(kind)


def _greedy(line, width, measure):
    return wrap.wrap_line(line, width, measure)


def _split_points(words, k, width, measure, sep=" "):
    """Break `words` into exactly `k` lines, minimising raggedness.

    Cost is the sum of squared slack on EVERY line, the last one included.
    That is deliberately not the Knuth-Plass convention, where the final line
    is free because a paragraph is expected to end short. A three-line dialogue
    box is not a paragraph: a free last line makes the optimum "fill line one,
    dump the remainder", which is the greedy wrap and the orphan we are trying
    to remove. Charging the last line too minimises the sum of squared widths,
    whose optimum is equal lines.

    A layout that does not fit is rejected with an infinite cost, so `None`
    means k lines cannot hold this text."""
    n = len(words)
    if k <= 1:
        s = sep.join(words)
        return [s] if measure(s) <= width else None

    # w[i][j] = width of words[i:j] joined
    INF = float("inf")
    best = [[INF] * (k + 1) for _ in range(n + 1)]
    back = [[0] * (k + 1) for _ in range(n + 1)]
    best[n][0] = 0.0
    for i in range(n - 1, -1, -1):
        for lines_left in range(1, k + 1):
            for j in range(i + 1, n + 1):
                w = measure(sep.join(words[i:j]))
                if w > width:
                    break                        # and every longer j is worse
                rest = best[j][lines_left - 1]
                if rest == INF:
                    continue
                if lines_left == 1 and j != n:
                    continue                     # the last line must finish it
                slack = (width - w) ** 2
                cost = slack + rest
                if cost < best[i][lines_left]:
                    best[i][lines_left] = cost
                    back[i][lines_left] = j
    if best[0][k] == INF:
        return None
    out, i, left = [], 0, k
    while left > 0:
        j = back[i][left]
        out.append(sep.join(words[i:j]))
        i, left = j, left - 1
    return out


def same_words(a, b):
    """True when two renderings differ only in whitespace."""
    return "".join(a.split()) == "".join("".join(b).split())


def rebalance(line, width, measure, orphan_ratio=0.34):
    """A better break for one authored line, or None to leave it alone.

    Returns a list of lines that each fit, or None when the greedy wrap has no
    orphan, when the line cannot be improved, or when any invariant fails."""
    if "\\" in line:
        return None                              # see the third invariant
    greedy = _greedy(line, width, measure)
    if len(greedy) < 2:
        return None
    if not wrap.orphans(greedy, width, measure, orphan_ratio):
        return None

    words = line.split()
    if len(words) < 2:
        return None                              # one long word: nothing to move
    cand = _split_points(words, len(greedy), width, measure)
    if not cand:
        return None
    if wrap.orphans(cand, width, measure, orphan_ratio):
        return None                              # no better than what we had
    if not same_words(line, cand):
        return None
    # The decisive check: the engine must render EXACTLY these lines. If any
    # candidate line still exceeds the box, `wordWrap` re-breaks it and the
    # repair has made things worse.
    for c in cand:
        if measure(c) > width or len(_greedy(c, width, measure)) != 1:
            return None
    return cand


def rebalance_text(text, width, measure, orphan_ratio=0.34):
    """Rebalance every authored line.

    Returns (new_text, n_lines_changed, n_orphaned_lines_skipped_for_codes)."""
    out, changed, coded = [], 0, 0
    for line in (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cand = rebalance(line, width, measure, orphan_ratio)
        if cand is None:
            out.append(line)
            if "\\" in line and wrap.orphans(_greedy(line, width, measure),
                                             width, measure):
                coded += 1
        else:
            out.append("\n".join(cand))
            changed += 1
    return "\n".join(out), changed, coded
