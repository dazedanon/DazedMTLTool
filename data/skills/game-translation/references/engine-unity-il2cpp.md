# Unity IL2CPP

**Indicators:** `GameAssembly.dll` + `<Game>_Data/il2cpp_data/Metadata/global-metadata.dat`. Code is compiled to native - no readable managed DLLs. Needs dumping to recover types, and BepInEx **6** (IL2CPP build) with Il2CppInterop for plugins.

**Reference implementations:**
- `tools/Game Translation/Reference Pipelines/Unity IL2CPP (Hitonatsu)/` - **the complete pipeline** (extract → Mistral → QA → build → plugin → package). Read its `PIPELINE.md` first; it is the only end-to-end IL2CPP reference here.
- `tools/Game Translation/Unity BepInEx Translation Plugin Template/SheepClickerTL/` - the canonical runtime dictionary plugin (copy this).
- `tools/Game Translation/Unity Text Extraction Pipeline/LoserLife/LoserLifeATest/` - a **second** BepInEx 6 IL2CPP plugin, and the better one to copy patch *registration* from: `AccessTools`-resolved optional targets, `RuntimeTextHarvester.cs`, `TextSweepBehaviour.cs`. The SheepClicker template has none of those.
- `tools/Game Translation/Unity IL2CPP Text Tools/` - extraction scripts + `find_bubble`/`Il2CppStringDump` C# CLIs.
- Finished mod projects (goblin-toybox: BepInEx 6 + bundled .NET runtime + Doorstop, the shipping layout to copy; ntrmeishi: BepInEx 5 Mono, only its negative lessons) are not bundled.

For dumping/reversing a **protected** binary, or building a native trainer instead of a managed plugin, use the **il2cpp-game-modding** skill. This file is the translation path.

---

## Step 0 - environment traps that produce a SILENT zero

Both of these report "no Japanese anywhere" rather than failing, which is the worst possible failure mode for a census.

- **`grep -P` needs `(*UTF)`.** `grep -P '[\x{3040}-\x{30ff}]'` dies with `character value in \x{} is too large` on Git Bash for Windows, and in a pipeline that error scrolls past and you read the empty result as "clean". `grep -P '(*UTF)[\x{3040}-\x{30ff}]'` works. Prefer Python for anything load-bearing.
- **The console is cp1252.** Any Python that prints Japanese - including a traceback containing it - dies with `UnicodeEncodeError`. Run everything with `PYTHONIOENCODING=utf-8` *and* rewrap in the module:
  ```python
  sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
  ```
- Working JP class for this environment: `[぀-ヿ一-鿿ｦ-ﾟ]` (kana, CJK, halfwidth katakana).

## Step 1 - dump types

`tools/.NET/Il2CppDumper-win-v6.7.46/Il2CppDumper.exe GameAssembly.dll global-metadata.dat` (a download, see `tools/THIRD-PARTY.md`) → `DummyDll/`, `script.json`, `stringliteral.json`.

**Metadata v29+ is where the stock tool starts refusing.** On **v39** (Unity 6.x) it prints `ERROR: Metadata file supplied is not a supported version[39]` and exits. Use **`tools/.NET/Il2CppDumper-ManualReg/`** (bundled as source; `dotnet build -c Release Il2CppDumper.sln`, see its `MANUAL_REG_NOTE.md`) - the fork reads v39 and auto-finds both registrations on an unprotected binary with no manual addresses. Check the version first, it is 8 bytes in:

```python
magic, version = struct.unpack_from('<II', open(meta,'rb').read(), 0)   # 0xFAB11BAF, 39
```

**Do not hand-parse the metadata header to recover string literals.** The layout changes between versions (v39 is *triples* - offset, size, count - not offset/size pairs), a wrong guess decodes 8,184 literals into plausible-looking garbage, and "7,537 of them contain Japanese" looks like a result rather than a bug. The fork's `stringliteral.json` is the answer.

Before treating a literal or method as player-facing, verify its callers and runtime use against the game’s code and scene data. Record that evidence alongside the extraction.

---

## Step 2 - extract text: four readers, four different blind spots

No single reader sees everything. Run all four and reconcile - the disagreements are the findings.

