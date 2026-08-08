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
- State exact coverage. Never imply that sampled semantic review covered every line.

Use a temporary script or compact index when useful. Do not leave generated QA artifacts in the
game data folder or elsewhere in the game folder.

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
`SHA-256("rpgmaker-qa-v2\0" + representative identity)`. Assign the representative a primary
stratum tuple of `file, event-code-or-database-field, speaker-or-empty, length-band`. Group by that
tuple, sort tuple names lexicographically, sort each group by mandatory-review status first and
selection key second, then interleave the groups round-robin while skipping exhausted groups.
Split that one frozen order into consecutive waves. Save and report a SHA-256 checksum of the
ordered representative-identity list. Reuse the manifest on resumed QA; never regenerate it merely
because English values were edited. This fixed construction is the release-readiness sampling
order; additional contextual leads may be reviewed, but they do not replace its wave entries.

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

- For database objects with an `_original` object, pair each string leaf with the value at the
  same path on the owning object. Numeric string keys in `_original` usually address list indexes
  in the live object, as in `System.json` lists and `terms` arrays.
- For event code 102, pair each `_original[index]` choice with `parameters[0][index]`.
- For scalar event-command `_original` values, resolve the live value by command shape:
  - 401, 405, 657, 356, 108: visible text in `parameters[0]`.
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

## Converged audit output and approval gate

Do not edit during discovery. Complete the convergence loop, exhaust the manifest, or report the
actual runtime/tool limit before returning these sections:

### QA coverage

- Files found / files parsed
- `_original` leaves found
- Pairs mechanically checked and unresolved pairs
- Unique pairs/clusters
- Pairs semantically reviewed, sampling method, and strata represented
- Per-wave coverage, overlap, new actionable findings, clean-wave count, and convergence status
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
