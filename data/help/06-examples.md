# Full Example: Your First RPG Maker Game

This example shows the whole process in order. The goal is to translate one small part, test it,
and only then work on the rest of the game.

## 1. Make a safe copy

Copy the entire game folder. Keep one copy untouched and work on the other one.

Start DazedTL. Open **Configuration**, enter your AI key and model, then save.

Open the working game folder in Cursor or VS Code too. This lets its AI helper read the game when
DazedTL later gives you setup instructions to copy.

## 2. Choose a small test

Open **Workflow**, choose **RPG Maker**, and go to Step 0.

Choose the folder containing `Game.exe`. When the file list appears, select the main game
information and one early map, such as `Map001.json`. Bring those files into DazedTL.

Starting small matters because online AI translation may cost money, and a setup mistake is much
easier to correct before fifty maps have been translated.

## 3. Set up names and writing style

Go to Step 2 and click **Collect names** if it is available. Click **Copy setup skill**, paste the
copied instructions into your AI helper, and wait for its answer.

The answer will be divided into labeled parts. Copy each part into the matching box in DazedTL,
then save. This helps the translator keep character names and important words consistent.

## 4. Translate the test

Go to Step 3 and use **Normal** mode. Translate the main game information first, then the dialogue
for the map you selected.

Wait for each job to finish. If there is an error, open **Activity** and read the newest message.
Common problems are an incorrect AI key, no internet connection, or a temporary limit from the AI
company.

## 5. Put the English into the game

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

## 6. Translate the rest a little at a time

When the test looks good, return to Step 0 and select more maps. Translate, export, and play again.
Small groups are easier to check than the entire game at once.

You can use **Batch** mode for a large job if your AI service supports it. Keep using **Normal**
mode when you want a result quickly or are fixing only a few files.

## 7. Clean up what was missed

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

## Short WOLF RPG version

The same idea applies to WOLF RPG:

1. In Step 0, choose the game, unpack its text, and bring the listed files into DazedTL.
2. In Step 2, use your AI helper to prepare the names and writing rules.
3. Translate only names marked **safe**, then the main game information and a small amount of
   dialogue.
4. Use **Preview all injection** before **Apply all translations**.
5. Build the playable game and test it.
6. Fix problems before translating more.
