# Workflow: WolfDawn

Open **Workflow** and select **Wolf RPG (WolfDawn)**.
The bundled `wolf` CLI unpacks archives, extracts strings to JSON, translates with the same AI pipeline, then injects byte-exact results.

## Steps at a glance

| Step | What it does |
|------|----------------|
| **0 Project** | Select game root, unpack/extract to `wolf_json/`, import into `files/` |
| **1 Pre-process** | Optional format + copy `gameupdate/` |
| **2 Glossary** | Build vocab with your IDE agent (not item/skill names from `names.json`) |
| **3 Names** | Translate safe `names.json` entries (Phase 0) |
| **4 Database** | Foundation DB then narrative DB sheets |
| **5 Maps/Events** | Maps, CommonEvent, Game.dat, Evtext |
| **6 Precheck** | Safety dry-run before writing binaries |
| **7 Inject** | Inject all translated JSON |
| **8 Package** | Loose Data/ or repack `Data.wolf`, optional save rewrite |
| **9 Fix wrap** | Find overflowing lines, wrap, reinject |

## Example: first WolfDawn run

1. Step 0 - point at the folder with `Game.exe` / `Data.wolf`.
2. Let extract finish; import the listed JSON (or leave the step with files checked).
3. Step 2 - copy the Wolf glossary prompt into Cursor with extracted files available; paste vocab back.
4. Step 3 - translate **safe** names only.
5. Step 4 - read the discovery summary. For a classic RPG layout: foundation DB → maps/events.
6. Step 6–8 - Precheck → Inject all → Package → playtest.

## Layout order

After extract, the Database discovery report classifies the game:

| Layout | Order |
|--------|--------|
| **DB-heavy** | Names → foundation DB → narrative DB → maps/events |
| **Classic RPG** | Names → foundation DB → maps/events |
| **Hybrid** | Names → foundation DB → narrative DB → maps/events |

## Safety badges on names

- `safe` - Phase 0 will translate
- `refs` / `verify` - stay Japanese so inject skips them until you handle them carefully
