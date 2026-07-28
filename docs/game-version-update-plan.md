# Game Version Update Plan

## Goal

Add a dedicated **Version Update** page to the main sidebar that updates an
existing translated game from one official game version to another while:

- preserving translations and translator-added files when their official source
  did not change;
- importing every new upstream file, including plugins, images, audio, movies,
  fonts, executables, and other engine assets;
- identifying files changed by both the developer and translator instead of
  silently choosing one copy;
- semantically migrating supported game data so only new or changed source text
  needs translation;
- producing a reviewable plan before any files are written; and
- supporting a staged updated copy by default, with a transactional in-place
  update as an advanced option.

The success result should be understandable without Git, for example:

> Updated My Game from v1.00 to v1.03. Preserved 4,812 translated entries,
> imported 137 upstream files, and left 23 entries ready for translation.

Git remains recommended for history and an additional recovery layer, but it is
not required by the update engine.

## Product and naming decision

Use **Version Update** for the sidebar label and feature name. The repository's
existing `gameupdate/` feature distributes translation patches to players; it
does not migrate a translator's project between official game versions. Keeping
the names distinct prevents the two workflows from being confused.

Add the new page near Workflow and Images in the main sidebar:

1. Guide
2. Workflow
3. Images
4. Version Update
5. Translation
6. Batches
7. Skills
8. Configuration

The page should live in `gui/version_update_tab.py`. The update engine and data
models should live below `util/version_update/` so scanning, planning, applying,
and testing do not depend on Qt.

## Is it engine agnostic?

The feature should use a shared, engine-agnostic update core with engine
profiles layered on top.

The shared core can safely handle every loose file using relative paths and
content hashes. It owns:

- recursive file inventory;
- source-baseline manifests;
- new, changed, deleted, and unchanged file classification;
- generic text three-way merging;
- binary conflict handling;
- staging, backups, apply, rollback, and reporting; and
- user resolution choices.

An engine profile owns operations that cannot be inferred safely from files
alone:

- detection and confidence evidence;
- ignored runtime/user-data paths;
- packed archive extraction and rebuilding;
- structured data identities and semantic merging;
- engine-specific validation; and
- links to the correct translation and image review workflows.

Therefore engine detection is required for semantic migration, but not for the
basic file-level update. Unknown loose-file games can use **Generic / Files
Only** mode. Packed or encrypted formats must never be treated as generic when
doing so would produce an invalid game.

Initial profiles:

| Profile | Initial capability |
|---|---|
| RPG Maker MV/MZ | Full loose-file update plus semantic JSON migration |
| Generic / Files Only | Safe hash-based loose-file reconciliation |
| RPG Maker Ace | Detection initially; full support after RV2JSON normalization is added |
| WOLF RPG | Detection initially; full support after archive/layout normalization is added |

Auto-detection should reuse and extend `util.project_scanner`. The UI must show
the detected profile, supporting evidence, confidence, and a manual override.
If the current and new folders detect as different engines, applying the update
is blocked unless a profile explicitly supports that migration.

## Required states and inputs

A correct update is a three-way comparison:

```text
O = old official source
T = current translated game based on O
N = new official source

update(O, T, N) -> updated translated game U
```

The page should ask for:

1. **Current translated game** (`T`).
2. **New official game** (`N`).
3. **Old version label** and **new version label**. Labels are for history and
   display; correctness comes from file content, not the label.
4. **Old official game** (`O`) only when the translated project has no saved
   baseline.
5. Output mode and destination.

After a project has been registered once, normal updates require only the
current translated folder and new official folder. The saved baseline supplies
`O`. RPG Maker `_original` values help with translated fields, but are not a
complete baseline for plugins, binaries, media, and untranslated files.

Version labels alone cannot update a game unless a future downloader integration
can securely acquire those official builds.

## Project baseline

Store project-local metadata below:

```text
<translated-game>/.dazedtl/version_update/
    project.json
    baselines/<source-fingerprint>/manifest.json
    baselines/<source-fingerprint>/mergeable/<relative source files>
    runs/<run-id>/plan.json
    runs/<run-id>/report.json
    backups/<run-id>/<replaced or deleted files>
```

The baseline manifest records at least:

- schema version;
- engine profile and detection evidence;
- user-supplied version label;
- normalized relative path;
- SHA-256, size, and file kind;
- whether the path is mergeable, protected local data, or ignored; and
- the overall source fingerprint.

Only files that may need semantic or text three-way merging need their old
contents saved under `mergeable/`. Hashes are sufficient for large binary files
such as audio, video, images, and executables. This avoids duplicating an entire
game merely to retain its baseline.

