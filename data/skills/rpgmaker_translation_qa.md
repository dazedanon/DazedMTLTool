# QA Exported RPG Maker Translations — Focused Pass

<!-- qa-contract:rpgmaker-qa-v4
focus-isolation exhaustive-coverage approval-before-edit preserve-original durable-artifacts
fresh-shard-workers immutable-context-pack indexed-mechanical-preprocessing
affected-identity-revalidation batched-registry-epochs parallel-component-propagation
adversarial-closing-validation semantic-first-layout-last threshold-only-nonfinding
family-consistency-validation offline-quality-benchmark throughput-evidence
coordinator-only-apply post-fix-regression
deterministic-manifest-gate independent-manifest-validation no-generated-extractors
-->

<task_context>
Audit the translated RPG Maker JSON files in this detected game data folder:

`{{GAME_DATA_FOLDER}}`

The preserved Japanese source attached to each translated value as `_original` is authoritative
for source-versus-translation comparisons. Use other records in the same folder for structure and
nearby event context.

Use the rest of this game folder as read-only evidence for scripts, enabled plugins, event flow,
assets, and runtime behavior:

`{{GAME_ROOT}}`

Before reviewing any translation, load all three required selected-game context files below. Do
not infer their contents from translated JSON or substitute similarly named files elsewhere in the
game.

Use this glossary as authoritative for applicable names and terminology:

`{{VOCAB_FILE}}`

Use these translation quirks as project-specific voice, style, and formatting rules:

`{{QUIRKS_FILE}}`

Use this game skill as the project's setting, register, characterization, and naming frame:

`{{GAME_SKILL_FILE}}`

Translation also uses optional custom Markdown overlays from this selected-game skills folder:

`{{GAME_SKILLS_FOLDER}}`

Use the shipped deterministic QA tooling from this exact DazedTL checkout:

`{{QA_TOOL_ROOT}}`

The selected mechanical focus key is `{{QA_FOCUS}}`.

Enumerate regular `*.md` files directly in that folder, excluding `game.md`, `quirks.md`, and the
legacy reserved name `translation.md`, and load every non-empty custom overlay before semantic
review. Treat a missing folder or no custom overlays as `none`, not as an error. Record an
unreadable, unsafe, or conflicting custom overlay exactly instead of silently ignoring it.

If any context file is missing, unreadable, or empty, record that exact status before continuing.
Apply every usable rule during semantic review. If the context files conflict with each other or
with authoritative Japanese/runtime evidence, report the conflict and do not guess silently.

This prompt contains one selected QA focus at the end. Audit only that focus. Other JSON values and
game files are context, not additional review scope. During discovery, do not edit translations or
modify any game file. Start immediately; ask about file selection only if no in-scope translated
JSON containing `_original` can be found.

Complete all four QA passes; none is optional. Run them in this order:

1. Database files
2. Risky event codes
3. Dialogue, choices, lore, and wordplay
4. Coverage and release gate

Carry each pass's checkpoint or final report forward as evidence for the final gate. Do not skip any
pass because it appears low-risk or because its mechanical scan was clean.
Run the four passes as separate selected-focus invocations in the listed order; do not widen one
invocation beyond the selected focus merely to satisfy the overall four-pass requirement.
</task_context>

## Bounded review contract

Keep this pass independent and measurable instead of widening it into a whole-game review.

- Inventory every `_original` leaf assigned to this focus and no others. If classification is
  uncertain, report the leaf as an unresolved scope/shape warning; do not silently absorb another
  pass.
- Mechanically check 100% of resolvable in-scope source/translation pairs.
- Deduplicate pairs by exact UTF-8 source and translation equality for semantic review, using one
  representative that retains every locator and materially distinct context class. Context-class
  occurrence checks do not create extra frozen representatives.
- Review every frozen cluster before this focus may end or request approval.
  Use 500 pairs as the routine wave size and follow a selected focus's explicit small-corpus rule
  when it requires reviewing up to 750 pairs.
  After each locally completed wave or validated worker shard, persist the checkpoint.
  Continue immediately with the next non-overlapping wave from the same frozen manifest, locally
  or by dispatching it to a worker in the same invocation.
  Do not stop merely because one wave completed or was clean.
  Anticipated context-window pressure, token or response-length concerns, wall-clock concerns,
  corpus size, wave count, or a desire to hand work off are not runtime or tool limits. Context
  compaction is continuation, not interruption. If you can still call tools, write the checkpoint,
  or continue reasoning, continue in the same invocation instead of returning an incomplete report.
  If an actual runtime or tool limit prevents continuing, report the focus as incomplete with the
  exact unreviewed count and resume from the checkpoint on the next invocation. Use this status
  only after a concrete tool failure, timeout, hard platform termination, or equivalent enforced
  limit actually prevents the next wave or checkpoint; record that evidence in the report.
- Put every mechanically flagged, glossary-bearing, short ambiguous, and context-sensitive cluster
  in the mandatory-review queue. Mandatory status changes attention order inside the current wave;
  it must not silently increase the wave or count as semantic review by itself.
- Inspect nearby commands or records when speaker, referent, token placement, or meaning needs
  context. For repeated text, inspect at least one occurrence from every materially different
  speaker, event shape, database field, or nearby-command context.
- Never imply that a partial semantic wave covered every line.
  Readiness requires 100% mechanical coverage, zero unresolved Critical/High findings, and an
  explicit reviewed disposition for every frozen cluster.
  Here `unresolved` means lacking adequate evidence, propagation, reconciliation, or a supported
  proposed correction; a confirmed actionable finding awaiting user approval is resolved for
  discovery-gate purposes and remains pending action.
  Sampling, risk ranking, or consecutive clean waves cannot substitute for exhaustive coverage.

## Reproducible inventory and checkpoint

Do not stream thousands of raw JSON lines into the conversation. Before semantic review, choose the
resolved durable task directory outside `{{GAME_ROOT}}`, then run these shipped commands with that
directory substituted for `<durable-task-dir>`:

```text
python "{{QA_TOOL_ROOT}}/scripts/build_rpgmaker_qa_manifest.py" --game-root "{{GAME_ROOT}}" --data "{{GAME_DATA_FOLDER}}" --focus "{{QA_FOCUS}}" --output "<durable-task-dir>/inventory.json"
python "{{QA_TOOL_ROOT}}/scripts/validate_rpgmaker_qa_manifest.py" --game-root "{{GAME_ROOT}}" --data "{{GAME_DATA_FOLDER}}" --manifest "<durable-task-dir>/inventory.json" --report "<durable-task-dir>/inventory-validation.json"
```

The validation report must say `"valid": true` before semantic review begins. Any unresolved
source shape makes validation invalid and must be fixed and regression-tested in DazedTL before the
inventory can be rebuilt. Treat the valid manifest's records,
clusters, unresolved list, file hashes, identities, speaker facets, and `review_sequence` as the
frozen mechanical authority. An unresolved locator may not be omitted, waived, or counted as
coverage by a worker. Preserve both files and their hashes in the task manifest.

