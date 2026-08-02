# Test-suite audit

Audit date: 2026-08-02

## Outcome

The audited baseline contained 919 tests. The suite now contains 770 tests:
673 core tests and 97 extended tests. The full suite is the union of those two
tiers; there is no third group of “full-only” tests.

On the audit machine, the pre-cleanup extended and full runs took about 100 and
105 seconds. The audited versions take roughly 9 and 14 seconds. The latest
follow-up run completed core in 4.330 seconds and full in 14.156 seconds.
Runtime and test-count ceilings are enforced by `scripts/run_test_suite.py`.

## Follow-up consolidation

A second pass converted related pure-function input/output variants into
labeled `subTest` tables. This removed 82 test-method wrappers while retaining
their individual case labels, inputs, expected outputs, and failure reporting.
The pass covered translation cache keys and merging, control-code validation,
speaker parsing, CSV target detection, WOLF code repair and classification,
provider-route defaults, SFX matching, and small parser/normalizer matrices.

One cache-key test that made the same call twice was removed as an exact
duplicate. An Anthropic test that only proved a third-party object lacked a
`.text` attribute was also removed; the retained case still verifies that the
application skips that block and extracts the following text. Stateful worker,
filesystem mutation, persistence, destructive-action, and distinct failure-path
tests remain separate.

## Decision rule

A test was retained when it detects a distinct product behavior, data-integrity
rule, destructive-action safeguard, worker lifecycle, persistence contract, or
external protocol. Tests were removed or narrowed when they primarily froze
prose, pixel geometry, layout hierarchy, source-code spelling, duplicated smoke
coverage, or a library behavior.

## Extended-suite decisions

| Area | Current | Decision |
| --- | ---: | --- |
| Evaluation UI | 29 | Keep provider/model routing, saved-run restoration, history, export/import, cancellation, polling, recovery, and result semantics. Replace the ignored 93 MB local corpus with a generated temporary corpus. Remove geometry and preset-copy checks. |
| Image manager/workflow | 17 | Keep selection semantics, non-destructive deletion, action scope, read-only scans, engine detection, folder routing, thumbnails, and workflow handoff. Remove layout, pagination, tooltip, copy, and production-source checks. |
| Workflow actions | 14 | Keep endpoint wiring, confirmation defaults, disposable-project detection, worker arguments/lifetimes, phase configuration, export scope, rewrap confirmation, and installer safety. Remove disclosure-copy and duplicate navigation checks. |
| Workflow shell | 9 | Keep navigation state, activity persistence/semantics, dependent controls, saved widths, and Wolf repair handoff. Remove page inventories, dimensions, margins, button placement, reflow, and exact copy. Move the pure worker exception check to core. |
| Translation UI | 7 | Keep evaluation locking, completion/unlock state, batch failure/no-work state, and pricing presentation. Remove layout/copy-only checks and move worker/formatter logic to core. |
| Config UI | 6 | Keep load, provider refresh, manual model preservation, full save/reload, and reset persistence. Remove alignment, popup geometry, opacity, and menu-layout checks; move provider filtering logic to core. |
| Shared GUI contracts | 4 | Keep contrast, semantic styling hooks, status state, and non-selectable guide headings. Replace broad source/layout assertions. |
| Version-update UI | 3 | Keep staged-update safety defaults, recovery workflow, and multi-selection conflict resolution. Remove sidebar placement and unrelated main-window composition. |
| File selection | 2 | Keep Ctrl/Shift/Ctrl+A selection semantics. |
| Engine dropdown | 2 | Keep engine discovery and applying the detected default. Move pure default-selection rules to core and remove splitter geometry. |
| Log viewer | 2 | Keep shutdown/non-tail lifecycle behavior. |
| Batch tab | 1 | Keep the ordering guarantee that completion callbacks run after worker cleanup. |
| Qt icons | 1 | Keep button text/icon transformation. Move pure mapping checks to core and remove a no-op widget smoke test. |

## Core/full-suite decisions

The core tier was reviewed by module inventory, slow-test timing, duplicate-name
inspection, and searches for source reads, layout assertions, sleeps, and exact
presentation contracts. The largest retained groups cover evaluation state and
pricing, provider batch state, translation caching/validation, RPG Maker source
preservation and rewrapping, Wolf extraction/injection safety, image mutation
safety, update staging/recovery, rate limiting, and API-key persistence. These
tests are cheap and exercise separate parser branches or failure modes; removing
them would trade small runtime savings for real regression gaps.

The audit removed source-substring workflow tests, exhaustive prompt prose
checks, guide ordering/wording checks, and duplicate shipped-asset assertions.
Prompt coverage now focuses on approval, path scope, immutable source fields,
required placeholders, and recovery choices. Shipped-data coverage still checks
asset existence, update eligibility, help-index references, and git tracking.

## Enforced budgets

| Tier | Test ceiling | Runtime target | Runtime ceiling | Per-test ceiling |
| --- | ---: | ---: | ---: | ---: |
| Core | 755 | 8 s | 15 s | 2 s |
| Extended | 97 | 12 s | 30 s | 3 s |
| Full | 852 | 20 s | 45 s | 3 s |

Raising a ceiling requires explicit user approval. New tests are core by default;
full widget/workflow tests must be deliberately classified as extended.
