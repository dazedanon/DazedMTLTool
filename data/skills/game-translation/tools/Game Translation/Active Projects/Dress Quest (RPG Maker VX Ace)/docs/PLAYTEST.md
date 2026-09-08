# Playtest and release - Dress Quest

The pipeline finishing is not the patch working. Run the five-item matrix after
**every** export, not once at the end: a defect found after one export has one
obvious cause, and a defect found after twenty has twenty.

## Two folders, always

    Dress Quest - CLEAN BACKUP    never edited, the recovery copy
    Dress Quest                   the WORKING install, the only one any tool points at

Extraction and translation write only into the workspace
(`Tools\Game Translation\Active Projects\Dress Quest (RPG Maker VX Ace)\`).
The game is mutated by exactly three things: `tl.py inject --in-place`,
`tl.py scripts apply`, and copying a release over it. Each has a preview
(`inject` to `out\Data` first, `scripts apply --dry-run`), and the ordering rule
is always preview before apply.

**When the game breaks, do not pile on more exports.** Leave the broken copy in
place - it still holds work - make a fresh working copy from the clean backup,
and re-add ONE group of translations at a time with a playtest after each.
Never delete `out\` or `tl\`: those results are already paid for and their
validity does not depend on whether the playable copy runs.

## Before the first playtest: two things this pipeline cannot measure

1. ~~Confirm loose files override the archive.~~ **ANSWERED, and the answer
   was no.** With `Game.rgss3a` present, RGSS3 serves `Data\*.rvdata2` from the
   ARCHIVE and ignores the loose file beside it: the game started in Japanese
   with a fully translated `Data\` in place. The delivery is therefore: extract
   the archive (`rgssad.py Game.rgss3a -o .`), copy the patch over the
   extracted `Data\`, and MOVE `Game.rgss3a` out of the folder. Keep it - it is
   the way back.
2. **Photograph a message box and count the cell width.** `docs/CENSUS.md`
   derives ~8.75 px per half-width cell from the author's own line lengths,
   which is what the wrap budget is built on. The budget is safe either way -
   it is the envelope the shipped Japanese already fits in - but confirming it
   turns `tl.py mock --font-px` from an approximation into a measurement.

## The five items, after every export

1. **Launch the game normally.**
2. **Load a save near what you just changed**, or start a new game.
3. **Open every menu** - item, skill, equip, status, save, and the shop. VX Ace
   database text renders ONLY in menus and never on a map, so a map-only
   playtest cannot see a database pass at all. This is the most commonly
   skipped step.
4. **Walk the maps you just exported.** Check the map-name banner too: 212 maps
   draw one.
5. **Save once and load it back.**

Hunt five defect classes: the same name spelled two ways, a line that does not
match its scene, text overflowing its box, an awkward line break, residual
Japanese.

**Fix and re-test ONE defect before making any further change.**

For each leftover Japanese string: screenshot it, then search the store for that
exact string (`tl/units/*.json`) to find the unit and the field it came from.
If it is not in the store at all, it was never a unit - check `tl.py scan`,
which lists exactly that class.

## Things specific to this game

* **The name plate is drawn from `\NAME[...]`, in its own window above the
  message box.** Watch it on the first few conversations: an untranslated
  speaker shows a Japanese plate over English dialogue, and `tl.py validate`
  lists those separately because no per-unit check can see them.
* **Faced and unfaced messages have different widths.** A faced box loses 112
  px to the portrait. If English runs under the portrait, the unit's `faced`
  flag is wrong, not the wrap width.
* **The title screen has a Recollection room.** Use it to confirm the CG count,
  never to sign off a scene: the replay path renders lines out of context and
  tells you nothing about the live trigger. Reach the scene the player's way.
* **Battle-log fragments only appear in combat.** `は倒れた！` renders after a
  name, and a leaked dummy subject (`Eris Taro has fallen!`) survives every
  text-only review. Fight something.
* **Seven dresses, seven equip states.** Change dress in the equip menu and
  check the portrait, the armour name and the status screen each time.

## Before release, four passes per-export testing cannot do

* **Play start to finish.** An old save resumes past the maps you edited.
* **Have a second person play**, so someone takes the choice branches you never
  take (532 choice labels, 36 unique).
* **Copy the finished patch onto a CLEAN copy of the game and test that.** The
  only check that catches a patch which works because your working folder still
  holds a file the release does not.
* **Audit the archive** for API keys, private notes and screenshots.
  `tools/build_release.py` enforces a denylist and verifies by absent files,
  but read the manifest yourself.

## Existing saves

A save carries the build's DATA, not just its position:

* `Game_Actor` copied `@name` and `@nickname` from the database at new-game and
  never re-reads them;
* `Game_Map` stores the WHOLE `RPG::Map` for the map the player is standing on,
  so that map's entire script is inside the save.

Run `python tools/translate_save.py --apply` once against existing saves. It
rewrites those in place (keeping a `.bak`) using the same text pipeline as
`inject`, so a line reads identically whether it came from the save or from the
patched file.

The patch itself cannot break a save: `tl.py verify` proves every command list
keeps its length, its codes and its indents, which is what the interpreter's
saved `@index` points into. `build_release.py` will not build if that fails.
