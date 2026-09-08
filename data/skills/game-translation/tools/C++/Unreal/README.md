# Ikisaw Translation Extraction/Injection Workflow

This workspace is for local translation tooling around the packaged Unreal Engine build. The game uses UE5 IoStore containers in `StoryFramework/Content/Paks`:

- `StoryFramework-Windows.utoc`
- `StoryFramework-Windows.ucas`
- `StoryFramework-Windows.pak`
- `global.utoc`
- `global.ucas`

The project manifest does not list project-level `.locres` files. The likely text-bearing assets are cooked DataTables, UI widgets, gameplay blueprints, LevelSequences, and some `.umap` level assets, so the workflow converts IoStore assets to legacy editable packages, exports candidate assets to UAssetGUI JSON, extracts strings to CSV, applies translated strings back to JSON, rebuilds changed assets, then creates a patch container.

Keep patches local unless you have permission to redistribute modified game content.

Current verified extraction:

- 370 candidate assets exported to JSON.
- 2673 cleaned translatable string segments extracted to `translations.csv`.
- 134 strings came from normal JSON fields such as name maps/UI strings.
- 2539 strings came from raw serialized DataTable/widget/blueprint/map blobs or Kismet bytecode constants.
- 1311 dialogue/narration lines exported to `plain.txt`.
- 1362 UI/other lines exported to `ui.txt`.
- English-only strings are intentionally skipped; mixed Japanese/ASCII strings such as `必要EXP:0` are kept.
- The noisy first-pass scan was saved as `translations_unfiltered_backup.csv`.
- `translations.csv` currently has one filled translation.

## Toolchain

For `scripts/make_locres_override.py`, install the pinned Python dependency in
the environment used for this project:

```bash
python -m pip install -r requirements.txt
```

The imported `python/` directory was an installed copy of PyPI packages, not
maintained tool source, and is excluded from DazedTL's Git archives. The other
extraction scripts use Python's standard library.

The bootstrap script downloads these tools into `.translation_tooling/tools`:

- `retoc` for UE IoStore to/from legacy conversion.
- `repak` for packing/unpacking legacy `.pak` files.
- `UAssetGUI` for JSON export/import of cooked assets.

References:

- https://github.com/trumank/retoc
- https://github.com/trumank/repak
- https://github.com/atenfyr/UAssetGUI

## Commands

Run these from the game root in PowerShell. If Windows blocks direct script execution, use the `powershell -ExecutionPolicy Bypass -File ...` form shown here.

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\00_inventory.ps1
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\01_bootstrap_tools.ps1
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\02_extract_legacy.ps1
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\03_export_json.ps1
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\04_extract_text.ps1
```

Translate the `translation` column in:

```text
.translation_tooling/work/translations.csv
```

For a readable dialogue/narration pass, use:

```text
.translation_tooling/work/plain.txt
```

For UI labels and other non-dialogue text, use:

```text
.translation_tooling/work/ui.txt
```

Both plain text files are reference-only and are not consumed by the rebuild step. `plain.txt` uses inferred speaker names from asset paths and narration cues. Multiline game strings are split into separate visible lines here instead of using a `/` separator:

```text
[CharacterName]: Dialogue
[Narration]: Dialogue
```

`ui.txt` is one source string per line:

```text
Text
Text
Text
```

CSV columns:

- `kind`: `json` for normal JSON strings, `raw` for strings inside base64 `RawExport.Data` blobs.
- `json_file`: exported asset JSON that owns the string.
- `json_pointer`: JSON pointer to the editable field or raw data blob.
- `raw_offset`: byte offset inside the raw blob for `kind=raw`.
- `encoding`: original string encoding used for injection (`utf16le`, `utf16le-null`, or `json`).
- `source`: original Japanese text.
- `translation`: fill this column only.
- `group_id`, `segment_index`, `segment_count`, `segment_prefix`, `segment_separator`: metadata used to stitch split multiline segments back into the original game string during injection.

Save the CSV as UTF-8/UTF-8 with BOM. Leave metadata columns unchanged. For split rows, translate each segment independently; the apply step rejoins them with the original hidden prefix/separator text.

Then rebuild and pack:

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\05_apply_text_and_rebuild.ps1
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\06_pack_patch.ps1
```

