# GameMaker: translation, UI repair and archive patching

Stable toolkit: `tools/Game Translation/GameMaker`. Run `python bootstrap.py` there once to fetch the pinned UTMT CLI into `vendor/utmt` (not bundled, 129 MB).
Read its `README.md` for CLI/schema and `CASE-NIGHTFALL.md` for measured evidence.
Use the bundled UndertaleModTool CLI for GML decompilation and archive writing;
do not build a new general GameMaker serializer.

For the completed manual translation and companion layout/image scripts, read
`tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)/manual-translation/README.md`.
Those adapters are per-game examples, not additional `gmtt.py` commands. Reuse
their checks and re-measure each game's constants. The APIs below were tested
against the bundled UTMT **0.9.2.0**, not every UTMT version.

## Route correctly

`data.win` (Windows), `game.unx`, `game.ios` and `game.droid` commonly contain
a `FORM` container with `GEN8`, `STRG`, and (VM builds) `CODE` chunks. Confirm
using `gmtt.py inspect` and `snapshot`. An exe version of 1.0.0.0 is a game
version, not an engine version. UTMT's inferred feature version is not proof
of the exact compiler patch release.

VM builds support literal-site extraction/injection. YYC compiles game logic
to native code; the tool rejects code-site patching there. Readable STRG data
does not imply all native literals are covered. Route the native executable
to reverse engineering; do not claim a STRG dump is the full text corpus.

## Workflow

1. `snapshot`, `census` and `decompile` from the original archive. Census every
   pooled string, including entries outside supported sites. Inspect game file
   readers for additional text tracks (external JSON/INI/CSV, native extensions).
2. `export` creates JSON entries keyed by original code/instruction position,
   with exact source, pooled ID and neighboring instructions. Default CJK
   selection is a candidate filter. Use `--select all` when appropriate;
   a string with no CJK characters can still be player-facing.
3. Review literal uses in recovered GML. One pooled string can be display text
   and a logic key. Set `reviewed` only on the appropriate uses. Establish
   speakers, scene groups, glossary and renderer-specific codes before doing
   translation. Supply control regexes to `--token-patterns`; there is no
   universal GameMaker dialogue markup language. Preserve masked sentinels.
4. `validate`, then `patch` to a separate archive. The injector appends strings
   and changes specific operands, preserving the old pool and every unselected
   use. It does not recompile scripts. Empty catalogs produce byte-identical
   copies. Longer translations use UTMT relocation, not byte-budget truncation.
5. Reopened output is checked against the expected string/reference changes,
   all instruction descriptions, resource identities, font data and embedded
   media hashes; a separate raw STRG reader checks the strings independently.
   Keep the generated report. These checks do not inspect every room coordinate.
6. Test a changed canary in a game copy, then follow the translation skill's
   live menu/layout/save matrix for a release. A passing archive test is not a
   screenshot or save/load proof. `runtime_tested` remains false in tool reports.

Catalogs are bound to the source SHA256. Re-export to a fresh file, never over
a finished catalog. `diff` is an advisory inventory, not automatic migration.
No built-in paid translation call, installation into the game, art replacement,
native hook or font regeneration is part of this tool.

## Font and layout traps

Use exported **glyph records**, not font range endpoints, to test coverage.
Assigned `font`, `max_width` and `max_lines` gate nominal explicit-line bounds.
The runtime can add scale, clipping, custom wrapping or substitutions, so derive
those separately and calibrate against source screenshots before enforcing a
layout model. Several draw paths may render the same text differently.

Nightfall Princess had 630 CJK literal sites; a Japanese-punctuation-only
separator made the final text catalog 631. Three CJK font names remain technical
metadata. ASCII is covered by its seven fonts; smart apostrophes and em dashes
are not. These are case findings, not a coverage rule for other games.

Measure final substitutions from the game's code, including every reachable
rank value and word-valued variant. Nightfall's audit expanded 391 rank forms
inside 1,012 measured forms. Check grammar at singular values too. When a help
lookup searches for literal substrings in translated descriptions, synchronize
the lookup keys with the locked English terms and verify the match sets. These
are coupled display/lookup uses requiring review, not permission to translate
arbitrary logic keys.

Measure the whole composed help panel: its height may count explicit source
newlines while its draw routine wraps English into extra rows. Each constituent
string fitting independently does not prove the assembled help block fits.

For typewriter dialogue, set the correct font and word-wrap the complete message
before revealing characters. Inspect any separate per-character wrap loop;
prewrapping is effective only if that loop will not split the words again.
Nightfall used a measured 510px prewrap ahead of its existing 520px loop.

### Tooltip headings are a separate render path

Read the actual plate width, title inset, icon reservation, font and scale.
Nightfall's 336px plate with a 70px title inset and 14px right margin allowed
252px. "Weapon Enchantment" measured 292px despite the description audit passing.
Sweeping all 89 skill/stat headings, including the ASCII-only `CD` sibling,
found five overflows. See [text-fitting.md](text-fitting.md) for the general
heading strategy; this game's `tooltip_audit.py` retains the failing example.

