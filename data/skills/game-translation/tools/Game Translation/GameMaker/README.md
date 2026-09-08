# GameMaker Text Tools

Reusable GameMaker inspection and translation-patch tooling. Python 3.10+,
standard library, with the official **UndertaleModTool CLI 0.9.2.0** backend.
The installed Windows CLI is self-contained; a .NET SDK is not required.

Stable home: `C:/Users/sw/Desktop/Tools/Game Translation/GameMaker`.

## Commands

Run from a writable project directory. Always keep the original archive.
Output commands refuse existing paths, so re-export cannot erase translations.

```powershell
$gmtt = 'C:\Users\sw\Desktop\Tools\Game Translation\GameMaker\gmtt.py'
python $gmtt inspect 'data.win'
python $gmtt snapshot 'data.win' -o 'work/source.snapshot.json'
python $gmtt census 'data.win' -o 'work/census.json'
python $gmtt decompile 'data.win' -o 'work/code'
python $gmtt export 'data.win' -o 'work/catalog.json'
python $gmtt find 'work/source.snapshot.json' 'draw_text'
python $gmtt validate 'data.win' 'work/catalog.json'
python $gmtt patch 'data.win' 'work/catalog.json' -o 'build/data.win'
python $gmtt verify 'data.win' 'work/catalog.json' 'build/data.win'
python $gmtt diff 'data.win' 'new-version/data.win'
```

`inspect` is dependency-free: FORM chunks, size/hash, STRG count and CJK census.
`snapshot` adds code instructions, literal references, ordered resource names,
font glyph advances/kerning and stored media hashes. `find` searches every
pooled string and lists supported code/caption sites. `census` explicitly lists
strings outside supported sites, including strings with no CJK characters.
`decompile` exports parent GML entries and checks expected output count and
decompiler error markers. Nested functions live inside their parent GML files.

`export` defaults to CJK candidates. Use `--select all` for other languages,
ASCII/full-width typography, captions and a complete supported-site inventory.
Neither selection is a proof of player-facing text: review each use in GML.

## Translating the catalog

Each entry represents one use: `CODE:<code index>:<instruction index>`, or
`GEN8:display_name` for the window caption. IDs are stable only within the
source build and are guarded by the entire archive's SHA256. Code names and
nearby disassembly supply context. Child code aliases are not double-counted.

Set `translation` to the translation of `masked_source`, preserving every
`⟦GM:0000⟧` sentinel exactly and in order. Leave `source`, coordinates,
`masked_source`, and `tokens` untouched. Set `reviewed: true` after verifying
that changing this particular code use is appropriate. `null` means untouched;
an identical source translation is a no-op. Empty replacements are rejected.

GameMaker has no universal game-specific dialogue control language. By default
only actual line breaks are masked. For custom markup, pass `--token-patterns`
with a JSON array of regular expressions after reading the game's renderer.
For example, a game that actually parses `{0}` and `[wait=12]` could use:

```json
["\\r\\n|\\r|\\n", "\\{[0-9]+\\}", "\\[wait=[0-9]+\\]"]
```

Do not copy another game's control-code rules without checking. Supply a
complete pattern list, including line breaks when they must be preserved.
The validator rejects missing, duplicate, reordered or added controls,
tampered masks, stale sources, duplicate IDs, embedded NULs and unreviewed edits.
`validate --complete` additionally requires translations and no residual CJK
**within the submitted catalog**; it does not certify whole-game coverage.
This toolkit makes no translation API requests or paid calls.

Optional per-entry `font`, `max_width`, and `max_lines` enable glyph coverage
and explicit-line measurement using the embedded font's glyph data. Font names
are in the snapshot. Width is nominal at the font's stored scale, with kerning;
extra draw transforms, custom parser substitutions, clipping and runtime wrap
must be established from the game's code/screens before treating it as a UI
fit guarantee. Entries with controls report layout as unmeasured rather than
guessing substitutions. No font assignment reports a warning. Missing glyphs
in an assigned font and exceeded declared bounds fail validation.

## How patches work

The patcher **appends a new pooled string for each changed site** and redirects
only that existing string operand (or window caption reference). It preserves
the original string table prefix, every unselected reference, instruction
counts, function offsets and asset identities. It never recompiles GML or
edits pooled strings globally. This matters because the same interned string
can be a visible label, asset name, filename and logic key simultaneously.
Changing even one use can still affect game logic: site-level GML review and
runtime testing remain necessary.

UTMT relocates the full archive, allowing longer UTF-8 strings. Output is built
in a temporary sibling directory, reopened and checked before publication:

- Independent strict FORM/STRG parsing agrees with the backend on every string.
- All original pooled strings and unselected references remain intact.
- All instruction descriptions, lengths, offsets, locals and argument counts
  match, apart from the explicitly redirected string IDs.
- Ordered resource names, font glyph metrics and stored texture/audio hashes match.
- Source and catalog identity are checked again before publishing.

A no-op copies the original archive byte for byte, then verifies it. This
proves the toolkit's no-op contract; it is **not** a claim that arbitrary UTMT
reserialization is byte-identical. Changed outputs undergo actual serialization.
Each build emits `<output>.report.json`, with input/output hashes, exact changes,
checks, warnings and `runtime_tested: false`. The structural checks do not
compare every non-text resource field (for example every room coordinate).

There is no deploy command: build to a separate file and test in a game copy.
Tool tests alone cannot prove startup, English wrapping, menu coverage or save
compatibility. Keep game executables and original archives out of public tool
distributions. No art replacement or automatic font regeneration is included.

## Supported scope

- GameMaker Studio FORM/STRG archives readable by the pinned UTMT backend.
- VM code literals and GEN8 window captions, with append-and-redirect injection.
- YYC archives can be inventoried where readable, but native code extraction
  and injection are explicitly rejected. Use native RE for those literals.
- Custom packed/encrypted formats, external localization files, LANGUAGE
  records, script-generated text and extensions require their own adapters.
- External textures are marked external; their file content is not hashed here.
- STRG inventory diff is advisory. Cross-version translation migration is
  deliberately not automatic because instruction IDs can shift.

## Setup and tests

```powershell
python bootstrap.py
python test_gmtt.py
python test_gmtt.py --data 'C:\path\to\game\data.win'
```

Bootstrap downloads the pinned official Windows release and verifies SHA256
`e7573e45d107be34f81f955c6e4afc3c7c8f2628e5a6f307a871e3825b3dfb40` against the
published release digest. `vendor/manifest.json` records provenance;
`vendor/source-reference` contains the pinned API sources and upstream license.
The upstream CLI ships its own dependencies and licenses. `GMTT_UTMT` may select
another compatible CLI executable; the bridge API is tested against 0.9.2.0.
`GMTT_TEMP_DIR` may select a writable scratch directory; default is current
directory. Scratch paths are checked before cleanup. No tool depends on this
game's installation path.

See [CASE-NIGHTFALL.md](CASE-NIGHTFALL.md) for measured validation results and
the completed translation/UI follow-ups. Companion scripts for controlled GML
layout imports, trimmed atlas edits, tooltip audits and window credits live in
`C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)/manual-translation`.
Read that project's `README.md` before adapting them. They are game-specific
adapters built on this toolkit; they do not change `gmtt.py`'s literal-only patch
contract or add image replacement to its CLI.

Sources: [official UTMT repository](https://github.com/UnderminersTeam/UndertaleModTool),
[pinned release](https://github.com/UnderminersTeam/UndertaleModTool/releases/tag/0.9.2.0),
[published asset digests](https://github.com/UnderminersTeam/UndertaleModTool/releases/expanded_assets/0.9.2.0).
