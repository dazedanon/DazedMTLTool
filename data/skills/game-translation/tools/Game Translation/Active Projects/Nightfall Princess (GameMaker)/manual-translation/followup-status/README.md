# Stats spacing and Virginity Lost popup

The follow-up applies to the credited English archive whose SHA256 is recorded
as `BASE` in `build_followup.py`. Run that builder after the root README's
translation, layout, image and title stages. It writes a separate archive and
refuses an existing output or an input that differs from the expected hash.
For a full rebuild after manual catalog edits, pass `--expected-input-sha256`
using the preceding title stage's receipt, as shown in the parent README.
The builder also verifies all current catalog translations before editing.

Only `obj_state`'s Draw event and the `spr_p` lettering change. Long partner
names use the existing blank space above and below the last row to form a
two-line field. Short values remain on one line; font size, panel art, counters
and save state are unchanged. `status-audit.json` covers 60 enemy-name entries
and Virgin: 61 cases, 56 distinct names, 13 stacked variants, no collisions.
The root `layout_audit.py` also runs this check.

The popup says **Virginity Lost**. Its 317x81 transparent canvas, origin and
atlas coordinates are unchanged; the fill and outline colors come from the
original pixels. `popup-translation.json` records the lettering. The builder
compares the decoded atlas outside the popup rectangle and re-exports its sprite.
`finalize_release.py` additionally compared all 25 translated sprites with their
reviewed PNGs before promoting this build; it is a guarded, one-time release
promotion step, not required to build an output archive.

`build_canary.py` uses `build/data.win` and the matching `final-decompiled/`
export (SHA checked) to exercise the actual stats Draw event and popup in a
title-only fixture. It removes the stats Create event's gameplay pause side
effect only from the fixture. It does not edit the player's save. The retained
GML files let the test be rebuilt; the test exe/archive are not distributed.

`runtime-1920.png` and `runtime-1366.png` show the short value, reported collision,
longest name, and popup. `runtime-review.json` records that visual review and
unchanged save. `drop-in-title.png` shows the updated project payload after
loading normally. These checks verify the affected rendering and package startup;
they are not a new full playthrough.