The repair used `min(1, available / max(1, string_width(title)))` as a uniform
`draw_text_transformed` scale, with the active heading font already selected.
It kept full glossary names and adjusted only overflowing headings. This game's
minimum scale was about 0.863; its audit floor of 0.85 is not a universal readable
size. Preserve vertical placement within the heading line and verify actual
ink margins at the supported display sizes.

## Controlled GML imports for layout fixes

Literal injection and code compilation are separate build stages. Compile only
the reviewed scripts/events that need a behavior change; do not decompile and
rebuild the whole game to replace text. Use the pinned compiler API:

```csharp
using UndertaleModLib.Compiler;
var group = new CodeImportGroup(Data);
group.QueueReplace(codeName, gmlSource);
var result = group.Import();
if (!result.Successful)
    throw new Exception(result.PrintAllErrors(false));
```

Resolve each approved code name exactly once before queuing it. Base edits on
the current translated archive; compiling original GML over it can revert
translated literals. Original source is safe only where inspection proves the
selected event contains no translated literals and carries no later edits.
The CLI decompile output is under `CodeEntries/`; inspect the emitted paths.

Reopen the output and allow code changes only in the approved entries and their
child functions. The compiler may append Variables, Functions and CodeLocals;
check the existing prefix and record those additions. Preserve other code,
resource identities, font metrics and media. Recheck the translated references
after compilation: instruction-site IDs are not guaranteed to survive an edited
event, so reconcile any shifted sites using the reviewed source and context.
Old Japanese pool entries are expected under append-and-redirect; check live
references, not an indiscriminate residual scan of the retained STRG pool.

## Baked UI sprites: preserve both atlas and canvas

Only inspect/redraw the image scope the user requested; named menus or screenshots
are enough to identify that scope. A literal census cannot inspect sprite text.
Use [image-translation.md](image-translation.md) for lettering edits and preserve
icons, keycaps, borders, alpha and decorative brushwork with explicit edit masks.

Export selected sprite frames and their full metadata with the pinned API:

```csharp
using UndertaleModLib.Util;
using var worker = new TextureWorker();
worker.ExportAsPNG(item, outputFile, null, true); // padded canvas
// Save an atlas through TextureData.Image.SavePng(stream).
// Import a reviewed atlas through:
Data.EmbeddedTextures[page].TextureData.Image =
    GMImage.FromPng(File.ReadAllBytes(atlasFile));
```

Record sprite/frame identity, page index, `SourceX/Y/Width/Height`,
`TargetX/Y/Width/Height`, `BoundingWidth/Height`, sprite dimensions and origins.
The source rectangle is stored in the atlas; the target rectangle places that
crop on the padded canvas. A 241px exported sprite can store only 101px of ink.
English fitting the PNG can therefore be silently clipped on import.

Before cropping edited pixels back into an atlas, detect any changed pixel
outside the stored target rectangle. If English needs that region, remap the
entry to storage large enough for it. Nightfall extended one existing atlas
from 256x256 to 256x512, kept its old pixels in place, and stored three full
canvases in the new area. It retargeted the existing page items, set source and
target sizes to their bounding sizes and target offsets to zero, preserving
bounding sizes, sprite dimensions, origins and identities. Verify page sharing,
texture-group loading and runner size limits before adapting this method;
growing this particular atlas is an example, not a universal repacking recipe.
The companion importer rejects scaled source/target rectangles until supported.

Reopen the actual patched archive and check **both**:

- Decoded atlas pixels match the intended atlas, including all unchanged pixels
  outside the approved masks. Font glyph art may share a page with UI art;
  unchanged font metrics alone cannot prove the glyph pixels survived.
- Every edited padded sprite matches its reviewed full-canvas PNG exactly;
  resource identities, bounds, origins and all unapproved mappings are unchanged.

Nightfall's atlas-only check initially passed while "Settings" was clipped by
the old crop. The second check caught it. Keep both and then inspect the game.

## Runtime evidence and drop-in delivery

For hard-to-reach tooltip states, first freshly decompile the archive being
tested. The companion `qa/build_tooltip_canary.py` reads that exported GML under
`qa/tooltip-decompiled/CodeEntries/`; it does not refresh the export itself.
Bind the decompile to the test archive so an old file cannot supply a stale draw
block. The fixture extracts the real block and exercises it in a title-only
test copy. This proved the five corrected headings had 15-17px of
right ink margin without entering gameplay or changing the player's save.
It proves that renderer, not the live gameplay trigger or a complete playthrough.
Keep the fixture out of the release and check the player's save hash before and
after when the runner still uses the normal user-data directory.

For a requested window credit, patch `GEN8:display_name` through the literal
injector; inspect GML for later `window_set_caption` overrides. Do not rename
`GeneralInfo.Name` or resource identifiers just to change the displayed title.
Nightfall retained internal identity `Nightfall_Princess`, used by its save
directory, while showing `Nightfall Princess | Translated by len`. Read back the
actual process window title; this caption uses the OS, not an embedded game font.

A requested drop-in patch for this build needs the final `data.win` plus a short
install/restore README. Test the actual delivery file beside the original exe
and required companion files in a clean game copy, and compare the package and
installed hashes. Retain code, masks, original archives and QA reports under
a stable tools project outside the game folder. See [playtesting-and-release.md](playtesting-and-release.md)
for payload allowlists, repository conventions and metadata-only follow-ups.
