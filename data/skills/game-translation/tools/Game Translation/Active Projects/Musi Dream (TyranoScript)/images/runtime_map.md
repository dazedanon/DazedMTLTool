# Image runtime map — Musi Dream

Read-only source audit for the image translation request, 2026-09-06 UTC.
This document identifies image paths and usage. It does **not** claim that an
image contains Japanese, that its transcription is correct, or that it has been
visually reviewed. The separate visual inventory decides those matters.

Evidence: pristine `resources/app.asar.original`, `reports/archive_inventory.json`,
and `source/app` scripts. The archive contains 517 image entries, including vendor
and editor assets. Files below are paths **inside the archive**. Source line
numbers refer to pristine scenario files under `data/scenario/` unless specified.

## Resolve the actual image consumer

- `[bg storage=...]` loads `data/bgimage/<storage>`.
- `[tb_image_show]` in `system/builder.ks:19` wraps `[image layer=1]`.
  `[individual_image]` in `data/others/plugin/individual_image/init.ks:2` wraps
  `[image]` as well. The shipped non-base `image` consumer defaults to **fgimage**:
  both load `data/fgimage/<storage>` unless an explicit folder overrides it.
- `[chara_show]`, `[chara_mod]`, registrations and character layers use
  `data/fgimage/`. Resolve `chara_part` IDs through `system/chara_layer_define.ks`;
  a part ID resembling a filename is still a lookup key.
- `[button graphic=...]` defaults to `data/image/`; `enterimg`, `clickimg` and
  `activeimg` share its folder. `../others/plugin/...` resolves under `data/others/`.
- `_clickable_img` is Builder metadata, not a rendered image. The shipped
  `clickable` and `button` consumers do not access it. Its many references to
  `ev_title.jpg`, `test.jpg`, or `ev_okini.png` are not load evidence.
- This game's installed delivery is an ASAR repack; preserve every archive path.
  The older reference game's loose-app loader priority does not apply here.

## Title, tutorial and interactive controls

| Exact archive path | Source reference | Runtime check |
|---|---|---|
| `data/bgimage/ev_title.jpg` | `title_screen.ks:50` | Cold launch and return from an ending. Inspect all baked art, including small background detail. |
| `data/image/ui_btn_start.png` | `title_screen.ks:53`; `scene2_undress.ks:121`; `scene4_insert.ks:538,581`; `scene7_ending.ks:151` | Title button at (71,465), 168×61; ending button at (959,500). The same wording must make sense in both contexts. |
| `data/image/ui_btn_load.png` | `title_screen.ks:54` | (71,582), 168×61; open and leave Load. |
| `data/fgimage/default/ui_hint_undress.png` | `scene2_undress.ks:64` | (40,589), 188×115; tutorial before first clickable. |
| `data/fgimage/default/ui_hint_kosuri.png` | `scene3_kosuri.ks:25` | (40,589), 173×106; tutorial beside the interaction area. |
| `data/fgimage/default/ev_insert_explain.jpg` | `scene4_insert.ks:13` | Full-screen explanation, 1280×720; click once to continue. This is the active copy. |
| `data/image/ui_btn_insert.png` | `scene4_insert.ks:32`, repeated for all ten facial states | (71,465), 168×61. |
| `data/image/ui_btn_stop.png` | `scene4_insert.ks:33`, repeated for all ten facial states | (71,582), 168×61. |
| `data/fgimage/default/ui_icon_hetare.png` | `scene4_insert.ks:56,99,185,317,361,452` | (249,579), 101×69; appears after choosing Stop in safe states. |
| `data/fgimage/default/ui_icon_danger.png` | `scene4_insert.ks:126,212,213,257,389,390` | (258,445), 93×83; danger states can add another at (224,388). |
| `data/fgimage/default/ui_gameover.png` | `scene2_undress.ks:120`; `scene4_insert.ks:537,580`; `scene7_ending.ks:150` | Full 1280×720 overlay behind the shared restart button. |

`data/image/ui_btn_hayai.png`, `ui_btn_hutuu.png`, `ui_btn_yukkuri.png`, and
`data/fgimage/default/ui_icon_select.png` have no usage in the source scenario or
plugin scripts searched. The real scene 5 speed choices are `[glink text=...]`;
their English was handled by the completed text track. Review these shipped
images visually, but do not call their existence proof of a live untranslated UI.

## Browser ending and final scene

