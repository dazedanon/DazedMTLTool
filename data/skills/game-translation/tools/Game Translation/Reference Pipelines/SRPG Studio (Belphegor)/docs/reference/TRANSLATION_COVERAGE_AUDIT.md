# SRPG-ToolBox — Belphegor translation-coverage audit

## 1. Bottom line

The unpacker's **structural support is complete**. The full extraction ran to exit 0 with empty stderr; because the parser hard-fails (exit -1, "ERROR: ... not implemented") on any unsupported type, this proves that **all 56 distinct event-command types and all 78 distinct data-class types** the game uses are parsed and repacked. No command or class is structurally missing. The remaining issues are **translation-coverage gaps, not structural ones**, and they are overwhelmingly concentrated in **hardcoded Japanese text living inside the game's JavaScript plugins and the engine string table** — content that lives outside `project.dat` and is therefore invisible to a `.dat`-based extractor by design. Inside the `.dat` itself, core dialogue and database text (names + descriptions) are well covered; only a handful of secondary `MemData` string fields (one command, several classes) are silently dropped to JSON. The current patch is **248 JSON files / 8.3 MB**.

## 2. Code the tool fully supports

- **Event commands (56 in use):** every command parses and round-trips. Player-facing dialogue is extracted wherever a command (or a base it derives from) overrides `ToJson` to emit its `MemData` strings. The message family is fully covered: `MESSAGESHOW` (0) and `STILLMESSAGE` (3) via their own `toJson`; `MESSAGETEROP` (2) and `MESSAGESCROLL` (100) via the inherited `MESSAGEBASE::toJson`. `CHOICESHOW` (103), `INFOWINDOW` (102), `UNITINFOCHANGE` (1501), and `MAPINFOCHANGE` (1503) all emit their text. All movement/sound/graphics/param/switch/unit-state commands legitimately carry no translatable text (only IDs, resource refs, coordinates, or sized binary blobs) and are correctly uncovered — e.g. `MAPCHIPCHANGE` (1403) `this_4` is `16*n` bytes of chip data, `UNITMOVE` (1002) `this_8` is `4*n` bytes of path data. `MESSAGEERASE` (id 1) carries no text despite its name.
- **Data classes (78 in use):** core DB text is well covered. Every `LEGENDDATA`-derived category emits name + description via `LEGENDDATA::toJson` (units, classes, weapons, items, skills, states, races, class-types, weapon-types, difficulties, fonts, titles, fusion, transform, NPCs, etc.). Dedicated `toJson` overrides cover strings/choices/layouts (`STRINGDATA`, `CHOICEDATA`, `COMMANDLAYOUTDATA`, `SHOPLAYOUT`, `FUSIONDATA`, `METAMORDATA`, `QUESTDATA`, `CHARACTERDATA`, `WORDDATA`, etc.), and `customParameters` is correctly emitted where the class overrides `toJson` (e.g. `skills.json`, `items.json`, both confirmed to carry translatable Japanese).

Bottom line for this section: **command/class coverage is essentially complete.** The flagged items below are narrow `MemData` omissions, not missing types.

## 3. Gaps to flag for implementation

### (a) Genuine command/class `ToJson` gaps (in-tool, real)

These are fields that round-trip through the binary but are never serialized to JSON, so a translator cannot see or edit them. Fix is to add/extend the class's `toJson`/`applyPatch` and add the corresponding patch slot.