Each record already contains independently validated live mapping, focus classification,
source/live lengths, length band, display shape, runtime-token and visible-number evidence, static
mechanical flags, and applicable speaker, choice-branch, database-entity, or risky-code context.
Exact clusters and the frozen review order are also precomputed. Query these fields; do not reparse
the corpus or generate a competing mechanical index for the same facts.

Do not ask an AI worker to write, replace, patch, or reinterpret the extractor or validator during
a live audit. Do not use an improvised script, filtered command stream, prior audit helper, or model-
generated manifest as a substitute. If the shipped tool lacks a source shape, stop preprocessing,
record the exact unsupported locator, and fix and regression-test DazedTL itself before restarting
the affected mechanical inventory. Semantic workers may write only review/checkpoint helpers that
consume the validated manifest without changing its identities, pair mappings, context facets, or
order.

- Identify a location by `relative file + canonical JSON path + SHA-256 of exact UTF-8 source`.
  Version the helper's canonical JSON-path grammar, normalization rules, and short/medium/long length
  thresholds in the task manifest so identities and strata reproduce across resumes.
- Freeze the in-scope cluster universe before the first wave. Choose the lexicographically lowest
  stable identity as each cluster representative and order representatives by
  `SHA-256("rpgmaker-qa-focus-v1\0" + focus name + "\0" + representative identity)`.
- Use the shipped manifest's `review_sequence` exactly. It is the versioned deterministic ordering
  algorithm for every focus; focus-specific strata affect attention and context checks inside a
  wave, never membership or order. Do not recompute, interleave, or reshuffle it on resume or after
  editing English.
- Save the ordered identities, locators, source hashes, dispositions, issue signatures, applicable
  focus-specific review-contract ID, and wave position in a checkpoint outside `{{GAME_ROOT}}`.
  Record the helper version or content hash and manifest checksum. Never place generated QA
  artifacts in the game folder or data folder.
- Create the persistent task directory before generating the first helper, checkpoint, registry,
  worker assignment, correction plan, or regression artifact. Authoritative artifacts must never
  originate in an operating-system temporary directory and later depend on an end-of-task copy for
  durability. Record every authoritative artifact path and SHA-256 in a task manifest; use temporary
  paths only for disposable validation outputs that can be regenerated from the durable copies.
- Reuse a valid checkpoint for this focus. Reject it and explain why if the focus, source hashes,
  manifest checksum, or applicable focus-specific review contract no longer matches. A selected
  focus may explicitly allow reuse of older mechanical inventory while requiring its semantic
  dispositions to restart. Keep checkpoints from other focuses separate.
- Display compact panes of roughly 75–150 rows with ordinal, locator count, risk reasons, source,
  and translation. Escape embedded newlines. Expand full locators and context only for candidates.

## Durable goal and parallel semantic review

This prompt explicitly authorizes a durable goal and subagent delegation for the selected focus.
When the host provides durable goals, create one whose stopping condition is this focus's exhaustive
coverage and required report. Do not mark the goal complete until the focus-specific completion gate
passes. A missing goal feature is not a blocker; continue with the checkpoint contract.

Keep the immutable corpus master, versioned coordinator state/checkpoint, worker shards, helper
scripts, registry, and merge log in one persistent task directory outside `{{GAME_ROOT}}`. Do not use
an operating-system temporary directory for the authoritative copies; temporary paths are suitable
only for disposable validation runs. Preserve a recoverable coordinator-state snapshot before every
accepted batch merge. Store one immutable frozen corpus master for the task plus immutable
coordinator-state and compact, read-only registry snapshots for every published revision/epoch.
Choose and record the resolved durable path before creating artifacts, using a stable hierarchy such
as `<durable-qa-root>/<game-id>/<focus>/<contract-or-schema-id>/`; reuse that exact path on resume.
Do not clone the full master or full registry into every worker shard. A shard is a lightweight
review delta containing assignment metadata, assigned identity/ordinal keys, pane commits,
dispositions, evidence, ledger additions, and local proposals. The coordinator materializes those
deltas into the master only after validation.

Run one deterministic preprocessing pass over the frozen corpus. Persist content-addressed indexes
for exact and normalized source/live text, glossary candidates, runtime tokens, visible numerals,
source residue, event/field/speaker/context facets, same-source classes, and known callback or
narrative edges. Compute static mechanical flags and risk features once. Propagation helpers must
query these immutable indexes instead of repeatedly reparsing every JSON file or asking workers to
rediscover mechanical candidates. A helper hit remains a candidate until semantic/context review
disposes it; preprocessing never substitutes for exhaustive review.

Build one immutable context pack from the exact bytes or explicit missing/empty status of the
glossary, quirks, game skill, custom overlays, applicable runtime/plugin evidence, and the versions
of the review contract, helper, path grammar, and schema. Preserve resolved provenance paths and
individual hashes in the pack. The pack may contain deterministic extracts and canonical tables but
must not contain prior workers' conclusions or interpretive summaries. Record its SHA-256 and derive
the focus context fingerprint from its inputs and generator revision.

Treat the frozen corpus master and the live issue registry as separate authorities. Never mutate
the frozen master to make a finding appear propagated. Publish each accepted registry revision as
an immutable epoch snapshot plus an append-only delta from the preceding epoch, then atomically
advance a small current-epoch pointer. Workers receive the exact master revision/hash and registry
epoch/hash in their assignment; they must not resolve work through a mutable pointer. Registry epoch
inequality alone does not invalidate completed semantic review. For every changed family, compute a
deterministic affected-identity set from the old and new selectors, candidate queries, confirmed
members, changed invariants/corrections/exclusions, same-source/context expansion, and transitive
callback/narrative dependency closure. Accept unaffected identities from an otherwise valid stale
worker delta and assign only its intersection with that set to a fresh revalidation worker. If the
impact query or dependency closure is unavailable or inconclusive, conservatively mark the entire
focus affected. Persist each impact proof and the family revisions revalidated per identity.

After freezing the manifest and completing the full mechanical scan, use subagents by default when
more than 750 semantic clusters remain and subagent tools are available. Keep one agent as the
coordinator and fill the remaining concurrency slots with workers. The number of workers is
capability-driven rather than hardcoded.

Start a fresh subagent for every shard assignment. Never reuse a completed worker for another
ordinal range, even when the host supports follow-up tasks or restarting an existing agent. Retire
the worker after it closes and returns its shard, then spawn a fresh replacement when the next
assignment is ready. Preserve project continuity in the durable context fingerprint, immutable
snapshot, registry, checkpoint, and assignment packet rather than in accumulated worker memory.
Fresh workers must independently load and hash-check the immutable context pack. They may inspect
its hash-verified provenance files and read-only game evidence when meaning requires more context;
do not pass prior workers' reasoning or summaries as substitute context or make every worker rebuild
deterministic glossary/runtime tables from mutable origin paths.

