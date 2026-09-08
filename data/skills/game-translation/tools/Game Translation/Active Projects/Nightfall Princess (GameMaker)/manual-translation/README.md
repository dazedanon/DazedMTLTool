# Nightfall Princess — manual English translation

English text and interface patch, 2026-09-05. The primary assistant authored the
translation locally, following this game's prepared glossary and bible. No
translation API, image API, or translation subagents were used.

The patch contains 631 translated instruction sites: 368 manually translated
units, 245 glossary-locked names, 17 synchronized help lookup keys, and one
enemy-list separator. The six `*.en.json` files are the hand-maintained text.
The earlier preparation files remain unchanged as source evidence.

The player-facing drop-in project is
`C:/Users/sw/Desktop/Projects/nightfall-princess-en`. Its payload is `data.win`
with a short README; it requires no patcher or Python. The window caption is
`Nightfall Princess | Translated by len`. The engine's internal project/save
identity remains `Nightfall_Princess`.

## Narration bottom-edge update

Long narration captions now move up just enough to leave a 16-pixel line-box
margin above the visible bottom edge. The four renderers in the hub, quests,
gallery and battle HUD use the room canvas when views are disabled, and the
active battle view otherwise. This preserves the full wording, font size,
wrapping, line spacing and bounce animation; shorter captions keep their positions.

All 110 captions were measured in the engine and checked across all four paths
(440 combinations). Five four-line captions needed the adjustment. The reported
caption was captured in every path at 1920x1080 and 1366x768, with measured ink
clearance of 19 and 14 pixels respectively. `narration_audit.py` retains the check;
`followup-narration/` contains the builder and evidence. The installer backs up
the preceding patch as `backup/data.english-v5.win`.

Compiling the hall Draw event moved two translated label instruction indices.
`release/narration-site-remap.json` maps the canonical original IDs to their current
output IDs. Re-extraction verified the complete, identical literal sequence within
each changed event, plus all 631 canonical texts. Use this mapping when patching
those two sites in the current English archive; keep original catalog IDs stable.

## Quest description update

Petrifying Gaze now fits the three body lines available below its reward.
The shorter wording preserves the petrification hazard, the need for the fairy
saint's help gathering materials, and the warning to avoid the monster's gaze.
`quest_audit.py` checks all 17 quests and 231 equipment rank variants sharing
this panel. It reserves the reward/header row and detects the previous four-line
description as a known failure. The full shop Draw event is exercised in the
title-only fixture in `followup-quest/`, at both supported window sizes.
The installer preserves the preceding patch as `backup/data.english-v4.win`.

## Status spacing and popup update

The First partner row now uses two lines when the full enemy name would collide
with its label. All 60 name-function entries and the Virgin state were checked
(61 cases, including duplicate names); 13 use the extra line.
The original font, panel and shorter values retain their sizes and positions.
The separate `spr_p` popup now reads **Virginity Lost**, preserving its pink fill,
brown outline, transparency, dimensions and origin. The total is now 32 labels
in 25 translated sprites.

The actual patched stats Draw event and popup were checked in a title-only
runtime fixture at 1920x1080 and 1366x768; the player's save stayed unchanged.
Evidence and the offline builder live in `followup-status/`. The 631 code-site
translations and preceding tooltip/menu fixes were preserved. The installer
backs up the preceding credited build as `backup/data.english-v3.win`.

## Tooltip heading update

The 2026-09-05 follow-up fixes Weapon Enchantment and four other long skill
headings. The renderer keeps the complete names, reduces only headings wider
than the space beside the icon, and reserves a 14-pixel right margin. The
description font and box stay the same. All 89 skill/stat titles pass the new
check included in `layout_audit.py`. The actual patched draw code was also run
in-engine: the five corrected headings have 15–17 pixels of measured right
margin. The test did not enter gameplay or change the player's save.

`release/tooltip-runtime-review.json` and `qa/tooltip-headings-fixed.png` contain
the evidence. The installer accepts the preceding English build and preserves
it at `backup/data.english-v1.win` when upgrading, alongside the Japanese backup.

## Menu and HUD fix

31 manually translated labels in 24 image sprites cover the title buttons,
settings, all three return buttons, movement/turn tutorial, inventory headings,
skill-tree prompt/navigation, status/equipment tabs, shop purchase/sell labels,
mouse hints, scene speed controls, gallery controls, Pleasure, and Game Speed.
`images/translations.json` records the Japanese, English, edit regions and fonts.
The branded title logo already includes its official English subtitle and is
preserved.

