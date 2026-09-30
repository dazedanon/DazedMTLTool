# DazedTL Electron desktop

Electron is the application UI. The old Qt launcher forwards to one-click setup;
Qt widgets and dependencies have been retired. See the [parity contract](../docs/desktop-parity.md)
and [installation guide](../docs/desktop-setup.md).

## Launch

End users run `START.bat` on Windows, `START.command` on macOS, or
`bash START.sh` on Linux. Setup installs pinned private runtimes and locked Python
dependencies. The renderer ships prebuilt; Node and npm are unnecessary.

Normal configured-provider operations are enabled. `--offline` uses cached
runtimes and disables providers. `--live` separately enables the cumulative $5
Luna development broker; normal provider operations do not use that test cap.
Offline test text is synthetic and labeled accordingly.

For renderer development, use Node 22.12+ and a Python development environment:

```sh
cd desktop
npm ci
npm run build
DAZEDTL_DESKTOP_PROVIDERS=0 npm start
```

`DAZEDTL_PYTHON` selects a development interpreter. Rebuild before distributing
source archives: `npm run build` writes verified `dist/` and `engine-defaults/`
assets that must be committed with their source changes.

## Choose a workspace

**Overview** offers direct starting routes for guided translation, Len’s Method
and manual engines. The sidebar separates these from the isolated snapshot
review tools and shared utilities. **Settings** and **Guide** remain available
at the bottom of the sidebar, including in compact windows.

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
  excludes credentials. **Import & export** contains transfer actions. Search
  within a settings section without changing hidden values; the save bar stays
  available while scrolling. **Guide** displays the shipped help.
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

One-click and packaged launches use Electron’s per-user DazedTL profile.
An existing preview workspace is bound to that profile on first upgrade, retaining
its saved work and cumulative development spending ledger. Packaged builds also
keep writable `tool/` and `python-env/` folders outside the application bundle.
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
`.tmp-ui/desktop-evidence/`. These are optional local checks. A macOS WolfDawn
binary is currently absent, so macOS WOLF execution is not supported by this bundle.

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

Runner-based CI was removed from this work. Local regression checks and package
tools remain available; native Windows/macOS execution has not been verified.
The bundled Linux WOLF executable needs x86-64 and glibc 2.39 or newer (for
example, Ubuntu 24.04). Generated fixtures verify integration; actual translated
games still need playtesting. Signing and publication are separate release steps.
