# Validation case: Nightfall Princess

Tested 2026-09-05. Original `data.win`: 153,903,396 bytes, SHA256
`2c22ad3c7dd540f4e870c195935a206eeafc58665c458673c88c3acb9a5ab611`.

## Original toolkit validation

- x64 Microsoft Visual C/C++ GameMaker VM runner, Direct3D 11; bytecode 17.
- UTMT detects feature version 2023.8.0.0. This is its format inference, not
  a verified exact IDE/runtime patch version used to build the game.
- 2,730 STRG records; 617 contain CJK characters.
- 630 CJK literal uses, covering 614 pooled strings. The other three strings
  are font face names: `思源黑体 CN Regular`, `思源宋体 CN`, `站酷庆科黄油体`.
- All 227 parent GML entries decompile, with zero reported failures. The 288
  total entries include child functions represented inside their parent code.
- 51,851 VM instructions, seven fonts, 13 rooms, 57 objects.
- 53 embedded textures and 212 embedded audio records hashed and preserved.
- Nineteen tests pass, including real-archive integration: byte-identical
  no-op; a long UTF-8 replacement containing non-ASCII BMP and supplementary
  characters; caption replacement; original pool preservation; isolated edit
  of one multiply-used literal; overwrite/source mismatch and control-code
  rejection. The supplementary-character sample tests storage, not font support.
- Tests never replace the game's original data file. No runtime launch or
  visual/save compatibility validation was performed for this tooling task.

## Findings from the original source

The code's `scr_newline` wraps after exceeding a width and splits at any
character. `obj_dialog_Step_0` has a separate 520-pixel typewriter wrap loop.
English word wrapping needs a separate, measured change; do not treat these
as one renderer or assume text prewrapping alone fixes both paths.

All seven embedded fonts contain the tested ASCII letters, digits and basic
punctuation, but none contains U+2014 EM DASH or U+2019 RIGHT SINGLE QUOTATION
MARK. A font gate should use actual glyph tables, not nominal character ranges.

`scr_save` and `scr_load` serialize numeric fields to `date.sav`. Preserving
instruction positions and asset IDs is useful, but is not a save compatibility
proof. A translation release still needs a live load/save test.

The title draws `spr_title_text` and `spr_title_button_*` sprites. Title art is
outside this text-tooling task.

## Completed translation and UI follow-ups

The same session subsequently completed manual translation and a drop-in
project. Stable implementation and evidence:
`C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)/manual-translation/README.md`.
The original toolkit-only runtime disclaimer above is historical; later checks
are listed here with their actual limits.

- 631 translated code sites: 245 locked names, 368 prose/help/UI units,
  17 synchronized help lookup keys and one Japanese-punctuation-only separator.
  A CJK-only extraction missed that last site. The requested caption credit is
  a separate `GEN8:display_name` change, not part of the 631 code-site count.
- 1,012 measured rendered forms include 391 rank substitutions. Checks cover
  actual embedded-font advances, width and rows together, singular grammar,
  word-valued replacements and composed help-height behavior.
- English wrapping required a shared wrapper change plus complete-message
  prewrapping at 510px before the merchant typewriter's 520px loop. Imports
  compile only approved events with UTMT `CodeImportGroup`; all other code and
  existing resource identities remain intact. Settings labels now match the
  existing Back/Return to Title/Return to Hub actions.
- User-reported Japanese menus were baked sprites. The requested UI scope
  contained 87 inspected sprites/89 frames, with 31 labels changed in 24 sprites
  across eight atlases. Borders, icons, shortcuts and pixels outside approved
  lettering masks were preserved. The branded title logo was retained.
- Three padded sprites exceeded their stored crop. Atlas equality alone passed
  while Settings was clipped. Extending an existing atlas from 256x256 to
  256x512 and remapping those existing page items preserved full English labels.
  Both decoded atlases and all 24 padded sprite exports match reviewed pixels;
  dimensions, origins, neighboring art and font glyph pixels are preserved.
- A passing description audit missed Weapon Enchantment's 292px heading in a
  252px space. A separate 89-heading audit found five overflows. A heading-only,
  uniform shrink-to-fit keeps all canonical names; 84 shorter headings retain
  their original size. The smallest applied scale is about 0.863.
- The actual shipped tooltip block was extracted from the patched archive into
  a title-only runtime fixture. Five long headings had measured right margins
  of 15-17px. The test did not enter gameplay and the player's save hash stayed
  unchanged. This checks rendering, not the live trigger or a full playthrough.

## Final caption and delivery evidence

Final `data.win`: 155,410,724 bytes, SHA256
`048ab7108d911f15be6cd1e1751b489c645a70c2c32ac7c59962fea08116d3aa`.
The displayed window title is `Nightfall Princess | Translated by len`.
The internal `Nightfall_Princess` project/save identity is unchanged; the
caption-only stage preserved all 631 translated references, code, fonts and media.

`C:/Users/sw/Desktop/Projects/nightfall-princess-en` contains the drop-in
`data.win`, a minimal install/restore README and local repository metadata.
The working payload is the full binary, with Git LFS used for repository storage.
No game executable, save, QA fixture or development scripts are player payload.
A clean game copy launched using this project's actual payload; the exact
caption was read from the process, the save hash was unchanged and the installed
archive matched. No remote publication was part of this task.

Relative to that stable `manual-translation` directory, adapters live in
`layout/apply_layout.py`,
`images/assets.csx`, `images/apply_images.py`, `tooltip_audit.py` and
`apply_title_credit.py`. Evidence lives in `release/release-manifest.json`,
`release/text-roundtrip.json`, `release/tooltip-runtime-review.json`,
`release/title-credit-report.json`, `release/project-package-report.json` and
`images/pixel-review.json` under that stable project.

Runtime smoke checks covered title/settings, inventory, stage selection, battle
HUD and return labels, the heading fixture and final package launch. All edited
sprites received visual and pixel review. This was **not a complete playthrough**.
Dormant and overwritten source records keep their reachability; the source help
coefficient 0.5 versus runtime 0.75 discrepancy remains documented, not silently
changed. Per-game constants and rulings must be re-measured before reuse.
