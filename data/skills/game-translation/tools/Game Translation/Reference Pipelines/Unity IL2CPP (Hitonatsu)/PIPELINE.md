# ひと夏の思い出 - English translation pipeline

Unity **6000.3.6f1**, **IL2CPP**, metadata **v39**, x64.
Developer はちみつサンド. R18 3D story + free-viewing mode.
Delivery is a **BepInEx 6 runtime dictionary** - no game file is modified.

```
extract  ->  translate (Mistral)  ->  qa  ->  build  ->  plugin  ->  playtest
```

---

## 0. Scope, measured

The whole player-visible corpus is **207 units / 199 distinct strings**. That is
not an estimate; it is what four independent readers agree on.

| Source | Units | Where |
|---|---|---|
| Dialogue Database (`Dialogue Text` 45, `Menu Text` 1) | 46 | `MonoBehaviour/Dialogue Database.asset` |
| Scene TMP labels (`m_text`) | 36 | `_Project/Scenes/Release.unity` |
| Dropdown captions and options | 12 | same scene |
| IL2CPP string literals | 8 | `global-metadata.dat` |
| Voice dropdown options, built at runtime | 105 | `StreamingAssets/aa/catalog.bin` |
| Title logo (baked into a PNG) | 1 image | `Texture2D/TitleLogo.png` |

**The story is genuinely 45 lines**, one conversation (`Story`) of 76 entries
across three in-game days. Verified four ways: the DB parse, a raw
length-prefixed-UTF8 byte walk of every MonoBehaviour blob, a UnityPy walk of
`data.unity3d` and all three Addressables bundles, and a guid-resolution pass
over all 349 `.unity`/`.prefab`/`.asset` files finding exactly one
`DialogueDatabase`. The bundles hold **only** AudioClips and ComputeShaders -
no text, no second database.

### What is deliberately NOT translated

Every Japanese-bearing field in the shipped data is ruled on in
`tools/hitonatsu/classify.py`. A field in neither table is a **fatal**
extraction error, not a warning - that is what makes it a gate, and what will
catch a field a future game build introduces.

| Excluded | Why - the evidence, not the guess |
|---|---|
| PlayMaker `fsm.states[].name`, `toState`, `startState`, `fsm.name` (928) | `toState` must equal `states[].name` byte for byte, or scene flow breaks silently |
| `shapeName` (33) | Blendshape channel, looked up by name. The game's own error string `…というシェイプキーが見つかりません。名前が合っているか確認してください。` proves it |
| `mixerKeySettings[].keyword` (声1..声4) | Substring-matched against an Addressables address - see the log literal `[VoiceOverride Mixer] アドレス名: ` |
| `GameObject.m_Name` (66) | Armature bones (mostly the literal word ボーン) |
| DB `Sequence` / `Conditions` / `Title` / actor `Name` | Executable Lua and Lua keys |
| .NET calendar eras (令和/平成/昭和/大正/明治/中華民國) | `System.Globalization`, never on screen |
| 年 / 月 / 日 / 時 / 分 / 秒 | **Looks like a playtime readout and is not.** literal caller analysis resolves every one to `DateTimeFormatInfoScanner.get_KnownWords` / `DateTimeFormatInfo.PopulateSpecialTokenHashTable`. The real playtime is `GameInfoManager.UpdateTimerText` (RVA `0x776B00`) building `String.Format("{0:D2}:{1:D2}:{2:D2}", …)` - language-neutral `HH:MM:SS`. Translating them would have put a live `分`→`m` rule into a dictionary applied to every string on screen, for no gain |
| `LineBreaking Following Characters` TextAsset | TMP's kinsoku table. **UnityPy found it; AssetRipper never exported it** - a real blind spot, and the correct handling is to leave it alone |
| ~150 AudioClip names, world-prop art | Asset paths / set dressing |

---

## 1. Prerequisites (already done in this checkout)

- AssetRipper export at `<game>/AssetRipper_export_20260829_001509/`
- BepInEx 6 IL2CPP installed in the game folder, interop assemblies generated
  (118 dlls). Launch the game once if `BepInEx/interop/` is missing.
