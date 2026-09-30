# DazedTL Electron desktop

Electron is the replacement target. The desktop preview runs the existing Python
engines and services behind a React/TypeScript interface. Len’s Method, Git version
updates, guided workflows, manual engines, image tools, batch recovery, evaluation,
settings, references, playtest tools and public release packaging are connected.
The Qt launcher remains the production entry point while the remaining native
platform checks are completed. See the [parity contract](../docs/desktop-parity.md)
and [validation report](../docs/desktop-prototype.md).

## Launch from source

Use Node 22.12+ and the repository’s Python environment:

```sh
cd desktop
npm ci
npm run build
npm start
```

If Electron’s download was skipped, run `node node_modules/electron/install.js`.
`DAZEDTL_PYTHON` selects an interpreter other than the repository’s `.venv`.
The launcher also supports explicit provider modes:

```sh
.venv/bin/python scripts/start_desktop.py
.venv/bin/python scripts/start_desktop.py --providers
.venv/bin/python scripts/start_desktop.py --live
```

`--providers` enables normal configured-provider operations, including manual
engines, evaluation, batch management and optional tool installation. These use
the saved provider settings and existing approval flows. They do **not** use the
Luna development-test cap. `--live` separately enables the cumulative $5 Luna test
broker used by **Translate** and **Text sample**. Packaged equivalents are
`DAZEDTL_DESKTOP_PROVIDERS=1` and `DAZEDTL_DESKTOP_ALLOW_LIVE=1`. Both default off.
Offline test text is synthetic and is labeled accordingly.

## Choose a workspace

- **Guided workflow** opens an RPG Maker MV/MZ, Ace or WOLF game. Its stages cover
  preparation, translation, references, export, QA, images and playtesting. Engine
  jobs use isolated inputs; explicit preparation/export/plugin/Git actions show
  their destination and can change the selected game. Ace hides unsupported
  stages and retains its existing native conversion tools.
- **Len’s Method** prepares either supported handoff, edits guidance and
  references, tracks shared progress, and opens the same game in **Git version
  updates**. Version updates use the existing preview/apply, branch, asset and
  conflict-recovery services. Private credentials stay in the desktop profile.
- **Manual engines** exposes all 19 registered handlers. Select a folder and
  engine, review the file selection, then estimate, translate, collect speakers,
  batch or run an offline check. Inputs, settings and instructions are frozen.
  Saved jobs retain progress, approvals, output ownership and recovery details.
- **Batch history** discovers manual/evaluation jobs and explicitly added legacy
  folders. Old jobs require their original named credential. Import copies engine
  inputs and context; unfinished queues remain linked to their original folder
  and submission lock. Keep that folder available. Prepare recovery before
  resuming, and explicitly confirm missing legacy RPG Maker code profiles.
- **Images** discovers engine assets, creates editable copies and opens portable
  image jobs. It supports OCR, image-text translation, paint/erase, typography,
  render/review/export and guarded game patching. Google Lens uploads the chosen
  original image only after confirmation; local OCR needs its optional models.
- **Evaluation** freezes a shared sample and model settings, estimates costs,
  requires submission approval, collects batches or live checkpoints, and supports
  paired/ranking reviews, calibration, comparison and portable archives.
- **Shared instructions** edits profile-wide prompts, contexts and the base
  glossary. Project editors handle game guidance, quirks and glossary separately.
  Saved translation/evaluation runs retain their frozen context.
- **Settings** manages credentials, providers, engine options, presets, playtest
  defaults and display preferences. Explicit legacy installation import preserves
  the old installation. Settings-file import opens a reviewable draft; export
  excludes credentials. **Guide** displays the shipped help.
- **Updates & rollback** stages verified whole packages, restarts into an update,
  and restores the preceding build. See [desktop updates](../docs/desktop-updates.md).

**Overview**, **Translate**, **Review & test** and **Release** operate on isolated
RPG Maker snapshots. Their project selector applies to those pages. Original Git
branch import is read-only. Reviewed output can become the next isolated working
revision or an exported JSON overlay. **Release** on this path creates a data test
copy; use **Guided workflow → Playtest → Public release** for the complete sanitized
public ZIP (Ace: Translation QA; WOLF: Package & saves).

