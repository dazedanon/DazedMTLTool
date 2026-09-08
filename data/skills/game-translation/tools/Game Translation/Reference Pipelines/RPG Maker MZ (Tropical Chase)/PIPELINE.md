# Tropical Chase: manual RPG Maker MZ reference

Completed manual English translation, followed by the v1.0.1 results-panel fix,
2026-09-07. Read this file before running any example. No API setup or provider
code is needed. This is a curated source/evidence reference, not a game package
or a turnkey translation of an arbitrary MZ game.

## What to use

| Need | File(s) |
|---|---|
| Offline independent geometry gate | `../../Text Fitting/panel_bounds.cjs`, `PAINTED-PANELS.md` |
| Engine caught-error/frame-progress check | `tools/mz_health.js`, `tools/test_mz_health.cjs` |
| Self-contained reference verification | `tools/verify_reference.py --node PATH` |
| Manual extraction, guarded injection, no-op proof | `example/translation_tooling/tl.py`, `selftest.py`, `js_probe.cjs`, `vendor/` |
| Source-hashed local authorship | `example/translation_tooling/manual/work.py` |
| Native result measurements and owned-bitmap repair | `example/translation_tooling/text_translation/results_panel_check.js`, `results_fix_lifecycle.js`, `english_runtime.js` |
| Native window capture, isolated launch and filesystem IPC | `example/translation_tooling/text_translation/capture_window.py`, `launch_runtime.ps1`, `runtime_host.js`, `runtime_request.py` |
| Original read-history and cached-display compatibility | `example/translation_tooling/text_translation/english_runtime.js`, `legacy_check.js`, `save_ui.js` |
| Payload audit, exact restore/install, archive gate | `example/translation_tooling/text_translation/audit_release.py`, `manage_patch.py`, `refresh_release.py`, `finalize_results_fix.py` |
| Image codec, inventory and local lettering recipes | `example/translation_tooling/image_review/`, `image_translation/` |

## Run without the game

```powershell
python -B -X utf8 tools/verify_reference.py --node 'C:\path\to\node.exe'
```

This verifies the curated file hashes, parses Python/JavaScript/PowerShell
sources, runs synthetic pixel/health regressions, and replays the recorded
before/after native panel bounds. It expects 56 old cases with 42 failures and
112 corrected cases with no failures, including both maps and all stage/profile
combinations. It is not a fresh native playtest. Node built-ins suffice; the
project's Acorn extractor has its own separate runtime prerequisite.

## Example inputs and limitations

Copy `example/translation_tooling` into an isolated working game as a starting
adapter; never run installers against this stable reference. The scripts keep
their original relative imports and some game-specific IDs/paths. Set
`project.json.node` to an available Node executable; js_probe requires Acorn
or the tested `--expose-internals` fallback. The original machine-specific Node
path was replaced with `node` only in this reference copy.

The commercial game's `source/` snapshot, font, executable, images, units.json,
editable translation store, build/payload directories and real saves are absent.
The source manifest contains hashes, not those files. Build/install/release
scripts require those inputs, their prior manifests and the exact game layout;
some historical release paths are intentionally v2/v3-specific. They are source
examples to adapt, not commands claimed to work on this asset-free copy.
The image recipes also require decoded originals and local review artifacts;
render_title's input artwork is not bundled. Its historical title image workflow
was separate from the later no-API full-text pass; consult the recorded recipe
and source paths rather than assuming a generated image is present.

The generic health helper is new and covered by simulated-engine tests. The
native fixture scripts are preserved as measured examples, including their
fixed waits and `tqa` helpers. For another game, wait for started scenes and the
actual consumer, then check `GameTranslationMZHealth` frame progress. Native
result checks use save 24, maps 4/14, common events 30/34, picture slots 1/10 and
a calibrated purple pixel predicate. Lifecycle uses hotel save 22 and QA slot
26. They alter fixture variables/transfers in isolated QA saves; they are not
normal route playthroughs. Never use a player's save directory.

`english_runtime.js` is a build template with generated original-read-text,
actor-name and display-value tables; do not install it unexpanded. Its results
repair uses this game's 816x624 canvas and body geometry. Its shared ImageManager
source remains unchanged, and sprite-owned bitmaps are disposed on teardown.
The copied vendor/codes.py header was corrected to distinguish Gakuen's unused
speaker heuristics from Tropical Chase's native speakers; code behavior is intact.

## Findings and honest coverage

2,340 manually authored units / 4,002 sites, 1,939 message blocks, 44 translated
images; 928 lists / 21,383 event commands preserved. Native dialogue width is
780 px (808 outer, 784 inner, start X 4), superseding preparation's 788 estimate.
Three tall tutorial blocks intentionally have four rows; preserve that branch.

The old viewport-only results gate was wrong and is excluded from the reusable
checks. `results_panel_before.json` proves the defect; `results_panel_after.json`
proves painted-panel containment after widening the body and centering text.
The historical before report lacks an engine-error observation; the replay
explicitly permits that absence without claiming health. The after report has it.
All 112 cases pass; reported/zero/five-digit counters retain scale 1, while
exceptional calculated totals scale uniformly. The lifecycle report measured
zero changed pixels outside the body and passed native Save/Load.

Command indices, cached display and read-history identity require separate
checks. Use the shipped plugin's original-text override; preserve custom names
with exact old-value guards. Old cached running events can show Japanese until
they finish. Native save handlers run onBeforeSave; loading while an old map
updates can create undefined-event errors. IPC responsiveness does not prove
engine health. Focus loss and hidden-frame throttling are separate QA issues.

A fresh New Game route completed the actual defeat ending at 580 points; it
did not complete a successful arrest. A separate modified-HP fixture checked
victory callbacks. All-block measurement is not all-branch story review. The
v1.0.1 delta changed one plugin only, explicitly superseded the wrong layout
signoff and retained prior unchanged-content evidence with its original scope.
The 69-game-file payload plus two docs was ZIP/hash checked; restore/reinstall
verified 716 tracked paths. See evidence/session_summary.json for exact counts,
limits and the final archive hash.

## Provenance and exclusions

`REFERENCE_MANIFEST.json` binds every curated file to its installed hash and,
where copied, its original source hash. Deliberately excluded: commercial assets,
corpus, saves, profiles, logs, API credentials, old viewport-only results_check.js
and the superseded release_v2 finalize_qa.py. Existing Gakuen code is attributed
in example/translation_tooling/PROVENANCE.json; shared fixes there are retained.
The original game workspace and installed patch are unchanged by this update.
