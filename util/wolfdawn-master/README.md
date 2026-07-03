# WolfDawn

WolfDawn turns Wolf RPG Editor game files into a readable, editable form and back. It unpacks the
`Data.wolf` archive, decompiles event code into readable WolfScript, pulls out translatable text and
puts it back, edits databases and save files, and packs everything into a runnable game again.

It comes as a command line tool (`wolf`) and a desktop app (WolfDawn Studio). The GUI is built for
people who do not use a terminal. Every option is a checkbox or a dropdown and every file is picked
with a normal file dialog.

## What it does

- Unpack and repack `Data.wolf`. Supports the current DXArchive v8 container, the older VER5 and VER6
  format used by Wolf 2.x, and WolfPro and ChaCha20 encryption.
- Decompile maps and common events into editable WolfScript, then compile them back. Untouched code
  stays byte for byte the same.
- Extract every player-facing string for translation and inject the finished translation back.
- A project glossary keeps database names (items, skills, enemies) consistent across every file that
  looks them up, so a renamed monster does not break by-name lookups.
- Carry an existing translation into a fresh extraction when a game updates. You only translate the
  lines that are actually new.
- Edit databases in a spreadsheet grid, edit `Game.dat` (title, fonts, messages, image paths), and
  edit save files.
- Fix saves so a Japanese or old save loads in a translated build. This rewrites the baked game title
  and refreshes the baked strings. It handles standard saves and the GamePro Pro save format.
- Verify that a file decodes and re-encodes without loss before you ship it.

## WolfDawn Studio (GUI)

Launch it with `wolf gui`, or run the `wolf-gui` binary directly. Open a game folder or a `Data.wolf`
and WolfDawn Studio reads the title, version, encoding, and font, then fills the relevant file lists
for each section. New files (for example after you unpack) show up on their own.

Sections:

- **Project** opens a game and shows its details.
- **Archive** unpacks `Data.wolf` to a folder and repacks a folder back, with encryption and format
  options.
- **Decompile** turns a map or common event into WolfScript, lets you edit it (with Ctrl+F search),
  and compiles it back.
- **Database** edits a database in a grid of rows and fields.
- **Game.dat** edits the title, fonts, messages, and image paths in a simple form.
- **Translation** extracts the whole `Data` folder into a source and translation grid plus a name
  glossary, then injects it. The English punctuation cleanup and the code-safety guard are checkboxes.
- **Saves** opens a `.sav`, shows the format and baked strings, lets you edit the title and strings,
  and re-encrypts. It can also batch-fix a whole `Save` folder.
- **Verify** round-trips a file or a whole data folder and reports pass or fail.
- **Settings** holds the theme and the default options. They persist between runs.

## Command line

```
wolf unpack <Data.wolf> -o <dir>
wolf pack   <dir> -o <out.wolf> [--encrypt --version 0x14b | --like <orig> | --format ver5|ver6]

wolf decompile <map.mps|CommonEvent.dat> [--mode edit] [-o out.wscript]
wolf compile   <doc.wscript> --base <orig> -o <out>

wolf db-json      <X.project|data-dir> [-o out]
wolf db-apply     <edited.json> --base <X.project> -o <out.project>
wolf gamedat-json  <Game.dat> [-o out.json]
wolf gamedat-apply <edited.json> --base <Game.dat> -o <out>

wolf strings-extract <CommonEvent.dat|map.mps|X.project|Game.dat> -o <out.json>
wolf strings-inject  <edited.json> --base <orig> -o <out> [--allow-code-drift] [--en-punct]
wolf names-extract   <data-dir> -o <names.json>
wolf names-inject    <names.json> --data <data-dir> [-o <out-dir>] [--allow-code-drift] [--en-punct]
wolf names-check     <file.json>...
wolf translations-merge --old <path>... --new <dir> -o <out-dir>

wolf save-update <save.sav|dir> [-o <out>] [--title <text> | --game <Game.dat>] [--translations <path>...]

wolf verify-roundtrip <file>
wolf verify-roundtrip --corpus <data-dir>

wolf gui
```

Exit codes: `0` ok, `2` round-trip or usage failure, `3` merge conflict, `4` crypto failure.

## A typical translation run

1. `wolf unpack Data.wolf -o Data` to get an editable folder.
2. `wolf strings-extract` per file and `wolf names-extract Data -o names.json` to pull the text. In the
   GUI the Translation section does the whole folder at once.
3. Translate the text. Pass `--en-punct` to convert Japanese punctuation to ASCII for English.
4. `wolf strings-inject` and `wolf names-inject` to write it back.
5. Rename `Data.wolf` and keep the edited `Data` folder next to `Game.exe`, or `wolf pack Data -o
   Data.wolf` to rebuild the archive.
6. `wolf save-update` so existing saves still load in the translated build.

## Build

```
cargo build --release
```

This produces `target/release/wolf` (the CLI) and `target/release/wolf-gui` (the desktop app). The
build is plain Rust with a small set of dependencies. The crypto, codecs, and binary format readers
are all hand written.

## Running the tests

```
cargo test
```

That runs the unit tests, which need nothing extra. A handful of integration tests want real Wolf
game data (an unpacked `Data` folder, a couple of saves, a GamePro Pro save and its ground-truth
decrypt). That data is copyrighted and not bundled, so those tests skip themselves unless you point
them at a fixtures folder.

Set `WOLFDAWN_TEST_DATA` to a folder laid out like this and the data-dependent tests run too:

```
<root>/chamber/Data/...               an unpacked game Data folder (BasicData, MapData)
<root>/chamber/Data/BasicData/Game.dat
<root>/chamber/Data/BasicData/CommonEvent.dat
<root>/chamber/Data/BasicData/DataBase.project (+ DataBase.dat)
<root>/chamber/Data/MapData/TitleMap.mps
<root>/chamber/Data.wolf               the packed archive (the unpack test)
<root>/chamber/SaveData01.sav          a standard save
<root>/pachimon/SaveData01.sav         a GamePro Pro save
<root>/pachimon/decrypted.bin          the ground-truth decrypt of that save
```

Any file that is missing just skips the test that needs it, so a partial fixtures folder is fine.
With the variable unset every one of these tests skips and the suite still passes.

## Project layout

- `wolf-core` holds the low level reader and writer, the LZ4 block codec, and CRC32.
- `wolf-archive` is the `Data.wolf` container and its encryption.
- `wolf-formats` reads and writes the binary maps, common events, databases, and `Game.dat`.
- `wolf-decompiler` is the WolfScript decompiler and compiler, the translation pipeline, the database
  and `Game.dat` editors, and the save codecs.
- `wolf-cli` is the `wolf` binary.
- `wolf-gui` is WolfDawn Studio.

## Notes

The decompiler aims for a faithful round trip. Where a region of a file is not fully understood it is
preserved as raw bytes, so a recompiled file always loads. Saves and `Game.dat` round-trip byte for
byte when you do not change a field. The GamePro Pro save format is supported for marker-3 saves. A
few other GamePro save markers are detected and skipped rather than corrupted.
