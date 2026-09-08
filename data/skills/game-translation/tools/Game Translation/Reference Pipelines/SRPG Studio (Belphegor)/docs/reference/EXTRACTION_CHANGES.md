# SRPG-ToolBox — added player-facing text extraction

Changes made to the cloned tool to extract player-facing text that the upstream
version parses but never emitted to the translation patch.

## What was added (25 files, +194 lines)

**`customParameters` extraction for 12 data classes** — each parsed a trailing
player-facing string field but never serialized it. Added `toJson()`/`applyPatch()`
(following the existing `SKILLDATA`/`ITEMBASE` idiom: `j["customParameters"] = <field>.ToString();`
+ `SET_STRING_IF_IN_JSON(...)`):

| Class | Field | Reaches patch file |
|---|---|---|
| STATEDATA | this_18 | `states.json` (18 escort-word entries, e.g. `護衛：ルート`) |
| WORDDATA | this_8 | `Extra/glossary.json` (108 entries — dictionary condition strings) |
| RACEDATA | this_8 | `races.json` |
| CLASSTYPEDATA | this_13 | `classtypes.json` |
| WEAPONTYPEDATA | this_11 | `WeaponTypes/*.json` |
| DIFFICULTYDATA | this_12 | `difficulties.json` |
| NPCDATA | this_8 | `NPCSettings/npc*.json` |
| SOUNDMODEDATA | this_12 | `Extra/soundroom.json` |
| RESTSHOPDATA | this_12 | `Base/shops.json`, `bonuses.json` |
| PASSCHIPDATA | this_15 | `Terrain/*.json` |
| CHARACTERDATA | this_8 | `Extra/characters.json` |
| GALLERYDATA | this_10 | `Extra/gallery.json` |

(`RACEDATA.cpp` also gained `#include "../CMenuOperation.h"` for the macro.)

**MOVETYPEDATA name extraction** — `MOVETYPEDATA::toJson()`/`applyPatch()` emitting
the movement-type name (`this_3`), plus two wiring lines in `SRPG_Database.cpp`
(`writePatches`/`applyPatches`) creating a new **`movetypes.json`** (12 names:
軽歩/重歩/騎馬…; 9 are `未定義`/undefined placeholders).

## Verified

- **Extraction**: regenerated patch = 249 files (was 248); new fields present and
  populated (movetypes 12, states escort 18, glossary 108).
- **Translation round-trip** (the correct test): extract → edit a value → `-a` apply →
  the new text is injected into `project.dat` (binary-verified: `Cavalry_TEST`,
  `ESCORT_TEST_ENGLISH`, `Guard:`×8 all written; the original `騎馬`/`護衛：ルート`
  instances I edited were replaced, others untouched).

## Important: apply behaviour (inherent to the upstream tool, NOT these changes)

`-a` apply re-encodes every string via `MemData::FromString`, which appends a null
terminator. For this game's `project.dat` that grows the file ~1064 bytes and the
tool **cannot re-parse its own apply output** (`ReadBytes past end of file`). This
was confirmed **identical on the pristine, unmodified tool** — it is a pre-existing
property of the apply path for this title, independent of the additions here.

Practical implications:
- Apply (`-a`) is the **final** step — produce the translated `project.dat` for the
  game; do **not** re-extract (`-c`) from an applied `project.dat`.
- Keep a backup of the original `project.dat` before applying.

## Not yet implemented (separate subsystem)

Hardcoded Japanese in the game's **JS plugins/scripts** (e.g. `文字変更.js` ~239
strings, `constants-stringtable.js` 215 strings, `EC_DefineString` tables) is not in
`project.dat` and needs a dedicated JS string-extraction pass — a separate feature.
See [TRANSLATION_COVERAGE_AUDIT.md](TRANSLATION_COVERAGE_AUDIT.md) §3(b)/(c).

## Rebuild

`MSBuild SRPG_Unpacker.sln /t:Build /p:Configuration=Release /p:Platform=x64`
Binary: `SRPG_Unpacker/x64/Release/SRPG_Unpacker.exe` (v0.1.2).