The baseline is advanced from `O` to `N` only after a successful apply. A failed
or cancelled run must leave the active version and baseline unchanged.
Retained manifests and mergeable source files are path-validated, fingerprinted,
and rehashed before use. Outputs keep the newest eight reports plus every baseline
referenced by those reports; older unreferenced history is pruned.

## Whole-folder reconciliation rules

Inventory `O`, `T`, and `N` by normalized game-relative path. Ignore timestamps;
use content hashes. Apply the following rules to every file, regardless of
engine or extension:

| Old `O` | Translated `T` | New `N` | Default result |
|---|---|---|---|
| Same | Same | Same | Keep the file |
| Same | Translator changed | Same | Preserve `T` |
| Same | Same | Upstream changed | Take `N` |
| Same | Translator changed | Upstream changed | Semantic merge or conflict |
| Missing | Translator added | Missing | Preserve translator-added file |
| Missing | Missing | Upstream added | Copy new upstream file |
| Present | Unchanged | Deleted | Delete it |
| Present | Translator changed | Deleted | Conflict; preserve a recovery copy |

Additional rules:

- Files under `.dazedtl/`, save folders, logs, caches, screenshots, and other
  profile-defined local state do not participate as official source content.
- Case-only and Unicode-normalization path collisions must be detected before
  writing, especially for Windows destinations.
- Symlinks are inventoried but never followed outside a selected root.
- A translator-added file that collides with a new upstream file is a conflict.
- Renames may be suggested using matching hashes, but path changes should not be
  assumed when more than one candidate exists.

## Structured translation migration

When both `T` and `N` changed a structured data file, the engine profile receives
`O`, `T`, and `N` and returns merged content plus decisions and conflicts.

For RPG Maker MV/MZ, the first semantic adapter should support:

- database entries matched by file, RPG Maker ID, and field;
- `System.json` fields matched by semantic JSON path;
- maps matched by map file and event ID;
- common events and troops matched by database ID;
- event pages aligned structurally;
- dialogue handled as blocks rather than individual code-401 lines;
- event commands aligned by code, indent, non-text parameters, and neighboring
  commands; and
- choices, name windows, scrolling text, plugin commands, and other currently
  supported translatable fields.

For each translatable segment:

| Source comparison | Migration result |
|---|---|
| `N source == O source` | Preserve the exact visible value from `T` and retain its manual edits |
| `N source != O source` | Use the new source, update `_original`, and mark it for translation |
| New source segment | Copy it from `N` and mark it for translation |
| Deleted source segment | Remove it |
| Exact approved translation-memory match | Reuse after validation and record the reuse |
| Ambiguous structural match | Require review; do not guess |

Non-translatable structure and parameters always follow `N`, except for
explicitly recognized translator metadata such as `_original`.

## Plugins and other text/code files

Plugins are ordinary files for inventory but require special conflict policy:

- A new plugin file is copied from `N`.
- An unchanged official plugin with translator edits keeps `T`.
- An upstream-changed plugin with no translator edits takes `N`.
- A plugin changed by both sides receives a standard three-way text merge when
  all three versions decode safely as text.
- RPG Maker MV/MZ `js/plugins.js` is decoded and merged by plugin name. New
  official ordering and settings win, safe nested parameter translations are
  retained, and genuinely translator-added plugin entries are appended.
- A clean text merge is still listed for review because syntactically separate
  edits may be behaviorally incompatible.
- Merge markers are never written into the runnable output.
- An overlapping plugin-code conflict defaults to **Use new** so the complete
  update remains runnable, and is placed in the translation-at-risk queue. The
  user can choose **Keep current** or supply a manually reviewed merged file.

Individual `js/plugins/*.js` files, Ace Ruby scripts, Ren'Py scripts,
configuration files, and other profile-declared text files use the conservative
text path. Later engine adapters may provide syntax-aware merging for visible
string literals.

## Images, audio, video, fonts, and other binaries

Binary files use the same three-way hashes:

- If the official binary is unchanged, retain the translated or modified `T`.
- If only upstream changed, take `N`.
- If upstream added it, copy it automatically.
- If both translator and upstream changed it, create a binary conflict.
- If upstream deleted a translator-modified binary, remove it from the proposed
  runtime output but keep its translated copy in the run's recovery area until
  the user confirms the resolution.

Binary conflicts cannot be merged automatically. The default safe resolution is
**Use new official and send old translated asset to review**, because silently
keeping an outdated asset can break dimensions, duration, encoding, or runtime
references.