## Saved work and safeguards

Normal close flushes editor, settings and image drafts before stopping Python.
If saving fails, the app stays open unless the user explicitly discards the edit.
Draft recovery does not approve translations or apply guidance. Changed source
files, plans, output ownership or recovery data invalidate stale actions.
One desktop instance owns a profile, and one heavy operation runs at a time.

Source development uses `.tmp-ui/desktop-workspace/` by default. Packaged builds
use Electron’s per-user DazedTL profile with writable `tool/`, `python-env/`,
settings and workspaces outside the application bundle.
`DAZEDTL_DESKTOP_PROFILE` selects a different profile;
`DAZEDTL_DESKTOP_WORKSPACE` selects a desktop workspace. Do not change workspaces
to evade the cumulative development API ledger.

The sandboxed renderer uses an allowlisted preload API and has no general file,
process or network access. Credentials and providers remain in Python. Engines,
rendering and workflow tasks run in dedicated workers. Large corpora, tool pages
and optional libraries load on demand. Image inputs are limited to 20 MB and
16 million pixels. Manual image rendering uses Pillow, NumPy and OpenCV; OCR and
inpainting resources are installed separately.

## Build and validate a standalone package

```sh
.venv/bin/python -m pip install -r desktop/requirements-build.txt
cd desktop
npm ci
npm run package
npm run test:updates
npm run test:packaged
npm run test:updates:packaged
```

Build on each target OS/architecture. The builder includes managed CPython
3.12.14, hash-locked dependencies, Electron, shared services, engine helpers and
shipped defaults. `npm run package -- --offline` uses previously cached build
dependencies. Output is in `desktop/out/packages/`; `out/package-result.json`
identifies the executable, archive and checksum. Packages are unsigned and are
not uploaded automatically.

Private `.env` files, API vaults, game workspaces, logs, outputs and optional model
downloads are excluded. The public tokenizer table is included for offline token
counting. Moving the package preserves the profile and installed extras. Runtime
installation is journaled and backs up local customizations when defaults change.

The native engine check runs real bundled tools against generated archives and
Ruby data, records executable hashes, and verifies original-file preservation:

```sh
.venv/bin/python desktop/scripts/check-native.py --packaged
# Optional Windows-binary compatibility check on Linux, in a disposable prefix:
.venv/bin/python desktop/scripts/check-native.py --packaged --wine
```

Linux checks WOLF archive round trips; Windows also checks Ace decryption and
JSON extraction/repacking. The optional Wine run exercises the Windows binaries
but does not replace a native Windows run. Commands have a 45-second cap within
a 180-second tool-execution deadline. Reports are written under
`.tmp-ui/desktop-evidence/`. CI runs these checks on Linux/Windows and retains
validation evidence. A macOS WolfDawn binary is currently absent; macOS WOLF
acceptance remains blocked until one is provided.

Run the relevant Python suites from the repository root:

```sh
./tests/run_tests.sh core
./tests/run_tests.sh integration
./tests/run_tests.sh extended
./tests/run_tests.sh imagetl
./tests/run_tests.sh full
```

`npm test` runs the five source Electron smoke flows; `test:packaged` runs the same
flows against the built app. They use generated fixtures and disposable profiles
with provider networking blocked. Linux needs a graphical session or Xvfb.
The separate update acceptance checks real restart/rollback and profile retention.

For debugger-free Linux relocation/startup measurements:

```sh
.venv/bin/python scripts/desktop_package_acceptance.py desktop/out/packages/DazedTL-linux-x64
```

The manual **Desktop package validation** CI workflow defines Linux, Windows and
macOS builds and native checks. Only Linux has been executed in this workspace.
Native Windows engine tools, macOS/Windows packages, signing and publication remain
release gates. A generated fixture can verify tool integration, but does not
replace an actual translated-game playtest.
