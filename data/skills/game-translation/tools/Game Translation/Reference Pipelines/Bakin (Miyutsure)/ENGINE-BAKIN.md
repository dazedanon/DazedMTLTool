# RPG Developer Bakin - engine reference

First Bakin game in the corpus.
Everything below was recovered from the shipped binaries of `RJ01394574` (`雨瀬みゆを全国大会につれてって！`, Bakin build r73294, 2026-01-27) and verified against the data.

## Detection

| Indicator | Meaning |
|---|---|
| `data/data.rbpack` | packed project (the whole game) |
| `data/bakinengine.dll`, `data/common.dll`, `data/kmyCore.dll` | Bakin runtime |
| `data/bakinplayer.pak` | zip holding `bakinplayer.exe` |
| `revision.txt` naming `Bakin_Steam_Release_Build` | build stamp |

Internal namespace is `Yukar` (Bakin is the successor to SMILE GAME BUILDER, same codebase lineage).
The managed assemblies are AnyCPU but `SharpKmyCore.dll` is a **x64 mixed-mode** C++/CLI wrapper over `kmyCore.dll`, so any tool binding to `common.dll` must run 64-bit.

## Startup chain

1. `みゆつれ.exe` (`Yukar_Engine_Launcher`) reads `data\data.rbpack`, rebuilds the inner zip and extracts it into a **fresh temp folder** `%TEMP%\bakin_engine_tmp\<random>` on every launch.
   `.dll .dlp .dlp_d .exe .cg .cgh` entries are descrambled by the launcher and `.dll` ones land in `data\`; everything else is written **still scrambled** into the temp folder.
2. The launcher unzips `data\bakinplayer.pak` (a plain zip) to `data\bakinplayer.exe` and starts it with
   `/TMP="<cwd>\data"|"<launcher exe>"|"<tempDir>"|<dataVersion>`.
3. `bakinplayer.exe` sets the CWD to the temp folder, calls `FSEx.initializeResourceFileInfo(<launchDir>\data.rbpack)` for bulk assets, then `Catalog.load()` reads `*.rbr` from the CWD.

Consequence: **the rom database the game actually reads lives in a throwaway temp folder**, not in the game directory. Any delivery method has to reach that folder, or rebuild `data.rbpack`.

Other player command-line switches: `/L=<lang>`, `/Dic`, `/W=<w>,<h>`, `/Skip`, `/Settings=`.
A `settings.dat` next to `data` holds the last chosen language.

## `data.rbpack` container

```
"BKNPAK"          6 bytes
version           uint16 BIG-endian   (1; launcher refuses > 1)
(int64)           read and discarded by the launcher
hasLabel          bool
  labelLen        byte + labelLen bytes UTF-8   ("Loading...")
drmNum            int32 LE
hashLen           byte + hashLen bytes = MD5(int32le(drmNum + 2525))
                  fallback MD5(int32le(drmNum + 5252)) -> Steam DRM branch
zipLen            int64 LE
<body>            zipLen - 8 bytes, scrambled
<resources>       everything after, scrambled - the native asset pack
```

The zip's first 8 bytes are **not stored**; the launcher synthesises
`PK\x03\x04\x14\x00\x00\x00` and appends the body.
Resource region starts at `headerLen + zipLen - 8`.

Reader/writer: `tools/rbpack.py`.

## The scramble

One algorithm, two code tables:

```
codes = [0..15]; for j in 0..15: swap(codes[j], codes[(j*M + 1) % 16])
raw[i] = plain[i] + codes[i % 16] * (i % 16)      (mod 256)
```

`i` is the **absolute offset in the enclosing stream**, which is why the launcher
threads a start counter through when it descrambles the rbpack body in place.

- **M = 7** - the launcher's own table (`Form1.getCodes`), used on the rbpack body and on the executable payloads.
- **M = 13** - the engine's table, used on every other packed file (`.rbr .cs .png .txt .cfg`) and on the resource region. Implemented natively in `kmyCore.dll` (`kmyIO::unscramble`, reached through `SharpKmyBase.StdResourceServer.CheckData`), keyed on the data version set from the rbpack header - so **M may differ for a future `dataVersion`**; re-derive it rather than assuming.

M = 13 was recovered by solving the table against the known `YUKAR` magic of an `.rbr`, then confirmed structurally: with it, the record chain of all 138 `.rbr` files walks exactly to EOF.

Reader/writer: `tools/scramble.py`.

## `.rbr` rom files

```
"YUKAR"
repeat until EOF:
  int32  length
  int16  signature
  byte[length]  rom record
