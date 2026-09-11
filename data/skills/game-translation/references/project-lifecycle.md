# Project lifecycle shared with DazedTL

Perform these phases inside the one starting prompt. Read existing artifacts first
on resume or QA. A preparation-only task completes discovery, source preservation,
Git setup, extraction and guidance, then stops before translation or injection.

## 1. Establish the source and local Git baseline

- Identify the actual engine, original release/version and current translation state.
  For fresh translation or preparation, the selected game folder is the intended
  untranslated starting original by default. Do a bounded check of that folder and
  the user's instructions for concrete contrary evidence, such as an injected
  translation or a source-version mismatch. Trust the user's identification of the
  starting original unless the actual game provides contradictory evidence.
- Normal DazedTL preparation does not invalidate that source: an enabled
  `TranslationUpdateCheck` plugin, GameUpdate files, `.dazedtl`, prepared glossaries,
  extracted data, JSON formatting and Git scaffolding do not establish that the game
  has been translated. Neither do English titles, stock UI labels or plugin metadata.
  Do not remove the updater, undo preparation, search downloads/mounts or demand a
  second copy just because these are present. Record known preparation and snapshot
  the supplied state honestly; do not claim independent vendor-archive verification.
- Preserve a recoverable backup before translation or injection. If another copy
  does not already exist, create the backup from the selected starting game yourself.
  A Git hash or ignored-asset inventory cannot restore uncommitted binaries by itself.
- Run `DAZEDTL_ROOT/scripts/len_translation.py git-status --game-root <game>`.
  Inspect existing branches, worktree state and pending operations. Preserve the
  existing translated branch and remotes; do not initialize a nested repository,
  rename branches or discard earlier work to simplify setup.
- For a fresh RPG Maker project, preserve a recoverable copy before preparation,
  then run `rpgmaker-prep --game-root <game>` through that same application script.
  This uses Workflow's dazedformat JSON formatter, plugins.js formatter, bundled
  GameUpdate copy rules, saved Config defaults and MV/MZ startup checker. Existing
  per-game patch configuration, README and ignore rules survive reinstallation.
  For MV/MZ, this command also honors the saved `install_forge` choice from Len's
  GUI (on by default), using Workflow's bundled Forge installer and saved playtest
  configuration. If preparation is already complete, `forge-setup --game-root
  <game>` applies just that choice. Unchecked means skip installation/updates,
  leaving any existing copy in place. Forge is unavailable for Ace/other engines.
  Include its referenced runtime plugin in patch scope while enabled; keep local
  Forge settings in the ignored workspace.
  Resolve preparation errors before Git setup or translation. Missing Game Update
  org/username defaults are reported; finish the per-game repository configuration
  before delivery without inventing a publication destination.
  For Ace, first complete Workflow's extraction/RV2JSON prerequisite; the command
  formats `ace_json`, or an existing export selected with `--data-path`, and skips
  MV/MZ-only plugin actions. Do not format native Marshal bytes as text.
  Keep the prepared untranslated snapshot recoverable for the subsequent baseline
  and `git-scope` source checks, separately from the pre-preparation backup.
  On resume, inspect completed preparation and repair only missing or requested
  parts; never rebuild an existing Japanese baseline from current English.
- Review `.gitignore` against the engine's actual files. The new Len Git mode keeps
  the project's rules instead of applying the RPG Maker/WOLF extension allowlist.
  Use exact paths for the intended runtime patch, plus `.gitignore`, `.gitattributes`
  and installation `README.md`; verify the proposed file list before the baseline.
  Exclude all `.dazedtl` work and guidance, unmodified artwork, unused plugins,
  engine libraries, runtime binaries, source copies, editable image sources,
  keys, saves, logs and caches.
  Include native translated files, translated runtime images and the modified or
  added plugins, fonts or other dependencies required to apply the patch.
  A file extension alone is not evidence that a file belongs in the patch.
  Include runtime dependencies introduced by tool preparation when the patched
  game references them, even if they are unchanged from the prepared backup.
  For example, an enabled updater plugin must ship with its patched registration;
  a diff against a backup that already contains that plugin will not select it.
- Preserve runtime encodings and line endings with appropriate `.gitattributes`.
  For byte-sensitive payloads, use `-text` rules; retain deliberate filter/LFS
  exceptions and confirm that checked-out files contain real usable payloads.
  The helper supplies `* -text` when no attributes file exists and keeps existing
  attributes intact. Check those existing rules against the engine before proceeding.
