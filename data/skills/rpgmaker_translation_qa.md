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
- Risk-score the remaining pairs and semantically review the highest-risk clusters first.
- Add a deterministic stratified sample across every file, event code or database field, speaker,
  and short/medium/long text band. Prefer at least one representative from every stratum; cap a
  routine first-pass semantic sample near 500 unique pairs unless severe problems justify more.
- Review nearby event commands together when meaning, speaker, referent, or control-code placement
  depends on context.
- State exact coverage. Never imply that sampled semantic review covered every line.

Use a temporary script or compact index when useful. Do not leave generated QA artifacts in the
game data folder or elsewhere in the game folder.

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
   overlong display line from intentional newlines or non-dialogue script text.

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
because another valid wording is possible. Separate definite defects from subjective polish.

## First-pass output and approval gate

Do not edit during the first pass. Return these sections:

### QA coverage

- Files found / files parsed
- `_original` leaves found
- Pairs mechanically checked and unresolved pairs
- Unique pairs/clusters
- Pairs semantically reviewed, sampling method, and strata represented
- Any blind spots

### Findings summary

Count findings by severity and category:

- **Critical**: invalid JSON/structure or runtime-breaking token corruption.
- **High**: clear mistranslation, missing content, wrong control-code scope, source residue, or
  glossary/name failure.
- **Medium**: likely context, consistency, fluency, tone, or overflow problem needing judgment.
- **Low**: optional polish only.

### Findings requiring action

Show a compact table with stable IDs, severity, file + JSON path, event code/field, short original,
current translation, issue, and proposed correction. Include every Critical and High finding when
practical. If many share one cause, group them, show representative locators and the total affected
count. Limit Medium/Low examples to the most useful representatives. Never dump whole JSON files.

### Recommendation

Say whether playtesting/release should be blocked, conditionally allowed after listed fixes, or
allowed with only optional polish remaining. End with one focused approval question offering to
apply all Critical/High-confidence fixes, selected finding IDs, or no edits.

Stop and wait for approval.

## After approval

Edit only the approved live translated values under `{{GAME_DATA_FOLDER}}`.

- Never modify or remove `_original`.
- Preserve JSON types, event commands, non-text fields, control codes, placeholders, indentation,
  and encoding. Make the smallest possible changes.
- Follow the glossary and nearby context. Do not rewrite acceptable lines outside the approved
  scope.
- Reparse every touched JSON file, rerun all mechanical checks on touched records, and check that
  no new Japanese residue or token mismatch was introduced.
- Report files and finding IDs fixed, remaining risks, and final game-data QA readiness.
- Do not modify anything outside the detected game data folder. The rest of the game is context
  only.
