# Len’s Method integration

Len’s Method uses the same project guidance as Workflow while an external coding assistant
runs Len’s extraction, translation, fitting, injection and QA playbook. The tab supports
preparation, full translation, continuation and QA, with direct translation or a selected
API. Image translation defaults to included. Choose the game and scope, click **Copy starting
prompt**, and paste it into the coding assistant with the game folder open. That single action
prepares or refreshes the workspace and copies the full handoff; it makes no API calls.
The assistant performs source preservation, local Git setup, investigation, translation
and validated checkpoints as phases of the selected task. Copying the prompt itself
prepares instructions and workspace files; Git operations run when the assistant starts.

## Local Git and resumable work

The starting prompt records the supplied untranslated starting state before translation.
The CLI uses Workflow's Git backend to create `original` and the translated branch,
or reuse existing baselines and branch names:

```bash
python scripts/len_translation.py git-status --game-root '/path/to/game'
python scripts/len_translation.py git-setup --game-root '/path/to/game' --version '1.00'
```

For fresh tasks, the selected game folder is the original by default. Normal DazedTL
preparation—an enabled `TranslationUpdateCheck` plugin, GameUpdate files, generated
guidance, extraction or formatting—is not evidence that translation has occurred.
The assistant records those additions, keeps them intact and creates a backup from the
selected folder when needed. It does not require a pre-existing second copy or claim
that a prepared snapshot is byte-identical to a separately verified vendor archive.

When continuing preparation on a still-untranslated game, the assistant can use
`--current-is-untranslated`. Actual translated games without a suitable baseline need
`--original '/path/to/untranslated-source'`. The assistant checks for concrete evidence
of prior injected translation or an unsuitable source, rather than treating every
tool-generated file or English label as a reason to reject the selected folder. Setup
refuses ambiguous parent repositories, unfinished Git operations, wrong branches and
dirty reconciliation. It leaves existing staged and working changes for deliberate
review and checkpointing. It does not create remotes or push.

New Len baselines preserve native encodings, line endings and JSON layout. They keep the
project's reviewed ignore policy instead of installing Workflow's extension allowlist.
When `.gitattributes` is missing, setup adds a byte-preserving default; existing rules
are retained for review. A clone can reuse an unambiguous existing remote-tracking
`original` ref without fetching or pushing.
The policy is stored in local Git configuration and commit trailers, so shared update
previews and official updates keep it after cloning. Existing complete repositories are
reused with their established policy. Review `.gitattributes` and the actual tracked
payload before relying on a baseline; Git does not replace an untouched source copy.

Authored scripts, translation records and QA notes belong under
`.dazedtl/len-method/work/` or existing versioned project folders. The work directory's
text/source allowlist, `project.json` and `status.md` are eligible for Git. Generated
context, handoff files, provider state and caches remain local. Export database-backed
translations into stable text records for checkpoints; extend the work allowlist when
an intended authored format is missing. Existing work rules and legacy adaptations are
preserved. The assistant records reviewed milestone commits and verifies saved artifacts
before resuming.

**Git version tracking** under **Optional: project tools and references** opens the
existing Version Update page for the selected Len game, including native-byte setup.
It does not select an unrelated Workflow game. The reference lifecycle also covers
independent extraction coverage, current context on resume, engine-compatible packaging
and explicit pending status for runtime checks that could not be performed.

## Shared project context

The game’s existing portable files remain authoritative:

- `.dazedtl/glossary.txt`: approved names, terms, identity and individual character voices.
- `.dazedtl/skills/game.md`: compact game frame.
- `.dazedtl/skills/quirks.md`: cross-cutting voice and recurring motifs.
- Other `.dazedtl/skills/*.md`: custom instructions.
- The existing reference-game registry: advisory translations from earlier games.

Under **Optional: project tools and references**, **Review glossary & skills** opens the
same editor used for generic Translation context, with its separate setup-prompt action hidden.
**Reference translations** registers paired Japanese/English JSON folders or DazedTL JSON
with `_original` fields in the same registry as Workflow. For another engine, first extract
corresponding JSON structures; raw proprietary archives cannot serve as reference folders.
The starting prompt directs the assistant to perform generic discovery and the shared
localization investigation. It creates missing guidance and preserves valid existing decisions;
the user does not need to copy files between tabs or supply another setup prompt.
Both setup routes include whole-corpus identity coverage, unknown gender and reveal-sensitive
alias rules. Glossary ownership stays separate from the game frame and research notes.

To inherit vocabulary from several prequels, name their folders (or one prepared corpus
folder) in **Instructions** before copying the starting prompt. For example:

> Use the prequel translations in /path/to/series-corpus as terminology references.
> Inspect all specified games, reuse established names and terms where the current
> Japanese supports the same meaning, and write the verified decisions into this
> game's shared glossary. Record conflicting spellings with their source games and
> resolve them against current context and my curated guidance. Keep the references
> read-only and register supported aligned pairs for exact-source matches.

