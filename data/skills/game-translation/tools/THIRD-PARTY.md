# Third-party tools

The skill references these tools by a path under `tools/`, but they are not bundled.
Install each one at the location in the table so the paths in `SKILL.md` and `references/` work unchanged.
Reusable source and deliberate tool assets are bundled. Generated per-game inputs and
build output are excluded; see the skill's `README.md` before adapting a reference pipeline.
`python scripts/check_tools.py` reports which of these are present.

## Fetched by a bundled script

| Tool | Location under `tools/` | How to get it |
|---|---|---|
| UndertaleModTool CLI 0.9.2.0 (GPL-3.0) | `Game Translation/GameMaker/vendor/utmt/` | `python "Game Translation/GameMaker/bootstrap.py"`. Pinned version and SHA-256 are in `vendor/manifest.json`. Release: https://github.com/UnderminersTeam/UndertaleModTool |
| retoc, repak, UAssetGUI for the FortuneBride pipeline | `.translation_tooling/tools/` inside the game folder | `01_bootstrap_tools.ps1` in `Game Translation/Reference Pipelines/Unreal (FortuneBride)/`. See its `README.md`. |

## Build from bundled source

| Tool | Location under `tools/` | How to build |
|---|---|---|
| Il2CppDumper-ManualReg (the fork that reads metadata v39 and memory dumps) | `.NET/Il2CppDumper-ManualReg/` | `dotnet build -c Release Il2CppDumper.sln` with the .NET 8 SDK. Output: `Il2CppDumper/bin/Release/net8.0/Il2CppDumper.exe`. Read `MANUAL_REG_NOTE.md`. |
| wolf_rpg_decode, wolf_unpack | `C++/Wolf/wolf_rpg_decode/`, `C++/Wolf/wolf_unpack/` | Prebuilt Windows exes are included under `target/release/`. Rebuild with `cargo build --release` if needed. |
| SheepClickerTL, VBV, LoserLifeATest, TextExtractor, find_bubble, Il2CppStringDump, HitonatsuTL and the other `.csproj` projects | their own folders | `dotnet build` in the project folder. Each `.csproj` references game or BepInEx assemblies by path. Point those references at your own copies. |
| BakinApi, BakinRes, BakinTL and BakinTranslationHook | the Artesia and Miyutsure example folders | Build with the `csc` commands in their `README.md` / `BUILD.md`, using the selected game's assemblies. The supplied source ships; old game-specific executables and DLLs do not. |

## Download and place

