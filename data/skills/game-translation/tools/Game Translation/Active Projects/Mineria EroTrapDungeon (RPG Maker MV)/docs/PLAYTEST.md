# Playtest and release

The pipeline finishing is not the patch working.

## Two-folder discipline, first

Keep two complete copies with unambiguous names:

```
魔王ミネリア… - CLEAN BACKUP     never edited, never pointed at by any tool
魔王ミネリア… - WORKING          the only one --game ever resolves to
```

Classify every command by what it mutates:

| Writes only into this workspace | Mutates the game folder |
|---|---|
| `census` `extract` `dryrun` `smoke` `selftest` `noop` `run` `live` `validate` `retry` `tighten` `ui` `scan` `mock` `release` `images/title.py` | `inject --in-place` (backs `data/` up first), `plugins apply` (backs `plugins.js` up first), `tools/translate_save.py --apply` (backs the saves up first) |

`inject` without `--in-place` writes a complete `out/www/data` you copy over
yourself, which is the safer default and the one the release builder reads.

**If the game breaks:** restore `www/data` from the newest `data_backup_*`
folder and `www/js/plugins.js` from the newest `plugins.js.bak_*`. Both are made
automatically before every in-place write. If that is not enough, copy the whole
folder again from CLEAN BACKUP - the workspace loses nothing, because the store
is here.

---

## The five items, after EVERY export

A defect found after one export has one obvious cause. A defect found after
twenty has twenty.

1. **Launch the game normally.** Not from a script, not with a console attached.
2. **Load a save near what you just changed**, or start a new game.
3. **Open every menu.** Item, Equip, Status, Options, Save, and the shop.
   **Database text renders only in menus and never on a map**, so a map-only
   playtest cannot see a database pass at all. This is the single most commonly
   skipped step - and in this game it is also the only place the
   `LL_MenuScreenCustomMV` help lines and the `TMMenuLabel` status labels appear.
4. **Walk every map you exported.**
5. **Save once and load it back.**

### Six defect classes to hunt

- the same name spelled two ways across files
- a line that does not match its scene
- text overflowing its box, or covering the screen
- an awkward line break
- residual Japanese
- the title image too crowded after editing

**Fix and re-test ONE defect before changing anything else.**

For a leftover Japanese string on screen: screenshot it, OCR the screenshot,
then `Ctrl+Shift+F` the exact string over `www/data`. `python tl.py scan` finds
the same thing from the other end and tells you which event code it sits in.

---

## This game specifically

| Check | Where | Why it is on the list |
|---|---|---|
| The map HUD shows `Lewdness 40/300` **with the `/max`** | any map | `drawVnCurrentAndMax` silently drops the `/max` when the label no longer fits. The gauge was widened for exactly this. |
| The menu status panel reads `Lewdness` / `Lewd Cap` / `Mana` / `Mana Cap` un-squashed | main menu | `Window_MenuLabel` gives the name 128px and `drawText` **squeezes** rather than clips, so an over-long label renders visibly compressed instead of erroring. |
| Every menu command shows a help line under it | main menu, arrow through all 8 | `menuHelpTexts[].symbol` is keyed on the displayed command name. A mismatch makes the line vanish with no error. |
| Right-click hides the message window | any dialogue | `MessageWindowHidden` matches `case '右クリック':` against a parameter that must stay Japanese. |
| The stat popup reads `Lewdness +5`, not `Lewdness` | walk into any trap | `command356` splits on ASCII space. A space in the text field truncates the popup to its first word. |
| The title screen reads `Quit Game` as its fourth command | title | `gameEnd.endName`, distinct from the menu's `Game End`. |
| The shop shows `Stock` and `SOLD OUT` | the Item Shop, Map047 | `KMS_ShopInventory`. |
| Item descriptions fit **two** lines | Item menu, every consumable | `Window_Help` is 2 rows tall. `tl.py validate` vetoes an over-tall wrap, but see it on screen. |
| Choice windows are not off-screen | the village conversion menu (Map029 ev19), the CG-room prompt | `Window_ChoiceList` sizes to its content. |
| The map-name banner is readable | entering any of the 19 named maps | `MapNameExtend` with `横幅 = 0` sizes to content. |
| A trap-encounter scene reads in Mineria's voice | walk into a slime | The `E<monster>接触` speaker rule. If one of these reads as an NPC, the rule is wrong and `config.solo_speaker_scene_re` needs revisiting. |

### Never sign off a scene from the Recollection Room

`Map011 回想部屋` replays every CG. The replay path renders lines out of context,
with different variable substitutions, and tells you nothing about the live
trigger. Use it only to confirm the CG count and see which sets exist. Reach
each scene the player's way to check the text.

### Reaching content fast

`Tools\Projects\forge-mvmz` (`Forge_MV.js`) is a drop-in F10 overlay: jump to
any map, set variables and switches, run a common event. Copy it to
`www/js/plugins/` and add it to `plugins.js` **last**. Remove it before
building the release - `build_release.py` does not know about it.

The debug items already in the game do most of this without a plugin:
`淫乱度変更デバッグ用` (Items #24), `服装変更デバッグ用` (#25),
`魔力変更デバッグ用` (#26), `CG部屋移動デバッグ用` (#34).

---

## Four passes that per-export testing structurally cannot do

Before release:

1. **Play start to finish**, not from old saves. An old save resumes *past* the
   maps whose events you edited.
2. **Have a second person play.** They take choice branches you never take -
   and choices are the only text where a wrong translation changes what the
   player *does* rather than what they read.
3. **Copy the finished patch onto a CLEAN copy of the game and test that.**
   The only check that catches a patch which works solely because your working
   folder still holds a file the release does not.
4. **Audit the archive** for keys, notes and screenshots.

---

## Release

```powershell
python tl.py inject
python tl.py scan                 # must report 0 leaked sentinels
python tl.py validate             # must exit 0
python tl.py plugins check        # menu-help symbols must agree
python tl.py plugins apply
python images/title.py
python tl.py release -o out/release
```

`build_release.py` verifies **by absent files, not by config values** - a config
value is an intention, an absent file is evidence. It:

* copies `out/www/data/*.json` and the in-place `plugins.js`,
* sets `status: false` on **`DRS_AllDataExtractor`**, the author's own
  script-dump plugin, which writes 44 Japanese `.txt` files into
  `www/data_output/` at boot. Deleting the `.js` instead would leave
  `plugins.js` registering a file that is not there and RPG Maker throws at boot,
* denylists `www/data_output/`, `www/save/`, `*.bak_*`, `data_backup_*`,
  `desktop.ini`, `.git*`,
* reports every player-facing Japanese string still in the shipped data,
* writes `MANIFEST.txt` with the install steps and what was deliberately left out.

Ship the **patch-only** archive. A full repack of the game is a licensing
question, not a technical one, and the builder deliberately does not make one.

### Existing player saves

```powershell
python tools/translate_save.py                # dry run: coverage report
python tools/translate_save.py --apply        # backs up to save_backup_* first
```

A save carries the build's *data*, not just its position: RPG Maker copies actor
names and the message backlog into it and never re-reads them, so a name
translated later stays Japanese in every save that already exists while the
shipped `data/*.json` greps clean. Every write asserts
`decode(encode(data)) == data` before it lands.

The *position* is safe by construction here: injection never changes the number
of commands in an event list, so the index a save stores still points at the
same command.
