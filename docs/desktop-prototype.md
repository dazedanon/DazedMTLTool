# Electron replacement validation

Electron is the sole desktop replacement target. The app reuses the existing
Python engines and services for Len’s Method, Git updates, guided RPG Maker/WOLF
workflows, all registered manual engines, image tools, batch recovery, evaluation,
settings, guidance, playtest plugins and release ZIPs. The
[desktop guide](../desktop/README.md) documents these paths; the
[parity contract](desktop-parity.md) distinguishes verified behavior from native
platform and external-service checks still required before production cutover.

Qt remains the production launcher. The Linux preview is packaged and runnable;
Windows/macOS native acceptance, signing and publication have not been performed.
No commits, repository pushes, releases or CI dispatches are implied by these
local validation results.

## Shared architecture and preservation

A sandboxed React renderer uses an allowlisted Electron preload bridge. One
Python service communicates over private stdin/stdout pipes. Credentials never
enter renderer state, and the renderer has no general network, process or file
access. Heavy engine, image and workflow operations run in dedicated workers.
The service serializes heavy work and locks each desktop workspace against a
second instance.

Manual translation and evaluation freeze their inputs, settings, instructions
and engine identity. Saved work retains output ownership, provider response
checkpoints, approval state and recovery information. Changed files invalidate
stale actions. Editor drafts remain separate from applied context or approved
translations; normal close flushes them and reports failures before exiting.

Snapshot import and separate exports preserve the selected source. Guided
preparation/export, Len setup, Git updates, plugin installation and game image
patching explicitly operate on the selected game through the existing services.
Their destinations and confirmations remain visible. Public release packaging
uses the shared exclusions for private tool files and saves while retaining the
existing game payload and updater behavior.

Legacy batches retain their original credential and endpoint. Fully submitted
runs can copy recovery data into an isolated manual workspace. Unsubmitted or
partially submitted queues remain in the original folder under the same
cross-process submission lock; copied inputs and frozen context remain private.
Queue identity/content checks prevent resubmitting changed or already-paid work.
Declining a linked submission preserves the original queue. Older RPG Maker
batches require explicit review of their missing code profile before writing
results; confirmation is bound to the prepared recovery files and frozen plan.

Normal configured-provider execution is enabled separately from the capped Luna
development broker. Automated checks use synthetic fixtures, fake provider
transports and blocked networking. No optional OCR/model download or image upload
has been used merely to validate the replacement.

## Linux acceptance evidence

The five Electron smoke flows cover:

1. Len handoff/recovery/clipboard, progress and navigation into Git updates;
   rejection of a changed official source followed by a fresh preview/apply.
2. Manual RPG Maker estimation, CSV translation/export, engine registry and
   saved batch discovery.
3. WOLF extraction, offline event translation and repeat-safe injection.
4. Guided phase translation/export, original preservation, stale confirmation
   rejection and persisted guidance drafts.
5. Snapshot translation/review/export, image edit/render/review, draft conflicts,
   close/reopen recovery, settings and global-instruction/guide navigation.

Additional generated-fixture checks exercise the real Python workers for
credential/settings transfers, reference and glossary propagation, evaluation
preparation/checkpoints/review/archive contracts, completed and partial batch
recovery, and legacy RPG Maker profile confirmation. The legacy acceptance
collects requests with the real engine, supplies synthetic provider results,
then consumes them with that engine without changing the source or making a
provider request.

The public-release/playtest acceptance uses the actual Electron controls to
install GameUpdate, save custom hotkeys, install/apply/remove TL Inspector and
Forge, copy the walkthrough handoff, reject a changed ZIP destination and build
an archive with the shared exclusions. This verifies integration and artifacts;
it does not establish an actual game’s playability or translation quality.

Whole-package update acceptance uses real application restarts into a staged
build and back to the previous build. It verifies changed shipped defaults,
preserved settings/credentials/instructions, health acknowledgement, rollback
and unchanged original package contents. Node checks cover damaged inventories,
changed/stale package selections, interrupted startup and release-feed filtering.
See [desktop updates](desktop-updates.md).

Screenshots and measurements are retained under `.tmp-ui/desktop-evidence/`.
The source and packaged smoke suites use disposable fixtures and profiles;
real local games are never automated-test dependencies.

## Test budgets

Python tiers retain the existing 8/20/30/45-second core/integration/extended/full
ceilings and their per-test/module limits. The Electron suite retains five tests,
20 seconds per test, a 60-second global limit, one worker and zero retries.
No count or runtime budget has been raised.

