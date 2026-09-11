# Len's Method review after SEQUEL thirst

This review addresses the September 2026 run's unclear progress, repeated context/QA overhead, RPG Maker locale behavior and ambiguous API/direct handoff.
The changes are in DazedMTLTool and its bundled skill; this review does not modify the game's translation or resume its playthrough.

| Finding | Change | Evidence and limits |
|---|---|---|
| English RPG Maker data could retain Japanese locale and name input. | The Len MV/MZ source-preserving writer sets an existing System locale to `en_US`, retaining the Japanese original. The engine reference requires checks for enabled locale-sensitive plugins, fonts and name input. | The existing source/QA round-trip case covers locale preservation and reinjection. Actual plugin checks remain specific to each game/build. |
| Single-batch context assembly repeatedly loaded shared guidance and references. | `context-many` compiles scene batches together, preserves complete context, checks dependencies again and exports source-bound requests. | All context fields matched single-batch output on the regression fixture and a 3,200-unit benchmark. Three warm runs had median times of 0.168s versus 0.055s, about 3.03× faster. This measures compilation, not translation or end-to-end completion. |
| An unfinished coverage audit hid useful progress, while elapsed days did not provide a meaningful ETA. | The panel shows completed/discovered units with explicit unaudited coverage, separate review/images/phases and remaining active-work estimates. Reports retain measured throughput samples and optional phase ranges. | Source/review fingerprints determine accepted counts. Changed scope/corpus, regressed counters, blockers and stale evidence invalidate or pause estimates. Unmeasured work stays explicit. |
| API and direct prompts could be copied without a clear cost boundary. | Explicit mode labels and mode-specific copy buttons; API Settings and Batch history links; a saved request quote with acceptance required for the API translation handoff. | Unquoted API translation is blocked; local preparation remains available. Source, guidance, reference, compiler and settings changes invalidate the quote. No translation provider calls were made during this review. |
| The skill's large entrypoint and blanket playtesting requirements encouraged expensive repeated work. | Reduced the entrypoint from 771 to 192 lines, preserved detailed engine lessons in a searchable reference, added direct/API workflows and replaced per-export full-menu/map walks with targeted checks. | Full playthroughs and additional testers are optional unless requested. Independent extraction coverage, structural/source checks, affected runtime checks and clean-copy delivery remain required within scope. |

## Progress contract

The assistant exports accepted saved records after batches/milestones, at least every 10 minutes during active work, and before a long wait or handoff.
The user receives a concise update with completed/discovered counts, audited coverage status, current phase, remaining active-work range, next checkpoint and blocker.
Translation, review, authorized images, injection, QA and packaging remain distinct.
A text bar at 100% does not establish release readiness.
The panel depends on these saved reports; it cannot infer actual completion from a running assistant process or a narrative log.

Direct translation starts with scene-aware batches, adapts their size to context/output limits and validates accepted units immediately.
Global checks run at bounded milestones and after changes that invalidate their assumptions, rather than after every small batch.
Saved evidence can be reused only when relevant source/output/context/validator/renderer dependencies still match.
Original source provenance is never regenerated merely to make old output pass.

## API boundary

An accurate whole-job quote needs the complete extracted request plan.
Before that, Len offers a preparation-only prompt and clearly reports that the estimate is unavailable, rather than displaying $0.
After preparation, the user reviews model/provider, request count, tokens, Batch cost, Live comparison and displayed rates before copying the API translation prompt.
The quote uses the application's pricing helpers and a 2.5× source-token output allowance.
Rates may use configured/built-in fallbacks and should be checked for the selected model.
Retries, billed reasoning, images, assistant work, QA and provider wait time are excluded; the quote is not a spending cap.

The existing API settings and supported Batch lifecycle are reused.
A Len request plan is not automatically an executable job for every engine in the historical tool bundle.
The engine adapter still collects its actual requests, checks their final estimate and uses the supported backend for submission/resume/collection.
Unsupported Batch routes do not fall back to Live translation silently.

## Validation

Existing handoff, source-preservation, progress and GUI cases were extended; distribution checks now include the new references.
The API preflight scenarios were consolidated into the existing handoff lifecycle test, keeping the test-count budgets unchanged.
No test runner, partition or runtime budget was changed.
Required suite results:

| Command | Selected tests | Elapsed / ceiling |
|---|---:|---:|
| `./tests/run_tests.sh core` | 780, with 5 existing skips | 1.955s / 8s |
| `./tests/run_tests.sh integration` | 130 | 7.838s / 20s |
| `./tests/run_tests.sh extended` | 100 | 8.213s / 30s |

All three passed their existing runtime and count budgets.
The initial sandboxed core attempt could not write existing test logs/staging files; rerunning with application-directory write access resolved those environment errors.
The final focused run of the handoff, source/QA, GUI and bundled-file tests passed (47 tests).
The skill validator, entrypoint reference check and whitespace check passed.
An offscreen Qt check exercised the real estimate worker with local fake token/pricing inputs, quote acceptance, clipboard handoff and mode switching.
Settled renders of the quote, progress and direct-mode screens were inspected; the initial captures occurred before Qt completed layout and were recaptured after processing its layout events.
No paid translation calls, release publishing or new game playtests were performed.
