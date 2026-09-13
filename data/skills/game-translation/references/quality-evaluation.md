# Translation Quality Evaluation

Every automated check can pass on a translation that is wrong. `訂正する` ("go back and re-enter") came back as **"Correct"**: English, right length, no placeholders, no residual Japanese, and it sends the player the opposite direction from the button's actual target (`references/llm-pipeline.md`, "What validation cannot catch").
Validation proves the *shape* is right and never the meaning.
Quality therefore needs its own pass, its own sampling method, and its own scoring - and it must be reported as a separate number from the validity rate, or the two get conflated and a 99% "pass" rate ships a mistranslated plot.

**Reference implementation:** `DAZEDTL_ROOT/util/evaluation.py`
(4,127 lines), with its operator view in `gui/evaluation_tab.py` (3,428 lines) and the
reviewer prompt in `data/skills/evaluation_csv_review.md`. Everything below is
distilled from it, so go there for the parts this file compresses.

Related: `glossary-and-prompts.md` for the review-context export and what each
model-blind snapshot may see, and `llm-pipeline.md` for the repair-oriented review
passes that run inside the translation loop.

This file covers: the two-gate split, how to *select* what to review when the corpus is 48,000 lines, the blind ranking rubric, how rankings become a score, repeatability as a distinct metric, how to re-import a judged file without trusting it, and what a verdict is actually worth.

---

## 1. Two gates, never one

**Keep the mechanical gate and the quality judgement in separate columns, and exclude lines that fail the gate from judging rather than ranking them last.** A model that drops `\C[3]` already fails placeholder validation. Letting the judge also rank it last on prose double-counts one defect and hides whether its writing was good.

Four automatic checks per returned line:

| Check | Runs against | Failure |
|---|---|---|
| Placeholder validation | **protected** source vs **raw** translation | per-placeholder `expected N, found M` |
| Control-code validation | original source vs **restored** translation | code set changed |
| Hard content failure | translation | too short to carry meaning, runaway repetition, residual source-language text |
| Warnings (non-blocking) | translation | increments `warning_segments`, leaves `valid=True` |

Warning triggers worth encoding, all non-blocking:

```
len(out) == 1 and len(src) > 3  and "\\" not in src   # 1 char out, no \X[ code in source
len(out) <= 2 and len(src) > 10
re.search(r"(.)\1{44,}", out)                          # runaway character repetition
```

**Label the validity rate honestly everywhere it is displayed**, in the UI, in the report, in the commit message:

```
Lines that passed automatic output and game-code checks.
This does not measure translation quality.
```

### Missing responses count as failures

**Compute validity against the manifest's expected segment total, never against what came back.**

```python
validation_failures = total_segments - valid_segments   # total_segments sums over ALL manifest executions
```

Any dashboard whose denominator is *responses received* ranks the least cooperative model highest.
Batch APIs silently drop requests, and a model that refuses or truncates on the hard lines scores 100% valid on the easy ones it answered.
Record `expected_requests`, `received_requests`, `missing_requests` and `provider_errors` separately so a low rate is diagnosable as refusal, truncation, or transport.

**Taint the whole request when the envelope is broken.** A response that is unparseable JSON, or whose line count differs from the request's segment count, copies its request-level issues into *every* line before per-line checks run. You cannot tell which line the model dropped.

---

## 2. Selecting what to review

You cannot review 48,000 lines. The selection method decides what the verdict measures, so it is the part to get right.

### Calibrate a voice-guidance change on complete exchanges

Before broad retranslation for a voice or fluency complaint, compare a bounded selection of
complete exchanges from the affected game, covering different speakers, listeners, and moods.
Keep the Japanese, speaker assignments, current glossary, and engine text boundaries visible.
Compare the existing translation with a candidate made under the revised guidance; preserve
source IDs and record the prompt/context used. Keep candidates in review artifacts until accepted.
This can be a local editorial exercise in direct mode; it does not authorize additional provider
calls or require a new full-game API pass. Apply the selected API workflow's cost boundary if used.

