# コイン☆プッシー / "Coin Pussy" — JP→EN translation toolkit

Game: **コイン☆プッシー** (くじら1% / Kujira 1%), Unity 2022 **Mono**, R18.
Engine detection: `CoinPussy_Data/Managed/Assembly-CSharp.dll` + `MonoBleedingEdge/`.

Status: **extraction complete (5,680 units staged), BepInEx plugin built and verified in-game, translation not yet run.**

## What this game actually is, text-wise

No localization system, no `TextAsset` folder in the AssetRipper export, and **no player-facing strings in `Assembly-CSharp.dll`** — every Japanese string in the decompiled C# is a PlayMaker editor `Tooltip`.
All game logic is PlayMaker FSMs. Text lives in two very different places:

### A. Asset-embedded — 662 unique strings
UI and popups, baked into scenes and prefabs.

| Where | Unique |
|---|---|
| PlayMaker action string params — `setTextmeshProUGUIText.textString`, `UiTextSetText.text`, `SetStringValue.stringValue`, `BuildString.stringParts`, `StringAddNewLine.stringParts`, `SetFsmString.setValue` | 322 |
| `m_Text` on `UnityEngine.UI.Text` | 160 |
| `m_text` on TextMeshPro | 131 |
| PlayMaker `Text*` string-variable defaults (stage titles, blurbs, control hints) | 49 |

Establishing that list took a **full census of every Japanese-bearing YAML path in the export** — 24 distinct paths across 8,136 files (`logs/census.txt`). The other 21 are identifiers: FSM state names, GameObject/Material/Mesh/Sprite/AnimationClip names, animator triggers, animation binding paths, blendshape names, and the font atlas character set.

Attribution is exact, not heuristic. PlayMaker packs every action parameter of a state into one column-oriented record whose `paramDataType` values are an enum compiled into `PlayMaker.dll`. Rather than guess the numbers, `derive` **solves** the code→column mapping from saturation constraints and then proves it: across **117,304 `actionData` blocks, all 25 codes resolve with 0 violations** (every column exactly filled, each slot consumed once). See `scripts/unitytl/pmparams.py` and `tl/playmaker_param_types.json`.

### B. Scripted dialogue — 5,018 units, CSV TextAssets
**AssetRipper exported none of these.** A byte sweep of the shipped data files (`logs/binscan_missing.txt`) found five CSV TextAssets inside `resources.assets` holding the entire script:

