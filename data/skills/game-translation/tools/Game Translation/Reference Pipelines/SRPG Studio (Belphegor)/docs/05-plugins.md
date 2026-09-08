# The JS plugins (loose Script/Plugin)

SRPG Studio runs the game's logic and UI as JavaScript. At boot the engine parses every file under two trees that live *inside* `data.dts`:

- **`Script/`** — the engine "core" (load/save screen, item windows, message rendering, the UI string table, …).
- **`Plugin/`** — mods, both the developer's own and third-party ones, organised into subfolders (`01 オリジナル`, `02 俺オリジナル`, `03 他作者`, …).

Both are full JScript source. Patch 2 (P2) of the exe lets a **loose copy on disk override the data.dts copy of the same file**, so a translator edits a plain `.js` next to `game.exe` and sees the change on next launch — no repack of `data.dts`. This page is about how that override works, the two failure modes that will bite you (encoding, double-execution), which plugins carry translatable text, and the tooling (`js_text_tool.py` + `js_strings.json`) that extracts and re-applies that text.

## How P2 resolves a loose `.js` (replace, not add)

The engine loads scripts through `sub_446380 → sub_456090`, which loops over every script entry packed in `data.dts` and parses it with `IActiveScriptParse::ParseScriptText` (flags `SCRIPTTEXT_ISVISIBLE|ISPERSISTENT` = `0x42`). Parsing == adding to the one global JS namespace, and **files parsed last win**.

P2 hooks the per-entry loose-vs-packed branch in that loop (`test edx,edx; jz loc_4562B4` at VA `0x456223`, file offset `0x55623`) and trampolines into a position-independent cave at VA `0x4A8620` (the `PERCAVE` blob in `tools/loosekit/patch_exe.py`, installed at file `0xA7A20`). For **each** archive entry the cave:

