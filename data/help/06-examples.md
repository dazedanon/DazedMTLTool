# Example walkthrough

This page is a concrete story of translating one game, step by step.
Use it to see the *order* of work. Details for each Workflow step live in the other Guide sections and in each step's **?** button.

Assume: Claude Sonnet 4.6 for paid quality + Batch, or Mistral if you are on the free tier.
Also assume Cursor (or VS Code) has the **game folder** open for glossary / UI script work.

---

## Example A - First RPG Maker MV/MZ game

You just downloaded a small MV game. You want English dialogue, menus that make sense, and a playable build - without boiling the ocean on day one.

### 1. Get the tool ready

1. Launch DazedTL (opens on this Guide).
2. Open **Configuration**, set your API key and model, save.
3. Open the game folder in Cursor so the agent can read JSON later.

### 2. Point Workflow at the game

1. Open **Workflow** → engine **RPG Maker**.
2. Step 0 - browse to the folder with `Game.exe` / `www/` (MV) or `data/` (MZ).
3. When the file list appears, start small: check core DB files (`Actors`, `Items`, `System`, …) plus **one** early map (`Map001.json`). Import those into `files/`.

You are not importing the whole game yet. A tiny slice proves the pipeline before you burn tokens on every map.

### 3. Set up names and voice (Step 2)

1. Use **Collect names** if the game uses nameplates the tool can harvest.
2. Click **Copy setup skill**, paste it into Cursor with the game open, and let the agent return the project guidance.
3. Paste each block into the Workflow editors and save.

Now the translation API has character genders, terms, and a short Translation Frame instead of guessing blind.

### 4. Translate a slice (Step 3)

1. Prefer **Normal** mode while you are learning.
2. Click **Translate database** for names and descriptions.
3. Click **Translate dialogue** for the selected map.
4. Skim `translated/` and `log/` - do names look consistent? Does dialogue sound okay?

If something is wrong, fix vocab / quirks *now* before you translate fifty maps.

### 5. Put it in the game and play

1. Step 5 - **Export selected files** (only what you imported).
2. Step 6 - optionally **Preview rewrap** and **Apply rewrap**, then copy the final QA skill and
   build the public release ZIP.
3. Launch the game and walk that first map.
4. Note leftovers: overflow, wrong names, Japanese in a menu.

Fix leftovers next (re-translate a file, tweak wrap width in Config, or OCR → search in the IDE). Do not jump to Phase 2 yet.

### 6. Scale up

When the sample map looks good:

1. Step 0 - import the rest of the maps / CommonEvents (or the next chunk).
2. Step 3 Phase 1 again - use **Batch** with Claude if the set is large; stay on **Normal** with Mistral.
3. Export again and play further.

### 7. Risky codes and UI (only when needed)

1. Step 4 - copy the Plugin / risky-codes prompt, audit the game in your IDE, enable only codes that hold player-visible text, then run Phase 2 carefully.
2. Step 5 - for MV/MZ, copy vocab + the plugins.js prompt and edit `plugins.js` in the IDE (player-facing strings only), then export. For **Ace**, edit `ace_json/scripts/*.rb` the same way, then Export so **RV2JSON** packs `Scripts.rvdata2`.
3. Step 6 - scan/reapply widths directly to exported dialogue, face dialogue, list/help, or note
   fields that need reflowing, then run final QA and package the release.
4. Step 7 (MV/MZ) - check image setup, then decrypt / translate / patch any bitmap UI text.
5. Step 8 (MV/MZ) - install TL Inspector / Forge if you want in-game inspection helpers.

### What “done enough” looks like

You can play through without walls of Japanese, menus are readable, and you know how to OCR → search → re-export when something slips through. Perfect first pass is rare; the loop is translate → play → fix → expand.

---

## Example B - Same idea on WolfDawn (short)

1. Workflow → **Wolf RPG (WolfDawn)** → Step 0 extract + import.
2. Step 2 - build vocab in Cursor from the extracted files (skip `names.json` value names).
3. Step 3 - translate **safe** names only.
4. Step 4 - **Translate foundation database** first; add the narrative database if discovery says the game is DB-heavy.
5. Step 5 - **Translate maps & events** (Batch for huge CommonEvent files on Claude).
6. Step 6 **Preview all injection** → Step 7 **Apply all translations** → Step 8 build the playable game → play.
7. Step 9 - fix overflowing lines → apply all translations → build again.

Same philosophy as RPG Maker: prove quality on a small slice of content, then scale; pack/inject before you judge overflow in-game.

---

## Habits that save time

- **Git** the game folder before big Export / Inject passes so you can roll back.
- Start with **one map** (or one DB sheet), not the whole project.
- Fix glossary and speaker flags early - they multiply across every later file.
- Use Batch for bulk overnight work; Normal for quick iteration.
- Leftover Japanese: screenshot → OCR → search in the IDE → re-translate or hand-edit → export/inject again.
