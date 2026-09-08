# VN & Misc Engines (KiriKiri, Siglus, YU-RIS, TyranoScript, Trois, Godot, Electron, LiveMaker)

Grouped because each is a smaller, archive-centric pipeline: **unpack archive → extract/translate script text → repack (or loose-file override) → patch UI images + exe strings**. Archive tools live in `tools/Game Archives/` and `tools/C++/`.

## KiriKiri (`*.xp3`)

- **Indicators:** `.xp3` archives, `data.xp3` + `patch.xp3`, KiriKiri2/KAG3 (`*.ks`, `*.tjs`).
- **Tool:** `tools/Game Archives/KiriKiri XP3/unpack_xp3.py`.
- **Flow:** unpack `.xp3` → `.ks` scenario scripts (KAG tags `[...]`) + `.tjs` config. Translate visible text, keep KAG tags. KiriKiri loads a `patch.xp3` / `patch2.xp3` over the base - ship the translation as a patch archive (no need to repack the original). Font may need a CJK→Latin-capable replacement in `Config.tjs`.

## Siglus (`Scene.pck` + `Gameexe.dat` + `SiglusEngine.exe`)

- **Tool:** `tools/Game Archives/Siglus G00-ScenePCK/` (`unpack_g00.py`, `pack_g00.py`, `scene_pck.py`, `decode_scene.py`, `extract_scene_text.py`, `dazed_scene_text_bridge.py`). The reference patch project (Sodom) is not bundled.
- **Flow (binary, most invasive VN):** unpack `Scene.pck` → story/dialogue/choices. Re-encode + repack after translating (line-wrapping recalculated per width). **Also patch:** `Gameexe.dat` (title/config strings), `SiglusEngine.exe` (engine window text + **DRM/error prompts users see**), `Config.exe` (config-tool UI - easy to miss), and `g00/` UI **image** assets (menus/buttons - visual translation). Ship the whole `GameData/` + `Config.exe` over `StartData/`.

## YU-RIS (`*.ypf` archives, `*.ystb` scripts)

- **Tools:** `tools/Game Archives/YU-RIS YPF-YSTB/` (`ypf_extract.py`, `ypf_repack.py`, `ystb_extract.py`, `ystb_repack.py`) and the fuller `tools/C++/Yuris/` (adds locale patch, font/speaker/nameplate fixes, lama inpainting, `patch_settings_exe.py`).
- **Flow:** extract `.ypf` package → `.ystb` scripts → extract/translate/repack. Yuris suite has modular patches for config, UI text, narrative, audio labels, gallery unlock.

## TyranoScript / TyranoBuilder (Electron)

**This engine has its own reference: `engine-tyranoscript.md`. Read it.** The
summary below is only enough to recognise the engine.

- **Indicators:** `resources/app.asar` (or loose `resources/app/`) holding `data/scenario/*.ks` + `tyrano/`, `data/system/Config.tjs`, Chrome/Electron DLLs (`libEGL.dll`, `ffmpeg.dll`, `chrome_*.pak`).
- **Tools:** `tools/Game Archives/Electron ASAR/unpack_asar.py`, and the full pipeline in `Reference Pipelines/TyranoScript (AjinSyoujyo)/`. `tools/Game Translation/Electron Text Tooling/goborin_text_tool.py` is the older, simpler extractor (dialogue as `[Speaker]: line`, KAG tags preserved) - fine for a small game, but it does not see `exp=`/`[iscript]` string literals, which is where a chunk of the UI text lives.
- **Delivery:** Electron checks `resources/app` **before** `app.asar`, so a ~2 MB loose folder with a loader shim beats repacking a 745 MB archive. Do **not** use the built-in `.tpatch` auto-updater on an asar build. Its asar branch races two un-awaited async calls at the archive and then deletes the patch.
- **Gotchas that cost time:** `exp=`/`cond=`/`[iscript]` hold display strings. Labels and jump targets must never be translated. `.ks` line endings are mixed per file. `[ptext]` does not wrap.

## Trois (DXA archive, vertical-text images)

- **Tools:** `tools/C++/Trois/` (`dxa_unpack.py`, `find_text_images.py` with EasyOCR/Tesseract, `script_tl.py`, `tl_translate.py`, `patch_*.py`). The reference patch project (夏とプールとイソギンチャク) is not bundled.
- **Engine quirks (from natuiso, worth knowing for old JP engines generally):**
  - Text is treated as on-screen only if the **first character is non-ASCII** (CJK detection). Bare English narration froze execution → **prefix narration lines with U+3000** (ideographic space), and ship a **custom font where U+3000 has zero width** so the prefix is invisible.
  - Body text color is per-language in `message.pixsettings`. The English slot may be hardcoded black → override to white.
  - Parser requires **CRLF** line endings.
- **Flow:** loose-file override next to a patched launcher (loose files take priority over `pix.bin`/archives). Translate scripts + system images. Build the zero-width-U+3000 font.

## Godot (`*.pck`)

- **Tools:** `tools/C++/Godot/` (PCK extract/repack, scene/script patching, vertical-text extraction, hardcoded sprite-text image replacement, save unlock). Flow: extract `.pck` → translate `.tscn`/`.gd`/resource text → repack, or ship a patched `.pck`.

## LiveMaker / Electron ASAR / others

- **LiveMaker:** `tools/Game Archives/LiveMaker/` (has `translation_work/`) - VN engine archive research.
- **Electron (generic web games):** `tools/Game Archives/Electron ASAR/unpack_asar.py` → JS/HTML/CSS/JSON assets, translate in place, repack asar. NW.js/Electron RPG-Maker-web hybrids exist (translate the `data/*.json` inside the asar as normal RPG Maker).
- **Custom/hardcoded-string engines (e.g. Kaneiki):** last resort - reverse the exe (Ghidra or IDA, and Detect It Easy at `tools/.NET/die` - downloads, see `tools/THIRD-PARTY.md`), patch hardcoded string offsets (same-length-or-shorter, padded) or a loader hook, and rebuild any `.idx`/`.pac` asset archives. See **reverse-engineering** skill.

## General VN rules

- Ship a **patch archive** (`patch.xp3`, extra pak) or **loose files** where the engine supports override precedence - avoids repacking the base and keeps rollback trivial.
- **UI is often baked into images** (logos, buttons, menu sprites) - translate those separately with PIL/inpainting. Text hooks won't touch them.
- **Don't forget the exe/config tool** - engine window text, DRM prompts, and the separate `Config.exe`/`Config.tjs` hold user-facing strings that headless script translation misses.
- Verify **font glyph coverage** (embedded vs system) and **line endings** (CRLF for older parsers) before shipping.
