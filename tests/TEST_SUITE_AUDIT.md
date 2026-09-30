# Test-suite audit

Audit dates: 2026-08-02, 2026-08-21, and 2026-08-25

## 2026-08-25 scalable tiering follow-up

The 900-test core profile had grown to 16.0–16.9 seconds despite every test
remaining below one second. Cumulative module timing showed that two modules
accounted for 13 seconds: real Git repository/update workflows used 9.832
seconds and persisted end-to-end evaluation workflows used 3.162 seconds. All
other core modules combined used about 2.7 seconds.

Those workflows now have an explicit `integration` profile. Full remains the
deterministic union of core, integration, and extended, while ImageTL remains
dependency-isolated. The resulting partitions contain 770 core tests, 128
integration tests, 99 extended tests, and 997 full tests. The final post-change
core run completed in 4.621 seconds including discovery (2.774 seconds of test
execution); integration completed in 16.106 seconds including discovery; and
full completed in 38.421 seconds including discovery.

Runtime enforcement now has three levels: whole-suite ceilings, per-test
targets/ceilings, and cumulative module ceilings. Core has a strict 0.5-second
per-test ceiling. Other profiles surface one-second target debt and enforce a
1.5-second ceiling; this preserves the desired limit without making real-Git
tests fail when the same scenario fluctuates from 0.96 to 1.13 seconds. Existing
integration and UI module debt has named overrides rather than granting every
future module the same allowance. Core's enforced suite ceiling was tightened
from 15 seconds to 8 seconds. Whole-suite timing now includes test discovery
and imports, which the previous runner left outside its clock.

Discovery-inclusive healthy targets are 5 seconds for core, 18 for integration,
20 for extended, 15 for ImageTL, and 40 for full. Enforced ceilings remain 8,
20, 30, 30, and 45 seconds respectively.

The repository guidance no longer requires the whole core suite for isolated
data, registry, documentation, or configuration changes that add no behavior.
It also explicitly rejects new declarative-entry tests when the processing path
and schema consistency are already covered.

The runner also sets an explicit test-offline mode before importing application
modules. Pricing fallback tests therefore cannot perform a live catalog lookup
because a local cache is stale or absent.

## 2026-08-21 follow-up

The default environment now selects 886 core tests and 97 extended tests. The
`full` profile is their deterministic 983-test union regardless of whether
optional image dependencies happen to be installed.

Three ImageTL modules previously raised `SkipTest` during import when OpenCV
was absent. Discovery counted those as three tests, but an OpenCV-enabled
environment loaded 312 real tests instead, making the old full-suite count and
runtime environment-dependent. Those modules now have an explicit `imagetl`
profile with a 312-test ceiling. A missing dependency produces an actionable
error instead of a misleading three-test success. The measured ImageTL run
completed in 9.556 seconds.

Eight overlapping batch-history method wrappers were consolidated into labeled
`subTest` matrices for persisted run states and legacy cache-key versions. An
empty-state method was removed because the queued-state test already verifies
the same state after clearing. Every prior input, expected state, and
paid-boundary safeguard remains covered. Together with one partition regression
test and the removal of three optional-module placeholders from `full`, this
reduced the deterministic full profile from 993 to 983 tests.

Evaluation estimates now tokenize each logical request once per estimate and
multiply by its execution repetitions. Token and cost totals are unchanged.
The follow-up core run completed in 14.000 seconds, compared with roughly
15–16 seconds before the change. Full completed in 31.714 seconds. Both remain
above their ratchet targets but within the unchanged enforced ceilings.

The remaining runtime is concentrated in real Git version-update integration
tests and full workflow-shell construction. Future optimization should extract
pure controller/planning seams while retaining focused integration smoke tests.

## 2026-08-02 outcome

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
| Core | 903 | 8 s | 15 s | 2 s |
| Extended | 97 | 12 s | 30 s | 3 s |
| ImageTL | 312 | 12 s | 30 s | 3 s |
| Full | 1000 | 20 s | 45 s | 3 s |

The 1,000-test full ceiling is capacity, not a target. New tests must still
protect distinct behavior and related cases must be combined or parameterized.
New tests are core by default; full widget/workflow tests must be deliberately
classified as extended, while OpenCV-dependent image tests belong in ImageTL.
Raising a ceiling requires explicit user approval.
