# QA Exported RPG Maker Translations — Local Task Handoff

<!-- qa-contract:rpgmaker-qa-local-v9
app-owned-inventory immutable-review-bundles scene-affine-semantic-screen
evidence-preserving-deep-handoff motif-family-receipts selective-risk-escalation
validated-checkpoints honest-global-coverage grouped-finding-families
motif-finding-attribution final-consistency-audit final-editorial-pass
subjective-precision-gate ignored-receipt-workspace clean-release-auto-approval
preserve-original atomic-apply post-fix-regression
no-provider-api
-->

<task_context>
Selected game root: `{{GAME_ROOT}}`

Selected game data: `{{GAME_DATA_FOLDER}}`

Selected QA focus: `{{QA_FOCUS}}`

DazedTL checkout: `{{QA_TOOL_ROOT}}`

Game glossary: `{{VOCAB_FILE}}`

Translation quirks: `{{QUIRKS_FILE}}`

Game skill: `{{GAME_SKILL_FILE}}`

Optional game skills: `{{GAME_SKILLS_FOLDER}}`

Ignored reviewer receipts: `{{GAME_ROOT}}/.dazedtl/qa-receipts/`
</task_context>

## Required workflow

DazedTL owns this QA pipeline. Do not create a replacement manifest, index, registry, checkpoint,
sharding system, or generated script. Do not call a model-provider API. The current AI helper is
the semantic reviewer; the local tools do the mechanical and orchestration work.

Prepare or resume the selected task with:

```text
python "{{QA_TOOL_ROOT}}/scripts/rpgmaker_qa.py" prepare --game-root "{{GAME_ROOT}}" --data "{{GAME_DATA_FOLDER}}" --focus "{{QA_FOCUS}}" --output-root "{{QA_TOOL_ROOT}}/log/rpgmaker_qa"
```

Open the generated task directory's `README.md` and follow it exactly. It gives the checksum-bound
screen and deep-review result schemas and the commands for claiming, accepting, resuming, and
finalizing bundles.

Write temporary screen and deep result JSON only beneath the task-specific directory named by the
generated README under `{{GAME_ROOT}}/.dazedtl/qa-receipts/`. Never place `.qa-*.json` or
`qa-*.json` in the game root. DazedTL retains accepted canonical receipts in its managed task;
the ignored game-local directory is convenient review history and must not pollute Git changes.

The screen stage keeps every dialogue command-list scene intact and assigns that complete scene to
one worker only. A bundle may contain several whole scenes, but no scene may cross bundle or worker
boundaries. Exact duplicate scenes may share one contextual receipt. Non-dialogue text remains a
compact cluster screen. Clean targets are represented by the accepted bundle receipt, while
exceptions contain only suspects or context needs. Risk cues, glossary hits, length ratios, and
same-source alternatives guide that screen; they do not by themselves mandate deep review.
When the user configured reference games, exact Japanese-source matches appear as
`reference_translations` evidence on the affected targets. Compare established wording for
returning terms and callbacks, but treat it as advisory: a difference is a cue to investigate, not
an automatic defect. The current source, scene, and explicit current-game glossary win when the
contexts differ or the older references conflict.

For every scene target, explicitly verify who performs each action and to whom;
pronouns and relationships; negation and conditions; certainty and obligation; quantities and
chronology; omitted or invented information; and speaker voice plus natural English. Repeated
translations containing third-person pronouns are shown in every distinct scene context; other
pronoun-bearing translations spoken by different detected speakers receive one representative scene per speaker.
Ordinary safe repetition remains deduplicated.

Recurring-joke and wordplay rules with distinctive Japanese anchors in translation quirks become
deterministic motif families. Every matching variant is reviewed together and receives an explicit
family receipt even when preserved. A preserved receipt must name one recognizable English joke
mechanism and verify that every nonliteral variant still reads as its callback; sharing a character
name alone is not enough. If a scene reviewer later disputes a wordplay variant, the local engine
reopens every variant in that preserved family for deep review. Otherwise, the engine expands scene
exceptions, motif suspects, and only strong mechanical/runtime defects and choice structures for
evidence-backed deep review.
Escalated screen suspects retain the reviewer's categories and rationale plus every complete scene
used to reach that judgment. Relevant motif-family receipts travel with the deep item so the deep
reviewer must reconcile scene and family evidence instead of silently discarding either one. A
deep reviewer may clear a screen suspect only with a concrete rebuttal recorded in its evidence.
Actionable deep findings use the documented category taxonomy and may share a generic `family_key`;
final reports group matching keys while retaining every independently correctable target. A local
checkpoint reports whole-focus progress, motif coverage, suspect counts, projected deep work,
worker assignments, throughput, and ETA—never merely one completed bundle.