- Run `git-setup --game-root <game> --version <label>` through that same application
  script. Fresh tasks default to the selected folder as the original; use
  `--original <source>` only when a different untranslated source is needed.
  If resuming preparation and the current game remains untranslated, the agent can
  add `--current-is-untranslated` after checking that fact; the task label alone does
  not establish that translation occurred. An actual translated game without a
  suitable baseline still needs an untranslated source. Never call a known
  translation the original merely to bypass this requirement.
  Use a verified release label; when none exists, `initial-unversioned` labels a
  snapshot without inventing an official version number.
- The helper creates `original` and the translated branch using the shared
  version-update backend. New repositories use `main`; existing branch names are
  preserved. Existing complete baselines are reused. Native bytes and the chosen
  ignore policy are retained. The byte-preservation policy also travels in commit
  trailers so a clone's official-update path cannot silently start normalizing text.
- A refusal describes a prerequisite to resolve. For an existing dirty or unborn
  repository, inspect the diff and make a reviewed initial checkpoint before
  reconciliation. Ask for another original only when concrete evidence or the user
  establishes that the selected game cannot serve as the requested untranslated
  starting source. Do not ask the user to reconfirm a source they already identified.
  Do not force-reset, discard changes or fabricate a baseline.
- Verify baseline commit IDs, the current translated branch and the actual tracked
  game files. Keep unrelated staged changes untouched. Local checkpoints are part
  of this task; creating remotes, pushing or publishing is a separate user action.

## 2. Preserve work that can be resumed

The handoff identifies `.dazedtl/len-method/work/` as the default location for authored tools, translated text records, image sources, research and QA notes.
All `.dazedtl` files are local and ignored on both `main` and `original`, including glossary, settings, `project.json`, `progress.json` and `status.md`.
Preserve these records and maintain separate workspace backups; the patch repository does not protect ignored files.
Export database-backed translations to stable JSONL/JSON/CSV records there for recovery and review.
Keep existing project-local adaptations and do not delete working files while removing them from Git tracking.
Do not force-add work records to either game branch.

### Align both branches before patch checkpoints

First inject the reviewed runtime outputs into the selected game folder and verify their hashes.
A translation present only in staging or an isolated QA game is not present in `main`.
Create a complete list of the patch's runtime file paths in the ignored workspace, then run:

```bash
python DAZEDTL_ROOT/scripts/len_translation.py git-scope \
  --game-root <game> --manifest <patch-files.json> \
  --original <matching-untranslated-backup> --dry-run
python DAZEDTL_ROOT/scripts/len_translation.py git-scope \
  --game-root <game> --manifest <patch-files.json> \
  --original <matching-untranslated-backup>
```

The manifest is a JSON list of exact relative paths, or an object with `files` mapping paths to records.
A record can bind `sha256` and `original_sha256`; use `original_sha256: null` only for a genuine translation-only addition.
Include the whole patch, not just the latest batch.
Repository metadata (`.gitignore`, `.gitattributes`, installation `README.md`) is handled separately.
A source backup is needed for a newly included original that the `original` branch does not already protect.
Existing original blobs must match any supplied backup; a different game release belongs in Version Update.
Never use current English bytes to fill a missing original.

The command stages the exact patch and removes unrelated files only from Git's index, preserving local files.
It appends a scope commit to `original` with the corresponding untranslated originals and shared repository metadata.
Translation-only additions exist on the translation branch only.
This retains history and aligns the ignored-asset inventory for official updates.
It does not commit `main`, check out branches, inject translations, push or publish.
Resolve existing staged changes deliberately, review `git diff --cached`, then commit the reviewed patch on the registered translation branch as part of the authorized local checkpoint.
Never merge `main` into `original` or cherry-pick translation commits there.
Verify both branch file lists, original bytes and delivered translation bytes after scope changes and official updates.
Record checkpoint commits and artifact paths in local `status.md` and its workspace backup.
Use the repository's configured identity; the backend's per-command tool identity is available when none exists.
Do not invent a user identity or change global Git settings.

## 3. Extract, investigate and establish guidance

Use the engine-specific playbook and reviewed source corpus. Run the shared `setup.md`
phase to prepare the glossary, game frame and quirks. Read all user-specified prequel
corpora and follow `reference-translations.md`; keep their source folders read-only.
For RPG Maker, `setup.md` is the same engine-specific setup and investigation prompt
used by Workflow, including speaker analysis and wrapping. Collect source names in
the selected direct/API mode; the direct route does not authorize paid name collection.
Check extraction coverage independently of the extractor. Preserve uncertainty,
placeholder/control-code contracts and reveal-sensitive identities.

