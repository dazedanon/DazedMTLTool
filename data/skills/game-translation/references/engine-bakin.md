# RPG Developer Bakin

SmileBoom's successor to SMILE GAME BUILDER. Internal namespace is `Yukar`; the
runtime is managed .NET over a native `kmyCore` layer.

**Two complete pipelines exist. Read the one whose BUILD matches your game.**

- `tools/Game Translation/Reference Pipelines/Bakin (Miyutsure)/` - build
  **r73294** (2026). `ENGINE-BAKIN.md` then `BUILD.md`.
- `tools/Game Translation/Active Projects/Artesia (Bakin)/` - build **r64268**
  (2024-07). `PIPELINE.md`, then `ENGINE-CODES.md` for the decompiled
  control-code reference. Adds the Claude batch+live translation driver, which
  the Miyutsure pipeline does not have.

## The build version is not a detail, it is the first thing to establish

`revision.txt` carries it. Between r64268 and r73294 the engine changed in ways
that break a carried-across pipeline **silently**, not loudly:

| | r64268 | r73294 |
|---|---|---|
| localization feature | **does not exist** - no `[Localizable]`, no `LocalizeData` ExtraChunk, no `StringAttr.guid` | full feature, in-game language menu |
| `Font` rom resource | **does not exist**; `GameSettings.gameFont` names an installed system font, or is EMPTY and a bundled `font.ttf` is loaded out of the pack | per-resource `Font` with `Size * DefaultScale` |
| `ResourceItem.sAttachResource` | absent (the catalog loads headlessly anyway) | present, and required |
| `ReadMessage` | no `isWordWrap` parameter - the message path **always** wraps | takes `isWordWrap` from `MenuItem.useMultiLineText` |
| rbpack header | no `hasLabel` bool; the label string follows the discarded int64 | `hasLabel` bool then the label |
| resource index paths | stored **relative to `res\`**, roots are `texture\`, `model\`, `character\3D\...` | stored with `res\` already in the string |
| `MenuItem` | no `font`, no `UseScrollBar` | both present |

So: **build a reflection dumper before you build anything else.** `BakinApi` in
the Artesia pipeline is 80 lines, binds to the game's own `common.dll`, and
prints the fields, properties, methods and enum values of any type plus
`Catalog.romSignatureToTypeDic` and any static table (the 541-entry control-code
list among them). Every field name a translation tool touches gets verified
against it before it is compiled, instead of after a build error that only
names the first three of twelve.

## Detection

| Indicator | Meaning |
|---|---|
| `data/data.rbpack` | the packed project - the whole game in one file |
| `data/bakinengine.dll`, `data/common.dll`, `data/kmyCore.dll` | Bakin runtime |
| `data/bakinplayer.pak` | a plain zip holding `bakinplayer.exe` |
| `revision.txt` naming `Bakin_*_Release_Build` | build stamp |

All the managed assemblies are AnyCPU, but `SharpKmyCore.dll` is **x64
mixed-mode**, so any tool binding to `common.dll` has to run 64-bit.

## The one thing that decides your whole approach

The game does **not** read its data from the game folder. The launcher unpacks
`data.rbpack` into a **fresh temp folder** (`%TEMP%\bakin_engine_tmp\<random>`)
on every launch, *then* starts `bakinplayer.exe` with
`/TMP="<gameDir>\data"|"<launcher>"|"<tempDir>"|<dataVersion>`, and the engine
reads `*.rbr` from that temp folder.

So a patch has to either rebuild the 3-4 GB pack or reach that temp folder. The
temp folder is fully populated before the player process exists, which makes an
**overlay** the cheap answer: register an `AppDomainManager` in
`data\bakinplayer.exe.config` (three lines), and it runs before `Main`, reads
`launchDir`/`tempDir` out of `/TMP=`, and copies `<launchDir>\translation\` over
the temp folder. No game binary is modified; reverting is restoring one config
file. Working hook: `BakinTLHook/` in the reference pipeline.

## Do not hand-write a parser

`common.dll` **is** the parser, and the same classes write the file back. Build a
tool that binds to the game's own `common.dll` (resolve it at runtime from an env
var so the tool is not tied to one game's build) and use `Catalog` directly.
`BakinTL/` is that tool, and its subcommands are PER BUILD rather than fixed.
Shared by both: `probe`, `roundtrip`, `export`, `inject`, `resources`, `layout`,
`effectparams`. Only on `[r73294]`: `audit`, `dump`, `fonts`. Only on `[r64268]`:
`census`, `attrcensus`, the two generic walks that replace the localization
metadata an older build does not have. Check the dispatch table before quoting a
command at someone.

Two post-load steps are mandatory, and skipping either **destroys data silently**:

- `Folder.initialize(catalog, false)` on every `Folder`. Folders serialise
  `Childs` (resolved objects), not `ChildIds` (the guids that were loaded), so
  without this `UpdateChildIds()` writes every folder empty.
- `gameSettings.initCommonEventListInfo(catalog)` - the same problem for the
  common-event folder tree nested inside `GameSettings`.

And `ResourceItem.sAttachResource = false` before loading, or `Texture.load` /
`Model.load` construct native `SharpKmyGfx` objects and throw without a renderer.
With all three, the whole project round-trips **byte-for-byte**. That is the gate:
run `roundtrip` and require 100% identical before trusting any injected build.

## Container and scramble

```
"BKNPAK" | uint16 version (BIG-endian) | int64 (ignored) | bool hasLabel
[ byte len + UTF-8 label ] | int32 drmNum | byte len + MD5(int32le(drmNum+2525))
int64 zipLen | <zip body, zipLen-8 bytes> | <native resource region>
```

The zip's first 8 bytes are not stored - the launcher synthesises
`PK\x03\x04\x14\x00\x00\x00`. Resources start at `headerLen + zipLen - 8`.

Everything is obscured by one additive scramble with two code tables:

```
codes = [0..15]; for j in 0..15: swap(codes[j], codes[(j*M + 1) % 16])
raw[i] = plain[i] + codes[i % 16] * (i % 16)        (mod 256)
```

`i` is the **absolute offset in the enclosing stream**. `M = 7` is the launcher's
table (rbpack body, and the `.dlp .dlp_d .dll .exe .cg .cgh` payloads it
unpacks); `M = 13` is the engine's, for everything else - `.rbr .cs .png .txt` and
the resource region. It is keyed on the data version from the rbpack header, so
**re-derive M for an unfamiliar `dataVersion`** rather than assuming; solving the
table against the known `YUKAR` magic of an `.rbr` takes minutes.

Consequence for delivery: files you ship loose must go out **scrambled**, because
that is the state the launcher leaves them in (it descrambles only the executable
payloads, which is why the game's own `terrainmap\*.png` sit on disk scrambled).

`.rbr` rom files are `"YUKAR"` then repeating `int32 length | int16 signature |
body`, with .NET `BinaryWriter` conventions inside.
`Catalog.romSignatureToTypeDic` maps signature to type.

## Its built-in localization is a trap

Bakin ships a first-class localization feature: an `ExtraChunk` with id
`FA43A17A-FF3E-48BA-9E63-CB765A2FC514` holding `langs`, `texts`, per-language
`resources` and `layouts`, applied at startup by
`LocalizedCatalog.ApplyLocalization(lang)` with an in-game language menu.

Finding it populated looks like the job is already scoped. **Audit it before
believing it.** On the reference game it declared `langs = ['ja','en']` with
16,950 slots and *every value empty*, and it reached only **14,937 of 27,890**
player-facing strings - `DIALOGUE` alone was 8,502 covered against **7,765 with no
slot at all**, because the developer generated the table once and kept adding
content. Filling only the existing slots ships a half-Japanese game and every
automated check passes.

Two more of its own bugs, worth knowing because they bite your keys too:

- **A `StringAttr`'s guid is not serialised with the attr.** `Script` writes a
  tail table of `AttrGuidEntry {guid, commandIndex, attrIndex}`, so the
  localization key is an **index into the command list** - insert or reorder a
  command and every translation after it silently repoints.
- **`MenuSettings.MenuItem.guid` is not unique.** Duplicating a layout in the
  editor clones the item guids: 162 collided on the reference game, 34 over
  genuinely different text. Key UI labels by
  **(LayoutNode.Guid, index in `ParseAllItems()`)** instead.

Unless you specifically want the ja/en toggle, writing English straight into the
rom fields is simpler and covers everything, and the byte-exact round trip is
what makes it safe.

## With no `[Localizable]` marker, the field list is a CENSUS, not a reading

On r64268 there is no attribute to reflect over, so "which fields hold player
text" has to be measured. Two censuses, and both are inputs to the whitelist
rather than reports:

- **`census`** walks every object reachable from the catalog roots - bounded
  reflective walk, reference-identity visited set, depth cap - and records every
  `string` / `string[]` field whose value contains Japanese, grouped by
  declaring type and field name. On the reference game that is **299 distinct
  field paths and 155,298 hits**, of which all but a dozen are editor names,
  asset paths, folder categories, or dev-machine import paths
  (`Texture.importPath`, 2,174 of them, holding `C:\Users\PC_User\Desktop\...`).
  `GfxResourceBase.name` alone is 1,251 units of 3D model names never on screen.
- **`attrcensus`** groups every `Script.StringAttr` by **(command type,
  attribute index)** with a JP count, a distinct count and samples. This is the
  one that scopes the job, because a script attribute is display text or an
  engine key **by its position in a command, never by its content**. On the
  reference game 92,783 attribute values contain Japanese and only **12
  (command, slot) pairs** are involved:

      DIALOGUE        slot 0   83,999 JP   22,914 distinct
      CHOICES         slots 1-6  2,855 JP
      MESSAGE         slot 0       511 JP
      COMMENT         slot 0       508 JP   <- editor only, EXCLUDE
      STRING_VARIABLE slot 1       103 JP
      TELOP           slot 0        49 JP
      SPTEXT          slot 1         2 JP

  Also print the slots that hold strings but **no** Japanese, because those are
  the ones an English build could put text into and their absence is evidence.

Adding a field costs money. Leaving one out ships it untranslated and **no
per-unit check can ever see it**, because a string that was never extracted
cannot fail anything.

## The nameplate is MARKUP, and it changes the speaker problem completely

`\NPL[name]` heads the dialogue string itself - 71,519 of 83,999 dialogue units
on the reference game, 465 distinct speakers. Consequences worth planning
around, all of them favourable:

- **Speaker recovery is exact, not heuristic.** The RPG Maker pipelines need
  four gates to decide whether the first physical line of a message block is a
  nameplate, and get it wrong on narration. Here it is a regex on a code the
  engine parses.
- **The speaker list IS the glossary's name list**, seeded automatically with
  line counts, which also gives you the `roster_min` threshold for free.
- **The English name goes back INSIDE the code**, so there is no `[Kurone]: `
  prefix artifact to strip off every line.
- **The nameplate has its own clipping box**, and the narrowest of its 36 slots
  is NOT the budget. `[r64268]` The narrowest declares 234px, but the author
  ships nameplates up to **330px**, so enforcing 234 flags 67 perfectly ordinary
  two-word job titles across 1,470 lines - the "your model is accusing the
  author" failure this file warns about below. The budget is
  `max(narrowest slot, widest shipped SOURCE nameplate)`; report the slot figure
  separately so the gap stays visible. It is the most visible label in the game
  (71,519 lines), so get the bound right before flagging anything.

## Six ways an ENGLISH string breaks the renderer, and Japanese cannot

Recovered by decompiling `MessageReader.MessageEntry.separateByCommands` on
r64268 (full IL evidence in the Artesia pipeline's `ENGINE-CODES.md`). Audit the
SOURCE for all six first - if it is clean, every hit afterwards is yours.

| trap | what happens |
|---|---|
| `,` inside a bracket argument | the bracket reader always does `.Split(',')` and consumers read `[0]`, so **`\NPL[Smith, Jr.]` renders `Smith`**. Japanese writes 、 and ，, never U+002C, so the source never trips it |
| `]` inside a bracket argument | closes it early; the rest becomes visible text |
| `\blinked`, `\blinks` | `commands = {blink, blspd, blrate, lipspd, lip, NP}` is matched by a bare `StartsWith` **before** the char switch and with no requirement that `[` follow, then indexes `func()[0]` on an empty array - an `IndexOutOfRangeException` at run time |
| a real TAB | `GameMain.replaceForFormat` parks `\\` on a TAB while parsing and converts every TAB back to a backslash, so a TAB is drawn as a visible `\` |
| a trailing `\` | CR and LF are tested before the escape flag and neither clears it, so it eats the next line's first character |
| `\b[x]` | every single-letter escape invokes the bracket reader before the char switch, so it toggles bold and **deletes** `[x]` |

Bakin does **not** have RPG Maker's greedy `[A-Za-z]+` escape lexer, so `\cRed
velvet` is safe - the dispatch is a bare char compare and an unrecognised escape
stays literal text. The risk runs the other way: the engine substitutes 541
backslash keywords, so a backslash the model invented can accidentally spell one.
Treat any backslash in the output that did not come from a restored sentinel as
a hard failure - there is no safe repair, because deleting it may destroy a code
the model correctly restored itself.

## Ruby binds OUTSIDE its own bracket

`\r[base,ruby]` is the two-argument form and both halves are display text.
`\r[ruby]X` is the one-argument form and it **silently consumes the single
character after the `]`** as its base - a character that sits in the visible
text where the model can move it away from its code. Apply the skill's tier-1
masking rule: resolve ruby to its base spelling and do **not** restore it.
English has no emphasis-dot typography anyway.

## Message bodies use real CRLF, not `\n`

106,302 CRLF pairs against 32 uses of the `\n` code, and those 32 are all in
layout option lists. Normalise to LF for the model and restore CRLF on inject,
or every author line break changes shape.

## Where the text is

| Holder | Field |
|---|---|
| `Script.StringAttr` | `value` - DIALOGUE, CHOICES, TELOP, MESSAGE, STRING_VARIABLE, SPTEXT |
| `MenuSettings.MenuItem` | `text` - every UI label, under `LayoutProperties.AllLayoutNodes` |
| `RomItem` | `name` - items, skills, casts, maps, battle commands, conditions |
| `NItem` / `NSkill` | `description` |
| `Condition` | `messageForAlly` / `messageForContinue` / `messageForFinished` |
| `GameSettings.glossary` | ~168 string fields plus `attrNames[]` - all system wording |
| `GameSettings.meta` | `title` / `subTitle` / `description` / `creator` / `license` |
| **`GameSettings.name`** | **the WINDOW TITLE** - see below |

**The window title is `GameSettings.name`, not `meta.title`.** They hold the same
Japanese string, so translating one and shipping the other produces a game that
still says 執聖官アルテシア in its title bar and looks exactly like the whole patch
failed to apply. This cost a full canary cycle to find, and finding it is
precisely what the canary is for.

Keys, never translate: `SPPICTURE`, `CHANGE_RENDER`, `PLGRAPHIC` (asset
references) and `Script.name` / `Event.name` / `Folder.name` / `Camera.name` /
`RenderSettings.name` (editor-only). `Script.COMMENT` is never drawn.

**Resolve every Script to its owning event, from all three places one can
live.** A map pass alone left 46,062 of 84,000 dialogue units in a single
undifferentiated `(common)` bucket on the reference game, which destroys the
scene grouping the model relies on. The other two are
`GameSettings.commonEvents` and `GameSettings.battleEvents` (both
`List<Guid>` of `Event`), plus `sourceEvents`. With all three, 1,487 named
owners and zero orphans.

`STRING_VARIABLE` is not junk - it is heavily used to **assemble battle messages
from fragments** (`　みゆは` + name + `に蹴りをあびせた！` + ` ` + `ダメージ！`). Player-facing,
but Japanese word order is baked into the concatenation, so these need
fragment-aware handling rather than sentence translation.

## Control codes

The layout vocabulary is a 407-entry `CommandItem` table in
`Yukar.Common.Rom.GameContentParser`; `Yukar.Engine.MessageReader` adds
single-letter codes and `GameMain.replaceForFormat` runs a substitution pass
first. Extract the table and match **longest-first**, or `\n` swallows the head of
`\nmotion_`.

The code table below is `[r73294]`. **It does not transfer**: on `[r64268]` several
of these do not exist at all, and the decompiled per-build table lives in
`Active Projects/Artesia (Bakin)/ENGINE-CODES.md`. Re-derive it for your build
before trusting any entry - a code you preserve that the engine does not define is
two stray characters on screen, and one you translate that it does define is a
broken lookup.

- **key arguments, never translate**: `\$[var]` `\$L[var]` `\savevar[var]`
  `\f[font]` `\c[hex]` `\z[n]` `\w[n]`
- **display text, translate**: `\r[base,ruby]` (furigana) `\NPL/NPC/NPR[name]`
  (name plate) `\currentskill*consumption*[template]`
- **bare, preserve**: `\n \b \i \u \s \R \^ \< \> \+ \-` and the ~400 keywords
- `\\` is an escaped literal backslash and must survive untouched

`\H[castName]` resolves a Cast **by name**, which would make cast names keys.
It had 0 uses on the reference game - **re-check per game, do not carry the
ruling across**.

## Text fitting: the engine reflows, but only for a minority of widgets

There is no single fitting rule - every determinant is layout **data** on the
`MenuItem`, so measure per widget (`BakinTL layout` dumps exactly the fields the
engine reads).

**Every count in this section is labelled with the game it came from, because
two are mixed here and they disagree.** `[r73294]` is the Miyutsure pipeline;
`[r64268]` is the Artesia one. A number without a label is one nobody has
re-measured on the other build - treat it as unverified there, exactly as this
file's own opening rule demands.

`[r73294]` 4,204 text-bearing items, all `sizeType = MANUAL`, `maxLineNum = 3`,
no scroll bars.

| `useMultiLineText` | `useClipping` | share | a long translation |
|---|---|---|---|
| 1 | either | 13% | wraps to `size.X`; bounded by size.Y, NOT by maxLineNum |
| 0 | 1 | 45% | one line, **cut at `size.X` - text LOST** |
| 0 | 0 | 42% | one line, drawn past `size.X` - collides |

`LayoutStateDialogue`/`LayoutStateMessage` pass `MenuItem.size.X` and
`useMultiLineText` into `MessageReader.ReadMessage`, which wraps using **real font
measurement** and then `splitByLines(maxLineNum)` cuts the result into pages the
player clicks through. **That is the MESSAGE path only** - see the bullet below,
which is the single most important correction in this section. Main dialogue
box: **690 x 140 px, 3 lines** on both builds measured.

- **`maxLineNum` DOES NOT BOUND A LAYOUT WIDGET.** It is read only by
  `LayoutDrawer` and consumed only by `MessageReader.ReadMessage` on the
  MESSAGE path. `TextRenderer` and `SpecialTextRenderer` - which draw every
  `TEXT_PANEL` - never reference it: they wrap through
  `MessageReader.SplitStringInnerWidth(text, width, ...)`, which takes a WIDTH
  and no line count. Verified by grep over the decompiled `TextRenderer.cs`:
  zero hits.

  So a wrapping layout label does not paginate and does not lose its extra
  rows - it simply keeps drawing them, bounded by `size.Y` and `useClipping`.
  A 360x128 description at a ~33px line advance holds 3 rows comfortably and
  spills the 4th toward whatever sits below it.

  This matters because `maxLineNum` is right there in the same `MenuSettings`
  and reads like a universal row cap. It is not. **Check which renderer
  consumes a limit before treating it as one** - the same field can bound one
  widget class and be inert on another.

- **You CAN pre-wrap dialogue on Bakin, and you should.** An earlier version of
  this file said the opposite - "a panel that already word-wraps would wrap your
  breaks again" - and that is wrong here, because `MessageEntry.wordWrap` is
  width-triggered:

  ```csharp
  if (this.measureStringSingleLine(i, 0, 32767).X > (float)width) { ...split... }
  ```

  A line that already fits is returned untouched, so breaks you choose are the
  breaks the player sees. This matters because the greedy wrap orphans words:
  measured on a finished 84,048-unit English build, **6.8% of units ended with a
  wrap tail under a third of the box** (against 4.4% in the shipped Japanese).
  Rebalancing the breaks - same words, same line count - removed **5,809 orphan
  lines across 5,694 strings with 0 defects**. See `text-fitting.md`, "A pre-wrap
  is only safe if the engine's wrap is WIDTH-TRIGGERED", for the preconditions
  and the refusal rules (any line carrying a code, because `\z[200]` rescales
  everything after it and `\NPL[Sister Agatha]` has a space inside its bracket).
  Still grade height as a soft note ("costs N extra pages"), not a failure.
- **Reflow does not exist for the other 87%.** A single-line label cannot be
  broken, so there is nothing to re-flow to: the remedy is the shortening pass.
  On Bakin the fitting work is mostly **shortening**, the inverse of the RPG Maker
  pipelines.
- **The budget is usually not on the unit you translated.** Most slots hold a
  content-getter code (`\\skillname`, `\\currentitemdes`) and draw what the getter
  returns, so the budget for `NSkill.name` is the **minimum `size.X` over every
  slot that draws `\\skillname` THAT CAN STILL HOLD THE AUTHOR'S OWN
  WIDEST VALUE** for that field. A plain minimum is only a ranking heuristic:
  a decorative 40px stub drags it down, and six English descriptions that wrap
  perfectly inside 1,080px then get reported CLIPPED. Drop the slots the
  author's own content proves are not the visual bound, multiply a wrapping
  slot by its row count, and take `clips` from the slot you CHOSE rather than
  from any of them. Budget per field, not per unit. Clipped items here have a median width of **96 px** - a few
  glyphs - and are where English expansion hurts first.
- `[r73294]` Measure with the game's own font. Width is
  `MeasureString(font at Font.Size, s).X * MenuItem.scale.X`; the base size is
  `Font.Size * Font.DefaultScale` on the **`Font` rom resource**, and the
  defaults are named by **`GameSettings.UseToMessageDefault` /
  `UseToLayoutDefault`** (the per-Font `UseTo*Default` booleans are not what the
  engine reads). Here both are `res\font\font.ttf` at 24 px effective and cover
  91% of text widgets. Treat that product as unverified on this build: it is the
  SYSTEM-font branch's rule (`newSystemFont(name, (uint)(size*scale))`), and a
  `res\font\*.ttf` is a FILE font, whose branch passes the two separately as
  `new Font(path, size, scale)` (see the two-branch note below). Nothing here
  falsifies it because the observed `DefaultScale` is 1. Read r73294's own
  `createFont` before trusting the product on a `Font` whose `DefaultScale` is
  not 1. Beware `Font.Type == Installed`: those are system fonts
  referenced by family name and are **not in the pack**, so both your
  measurement and the player's screen depend on what they have installed.
- **On a build with no `Font` rom resource, what is unreadable is the MEASURING
  size, not the engine's.** r64268 has no `Font` resource, no `MenuItem.font`
  and no `UseToMessageDefault`. The engine's own size is a compiled constant
  either way - `NORMAL_FONT_SIZE = 24f`, `LARGE_FONT_SIZE = 72f`, and
  `refreshFont` picks the face off `getMaxTexture2DSize()` (next bullet). The
  one setting is `GameSettings.gameFont`, which names an installed family or is
  EMPTY, and empty routes to the file branch and a face out of the pack. What no
  rom field states is the px a PIL-class library needs to REPRODUCE each raster,
  and guessing 24 cost a full round of wrong width numbers.

  **The author's own line breaks cannot calibrate it - only an observed render
  can.** Fitting the size against the shipped breaks is free and needs no
  screenshot, so it is what the next reader will reach for. It does not
  converge: `[r64268]` over **44,056** author-placed breaks, the rate at which
  the next word would still have fitted is **99.97% at 16px and still 90.52% at
  24px**, falling with no minimum anywhere, because a Japanese author breaks at
  PHRASE boundaries and not at the box edge. The curve looks plausible and pins
  down nothing. A screenshot settles it instead: find the (font, size, width)
  triple that reproduces both a break point it shows and a long line it fits on
  one row - `[r64268]` **22px in the 690px node**.

  **That 22 is not a second engine size.** The engine is nominally 24 on BOTH
  paths; the message box measures a natively-hinted 24px face (`mFont`) while
  layout measures a 72px face's advances divided by three (`mLargeFont`). Those
  rasterise differently, so a PIL-class measuring library needs 22 to reproduce
  one and 24 to reproduce the other. Calibrate each PATH separately and say
  which is which - do not report it as "the game uses two font sizes". Report
  the substitution on every run; never let a measurement quietly claim to be
  the game's.

  **And that 22 was measured on Yu Gothic Light, which is not the face to
  ship.** Light is only what this machine picked for the author's uninstalled
  Mincho, and it is rejected on weight grounds below. Widths are
  weight-dependent, so a ruler pinned on Light does not measure what the player
  sees. Re-calibrate at the weight you ship, and treat every width number
  standing on the Light ruler as stale until you have.
- **The layout text model, decompiled and verified.** There is no font size on
  a `MenuItem` anywhere. `GraphicsCore.refreshFont` creates **TWO** faces:
  `mFont = createFont(24, 1f)` - or `createFont(48, 0.5f)` where
  `getMaxTexture2DSize() < 4096` - and `mLargeFont = createFont(72, 1f)`. The
  constants are right there: `NORMAL_FONT_SIZE = 24f`, `LARGE_FONT_SIZE = 72f`.

  **The two paths use different faces and both come to 24px nominal.** Every
  LAYOUT renderer takes `mLargeFont` (`TextRenderer` ctor) and draws it at a
  third - `ResetProperty` sets `textScale = scale.X * 0.33333334f`. The MESSAGE
  path measures through `TextDrawer.MeasureString(text)`, whose no-font overload
  reaches `Graphics.MeasureString(fontId, text)` -> `MeasureString(this.mFont,
  text)`, i.e. the natively-hinted 24px face. So:

      drawn_px = MeasureString(24px face, s) * MenuItem.scale.X * PROD(ancestor scale.X)

  **Two rasters means two IMAGE QUALITIES, and a player will report it as a
  bug.** The nameplate is a layout panel, so it draws a 72px raster shown
  small - downscaled, crisp. The dialogue body draws `mFont`, a 24px raster,
  and any window larger than the design resolution scales it UP. On one game
  at ~1.755x the body was a 24px raster stretched to ~42px sitting directly
  under a 72px raster shrunk to the same size, in the same window. The player
  saw "the dialogue is blurry, the name isn't", and "it gets better at lower
  resolution" is the confirming symptom, not a workaround.

  You cannot fix that from rom data - but the WEIGHT of the substituted face
  decides how bad it looks, and that you control. Thin stems are what an
  upscale destroys. Match the weight the author asked for: substituting a
  *Light* for a *Demibold* is a visible regression that no width check sees.

  Weight is a width decision too, so decide it on the author's intent and then
  pay whatever it costs, rather than picking the face your fitting numbers
  like. `[r64268]` paginating the 83,999 dialogue units at 670px, units needing
  more than three rows: **Light 834 (0.99%), Medium 1,365, Regular 1,370, Bold
  1,849, bundled M+SmileBoom 2,498 (2.97%)**. The lightest face is the cheapest
  to fit and the worst to look at.

  **`GameSettings.gameFont` has a magic empty value.** `setGameFont` is
  `useSystemFont = !IsNullOrEmpty(name)`, and when that is false
  `GraphicsCore.createFont` probes `font.ttf`, `<exe>/font.ttf`,
  `<exe>/lib/sysresource/font.ttf`, `<exe>/sysresource/font.ttf` and loads the
  first that exists - through `FileUtil.Exists`, which is
  `File.Exists(p) || FSEx.existsResourceFile(p)`, so it resolves INSIDE the
  resource pack. Bakin games ship a bundled `font.ttf` (M+SmileBoom), so
  clearing the name gives you a face that is guaranteed present on every
  player's machine and cannot tofu. That is the one option immune to "what is
  installed on this particular PC", which is otherwise a permanent hazard for
  a game that NAMES a font instead of shipping one.

  Buy it deliberately, because it is not free. The bundled face is M+SmileBoom
  **bold** - a weight no author asked for, and the worst of the candidates to
  fit at 2,498 units over three rows against Light's 834 (numbers above). And
  nothing catches you if the probe misses: the `Meiryo` fallback line in
  `createFont` sits AFTER the `!useSystemFont` early return and is
  **unreachable**, so an empty `gameFont` with no `font.ttf` anywhere on the
  probe list has no system-font safety net behind it.

  Note the two branches of `createFont` do not agree on what its arguments
  mean. The system-font branch calls `newSystemFont(name, (uint)(size*scale))`
  - the product, so `createFont(48, 0.5f)` and `createFont(24, 1f)` are the
  same 24px. The file branch calls `new Font(path, size, scale)` with the two
  SEPARATE. Do not reason about one from the other.

  Three further consequences worth writing down, because each one cost real time:

  * **The nominal layout size is 24px**, and `scale.X` is the ONLY per-widget
    size control. A screenshot with both a 1.0 and a 0.8 label in it shows the
    difference plainly.
  * **`MenuItem.textScale` is INERT for a text panel.** It is read in exactly
    two places in the engine, `SpinRenderer.ResetProperty` and
    `SliderRenderer` - `TextRenderer` and `SpecialTextRenderer` compute their
    scale from `scale.X` and never look at it. Do not multiply by it.
  * **`scale.X` scales the GLYPHS but NOT the box.** `GetScaledSizeWithoutMyself`
    applies only the ANCESTOR scales to the draw area, so the two do not
    cancel. Measuring at a fixed 24px, the budget is **`size.X / scale.X`**,
    not `size.X * scale.X`. Getting that backwards is wrong by `scale.X`
    squared - too tight at 0.8, too loose by 1.69x at 1.3 - and it hides
    itself, because the too-small budget makes the shipped JAPANESE look
    over-wide and the "author already overflows" rule then drops the widget
    from the check entirely.

- **The label's own `size.X` may bound nothing at all.** Clipping is not done
  against the label's box: `TextRenderer.DrawCallback` passes a rectangle that
  `GraphicsCore.DrawString` never forwards - the native `drawText` overload has
  no rectangle argument - so `useClipping` is only a boolean meaning "obey the
  clip stack". The actual scissor is pushed by the nearest ANCESTOR that
  returns true from `GetClipRectangleSolo`: `MenuContainer`,
  `MenuSubContainer`, `RenderContainer`, `WindowBaseRenderer`. On this game's
  main menu that ancestor is a `MenuSubContainer` whose `CreateWindow`
  OVERWRITES its size with `(MenuContainer.subItemsBaseWidth,
  subItemsBaseHeight)` = **192x35** and draws the plate texture. So the real
  bound on every menu label is at most 192px - `WindowDrawer.GetRectangle`
  narrows it further by half the plate's 9-slice inset, so read `Texture.left`
  off the window resource for the exact figure - while the labels declare 256, 243 and
  200 - three numbers that bound nothing. **Resolve the governing clip
  ancestor before believing any `size.X`.**

- **Watch the already-over count as a RATE.** At the guessed metrics the
  validator excluded `[r64268]` **220 of 551** slots as author-overflowing; at
  the calibrated ones, **70** - and later **38**, once the budget arithmetic
  itself was corrected to `size.X / scale.X`. 40% is not an author, it is a wrong ruler - and the
  exclusion is silent, so every downstream check still reported a clean zero.
  After any calibration change, re-derive **every** width-dependent number:
  overflow flags, nameplate budgets, field budgets.
- **A weight change invalidates the widths and NOT the vertical correction.**
  This build names a font instead of shipping one, so a substituted face is
  unavoidable and its ink box sits differently inside the line box than the
  author's did. Text the engine positions by advance then reads visibly high or
  low, and the fix is an ink offset measured off a screenshot as a fraction of
  the pixel size. That fraction is stable across the LIGHT-to-MEDIUM range and
  not across the whole family: `[r64268]` measured with PIL on descender-free
  text, `(line_centre - ink_centre) / px` is **+0.0547 for Yu Gothic Light,
  Regular and Medium alike, and +0.0625 for Bold** - a 14% move at the heavy
  end. So the Light-to-Medium change actually shipped forced the full width
  re-derivation above and left every vertical nudge standing, but do not read
  that as licence. Re-measure the ink offset when the FAMILY changes, and when
  a weight change crosses into bold.
- **Make the check differential.** Measuring the shipped Japanese first caught
  two modelling errors (a literal's own `\n` breaks measured as one line;
  validating widgets that word-wrap, where width is not a constraint). Even after
  those, `[r73294]` **653 slots were already over their declared box in Japanese** -
  `size.X` on a nested sub-element is often not the visual bound. Flag a slot
  only when the English is wider than the Japanese it replaced. For the same
  reason the per-code min-width map is a **ranking heuristic, not a budget**: the
  narrowest `partyname` slot is 84 px and the shipped `雨瀬みゆ` is 96 px.

### `useMultiLineText` is not the wrap flag on every build - check the signature

On **r64268** `MessageReader.ReadMessage(text, textDrawer, width, textScale,
maxLineNum, sender)` has **no `isWordWrap` parameter at all**: the message path
always wraps, and `MenuItem.useMultiLineText` does not reach it. Reading the
layout data alone would say the opposite - Artesia's Message widget reports
`useMultiLineText = 0` - and a pipeline built on that reading would spend a
fortune compressing prose the engine handles by itself.

Two independent checks caught it, and either alone is enough:

- **Decompile the signature.** One parameter list settles it.
- **Measure the shipped Japanese against the box.** **11.8% of Artesia's
  dialogue physical lines already exceed the 690px panel.** No author ships one
  line in eight visibly broken, so the engine must be wrapping.

The second check generalises to any engine: when a layout model accuses the
author at scale, the model is wrong.

Either way, `splitByLines` **paginates rather than clips** - it does
`line %= lineCount` and starts a new inherited `MessageEntry` each time the index
wraps, enqueuing every one. Nothing is discarded. The real cost of a long
translation on the message path is pacing: extra key presses, which can
desynchronise whatever the script does after the message. Grade it as a soft
note with a threshold.

## What a Bakin harness must DUMP and must be able to WRITE

Everything below was added after a flat `size.X` dump proved unable to answer
"why does this look wrong". Build them in from the start; each one cost a
round trip to discover it was missing.

**Dump, per MenuItem:** `pos`, `offset`, `origin`, `posType`, `image`,
`window`, `useText`, `parent`, `layoutType`, plus the parent container's
`subItemsBaseWidth`/`subItemsBaseHeight`/`subItemMergin`, and per NODE its
`Usage` and `NodeType`.

* **`image` is not the only picture.** `MenuItem` carries about twenty `Guid`
  fields, and the one that draws a container's frame is **`window`** - separate
  from `image` (a sprite), from `subItemBaseBackground` (the plate under each
  row of a sub container), and from the `slider*`/`spin*` families. A dump that
  emits only `image` reports a screen as having no art when every panel on it is
  framed, which is how one battle-result plate stayed invisible for a whole
  debugging session. Cross-reference the id against the resource table to get
  the PNG path: with the art on disk you can composite the widget yourself and
  stop guessing at positions.

* **`parent` and `layoutType`** - `MenuSettings.ParseAllItems()` FLATTENS the
  tree, and a flat list cannot say what a label is drawn on top of. Rebuild the
  link by walking `items`/`subItems` and matching object identity against the
  flat list, not by re-deriving the order.
* **`pos`/`origin`** - without them there is no distance-to-neighbour, so a
  `useClipping = 0` widget (which collides rather than clipping) has no
  measurable budget at all.
* **the parent's `subItemsBase*`** - `MenuSubContainer.CreateWindow` OVERWRITES
  the sub item's own `size` with these, so the row's `size.X/Y` is NOT the
  plate. Read the plate off the CONTAINER that defines it.
* **`Usage` and `NodeType`** - several usages carry TWO `UserResource` nodes
  competing with the `SystemResource` one. On this game `BattleSkill` had three and `SkillSelect` two.
  You cannot reason about a screen without knowing which node is live, and a
  node named nothing like the screen it serves (`スキル` with
  `Usage = BattleSkill`) will mislead you.

**Write, beyond strings:** `pos.X/Y` and `scale.X/Y`, and DOTTED PATHS.

* `pos` and `scale` are XNA `Vector2` STRUCTS - `GetValue` hands back a boxed
  copy, so mutate the box and write it back or the assignment is silently lost.
  Guard `scale`: a 0 erases the text.
* A dotted path like `EffectParamSettings.EffectParamList[3].ChangeParam`
  resolves a property chain with a list index and sets a string PROPERTY, not
  just a public field. Refuse the write if any hop is missing, so a stale index
  can never land in the wrong element.

## A rom field can hold the same text TWICE, and the engine reads the copy

A `Condition` stores its battle messages in the flat `messageForAlly` /
`messageForContinue` / `messageForFinished` fields AND again inside
`EffectParamSettings.EffectParamList[]`, on a `ChangeStringParamEffectParamBase`
element exposing both `Message` and `ChangeParam`. **The engine reads the nested
copy.** Translating only the flat fields left 50 Japanese battle messages on
screen while every unit in the store was translated.

A flat `ROM_TEXT_FIELDS` table cannot reach it, so those strings were never
units - and the usual output check could not see them either, because it
re-extracts the injected build and inherits the same blind spot. It reported
`never extracted as a unit: 0`.

Two habits close this:

* dump the list WITH ITS INDEX (`BakinTL effectparams`) so a write address
  exists at all, and fill the nested copy by SOURCE MATCH against the already
  translated flat field - no second translation, and the two copies cannot
  drift;
* verify the SHIPPED rom with `BakinTL census`, which walks every field and
  property generically. It sees everything - 73,698 Japanese strings on this
  game, almost all editor metadata - so classify each PATH (editor name, asset
  path, formula, key, tag) and fail on any path nobody has classified. An
  unknown path defaulting to FAILURE is what catches the next build's new field.

## Assets: extract through the engine, inject by repointing

### The index is a walkable table, and walking it beats pattern-matching it

The Miyutsure pipeline harvested paths with a regex anchored on a fixed set of
project roots. That is build-dependent: r64268 stores paths **relative to
`res\`** with roots like `texture\`, `model\`, `character\3D\effekseer\`, so the
anchored regex found nothing usable.

Walk the index structurally instead. It is a contiguous run of
`[path][17-byte record]` entries starting at `res_offset + 5`, and the stride is
exact - the next path begins 17 bytes after the last byte of the current one.
That makes the walk **self-checking**: a wrong extension guess desynchronises on
the very next entry and the walk stops, so a clean termination is evidence. On
the Artesia game it terminated on entry 4,405 at
`window\default_selectable.png`, after which the region turns to high-entropy
asset data, and the engine confirmed **4,405 of 4,405 served, 0 missing**.

Two details that each cost a debugging round: `.efk` is a prefix of `.efkmat`,
so the terminator must be the **longest** extension matching at the earliest
position, not the first found; and whether the stored path needs a `res\` prefix
is a per-game measurement - probe one entry both ways with `BakinRes probe` and
use whichever the engine serves.

Watch for a game that ships a file whose EXTENSION lies about its format: seven
of Artesia's 3,403 images are BMP bytes under a `.png` name. Dispatch on magic,
not on extension, anywhere you decode.

The resource region is a native format whose index records carry a second
scramble layer. Do not reverse it. Read assets through the engine's own layer:

```
StdResourceServer.SetDataVersion(<version from the rbpack header>)   # FIRST
FSEx.initializeResourceFileInfo(<data.rbpack>)
FSEx.existsResourceFile(rel) / FSEx.readResourceFileAllBytes(rel)
```

**`SetDataVersion` before `initializeResourceFileInfo`, or every lookup silently
misses** - initialization still returns true. Get the path list by harvesting
path-shaped runs from the descrambled index (it is a contiguous table in the
first few MB); on the reference game 7,906 candidates yielded 7,905 the engine
serves. `BakinRes/` does all of this.

For injection, a loose file at the same relative path is **ignored - the pack
wins**. But the path a texture loads from is just `ResourceItem.path`, and the
catalog round-trips byte-exactly, so:

1. extract the image, edit it
2. set that resource's `path` to something the pack does **not** contain
   (`.\res\tl\<name>.png`)
3. ship the new image **scrambled** under `data\translation\`
4. the hook copies it in, and the native loader falls back to disk

`data.rbpack` is never rebuilt. Proven in-game on the reference title:
`ResourceItem.rbr` changed by exactly the path-length difference and nothing else
moved.

`badpath texture ...` in `data\bakinplayer_log.txt` is **not** a failure signal -
it appears for textures that go on to load normally.

## Custom C# plugin scripts

`script/*.cs` and `battlescript/*.cs` are compiled at runtime by a bundled
Roslyn. Almost all their Japanese literals are **editor-facing plugin metadata**
(command descriptions shown in the Bakin editor); genuine player-facing ones are
rare. This is a separate, **in-place** edit track - these files are edited in the
pack, never exported from the catalog. Do not mix the two tracks (see the
scope-discipline rule in `SKILL.md`).

## Verification the reference pipeline actually ran

- `roundtrip`: **138/138 rom files byte-identical**
- **no-op inject**: all 27,890 units extracted, re-applied and written back,
  **138/138 byte-identical** - extraction and injection are lossless
- **canary build**: title, glossary terms, UI labels and map names replaced,
  installed, launched; the process reported the injected window title
- **image canary**: a texture repointed at a loose scrambled substitute rendered
  in-game
