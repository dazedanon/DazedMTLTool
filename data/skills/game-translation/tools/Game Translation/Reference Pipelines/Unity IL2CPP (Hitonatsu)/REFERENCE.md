# Unity IL2CPP reference pipeline (ひと夏の思い出)

**Read `PIPELINE.md` first.** This file is only what to copy and what to distrust.

The first end-to-end **IL2CPP** pipeline in this reference set. Everything else
here is Mono, Utage, Unreal, RPG Maker, Wolf, Bakin, SRPG Studio or TyranoScript.

Game: Unity **6000.3.6f1**, IL2CPP, metadata **v39**, x64, PixelCrushers Dialogue
System + PlayMaker + Addressables. 207 units, delivered as a BepInEx 6 runtime
dictionary. No game file is modified.

## What to copy, in order of value

| Path | Why |
|---|---|
| `tools/hitonatsu/unityyaml.py` | Unity YAML reader (`!u!` multi-constructor + document splitter). Engine-generic. 6.8 MB scene in ~8s, `fileID` preserved as a stable id. |
| `tools/hitonatsu/classify.py` | The DISPLAY/INTERNAL ruling tables, where an **unruled path raises**. This is the shape that makes extraction a gate. Rewrite the entries per game; keep the structure. |
| `tools/qa.py` | Font-coverage / same-source / parallel-drift / placeholder / bracket checks. The font gate is IL2CPP-specific and cheap. |
| `tools/translate_mistral.py` | Mistral free-tier driver: two keys, adaptive limiter off live headers, **batch-local opaque ids**, scene-grouped dialogue, locked-unit skip. |
| `plugin/HitonatsuTL/` | BepInEx 6 IL2CPP plugin: setter prefixes + lifecycle postfixes + dropdown hooks + periodic sweep + raw-texture image swap + harvester. |
| `tools/pack_images.py` + `ImagePatches.cs` | **Opt-in - do not wire this in unless the user asks for image work.** It exists here because it was built as unrequested scope creep on this game. When images ARE asked for, it is the only working path once `ImageConversion.LoadImage` proves unusable. |
| `tools/catalog_addresses.py` + `hitonatsu/voiceopts.py` | Reading Addressables addresses out of `catalog.bin` (UTF-16LE) and generating a translated family by construction. |
| `tools/package.py` | Release archive + denylist, and it refuses to package a build with the harvester on. |

`tools/extract.py` and `workspace/*` are **this game's rulings**, not code to
carry over. Per the skill's own rule: treat every value in them as unset until
this game's census fills it.

## The three findings that cost the most time

1. **`ImageConversion.LoadImage` is unusable on a stripped corlib** (relevant only once image work is requested - it should not have been done here). Every
   overload funnels into `Il2CppSystem.ReadOnlySpan<byte>`, whose
   `GetPinnableReference` is missing → `Method not found`. No argument type
   helps; reading the bytes on the il2cpp side does not help. Decode at build
   time, upload with `LoadRawTextureData(IntPtr, int)`, ship RGBA32 bottom-up.
2. **A ctor default is not the runtime value.** Two patches were built on
   `FacialLipSync..ctor` defaults that the scene overrides EMPTY. Both were inert
   and both were documented as real fixes until the scene file was read. Grep the
   scene for the component before building on a field.
3. **Half the corpus was in no file.** 105 voice-dropdown options are built at
   runtime from Addressables addresses stored **UTF-16LE** in `catalog.bin` - a
   UTF-8 scan returns zero and reads as "nothing here". And the function that
   looked certain to build those labels (`GetBaseSituationName`) turned out to
   have a single caller: a sort comparator. Caller analysis before believing a
   name.

## Verification status - read this before trusting the numbers

**Verified:** the whole toolchain runs green end to end (extract → translate →
QA → build → plugin → package). The plugin builds, loads, and its log confirms
`199 translations active` with every hook applied. 207/207 units translated, 0
hard QA failures. The Mistral run cost 16 calls / 36.6k in / 4.8k out on the free
tier. The metadata-v39 dumper path, the lifter queries and every RVA cited in
`PIPELINE.md` were run, not recalled.

**NOT verified:** nobody has watched the patched game render. In particular the
105 generated voice labels rest on a chain of static inference
(`setName = address` → `SetupDropdownOptions` → `OptionData`), and the title-logo
swap had *two* separate bugs found only by reading the runtime log. Treat the
on-screen result as untested and run the playtest matrix in `PIPELINE.md` §6.

The lesson that generalises: on this game every defect that mattered was found by
reading the shipped **data** or the runtime **log**, and none of them by reading
the code more carefully.