The coordinator owns the manifest, master checkpoint, issue propagation, cross-shard reconciliation,
approval gate, and final report. Partition the frozen order into consecutive, disjoint semantic
shards using the applicable routine wave size. Give each worker one explicit assignment containing
the focus and review-contract ID, manifest checksum, context fingerprint when applicable, inclusive
ordinal range, immutable corpus-master revision and SHA-256, coordinator-state revision and SHA-256,
canonical issue-registry epoch and snapshot SHA-256, registry delta-chain SHA-256, helper SHA-256,
immutable context-pack revision and SHA-256, provenance paths, output schema, and read-only game
paths. Use snapshot isolation: every worker in one batch receives the same immutable master,
coordinator state, registry epoch, delta chain, helper revision, and context pack, and only the
coordinator may publish a newer revision.

Run a coordinator scheduling loop while work remains. Validate and retire each returned worker
immediately. At a registry-epoch boundary, reconcile all returned proposals, publish the next compact
registry snapshot, and atomically merge accepted deltas. Dispatch only against a fully published
immutable epoch, but do not idle worker slots merely because a newer epoch is being reconciled or
challenged. Older in-flight outputs may finish and merge through affected-identity validation.
Reconcile proposals at fixed ordinal scheduling-batch boundaries rather than worker completion order,
then publish one epoch containing the batch's canonicalized changes. A scheduling batch is the
complete set of assignments selected together from the frozen order; record every closed,
interrupted, and superseded assignment before reconciling it. Propagation and affected-locator
revalidation must converge before approval or correction-map finalization, not before unrelated
semantic review proceeds. Never dispatch against a mutable or partially published registry.
Treat any change to a family's selectors, invariants, canonical correction, severity, confirmed
membership, callback links, or exclusions as material.

Maintain one coordinator-owned canonical issue registry as a versioned durable artifact alongside,
not inside, the immutable corpus master. The coordinator state records only its current epoch and
hash. Publish each compact snapshot for workers as a separate read-only artifact. Give each entry a
stable ID, severity, canonical signature, proposed correction, affected ordinals and live-value
count, propagation status, and reconciliation status. A worker must classify a candidate as either
a match to an existing registry ID or a locally named new proposal with evidence; workers must not
allocate canonical IDs. Reconcile duplicate proposals across the whole returned batch, assign or
reuse the canonical ID centrally, and propagate it across the full focus before the next approval or
completion gate. Canonicalize signatures and allocate IDs in stable sorted order so worker return
timing cannot change the registry.

Give every actionable registry entry a machine-readable propagation contract. Include source-side
selectors and normalized variants, known-bad English selectors, required canonical terms or
semantic invariants, same-source and context-class expansion rules, setup/payoff or callback links,
runtime/display constraints, explicit evidence-backed exclusions, and deterministic verification
queries. Track the contract's revision, last challenged corpus hash, candidate count, confirmed live
locator count, excluded-candidate count with reasons, and state (`open`, `searching`, `challenged`,
or `converged`). Counts copied from a finding table are not proof of propagation; only the current
contract queries and an independent challenge may establish convergence.

Workers must not edit game files, write the master checkpoint, change helpers, request user approval,
publish a focus status, or spawn further agents. A worker may write only a uniquely named shard
artifact outside `{{GAME_ROOT}}` when the coordinator requests one. Each returned shard must record:

- its assignment ID, focus, contract ID, manifest checksum, context fingerprint when applicable,
  and exact ordinal range;
- one explicit semantic disposition for every assigned representative, with stable identity and any
  issue signature;
- expanded context evidence for findings and materially distinct repeated occurrences;
- applicable narrative anchors, wordplay candidates, cross-focus dependencies, unresolved evidence,
  and proposed corrections required by the selected focus.

Review and persist each shard incrementally. Before dispatch, freeze a deterministic shard review
sequence that applies the required risk ordering with stable ordinal tie-breaks. Use consecutive
panes of at most 100 positions in that sequence; after actually reviewing a pane, atomically save its
explicit semantic, narrative, and wordplay dispositions plus its next sequence position in the worker
shard before reading the next pane. Never keep all 500 dispositions only in agent memory or bulk-mark
the whole shard at the end. On interruption, resume from the shard's first uncommitted sequence
position with a fresh replacement worker and do not repeat or infer the missing pane. Give the
replacement only the immutable assignment packet and committed shard delta, not the interrupted
worker's accumulated conversation.

Treat worker output as untrusted review evidence until validated. Confirm matching fingerprints and
contract, exact assigned identity coverage, no missing or extra representatives, no overlap with
accepted shards, valid dispositions, and no unauthorized writes. Reject a partial summary or invalid
shard without marking its range reviewed, then reassign the original range. Merge accepted shards
into the master checkpoint in deterministic ordinal order and record each wave exactly once. The
coordinator may slice a complete valid delta into unaffected accepted identities and an
affected-identity revalidation microshard; this is not permission to accept an incomplete worker
summary. Store revalidation results as ledger deltas without changing the original frozen 500-pair
wave membership or history. Retire every returned worker whether its shard is accepted or rejected;
reassignment always goes to a fresh worker.

For every published batch epoch that adds or materially changes finding families, build a
deterministic dependency graph from shared candidates, terms/entities, context predicates, and
callback/narrative links. Partition it into stably sorted connected components after the
coordinator's indexed full-corpus propagation pass. Start one fresh adversarial propagation worker
per independent component in parallel when slots are available. Give each worker the immutable
corpus master, indexes, context pack, current registry snapshot, component contracts, and read-only
game evidence, but not earlier workers' reasoning or a claimed complete locator list. Require it to
challenge exact-source matches, lexical and normalized variants, context-resolved references,
same-event siblings, repeated prompts/prerequisites, and setup/payoff or joke callbacks as applicable.
It must return either evidence-backed new candidates or a machine-readable report stating
`zero new confirmed locators`, with every rejected candidate and exclusion reason. A confirmed
locator reopens and rechallenges only its dependency component and adds its impact set to the
affected-locator revalidation queue. Use a separate fresh component closer when one component was
split into candidate chunks.

After all issue families report convergence, start a different fresh closing validator that has not
performed semantic review, correction planning, or the preceding propagation challenge. Have it
rebuild the full-corpus searches from the immutable artifacts, validate registry totals and
exclusions, compare canonical renderings and context-justified variants within every terminology,
title, pronoun/referent, catchphrase, callback, and other linked family, and challenge cross-family or
cross-component misses. Do not ask for approval, apply fixes, or report completion until this
validator also returns zero new confirmed locators and zero unexplained family inconsistencies. A
miss invalidates the completion hash and reopens the affected family plus its dependency-component
closure; unrelated converged components remain valid when corpus, context-pack, and contract hashes
are unchanged.