| Exact archive path | Source reference | Runtime check |
|---|---|---|
| `data/fgimage/default/ev_mission.jpg` | `scene8_syussan.ks:5` | Full-screen transition card at `*start`; `[l]` waits for a click. |
| `data/bgimage/ev_Ytube.jpg` | `scene8_syussan.ks:10` | Browser at `*ytube`; six thumbnails and top navigation form one flattened image. |
| `data/fgimage/default/ev_okini.png` | `scene8_syussan.ks:22` | Full 1280×720 transparent overlay at `*okini`; must align with the browser underneath. |
| `data/bgimage/ev_sakuzyo.jpg` | `scene8_syussan.ks:111` | `*sakuzyo`, reached by the bottom-center Ytube tile. |
| `data/bgimage/ev_Hdouga.jpg` | `scene8_syussan.ks:118` | `*Hdouga`, reached from the second favorites entry. Inspect navigation and all thumbnail labels separately. |
| `data/fgimage/chara/24/ev_baby1.jpg` through `ev_baby7.jpg` | `scene9_baby.ks:5,19,21,46,68,99,126` | Final scene character frames, 1280×720; changes happen during normal dialogue. |
| `data/fgimage/default/ev_baby8.jpg` | `scene9_baby.ks:142` | Full-screen concluding frame before the viewer's final dialogue. |

Browser click map (game coordinates, preserve all clickable geometry):

| Screen | Rectangle x,y,w,h | Destination |
|---|---|---|
| Ytube | 1062,4,154,42 | Favorites overlay `*okini` |
| Ytube | 429,413,403,285 | Removed-video page `*sakuzyo` |
| Favorites | 1062,57,205,51 | `*pixup` commentary |
| Favorites | 1061,109,205,51 | `*Hdouga` browser |
| Favorites | 1061,155,205,51 | `*adultchat` commentary |
| Favorites | 1062,205,205,51 | `*mail` commentary |
| Favorites / Removed page / Hdouga | 12,56,56,30 | Ytube back control |
| Hdouga | 850,107,408,275 | `scene9_baby.ks:*start`, the story's final video |

The other five tiles on each browser open viewer comments and return to their
browser; they are genuine clickable player content. Do not rename `*kana`,
`*elf`, `*3p`, `*hurin`, `*saimin`, `*Hdouga` or any other technical targets.
The `ev_baby` character ID is the heroine's speech-bubble anchor, not age evidence.

## Artwork families and flattened variants

Text can occur in clothing, cut-ins or background art even when the filename does
not suggest it. Visually inspect all frames in these active families, including
part images and static full-screen counterparts.

| Scene | Main image families / backgrounds |
|---|---|
| 1 | `data/bgimage/ev_bed_kiwi.jpg` (`scene1.ks:6`) |
| 2 | `data/fgimage/chara/1/` undress base/parts, `/2/` insect, `/3/` face |
| 3 | `data/bgimage/ch_kosuri.jpg`; `data/fgimage/chara/4/` face/marks, `/5/` insect, `/7/` cut-ins |
| 4 | `data/bgimage/ch_insert.jpg`, `ev_insert1.jpg`, `ev_insert2.jpg`, `ev_insert3_clear.jpg`; `data/fgimage/chara/8/`, `/9/`, `/10/` |
| 5 | `data/bgimage/bg_piston.jpg`; `data/fgimage/chara/13/` cut-ins, `/14/` bed frames, `/21/manpu_toiki.png` |
| 6 | `data/bgimage/ev_bed_kage.jpg`; `data/fgimage/chara/15/` body, `/16/` face/marks, `/17/` cut-ins, `/18/` and `/19/` front cut-ins, `/22/` alternate face/marks, `/23/` full-screen frames, `/25/` transparency layer |
| 7 | `data/bgimage/ev_bed.jpg`, `ev_toire.jpg`; `data/fgimage/chara/23/ev_ne_okita.jpg` and `ev_ne_okita_biku.jpg` |
| 8–9 | Browser files and final-scene family listed above |

The archive contains 317 files below `data/fgimage/chara/`. This is an inventory
count, not a count of text-bearing images or a claim every registered part is
actually displayed. `system/chara_define.ks` and `system/chara_layer_define.ks`
are active initialization, while the two `_preview.ks` scripts are editor copies.

Same-stem findings, checked by SHA256 of **original ASAR entry bytes**:

| Copies | Relationship |
|---|---|
| `data/bgimage/ev_okini.png` and `data/fgimage/default/ev_okini.png` | Byte-identical. Foreground copy is the actual favorites overlay. |
| `data/bgimage/ev_insert_explain.jpg` and `data/fgimage/default/ev_insert_explain.jpg` | Different bytes; inspect both, do not copy blindly. Only foreground copy has a live draw/preload reference. |
| `data/bgimage/ev_baby1.jpg` and `data/fgimage/chara/24/ev_baby1.jpg` | Different bytes; active final-scene copy is under chara/24. |
| `data/bgimage/ev_ne_okita.jpg` and `data/fgimage/chara/23/ev_ne_okita.jpg` | Byte-identical. Character copy is used in scene 7. |
| `data/bgimage/ch_undress_diff4.png` and `data/fgimage/chara/1/_parts/base/ch_undress_diff4.png` | Byte-identical; part copy is selected in scene 2. |
| `data/fgimage/default/ev_rabel33.jpg` and `data/fgimage/chara/23/ev_rabel33.jpg` | Byte-identical. Both forms are used by scene 6. |
| `ev_rabel53.jpg`, `ev_rabel69.jpg`, `ev_rabel93_tamago.jpg` under `data/fgimage/default/` and `data/fgimage/chara/23/` | Each same-name pair differs in bytes; inspect both. Scene 6 explicitly draws default/ev_rabel53 at line 699 and default/ev_rabel69 at 1095. |
| `data/bgimage/bg_config.jpg`, `data/image/config/bg_config.jpg`, `tyrano/images/system/bg_config.jpg` | All byte-identical; these are separate from active theme `config_bg.png`. |

