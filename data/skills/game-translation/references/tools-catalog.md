# Tools Catalog

Everything bundled with this skill, by job. All paths are relative to the skill folder: `tools/` sits next to `SKILL.md`. **Copy from these - don't reinvent.** Third-party binaries are not bundled; `tools/THIRD-PARTY.md` says where each one goes.

There are **two** stable homes, not one. `tools/Game Translation/Reference Pipelines/` holds
the finished pipelines ranked below. `tools/Game Translation/Active Projects/` holds code-only snapshots (taken 2026-09-07: scripts, docs, glossaries, prompts; no game data, work trees or builds) of the three
still moving - `Artesia (Bakin)/`, `Dress Quest (RPG Maker VX Ace)/`, `Mineria EroTrapDungeon
(RPG Maker MV)`. The deepest Bakin pipeline is an Active Project and is not in the ranked list,
so read the Bakin section at the bottom of this file before adapting anything Bakin.

## Reusable translation tooling - `tools/Game Translation/`

| Folder | What | Engine |
|---|---|---|
| `GameMaker` | `gmtt.py`: FORM/STRG inspect, full string census, GML decompile, contextual per-use JSON export, control/font validation, longer-string archive patch and verification. Pinned UTMT CLI in `vendor/utmt`; read `README.md` and skill `engine-gamemaker.md`. Tested on Nightfall Princess; YYC code patching is rejected. | GameMaker VM |
| `Unity BepInEx Translation Plugin Template\SheepClickerTL` | **Canonical runtime dictionary plugin** (Plugin/TextPatches/BubblePatches/TranslationStore.cs, hand-rolled JSON, `{0}`-format patterns, compose matching). Copy for any Unity translation mod. | Unity IL2CPP (adapt for Mono) |
| `Unity BepInEx Text Layout Plugin\VBV` | Auto-sizing plugin (TMP/UI.Text shrink-to-fit) when EN overflows JP boxes. | Unity |
| `Unity IL2CPP Text Tools` | `parse_text.py` (TMP/UI YAML), `parse_dialogues.py` (CSV), `parse_messages.py` (serialized arrays), `dump_il2cpp_strings.py` (metadata scan), `find_bubble` (hook-target reflector), `Il2CppStringDump` (LibCpp2IL). | Unity IL2CPP |
| `Unity Text Extraction Pipeline\LoserLife` | Heavyweight: C# parallel `TextExtractor`, `LoserLifeATest` coverage/A-test plugin, runtime harvester, bundle decryption, DazedMTL export. | Unity IL2CPP (encrypted/complex) |
| `Electron Text Tooling` | `goborin_text_tool.py` (extract/inject KAG), `translate_system_images.py` (PIL image text). | TyranoScript/YU-RIS Electron |
| `Text QA and Glossary` | `autofill_glossary.py` (gender/role heuristics), `build_vocab.py` (→DazedMTL vocab), `count_tokens.py` (tiktoken pricing), `dialogue_export.py`/`dialogue_import.py` (`[Speaker]: line` bridge), `analyze_length.py`. | Any |
| `Image Translation` | `imgtl.py` - PIL toolkit for translating text baked into PNGs: probes (alpha/bands/clusters/grid), erasers (clear/fill/patch/tile/rowfill/rowclip), glyph masks + inpainting, sibling-median background rebuild, overlay snapshot-restore, styled text (stroke/glow/gradient-logo/shadow), font map incl. msgothic symbol fallback, plus the hand-lettered overlay kit: erase-by-component on transparent canvases, hand-drawn stamp reuse, `marker_line` angled outlined text with proportional stroke ratios and a drawn censor ring, `text_angle`, `line_gap`, gradient-plate rebuild (`ellipse_from_rows`/`surface_fit`), `composite_mask` to prove an overlay's flattened twin and hand back its free exact mask, `inpaint_pyramid`/`inpaint_large` for holes too big for any single-scale fill (display type destroys 76-90% of its own band), `seal_islands` and `poly_background` for the two things that otherwise leave ghosts, `soft_plate` as a last resort only, and `glyph_strip` to settle an ambiguous kana against the same author's hand elsewhere in the set. Worked graffiti example: `Active Projects/KihoushiScarlet (Wolf)/images/build.py`. Workflow + edge cases: skill `references/image-translation.md`. | Any |
| `Text Fitting` | `layout.py` - engine-agnostic box fitting: 2:1 CJK/Latin cell widths, balanced-line DP with width as a hard constraint, `fit_box` (wrap to W cells x H lines, reports when text cannot fit at any breaking), `restore_indent`, full-width-gap preservation. Pass H and mean it: a wrapping box has two budgets, and a width-only check reports zero overflow while the panel visibly repeats a line, because every line in a row-count failure fits (see the Bakin section at the bottom). `test_layout.py` alongside. `panel_bounds.cjs` plus `test_panel_bounds.cjs` adds RGBA painted-region bounds, axis-aligned transforms, four-side margins and fail-closed native-report replay; read `PAINTED-PANELS.md`. Method: skill `references/text-fitting.md`. | Any |
| `ForumPostGen` (at `tools/ForumPostGen/`) | F95-style BBCode thread builder: GUI + live preview, tag picker, per-game profiles, crash-safe autosave. `new_post.py` starts a post from a blanked session so no field survives from the previous game. Method: skill `references/forum-post.md`. | Any |
| `Reference Pipelines/Bakin (Miyutsure)/tools` | Bakin container tooling, **per-build - re-measure before adapting**: `rbpack.py` (`BKNPAK` header + inner zip), `scramble.py` (both additive code tables), `unpack.py` (pack → plain project), `scan_resources.py` (asset-path harvest from the packed index), `flatten_images.py` (extracted tree → one folder for eyeballing). Measured on the second Bakin game, only `scramble.py` (M=7 launcher, M=13 engine) carried across unchanged: build r64268 writes no `hasLabel` bool, so this reader mis-parses the label's length prefix as the bool, and `scan_resources.py` harvested nothing because its regex is anchored on the reference game's project roots. See `Active Projects/Artesia (Bakin)/tools/` for `rbpack.py` trying both header layouts and letting the DRM MD5 decide, and `index_walk.py` replacing the regex with a self-checking walk. | Bakin |
| `Reference Pipelines/` | **Complete per-engine pipelines** copied out of volatile game folders (see the ranked list at the bottom of this file, and the Bakin section after it for the one that is an Active Project instead). | All engines |

