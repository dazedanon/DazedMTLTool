# Apply Patch
1. Click Code
2. Click Download ZIP
3. Extract to game folder and Replace All.

## Future Patching
1. Run **`GameUpdate.bat`** to auto patch (Windows).

### Folder layout

**In this translation-tool repo:** Patch payloads stay tidy inside **`gameupdate/gameupdate/`** (`patch.ps1`, `patch-config.txt`, etc.). **`GameUpdate.bat`** and **`GameUpdate_linux.sh`** sit one level up, under **`gameupdate/`**.

**On an installed game (what gets copied over):** Put **`GameUpdate.bat`** in the **game root**, next to the game exe. Put **`patch.ps1`** and friends inside **`gameupdate\`** under that same root (mirror names—still **`gameupdate\`**). **`GameUpdate.bat`** finds **`gameupdate\patch.ps1`** from its own folder, so **`GameRoot`** is correct even if the console cwd is somewhere else.

**Copy checklist:** From the tool repo's **`gameupdate/`**, copy **`GameUpdate.bat`** to `<game>\`; copy everything inside **`gameupdate/gameupdate/`** into `<game>\gameupdate\`.

2. Optional: set `GAMEUPDATE_PROMPT_PWSH=1` before running `GameUpdate.bat` if you want users to be prompted to install PowerShell 7 via winget.
3. Optional: set `GAMEUPDATE_DL_ATTEMPTS` (default `2`) to control retries for API checks/downloads. Lower values fail faster; higher values tolerate flaky networks.

### patch-config.txt

Create `gameupdate/patch-config.txt` next to `patch.ps1` (see `patch-config.example.txt`).

In DazedTL, set **Config → Game Update Defaults** (forge, host, org/username, branch) once. Step 1 **Copy gameupdate/** writes those into each game's `patch-config.txt`. You still set `repo=` per game.

For RPG Maker MV/MZ, **Install GameUpdate** also enables
`TranslationUpdateCheck.js`. When a saved patch commit exists, the plugin checks
the configured public repository in the background at game startup. It warns the
player if the branch has a newer commit and otherwise stays silent. Missing
configuration/state, offline play, API errors, and every other check failure are
ignored so the game always continues normally.
The warning includes a clickable link to the configured repository for players
who prefer to download and apply the patch manually. After copying the patch,
reopen the game and choose **I installed this update manually**. After an
explicit confirmation, the plugin records the already-verified remote commit in
the existing `previous_patch_sha.txt`; no second version marker is used.

DazedTL's public release builder stamps the clean translation repository's
current commit into `gameupdate/previous_patch_sha.txt` inside the ZIP. The
source game folder is not modified, and stale local updater state is never
copied. Commit the game and check out the branch named in `patch-config.txt`
before building a public release.

```txt
forge=gitlab
host=gitgud.io
username=YOUR_ORG_OR_USER
repo=YOUR_PATCH_REPO
branch=main
```

| Key | Meaning |
|-----|---------|
| `forge` | `gitlab` (default), `github`, or `forgejo` (`gitea` also accepted) |
| `host` | Hostname only. Defaults: `gitgud.io` / `github.com` / `codeberg.org` |
| `username` | Owner / org / group (`owner=` / `org=` aliases work) |
| `repo` | Repository name |
| `branch` | Branch to track |

Examples:

```txt
# GitLab / gitgud
forge=gitlab
host=gitgud.io
username=myorg
repo=cool-game-en
branch=main

# GitHub
forge=github
host=github.com
username=myorg
repo=cool-game-en
branch=main

# Forgejo / Codeberg
forge=forgejo
host=codeberg.org
username=myorg
repo=cool-game-en
branch=main
```

Older configs with only `username` / `repo` / `branch` still work (assumes GitLab on `gitgud.io`).

# Troubleshooting
**GAMEUPDATE.bat doesn't update and closes immediately**
1. Make sure your path doesn't contain any Japanese characters or lots of whitespace.
2. Make sure you actually have permissions in the folder
3. Auto-update calls the forge's public HTTP API (GitLab `/api/v4`, GitHub `/repos/...`, Forgejo `/api/v1`), not the web “Download ZIP” button - no account is required for public patch repos.

# Wolf Games
WOLF RPG installs from DLSite ship a master `Data.wolf` archive that takes priority over loose English patch files. `GameUpdate.bat` detects that and unpacks it automatically with the bundled `UberWolfCli.exe` (MIT, [Sinflower/UberWolf](https://github.com/Sinflower/UberWolf)), then renames `Data.wolf` to `Data.wolf.bak` so the patched loose `Data/` files load.

Just run **`GameUpdate.bat`**. No manual UberWolf download is required.

If unpack fails (rare Pro / protected builds), unpack once with [UberWolf](https://github.com/Sinflower/UberWolf/releases), ensure a loose `Data/` folder exists, rename or remove `Data.wolf`, delete `gameupdate/previous_patch_sha.txt`, and run `GameUpdate.bat` again.

# Contributing

Keep updater changes small and test both `patch.ps1` and `patch.sh`. Use the
repository-level development guidance and submit changes through the normal
merge-request workflow.