Read the English exchanges for flow, then verify changes against the Japanese. Report meaning,
voice/register, and reading flow separately, citing concrete preserved or lost nuances rather than
"more creative" or "sounds better." Keep deliberate formality and awkwardness. Promote only
source-supported recurring speech habits into the existing glossary; examples are not universal
line replacements. Recheck controls and fit before accepting an edited translation. A small scene
comparison is qualitative calibration, not a full-game quality score or release clearance.

### Stratify, never sample uniformly

**Never draw a benchmark corpus uniformly at random.** RPG Maker text is dominated by short database strings and one or two chatty maps, so a uniform draw measures item-name translation and misses the control-code dialogue where models actually break.

Tag every segment at capture time:

| Stratum | Rule | Quota |
|---|---|---|
| `code_heavy` | source contains a backslash (any `\C[n]`, `\V[n]`, `\N[n]`) | 15% |
| `database` | Actors/Items/Skills/States fields and map display names | 20% |
| `event_text` | everything else | remainder |

Take `code_heavy` **last**, excluding ids already selected, so it never double-counts.

**Seed selection from a corpus fingerprint, not from a constant**: sha256 over the sorted `(id, source, source_category)` triples of the whole pool. The same game always draws the same benchmark and can be re-run and compared, a different game draws different lines, and no model can be tuned to a fixed fixture.

Round-robin across files and then across scenes within each file, ordering both by `sha256(f"{seed}:file:{name}")`, sorting scenes holding at least `per_scene` items first, and taking up to `per_scene` **contiguous** items per visit so each draw carries local context. Enforce a floor of about **60 eligible lines** before a benchmark is worth running at all.

### Samples are contiguous same-scene blocks

**A review sample must be a contiguous run of one scene.** Map each selected segment to its position in the full scene and start a new chunk whenever the next selected line is not at `previous_position + 1`, or the chunk hit `sample_size`. Judging isolated lines cannot detect the failures that matter most in game text: speaker continuity, pronoun and gender drift, terminology consistency across a scene.

**Cap history to exactly what production gives.** For a chunk that does not start its scene, carry

```python
history_size = min(sample_size, 10)   # production carries the preceding chunk, capped at maxHistory 10
```

A flat ten lines gives samples shorter than ten lines *more* context than the real workflow, so the benchmark winner underperforms in the shipped patch, worst at small batch sizes. Assert the invariant:

```python
assert all(len(r["history"]) <= 10 for r in requests)
```

One chunk = one translation request = one review row. Tell the judge to review the row **as a whole** and not to rank individual lines.

### Apples to apples

Admit a sample into the blind review only when **every** one of its segments has a valid first-repetition translation from **every** candidate. Report eligible against total samples and lines, so the exclusion cannot become silent survivorship bias.

---

## 3. Blinding

**Reshuffle the candidate labels independently on every sample row, not once per run.** A single global A/B/C assignment lets the judge lock onto one column's style and score by identity for the whole file, and fixed column order triggers LLM position bias, a documented and strong judge failure mode.

Spreadsheet labels A, B, C ... AA, AB. Seed deterministically from run and sample so the shuffle is reproducible and a lost key can be regenerated:

```python
random.Random(f"{run_id}:{sample_id}").shuffle(shuffled)
```

Write the per-sample label→candidate map to a separate `blind_key.json` next to the CSV, atomically and **after** the CSV. In the judge prompt:

- state that labels are shuffled per row,
- forbid opening `blind_key.json` or any file other than the CSV and the context snapshots,
- forbid inferring model identity from writing style.

Keep candidate names hidden in the comparison view until a reviewed CSV is imported. Re-attach labels to real model names only at import time.

---

## 4. The rubric: ordinal ranking on four axes

**Make the judge rank candidates ordinally. Never ask it for 1-5 scores.** Absolute LLM scores are uncalibrated and drift between runs, prompts and rubric wordings, so two runs a week apart are not comparable.

