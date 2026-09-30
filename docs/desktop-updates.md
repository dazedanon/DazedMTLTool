# Desktop application updates

## One-click source installations

Use **Updates & rollback → Check for updates**, then **Download update** and
**Install and restart**. The app checks GitGud, git.dazedtl.dev and the fallback
mirror for the selected commit. It verifies the archive, shipped UI and engine
defaults, and prepares changed runtimes before offering restart. Drafts are saved
and active jobs must finish or stop first.

Updates preserve user data and maintain a per-file backup journal in the profile's
`source-updates` folder. Interrupted copies are rolled back at the next launch.
**Roll back and restart** restores the previous application without replacing
saved work. A file edited after updating blocks rollback before any file is
changed. Keep the source installation in a writable folder.

Existing Qt users reach this app through the old **Update** action and the same
launcher after restarting. See [one-click setup and migration](desktop-setup.md).

## Standalone packages

Open **Updates & rollback** in a packaged application. **Check for updates**
looks for a stable GitHub release containing
`dazedtl-desktop-<platform>-<architecture>.tar.gz` and a SHA-256 digest supplied
by GitHub. **Download and stage** checks that digest, safely extracts the
archive, and checks the complete application inventory. An extracted package
can also be selected with **Import extracted package**. Local package checks
establish integrity; the current development builds are unsigned.

**Activate and restart** saves open editor drafts and starts the selected build.
An active translation or tool action must finish or stop first. Packages are
stored separately under the desktop profile's `app-updates/packages` directory;
the original application is retained. Launching the original application again
opens the selected build. Keep the complete extracted package together,
including its manifest and, on macOS, the enclosing folder around `DazedTL.app`.

**Roll back and restart** selects the previous application. Settings, named
credentials, shared instruction overrides, saved runs, and optional Python
dependencies remain in the same profile. A run whose engine version changed
can require its previous application version to resume. The existing managed
backend installer preserves local files and keeps a recovery journal when
updating shipped defaults.

Linked legacy-batch jobs use a newer saved-job format. Older builds refuse
those jobs instead of ignoring the original queue link and collecting paid
requests again. Return to a compatible build to continue that recovery.

The first start of a newly selected build is provisional. After Python and the
renderer report ready, that start is acknowledged. If it does not finish,
launching the application again selects the previous build. Package and profile
format checks reject incompatible releases before selection.

## Building and verification

`node desktop/scripts/package.mjs` produces the complete application, package
manifest, compressed archive, and archive checksum in `desktop/out/`. The
builder preserves internal Python links and creates interpreter-matched,
hash-validated dependency caches so the application can run from a read-only
installation. It does not sign or publish a release.

From `desktop/`, run `npm run test:updates` for the small fixture checks and
`npm run test:updates:packaged` after building for actual update/restart/rollback
acceptance. The latter uses temporary applications and a temporary profile,
checks that shipped defaults change and restore, and verifies that profile
files and the original package remain intact. It fakes the release lookup and
does not contact providers. The existing five-test packaged UI suite retains
its original time limits.

Linux package activation and rollback have been exercised locally. Native Windows
and macOS behavior remains unverified. Runner-based CI was dropped; local update
checks remain available. Release signing and publication are separate steps.