Before reporting completion, run a machine-verifiable gate that rejects any non-final disposition,
unreviewed cluster, missing/duplicate/gapped/overlapping wave, stale registry total, unreconciled
proposal or issue propagation, unaccounted unresolved source shape, unreconciled narrative or
wordplay ledger, stale source/mechanical evidence, or unauthorized game-file modification. For a
large corpus, require the exact expected sequence of 500-pair waves plus the final partial wave.
Also require every propagation contract to be `converged`, its current-epoch verification queries to
reproduce the stored counts, the latest fresh adversarial challenge and closing validation to report
zero new confirmed locators, and every exclusion to remain reproducible. Accept an older per-locator
disposition only with a reproducible proof that no intervening changed family's affected set contains
it. Require the supplemental revalidation queue to be empty. Completion requires the gate to pass,
not merely a worker summary, registry count, or stored reviewed count.

## Quality and throughput evidence

Measure speed as completed verified work, never as permission to sample or skip review. Record per
scheduling batch and for the whole focus: elapsed time; unique clusters and occurrence contexts
reviewed; deterministic candidates generated; actionable findings and affected locators;
revalidation identities; rejected shard identities; propagation component/challenge counts; and,
when the host exposes them, input/output tokens. Report clusters per elapsed hour and revalidation
percentage, but do not impose a flaky wall-clock completion threshold.

When a committed or previously user-approved QA calibration oracle exists for the same benchmark
contract, run it once per review-contract, helper, context-pack generator, or orchestration revision.
Record the oracle hash, locator/family precision and recall, F1, propagation completeness, correction
exactness, per-focus coverage, focus/severity accuracy, false positives, and elapsed/throughput
metadata. Never derive expected answers from the run being scored. A missing project oracle does not
block a live audit; after approval and closing validation, preserve a candidate calibration pack of
confirmed findings plus verified hard negatives for explicit user approval and future revisions.
Accept a speed optimization only when exhaustive coverage and completion gates remain unchanged and
available calibration quality does not regress.

Delegation does not replace whole-scope reasoning. The coordinator must propagate every confirmed
issue signature across the entire focus, reconcile terminology and context classes across shards,
and perform the selected focus's global narrative, wordplay, dependency, or release reconciliation.
If subagents are unavailable, finish the same frozen shards sequentially. Subagent unavailability,
worker failure, or a full worker queue is not permission to stop while coordinator tools remain
callable.

## Project context and evidence rules

Load `{{VOCAB_FILE}}` before terminology review. Report whether it loaded, its usable deduplicated
entry count, and confirmed violations. Reject substring collisions and contextually different
senses. Treat approved project-specific exceptions as non-findings and record them in the focus
checkpoint so they do not recur.

Load `{{QUIRKS_FILE}}` and `{{GAME_SKILL_FILE}}` before semantic review. Use their applicable voice,
style, formatting, setting, register, characterization, and naming guidance when judging each
translation. Record both paths, load status, and whether each file supplied usable guidance. Do not
claim either file was considered merely because its parent game folder was inspected.

Load every optional custom overlay discovered under `{{GAME_SKILLS_FOLDER}}` as project guidance
used during translation. Record the folder, filenames, load status, and whether each supplied an
applicable rule. Japanese source and verified runtime evidence remain authoritative when an overlay
conflicts with them.

Preserve live text unless concrete evidence shows a defect and supports a correction. Evidence may
come from the Japanese source, glossary, runtime token rules, surrounding context, related database
records, or enabled plugin code. Report changed or missing meaning, wrong names/terms, source
residue, broken structure/tokens, wrong polarity/number/referent, or demonstrable display damage.
Also report a source-supported lore contradiction, lost intentional ambiguity, erased joke or
wordplay function, or broken callback in the focus that owns the live target. Functional English
adaptation is valid and need not reproduce the Japanese mechanism when it preserves the semantic
payload, character voice, intended effect, and any dependent payoff.

Use this evidence order for narrative or wordplay decisions: authoritative Japanese and its event
context; applicable glossary/project guidance; corroborating Japanese occurrences, database
records, and verified runtime behavior; then the current English as the text being evaluated, never
as proof of canon. Do not promote an interpretation to lore merely because several English lines
repeat it. Leave genuinely ambiguous evidence unchanged and report the specific gap when it blocks
a safe disposition.

Do not report preference-only rewrites. Valid transliteration, honorific, dialect, punctuation,
loanword, register, literal-versus-localized phrasing, or metadata differences are not findings when
meaning and runtime behavior remain sound. Do not infer that source-absent translator credits,
patch notes, or coherent added labels are accidental without evidence of corruption or runtime
harm. Leave genuinely uncertain text unchanged.

When a defect is confirmed, immediately search every resolvable in-scope pair for the broader issue
signature. Verify lexical matches in source and runtime context, group confirmed matches under one
finding ID, and repeat propagation until a full search adds no affected live values. Do not limit
propagation to an identical Japanese sentence or the current semantic wave.

## Review priority and layout policy

Use this default priority for risk scoring, shard scheduling, finding review, and correction
planning; it does not reduce exhaustive cluster coverage:

1. Factual and semantic correctness, including omissions, polarity, conditions, and wrong
   subjects, objects, speakers, or actions.
2. Identity and referents, including pronouns, kinship, titles, roles, quantities, and who is doing
   or receiving an action.
3. Canonical glossary names, terminology, factions, places, abilities, and consistent propagation
   across every applicable occurrence.
4. Context-dependent callbacks, setup/payoff relationships, deliberate ambiguity, wordplay, and
   character voice.
5. Runtime integrity, including structure, controls, placeholders, visible numbers, choices,
   bullets, alignment, and other behavior-bearing formatting.
6. Fluency and demonstrable display/layout damage where the basic meaning remains sound.

Treat a raw or plugin-stripped visible character count as a triage signal, not an actionable
finding by itself. A configured threshold such as 55 characters does not prove that the runtime
clips, truncates, overlaps, or paginates the line incorrectly. Register a standalone display/layout
finding only when engine/plugin rules, a reproducible render, a screenshot, or another concrete
runtime artifact proves player-visible damage or a hard display constraint violation. Keep an
explicitly requested layout audit's threshold-only candidate inventory separate from actionable
findings.

When an approved substantive or runtime-integrity correction already changes a locator, rewrap that
locator safely as a companion transform when needed. Preserve meaning, controls, message shape, and
intentional pacing, and do not allocate a separate overflow finding ID unless the display defect is
independently proven. Leave an untouched threshold-only locator unchanged and out of correction
maps and propagation counts.

## Mechanical checks for every in-scope pair

