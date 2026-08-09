# QA Exported RPG Maker Translations

<task_context>
Audit the translated RPG Maker JSON files in this detected game data folder:

`{{GAME_DATA_FOLDER}}`

The preserved Japanese source attached to each translated value as `_original` is authoritative
for source-versus-translation comparisons. Inspect every JSON file in this folder that contains
`_original`; use other JSON records in the same folder for structure and nearby event context.

Use the rest of this game folder as read-only context for scripts, plugins, event flow, assets,
per-game skills, and any other evidence needed to understand how text appears at runtime:

`{{GAME_ROOT}}`

Use this glossary as authoritative for names and terminology:

`{{VOCAB_FILE}}`

This is a post-export QA review of the playable game data. During the first pass, do not edit any
translation or modify any game file. Start immediately with the audit; do not ask the user to
choose files unless no translated JSON containing `_original` can be found.
</task_context>

## Required review model

Do not try to read thousands of raw lines sequentially into context. Build a compact inventory of
every `_original` leaf and its current translated counterpart, then combine exhaustive mechanical
checks with targeted semantic review.

- Mechanically check 100% of resolvable source/translation pairs.
- Deduplicate identical source/translation pairs and repeated issue signatures.
- Put mechanically flagged and glossary-bearing clusters in the mandatory semantic-review queue.
- Add deterministic stratified semantic-review waves across every file, event code or database
  field, speaker, and short/medium/long text band. Treat 500 unique pairs per wave as the routine
  target, not as the limit for the whole audit. Construct the waves from the canonical frozen
  manifest described below; do not hand-pick or reshuffle samples between runs.
- Review nearby event commands together when meaning, speaker, referent, or control-code placement
  depends on context.
- For clusters repeated across files, speakers, event shapes, or database fields, inspect their
  locator metadata for context diversity. Expand at least one occurrence from each materially
  distinct context class when the text is short, ambiguous, risk-flagged, or context-sensitive;
  do not assume one representative proves every occurrence is semantically correct.
- State exact coverage. Never imply that sampled semantic review covered every line.

Prefer a committed, tested DazedTL audit runner when one supports the required manifest schema.
Record its version or content hash. If no suitable runner exists, use a temporary script or compact
index and preserve the helper with the external checkpoint so the audit remains reproducible. Do
not leave generated QA artifacts in the game data folder or elsewhere in the game folder.

## High-throughput full-coverage review

Optimize the review representation before reducing scope. After building the frozen manifest,
create a compact, lossless review view backed by the manifest instead of repeatedly printing full
pair records as JSON. Each displayed row should normally contain only the frozen ordinal, repeated
locator count, risk reasons, source, and translation, with embedded newlines escaped onto one row.
Keep filenames, JSON paths, identities, strata, and complete flags in the manifest and expand them
only for entries that need investigation. Use panes of roughly 75–150 compact rows, adjusted to the
actual text length, and combine panes into routine 500-pair waves.

Before reviewing the first pane, score the entire unreviewed frozen suffix with a high-recall risk
overlay. Include existing mechanical flags plus heuristic cues for negation, numbers, quantities,
conditions, temporal order, pronouns, referents, kinship, glossary terms, short ambiguous text,
large length changes, and inconsistent source/translation clusters. Inspect the highest-risk rows
first, then scan every remaining row in the wave in frozen order. Risk ranking changes attention
order only: it must not change frozen wave membership, count as semantic review by itself, or allow
any row to be skipped. Record an explicit reviewed disposition for every wave representative.

Resolve likely defects in batches. Retrieve surrounding event commands, alternate translations of
the same source, glossary records, and authoritative database entries only for candidates that need
that evidence. Propagate all confirmed signatures corpus-wide, apply the approved fixes together,
then run one complete regression cycle for the remediation wave. Do not rerun the same expensive
inventory or print verbose progress between individual findings when its cached inputs are still
valid. Always perform the required full reparse and mechanical/regression checks before closing the
wave.

