# Quick Start

This is the happy path for a new game.

## 1. Configure the API

Open **Configuration** (sidebar gear).
Enter your key and model, then save.

- **Recommended:** `claude-sonnet-4-6` (cheap high-quality TLs; enables Batch at ~50% off).
- **Free:** `mistral-medium-3.5` (live only).

A wrong key shows up immediately when you try the first translate.

## 2. Open Workflow

Use the Workflow sidebar button (or **Open Workflow** on this Guide).
Choose the engine at the top:

- **RPG Maker MV / MZ / Ace**
- **Wolf RPG (WolfDawn)**

## 3. Step 0 - Project

Browse to the game folder.
Import the listed data files into the tool's `files/` folder (Workflow does this for you when you import or leave the step with files checked).

**Example:** for RPG Maker MV, you typically import `Actors.json`, `Items.json`, maps, `CommonEvents.json`, and so on into `files/`.

## 4. Step 1 - Pre-process (optional)

Run formatters / copy `gameupdate/` only if you want cleaner diffs or the updater scripts.
Skip if you just want to translate.

## 5. Step 2 - Setup with your IDE agent

1. Parse speakers into vocab when available.
2. Copy the **Project Setup** skill into Cursor / VS Code with the game open.
3. Paste the returned `glossary`, `speakers`, `translation_quirks`, and `game_skill` blocks into the Workflow editors and save.

See **Examples** for paste-ready prompts.

## 6. Translate in phases

Follow the Workflow steps (Phase 0 / 1 / 2 for RPG Maker, or Names → Database → Maps for Wolf).
Each action configures the Translation tab and can start a run for you.

**Example (RPG Maker):** Phase 0 = database names → Phase 1 = dialogue → Phase 2 = risky plugin / variable codes.

## 7. Export / inject and playtest

- RPG Maker: Export from `translated/` back into the game, then install TL Inspector / Forge if you want.
- Wolf: Precheck → Inject all → Package → playtest → Fix wrap.

## 8. Fix leftovers

Screenshot Japanese text → OCR → search in the IDE across the game / `translated/` → re-translate or hand-edit → export/inject again.

See **Example Walkthrough** for a full first-game process story.
