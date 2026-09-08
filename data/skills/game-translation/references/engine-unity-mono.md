# Unity Mono

**Indicators:** `<Game>_Data/Managed/Assembly-CSharp.dll`, `MonoBleedingEdge/`, often `winhttp.dll` + `doorstop_config.ico` (BepInEx already installed). Managed DLLs are real .NET assemblies (unlike IL2CPP) - readable directly in dnSpy.

**Reference implementations:**
- `RP/Unity Mono (NTR Soccer)/` - Unity 2022.3, BepInEx 5.4.23, Pixel Crushers Dialogue System. The **official-localization-locked-to-ja** case (step 3). Mod at `.\mod\NTRSoccerEnglish\`.
- `RP/Unity Mono PlayMaker (CoinPussy)/` - Unity 2022.3, BepInEx 5.4.23, **no localization system and no strings in Assembly-CSharp at all**: everything is PlayMaker FSMs plus CSV TextAssets. Claude batch + live drivers, box-fitting (`reflow`/`shorten`), sha1-keyed CSV swap. See "PlayMaker games" below.

(`RP/` = `tools/Game Translation/Reference Pipelines/`.)

## Step 1 - extract with AssetRipper

`tools/.NET/AssetRipper/AssetRipper.GUI.Free.exe` (a download, see `tools/THIRD-PARTY.md`) → export the game to an `ExportedProject/`. This gives you decompiled `Assets/Scripts/Assembly-CSharp/*.cs` (readable) and all serialized assets as YAML (`.unity`, `.prefab`, `.asset`, `MonoBehaviour/*.asset`).

## Step 2 - find where the JP text lives

Search the export for Japanese `[぀-ヿ一-鿿]`. It is almost never in `.cs` code - it's in serialized assets. The usual homes:
- **A dialogue database** - Pixel Crushers Dialogue System stores everything in one big `MonoBehaviour/*.asset` YAML (NTR Soccer: `Dialogue Database.asset`, 8 MB). Entries have base + per-language fields (`Dialogue Text` / `ja` / `zh` / `ko`).
- **A UI text table** - `MonoBehaviour/UI Localization Text Table.asset` (Pixel Crushers TextTable): `m_languageKeys` + `m_fieldValues`, each field with a value per language.
- **TextMeshPro components** in scenes/prefabs - `m_text:` fields (dominant. NTR Soccer had 79 TMP prefabs, 0 legacy `UI.Text`).
- **PlayMaker FSMs** - `stringParams` (plaintext YAML) and hex `byteData` blobs. Decode byteData as UTF-8/UTF-16LE and scan. Usually noise **but sometimes the entire script** - see below.
- **TextAssets** - `TextAsset/*.txt|.csv|.json` in the export, or `m_Script` inside `resources.assets`. CSV script tables live here.
- **StreamingAssets Addressables bundles** (`*.bundle`) - binary. Only if the YAML export is incomplete.

If a full JP sweep of the export finds nothing in `.cs` **and** nothing in a
localization asset, the game is almost certainly FSM-driven. Do not conclude the
text is encrypted - look at PlayMaker and TextAssets before reaching for a runtime
harvest.

Robust YAML field extraction: parse `- title: X` / `value: Y` pairs, join Unity's wrapped multi-line scalars (folds line-wraps as single spaces), handle single-quote `''` escaping. See `tools/Game Translation/Reference Pipelines/Unity Mono (NTR Soccer)/scripts/extract_text.py`.

## Step 3 - CHECK FOR AN OFFICIAL LOCALIZATION FIRST

**Many Japanese Unity games ship a complete official English localization that is simply locked to `ja`.** Before building any dictionary, check:
- Dialogue DB entries have non-empty English base fields (`Dialogue Text`) with `ja` as the variant.
- Scenes hard-code `localizationSettings: { language: ja }`.
- A TextTable has an English `Default`/`en` column.

If so, the entire job is **flipping the language** - a few Harmony prefixes, zero translation. NTR Soccer was 2,590/2,595 strings already in official English. Only 5 needed Mistral.

### Force-locale mod (Pixel Crushers example)
Harmony prefixes that rewrite the language to base/English on every entry point:
```csharp
// DialogueSystemController.SetLanguage(string language)  -> language = ""
// UILocalizationManager.set_currentLanguage(string value) -> value = ""
// Localization.set_language(string value)                 -> value = ""
// TextTable.set_currentLanguageID(int value)              -> value = 0   (0 = Default = EN)
```
Also clear the saved choice: `PlayerPrefs.SetString("Language", "")`. With language `""`, `Field.LookupLocalizedValue` returns base (English) fields and `TextTable.GetFieldTextForLanguage` falls back to the Default column (and for blank Defaults, to the field name, which is usually English too).

Adapt the entry points to the game's localization framework (Unity Localization `LocalizationSettings.SelectedLocale`, I2 Localization `LocalizationManager.CurrentLanguage`, or a custom manager - find it in the decompiled scripts).

## PlayMaker games (no localization, no strings in Assembly-CSharp)

Indicator: `PlayMaker.dll` in `Managed/`, thousands of `Fsm`/`actionData` blocks in
the YAML, and a JP sweep of `Assets/Scripts/` that comes back empty.

### Decoding `actionData`

PlayMaker serialises action parameters into parallel arrays. Each entry has a
`paramDataType` code selecting which typed column its value lives in
(`stringParams`, `intParams`, `fsmStrings`, …). **The codes are build-specific - do
not hardcode a table.** Derive it and prove it:

1. Sweep every `actionData` block, recording each `(paramDataType, column lengths)`.
2. Solve for the assignment where every column is consumed **exactly**.
3. Assert zero saturation violations. A wrong mapping silently reads the wrong
   column and you extract garbage that looks plausible.

Reference: `RP/Unity Mono PlayMaker (CoinPussy)/scripts/unitytl/pmparams.py`
(`tl.py derive` - run once per export, prints the solved table and the proof).

### Separating display text from engine keys

FSM strings are a mix of dialogue and machinery: state names, animator triggers
(`H_M字ピース`), `StringSwitch` comparison values. Translating a key breaks the game
logic silently. Classify by **site**, not by content:

- A string read by a text-setting action (`setTextmeshProUGUIText`, `UiTextSetText`) → display.
- A string used by `StringSwitch` / `StringCompare` / `SetAnimatorTrigger` → key. Denylist it.
- A string that is **both** (a name-box label that is also a switch value - `支配人`,
  `バニー`, `終了`) → translate it, because the dictionary hook runs on the text
  setter, *after* every FSM comparison has already happened. Exclude these from the
  denylist explicitly or they never translate.

Ship the denylist with the plugin: it also stops the untranslated-text log filling
with animator names.

### CSV script tables - one chokepoint hook

Scripted dialogue often lives in TextAsset CSVs parsed through PlayMaker's
DataMaker addon. Every one of them passes through a single static method:

```
HutongGames.PlayMaker.Ecosystem.DataMaker.CSV.CsvReader.LoadFromString(string file_contents, bool, char)
```

One Harmony prefix there swaps the whole file for a translated copy - every row at
once, no per-cell ambiguity, no repack. Resolve it by name via
`AccessTools.Method("Namespace.Type:Method")` so the plugin still builds if the game
updates, and match the Harmony parameter name (`file_contents`) exactly.

**Key the swap on SHA-1 of the original file, not its name or header.** A CSV the
pipeline never saw then simply does not match and stays Japanese, which rules out
the one failure mode that is invisible in play: a stale translation silently
substituted for content it was not built from. Log the unrecognised file's header
and what to re-run. Ship a `DumpLoadedCsv` debug option that writes every CSV the
game parses - that is how you catch one the extractor missed after an update.

### BOM discipline

`TextAsset.text` **keeps** the UTF-8 BOM on Unity 2022.3. Two consequences:

- The first CSV field is a column key the FSMs look up by name. Adding or removing a
  BOM silently renames it. Preserve the caller's BOM state exactly - strip it for
  hashing, re-attach it if the input had one.
- Strings reaching the UI can carry one too. **`String.Trim()` does not treat U+FEFF
  as whitespace in .NET**, so a dictionary key without the BOM never matches one
  with it. Strip U+FEFF explicitly in your normaliser.

## Step 4 - dictionary hook (when text is genuinely Japanese)

Build a BepInEx 5 plugin that hooks text setters and swaps JP→EN from a bundled JSON dict.
Reference: `tools/Game Translation/Reference Pipelines/Unity Mono (NTR Soccer)/mod/NTRSoccerEnglish/` (ported from `tools/Game Translation/Unity BepInEx Translation Plugin Template/SheepClickerTL/`, which is IL2CPP - for Mono, target `BaseUnityPlugin`/`Awake` not `BasePlugin`/`Load`, and reference the real `TMP_Text`/`Text` types directly).

Hooks (two coverage layers):
```
Prefix  TMP_Text.set_text(ref string value)             -> translate in place
Prefix  TMP_Text.SetText(ref string sourceText, bool)
Prefix  UnityEngine.UI.Text.set_text(ref string value)
Postfix TextMeshProUGUI.Awake / OnEnable (TMP_Text __instance)  -> refresh deserialized labels
Postfix TextMeshPro.Awake / OnEnable
Postfix UI.Text.OnEnable
```
The Awake/OnEnable postfixes catch text Unity wrote directly to the `m_text` backing field during scene deserialization (never goes through the setter). Re-assigning `t.text` there routes through the setter prefix.

`TranslationStore` (dict lookup): exact match, newline-normalized match (`\\n`/CRLF/trim), `{0}`-format-pattern matching (compile JP `得点 {0}/{1}` → regex, splice captures into EN template, **slot-aware** so `{1}は{0}`→`{0} is {1}` maps correctly), and a compose walk for concatenated strings.
**Gate the compose/pattern paths behind "input contains JP"** and **reject a compose result that leaves any JP in the passthrough** - otherwise a 2-char key like `ん？` corrupts novel strings mid-word (`さん？`→`さHm?`).
Cap the hit/miss caches (dynamic timers/counters grow them unbounded).
Log unmatched JP to `untranslated.txt` for the QA loop.
Hand-rolled flat JSON parser (`{ "<jp>": "<en>" }`) - no external deps.

## Step 5 - build & install

Compile against the game's own DLLs (`<Game>_Data/Managed/`) + BepInEx core. Csc from VS is fine. **add `netstandard.dll` from the game's Managed folder** as a reference or you get `CS0012: type 'Object' ... netstandard`:
```powershell
csc /target:library /out:Mod.dll `
  /r:"$Managed\mscorlib.dll" /r:"$Managed\netstandard.dll" `
  /r:"$Managed\UnityEngine.CoreModule.dll" /r:"$Managed\UnityEngine.UI.dll" `
  /r:"$Managed\Unity.TextMeshPro.dll" /r:"$Managed\Assembly-CSharp-firstpass.dll" `
  /r:"$Core\BepInEx.dll" /r:"$Core\0Harmony.dll" *.cs
```
Install to `BepInEx/plugins/<ModName>/` with a `translations/` subfolder for the dict. Verify by launching 30s and reading `BepInEx/LogOutput.log` for "N plugins to load" and your hook count.

**Log your verbose swaps at Info, not Debug.** BepInEx's default disk `LogLevels`
excludes `Debug`, so a `LogDebug` line makes `VerboseLogging = true` look broken
unless the user also edits `BepInEx.cfg`.

## Step 6 - the coverage A-test

With the untranslated logger on, play a pass and diff what reached a text component
against what you extracted. On a real run this was **131 of 132 already extracted**,
and the one exception was built at runtime by joining two FSM variables - both of
which *were* extracted separately, and which the store's compose fallback splices.
So coverage was effectively total, and the test proved it rather than assuming it.

Normalise both sides before diffing (unescape the logger's `\n`, strip BOM and CRLF)
or you will chase phantom misses. That same diff is what surfaced the U+FEFF bug.

## Step 7 - fit the text to its boxes

TMP renders CJK already, so EN needs no font work - but it will overflow boxes
authored for full-width glyphs, and **matching the source's line count does not
prevent it**. Measure the box and wrap to it: `references/text-fitting.md`, toolkit
at `tools/Game Translation/Text Fitting/layout.py`. Auto-sizing
(`tools/Game Translation/Unity BepInEx Text Layout Plugin`) is the fallback for the
long tail of individually-sized widgets, not the fix for dialogue.

## Step 8 - ship it: a build for players, not for you

The dev install logs everything on purpose. A release must not, or the first thing
a player sees is a console window full of Harmony chatter.

```
BepInEx.cfg   [Logging.Console] Enabled = false     # no console window
              [Logging.Disk]    Enabled = false     # no LogOutput.log
plugin cfg    VerboseLogging   = false
              LogUntranslated  = false              # no untranslated.txt
              DumpLoadedCsv    = false
```

Several sections of `BepInEx.cfg` share the key name `Enabled`, so edit
**section-aware** - a blind `Enabled = true -> false` also disables the chainloader
and the patch silently stops loading.

Exclude from the copy: your `tools/`, the AssetRipper export, `BepInEx/cache/`
(machine-specific, regenerates), `LogOutput.log`, `untranslated.txt`, `__pycache__`.
Keep `winhttp.dll`, `doorstop_config.ini` and `.doorstop_version` - drop those and
BepInEx never loads, and the game just runs in Japanese with no error.

Ship **two** artefacts. The patch-only archive (plugin + `translations/` + config +
readme, laid out to extract over a game folder) is a couple of hundred KB and is the
one you can hand out. A full repack is the game itself and a licensing question, not
a technical one.

Verify by running the distribution copy and confirming no `LogOutput.log` and no
`untranslated.txt` appear. The general release discipline, including the archive
denylist, is in `playtesting-and-release.md`.

**Windows gotcha:** `[` and `]` are wildcards to PowerShell's path parser, so a
folder like `Game [English v1.0]` makes `Copy-Item`/`Compress-Archive` match nothing
and succeed silently - producing an empty archive with no error. Use `-LiteralPath`,
or build the archive from a language that does not glob.