Four ranking columns per sample, over the randomized labels, using only `>` and `=`:

```
meaning_accuracy_ranking
glossary_prompt_ranking
natural_contextual_ranking
ranking                      # overall
```

**State the overall tie-break priority in fixed order and make the judge apply it in that order:**

1. **Fidelity** - meaning, intent, polarity, subject, quantity, relationships, tone.
2. **Runtime safety** - placeholders and control codes preserved with sensible scope.
3. **Contextual appropriateness** - speaker voice, register, locked terminology, choice wording.
4. **Natural English** - fluent, no model commentary, no unjustified additions.

Without that stated order the judge silently optimizes for English fluency, which is exactly how a fluent mistranslated plot line beats a slightly stiff correct one.

Natural delivery of source-supported attitude and subtext is part of fidelity. Among candidates
that preserve meaning and required controls, prefer the exchange with natural flow and evidenced
speaker rhythm and register. Literal syntax alone earns no accuracy advantage. Do not reward added
wit, slang, hostility, or explanation, or erase deliberately formal, awkward, or restrained speech.

Two anti-bias clauses, verbatim in the prompt:

```
Do not reward literalness by itself, and do not penalize a valid localization
merely because you prefer another style.

Ignore tiny punctuation or wording preferences when meaning and voice are equivalent.
```

Allow `=` only for genuine equivalence, including `A=B=C` when the available context cannot support a defensible distinction. **Require every label to appear exactly once in every ranking column, and enforce that on import** - a parser that accepts a ranking missing a label is scoring a candidate that was never judged.

---

## 5. Rankings → score: fixed-sum Borda, tie-averaged, line-weighted

**Convert rankings to fixed-sum Borda points with ties averaged, then weight each row by its line count.** For N candidates, tier positions run `0..N-1` and each tier awards:

```python
award = sum(N - 1 - index for index in occupied_positions) / len(tier)
points[label] += award * line_count       # one judge decision, applied once per source line
```

Three candidates:

| Ranking | A | B | C |
|---|---|---|---|
| `A>B>C` | 2 | 1 | 0 |
| `A=B>C` | 1.5 | 1.5 | 0 |
| `A>B=C` | 2 | 0.5 | 0.5 |
| `A=B=C` | 1 | 1 | 1 |

Every row sums to `N(N-1)/2` regardless of tie pattern, so no ranking shape inflates a total and a judge that ties everything cannot manufacture points. Line weighting makes a 10-line dialogue block count ten times a 1-line item name while the judge still makes one decision per sample.

Accumulate weighted Borda separately for **each** axis. Report alongside it:

- unweighted first-place counts,
- **strict wins** (top tier has exactly one member),
- **full ties** (one tier),
- **partial ties** (any tier with more than one member).

Naive win-counting throws the tie information away and lets an indecisive judge look decisive.

**Version the scheme in the saved state** so an old run's totals are never silently compared against a new formula:

```json
"scoring": "fixed-sum-borda-average-per-line-v2"
```

---

## 6. Repeatability is a separate metric from quality

**Re-run a subset 3 times and compare exact normalized strings, at whole-sample granularity.**

```python
norm = lambda t: re.sub(r"\s+", " ", t.strip()).casefold()
```

Count only lines that passed validation.
A segment is exactly stable only when it collected exactly `repetitions` values and `len(set(values)) == 1`. A **sample** contributes its ordered tuple of line translations only when the result has the same line count as the request and every segment id is present and valid, so the block counts as stable only if the entire multi-line chunk is identical every run.
A block that is stable line by line can still shuffle speaker attribution.

Report both rates and prefer the sample rate. Label it:

```
Repeated samples translated exactly the same every run.
Higher means more repeatable, not better.
```

A model can be perfectly stable and stably bad. Choose the repeated subset **round-robin across strata** so consistency is not measured only on short database entries, and re-run **only** the stability subset on repetitions 2 and 3 so the extra cost buys determinism data without adding review rows.