1. Parse the containing JSON and verify the live counterpart, type, list/object shape, and non-empty
   output. Report unresolved or unfamiliar `_original` shapes instead of guessing.
2. Detect unchanged Japanese, unintended source-language residue, truncation, mojibake, model
   commentary, refusal text, Markdown fences, or pasted JSON fragments.
3. Compare runtime tokens and placeholders for loss, addition, duplication, malformed escaping,
   unsafe reordering, or changed scope. Include RPG Maker codes such as `\C[n]`, `\N[n]`, `\V[n]`,
   `\I[n]`, `\{`, `\}`, `\.`, `\|`, `\!`, `\>`, `\<`, and `\^`; custom backslash codes;
   `__PROTECTED_n__`; printf placeholders; interpolation; and meaningful HTML/plugin tags. Derive
   custom escape parsing and token scope from the enabled engine/plugin code when generic RPG Maker
   parsing is insufficient. Treat numeric control arguments such as the `0` in `\C[0]` as runtime
   syntax, not visible numbers, and test any inserted delimiter against the runtime parser rather
   than assuming a regex-safe spelling is display-safe.
4. Verify semantic placement, not only token counts. Colors and font scopes must wrap the translated
   equivalent; icons and variables must remain beside what they modify; waits and pauses must keep
   their intended beat. Natural English word order does not require identical offsets.
5. Flag concrete number, quantity, polarity, pronoun, subject, speaker, terminology, quote, and
   punctuation damage; suspicious length changes; unrelated sources collapsed to generic output;
   or one source translated inconsistently where context does not justify it. Compare semantic,
   player-visible numbers separately from control arguments, record IDs, filenames, script literals,
   and other structural numerals; normalize only forms proven equivalent for the active runtime.
6. Check actual display constraints applicable to this focus without treating a character threshold
   as proof of failure. Use configured wrap widths and enabled plugin behavior when available.
   Measure raw serialized length and rendered visible width separately with a plugin-aware control
   stripper; record threshold hits as mechanical candidates only. A raw-width flag caused only by
   verified zero-width runtime controls is not a visible overflow. Conversely, do not hide a proven
   overflow by stripping a control whose plugin renders text, an icon, spacing, or changes the
   effective width. Record a proven auto-wrap, pagination, or control-inflation exception once;
   persist its selector, runtime evidence path and hash, candidate count, exclusion reason, and
   visible maximum so the closing validator can reproduce it as a narrow predicate. An exclusion
   may suppress only the proven mechanical false positive, never semantic placement or another
   check. Do not raise or propagate threshold-only findings.

## Required report and approval gate

Return these sections after the exhaustive discovery run, or after documenting a genuine runtime,
tool, or evidence blocker that prevents it from finishing:

### Focus coverage

- Focus name and exact included/excluded shapes
- Files found / parsed and in-scope `_original` leaves
- Resolvable pairs mechanically checked and unresolved pairs
- Unique clusters, semantically reviewed this wave, previously reviewed, and remaining
- Context classes found/reviewed and represented files/codes/fields/speakers/length bands
- Per-wave history, overlap, new signatures/affected values, clean-wave count, and convergence state
- Elapsed time, clusters per hour, revalidation percentage, rejected shard identities, propagation
  component/challenge counts, and available input/output token totals
- Checkpoint location, schema/version or helper hash, manifest checksum, and blind spots
- Glossary path, load status, usable entry count, and confirmed violations
- Translation quirks path, load status, and whether usable rules were applied
- Game skill path, load status, and whether usable guidance was applied
- Optional custom-skills folder, discovered files, load status, and applicable guidance

### Findings summary

Count only actionable findings:

- **Critical**: invalid JSON/structure or runtime-breaking token/script corruption.
- **High**: clear mistranslation, missing content, source residue, wrong control-code scope,
  glossary/name failure, altered lore/plot fact, broken foreshadowing, or wordplay required by a
  choice, puzzle, clue, or later payoff.
- **Medium**: evidence-backed context, consistency, fluency, tone, demonstrable player-visible
  display damage, or flattened humor/callback defect where the basic meaning remains sound.

Do not create Low findings for optional polish.

### Findings requiring action

Use a compact table with stable finding ID, severity, file + JSON path, event code/field, short
source, current translation, concrete evidence, issue, and proposed correction. Group identical
signatures while retaining representative locators and affected counts. Never dump full files.

### Focus status and next action

State `complete`, `incomplete - execution interrupted with clusters remaining`, or
`blocked - unresolved evidence or findings`.
Only the Coverage & release gate focus may make a whole-game release recommendation.
Use `blocked` only for an evidence gap or unresolved condition that prevents a safe disposition;
confirmed actionable findings with supported corrections may proceed to the approval gate.
Ask for fix approval only when zero frozen clusters remain unreviewed.
If execution was interrupted or blocked, provide the checkpoint and exact resume position instead
of presenting a normal completion approval gate.
When coverage is complete, end with one focused approval question offering the relevant choices:

- Apply all high-confidence fixes found in this focus.
- Apply selected finding IDs only.
- Make no edits after the completed review.
- Stop with no edits.

`High-confidence` means the source/runtime/context evidence supports both the finding and its exact
correction, its propagation contract has converged, and no material ambiguity remains; it is not a
severity synonym.

Do not edit until the user approves.

## After approval

Edit only approved live translated values under `{{GAME_DATA_FOLDER}}` that belong to this focus.
Never modify or remove `_original`. Preserve JSON types, event commands, non-text fields, control
codes, placeholders, indentation, and encoding. Make the smallest supported change and do not edit
plugin/script source under `{{GAME_ROOT}}` from this game-data QA prompt.

Before changing a game file, create a durable fix revision under the persistent task directory.
Freeze an immutable approved-fix manifest containing the approved finding IDs, propagation-contract
IDs/revisions, canonical corrections, exclusions, and approval evidence/hash. Correction planning
and supplemental-locator decisions must resolve against that manifest rather than the latest mutable
registry pointer.
Use fresh one-shot correction workers for disjoint semantic, identity, terminology, wordplay, and
independently proven runtime/display categories when subagents are available; workers may propose
entries but must not edit game files. Do not create a correction category or worker shard solely for
character-threshold hits. Every entry must carry stable identity, file and live path, source
path/hash, exact old and new values, issue IDs, propagation-contract IDs/revisions, evidence,
constraints, composition trace, and worker/base-registry hashes. Revalidate every old value against
the live JSON immediately before composition.

