# RPG Maker Steps

Open **Workflow** and choose **RPG Maker**. Work from the top step to the bottom step. The **?**
button on each page explains the controls on that page.

Use **Back** and **Continue** at the bottom. The **Activity** button shows progress messages and
errors.

## What each step does

| Step | In plain language |
|---|---|
| **1 Project** | Choose the game and the text you want to work on |
| **2 Prepare** | Optional cleanup tools and version tracking; beginners can usually skip this for the first small test |
| **3 Setup** | Collect character names, run Project Setup, and review the guidance it writes |
| **4 Phase 1** | Translate normal game information and dialogue |
| **5 Phase 2** | Translate harder text hidden in events and add-ons; leave this until later |
| **6 Export** | Put reviewed translations back into the game |
| **7 Rewrap** | Fix exported lines that are too wide |
| **8 QA** | Run the final translation review and apply validated corrections |
| **9 Images** | Translate words that are part of pictures (MV/MZ only) |
| **10 Playtest** | Configure playtest tools, test the finished game, and build the release |

## A safe first test

1. In Step 1, choose the folder containing `Game.exe`.
2. Select the main game information and one early map, such as `Map001.json`.
3. In Step 3, click **Collect names** first. Then copy the setup instructions into your AI helper.
   The helper writes the guidance files directly. If its report marks an extra speaker option
   **ENABLE**, turn it on, collect names again, then click **Reload and review guidance**.
4. In Step 4, translate the main game information and dialogue.
5. In Step 6, use **Export selected files**.
6. Start the game and test that map.

Only select the rest of the maps after this test looks good.

![RPG Maker Project and Files step with the game folder and small file selection highlighted](images/workflow-project.png)

## Name options in Step 3

DazedTL shows options named **INLINE401**, **FIRSTLINE**, and **FACENAME**. These are extra places
where RPG Maker games may store a speaker's name. Click **Collect names** before worrying about
them. Then run the setup instructions with your AI helper. In its **speakers** report, turn on only
the options marked **ENABLE** and click **Collect names** again. The helper writes the guidance files
directly; click **Reload and review guidance** when it finishes. Many games need no extra options.

## Normal mode or Batch mode?

- Use **Normal** for your first test or a few files. You see the result sooner.
- Use **Batch** for a large amount of text when your selected AI service supports it. It may be
  cheaper, but it takes longer and is not available with every service.

## Step 5: harder text

Leave **Phase 2** alone until the normal dialogue works. This step can contain words the game uses
as instructions rather than words shown to the player. Translating the wrong one can break the
game.

When you are ready, click **Copy advanced-text audit** and paste those instructions into your AI
helper. Turn on only the items it confirms are player-visible text.

## Step 7: text that does not fit

English often takes more space than Japanese. **Rewrap** changes where a line breaks so it fits in
the message box.

1. Export the translation in Step 6 first.
2. In Step 7, choose the kind of text and the files you want to check. **Select all** checks the
   entire game.
3. Leave **Only rewrap text over its line-width limit** on to preserve text that already fits, then
   scan and preview every over-limit line.
4. Apply the reviewed fixes. Turn that option off only when you deliberately want to reflow all
   selected text.
5. Start the game and test again.

![Rewrap step with the over-limit safeguard, Preview rewrap, and Apply rewrap highlighted](images/workflow-rewrap.png)

The extra settings are for unusual games. Leave their default values alone on your first pass.

## Step 8: translation QA

After the exported text has been rewrapped, use **Full game - coverage & release gate** for the
final translation review. Click **Prepare / resume QA**, paste the copied handoff into your AI
helper, and let it finish the prepared review. DazedTL applies a clean validated result and pauses
when it needs a decision or a safeguard fails. The targeted QA modes are optional reruns after you
change one area; you do not need to run all of them after the full-game pass.

## Step 9: words inside pictures

Some menus and signs are pictures rather than normal text. Click **Open Image Manager**, make an
editable copy of the pictures you want, then click **Copy skill**. Give those instructions to your
AI helper and review every edited picture before clicking **Patch selected** or **Patch all**.

For difficult image work, DazedTL recommends Codex with **GPT-5.6 Sol** when it is available.
Smaller models may be fine for plain signs or buttons, but can struggle with small text, stylized
fonts, and crowded layouts.

DazedTL keeps backups, but you should still keep your own untouched copy of the game.

## Step 10: playtest and build

For MV/MZ games, configure any optional playtest tools, play through the translated game, and fix
anything you find. When the game is ready to share, use **Build public release ZIP**. RPG Maker Ace
builds its release from the QA step because the image and playtest-tool pages are MV/MZ-only.

## Note for RPG Maker Ace

Ace stores some menu text differently from MV and MZ. DazedTL handles the unpacking and packing
from Steps 1 and 6. If you need to edit menu or script text, follow the instructions shown in Step
6 and use your AI helper. Normal dialogue still uses the same translation steps above.
