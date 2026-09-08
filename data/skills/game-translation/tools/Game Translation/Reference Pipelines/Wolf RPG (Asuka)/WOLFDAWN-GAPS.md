# WolfDawn: gaps found and integration proposals

From a full JP to EN localization of a WOLF Pro RPG (明日香ヴァージンアイドルデビュー / Asuka Virgin Idol Debut), ~26,573 extracted lines, done with the `wolf` CLI plus a custom Claude batch driver (`claude_translate.py`).
Every claim is grounded in what actually happened on that run.
Feature proposals are sized against WolfDawn's current CLI surface and cross-referenced to sibling pipelines where a matching capability already exists.

## What WolfDawn already does well (keep, and credit)

This run reached ship quality because the core is solid. Do not disturb any of this.

- **Unpack / repack** across loose-folder, archive, WolfPro, and ChaCha20 layouts, natively. Encryption was a non-event.
- **`decompile --mode edit` / `compile` round-trip that reconstructs jumps and indentation from block structure.** This is the single most important thing WolfDawn does. It is what made it safe to insert new `Message` commands (page-splitting) and event-side string overrides without hand-tracking jump targets. Nearly every gap workaround below leans on it.
- **`strings-extract` / `strings-inject`** per file, with the code-multiset guard.
- **`mt-export` / `mt-import`** round-trip with speaker context.
- **`names-extract` / `names-inject` / `names-check` / `names-fill`** with safety classes (safe / refs / verify), plus `dynamic_lookups` and `registry_skipped` counts. `names-inject` correctly rewrites the DB cell, the cid250/251/252 by-name lookup operands, and the cid112 condition literals together. That is exactly right, and it is why glossary work was safe while manual schema edits were not (Gap 5).
- **`db-json` / `db-apply`, `gamedat-json` / `gamedat-apply`, `roles` dump, `pseudo` smoke test, `verify-roundtrip`, `translations-merge`, `save-update`.**

The gaps below are all additive. None is a defect in the above.