| Item | Where | Why it matters | Severity | Suggested fix (in tool) |
|---|---|---|---|---|
| **MOVETYPEDATA** (class 204) | `Classes/MOVETYPEDATA.{h,cpp}`; `Functions.cpp:358`. No `toJson` override; inherits `EDITDATA::toJson` (emits only `{id}`). | `this_3` is read via the same length-prefixed `initMemData` path as `LEGENDDATA.name`; it is the **player-facing movement-type name** (歩行/騎乗/飛行). No `movetypes` patch file exists; `m_pMoveTypeData` is loaded + dumped but in neither `writePatches` nor `applyPatches`. | **High** | Add `MOVETYPEDATA::toJson()` emitting `this_3.ToString()` as `name`; wire `m_pMoveTypeData` into write/apply; create `movetypes.json`. |
| **STATEDATA** (class 5) `customParameters` | `Classes/STATEDATA.{h,cpp}`; no own `toJson`. | **Confirmed at runtime:** `this_18` holds player-visible JP word-substitutions in 9/53 states — e.g. `{ escort_word: '護衛：ルート' }` plus 8 character-name variants (護衛：ルツ/サーシャ/…). 護衛 = "escort/guard." `states.json` has only `id/name/desc`; the value is unreachable via any other object. `this_35` is empty in this build. | **Medium** | Add `STATEDATA::toJson`/`applyPatch` to emit `this_18` (and `this_35` if string) as `customParameters` into `states.json`. |
| **RACEDATA** (221), **NPCDATA** (208), **CLASSTYPEDATA** (200), **WEAPONTYPEDATA** (203), **DIFFICULTYDATA** (205), **SOUNDMODEDATA** (803), **RESTSHOPDATA** (225), **PASSCHIPDATA** (101) `customParameters` | Respective `Classes/*.{h,cpp}`; all `LEGENDDATA` subclasses with a trailing `MemData` (e.g. `this_8`/`this_11`/`this_12`/`this_13`/`this_15`+`this_41`) but **no own `toJson`**. | Same `customParameters` slot that demonstrably carries display JP elsewhere (`skills.json`: `{damage_guard_word:'アーマー系'}`; `items.json`: `{text1:'ステージクリア後回数回復'}`). Structurally identical, but dropped from `races.json`/`classtypes.json`/etc. RACEDATA/DIFFICULTYDATA verified real gaps; their specific bytes may be empty in this build. | **Medium** | Add a `toJson` override (or factor a shared `LEGENDDATA::emitCustomParameters` helper) emitting the field as `customParameters` into each category's patch file. |
| **WORDDATA** (801) `this_8` | `Classes/WORDDATA.cpp` `toJson` emits name+desc+pages but not `this_8`. | **Confirmed player-facing:** `this_8` is the glossary `customParameters` blob with `condstr1/condstr2` (e.g. `'敵を１００以上撃破'`); the runtime plugin `表示変更_用語解説.js` renders these in the in-game Dictionary list for locked pages. Worded differently from the emitted `pages`, so not redundant. Absent from `Extra/glossary.json`. | **Low** | Add `this_8` (`customParameters`) to `WORDDATA::toJson`/`applyPatch` → `Extra/glossary.json`. |
| **CHARACTERDATA** (800), **GALLERYDATA** (802) `customParameters` | `Classes/CHARACTERDATA.cpp` (emits name+desc+pages, not `this_8`); `GALLERYDATA` has no own `toJson`. | Same dropped `customParameters` slot; lower confidence of translatable content here. | **Low** | Emit `this_8`/`this_10` as `customParameters` if non-empty. |
| **MESSAGELAYOUTDATA** (1000) `this_28`, **MAPTREEDATA** (900) `this_3`, **PARAMHEADDATA** (2516) `this_4` | Respective `Classes/*`; derive from `EDITDATA`, no `toJson` → emit only `{id}`. `m_pMessageLayout` is also omitted from `writePatches`/`applyPatches` entirely. | Lone `MemData` string amid geometry/reference fields. By strong structural analogy to sibling layout classes (`COMMANDLAYOUTDATA.commandName`, `SHOPLAYOUT.shopMessages`) these are likely human-facing layout/label/node text, but exact content was not byte-sampled. | **Low** | Inspect content; emit only fields that prove player-facing (e.g. map-tree/chapter node name). Leave editor-only keys as-is. |

### (b) Hardcoded JS plugin text — **the main gap** (out of `.dat` scope)

This is the dominant translation gap. None of it is in `project.dat`; it lives in plugin `.js` source and is not captured by any DB extraction. **14 plugin files** contain player-facing Japanese; all verified as real gaps (literals confirmed live and rendered, and confirmed absent from the patch).

