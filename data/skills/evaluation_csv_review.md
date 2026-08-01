# Review a Blinded Japanese-to-English Evaluation CSV

Review this exported evaluation CSV:

`{{BLIND_REVIEW_CSV}}`

Before judging, read these model-blind snapshots from the evaluation run:

- Effective translation system prompt: `{{REVIEW_SYSTEM_PROMPT}}`
- Matched game glossary context: `{{REVIEW_GLOSSARY}}`
- Matched Japanese SFX reference suggestions: `{{REVIEW_SFX_REFERENCE}}`

Treat the system prompt's translation requirements and the glossary's approved names and terms
as authoritative review criteria. Penalize candidates that violate them when the relevant rule or
term applies. These snapshots contain the exact merged system instructions and glossary context
used by the normal translation engine for the reviewed samples.
Treat the SFX snapshot only as contextual possibilities. It is not authoritative wording, and
candidates may choose a different natural rendering when supported by the scene.

## Important limitation

AI judging is not objective. You may share stylistic preferences, training biases, or failure
modes with the models that produced these translations. Treat this review as a useful second
opinion, not a replacement for a fluent human Japanese reviewer. State this limitation in your
final report.

## Preserve the blind

- Judge only the randomized candidate columns in the CSV.
- Do not open `blind_key.json` or other files beyond the CSV and the three review-context snapshots
  above to discover which model produced a candidate.
- Do not infer or speculate about model identity from writing style.
- Candidate labels may be shuffled independently for every sample row.

## Task

Read the CSV as UTF-8 with BOM support. Each row is one complete review sample. It contains
identifying/context columns such as `sample_id`, `scene_id`, `stratum`, `line_count`, and
`segment_ids`; a Japanese `source` block; randomized candidate blocks such as `A`, `B`, and `C`;
followed by three quality-ranking columns, the overall `ranking`, and `notes`. The source and
candidate blocks are JSON arrays whose entries are aligned in order.

Review every sample row as a whole. Compare each candidate's complete ordered translation block
with the complete Japanese source block and use the limited scene/stratum metadata only as
supporting context. Do not rank or score individual lines separately. Judge how well each block
maintains context, speaker continuity, terminology, tone, and relationships across its lines.
Rank candidate blocks in this order:

1. Fidelity: preserved meaning, intent, polarity, subject, quantity, relationships, and tone.
2. Runtime safety: preserved placeholders and RPG Maker control codes with sensible scope.
3. Contextual appropriateness: suitable speaker voice, register, terminology, and choice wording.
4. Natural English: clear, fluent dialogue without model commentary or unjustified additions.

Do not reward literalness by itself, and do not penalize a valid localization merely because you
prefer another style. Ignore tiny punctuation or wording preferences when meaning and voice are
equivalent.

For each sample row:

- Fill all four ranking columns using every randomized candidate label, ordered best to worst
  with `>`. For three candidates, a strict ranking looks like `A>B>C`:
  - `meaning_accuracy_ranking`: fidelity to meaning, intent, polarity, subjects, quantities,
    relationships, and tone. Do not reward literal wording by itself.
  - `glossary_prompt_ranking`: compliance with applicable system-prompt requirements and the
    glossary's approved names and terms.
  - `natural_contextual_ranking`: fluent English, suitable speaker voice and register, and
    continuity across the complete sample.
  - `ranking`: best overall, applying the priority order above, including runtime safety.
- Use `=` only for candidates that are genuinely equivalent. Examples: `A=B>C` for a tied
  best pair, `A>B=C` for a tied lower pair, and `A=B=C` when all candidates are equivalent or
  the available context cannot support a defensible distinction.
- Include every candidate label exactly once in every ranking column.
- Add a short, evidence-based `notes` explanation about the block as a whole. You may cite a
  specific line as evidence, but do not create separate line-level rankings. Avoid generic
  comments such as "sounds better."
- Never change source text, candidate text, identifiers, or column order. Edit only the four
  ranking columns and `notes`.

Create a sibling CSV whose filename ends in `.ai-reviewed.csv`; do not overwrite the original.
Preserve UTF-8 encoding, quoting, embedded newlines, and every row. Re-open the written file and
verify that every quality and overall ranking contains every candidate-column label exactly once
using only `>` and `=`, and that the row count and all protected columns exactly match the source
CSV.

Finally report:

- The reviewed output path.
- Total sample rows and source lines; fixed-sum points per randomized label for Meaning Accuracy,
  Glossary & Prompt, Natural & Contextual, and Best Overall; plus overall unique first-place
  finishes, partial ties, and full ties. For three candidates, score strict ranks as 2/1/0 and average
  the occupied points for tied ranks (`A=B>C` gives 1.5/1.5/0; `A>B=C` gives 2/0.5/0.5;
  `A=B=C` gives 1/1/1). Apply that whole-sample award once for every source line shown in
  `line_count` when calculating total points; do not make separate line-level judgments.
- Any rows you could not judge safely.
- The explicit warning that this AI review may be biased and should be confirmed by a qualified
  human reviewer before making a high-stakes model choice.