The assistant handles discovery, terminology review and registration within the same
task. The reference dialog is optional. Curated terms in the shared glossary also apply
inside new dialogue that has no complete-line match in any prequel. The shipped
`references/reference-translations.md` explains prebuilt corpus formats and provenance.

Each game’s `.dazedtl/len-method/` contains:

- `project.json`: versioned scope settings, restored when reopening the game.
- `setup.md`: current shared setup and investigation instructions.
- `context.json`: current assembled system prompt, glossary and reference registry.
- `handoff.md`: scoped instructions and paths for the coding assistant.
- `status.md`: assistant-written progress and evidence; prompt preparation never overwrites it.
- `work/`: versioned authored tools, translation records and QA/provenance notes.
- Any project-specific tools, extraction stores, research and translation outputs.

Copy refreshes shared guidance from disk. Moving a game and copying its starting prompt again
regenerates absolute handoff paths. Existing project-local skill copies and adapted tools
from the first integration remain untouched; the handoff points to the maintained app skill.

## Context compiler and glossary import

From the application folder:

```bash
python scripts/len_translation.py prepare --game-root '/path/to/game'
python scripts/len_translation.py context --game-root '/path/to/game'
python scripts/len_translation.py context --game-root '/path/to/game' \
  --sources '/path/to/sources.json' --output '/path/to/request-context.json'
python scripts/len_translation.py import-glossary --game-root '/path/to/game' \
  --input '/path/to/reviewed-glossary.json'
```

`sources.json` is a nonempty list of Japanese strings or an object mapping stable string IDs
to Japanese strings. Each batch is compiled using the current shared system loader,
`createContextParts` glossary/SFX matching, and exact source matches from the reference index.
Optional `--instruction-key section.key` selects a shared field template; `--source-context`
reads a UTF-8 text file of preceding untranslated Japanese and fills contextual templates.
The generated JSON separates system, glossary, SFX, request instructions, source context,
source payload and reference translations. It contains no credentials.

Direct translation and adapted API drivers must consume those fields, retain their own
required output schema, and store the request fingerprint with results. Recompile before
reusing results after guidance changes. Fingerprints expose changes; the compiler does not
operate a provider queue or enforce reuse decisions inside historical example drivers.

The importer accepts Len’s `names` entries with `en`, or legacy `characters` entries with
`name`, plus string-valued `terms`. Identity, register and evidence notes stay with names.
Aliases with separate named entries keep their own spellings. Optional `do_not_merge` name
pairs prevent importing a protected alias without its own entry. Existing equal decisions
and notes are preserved; conflicting source spellings or aliases abort the entire merge.
`do_not_translate` remains extraction metadata in the archived input, never prompt rows.
All subsequent edits belong in the shared glossary. The shipped `build_vocab.py` forwards
to this importer and no longer writes the obsolete application-root `vocab.txt`.

## Maintained sources and updates

`data/skills/game-translation/` contains the skill, references and supplied reusable Len tools
as ordinary versioned files. There is no nested skill ZIP or per-project installation step.
The supplied frozen DazedTL extract is replaced by references to live application code.
`DAZEDTL_ROOT` means the current application folder. App updates refresh these maintained
sources; project adaptations belong in the project workspace and are preserved.

The source package was supplied as Len TL Tools and imported on 2026-09-07. Its reference
pipelines retain provenance and license files. Python caches, environment files, a captured
game snapshot and the duplicated DazedTL tree are excluded. Historical paths, manifests and
example prompts must be adapted to the current game and shared context contract. Copy needed
tools before modifying them or running scripts that write beside themselves. Dependencies
are documented in `tools/THIRD-PARTY.md`; preparation does not download them.

Validate the source layout with:

```bash
python data/skills/game-translation/scripts/check_tools.py
```

The check distinguishes shipped Len tools, live DazedTL modules and optional dependencies.
The app’s bundled-asset regression covers Git ignore rules and update installation eligibility.
Sources must be committed to be included in branch archives.

The skill's own `.gitignore` applies after the app's broad shipped-data exceptions.
It excludes generated reports, extracted game text, rendered replacements, local state,
dependency installs and rebuildable Bakin outputs. Reusable source, example configuration,
licenses, curated evidence and required binary inputs remain eligible for Git. See the
skill's `README.md` for the retained assets and per-project regeneration requirements.
The exclusion rules leave local copies in place; they do not delete previous work.

## Completion and QA

Translation runs in the coding assistant or its adapted driver. The tab displays the
assistant’s report; it does not independently certify completion. Keep measured string
coverage, image coverage, placeholder/layout checks, injection checks and actual playtested
scenes separate. Unavailable runtime verification remains pending. A successful preparation
or a complete string count is insufficient evidence for a finished game or release.
