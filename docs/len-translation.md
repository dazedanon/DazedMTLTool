# Len’s Method integration

Len’s Method shares Workflow's project guidance while a coding assistant carries out extraction, translation, fitting, injection and QA.
Choose the game, task, image scope and translation mode before copying a prompt.
**Agent / Sub Direct Translation** uses the coding assistant's access and plan limits, with no DazedTL translation API calls.
The mode name does not itself authorize delegation.
**API Batch Translation** uses the app's existing API Settings and supported Batch backend.

API mode has a separate preflight card with **API Settings**, **Estimate prepared requests** and **Batch history**.
If no complete source request plan exists, choose preparation only, run that prompt in the assistant and return to Len's Method for a quote.
Preparation extracts and compiles locally; it does not call a translation provider.
An unavailable quote is not a $0 price.
The quote shows model/provider, request and unit counts, estimated input/output tokens, Batch cost, Live comparison and rates.
Review and accept it before copying an API translation prompt.
Changing source, shared guidance, references, compiler/templates, scope or API settings invalidates the estimate.
A saved quote must be accepted again when reopening the game.

The estimate reuses application pricing rules and a 2.5× source-token output allowance, with no assumed cache savings.
Rates can come from the pricing catalog or configured/built-in fallbacks; verify the displayed rates for the selected model.
It excludes provider waiting, retries, billed reasoning, image work, coding-assistant work and QA, and is not a spending cap.
The actual engine adapter must collect and review its final provider requests before submission.
Len does not automatically submit arbitrary engine request plans through the existing Translation tab; compatible adapters reuse that backend and persisted Batch lifecycle.
Unsupported Batch routes cannot silently fall back to Live translation.

Copying a prompt prepares or refreshes the workspace and makes no translation API calls.
The assistant performs source preservation, local Git setup, investigation and validated checkpoints within the selected task.
Git operations run when the assistant starts, rather than when the prompt is copied.

## Local Git and resumable work

The starting prompt records the supplied untranslated starting state before translation.
The CLI uses Workflow's Git backend to create `original` and the translated branch,
or reuse existing baselines and branch names:

```bash
python scripts/len_translation.py git-status --game-root '/path/to/game'
python scripts/len_translation.py git-setup --game-root '/path/to/game' --version '1.00'
```

For fresh tasks, the selected game folder is the original by default. Normal DazedTL
preparation - an enabled `TranslationUpdateCheck` plugin, GameUpdate files, generated
guidance, extraction or formatting - is not evidence that translation has occurred.
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

Len keeps `.dazedtl/` local, including authored scripts, translation stores, editable image sources, glossary, research, status, progress and QA evidence.
Keep separate backups of that workspace; it is excluded from both game branches.
Prompt and progress refreshes maintain this policy without deleting existing files or changing Git's index.

`main` is the runtime translation patch: translated native files and images, required modified or added plugins/fonts, and minimal repository metadata.
`original` stores the corresponding untranslated originals for backup and version updates.
A plugin or other file added only by the translation has no original counterpart.
Unused vendor assets, engine files, unrelated plugins and development artifacts do not belong in either branch.
Before the first baseline, the assistant reviews the engine and writes an exact-path ignore allowlist for the intended patch.
At each later checkpoint it injects the reviewed runtime outputs into the actual game folder and synchronizes the complete patch scope:

```bash
python scripts/len_translation.py git-scope --game-root '/path/to/game' \
  --manifest '/path/to/patch-files.json' --original '/path/to/untranslated-backup' --dry-run
python scripts/len_translation.py git-scope --game-root '/path/to/game' \
  --manifest '/path/to/patch-files.json' --original '/path/to/untranslated-backup'
```

The manifest is a complete JSON list of runtime paths or a `files` object with optional `sha256` and `original_sha256` bindings.
An explicit null original hash identifies a translation-only addition.
The helper reuses registered original blobs; a matching backup supplies originals for newly included files.
It checks source and delivery hashes, stages only the patch and minimal metadata, untracks other files without deleting local copies, and appends a scope commit on `original`.
It updates the official updater's ignored-asset inventory and preserves existing history.
Existing staged edits, pending updates, mismatched sources and an `original` branch checked out elsewhere must be resolved first.
The assistant reviews the staged result and commits the patch on `main` (or the established translation branch).
The command does not inject files, commit `main`, check out branches, push or publish.
Never merge English commits into `original`.

**Git version tracking** under **Optional: project tools and references** opens the
existing Version Update page for the selected Len game, including native-byte setup.
It does not select an unrelated Workflow game. The reference lifecycle also covers
independent extraction coverage, current context on resume, engine-compatible packaging
and explicit pending status for runtime checks that could not be performed.

Len's starting prompt also requires source metadata at injection time. For MV/MZ,
the assistant stages map/database JSON and writes each file through:

```bash
python scripts/len_translation.py write-rpgmaker-json \
  --source '/path/to/source/Map001.json' \
  --translated '/path/to/staged/Map001.json' \
  --output '/path/to/game/data/Map001.json'
```

