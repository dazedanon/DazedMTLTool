# Wolf RPG Editor

**Indicators:** `Data.wolf` / `Data/*.wolf` / `*.wolfx`, `Game.exe` or `GamePro.exe`, `Config.exe`. Data is a DXArchive (v8 / VER5 / VER6 / WolfPro, sometimes ChaCha20-encrypted) containing binary `.mps` maps, `CommonEvent.dat`, `DataBase`, `Game.dat`. Text is inside compiled event code - decompile to reach it.

**Reference implementations:**
- WolfDawn (not bundled; upstream `https://gitgud.io/zero64801/wolfdawn`, build its `wolf` CLI from the tag recorded in `DAZEDTL_ROOT/util/wolfdawn/bin/PROVENANCE.md`; the binaries are not bundled because upstream declares no license) - full Rust framework: unpack + decompile + string extract/inject + database editor + save fixer + round-trip verify, plus box-geometry relayout (`relayout` / `desc-relayout`), font diagnosis (`font-check`), symbol normalization, surgical renames (`rename` + `verify-semantic --baseline` + `xref`), and exe-string patching (GUI Exe Text). **Copy/use this** - it's the mature path.
- `tools/C++/Wolf/` - `wolf_rpg_decode` and `wolf_unpack` (Rust sources plus prebuilt `target/release/*.exe`), `parse_ce.py`/`analyze.py` and the `RE/` notes. The IDA `.i64` databases and decompiled CommonEvent dumps are not bundled.
- **Wolf + Mistral pipeline** (prompt, glossary, build scripts, runtime-key locking): `tools/Game Translation/Reference Pipelines/Wolf RPG (Pachimon)/` - `prompt.md`, `glossary.md`, `translate_mistral.py`, and the `build_*`/`dump_db_structure.py`/`sync_runtime_lookup_terms.py` scripts that separate visible DB/UI text from protected runtime lookup keys.
- **Wolf + Claude pipeline, with relayout + font/symbol fixes** (the mature, `wolf`-CLI + `mt-export` path): `tools/Game Translation/Reference Pipelines/Wolf RPG (Asuka)/` - `claude_translate.py` (2-phase Claude batch driver over the mt-export JSON, control-code multiset validation, JSON-escape repair, resumable retry), `relayout.py` (box-geometry reflow + portrait-aware width + page-splitting), `scan_all_strings.py`/`scan_display2.py` (residual-JP/symbol sweep), `fix_ui_strings.py`/`strip_ruby.py`, plus `scripts\examples\` (the event-side field-label override, DB-memo translation, cleanup patterns) and a `README.md` + `WOLFDAWN-GAPS.md`. Read this one for the font-resolution and relayout lessons.
- **DazedTL Wolf driver** - `DAZEDTL_ROOT/modules/wolfdawn.py` (resume ladder, nameplate pre-resolution, code repair), `DAZEDTL_ROOT/util/wolfdawn/db_classify.py` (sheet tiers + archetype), `DAZEDTL_ROOT/util/wolfdawn/names.py` (glossary harvest filter). Cited by line below where it matters.

## Workflow (WolfDawn CLI)

```bash
wolf unpack Data.wolf -o Data                     # 1. editable folder (v8/VER5/6/WolfPro/ChaCha20)

wolf pseudo Data -o Data-pseudo                   # 1b. SMOKE TEST before translating anything: copies
#   the folder and fills every string with deterministic gibberish (codes kept, names consistent,
#   width matched) through the real pipeline. Play it 5 min - anything that breaks, breaks on
#   throwaway text. To isolate a breakage: --skip <maps,common,db,gamedat,txt,names> and rebuild
#   (misbehaves with names but not without => renaming problem, not text).