For image conflicts, offer **Open in Images** after the update so the existing
Image Manager can make the new official image editable and the translator can
reapply or recreate its translation. Audio and video conflicts remain manual
until dedicated managers exist.

New media must be copied even when it contains no translatable content. This is
why the feature scans the entire game root rather than only RPG Maker `data/`.

## Executables, DLLs, archives, and engine runtime files

Executables, DLLs, engine runtime libraries, and packed archives are treated as
binary files. The new official version wins when the translator did not modify
them. A both-changed result defaults to the new official file and is listed as
a local-change risk rather than silently preserving an outdated runtime file.

Packed engines require normalization through a profile:

- WOLF must compare compatible unpacked layouts, then rebuild or leave loose
  data according to an explicit output option.
- RPG Maker Ace must use RV2JSON to compare mergeable data and scripts, then
  rebuild `rvdata2` files.
- Unknown packed archives are copied only when unmodified by the translator;
  they are never unpacked or repacked generically.

## Version Update page workflow

### 1. Select

- Current translated game folder.
- New official game folder.
- Old official folder when baseline metadata is unavailable, with read-only
  fallback to a local Git `original` or `origin/original` branch.
- Old and new version labels.
- Auto-detected engine/profile with manual override.

### 2. Scan

Scanning is read-only and runs outside the UI thread. It performs:

- root and engine validation;
- baseline validation;
- Git old-source discovery/export without checkout or worktree mutation;
- full file inventory and hashes;
- canonical JSON comparison that ignores formatting-only differences;
- exclusion of VCS/tool metadata from game decisions;
- new-official authority for audio and images not marked as translated;
- image-manager backup baselines for accurate translated-image decisions;
- semantic scans for supported files;
- disk-space and destination preflight; and
- construction of a deterministic update plan.
- byte-for-byte validation of every staged decision and a second parse of supported
  RPG Maker JSON before the staged folder can be published.

### 3. Review

Show summary counters and a filterable tree grouped by:

- Preserved translations
- New upstream files
- Upstream-only changes
- New/changed text to translate
- Clean text merges requiring review
- Translation-at-risk files that default to new official
- Deleted files
- Translator-added files
- Protected local/user data
- Unsupported or blocking items

The default filter is **Needs review**. Each row shows its relative path, file
kind, decision reason, proposed action, and current recommendation. Review rows
provide **Use New (drop local file changes)**, **Keep Current (skip this new
file)**, **Merge New + Local Changes**, and a manually merged-file option.
Multiple rows can be selected for a bulk override.

The update plan should be exportable as JSON and a readable text/Markdown
report. Normal both-changed files receive upstream-first defaults, so they do
not block staging. Applying remains disabled for failed validation or a case
where no safe output choice can be produced.

### 4. Apply

Offer two modes:

1. **Create updated copy (recommended):** build a sibling/output folder without
   changing either input. The output includes the new baseline and run report.
2. **Update current folder in place (advanced):** stage all output first, back
   up the complete previous translated folder, apply with a same-volume folder
   swap, and roll back automatically if the swap fails.

An in-place run must preflight free disk space, write permission, path safety,
and whether current inputs changed since the scan. If any source hash no longer
matches the plan, require a rescan.

### 5. Finish

After a successful apply:

- store `N` as the new official baseline;
- record the old and new labels and source fingerprints;
- show the `Updated from v1.00 to v1.03` result;
- offer **Translate changed text**, **Open image conflicts**, **Open output
  folder**, **View report**, and **Rollback** when applicable; and
- leave Git commit/tag creation as a later optional integration.

## Translation-memory integration

The existing exact payload cache is useful within a run but is too coarse for
version migration. Add a per-game segment-level translation memory in a later
phase. Each entry should include:

- source and target text;
- target language;
- semantic location and nearby context;
- engine/profile;
- control-code signature;
- manual or AI provenance;
- model/prompt metadata when applicable; and
- approval state.

The visible value in `T` is always authoritative for an unchanged source,
including manual edits made after AI translation. Translation memory is used for
new or moved exact matches only after control-code and content validation.
Source-only matches from a different context should be suggestions unless the
user enables an explicit broader reuse policy.

## Safety and recovery requirements

- Merely opening the page, selecting folders, or scanning never writes files.
- The current and new official folders cannot be the same path or nested in the
  output/staging directory.
- Inputs are re-hashed before apply to prevent stale-plan writes.
- Writes stay inside explicit staging, output, backup, and destination roots.
- Symlink escapes and path traversal are rejected.
- No unresolved conflict markers enter a runnable text file.
- Backups retain original relative paths and a manifest sufficient for rollback.
- Cancellation during scan is harmless; cancellation during apply completes or
  rolls back the active atomic step and leaves a resumable journal.