| Tool | Location under `tools/` | Source |
|---|---|---|
| AssetRipper | `.NET/AssetRipper/AssetRipper.GUI.Free.exe` | https://github.com/AssetRipper/AssetRipper |
| Il2CppDumper 6.7.46 | `.NET/Il2CppDumper-win-v6.7.46/Il2CppDumper.exe` | https://github.com/Perfare/Il2CppDumper |
| Cpp2IL | `.NET/Cpp2IL/` | https://github.com/SamboyCoding/Cpp2IL |
| BepInEx 5.4.x (Mono) and BepInEx 6 bleeding edge (IL2CPP) | `.NET/BepInEx/` | https://github.com/BepInEx/BepInEx and https://builds.bepinex.dev |
| HarmonyX | `.NET/HarmonyX/` | https://github.com/BepInEx/HarmonyX |
| Il2CppInterop | `.NET/Il2CppInterop/` | https://github.com/BepInEx/Il2CppInterop |
| MelonLoader | `.NET/MelonLoader/` | https://github.com/LavaGang/MelonLoader |
| dnSpy | `.NET/dnspy/dnSpy.exe` | https://github.com/dnSpyEx/dnSpy |
| de4dot | `.NET/de4dotex/de4dot-x64.exe` | https://github.com/de4dot/de4dot |
| Detect It Easy | `.NET/die/diec.exe` | https://github.com/horsicq/Detect-It-Easy |
| ILSpy and `ilspycmd` | `.NET/ILSpy/`, plus `dotnet tool install -g ilspycmd` | https://github.com/icsharpcode/ILSpy |
| retoc | `C++/Unreal/retoc/retoc.exe` | https://github.com/trumank/retoc |
| repak | `C++/Unreal/repak/repak.exe` | https://github.com/trumank/repak |
| UAssetGUI | `C++/Unreal/UAssetGUI/UAssetGUI.exe` | https://github.com/atenfyr/UAssetGUI |
| FModel | `C++/FModel/FModel.exe` | https://github.com/4sval/FModel |
| RV2JSON (rvdata2 to JSON and back) | `DAZEDTL_ROOT/util/ace/offline/RV2JSON.exe` | ships in the DazedTL repository under `util/ace/offline/`: https://git.dazedtl.dev/dazed/DazedTL |
| RPGMakerDecrypter CLI (`.rgssad`, `.rgss2a`, `.rgss3a`) | `DAZEDTL_ROOT/util/ace/offline/RPGMakerDecrypter-cli.exe` | https://github.com/uuksu/RPGMakerDecrypter |
| Unity and BepInEx reference assemblies for VBV (`UnityEngine*.dll`, `Unity.TextMeshPro.dll`, `BepInEx.dll`, `0Harmony.dll`) | `Game Translation/Unity BepInEx Text Layout Plugin/VBV/References/` | copy from the target game's `*_Data/Managed/` and your BepInEx `core/` folder |
| WolfDawn `wolf` CLI | `DAZEDTL_ROOT/util/wolfdawn/bin/windows/wolf.exe` | build from https://gitgud.io/zero64801/wolfdawn at the tag in `PROVENANCE.md` next to it |
| Ghidra | anywhere on PATH | https://github.com/NationalSecurityAgency/ghidra |
| IDA Pro | anywhere | commercial, https://hex-rays.com |
| x64dbg | anywhere | https://x64dbg.com |
| llama.cpp | anywhere | https://github.com/ggml-org/llama.cpp |
| w64devkit | anywhere on PATH | https://github.com/skeeto/w64devkit |
| pylivemaker (`lmar`, `lmlsb`, `lmpatch`, `lmgraph`) for LiveMaker | `pip install pylivemaker` | https://github.com/pmrowla/pylivemaker |

## Referenced but not included

These were private working projects on the author's machine.
The references mention them for context only.

- `il2dump` and `Il2CppLifter`: the author's own Rust tools for protected IL2CPP binaries.
- `IL2CPP-Trainer-Template`: native trainer skeleton, out of scope for translation.
- `DazedMTLTool`: superseded by the live DazedTL application at `DAZEDTL_ROOT`. Upstream: https://github.com/dazedanon/DazedMTLTool
- WolfDawn: use the live DazedTL installation at `DAZEDTL_ROOT/util/wolfdawn/bin/windows/wolf.exe` (or `linux/wolf`). Its pinned source and update instructions are in `DAZEDTL_ROOT/util/wolfdawn/bin/PROVENANCE.md`. Upstream: https://gitgud.io/zero64801/wolfdawn
- `forge-mvmz`: the live DazedTL application carries the same overlay under `util/forge/` (`upstream/Forge_MV.js`, `Forge_MZ.js`).
- The finished mod projects goblin-toybox, ntrmeishi, Sodom and natuiso, and the IDA databases for Wolf RPG.
- The LiveMaker `translation_work/` tree.

## Runtime dependencies

- Python 3.10 or newer for every `.py` tool.
- Pillow for `imgtl.py` and the image scripts, numpy for the KihoushiScarlet overlay builder, fontTools where a reference measures glyphs, tiktoken for `count_tokens.py`, customtkinter for `ForumPostGen`.
- API clients only for the API workflow you choose: `anthropic`, `mistralai`, `openai`, `google-genai`. Each reference pipeline lists its own in `requirements.txt` where it has one.
- `pylocres` for the Unreal locres override helper: install `C++/Unreal/requirements.txt` in the project environment. Its old copied `python/` package installation is excluded from Git.
- Node.js for `panel_bounds.cjs`, `js_literals_acorn.cjs` (needs the `acorn` package) and the RPG Maker MZ decrypt scripts.
- .NET 8 SDK for the C# projects. Rust for rebuilding the Wolf tools.