Nondeterminism is what makes a patch un-reproducible. Re-running one map renders the same NPC's name three different ways.

---

## 7. Re-import: verify, do not trust

**Re-derive every protected column from the frozen manifest and reject the import on any mismatch.** Excel mangles UTF-8, strips leading zeros, reformats long strings and re-wraps embedded newlines. An LLM told to write a sibling CSV will happily rewrite or truncate the candidate text it was judging. Scoring text a model never produced makes the verdict that picks the translator for the whole game garbage.

Per row:

- `scene_id`, `stratum` - compare as exact strings.
- `segment_ids`, `source` - parse as JSON and compare against the manifest.
- **every** blind label column - compare its JSON array against the exact ordered list of that candidate's stored translations, failing with `Protected candidate text {label!r} changed`.
- `line_count` - must equal the manifest's segment count for that request.
- duplicate or unknown `sample_id` - raise.
- **if any quality-ranking column is present, require all of them present and non-empty on every scored row**, so a half-filled review cannot be credited as complete.

Have the judge write a new sibling file ending in `.ai-reviewed.csv`, never overwrite the original, then re-open what it wrote and self-verify row count, label completeness and protected columns before reporting.

### Bind result files to candidate and corpus

**Refuse to load a result file that is not cryptographically bound to the candidate that produced it and the exact corpus it ran against.** Evaluation runs are long-lived and get exported and re-imported across machines. Without binding, re-preparing a benchmark and reusing old result files attributes one model's translations to another, or scores a model against a corpus it never saw, and the wrong model then translates the whole game.

Stamp each result with `candidate_id`, `model`, `provider`, `execution`, `endpoint`, `manifest_sha256`, and verify all six on load. Per execution, verify `logical_request_id`, `repetition`, the request's `logical_hash`, and that the returned lines' `segment_id` sequence equals the manifest's `segment_ids` list **in order**.

Hash the manifest over every key except `created_at` and the hash field itself.
Reject a run whose manifest hash is missing, is not 64 hex characters, disagrees between the state file and the manifest, or no longer matches the manifest contents.
Forbid two candidates sharing one result file.
Constrain result paths to exactly `results/<name>.json`, no traversal.
Gate the strictness on a stored binding version so older runs still load with the newer fields tolerated as missing.

---

## 8. The verdict, and what it is worth

**Treat the judge's own bias as a required output of the review, not a footnote.** An LLM judging LLM translations shares training data and stylistic priors with the candidates, and self-preference bias is real. A model tends to rank its own family highest.

Mandatory limitation section in the judge prompt:

```
AI judging is not objective. You may share stylistic preferences, training biases,
or failure modes with the models that produced these translations. Treat this review
as a useful second opinion, not a replacement for a fluent human Japanese reviewer.
State this limitation in your final report.
```

**Itemize the required final report** so it cannot shrink to a winner announcement:

- reviewed output path,
- total sample rows and total source lines,
- fixed-sum points per randomized label, for all four ranking columns,
- overall unique first places, partial ties, full ties,
- **any rows the judge could not judge safely**,
- an explicit warning that the review may be biased and should be confirmed by a qualified human before a high-stakes model choice.

Carry that same warning to every point of use, at warning severity and not informational. Presenting an LLM's verdict as an objective quality score is the single most misleading thing a translation tool can do.

### Acting on it

- A **strict win on fidelity** with the loser also losing on runtime safety is a decision. Take it.
- A **full tie or a fluency-only win** is not a decision. Pick on cost, rate limit, or repeatability instead, and say that is what you did.
- Rows the judge flagged as unjudgeable are the shortlist for the human pass, ahead of anything else.
- Winning the benchmark does not clear the UI strings. Dump every button, choice, notice and tooltip as `JP → EN` side by side and read them (`references/llm-pipeline.md`). A few hundred lines, minutes of reading, and it is the only pass that catches a short verb rendered as the wrong part of speech.