Before checking terminology, load `{{VOCAB_FILE}}`, confirm that it is readable, and build a
deduplicated source-term to approved-English index. Treat it as authoritative for applicable
names and gameplay terms, while rejecting substring collisions and contextually different senses.
Report the glossary path, whether it loaded, its usable entry count, and the number of confirmed
violations. If the user approves a deliberate style or terminology exception, record it in the
temporary manifest and do not raise it again unless its context or spelling materially changes.

## Memory-bounded review and recovery

Keep the full audit reproducible without retaining a large editor, terminal, or helper-process
footprint. The frozen manifest on disk is the source of truth; retain compact identifiers,
dispositions, risk reasons, and checksums there rather than full parsed JSON or expanded candidate
text in memory.

- Process a single compact pane (normally 75–150 rows) and its targeted context at a time. Keep
  only the current wave, the current high-risk subset, and evidence for unresolved candidates in
  memory; retrieve surrounding commands and alternate occurrences on demand, then discard them.
- Use ranked review: handle high-risk rows first with contextual expansion, then review lower-risk
  rows in frozen order through compact direct comparisons and targeted contextual spot checks
  across strata. Do not expand full event context for every apparently sound low-risk row, but
  record a review disposition for each representative.
- Batch confirmed fixes and validation work at the remediation-wave level. Do not reparse the
  entire corpus after each individual edit when the same cached manifest remains valid; perform
  the required complete reparse and regression cycle before closing the batch.
- Use short-lived helper processes for inventory generation, scoring, validation, and regression.
  Have each process write its compact result or checkpoint and exit before the next expensive
  phase so its parsed objects and intermediate data are released.
- Never dump a complete manifest, JSON file, candidate corpus, or verbose per-row progress into
  the terminal or agent conversation. Emit compact totals, the active pane, confirmed findings,
  and bounded diagnostic excerpts only. Cap query output before displaying it.
- After every closed wave and before a potentially expensive operation, save a validated manifest
  checkpoint containing the ordered identities, reviewed dispositions, issue signatures, and
  checksum. On interruption or restart, reload and verify that checkpoint; do not rebuild or
  reprint the corpus merely to resume.
- If host memory pressure or editor stutter appears, first checkpoint the current state, let active
  helpers exit, clear no-longer-needed in-memory candidate/context collections, and resume from
  the manifest with smaller panes or output caps. Do not compensate by reducing coverage,
  skipping contextual evidence, or altering frozen wave membership.

Memory-bounded operation changes storage and presentation only. Every frozen representative still
needs a recorded review disposition, and risk ranking remains an attention order rather than a
substitute for semantic coverage.

## Actionability threshold

Preserve the current live text unless there is concrete evidence that it is wrong. Treat a finding
as actionable only when the source, glossary, runtime behavior, repeated context, or display rules
demonstrate a specific defect and support a specific correction. Actionable defects include changed
or missing meaning, wrong names or gameplay terms, accidental source residue, broken structure or
runtime tokens, clear speaker/referent/polarity/number errors, and demonstrable display damage.

Do not report or edit preference-only differences. In particular, ignore:

- Translator credits, patch/mod labels, version notes, cheat/debug hotkeys, and similar deliberate
  metadata added outside the source when they are coherent and do not break runtime behavior.
- Valid transliterations, loanwords, interjections, honorific choices, dialect, stretched vowels,
  punctuation style, or other deliberate voice choices.
- Alternative natural phrasings, literal-versus-localized wording, or optional fluency polish when
  the current text preserves the meaning and works in context.

Do not infer that source-absent text is accidental merely because it is absent from `_original`.
Require evidence such as model commentary, corruption, irrelevant content, contradictory context,
or runtime harm. When intent remains genuinely uncertain, leave the value unchanged and omit it
from actionable findings; mention it only as a concise non-actionable limitation if it could hide a
material defect. Never let stylistic or intentional differences reset semantic convergence.

## Iterative semantic convergence

