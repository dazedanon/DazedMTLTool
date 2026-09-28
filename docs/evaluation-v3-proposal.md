# Translation evaluation v3 proposal

Status: approved 2026-09-25; all four implementation stages are implemented alongside
legacy reviews. Numerical sampling and decision thresholds remain pilot settings, not
empirically validated Japanese-game thresholds. Existing verdicts are not converted.

Implementation notes: v3 uses exact marginal binomial intervals for ternary group
outcomes and conservative bounded-mean intervals for fractional or weighted groups.
This replaces the proposed bootstrap starting point and avoids zero-width intervals
from all-equivalent samples. Confirmation translations stay hidden until contenders
are frozen. Human adjudication preserves prior judgments and retires stale audits.

## Decision the evaluation should support

Choose a model and generation configuration for Japanese-to-English game translation.
The result should explain which configuration produces better scenes, what still
requires editing, whether it obeys production requirements, and whether its advantage
justifies its cost. A model name alone is not a candidate identity: settings matter.

The current system already preserves blinded inputs, records exact error evidence,
supports abstention and independent judge checks, and computes scene-based statistics.
Keep those capabilities. Replace the primary eight-way ranking and Borda leaderboard.

Three weaknesses need addressing:

1. An acceptable translation is not necessarily as good as another acceptable
   translation. Requiring a defect to justify every preference misses better delivery
   of source-supported voice, emphasis, and conversational timing.
2. Relative rank does not measure error severity or absolute quality. The same rank
   gap can follow a missing suffix or a reversed meaning; a shared error disappears
   into an all-candidate tie.
3. A complete ordering hides uncertainty, trade-offs, and conflicting preferences.
   The current sidebar also calls any ranking with a tied subgroup a tie.

## What to measure

Keep five separate results. Do not average them into an unexplained score out of 100.

| Result | Measurement | Purpose |
|---|---|---|
| Translation preference | Direct paired choices, with slight/clear strength and source-linked reasons | Which complete scene reads better while retaining the Japanese? |
| Editing required | Ready; light edits; substantive edits; rewrite | Are either of the translations good enough? |
| Fidelity failures | Share of reviewed scene blocks with confirmed major/critical meaning or important voice errors | Does a fluent candidate change the story? |
| Production compliance | Runtime validity and each applicable rule's violation rate | Can the output be used under this project's requirements? |
| Cost and speed | Observed generation cost, retry cost, and latency on the same source workload | What does the quality difference cost? |

Report numerator, denominator, content coverage, and uncertainty. Translation failures
remain in production-validity coverage even when there is no text to judge. Never
silently remove a difficult sample from all candidates because one candidate failed.
Paired linguistic results use common judgeable outputs and disclose that conditioning.

## Review workflow

### 1. Freeze the task and review rules

Supply the same Japanese block, preceding context, glossary, system prompt, and SFX
reference to every candidate. Give the judge those exact inputs. Context is not scored
as extra source lines. Empty history is valid at a genuine scene start; missing needed
history produces an explicit abstention. Do not fix an old experiment by giving only
its judge extra context and presenting the result as the same test.

Before judging, resolve policy questions such as honorifics on collective forms of
address, permitted inflections of glossary terms, and conflicts between an explicit
source pronoun and an unspecified glossary gender. Record decisions in a versioned
review policy. A policy conflict is not evidence that a candidate mistranslated.

Continue randomizing labels locally, protecting input hashes, preserving code spans,
and preventing judges from seeing candidate identities, cost, or prior verdicts.

### 2. Assess each unique candidate block

Read the whole exchange. Record its editing requirement and any concrete errors before
making comparative judgments. Exact duplicate blocks share this assessment, while their
different generation configurations retain separate reliability and cost measurements.

| Editing requirement | Anchor |
|---|---|
| Ready | No necessary linguistic edits under the declared brief |
| Light edits | Local corrections or wording repairs; meaning and important voice remain intact |
| Substantive edits | At least one consequential meaning, relationship, intent, or voice correction |
| Rewrite | Pervasive problems make local repair impractical |