Compose overlaps centrally and deterministically instead of accepting last-writer-wins output.
Accept and apply correction categories in this fixed order: factual/semantic meaning; identity,
referent, pronoun, and quantity; canonical names/terminology/titles; wordplay/voice; then layout.
Apply bullet restoration, wrapping, alignment delimiters, and other layout transforms only in the
final layout tier. Limit that tier to independently proven runtime/display findings and companion
transforms on locators already changing for an approved substantive or runtime-integrity finding;
never add untouched threshold-only locators to the map.
Preserve the union of issue IDs and runtime constraints. If two semantic proposals disagree or a
layout transform cannot preserve the semantic result, fail that target for coordinator resolution
rather than selecting a worker by completion order. Record the composition rule and result in the
merge log so the closing validator can reproduce all overlaps.

After composing all approved correction categories in the fixed order, publish one correction-map
revision and one fix-registry epoch containing every materially changed family or expanded target set.
Build the family dependency graph and run fresh adversarial propagation challenges for independent
components in parallel under the same `zero new confirmed locators` rule used during discovery. A
miss rebuilds and rechallenges its affected component; unchanged components remain valid while their
corpus, context-pack, contract, and proposal hashes match. After every component converges, publish
one immutable hashed final correction map with a SHA-256 and start a different fresh closing validator
against that exact hash. Require it to validate every registry locator, every supplemental locator,
all propagation contracts and exclusions, exact live old values/source hashes, deterministic overlap
compositions, family-level consistency and justified variants, runtime tokens, visible numbers,
hearts, message shapes, and display constraints. Any new confirmed locator or changed map invalidates
the whole-map hash and requires a rebuilt map plus another fresh closing validation.
Family-level approval covers supplemental locators found after approval only when they satisfy the
same approved propagation contract and canonical correction. A materially different correction or
an entirely new issue family requires renewed user approval and must stay out of the current map.

Only the coordinator may write game files, and it may do so once, from the closing-validated
immutable correction map, after a complete dry run passes. The dry run must prove that every
registered locator is changed or explicitly already correct, every supplemental locator belongs to
the frozen corpus and an existing finding contract, `_original` source hashes match, no proposal is
a no-op, and all structural/runtime/display gates pass. Do not let correction workers, propagation
workers, or validators perform partial writes.
Here `once` means one coordinator-controlled application phase or atomic multi-file transaction;
multiple affected files are expected, but no worker writes or interleaved partial application is
allowed.

Reparse every affected JSON file, rerun this focus's complete mechanical checks, rescan each
approved issue signature across all in-scope pairs until no new affected values appear, and confirm
no residue, token, display, or structural regression. Put edited identities in a regression queue;
do not count regression as a new semantic wave.
Rebuild the complete selected-focus post-fix corpus, verify every in-scope string-valued `_original`
against the frozen source hashes, account for every in-scope unresolved non-string source shape,
reproduce every propagation
contract and false-positive exclusion, and rerun the fresh closing validator's signature searches
against the written files. Start a fresh post-fix validator, distinct from all review, correction,
propagation, and pre-write closing workers, and require it to return zero new confirmed locators and
zero structural/runtime/display regressions from the rebuilt on-disk corpus. It must also regroup the
written values by terminology, title, identity/referent, catchphrase, callback, and issue family and
return zero unexplained inconsistencies between canonical renderings and context-justified variants.
Persist the immutable final map, merge log, post-fix corpus/checkpoint, compact regression report,
hashes, and validator reports in the durable task directory from the start; temporary copies are not
authoritative.
Report raw mechanical flags separately from plugin-aware visible failures so control-token
inflation cannot masquerade as a regression. A pre-existing untouched threshold-only candidate is
not a post-fix regression and cannot fail the correction gate; validate edited locators against
their approved constraints and fail actual newly introduced display damage.
If the post-fix validator fails, mark that application revision failed and do not make an ad hoc
edit. For a regression or missed locator still covered by the approved-fix manifest, build a new
immutable repair-map revision, repeat adversarial propagation, dry run, and fresh pre-write closing
validation, then execute one new coordinator-controlled application phase. A different correction
or new family still requires renewed approval. Completion remains blocked until a fresh post-fix
validator passes.
Report fixes and remaining risks, then stop.

<!-- qa-focus:dialogue -->
## Selected focus: Dialogue, choices, lore, and wordplay

Dialogue semantic review contract: `dialogue-narrative-wordplay-v1`.

A checkpoint or report without this exact contract ID does not establish semantic completion for
this focus. When its focus, source hashes, and manifest checksum still match, its frozen manifest
and completed mechanical results may be reused, but reset semantic dispositions to unreviewed and
rebuild the narrative and wordplay ledgers from the start. Do not invalidate checkpoints from the
other three focuses solely because this dialogue contract changed.

Compute and store a dialogue context fingerprint from the exact UTF-8 contents or explicit
missing/empty status of `{{VOCAB_FILE}}`, `{{QUIRKS_FILE}}`, `{{GAME_SKILL_FILE}}`, and every loaded
custom overlay, ordered by resolved path, together with the immutable context-pack generator
revision. Reuse prior dialogue semantic dispositions only when this fingerprint and context-pack hash
also match. If project guidance changed while the source manifest remained valid, reuse the frozen
manifest and mechanical results but reset all dialogue semantic dispositions and both ledgers; new
guidance can change lore, voice, and wordplay judgments even when Japanese and English text are
unchanged.

Audit only event commands 101, 102, 401, and 405 in `Map*.json`, `CommonEvents.json`, and
`Troops.json`.

### Pair extraction

- Code 401: pair the preserved source with the visible message text in `parameters[0]`.
- Code 405: pair the preserved source with scrolling text in `parameters[0]`.
- A scalar `_original` on the first command of a merged 401/405 group may represent several live
  continuation commands. Rejoin the contiguous translated display group before comparison and do
  not report continuations as missing.
- Code 101: pair the visible speaker/name field at `parameters[4]`, or `parameters[0]` for the
  variable-name form. Treat its following message commands as read-only context.
- Code 102: pair each `_original[index]` choice with `parameters[0][index]`. Verify choice count,
  order, branch meaning, and cancel/default behavior using nearby commands. Code 402 branch labels
  are structural/context evidence, not a second translation target unless they independently carry
  `_original`.

Exclude 108/408 comment text and every risky-code shape; those belong to Risky event codes. Exclude
database/object fields even when their text appears near dialogue.

Stratify the frozen wave by relative file, event code, speaker or empty, message/choice display
shape, and short/medium/long length band. Prioritize speaker changes, omitted subjects, pronouns,
kinship, negation, conditions, quantities, choice polarity, choice/branch mismatches, name-box
errors, control-code scope, and page/wrap damage. Review adjacent 101/401 groups and full choice
blocks together when meaning depends on them.

### Narrative continuity and wordplay protocol

Assess every frozen dialogue cluster for narrative continuity and wordplay while performing its
ordinary semantic review. This is an additional disposition lens, not a heuristic sample and not a
second set of translation targets.

For each reviewed cluster, record either `no narrative/wordplay signal` or the applicable compact
ledger entries:

- **Narrative anchors:** translation-sensitive identities, relationships, forms of address,
  factions, titles, geography, chronology, quantities, world rules, revelations, foreshadowing,
  denials, and deliberate ambiguity. Store the Japanese-supported proposition, entities, certainty
  or story-state qualifier, English rendering, evidence locators, and any cross-focus dependency.
- **Wordplay candidates:** puns, homophones or double meanings, name jokes, twisted idioms,
  cultural references, comedic misunderstandings, catchphrases, reaction lines that signal a joke,
  and later callbacks. Store the source mechanism when knowable, required semantic payload,
  intended effect, speaker/voice, English localization strategy, linked locators, and disposition.

Do not record every mundane statement as lore. Record facts whose mistranslation could change the
reader's understanding or make another translation inconsistent. Do not assume Japanese map/event
order is story chronology; use transfers, conditions, nearby commands, and corroborating source as
evidence, and keep story-state variants distinct.

After every frozen cluster has a semantic disposition, reconcile both ledgers before this focus can
be complete:

1. Group narrative anchors by canonical entity/concept and compare polarity, identity,
   relationship, title, place, quantity, chronology, and story-state qualifiers across distant
   files and context classes.
2. Group wordplay by source expression, shared mechanism, catchphrase, response/callback, and
   dependent clue or choice. Inspect every linked occurrence needed to judge whether the English
   setup and payoff still work together.
3. Search the entire dialogue scope for each confirmed contradiction or broken-joke signature and
   propagate findings as required by the common contract.
4. When the live dependency belongs to Database, Risky codes, or other translated game-data text,
   keep it read-only, record the exact cross-focus dependency, and carry it to the release gate.

A different English joke is acceptable when it preserves meaning, voice, comedic/rhetorical
function, and downstream dependencies. Literal wording that erases a demonstrable joke is not
automatically acceptable. Conversely, do not flag subjective funniness, an unproven possible pun,
or a preference for another localization strategy.

Report static blind spots explicitly, including wordplay dependent on omitted readings/furigana,
voice acting, images, animation, timing, or route order that the available files cannot prove.
Convert those blind spots into targeted playtests rather than guessed edits.

### Large-corpus semantic protocol

Complete the full mechanical scan before the first semantic wave. On an unchanged resumed corpus,
verify file/source checksums and reuse the completed mechanical result; after any edit or corpus
change, reparse and rerun the full scan before closing the next wave.

Use the validated manifest's frozen dialogue `review_sequence` before Wave 1:

For a representative spanning several context classes, use the lexicographically selected
representative locator's file/code/speaker/display-shape/length fields for queue ownership while
retaining and reviewing every other context facet as occurrence evidence.

Do not rebuild the queue from prose, a worker helper, filtered commands, strata, or risk scores.
Group by relative file, event code, speaker or empty, display shape, and length band only when
measuring context-class coverage or prioritizing attention within the current frozen wave. These
facets never change queue ownership, wave membership, or ordinal identity.

Compute the high-recall static risk features once during deterministic preprocessing. Include
mechanical flags plus cues for negation, quantities, conditions, temporal order, pronouns,
referents, kinship, glossary terms, short ambiguous Japanese, large length changes, inconsistent
clusters, choice polarity, speaker changes, lore-bearing assertions, deliberate ambiguity,
wordplay/joke reactions, catchphrases/callbacks, and control-code placement. Before each wave, overlay
only registry-dependent affected-family features and rank that wave's members; do not rescore the
entire unreviewed suffix. Inspect the highest-risk members of the current wave first, then review
every remaining member in frozen order. Risk ranking must not change wave membership, substitute for
review, or allow any member to be skipped. Record an explicit reviewed disposition for every
representative.

Review every frozen dialogue cluster across consecutive resumable waves:

- With 750 or fewer unique dialogue clusters, review all of them in one wave.
- With more than 750 clusters, review consecutive non-overlapping 500-pair waves plus the final
  partial wave until the frozen manifest is exhausted.
- Persist the checkpoint after each wave, but continue automatically in the same invocation.
  Resume in a later invocation only after a genuine runtime or tool interruption.
- Never treat anticipated context compaction, token usage, response size, elapsed time, corpus size,
  or remaining wave count as a genuine interruption. Continue across compaction and keep invoking
  the next wave while tools remain callable.
- Track clean-wave history as diagnostic evidence, not as permission to leave clusters unreviewed.
- Do not impose an arbitrary total-wave cap.
  If an actual runtime or tool limit prevents the next wave or checkpoint, report incomplete status
  and the exact unreviewed count.

For repeated clusters, retain all locator context facets and deterministically review every
risk-bearing materially distinct context class. These occurrence checks supplement representative
coverage; they do not inflate the unique-cluster count or replace a frozen wave member.

Dialogue status may be `complete - exhaustive` only when all frozen clusters were reviewed.
Report the exact reviewed count, zero unreviewed count, represented strata, context-class coverage,
wave history, issue-propagation totals, manifest checksum, dialogue review-contract ID, narrative
anchor count and reconciliation result, wordplay candidate/disposition counts, cross-focus
dependencies, dialogue context fingerprint, and static blind spots.
<!-- /qa-focus:dialogue -->

<!-- qa-focus:database -->
## Selected focus: Database files

Audit `_original` leaves in these canonical database files when present:

`Actors.json`, `Armors.json`, `Classes.json`, `Enemies.json`, `Items.json`, `MapInfos.json`,
`Skills.json`, `States.json`, `System.json`, and `Weapons.json`.

Include translated object/list fields such as names, nicknames, profiles, descriptions, messages,
UI terms, type labels, game title, and translated note content. Do not audit event-command lists in
this focus. If an unexpected command list appears inside a database file, report it as a scope
warning for classification rather than silently reviewing it here.

### Pair extraction

- For an `_original` object, recursively pair every string leaf with the value at the same path on
  its owning live object.
- Numeric keys in `_original` usually address list indexes in live `System.json` arrays and terms.
  Resolve them as indexes; preserve empty/reserved slots and report unsafe or missing counterparts.
- Keep entity identity (`id`, owning record name/type, and field) with every locator. Use related
  skills/items/states/classes and battle-message templates as context where terminology must agree.
- Treat note tags, formulas, and plugin markup as structured text: translate only the preserved
  display leaf and verify tags, delimiters, IDs, and script fragments remain intact.

Exclude all event codes, map display names, map event names, and translated map/plugin-note shapes;
those belong to other focuses.

Stratify the wave by filename, entity type, field name, record identity, and short/medium/long
length band. Prioritize glossary entities, similarly named levels/variants, battle terminology,
menu labels, parameter names, state messages, actor identity, number/element/type mismatches, and
inconsistent translations of one database term. Also prioritize lore-bearing profiles or
descriptions, paired or joke names, myth/folklore references, and database text required by a
dialogue setup, clue, or callback.

