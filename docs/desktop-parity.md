# Electron replacement parity contract

Electron is the replacement target. Qt remains the production entry point until
required native acceptance gates are met. Feature implementation and exercised
behavior are recorded separately below; an untested engine/platform/provider is
not implied to be validated by reusing its shared backend.

The implementation order was production adapter → image editor → runtime and
packaging → workflow/UI parity → cutover checks. Len and Git remain supported
through their existing services. No package is signed or published by this work.

| Area | Preserved contract | Implemented and exercised | Remaining acceptance |
| --- | --- | --- | --- |
| Runtime and saved work | Existing engine helpers/defaults; isolated inputs and saved jobs | Linux standalone package, readonly snapshot import, frozen plans, draft/approval recovery, cancellation, Unicode relocation and profile retention | Windows/macOS native runs; cold-cache measurements |
| RPG Maker MV/MZ | Production parser, glossary, speakers, runtime codes, wrapping, `_original` | Real offline database/dialogue translation; actor dependencies; shared phase profiles, variable-cache/glossary handoff; reviewed export and original preservation | Additional real translated-game playtests |
| Guided RPG Maker | [Behavior inventory](rpgmaker-workflow-behavior-inventory.md) | All ten stages call shared preparation, translation, references, rewrap, QA, images, playtest and release services. Electron phase→export, stale-action rejection, drafts, reference/setup and release/plugin flows pass | Native Ace and real-game playtests; full QA task completion belongs to the invoked QA workflow |
| RPG Maker Ace | Existing decrypter, RV2JSON, Ruby audit and packing | Engine detection, supported stages, native tool routes, Ruby handoff and public ZIP controls exposed. Real bundled tools pass generated decryption/extraction/repacking under Wine; originals/backups are preserved. Changed native databases or archives invalidate action previews; game preparation rejects directory junctions as well as symlinks | Native Windows execution remains required; Wine is compatibility evidence |
| WOLF | WolfDawn extraction/originals/precheck/injection/package helpers | Ten stages, safe names, database profiles/scopes, speakers, wrapping and saves exposed. Offline event extraction→translation→repeat injection passes in Electron; component checks cover relocated manifests, database scopes and stale injection. Real Linux and Wine-hosted Windows binaries pass archive pack/unpack/repack with original payload preservation | Native Windows/macOS runs and map/database/save fixtures; no macOS WolfDawn binary is currently bundled |
| Manual engines | Same 19-engine registry and shared Qt-free `TranslationTask` | All handlers/settings exposed; real RPG Maker estimates, CSV output/export, WOLF workflow, saved-job recovery, speaker/batch approval boundaries and source isolation | Real fixtures for engines outside the exercised set |
| Len’s Method | `len_translation`, `len_api`, Git, progress and patch scope | Both handoff modes, scope switches, guidance, references, profile-aware CLI, saved drafts and progress. Source/package handoff→Git flow passes; native reference add/pair/build/remove and counted-progress display pass | Actual assistant-driven completion and game validation remain the handoff’s work |
| Git version updates | Existing bootstrap/reconcile, registration, branches, exact update plan, assets, conflicts and handoff | Electron rejects changed official input then applies a fresh preview; worker checks cover abort/retry, conflict continuation, registration/switch and metadata using disposable repos | Native Windows/macOS subprocess/path behavior |
| Image manager/editor | `image_manager`, engine discovery, portable jobs and existing renderer | Editable copies, text exchange, region geometry, styles/reconstruction, painting, draft conflicts, render/review/export and guarded patching. Source/package image paths pass; existing image suite covers reused rendering behavior | Live OCR uploads and optional model installation were not performed; native external tools need platform checks |
| Batch history and recovery | Original provider IDs, credentials/endpoints, paid request ownership and shared locks | Local/legacy discovery, credential binding, refresh/cancel/usage/download, prepared resume. Real CSV/RPG Maker collect→synthetic results→consume passes. Partial queues remain linked to original files/locks; queue-change rejection, exactly-once fake submission, decline preservation and explicit legacy RPG profile confirmation pass | Live external provider routes are not inferred from fake-transport checks |
| API settings | Shared named vault, endpoint/model routes, pricing and engine options | Credential add/select/edit/delete, keyless endpoint, provider discovery lifecycle, presets, resets, legacy import, settings-file drafts/export and secret redaction verified at service/UI boundaries | Actual model discovery on each desired external account |
| Instructions/glossary/references | Shared prompt/context/base-glossary and per-game guidance/reference utilities | Profile overrides reach workflow, Len, manual and evaluation workers. Placeholder checks, stale edits, imports/restores and draft recovery pass. Embedded/paired matches and shared setup guidance verified; reference source games remain unchanged | No remaining local implementation gate identified |
| Evaluation | Immutable manifests, budgets, checkpoints, batch/live jobs, blind reviews and archives | Setup/settings, estimates and exact approval/binding, collection, paired/ranking reviews, calibration/audits, browsing and archive import/export connected to shared services. Real offline workers and source/package UI round trips pass | Live model comparisons require separately authorized payloads and spend |
| Guide/preferences/navigation | Shipped help, project/settings transfer, display preferences and draft lifecycle | Guide images/links, navigation shortcuts, scale/settings transfers and defaults pass. Independent tool pages show their own context; snapshot project selection stays on snapshot pages | Native platform presentation/accessibility checks |
| Application updates | Shipped-data protection, complete runtime compatibility, recovery and rollback | Full-package lookup/download/staging, integrity checks and restart/rollback implemented. Actual Linux restart into changed defaults and rollback preserves profile data and original package; interrupted-start recovery checks pass | Published release artifacts, signing and Windows/macOS update acceptance |
| GameUpdate/playtest/public release | Existing updater configuration, TL Inspector/Forge installers, walkthrough and release exclusions | Actual Electron settings→GameUpdate→plugin install/apply/remove→clipboard→ZIP flow passes. Explicit overwrite notice and changed-output rejection preserve newer archives; public ZIP retains game/updater payload and excludes private tool files/saves | Actual in-game playtest and release approval |
| Distribution/migration | Bundled Python/tools/defaults and explicit legacy recovery | Linux includes Python 3.12.14, locked dependencies and tokenizer; no private vaults/workspaces. Settings/guidance/portable-image/evaluation and legacy-batch import paths exercised | Windows/macOS packages; no blanket automatic migration of an arbitrary old installation |