1. **AssetRipper export** - the only one that resolves `MonoBehaviour` typetrees on an IL2CPP build. This is where scene TMP `m_text`, ScriptableObject databases and serialized component fields come from. Parse the YAML with a `!u!` multi-constructor (see below).
2. **UnityPy over the shipped containers** (`data.unity3d`, `resources.resource`, every `.bundle`) - generic and independent of AssetRipper's reader, so it catches assets AssetRipper never exported. It **cannot** typetree `MonoBehaviour` here (returns raw bytes), so it complements rather than replaces #1. On one game it was the only reader that saw a `TextAsset` at all. It also enumerates Texture2D/Sprite cheaply - **report which of those carry baked Japanese, do not translate them**; images are opt-in and separately requested (SKILL.md step 8).
3. **A raw byte walk of the MonoBehaviour blobs** - Unity serializes a managed string as `int32 length + UTF-8`, 4-aligned. Walking that shape reaches fields no typetree reader has, which is exactly the point: it does not share the extractor's blind spot. Use it to *confirm* #1 found everything, not as a primary source.
4. **`stringliteral.json`** - hardcoded UI strings compiled into the binary.

**Unity YAML needs a custom loader.** Unity emits `--- !u!<classID> &<fileID>` headers and `!u!` local tags that PyYAML rejects outright. Split the documents on the header regex and register a passthrough multi-constructor; you get plain dicts *and* the `fileID` as a stable per-object id:

```python
class _Loader(yaml.SafeLoader): pass
_Loader.add_multi_constructor("tag:unity3d.com,2011:", _passthrough)
_Loader.add_multi_constructor("!u!", _passthrough)
DOC_RE = re.compile(r"^--- !u!(\d+) &(\d+)(?: stripped)?\s*$", re.M)
```
A 6.8 MB scene parses in ~8s this way.

**Classify every JP-bearing field path, and make an unruled path FATAL.** Normalise list indices (`a[3].b` → `a[].b`), then require each distinct path to appear in a DISPLAY or an INTERNAL table with its reason. Defaulting an unknown path to *failure* is what makes it a gate rather than a report, and it is what catches the field the next game build adds. Typical INTERNAL set on a Unity game, each with real evidence:

| Field | Why it is a key, not text |
|---|---|
| PlayMaker `fsm.states[].name` / `.transitions[].toState` / `startState` / `fsm.name` | `toState` must equal `states[].name` byte for byte |
| `shapeName` | Blendshape channel looked up by name - the game's own error string usually says so |
| `*.keyword` matched against an Addressables address | A key; the game logs the address next to it |
| `GameObject.m_Name` | Bones and scene objects, resolved by `GameObject.Find` |
| `LineBreaking Following Characters` TextAsset | TMP's kinsoku table. Leave it alone |
| .NET calendar eras (令和/平成/昭和/…) | `System.Globalization`, never on screen |

**A single-CJK literal is almost never what it looks like.** `年 月 日 時 分 秒` read as a playtime widget waiting to be translated; caller analysis resolved every one to `DateTimeFormatInfoScanner.get_KnownWords` and `DateTimeFormatInfo.PopulateSpecialTokenHashTable` - .NET's Japanese calendar tables, reachable from no game code - while the real playtime was `String.Format("{0:D2}:{1:D2}:{2:D2}")` with no Japanese in it. Translating them would have put a live `分`→`m` rule into a dictionary applied to **every string that reaches a text component**. Resolve each short literal to its caller before extracting it.

---

## Step 3 - the text that is in NO file

This is the class that static extraction structurally cannot reach, and on one game it was **half the corpus** (105 of 207 units).

**Symptom:** a component with an empty serialized list plus an Addressables label - `replaceSetList: []`, `addressableLabel: OverrideVoice`. The list is built at runtime, so the labels exist in no asset.

**Where they actually live:** `StreamingAssets/aa/catalog.bin`, as length-prefixed **UTF-16LE**. A UTF-8 scan of that file returns *zero* Japanese and reads exactly like "there is nothing here". Decode the whole blob at **both byte parities** and pull readable runs out of the text - hand-walking the blob and guessing where a string starts gets the alignment wrong one byte in two, which turns `ogg` (`6F 00 67 00`) into `漀最最`, CJK-looking mojibake that passes a Japanese test and poisons the result.

**Then confirm the address actually becomes the label**, in the code, before believing it:

- **Check the plausible function’s callers first.** On one game `GetBaseSituationName` sliced an address at exactly the right markers and looked certain to be the label builder; its only caller was a `String.Compare`/`CompareTo` **sort comparator**. Chasing it leads directly away from the real path. A name is a hypothesis.
- The real path was `setName = address` in the async state machine, then a `SetupDropdownOptions` that feeds `setName` straight into `OptionData`. Tracing the empty-state placeholder located that path, because the placeholder literal only exists in the method that builds the options.