```

The first record is always signature `1` - the system container: `int16 romVersion` (74 here) + `int32 lastUsedSwitch`.
`Catalog.romSignatureToTypeDic` in `common.dll` maps signature to type. Record bodies use .NET `BinaryWriter` conventions (7-bit length-prefixed UTF-8 strings, `Guid.ToByteArray()`).

Files in this game: `GameSettings.rbr` (settings + glossary + 995 common Events + 2068 Scripts), 120 `map/*.rbr` (Map + its Events and Scripts), `Layout.rbr`, `Cast.rbr` (+ BattleCommand), `NItem`, `NSkill`, `Condition`, `Attribute`, `Camera`, `BattleCamera`, `RenderSettings`, `ResourceItem.rbr`, `ExtraChunk.rbr`.

**Do not hand-write a parser.** Bind a tool to the game's own `common.dll` (see `BakinTL/`) - the rom classes are the parser, and the same classes write the file back.

## Where the text lives

`[Localizable]`-marked string fields on the rom classes, plus the glossary:

| Holder | Field | Note |
|---|---|---|
| `Script.StringAttr` | `value` | the bulk: DIALOGUE, CHOICES, TELOP, MESSAGE, STRING_VARIABLE, SPTEXT |
| `MenuSettings.MenuItem` | `text` | every UI label, inside `LayoutProperties.AllLayoutNodes` |
| `RomItem` | `name` | items, skills, casts, maps, battle commands, conditions, attributes |
| `NItem` / `NSkill` | `description` | |
| `Condition` | `messageForAlly` / `messageForContinue` / `messageForFinished` | |
| `GameSettings.glossary` | ~168 string fields | all system UI wording |

Command types that hold **keys, not text** - never translate:
`SPPICTURE`, `CHANGE_RENDER`, `PLGRAPHIC` (asset paths), and `Script.name` / `Event.name` / `Folder.name` / `Camera.name` / `RenderSettings.name` (editor-only). `Script.COMMENT` is an editor comment and is never drawn.

Control codes inside text: `\\<keyword>` (`\\skillname`, `\\battlemessage`), `\\$[variable name]`, and bracketed arguments after a code (`\\currentskillconsumptionhp[消費HP : {0} ]`) where the bracket content **is** display text. Choice option `%%WhenCancel%%` is a token.

`STRING_VARIABLE` is heavily used to assemble battle messages from fragments
(`　みゆは` + name + `に蹴りをあびせた！` + ` ` + `ダメージ！`). These are player-facing
but cannot be reordered, so they need fragment-aware handling, not sentence translation.

## The built-in localization system

Bakin ships a first-class localization feature. Its data is an `ExtraChunk`
(rom signature 8192) with id `FA43A17A-FF3E-48BA-9E63-CB765A2FC514`, stored in
`ExtraChunk.rbr`, holding `langs`, `texts`, `resources` (per-language asset swaps),
`fallbackLang` and `layouts`.

`LocalizableText` records only `typeName` / `propertyName` / `guid` / `values{locale: string}` -
**the source Japanese is not stored**, so a dump has to resolve each guid against the roms.

At startup `Yukar.Engine.LocalizedCatalog.ApplyLocalization(lang)` clones the catalog and
applies the table by reflection; `Script` entries are matched to a `StringAttr` by guid,
`LayoutNode` entries to a `MenuSettings.MenuItem`, `Glossary` to `GameSettings.glossary`,
everything else to `getItemFromGuid(...)` and a public field named `propertyName`.
Supported languages appear in an in-game language menu.

**A `StringAttr`'s guid is not serialised with the attr.** `Script` writes a tail table of
`AttrGuidEntry {guid, commandIndex, attrIndex}` and reattaches them on load - so the
localization key is an **index into the command list**. Inserting or reordering commands
silently repoints every translation after that point.

### Coverage is not automatic

On this game the table exists with `langs = ['ja','en']` and 16,950 slots, **all values empty** -
the developer set the feature up and never filled it, and then kept adding content
without regenerating the table. Measured against every Japanese-bearing localizable
string the engine can reach:

```
player-facing units 27,890   covered by the table 14,937   uncovered 12,953
```

`Script.DIALOGUE` alone is 8,502 covered against 7,765 uncovered.
**Always run the coverage audit** (`BakinTL audit`) before assuming the built-in table is
a complete extraction map. Filling only the existing slots would ship a half-translated game.

## Round-trip fidelity

`BakinTL roundtrip` loads the descrambled project with `common.dll` and writes the whole
project back with `Catalog.save`, then compares bytes.

**137 of 138 files are byte-identical.** Two post-load steps are required to get there,
and without them the writer silently destroys data:

- `Folder.initialize(catalog, false)` on every `Folder` - folders serialise `Childs`
  (resolved objects), not `ChildIds` (the loaded guids). Skip it and `UpdateChildIds()`
  writes every folder empty.
- `gameSettings.initCommonEventListInfo(catalog)` - same problem for the common-event
  folder tree nested inside `GameSettings`.

`ResourceItem.rbr` is the one exception: loading it constructs `SharpKmyGfx.Texture`
objects and needs a live renderer. It carries no player-facing text, so it is excluded
from the load and must be **copied through verbatim** on export.

## Rebuilding the pack without moving the resources

The resource region is scrambled by **absolute file offset** (descrambling at
`res_offset` yields readable paths such as `res\1103_追加分\texture\オールバック_茶髪.png`),
and its index is a native format that has not been reversed. Shifting it would mean
re-scrambling 3.7 GB and possibly patching internal offsets.

Avoid the question: the shipped zip was written with `CompressionLevel.NoCompression`
(52,053,896 bytes for 51,991,194 bytes of content), but the same content re-deflates to
**15.5 MB - 36.5 MB of headroom**. Rebuild the zip with real compression and pad it back
to exactly the original `zipLen` (coarse: store selected entries; fine: the EOCD comment,
up to 65,535 bytes). The resource region then never moves and the header needs no change.

## Control codes - measured, not assumed

The layout vocabulary is a 407-entry `CommandItem` table in
`Yukar.Common.Rom.GameContentParser`; the message renderer
(`Yukar.Engine.MessageReader`) adds its own single-letter codes, and
`GameMain.replaceForFormat` runs a substitution pass before either.
Extract the table with `tools/codes.txt` and match **longest-first**, or `\n`
will swallow the head of `\nmotion_`.

Census over this game's 27,890 units (2,250 code occurrences, 4 unmatched):

| Bracket argument | Codes | Uses here |
|---|---|---|
| **key - never translate** | `\$[var]` `\$L[var]` `\savevar[var]` `\f[font]` `\c[hex]` `\z[n]` `\w[n]` | 1,770 / 83 / 12 / 1 / 158 / 1 / 7 |
| **display text - translate** | `\r[base,ruby]` `\NPL[name]` `\NPC` `\NPR` `\currentskill*consumption*[template]` | 55 / 3 / - / - / 9 |
| **no argument - preserve** | `\n` `\b` `\i` `\u` `\s` `\R` `\^` `\<` `\>` `\+` `\-` and ~400 content-getter keywords | 101 + |

`\\` is an escaped literal backslash (`replaceForFormat` parks it on a tab
before parsing) and must survive untouched.

`\H[castName]` resolves a Cast **by name** through `getItemFromName`, which would
make Cast names keys - but it has **0 uses in this game**, so Cast names are safe
to translate. Re-check this per game; do not carry the ruling across.

## MenuItem guids are not unique

`MenuSettings.MenuItem.guid` is the obvious key for a UI label, and it is wrong:
duplicating a layout in the editor clones the item guids. This game has **162
colliding guids, 34 of them over genuinely different text** (`SaveAsk` / `SaveAsk_2`
share the guid for both `はい`/`上書き保存` and `いいえ`/`セーブしない`).

Key UI labels by **(LayoutNode.Guid, index in `MenuSettings.ParseAllItems()`)** instead.
This also means Bakin's own localization table cannot address those items correctly.

## Delivery

The engine reads its roms from the throwaway temp folder, which the launcher
fills *before* it starts `bakinplayer.exe` - so the folder is complete by the
time the player process exists, and can simply be overlaid.

`BakinTLHook` is an `AppDomainManager` registered through three lines in
`data\bakinplayer.exe.config`. It runs before `Main`, reads `launchDir` and
`tempDir` out of the `/TMP=` argument, and copies `<launchDir>\translation\`
over the temp folder. **No game binary is modified** and reverting the patch is
restoring the config file.

Two things the overlay must get right:

- Shipped roms go out **scrambled** (M = 13). `FileUtil.getMemoryStream` calls
  `CheckData` on anything read from disk that the resource pack does not serve.
- Translated map names change map **file names**, so the hook deletes
  `tempDir\map\*.rbr` before copying and the patch ships the whole map set.

`data.rbpack` is never touched, so the patch is ~36 MB of roms rather than 3.8 GB.

## Verified end to end

- `roundtrip`: **138/138 files byte-identical**, `ResourceItem.rbr` included.
- **no-op inject**: all 27,890 units extracted, re-applied, and written back -
  **138/138 files byte-identical**. Extraction and injection are lossless.
- **canary build**: title, 11 glossary terms, 12 UI labels and 3 map names replaced,
  patch built, installed, game launched - overlay present in the temp folder, no hook
  error, `Applying localization: en` in the log, and the process reported
  `MainWindowTitle: CANARY TITLE`.

## Images and other assets

The 3.74 GB resource region holds **7,905 assets**: 3,320 PNG (1.60 GB), 814 BMP
(1.13 GB), 1,958 WAV, 1,593 FBX, 108 OGG, 95 WEBM, 11 HDR, 6 fonts.
Its index is a contiguous table of path strings in the first ~4 MB, each followed
by a 17-byte record. The paths descramble with the usual M = 13 table at absolute
offsets; **the 17-byte records carry a second scramble layer that has not been
decoded** - and does not need to be.

### Extraction - use the engine, not the format

`BakinRes` binds to `SharpKmyCore` and reads assets through the engine's own
resource layer, so the native index never has to be reversed:

    StdResourceServer.SetDataVersion(<version from the rbpack header>)
    FSEx.initializeResourceFileInfo(<data.rbpack>)
    FSEx.existsResourceFile(rel) / FSEx.readResourceFileAllBytes(rel)

**`SetDataVersion` first, or every lookup silently misses** - the native
descramble is keyed on it and `initializeResourceFileInfo` still returns true.

Paths come from `tools/scan_resources.py`, which harvests path-shaped runs out of
the descrambled index; 7,906 candidates yielded 7,905 that the engine serves.
`BakinTL resources` then classifies them from the catalog: `Texture` (5,139) holds
the real paths, `NSprite` (3,182) is the 2D picture layer and references a texture
by guid rather than carrying a path of its own.

### Injection - repoint the catalog, do not rebuild the pack

A loose file at the same relative path is **ignored**: the pack wins
(`readResourceFileAllBytes` still returns the packed bytes). But the path a
texture loads from is just `ResourceItem.path` in the catalog, and the catalog
round-trips byte-exactly. So:

1. Extract the image, edit it.
2. Set that resource's `path` to something the pack does **not** contain
   (`.\res\tl\<name>.png`) - key `R:<resourceGuid>:path`.
3. Ship the new image **scrambled** (M = 13) under `data\translation\`.
4. The hook copies it into the temp folder and the native loader, finding nothing
   in the pack, falls back to disk.

Loose assets must be scrambled because that is how the launcher leaves them:
it descrambles only `.dlp .dlp_d .dll .exe .cg .cgh`, so `terrainmap\*.png` and
`icon.png` sit on disk scrambled and the engine copes.

Proven: `title_mytr_EA` repointed to `.\res\tl\canary_title.png`, the trial-version
title art shipped there, and the game drew the 体験版 badge in place of the shipped
アーリーアクセス版 one. `ResourceItem.rbr` changed by exactly 6 bytes - the difference
in path length - and nothing else moved.

`badpath texture ...` in the log is **not** a failure signal; it appears for
textures that go on to load normally.

### Loading the catalog without a renderer

`Texture.load` and `Model.load` construct native `SharpKmyGfx` objects, which is
why `ResourceItem.rbr` first appeared unloadable. `ResourceItem.sAttachResource =
false` is the engine's own switch for this and makes the whole catalog readable
headlessly - after which the round trip is **138/138 byte-identical**, with no
file copied through.

## Text fitting: overflow and reflow

Bakin does **not** have one fitting rule. Every determinant is layout DATA on the
`MenuItem`, so the regime has to be measured per widget - `BakinTL layout` dumps
exactly the fields the engine consults.

| `useMultiLineText` | `useClipping` | items here | what a long translation does |
|---|---|---|---|
| 1 | either | **544** | wraps to `size.X`, paginates at `maxLineNum` - **safe** |
| 0 | 1 | **1,887** | one line, **cut at `size.X` - text is LOST** |
| 0 | 0 | **1,773** | one line, drawn past `size.X` - collides with neighbours |

Measured on this game: 4,204 text-bearing layout items across 170 nodes, all
`sizeType = MANUAL` (so every one declares a real pixel box), `maxLineNum = 3`
everywhere, no scroll bars.

### The engine reflows for you - on 13% of widgets

`LayoutStateDialogue` / `LayoutStateMessage` call

```
MessageReader.ReadMessage(text, textDrawer, (int)MenuItem.size.X, scale,
                          LayoutDrawer.maxLineNum(), sender,
                          isWordWrap: textPanel.IsWordWrapEnabled())
```

and `IsWordWrapEnabled()` is just `MenuItem.useMultiLineText`. When it is on,
`wordWrap()` breaks lines using **real font measurement**
(`textDrawer.MeasureString(font, s) * scale`), then `splitByLines(maxLineNum)`
cuts the result into pages that are queued and clicked through.

So for the message path, **width and height are both soft**: nothing is clipped,
nothing is lost, and a long translation costs the player extra clicks. The main
dialogue box is **690 x 140 px at 3 lines**; `Telop` is 1280 x 720 at 3 lines.

Two consequences for the pipeline:

- **Do not pre-wrap dialogue.** Inserting your own line breaks into a panel that
  already word-wraps double-wraps it. Let the engine do it, and grade height as a
  soft note - "this line now costs N extra pages" - with a threshold, not a
  failure.
- **Reflow is not available for the other 87%.** A single-line label cannot be
  broken, so when it does not fit there is nothing to re-flow *to*: the only
  remedy is the shortening pass. On Bakin the pipeline's fitting work is mostly
  **shortening**, not wrapping - the inverse of the RPG Maker pipelines.

### The budget usually is not on the unit you translated

Most layout slots do not hold literal text - they hold a content-getter code
(`\\skillname`, `\\currentitemdes`, `\\message`) and draw whatever the getter
returns at runtime. So the width budget for `NSkill.name` is **not** a property of
the NSkill: it is the **minimum `size.X` over every layout slot that draws
`\\skillname`**, and a slot with `useClipping` makes that minimum hard.

That is the skill's "one string, two widgets: the narrow one is the budget" and
"budget per column, not per table", and on Bakin it is the normal case rather than
the exception. A fitting pass therefore needs, in order:

1. every content-getter code → the rom field that feeds it
2. per field, `min(size.X)` across the slots that draw it, plus whether any of
   those slots clips
3. per literal-text item, its own slot's `size.X`
4. dialogue/message units → the message panel's `size.X`, soft, page-counted

### Measuring width honestly

Rendered width is `MeasureString(font at Font.Size, s).X * MenuItem.scale.X`, so
the base size lives on the **`Font` rom resource**, not on the widget:
`Font.Size * Font.DefaultScale` is the effective pixel size. The defaults are
named by **`GameSettings.UseToMessageDefault` / `UseToLayoutDefault`** (the
per-Font `UseTo*Default` booleans are all false here and are not what the engine
reads).

On this game both resolve to `res\font\font.ttf`: `Message` is 48 x 0.5 and
`Layout` is 72 x 0.3333 - both **24 px effective** - and **3,818 of 4,204 text
widgets (91%) take the Layout default**, so one font file covers almost
everything. `BakinRes extract` pulls all six shipped font files.

Watch the font *type*: 10 of the 19 `Font` resources are `Installed`, referenced
by system family name (`パンダベーカリー`, `モボ-Bold`, `ＡＲＰ新藝体Ｕ`) and **not shipped
in the pack**. A player without them installed gets a substitute, so both the
measurement and the on-screen result are approximate for those widgets. `fit.py`
reports which fonts it had to substitute rather than pretending.

### The check has to be differential

`fit.py validate` measures the **shipped Japanese** against its own declared box
first. Two modelling errors surfaced that way and were fixed: measuring a literal
with its own `\n` breaks as one line, and validating widgets that word-wrap (for
which width is not a constraint at all). After both, the shipped Japanese sits at
89.7% fitting.

The residue matters more than the number. Running the finished check over a
build, **653 slots were already over their declared box in Japanese** - `size.X`
on a nested or decorative sub-element is often not the visual bound. An absolute
budget would have reported all 653 as failures. So the shipped check flags a slot
only when the English is wider than **the Japanese it replaced**, and reports the
already-over count separately.

Same trap on the code budgets: the narrowest clipping `partyname` slot is 84 px,
but the shipped `雨瀬みゆ` measures 96 px and `山間田休太` 120 px. The min-across-slots
rule accuses the author, so it is a **ranking heuristic for what to check, not a
budget to enforce**.

Concretely, on a width-neutral build: 552 labels fit, **0 clipped**, 18 marginal
overflows at 1.04-1.25x. The clipped bucket has a median box of **96 px** and is
where English expansion will bite first.

## Custom C# plugin scripts

`script/*.cs` and `battlescript/*.cs` are compiled at runtime by the bundled Roslyn.
78 Japanese string literals total, almost all **editor-facing plugin metadata**
(command descriptions shown in the Bakin editor). Genuine player-facing ones are rare -
`battlescript/BattleSequenceManager.cs` has `所持数 {0, 4}個`. This is a separate,
**in-place** edit track: these files are edited in the pack, never exported from the catalog.

---

## Added after a second Bakin game (r64268)

A later project on an OLDER build hit a set of problems this pipeline never
exercised. The tooling here was extended to match and re-gated (`roundtrip`
still 138/138). The full write-up is in the skill: `references/engine-bakin.md`
and `references/text-fitting.md`.

* **`maxLineNum` does not bound a layout widget.** It is consumed only by the
  MESSAGE path. `TextRenderer` never reads it and wraps by width alone through
  `SplitStringInnerWidth`, so a wrapping label neither paginates nor drops rows -
  it keeps drawing, bounded by `size.Y` and clipping.
* **`scale.X` scales the GLYPHS, not the box.** Measuring at a fixed size, the
  budget is `size.X / scale.X`. `TextRenderer.InitializeText` is where that comes
  from: it wraps at `GetScaledSizeWithoutMyself().X`, which excludes the widget's
  OWN scale, while the glyphs shrink with it through
  `textScale = scale.X * 0.33333334f`. So lowering `scale.X` really does buy
  characters per line, which makes it a repair for a label that will not fit. Having it the wrong way round is wrong by
  `scale.X` squared and hides itself, because the too-small budget makes the
  SOURCE look over-wide and the "author already overflows" exclusion then drops
  the widget from the check entirely. Watch that exclusion as a RATE.
* **`useClipping` is only a boolean channel** - the scissor comes from the
  nearest ancestor container, so a label's own `size.X` may bound nothing at all.
* **You CAN pre-wrap dialogue.** `MessageEntry.wordWrap` only re-breaks a line
  whose measured width EXCEEDS the box, so breaks you choose are the breaks the
  player sees. That makes an orphan-repair pass safe and worthwhile.
* **A Condition holds its battle messages twice** and the engine reads the
  nested copy - see `BUILD.md`, and run `BakinTL effectparams`.
* **`GameSettings.gameFont` names an INSTALLED font**, so where it is absent the
  OS substitutes and the glyph repertoire becomes the player's machine's
  business. One game lost U+2661 that way, used 229,107 times. Diff the shipped
  corpus against the chosen font's cmap and name a font that has the glyphs.

  **An EMPTY `gameFont` is the stronger answer.** `setGameFont` sets
  `useSystemFont = !IsNullOrEmpty(name)`, and when that is false `createFont`
  probes `font.ttf`, `<exe>/font.ttf`, `<exe>/lib/sysresource/font.ttf` and
  `<exe>/sysresource/font.ttf` through `FileUtil.Exists`, which is
  `File.Exists(p) || FSEx.existsResourceFile(p)` and therefore resolves INSIDE
  the pack. Bakin ships a bundled `font.ttf` (M+SmileBoom bold), so clearing the
  name gives a face that is guaranteed present on every machine and cannot tofu.
  It costs metrics: on one corpus it took dialogue needing a fourth row from
  0.99% to 2.97%. The `メイリオ` fallback in that method is unreachable, sitting
  after the `!useSystemFont` early return.

  **Match the WEIGHT the author asked for.** Substituting a Light face for the
  author's `游明朝 Demibold` was a visible regression that no width check sees,
  because thin stems are what an upscale destroys.

* **Text is drawn from TWO rasters, and they do not look alike.**
  `GraphicsCore.refreshFont` builds `mFont` (24px) and `mLargeFont` (72px).
  Layout text draws `mLargeFont` at `scale.X/3`, a big raster shown small, so it
  is crisp. The MESSAGE body draws `mFont` and any window larger than the design
  resolution scales that 24px raster UP. A player reports it as "the dialogue is
  blurry but the speaker name is not", and "it improves at lower resolution"
  confirms it rather than working around it. No rom edit fixes this. Only the
  substituted face's weight is yours to choose.

  Do not reason about one branch of `createFont` from the other: the system-font
  branch calls `newSystemFont(name, (uint)(size * scale))`, the PRODUCT, so
  `createFont(48, 0.5f)` and `createFont(24, 1f)` are the same 24px. The file
  branch calls `new Font(path, size, scale)` with the two SEPARATE.

* **`image` is not the only picture on a `MenuItem`.** It carries about twenty
  `Guid` fields, and a container's FRAME is `window`, distinct from `image` (a
  sprite) and `subItemBaseBackground` (the plate under each sub-item row). A dump
  emitting only `image` reports a fully framed screen as having no art. Resolve
  the id against the resource table to get the PNG, and you can composite a
  widget yourself instead of guessing at positions.

* **One `usage` can have several competing nodes.** `BattleSkill` had THREE on
  one game, a `SystemResource` and two `UserResource`, and `SkillSelect` had two.
  Only one is live. Never fix "the" widget for a screen without checking how many
  claim that usage, and prefer fixing every candidate over guessing which.
* `tools/wrap.py` is the engine's own word wrap, transcribed from the decompiled
  `MessageEntry.wordWrap`. Pure - pass it a width and a measure callable. Use it
  to predict what the player will actually see rather than approximating.