## .NET / Unity - `tools/.NET/` (downloads, except where marked bundled)

| Tool | Entry | Use |
|---|---|---|
| **AssetRipper** | `AssetRipper\AssetRipper.GUI.Free.exe` | Export Unity game → readable project (scenes/prefabs/scripts/assets as YAML). First step for any Unity translation. |
| **Il2CppDumper** | `Il2CppDumper-win-v6.7.46\Il2CppDumper.exe` | Dump IL2CPP → DummyDll + script.json + stringliteral.json. |
| **Il2CppDumper-ManualReg** | bundled source: `dotnet build -c Release Il2CppDumper.sln` | Protected/stripped IL2CPP (WinLicense/Themida) needing manual registration pointers. See `MANUAL_REG_NOTE.md`. |
| **il2dump** | (not bundled) | Memory-dump decrypted `GameAssembly.dll` from a live protected process. |
| **Il2CppLifter** | (not bundled) | Disassemble/lift IL2CPP to pseudo-C/C#, xref DB. |
| **Cpp2IL** | (CLI) | Reverse IL2CPP → managed DLLs. |
| **BepInEx / MelonLoader** | (source repos) | Mod loaders. BepInEx 5 = Mono, BepInEx 6 = IL2CPP. MelonLoader = either. |
| **HarmonyX / Il2CppInterop** | (source) | Runtime patching + IL2CPP↔CoreCLR bridge (plugin deps). |
| **IL2CPP-Trainer-Template** | (not bundled) | Native C++/MinHook trainer skeleton (for native mods, not translation). |
| **dnSpy** | `dnspy\dnSpy.exe` | Inspect/edit **Mono** managed DLLs. Live .NET debug. |
| **de4dot** | `de4dotex\de4dot-x64.exe` | Deobfuscate .NET before analysis. |
| **Detect It Easy** | `die\diec.exe` | Identify engine/packer/protection on an unknown exe. |

## C++ / engine tools - `tools/C++/`

| Folder | Tools | Engine |
|---|---|---|
| `Unreal` | `README.md`, `scripts/`, `python/` bundled. `retoc.exe` (IoStore), `repak.exe` (pak), `UAssetGUI.exe` (JSON) are downloads placed in `retoc/`, `repak/`, `UAssetGUI/` | Unreal 4/5 |
| `FModel` | `FModel.exe` (download) | Unreal asset browser |
| `Wolf` | `wolf_rpg_decode` and `wolf_unpack` (Rust sources plus prebuilt `target/release/*.exe`), `parse_ce.py`/`analyze.py`, `RE/` notes. The IDA `.i64` databases are not bundled | Wolf RPG |
| `Yuris` | `ypf/ystb` extract/repack + patch suite (locale, font, nameplate, inpaint) | YU-RIS |
| `Trois` | `dxa_unpack.py`, `find_text_images.py` (OCR), `script_tl.py`, `patch_*.py` | Trois DXA |
| `Godot` | PCK extract/repack, scene/script patch, vertical-text, save unlock | Godot |
| `RPGM random obf\Namaiki` | RPGM randomized-obfuscation research | RPG Maker (obfuscated) |

## Archive formats - `tools/Game Archives/`

