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
- Review `.gitignore` against the engine's actual files. The new Len Git mode keeps
  the project's rules instead of applying the RPG Maker/WOLF extension allowlist.
  Include required game text and intended patch inputs. Exclude keys, saves, logs,
  caches and bulk source assets that have a separate recoverable backup. Verify
  the proposed tracked file list before recording a baseline.
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

The handoff identifies `.dazedtl/len-method/work/` as the default location for
authored tools, translated text records and QA notes. Its text/source allowlist,
`project.json` and `status.md` are eligible for Git. Read existing project rules and
extend that allowlist when a required authored format is missing. Check that secrets
and runtime caches remain excluded. Existing versioned project folders are also valid.

Generated handoff/setup/context files, raw source snapshots, provider state and caches
outside `work/` stay local. Export completed translations from SQLite or similar
working stores to stable JSONL/JSON/CSV records under `work/` so Git protects them.
Preserve old project-local adaptations; move or copy useful authored work deliberately.
Record milestone commits and artifact paths in `status.md`. Checkpoint small reviewed
changes after validation, using explicit paths rather than indiscriminate staging.
Use the repository's configured identity. If none exists, automatic checkpoints may
use the backend's per-command tool identity (`DazedMTLTool`, `local@dazedmtl.invalid`);
do not invent a user identity or change global Git settings.

## 3. Extract, investigate and establish guidance

Use the engine-specific playbook and reviewed source corpus. Run the shared `setup.md`
phase to prepare the glossary, game frame and quirks. Read all user-specified prequel
corpora and follow `reference-translations.md`; keep their source folders read-only.
Check extraction coverage independently of the extractor. Preserve uncertainty,
placeholder/control-code contracts and reveal-sensitive identities.

The setup phase's guidance-only edit boundary ends when that phase is complete.
Continue into the selected task automatically; do not ask for another setup prompt.

## 4. Translate and resume from verified artifacts

Consume per-batch context from the live compiler, retaining source/context fingerprints
and stable IDs with results. Confirm provider/model/budget only when API mode needs
information the user has not supplied. Keep credentials out of project artifacts.
Revalidate saved results after guidance or source changes. Correct missing, malformed
or stale outputs before injection; a populated cache does not prove valid translation.

## 5. Inject, validate and deliver

Apply reviewed output with the engine's appropriate injector or patcher. Check source
coverage, placeholders, layout, fonts, runtime-generated labels and images in scope.
Report actual playtested scenes separately from static checks. Mark unavailable runtime
verification pending instead of treating it as passed.

Use the engine-compatible delivery route: GameUpdate where the project supports it,
otherwise the reference pipeline's validated patch/install/restore procedure. Verify
the actual packaged payload, repeat installation and recovery path, and record any
remaining checks. A Git baseline does not make every native-engine package compatible
with every updater. Keep remote publication outside the local translation task.

For later official releases, use the shared Version Update workflow and
`version-updates.md`, preserving the recorded byte policy. Keep localization of new
content separate from the official-file update and carry forward existing guidance.
