# RPG Maker MZ: completed manual translation and native QA

Measured on Tropical Chase, MZ 1.9.0, 2026-09-07. Stable reference:
`tools/Game Translation/Reference Pipelines/RPG Maker MZ (Tropical Chase)/PIPELINE.md`.
The adapter contains no translation API; game-specific inputs are documented,
not silently assumed available. The offline regression suite needs only Python
and Node; fresh native QA needs the actual game and isolated fixture saves.

## Extraction, authorship and structure

The completed release has 2,340 manually authored units at 4,002 sites and 44
translated images. Follow enabled consumers into external gallery JSON under
`img/system`, nested plugin parameters, JavaScript literals/templates, native
101 speakers and script-assigned display variables. Protect technical keys by
use, not by a global Japanese-string denylist. The Gakuen adaptation reference
retains the detailed extraction census and numbered/nested portrait-code tests.

Keep masked JSONL edits resumable with source hashes and previous/target text
history. Preserve exact 401 command counts by putting line breaks inside
existing string slots; fill spare slots without removing commands and pack
extra lines into existing slots when required. Do not prefix an MZ body with a
speaker already stored in 101 parameters[4]. Four demonstrated source nameplate
errors were exact guarded corrections, not a new general attribution rule.

Independent output walks classify residual Japanese by consumer/path instead
of merely re-running the extractor. Compare command code, indent, order,
list length and non-string data independently. This build preserved all 928
lists / 21,383 commands; an empty inject preserved 106 source files byte-for-byte.
The synthetic suite exercised every selected site and real validator rejection
paths, plus JavaScript reparse and decoded-value readback.

## Native visible bounds replace preparation estimates

| Surface | Measured consumer bound |
|---|---|
| Ordinary message | Outer 808x144; inner 784x120; start X 4; width 780; font 26; line height 36; three rows |
| Explicit tall tutorial | Variable 103 sets height 192; inner 168; four rows use 144 |
| Shop help | Actual row width 460; one extra space made a 455 px line overflow |
| Achievement help | 24 entries, two rows / 72 px, width 776 |

These are per-game values. NRP_MessageWindow's larger contents bitmap did not
change the window's visible inner clip. All 1,939 written dialogue blocks were
measured through the shipped parser/font; this does not mean every branch was
played in-world. Custom list selection also needed scrolling before capture.

## The results-panel regression

The old screenshot showed totals outside a purple body inside a larger image.
The old check used viewport width and falsely passed. The corrected native
collector independently detected body pixels `[185,94,624,525)` on the 816x624
canvas and text ink from TextPicture's rendered bitmap. 42/56 pre-fix cases
failed, including the reported ordinary 580-point result.

Version 1.0.1 changes only `TropicalChaseEnglish.js`: it copies the background
into an owned bitmap, widens only the body to `[88,94,728,525)`, and centers
the text sprite. The title, gradient and alpha are retained; outside-body pixel
delta was 0. Stored picture coordinates and source text remain unchanged.
The sprite owns/disposes its copy without modifying ImageManager's shared asset.

Four profiles (reported, zero, five-digit and seven-digit counters) include
calculated contributions/totals. All 14 tally stages on both result maps passed:
112 cases, minimum side margins 24, top about 28.89, bottom 19 px. Normal and
five-digit cases keep scale 1; exceptional totals use uniform scaling. The
collector's color thresholds, map IDs, slots and delays are fixture-specific.
`Text Fitting/panel_bounds.cjs` generalizes geometry validation, not those IDs.

## Save/load and read history

Preserve interpreter indices and cached lists; migrate only exact known
display fields. Old running events can still display cached Japanese until
completion. Read-history flags are a separate identity: the shipped plugin
supports `org_text`, filled from pristine 401 text before its command101 hook.
Inspect the plugin metadata for map/event/page/index; do not assume standard
map IDs. Native old-save tests preserved flags and recognized previously read
text without rewriting the flag database.

Use native Save/Load handlers for the lifecycle probe. A direct save omitted
`onBeforeSave()` and produced invalid null BGM fixture state. Loading a save
while an old Scene_Map kept updating caused undefined `event.pages` in a sensor
plugin. Leave the old scene before replacing game objects. These were harness
errors, resolved in the harness rather than by changing game rules.

MZ may catch an engine exception, stop rendering and still answer filesystem
IPC. Require an empty Graphics error panel, advancing frames, correct scene/map
and an updated visible consumer. Focus checks and hidden-frame throttling are
separate. Record any isolated QA-only override and remove it on teardown. See
[playtest instrumentation](playtest-instrumentation.md) for the reusable rules.

## Evidence and release scope

The independent New Game route used normal UI/collision-respecting movement
and completed George's defeat ending at 580 points. It did not win the arrest.
A separate forced enemy-HP fixture exercised victory callbacks/credits, not
legitimate combat balance. All-block measurement, targeted fixtures, wording
reviews and a fresh route have distinct coverage limits.

The v1.0.1 payload delta is one plugin among 69 game files. It reuses prior
content/route evidence only for unchanged content and explicitly supersedes the
wrong viewport-only layout signoff. Native corrected panels and Save/Load were
rechecked; original and English restoration matched 716 tracked file hashes.
The 71-entry ZIP was checked against its exact 69-game-file + two-document
allowlist, per-file hashes and CRC. Packaging consumes a verified build; it does
not rebuild one. The curated reference preserves measured observations and
hash provenance without shipping the commercial game or player saves.