Keep a temporary review manifest outside the game folder. Identify reviewed locations by stable
`relative file + JSON path + source hash`, independent of the current English, so an edited value
does not re-enter a later discovery wave. Canonicalize those components as relative POSIX path,
canonical JSON path, and SHA-256 of the exact UTF-8 source. Track deduplicated source/translation
pairs separately for cluster coverage and propagate each reviewed judgment to every equivalent
locator.

Freeze the complete cluster universe before Wave 1. For each cluster, choose the lexicographically
lowest stable identity as its representative and compute its selection key as
`SHA-256("rpgmaker-qa-v3\0" + representative identity)`. For new v3 audits, construct the frozen
order hierarchically so one dominant file cannot consume the final waves:

1. Group representatives by file. Within each file, group by the sub-stratum tuple of
   `event-code-or-database-field, speaker-or-empty, length-band`.
2. Sort each sub-stratum by mandatory-review status first and selection key second, then interleave
   the sub-strata round-robin to create one deterministic queue per file.
3. Build the global order by repeatedly selecting the non-exhausted file with the smallest
   `consumed queue entries / total queue entries` ratio, breaking ties by relative filename, and
   taking its next representative. This keeps each substantial file advancing through roughly the
   same percentage of its queue across the audit instead of exhausting smaller files early.

Split that one frozen order into consecutive waves. Save and report a SHA-256 checksum of the
ordered representative-identity list. Reuse any valid saved manifest on resumed QA, including a
v2 manifest; never regenerate it merely because the algorithm changed or English values were
edited. This fixed construction is the release-readiness sampling order; additional contextual
leads may be reviewed, but they do not replace its wave entries.

For every cluster, retain all locator context facets: relative file, event code or database field,
speaker, display shape, and nearby-command signature when available. The representative supplies
base pair coverage. When those facets reveal materially distinct contexts, create a deterministic
context-diversity queue using the lexicographically lowest locator in each distinct context class.
Review all risk-bearing classes and record how many total classes were checked. Treat these checks
as occurrence-context coverage, not additional unique-cluster coverage.

Before presenting the first findings report, run non-overlapping discovery waves until the audit
converges, exhausts the frozen manifest, or encounters an actual runtime/tool limit:

- Review all unique pairs when there are 750 or fewer.
- For projects with 751–2,500 unique pairs, run at least two 500-pair waves. For projects with more
  than 2,500, always complete five 500-pair waves before convergence is possible, even if earlier
  waves appear clean.
- Close each wave only after corpus-wide propagation reaches closure. A wave is clean only when it
  produces both zero new actionable Critical/High/Medium signatures and zero newly confirmed live
  values for any actionable signature. A new affected value of an existing signature resets the
  clean-wave count. Dismissed stylistic or intentional differences do not reset it.
- After the required minimum, require the final two consecutive waves to be clean. If either of the
  last two required waves is not clean, continue with non-overlapping 500-pair extension waves
  from the frozen order until two consecutive waves are clean or every unique pair is reviewed.
  Treat 2,500 pairs as a routine reporting checkpoint, not permission to make a false readiness
  claim. If an actual runtime or tool limit prevents extension, report non-convergence and the
  exact remaining count.
- Never reuse a reviewed stable identity in a discovery wave. Put edited identities in a separate
  regression queue instead.

Each wave must retain the frozen stratification. Record its unique-pair count, overlap with earlier
waves, represented strata, new issue signatures, new affected live values, clean-wave count, and
manifest checksum. A wave is not clean merely because its newly confirmed values share a finding
signature already known from an earlier wave.

## Corpus-wide issue propagation

When a defect is confirmed, immediately search all resolvable pairs for the broader issue
signature before continuing sampling. Repeat propagation until a full search adds no affected live
values, then mark the closure set reviewed before judging whether the wave is clean. Do not limit
propagation to an identical Japanese sentence.
Inspect, as applicable:

- Every occurrence and inflection of the implicated source and English gameplay term.
- The authoritative database entity, glossary entry, state, item, skill, location, or character.
- Identical-source clusters, neighboring levels/variants, tutorial copies, repeated maps, and
  related choice text.
- The same pronoun/subject pattern, polarity, number, control-code scope, or formatting defect.