## Recorded test gates

Latest relevant Python gates on Linux:

| Suite | Tests | Total | Enforced ceiling | Result |
| --- | ---: | ---: | ---: | --- |
| Core | 776 | 5.157 s | 8 s | Pass; slightly above the 5 s ratchet target |
| Integration | 124 | 15.915 s | 20 s | Pass |
| Extended | 100 | 18.178 s | 30 s | Pass |
| Full | 1,000 | 35.984 s | 45 s | Pass; 2 existing skips |

Ten overlapping case groups were parameterized with their assertions retained.
The full count now meets its existing 1,000-test ceiling. No runtime, module,
per-test or count limit was raised. The six desktop integration cases take about
0.37 seconds within the integration tier. See the
[validation report](desktop-prototype.md) for acceptance scope and earlier image
and paid-test evidence.

The five-flow Electron suite passed from source at the feature checkpoint in
**58.2 seconds** and from the latest Linux package in **59.7 seconds**, within the unchanged
60-second global and 20-second per-test ceilings. Earlier runs exceeded the
global limit. Active-job refresh now updates completion/approval controls more
promptly, and completion assertions poll more often while retaining their
expected states and 10-second deadlines. The suite still has limited runtime
headroom; native platform checks remain required.

The current package ID is
`3dc76e32afd6aba87cba6e25efec6dde3054394d12399e9203acb40e2d6dd183`.
Its archive SHA-256 is
`1911a65fca16c701338dfc148d15e9977dd61376147cbca0128deac16eae6f74`.
The standalone legacy-profile, reference/progress and release/playtest checks
passed at the feature checkpoint. The current package also passes 13 real
native-tool steps in 9.647 seconds: Linux WOLF archives, Windows WOLF through
Wine, and Ace decryption/extraction/repacking through Wine. Original archives,
untouched payloads and Ace backups remain intact. These are compatibility
checks; native Windows execution and its real junction fixture remain pending.
The complete package inventory is verified after the final smoke suite.

## Saved checkpoint and native continuation

Local checkpoint `1bce6748` is retained under
`refs/checkpoints/electron-replacement-20260930T030201Z`. Its validated package
and checksum are preserved in the ignored `.tmp-ui/desktop-checkpoints/` folder.
The current branch and staging were preserved.

The continuation adds Ace native-input preview guards, junction protection and
`desktop/scripts/check-native.py`. The CI workflow can select a native OS and
retains its generated evidence. A push to a dedicated
`codex/electron-validation-*` branch runs Linux/Windows checks; other branches
remain manual. The workflow does not publish application releases. No validation
branch has been pushed and no native CI run is claimed here.

## Cutover requirements

- Keep engine/provider behavior in shared Python services and preserve the
  existing workflow destinations, confirmations and recovery rules.
- Run generated-fixture checks without private games, user settings or network
  dependence. Real games are explicit manual acceptance inputs only.
- Preserve the cumulative $5 development-test ledger and exact-payload consent.
  Normal configured-provider execution is a separate explicitly enabled mode.
- Pass source and packaged Electron checks without weakening their five-test,
  20-second per-test or 60-second global limits.
- Run the committed manual desktop package workflow on Windows and macOS, then
  verify required native engine tools, relocation and saved-work recovery.
- Keep Qt as the production launcher until the required native checks are
  verified. Sign/publish packages and switch the launcher as a release decision.
