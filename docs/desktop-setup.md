# One-click installation and Qt upgrade

Download and extract the full source archive into a writable folder. Windows
users double-click `START.bat`; macOS users open `START.command`; Linux users run
`bash START.sh` or open the desktop shortcut. Keep the whole extracted folder.
The first start downloads verified, pinned uv, Python and Electron runtimes and
installs hash-locked Python packages into a private cache. It shows progress and
opens the app when the Python service is ready. Later starts reuse this cache.
Python, Node, npm and Qt do not need to be installed separately.

Use Windows 10/11 x64, Windows 11 on ARM with x64 emulation, macOS 13+ on Apple
Silicon or macOS 14+ on Intel, or desktop Linux. The locked [OpenCV wheels](https://pypi.org/project/opencv-python-headless/5.0.0.93/#files)
require x64 on Windows and those macOS versions; Windows setup selects matching
x64 Python and Electron on ARM machines. Linux still needs its desktop libraries and curl or
wget. Git is optional for version tracking. Engine-specific native tools and
optional OCR/inpainting models retain their own platform requirements.

Setup can be retried by launching again after a download or startup failure.
It does not alter system Python, PATH or the registry. On Windows, `START.bat
-SetupOnly` prepares the app without opening it; `START.bat -Offline` uses the
completed cache and disables providers. POSIX equivalents are `bash START.sh
--setup-only` and `bash START.sh --offline`. The first install needs internet.

## Existing Qt installations

Once this version is published to an update mirror, use **Update** in Qt, wait
for completion, close the old app, and relaunch using the existing shortcut or
`START` file. No separate import step is needed for that installation.

The source archive deliberately leaves the four configurable engine modules
untouched during the old updater's copy step. First launch captures their
preferences, backs up the originals, then installs the new engine code. It also
imports `.env`, the named credential vault, customized shared instructions still
present in the installation, recent game paths, batch history and evaluations.
Malformed settings are reported for review. Existing desktop settings win over
legacy values; newly added fields can be recovered from the old configuration.

The migration never submits or resumes provider work. A conflicting credential
name is imported under a separate name, and old batches require explicit binding
to that original credential. Unfinished evaluation imports are paused and require
credential selection. Legacy queues keep their original files and shared lock;
keep the old application folder available while completing those jobs.

The **Recent** page shows the migration report and recovered locations. Backups
and the migration journal live under `workspace/migrations/qt-<installation-id>`.
Original `.env`, credentials, `files/`, `translated/`, `log/`, game folders and the
old `.venv` are retained. Known retired Qt code is backed up before removal.
Configuration changes made in the new app are saved in its profile.

## Locations and recovery

| Platform | Profile | Runtime cache |
| --- | --- | --- |
| Windows | `%APPDATA%\DazedTL` | `%LOCALAPPDATA%\DazedTL\setup` |
| macOS | `~/Library/Application Support/DazedTL` | `~/Library/Caches/DazedTL/setup` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/DazedTL` | `${XDG_CACHE_HOME:-~/.cache}/DazedTL/setup` |

`DAZEDTL_DESKTOP_PROFILE`, `DAZEDTL_DESKTOP_WORKSPACE` and `DAZEDTL_SETUP_HOME`
override these locations. An existing desktop preview workspace is bound on
upgrade so its saved work and cumulative development API ledger are retained.
Do not change that binding to reset the development spending cap.

For normal app updates, open **Updates & rollback**. Source installs use the
configured Git mirrors, verify the selected commit and staged files, prepare
runtime changes, then save drafts and restart to apply. Interrupted file copies
are recovered from a journal. Rollback restores the previous app while retaining
profile data; a newer local edit blocks replacement and keeps its backup.
Package updates use a complete runtime bundle. See [desktop updates](desktop-updates.md).

Native Linux fresh setup, source upgrade and package checks are recorded in the
parity report. Windows and macOS launchers are implemented but native execution
has not been verified. This change does not publish or sign a release.