This adds Workflow-compatible `_original` entries and retains existing Japanese
through corrections and clean-baseline reinjection. The source must be the matching
untranslated baseline or a previous game file with its originals intact. The writer
checks alignment before replacing one file atomically; command insertion/reordering
and unsupported schemas require an explicit source-aware adapter. The historical
reference injectors need their output redirected to staging first. Final source/live
records are checked with the existing RPG Maker QA tools. Native formats that cannot
store `_original` use separately backed-up source/injection sidecars instead. These steps are
part of the same starting prompt.

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

- `project.json`: local scope settings, restored when reopening the game.
- `setup.md`: current shared setup and investigation instructions.
- `context.json`: current assembled system prompt, glossary and reference registry.
- `handoff.md`: scoped instructions and paths for the coding assistant.
- `progress.json`: counted progress, reported phase checkpoints and artifact fingerprints.
- `status.md`: detailed progress and evidence, available under **View detailed log**.
- `work/`: local authored tools, translation records and QA/provenance notes.
- Any project-specific tools, extraction stores, research and translation outputs.

Copy refreshes shared guidance from disk. Moving a game and copying its starting prompt again
regenerates absolute handoff paths. Existing project-local skill copies and adapted tools
from the first integration remain untouched; the handoff points to the maintained app skill.

The progress panel refreshes every three seconds while the tab is visible. It shows
text translated, text reviewed and images translated, plus phase checkpoints, the
last update, a short blocker, the next action and remaining active-work estimates. Unaudited corpora show a provisional completed/discovered percentage; before any export, counts show **Not measured**;
excluded images show **Out of scope**. A complete text bar does not imply finished QA.
Both progress files survive prompt refreshes and project moves.

The agent updates the panel after saved batches/milestones, at least every 10 minutes during active work, and before a long wait using:

```bash
python scripts/len_translation.py progress-update --game-root '/path/to/game' --input '/path/to/report.json'
python scripts/len_translation.py progress --game-root '/path/to/game'
```

Reports reference saved unit exports; the helper calculates counts from unique IDs
and checks source/review fingerprints. It flags changed or missing tracked artifacts
and changes to project scope. Phase checkpoints are reported by the agent and still
need the corresponding evidence. Existing projects initially show unmeasured progress
until their agent reports it. The bundled
`references/progress-reporting.md` documents unit exports, cumulative active seconds, throughput history and remaining phase ranges.
Estimates require measured samples or an explicit phase basis and pause when evidence is stale or work is blocked.
A discovered-unit percentage does not claim independently audited full-game coverage.

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

Dialogue batches also accept `--speakers '/path/to/speakers.json'`. The agent builds
this metadata from the game's speaker fields, markup and reviewed extraction. For
sources `{"line1": "待って。", "line2": "はい。", "line3": "静かな夜だ。"}`, a matching
speaker file is `{"line1": "ハイメ", "line2": "レオン", "line3": null}`. For a source
list, supply an equally sized speaker list. Every ID/position must be present; use
null for unidentified speakers (blank names normalize to null). Missing/extra IDs,
wrong shapes, non-text names and multiline names fail before context is prepared.

The compiler includes current speakers' glossary/voice notes even when their names
are absent from the source. It returns the normalized `speakers` metadata and embeds
that map as context before the unchanged source body in `user`. Send the complete
`user` field to the model; only the source body is translated, with the original
IDs/order and the driver's output schema. Separate nameplates remain separate
translation/injection units. Speaker metadata does not affect SFX or exact reference
matching. Unknown speakers do not inherit the previous speaker automatically.

Changing a speaker assignment changes `request_sha256`, even if the dialogue and
matched glossary stay identical. Use it for dialogue cache/retry decisions and retain
speaker/scene associations in stored units. Calls without `--speakers` retain their
existing request format for non-dialogue and legacy callers.

Direct translation and adapted API drivers must consume those fields, retain their own
required output schema, and store the request fingerprint with results. Recompile before
reusing results after guidance changes. Fingerprints expose changes; the compiler does not
operate a provider queue or enforce reuse decisions inside historical example drivers.

For a sequence, prefer `context-many` to repeated single-batch context calls:

```bash
python scripts/len_translation.py context-many --game-root '/path/to/game' \
  --input '/path/to/plan.json' --output '/path/to/game/.dazedtl/len-method/api-requests.json'
```

The input has `complete`, game-relative `inputs` and `batches`; each batch has a unique `id`, `sources`, and optional `speakers`, `instruction_key` and `source_context`.
See `references/direct-workflow.md` for the full example.
The compiler reads shared guidance/reference data once per operation, verifies dependencies again and produces the same contexts as single-batch calls.
The output binds source inputs, scope, payloads and compiler/templates for estimate invalidation.
Only an audited complete plan can be priced as the whole API job.

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
QA defaults to changed renderers, windows, triggers and save behavior, with independent coverage/structural checks at bounded milestones.
Hash-matched evidence can be reused when its relevant dependencies are unchanged.
A full playthrough or a second tester is optional unless requested.
For English MV/MZ output, the source-preserving writer sets `System.json.locale` to `en_US` when present and retains its original value; check locale-sensitive plugins, fonts and English name entry in the runtime.