These are editorial estimates, not measured editing minutes. Runtime usability is a
separate status. All candidates can be ready, or all can require rewriting.

Keep exact source/translation quotations and line locations. Error severity follows
impact: minor for local repair, major for a consequential change, critical for unusable
content or essential runtime failure. A mandatory-rule violation is always recorded,
but it is not automatically a major linguistic error. A missing -san with otherwise
preserved respect can be a local compliance repair; removing an important relationship
distinction can also be a major voice error. A reversed negation is a major meaning
error. A broken indispensable placeholder is a critical runtime defect.

Give an underlying error one identity with applicable tags. Do not count one defect
three times because it affects meaning, voice, and a prompt rule. Store recurring
occurrences and root causes separately. Verify deterministic code/placeholder and
spelling checks in code; use linguistic judgment for their applicability and meaning.

### 3. Compare two complete blocks directly

Ask: "Which version would you choose for this scene, considering fidelity first, then
source-supported voice, continuity, and English delivery? Identify the consequential
trade-off, if any. Evaluate production-only compliance separately."

Allowed decisions:

- Left clearly better.
- Left slightly better.
- Practically equivalent.
- Right slightly better.
- Right clearly better.
- Cannot judge: missing context, uncertain interpretation, or policy conflict.

"Slightly better" requires a reproducible editorial reason, not punctuation taste.
It does not require calling the alternative erroneous. For example, one version may
make a hesitant reply connect more naturally with the preceding question while both
remain accurate. "Clearly better" requires a consequential improvement or a sustained
block-level advantage. An invented joke or simplified formal voice is not an advantage.

Require exact evidence from the source and both versions for a preference. Save positive
comparative evidence separately from error evidence. Do not invent an error simply to
justify a choice. Prefer neither a fixed tie quota nor a minimum number of wins.

Pairwise preferences can form a cycle. Preserve that result and show the trade-offs;
do not silently turn it into a supposedly certain complete ranking.

### 4. Check the judge

Use a small, human-reviewed calibration set containing meaning changes, valid stylistic
alternatives, intentional formality, ambiguous pronouns, rule-only violations, and broken
codes. The calibration set stays separate from model-comparison scores.

As a starting audit budget, independently rejudge a randomly selected 20% of comparisons
with left/right order reversed and have a second judge review a random 20%, plus critical
findings and disputed finalist decisions. These percentages need calibration. A second
pass sees the source and outputs, never the first judge's verdict. Repeated votes on the
same scene are not extra independent samples. Unresolved reversals remain disputed.

Judge agreement is a reliability check, not proof of Japanese accuracy. Inspect whether
the recommendation changes by judge and after disputed judgments are excluded. Escalate
decision-changing disputes and consequential interpretations to a qualified reviewer.

## Sampling and review cost

Start with a fixed screening set of 30 distinct narrative or content groups, selected
before looking at model outputs. Include everyday dialogue, emotional exchanges,
formal speech, humor, narration, lore, UI instructions, and terminology/code-heavy text
in proportions declared for the intended workload. Include mature-content registers
when they are part of that workload.

Keep a separate challenge set, initially around 20 blocks, for ambiguity, speech quirks,
control scope, omitted subjects, and other known difficulties. Report its results
separately. Do not blend deliberately difficult material into a representative score
without a declared weighting scheme.

Use bounded, coherent scenes with enough source context. Multiple calls/chunks from
one event/page must share a content-group identifier; a request ID is not an independent
scene. Related/repeated passages must not span screening and confirmation sets.

For eight candidates, an initial balanced schedule can compare each candidate with two
opponents per scene: eight comparisons per scene, 240 across 30 scenes. Rotate a seeded
round-robin schedule so pair exposure is balanced across scenes and content categories.
The task may be exported as CSV; this design does not require a paid judge API.

Screening identifies plausible contenders. Keep candidates whose uncertainty leaves
them plausibly competitive, rather than always cutting to exactly three. Then freeze
the contender set and compare every pair on the same new confirmation scenes, initially
30. Three finalists require 90 paired comparisons. If more remain plausible, show the
larger review budget before extending the run. Those counts exclude audit rejudgments.