| Folder | Tool | Format |
|---|---|---|
| `RPG Maker MZ` | `decrypt_rpgmz_data.js`, `decrypt_rpgmz_audio.js`, `run_runtime_image_dump.js` | encrypted MZ |
| `KiriKiri XP3` | `unpack_xp3.py` | `.xp3` |
| `Siglus G00-ScenePCK` | `unpack_g00.py`/`pack_g00.py`, `scene_pck.py`, `extract_scene_text.py`, `dazed_scene_text_bridge.py` | Siglus |
| `YU-RIS YPF-YSTB` | `ypf/ystb_extract.py` + `_repack.py` | YU-RIS |
| `RPG Maker RGSSAD` | `rgssad.py` (v1/v2/v3 extract + list), `install-template.ps1`/`.bat` (a PLAYER-facing installer: unpacks the archive with an embedded C# routine, lays the patch over it, moves the archive aside, `-Uninstall` reverses it). **Read its README**: RGSS3 serves `Data\*.rvdata2` from the archive whenever it is present and ignores a loose file beside it, so a patch dropped in next to `Game.rgss3a` does nothing, silently. | `.rgssad` XP, `.rgss2a` VX, `.rgss3a` Ace |
| `Electron ASAR` | `unpack_asar.py` | `.asar` |
| `LiveMaker` | not bundled (a 144 MB per-game working tree built on pylivemaker's `lm*` CLIs) | LiveMaker |

## DazedTL subsystem map - `DAZEDTL_ROOT/`

A curated extract of DazedTL (MIT, upstream `https://git.dazedtl.dev/dazed/DazedTL`, commit 4557680 of 2026-08-22): the engine modules, `util/`, `data/`, `scripts/`, the non-GUI tests and one GUI file. Files are unchanged, so the `path:line` citations below resolve. The GUI, app shell and third-party binaries were dropped; read `EXTRACT.md` there.

Every path verified present. Line counts are a rough guide to how much is in there.
The right-hand column is the skill reference that already distils it, so check that
first and go to the source for detail.

| Path | What it is | Distilled in |
|---|---|---|
| `modules/rpgmakermvmz.py` (6381) | The authority on MV/MZ per-event-code behaviour: `HEADER_MAPPINGS_357` plugin table, `PATTERNS_355655` script regexes, speaker cascades, `FACENAME101_MAP`, the `_original` sidecar | `engine-rpgmaker.md` |
| `modules/rpgmakerplugin.py` (1137) | `js/plugins.js` parameter extraction and structural write-back | `engine-rpgmaker.md` |
| `util/rpgmaker_qa.py` (3145) | Post-translation QA engine, the full check list | `engine-rpgmaker.md` |
| `util/ace/offline/` (binaries not bundled, see `tools/THIRD-PARTY.md`) | `RV2JSON.exe` (`-c` rvdata2→JSON, `-u` back) and `RPGMakerDecrypter-cli.exe` (`.rgss3a`) | `engine-rpgmaker.md` (VX Ace) |
| `util/translation.py` (6058) | The LLM driver: prompt build, chunking, retry classification, resume | `llm-pipeline.md` |
| `util/batch_history.py` (1086) | Batch bookkeeping and resume state | `llm-pipeline.md` |
| `util/evaluation.py` (4127) + `gui/evaluation_tab.py` (3428) | LLM-as-judge quality scoring: rubric, sampling, blinding, Borda ranking | `quality-evaluation.md` |
| `util/version_update/git_workflow.py` (3014) + `gameupdate/` | Carrying a translation onto a new game version, and the in-game update notice | `version-updates.md` |
| `util/reference_games.py` (786) | Reusing a prior translated game as advisory evidence, keyed by logical path | `reference-translations.md` |
| `util/tl_inspector/TLInspector.js` (3142) + `config.py`, `installer.py` | In-game overlay mapping on-screen text back to its source file and offset | `playtest-instrumentation.md` |
| `util/forge/` (`modern_patches.py`, `installer.py`) | The Forge in-game editor overlay and its NW.js game-root resolution | `playtesting-and-release.md` |
| `util/paths.py` (584) | Per-game state dir and the marker-delimited `.gitignore` allowlist block | `playtesting-and-release.md` |
| `util/sfx_reference.py` (279) + `scripts/update_sfx_reference.py` (157) | Onomatopoeia index build, bucketing and longest-variant matching | `sfx-onomatopoeia.md` |
| `data/sfx_reference/j_ono.json` (22671) | The onomatopoeia corpus itself (3,595 variants). Check `SOURCE.md`/`LICENSE.md` before shipping any of it | `sfx-onomatopoeia.md` |
| `util/imagetools/render.py` (999) + `style.py` (1230) | Image text rendering and style derivation | `image-translation.md` |
| `util/wolfdawn/wrap_search.py` (1702) | Wolf text fitting solved by search rather than formula | `engine-wolf.md` |
| `modules/wolfdawn.py` (829), `util/wolfdawn/` | Wolf driver: resume ladder, nameplate pre-resolution, DB sheet tiers | `engine-wolf.md` |
| `modules/srpg.py` (2156) | SRPG Studio, incl. `customParameters` JS literals | `engine-srpg-studio.md` |
| `modules/csv.py` (492) | Translator++ CSV convention and the batch-aligned resume | this file, above |
| `modules/yuris.py` (403) | Whole-file pass-through for asset-path and font-face tables | `SKILL.md` (non-negotiables) |
| `data/skills/*.md` | **Reusable per-game audit prompts**, directly copyable: `risky_codes.md` (which optional event codes hold text), `wrap_config.md` (derive width/faceWidth/rows), `ace_script_translation.md` (Ruby script audit), `wolf_speakers.md` (rule on low-confidence speakers), `rpgmaker_translation_qa.md`, `plugin_translation.md` | throughout |
| `tests/` | Encode the quirks more precisely than the source does. Each case is a real failure someone hit | - |

## Row-based / CSV formats: the resume convention

`DAZEDTL_ROOT/modules/csv.py` handles the Translator++ CSV convention (source column 0, target column 1, optional speaker column where `-1` = none) and solves the resume problem in a way that generalizes to **any** row-based format.

- **"Done" means no source-language characters left, not "the cell is non-empty."** `_target_is_translated` (`:224`) requires the write-target cell to be non-empty AND `re.search(LANGREGEX, target)` to fail. A non-empty target that still contains Japanese is a half-finished or echoed translation, not a finished one.
- **Skip in BATCH-sized groups, not row by row.** `_collect_process_indices` (`:255`) walks the candidate rows in slices of exactly `BATCHSIZE`, the same size the translator uses, skips a slice entirely when every row in it is done, and otherwise keeps the slice but queues only its unfinished rows. Row-by-row filtering re-chunks the work on every resume and destroys the cache prefix.
- **An existing target cell can be the SOURCE.** With `USE_TARGET_IF_NOT_EMPTY`, `_row_source_text` (`:235`) feeds the target cell to the model instead of the source. That is how you post-edit a machine pre-translation. `WRITE_TO_NEXT_COLUMN` shifts the write target one column right so the original is preserved for diffing.
- **Pre-clean before the model sees the row** (`:315-340`): strip a `:name[Speaker]` prefix and its newline, translating the captured name separately and substituting it back, strip `\M` markers and their newline, strip voice markers matching `\\[vfF]+\[.+]`, and remove `＜＝＞` furigana annotations. Optionally skip rows whose first column contains "comment".

## Multi-engine frameworks

| Project | What |
|---|---|
| **`DAZEDTL_ROOT`** | **The deepest RPG Maker knowledge base here. Read it before writing any new extractor.** Live modules, utilities, data and tests of DazedTL, the multi-engine tool for RPG Maker MV/MZ/VX Ace, Wolf, SRPG Studio and CSV. Subsystem map in its own section above. |
| `DazedMTLTool` (older, not bundled) | The predecessor GUI MTL tool (OpenAI/Gemini/Mistral-compatible). Superseded by DazedTL above. |
| `WolfDawn` (not bundled; build the `wolf` CLI from the tag in DazedTL's `util/wolfdawn/bin/PROVENANCE.md`, see `tools/THIRD-PARTY.md`) | Rust Wolf RPG framework: unpack/decompile/extract/inject/repack/save-fix/round-trip verify. |
| `forge-mvmz` (not bundled; DazedTL carries the same overlay under `util/forge/`) | RPG Maker MV/MZ in-game editor overlay (F10) - jump maps, set vars/switches, run events. For reaching untranslated scenes during testing. |

## Support / RE - not bundled, see `tools/THIRD-PARTY.md`

- **Disassemblers:** Ghidra or IDA - exe string extraction, hardcoded-string patching.
- **Debugger:** x64dbg, optionally with x64dbg-mcp - live debugging, Frida-style tracing to verify injected text.
- **LLM local:** llama.cpp (CPU or Vulkan build) - offline models if needed.
- **w64devkit** - GCC toolchain for building the Rust/C tools.

## Reference pipelines - `tools/Game Translation/Reference Pipelines/`

Complete per-engine pipelines (scripts + glossaries + prompts + docs + mod source), copied out of volatile game folders into this stable location. Read the folder's README first, then copy and adapt. **Do NOT reference the original game-folder copies - they get deleted.** This is one of the two stable locations. `Active Projects/` is the other, and the list below does not include it.

1. `SRPG Studio (Belphegor)\` - SRPG Studio. **best wrapping/layout code** in the corpus (`docs\04-wrapping-layout.md`), `srpgtl/`, `loosekit/`, `jstools/`, `typeset_*.py`, `tl/`.
2. `Unreal (FortuneBride)\` - Unreal + Mistral. `scripts/mistral_translate.py`, `scripts/text_json.py`, `tl/`, PowerShell `00-06`. (UE binaries live in `tools/C++/Unreal/`.)
3. `RPG Maker MV (Mineria)\` - RPG Maker **MV** + Claude, batch and live off one request builder. A finished translation (2,866 units, 100%, $1.15 on Sonnet 5, 68 requests, zero errors). **Read `PIPELINE.md` first** - it says what to lift and how this differs from BroodGeneral. `tl.py`, `mvtl/` (17 modules), `tools/`, `tests/`, `docs/CENSUS.md`, `images/title.py`.
Read this for **widths measured from the game's own font** (`measure.py` - the font and `east_asian_width` disagree, and one heart is not in the font at all), **injection that never changes the command count** plus `tools/verify_structure.py` proving it (9,144 command lists, 0 differences, gated into the release build), **`tools/trace_parser.py`** which reads the engine's regexes and delimiters out of the shipped JavaScript at run time rather than copying them, a **number-drift check that does not cry wolf** (61 flags to 5, 4 of them real) with a per-unit `waive` escape hatch, and `qa.py:unify_repeats` (243 same-source conflicts to 20).
4. `RPG Maker MZ (Gakuen)\` - RPG Maker **MZ** + Claude batch. A finished translation (10,665 units, 100%, $3.32 on Sonnet 5, 204 requests, zero errors). **Read `PIPELINE.md` first.** `tl.py`, `mztl/` (18 modules), `tools/`, `tests/`, `audit/`, `images/`, `js_plugins/`.
Read this one for everything that is **not** in `data/*.json`. It is the pipeline with the most TRACKS - plugin parameters, **Japanese hardcoded in plugin SOURCE** (`tools/js_strings.py` a JS tokenizer that tells a literal from the giant `@help` comment, `tools/plugins_src.py` an exact-match key guard over notes/commands/params/**pristine** DB names plus a parse-and-read-the-value-back patcher - three casino minigames shipped 100% Japanese because their plugins draw their whole UI from their own code and nothing else in the pipeline produces a unit for that), a hand-written `js/plugins/*Config.js`, drawn `<LB:>` note tags, `package.json`/`index.html`, and encrypted `img/**` - and it carries the tooling for each: `images/rpgmv_crypt.py` (the `.png_` codec, verified in both directions against the developer's own plaintext `img.zip`), `tools/skilltree_config.py`, `tools/window_title.py`, `tools/install_patch_plugin.py` (a validated structural insert into `plugins.js`), and `js_plugins/GakuenTL_Patch.js` (re-derives display text a save cached from the pre-patch build). Also `audit/label_fit.py` (same-row overlap AND off-map overflow for centred `<LB:>` captions, scored at two font sizes so a change is a comparison, behind `inject._apply_label_offsets` which lays out each map ROW as a 1-D packing problem instead of nudging one label). And: `PICTURE_LAYOUT`/`CBR_LAYOUT` - declared, guarded and *reported* overrides for captions drawn at an absolute x/y whose only bound is the widget to their right - `audit/cbr_fit.py` and `audit/dtext_layout.py` which pair a caption with that neighbour, and `audit/numablate.py`, which ablates each number-drift rule and prints what it fixes against what it causes.
The later `RPG Maker MZ (Gakuen)\MZ-ADAPTATION.md` companion (2026-09-07)
records Tropical Chase tooling-preparation findings: external gallery JSON,
nested parameter scripts, native speakers, script operands and dynamic message
height. Shared `codes.py`/`wrap.py`/`measure.py` now protect complete numbered
portrait codes with a nested variable. `tools/js_literals_acorn.cjs` is a
parse-only JS literal/template extractor with Python-compatible source spans;
its synthetic regression suite needs Python and Node/Acorn, no game corpus or
API. That document preserves the preparation milestone; the completed manual/no-API
case is now `RPG Maker MZ (Tropical Chase)\PIPELINE.md`. Its curated adapter
sources cover 2,340 manual units / 4,002 sites and a 44-image release; game assets,
source corpus and saves are deliberately absent. `tools/verify_reference.py`
and the shared painted-panel tests run without the game. Native evidence records
42/56 old panel failures and 112/112 corrected cases. `tools/mz_health.js`
checks caught engine errors, stopped tickers and frozen frames. Read the input
requirements before running project-specific build/install/fixture scripts.

5. `RPG Maker MVMZ (BroodGeneral)\` - RPG Maker **MZ** + Claude batches. `tl.py`, `batches.py`, `rpgmvtl/`, `translate_save.py`, `tl/`. Take its `helpwrap.py`, `122`-display-variable subset and native `101 parameters[4]` speaker handling - MV has none of those.
6. `Unity Mono (NTR Soccer)\` - Unity Mono. Force-locale + dictionary hook. `scripts/extract_text.py`, `scripts/mistral_translate.py`, `mod/NTRSoccerEnglish/`, full README.
7. `Unity Mono PlayMaker (CoinPussy)\` - Unity Mono + PlayMaker, no localization system and no strings in Assembly-CSharp. `tl.py` (`derive`/`extract`/`dryrun`/`submit`/`fetch`/`live`/`validate`/`reflow`/`shorten`/`package`), `scripts/unitytl/` (`pmparams.py` solves+proves PlayMaker's paramDataType encoding, `csvtext.py`, `layout.py`, tolerant JSON parser in `batch.py`), `mod/CoinPussyEnglish/` (CsvReader.LoadFromString sha1-keyed swap + TMP dictionary hook), `scripts/test_layout.py` + `test_parse.py`. Read this for **FSM text extraction**, **CSV chokepoint delivery**, and **measured box-fitting**.
8. `Unity Utage (Goblin Sword)\` - Unity/Utage + Mistral. `translate_mistral.py`, JSONL resume, `prompt.md` + `glossary.md`.
9. `Wolf RPG (Pachimon)\` - Wolf + Mistral. `translate_mistral.py`, DB/UI vs protected-runtime-key separation, `prompt.md` + `glossary.md`.
10. `Wolf RPG (Asuka)\` - Wolf + Claude (the mature `wolf`-CLI + `mt-export` path). `claude_translate.py` (2-phase batch driver, escape repair), **`relayout.py`** (box-geometry reflow + portrait-aware width + page-splitting - the thing WolfDawn lacks), `scan_all_strings.py`/`fix_ui_strings.py` (symbol sweep), `scripts/examples/` (event-side field-label override, DB-memo translation), `README.md` + **`WOLFDAWN-GAPS.md`**.
Read this for the **font-resolution** (#1 tofu cause) and **relayout** lessons.
11. `TyranoScript (AjinSyoujyo)\` - TyranoScript v5 / Electron.
The only Electron pipeline. `tl.py`, `scripts/tyranotl/` (byte-faithful `.ks` lexer, `(tag,param)` site table, JS-literal scan of `exp=`/`[iscript]`, span-splice injection with a reversibility proof), `patch_src/main.js` (**2 MB loader-shim patch instead of a 745 MB repack**), `scripts/imgwork/` (plate-clip UI image redraw), 38 offline tests.
Read this for **the KAG parser eating spaces inside quoted attributes**, **Electron app-dir precedence**, and **cost calibration against a real bill**.

12. `RPG Maker VX Ace (DressQuest)\` - RPG Maker **VX Ace** (RGSS3) + Claude, batch and live. A finished translation (14,750 units, 100%, 0 residual Japanese, $8.36 on Sonnet 5). **Read `PIPELINE.md` first.** `tl.py`, `acetl/` (18 modules), `tools/`, `tests/` (68), `docs/CENSUS.md`.
Read this for **`rvmarshal.py`** - a Ruby Marshal 4.8 reader/writer that round-trips 231/231 shipped files byte for byte, which is what lets the no-op inject compare BYTES rather than parsed trees (and RV2JSON does not: 28/231 files change on an edit-free round trip, and it silently drops `System.terms.etypes`); the **archive-beats-loose-files** delivery and the installer that follows from it; the **`Scripts.rvdata2` second track** with a two-gate audit (`tools/translate_scripts.py`) that turned 384 literals into 99 shipped UI strings; **custom nametag codes** (`\NAME[...]`) as glossary-owned text split off before the model sees it, including the 79 "silent beat" units extraction would otherwise drop; **calibrating the cell from one clipped screenshot** when the game sets no font size; and a **number check tuned 246 flags to 47** with the taxonomy in `llm-pipeline.md`.

13. `Bakin (Miyutsure)\` - **RPG Developer Bakin** (SmileBoom, namespace `Yukar`). The first Bakin game in the corpus, and no longer the deepest. The engine was reversed from scratch here, but every font, wrap-width and menu-geometry finding was reversed against the SECOND build and lives in `Active Projects/Artesia (Bakin)/ENGINE-CODES.md`, so read the Bakin section at the bottom of this file too. **Read `ENGINE-BAKIN.md` first**, then `BUILD.md`.
`tools/` (`rbpack.py` the `BKNPAK` container, `scramble.py` both code tables, `unpack.py` pack→plain project, `netbin.py` .NET `BinaryReader`/`Writer`, `scan_resources.py` asset-path harvest, `flatten_images.py`, `build_patch.py`), `BakinTL/` (C# harness bound to the game's own `common.dll`: `probe`/`dump`/`audit`/`roundtrip`/`export`/`resources`/`layout`/`effectparams`/`fonts`/`inject` - `layout` is the entry point for the whole widget-geometry track, and the subcommand set differs per build, so dispatch it once before scripting against it), `BakinRes/` (asset read via the engine's `FSEx`), `BakinTLHook/` (the `AppDomainManager` overlay).
Read this for **binding a tool to the game's own assemblies instead of writing a parser** - and the two post-load steps (`Folder.initialize`, `initCommonEventListInfo`) plus `ResourceItem.sAttachResource = false` that take the round trip to **138/138 files byte-identical**, which is what makes a no-op inject a byte comparison; **auditing a built-in localization table before trusting it** (16,950 populated-looking slots, all empty, covering 54% of the game); **non-unique MenuItem guids** (162 collisions) forcing a positional key; **an overlay hook that patches no game binary** (three lines in an `.exe.config`); and **replacing packed art without rebuilding a 3.8 GB pack** by repointing `ResourceItem.path` at a loose scrambled file.

## TyranoScript (added 2026-08)

`Reference Pipelines/TyranoScript (AjinSyoujyo)/` - the fullest Electron/KAG
pipeline on disk. Worth copying whole:

| Path | What |
|---|---|
| `tl.py` | the CLI: unpack / extract / selftest / dryrun / names / submit / status / fetch / validate / retry / polish / fit / inject / deploy |
| `scripts/tyranotl/kslex.py` | byte-faithful `.ks` reader - per-line separators (games mix CRLF and LF *within one project*), tag/attribute scanner with exact spans |
| `scripts/tyranotl/sites.py` | the `(tag, param)` classification table. Unknown JP-bearing sites are excluded *and reported* |
| `scripts/tyranotl/jsstr.py` | JS string-literal scanner with comment masking - finds the UI text hiding in `exp=` and `[iscript]` |
| `scripts/tyranotl/inject.py` | span-splice injection + the reversibility proof, and `inside_kag_attribute()` for the NBSP fix |
| `scripts/tyranotl/widgets.py` | re-measures script-sized plates (`[image width=]` behind a `[ptext]`) against the English and rewrites the width. Relocations live in an explicit `MOVES` table |
| `scripts/mock_hideout.py` | composites a screen from the script's own coordinates - icons, stretched plates, labels in the game font - to check fit without launching |
| `scripts/check_plates.py` | reports any label wider than its plate or past the screen edge |
| `scripts/tyranotl/savetext.py` | extracts the build's copy of table text a save keeps its own version of, into the shipped `save_text.js`.`OWNED` lists display-only fields so a jump target is never rewritten |
| `patch_src/save_compat.js` | the save-migration shim: stamps new saves with (line, ordinal, kind) and re-derives the resume index on load |
| `scripts/test_remap.js` | the proof - parses every scenario before and after, remaps all 24k elements, reports exact / same-line / wrong-line |
| `scripts/tyranotl/rewrap.py` | the layout-repair pass over injected English: orphaned hard breaks, glued junctions, flush lines, word-splitting ruby |
| `scripts/tyranotl/tables.py` | per-`(array, column)` width budgets for text declared in `f.x=[…]` data tables, plus the measured item-list / status-table containers |
| `scripts/tyranotl/deploy.py` | the three delivery modes, incl. An ASAR repack that reads itself back and diffs every entry |
| `patch_src/main.js` | the Electron loader shim |
| `scripts/imgwork/relabel.py` | plate-clip image relabelling (see `image-translation.md`) |
| `scripts/tests/test_pipeline.py` | 38 offline regression tests, no key needed |

Generic pieces to lift for *any* engine: `codes.py` (JP detection that correctly
excludes censor glyphs and slur dakuten, sentinel masking, offline kana
romanisation and fullwidth-punctuation conversion), `pricing.py` (published rates,
four-way cost model, per-script token estimator), `prompts.py` (two cache
breakpoints, scene packing, the JSON-repair parser).

## Bakin, second build - `Active Projects/Artesia (Bakin)/` (added 2026-08)

RPG Developer Bakin **r64268**, "Holy Executor Artesia" Ver1.06. The deepest Bakin
pipeline on disk and the one to copy: 31 scripts in `tools/`, 22 modules in `artl/`,
plus `audit/`, `tests/`, `BakinTL`, `BakinApi`, `BakinRes`, `BakinTLHook`, a 58 KB
`PIPELINE.md` and a 32 KB `ENGINE-CODES.md`. **Read `ENGINE-CODES.md` first** - the
reference pipeline's `ENGINE-BAKIN.md` has none of the work below.

Its `BakinTL` dispatches `probe`/`census`/`attrcensus`/`roundtrip`/`export`/`layout`/
`effectparams`/`resources`/`inject`. No `audit`, no `dump`, no `fonts` - those belong to
the reference build. `layout` is the entry point for everything geometric, and it emits
`usage` and `nodeType` because one usage can have several competing nodes (BattleSkill
had three, SkillSelect two), so check which node is live before editing a screen.

### What the engine actually does

- **Two font faces, and the message body gets the bad one.** `GraphicsCore.refreshFont`
  builds `mFont` (24px) and `mLargeFont` (72px). Layout widgets draw `mLargeFont` at
  `scale.X/3`, so a 72px raster shown small is crisp. The MESSAGE body draws `mFont`
  scaled UP, which is why the player reports blurry dialogue with sharp nameplates and
  why it looks better at a lower resolution. Consequence for every measuring tool: **two
  sizes**, `config.font_size` 22 for message text and `config.layout_font_size` 24 for
  layout widgets.
- **`createFont`'s two branches disagree about their own arguments.** The system-font
  branch calls `newSystemFont(name, (uint)(size*scale))` - the PRODUCT, so
  `createFont(48, 0.5f)` is 24px. The file branch calls `new Font(path, size, scale)`
  and keeps them separate.
- **An empty `GameSettings.gameFont` is the safe fallback, and the Meiryo line is dead
  code.** `setGameFont` sets `useSystemFont = !IsNullOrEmpty(name)`, so an empty name
  sends `createFont` probing `font.ttf`, `<exe>/font.ttf`, `<exe>/lib/sysresource/font.ttf`
  and `<exe>/sysresource/font.ttf` through `FileUtil.Exists`, which resolves INSIDE the
  resource pack. Bakin ships `font.ttf` (M+SmileBoom bold), so that face is guaranteed on
  every player machine. The Meiryo fallback sits after the `!useSystemFont` early return
  and never runs.
- **The wrap width excludes the widget's own scale.** `TextRenderer.InitializeText` takes
  its width from `GetScaledSizeWithoutMyself()` while `textScale` shrinks the glyphs with
  it. So **effective width = `size.X` / scale**, and lowering `scale.X` buys characters
  per line. `tools/fit.py`, `tools/budgets.py` and `config.layout_scale_overrides` all run
  on that model.
- **`MenuItem` carries about 20 Guid fields and the frame is `window`.** Not `image` (a
  sprite), not `subItemBaseBackground`. A dump emitting only `image` reports a visibly
  framed screen as having no art, so `layout`/`resources` output and any mock must carry
  all three.

### Fitting rules no width check can reach

- **A wrapping widget has two budgets, width AND row count.** A width-only check reports
  0 while a panel visibly repeats a line, because every line in a row-count failure fits.
- **Part of the row budget may not be yours.** Every description slot declares
  `maxLineNum = 3` and the author wrote the MP cost INTO the description field behind a
  hard newline, so row 3 was already spoken for. English needing 3 rows pushed the MP line
  to a 4th and the player saw the cost twice.
- **One database record is drawn through several codes** - `\currentitemdes`,
  `\currentskilldes`, `\selectshopitemdes`, `\currentdictionarydes`. Fix and audit only
  one and you ship the same bug to the player twice.
- **A gate written from the same premise as its fix CONFIRMS the bug.** The row-count
  audit and the fix were written together and both assumed one code, so the audit reported
  0 while the screen was unchanged and the identical screenshot arrived a second time. The
  mitigation is structural: derive the slot set out of the layout every run and print it
  (`rowfit_audit.py --slots`), never name a code.
- **The vertical correction is two independent terms**, `want = region_centre - size.Y/2 -
  ink_offset`. The centring term changes the author's layout and needs intent evidence.
  The ink term repairs YOUR font substitution and needs none, so a widget the centring gate
  rightly declines can still need the ink term alone.
- **The ink offset ratio is stable from Light to Medium, not across the whole family.**
  Measured with PIL on descender-free text, `(line_centre - ink_centre)/px` is +0.0547 for
  Yu Gothic Light, Regular and Medium alike and +0.0625 for Bold. A screenshot-measured
  offset therefore survives the Light-to-Medium change untouched, and has to be re-measured
  when the weight crosses into bold or the family changes.
- **The shipped Japanese cannot calibrate the measuring size.** Over 44,056 author-placed
  breaks the "the next word would still have fitted" rate is 99.97% at 16px and 90.52% at
  24px and never bottoms out, because a Japanese author breaks at PHRASE boundaries. Only
  an observed render pins it down.
- **A font substitution is a layout decision with a measurable cost, so match the WEIGHT
  the author asked for.** Yu Gothic Light for the author's 游明朝 Demibold was a visible
  regression no width check sees, because thin stems are what an upscale destroys.
  Pagination over 83,999 units at 670px, units needing more than 3 rows: Light 834 (0.99%),
  Regular 1370, Medium 1365, Bold 1849, bundled M+SmileBoom 2498 (2.97%).
- **Verify a layout nudge without launching the game.** The widget names its plate by
  resource id and the resource table maps that id to a PNG, so composite it yourself.
  Render the plate two ways (uniform squash, and native end-caps) and trust only what both
  models agree on. The mock centres on INK while the engine centres on ADVANCE, so
  horizontal drift seen only in a mock is not real.

### Staleness and artifact rules - these apply to every pipeline

- **The packaging step packages the injected tree, it does not build it.** Editing config,
  running every gate and then packaging shipped the PREVIOUS inject with all gates green,
  because they read the store and the SOURCE tree and never the output.
- **The unpack step is never re-run.** Point the pipeline at a newer game build and it
  ships stale roms that MASK the author's new ones, because the patch is an override and
  not a merge. This is invisible to the gates structurally: `verify_noop` proves
  `out == proj`, which says nothing about whether `proj` still describes the game.
- **So producers stamp what they built from and consumers refuse on a mismatch, fatally.**
  Cheap identity only - size plus mtime, a config hash, the newest mtime. Never a content
  hash of a 1.7 GB archive. `artl/provenance.py` is the implementation and names both
  incidents.
- **Verify the ARTIFACT carries the change, not that the command succeeded.** A scale
  override keyed by widget silently no-opped on every description panel, because those
  widgets draw a bare code, carry no Japanese, were never extracted as units, and the
  injector could not name an owning file. Config said 0.90, the run said OK, the built tree
  said 1.0.

### The tools, one finding each

| Path | The finding it carries |
|---|---|
| `artl/measure.py` | r64268 has **no Font rom resource**. One setting, `GameSettings.gameFont`, holding an INSTALLED font (游明朝 Demibold), so the player's screen depends on their machine. `resolve()` reports whether the face it opened was substituted |
| `tools/calibrate_font.py` | what pixel size reproduces the engine's own text layer. `--fit` gives an upper bound, `--break-after` the lower one, and only the pair brackets it. Carries the 44,056-break proof that the shipped Japanese cannot |
| `tools/fit.py` | validate the SHIPPED Japanese against its own box FIRST. The author's layout is ground truth, so a model that says the original overflows is a broken model, not a broken game |
| `tools/glyph_audit.py` | cmap of the font the game will actually ASK for, diffed against every character the patch ships, plus coverage across the plausible substitutes. U+2661 is used 229,107 times and is in none of them |
| `tools/vcentre_calibrate.py` | the ink offset read off a screenshot. hhea predicts -0.9px, OS/2 win -0.6px, OS/2 typo +0.1px, MEASURED -5.32px. No font metric table predicts what the native `Font.measureString` does |
| `tools/rowfit_audit.py` | the row-count gate, `doubled` against `clipped`, and the `--slots` derivation that stops a gate sharing a premise with its fix |
| `tools/budgets.py` | a budget is not a property of the field. It is the NARROWEST slot that draws the code, and hard only if that slot clips |
| `artl/recentre.py` + `tools/recentre_audit.py` | seven hand-nudged labels landing on the same centre within 1.2px. Requires a GROUP before it moves anything and reports what it declined. `--groups` doubles as a check on `layout_font_size` (5.6px spread at 22px against 1.2px at 24px) |
| `tools/menu_mock.py` | composites the real 192x35 sub-item plate and the `window_02` 9-slice from the engine's own coordinates, and renders the Japanese through the identical code so the before/after pair is honest |
| `artl/wrap.py` | `MessageEntry.wordWrap` transcribed line for line from the decompiled build, `isWord` covering U+00C0..U+07FA included. A "close enough" wrapper predicts the wrong line |
| `artl/balance.py` | why a pre-wrap is safe when the engine only re-breaks lines that EXCEED the box, and why any line holding a control code is excluded |
| `tools/orphan_audit.py`, `tools/rebalance_verify.py` | orphan tails counted through the engine's own wrap, and the proof the repair moved whitespace and nothing else |
| `artl/provenance.py` | the two staleness incidents above, cheap identity rather than hashing, deliberately fatal rather than a warning |
| `tools/census_gate.py` | `scan-output` re-extracts and so shares the extractor's blind spot exactly. The generic rom walk with a REVIEW bucket is what caught the 50 nested `EffectParamSettings.EffectParamList[].Message` battle messages |
| `tools/trap_audit.py` | four English-only failures recovered by decompiling: a comma inside a bracketed code argument, a TAB becoming a visible backslash, the one-argument `\r[ruby]X` eating the next character, `\H[castName]` resolving by name |
| `tools/canary.py` | prove the delivery path end to end while the text is still 100% Japanese, so a blank screen has one possible cause |
| `tools/make_coverage_build.py` | filler as a pure FUNCTION of the source run, so string-variable comparisons still match and the game stays progressable |
| `tools/unresolved_names.py` | whole-package Load-name sweep for adaptation damage that `ast.parse` and a code review both walk past |
| `tools/gender_scan.py` | gendered NOUNS applied to the addressee, which a pronoun-against-speaker check structurally cannot see. A third pass finds a gendered PRONOUN where the Japanese named no referent at all, ranked by source length because 1,944 lines match and 113 are readable |
| `tools/parallel_audit.py` | entries whose sources are identical once the varying index is masked, so `男A`/`男B` group together and a same-source check cannot. Grades divergence as punctuation against wording, and wording is usually a glossary break |
| `tools/dedup_risk.py` | measure the risk surface of deduplicating dialogue instead of assuming the default. 3.6x duplication is most of the bill |
| `tools/index_walk.py` | the self-checking `[path][17-byte record]` walk of the rbpack index that replaced the reference regex |
| `tools/flatten_png.py` | dispatches on magic, for the seven files shipped with a `.png` name over BMP bytes |
| `tools/backslash_audit.py`, `tools/escape_audit.py`, `tools/triage.py`, `tools/code_census.py`, `tools/image_triage.py`, `tools/build_patch.py`, `audit/{numablate,numbuckets,kana_ablate,ordinal_ablate}.py` | the rest of the QA and packaging surface |
