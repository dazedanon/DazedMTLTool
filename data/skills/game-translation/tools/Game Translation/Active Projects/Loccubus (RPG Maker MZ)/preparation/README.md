# Loccubus offline translation preparation

This project prepares 137 nonsexual general UI units at 158 sites, with blank targets, a glossary, game prompts, and reproducible offline validation.
The source is Simplified Chinese in RPG Maker MZ 1.9.0.
No translation API is configured or used.
Sexual content involving minors is excluded; this is not full-game translation readiness.

## Start here

Read `CENSUS.md`, `game_prompt.md`, `glossary.json`, and `VALIDATION_PLAN.md`.
The glossary contains two character identity rows and 68 initial display-term decisions.
Reich is explicitly marked as a provisional spelling.
Targets in `units.json` remain empty until permitted text is authored locally.

Run these commands from the game folder:

```bash
python -B translation_tooling/tl.py check
python -B translation_tooling/tl.py verify-game
python -B translation_tooling/selftest.py
python -B translation_tooling/layout_audit.py
```

Python and Node are used locally.
The layout inventory additionally uses the already-installed `fontTools` package.
No launcher installs packages or requests credentials.
The bundled JavaScript helper uses an available Acorn package or Node's exposed internal Acorn fallback.

## Local authoring

`batches/general_ui_001.json` is a prepared first batch with instructions, glossary, source hashes, and masked text.
To create another batch, use a fresh output filename:

```bash
python -B translation_tooling/tl.py export-batch --output translation_tooling/batches/general_ui_002.json --limit 30
```

Write permitted edits as JSONL records containing `id`, `source_hash`, and `target`.
Use the IDs and source hashes supplied in the batch.
The import validates the entire edit set before updating targets and records previous/target history.

```bash
python -B translation_tooling/tl.py import-edits translation_tooling/edits/general_ui_001.jsonl
python -B translation_tooling/tl.py check
python -B translation_tooling/tl.py build --output translation_tooling/builds/general_ui_review_001
```

The staged subset is for inspection and testing.
It is not a drop-in game or a release patch.
English remains unregistered because the game's English story routes are unfinished and excluded from this preparation.
No command installs a build, starts the game, edits saves, or changes the selected locale.

## Source preservation

`source_snapshot.zip` is the authoritative immutable baseline for the 17 selected source/reference files.
The tools unpack it to a temporary directory outside the game and verify every file hash before use.
`manifest.json` also fingerprints the 131 current game text/runtime/font files so later drift is detected.
This excludes binaries, audio, images, and saves from the baseline's whole-game integrity claim.
`source/` is the historical pre-archive snapshot and is no longer read while the archive exists.
Concurrent DazedTL initialization formatted JSON and appended `TranslationUpdateCheck`; `reports/external_changes.json` records the verified transition without reverting it.
All reviewed source sites remained unchanged.
Do not manually replace the archive or bypass a fingerprint failure.
If the game changes, preserve the project and its history before adapting to the new version.

## Evidence

`reports/preflight.json` records byte-exact empty output, synthetic injection of all selected sites, real validator rejection cases, repeat extraction, and isolated tests of the shipped localization functions.
`reports/layout_source.json` records source font advances and their limits.
`reports/plugin_inventory.json` records parsed source literal counts and locations without classifying every literal as player-facing.
`reports/content_exclusions.json` records exclusions by location without reproducing the scenes.
No gameplay, visual English fit, image, or save/load signoff follows from these preparation checks.

## Stable copy

The stable project location is recorded in `project.json.stable_backup` under Len TL Tools.
`PROVENANCE.json` identifies the reused Tropical Chase and Gakuen helpers.
Keep authored changes and source archives in that stable location as work progresses, since the working game folder may be removed.
