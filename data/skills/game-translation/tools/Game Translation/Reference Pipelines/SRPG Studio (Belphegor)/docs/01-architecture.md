# Architecture & overview — how full-loose translation works

This page explains the *shape* of the full-loose translation before any tool is run: what the published game is, what files the patched engine prefers at launch, and why this approach lets a translator edit plain files and just relaunch. Every claim below is grounded in the patched exe builder (`FullLooseKit/tools/loosekit/patch_exe.py`), the folder builder (`FullLooseKit/tools/loosekit/make_folder.py`), the memory notes (`engine-resource-loading.md`, `exe-patches.md`, `translation-folder.md`), and the live game directory `C:\Users\sw\Desktop\Games\Belphegor\`.

## The published game IS the SRPG Studio engine

`game.exe` (NOT `runtime.rts`) is the full SRPG Studio engine, imagebase `0x400000`. At launch it memory-maps **one** archive, `data.dts` (~570 MB here), and reads essentially everything out of it:

- **Database / all text** — every unit name, item/skill name+description, dialogue line, event text. This is the *ProjectSection* (the original `project.dat`) packed at the tail of `data.dts`. The container loader is `sub_4465B0` (checks the `SDTS` magic + version); each database string is decoded through one function, `sub_474100(ecx=cursor, edx=&out)`, with ~180 callers across the parsers.
- **Code** — the game's `Script\` and `Plugin\` `.js` are stored *inside* `data.dts` and parsed via `IActiveScriptParse::ParseScriptText`; last-parsed wins in the global JS namespace.
- **Graphics / Audio / UI** — resolved per-type. SRPG Studio already has a loose-file mechanism for these (`sub_474350` builds `<base>\Graphics|Audio|UI\<category>\<name>.<ext>`), but it is gated behind project "externalize this resource type" flags and the editor-mode switch `dword_4E1BB4`; in the published build most types read from the mapped `data.dts`.
- **Font** — the game's text font (M+ 2m) is **embedded** in the database as in-memory font bytes (`sub_402170` builds an array of `{ptr,len}` that DirectWrite reads from). Because it's embedded, the stock engine ignores any loose `Fonts\` file for it.

So stock SRPG Studio gives you loose override for art/audio/UI, but **not** for the two things a translation needs most — the database text and the embedded font — and its script-loose path is editor-only and destructive (all-or-nothing, MessageBoxes if no loose `Script\`). The full-loose patch closes exactly those gaps.

## What "full loose" means

`game.exe.full` is the stock v1.23 exe binary-patched so that **each subsystem prefers a loose file on disk over the copy in `data.dts`**, and `data.dts` is left **byte-for-byte the original Japanese**. The translation lives entirely in loose files next to the exe. There is **no repack, no recompile, no `translation.bin`** — a translator edits a plain text/JSON file, relaunches, and the change shows. The whole patched exe is built in one pass:

```
python FullLooseKit/tools/loosekit/patch_exe.py game.exe.orig.bak -o game.exe
```

`patch_exe.py` refuses anything but the known stock exe (SHA `afd79d5b…`, `STOCK_SHA` in the script), verifies every patch site's original bytes via `expect()` before writing, and needs `probe.bin` + `load_table.bin` + `apply_fontsize.bin` + `apply_title.bin` beside it. The resulting build is `game.exe.full` (Patches `P1+2+3+5b+6+7+8`, SHA `88a13f3a…`) and IS the shipped `game.exe`.

## Exactly what ships and where each piece overrides

Five loose override channels, all layered on top of the **unchanged JP `data.dts`**:

| # | What | Loose location (next to game.exe) | Patch | Engine hook |
|---|------|-----------------------------------|-------|-------------|
| 1 | Database text (names/descs/dialogue/events) | `Project\` JSON tree | **P5b** | db-string reader return at `0x474167` → probe in `.mtl` |
| 2 | Database `fontSize` (the one non-string field) | `Project\fonts.json` | **P8** | font-system init at `0x40218C` → fontSize cave in `.mtl` |
| 3 | Game font | `Fonts\M+ 2m.ttf` | **P6** | font-table store at `0x40227A` → font cave |
| 4 | Code | `Script\` + `Plugin\` `*.js` | **P2** | script loop branch at `0x456223` → replace-loader cave |
| 5 | Art | `Graphics\*.srk` | (stock SRPG loose path) | per-type resolver `sub_464BF0` |

Plus **P1** (never force-quit on a momentarily-missing resource; flag forced to 0 at file `0x38D86`/VA `0x439986`) for robustness, and **P7** (OS window title, read live from `Project\titles.json` → `windowTitle`, falling back to the engine's own caption). P1 isn't a translation channel; P7 effectively makes the window caption a sixth loose field (it's just resolved at window-creation rather than DB-parse time). (**P3**, a loose-`project.dat` loader, stays in the exe but is dormant — the loose build ships no `project.dat`; everything in the database is now live from `Project\` via P5b + P8.)

### 1. Database text — the loose `Project\` tree (Patch 5b)

This is the heart of the kit. `Project\` **is the native SRPG `project.dat` JSON tree** — exactly what `SRPG_Unpacker -c` produces (`items.json`, `Maps\map_000.json`, `Base\…`, `Extra\…`; ~250 `.json` files in the live folder) — **except every translatable Japanese string is wrapped** as `{"jp": "<original>", "en": "<translation>"}`. Confirmed in `Project\items.json`:

```json
"name": {"jp": "ベルフェゴール", "en": "Belphegor"},
"desc": {"jp": "王家の証　１ステージに１度だけＨＰ１で耐える", "en": "Royal Proof — Survive once per stage with 1 HP"},
```

At launch the P5b cave (a PIC asm stub at VA `0x558300` plus the compiled C blob from `load_table.bin`) walks `<gamedir>\Project` and its subfolders (via an explicit dir-stack, not recursion), reads every `*.json`, scans each for `"jp": "..."` then the following `"en": "..."`, UTF-8→UTF-16 converts, and builds an in-memory FNV-1a jp→en hash table (first-win on duplicate `jp`). Then the probe (`probe.bin`, hooked at the success return of `sub_474100`, file `0x73567`/VA `0x474167`) runs on **every** database string the engine reads: it hashes the JP blob, probes the table, and on a hit returns an English buffer instead. Because the swap happens at the **data layer** (parse time), all downstream wrapping/composition is correct — there are no display-hook limitations.

Key behaviors a translator must know:
- **Blank `en` (or a string not in the folder) passes through to the original `data.dts` Japanese.** A fresh folder shows pure JP and fills in as you translate. (In `load_table`, `ne==0` sets `g_table=-1` = full passthrough.)
- The base directory is taken from the engine at runtime (`[dword_4E1AF4]+0x8E8`), rootname `"Project"` — so the folder must sit next to `game.exe`.
- `speaker` / `comment` / `fontName` fields are **left as plain strings**, not wrapped — speaker names translate through the unit-name entries, so the speaker text doesn't need its own wrap.

The folder is generated by `FullLooseKit/tools/loosekit/make_folder.py`, which unpacks `project.dat` and wraps every Japanese string (its `JPAT` regex detects CJK; `SKIP = {speaker, comment, fontName}`). As shipped it computes `ROOT = HERE\..\..` = the `FullLooseKit` folder, so `--out` defaults to `FullLooseKit\Project` and `--project` defaults to `FullLooseKit\tooling\_jpbase\project.dat` (which does not exist in the kit) — a bare command does **not** drop `Project\` at a game root, so pass explicit paths (e.g. `--project <game>\tooling\_jpbase\project.dat --out <game>\Project --store <game>\tooling\tl`). Fill the EN side with `--store`, which runs the `srpgtl` `inject` pass so dialogue/info text gets the same width-fill reflow, page-align and glossary names as the old data.dts build (no orphan tail-words).

### 2. Font — loose `Fonts\M+ 2m.ttf` (Patch 6)

The stock engine stores M+ 2m as embedded bytes, so it never consults `Fonts\` for it. P6 hooks the embedded-store path at `0x40227A`, builds `<base>\Fonts\<name>.ttf` (name read at `node+0x10`), and calls the engine's own loose reader `sub_441450` to load the on-disk TTF into the DirectWrite font array instead. The live `Fonts\M+ 2m.ttf` is a valid TTF (signature `00 01 00 00`) and is the fixed (non-broken) font; ships in `FullLooseKit/assets/font/M+ 2m.ttf`. (Gotcha that cost a debug pass: the original `mov eax,lpMem` operand carries a base-reloc at RVA `0x227B`; the trampoline reuses those bytes, so `patch_exe.py`'s `kill_reloc()` neutralizes that reloc or ASLR relocates the jump into garbage.)

### 3. Code — loose `Script\` + `Plugin\` `*.js` (Patch 2)

P2 makes the engine prefer a loose `.js` over the `data.dts` copy, **per file, in REPLACE mode** (not additive — additive double-runs the alias/wrapper plugins and breaks gameplay). For each archive script entry the cave builds `<gamedir>\Script|Plugin\<name>` — and `<name>` **includes subfolders** (e.g. `constants\constants-stringtable.js`), matching the live tree (`Script\window\window-info.js`, `Plugin\02 俺オリジナル\文字変更.js`). If the loose file exists it loads that instead of the archive buffer; if absent, original behavior (zero change). The edited loose `.js` ship in `FullLooseKit/assets/plugins/Script\` and `…/Plugin\`.

**Encoding gotcha (verified):** loose `.js` MUST be **UTF-16LE with a `FF FE` BOM**. The live files are (`Script\window\window-info.js` starts `ff fe`). The engine's loose reader `sub_4749B0`, if the file isn't UTF-16, falls back to the **ANSI codepage (CP1252), not UTF-8** — a UTF-8 file mojibakes every non-ASCII char and a UTF-8 BOM makes ParseScriptText throw `property 'ï»¿' is null`. The active runtime StringTable/ContentLayout lives in `Plugin\02 俺オリジナル\文字変更.js` (it shadows `constants-stringtable.js`).

### 4. Art — loose `Graphics\*.srk` (stock loose path)

Translated/typeset images ship as loose `..\Graphics\*.srk` and override the copies in `data.dts` through SRPG Studio's existing per-type Graphics resolver (`sub_464BF0`). These are *not* a new patch — they ride the engine's built-in externalized-resource path. They must be synced as their own files; updating `data.dts` does not touch them.

## Data / parse flow at launch

1. `game.exe.full` starts and memory-maps the original JP `data.dts` (`sub_4465B0`, `SDTS` magic).
2. **Code:** as the engine parses each `Script\`/`Plugin\` entry, the P2 cave probes for a matching loose `.js` and parses it instead when present.
3. **Database:** on the **first** database-string read, the P5b cave lazily walks `Project\` and builds the jp→en FNV table; thereafter the probe at `sub_474100` swaps JP→EN for every string with a non-blank `en`, falling through to JP otherwise.
4. **Font:** when the engine builds its font array, the P6 cave substitutes loose `Fonts\M+ 2m.ttf` for the embedded font.
5. **Art:** Graphics requests resolve loose `Graphics\*.srk` over the archive.
6. **Title** (P7) and **stability** (P1) apply throughout.

The result is an all-English in-memory game built from the untouched Japanese `data.dts` plus the loose overlay — no archive was repacked and no script was recompiled.

## Why loose: edit-and-reopen, no repack/recompile/translation.bin

The older pipeline repacked an English `data_EN.dts` and shipped a delta patcher (see `deploy-checklist.md`, `patcher-system.md`); an intermediate iteration (Patch 5) prebuilt a `translation.bin` FNV table that still needed a build step. Both are **superseded** here. With full loose:

- Editing a translation = editing a plain UTF-8 JSON value in `Project\…json` (or a UTF-16LE `.js`, or a `.srk`), then relaunching. The game reads the folder directly; the change shows on next launch. `Translate and Play.bat` in the game root just does `start "" "game.exe"` — there is no build target.
- **`translation.bin` is deleted** — the cave reads the editable folder at runtime, so there's nothing to rebuild.
- Iteration is tight: a translator never touches the engine, the archive, or a compiler.

## What the player installs

Ship, and have the player drop into the game folder next to the original `data.dts`:

- the patched **`game.exe`** (`game.exe.full`) — placed **loose at the release-zip root**; the player copies it in and Windows prompts to replace. (Deliberately NOT shipped through any patcher's extra-files channel, so no player settings are touched.)
- the **`Project\`** JSON tree (the database translation)
- loose **`Fonts\M+ 2m.ttf`** (the fixed font)
- the loose **`Script\`** + **`Plugin\`** `*.js` (UI/code edits, UTF-16LE)
- the loose translated **`Graphics\*.srk`**

The original **JP `data.dts` stays as-is** — it is the base every loose file overrides. There is **no `translation.bin`** and **no `game.ini`** in the ship set (`game.ini` is never shipped, to avoid resetting the player's keybinds/fullscreen). The companion docs cover each channel in depth: P5b/`Project\` and `make_folder.py`, P2/loose `.js` and the `jstools` pipeline, P6 font, and the image/`.srk` typesetting tools.