To copy the generated patch into the game `Paks` folder after it builds:

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\06_pack_patch.ps1 -Install
```

For quick live tests, set one row and rebuild/install in one command:

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\07_set_translation.ps1 -Id "733f239ef387f1ab" -Translation "Where am I...?" -Install
```

Longer translations are supported for normal Unreal strings and for Kismet bytecode strings. For `utf16le-null` Kismet bytecode strings, the default path writes the full translated literal. When an ASCII translation fits in the original payload span, it is stored as an ANSI `EX_StringConst` (`0x1F`) padded before the NUL terminator so the bytecode layout does not move. When it does not fit, the injector preserves `EX_UnicodeStringConst` (`0x34`) where needed and resizes the surrounding script bytecode with structural flow-target fixups.

Non-bytecode `utf16le` strings inside opaque `RawExport.Data` blobs are handled differently. These assets can contain unparsed serialized structs/DataAssets, so moving later fields is unsafe unless the surrounding format is understood. The injector now keeps those FString spans fixed: ASCII translations are stored as ANSI FStrings padded to the original byte span when they fit, and overlong translations are skipped with a `skipped fixed-span raw string` warning instead of shifting the raw blob. This keeps assets like `Blueprint/DataAsset/Lobby/Mary_FirstContact` at the same byte size while still translating short lines such as `...Where is this?`.

The rebuild command enables Kismet bytecode resizing by default:

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\05_apply_text_and_rebuild.ps1
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\06_pack_patch.ps1 -Install
```

When a bytecode string changes size, the apply step attempts to adjust:

- serialized script bytecode length fields;
- structurally identified Kismet absolute flow targets such as `EX_Jump`, `EX_JumpIfNot`, `EX_Skip`, and `EX_PushExecutionFlow`;
- wrapper event entrypoints that call `ExecuteUbergraph_*`.

The rebuild log should print lines like `adjusted bytecode icode length`, `adjusted bytecode disk length`, `adjusted bytecode jump target`, and `adjusted bytecode event entrypoint` for resized bytecode captions. If a resized bytecode literal cannot be matched to a structurally parseable script, that raw export is left unedited and logged as `skipped unsafe bytecode resize` instead of being patched by byte-pattern guessing.

Do not blindly rewrite the int32 immediately before a detected bytecode length. It is only treated as an iCode length when known absolute Kismet flow targets fit inside it. In `LVS_NormalEnd_Skit_Skit01`, that nearby value is `256`, but the function has jump targets around `1702`, so changing it caused a bad export index crash while loading the director blueprint. In `WBP_PoseGet`, the nearby value is `438` and the largest known jump target is `435`, so it is a real iCode length and must move with the resized string.

Kismet flow-target relocation is structural, not byte-pattern based. The walker identifies jump operands by opcode layout and fails closed on unsupported bytecode instead of rewriting coincidental `0x06`/`0x07` bytes inside package indexes, names, property references, constants, or UTF-16 text. Candidate bytecode spans must also parse through the declared script length; an early `EX_EndOfScript` with nonzero trailing bytes is rejected so nested length-like integers are not resized by mistake. A candidate must also recognize every resized string at the exact `EX_StringConst`/`EX_UnicodeStringConst` payload offset recorded during extraction, so a plausible-looking script span is not accepted unless it structurally owns the edited literals.

Wrapper event entrypoint relocation is structural too. Event stubs are parsed as tiny Kismet scripts and only `EX_FinalFunction`/`EX_LocalFinalFunction` or virtual calls that actually target the resized `ExecuteUbergraph_*` have their first `EX_IntConst` entrypoint moved. Do not reintroduce byte-by-byte scanning or per-asset blocklists for these passes; unsupported scripts should be skipped rather than guessed.

Keep `translations.csv` as the full desired translation memory. The injector no longer destructively compacts, truncates, or replaces bytecode translations with short fallback text. Fixed-span skipping for non-bytecode raw FString data is a safety guard, not a translation-memory change. Historical fixed-span audit files are kept only as debugging references:

```text
.translation_tooling/work/bulk_fixed_span_shorten_report.csv
```

The final all-overflow shortening audit is:

```text
.translation_tooling/work/all_fixed_span_shorten_report.csv
```

The current overflow audit is:

```text
.translation_tooling/work/utf16le_ansi_overflow.csv
```

An experimental locres helper exists for testing whether a cooked build loads patch-provided localization resources. In this build, locres did not override the LevelSequence caption, so treat this as an investigation tool rather than the default long-text path:

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\07_set_translation.ps1 -Id "733f239ef387f1ab" -Translation "Where...?" -Rebuild
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\08_add_locres_override.ps1 -Id "733f239ef387f1ab" -RuntimeSource "Where...?" -Translation "Where am I...?" -Install
```