- `RE/dump/` from **`Tools/.NET/Il2CppDumper-ManualReg`**. Stock Il2CppDumper
  6.7.46 rejects metadata v39 outright (`not a supported version[39]`); the fork
  reads it and auto-finds `CodeRegistration=0x182c67a50`,
  `MetadataRegistration=0x1833fed20`.
- `RE/dump/lifter.db` from `Tools/.NET/Il2CppLifter` (`build` then `xref-build`).
- Python: `PyYAML`, `UnityPy`, `Pillow`. `dotnet` SDK for the plugin.
- Two Mistral free-tier keys in `tl/mistral_keys.txt` (gitignored), or
  `MISTRAL_API_KEYS` in the environment.

**Always run Python with `PYTHONIOENCODING=utf-8`.** The console here is cp1252
and any Japanese in a traceback kills the process. `tools/hitonatsu/common.py`
rewraps stdout, but the environment variable covers everything else.

---

## 2. Run it

```bash
cd C:/Users/sw/Desktop/Projects/hitonatsu-en

PYTHONIOENCODING=utf-8 python tools/extract.py            # -> workspace/units.json  (207 units)
PYTHONIOENCODING=utf-8 python tools/translate_mistral.py run
PYTHONIOENCODING=utf-8 python tools/translate_mistral.py report   # READ THIS
PYTHONIOENCODING=utf-8 python tools/qa.py
PYTHONIOENCODING=utf-8 python tools/build.py              # -> plugin/.../translations/*.json
PYTHONIOENCODING=utf-8 python tools/make_title_logo.py    # -> images/out/TitleLogo.png
PYTHONIOENCODING=utf-8 python tools/pack_images.py        # -> plugin/.../images/*.tex

cd plugin/HitonatsuTL && dotnet build -c Release           # builds AND deploys into the game
```

Measured cost of a full run: **16 API calls, 36,600 input + 4,765 output
tokens**, comfortably inside one free-tier key's 25k tokens/minute. Two keys run
in parallel anyway.

---

## 3. The pieces

### `tools/extract.py`
Walks the Dialogue Database and the scene through `hitonatsu/unityyaml.py` (Unity
emits `!u!` tags PyYAML rejects, so documents are split by hand and a
multi-constructor is registered), classifies every Japanese field, masks control
codes to `⟦N⟧` sentinels, and writes `workspace/units.json`.

Two safeties worth knowing about:
- **It refuses to shrink the store.** Extraction reads the game folder; after an
  in-place patch that folder is the English build, so a re-run would find nothing
  and save the emptiness over real work.
- **It preserves existing `tl` values** by unit id, so re-extracting after a game
  update does not throw away finished translations.

### `tools/translate_mistral.py`
Ported from `Reference Pipelines/Unity Mono (NTR Soccer)`. stdlib only. Two keys,
one `AdaptiveLimiter` each, synced to the live `x-ratelimit-remaining-*` headers
(measured on this account: 50 req/min, 25,000 tokens/min per key).

Batching follows the rule that dialogue needs continuity and nothing else does:
**dialogue goes out one scene at a time, in play order, speaker-labelled, not
deduped**; UI/dropdown/literal are deduped globally.

> **Prompt ids are batch-local (`n1`, `n2`, ...), not unit ids.**
> The real ids look like `ui:6404:MonoBehaviour.m_text` and the model reliably
> truncates them at the second colon, so it answered with keys matching nothing
> and **every UI batch scored 0/8 while reporting no error**. Short opaque tokens
> round-trip; `batch["keymap"]` maps them back.

### `tools/catalog_addresses.py` + `hitonatsu/voiceopts.py` - the 105 that were nearly missed

The voice dropdown has 105 options and **not one of them is in any asset file**.
`VoiceFaceOverrideController` ships `replaceSetList: []` and `addressableLabel:
OverrideVoice`, so the list is built from Addressables at runtime. In
`<InitializeReplaceDataAsync>d__36.MoveNext` (RVA `0x792780`) each
`ReplaceSet.setName` is assigned the address itself:

```
rax[0x10] = loc2;                                 // setName = address
var v26 = loc2.Substring(removePrefix.Length);    // ...or minus the prefix
```

