# Extracting, translating & building the text

This is the heart of the full-loose workflow: turn the game's Japanese database
into translated English files that the patched `game.exe` reads at launch. There
is no repack and no recompile — the end product is the editable `Project\`
folder (a wrapped copy of the native SRPG JSON tree). Everything in between is the
machine-translation pipeline that fills that folder with reviewed, reflowed English.

The whole flow is two cooperating toolsets:

| Stage | Tool | Produces |
|---|---|---|
| 1. Unpack | `tools/SRPG_Unpacker/SRPG_Unpacker.exe -c` | the native JSON tree (`items.json`, `Maps/map_NNN.json`, …) |
| 2. Extract | `tools/srpgtl/extract.py` | the translation **store** (`tooling/tl/`, one doc per kind/map) + a seeded glossary |
| 3. Translate | `tools/srpgtl/batch.py` (via `tl.py run`) | the same store, with each unit's `tl` filled by Claude |
| 4. Inject | `tools/srpgtl/inject.py` (via `tl.py inject`) | translated+reflowed strings written back into the JSON tree |
| 5. Build folder | `tools/loosekit/make_folder.py --store tooling/tl` | the editable `Project\` tree, each JP string wrapped `{"jp","en"}` |
| 6. JS strings | `tools/jstools/js_text_tool.py` | translated plugin/engine `.js` (a separate layer, see its own page) |

The orchestrator is `tooling/tl.py` — a thin CLI that imports `srpgtl.{extract,inject,batch,store}`
and exposes the subcommands `extract / dryrun / submit / status / fetch / run /
validate / retry / inject / selftest`. Run everything through it; you rarely call
the `srpgtl/*.py` modules directly.

> Key mental model: steps 2–4 operate on the SRPG JSON tree and write **whole-field
> English** back into it. Step 5 then re-wraps that tree into the `{jp,en}` form the
> loose loader keys on. The store (`tooling/tl/`) is intermediate scaffolding for the
> LLM; the shipped artifact is `Project\`.

---

## Step 1 — Unpack `project.dat` to the JSON tree

`make_folder.py` does this for you, but the translation pipeline needs the tree
separately as its `--patch` input. Unpack with the bundled (patched) unpacker:

```powershell
tools\SRPG_Unpacker\SRPG_Unpacker.exe <extracted>\project.dat -c -o tooling\patch
```

`<extracted>` is wherever you dumped `data.dts`'s `project.dat`. The `-c` mode
("create-patch") emits ~249 JSON files. Note this is a **patched** SRPG_Unpacker:
`docs/reference/EXTRACTION_CHANGES.md` documents 25 files / +194 lines that added
`customParameters` extraction for 12 data classes (e.g. `STATEDATA.this_18` →
`states.json` escort words like `護衛：ルート`, `WORDDATA.this_8` → `Extra/glossary.json`
dictionary conditions) plus a new `movetypes.json`. The stock upstream tool parses
those fields but never emits them, so player-facing text would silently leak as JP.

**GOTCHA — `-a` is terminal.** The apply step (`-a`) re-encodes every string via
`MemData::FromString`, appends null terminators, grows the file ~1064 bytes, and the
tool then **cannot re-parse its own output** (`ReadBytes past end of file`). This is a
property of the upstream tool for this title, confirmed on the pristine binary — not a
bug in the additions. Practical rule: **always back up the original `project.dat`,
and never re-extract (`-c`) from an applied (`-a`) file.** In the full-loose workflow
you don't actually apply back into `project.dat` at all (the loose loader reads
`Project\` directly) — `-a` only matters for the legacy data.dts build path.

---

## Step 2 — Extract: building the store (`tl.py extract`)

```powershell
python tooling\tl.py extract
# --patch tooling\patch  --js tooling\js_strings.json  --store tooling\tl  (defaults)
```

`extract.py::extract_store()` walks every `*.json` under `patch/` plus
`js_strings.json` and writes the **store** to `tooling/tl/`.

### The store layout

The store is a directory of JSON docs, one logical group per file (real layout,
verified on disk):

```
tooling/tl/
  glossary.json          {names:{jp->{en,gender,role,register,aliases,note}}, terms:{jp->en}, meta:{}}
  game_prompt.md         per-game setting/tone/character-voice addendum (cached in every request)
  dlg_map_000.json …     per-map dialogue + info text, scene-grouped, with speakers
  names.json             deduped name units (database names)
  desc.json              deduped descriptions
  ui.json                UI labels / window titles / win-lose conds / story pages
  info_misc.json         non-map message/info text
  customparams.json      JP substrings pulled out of customParameters JS literals
  plugins.json           player-facing strings from js_strings.json
  _batch_state.json      transient Anthropic batch bookkeeping (skipped on load)
```

`store.py::load_docs()` returns every `*.json` except `glossary.json`,
`_batch_state.json`, and anything starting with `_`.

### A *unit* — the atom of translation

Every translatable thing is one unit dict (real example from `names.json`):

```json
{ "id": "names:1", "kind": "name",
  "src": "◆サブクエスト会話自動オフ",   // cleaned + code-masked JP shown to the model
  "raw": "◆サブクエスト会話自動オフ",   // ORIGINAL JP string (the key everything matches on)
  "codes": {},                          // placeholder -> original control code
  "tl": "◆Sub-Quest Dialogue Auto-Off"  // the translation (filled in step 3)
}
```

Dialogue units additionally carry `"speaker"` (raw JP speaker, context for the model)
and `"ctx"` (a sanitized scene id grouping a whole event page).

### `KEY_KIND` — what gets pulled, and as what

`extract.py::KEY_KIND` maps JSON keys to unit kinds (this is the contract for "what
is player-facing"):

```python
KEY_KIND = {
  "data": "text", "msg": "text",          # message dialogue (has a speaker)
  "infoText": "info",                      # action-log / info window
  "name": "name",
  "desc": "desc", "description": "desc",
  "victoryConds": "cond", "defeatConds": "cond",
  "pages": "pages",                        # story / dictionary narration
  "commandName": "ui", "command": "ui", "mapName": "ui", "rewardData": "ui",
  "windowTitle": "title", "gameTitle": "title", "saveFileTitle": "title",
}
SKIP_KEYS = {"speaker", "comment", "fontName"}
```

`SKIP_KEYS` are deliberately **never** translated: `speaker` is context-only (the name
box is fed from the unit-name entry instead), `comment` is dev notes, `fontName` is a
font face. Any key not in `KEY_KIND` is ignored entirely.

Two special cases:
- **`customParameters`** values are JS object literals (e.g.
  `{text1:'ステージクリア後回数回復'}`). Extract pulls **only the single-quoted JP
  substrings** (`_SQ_RE`) as `customparam` units, preserving the JS structure.
- **Plugin strings** (`js_strings.json`) become `plugin` units, but only those that
  pass `plugin_translatable()` — a denylist (`plugin_blacklist()`) drops any string
  ever used as an asset filename (`.png/.ogg/…`), a path, a debug-log arg, or an
  `=== 'id'`/voice-key comparison. Translating an internal id would break the game,
  so such a string is skipped **everywhere** even if the same text appears as a label
  elsewhere.

### Dialogue vs. global dedup

- **Map dialogue/info** (`text`/`info` in a `Maps/*.json` file) is stored **per map**,
  grouped by event-page "scene" (`_scene_id()`), and is **not** deduped — the model
  needs the coherent run of lines with speakers. Each gets an id like
  `map_000:<scene>:c3`.
- **Everything else** (names, descs, UI, conds, pages, off-map messages,
  customparams) is **globally deduped**: one unit per unique JP string, then injected
  back to **every** occurrence. So you translate `回復` once and every copy updates.

### Glossary seeding

Extract collects every distinct JP message `speaker` and seeds it into
`glossary["names"]` (so character names are owned by the glossary, the single source
of truth for name-box / pronoun / voice consistency). Those character names are then
**dropped** from the deduped `names.json` bucket — see `name_units` filtering at the
end of `extract_store`. Hand-edit `glossary.json` to lock spellings/genders before
translating; per `TRANSLATE_README.md` the kit ships a pre-built glossary of 167
characters + 171 terms.

### Idempotency (re-extract is safe)

`extract_store` first loads any existing `*.json` docs and carries forward every
non-empty `tl` keyed by `(kind, raw)` (`old_tl`), and `load_glossary` preserves the
glossary. So re-running `extract` after a game update or a tweak **preserves your
work** — it only refills what's genuinely new. You only need to re-extract if you
regenerate `patch/` or `js_strings.json`.

---

## Step 3 — Translate the store (`tl.py run`)

```powershell
pip install anthropic tiktoken
$env:ANTHROPIC_API_KEY = "sk-ant-..."
python tooling\tl.py dryrun --show-sample    # scope + cost + a sample prompt, NO API call
python tooling\tl.py run                      # names first, then all text; polls to done
python tooling\tl.py validate                 # completeness / residual-JP / code-integrity
python tooling\tl.py retry                     # (optional) re-do hard failures with scene context
```

`batch.py` translates the store with Claude via the **Message Batches API** (50% off,
with prompt caching). Mechanics that matter:

- **Two-phase `run`.** Phase 1 translates character **names** only and writes them into
  the glossary; phase 2 translates dialogue/data with that freshly filled glossary in
  the (cached) prompt, so prose-embedded names stay consistent.
- **Resumable.** `run` polls to completion; Ctrl-C is safe — resume with
  `python tooling\tl.py fetch`. Or drive it manually: `submit` → `status` → `fetch`.
- **Scene-aligned chunking** (`build_text_chunks`): whole event pages stay together in
  one request (default `--max-units 80`), so the model sees a coherent scene with
  speakers; oversize scenes split but carry a context tail.
- **Code safety.** Control codes are already masked to `⟦n⟧` placeholders in `src`
  (see `codes.py::mask_codes`), so the model can't corrupt `\C[n]`, `\v[n]`, `\i[327]`,
  `%1`, pause codes, etc. `validate` flags any unit whose placeholder set changed.
- **Cost (per `TRANSLATE_README.md` / `dryrun`):** ~11.8k units, ~380k JP tokens at
  `low` effort ≈ **$6–7** on `claude-sonnet-4-6` (default) or **$9–12** on
  `--model claude-opus-4-8`. Effort defaults to `low`; raise with `--effort medium`.

**GOTCHAS:**
- Effort is the silent cost multiplier. Opus 4.8 / Sonnet 4.6 default to `high` effort
  (spends "as many tokens as needed"); `batch.py` forces `low` and never enables
  `thinking`. If you bump `--effort`, the output estimate from `dryrun` no longer holds.
- `dryrun` uses a `tiktoken` o200k_base proxy that differs from Anthropic's tokenizer
  by ~10–15%, and batch cache hits require the 1h-TTL prefix to stay warm.
- `validate` returns nonzero only on **hard** issues (empty / residual real-Japanese /
  placeholder mismatch). "identical-to-source" and possible-misgender are soft
  warnings (review, not fail). A lone `・`/`ッ`/`ー` left in English is cosmetic and
  auto-stripped on inject — never a hard fail.

---

## Step 4 — Inject (`tl.py inject`)

```powershell
python tooling\tl.py inject
# writes translated patch/*.json in place (+ fills js_strings.json)
```

`inject.py::inject_patch()` walks the JSON tree again and substitutes whole fields by
`(kind, original-JP)`, looked up in the maps built by `_build_maps`. For each
translated unit it calls `_restore()`, which:
1. restores masked `⟦n⟧` codes (`unmask_codes`),
2. normalizes JP corner-quotes `「」` → `"`, strips stranded sokuon,
3. **reflows** dialogue/info to the message-box width.

### The reflow rules (this is what makes the EN look native)

- **`_reflow(text, width)`** — greedy max-fill: every line fills to `width` monospace
  cells before it breaks, merging away the LLM's own soft breaks (kills orphan
  tail-words). This implements the `[[text-wrap-max-fill]]` memory rule. Hard breaks
  survive only at blank lines (paragraph) and speaker headers (`【…】` or a bare
  `Name:` line). `_bind_units` glues titles to names (`General Balam`), numbers to
  units (`3 turns`), and lead function words to their phrase so a wrap never strands
  them; `_fix_widow` pulls a lone last word up.
- **Width depends on kind/box** (real constants in `inject.py`):
  - `DEFAULT_WIDTH = 54` — normal message box (override with `--width`).
  - `PAGES_WIDTH = 44` — dictionary/Manual pages wrap narrower to clear the right-side
    illustration that otherwise clips wide lines.
  - `SHOP_BOX_WIDTH = 32` for `info_misc` ids `1056..1157` (`SHOP_NARROW_IDS`) — the
    narrow 2-line shop-keeper face box; page-align/pack disabled there.
- **Page structure** so voices and pauses stay synced:
  - `text` kind → `_page_align` (`MESSAGE_PAGE_LINES = 3`): each speaker
    segment is padded to a whole number of pages so the next `【Name】` lands at the
    top of a fresh page (and its `\vo` voice fires correctly).
  - `info` kind → `_page_pack` (`INFO_PAGE_ROWS = 15`): packs whole paragraphs into
    pages so the down-arrow break lands at a paragraph gap, not mid-sentence.

`customParameters` get only their quoted JP substrings replaced, with backslashes and
single-quotes re-escaped so an apostrophe (`Knight's`) can't break the JS literal.

**Inject is idempotent** — it always rebuilds substitutions from the original JP
(`raw`), so re-running never double-translates. `inject_js` likewise fills
`js_strings.json` `translation` fields, re-checking `plugin_translatable` so an
internal id is never filled even if the same text is a label elsewhere.

---

## Step 5 — Build the editable `Project\` folder (`make_folder.py --store`)

This is the step that produces the **shipped artifact**. `make_folder.py` unpacks
`project.dat` (or reuses `--unpacked`) and re-serializes the native JSON tree with
every translatable JP string wrapped as `{"jp": "<original>", "en": "<translation>"}`:

```powershell
# preferred: fill EN with the SAME reflow/page-align/glossary as the data.dts build
python FullLooseKit\tools\loosekit\make_folder.py --store tooling\tl

#   --project <project.dat>   default tooling\_jpbase\project.dat
#   --out <dir>               default <root>\Project
#   --en <old folder>         fill EN from an old category folder (RAW, NOT reflowed)
#   --unpacked <dump>         reuse an existing unpack instead of running the unpacker
```

Real output (verified) — `Project\items.json`:

```json
{
  "id": 107,
  "name": {"jp": "ベルフェゴール", "en": "Belphegor"},
  "desc": {"jp": "王家の証　…", "en": "Royal Proof — Survive once per stage with 1 HP"},
  "customParameters": {"jp": "{\r\ntext1: 'ステージクリア後回数回復'\r\n}",
                       "en": "{\r\ntext1: 'Uses recover after stage clear'\r\n}"}
}
```

Only string fields with Japanese are wrapped; `speaker`/`comment`/`fontName` stay
plain (same `SKIP` set as extract). A wrapped pair serializes onto **one line**
(`ser()`), so the tree stays diff-friendly.

### Why `--store` is mandatory, not `--en`

`--store tooling\tl` makes `make_folder` run **inject in-memory** over the tree
(`inject.inject_patch(..., in_place=False)` into a temp `_entree`, then `walk_en_tree`
copies the EN back keyed by `<file>#<json-path>`). The result: the folder's `en`
fields get the **identical width-fill reflow, page-align, and glossary names** the
data.dts build produced — no orphan tail-words. The loose path otherwise skips inject,
so `--en <old folder>` would carry the translator's raw wraps (orphans). Per the
`[[project-folder]]` memory note, the shipped `Project\` was built with
`--store`; `translation_en_backup/` is the old raw form. **Use `--store`.**

**GOTCHA — blank `en` means "show JP".** `transform()` writes `"en": ""` whenever the
stored EN equals the JP (i.e. untranslated). A fresh folder is therefore all-JP and
fills in as you translate. This dovetails with the loader: a blank `en` (or a JP
string not present in the folder) **passes through to the original `data.dts`
Japanese**. So you can ship a partially-translated folder and the game stays playable.

---

## How the loose loader keys translations — and why `jp` must be kept

The patched `game.exe` (Patch 5b — the PIC shellcode in `tools/loosekit/load_table.c`,
compiled to `load_table.bin`) reads `Project\` **directly at launch**. From the
source (`load_table.c`), the loader:

1. Recursively walks `<gamedir>\Project` (`rootname = L"Project"`).
2. In each file scans for `"jp": "..."` then the following `"en": "..."`
   (`after(p,e,I->jpkey)` / `I->enkey`, with `vend()` finding the value end).
3. **Hashes the JP value** (`jhash`, an FNV-style hash) into a bucket table — this is
   the `jp -> en` lookup the cave's `probe.bin` consults when the engine reads a
   database string at parse time.
4. On a blank `en` it `continue`s (comment: `blank en -> show JP`), so the original
   Japanese passes through.
5. On a duplicate JP key it is **first-win** (`if (!b) { buckets[hh] = off; … break; }`
   — an existing bucket is left untouched).

Consequences for a translator:

- **Never delete or edit the `jp` field.** It is the literal lookup key. If `jp` no
  longer matches the byte-exact Japanese the engine reads from `data.dts`, the entry is
  dead and the line stays Japanese. Edit **only** the `en` side.
- **Match is exact and value-keyed**, not position-keyed — you can reorder or reformat
  the tree freely; only the `jp` string text matters.
- **Duplicate JP collapses to first-win.** If two different contexts share identical JP
  but need different English, the loose folder cannot distinguish them (the first
  `en` wins everywhere). This is why the upstream pipeline dedupes global strings — the
  loose layer has the same limitation by construction.

---

## Step 6 — Plugin / engine `.js` strings

Hardcoded Japanese in the SRPG plugins/scripts (e.g. `文字変更.js`, `constants-stringtable.js`,
`EC_DefineString` tables) is **not** in `project.dat`, so it is a separate layer
handled by `tools/jstools/js_text_tool.py` (extract → translate via the same store's
`plugin` units → apply), and the edited UTF-16LE `.js` ship loose under
`assets/plugins/Script/` and `assets/plugins/Plugin/` (override data.dts via Patch 2's
code-cave). That pipeline has its own reference page — this section covers only how its
strings enter the store (`plugins.json`) and are filled (`inject_js`).

---

## End-to-end command summary

```powershell
# 1. unpack
tools\SRPG_Unpacker\SRPG_Unpacker.exe <extracted>\project.dat -c -o tooling\patch
python tooling\js_text_tool.py extract <extracted> -o tooling\js_strings.json

# 2-4. extract -> translate -> inject  (store = tooling\tl)
python tooling\tl.py extract
# (hand-review tooling\tl\glossary.json: genders/spellings/terms)
python tooling\tl.py dryrun --show-sample
python tooling\tl.py run
python tooling\tl.py validate
python tooling\tl.py inject

# 5. build the shipped, reflowed Project\ folder
python FullLooseKit\tools\loosekit\make_folder.py --store tooling\tl
```

After this, `Project\` is the loose translation the patched exe reads. To iterate
on a single line you can also just open the relevant `Project\*.json` and edit an
`en` field by hand — relaunch and the change shows, no rebuild. Re-running the full
pipeline is only needed when you re-translate in bulk; the store and glossary are
preserved across runs.

### Top GOTCHAS recap

- `Project\` `jp` fields are lookup keys — edit `en` only; blank `en` = show JP.
- Always `make_folder.py --store` (reflowed), not `--en` (raw orphans).
- Re-extract / re-inject are idempotent and preserve prior work; SRPG_Unpacker `-a`
  is **not** — it's terminal, back up `project.dat`, never re-`-c` an applied file.
- Effort silently multiplies LLM cost; keep it `low` unless a pass needs nuance.
- Plugin internal-id strings are denylisted everywhere — never translate an asset
  filename / `=== 'id'` / voice key, or you break triggers.
- Duplicate JP in the loose folder is first-win; identical source can't get two
  different translations.
