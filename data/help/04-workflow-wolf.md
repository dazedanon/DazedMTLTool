# Workflow: WolfDawn

Open **Workflow** and select **Wolf RPG (WolfDawn)**.
The bundled `wolf` CLI unpacks archives, extracts strings to JSON, translates with the same AI pipeline, then injects byte-exact results.

## Steps at a glance

| Step | What it does |
|------|----------------|
| **0 Project** | Select game root, unpack/extract to `wolf_json/`, import into `files/` |
| **1 Prepare** | Optionally format extracted data and install GameUpdate |
| **2 Setup** | Configure speakers and build project guidance with your IDE agent |
| **3 Names** | Translate safe `names.json` entries |
| **4 Database** | Translate foundation data, then narrative database sheets |
| **5 Maps & events** | Translate maps, CommonEvent, Game.dat, and Evtext |
| **6 Precheck** | Preview injection before writing binaries |
| **7 Inject** | Apply all reviewed JSON translations |
| **8 Package** | Use loose Data or build `Data.wolf`, with optional save updates |
| **9 Fix wrap** | Find overflowing lines, rewrap them, and apply again |

## Example: first WolfDawn run

1. Step 0 - point at the folder with `Game.exe` / `Data.wolf`.
2. Let extract finish; import the listed JSON (or leave the step with files checked).
3. Step 2 - copy the Wolf glossary prompt into Cursor with extracted files available; paste vocab back.
4. Step 3 - translate **safe** names only.
5. Step 4 - read the discovery summary. For a classic RPG layout, translate the foundation database before maps and events.
6. Steps 6–8 - **Preview all injection** → **Apply all translations** → build the playable game → playtest.

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
