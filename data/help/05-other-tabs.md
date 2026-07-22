# Other Tabs

Workflow is the guided path.
These tabs cover everything else.

## Translation

Manual control: pick a module, check files in `files/`, run Normal or Batch translate.
Workflow jumps here when you start a phase.

**When to use it directly**

- Re-running one stubborn file
- Engines without a full Workflow (Ren'Py, Tyrano, CSV, …)
- Resuming a batch from the Batches tab

**Example:** check only `Map003.json`, module = RPG Maker MV/MZ, click Translate, then export from Workflow Step 5 (or copy from `translated/` yourself).

## Batches

History for Anthropic Message Batch jobs.
Resume a batch back onto the Translation tab without submitting a new one.

**Example:** a long CommonEvents batch finished overnight - open Batches, pick the entry, resume consume / validation from here.

## Skills

Edit tool-level markdown:

- `data/skills/system.md` - base translation system prompt
- `data/skills/project_setup.md` - clipboard skill for IDE setup
- `data/translation_contexts.json` - per-call history templates

Per-game quirks / Translation Frame live under `<game>/skills/` and are edited in Workflow Step 2, not here.

## Configuration

API keys, wordwrap widths, and engine toggles (which RPG Maker codes to translate, Wolf options, CSV delimiters, SRPG, …).

**Example:** if dialogue overflows in MV, set wrap width near `60` and re-run wrap / re-translate the overflowing maps.

## Folder cheat sheet

| Path | Role |
|------|------|
| `files/` | Input JSON / text for the current run |
| `translated/` | Output from the translator |
| `log/` | Run logs and caches |
| `data/help/` | This Guide's markdown (edit to update) |
| `data/skills/` | Tool-level skills |
