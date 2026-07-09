# Apply Patch
1. Click Code
2. Click Download ZIP
3. Extract to game folder and Replace All.

## Future Patching
1. Run **`GameUpdate.bat`** to auto patch (Windows).

### Folder layout

**In this translation-tool repo:** Patch payloads stay tidy inside **`gameupdate/gameupdate/`** (`patch.ps1`, `patch-config.txt`, etc.). **`GameUpdate.bat`** and **`GameUpdate_linux.sh`** sit one level up, under **`gameupdate/`**.

**On an installed game (what gets copied over):** Put **`GameUpdate.bat`** in the **game root**, next to the game exe. Put **`patch.ps1`** and friends inside **`gameupdate\`** under that same root (mirror names—still **`gameupdate\`**). **`GameUpdate.bat`** finds **`gameupdate\patch.ps1`** from its own folder, so **`GameRoot`** is correct even if the console cwd is somewhere else.

**Copy checklist:** From **`DazedMTLTool/gameupdate/`**, copy **`GameUpdate.bat`** to `<game>\`; copy everything inside **`gameupdate/gameupdate/`** into `<game>\gameupdate\`.

2. Optional: set `GAMEUPDATE_PROMPT_PWSH=1` before running `GameUpdate.bat` if you want users to be prompted to install PowerShell 7 via winget.
3. Optional: set `GAMEUPDATE_DL_ATTEMPTS` (default `2`) to control retries for API checks/downloads. Lower values fail faster; higher values tolerate flaky networks.

### patch-config.txt

Create `gameupdate/patch-config.txt` next to `patch.ps1` (see `patch-config.example.txt`).

In DazedMTLTool, set **Config → Game Update Defaults** (forge, host, org/username, branch) once. Step 1 **Copy gameupdate/** writes those into each game's `patch-config.txt`. You still set `repo=` per game.

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

# Edit/Contribute
TLDR 3 steps.

    Fork the repository.
    Make the changes.
    Submit a merge request.

If everything looks good and doesn't break things I'll merge it in.

Longer Version:

# Required Software:
* [VSCode](https://code.visualstudio.com/) Make sure you check all the boxes for context menus.
* [Git](https://git-scm.com/downloads) (Use the default for everything. Just keep clicking Next)

# Guide to contributing

### 1. Fork the Repository
- Go to the repository you want to fork.
- Click the "Fork" button.

### 2. Clone Your Fork
- Clone your forked repository to your local machine.
    ```sh
    git clone https://gitgud.io/YOUR_USERNAME/REPO_NAME.git
    ```

### 3. Make Your Changes (In VSCode)
- Edit the files locally on your new branch using VSCode.
- Add and commit your changes.
    ```sh
    git add .
    git commit -m "Description of your changes"
    ```

### 4. Push Your Changes
- Push your changes to your fork on GitGud.io.
    ```sh
    git push origin your-feature-branch
    ```

### 5. Create a Merge Request
- Go to your fork on GitGud.io.
- Click on "Merge Requests" in the sidebar.
- Click the "New merge request" button.
- Select the branch you made changes to and the target project (the original repo).
- Provide a title and description for your merge request and submit it.

---

## Example

Assuming you want to fork a repository named `example-project`:

### 1. Fork the Repo
- Navigate to `https://gitgud.io/original_user/example-project` and click "Fork".

### 2. Clone Your Fork
    ```sh
    git clone https://gitgud.io/YOUR_USERNAME/example-project.git
    ```

### 3. Make Changes and Commit
    ```sh
    # Make changes to the files
    git add .
    git commit -m "Add new feature to example project"
    ```

### 4. Push Changes
    ```sh
    git push origin add-new-feature
    ```

### 5. Create a Merge Request
- Go to `https://gitgud.io/YOUR_USERNAME/example-project/merge_requests` and click on "New merge request"
- Choose the source branch `add-new-feature` and target branch (default: `main` or `master`)
- Fill in the details and submit the merge request