These sample sizes provide a bounded pilot, not a guarantee of sufficient power. If
confirmation is inconclusive, report that and plan a new fixed batch. Do not keep
peeking and adding scenes until a favored candidate becomes significant.

## Aggregation and recommendation

### Transparent paired results

For each pair, show clear wins, slight wins, equivalents, slight losses, clear losses,
and abstentions. A compact summary is the net preference:

`net preference = (wins - losses) / (wins + equivalents + losses)`

Equivalents remain in the denominator and contribute zero direction. Abstentions are
excluded and displayed. Preserve slight/clear counts separately; do not assume a clear
win is exactly twice the value of a slight one. The primary comparison is linguistic
quality; a separate compliance result captures a policy-only difference.

Hypothetical example: in 40 independent, judgeable scenes, A wins 18, B wins 10, and
12 are equivalent. Display "A preferred 18; equivalent 12; B preferred 10; net advantage
20 percentage points." Do not call this a 64% win rate by deleting equivalents, or
turn it into a calibrated probability that A is the best model.

Average blocks within their content group before aggregation. Apply fixed representative
stratum weights, or declared equal-scene weights, consistently. Longer requests and
repeated lines do not multiply the strength of a subjective block preference. Cost
can still be normalized by source characters. Do not pool votes from uneven opponents
to declare a final winner; use the balanced confirmation comparisons.

### Absolute quality and compliance

Alongside preferences, display the distribution of editing requirements and the share
of scene blocks affected by major fidelity errors. Report recurring terminology and
honorific violations per applicable opportunity, with denominators; do not assume every
scene contains a given rule. Preserve the raw occurrence counts for investigation.

Runtime and mandatory-rule requirements determine production eligibility under a policy
chosen before results are revealed. A quality leader with a recurring rule violation
can be labeled "quality leader; correction required." It cannot silently become a
production recommendation. If a proposed automatic fix is part of the workflow, evaluate
the actual fixed outputs as a separately versioned pipeline. Never assume a fix works.

### Evidence strength

Compute paired uncertainty over independent content groups, preserving stratum weights.
Retain the current scene-resampling approach as a starting implementation, but increase
the resample count appropriately and use intervals for the new paired quantities.
Repeated judges and translation repetitions stay inside the content group.

Predeclare comparisons and adjust simultaneous finalist claims for multiplicity. A
bootstrap with no observed variation can return a zero-width interval: that alone must
not establish population equivalence. Show insufficient variation/calibration and obtain
more evidence or use a validated bounded-outcome interval before an equivalence claim.
Intervals describe sampling uncertainty, not judge bias or performance on another game.

Use distinct recommendation states:

| State | Meaning |
|---|---|
| Supported quality leader | Confirmation shows a practically meaningful advantage over each relevant rival, with acceptable fidelity risk and stable judge checks |
| Provisional leader | Best observed results; uncertainty still overlaps alternatives |
| No demonstrated difference | Current evidence cannot distinguish contenders; this is not proof of equivalence |
| Practically equivalent | Adequately calibrated intervals fit inside a predeclared practical-equivalence margin |
| Trade-off or disputed | Fidelity, delivery, compliance, or judges favor different candidates |
| No production-ready candidate | No contender meets the configured production requirements |

A starting practical margin could be 5 percentage points of net scene preference,
chosen before confirmation and shown in the report. It needs validation with real
editing decisions. A supported leader requires the adjusted lower interval bound to
exceed that margin against relevant rivals; equivalence requires a suitable interval
entirely inside the positive/negative margin. Predeclare an acceptable fidelity-risk
margin as well; absence of a significant harm finding does not establish noninferiority.

Report a value recommendation only among candidates meeting the selected quality and
production criteria. If the user chooses a cheaper provisional contender despite
unresolved quality differences, state that trade-off rather than calling it equal.

## Interface and data contract

