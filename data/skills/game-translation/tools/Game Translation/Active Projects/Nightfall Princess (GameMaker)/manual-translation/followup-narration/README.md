# Narration bottom-edge repair

The reported caption is scene 1033 (`CODE:82:947`). Its four lines have a
154-pixel line box (49-pixel embedded font height, 35-pixel line pitch). The
previous screen-space top of 940 placed the bottom at 1094, below the 1080-pixel
canvas. All five four-line narration captions shared this problem.

The builder freshly decompiles the input and replaces only the narration draw
call in the hub, quest, gallery and battle HUD events. It wraps once, measures
the result with `string_height_ext`, and uses the smaller of the original top
and `visible_bottom - 16 - text_height`. The original bounce offset is then
applied. Wording, font, width, line pitch and animation remain intact.

The viewport must be active before its dimensions can bound text. Most rooms
render directly on their 1920x1080 canvas; their unused view can still report
1366x768. The battle rooms enable a 1920x1080 view at world offset (48,48).
`room-geometry.json` records the archive values. The repair uses `room_height`
when views are disabled and the camera bottom when they are enabled.

The final candidate is `build-verified/data.win`; its hash is in
`build-verified/data.narration-report.json`. `verified-decompiled/` is tied to
that hash. `build_canary.py` extracts the real four caption blocks from it,
including the active battle view geometry. The runner measured all 110 captions
into `engine-metrics.csv`; the temporary QA file in the save directory was
collected and removed, and `date.sav` stayed unchanged.

`../narration_audit.py` checks all 440 caption/renderer combinations, the engine
metrics, enabled-view rules and unchanged short-caption positions. The eight
`*-fixed.png` captures measure 19 pixels of bottom ink clearance at 1920x1080
and 14 pixels at 1366x768. Two additional short-caption captures verify their
original placement. These title-only tests exercise rendering, not progression.

The compiler shifted two hall-label instructions; the identical ordered string
sequence within each event supplies an explicit canonical-to-output mapping in
`build-verified/data.site-remap.json`. All 631 translated texts, all other code,
old string pool, textures, fonts, audio and save identity are verified.

```powershell
python build_followup.py "<preceding English data.win>" build-verified/data.win
python "C:\Users\sw\Desktop\Tools\Game Translation\GameMaker\gmtt.py" decompile build-verified/data.win -o verified-decompiled
python build_canary.py --game "<game directory>"
```

Use fresh output directories. For a complete rebuild from the original archive,
follow the parent README and supply the preceding status builder's receipt hash
with `--expected-input-sha256`. QA archives and executables are excluded from the
stable tooling copy and player project.
