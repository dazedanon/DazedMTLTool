# RPG Maker **MV** reference pipeline - `mvtl`

Copied out of the finished translation of
`魔王ミネリアと名もなき村のエロトラップダンジョン` (RPG Maker MV, 2,866 units,
100% translated, $1.15 on Sonnet 5 live+cache, 68 requests, zero errors).

`README.md` is the project's own runbook. This file is what to take from it, and
what it does differently from
`Reference Pipelines\RPG Maker MVMZ (BroodGeneral)\`.

**The store here is the finished Mineria one.** Delete `tl/units/`, rewrite
`tl/glossary.json` and `tl/game_prompt.md` for the new game, and re-run
`extract`. Every path into the game is resolved from `mvtl/config.py`
(`--game`, or `MINERIA_GAME_ROOT`).

## Which one to copy

| | BroodGeneral | Mineria (this) |
|---|---|---|
| Engine flavour | **MZ** - native `101 parameters[4]` speaker | **MV** - no speaker field anywhere |
| Driver | Claude batch | batch **and** live, one shared builder/parser/apply |
| Width | char-count against a stated cell size | **the game's own font**, via `fontTools` |
| Write-back | tombstone + merge into the anchor | **preserves the command count** |
| Save safety | `translate_save.py` | that, plus a structural proof gated into the release |

Take BroodGeneral's `helpwrap.py` and its `122`-display-variable subset if the
game needs them; neither exists here because this game needed neither.

## What is worth lifting, module by module

**`measure.py` - widths from the shipped font, never a table.**
`unicodedata.east_asian_width` and the font disagree in ways that matter:
U+2026 `…` is "ambiguous" in the table and full-width in M+ 1m; U+00A0 is
"narrow" in the table and present at half width in the font; U+2764 `❤` is *not
in the font at all* and renders from a browser fallback. `missing_glyphs()`
lists what the font cannot draw so nothing is measured on a guess in silence.
Reports `exact=False` when `fontTools` is unavailable rather than pretending.

**`wrap.py` - balanced DP with three corrections.** Width is a hard constraint;
the **last line is charged at 0.6** (Knuth-Plass's free tail orphans a word in a
4-row box); and a break at sentence punctuation gets a 0.45 cost multiplier.
Without the last two, `"…It'll cost you 500G how" / "about it?"` ships and passes
every width check.

**`inject.py` - never changes the command count.** MV joins the `401`s of a block
with `\n`, so k wrapped lines across c commands render `max(k, c)` rows. That is
what lets the wrap re-flow freely while the index a save file stores stays put.
`noop_test()` proves an empty store injects byte-identically.

**`tools/verify_structure.py` - the save-safety proof, and a release gate.**
Walks source against output asserting same files, same keys, same array lengths,
same command-list lengths, same `(code, indent)` sequences, same non-string
leaves. 9,144 lists / 40,677 commands / 0 differences on this game.
`build_release.py` aborts if it fails.

**`tools/trace_parser.py` - what the ENGINE does to a translated string.**
Reads every regex, delimiter and replacement **out of the shipped JavaScript at
run time** and raises if an anchor moved, so it cannot certify a stale copy of
the engine. Demonstrates three real failure modes on this engine:
`\Helen` swallowed whole by `obtainEscapeCode`'s `^[A-Z]+`; a space truncating a
plugin argument at `command356`'s `split(" ")`; and `Mana\V[66]` rendering
"Mana25".

**`validate.py` - the number check that does not cry wolf.** Canonicalises kanji
numerals (counter-gated), myriad grouping, thousands separators, currency
suffixes, spelled-out English and lexicalised multipliers on *both* sides before
comparing, and drops the value 1 symmetrically. 61 flags to 5, of which 4 were
real. Also carries the per-unit **`waive`** mechanism - a check with no visible
escape hatch gets switched off wholesale.

**`qa.py:unify_repeats` - one repeated line, one English rendering.** Auto-unifies
same-source clusters except where a third-person pronoun or a second speaker
makes the reuse genuinely scene-dependent. 243 conflicts to 20 on this game.

**`plugins_js.py` - the in-place track, with two things nothing else catches.**
A `MIRRORS` table for a plugin parameter that is a lookup key into another file's
translated field, and a `LAYOUT_OVERRIDES` table for raising a widget's declared
bound instead of compressing the English.

**`tools/seed_stock_ui.py` - 96 units, zero API calls.** RPG Maker's own
published English for its own strings, marked `locked`.

**`tests/test_requests.py` - prove the request set before paying for it.** Builds
with `retranslate_all=True` and fails loudly on an empty build, because a test
whose fixtures come from *pending* work silently passes once the work is done.

## The per-game work

Everything below came from a census, not from a default. `docs/CENSUS.md` records
the evidence for each; redo it for the next game.

- which optional event codes hold text (all of `355`/`122`/`111`/`108` were OFF here)
- the wrap width, from window geometry + the font + the author's own line histogram
- how the game identifies a speaker (this one: a portrait plugin's control code)
- which plugin parameters are text, which are keys, which are layout
- which images carry baked text