Final motif-family summaries reconcile the earlier family receipt with every accepted deep result.
Actionable or uncertain variants supersede an earlier clean family disposition, while the original
screen receipt remains nested in the report for auditability. Deep reviews explicitly attribute
motif IDs only when their correction or playtest uncertainty concerns that joke mechanism;
unrelated defects and ordinary anchor collisions never make a motif family look broken.

If QA rules change after an exhaustive screen finishes, reuse its checksum-validated receipts and
regenerate only deep review with `rebuild-deep --task "<completed-task>"`. The command creates a
new task; it never overwrites the completed source task or reuses evidence when the manifest,
context, or screen-bundle checksums differ.
If only final-report rules change after deep review completes, use
`rebuild-final --task "<completed-task>"`; compatible screen and deep receipts are
checksum-validated and replayed into a new task without invoking semantic review again.

Finalization first runs a deterministic consistency audit against exact mappings recorded in the
translation quirks and repeated structured UI headers. If it reports a conflict, do not present a
partial report: reconcile the named deep receipts and use `rebuild-final` until the audit passes.

After finalization and before showing findings to the user, perform a final editorial pass over
every actionable correction. Prefer a reviewer who did not author the correction when another
reviewer is available. Compare the source, current translation, proposed correction, evidence,
and supplied scene context. Confirm that each correction is publication-ready, not merely
semantically defensible: it must read naturally, preserve speaker voice and register, follow the
project's terminology and honorific policy, retain required runtime controls, and fit the relevant
dialogue or UI constraints. Keep this pass scoped to the proposed findings; do not reopen clean
inventory records.

Treat stylistic preference as clean. Change a line only when you can name a concrete defect, use
the smallest natural correction that resolves it, and withdraw the finding when the current and
proposed wordings are merely equally valid stylistic alternatives.

For actionable `fluency`, `voice`, and `wordplay` findings, require a reviewer who did not author
the correction to independently confirm the recorded `editorial_basis`: the concrete
reader-facing defect, the source/scene/guidance that makes it defective, and that the proposal is
not merely preferred wording. If independent review is unavailable or does not agree, revise the
deep result to `clean` and rebuild the final report. Objective categories do not need this extra
gate.

Do not show or apply a correction that fails this pass. Do not edit `findings.json` directly.
Revise its corresponding deep result receipt, run `rebuild-final` into a separate output root, and
repeat the editorial pass on the returned task.

For a full-game release task, once every actionable correction passes and there are no unresolved
playtest/context records, automatically create the all-findings correction map, dry-run it, and
apply it through DazedTL's atomic regression gate. Do not make the user approve already-verified
stable IDs. If `uncertain_playtests` is nonempty, or any deterministic audit, dry-run, apply, or
regression safeguard fails, pause and ask only for the decision needed to resolve that issue. The
generated README provides the restricted `--approve-all` commands and the explicit
`--allow-uncertain` path for applying verified findings while leaving uncertain records unchanged.

Targeted reruns still require approval of specific stable IDs because they do not represent the
complete release gate. Never modify or remove `_original`, and never write game files directly;
always use the generated README's correction-map, dry-run, atomic-apply, and regression commands.

<!-- qa-focus:database -->
Database focus. The local manifest owns the exact canonical database-file scope; review only the
prepared bundles for this focus.
<!-- /qa-focus:database -->

<!-- qa-focus:risky-codes -->
Risky event-code focus. The local manifest owns the exact translation-sensitive command scope;
review only the prepared bundles for this focus.
<!-- /qa-focus:risky-codes -->

<!-- qa-focus:dialogue -->
Dialogue focus. Review each prepared scene as one ordered conversation, plus the prepared motif
families for recurring humor and wordplay. When a concrete issue exposes a same-source, glossary,
or context family, use the related evidence supplied in the deep bundle rather than building a
separate corpus index.
<!-- /qa-focus:dialogue -->

<!-- qa-focus:release -->
Coverage and release focus. The local manifest inventories every supported `_original` leaf and
the task may finish only when its exhaustive screen and deep-review denominators are complete.
<!-- /qa-focus:release -->
