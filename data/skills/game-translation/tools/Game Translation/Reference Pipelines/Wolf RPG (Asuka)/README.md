# Wolf RPG (Asuka) - Claude batch pipeline + relayout + font/symbol fixes

Complete JP to EN pipeline from the translation of a WOLF Pro RPG (Asuka Virgin Idol Debut, ~26,573 lines).
Sibling of `Wolf RPG (Pachimon)`, which used Mistral + the older `wolf_rpg_decode.exe`.
This one uses the mature **`wolf` CLI** (WolfDawn) for the binary layer plus a **Claude Message Batches** driver, and adds the two things WolfDawn does not do: **EN text relayout** (box-geometry reflow + page-splitting) and **font/symbol fixes**.

WolfDawn carries the binary layer: unpack, `strings-extract`/`inject`, `mt-export`/`import`, `names-*`, `db-json`/`apply`, `gamedat-json`/`apply`, and the `decompile --mode edit` / `compile` round-trip that reconstructs jumps and indentation. That round-trip is what makes inserting continuation `Message` commands (page-splitting) and event-side label overrides safe. See `WOLFDAWN-GAPS.md` for the full analysis of what WolfDawn is missing and proposed fills.

## End-to-end sequence

Paths shown for this game. `$wolf` = `C:\Users\sw\Desktop\Projects\WolfDawn\target\release\wolf.exe`. Confirm exact flag names against `wolf <cmd> --help` before first use.

```powershell
# 1. EXTRACT (WolfDawn) - loose Data folder, no unpack needed here; else: wolf unpack Data.wolf -o Data
& $wolf strings-extract Data\BasicData\CommonEvent.dat -o out\CommonEvent.json
& $wolf strings-extract Data\BasicData\DataBase.project -o out\DataBase.json   # + CDataBase, SysDatabase
& $wolf strings-extract Data\BasicData\Game.dat -o out\GameDat.json
foreach ($m in Get-ChildItem Data\MapData\*.mps) { & $wolf strings-extract $m.FullName -o "out\map_$($m.BaseName).json" }
& $wolf names-extract Data -o out\names.json
& $wolf mt-export out\*.json -o batch.json      # every untranslated line + speaker/context

# 2. TRANSLATE (Claude batches) - phase 1 names, phase 2 text; resumable
$env:ANTHROPIC_API_KEY = "sk-..."
python scripts\claude_translate.py dryrun --show-sample   # cost preview, no spend
python scripts\claude_translate.py run                    # names then text, polls to done
python scripts\claude_translate.py validate               # residual-JP / control-code integrity
python scripts\claude_translate.py retry                  # re-translate hard failures with scene context

# 3. POST-FETCH REPAIR (external-LLM JSON-escape collision, speaker tags)
python scripts\repair_batch.py                            # \f/\r un-mangle + speaker-tag glossary fill

# 4. APPLY BACK + names consistency (WolfDawn)
& $wolf mt-import batch.json (Get-ChildItem out\*.json).FullName
& $wolf names-fill out\names.json (Get-ChildItem out\*.json -Exclude names.json).FullName
& $wolf names-check (Get-ChildItem out\*.json).FullName   # exit 2 = conflicts; also width lint

# 5. INJECT to a copy (WolfDawn) - strings per file FIRST, names LAST in place
Copy-Item Data DataEN -Recurse
& $wolf strings-inject out\CommonEvent.json --base Data\BasicData\CommonEvent.dat -o DataEN\BasicData\CommonEvent.dat --en-punct
#   ... per DB pair / Game.dat / each map (add --dry-run first) ...
& $wolf names-inject out\names.json --data DataEN --en-punct

# 6. RELAYOUT (this pipeline) - reflow EN to box geometry + page-split; run from a decompile
& $wolf decompile DataEN\BasicData\CommonEvent.dat --mode edit -o ws\CE.wscript
python scripts\relayout.py wscript ws\CE.wscript ws\CE.wrapped.wscript   # or `simulate` first
python scripts\fix_ui_strings.py ws\CE.wrapped.wscript ws\CE.final.wscript   # symbol/label normalize
& $wolf compile ws\CE.final.wscript --base DataEN\BasicData\CommonEvent.dat -o DataEN\BasicData\CommonEvent.dat
#   ... repeat decompile->relayout->compile per map ...

# 7. FONT FIX (this pipeline) - the #1 tofu fix; point Game.dat at a built-in CJK font
& $wolf gamedat-json DataEN\BasicData\Game.dat -o gamedat.json
#   edit gamedat.json: "Font": "ＭＳ ゴシック"   (MS Gothic, built-in, no install)
& $wolf gamedat-apply gamedat.json --base DataEN\BasicData\Game.dat -o DataEN\BasicData\Game.dat

# 8. VERIFY + SWEEP + IN-GAME TEST
& $wolf verify-roundtrip --corpus DataEN
python scripts\scan_all_strings.py ws DataEN\...\*.project   # residual JP / fullwidth symbols
#   then PLAY - verify-roundtrip does NOT catch by-name-lookup breakage; only in-game does.
```

