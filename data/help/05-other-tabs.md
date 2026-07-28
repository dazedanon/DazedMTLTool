# Other Tabs

Workflow is the guided path.
These tabs cover everything else.

## Version Update

Move an existing translation from an old official game version to a newer one without relying on
Git conflict resolution. A first scan needs three states: the old clean game, the current
translated game based on it, and the new clean game. Old official can be a selected folder or the
game's local Git `original` branch (`origin/original` is also recognized). The branch is exported
read-only without checking it out or changing the working branch. After a successful update, the
output stores an official-source baseline under `.dazedtl/version_update/`, so future scans only
need the current translation and new official game.

1. Select the folders and optional labels such as `v1.00` → `v1.03`.
2. Use **Auto-detect** for RPG Maker MV/MZ semantic JSON migration, or **Generic / Files Only** for
   safe whole-folder reconciliation.
3. Click **Scan Update**. Scanning is read-only and covers the entire game folder: data, plugins,
   images, audio, video, fonts, executables, DLLs, and other assets.
4. Choose a destination and click the recommended action:
   - **Create a separate updated folder** is the default. It creates a new game folder and leaves
     every input untouched.
   - **Update the current translated folder** builds the complete result in a sibling staging
     folder first. After staging succeeds, it swaps the folders and keeps the previous translated
     game beside it as a complete rollback backup. Close the game and editors before using this.
   Both modes restore every upstream-first recommendation, apply the complete official update, and
   carry forward only local changes that the three-way comparison can prove safe.
5. Reconcile afterward as needed: translate newly introduced text and review the files listed as
   **Translation at risk** in the report. Reviewing before creation is optional. If you deliberately
   override rows in the **Needs review** queue, use **Create with Review Choices** instead.

If the selected official build exactly matches the saved baseline, Version Update automatically
runs a read-only **Recovery audit** instead of presenting an unexplained empty review queue. This
reconstructs the earlier old-to-new comparison from retained baselines or a fingerprint-verified
Git `original` branch, then presents potentially reverted maps, plugins, images, and other files
through the normal reviewable merge. Nothing is modified until you explicitly choose **Reapply
Recovered Changes** or **Reapply with Review Choices**. A prior update report or the matching old
official folder is required; version labels alone are not used as proof. If the history is missing,
the tab reports that the build was already applied and explains why automatic recovery is
unavailable.

Recovery findings distinguish three states. **Definite revert** means the complete current file is
byte-for-byte or semantically equal to the previous official file. **Possible revert / local edit**
means it matches neither official version and therefore requires judgment. **Official change
present** means the current file already matches the newer official source. The Recovery findings
filter shows only the first two states.

Every staged file is checked against its selected source or generated merge before publication,
and supported RPG Maker JSON is parsed again. Retained manifests and mergeable sources are also
rehashed before use. Outputs retain the newest eight reports and every baseline those reports need;
older unreferenced history is pruned to keep `.dazedtl` bounded. Keep `.dazedtl/version_update/`
with the translated game or retain a matching Git `original`/old official copy. These checks do not
launch the engine, so always start the resulting game and smoke-test affected maps and plugins.

RPG Maker data changed only upstream is taken from the new game. Unchanged source text keeps its
visible translation exactly. New or changed Japanese text remains ready for Translation.
`js/plugins.js` is merged by plugin name rather than line position: the new official plugin order,
new plugins, and settings are accepted while unchanged nested parameter translations and genuinely
translator-added plugins are retained. Individual plugin source files receive a conservative
three-way text merge when edits do not overlap. An overlapping code edit defaults to the complete
new official file and stays visible in **Translation at risk** for manual review.

JSON is compared by parsed content, so indentation, whitespace, and object-key ordering do not
create false changes. You do not need to format the old and new games alike, and Version Update
does not rewrite either input just to normalize formatting.

File policies keep repository management out of the game comparison:

- `.gitignore`, other VCS metadata, OS metadata, `.dazedtl/`, and translation `skills/` are not
  update decisions. Existing local copies can remain in the staged output without blocking it.
- DazedTL's `gameupdate/` support folder and its root launchers (`GameUpdate.bat`,
  `GameUpdate_linux.sh`, and UberWolf helper files) are local distribution tooling, not official
  game content. Version Update preserves the current copies unchanged and does not compare
  `patch-config.txt` with the official versions.
- Audio is never treated as translated and always follows the new official game, including
  upstream deletion.
- Images not marked as translated follow the new official game. For images patched through the
  Images tab, Version Update uses `.dazedtl/image_backups/` as the old source: it preserves the
  translated image when the upstream original is unchanged. If the new version changed or removed
  it, the recommended result follows the new version and the image remains in the review queue so
  you can deliberately keep or recreate the translation.
- Saves and local runtime state remain protected. Plugins, scripts, HTML/CSS, fonts, videos, and
  other binaries keep conservative three-way handling because they may contain localized content.
  Choosing **Keep Current** on a review row intentionally skips the new official version of that
  file; **Merge New + Local Changes** is preferred whenever it is available.

Ace and WOLF layouts are detected, but packed archive migration remains blocked until their
dedicated normalize/repack profiles are implemented.

## Translation

Manual control: pick a module, check files in `files/`, run Normal or Batch translate.
Workflow jumps here when you start a phase.

**When to use it directly**

- Re-running one stubborn file
- Engines without a full Workflow (Ren'Py, Tyrano, CSV, …)
- Resuming a batch from the Batches tab

**Example:** check only `Map003.json`, module = RPG Maker MV/MZ, click Translate, export it from Workflow Step 5, then optionally rewrap the exported game data in Step 6.

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
| `<game>/.dazedtl/version_update/` | Official baselines and Version Update reports |