`removePrefix` is empty in the scene, so `setName` **is** the address, and
`SetupDropdownOptions` (RVA `0x7963E0`) feeds it straight into `OptionData`.

Two things hid this:
- The addresses are **UTF-16LE** in `catalog.bin`. A UTF-8 scan of that file
  returns zero Japanese, which reads exactly like "there is nothing here".
- `GetBaseSituationName` (RVA `0x795200`), which slices an address at
  喘ぎ/絶頂/余韻, *looks* like the label builder. It is not - its only caller is
  `b__36_0`, a `String.Compare`/`CompareTo` **sort comparator**. Chasing it leads
  away from the real path.

They are translated **by construction**, not by the model: 105 options over four
vocabulary words in a fixed shape (`声N_喘ぎNN` -> `Voice N - Moan NN`). Generating
them makes it impossible for `声1_喘ぎ01` and `声3_喘ぎ07` to disagree about what
喘ぎ means - the exact parallel-construction drift a 105-unit model pass invites.
These units carry `locked: true`; the driver skips them and QA still checks them.

### `tools/qa.py`
Exit non-zero on any hard failure. `tools/build.py` runs it and refuses to
package if it fails.

| Check | Why it exists here specifically |
|---|---|
| `font-coverage` | The TMP atlas is **static** (`m_AtlasPopulationMode: 0`), 7,129 baked glyphs, **empty fallback table**. Anything outside that set draws blank |
| `same-source` | Delivery is keyed on the source string, so two translations of one key means one silently wins everywhere |
| `parallel-drift` | Masks digits and groups, catching `Override01..06` drifting apart where a same-source check cannot |
| `placeholders` | Compared on the **restored** string the engine parses, not the masked form the model saw |
| `brackets` | The protagonist's spoken lines are marked `「 」`; losing them reattributes the line |
| `residual-jp` | Any Japanese left in English |
| `expansion` | Reports how far English runs past the Japanese. Bears on box fit only - see the FacialLipSync note |

**Two of these checks were wrong on their first run and were fixed before any
translation was touched**, which is the right order:
- `font-coverage` flagged `\n` and `\r` as missing glyphs and accused every
  multi-line label in the game. Control characters are layout, not glyphs.
- `lipsync-length` flagged 36 of 45 dialogue lines at a 1.6x threshold. Japanese
  is dense; ~2.1x is the *normal* expansion for this pair, so the check was
  measuring the language, not the translation. It is now an informational
  `expansion` report scoped to box fit.

False-positive rate went from 39-of-41 findings to 0.

### `tools/build.py`
Emits `{japanese: english}` into numbered files (later file wins):
`00_dialogue`, `10_ui`, `20_dropdown`, `25_voice`, `30_literal`, `99_overrides`. Runs `qa.py` first and refuses on failure.

> **Caveat inherited from the store:** "last file wins" is only true for keys
> **without** a `{0}`-style placeholder. `TranslationStore` routes placeholder
> keys to an append-only `_patterns` list sorted by literal length, so an
> override of such a key would not reliably win. **This corpus has zero
> placeholder keys**, so it does not bite here - but it would after adding one.

### Images ship as raw pixels, because the PNG decoder is unusable

`ImageConversion.LoadImage` cannot be called on this build **at all**. Every
overload in the interop funnels into the same place:

```csharp
public static bool LoadImage(Texture2D tex, Il2CppStructArray<byte> data)
    => LoadImage(tex, new Il2CppSystem.ReadOnlySpan<byte>(...), false);
```

and the span path needs `Il2CppSystem.ReadOnlySpan<byte>.GetPinnableReference`,
which this game's corlib has stripped:

```
failed to load TitleLogo.png: Method not found:
  '!0 ByRef Il2CppSystem.ReadOnlySpan`1.GetPinnableReference()'
