# Loser Life Text Tooling

This workspace is for repeatable text extraction from the local game files.

## Layout

- `TextExtractor/` is the primary C#/.NET parallel scanner. It extracts Japanese text from Unity YAML, scenes, prefabs, MonoBehaviours, the Dialogue System database, shops, NPC talk fields, tutorial UI, and project settings.
- `scripts/extract_japanese_text.py` is the older Python reference extractor. Keep it for readability, but use the C# tool for real runs.
- `scripts/extract_decrypted_bundle_text.py` scans runtime-decrypted Unity bundles dumped by the BepInEx test plugin and merges their typetree strings into the main occurrence CSV.
- `scripts/merge_runtime_harvested_text.py` merges strings learned during live play, especially code-composed skill tips, into the main occurrence CSV.
- `scripts/export_dazed_mtl_text.py` converts the current occurrence CSV into DazedMTLTool text-module inputs plus reinjection manifests.
- `outputs/` is where generated dumps are written.
- `mtl_exports/` is where DazedMTLTool-ready dialogue/general text files are written.
- `scratch/` is reserved for temporary experiments.

## Run

From the game root:

```powershell
.\tooling\run_text_extractor.ps1
```

Outputs:

- `tooling/outputs/japanese_text_dump.txt` is the deduped human-readable dump.
- `tooling/outputs/japanese_text_all_occurrences.csv` keeps every source occurrence with file, line, field, object id, and context.
- `tooling/outputs/japanese_text_all_occurrences.json` is the same occurrence data in structured form.
- `tooling/outputs/japanese_text_summary.txt` gives category and source-file counts.

The scanner uses the newest `AssetRipper_export_*/ExportedProject` by default. To point it at another export:

```powershell
.\tooling\run_text_extractor.ps1 --exported-project "C:\path\to\ExportedProject"
```

Use `--max-degree N` to cap parallel workers if you want to keep the machine more responsive while scanning.

The wrapper keeps .NET's first-run/cache files inside `tooling/scratch` and avoids noisy environment setup messages.

## Runtime-Decrypted Bundles

After launching the game with the A-test plugin, decrypted bundles are written under:

```powershell
BepInEx\plugins\LoserLifeATest\decrypted_bundles
```

Merge their player-facing Japanese typetree strings into the main export:

```powershell
.\tooling\extract_decrypted_bundle_text.ps1
```

This writes `tooling/outputs/decrypted_bundle_text_*` files and updates `tooling/outputs/japanese_text_all_occurrences.csv` for the plugin known-text list and DazedMTL export.

Merge exact strings learned while playing with the A-test plugin:

```powershell
.\tooling\merge_runtime_harvested_text.ps1
```

This writes `tooling/outputs/runtime_harvested_text_*` and adds the live strings to the main occurrence CSV. Run it after a coverage playthrough before rebuilding the plugin known-text list or exporting for translation.

## DazedMTLTool Text Export

Generate line-based text-module input files after running the extractor:

```powershell
powershell -ExecutionPolicy Bypass -File .\tooling\export_dazed_mtl_text.ps1
```

Main outputs:

- `tooling/mtl_exports/dialogue/dialogue_all.txt` contains all dialogue-like text with `[Speaker]: line` context.
- `tooling/mtl_exports/general/general_text_all.txt` contains UI, menus, item text, speaker names, runtime literals, and other non-dialogue text.
- `tooling/mtl_exports/dialogue/*.txt` and `tooling/mtl_exports/general/*.txt` also provide smaller split files for easier translation batches.
- `tooling/mtl_exports/**/_manifest.csv` and `.json` map every exported line back to source file, line, field, original text, all-in-one line, and split-file line for reinjection.

Actual game-string newlines are escaped as `\n` so each source record stays one Dazed text-module line.
