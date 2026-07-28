# Full Example: Your First Translation

This example uses an RPG Maker game. WOLF RPG uses the same basic cycle; the few different buttons
are listed near the end. The goal is to translate one small part, test it, and only then do more.

## 1. Finish the one-time setup

Before translating:

- keep one untouched copy of the whole game;
- complete **Set Up Your AI Helper**;
- enter your translation API key and model under **Configuration → General**; and
- complete **Set Up Git** if you want easy checkpoints and recovery.

Open the working game folder—the copy containing `Game.exe`—in Cursor or VS Code. Keep that same
folder open in your Agent while you work.

## 2. Choose the game

Click **Open Workflow** below the Guide and choose **RPG Maker MV / MZ / Ace**. In Step 0, choose
the working game folder.

Not sure which engine you have? RPG Maker games often contain a `www` or `data` folder. WOLF RPG
games often contain `Data.wolf`. DazedTL also tries to recognize the game after you choose it.

## 3. Import one small test

When the file list appears, select the main game information and one early map, such as
`Map001.json`. Click **Import selected files**.

Starting small matters because online AI translation may cost money, and a setup mistake is much
easier to correct before fifty maps have been translated.

Beginners can normally skip the optional **Prepare** step.

## 4. Set up names and writing style

Go to Step 2 and click **Collect names** if it is available. Click **Copy setup skill**, paste the
copied instructions into your AI helper, and wait for its answer.

The answer is divided into labeled parts. Copy each part into its matching place in DazedTL, then
save. The **Set Up Your AI Helper** page has a table showing where every label goes.

## 5. Translate the test

Go to Step 3 and use **Normal** mode. Translate the main game information first, then the dialogue
for the map you selected.

Wait for each job to finish. If there is an error, open **Activity** and read the newest message.
Common problems are an incorrect AI key, no internet connection, or a temporary limit from the AI
company.

## 6. Put the English into the game

Go to Step 5 and click **Export selected files**. This puts only the files from your small test back
into the game.

Start the game and play that map. Look for:

- names that change spelling;
- sentences that sound wrong;
- text cut off by the edge of a box;
- Japanese words that were missed;
- anything in the game that stopped working.

Fix your setup now if names or writing style are wrong. Use Step 6 Rewrap if good English text is
simply too wide for its box.

## 7. Save a good checkpoint

When the test works, press **Ctrl+Shift+G** in Cursor or VS Code to open **Source Control**. Review
the changed files, click **+** beside the changes you want to save, type
`Complete first playable translation test`, and click **Commit**. Click **Sync Changes** too if you
connected a private online repository.

Skip this step if you did not set up Git.

## 8. Translate the rest a little at a time

When the test looks good, return to Step 0 and select more maps. Translate, export, and play again.
Small groups are easier to check than the entire game at once.

You can use **Batch** mode for a large job if your AI service supports it. Keep using **Normal**
mode when you want a result quickly or are fixing only a few files.

## 9. Clean up what was missed

Only after normal dialogue works should you use Step 4 for harder text, Step 7 for words inside
pictures, or Step 8 for optional testing tools.

When you see leftover Japanese while playing:

1. Take a screenshot.
2. Use the Windows Snipping Tool to copy the Japanese words from the picture.
3. Search for those words with your AI helper.
4. Translate or edit the matching text.
5. Export it and test again.

## When is it finished?

The game is ready when you can play from beginning to end, the menus make sense, text fits on
screen, and no important Japanese remains. The normal cycle is **translate → play → fix → repeat**.

## If your game uses WOLF RPG

The same idea applies to WOLF RPG:

1. In Step 0, choose the game, unpack its text, and import the listed files into DazedTL.
2. In Step 2, use your AI helper to prepare the names and writing rules.
3. Translate only names marked **safe**, then the main game information and a small amount of
   dialogue.
4. Use **Preview all injection** before **Apply all translations**.
5. Build the playable game and test it.
6. Fix problems before translating more.

Open **WOLF RPG Steps** under **EXTRA INFORMATION** for the exact buttons and safety labels.