## Script index (reusable)

| Script | Purpose | Reuse note |
|---|---|---|
| `claude_translate.py` | 2-phase (names/text) Claude Message Batches driver over the `mt-export` JSON: prompt caching, control-code multiset validation, JSON-escape repair (`_repair_json_escapes`), resumable retry, cost dryrun | Genericize: `SYSTEM_SHARED` prompt, model pricing snapshot, paths. Keep the escape repair and code-multiset logic verbatim. |
| `relayout.py` | Box-geometry reflow: refill-wrap to `WIDTH`/`WIDTH_FACE` cells x `MAX_ROWS`, portrait-aware width, page-split into continuation `Message` commands with header repeat + stateful-code (`\c\f\font\s`) re-arm | `layout_message()` is pure/generic. `WIDTH`/`WIDTH_FACE`/`MAX_ROWS` are config. **`FACE_IDS` is game-specific** - rebuild per game from SysDatabase type 24 (顔グラフィック名 ids with a non-empty image file). |
| `repair_batch.py` | Post-fetch: un-mangle form-feed/CR (from `\f`/`\r` JSON collisions) and glossary-fill speaker tags | Control-code + glossary format is Wolf-specific; `name_map` builder reusable. |
| `fix_ui_strings.py` | Normalize fullwidth punctuation -> ASCII in display literals, plus game-specific label/overflow fixes; depth-0 literal parsing (`literal_spans`) skips compiler symbol annotations | `CHARMAP` + `literal_spans()` reusable. `EXACT`/`REGEX` dicts are per-game (fold your fixes in). |
| `scan_all_strings.py` | Post-deploy QA sweep: every wscript command arg + all DB fields for residual JP words and fullwidth symbols the extractor skipped | Generic QA. `FW_RISK`/`SAFE`/`classify()` configurable. |
| `scan_display2.py` | Narrower sweep: display-command literals + Database written-value args only (skips lookup-name operands) | Complement to `scan_all_strings`. |
| `strip_ruby.py` | Strip ruby `\r[base,reading]` -> base (WolfDawn treats ruby as droppable) | Generic; keeps escaped `\\r[..]` (tutorial demos) intact. |
| `rewrap_batch.py` | Simpler predecessor to `relayout.py` (48-cell wrap, no page-splitting) | Kept for reference; `relayout.py` supersedes. |