Group confirmed matches under one finding ID and mark their stable identities reviewed. Do not
automatically treat lexical matches as defects; verify their source meaning and runtime context.

## Pair extraction

Preserve a stable locator for every pair: relative filename plus JSON path, and event code when
present.

- For database objects and event codes 111/357 with an `_original` object, pair each string leaf
  with the value at the same path on the owning object. Numeric string keys in `_original` usually
  address list indexes in the live object, as in `System.json` lists, `terms` arrays, and event
  command `parameters` arrays. These event-command objects are sparse: only translated paths are
  present.
- For event code 102, pair each `_original[index]` choice with `parameters[0][index]`.
- For scalar event-command `_original` values, resolve the live value by command shape:
  - 401, 405, 657, 356, 108, 355, 655: visible text or containing script in `parameters[0]`.
  - 408: comment continuation in `parameters[0]`; classify its runtime visibility from the
    preceding 108 block and enabled plugin code before treating it as internal or player-facing.
  - 101: visible name field in `parameters[4]`, or `parameters[0]` for the variable-name form.
  - 122: translated inner quoted/backticked string in `parameters[4]`, excluding its script
    wrapper and trailing semicolon.
  - 320, 324, 325: visible value in `parameters[1]`.
- A scalar `_original` on the first command of a merged 401/405/408 group may represent multiple
  live lines. Rejoin the contiguous translated display commands before comparing it; do not report
  the continuation commands as missing translations.
- If a pair cannot be resolved safely, report an extractor/shape warning. Do not guess or mutate
  that record.

## Exhaustive mechanical checks

Check every resolvable pair for:

1. Invalid JSON, damaged command/list/object structure, missing live counterparts, wrong choice
   counts, empty output, or accidental type changes.
2. Japanese or other source-language residue, unchanged source copied as translation, truncation,
   mojibake, model commentary, refusal text, Markdown fences, or JSON fragments inside player text.
   Do not count unchanged code-408 values as player-facing residue when they are editor-only.
   When enabled plugin code consumes a 108/408 comment block and displays its content, audit that
   content as player-facing text. Report uncertain code-408 groups separately instead of guessing.
3. Lost, added, duplicated, reordered, malformed, or altered runtime tokens. Include RPG Maker
   control codes such as `\C[n]`, `\N[n]`, `\V[n]`, `\I[n]`, `\{`, `\}`, `\.`, `\|`, `\!`,
   `\>`, `\<`, and `\^`; custom backslash codes; `__PROTECTED_n__`; printf-style placeholders;
   interpolation; and meaningful HTML/plugin tags.
4. Control-code scope and placement, not just token counts. Color/font openers and resets must wrap
   the translated equivalent of the same source span. Name colors must remain around the name;
   icon and variable codes must stay beside the phrase they modify; waits and pauses must retain
   their intended beat. Do not demand identical character offsets because English length differs.
5. Suspicious length ratios, repeated generic output, many unrelated sources collapsed to one
   translation, one source translated inconsistently, broken speaker tags, inconsistent glossary
   terms, changed numbers, polarity/negation risk, pronoun or subject flips, and punctuation or
   quote damage.
6. Likely display overflow using the configured wrap widths when available. Distinguish an actual
   overlong display line from intentional newlines or non-dialogue script text. If runtime evidence
   or the user confirms that a command shape such as code 401 automatically paginates safely,
   record that exception once and suppress overflow-only findings for that shape; continue checking
   the same values for semantic and control-code defects.

Treat token spelling case-insensitively only where RPG Maker itself does; preserve the spelling and
escaping already used by the file. Do not flag natural English word order merely because an inline
token moved, provided it still modifies the same semantic phrase and its runtime order is safe.

## Targeted semantic review

Compare Japanese and English for fidelity, fluency, tone, and context. Prioritize candidates with:

- Negation, conditionals, quantities, dates, choices, objectives, or gameplay instructions.
- Pronouns, omitted subjects, kinship, speaker changes, or third-person self-reference.
- Names and terms missing from or conflicting with the glossary.
- Very short ambiguous Japanese, unusually large length changes, or awkward literal English.
- Sex, violence, comedy, dialect, honorifics, emotional intensity, and other register-sensitive
  language.