| CSV | Rows | Units | Translated columns |
|---|---|---|---|
| `EventData_Hscene_casino.csv` | 2,030 | 2,569 | `MessageJP` (heroine's subtitles), `Announce` (broadcast narrator) |
| `EventData_Comment_W.csv` | 1,300 | 1,157 | `MessageJP` + unnamed 3rd column (live-stream viewer comments) |
| `EventData_Event_casino.csv` | 842 | 765 | `MessageJP` (story dialogue), `Announce` (speaker name box) |
| `EventData_Stage_casino.csv` | 497 | 392 | `MessageJP` (in-battle barks) |
| `EventData_W.csv` | 143 | 135 | `MessageJP` (minigame reactions) |

Everything else in those files (`Animation`, `AnimationBack`, `Facial`, `FacialBack`, `Voice`, `Special`, `State`, `Sweat`, `Time*`, `No`, `Back`, `EventID`) is engine data and is never touched.

## Delivery (two layers, one BepInEx 5 plugin) — built and verified

The game reads the CSVs through `ReadTextAsset` → `ReadCsv` → `HutongGames.PlayMaker.Ecosystem.DataMaker.CSV.CsvReader.LoadFromString(string, bool, char)`.

1. **CSV swap** — a Harmony prefix on `CsvReader.LoadFromString` returns the translated CSV when the incoming string's header matches. Covers all 5,018 script units at source, per row, with no dedup constraint. Read/rewrite is **byte-identical** on all five files (QUOTE_MINIMAL, CRLF, UTF-8 BOM), asserted on every extract and verified end-to-end by `tl.py inject` on an untranslated store.
2. **Text-setter dictionary** — a Harmony hook on `UI.Text.text` / `TMP_Text.text` setters + `Awake`/`OnEnable` passes, looking up `translated/translations.json`. Covers the 662 asset-embedded strings. Because it runs *after* every FSM comparison, the 3 strings that are both display labels and `StringSwitch` keys (`支配人`, `バニー`, `終了`) are safe to translate — they are flagged `collides_with_key` so the plugin restricts them to **exact-match** replacement and never substring/compose replacement. `extracted/key_strings.json` carries the 507-string denylist for that (minus anything we are deliberately translating).

Verified in-game on BepInEx 5.4.23.5 / Unity 2022.3.62: 9 hooks applied, 0 errors. A smoke run with seeded translations confirmed both layers substitute — `CSV swap: EventData_Event_casino.csv (59109 -> 61469 chars)` for layer 1, and every seeded label dropping out of `untranslated.txt` for layer 2.

**Runtime coverage A-test.** With the untranslated logger on, a menu-to-shop pass reported 132 unique Japanese strings reaching a text component. 131 were already in the extraction. The one exception, `バニーちゃんのおっぱいを狙って
コインがなくなる前に撃ちまくろう！`, is built at runtime by joining two FSM variables (`Text explain 01` + `Text explain 02`) that are both extracted separately — the store's compose fallback splices it, which the smoke run confirmed.

Two things that test caught, both fixed:
* One hint string reaches the UI still carrying a **UTF-8 BOM**. .NET's `Trim()` does not treat U+FEFF as whitespace, so the exact key never matched; `Normalize` now strips it.
* Since `TextAsset.text` keeps the BOM on this Unity version, the CSV layer now preserves the caller's BOM state exactly — the first CSV field is a column key the FSMs look up, so adding or removing a BOM would silently rename it.

## Layout

```
tools/
  README.md                    this file
  tl.py                        the CLI
  tl/
    glossary.json              18 hand-locked names + 89 terms  <- edit by hand
    game_prompt.md             the translation bible (cached prefix)
    playmaker_param_types.json derived + proven paramDataType mapping
    <Bucket>.json              the store: one file per scene / CSV
    _batch_state.json          transient Anthropic batch bookkeeping
  extracted/
    textassets/*.csv           the five script CSVs, dumped with UnityPy
    strings.json               asset-embedded units with full site attribution
    csv_strings.json           CSV units with speaker / scene / cell refs
    jp_all_strings.txt         every unique asset-embedded JP string
    key_strings.json           strings used as engine keys — plugin denylist
    excluded.jsonl             every rejected string + the reason (audit trail)
    extract_report.txt         the integrity summary
  translated/
    textassets/*.csv           translated CSVs (from `inject`)
    translations.json          JP->EN dictionary (from `dict`)
    plugin/translations/       the packaged plugin payload (from `package`)
  mod/CoinPussyEnglish/        the BepInEx 5 plugin
    Plugin.cs                  entry point + config
    CsvPatches.cs              layer 1: CsvReader.LoadFromString swap
    TextPatches.cs             layer 2: UI.Text / TMP_Text hooks
    TranslationStore.cs        dictionary, denylist, compose/format matching
    build.ps1                  compile + install into BepInEx/plugins/
  scripts/
    dump_textassets.py         UnityPy TextAsset dumper
    unitytl/
      uyaml.py                 streaming reader for AssetRipper YAML
      pmparams.py              PlayMaker ActionData decoder + mapping derivation
      extract.py               asset scan + site classification
      csvtext.py               CSV script extract / inject
      codes.py                 JP detection, markup masking, validation
      store.py                 store + glossary
      batch.py                 Claude Message Batches driver
  logs/
    census.txt                 every JP-bearing YAML path in the export
    pm_mapping.json            derivation report
    recon_fsm.txt              (action, param) site tally
    binscan_missing.txt        JP found in binaries but absent from the export
```

## Commands

```powershell
pip install anthropic tiktoken UnityPy
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # or: ant auth login

python tools/scripts/dump_textassets.py   # resources.assets -> extracted/textassets/*.csv
python tools/tl.py derive                 # solve + prove PlayMaker's param encoding
python tools/tl.py extract                # -> tl/ store + extracted/ reports
python tools/tl.py selftest               # offline round-trip proof (writes nothing)
python tools/tl.py dryrun --show-sample   # scope + cost + a real prompt, no API call
python tools/tl.py run                    # names phase, then the text batch
python tools/tl.py validate               # completeness / residual-JP / placeholders / layout
python tools/tl.py retry                  # re-translate hard failures with scene context
python tools/tl.py inject                 # -> translated/textassets/*.csv
python tools/tl.py dict                   # -> translated/translations.json
python tools/tl.py package                # -> translated/plugin/ (what the mod loads)
tools/mod/CoinPussyEnglish/build.ps1      # compile + install the plugin
```

### Plugin config — `BepInEx/config/com.sw.coinpussy.english.cfg`

| Key | Default | What it does |
|---|---|---|
| `EnableCsvSwap` | true | Layer 1 — swap the five script CSVs |
| `EnableTextHook` | true | Layer 2 — the UI.Text / TMP dictionary |
| `EnableAutoSize` | false | Shrink-to-fit text; off because translations keep the source line count |
| `LogUntranslated` | true | Write missed Japanese to `plugins/CoinPussyEnglish/untranslated.txt` |
| `VerboseLogging` | false | Log every swap (at Info, so it shows with BepInEx's default log level) |
| `DumpLoadedCsv` | false | Dump every CSV the game parses — use it to catch a file the pipeline missed |
| `FallbackContainsReplace` | false | Last-resort substring replace; can splice a partial match |

To uninstall, delete `BepInEx/plugins/CoinPussyEnglish/`.

`run` is one-shot; `submit` → `status` → `fetch` is the manual equivalent and `fetch` works any time after the batch ends (Ctrl-C during polling is safe).

## Translation setup

**Model** `claude-opus-5`, **reasoning effort `low`**, Message Batches API.

- The stable prefix (localization rules + `game_prompt.md`, ~5.1K tokens, written once and re-read 117×) is one `cache_control: {"type":"ephemeral","ttl":"1h"}` block. The 1h TTL matters: batch requests are processed minutes apart and would miss a 5-minute cache.
- The glossary is the **uncached tail**, so editing it never invalidates the prefix.
- Requests carry short integer indices; the unit-id map stays local and is reattached on fetch.
- Dialogue is chunked **scene-aligned** (by `EventID` beat, e.g. `H_Casino_Stage01_Rush`) in play order, 60 units per request, and a split scene carries 3 preceding lines as do-not-translate context.
- `hdialogue` and `narration` alternate line-by-line in the H-scene CSV, so every line is tagged with its speaker (`受付ちゃん` vs `実況アナウンサー`) — the two registers are nothing alike.
- No sampling params are sent (Opus 5 rejects `temperature`).

Measured scope: **118 requests, 5,680 units, 127,764 JP characters**.

Estimated cost by model and delivery path (`dryrun` prints this; ratio 1.3):

| Model | batch + cache | batch only | live + cache | live only |
|---|---|---|---|---|
| Opus 5 | $2.38 | $3.71 | $4.73 | $7.41 |
| Sonnet 5 | $0.95 | $1.48 | $1.89 | $2.97 |
| Haiku 4.5 | $0.48 | $0.74 | $0.95 | $1.48 |

Rates are transcribed from the published pricing table (checked 2026-08-18) with
the five columns Anthropic publishes; the batch discount halves every class. The
live column assumes the **5-minute** cache TTL, which is right for back-to-back
requests and cheaper to write than the 1-hour TTL the async batch path needs.

## Invariants the pipeline enforces

- **Nothing is dropped silently.** Every Japanese string that is not translated is written to `excluded.jsonl` with a reason. An unrecognised `(action, param)` site is excluded *and* logged as `unknown-site`, so a game update surfaces new sites instead of quietly mistranslating or missing them.
- **Key strings never become English.** `StringSwitch.compareTo`, animator triggers, FSM names and ES3 save keys are deny-listed by site and by parameter name.
- **CSV bytes are sacred.** Round-trip is asserted on every extract; `inject` on an untranslated store reproduces all five files byte for byte.
- **Stable unit ids** (`sha1(kind + source)`), so re-extracting after a game update keeps every finished translation.
- **`selftest` writes nothing.** It deep-copies the store, fake-translates, and checks placeholder and line-count integrity in memory.
- **Layout is validated.** English must keep the source's line count (fixed-size subtitle/UI boxes); drift is a soft warning, and UI labels expanding >4× are flagged.

## Notes

- Adult content is translated faithfully and uncensored — that is the correct localization for an R18 commercial title, and the bible says so explicitly.
- No TMP rich-text markup or format placeholders occur anywhere in the translatable set (`markup tokens found: (none)`), so masking is a no-op here — it stays in place because a game update could introduce some.
- Full-width space `　` inside a line is a **pacing gap between gasps**, not indentation. The prompt calls this out; deleting it would run the phrases together.
- Not yet done: images with baked-in Japanese (signage, panels, the calendar-style props) — see the skill's `references/image-translation.md` and `Tools\Game Translation\Image Translation\imgtl.py`.