The setup phase's guidance-only edit boundary ends when that phase is complete.
Continue into the selected task automatically; do not ask for another setup prompt.

## 4. Translate and resume from verified artifacts

Before relying on an exclusion list, reconcile it with prior reviews, retractions and user corrections using `review-decisions.md`.
Do not suppress previously accepted work from a rationale already withdrawn unless new source evidence supports that change.
Propagate a reviewed scope correction through batch selection, injection, QA, progress and delivery together.

Follow `progress-reporting.md` from the first measured corpus onward. Export current
saved units, including unfinished occurrences, and call the live `progress-update`
helper after saved batches and milestones and before a pause/handoff. Report the
current phase, short blocker and next action; keep detailed history in `status.md`.
Revalidate source/output fingerprints and downstream phase checkpoints before
refreshing stale progress. Resuming or copying another prompt must preserve the
last report rather than resetting it or inventing an overall completion percentage.

Consume per-batch context from the live compiler, retaining source/context fingerprints
and stable IDs with results. Confirm provider/model/budget only when API mode needs
information the user has not supplied. Keep credentials out of project artifacts.
Revalidate saved results after guidance or source changes. Correct missing, malformed
or stale outputs before injection; a populated cache does not prove valid translation.

For dialogue, extract and retain a source speaker for each unit. Use the engine's
nameplates/markup and resolved actor names; respect message-block and scene boundaries.
Preserve source-visible aliases and anonymous labels instead of substituting an
internal identity or a name revealed later in the story.
Leave unidentified speakers null rather than assigning the last named character or
guessing from gender/register. Supply `--speakers` alongside `--sources`, with exactly
the same IDs or list positions, during every dialogue-context compilation. Both files
must come from the same reviewed batch snapshot. The user need not build this mapping.

The compiled `user` field includes the speaker map as context only; send it intact.
The glossary includes current speakers' character notes even if their names never
appear in the dialogue. The source strings, SFX matching and exact reference matching
remain based on the text to translate. Return only the required translations, without
extra metadata fields or invented name prefixes. Separate nameplates are translated
as separate units, using the curated glossary and `names.speaker` template as appropriate.
Speaker changes alter the request fingerprint: preserve per-occurrence IDs and do not
reuse a translation solely because another speaker says the same Japanese text.

## 5. Inject, validate and deliver

Capture exact source before the first live write. MV/MZ map and database JSON must
carry Workflow-compatible `_original` metadata even when translations also live in
a separate store. Follow `engine-rpgmaker.md`'s preservation procedure: stage the
injector's output, then call `DAZEDTL_ROOT/scripts/len_translation.py
write-rpgmaker-json --source <matching source> --translated <staged JSON> --output
<game JSON>` for every changed file. The historical injectors need this adaptation.
Retain existing originals through correction and rewrapping; validate the final
source/live bindings with the shared QA manifest and independent verifier.
Do not backfill missing Japanese from an already translated live value. Recover it
from the matching baseline/store and verify IDs and source hashes first.
For formats that cannot store `_original`, keep sidecars in the separately backed-up `work/` directory
with file/unit IDs, exact source, final live text, source hashes and injection
bindings. Validate these against the shipped payload without adding unsupported
keys to native containers. A Git baseline or store alone does not establish that
the final injected text still maps to the correct source.

Apply reviewed output with the engine's appropriate injector or patcher. Check source
coverage, placeholders, layout, fonts, runtime-generated labels and images in scope.
Report actual playtested scenes separately from static checks. Mark unavailable runtime
verification pending instead of treating it as passed.
Check speaker-to-line binding and the final restored nameplates as well as dialogue
bodies; metadata separated from a text unit must not disappear from injection QA.

Use the engine-compatible delivery route: GameUpdate where the project supports it,
otherwise the reference pipeline's validated patch/install/restore procedure. Verify
the actual packaged payload, repeat installation and recovery path, and record any
remaining checks. A Git baseline does not make every native-engine package compatible
with every updater. Keep remote publication outside the local translation task.

For later official releases, use the shared Version Update workflow and
`version-updates.md`, preserving the recorded byte policy. Keep localization of new
content separate from the official-file update and carry forward existing guidance.