Many part images are exact duplicate copies elsewhere: insertion cut-ins under
chara/9 and chara/13, bed frames under chara/14 and its `_parts/bed`, and face/mark
images shared by chara/3,4,8,15,16,22. Fan out a reviewed replacement by hash to
matching originals; preserve distinct bytes unless separately reviewed.

## Active theme menus and hover variants

The active theme is `data/others/plugin/theme_kopanda_16/`. Its `init.ks` replaces
all four sysviews, loads its own configuration through `setting.js`, and its
`add_theme_button` macro is invoked by `data/scenario/system/plugin.ks:41`.

| Archive paths relative to the active theme | Use |
|---|---|
| `image/button/{qsave,qload,auto,skip,log,menu,close}.png` and corresponding `*2.png` | Seven role controls at y=518; macro in `init.ks:54–72`. Mouse enter substitutes `*2.png`. |
| `image/system/menu_bg.png` | Main menu backdrop, `html/menu.html:33`. |
| `image/system/menu_button_{save,load,config,title,close}.png` and corresponding `*2.png` | Main menu actions; close is shared with save/load/backlog. |
| `image/system/menu_save_bg.png` | Save backdrop, `html/save.html:33`. |
| `image/system/menu_load_bg.png` | Load backdrop, `html/load.html:32`. |
| `image/system/menu_log_bg.png` | Backlog backdrop, `html/backlog.html:14`. |
| `image/system/arrow_{up,down}.png` and corresponding `*2.png` | Save/load/backlog scroll controls; hover names generated in template JS. |
| `image/system/saveslot.png` and `saveslot2.png` | Save slot plates selected by `ts16.css:155–204`. |
| `image/config/config_bg.png` | Configuration screen backdrop, theme `config.ks:155`; baked settings captions, if present, live here. |
| `image/config/back.png` and `back2.png` | Config back button at (0,645), theme `config.ks:156`. |
| `image/config/{c_btn.gif,set.png,mute.png}` | Configuration toggles/markers, dynamically composed paths from `tf.img_path`. |
| `image/frame_message.png` | Message frame, `init.ks:29`; inspect decorative text if present. |

The template hover handler generates the alternate filename (`.png` → `2.png`),
so static `src=` matching alone misses half the controls. Test default and hovered
states in the actual title, menu, save, load, backlog and configuration screens.
The theme's sample prose is real text fetched separately from
`testMessagePlus/sampletext.ks`; it has already been translated in the text track.

## Shipped templates, fallbacks and editor assets

- `tyrano/images/system/` belongs to stock engine UI. The active sysviews are
  overridden by the theme, but the engine still uses shared assets such as its
  menu glyph, cursors, next-page glyph and save thumbnail fallback. Avoid treating
  that entire directory as dead.
- `data/scenario/config.ks` is the stock configuration fallback, distinct from
  the theme's active configuration. It refers to `data/image/config/bg_config.png`,
  `c_btn_back.png`/`c_btn_back2.png`, `c_skipoff.png`/`c_skipon.png`, and related
  switch images. Keep its visual inventory separate from the theme QA.
- `data/image/button/` has 24 stock role-button images; the active macro uses the
  theme-specific directory instead. No scene/plugin references to that stock
  directory were found in this audit.
- `data/image/title/button_{cg,config,load,replay,start}.gif` are stock title
  controls. The active title script uses `data/image/ui_btn_*.png` instead.
- `data/others/plugin/individual_image/kobetu.png` is the plugin's Builder icon;
  `individual_image/init.ks` draws the storage requested by the scenario, not this
  icon. `individual_image.builder.js` is editor metadata.
- `node_modules/zip-dir/test/...` image is a vendor test fixture; jQuery UI's six
  icon sheets are vendor icons. Their presence does not imply game wording.

## Release QA guidance

Inspect every translated output at native size and a 2–3× text crop before the
runtime check. Preserve canvas size, alpha, alignment, surrounding art and the
original filename; do not move hotspots to compensate for artwork changes.
Runtime tests should include title/Load, all theme screens and hover variants,
scene 2 and 3 hints, scene 4 explanation and danger/stop indicators, at least one
game-over overlay with its shared restart button, scene 8 transition/browser/
favorites/removed-video screens, and every changed final-scene frame. Review
clothing or SFX edits at their actual composed positions, not as isolated layers.

Use the existing local game QA fixture/CDP helpers; this audit made no API calls,
network requests, image edits, scene edits, or installation changes.