- Mechanical warnings, inconsistent translation clusters, or context-dependent control codes.

Use the source and surrounding event context as evidence. Do not call a translation wrong solely
because another valid wording is possible. Exclude subjective polish and plausible intentional
localization choices from findings rather than assigning them a severity.

## Static QA boundary and runtime handoff

Do not equate static corpus coverage with runtime or playthrough coverage. After static convergence,
recommend a separate targeted playtest covering the most heavily repaired events, representative
message and choice shapes, name boxes, control-code behavior, wrapping exceptions, and any
engine-specific pagination assumptions. Do not launch the game or create saves/configuration under
this skill unless the user separately authorizes that phase and its filesystem side effects.

Report static readiness and runtime confidence separately. A complete static audit may support a
release recommendation while still naming focused playtest scenarios that remain unverified.

## Converged audit output and approval gate

Do not edit during discovery. Complete the convergence loop, exhaust the manifest, or report the
actual runtime/tool limit before returning these sections:

### QA coverage

- Files found / files parsed
- `_original` leaves found
- Pairs mechanically checked and unresolved pairs
- Unique pairs/clusters
- Pairs semantically reviewed, sampling method, and strata represented
- Repeated-pair context classes found and context classes reviewed
- Per-wave coverage, overlap, new actionable findings, clean-wave count, and convergence status
- Audit runner version or helper content hash and checkpoint schema
- Any blind spots

### Findings summary

Count findings by severity and category:

- **Critical**: invalid JSON/structure or runtime-breaking token corruption.
- **High**: clear mistranslation, missing content, wrong control-code scope, source residue, or
  glossary/name failure.
- **Medium**: clear, evidence-backed context, consistency, fluency, tone, or overflow defect that
  does not rise to High severity.

Do not count or report optional polish as Low findings. The QA target is incorrect text, not a list
of stylistic alternatives.

### Findings requiring action

Show a compact table with stable IDs, severity, file + JSON path, event code/field, short original,
current translation, concrete evidence, issue, and proposed correction. Include every Critical and
High finding when practical. If many share one cause, group them, show representative locators and
the total affected count. Include Medium findings only when they meet the actionability threshold.
Never dump whole JSON files or add preference-only examples.

### Recommendation

Say whether playtesting/release should be blocked, conditionally allowed after listed fixes, or
allowed because no actionable defects remain. End with one focused approval question offering:

- Continuous remediation: apply all current and subsequently discovered high-confidence fixes in
  the same game-data scope, then continue regression and fresh discovery waves until convergence.
- Selected finding IDs only.
- No edits.

Stop and wait for approval.

## After approval

Edit only the approved live translated values under `{{GAME_DATA_FOLDER}}`.

- Never modify or remove `_original`.
- Preserve JSON types, event commands, non-text fields, control codes, placeholders, indentation,
  and encoding. Make the smallest possible changes.
- Follow the glossary and nearby context. Do not rewrite acceptable lines outside the approved
  scope.
- Reparse every JSON file, rerun all mechanical checks, rescan every approved issue signature, and
  check that no Japanese residue, token mismatch, or display regression was introduced.
- Move edited stable identities through the regression queue; do not count regression review as
  fresh semantic coverage.
- Run another non-overlapping discovery wave after fixes. If it finds a new actionable defect,
  propagate that signature corpus-wide and reset the clean-wave count.
- Under continuous-remediation approval, apply new high-confidence fixes that remain within the
  approved game-data scope and repeat. Leave non-actionable or uncertain text unchanged and pause
  for anything outside that scope. Without continuous approval, report new findings and ask before
  editing.
- Report files and finding IDs fixed, remaining risks, total unique semantic coverage, wave
  history, convergence status, and final game-data QA readiness. Never claim readiness without
  meeting the convergence criteria.
- Do not modify anything outside the detected game data folder. The rest of the game is context
  only.