**Every gap below now has a working Python prototype** in `scripts/` (see the README's tool table), each tested against the real game data and importing a shared `wolfscript.py`. They are the reference for porting the features into WolfDawn. Where a proposal has extra design detail (widths, UI/CLI), it is under the gap.

## The gaps, prioritized

P0 = hit essentially every message-bearing Wolf game and cost the most time. P1 = high-friction, silent, or correctness-affecting, but narrower. P2 = real but low-frequency or external-pipeline-only.

### Gap 1 - No font-resolution diagnostic (P0)

**What happened.** This was the number-one time sink and the root cause of all tofu / box glyphs. `Game.dat`'s Font face was `源暎ラテミン v2 Medium`. WOLF renders through GDI `CreateFontW`, and on an English-locale Windows `CreateFontW` cannot match that face name. The trailing ` Medium` style suffix baked into the face name breaks matching, so GDI silently falls back to MS Sans Serif, which has no CJK, no `★`, no fullwidth forms. Every non-ASCII character rendered as U+FFFF tofu. Proven directly through GDI: requesting `源暎ラテミン v2 Medium` resolved to MS Sans Serif with `★` missing (glyph 0xFFFF), while requesting `源暎ラテミン v2` (dropping ` Medium`) resolved to the real font with `★` present. The failure looked like a translation or encoding bug for a long time before the font was implicated. The final fix pointed `Game.dat`'s Font at `ＭＳ ゴシック` (MS Gothic, built-in, no install). The lesson to enshrine: verify the font RESOLVES via GDI. "Installed" does not imply "resolves".

**Proposal.** `wolf font-check [Game.dat] --corpus <dir>`
- Print the `Game.dat` Font face verbatim.
- `CreateFontW` with that face, select the HFONT into a DC, `GetTextFace(hdc,...)` to report the actually resolved face. If requested does not equal resolved, flag it loudly. That is the style-suffix trap.
- Glyph-test the corpus's non-ASCII characters against the resolved font (`GetGlyphIndicesW` with `GGI_MARK_NONEXISTING_GLYPHS`, treat 0xFFFF as missing). List any missing glyph.
- Suggest built-in CJK fallbacks that resolve with no install: `ＭＳ ゴシック` (MS Gothic, max compatibility) and Yu Gothic (cleaner). Note the window `SubFont` too (a `SubFont[0]="Arial Black"` renders code-switched text with no CJK/star).

**Priority (P0).** It caused 100% of the glyph corruption, is invisible to every existing tool, and generalizes to essentially every Japanese Wolf game run on English Windows. `gamedat-json` already parses the Font field, so the read half is in-crate. The new surface is a GDI probe, which is fine given WolfDawn already targets Windows. No sibling pipeline has this.

### Gap 2 - No text relayout / wrapping (P0, biggest missing feature)

**What happened.** WolfDawn extracts and injects but does nothing about EN text expansion against message-box geometry. `--en-punct` is punctuation only, never geometry. EN runs 30 to 60% longer than JP, and Wolf boxes are fixed at 4 rows. This was built from scratch (`relayout.py`) and it is a large, high-value feature:
- **Refill-wrap** merged rows to a box width using a cell model (CJK = 2, Latin = 1), against a 4-row limit.
- **Portrait-aware width.** A message carrying an `@N` face prefix has a narrower usable width because the bust occludes part of the box. Which `@N` ids actually show a portrait is read from SysDatabase type 24 (顔グラフィック名): ids whose 顔画像ファイル is non-empty draw a bust, while ids 0-9 are window-style selectors with no image. The width was measured in-game (68 cells plain, 60 with a portrait) because the JP percentiles under-filled.
- **Page-splitting** overlong messages into continuation `Message` commands, split at sentence boundaries, repeating the `@N` + `[Name]` header on each continuation and re-arming stateful codes (`\c`, `\f`, `\font`, `\s`) at the top of each so styling does not reset mid-thought.
- **Idempotent merge-then-rewrap**, so it re-runs after glossary edits without compounding.

The page-splitting half is safe only because `decompile --mode edit` / `compile` reconstructs jumps and indentation.

**Proposal.** `wolf relayout <wscript-dir> -o <out-dir> --portrait-db <db.json> [--width N] [--width-face M] [--max-rows R] [--simulate]`
- Rewrapped wscript with continuation `Message` commands inserted. `--simulate` prints per-box row/width overflow without writing (mirrors `relayout.py`'s `simulate()` and `check_wscript()` gate).
- Greedy space-wrap with the cell model, deliberate-layout detection, sentence-packing within a per-box budget, header repetition, stateful-code re-arm. `layout_message()` is a pure function that ports cleanly to Rust. Note the portrait id set is game-specific and must be rebuilt from SysDatabase type 24 (do not hardcode Asuka's id set).

**Priority (P0).** Affects 90%+ of message text on any EN localization. Largest single missing feature, algorithms proven and generic.

**Crib from.** The SRPG Studio (Belphegor) pipeline already has wrapping. The Wolf path is silent. Port Belphegor's wrap contract and extend it with Wolf's portrait-aware width and page-splitting. `relayout.py` is the reference to translate.

**Design details (from working the feature out):**

- **Box width is game-specific, never hardcode it.** Cells-across is a product of resolution, message-window pixel width, and base font size, all of which a game can change. The stock basic-system box is ~40-50 cells, but this WolfPro game measured 68 plain / 60 with a portrait. So: (1) **auto-estimate** a starting width from the game's own config (resolution + window image + font size, all readable from Game.dat/SysDatabase), (2) let the user **override/confirm** via `--width`/`--width-face` (the prototype defaults these and makes them optional - pass one and the other keeps its default), (3) rows default to 4 but are overridable. The one thing that IS portable to automate is face **detection**: which `@N` ids draw a portrait always comes from SysDatabase type 24 (ids with a non-empty image), so the face-id set is derivable per game even though the specific ids and the width reduction are not.
- **Optional and adjustable.** Never force it into the inject pipeline. It is a separate, skippable pass that runs on a copy (like inject already does with `--dry-run`). Every knob exposed with a sane default: widths, rows, page-splitting on/off, code-rearm on/off, sentence-vs-hard split, leave-deliberate-layout-alone. A `--simulate` mode reports overflow and box counts before writing (the prototype has `simulate()` + a `check` gate).
- **Both CLI and GUI, one shared core.** Put the layout logic once in the WolfDawn core crate and call it from both the `wolf relayout` command and a WolfDawn Studio panel (WolfDawn already shares the decompiler/core crates between CLI and `wolf gui`). The GUI has a real advantage worth building: render the message in the game's **actual window skin + font + portrait** and let the user drag a width slider to see text fit or overflow live. That WYSIWYG preview solves the "widths are game-specific, measure in-game" problem without booting the game. The CLI keeps `--simulate` for scripted/batch runs.

### Gap 3 - Symbol-only strings the extractor skips bypass `--en-punct` (P1)

**What happened.** `strings-extract` intentionally skips strings with no translatable words (`・・・`, `！？`, `＜Lunch Break＞`, `＞[￥８００]` price rows). Reasonable as a translation filter, but those rows still contain fullwidth punctuation that tofus in the Latin window font (here the `SubFont` Arial Black), and because they are never extracted they never receive `--en-punct`. Add model-glyph artifacts (`▶`, `≒`, Cyrillic/hangul lookalikes leaking into names) and this needed a dedicated pass. `scan_all_strings.py` / `scan_display2.py` were written specifically to sweep the rows `strings-extract` skips, and `fix_ui_strings.py` normalizes them.

**Proposal.** Either is sufficient:
- `strings-extract --include-symbols` so `--en-punct` reaches symbol-only rows, or
- `wolf normalize-symbols <wscript-dir>` mapping fullwidth punctuation and known risky symbols to ASCII across all literals regardless of extraction eligibility, with a report of touched rows.

**Priority (P1).** Only 2 to 3% of the corpus, but silent (the extractor's own skip logic is why it is invisible) and it produces visible tofu. Cheap to add.

**Crib from.** `fix_ui_strings.py`'s `CHARMAP` and `literal_spans()` are the reusable core, `scan_all_strings.py`'s `FW_RISK` regex plus `SAFE` set is the detector.

### Gap 4 - Field-name-GET display labels (dataID=-3) are outside the whole translation model (P1)

**What happened.** A WOLF event can display a DB field's name by reading `Database(typeID=T, dataID=-3, fieldID=F)` into a string var and then drawing it (`行動力:10`). WolfDawn's names/roles/extract tooling only tracks string field cell values. An INT field's name read this way is invisible to every WolfDawn tool and to `names.json` / `roles.json`. Worse, the field name lives only in the `.project` schema plus as by-name lookup operands in `CommonEvent.dat`. The compiled `.dat` has no field names at all. Translating the label by binary-patching the length-prefixed field-name strings in `CDataBase.project` / `DataBase.project` broke the game: `verify-roundtrip` passed clean (109 files ok), but the by-name DB Operation lookups (cid250/251/252) failed at runtime, surfacing as a `□DB … 28 … Common48` type-28 access error on boot. The safe fix was an event-side string override, extending the game's own per-index override pattern (`translate_reqlabels.py` did this for all 14 T66 stat indices), never touching the schema.

**Proposal.** `wolf field-names-detect <data-dir>`
- Scan for `Database(dataID=-3, fieldID=F)` GET sites, resolve each to its schema field name, report every place a field name (not value) reaches a display command.
- Cross-reference each candidate against the cid250/251/252 by-name lookup operands so the tool flags which labels are load-bearing keys (unsafe to rename at the schema) versus pure display.
- Optionally emit an event-side override scaffold (SetString branches keyed by field index) so the translator extends the game's own pattern instead of editing the schema.

**Priority (P1).** These labels are player-facing and 100% invisible today, and the obvious fix (rename the schema) is a runtime-breaking trap that `verify-roundtrip` does not catch.

**Crib from.** `translate_reqlabels.py` is the reference for the safe event-side override. WolfDawn's own `names-inject` already locates and rewrites cid250/251/252 operands, so reuse that to build the "is this name a by-name key?" check.

### Gap 5 - `verify-roundtrip` does not catch semantic breakage (P1)

**What happened.** The field-name binary patch in Gap 4 passed `verify-roundtrip` (byte-for-byte reconstruction was perfect) and still broke by-name DB Operation lookups at runtime. `verify-roundtrip` validates the binary reconstruction layer only. It does not validate that a name used as a by-name DB Operation key elsewhere still resolves. The contrast that makes this actionable: `names-inject` is semantically safe (it rewrites the DB cell, the cid250/251/252 operands, and cid112 condition literals together). It is manual schema and DB edits that slip through.

**Proposal.** `wolf verify-semantic <data-dir>`
- Cross-check every by-name DB Operation operand (cid250/251/252) and cid112 condition literal against the current `.project` schema and registries. Report any operand that no longer resolves to an existing type/data/field name.
- Optionally run automatically as a warning inside `db-apply` / `gamedat-apply` when an edit changes a name used as a by-name key elsewhere ("you renamed field X, referenced by-name at 3 sites, those lookups will fail at runtime").

**Priority (P1).** It converts a silent, ship-breaking, "verify passed" failure into a caught error at edit time. Narrower than Gaps 1-2, but the failure mode is severe precisely because the existing verify gives false confidence.

**Crib from.** The operand-resolution logic already inside `names-inject` / `names-check`. Run that same check as a standalone invariant over arbitrary edits, not only during names-inject.

### Gap 6 - JSON-escape collision for external LLM pipelines (P2)

**What happened.** `mt-export` embeds textual instructions telling the LLM to preserve WOLF codes verbatim, and trusts the model to obey. An external LLM emits those codes (`\f`, `\r`, `\cself`) into JSON, where the transport itself corrupts them regardless of model compliance. `\f` decodes to a form-feed character and `\r` to CR (silently applied, then have to be un-mangled by detecting the form-feed/CR followed by `[`). `\cself` is an invalid JSON escape, which raises `JSONDecodeError` and fails the whole request's parse, so those translations are not applied until the parser is hardened. This cost 127 of 477 text-batch requests until the parser gained invalid-escape repair (backslash-doubling) plus `json.loads(strict=False)`, and the form-feed/CR corruption was reversed. The fix lives in `repair_batch.py` and the driver's `_repair_json_escapes`.

**Proposal.** `wolf mt-export --sentinel-mask` with matching restore in `mt-import`.
- Before handing text to the LLM, replace each WOLF control code with an opaque sentinel token (`{CTRL1}`, `{CTRL2}`, ...) drawn from a per-batch legend. On `mt-import`, restore each sentinel to its exact original code. Sentinels contain no backslash, so external JSON transport physically cannot corrupt them. Correctness stops depending on model obedience.

**Priority (P2).** Only external LLM pipelines are exposed (WolfDawn's own `mt-import` path trusts its own codes), so it is narrower. But it is cheap and turns a class of silent data loss into a structural impossibility.

**Crib from.** `repair_batch.py` and `_repair_json_escapes` show what corruption to prevent. The masking direction is new but small.

### Gap 7 - No way to trace where a displayed string comes from (P1)

**What happened.** The `行動力:10` label appears on screen but is in NO extracted string - it is read from a DB field name at runtime and composed into a display string. Finding its source took a long manual investigation: decompile everything, grep the literal (found only lookup operands), discover the `dataID=-3` field-name-GET, then follow the variable to the `SetString` that draws it. This "an untranslated thing is on screen but I cannot find what sets it" problem recurs on every non-trivial game.

**Proposal.** `wolf xref <term>` - a WOLF-aware cross-reference over the decompiled corpus that indexes command *operands*, not just string literals. Given a DB field, a string, or a variable, classify every hit by role:
- **display-literal** - drawn on screen (inside a display command literal).
- **lookup-name** - a by-name Database operand (internal key).
- **annotation** - only inside an editor `[n "..."]` label, not runtime.
- **var-set / var-draw** - for a `CSelf[N]`/`Sys[N]`, where it is assigned and where its `\cself[N]` form is drawn.
- **field-name-get** - the `dataID=-3` sites that display a field's name.

For the AP case this is a two-hop query: trace the field -> "read via `dataID=-3` into `CSelf[6]` at 55290" -> trace `CSelf[6]` -> "drawn in the compose `SetString` at 55322". Seconds instead of an hour. Pair it with `field-names-detect` (Gap 4) and "untranslated thing with no source string" is solved.

**Priority (P1).** Every non-trivial game has at least one runtime-composed display string with no literal to grep. Modest per-game frequency but high value when it hits, because without it you are reverse-engineering event flow by hand.

**Crib from.** The prototype `xref.py` already does the static classification. A runtime alternative worth noting alongside it: hook WOLF's text-draw function with Frida to see the exact string being rendered and trace back - the most direct "what is actually on screen" answer when a string is composed in a way static analysis cannot follow (from a save, heavy concatenation). Static xref is the accessible default, the Frida hook is the fallback.

## Suggested roadmap

| Priority | Gap | Proposed command | Prototype | Why now |
|---|---|---|---|---|
| P0 | 1. Font resolution | `wolf font-check` | `scripts/font_check.py` | Caused 100% of tofu, invisible today |
| P0 | 2. Text relayout | `wolf relayout` | `scripts/relayout.py` | Largest missing feature, hits 90%+ of message text |
| P1 | 3. Symbol-only strings | `strings-extract --include-symbols` / `wolf normalize-symbols` | `scripts/normalize_symbols.py` | Silent tofu on skipped rows |
| P1 | 4. Field-name-GET (dataID=-3) | `wolf field-names-detect` | `scripts/field_names_detect.py` | Player-facing labels invisible, schema-rename is a runtime trap |
| P1 | 5. Semantic verify | `wolf verify-semantic` | `scripts/verify_semantic.py` | `verify-roundtrip` gives false confidence on by-name keys |
| P1 | 7. Display-string tracer | `wolf xref` | `scripts/xref.py` | Untranslated runtime-composed strings have no literal to grep |
| P2 | 6. Sentinel masking | `mt-export --sentinel-mask` | `scripts/sentinel_mask.py` | External-pipeline-only, structural fix for escape collisions |

**Every gap has a working, tested Python prototype in `scripts/`** (all import the shared `wolfscript.py`, run with sensible defaults, and fail gracefully on bad input). They are the reference for the Rust port. `font_check` needed a GDI FFI built fresh (`CreateFontW` / `GetTextFace` / `GetGlyphIndicesW`), which the prototype now demonstrates end-to-end.

Two honest caveats surfaced while building the prototypes:
- **`verify-semantic` reports a superset of true breaks.** Most Database operands resolve by numeric index with the name as annotation, so a non-resolving name is only runtime-breaking for a *name-mode* lookup. The prototype flags all mismatches (the reliable signal is the *delta* when you rename something - a `行動力`->`AP` rename produced exactly +2 danglers, precisely the two lines that break). A production port inside WolfDawn should use the actual per-operand mode (which the binary carries but the decompiled annotation does not fully expose) to drop index-mode false positives, and support an allowlist for known dynamic lookups.
- **`sentinel-mask` for pathologically nested codes** (`\f[\cself[18]]`) is bounded by whatever `WOLF_CODE_RE` tokenizes. Round-trip stays exact and tokens stay backslash-free in every real case tested (~32k strings), but a production masker should tokenize nested codes fully.