Review every frozen database cluster in consecutive waves before reporting this focus complete or
asking for fix approval.
The final database coverage report must show zero unreviewed clusters.
<!-- /qa-focus:database -->

<!-- qa-focus:risky-codes -->
## Selected focus: Risky event codes

Audit translated or translation-sensitive event commands 108/408, 111, 122, 320, 324, 325, 355,
356, 357, 655, and 657 in `Map*.json`, `CommonEvents.json`, and `Troops.json`. These shapes may mix
display text with logic, keys, scripts, plugin arguments, or filenames. Player-visible text must be
correct without changing runtime behavior.

### Pair extraction and runtime classification

- Codes 108/408: join a 108 comment and its contiguous 408 continuations. Inspect enabled plugin
  code to determine whether the block is editor-only, a plugin notetag, or player-visible. Audit
  displayed text; verify internal markers remain exact. Report uncertain visibility instead of
  guessing. A supported displayed 408 continuation may carry a scalar merged `_original`.
- Code 111: recursively pair `_original` object leaves to the same live parameter paths. Treat
  string comparisons as logic-sensitive. Verify translated comparison operands remain synchronized
  with every related assignment/use; never rewrite an internal key merely for fluency.
- Code 122: pair the translated inner quoted or backticked string in `parameters[4]`, excluding the
  script wrapper and trailing semicolon. Resolve the variable ID range from `parameters[0:2]` and
  verify whether the value is display text, a code-111 comparison value, or an internal/plugin key.
- Codes 355/655: assemble the full script block beginning at 355 with contiguous 655 lines. Pair
  only preserved display substrings, then verify quotes, escapes, interpolation, calls, and block
  structure. Do not treat continuation lines as separate missing translations.
- Code 356: pair preserved player-visible text inside the MV plugin-command string in
  `parameters[0]`; preserve command keywords, argument order, quoting, IDs, and internal keys.
- Code 357: recursively pair `_original` leaves with the same paths in the MZ command argument
  object, normally `parameters[3]`. Use plugin headers and enabled plugin source to distinguish
  displayed arguments from keys, enums, filenames, and serialized structures.
- Code 657: pair visible picture text in `parameters[0]`; distinguish it from filenames or internal
  identifiers using surrounding commands and plugin behavior.
- Codes 320/324/325: pair the visible actor name, nickname, or profile in `parameters[1]`. Resolve
  the actor ID and verify identity and glossary consistency.

Exclude codes 101/102/401/405 and all non-command database/object fields.

Stratify the wave by relative file, event code, plugin/script header or pattern, visibility class,
speaker/actor where applicable, and short/medium/long length band. Prioritize logic/display
ambiguity, code-111/code-122 synchronization, quoting/escaping, interpolation, plugin argument
schema, altered IDs/keywords, Japanese inside visible script strings, and values translated even
though they function as internal keys.

Treat `js/plugins.js` and plugin source as read-only evidence. If source itself needs translation,
report that the dedicated Plugin TL skill must handle it; do not expand this pass into plugin-file
translation.
<!-- /qa-focus:risky-codes -->

<!-- qa-focus:release -->
## Selected focus: Coverage and release gate

Run this focus last. It is a cross-cutting inventory and static release check, not another broad
line-by-line rewrite pass.

### Coverage partition

Inventory every `_original` leaf in every JSON file under `{{GAME_DATA_FOLDER}}` and assign it to
exactly one class:

1. Dialogue: event codes 101/102/401/405.
2. Database: canonical database files listed in the Database focus, excluding command lists.
3. Risky codes: 108/408, 111, 122, 320, 324, 325, 355/655, 356, 357, and 657.
4. Other translated game-data text: non-command leaves in maps/common events/troops, including map
   display names, translated event names, preserved plugin-note display substrings, and any
   supported shape not assigned above.
5. Unresolved/unsupported: any leaf whose live counterpart or runtime role cannot be proven.

Verify that every leaf has one class, no leaf is double-counted, and all JSON files parse—even files
without `_original`. Mechanically recheck structural integrity, live counterpart resolution,
runtime tokens/placeholders, obvious residue, and cross-class glossary/inconsistency signatures.
Do not repeat semantic review already evidenced by completed focus checkpoints or reports.

Semantically review only class 4 and actionable cross-class conflicts in this pass.
Use consecutive 500-pair waves until every frozen class-4 cluster has a reviewed disposition.
Treat class 5 as a coverage blocker until resolved or explicitly shown to be
non-translated/internal.
Stratify class 4 by file, JSON field/shape, runtime visibility, plugin marker where applicable, and
length band.

### Plugins and other assets

Use enabled plugins, scripts, and assets only to resolve runtime visibility or display behavior.
Do not translate `js/plugins.js`, plugin source, Ruby scripts, or images here. Their dedicated
Plugin TL, Ace Script TL, and Image TL skills remain separate QA surfaces. Report missing completion
evidence for those surfaces when relevant to release, without absorbing their work into this pass.

### Release decision

Reconcile the Database, Risky-code, and Dialogue focus reports/checkpoints. Require the Dialogue
evidence to declare `dialogue-narrative-wordplay-v1` and a context fingerprint matching the current
selected-game glossary, quirks, game skill, and custom overlays; an older or context-stale dialogue
report may supply matching mechanical inventory but not semantic-completion evidence. If any
required report or valid checkpoint is unavailable or incomplete, independently report that
focus's exact inventory count when possible and block release for missing semantic-completion
evidence. Never treat the final coverage pass as a substitute for one of the first three required
passes.

Reconcile the Dialogue narrative-anchor and wordplay ledgers against Database, Risky-code, and
class-4 findings. Verify that every recorded cross-focus dependency has a compatible disposition,
that source-supported lore facts do not conflict across classes, and that linked joke/clue setups
and payoffs still function. This is evidence reconciliation, not permission to repeat or silently
replace the owning focus's semantic review.

Static release approval requires:

- complete mechanical coverage and no unresolved/double-classified `_original` leaves;
- exhaustive completion or valid focus-specific semantic convergence for all four game-data classes;
- no unresolved Critical/High findings and no approved fix awaiting regression;
- for every focus that applied fixes, matching immutable final-map, registry-epoch, zero-new-locator
  propagation/validator, rebuilt-corpus, and durable post-fix regression evidence;
- explicit separation between static QA and runtime/playthrough confidence.

Recommend a focused playtest for repaired events, representative messages/choices/scrolling text,
name boxes, database menus and battle messages, risky plugin/script displays, control codes,
wrapping/pagination assumptions, plugin-derived class-4 text, and lore/wordplay blind spots that
depend on route order, omitted readings/furigana, voice acting, images, animation, or timing. State
whether release is blocked, conditionally allowed after named fixes/evidence, or statically allowed
with targeted runtime checks remaining.
<!-- /qa-focus:release -->
