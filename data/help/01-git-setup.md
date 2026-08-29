# Set Up Git (Optional, Strongly Recommended)

Git saves named checkpoints of your files. If a translation change breaks something, you can
compare it with an earlier checkpoint or recover the older version.

Cursor and VS Code have a built-in **Source Control** screen for Git. Use that screen for normal
Git work. The Agent is most useful for checking the first setup, explaining a confusing change or
error, and helping with careful recovery.

This setup is optional, but doing it before your first translation can save hours later. Git does
**not** replace the untouched game copy from **Start Here**.

## Two kinds of protection

- **Local Git** keeps checkpoints on this computer. This is the most important part.
- A **Git host** such as GitHub, GitGud, GitLab, or Codeberg keeps a copy online. This is optional.

> **Upload warning:** Only upload files you own or have permission to store. A private repository
> is not permission to redistribute somebody else's game. **[GitGud's rules](https://gitgud.io/-/users/terms)**
> also say it is for code and development, not general media or backup storage. When in doubt,
> use local Git only.

## 1. Install Git

1. Open **[Git Downloads](https://git-scm.com/downloads)**.
2. Choose your computer type and install Git. The normal installer choices are fine for beginners.
3. Close and reopen Cursor or VS Code after installation.

## 2. Let the Agent do a one-time safety check

Make sure the working game folder is open in Cursor or VS Code. Paste this into your Agent:

> Check whether this game folder is ready for Git. Do not change anything yet. Check whether it
> already uses Git and review any existing `.gitignore` without replacing it. Look for passwords,
> API keys, save files, logs, caches, backups, and files larger than 90 MB. In `.dazedtl`, keep only
> `glossary.txt`, `settings.json`, and `skills/*.md` visible to Git; all other `.dazedtl` contents
> should stay ignored. Show any `.gitignore` changes you recommend. Do not delete files,
> commit, push, rename branches, change remote addresses, or use force commands. Wait for my
> approval.

A `.gitignore` is simply a list of files Git should leave alone. Read the Agent's recommendations.
Make sure it is not excluding the translated game text you want to protect. You can let the Agent
apply only the `.gitignore` changes you approve.

## 3. Start Git from Cursor or VS Code

1. Click the **Source Control** icon on the left. It looks like a line that splits into branches.
   You can also press **Ctrl+Shift+G** on Windows/Linux or **Control+Shift+G** on macOS.
2. If you see **Initialize Repository**, click it.
3. If you already see a list of changed files or a commit history, Git is already set up. Do not
   initialize it again.

If Source Control says Git is missing, restart the editor once. If it still cannot find Git, ask
your Agent to check the installation without changing the game.

## 4. Save the first checkpoint

The Source Control screen lists the files Git sees:

- **U** means a new file that Git has not saved before.
- **M** means a file was changed.
- **D** means a file was deleted.

To save the untouched starting point:

1. Click files in the list to review them. Make sure you do not see passwords, API keys, save
   files, logs, or backups.
2. Move your mouse over **Changes** and click the **+** button. This prepares the listed files for
   the checkpoint. Git calls this **staging**.
3. Type `Save untouched game before translation` in the message box near the top.
4. Click **Commit**.

If the editor asks for your name or email, follow its prompt. Ask your Agent to explain the message
if it is unclear; you do not need to hand the whole Git process over to the Agent.

The first local checkpoint is now ready.

## 5. Use Source Control during translation

This is the normal routine after a small group of translations works:

1. Press **Ctrl+Shift+G** on Windows/Linux or **Control+Shift+G** on macOS to open Source Control.
2. Click each changed file you care about. The editor shows the old version and new version so you
   can review what changed.
3. Click **+** beside the files you want, or beside **Changes** to prepare all visible changes.
4. Type a short message such as `Translate maps 1 to 5`.
5. Click **Commit** to save the checkpoint on this computer.
6. If you connected an online host, click **Sync Changes** to upload the checkpoint and receive any
   changes from the host.

Open **Source Control Graph** when you want to see earlier checkpoints.

> Be careful with **Discard Changes**. It removes work instead of saving it. Do not use it unless
> you understand exactly which file changes will be lost.

## 6. Optional: publish privately to GitHub

Skip online publishing if you do not have permission to upload the files. Local Git still works.

GitHub has the simplest built-in route:

1. Open **Source Control**.
2. Click **Publish to GitHub**. If it is not visible, open the **…** menu and look for **Publish**.
3. Sign in to GitHub when the editor opens the sign-in window.
4. Choose **Publish to GitHub private repository**. Do not choose public unless you have permission.
5. Review which files will be included, then confirm.
6. Open the new repository on GitHub and confirm it says **Private**.

Cursor and VS Code may word the Publish button slightly differently, but both use the same
VS Code-style Source Control screen.

## 7. Optional: connect GitGud, GitLab, or another host

1. Sign in to the host and choose **New repository**, **New project**, or **Create blank project**.
2. Choose **Private** and create an empty project. Do not add a README, license, or `.gitignore` on
   the website.
3. Copy the project's **HTTPS** address. It looks similar to
   `https://example.com/your-name/your-project.git`.
4. Return to Source Control and click **… → Remotes → Add Remote**.
5. Paste the HTTPS address, then name the remote `origin`.
6. Click **Publish Branch** or use **… → Push**.
7. Complete the host's sign-in window yourself. Never save a password or access token in the game
   folder or paste it into Agent chat.

If an `origin` remote already exists, stop instead of replacing it. Ask your Agent to explain where
it points and what the safe choices are.

## If a large-file error appears

**[GitHub blocks normal Git files larger than 100 MB](https://docs.github.com/en/repositories/creating-and-managing-repositories/repository-limits)**,
and other hosts have their own limits. Do not delete the file. Ask your Agent to identify it and
explain whether it should be ignored or stored with Git LFS. Git LFS is an extra large-file
feature and may have storage or bandwidth limits.

## When should I ask the Agent for Git help?

The Agent is useful when you need it to:

- review a proposed `.gitignore`;
- explain an unexpected file or error in simple language;
- check for secrets or oversized files before publishing; or
- explain recovery choices when the game stops working.

For everyday reviewing, committing, and syncing, use Source Control. Never approve a force-push,
reset, or file deletion until you understand exactly what would be lost.
