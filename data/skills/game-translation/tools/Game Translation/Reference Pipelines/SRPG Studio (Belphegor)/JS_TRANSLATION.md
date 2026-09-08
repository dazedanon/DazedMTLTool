# Translating the JS plugins / scripts (`js_text_tool.py`)

A lot of player-facing text in this game is **hardcoded inside `.js` files**
(plugin/engine string tables), not in `project.dat`. The SRPG_Unpacker patch
workflow can't reach it, so `js_text_tool.py` handles this layer.

**682 translatable strings across 21 files** were found in this game. Biggest:

| strings | file |
|--:|---|
| 226 | `Plugin/02 俺オリジナル/文字変更.js` (StringTable override) |
| 215 | `Script/constants/constants-stringtable.js` (engine UI strings) |
| 96  | `Plugin/03 他作者/OT_ExtraConfigSkill/ExtraConfigBase.js` (`EC_DefineString`) |
| 33  | `Plugin/03 他作者/OT_ExtraConfigSkill/ExtraConfigSkill.js` |
| 28  | `Plugin/01 オリジナル/各種ボイス.js` (⚠ mostly internal voice-trigger IDs — leave blank) |
| …   | (16 more files, 1–22 each) |

## Workflow

```
# 1. (already done) unpack data.dts -> extracted/   (has Script/ + Plugin/)

# 2. extract translatable strings
python js_text_tool.py extract extracted -o js_strings.json

# 3. translate: edit js_strings.json, fill each "translation" field
#    (leave blank to keep the original; blanks are never applied)

# 4. inject the translations into the .js files
python js_text_tool.py apply extracted js_strings.json

# 5. repack and use in game
SRPG-ToolBox\SRPG_Unpacker\x64\Release\SRPG_Unpacker.exe extracted -o data.dts
#    back up the original data.dts first, then replace it with this one
```

`stats` shows progress any time: `python js_text_tool.py stats js_strings.json`

## The `js_strings.json` entries

```json
"Script/constants/constants-stringtable.js": [
  {
    "id": 12,                                  // stable literal index — do NOT change
    "line": 12,
    "context": "LoadSave_SaveQuestion: '…',",  // surrounding line, for reference
    "preview": "このファイルにセーブしますか？",   // human-readable (escapes decoded) — reference only
    "original": "このファイルにセーブしますか？",   // raw text matched on apply — do NOT change
    "translation": ""                          // <-- put your translation here
  }
]
```

Only edit **`translation`**. Rules:
- Leave `\n`, `\t` etc. as-is if present (they're literal in the raw form).
- A literal `'` in your text is auto-escaped on apply, but you can pre-escape as `\'`.
- Blank `translation` = keep original.

## How it works / safety

- A JS lexer finds string literals while **skipping `//` and `/* */` comments**, so
  Japanese that only appears in comments is ignored. Only literals containing
  hiragana/katakana/kanji are listed (pure-English/ASCII strings are skipped).
- Template literals with `${…}` interpolation are skipped (not translated).
- Each string is keyed by its **position among all literals in the file** (stable
  even after a value is translated), and `apply` re-checks `original` before
  replacing. So:
  - **Incremental translation works** — translate in batches, run `apply` repeatedly.
  - **Re-running `apply` is safe/idempotent** — already-applied strings are skipped;
    a genuinely hand-edited file produces a warning and is skipped, never corrupted.
- Files are written back byte-for-byte except the translated values (line endings,
  BOM, keys, quotes, commas preserved).

## Notes / cautions

- **`各種ボイス.js`** (28) and similar: many entries are **internal trigger keywords /
  material IDs**, not UI text — translating them breaks the game. Use the `context`
  to tell UI strings from IDs and leave IDs blank.
- **Debug logs**: a few strings are `EC_Putlog`/`root.log` debug text — harmless to
  skip.
- `文字変更.js` and `constants-stringtable.js` are near-duplicates (the plugin
  overrides the engine table); translate both (or just whichever the game uses) —
  they share the same keys, so you can copy translations across.
- `apply` edits the files in `extracted/` in place. `data.dts` is untouched, so you
  can always re-run `extract` from a fresh unpack to start over.