The primary results table should show: recommendation status, editing requirement
distribution, major-fidelity-error rate, compliance, runtime validity, pairwise advantage
over the selected comparator with uncertainty, cost, and latency. Each aggregate opens
its underlying scenes and evidence. A visible quality/compliance distinction prevents
missing honorifics from masquerading as a general translation-quality gap.

In the comparison view, use explicit labels: "Identical outputs," "Equivalent quality,"
"Slight preference," "Clear preference," "Mixed preferences," "Disputed," and "Not
judgeable." Show editing requirements alongside equivalents so equally poor outputs
are visible. Legacy ranks should at least distinguish full and partial ties.

Introduce a versioned export/import contract with three linked record types:

- Protected samples: source, exact context, source/content-group IDs, candidate outputs,
  duplicate groups, output status, opaque candidate mapping, and input hashes.
- Assessments: local candidate label, status, editing requirement, evidence IDs, error
  occurrences, policy-rule IDs, and reviewer/policy version.
- Comparisons: pair-specific opaque labels, sample ID, decision, slight/clear strength,
  source and both translation quotes, rationale, uncertainty/dispute status, and judge
  provenance. Store language preference separately from policy-compliance comparison.

Keep CSV available for manual or assistant review. The importer maps candidate identity
privately and validates every protected input and quotation. Do not infer v3 preferences,
readiness, or severity from an old Borda ranking. Legacy runs retain their original scores
and can be re-exported for a fresh blinded assessment under a new review version.

## Implementation sequence and acceptance checks

1. Correct legacy full/partial tie labels and expose existing paired evidence.
2. Add the v3 policy, protected export/import contract, assessments, and paired tasks.
3. Add pure aggregation and recommendation logic, then the results interface.
4. Add balanced screening, confirmation holdouts, judge audits, and calibration reporting.

Relevant existing components are `util/evaluation.py`, `util/evaluation_review.py`,
`gui/evaluation_tab.py`, and the exported review instructions. Reuse their protections
and persisted-job behavior. Preserve ongoing work in those files.

Behavioral acceptance cases for implementation:

- Two ready candidates can have an evidenced slight preference without an invented error.
- Two equally flawed candidates show equivalent preference and poor absolute quality.
- Rule-only suffix repair and reversed meaning produce different error-impact reports.
- A failed output affects validity coverage and never becomes an invented linguistic loss.
- Uncertain comparisons are abstentions, not ties or half-wins.
- Adding an unrelated candidate cannot change a stored pair's result or paired statistic.
- Rechunking one content group or adding an audit vote cannot inflate its statistical weight.
- Order-swap disagreement becomes disputed; it cannot silently strengthen a preference.
- Zero-variation data and overlapping intervals do not manufacture equivalence.
- Wrong quotes, changed context, invalid status, missing candidate coverage, or hidden-key
  exposure are rejected by the relevant contract boundary.
- Legacy import and display remain intact, with explicit v2/v3 provenance.

Run the required core, integration, and extended suites for these shared,
persisted-workflow, and UI changes. Existing review contract tests cover both formats;
the Qt smoke path also exercises the paired results and evidence navigation.

## Research basis and limits

The design combines source-grounded error analysis and direct comparative judgment.
[Experts, Errors, and Context](https://aclanthology.org/2021.tacl-1.87/) supports expert
error annotation with document context.
[Enhancing Human Evaluation in Machine Translation with Comparative Judgement](https://aclanthology.org/2025.acl-long.1002/)
reports benefits from side-by-side human evaluation, including subtle distinctions.
[GEMBA-MQM](https://aclanthology.org/2023.wmt-1.64/) demonstrates LLM error-span annotation
and explicitly cautions about reliance on a proprietary judge.
[Judging LLM-as-a-Judge](https://arxiv.org/abs/2306.05685) documents position and other biases.

These studies motivate the architecture. They do not validate this proposed protocol,
its thresholds, or an AI judge for Japanese game dialogue. Validate the policy and
recommendations against qualified Japanese reviewers and real editing outcomes before
treating the system as authoritative.
