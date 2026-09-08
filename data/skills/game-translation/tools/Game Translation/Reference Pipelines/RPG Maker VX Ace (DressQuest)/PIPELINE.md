# RPG Maker **VX Ace** reference pipeline - `acetl`

Copied out of the finished translation of **Dress Quest ~エリスと七つのドレス~**
(circle ぽいずん, v1.13, RGSS3): 14,750 units, 100% translated, 0 residual
Japanese, 0 placeholder or control-code failures, $8.36 on Sonnet 5 batch.

`README.md` is the project's own runbook. This file is what to take from it and
what an Ace game does differently from MV/MZ.

**The store here is the finished Dress Quest one** minus `tl/units/`. Rewrite
`tl/glossary.json`, `tl/game_prompt.md` and `tl/quirks.md` for the new game,
delete `tl/scripts_rb.json`, and re-run `extract`. Every path into the game is
resolved from `acetl/config.py` (`--game`, or `DRESSQUEST_GAME_ROOT`).

---

## Start here: the four Ace facts that cost a day to learn

**1. Do not put RV2JSON in the delivery path.** It is fine for reading, and
genuinely useful for grepping. But `RV2JSON -c` followed by `-u` with ZERO
edits returns **28 of 231 files changed** (`Enemies.rvdata2` 35,587 -> 32,337
bytes), and it silently **drops `System.terms.etypes`** - the five equip-slot
labels that `Vocab.etype` reads and two windows draw are simply not in its JSON
at all. Writing that JSON back deletes them from the game.

`acetl/rvmarshal.py` is a Ruby Marshal 4.8 reader/writer that round-trips
**231/231 shipped files byte for byte**. That is what lets `tl.py noop` compare
FILE BYTES and prove an empty store changes nothing - a far stronger claim than
comparing parsed trees, because it also catches a changed link table, a
re-ordered ivar or a rewritten float. Take that module first; everything else
rests on it.

**2. RGSS3 reads the ARCHIVE before it reads a loose file.** With
`Game.rgss3a` present, `Data\*.rvdata2` is served out of the archive and an
identically-named loose file beside it is IGNORED. A patch dropped in next to
the archive does nothing at all, silently - the game starts in Japanese with a
fully translated `Data\` sitting right there. (Measured by running the game,
after assuming the opposite and shipping it.)

So the install is: extract the archive, copy the patch over the extracted
`Data\`, then MOVE `Game.rgss3a` out of the folder. Audio is loose and not in
the archive, which is the proof that RGSS falls back to the filesystem for
anything the archive does not contain.

`Tools\Game Archives\RPG Maker RGSSAD\rgssad.py` extracts (v1/v2/v3), and
`install-template.ps1` beside it is a player-facing installer that does all
three steps with an embedded C# unpacker - no Python on the player's machine.

**3. Height paginates, width clips.** `Window_Message#process_new_line` calls
`input_pause` then `new_page`, so a message taller than `visible_line_number`
costs the player a click and loses nothing. `process_normal_character` advances
x and draws without ever testing the right edge, so a line wider than the
contents bitmap is simply cut off. Treating both as hard failures makes the
pipeline pay a model to compress prose the engine would have handled: width is
a hard failure, height is a soft `pagination` note.

**4. The author's own line widths are only a safe budget if the author's text
fits.** This one is in `text-fitting.md` as a caveat; here it was the actual
case. The first build derived the wrap width from the widest shipped line (66
cells unfaced, 56 faced) and the very first faced line in the game clipped. See
"Calibrating the cell" below.

---

## What is worth lifting, module by module

**`rvmarshal.py` - the foundation.** Every non-immediate value is a wrapper
object (`RString`, `RArray`, ...) rather than a Python native, because Marshal
emits a back-reference the second time it writes the SAME OBJECT, judged by
identity. CPython interns short strings, so mapping Marshal strings onto `str`
would collapse two distinct Ruby strings into one and the writer would emit a
link where the original had a full copy. `loads_many` / `dumps_many` handle a
SAVE, which is two concatenated documents. `roundtrip_ok()` over the whole
`Data\` folder is the acceptance test - run it before writing any other code.

**`rvdata.py` - pointers into that tree.** JSON-serialisable steps: `"@ivar"`,
an int index, and `{"h": key}` for a hash. Ace stores a map's events as a
**Hash keyed by event id**, not the sparse array MV uses, so the pointer must
carry the KEY - a hash written back in a different order would send a
translation to the wrong event if positions were used.

**`inject.py` - never changes the command count.** A VX Ace save marshals
`$game_map.interpreter` including `@index`, an index into the command list it
was running, and `Game_Interpreter#setup` re-binds `@list` from the patched map
on load. Wrapped English is redistributed across exactly the commands the run
already had. `noop_test()` proves an empty store injects byte-identically.