1. Reads the entry's name field `[edi+0xC]` — this is the archive-relative path **including subfolders** (e.g. `constants\constants-stringtable.js`, `02 俺オリジナル\文字変更.js`), and the Script-vs-Plugin selector `[edi+0x14]`.
2. Builds `<gamedir>\Script\<name>` or `<gamedir>\Plugin\<name>` (via `wsprintfW`, IAT call `[edx+0x4A92D8]`, using the engine's own `\Script\%s` / `\Plugin\%s` and `%s\%s` format strings).
3. `GetFileAttributesW`-probes that path. **If the loose file exists → it loads the loose file *instead of* the archive buffer** (`jmp loc_4562B4`, which runs the engine's own loose loader `sub_4563F0(path, mode=1)` → reads the file via `sub_4749B0` then `ParseScriptText`). If absent → it reproduces the displaced `test edx,edx; jz` and falls through to the packed buffer.

So loose override is **per-entry, replace-mode**, loose-first with archive fallback, and a complete no-op for any entry that has no loose file. The cave is PIC: the `89 E6` (`mov esi,esp`) sets `esi` to the local-buffer base, and `E8 00000000 58 2D 30 86 4A 00` (`call $+5; pop eax; sub eax,0x4A8630`) recovers the ASLR delta into `eax`, so every absolute is formed as `[eax+abs]` (e.g. the `wsprintfW` IAT call `[edx+0x4A92D8]`). The exe sets `DYNAMIC_BASE`, so any hardcoded absolute would point ~0x30000 off and boot would fail with "ゲームの起動に失敗しました".

### Loose tree mirrors the archive paths (subfolders are fine)

Because the cave uses the entry's full subfolder-relative name, your loose tree must **mirror the data.dts layout exactly**, subfolders and all. That is what `FullLooseKit/assets/plugins/` already does:

```
assets/plugins/Script/constants/constants-stringtable.js
assets/plugins/Script/window/window-iteminfo.js
assets/plugins/Plugin/01 オリジナル/各種ボイス.js
assets/plugins/Plugin/02 俺オリジナル/文字変更.js
assets/plugins/Plugin/03 他作者/立ち絵表示_ステータス画面.js
```

(An early note claimed the cave was non-recursive and the loose `.js` had to be flat at top level — that is **superseded**: the shipped `PERCAVE` keys on `[edi+0xC]`, which carries the subfolder path, so the nested layout above is correct.)

## GOTCHA 1 — loose `.js` MUST be UTF-16LE (with the `FF FE` BOM)

This is the single most important rule on this page. The packed `data.dts` scripts are UTF-16, and the loose reader `sub_4749B0` only treats a file as Unicode when `IsTextUnicode` says so (i.e. it has the UTF-16LE BOM `FF FE`). For anything else it falls back to the **ANSI codepage (CP1252), not UTF-8**. Consequences:

- A **UTF-8** loose `.js` mojibakes every non-ASCII byte. An em dash `—` (`E2 80 94`) decodes as `â€"`; every accented or Japanese character is garbled. The game still boots, the text is just corrupt.
- A **UTF-8 BOM** (`EF BB BF`) is worse: it decodes to the literal characters `ï»¿` at the head of the file, so `ParseScriptText` throws `property 'ï»¿' is null` and that script fails to load.
- A correct **UTF-16LE BOM** `FF FE` is detected by `IsTextUnicode`, and JScript silently skips the BOM, so it parses cleanly.

Every shipped loose file in the kit is UTF-16LE+BOM. Verified head bytes:

```
Plugin/02 俺オリジナル/文字変更.js          : ff fe ...   (UTF-16LE)
Script/constants/constants-stringtable.js  : ff fe ...   (UTF-16LE)
Plugin/01 オリジナル/各種ボイス.js          : ff fe ...   (UTF-16LE)
```

**Practical consequence for the toolchain:** `tools/jstools/js_text_tool.py` reads and writes its files as **UTF-8** (`read_text`/`write_text` do `.decode('utf-8')` / `.encode('utf-8')`). So you translate against a UTF-8 working copy, then **convert each edited `.js` to UTF-16LE+BOM as the last deploy step** before it goes loose next to `game.exe`. The conversion is: decode as `utf-8-sig` (strips any UTF-8 BOM), then write `b"\xff\xfe" + text.encode("utf-16-le")`. Skipping this conversion is the most common reason a "translated" plugin shows garbage in-game.

## GOTCHA 2 — why P2 is replace-mode (the alias/wrapper double-execution)

Most of these plugins extend the engine with the alias/wrapper idiom: save the original method into a local, then overwrite the method with a function that calls the saved original. Real example from `Plugin/01 オリジナル/表示変更_アイテム＆スキル詳細.js`:

```js
var alias1 = ItemSentence.ResistState.drawItemSentence;
ItemSentence.ResistState.drawItemSentence = function(x, y, item) {
    alias1.call(this, x, y, item);
    ...
};
```

This pattern is everywhere in the edited core scripts (e.g. `Script/utility/utility-messageanalyze.js`, `Script/map/map-unitcommand.js`, `Script/window/window-iteminfo.js`, `Script/screen/screen-loadsave.js`, `Script/item/item-base.js` all carry many such reassignments).

If P2 loaded loose files **additively** (parse the packed copy *and* the loose copy), the wrapper would execute **twice**: the packed copy wraps the engine method once, then the loose copy captures *that already-wrapped* function into `alias1` and wraps it again. The result is double-applied effects (counts added twice, lines drawn twice, hooks fired twice) — visible gameplay bugs across the ~16–21 wrapper plugins. That is exactly why P2 is per-entry **replace**: when a loose file exists, the engine loads it *instead of* the packed one, so each method is wrapped exactly once. (The earlier additive trampoline at `0x456298` was reverted for this reason.)

## Inventory: which loose plugins matter for translation

These are the edited files under `assets/plugins/`. The ones that actually carry or control translated UI text:

- **`Plugin/02 俺オリジナル/文字変更.js`** — the live `StringTable` and `ContentLayout`. It does `var StringTable = {…}` (line 2) and `var ContentLayout = {…}` (line 323) as **full replacements**. Because plugins load after `Script/`, this **shadows** `Script/constants/constants-stringtable.js`, which is therefore inert at runtime. **Make StringTable / UI-label edits here.** Watch two specific items: `Chapter_Footer` must be `''` (line 211 in the kit; the JP was `'章'`, and leaving it produced "Chapter1章"/"Chapter1Chapter"), and `ContentLayout.ITEM_SPACE` (line 324, set to `84`) governs the gap between an info-window label and its value — too small and labels overlap their values, too large and 2-column rows overflow. Many info labels (Effective, Exclusive, Range, Value, Skill, Attack/Hit, …) come from `root.queryCommand(...)` *editor* data, not JS, so they can only be widened via `ITEM_SPACE`, not retranslated in this file.
- **`Script/constants/constants-stringtable.js`** — the engine's own UI string table (Save/Load prompts, generic menu words). At runtime it is **shadowed** by `文字変更.js`, but it shares the same keys/line numbers, so the workflow translates both for safety (you can copy translations across).
- **`Plugin/01 オリジナル/各種ボイス.js`** — the voice-trigger plugin. ⚠ Most of its Japanese string literals are **internal trigger keywords / motion IDs**, not UI text — e.g. `'戦闘開始'`, `'近-'`, `'遠-'`, `'移-'`, `'受-'`, `'lvup'`, `'杖使用'`, `'アイテム'`, `'自分にアイテム'`. They are compared against motion/attack IDs (`VoiceBattle('受-' + ...getPassiveMotionId())`), so **translating them breaks voice playback**. Leave these blank.
- **The `表示変更_*` display plugins** (`Plugin/01 オリジナル/表示変更_アイテム＆スキル詳細.js`, `…_マップユニット情報.js`, `…_支援ステータス.js`, `…_用語解説.js`) — these are the alias/wrapper plugins that redraw item/skill detail, the map-unit info box, support status, and the glossary. They pull most labels from `StringTable` (e.g. `StringTable.Status_Level`, `StringTable.Status_Experience`), so once `文字変更.js` is translated they render English; a few carry literal strings of their own that `js_text_tool.py` will surface.
- **`Plugin/03 他作者/立ち絵表示_ステータス画面.js`** — the status-screen portrait/description plugin; its description bar draws line-by-line, centred at `gameAreaHeight-50`, band height 64 (relevant when an English line is wider than the JP).
- **`Plugin/03 他作者/OT_ExtraConfigSkill/`** (`ExtraConfigBase.js`, `ExtraConfigSkill.js`, `CommandSkill.js`, `window-skillinfoExtra.js`) — the extra-config/skill system; `ExtraConfigBase.js` defines a large block of UI strings via `EC_DefineString`, `ExtraConfigSkill.js` more. Watch for `EC_Putlog`/`root.log` debug strings here — harmless to leave untranslated.
- Other edited core scripts (`Script/window/window-info.js`, `window-iteminfo.js`, `Script/screen/screen-loadsave.js`, `screen-quest.js`, `Script/item/item-base.js`, `item-recovery.js`, `Script/utility/*`, `Script/map/map-unitcommand.js`, `Script/singleton/singleton-itemcontrol.js`, `Script/eventcommand/eventcommand-itemchange.js`) carry smaller amounts of literal text and layout tweaks; `window-iteminfo.js` in particular holds the 2-column info rows (Attack/Hit, Crit/Range, Wlv/Weight) whose spacing was hand-tuned so the wider `ITEM_SPACE=84` from `文字変更.js` doesn't overflow column 2.

## The text pipeline: `js_strings.json` + `js_text_tool.py`

`tools/jstools/js_text_tool.py` is the extract/apply tool for the text that lives *in `.js` source* (the patch-the-database workflow can't reach it). It found **682 translatable strings across 21 files**; the biggest are `文字変更.js` (226), `constants-stringtable.js` (215), `ExtraConfigBase.js` (96), `ExtraConfigSkill.js` (33), `各種ボイス.js` (28, mostly trigger IDs).

Commands (run against an `extracted/` tree — i.e. the unpacked Script/+Plugin/):

```
python tools/jstools/js_text_tool.py extract extracted -o js_strings.json
# edit js_strings.json: fill each "translation" field (blank = keep original)
python tools/jstools/js_text_tool.py apply   extracted js_strings.json
python tools/jstools/js_text_tool.py stats    js_strings.json   # progress any time
```

`js_strings.json` (shipped pre-translated in `tools/jstools/`) keys each string per file:

```json
"Script/constants/constants-stringtable.js": [
  { "id": 12, "line": 12,
    "context": "LoadSave_SaveQuestion: '…',",
    "preview":  "このファイルにセーブしますか？",   // unescaped, reference only
    "original": "このファイルにセーブしますか？",   // raw match text — do NOT change
    "translation": "Save to this file?" }            // <- edit only this
]
```

How it stays safe:

- A small **JS lexer** finds string literals while skipping `//` and `/* */` comments, so Japanese that only appears in comments is ignored. Only literals containing hiragana/katakana/kanji are listed; pure-ASCII strings and template literals with `${…}` interpolation are skipped.
- Each string is keyed by its **index among all literals in the file** (`id`), which is stable even after a JP value becomes EN, so you can translate in batches and run `apply` repeatedly.
- `apply` re-tokenises with the same filter and re-checks `original` before replacing. Already-applied strings are skipped silently; a genuine mismatch (hand-edited file) prints a warning and is **skipped, never corrupted**. A literal quote in your translation is auto-escaped. Files are written back byte-for-byte except the translated values.

**Encoding caveat for this tool, restated:** `js_text_tool.py` operates on UTF-8 (it `extract`s/`apply`s UTF-8 bytes). The `extracted/` tree it edits is the UTF-8 working copy; it is **not** what ships loose. After `apply`, convert each `.js` to **UTF-16LE+BOM** before placing it next to `game.exe` (see GOTCHA 1). If you ever round-trip by re-unpacking `data.dts`, note the packed copies are already UTF-16; this tool's UTF-8 read assumes you fed it a UTF-8 source tree.

## Quick checklist for a plugin edit

1. Edit the right file: UI strings/labels → `Plugin/02 俺オリジナル/文字変更.js`; per-plugin literals via `js_strings.json` → `apply`.
2. Leave `各種ボイス.js` trigger IDs and `EC_Putlog`/`root.log` debug strings blank.
3. Keep the loose tree mirroring the data.dts subfolder paths (`Script/constants/…`, `Plugin/02 俺オリジナル/…`).
4. **Convert every shipped `.js` to UTF-16LE+BOM** (`FF FE`). UTF-8 = mojibake; UTF-8 BOM = `ParseScriptText` failure.
5. Don't expect additive behaviour — P2 replaces; a loose file fully supersedes its data.dts twin (and only that twin), so wrappers run exactly once.