The optional UE4SS runtime hook scaffold remains available for research/fallback only:

```text
.translation_tooling/runtime_hook
```

This game reports UE 5.5 to UE4SS. The stable UE4SS `v3.0.1` build timed out while scanning `GUObjectArray` and `FText::FText(FString&&)`, so the installer defaults to `experimental-latest` and uses its nested `ue4ss` layout. `dwmapi.dll` is placed next to the game exe; `UE4SS.dll`, settings, and `Mods` live under `StoryFramework/Binaries/Win64/ue4ss`.

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\10_install_ue4ss.ps1
```

## AES Keys

If `retoc` reports encrypted containers, rerun the relevant command with an AES key you are authorized to use:

```powershell
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\02_extract_legacy.ps1 -AesKey "0x..."
powershell -ExecutionPolicy Bypass -File .\.translation_tooling\scripts\06_pack_patch.ps1 -AesKey "0x..."
```

## Oodle DLL

This game's main container reports `compression_methods: [Oodle]`. `retoc` and `repak` need an Oodle runtime DLL to decompress those blocks. The game folder here does not ship one, and the machine scan did not find one.

This workspace already has `oo2core_9_win64.dll` placed locally and copied beside `retoc.exe` and `repak.exe`. For a fresh setup, copy a legally sourced `oo2core_9_win64.dll` or `oo2core_5_win64.dll` into:

```text
.translation_tooling/tools/oodle/
```

A common source is `Engine/Binaries/ThirdParty/Oodle/Win64` from a matching Unreal Engine install, or the `Binaries/Win64` folder of another game you own that ships Oodle. Avoid putting this DLL into `System32`; keep it local to the tooling folder.

If `retoc` still reports `InitializationFailed`, also copy the DLL beside:

```text
.translation_tooling/tools/retoc/retoc.exe
.translation_tooling/tools/repak/repak.exe
```

## Version Overrides

The config defaults to `VER_UE5_5` for UAssetGUI and `UE5_5` for retoc because the shipped assets look like a 2025 UE5 build. If `retoc` detects a different package version or UAssetGUI fails to preserve binary equality, edit `.translation_tooling/config.json` and rerun from JSON export onward.

Common values to try:

```text
VER_UE5_4 / UE5_4
VER_UE5_5 / UE5_5
```

## Output Layout

- `work/candidate-assets.txt`: target cooked assets from the manifest.
- `work/legacy_all.pak`: IoStore converted to legacy.
- `work/legacy_unpacked`: unpacked legacy files.
- `work/json`: UAssetGUI JSON exports.
- `work/translations.csv`: translator-facing file.
- `work/plain.txt`: dialogue/narration reference export.
- `work/ui.txt`: UI/other reference export.
- `work/translations_unfiltered_backup.csv`: original broad scan kept for comparison.
- `work/patch_legacy`: rebuilt changed assets only.
- `dist/Ikisaw_Translation_P.*`: patch container files.

## Notes

`retoc to-legacy` is run with `--no-parallel` for this build because parallel Oodle initialization failed on this machine. The slower single-threaded conversion completed cleanly.

The final packaging step was smoke-tested with one temporary string replacement and successfully produced `.pak`, `.utoc`, and `.ucas` patch files. The temporary test files were removed afterward.