**Translate a generated family BY CONSTRUCTION, not with the model.** 105 options over four vocabulary words in a fixed shape (`声N_喘ぎNN` → `Voice N - Moan NN`) is a generator, not a translation job. It costs nothing, and it makes it *impossible* for `声1_喘ぎ01` and `声3_喘ぎ07` to disagree about what 喘ぎ means - the exact parallel-construction drift a 105-unit model pass invites. Mark those units `locked`, have the driver skip them and QA still check them.

**Runtime harvest is the backstop**, not the plan: a config flag that appends every JP string reaching a text component with no dictionary hit to `untranslated.txt`. It is the only pass that does not share the extractor's blind spot. Must be **off** in a release build.

---

## Step 4 - the trap that costs the most: code is not data

**A constructor default is a HYPOTHESIS about the runtime value. The serialized scene value is the truth, and it silently wins.**

This produced two confidently-wrong patches in one session. `FacialLipSync..ctor` set `textUIName = "SubtitleText"`, `speakerNameUIName = "SpeakerNameText"`, `targetSpeakerName = "美羽"`. `Update` gated lip sync on `String.Equals(speakerNameText.text, targetSpeakerName)` - so translating the nameplate would obviously break it - and `UpdateTextLipSyncLogic` sized mouth time from the subtitle's **character count**, so English at 2.1x would obviously overrun every voice clip. Both readings were supported by correct disassembly at correct RVAs.

Both were wrong. **Every instance in the scene serialized all three fields empty**, `GameObject.Find("")` returns null, neither field was ever assigned, and both code paths were dead - lip sync ran off audio amplitude and did not care about text at all. The patches did nothing, and the documentation asserted they fixed real defects.

Before building anything on a field: **grep the scene/prefab for that component and read the serialized values.** It is thirty seconds and it is the difference between a fix and a fiction. The same applies in reverse - a field that looks inert in code may be filled in by the scene.

---

## Step 5 - hook targets

Get the real signatures out of `dump.cs`; do not invent them.

- `TMP_Text.set_text` / `SetText(string, bool)` **prefixes** - runtime writes.
- `TextMeshProUGUI` / `TextMeshPro` `Awake` + `OnEnable` **postfixes** - text Unity deserialized straight into the `m_text` backing field, which never passes through the setter. This is what scene-baked labels need.
- `TMP_Dropdown` `Awake` + `RefreshShownValue` postfixes - dropdown options never touch a text setter. Mutate `OptionData.text`; selection is index-based (`UnityEvent<int>`), so this is safe. Re-running is free because an already-English option misses the dictionary.
- **A periodic `FindObjectsOfType<TMP_Text>` sweep** for anything already enabled when the plugin installed, or written by a path that bypasses the property. (Sweep `Image` in the same pass *only* if image replacement was actually asked for.)
- **Typewriter effects** need hooking at the coroutine *entry* (`StartTyping` / `PlayText`), not at the setter - partial `Substring(0,n)` frames never match a dictionary key.
- PixelCrushers Dialogue System: `StandardUISubtitlePanel.SetSubtitleTextContent` / `SetFormattedText`, `StandardUIResponseButton.SetFormattedText`, and `UITextField.set_text` as the funnel. Note that `TMP_Text::set_text` typically has **zero direct callers** - every write is vtable dispatch, so an E8-only xref scan sees nothing and that is not evidence of absence.

**Register patches explicitly, not with `PatchAll`.** `AccessTools.DeclaredMethod(...)` returning null should log and skip, so a target the next game build renames costs one feature with a line in the log instead of taking the whole translation layer down.

---

## Step 6 - the plugin (BepInEx 6 IL2CPP)

Copy `SheepClickerTL`; take registration and harvesting from `LoserLifeATest`. `net6.0`, **zero PackageReferences** - every dependency is a `<Reference>` with a `HintPath` into the game install and `<Private>false</Private>`, from `BepInEx/core` and `BepInEx/interop`.

- `BasePlugin` + `Load()`, `internal static new ManualLogSource Log` (the `new` is required).
- `TranslationStore` with a hand-rolled flat JSON parser (`System.Text.Json` is not available). Exact + normalized + `{0}`-format-pattern + compose matching, capped caches.
- Numbered payload files, later wins: `00_dialogue.json`, `10_ui.json`, `…`, `99_overrides.json`. **Caveat: "last file wins" is only true for keys WITHOUT a `{0}`-style placeholder** - those go to an append-only `_patterns` list sorted by literal length, so an override of a placeholder key does not reliably win.
- Log at `LogInfo`, not `LogDebug`: BepInEx's default disk `LogLevels` excludes Debug, so the template's debug calls look broken.
- Custom `MonoBehaviour`s need `ClassInjector.RegisterTypeInIl2Cpp<T>()` and an `IntPtr` constructor.
- Build: install BepInEx 6 IL2CPP, **launch the game once** to generate `BepInEx/interop/`, then `dotnet build -c Release`.
- **Make the deploy target MIRROR, not merge.** A plain `<Copy>` never deletes, so a payload file you removed from the source stays in the game folder and keeps being loaded - while every gate stays green, because they read the source tree and the store, never the output. `<Delete>` the deployed payload before copying.

