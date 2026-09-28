# Review a Blinded Japanese-to-English Evaluation CSV

Review this exported evaluation CSV:

`{{BLIND_REVIEW_CSV}}`

Read each row's `context` JSON before judging. It contains the exact preceding Japanese
`history`, translation `system`, matched `glossary`, and `sfx_reference` supplied for that
sample. History provides context; do not score it as additional lines. Keep context scoped
to its sample instead of importing facts or glossary requirements from other rows.

For legacy CSVs without a context column, read these model-blind snapshots:

- Translation system prompt: `{{REVIEW_SYSTEM_PROMPT}}`
- Glossary context: `{{REVIEW_GLOSSARY}}`
- SFX suggestions: `{{REVIEW_SFX_REFERENCE}}`

Treat the applicable translation prompt and glossary's approved names and terms as
authoritative review criteria. Penalize violations when a rule or term applies. For modern
CSVs the row's context takes precedence over the aggregate snapshots. SFX references are
contextual possibilities, not authoritative wording; accept other scene-supported renderings.

## Limitations and blinding

AI judging is not objective. You may share stylistic preferences, training biases, or failure
modes with the candidate models. This review is a second opinion, not a replacement for a
qualified human Japanese reviewer. State this limitation in your final report.

- Judge only randomized candidate columns. Labels may shuffle independently for each row.
- Do not open `blind_key.json`, state, manifests, other reviewed CSVs, or other run files.
  Only the supplied CSV and the three snapshots above are authorized review inputs.
- Do not infer or speculate about model identity from writing style.
- For an independent judge check, use a fresh session without previous verdicts. Apply the
  same rubric rather than seeking agreement with an earlier judge.

## Review complete blocks

Read the CSV as UTF-8 with BOM support. Each row is one complete sample. `source` and
candidate columns such as A/B/C are JSON arrays aligned in order. Modern CSVs also contain
protected `review_id`, `context`, and `identical_candidates` fields.

Compare each complete ordered translation block with the Japanese source and its preceding
history. Assess context, speaker continuity, terminology, tone and relationships across lines.
Do not rank or score individual lines separately. Use scene/stratum metadata only as context.

Apply these priorities: fidelity to meaning, intent, polarity, subjects, quantities,
relationships and tone; runtime safety including placeholder/control-code scope; contextual
voice and terminology; then natural English. Do not reward literal syntax or invented wit,
slang, hostility, or explanations. Natural delivery of source-supported attitude and subtext
is part of fidelity. Preserve formal, awkward, restrained and distinctive speech where
evidenced. Ignore tiny punctuation or wording preferences when meaning and voice are equivalent.

For each sample:

- Set `status` to `judged` when a defensible judgment is possible. Use `insufficient_context`
  when missing context prevents judgment, or `needs_human_review` when ambiguity or your
  Japanese understanding makes judgment unsafe. In either abstention, leave ALL four rankings
  blank and explain the issue in `notes`. Abstentions earn no points and are not ties.
  For legacy CSVs without status fields, leave rankings blank for unsafe samples and list
  them in the report; do not add columns.
- On judged rows, fill `meaning_accuracy_ranking` for meaning and tone, `glossary_prompt_ranking`
  for applicable terminology and prompt rules, `natural_contextual_ranking` for fluency and
  voice, and `ranking` for overall quality using the priorities above, including runtime safety.
- Include every candidate label exactly once in each judged ranking. Use `>` best to worst
  and `=` for genuine equivalence: `A>B>C`, `A=B>C`, `A>B=C`, or `A=B=C`. Do not force small
  stylistic differences into strict rankings, or use a tie to hide an inability to judge.
- `identical_candidates` groups exact output duplicates. Keep each group tied in all
  dimensions. Fully identical rows are prefilled as ties; retain equality unless abstaining.
  Equality does not establish correctness: identical candidates may share serious errors.
- Fill `error_evidence` as a JSON object with every candidate label mapped to an array.
  Use empty arrays when no concrete error is identified. Each error object requires
  `category` (meaning, omission, addition, terminology, voice, grammar, runtime), `severity`
  (minor, major, critical), `line` (1-based within the sample), `source_quote`,
  `translation_quote`, and `explanation`. Both quotes must be nonempty exact substrings of
  the indicated lines; for an omission, quote the affected translated clause. These are
  evidence locations, not line scores. Minor means local awkwardness without substantial
  meaning change; major alters meaning, relationships, required terminology, or important
  voice; critical makes the block unusable or breaks essential runtime behavior. Do not mark
  valid stylistic alternatives as errors. Confidently identified major errors can be judged
  and will also be flagged for qualified human follow-up.
- Add concise block-level `notes` with specific evidence for meaningful distinctions. Avoid
  generic claims like "sounds better." Explain uncertain interpretations instead of inventing
  context. Every strict distinction should have a defensible meaning, compliance or voice basis.
- Edit only the four rankings, `status`, `error_evidence`, and `notes` where present. Never
  change source/candidate text, identifiers, context, duplicate groups, rows or column order.

## Save and verify

Create a sibling filename ending in `.ai-reviewed.csv`; never overwrite the original.
Preserve UTF-8 encoding, quoting and embedded newlines. Reopen it and verify every judged
ranking contains every label exactly once with only `>`/`=` separators; abstention rankings
are blank; evidence quotes match their lines; and every protected column and row matches
the original exactly.

Report the output path, total samples/source lines, judged and abstention counts, full and
partial ties, and major/critical findings with sample IDs. List any samples you could not
judge safely. Do not sum points or wins by A/B/C across rows: those labels change identity.
The application privately maps candidates on import and computes line-weighted Borda points,
category results, pairwise wins/ties/losses, and scene-bootstrap intervals. Do not inspect
the key to calculate model scores yourself.

Explicitly warn that the AI review may be biased and should be confirmed by a qualified
human Japanese reviewer before a high-stakes model choice.
