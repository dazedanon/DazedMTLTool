# Translation validation and future updates

The store contains 509 manually translated units across 574 source occurrences.
The image update contains 30 replacement entries: 28 manually redrawn images
and two exact duplicates. Its visual census audited 517 entries / 448 unique
images. The text and image package is installed in the main game; its archive
matches the isolated QA archive. All 30 replacement images passed native-size
decoding, as recorded in `reports/image_decode.json`. `reports/image_runtime.json`
records 14 active scene assets checked visually in game and 16 unused or template
assets reviewed at native size. A fresh normal playthrough covered all nine scenes
and returned to the title without renderer exceptions. Targeted checks covered
both warning indicators, the final caption, browser removal/back/favorites, five
menu screenshots and hover states, and legacy and English save/reload. All 442
measured text units fit without overflow. Not every alternate route was played
individually.

The installed archive retains 1,005 entries with 50 replacements. The new package's
restore test reproduced the exact original archive. Final evidence and tested
identities are recorded in `reports/RELEASE_VALIDATION.json`; the fresh normal
playthrough is recorded in `reports/image_visible.json`. Historical reports retain
earlier validation states and must not be treated as proof for the new image payload.

Before each future release:

1. Import reviewed wording through the strict importer. Preserve IDs, source spans,
   placeholders, labels and registered keys.
2. Run `tl.py selftest` and `tl.py validate --complete`.
3. Rebuild any changed image family from `images/source`; review each changed
   output and its 2–3× text crops, update the exact approved hashes, and run
   `images/assemble.py`. Keep `images/PROMPT.md`, `image_glossary.json`, source/target
   records, masks and fit measurements in sync. Require the complete 517-entry
   census and the documented exclusion; unresolved text-bearing candidates fail.
4. Run `scripts/build.py`, then `manual/runtime_audit/compare_runtime.cjs` with the
   shipped runtime. All 33 scenario arrays must retain their 5,138 total elements,
   label positions, control attributes and source line coordinates.
5. Run `scripts/package.py --game-root <game directory>` and install that exact
   package into the isolated QA game. It reinjects before packaging a strict
   allowlist. The installer verifies all 1,005 archive entries and SHA256 block
   metadata. Keep the previous patch manifest to restore that release before
   changing the payload supported by its installer. The image update's expected
   allowlist is 50 payload files / 56 package files.
6. Run `manual/fit_audit.py` with the new parsed-output report and live renderer.
   Include paragraph padding, inline page markers, outlines and neighboring controls.
   Never add or remove break tags to satisfy an estimated character budget.
7. Exercise changed content through normal controls. Open save, load, backlog and
   configuration; check original-save loading and save/reload in the newly packaged
   archive. Preserve save fixtures before tests.
8. Decode all replacement image URLs through the installed game's Chromium
   renderer, including PNG bytes stored at original `.jpg` paths. Check native
   canvas dimensions and scaled readability. Compare encoded bytes before
   decoded pixels; preserve any embedded ICC profile and independently convert
   expected pixels to sRGB when necessary. The current theme preview matches
   within one channel-value rounding difference after LittleCMS conversion.
   Follow `images/runtime_map.md` for
   title, hover controls, tutorial hints and explanation, danger/stop indicators,
   game-over controls, mission card, browser/favorites/removal screens and the
   changed final-video frame. A successful file decode is not a visual fit check.
9. Record exact tested scope and limitations, then synchronize the reviewed
   project to Tools with `scripts/sync_project.py --apply`.

Measured layout: 1280×720 screen; normal content 870×118px, default 28px text with
36px line height and 8px paragraph-top padding. Nameplate 360px at 26px. Bubble widths and
fonts vary by character; height grows with text, but the inline page marker needs
space. Piston columns are 169px apart. Configuration sample content 760×62px at 18px.

The patch preserves package name, projectID, preload/IPC, character registrations,
macro indices and save location. Saved display fields are refreshed on load;
registered keys, counters and event attributes remain unchanged. The sample loader
preserves word spaces. Six scenario continuation lines use the engine's `_ ` space
marker; the sample loader has its own reviewed separator. Backlog aliases change
visible names while retaining original IDs and CSS classes.

The user explicitly requested image translation after the text release, so it is
part of this update's scope. Native image checks require source/output hashes,
nonempty erasure masks, preserved dimensions/mode, no unintended pixel changes
outside declared zones, and magnified inspection for Japanese remnants, damaged
art, clipped borders and misleading wording. Exact duplicates receive identical
translated bytes. Image coverage and literal text coverage remain separate counts.

`data/bgimage/ev_Hdouga.jpg` remains unchanged and outside the payload because it
contains sexual depictions explicitly labeled as minors. Keep this one-image
limitation visible in coverage and release documentation; do not classify it as
translated or claim that all image text has been localized.
