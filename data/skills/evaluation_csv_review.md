# Review a Blinded Japanese-to-English Evaluation CSV

Review this exported evaluation CSV:

`{{BLIND_REVIEW_CSV}}`

## Important limitation

AI judging is not objective. You may share stylistic preferences, training biases, or failure
modes with the models that produced these translations. Treat this review as a useful second
opinion, not a replacement for a fluent human Japanese reviewer. State this limitation in your
final report.

## Preserve the blind

- Judge only the randomized candidate columns in the CSV.
- Do not open `blind_key.json` or other files to discover which model produced a candidate.
- Do not infer or speculate about model identity from writing style.
- Candidate labels may be shuffled independently on every row.

## Task

Read the CSV as UTF-8 with BOM support. It contains identifying/context columns such as
`segment_id`, `scene_id`, `stratum`, and Japanese `source`; randomized candidate columns such as
`A`, `B`, and `C`; followed by `ranking` and `notes`.

Review every row. Compare each candidate directly with the Japanese source and use the limited
scene/stratum metadata only as supporting context. Rank candidates in this order:

1. Fidelity: preserved meaning, intent, polarity, subject, quantity, relationships, and tone.
2. Runtime safety: preserved placeholders and RPG Maker control codes with sensible scope.
3. Contextual appropriateness: suitable speaker voice, register, terminology, and choice wording.
4. Natural English: clear, fluent dialogue without model commentary or unjustified additions.

Do not reward literalness by itself, and do not penalize a valid localization merely because you
prefer another style. Ignore tiny punctuation or wording preferences when meaning and voice are
equivalent.

For each row:

- Put every randomized candidate label in `ranking`, ordered best to worst with `>`.
  For three candidates, a strict ranking looks like `A>B>C`.
- Use `=` only for candidates that are genuinely equivalent. Examples: `A=B>C` for a tied
  best pair, `A>B=C` for a tied lower pair, and `A=B=C` when all candidates are equivalent or
  the available context cannot support a defensible distinction.
- Include every candidate label exactly once in each non-empty ranking.
- Add a short, evidence-based `notes` explanation. Avoid generic comments such as "sounds better."
- Never change source text, candidate text, identifiers, column order, or any other cell.

Create a sibling CSV whose filename ends in `.ai-reviewed.csv`; do not overwrite the original.
Preserve UTF-8 encoding, quoting, embedded newlines, and every row. Re-open the written file and
verify that every non-empty `ranking` contains every candidate-column label exactly once using
only `>` and `=`, and that the row count and all protected columns exactly match the source CSV.

Finally report:

- The reviewed output path.
- Total rows, fixed-sum ranking points per randomized label, unique first-place finishes,
  partial ties, and full ties. For three candidates, score strict ranks as 2/1/0 and average
  the occupied points for tied ranks (`A=B>C` gives 1.5/1.5/0; `A>B=C` gives 2/0.5/0.5;
  `A=B=C` gives 1/1/1).
- Any rows you could not judge safely.
- The explicit warning that this AI review may be biased and should be confirmed by a qualified
  human reviewer before making a high-stakes model choice.
