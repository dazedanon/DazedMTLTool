# SRPG Studio

**Indicators:** SRPG Studio `game.exe` (imagebase `0x400000`), a single large `data.dts` archive (~500 MB) holding database + code + graphics + audio + fonts. Fire-Emblem-style tactical RPGs.

**Reference implementation:** `tools/Game Translation/Reference Pipelines/SRPG Studio (Belphegor)/` - the **gold-standard translation pipeline in this whole corpus**, especially its text-wrapping/layout code. Read `.\docs\01-architecture.md` through `08-changing-the-database.md`. Tooling: `.\tl.py` + `.\srpgtl\` package + `.\loosekit\make_folder.py` + `.\jstools\` + `.\typeset_*.py`. Glossary/bible at `.\tl\`.

## Delivery: patched exe + loose-file override (no repack)

The kit binary-patches a copy of `game.exe` (ships as `game.exe.full`, verify stock SHA first) to make the engine read **loose files layered on the untouched `data.dts`**. Original archive is never modified → instant rollback and side-by-side JP/EN comparison. Patch channels:

| What | Loose location | Hook |
|---|---|---|
| Database text (names/descs/dialogue) | `Project/` JSON tree | db-string reader hook (FNV-1a table) |
| Code | `Script/*.js`, `Plugin/*.js` (loose) | script-loader branch → loose path |
| Font | `Fonts/*.ttf` | font-init hook |
| fontSize | `Project/fonts.json` | font-system init |
| Window title | `Project/titles.json` | window-creation read |
| Art | `Graphics/*.srk` (loose) | engine's existing loose path |
| Stability | never force-quit on missing resource | flag patch (allows partial `Project/`) |

## Text pipeline

1. **Unpack** database: `SRPG_Unpacker -c` → ~250 JSON files (`items.json`, `skills.json`, `actors.json`, `Maps/map_NNN.json`, `Extra/`, etc.). Use the patched unpacker that also extracts `customParameters` JS literals.
2. **Extract** `srpgtl/extract.py` → a translation *store* (`tooling/tl/`) + seeded glossary. Unit format:
   ```json
   {"id":"names:1","kind":"name","src":"◆…(code-masked)","raw":"◆…(match key)","codes":{},"tl":""}
   ```
   Dialogue units also carry `"speaker"` (JP, context only) and `"ctx":"map_000:<scene_id>"` (groups the event page).
3. **Translate** `tl.py run` (Claude batches, two-phase: names → glossary → dialogue). See `llm-pipeline.md`.
4. **Inject** `srpgtl/inject.py` → reflow + write strings back into JSON.
5. **Build folder** `make_folder.py --store tooling/tl` → `Project/` with every translatable string wrapped `{"jp":"…","en":"…"}`.
6. **JS strings** `jstools/js_text_tool.py` → translated plugin/engine `.js`.

**KEY_KIND map** (which DB fields are what): `data/msg`→text (dialogue, has speaker), `infoText`→info, `name`→name, `desc/description`→desc, `victoryConds/defeatConds`→cond, `pages`→pages (narration), `commandName/command/mapName/rewardData`→ui, `windowTitle/gameTitle/saveFileTitle`→title. **SKIP_KEYS never translated:** `speaker` (flows through unit-name entries), `comment` (dev-only), `fontName`.

**Dedup:** map dialogue/info stored per-map, scene-grouped, **not deduped** (model needs speaker runs). Everything else globally deduped.

## customParameters: text hidden inside a JS literal

**SRPG Studio hides player-facing text inside `customParameters`, a JavaScript
object literal stored as a *string* in the JSON.** Mishandling it breaks the entity
at runtime rather than merely leaving text Japanese. Two forms:

```python
# name:'...'   - single-quoted, simple
r"name:\s*['\"]([^'\"]+)['\"]"
# re-insert with re.sub(r"(name:\s*['\"])([^'\"]+)(['\"])", ...) and DOUBLE the
# backslashes in the replacement

# hint:"..."  - double-quoted, escape-aware: "not quote and not backslash"
#              OR "backslash followed by anything"
r'hint:"((?:[^"\\]|\\.)*)"'
```

Because `hint` is a double-quoted JS string, replace any `"` in the translation with
`'`, wrap the text, and re-encode newlines as a literal backslash-n rather than a
real break. **When a record has no hint, still append an empty placeholder** so list
indices stay aligned across the collect and apply passes.

**Know which fields are identifiers.** On a map, `name` is an internal identifier
that event references resolve against and must be skipped, while `mapName` is the
displayed name. `rewardData` entries are translated but never wrapped.

**Seed the glossary from the name-bearing DB files before any dialogue runs.**
Harvest original-to-translated pairs out of `characters`, `items`, `skills`,
`classes` and `weapons` into their own glossary sections. That is what keeps an item
or skill name identical between the menu that lists it and the conversation that
mentions it.

Route files by filename shape through one two-pass recursion: pass 1 collects with
newlines flattened to spaces, batch translate, pass 2 re-walks and pops in order with
a per-list length check that flags any file whose counts disagree.

## THE WRAPPING ALGORITHM (reusable across engines)

`docs/04-wrapping-layout.md` - this is the reference text-layout code for any fixed-width box. Core `_reflow(text, width)`:

- **Greedy MAX-FILL**: merge soft `\n` away, fill each line to `width` before breaking. Preserve **hard `\n\n`** (paragraph breaks) and **speaker headers `【Name】`**.
- **Cell-width counting (monospace, code-aware):** East-Asian Wide/Fullwidth/Ambiguous glyphs (CJK, kana, `…♡。※`) = **2 cells**. ASCII = **1**. Masked control codes `⟦n⟧` and `\xx[..]` = **0** (invisible to layout). Count cells, not chars.
- **Kinsoku binding** (never split these across a line break): `_BIND_TITLE` (title↔name: `Lady␣Balam`), `_BIND_UNIT` (number↔unit: `3␣turns`), `_BIND_LEAD` (leading function word↔next: never end a line on stranded `The`/`to`). Mechanism: swap the protected space for a `\x00` sentinel during wrap, restore after.
- **Widow control** `_fix_widow`: if a block's last line is a lone short word, pull the previous word down - **but only if the merged line still fits** (never create overflow to fix a widow). Never break `\x00`-bound units.
- **Per-box widths** (measure in-game): dialogue 54, dictionary/manual pages 44 (narrower - right-side art clips full width), shop face-box 32 (must fit ≤2 lines). Assign narrow width to the specific unit-id range that renders in the narrow box.

## Critical encoding gotcha

**Loose `.js` files MUST be UTF-16LE with a `FF FE` BOM.** The engine's loose reader falls back to CP1252 (ANSI) if the file isn't UTF-16 → any non-ASCII mojibakes. A UTF-8 BOM produces `property 'ï»¿' is null` in ParseScriptText. JSON stays UTF-8. Verify encoding before shipping.

## Build command

```bash
# from the copied pipeline folder (Reference Pipelines/SRPG Studio (Belphegor)/)
python tl.py extract
python tl.py run
python tl.py inject
python loosekit/make_folder.py --project _jpbase/project.dat --out Project --store tl
```
Ship: patched `game.exe`, loose `Project/` `Script/` `Plugin/` `Fonts/` `Graphics/`. Original `data.dts` untouched.
