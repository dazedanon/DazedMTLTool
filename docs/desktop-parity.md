# Electron replacement parity contract

Electron is now the application UI. Source launchers prepare private runtimes;
existing Qt shortcuts forward to the same bootstrap after an archive update. Feature implementation and exercised
behavior are recorded separately below; an untested engine/platform/provider is
not implied to be validated by reusing its shared backend.

The implementation order was production adapter → image editor → runtime and
packaging → workflow/UI parity → cutover checks. Len and Git remain supported
through their existing services. No package is signed or published by this work.

| Area | Preserved contract | Implemented and exercised | Remaining acceptance |
| --- | --- | --- | --- |
| Runtime and saved work | Existing engine helpers/defaults; isolated inputs and saved jobs | Linux standalone package, readonly snapshot import, frozen plans, draft/approval recovery, cancellation, Unicode relocation and profile retention | Windows/macOS native runs |
| RPG Maker MV/MZ | Production parser, glossary, speakers, runtime codes, wrapping, `_original` | Real offline database/dialogue translation; actor dependencies; shared phase profiles, variable-cache/glossary handoff; reviewed export and original preservation | Additional real translated-game playtests |
| Guided RPG Maker | [Behavior inventory](rpgmaker-workflow-behavior-inventory.md) | All ten stages call shared preparation, translation, references, rewrap, QA, images, playtest and release services. Electron phase→export, stale-action rejection, drafts, reference/setup and release/plugin flows pass | Native Ace and real-game playtests; full QA task completion belongs to the invoked QA workflow |
| RPG Maker Ace | Existing decrypter, RV2JSON, Ruby audit and packing | Engine detection, supported stages, native tool routes, Ruby handoff and public ZIP controls exposed. Real bundled tools pass generated decryption/extraction/repacking under Wine; originals/backups are preserved. Changed native databases or archives invalidate action previews; game preparation rejects directory junctions as well as symlinks | Native Windows execution is unverified; Wine is compatibility evidence |
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
| Application updates | Shipped-data protection, complete runtime compatibility, recovery and rollback | Source-archive and full-package staging, integrity checks and restart/rollback implemented. Actual Linux update/restart/rollback passes for both routes, preserving profile data and originals; interrupted-copy and interrupted-start recovery checks pass | Published release artifacts, signing and Windows/macOS update acceptance |
| GameUpdate/playtest/public release | Existing updater configuration, TL Inspector/Forge installers, walkthrough and release exclusions | Actual Electron settings→GameUpdate→plugin install/apply/remove→clipboard→ZIP flow passes. Explicit overwrite notice and changed-output rejection preserve newer archives; public ZIP retains game/updater payload and excludes private tool files/saves | Actual in-game playtest and release approval |
| Distribution/migration | Bundled Python/tools/defaults and explicit legacy recovery | Linux cold setup with no system Python/Node installs Python 3.12.14, locked dependencies and Electron. Automatic in-place Qt migration preserves engine options, settings, named keys and original work; standalone packages include the same runtime | Windows/macOS packages; arbitrary external installations still require explicit import |

## Recorded test gates

The Qt retirement gates use the original budgets. No suite, module, per-test or
count ceiling was raised.

| Check | Tests | Total | Enforced ceiling | Result |
| --- | ---: | ---: | ---: | --- |
| Core | 764 | 4.891 s | 8 s | Pass; below the 5 s ratchet target |
| Integration | 128 | 16.713 s | 20 s | Pass |
| Full Python | 892 | 20.056 s | 45 s | Pass; 2 existing skips |
| Full Python in managed, Qt-free runtime | 892 | 23.275 s | 45 s | Pass; 2 existing skips |
| Electron source, as part of full | 5 | 54.2 s | 60 s | Pass |
| Electron Linux package | 5 | 59.5 s | 60 s | Pass |
| ImageTL, managed runtime | 216 | 1.295 s | 30 s | Pass |

`./tests/run_tests.sh full` runs Python and then the established Electron suite.
Electron keeps its 20-second per-test ceiling and limited total runtime headroom.
The earlier sandboxed UI attempt could not launch Electron; native desktop runs
above passed. No provider requests were made during retirement validation.

Fresh setup was exercised with no Python, Node, npm or Git on PATH, downloading
verified runtimes and locked dependencies into an empty private cache. A warm
offline launch connected to Python. The complete source archive also passed
through the frozen old Qt updater: custom CSV options, language/width, credentials,
files and logs survived; the old `start_gui.py` shortcut opened Electron. Known
retired GUI files were backed up before cleanup.