# 2. extract - strings-extract is PER FILE (a bare dir arg means "folder of event .txt", not the game):
mkdir out
wolf strings-extract Data/BasicData/CommonEvent.dat    -o out/CommonEvent.json
wolf strings-extract Data/BasicData/DataBase.project   -o out/DataBase.json      # + CDataBase, SysDatabase
wolf strings-extract Data/BasicData/Game.dat           -o out/GameDat.json
for m in Data/MapData/*.mps; do wolf strings-extract "$m" -o "out/$(basename "$m").json"; done
wolf names-extract Data -o out/names.json              # names glossary takes the whole dir

# 3. translate - one MT batch for any LLM, or edit the JSONs' `text` fields directly:
wolf mt-export out/*.json -o batch.json --sentinel-mask   # every untranslated line + speaker/context,
#   with embedded instructions (keep codes verbatim, keep speaker voice, never edit id).
#   --sentinel-mask hides \codes as backslash-free {Wn} tokens so LLM JSON transport can't corrupt
#   them (restored automatically on mt-import) - use it for any external-LLM pipeline.
#   ... fill each empty "text" with the LLM ...
wolf mt-import batch.json out/*.json             # strict id+source matching; SAME files, SAME order
wolf names-fill out/names.json out/*.json        # copy glossary names onto exact-match lines
wolf names-wrap out/names.json                   # re-fit translated multi-line glossary entries (rumor boards) to their slot: nameWraps rules > JP-measured width (capped auto-expand) > font shrink with inline \f scaling; one-line names never wrapped
wolf names-check out/*.json                      # conflicts (exit 2) + stale names + width overflows + multi-box entries + positioning breaks
wolf layout-restore out/*.json                   # auto-repair broken positioning where unambiguous: a pad skeleton around ONE visible value gets the source's whitespace copied verbatim around the translation (the status-card <pad>\nなし -> None class); multi-value sources reported for hand repair. GUI: "Restore positioning" button on the warning panel

# 4. inject - copy the folder, strings per file, then names IN PLACE over the result (names layer last):
cp -r Data DataEN
wolf strings-inject out/CommonEvent.json --base Data/BasicData/CommonEvent.dat -o DataEN/BasicData/CommonEvent.dat --en-punct
#   ... same per DB pair / Game.dat / each map (add --dry-run first to preview applied/skipped/drifted) ...
wolf names-inject out/names.json --data DataEN --en-punct   # no -o: in place on the copy, AFTER strings

wolf relayout DataEN --width auto --width-face auto --max-rows auto --orig Data  # 5. reflow EN text; auto = box geometry measured from the JP corpus (the dev filled the box they built: K-th widest shipped row / K-th tallest message, outlier-robust, unresolved \cself rows excluded). --orig points at the untranslated Data; .bak siblings work too. Type numbers to refine after an in-game screenshot (JP cells slightly over-state proportional English). Traumerei measured 85 cells wide where the old default assumed 68 - wrong defaults are why relayout "kinda works kinda doesn't" on wide-box games.
#   (measure width/rows in-game; no -o = dry-run count; idempotent). \cself/\cdb inserts are measured
#   at their REAL database field width; --sub-width 0 auto-calibrates the unresolvable ones.
wolf desc-relayout DataEN/BasicData/DataBase.project --width auto --orig Data/BasicData/DataBase.project -o ...  # 5b. fixed desc boxes; auto = each type's box measured from the pristine DB's own JP text (prints the per-type geometry - persist it as descBoxes in wolfdawn-roles.json once refined)
wolf font-check DataEN/BasicData/Game.dat        # 5c. prove the Font face resolves + covers every glyph

wolf pack DataEN -o Data.wolf                    # 6. repack (OR ship DataEN/ loose - engine reads loose first)
wolf save-update save.sav --game DataEN/BasicData/Game.dat  # 7. fix player saves
```

`wolf translations-merge --old old/ --new new/ -o result/` carries forward translations to a new game
version so only new text needs translating. `wolf roles Data` dumps every DB field's classification
(machine-readable) when you need to see what the extractor will and won't touch.

## Exit codes, inject outcomes, diagnostics

**`wolf` exit codes are distinct failure classes - never collapse them into "failed".**

| code | meaning | where the fix lives |
|---|---|---|
| 0 | success | - |
| 2 | round-trip mismatch / inject guard skip / name-consistency failure | the JSON content |
| 4 | read / parse / write / crypto failure | I/O, wrong key, missing file |
| 64 | usage error | your command line |

`DAZEDTL_ROOT/util/wolfdawn/__init__.py:11-15`

**Exit 2 still writes every good line.** Treat any positive applied count as success and report the skips as warnings, or a mostly successful inject reads as a total failure.

**The four inject outcomes are not equivalent.** `applied`. `untranslated` (text equals source - a benign no-op, count it as untranslated and never as a safety skip). `drifted` (the base no longer holds `source` - a file-level baseline problem, not a translation problem). Per-line safety skip (the guard rejected the codes).

Per-line diagnostics parse as `^<locator>: (control-code mismatch|text not representable in Shift-JIS)<rest>$`. **Resolve every locator structurally back into the live JSON** so "12 lines were skipped" becomes 12 editable rows:

| locator form | JSON path |
|---|---|
| `db type N row N field N` | `group.type` → `line.row`, `line.field` |
| `event N [page N] cmd N str N` | `scene.event` (+ `scene.page` when present) → `line.cmd`, `line.str` |
| `gamedat <key>` | `line.key` |

Return both the line dict (so `source` and `text` can be diffed and edited) and a stable locator id the edit UI can reuse.

**"0 applied, N drifted" almost always means stale `source` fields, not bad translations - rebase, do not re-extract.** Re-extract the *pristine* original to a temp JSON, walk both documents collecting every dict that carries both `source` and `text` keyed by its tuple path through the structure, **refuse outright if the two key sets differ** ("document structure differs from the pristine extraction") rather than repairing partially, and otherwise copy `source` across and nothing else, leaving every `text` untouched. Re-extracting the whole JSON to fix the same symptom throws away every translation.

Baseline hygiene around that: keep a pristine snapshot tree mirroring the data dir path for path, make sure paired schema and data files are both present (backfill a missing `.dat` sibling for a `.project`), and restore the live tree from the snapshot before the first inject pass.
Preflight the names pass with a dry run - if it would apply 0 changes while the names file holds edits, force-rebuild the originals from the archives and retry.
Re-run the dry run *after* a successful inject too.
Still-pending changes mean a partial apply, which otherwise reads as green.

## Where the text hides: event command codes

**Most of a Wolf game's UI text lives in the ARGUMENTS of common-event calls, not in Message commands.** Code 300 dispatches on the callee's Japanese name in `stringArgs[0]`.

| code | recognized by | text |
|---|---|---|
| 300 | `stringArgs[0]` = `[共]汎用ウィンドウ生成`, `選択肢/確認` | question in `stringArgs[2]`, whole choice list in `stringArgs[1]` as ONE comma-joined string |
| 300 | `BTLメッセージ`, `X[移]メニュー時文章表示` | plain dialogue in `stringArgs[1]` |
| 300 | `援護文章` | `@N\nName：\nbody` - needs its own speaker regex |
| 210 | `intArgs[0] is None` and exactly 2 stringArgs | speaker setter, name in arg 1 |
| 210 | `intArgs[0] == 500725` | log message |
| 250 | `stringArgs[1] == "万能ｳｨﾝﾄﾞｳ一時DB"` | generic-window DB write - strip existing `\f[\d+]` before setting |
| 122 | SetString | filter before translating: skip `\.[\w]+$` (filenames), anything containing `_`, `",` or `/`, and anything with no Japanese at all |
| 150 | picture text | shrink each `\f[N]` by 2 on write-back - English needs more room in a picture |
| 101 | message | supports `@N\nName：\nbody` and the prefix-less `Name：\nbody`. Write back with `str.replace(initialJAString, translatedText)` so the `@N` header and nameplate stay byte-identical |

**A comma inside a translated choice string silently adds a menu option.** Rewrite every `", "` in a translated choice to `"、"` before re-joining the list with `,`. "Yes, of course" otherwise splits a 3-option menu into 4 broken entries, and players report it as a game bug rather than a translation bug.

Mapping each common event by its Japanese name is per-game work. Knowing the text lives in call arguments is what tells you to look before playtest finds the gap.

## DB sheet triage (do this before the first API call)

**Classify every DB sheet into a tier first - Wolf games hide narrative in custom sheets and boilerplate in the standard ones.** Scan the staged `files/*.json` and bucket every `groups[]` sheet into `foundation` / `system` / `narrative` / `unknown`. Classification order, first match wins:

1. **narrative** if `typeName` matches `CUSTOM_SHEET_RE = /^[■├]|イベント|セリフ|プロフィール|MOB|感想|所持アイテム|CG/`
2. **foundation** if the Japanese half is in `STANDARD_SHEETS_JP`: 武器 / 防具 / 技能 / アイテム / 状態設定 / 用語設定 / 戦闘コマンド / システム設定 / 属性名の設定 / 主人公ステータス / 敵グループ / 敵ｷｬﾗ個体ﾃﾞｰﾀ
3. Otherwise count field-name hits and let the largest win, with narrative needing a strict majority:
   - dialogue: `セリフ|コメント|相手|行為|台詞|会話|メッセージ_`
   - standard: `説明|Description|商品説明|セーブ|ロード|使用時文章|発生時の文章|回復時の文章`
   - system: `メッセージ|Message|タイトル|用語|Terms?`

`FOUNDATION_TIERS = {foundation, system, unknown}` are translated by default. Narrative sheets are deferred until foundation lands, so a broken glossary is caught on cheap text.

**Archetype tells you where the budget goes.** Count lines by extraction kind (db / map / common / gamedat / txt-dir), then:

| archetype | test |
|---|---|
| `simulation_db_heavy` | `db_lines/total > 0.5` AND `narrative_lines/db_lines > 0.4` |
| `classic_rpg` | event lines exceed db lines by more than 2x AND narrative db lines are under 20% of db lines |
| `hybrid` | everything else |

`DAZEDTL_ROOT/util/wolfdawn/db_classify.py:132` (ordering), `:244` (distribution), `:283` (archetype thresholds).

Glossary seeding from the DB is gated separately from translation: harvest only fields matching `マップ名|属性名|用語名|コマンド名|タイトル|Name|Title|名称|称号|好きなもの`, exclude anything matching `説明|Description|文章|メッセージ|セリフ|コメント|行為|相手|台詞|会話`, and cap the harvested string at 72 characters.

## What matters

- **Decompile → readable WolfScript.** Event code (maps, common events) decompiles to editable script. Unchanged code round-trips byte-for-byte (`wolf` verifies). This is safer than raw binary patching.
- **Glossary consistency is critical** - Wolf games do by-name lookups (a renamed monster/item breaks the reference). `wolf names-inject` renames every mirror together (DB cell, stored row name, cid250/251/252 lookup operands, cid112 condition literals). `wolf names-check` catches divergent translations AND stale names (glossary-translated but left raw in another file - a SetString→lookup chain would break. `wolf names-fill` is the one-command fix). This is more important here than in most engines.
- **Displayed DB *field names* (`dataID=-3`) sit outside the whole translation model.** An event can draw a field's NAME by reading `Database(typeID=T, dataID=-3, fieldID=F)` into a string var, then drawing it (e.g. `行動力:10`). WolfDawn's names/roles/extract only track string CELL values, so an INT field's *name* read this way is invisible to every tool and to `names.json`/`roles.json`. The name lives ONLY in the `.project` schema plus as by-name lookup operands in `CommonEvent.dat` - the compiled `.dat` has no field names at all. **Do NOT rename the schema field to translate the label.** (Tried it as a length-prefixed binary patch of the `.project` strings: it passed `verify-roundtrip` clean, then broke at runtime - the cid250/251/252 by-name lookups failed, surfacing as a `□DB … <type> … Common48` DB-access error on boot.) Fix it EVENT-SIDE: override the string where the event sets it, extending the game's own per-index override pattern (a `when (loop==N) SetString CSelf[x] = "..."` per field index). See `Reference Pipelines/Wolf RPG (Asuka)/scripts/examples/translate_reqlabels.py`.
- **Read the safety fields in `names.json`** - every entry carries `"safety"`: `safe` (display-only, nothing looks it up), `refs` (looked up by name, but injection renames the references too), `verify` (also sits in a SetString/event-input literal - test in-game). Header `"dynamic_lookups": 0` means the game builds no lookup names at runtime, so every rename is statically provable. Engine registries (variable-name tables, colour/asset slot labels, 基本システム用変数) are auto-excluded (`"registry_skipped"` counts them) - they're editor labels, never player text. Leaving them untranslated can never break anything.
- **Harvesting DB names into the GLOSSARY needs a stricter filter than translating them.** On top of the safety badge, skip any candidate that contains a newline, runs longer than **72 characters**, whose category note matches `プロフィール|説明|セリフ|台詞|会話|自己紹介|挨拶|モノローグ|独白`, or that contains two or more of `。！？`. Those are dialogue-shaped rows sitting in a name field, and a glossary entry built from one poisons every later batch that tries to match it as a term (`DAZEDTL_ROOT/util/wolfdawn/names.py:38-46`). **A name refused for translation stays in the file with `text == source`** rather than being filtered out - inject then counts it as a benign untranslated no-op and the untranslated total stays a meaningful number instead of silently shrinking.
- **Misclassified DB fields**: don't patch the tool - drop a `wolfdawn-roles.json` next to the data dir: `{ "name": [...], "content": ["Type/Field"], "internal": [...], "keepRowNames": ["BGMリスト"], "skipRowNames": [...] }`. All `strings-*`/`names-*` commands pick it up automatically (e.g. `keepRowNames` re-includes a registry for a music-room game that displays BGM titles).
- **Control codes**: see [Control codes](#control-codes-the-guard-is-graded) below - the guard is graded, not exact-match, and the JSON transport (not the model) is what corrupts codes.
- **Positional whitespace** (Traumerei status screens): DB fields center a value in a fixed-width slot with pad spaces, often spanning a `\n` (`"　　　　　　　　なし"`, field names even declare the slot: `直前の相手(全角17字)`). MT reliably collapses the padding, and the text then renders in the wrong place or overlaps the next label. The inject guard cannot hard-reject this (single newlines and spaces are legitimate rewrap material in dialogue), so it is a LINT: `wolf names-check` flags whitespace-positioned sources before translation (Traumerei: 220 of them) and flags translated lines whose whitespace skeleton degraded (fewer pad runs, or a changed newline count). Prevention: `wolf mt-export --sentinel-mask` also masks pad runs as `{Wn}` tokens (whole run, including a spanned `\n`), so the LLM just echoes the token and the padding survives byte-exact - `"{W0}なし"` comes back as `"{W0}None"` and unmasks to the original pad + `None`. For hand fixes, keep the source's whitespace shape around the translation and re-center for the English width (the `(全角N字)` hint gives the slot: N fullwidth = 2N cells).
- **Fixed-slot multi-line DB fields** (Traumerei rumor board, `ロ：町のウワサ0`): a translation that changes a field's LINE COUNT spills into the next slot and entries render on top of each other. No relayout pass touches these. See [Fixed-slot DB fields](#fixed-slot-multi-line-db-fields) below.
- **names-inject output is a MATCHED SET.** The DB row names and every by-name event operand are renamed in one pass. Cherry-picking single files out of the `-o` output (or re-copying an older file over one of them) splits the rename and by-name lookups crash: `【DB操作】タイプN には以下のデータ名は存在しません`. Reproduced on Traumerei: full adoption = 0 new danglers. Adopting only the renamed CommonEvent.dat = 17 dangling `[Character Sprite] Character` lookups, the exact runtime error. `wolf verify-semantic <dir> --baseline` on the assembled folder catches a split statically - run it whenever files were mixed between inject generations. This is also the real story behind "refs names are not safe to translate": REFS renames are safe *as a set*. They break when the set is torn apart.
- **Loose vs repack**: the engine reads a loose `Data/` folder before `Data.wolf`, so you can ship loose files (chamber-game does) - tighter iteration, no repack. Repack only for clean distribution.
- **Encryption**: WolfPro + ChaCha20 must be handled by the unpacker (WolfDawn does it natively. No external tool).
- **Save fixing**: Wolf bakes strings (incl. Title) into saves. `wolf save-update` handles standard + GamePro Pro formats. Rewrites baked strings + title so JP/old saves load in the translated build. Chamber-game shipped a standalone `Fix Save.exe` that auto-translates on load.
- **Width**: **measure it, do not assume.** Shipped games run 55-85 cells (Asuka 68 plain / 55 with a portrait, Traumerei 85), and a wrong default is why relayout "kinda works kinda doesn't" on wide-box games. `--en-punct` converts JP punctuation to ASCII, and `wolf names-check` width-lints translated lines (flags a line whose widest row grew >30% and at least 8 cells past the source). Some engine width limits are hard - the 8bitMonster README notes button text still clips - so shorten UI labels to fit fixed sprites.
- **`strings-extract` deliberately SKIPS symbol-only strings.** Rows with no translatable words (`・・・`, `！？`, `＜Lunch Break＞`, `＞[￥８００]` price rows) never reach `--en-punct`, so their fullwidth punctuation tofus in a Latin window font. **`wolf normalize-symbols <data-dir>` handles this natively**: ASCII-folds fullwidth punctuation and digits, `・・・` to `...`, `▶` to `->`, `≒` to `~`, in display literals only. No `-o` means dry run. For residual-JP sweeps and model-glyph lookalikes (Cyrillic or hangul leaking into names) see `scripts\scan_all_strings.py` / `fix_ui_strings.py` in the Asuka pipeline.
- **Inject order + safety nets**: strings per file FIRST, names pass LAST and in place over the result (it must layer on the string-injected files). Whichever pass runs SECOND must take the live, already-patched binary as its base - pointing it back at the pristine original rebuilds the file from Japanese and silently reverts everything the first pass wrote. `--dry-run` on both injects runs the full pipeline - guards, re-parse verification, per-file applied/skipped/drifted - without writing a byte. Every written file is re-parse-verified. `wolf verify-roundtrip --corpus DataEN` as a final gate. **`verify-roundtrip` catches binary drift, NOT semantic breakage** - it proves decompile→compile is byte-equal, it does not know a name is used as a by-name DB Operation key elsewhere (a manual `.project` field-name patch passed roundtrip clean and still broke cid250/251/252 lookups at runtime. `names-inject` is safe because it rewrites the cell + operands + condition literals together, manual edits are not). The semantic gate is `wolf verify-semantic`.
- **Post-translation renames: use `wolf rename`, bracketed by `verify-semantic --baseline`.** In-game testing WILL surface names that overflow fixed-column UIs (a weekly schedule slot holds ~12 cells. A list column ~20). Shortening them by editing the DB is the classic lookup-breaker - instead `wolf rename "Swimming Class" "Swimming" --data Data [--dry-run]` renames the DB rows + name cells + every by-name operand together and leaves dialogue prose alone. Safety check: `wolf verify-semantic Data --baseline sem.txt` BEFORE the edit (snapshots pre-existing danglers), same command AFTER (fails only on NEW danglers). The absolute dangler list is a superset of real breaks - ops that resolve by numeric index carry their name as a dead annotation, and *stock JP games ship mismatches* (Asuka: lookup key デリヘル vs row 手コキ屋) - so only the delta means anything. `wolf xref "<name>" <dir>` shows every reference tagged by role (display / lookup-name / annotation) when you need to see what a rename will touch.
- **Text hardcoded in the exe**: gamepad button labels (`ボタン1..15`), a few menu strings, and Config.exe's dialog live as null-terminated UTF-16LE in the executable, not in game data. WolfDawn Studio's **Exe Text** section scans Game/GamePro/Config.exe, pre-fills known strings, and byte-patches same-length English in place (space-padded, longest-source-first, backup to `<exe>.wolfdawn-bak` - file size never changes so internal offsets stay valid).

### Fixed-slot multi-line DB fields

Some DB entries are drawn in a slot **N lines tall**, and the line count is load-bearing. Traumerei's rumor board (`ロ：町のウワサ0`) draws exactly 2 quote lines split by one `\r\n` or `\n`.

**A translation, or a tool-side wordwrap, that changes the line count spills into the next slot and entries render on top of each other.**

- **No relayout pass will save you.** `wolf relayout` only rewrites Message commands and `desc-relayout` only `説明` fields. Neither touches these, and the damage happens at translation and wrap time rather than at relayout time.
- **Detection:** `wolf names-check` flags translated DB entries whose newline count drifted from the source (`説明` exempt).
- **Rule for translators:** in DB fields, treat line breaks as **slots, not as wrapping**. Same number of `\n`, shorter lines.

When the fixed-slot strings live in the NAMES glossary rather than a DB field (Traumerei's `├■街の噂（MOB）` category is 77 natively multi-line "names"), `wolf names-wrap names.json` re-wraps translated entries to the slot:

- **width** = the category's widest JP line. Treat that as a **FLOOR, not a budget** - short JP rumors under-state a wide board, so calibrate `--width N` from a screenshot. `--note <substr>` targets one category.
- **line budget** = each entry's own JP line count.
- All widths are halfwidth cells: 1 ASCII = 1, 1 fullwidth = 2.

**Persist per-category geometry as `nameWraps` in `wolfdawn-roles.json`**, then plain `wolf names-wrap names.json` (or the GUI Wrap-names button) applies each category's own slot:

```json
{ "nameWraps": [ { "note": "街の噂", "width": 64, "maxLines": 2, "font": 18 } ] }
```

A `maxLines >= 2` entry also opts that category's ONE-line entries into wrapping. That is explicit opt-in only.

Two fallbacks make auto mode land without config:

1.
**Auto-expand, capped.** When the JP floor cannot hold the translations' line budgets, the width expands to the smallest that does, capped at ~1.4x the floor.
That covers the normal EN-wider-than-JP gap (Traumerei's rumor board: floor 50 cells, real slot ~64-68).
Anything needing more takes the shrink instead, because **a shrunk line always stays inside the board while an over-expanded one gambles on width the board may not have.**
2.
**Shrink with scaled inline codes.** An entry that still cannot fit gets the desc-relayout treatment: the largest `\f[N]` that fits is prepended, and the string's own inline `\f` codes are SCALED with it (`\f[20]`/`\f[18]` becomes `\f[14]`/`\f[13]`), preserving relative emphasis.
The native px auto-derives from the JP source's last `\f` code, which is the body size it settles on, else set `font` in `nameWraps`.

Only an entry that fails all three (rewrap, expand, shrink-to-minFont) is reported unfit.

**One-line names are NEVER wrapped** - shorten those with `rename`. An entry that cannot fit is left untouched and reported. A wrapped name stays lookup-safe because `names-inject` renames the DB row and every by-name operand to the identical `\n`-bearing string, verified as 0 new danglers via `verify-semantic`.

## Control codes: the guard is graded

The general masking and placeholder-validation contract is in `llm-pipeline.md`.
What follows is Wolf-specific: which codes exist, and where the guard must be
graded rather than strict.

**Grade the code guard instead of demanding exact token equality.** An exact-match guard fires on legitimate translator actions, the operator turns it off wholesale, and real corruption ships. Compare `\r[...]`, `\c[...]`/`\cself[...]`, `\f[...]` and generic `\x[...]` as **ordered** sequences, then allow exactly three drifts:

1. **Font size.** Normalize `\f[N]` to `\f[_]` and exclude font tokens from the non-font compare. Shrinking the font to fit longer English is what relayout is *for*, so a font-size difference is a signal, not a defect.
2.
**Ruby removal.** Accept a translation that drops **all** `\r[kanji,kana]` tokens when every other non-font token matches exactly.
**Drop ruby wholesale.
Never render it in place as `\r[life,life]`.** English has no furigana and the doubled reading renders as noise.
Dropping the ruby wholesale is the correct output (`strip_ruby.py` in the Asuka pipeline does exactly this).
Partial ruby loss is still a defect - all or nothing.
3. **Unclosed source codes.** Shipped Wolf events sometimes end a physical line with a bracketed code missing its `]` - `\\[A-Za-z]+\[[^\]\r\n]*(?=\r?$)` in MULTILINE - which the extractor keeps as one malformed protected token. Accept a translation that merely adds the `]` when the repaired source and the translation have identical token sequences.

**The multiset also counts blank-line page breaks** (runs of 2+ newlines). Many games pack several textboxes into ONE string separated by `\n\n`, and an LLM that collapses or drops one silently destroys the pagination - no relayout can recover it because the structure is gone. A changed `\n\n` count skips the line, same as a dropped `\code`. Single newlines stay free (soft wraps relayout rewrites), so ordinary dialogue is unaffected. `wolf names-check` flags multi-box entries *up front* from the source (a "packs N textboxes" note), so run it right after extract to see which DB entries a whole-file MT pass could break before paying to translate them - hand-translate or exclude those.

A custom per-box code like `\D[342]` needs no config: any `\code` is already a must-preserve token, so the guard protects arbitrary game-specific codes without knowing what they mean. The only structure it cannot protect is a separator expressed as plain text (no `\code`, no blank line) - rare, and uncatchable generically.

### Deterministic pre-inject repair, in this order

Peel any leading window prefix (`@<option>\n`) off both sides first and prefer the translation's own, falling back to the source's. Then:

```
1. Undo a prior repair pass's duplicated font prefix — ONLY when the source begins with a
   non-font code before its first font, both translated fonts are identical, and it is the
   translation's only extra font.
2. Literal "\n" -> real newline ONLY when
       text.count('\\n') == source.count('\n') - text.count('\n')
   exactly. Never globally.
3. Two-char escapes (\^ \. \!): replace one occurrence of the space-injected form "\ ^".
4. Whitespace inside a bracketed code: repair ONLY when source and translation carry the same
   number of code tokens in the same order. Zip them; if any token's whitespace-stripped form
   still differs from its counterpart, return the text untouched.
```

**Missing, extra or reordered tokens are never guessed.** A repair that reinserts `\c[6]` at a plausible position mis-colours or hangs the line. Leave those to the guard and fix them in the JSON. (`DAZEDTL_ROOT/modules/wolfdawn.py` - repair order and bail-outs.)

**Earn `--allow-code-drift` per document, never pass it globally.** Allow it only when the drift is font-size-only, or a safe ruby removal, or the translation merely closes a malformed source code, AND the document has no non-font code drift anywhere. Detect font-only drift by normalizing every `\f[N]` to `\f[_]` and comparing token sequences, and accept the case where wrapping added a leading font code the source never had as long as the non-font token sequence is still identical.

### The JSON transport corrupts codes, not the model

**For an external LLM JSON pipeline, mask every code to a sentinel before the LLM and restore on import.** Do not trust textual instructions - the *transport* corrupts codes regardless of model compliance. An LLM emits `\f`/`\r`/`\cself` into JSON where `\f` decodes to a form-feed char and `\r` to CR (silently applied, then have to be un-mangled), and `\cself` is an *invalid* JSON escape that fails the whole request's parse (lost 127/477 text-batch requests until the parser was hardened with invalid-escape repair + `json.loads(strict=False)`, and the FF/CR corruption reversed - see `scripts\repair_batch.py` and `claude_translate._repair_json_escapes`). Sentinels contain no backslash, so code corruption becomes physically impossible. **`wolf mt-export --sentinel-mask` does this natively** (codes hidden as `{Wn}` tokens, auto-restored on `mt-import`), and it masks positional pad runs the same way.

## Speakers and nameplates

**Split first-line speaker detection into two confidence tiers and only make the weak tier configurable.**

- **Confident:** a face or name-window command precedes the message, so line 1 is a real nameplate. Always reshape it, no toggle.
- **Weak:** line 1 is short, carries no control codes and no sentence punctuation, with no preceding face window. A guess. Reshaping the weak tier in a game that does not use nameplates converts the opening clause of thousands of lines into a fake speaker label, and it is unrecoverable without re-extraction. Resolve it **once per game**, not by global heuristic: show a model a sample of those entries, require exactly `LOWCONF_FIRSTLINE: ENABLE|DISABLE` back, and persist the ruling per game.

**Bare speaker-line games** (Traumerei style): the speaker is a plain first message line (`市民\nセリフ…`) that a custom message system pops into a name plate - merging it into the reflow renders the WHOLE dialogue as the giant speaker name. `wolf relayout` auto-detects the convention corpus-wide (recurring name-like first rows heading ≥30% of multi-line messages) and then keeps those lines as headers, repeated on page splits like `[Name]`. It prints the verdict. `--speaker-lines` forces it for a corpus too small/odd to detect, `--no-speaker-lines` kills it. If the relayout report does NOT mention the convention on a game whose dialogue shows names above the box, check before injecting.

**Pre-resolve the speaker name to English before translation and let it outrank the model's echo.** Peel any window prefix (`^@[^\n]*\n`) off verbatim, look the nameplate up in the glossary with ranked sections (Game Characters above Speakers above everything else, alias- and honorific-aware), fall back to a cached model call, and send the body as `[EnglishName]: body`. On write-back accept the model's tag **only** when yours is still Japanese and the model's contains no Japanese. If the model dropped the tag entirely, peel a leading short (≤20 chars) Japanese first line off the body as an echoed nameplate. Trusting the model's tag gives a different English spelling of the same character in different scenes.

## Resume: what counts as already translated

**Japanese left in a nameplate or inside a control code does NOT mean the line is untranslated.** The naive test ("text still contains Japanese") retranslates the whole game forever. The ladder (`DAZEDTL_ROOT/modules/wolfdawn.py:334-346`):

1. Empty/whitespace `text` → needs work
2. `text == source` (fresh extract) → needs work
3. No Japanese anywhere → done
4. Otherwise test **only the BODY**

Body test (`:311-331`): strip the `@<option>\n` window prefix, then drop line 1 when `speaker_src` is a known first-line format (`literal_line1`, `literal_line1_lowconf`, `ui`, `narration`) OR line 1 is 1-20 chars and contains Japanese (a nameplate the model echoed), and finally remove every inline control code with `_WOLF_CODE_RE` (`:124`).
That last step is load-bearing: ruby like `\r[我,わ]` legitimately keeps Japanese in a fully translated English line.

Because `source` stays Japanese forever, every resume decision must come from `text`. A line whose body is already English but whose nameplate is still Japanese gets the cheap `_maybe_fix_nameplate` pass (`:572-580`) instead of a full retranslation billed twice.

## Font resolution (the #1 tofu cause)

**Before blaming extraction, check the font.** If EVERY non-ASCII glyph (CJK, `★`, fullwidth punctuation) renders as tofu / boxes, the `Game.dat` `Font` face is not resolving. Wolf draws with GDI `CreateFontW`, which matches on the **face name only** and silently falls back (usually to MS Sans Serif - no CJK, no `★`) when the name does not match an installed face.

- **A style suffix in the face name breaks matching.** `Game.dat` Font `"源暎ラテミン v2 Medium"` fails on English-locale Windows - the trailing ` Medium` is a *style*, not part of the face name - so GDI falls back and every non-ASCII char becomes U+FFFF. Dropping the suffix (`"源暎ラテミン v2"`) resolves the real font. **"Installed" does NOT mean "resolves"** - test the exact face string via GDI.
- **Diagnose:** `CreateFontW` with the literal `Game.dat` Font string, select the HFONT into a DC, then `GetTextFace(hdc,…)` to see the face GDI *actually* picked. If it comes back `MS Sans Serif` (or anything other than requested), the name did not match. Glyph-test the corpus's non-ASCII chars with `GetGlyphIndicesW`/`GGI_MARK_NONEXISTING_GLYPHS` - `0xFFFF` = missing. (Note the window **SubFont** matters too: a `SubFont[0]="Arial Black"` renders any code-switched text with no CJK/★.)
- **Fix (best):** edit the Font in the `gamedat-json` output to a built-in CJK face that needs no install, then `wolf gamedat-apply`: **`"ＭＳ ゴシック"`** (MS Gothic - max Windows compatibility) or Yu Gothic (cleaner, Win10+). No font shipping, no per-machine install, works on any Windows. On this box no built-in *Mincho/serif* face had full coverage - only gothic did.
- **`wolf font-check <Game.dat>` does all of this natively**: resolves the Font face through GDI, reports the face actually picked, and glyph-tests the corpus's display chars (`--corpus <data-dir>`, `--glyphs <chars>`). Run it before shipping and after any font change.

## Text relayout & page-splitting (EN expansion - `wolf relayout` / `wolf desc-relayout`)

**WolfDawn now does this natively** - `wolf relayout <data-dir>` (post-inject pass, also a Relayout checkbox on the GUI's Inject) reflows Message text to the box geometry and page-splits overflow. `wolf desc-relayout` fits fixed description boxes. The Asuka `relayout.py` remains as the reference implementation the Rust port came from. Both are idempotent - re-run freely after glossary/text edits.

- **Cell model:** CJK = 2 cells, Latin = 1. Box is ~N cells wide × **4 rows** max (measure N in-game - JP percentiles under-fill. Asuka's boxes were 68 plain / 55 with a portrait). Refill-wrap = merge the source's rows back into a paragraph, then greedily re-wrap to width. Deliberate layout (blank rows, indented rows, tables) is preserved.
- **Cell counts over-state English capacity.** The cell model assumes Latin = half a full-width glyph, but proportional CJK fonts (MS Gothic) draw typical English *wider* than that. A width measured from the widest JP line over-states what English fits (Asuka armor: JP-measured 97 cells, real English capacity ~84). Calibrate conservatively and adjust from in-game screenshots. One reported overflow usually means the whole column's width was optimistic, not that one string is special.
- **The extreme case: Latin at FULLWIDTH advance** (Traumerei). Some games draw text fixed-pitch at zenkaku width - each English letter occupies the same width as a kanji, so ~31 English chars fill the board line that ~32 kanji fill. The standard half-width charge then under-counts English **2x** and every width feature over-fills boxes ("62 cells fits the 64-cell board" while 62 chars really occupy 124 cells). Diagnose from a screenshot: count how many English letters fit one line vs how many kanji - near 1:1 means fullwidth Latin. Set `{ "asciiFullWidth": true }` in `wolfdawn-roles.json` (Game rules window checkbox): the measurement core (`char_cells`) then charges ASCII 2 cells everywhere - relayout, width lint, names-wrap, desc fit - and the shrink fallbacks produce physically-true results (an 84-char rumor over a 2x32-char board correctly shrinks to ~13px or demands shorter text, instead of pretending to fit).
- **Portrait-aware width.** A message with an `@N` face prefix has a **narrower** usable width. Which `@N` ids actually draw a portrait comes from `SysDatabase` type 24 (顔グラフィック名): an id with a non-empty 顔画像ファイル draws a bust. Ids 0 - 9 are window-**style** selectors with no image. `wolf relayout` builds this set from the DB, and tracks the face across messages (a plain message inheriting an earlier `@N` still uses the narrow width).
- **Variable inserts are not zero-width.** `\cself`/`\cdb`/`\udb` insert a runtime DB value. `wolf relayout` resolves each insert's real field width from the databases (per-event CSelf tracking), with `--sub-width 0` auto-calibrating a fallback budget from the game's own name-field widths. Without this, lines with inserted names overflow at runtime while looking fine in the extract.
- **Page-split overlong messages** into continuation `Message` commands at sentence boundaries: repeat the `@N` prefix + `[Name]` header, re-arm stateful codes (`\c`, `\f`, `\font`, `\s`) on each continuation - they do NOT carry across a new Message command. (Under the hood: `decompile --mode edit` → edit → `compile`. WolfDawn rebuilds jumps + indent, so inserting commands is safe.)
- **Dramatic font sizes shrink the box.** A message enlarged with a leading `\f[25]`/`\f[30]` fits FEWER cells per row and fewer rows per box (at 1.25x, a 55-cell 4-row box is really 44×3) - text wrapped to the standard geometry overflows exactly at the punchlines. `wolf relayout` scales the geometry by `base/N` for uniformly-enlarged messages (`--base-font`, default ~20) and page-splits them like any dialogue. Smaller/mixed sizes stay as authored.
- **Fixed boxes that cannot page-split** (item/skill/armor descriptions drawn in an N-line window): `wolf desc-relayout <X.project> --width N` re-wraps first and shrinks the font with a leading `\f[N]` ONLY when the text cannot fit the line budget, and then only as much as needed. Per-field line limits auto-read from the `[N行]` hint in the field name - but **the hint can lie in both directions**: fields labeled `[2行まで可]` had JP originals using 3 lines in one menu, while another menu's box really was 2 lines and the JP "3-line" reading came from two outlier rows. Calibrate each category's line count from the JP MODE (typical usage), not the max, and confirm against in-game screenshots. `--keep-breaks` preserves semantic `flavor\nstat-line` splits (common in equipment descriptions). **Persist the per-category geometry in `wolfdawn-roles.json`** - `{ "descBoxes": [ { "db": "DataBase", "types": [0], "width": 75, "maxLines": 2 }, ... ] }` - then `wolf desc-relayout <X.project>` with no `--width` (and the GUI's Fit descriptions) applies each type's own box in one pass.
- **Composed UI strings shrink the first line's budget.** Some windows build one render string from parts (Asuka's gallery: `"\n" + size-comment + memo` drawn as a single string-picture) - the translated part's first line must fit `box_width - prefix_width`, and English usually needs a separator space the JP concatenation didn't ("cock.Apparently"). Find the assembly in the event (`SetString` append chains feeding one Picture/Message) before wrapping such text as if it owned the full line.

### The `　` indent is a MARKER, not just an indent - do not strip it upstream

Japanese aligns a quoted continuation line under the opening `「` with one
IDEOGRAPHIC SPACE. In English the box opens with a halfwidth `"`, so that pad draws
as a **two-cell indent under a half-cell mark** and reads as a stray space. The
obvious fix - strip it from the translation store - is wrong, and silently so.

`relayout`'s `deliberate_row()` is `blank || code-only || starts_with('　')`. That
pad is the author's **"this break is mine, keep it"** marker: a message with one has
each row wrapped on its own, and a message *without* one has every row merged and
refilled to the full box width. Stripping the pads in the store converted 26,281
units from "keep the author's layout" to "reflow as free prose", which is how a
message the author broke at 26/42/42 cells came back as one 76-cell line running
under the standing portrait that scene draws.

- **Strip it AFTER relayout, from the built tree**, through `strings-extract` →
  edit → `strings-inject` - never from the store the injector reads. This is the
  general "layout repair is a pass over the output" rule with teeth.
- **Restore the marker before relayout, because the model halves it.** The same pad
  comes back two ways: on one corpus **8,315 lines kept `　` and 20,118 folded it to
  an ASCII space**, and only the fullwidth one is a marker - so two thirds of the
  author's own breaks were being discarded before anyone noticed. Copy the pad back
  from the source line at the same index (never invent one: 0 lines had lost it
  entirely) and skip units whose line count no longer matches the source.
- **A block whose FIRST line is indented is a column skeleton, not dialogue** - a
  `\v[]` status card, `" [Name]\n \s[4]"`, `"\n Left x \cself[11]"`. Its pads are
  load-bearing. Leave ASCII-only indents alone as well: they are not the marker.
- **The continuation state-code prefix must be emitted AFTER the pad.** `\c[2]　text`
  does not satisfy `starts_with('　')`, so a carried colour code in front of an
  authored indent made that row non-deliberate on the *next* pass and the message
  re-merged. Fixed in WolfDawn, but it is the shape to look for in any similar rule.

### Wrap quality: widows, fragment continuations, hanging quotes

Three defects that every automated check passes and only a screenshot catches.
All three are fixed in `wolf relayout`; the reasoning is here because the same
traps recur in any wrapper.

- **A greedy fill makes widows.** A row overflowing by one word puts that word
  alone on the next line: `...didn't` / `I?`. Measured on one game, **2,964 widow
  rows, 1,984 of them a single word**. The fix is greedy-THEN-balanced: greedy still
  decides the line COUNT, then a DP re-breaks the same words into exactly that many
  lines minimising squared unused cells **including the last line**. Charging the
  last line is the whole trick - with a free tail the optimum *is* the greedy widow.
- **Pin the balanced result to greedy's line count.** That is what keeps the blast
  radius at zero: `min_fit_width`, the names-wrap ladder and `desc-relayout` all read
  `wrap_row(..).len()`, and a wrapper that can return a different count moves all of
  them. Decline and return greedy verbatim on anything unsafe (a row already over
  width, an unbreakable token, no widow to fix).
- **Balanced wrapping BREAKS blind page-splitting, so fix the pager first.** Today's
  chunker survives a second pass only because greedy fill is *start-index
  deterministic* - a break depends solely on which word a line starts at, so any
  contiguous run of rows re-merges and re-wraps to itself and `rows.chunks(budget)`
  may cut anywhere. Balanced rows are shorter, so re-wrapping a chunk of them yields
  different lines. **Defect 2 is a hard prerequisite for defect 1, not an independent
  quality item.**
- **Sentence-aware paging needs to see past a closing quote.** `split_sentences`
  required the ender to be followed *immediately* by whitespace, so `control."` and
  `didn't I?"` were not boundaries - and in a corpus that is almost entirely quoted
  dialogue that means **no** sentence is a boundary and the sentence packer never
  fires. Skip a run of closers (`" ' ” ’ 」 』 ) ）`) after the ender.
- **A continuation box should carry a whole unit, not the tail.** Pack pages with
  whole blocks and route an oversized prose block through the sentence packer, not
  straight to the row chunker. Cap the packing at "flat chunking + 1 box" so a
  prettier break can never cost the player more than one extra key press.
- **Quoting across a split follows the English continued-quotation rule.** Every new
  box of the same speech RE-OPENS with `"`, and the closing mark waits for the end of
  the speech - the absence of a closer is what tells the reader the same person is
  still talking. So: always open the continuation; close the box before it **only
  when the break lands on a sentence end**. Closing unconditionally produces
  `...for drinking water,"`, punctuation asserting the speech stopped where it
  plainly did not. Add the mark only where it FITS and only if the page still
  re-normalises to the same row count - appending one character changes the run's
  merged text, and a box that no longer re-reads as itself gets dropped through the
  fallback **unwrapped** (one 113-cell row shipped that way before a width sweep
  caught it).
- **Verify idempotency at runtime instead of arguing it.** Re-lay every emitted box
  exactly as the next run will read it (its own re-derived geometry, its own fixup)
  and only write a layout whose every box comes back unchanged. Ladder it: balanced
  → legacy → leave the message as authored. An improvement that is wrong on one
  message then degrades instead of shipping broken. **Count and report the
  fall-through** - the last rung emits text with no wrap and no page split, and a
  silent one reads as "covered everything".

### Relayout mechanics worth knowing before you measure anything

- **`relayout -o` writes a SPARSE tree** - only files whose message text changed.
  An A/B or idempotency comparison must overlay the output onto the input first, or
  it compares 56 files against 227 and calls the rest identical.
- **A whitespace sentinel containing a NEWLINE is the author's hand-pagination.**
  `mt-export --sentinel-mask` masks positional whitespace too, and one token expanded
  to eleven `　`, a newline, and one more `　`: pad out the line, break it, indent
  the next. That is Japanese pagination in Japanese cells, and English repaginates
  from scratch, so it is droppable markup for the same reason ruby is - keep it out
  of the must-preserve multiset. A whitespace pad with **no** newline is different
  and stays protected: it may be centring a label.
- **A portrait drawn by a `Picture` command is invisible to the face logic.**
  `relayout` narrows to `--width-face` from a message's `@N` prefix. This game draws
  its busts with `Picture(pictureNumber=2) "Picture/kao*.png"`, persisting across
  messages, in 66 files - no `@N` anywhere, so `width-face` auto-calibrates to
  `width` and every portrait scene lays out full width. The author's own row widths
  on those scenes are the only portrait-aware budget available.
- **Measure the built tree with the pipeline's own regexes.** A hand-rolled
  code-stripper written for a one-off width sweep ate the closing `]` of every
  `\i[126]`, and reported a 114-cell maximum and 25,420 rows over budget that did not
  exist. Import the tested pattern, and probe the scanner on a string you know before
  trusting any number it prints.
- **`Game.dat` is UTF-8 in current builds**, and the Font trap has a second form
  beyond the style suffix: the shipped face `MSゴシック` is written in **halfwidth
  katakana**, which `CreateFontW` does not match - the real face name is the
  fullwidth `ＭＳ ゴシック`. Same silent Arial fallback, same tofu.

## Gotchas (from 8bitMonster)

- Some games phone home for DRM/version check (8bitMonster pinged `jaxycreate.com`. Failure locked gallery/saves and cut the story). Patch the URL in `CommonEvent.dat` to `http://127.0.0.1:1/` and clear the fallback triggers to always boot retail mode.
- Fixed-width button sprites truncate long EN - abbreviate ("Mash to endure!" won't fit).