- The active baseline/version changes only when the full transaction succeeds.
- Update reports must never contain API keys or unrelated local file contents.

## Delivery phases

### Phase 1 - Shared models, baseline, and generic scanner

- Add immutable inventory, manifest, decision, conflict, plan, and report models.
- Add safe recursive hashing and path normalization.
- Add project registration and baseline storage.
- Implement generic three-way file classification.
- Cover additions, deletions, translator-only files, collisions, and binary
  conflicts with unit tests.

### Phase 2 - RPG Maker MV/MZ semantic adapter

- Reuse project detection and translatable-field knowledge from the existing
  RPG Maker module.
- Implement database, System, map, common-event, troop, event-command, and
  dialogue-block migration.
- Preserve visible translations and `_original` correctly.
- Produce new/changed/ambiguous segment reports without calling an AI model.

### Phase 3 - Version Update sidebar page

- Add the sidebar page and page index wiring in `gui/main.py`.
- Implement Select, Scan, Review, Apply, and Finish states.
- Add a background scan worker, progress, cancellation, filters, resolution
  controls, and report export.
- Initially expose only **Create updated copy** until transactional apply is
  complete.

### Phase 4 - Transactional in-place apply

- Add staging, backup manifest, transaction journal, atomic replacements,
  deletion handling, stale-plan detection, rollback, and recovery UI.
- Add failure-injection tests proving the original folder is restored.

### Phase 5 - Selective translation and asset handoff

- Send only new/changed segments into the existing Translation workflow.
- Add per-game segment translation memory and reuse statistics.
- Hand image conflicts to the Images page with the new official assets selected.
- Persist review status across sessions.

### Phase 6 - Additional engine profiles

- Add WOLF normalization through its existing unpack/inject/repack tooling.
- Add RPG Maker Ace normalization through RV2JSON.
- Add profile contracts for other loose-script engines.
- Keep Generic / Files Only available when semantic support is absent.

### Phase 7 - Optional Git integration

- Accept Git refs/tags as alternatives to folders.
- Offer a version-update branch and commit after a successful apply.
- Record source fingerprints and version labels in commit metadata.
- Consider exposing the semantic merger as a Git merge driver only after the
  standalone workflow is stable.

## Test strategy

At minimum, automated fixtures must cover:

- unchanged translation preservation, including manual edits;
- upstream-only and translator-only text/binary changes;
- both-changed JSON, plugin, image, and audio files;
- new and deleted files at every folder depth;
- translator-added files colliding with newly added upstream files;
- map event insertion, deletion, page changes, and command reordering;
- dialogue line-count and wrapping differences;
- `_original` migration and changed-source invalidation;
- Windows case collisions and Unicode-normalized collisions;
- symlink/path traversal rejection;
- source changes between scan and apply;
- insufficient disk space and unwritable destinations;
- apply interruption and complete rollback;
- packed-engine refusal when no safe adapter exists; and
- deterministic plans and idempotent rescans.

Use small synthetic fixtures for unit coverage and sanitized real-layout fixtures
for MV/MZ integration coverage. No test should require a network connection or
AI API call.

## First-release scope

The first usable release should include:

- the Version Update sidebar page;
- project registration with an old official baseline;
- current translated + new official folder inputs;
- Generic / Files Only whole-folder scanning;
- RPG Maker MV/MZ semantic JSON migration;
- complete handling of new plugins and media through whole-folder copy rules;
- text/plugin and binary conflict reporting;
- a filterable dry-run review;
- **Create updated copy** output; and
- a clear list of text and assets requiring follow-up translation.

In-place automatic updating, WOLF/Ace semantic migration, segment-level
translation memory, and Git automation should follow after the staged-copy path
has proven safe.

## Definition of done

- A translated RPG Maker MV/MZ v1.00 folder and clean official v1.03 folder can
  produce a runnable staged v1.03 translation without modifying either input.
- Every file in the new official version is either copied, semantically merged,
  deliberately superseded by an unchanged-source translation, or reported as a
  visible conflict.
- Unchanged translated text and manually edited translations are preserved
  exactly.
- New or changed source text is identifiable and can be sent to Translation
  without retranslating the rest of the game.
- New plugins, images, audio, video, fonts, and runtime files are not omitted.
- Both-changed binaries and unresolved plugin merges are never silently chosen.
- The report explains every nontrivial decision and includes old/new source
  fingerprints and version labels.
- Existing Workflow, Images, Translation, GameUpdate, RPG Maker, and WOLF tests
  continue to pass.