Only lettering regions change. Borders, icons, shortcuts, sprite dimensions and
origins are preserved. Three sprites had cropped storage too narrow for English;
their full canvases are now stored in an extension of the smallest existing UI
atlas (256×256 to 256×512). Atlas and sprite pixels were re-exported from the final
archive and compared exactly with the reviewed images. Neighboring art and font
glyphs are preserved.

## Installation and restoration

Close the game, then run from this folder:

```powershell
python install_translation.py --game "C:\Users\sw\Desktop\Games\Nightfall Princess"
```

Launch the normal `Nightfall Princess.exe` afterward. Installation verifies the
source and patch hashes and backs up the Japanese archive to
`<game>/manual-translation/backup/data.original.win`. Save files are not changed
by the installer. To restore the original archive, close the game and run the
same command with `--restore`.

## Validation

- All 631 final instruction sites re-extracted and matched against the catalog.
- Protected tokens and synchronized help lookups pass with zero errors.
- 1,243 rendered forms measured using the game's own font advances, including
  all 391 rank substitutions; tooltip width/height and singular-form checks pass.
- Eleven digit-versus-word differences have exact source/target review waivers.
- All 25 edited sprites pass final decoded-pixel round trips; the popup edit
  preserves every neighboring pixel on its existing atlas.
- Runtime smoke tests cover title/settings, inventory, stage selection, the
  battle HUD and speed tooltip, and the battle return button. The final build's
  title Settings screen was separately checked after correcting its Back label.
  This is not a complete playthrough of every scene and unlock.

The generic literal validator reports 184 control-expansion warnings and seven
translation-length warnings. The game-specific rank and layout audit performs
the expansion and measures descriptions with the embedded font advances. Reports are in `build/`,
`release/`, and `images/pixel-review.json`; screenshots are in `qa/`.

## Source quirks and integration

Four descriptions now accurately say effects trigger every N qualifying attack
hits, matching the verified runtime counters. The dormant Ricochet helper and
undisplayed fourth merchant record are translated while retaining their original
reachability. Holy Mark's source help coefficient remains 0.5; the documented
runtime coefficient is 0.75. That discrepancy is not silently changed.

English word wrapping replaces the original character wrap, and merchant text
is wrapped before typewriter animation. Settings now selects Back on the title
screen, Return to Title in the hub, and Return to Hub in battle. Button actions,
save schema, audio, font metrics and resource identities remain intact.

## Offline rebuild

Use the original archive or the hash-verified backup as input. Output archives
must not already exist. The stable toolkit dependencies are the installed
GameMaker `gmtt.py`/UTMT and the local Image Translation `imgtl.py` (Pillow, NumPy,
SciPy). No network is used.

```powershell
python build_catalog.py
python layout_audit.py
python "C:\Users\sw\Desktop\Tools\Game Translation\GameMaker\gmtt.py" patch "<original data.win>" build/catalog.en.json -o build/new-text.win
python layout/apply_layout.py build/new-text.win build/new-layout.win
python images/translate_ui.py
python images/apply_images.py build/new-layout.win build/new-english.win
python apply_title_credit.py build/new-english.win build/new-credited.win
$creditedBuild = Get-Content build/new-credited.win.title-report.json -Raw | ConvertFrom-Json
python followup-status/build_followup.py build/new-credited.win build/new-status.win --expected-input-sha256 $creditedBuild.sha256
$statusBuild = Get-Content build/new-status.win.followup-report.json -Raw | ConvertFrom-Json
python followup-narration/build_followup.py build/new-status.win build/narration-final/data.win --expected-input-sha256 $statusBuild.output_sha256
```

`images/export_ui.py "<original data.win>"` exports only the named interface
families if their source sprites need refreshing. The image round-trip check
also guards the three uncropped entries' coordinates, dimensions and origins.

The current manual catalog includes the quest fix, so a full rebuild already
contains it. To reproduce the exact shipped quest-only update from the preceding
status/popup release, use `followup-quest/build_followup.py` with that hash-verified
archive as input. Its report proves only `CODE:110:97` changes. Retained intermediate
reports describe their named build stages; `release/release-manifest.json` and
`release/text-roundtrip.json` identify the current final archive.
