# QA Exported RPG Maker Translations — Focused Pass

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
</task_context>

## Bounded review contract

Keep this pass independent and measurable instead of widening it into a whole-game review.

- Inventory every `_original` leaf assigned to this focus and no others. If classification is
  uncertain, report the leaf as an unresolved scope/shape warning; do not silently absorb another
  pass.
- Mechanically check 100% of resolvable in-scope source/translation pairs.
- Deduplicate identical source/translation pairs for semantic review while retaining every locator
  and materially distinct context class.
- Review every frozen cluster before this focus may end or request approval.
  Use 500 pairs as the routine wave size and follow a selected focus's explicit small-corpus rule
  when it requires reviewing up to 750 pairs.
  After each wave, persist the checkpoint and continue immediately with the next non-overlapping
  wave from the same frozen manifest in the same invocation.
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
  Sampling, risk ranking, or consecutive clean waves cannot substitute for exhaustive coverage.

## Reproducible inventory and checkpoint

Do not stream thousands of raw JSON lines into the conversation. Build a compact manifest and use
short-lived helpers when useful.

- Identify a location by `relative file + canonical JSON path + SHA-256 of exact UTF-8 source`.
- Freeze the in-scope cluster universe before the first wave. Choose the lexicographically lowest
  stable identity as each cluster representative and order representatives by
  `SHA-256("rpgmaker-qa-focus-v1\0" + focus name + "\0" + representative identity)`.
- Interleave files and the focus-specific strata named below so one large file or shape does not
  consume the wave. Do not reshuffle on resume or after editing English.
- Save the ordered identities, locators, source hashes, dispositions, issue signatures, applicable
  focus-specific review-contract ID, and wave position in a checkpoint outside `{{GAME_ROOT}}`.
  Record the helper version or content hash and manifest checksum. Never place generated QA
  artifacts in the game folder or data folder.
- Reuse a valid checkpoint for this focus. Reject it and explain why if the focus, source hashes,
  manifest checksum, or applicable focus-specific review contract no longer matches. A selected
  focus may explicitly allow reuse of older mechanical inventory while requiring its semantic
  dispositions to restart. Keep checkpoints from other focuses separate.
- Display compact panes of roughly 75–150 rows with ordinal, locator count, risk reasons, source,
  and translation. Escape embedded newlines. Expand full locators and context only for candidates.

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

## Mechanical checks for every in-scope pair

1. Parse the containing JSON and verify the live counterpart, type, list/object shape, and non-empty
   output. Report unresolved or unfamiliar `_original` shapes instead of guessing.
2. Detect unchanged Japanese, unintended source-language residue, truncation, mojibake, model
   commentary, refusal text, Markdown fences, or pasted JSON fragments.
3. Compare runtime tokens and placeholders for loss, addition, duplication, malformed escaping,
   unsafe reordering, or changed scope. Include RPG Maker codes such as `\C[n]`, `\N[n]`, `\V[n]`,
   `\I[n]`, `\{`, `\}`, `\.`, `\|`, `\!`, `\>`, `\<`, and `\^`; custom backslash codes;
   `__PROTECTED_n__`; printf placeholders; interpolation; and meaningful HTML/plugin tags.
4. Verify semantic placement, not only token counts. Colors and font scopes must wrap the translated
   equivalent; icons and variables must remain beside what they modify; waits and pauses must keep
   their intended beat. Natural English word order does not require identical offsets.
5. Flag concrete number, quantity, polarity, pronoun, subject, speaker, terminology, quote, and
   punctuation damage; suspicious length changes; unrelated sources collapsed to generic output;
   or one source translated inconsistently where context does not justify it.
6. Check actual display constraints applicable to this focus. Use configured wrap widths and
   enabled plugin behavior when available. Record a proven auto-wrap or pagination exception once;
   do not keep raising overflow-only findings for that shape.

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
- **Medium**: evidence-backed context, consistency, fluency, tone, overflow, or demonstrably
  flattened humor/callback defect where the basic meaning remains sound.

Do not create Low findings for optional polish.

### Findings requiring action

Use a compact table with stable finding ID, severity, file + JSON path, event code/field, short
source, current translation, concrete evidence, issue, and proposed correction. Group identical
signatures while retaining representative locators and affected counts. Never dump full files.

### Focus status and next action

State `complete`, `incomplete - execution interrupted with clusters remaining`, or
`blocked - unresolved evidence or findings`.
Only the Coverage & release gate focus may make a whole-game release recommendation.
Ask for fix approval only when zero frozen clusters remain unreviewed.
If execution was interrupted or blocked, provide the checkpoint and exact resume position instead
of presenting a normal completion approval gate.
When coverage is complete, end with one focused approval question offering the relevant choices:

- Apply all high-confidence fixes found in this focus.
- Apply selected finding IDs only.
- Make no edits after the completed review.
- Stop with no edits.

Do not edit until the user approves.

## After approval

Edit only approved live translated values under `{{GAME_DATA_FOLDER}}` that belong to this focus.
Never modify or remove `_original`. Preserve JSON types, event commands, non-text fields, control
codes, placeholders, indentation, and encoding. Make the smallest supported change and do not edit
plugin/script source under `{{GAME_ROOT}}` from this game-data QA prompt.

Reparse every affected JSON file, rerun this focus's complete mechanical checks, rescan each
approved issue signature across all in-scope pairs until no new affected values appear, and confirm
no residue, token, display, or structural regression. Put edited identities in a regression queue;
do not count regression as a new semantic wave.
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
custom overlay, ordered by resolved path. Reuse prior dialogue semantic dispositions only when this
fingerprint also matches. If project guidance changed while the source manifest remained valid,
reuse the frozen manifest and mechanical results but reset all dialogue semantic dispositions and
both ledgers; new guidance can change lore, voice, and wordplay judgments even when Japanese and
English text are unchanged.

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

Construct one frozen dialogue order before Wave 1:

1. Group representatives by relative file. Within each file, group by event code, speaker or empty,
   display shape, and length band.
2. Sort each sub-stratum by mandatory-review status first and the stable selection key second, then
   interleave its sub-strata round-robin to create one deterministic queue per file.
3. Build the global order by repeatedly choosing the non-exhausted file with the smallest
   `consumed queue entries / total queue entries` ratio, breaking ties by relative filename, and
   taking its next representative. This keeps large maps from crowding out smaller files.

Before each wave, score the entire unreviewed frozen suffix with a high-recall risk overlay. Include
mechanical flags plus cues for negation, quantities, conditions, temporal order, pronouns,
referents, kinship, glossary terms, short ambiguous Japanese, large length changes, inconsistent
clusters, choice polarity, speaker changes, lore-bearing assertions, deliberate ambiguity,
wordplay/joke reactions, catchphrases/callbacks, and control-code placement. Inspect the
highest-risk members of the current wave first, then review every remaining member in frozen order.
Risk ranking must not change wave membership, substitute for review, or allow any member to be
skipped. Record an explicit reviewed disposition for every representative.

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
- explicit separation between static QA and runtime/playthrough confidence.

Recommend a focused playtest for repaired events, representative messages/choices/scrolling text,
name boxes, database menus and battle messages, risky plugin/script displays, control codes,
wrapping/pagination assumptions, plugin-derived class-4 text, and lore/wordplay blind spots that
depend on route order, omitted readings/furigana, voice acting, images, animation, or timing. State
whether release is blocked, conditionally allowed after named fixes/evidence, or statically allowed
with targeted runtime checks remaining.
<!-- /qa-focus:release -->
