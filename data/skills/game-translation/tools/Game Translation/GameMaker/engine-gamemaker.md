# GameMaker: text extraction and archive patching

Stable toolkit: `C:/Users/sw/Desktop/Tools/Game Translation/GameMaker`.
Read its `README.md` for CLI/schema and `CASE-NIGHTFALL.md` for measured evidence.
Use the bundled UndertaleModTool CLI for GML decompilation and archive writing;
do not build a new general GameMaker serializer.

## Route correctly

`data.win` (Windows), `game.unx`, `game.ios` and `game.droid` commonly contain
a `FORM` container with `GEN8`, `STRG`, and (VM builds) `CODE` chunks. Confirm
using `gmtt.py inspect` and `snapshot`. An exe version of 1.0.0.0 is a game
version, not an engine version. UTMT's inferred feature version is not proof
of the exact compiler patch release.

VM builds support literal-site extraction/injection. YYC compiles game logic
to native code; the tool rejects code-site patching there. Readable STRG data
does not imply all native literals are covered. Route the native executable
to reverse engineering; do not claim a STRG dump is the full text corpus.

## Workflow

1. `snapshot`, `census` and `decompile` from the original archive. Census every
   pooled string, including entries outside supported sites. Inspect game file
   readers for additional text tracks (external JSON/INI/CSV, native extensions).
2. `export` creates JSON entries keyed by original code/instruction position,
   with exact source, pooled ID and neighboring instructions. Default CJK
   selection is a candidate filter. Use `--select all` when appropriate;
   a string with no CJK characters can still be player-facing.
3. Review literal uses in recovered GML. One pooled string can be display text
   and a logic key. Set `reviewed` only on the appropriate uses. Establish
   speakers, scene groups, glossary and renderer-specific codes before doing
   translation. Supply control regexes to `--token-patterns`; there is no
   universal GameMaker dialogue markup language. Preserve masked sentinels.
4. `validate`, then `patch` to a separate archive. The injector appends strings
   and changes specific operands, preserving the old pool and every unselected
   use. It does not recompile scripts. Empty catalogs produce byte-identical
   copies. Longer translations use UTMT relocation, not byte-budget truncation.
5. Reopened output is checked against the expected string/reference changes,
   all instruction descriptions, resource identities, font data and embedded
   media hashes; a separate raw STRG reader checks the strings independently.
   Keep the generated report. These checks do not inspect every room coordinate.
6. Test a changed canary in a game copy, then follow the translation skill's
   live menu/layout/save matrix for a release. A passing archive test is not a
   screenshot or save/load proof. `runtime_tested` remains false in tool reports.

Catalogs are bound to the source SHA256. Re-export to a fresh file, never over
a finished catalog. `diff` is an advisory inventory, not automatic migration.
No built-in paid translation call, installation into the game, art replacement,
native hook or font regeneration is part of this tool.

## Font and layout traps

Use exported **glyph records**, not font range endpoints, to test coverage.
Assigned `font`, `max_width` and `max_lines` gate nominal explicit-line bounds.
The runtime can add scale, clipping, custom wrapping or substitutions, so derive
those separately and calibrate against source screenshots before enforcing a
layout model. Several draw paths may render the same text differently.

Nightfall Princess is a tested example, not a universal rule: it has 630 CJK
literal sites and three non-display CJK font names; it wraps one path in
`scr_newline` and another in a typewriter loop. ASCII is covered by its seven
fonts, but smart apostrophes and em dashes are not. Re-measure for each game.