**`codes.py` - the nametag split.** This game's own script defines
`\NAME[...]`, consumed in `convert_escape_characters` and drawn in a separate
auto-sized window. It costs ZERO width, must be split off before the model sees
the line, and is rebuilt from the glossary on inject. `name_is_safe()` refuses
an English name containing `]`, because the engine's tag regex is non-greedy
and a bracket closes the tag early - proven by `tools/trace_parser.py` probe 5.

**`extract.py` - two lessons in the shape of the units.**
* **Silent beats.** 79 message boxes draw a body with no Japanese in it
  (`「………」`) while the only Japanese on screen is the speaker inside the tag.
  Extraction keys on "contains Japanese", so those were never units and would
  have shipped a Japanese name plate over an English scene. They are extracted,
  pre-filled with their own body, `locked`, and carry a waiver.
* **Battle-log fragments are name-prefixed per FIELD, not per string.**
  `Window_BattleLog` draws `subject.name + item.message1` for Skill message1 and
  `target.name + state.message1..4`, but Skill message2 stands alone. Japanese
  needs no separator there and English does, so the prefixed fields get a dummy
  subject in the prompt and a restored LEADING SPACE on the way back. Without
  it the log reads `Erisattacks!`.

**`scripts_rb.py` - the second track, and the one everybody forgets.** MV keeps
UI text in `plugins.js`; Ace keeps it in Ruby source inside
`Data\Scripts.rvdata2`. On this game that was **384 literals**, of which
`Vocab` alone held 51 with published Enterbrain English (free, no API call) and
another 48 were live UI: the volume screen, four extra stat rows, the world
map's place names and descriptions, CG Mode / Replay Mode, damage popups, item
synthesis. Everything defaults to `translate: false`, which is right - but if
you stop there, the game ships with Japanese menus. Run
`tools/translate_scripts.py` and read what it approved.

**`validate.py` - the number check that had to be tuned before it was useful.**
It opened at **246 flags on this corpus and finished at 47**, all by fixing the
CHECK rather than the text - and the survivors included a real defect (an inn's
price `10\G` translated to just `\G`). The taxonomy is in `llm-pipeline.md`;
the short version is that ordinals must be CONVERTED on both sides rather than
deleted, a leading `-` is an em-dash and not a minus, and a katakana numeral
matches inside place names unless you anchor it.

**`tools/trace_parser.py` - what the ENGINE does to a translated string.**
Reads `convert_escape_characters`, `obtain_escape_code` and this game's
nametag alias OUT OF the shipped `Scripts.rvdata2` at run time and raises if an
anchor moved, so it cannot certify a stale understanding. Demonstrates five
real failure classes including `\Helen` swallowed whole by `^[A-Z]+` and `\G`
with no word boundary rendering `10Ｇold`.

**`tools/translate_save.py` - and it has to be tested against a synthetic
save.** There was no save file on the box, so `tests/test_save.py` builds one
to the exact shape `DataManager.make_save_contents` produces. That test found a
real bug on its first run: the baked map was translated with an empty glossary,
so the save's name plates stayed Japanese while the patched data file said
Eris.

---

## Calibrating the cell - do this before wrapping anything

Ace draws message text at `Font.default_size` in `Font.default_name`. A game
that sets neither (common) leaves both to the engine and to whatever font the
player has, so the cell cannot be read out of the data. Two ways to get it, in
order of preference:

**Photograph one clipped line.** Inject a line you know is too long, screenshot
it, count the characters that survived, and solve:

    a faced line is drawn from new_line_x to (Graphics.width - padding)
    640 - 12 - 112 = 516 px carried 51 half-width characters -> 10.1 px/cell
    MS Gothic at 20 px reproduces the clip at exactly 51 of 54 -> FONT_PX = 20

That gave 616/10 = **61 cells unfaced** and 504/10 = **50 faced** on this game.