Actual one-click source update → restart → rollback → restart preserved settings,
the vault and shared instructions. Actual standalone package update/rollback
preserved those same profile files and the original package inventory. Separate
checks cover interrupted copies, stale stages, changed-file rollback rejection,
credential collisions, evaluation-import retries and the old archive's engine
preservation contract. First-party Ruff checks pass; whole-repository lint still
reports 54 pre-existing findings in bundled third-party decompiler scripts.

The final Linux package metadata and checksums are recorded in
`desktop/out/package-result.json`; the retirement evidence is retained in
`.tmp-ui/desktop-evidence/qt-retirement.json`. Signing, publication and native
Windows/macOS execution are not part of these local results. Windows ARM setup
uses matching x64 runtimes for the locked OpenCV dependency. Earlier native-tool
checks remain recorded in the [validation report](desktop-prototype.md): Linux
WOLF archives, Windows WOLF under Wine, and Ace decryption/extraction/repacking
under Wine. These do not establish native Windows or macOS acceptance.

## Saved checkpoint and local continuation

Local checkpoint `1bce6748` is retained under
`refs/checkpoints/electron-replacement-20260930T030201Z`. Its validated package
and checksum are preserved in the ignored `.tmp-ui/desktop-checkpoints/` folder.
The current branch and staging were preserved.

The second UI QA pass starts from checkpoint `11d489bd`, retained under
`refs/checkpoints/electron-ui-qa2-20260930T132208Z`. It includes local CI cleanup
and a checksum-verified copy of the preceding Linux package. No local GitLab
runner binary, process, service or registration configuration was installed.

The continuation adds Ace native-input preview guards, junction protection and
the optional local `desktop/scripts/check-native.py` command. Runner-based CI
validation was dropped at the user's request on September 30, 2026; its local
configuration and orchestration script were removed. Native CI is not a
prerequisite for the second UI QA/polish pass. Unexercised platforms above remain
unverified, rather than being counted as passing.

Fresh-checkout verification also found that Git stored the Linux WOLF helper
without its executable bit. Packaging now establishes its executable mode before
writing the runtime manifest, independently of local permissions. The updater
checks actual symbolic links/junctions instead of rejecting normal Windows path
case or short-name normalization.

## Second UI QA and polish

The review covered all 15 navigation destinations, all ten RPG Maker stages,
empty and populated workspaces, 900×650 windows and 125% interface scaling.
Captures and audit results are retained in the ignored `.tmp-ui/qa2/` directory.
The screen sweep recorded no renderer errors, visible unlabeled fields or
page-width overflow. Native Electron captures were used for scaled layouts.

- The welcome screen offers the full guided workflow, Len’s Method and manual
  engines directly. Snapshot review is identified as a separate workflow.
- Navigation is grouped by purpose. Settings, Guide and application updates
  remain visible while the main navigation list scrolls.
- Guided actions use native modal dialogs with contained keyboard focus,
  Escape cancellation and focus restoration. Stale-preview errors appear in
  the dialog and require a fresh preview before retrying.
- Game pickers align their fields and buttons; active stages stay in view.
  A duplicate recent-project selector is omitted when only one project exists.
- Settings support section search, a persistent save bar and a compact transfer
  disclosure. Filtering preserves the full draft and hidden setting values.
- Evaluation tabs support arrow keys, Home and End; saved-run filters appear
  when there are saved runs. Confirmation dialogs share the same modal behavior.
- Image render/approval/export actions stay above the canvas. Translation text
  takes priority in the inspector; position, order and rotation remain available
  in a disclosure. Tool buttons now expose descriptive hover labels.

The existing five Electron flows retain Len/Git handoff, manual engine execution,
WOLF extraction/injection, guided translation/export and snapshot/image review.
The guided test now also protects keyboard cancellation without importing and
visible stale-preview rejection. No new test cases or larger budgets were added.
Additional offline UI checks cover settings search/import/export and presets,
instruction draft recovery, guide links/images, evaluation preparation/cost
approval/comparison/archive export, and real GameUpdate/playtest/plugin/release
actions against generated games. Original files and private release exclusions
remain protected. This pass made no provider requests.

## Cutover requirements

- Keep engine/provider behavior in shared Python services and preserve the
  existing workflow destinations, confirmations and recovery rules.
- Run generated-fixture checks without private games, user settings or network
  dependence. Real games are explicit manual acceptance inputs only.
- Preserve the cumulative $5 development-test ledger and exact-payload consent.
  Normal configured-provider execution is a separate explicitly enabled mode.
- Pass source and packaged Electron checks without weakening their five-test,
  20-second per-test or 60-second global limits.
- Keep platform limitations visible; runner-based native CI is not required.
- Sign/publish packages and switch the production launcher as a release decision.