### Il2CppInterop: the marshalling wall

*Only relevant if the user asked for image work - image replacement is opt-in (SKILL.md step 8), and on this game it was scope creep nobody requested. Read on when it has actually been asked for.*

**`ImageConversion.LoadImage` can be entirely unusable, and no argument type fixes it.** Every overload funnels into the same place:

```csharp
public static bool LoadImage(Texture2D tex, Il2CppStructArray<byte> data)
    => LoadImage(tex, new Il2CppSystem.ReadOnlySpan<byte>(...), false);
```

and the span path needs `Il2CppSystem.ReadOnlySpan<byte>.GetPinnableReference`, which stripped corlibs do not have:

```
Method not found: '!0 ByRef Il2CppSystem.ReadOnlySpan`1.GetPinnableReference()'
```

Passing `Il2CppStructArray<byte>` instead of `byte[]` does not help. Reading the bytes with `Il2CppSystem.IO.File.ReadAllBytes` instead of `System.IO.File` does not help. The conversion happens **inside** `LoadImage`.

**Fix: decode at build time and upload raw pixels.** `Texture2D.LoadRawTextureData` goes straight to `LoadRawTextureDataImplArray` with no span dependency, and its `(IntPtr, int)` overload avoids IL2CPP arrays entirely:

```csharp
var handle = GCHandle.Alloc(blob, GCHandleType.Pinned);
try  { tex.LoadRawTextureData(IntPtr.Add(handle.AddrOfPinnedObject(), headerLen), byteCount); }
finally { handle.Free(); }
tex.Apply(false, false);
```

Ship RGBA32 rows **bottom-up** - Unity's texture origin is lower-left and `LoadRawTextureData` writes the buffer verbatim. Raw is ~100x the PNG on disk and deflates back to about PNG size in the release zip.

**The general rule:** before assuming an interop call works, `ilspycmd -t <Type> <interop dll>` and read what the generated proxy actually does. `ilspycmd` is a dotnet global tool; on Git Bash invoke it by full path (`~/.dotnet/tools/ilspycmd.exe`) because it is not on PATH.

---

## Step 7 - fonts: check before assuming you need a font swap

Read the TMP font asset the scene actually references (check *all* TMP components - a project can ship `LiberationSans SDF` with zero references):

- `m_AtlasPopulationMode: 0` means **Static** - the character set is baked and `m_FallbackFontAssetTable: []` means anything outside it draws **blank**.
- Even so, a Japanese font like Noto Sans JP normally bakes all 95 printable ASCII plus curly quotes and ellipsis, so an English patch usually needs **no font work at all**. Verify rather than assume, in either direction.

Bake the covered codepoint set into a QA gate: any character in a translation outside it is a hard failure. **Skip control characters** - `\n` and `\r` are layout, not glyphs, and flagging them accuses every multi-line label in the game.

---

## Coverage, layout, release

- A-test plugin: replace every known extracted string with `"A"` at runtime; anything still Japanese on screen is unextracted.
- Layout: `tools/Game Translation/Unity BepInEx Text Layout Plugin/VBV` - postfix `GenerateTextMesh` for auto-sizing. Its `References/` DLLs are not bundled: copy them from the game's `Managed/` and BepInEx `core/` before building. Enable auto-sizing but **do not set `overflowMode = Ellipsis` globally**: right for a button, wrong for a subtitle, where it silently drops words.
- Report expansion (JP→EN runs ~2.1x here) as a **box-fit** signal only. A per-line threshold below ~3x flags most of the corpus and is measuring how dense Japanese is, not how good the translation is.
- Release: ship `winhttp.dll`, `.doorstop_version`, `doorstop_config.ini`, `dotnet/` (the bundled runtime is why no .NET install is needed), `BepInEx/core`, `BepInEx/config/BepInEx.cfg`, `BepInEx/plugins/<Name>/`. **Exclude** `BepInEx/interop/` (~100 MB, regenerated on first launch - that IS the 30-90s first start), `BepInEx/cache/*.dat`, all `*.log`, `untranslated.txt`, `*.pdb`, and the plugin's own `.cfg`.
