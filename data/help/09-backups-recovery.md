# Backups & Recovery

The safest setup is two complete game folders:

- an **untouched copy** that you never edit; and
- a **working copy** that DazedTL may change.

Give them obvious names such as `Game - CLEAN BACKUP` and `Game - WORKING`. Always choose the
working copy in DazedTL and Cursor or VS Code.

## What can change the working game?

Importing and translating make files in DazedTL's work area. The game itself is changed when you
use actions such as **Export**, **Inject**, **Build**, or **Patch**.

Preview and Precheck are safer first steps because they show planned changes without applying
them.

## Keep the hidden DazedTL folder

DazedTL may make a hidden folder named `.dazedtl` inside the working game. Keep it. It contains
backups and information used to make later work safer.

DazedTL's automatic backups are helpful, but they do not replace your untouched copy of the whole
game.

## Simplest recovery

If the working game is badly broken:

1. Close the game and DazedTL.
2. Leave the broken working copy alone for now. It may contain useful translated files.
3. Make a new working copy from the untouched game folder.
4. Open the new working copy in DazedTL and your Agent.
5. Add back only a small group of translations, then playtest it.

Do not delete the `translated` folder in DazedTL's work area. It normally contains the translation
results you already paid or waited for, even if the playable game copy has a problem.

## Optional: Git

Git can keep named checkpoints of your working game. Open **Set Up Git (Optional)** in the first
Guide group for Agent-assisted setup and recovery instructions. Git is useful, but it does not
replace your untouched copy of the entire game.