| Item | Where | Why it matters | Severity | Suggested fix |
|---|---|---|---|---|
| **文字変更.js** StringTable override | `Plugin/02 俺オリジナル/文字変更.js` | **~280 (≈239 unique) player-facing UI strings** — config labels/descriptions, shop/stock/marshal menus, confirmation dialogs, battle-result terms, currency names (ペオル/カルマ). Effectively a wholesale string table. | **High** | Out of `.dat`-tool scope. Add a **plugin/script string-extraction pass** that emits `Identifier_Key → value` JSON for `var StringTable = {…}` objects; this file is the primary target. |
| **OT_ExtraConfigSkill/ExtraConfigBase.js** `EC_DefineString` | `Plugin/03 他作者/OT_ExtraConfigSkill/ExtraConfigBase.js` | **39 skill-condition labels** rendered in the skill-info window (e.g. `コマンドスキル(攻撃型)`, `相手の見切りを無視して発動可能`). Exclude `EC_Putlog`/`root.log` debug Japanese. | **Medium** | Same extraction pass; target the `EC_DefineString` table only. |
| **戦闘予測.js** | `Plugin/01 オリジナル/戦闘予測.js` | ~30 config titles/descriptions + on-map key-hint overlay labels (全員一括移動, 登録解除, …). | **Medium** | Same extraction pass (config + drawn-text literals). |
| **表示変更_マップユニット情報.js** | `Plugin/01 オリジナル/…` | 17 config titles/descriptions, choice labels (簡易/通常/詳細), on-screen `なし` fallback. | **Medium** | Same. |
| **マーキング自動終了.js**, **ユニット範囲表示.js**, **各種ボイス.js**, **スキル_射程変更…予備武器射程表示.js**, **改変01 戦闘UI.js**, **序章.js**, **表示変更_アイテム＆スキル詳細.js** | `Plugin/01 オリジナル/…` and `Plugin/02 俺オリジナル/…` | 2–6 strings each: config option titles/descriptions, density/choice arrays, skill-detail keyword labels (一方向攻撃, 追撃不可…), chapter titles (外伝/序章). All confirmed rendered and absent from patch. | **Low–Medium** | Same extraction pass. For `各種ボイス.js` translate only the 4 config strings; do **not** touch the voice/material trigger keywords (internal IDs). |
| **魔法武器（物理防御）.js** | `Plugin/00 他作者/…` | 2 weapon-keyword labels drawn via `ItemInfoRenderer.drawKeyword` (`物理攻撃（魔法防御判定）`, `魔法攻撃（物理防御判定）`). | **Low** | Same; or route through StringTable. |
| Smaller single-label plugins | `撃破数.js`, `表示変更_支援ステータス.js`, `表示変更_用語解説.js` | 1 on-screen status/keyword label each (撃破数, 支援する対象, glossary description). | **Low** | Same extraction pass. |

Where the strings are genuinely hardcoded inline (not in a `StringTable`/`EC_DefineString` map), they may need **manual JS translation — out of automated tool scope**.

### (c) Engine / string-table text (out of `.dat` scope)

| Item | Where | Why it matters | Severity | Suggested fix |
|---|---|---|---|---|
| **constants-stringtable.js** | `Script/constants/constants-stringtable.js` | **215 player-facing JP entries** — the engine's central UI string table (save/load prompts, command names, status labels, confirmation dialogs). Primary engine-text target. Some entries are already English; preserve literal `\n` and trailing-colon prefixes. | **High** | Same plugin/script string-extraction pass. The other 155 runtime scripts contain Japanese only in **comments** (verified via comment-stripping tokenizer) — leave them untouched. |

### (d) Baked-in text in images (non-code coverage gap)

UI/graphics assets under `Material/`, `Panel/`, and similar contain Japanese text rendered into the image bitmaps themselves (titles, UI chrome, panels). This is **not a code/`.dat` gap and cannot be reached by any JSON extractor**; it requires image re-authoring. Flag for the art/localization track, out of unpacker scope.

## 4. Recommended next steps

1. **Confirm the high-severity tool gap.** Add `MOVETYPEDATA::toJson` (+ write/apply wiring + `movetypes.json`). This is the only DB field that silently drops a primary player-facing **name** (12 uses).
2. **Add a plugin/script string-extraction pass to the tool** (the single highest-leverage change). Parse `var StringTable = {…}` and `EC_DefineString` objects into editable `key → value` JSON and re-inject on repack. This captures the two largest gaps — `文字変更.js` (~239 strings) and `constants-stringtable.js` (215 strings) — plus the `EC_DefineString` set, in one mechanism.
3. **Emit dropped `customParameters` on `LEGENDDATA` subclasses.** Factor a shared helper and turn it on for `STATEDATA` (confirmed live: escort-word state text), then `RACEDATA`, `NPCDATA`, `CLASSTYPEDATA`, `WEAPONTYPEDATA`, `DIFFICULTYDATA`, `SOUNDMODEDATA`, `RESTSHOPDATA`, `PASSCHIPDATA`, `WORDDATA` (confirmed live: glossary condition strings), `CHARACTERDATA`, `GALLERYDATA`.
4. **Triage the remaining hardcoded inline JS literals** (the 1–6-string plugins) for manual translation; exclude internal IDs (各種ボイス trigger keywords) and debug logs (`EC_Putlog`/`root.log`).
5. **Byte-inspect the three low-confidence `EDITDATA` fields** (`MESSAGELAYOUTDATA.this_28`, `MAPTREEDATA.this_3`, `PARAMHEADDATA.this_4`); emit only those that prove player-facing.
6. **Hand off baked-in image text** (`Material/`, `Panel/`, UI) to the art/localization track — it is outside the unpacker's reach.

---
*Generated by a 35-agent verified audit. Used types: 56 commands / 78 classes (all implemented). Confirmed in-tool code gaps: 6 classes. JS files flagged: 16 (12 top-priority verified against the patch).*
