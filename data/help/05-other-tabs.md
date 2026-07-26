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

## Images

Engine-aware bitmap UI workflow. Choose **Auto-detect**, **RPG Maker MV/MZ**, or
**Generic / Loose Images** after selecting the game folder. Auto-detect uses RPG Maker project,
`System.json`, and encrypted-image markers; otherwise it falls back to Generic and asks for the
folder containing loose PNGs.

1. Use **Decrypt** for RPG Maker assets or **Make editable** for ordinary PNGs. Editable copies
   mirror their game-relative paths under `.dazedtl/images/`.
2. Click **Copy skill** and paste the scoped bitmap-localization instructions into your coding
   agent. The shared workflow automatically receives RPG Maker or Generic-specific guidance from
   the active image profile.
3. Review the edited PNGs here.
4. Patch highlighted images, or clear highlights to patch every editable PNG.

Scanning is read-only. Runtime images remain untouched until you deliberately patch reviewed
copies. Patching checks for external source changes, stages the selected batch, keeps originals
under `.dazedtl/image_backups/`, and adds exact Git/GameUpdate allow-rules.

The Generic profile supports loose PNG files. Packed engine archives require a dedicated engine
profile and are not silently unpacked or rebuilt.

## Batches

History for Anthropic Message Batch jobs.
Resume a batch back onto the Translation tab without submitting a new one.

**Example:** a long CommonEvents batch finished overnight - open Batches, pick the entry, resume consume / validation from here.

## Skills

Edit tool-level markdown:

- `data/skills/system.md` - base translation system prompt
- `data/skills/project_setup.md` - clipboard skill for IDE setup
- `data/skills/wrap_config.md` - RPG Maker wrap-width analysis prompt
- `data/skills/plugin_translation.md` - MV/MZ plugin translation prompt
- `data/skills/ace_script_translation.md` - VX Ace Ruby script translation prompt
- `data/skills/image_translation.md` - scoped bitmap UI translation skill copied from Images
- `data/skills/risky_codes.md` - RPG Maker optional event-code audit prompt
- `data/skills/wolf_speakers.md` - WOLF speaker-format audit prompt
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
