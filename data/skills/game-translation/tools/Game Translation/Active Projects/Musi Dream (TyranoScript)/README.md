# musi_dream — manual English translation

The authoritative translation store is complete: **509 units / 574 occurrences**,
covering runtime dialogue, narration, choices, nameplates, and engine/UI text.
The requested image update adds **30 image replacements: 28 manually redrawn
images and two exact duplicates**. Its census visually audited all **517 image
entries / 448 unique images**, including tutorial insets and animated frames.
All translation and lettering were done manually and offline, without APIs,
network translation services, OCR services, API keys, or model clients.

The text and image translation is installed. The installed archive matches the
isolated QA archive, with 50 replacements across 1,005 entries. All 30 replacement
images passed native-size decoding; 14 active scene assets were checked visually
in game, and 16 unused or template assets were reviewed at native size. A fresh
normal playthrough covered all nine scenes and returned to the title. Targeted
checks covered warning indicators, the final caption, browser navigation, menus,
hover states and save/reload. All 442 measured text units fit without overflow.
Not every alternate route was played individually. The new package's restore
test reproduced the exact original archive.

One image,
`data/bgimage/ev_Hdouga.jpg`, is excluded because it contains sexual depictions
explicitly labeled as minors. It remains unchanged and is absent from the patch
payload. Image coverage must always be reported with this limitation.

The durable project is:
`C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\Musi Dream (TyranoScript)`.
The game's `translation` directory is the local scratch copy for building and QA.
Keep the durable project, including its source snapshot and history, independently
of the installed game. `glossary.json`, `game_bible.md`, and `quirks.md` record the
translation decisions.

## Translation records and revisions

`store/*.json` holds the validated English with the exact original source spans.
The manually authored inputs are `manual/ui.json`, `manual/opening_endings.json`,
`manual/middle.json`, and `manual/scene6.json`. `scripts/import_manual.py` combines
these maps into `manual/complete.packet.json` and `manual/complete.reply.json`,
checks complete ID ownership and source identity, and imports through the atomic
validation gate with a history backup. The complete reply is the imported master
translation input.

The 24 packets under the initial `packets/latest.json` export retain their original
blank reply templates. They are historical source/context exports, not the current
translation state. Do not import those blank replies over completed work.

For a deliberate wording revision, update the appropriate manual map, then run
`python scripts/import_manual.py`. Keep the maps, complete reply, and store in
sync: the build injects the store, while the generated legacy-save display helper
also reads the complete packet/reply. Imports reject missing or duplicate IDs,
stale source, altered placeholders, and invalid text before changing records.

## Image records and revisions

`images/README.md` describes the separate image workspace. `images/source` holds
pristine archive images; the four `render_*.py` scripts rebuild reviewed lettering
into `images/output` using the copied `imgtl.py` toolkit. The exact source and
target text, measured regions, masks, fitting choices, and magnified comparisons
remain beside those scripts. `images/PROMPT.md` and `images/image_glossary.json`
extend the main glossary and bible for image-specific wording.

The image title is localized as **BUG DREAM**; `musi_dream` remains the project,
folder and save identifier. `images/runtime_map.md` maps active image paths,
character layers, hover variants, tutorials and browser controls to their scenes.
The census also covers stock templates and unused copies; a filename alone is
not evidence of runtime use.

For image revisions, change the appropriate family's translation records and
rerun its renderer from pristine source. Inspect native-size output and every
changed block at 2–3× before approving the new output hashes. `images/assemble.py`
merges the reviewed manifests, fans out only exact source duplicates, and writes
`images/coverage.json` and `images/manifest.json`. It rejects unreviewed outputs.

## Verify, build, and package

Run these commands from this project directory:

```powershell
python tl.py status
python tl.py selftest
python tl.py validate --complete
python images/render_controls.py
python images/render_ui.py
python images/render_title.py
python images/render_web.py
python images/assemble.py
python scripts/build.py
python scripts/package.py --game-root 'C:\Users\sw\Desktop\Games\musi_dream-win32-x64'
```

`selftest` checks byte-identical no-op injection and negative validator cases.
`validate --complete` requires all translations. Use
`reports/RELEASE_VALIDATION.json` for the final runtime QA record and any remaining
limitations; static validation alone is not a complete playthrough.

`build.py` verifies source spans, injects the English, and applies reviewed
continuation-space and fit adjustments from `manual/build_adjustments.json`.
It preserves English word spaces in the configuration sample, maps backlog
speaker display names without changing internal character IDs, and generates the
legacy-save helper that refreshes cached visible messages, nameplates, and choices.
The generator runs with the game's bundled `musi_dream.exe` in Node mode, located
from the original archive path in `source/manifest.json`; keep that runtime
available when rebuilding. No separate Node installation is required.

The image build additionally checks approved hashes, source identity against
the original archive entry, image dimensions/mode, and preserved archive paths.
Some original `.jpg` paths intentionally contain lossless PNG bytes, allowing
pixels outside the lettering masks to remain exact. `reports/image_decode.json`
records the successful 30/30 live Chromium decode check. The theme preview's
embedded ICC profile is accounted for by an independent LittleCMS conversion to
sRGB, allowing at most one channel-value rounding difference. Native decoding
does not certify scaled scene readability. Do not rename image files or move
clickable regions.

`package.py` runs the build again before packaging. Its allowlist contains
**50 payload files / 56 package files** for the image update, excluding the source
snapshot, translation store, QA fixtures, and developer-only installer material. It produces
`Musi_Dream_English_Patch.zip` and the `release` directory. Player installation and
restoration instructions are in `release_tools/README.md`; the archive format,
build-only mode, and installer regression details are in
`release_tools/INSTALLER_DEVELOPMENT.md`.

## Source identity and integrity

The supported original `resources/app.asar` is **194,588,601 bytes**, with SHA256:

```text
0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524
```

`source/manifest.json` records the original archive location, size, header identity,
and per-file snapshot hashes. Never edit `source/app`, re-extract a patched
installation into it, or treat `tl.py extract` as a game-version upgrade command.
Extraction merges against this preserved source and guards against losing
translated units. Installation preserves the original archive as
`resources/app.asar.original`; the patch installer rejects unknown originals and
independently modified installations.

This game's Electron 24 runtime searches `resources/app.asar` before a loose
`resources/app` directory. Deployment therefore repacks and verifies the archive,
retaining its original startup and preload code. The skill's older Tyrano
reference describes a loose-folder shim for another game/build; it is not this
project's delivery method.

Useful evidence is retained in `reports` and `manual`: extraction/census and
runtime inclusion reports, source-span validation, `build.json`, coverage and
semantic reviews, actual-parser comparisons, fit checks, and live save/load QA.
`PROVENANCE.md` records the reused tooling and game-specific implementation.