The former 1,010-test full-suite count was consolidated to its 1,000-test
ceiling by parameterizing overlapping input variants. Assertions remain for
atomic-write retry/failure, shared mutation locks, source-context resolution,
legacy failed/pollable evaluation states, protected review fields, cost estimates,
credential migration/sync, content failures and schema-versus-transport retries.
GUI assertions remain in the extended/Electron tiers; provider and persistence
behavior is checked at the cheaper shared-service boundary where practical.

The full suite passes all 1,000 tests in 35.984 seconds (two existing skips).
Final source and packaged Electron runs pass in 58.2 and 59.7 seconds. Several
preceding GUI runs exceeded 60 seconds; active progress refresh and test
completion polling were shortened without changing scenarios, expected states
or timeouts. The suite remains close to its global ceiling. Detailed tier and
package results are recorded in the parity contract. Reproduce them with the
commands in `desktop/README.md`.

## Package and performance evidence

The Linux package bundles Electron, managed CPython 3.12.14, hash-locked Python
dependencies, shared engines/helpers, shipped defaults and offline tokenizer data.
Private settings, vaults, game workspaces, logs and optional models are excluded.
The package has a complete file inventory and relocatable internal links.
The current extracted Linux build occupies approximately 807 MiB; its compressed
archive is about 300 MiB, including Python and dependencies.
Precompiled Python caches keep application files unchanged during real engine
and image work; writable profile environments support optional installations.

The profile survived relocation to a Unicode path with settings, an installed
optional Python module and the Len CLI intact. A recent debugger-free Linux
relocation check observed 1,408 ms / 334 MiB process-tree PSS on initial setup and
528 ms / 312 MiB after relocation. These are local warm-filesystem observations,
not cold-start or cross-platform guarantees. Reproduce with
`scripts/desktop_package_acceptance.py`.

Historical comparison before removing Tauri:

| Measure | Electron 44.4.5 | Tauri 2.12.0 / system WebKit |
| --- | ---: | ---: |
| Median readiness, three empty launches | 453 ms | 528 ms |
| Median process-tree PSS | 283 MiB | 263 MiB |
| Loaded 38,453-entry project, one launch | 553 ms / 335 MiB | 628 ms / 303 MiB |
| Shell payload, excluding Python/tools | 282.6 MiB | 6.8 MiB |

The Tauri comparison is historical evidence, not a supported target. The later
Electron-only launch of the same loaded workspace measured 553 ms / 287 MiB PSS.
Variation between single launches does not establish causation. Automated browser
working-set measurements are not directly comparable to debugger-free PSS.

## Earlier real-game and paid acceptance

Read-only original-branch imports succeeded on Loccubus (22 data files, 18,160
supported entries) and Lulumachi (242 files, 38,453 entries). Source Git state and
data stayed unchanged. Offline production-engine processing of Lulumachi Actors,
Items and Map001 took 9.20 seconds and produced 383 review entries with no runtime
code mismatches or unresolved review mappings. Nine content warnings arose from
synthetic test translations; this was engine integration evidence.

Three Luna API requests were previously made: one for four generated fixture
phrases, and two for the same four explicitly approved Lulumachi item names
through the diagnostic and production-parser paths. Exact-payload guards ran
immediately before dispatch. The production request completed in 7.55 seconds;
all four results were reviewed/exported with Japanese `_original` records intact.
No further game text, provider requests or image uploads were used in the later
migration checks.

The canonical ledger is `.tmp-ui/desktop-workspace/spend.sqlite3`: three requests,
$0.000683375 estimated usage, $0.06 reserved against the $5 cumulative cap, and
zero requests with unknown usage. Never reset or replace it to continue paid
testing. The broker reserves $0.02 per attempt, including failures/timeouts, with
no automatic retries, a 100,000-byte prompt limit and a 4,096-output-token limit.
Those limits apply to this development broker; normal configured-provider jobs
retain their own existing settings and approval flows.

## Remaining native release gates

- Run the committed package workflow on Windows and macOS. Check native engine
  executables, cancellation, Unicode/long paths, relocation and recovery there.
- Validate any desired live provider/OCR route using the correct account and
  explicitly approved payload; offline fakes do not establish external uptime.
- Playtest real translated games before treating a release ZIP as release-ready.
- Sign/publish distributables and change the default launcher only after the
  required platform and parity gates have been met.
