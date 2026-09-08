# loosekit

Everything needed to build the loose-translation `game.exe`, and to build the
editable `Project\` folder it reads.

The game translates from a `Project\` folder that **is the native SRPG
`project.dat` JSON tree** (`items.json`, `Maps\map_000.json`, …) with each
translatable string wrapped as `{"jp": "<original>", "en": "<your text>"}`. Edit an
`en`, relaunch, done — no build, no `translation.bin`. Blank `en` stays Japanese.

That edit-and-relaunch loop covers **everything the folder exposes** — every `{jp,en}`
string (including the numbers/flags inside `customParameters`, which is one wrapped
string), and `fontSize`, the one bare-number field, which P8 applies straight from
`fonts.json`. No build step, no loose `project.dat`. Full editable-field map in
[docs/08-changing-the-database.md](../../docs/08-changing-the-database.md).

## `patch_exe.py` — build the full loose `game.exe`

Turns a **stock v1.23** `game.exe` into the patched build in one pass:

- **P1** never force-quit on a momentarily-missing resource
- **P2** load loose `Script\`/`Plugin\` `.js` over the `data.dts` copies
- **P3** load a loose `project.dat` over the one in `data.dts`
- **P5b** read the editable `Project\` JSON tree at runtime and translate the
  database JP→EN at parse time — no `translation.bin`, no build step
- **P6** load a loose `Fonts\<name>.ttf` over the embedded (broken) font
- **P7** set the OS window title from `Project\titles.json` (`windowTitle` en → jp →
  the engine's own caption); read live, nothing baked in
- **P8** apply `Project\fonts.json` `fontSize` edits onto the parsed font records at
  startup (the one non-string field — live from the folder, no built files)

```
python patch_exe.py game.exe.orig.bak -o game.exe
```

It verifies every patch site and refuses anything but the stock exe. Needs
`probe.bin`, `load_table.bin`, `apply_fontsize.bin`, and `apply_title.bin` (all here).
`data.dts` stays the original Japanese; the loose files do the translating.

## `make_folder.py` — build the `Project\` tree from the game

Unpacks `project.dat` (with `SRPG_Unpacker`) and writes the native JSON tree, wrapping
every Japanese string as `{"jp": ..., "en": ""}`. Drop the result in as `Project\`.

```
python make_folder.py                          # _jpbase\project.dat -> Project\ (blank en)
python make_folder.py --store tooling\tl       # fill EN, reflowed exactly like data.dts
python make_folder.py --en translation_en_backup   # fill EN from an old folder (NOT reflowed)
python make_folder.py --project <project.dat> --out Project
```

Only Japanese-containing strings are wrapped; `speaker` / `comment` / `fontName` are
left as plain strings (speaker names translate through the unit-name entries).

**`--store`** runs the translation pipeline's `inject` over the tree, so dialogue/info
text gets the same width-fill **reflow**, page-align and glossary names as the data.dts
build (no orphan tail-words). Use it; `--en` (copy from an old `{id,en}` folder) carries
the raw translator wraps. Needs `tooling/srpgtl` (the `tl/` store).

## `apply_fontsize.c` — the P8 fontSize override (`fontSize` is the one non-string field)

`fontSize` is the only field in the tree that isn't a `{jp,en}` string, so P5b can't
key on it. `apply_fontsize.c` is the P8 cave: at font-system init it reads the ten
`fontSize` values out of `Project\fonts.json` and writes them onto the parsed font
records, so editing `fonts.json` shows next launch with no build and no loose
`project.dat`. It's compiled to position-independent shellcode (`apply_fontsize.bin`),
exactly like the loader, and reaches the engine through an `Imp` struct the asm stub in
`patch_exe.py` fills. (Deep numeric tables — unit stats, item might/weight, prices — aren't
in the tree at all and stay SRPG Studio editor territory; see
[docs/08](../../docs/08-changing-the-database.md).)

## `apply_title.c` — the P7 live window title

`apply_title.c` is the P7 cave: at window creation it reads `Project\titles.json` and
resolves `windowTitle` — `en` if non-empty, else `jp`, else the engine's own caption
(i.e. unpatched, if the file/key is missing) — and hands the string back as the window
title. Nothing game-specific is baked in, so it works for any SRPG Studio game. Compiled
to PIC shellcode (`apply_title.bin`) like the others.

## `load_table.c` / `apply_fontsize.c` / `apply_title.c` / `build_loader.ps1` / `_emit*.py`

The three C caves — `load_table.c` (P5b runtime folder reader → `load_table.bin`),
`apply_fontsize.c` (P8 fontSize → `apply_fontsize.bin`), and `apply_title.c` (P7 title →
`apply_title.bin`) — compiled to position-independent shellcode. Only rebuild if you
change a `.c`:

```
powershell -ExecutionPolicy Bypass -File build_loader.ps1   # builds all three; needs VS 2022
```

`build_loader.ps1` compiles each and runs `_emit.py` / `_emit2.py` to extract the
`.text` and assert **0 relocations**. `patch_exe.py` embeds the committed `.bin` files;
`probe.bin` is the hand-assembled JP→EN lookup that runs on every database string.