`scripts/examples/` holds three **game-specific reference patterns** (do not run as-is, read them):
`translate_reqlabels.py` (the SAFE fix for a `dataID=-3` field-name-GET label - event-side override, never schema), `translate_memos.py` (translate a DB field WolfDawn's extractor skips, via `db-apply`), `finalize_batch.py` (hand-fix + cleanup patterns).
`tl/` holds `glossary.json` + `game_prompt.md` as templates.

## WolfDawn-gap prototype tools

Working prototypes of the six roadmap features in `WOLFDAWN-GAPS.md` (all import the shared `wolfscript.py`, have sensible defaults, and fail gracefully on bad input). These are usable now and are the reference for eventually porting the features into WolfDawn itself.

| Tool | Prototypes | Run |
|---|---|---|
| `wolfscript.py` | (shared primitives: code regex, cells, escape, `literal_spans`, `iter_display_literals`, safe `load_json`/`read_text`) | imported by the others |
| `font_check.py` | `wolf font-check` - the #1 tofu diagnostic | `python font_check.py --font "源暎ラテミン v2 Medium"` -> shows the GDI fallback + missing glyphs + suggests MS Gothic. `--gamedat-json`, `--corpus` optional. |
| `relayout.py` | `wolf relayout` - reflow + page-split (P0-2) | `python relayout.py wscript IN OUT [--width N --width-face M --max-rows R]` (all width flags optional, default 68/60/4) |
| `normalize_symbols.py` | `wolf normalize-symbols` - fold fullwidth punct the extractor skipped | `python normalize_symbols.py FILE.wscript [--report-only]` |
| `field_names_detect.py` | `wolf field-names-detect` - find `dataID=-3` field-name display labels | `python field_names_detect.py --ws ws --db db/*.json` -> lists sites + flags unsafe-to-rename names |
| `verify_semantic.py` | `wolf verify-semantic` - catch by-name-lookup breakage roundtrip misses | `python verify_semantic.py --ws ws --db db/*.json` |
| `sentinel_mask.py` | `mt-export --sentinel-mask` - make code corruption impossible for external LLMs | `python sentinel_mask.py mask batch.json -o masked.json --legend legend.json` / `unmask` |
| `xref.py` | `wolf xref` - trace where a displayed string/field/variable comes from | `python xref.py 行動力` / `python xref.py 'CSelf[6]'` |

Defaults assume a working dir with `ws/` (decompiled `*.wscript`) and `db/` (`wolf db-json` dumps) subfolders; pass `--ws`/`--db` to point elsewhere. Notes: `verify_semantic` reports a superset of true breaks (a non-resolving name annotation is only runtime-breaking for name-mode lookups, not index-mode; the reliable signal is the delta when you rename something). `sentinel_mask` round-trips exactly on every real string tested.

## Key gotchas (the ones that cost the most time)

1. **Font resolution is the #1 tofu cause.** `Game.dat` Font `"…v2 Medium"` does not resolve via GDI `CreateFontW` (a style suffix in the face name breaks matching) and falls back to MS Sans Serif, so every non-ASCII char is a box. Fix: point Font at a built-in CJK font (`ＭＳ ゴシック`), no install. "Installed" is not "resolves" - test the exact face string via GDI `CreateFontW` + `GetTextFace`.
2. **Relayout widths: measure in-game, not from JP percentiles.** JP percentile guesses under-filled. Real box was 68 cells plain / 60 with a portrait.
3. **Portrait-aware width uses real face ids.** Build `FACE_IDS` from SysDatabase type 24: only ids with a non-empty 顔画像ファイル draw a bust. Ids 0-9 are window-style selectors, no portrait, full width.
4. **Displayed DB field names (`dataID=-3`) are untranslatable by the tools AND unsafe to rename in schema** (breaks by-name cid250/251/252 lookups, giving a `□DB` error at runtime). Fix event-side (see `examples/translate_reqlabels.py`).
5. **`verify-roundtrip` is necessary, not sufficient.** It passed on a schema edit that broke at runtime. Only in-game testing catches by-name-lookup breakage.
6. **Mask control codes to sentinels for external LLM JSON.** The transport corrupts `\f`/`\r`/`\cself` regardless of instructions (cost 127/477 requests before the parser was hardened).

## Next WOLF game: start here

1. **Font first.** Dump `Game.dat`, check the Font face resolves via GDI. If not, set it to `ＭＳ ゴシック` before anything else - it rules out the biggest false-lead.
2. Extract + `mt-export`, hand-build `tl/glossary.json` + `tl/game_prompt.md` (copy the templates here).
3. Translate with `claude_translate.py` (adjust the prompt/pricing), `validate`, `retry`, `repair_batch.py`.
4. `mt-import` + `names-fill` + `names-check`. Inject strings then names.
5. Build `FACE_IDS` from SysDatabase type 24, measure box width in-game, run `relayout.py` per file.
6. `fix_ui_strings.py` + `scan_all_strings.py` sweep for skipped symbol rows.
7. `verify-roundtrip`, then PLAY - watch battles/shops/menus for by-name-lookup breakage and any `dataID=-3` field-name labels.