**Do NOT trust the author's envelope without checking it fits.** The corpus
said 66 and 56 cells; at a 10 px cell those are 660 px and 560 px in boxes of
616 px and 504 px. 255 of the author's own lines lose a character or two off
the right edge in the original game, and a budget copied from them clips too.

And remember that one string can have two budgets: this game's world map draws
the same place name in a 140 px command list (**11 cells**) and again as a
476 px info title (47 cells). The narrow one governs, and only the narrow one
clips. `tools/fix_worldmap.py` is the worked example, including using both
rows of a two-element description array the author left half empty.

---

## The two tracks disagree quietly - check for it

Each track is translated by its own pass, so the same source string can be
rendered two ways and *both tracks stay internally consistent*. Every per-unit
check passes. The defect is only visible by playing, and it is the kind a
player reports: this game shipped `マッスルーム` as "Mussroom" in 85 lines of
dialogue and "Muscleroom" on the world map, with `レーゲンヘーレ`
("Regenhere" against the correct German "Regenhoehle") sitting right beside it.

`validate.cross_track_conflicts` joins the tracks on the source string: for
every ledger literal marked translate, it compares the English against the
glossary entry and against every unit whose `src` is that same string. It
reports and never blocks, because plenty of disagreements are deliberate - a
map pin shortens what prose spells out (`王都バロン` is "the Royal Capital of
Baron" in dialogue and "Baron" on an 11-cell pin), and a stat window
abbreviates (`魔法回避` -> "M.Evasion"). On the finished game: 8 conflicts,
2 real and 6 intended.

**Settle a disagreement from the Japanese, never from the majority.** Both
correct readings here were the lone outlier, and both came from the script
audit, which ran with more context than the glossary seed. Grep the corpus
before preserving half a pun: zero of 14,750 units mentioned a mushroom, which
is what proved `マッスル` (muscle) was the half that mattered.

## Run `scripts apply` before every release build

`build_release.py` reads `Scripts.rvdata2` from the GAME folder, which is
correct - the in-place track has no other home - but it means the script track
lives outside the workspace and dies quietly. Refresh the working game folder
from a clean copy, or re-extract the archive, and every workspace artifact
still looks finished while the release ships Japanese menus under English
dialogue. Assert a known English UI string in the built release.

## Players run it on hosts you do not have

A patch gets played on JoiPlay and other reimplementations, where scripts that
lean on a Ruby incidental stop working. This game's recollection gallery is the
worked example: `usable_event?` never returns explicitly, so its value is the
trailing `if` branch, which ends in `p debug`. Ruby 1.9+ returns the argument
from `p`; a console-less host stubs it to nil, every event is rejected, the
gallery holds only its dummy entry, and the unguarded confirm handler raises
`undefined method 'event_id' for nil:NilClass`. The tell was the page counter
reading 1/1 instead of 1/6.

**Before touching anything, prove the patch is neutral.** Reimplement the
game's own filter in Python and run it over the pristine and the patched data:
here both gave 47 entries and 197 CGs, which ruled out the translation in one
step and pointed at the host. Only then read the script for a value that is
true by accident.

`tools/patch_scripts_code.py` applies anchored CODE patches with the same
discipline as the string ledger - exact match, only edited sections
recompressed, backup, read-back verification, idempotent. Define patches as
LISTS OF LINES: these sections use CRLF and an anchor built with LF matches
nothing. `tools/check_scripts_syntax.py` then runs `ruby -c` over all 129
non-empty sections; Ruby is optional and the check skips rather than fails
without it.

## The per-game work

Everything below came from a census, not a default. `docs/CENSUS.md` records
the evidence for each; redo it for the next game.

- which optional event codes hold text (`355`/`122`/`111`/`108` were all OFF
  here, `118`/`119` hard off as always)
- what the game's own scripts add to the escape set (here: `\NAME[...]`)
- how a speaker is identified - Ace's `101` has NO speaker field, so it is
  either a custom code, a face graphic, or nothing
- which script literals are display text and which are keys
- whether the two tracks agree on every shared source string, and which
- whether any script the patch depends on relies on a Ruby incidental (an
  implicit return value, a redefined constant) that a mobile host breaks
  disagreements are deliberate
- the message-box geometry, calibrated as above
- whether `CommonEvents[].name` is drawn (here it is: 47 of 56 appear in the
  recollection gallery, and ruling that out by habit would have shipped a
  Japanese scene list)
