# Unreal Engine (UE4 / UE5)

**Indicators:** `Engine/` folder, `<Game>/Content/Paks/*.pak` (UE4) or `*.utoc` + `*.ucas` + `*.pak` (UE5 IoStore), a `<Game>.exe` + `<Game>/Binaries/`. Rare for indie JP games but happens (e.g. FortuneBride).

**Reference implementation:** `tools/Game Translation/Reference Pipelines/Unreal (FortuneBride)/` - full IoStore→legacy→JSON→translate→repack pipeline (`config.json`, PowerShell scripts `00-06` + `scripts/mistral_translate.py`, `scripts/text_json.py`, `scripts/build_translation_master.py`, `tl/` glossary+prompt, `README.md`/`TRANSLATE_README.md`). The UE binaries (retoc, repak, UAssetGUI, oodle, FModel) are not bundled - download them into `tools/C++/Unreal/` (`retoc/`, `repak/`, `UAssetGUI/`) and `tools/C++/FModel/` as listed in `tools/THIRD-PARTY.md`. Read `tools/C++/Unreal/README.md`.

## Toolchain

| Tool | Path | Job |
|---|---|---|
| **retoc** | `tools/C++/Unreal/retoc/retoc.exe` | UE5 IoStore `.utoc`/`.ucas` ↔ legacy `.pak`. Zen ↔ Legacy asset conversion |
| **repak** | `tools/C++/Unreal/repak/repak.exe` | UE4/5 `.pak` unpack/pack (fast, AES-aware) |
| **UAssetGUI** | `tools/C++/Unreal/UAssetGUI/UAssetGUI.exe` | cooked `.uasset` ↔ JSON (DataTables, widgets, blueprints) |
| **FModel** | `tools/C++/FModel/FModel.exe` | browse/preview assets, find where text lives |

`config.json` pins versions (e.g. VER_UE5_5, retoc 0.1.5, repak 0.2.3, uassetgui 1.1.0) - match the game's UE version.

## Pipeline (FortuneBride's scripts 00 - 06)

1. **Inventory** assets. **bootstrap** tools.
2. **Extract IoStore → legacy pak** (retoc) so assets become editable.
3. **Export JSON** from cooked assets (UAssetGUI / repak): DataTables (`DT_DialogueNodes`), UI widgets, string tables.
4. **Extract strings → CSV** with metadata: `id, json_file, kind (json|raw), json_pointer, raw_offset, encoding (utf16le|utf16le-null|json), source, translation, + segment stitching fields`. Dialogue often lives in a `DT_*` DataTable and inside Kismet bytecode blobs (`RawExport.Data`) - `text_json.py` handles FString spans and Kismet flow-target relocation.
5. **Translate** the CSV/master JSON via Mistral (`mistral_translate.py`. See `llm-pipeline.md`). Markup to preserve: `<Green>…</>`, `<LightGreen>…</>`, `<Red>…</>`, `<img id="…"/>`, `{Placeholder}`, `\n`.
6. **Apply + rebuild** (script 05): write translations into the JSON, rebuild UE packages.
7. **Pack patch** (script 06): repak/retoc into a patch `.pak`/`.utoc`/`.ucas`, install to the game's `Paks/` (loads over the base game - no need to touch originals).

## Byte-span constraint (the Unreal-specific rule)

Strings are injected into **fixed byte spans** (especially Kismet `utf16le-null` bytecode strings - expanding one triggers flow-target relocation).
The bible tells the model to **be concise: EN must fit ~2× the JP character count**.
Trim filler before meaning.
UI labels terse.
Post-process folds smart quotes/dashes/arrows to ASCII (`'`→`'`, `…`→`...`, `—`→`-`, `→`→`->`) so translations stay within ANSI-encodable byte budgets, and unsquashes CamelCase item names (`CursedSpring`→`Cursed Spring`).

Encodings in the CSV: `utf16le` (normal FString, can flex within limits), `utf16le-null` (Kismet bytecode - expansion relocates flow targets, handled by `text_json.py`), `json` (JSON string field). Never translate `/NameMap/` FName identifiers - corrupts the asset.