```

Changing the argument type does not help, and neither does reading the bytes on
the il2cpp side with `Il2CppSystem.IO.File.ReadAllBytes` - both were tried, both
fail identically, because the conversion happens *inside* LoadImage.

So decoding moved to build time. `tools/pack_images.py` turns each PNG in
`images/out/` into a `.tex`: `"HTEX"`, width, height, then RGBA32 rows
**bottom-up** (Unity's texture origin is lower-left and `LoadRawTextureData`
writes the buffer verbatim). At runtime the plugin pins the managed buffer and
calls `LoadRawTextureData(IntPtr, int)`, which has no span dependency.

Cost is size: 1400x300 is 1.6 MB raw against 16 KB as PNG. It deflates well in
the release zip and there is exactly one image.

### Deployment mirrors, it does not merge

`DeployPlugin` deletes the deployed `translations/*.json` and `images/*.png`
before copying. A plain `Copy` never deletes, so a payload file removed from the
source stayed in the game folder and kept being loaded - and **every gate stayed
green**, because `qa.py` and `build.py` read the source tree and the store, never
the output. That is how `40_composed.json` survived one build after the rules in
it were deleted for being wrong.

### `workspace/overrides.json`
Hand rulings keyed by source string, each with its reason, applied last and
honoured by QA so a fix survives `--retranslate`. Currently resolves the two
same-source dropdown conflicts by corpus majority (spaced, not underscored).

---

## 4. The plugin - and the two defects translating *creates*

`plugin/HitonatsuTL/`, BepInEx 6 IL2CPP, `net6.0`, no NuGet packages (every
reference is a `HintPath` into the game install). Building auto-deploys to
`<game>/BepInEx/plugins/HitonatsuTL/`.

Coverage layers:
1. `TMP_Text.text` / `SetText` **setter prefixes** - runtime writes.
2. `TextMeshProUGUI`/`TextMeshPro` **Awake/OnEnable postfixes** - text Unity
   deserialized straight into the `m_text` backing field, which never passes
   through the setter. This is what the 36 scene-baked labels need.
3. **`TMP_Dropdown` postfixes** - the voice and expression dropdowns are built at
   runtime by slicing Addressables address strings
   (`VoiceFaceOverrideController.GetBaseSituationName`, RVA `0x795200`, which
   truncates the address at 喘ぎ / 絶頂 / 余韻), so those labels exist in **no
   asset file** and static extraction could never have found them.
4. **`TextSweep`** - a periodic `FindObjectsOfType<TMP_Text>` pass. Insurance for
   exactly the class above.
5. **`ImagePatches`** - swaps a sprite by its original name against a PNG in
   `images/`. Reports any replacement that never matched, because a swap that
   silently never applied looks identical to one that did.

### FacialLipSync: the trap that looked like two defects and is neither

Worth writing down, because everything about it says "patch me" and the correct
action is to do nothing.

`FacialLipSync..ctor` (RVA `0x7761B0`) sets three defaults that together look
like an English patch is about to break the game:

```
this.textUIName        = "SubtitleText";
this.speakerNameUIName = "SpeakerNameText";
this.targetSpeakerName = "美羽";
```

and the code around them backs the story up. `Update` (RVA `0x775890`) gates lip
sync on `String.Equals(speakerNameText.text, targetSpeakerName)` - so translating
the nameplate to "Miu" should stop the mouth forever. `UpdateTextLipSyncLogic`
(RVA `0x7756F0`) sizes mouth time from the subtitle's character count:

```
mulss xmm0,[rbx+58h]      ; xmm0 *= durationPerCharAfterFinish
movss [rbx+0A8h],xmm0     ; remainLipSyncTime = xmm0
```

- so English at a measured median 2.10x should over-run every voice clip.

**Both readings are wrong, and the disassembly is not where the error is.** All
of the above is accurate. What it omits is that a ctor default is only a
*hypothesis* about runtime state: Unity's serialized scene values overwrite it
before anything runs. Both `FacialLipSync` instances in `Release.unity` (lines
160637 and 169023) serialize **all three fields empty**:

```
    textUIName:
    speakerNameUIName:
    targetSpeakerName:
```

`GameObject.Find("")` returns null, so `TryFindTextUI` (RVA `0x7752A0`) never
assigns `targetText` or `speakerNameText`. `UpdateTextLipSyncLogic` returns at
its first null check, so `durationPerCharAfterFinish` is never read; the speaker
comparison sits behind a `speakerNameText != null` guard and is never reached.
Lip sync in this build runs entirely off `GetWeightFromAudio` ->
`activeSource.GetOutputData`, which is audio amplitude and is indifferent to how
long the subtitle is.

**A first version of this plugin patched both**, rewriting `targetSpeakerName`
to "Miu" at `Start` and scaling `durationPerCharAfterFinish` by 0.476. Neither
did anything, and both were changes to shipped state made on a false premise.
They have been removed. If a future build fills those three fields in, the
analysis above becomes live again - **check the serialized values first**.

The general rule this is an instance of: verifying the CODE is not verifying the
DATA. A field's runtime value comes from the scene, not the constructor.

### Config (`BepInEx/config/com.sw.hitonatsu.tl.cfg`, written on first run)

| Key | Default | Notes |
|---|---|---|
| `General/Verbose` | false | logs every swap |
| `General/FallbackContains` | false | substring fallback; can half-translate |
| `QA/Harvest` | false | **must be false in a release** |
| `Layout/AutoSize` | true | shrink-to-fit; deliberately does **not** set `overflowMode=Ellipsis`, because clipping a subtitle loses words silently |
| `Coverage/Sweep` | true | |
| `Coverage/SweepIntervalSeconds` | 5 | |

---

## 5. Finding what static extraction missed

Set `QA/Harvest = true`, play through all three days **and** Free Mode with every
dropdown opened. Every Japanese string that reaches a text component without a
dictionary hit is appended to
`BepInEx/plugins/HitonatsuTL/untranslated.txt` as `where<TAB>text`.

This is the only way to enumerate the runtime-composed dropdown labels, and it is
the check that does **not** share the extractor's blind spot. Add anything it
finds to `workspace/overrides.json` (or to `LITERALS` in `extract.py` if it comes
from metadata) and re-run the pipeline.

**Turn Harvest back off before packaging.**

---

## 6. Playtest matrix

Run after **every** build, not once at the end:

1. Launch. Check `BepInEx/LogOutput.log` for `patched …` lines and
   `N translations, 1 image replacements active`.
2. Title screen - the logo should read *A Summer to Remember*; the three day
   buttons and Credits should be English.
3. Play each day through to the end.
4. Open every settings tab. The rows are fixed width; look for a label that
   collided rather than shrank.
5. Free Mode: open the expression and voice dropdowns and every option in them.
   This is where harvested strings live.
6. Response buttons: the protagonist's 「 」 lines and the action commands
   (`Insert` / `Finish inside` / `Change position`) surface as **menu buttons**,
   not subtitles - check they fit.

Fix and re-test **one** defect before changing anything else.

---

## 7. Release packaging

`python tools/package.py` builds the archive. It ships what is already installed,
minus the denylist:

**Include:** `winhttp.dll`, `.doorstop_version`, `doorstop_config.ini`, `dotnet/`
(the bundled .NET 6 runtime - this is what means a player needs no .NET install),
`BepInEx/core/`, `BepInEx/config/BepInEx.cfg`, `BepInEx/plugins/HitonatsuTL/`.

**Exclude:** `BepInEx/interop/` (~100 MB, regenerated on first launch - that is
the 30-90 second first start), `BepInEx/cache/*.dat`, all `*.log`, the plugin's
own `.cfg` (shipping it freezes dev toggles onto the player), `untranslated.txt`,
`*.pdb`, and the whole dev tree (`tools/`, `tl/`, `RE/`, `workspace/`, `obj/`,
`bin/`).

`tl/mistral_keys.txt` is gitignored and denylisted. Verify by running the
**distribution copy** and confirming no log file appears - config values are an
intention, absent files are the evidence.

---

## 8. If the game updates

1. Re-run AssetRipper and the ManualReg dumper; rebuild `lifter.db`.
2. `python tools/extract.py`. Finished translations are preserved by unit id.
   **An `UnclassifiedPath` exception is the point** - it means a new
   Japanese-bearing field appeared and somebody has to rule on whether it is
   drawn or matched by name.
3. Re-check the serialized `FacialLipSync` fields in the new scene. If
   `textUIName` / `speakerNameUIName` / `targetSpeakerName` are still empty,
   nothing changes; if the developer has filled them in, read the FacialLipSync
   note above, because both problems it describes become real.
4. `qa.py`, `build.py`, rebuild, replay the matrix.
