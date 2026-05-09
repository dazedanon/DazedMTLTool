# Apply Patch
1. Click Code
2. Click Download ZIP
3. Extract to game folder and Replace All.

## Future Patching
1. Run GAMEUPDATE.bat to auto patch.
2. Keep the whole `gameupdate` folder together when you ship the game—`patch.bat` and `patch-download.ps1` must sit side by side.
3. Optional: set `GAMEUPDATE_PROMPT_PWSH=1` before running `GameUpdate.bat` if you want users to be prompted to install PowerShell 7 via winget.
4. Optional: set `GAMEUPDATE_DL_ATTEMPTS` (default `2`) to control retries for API checks/downloads. Lower values fail faster; higher values tolerate flaky networks.

# Troubleshooting
**GAMEUPDATE.bat doesn't update and closes immediately**
1. Make sure your path doesn't contain any Japanese characters or lots of whitespace.
2. Make sure you actually have permissions in the folder
3. Auto-update calls GitLab’s public HTTP API (`/api/v4/...`), not the web “Download ZIP” URL—no account or token is required for public patch repos.

For WOLF RPG games, if you downloaded the game off of DLSite, you will need to do some extra steps to patch it. This is because there is a "master" file called Data.wolf that will take priority over the english patch files. You will need this file to be a folder before patching will work.

# Wolf Games
1) Download the latest UberWolf.exe release from the following link:
https://github.com/Sinflower/UberWolf/releases
2) Drag Data.wolf onto UberWolf.exe. This will create a new folder called data.wolf~
3) Rename the new data.wolf~ folder to Data
4) Delete the Data.wolf file
5) Delete previous_patch_sha.txt (this will exist if you ran GameUpdate.bat previously)
6) Run GameUpdate.bat

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