# Petrifying Gaze overflow correction

The previous description wrapped into four body lines. The shared shop panel
allows three below its reward or equipment heading: y=714, line pitch=39,
embedded font line height=38, safe lower edge=830. The earlier six-line quest
allowance was wrong. `../quest_audit.py` retains the overflowing wording as a
negative check and measures all 17 quests plus 231 equipment rank variants.

The primary assistant shortened this one description manually. The build script
appends the corrected text and redirects only `CODE:110:97` in the preceding
English release (`ea0fd75a...`). It re-extracts all 631 translated sites and
checks the other literals, original pool, fonts, images, audio, resource
identities and title credit. No API, gameplay or save edits are involved.

```powershell
python build_followup.py "<preceding English data.win>" build/data.win
python "C:\Users\sw\Desktop\Tools\Game Translation\GameMaker\gmtt.py" decompile build/data.win -o decompiled
python build_canary.py
```

Output paths must be fresh. The canary compiles only the title fixture events
and executes the freshly decompiled, complete shop Draw event, with Petrifying
Gaze selected and a 140G reward. `runtime-1920.png`, `runtime-1366.png` and
`runtime-review.json` record the visual review. The fixture proves this renderer;
it does not exercise quest progression. The canary archive is not distributed.

For rebuilding from the Japanese archive with the current catalog, follow the
parent README; the new quest wording is already included in that pipeline.
