# What the Other Tabs Do

Use **Workflow** for most jobs. The other tabs are useful when you need a specific tool.

## Version Update

Use this when you already translated an older release of a game and the developer publishes a new
release. DazedTL tries to carry your work into the newer game.

For the first update, you need three game folders:

1. the untouched old release;
2. your translated copy of that old release;
3. the untouched new release.

Click **Scan Update** first. Scanning only compares the folders; it does not change them. The safest
choice afterward is **Create a separate updated folder**. This leaves all three starting folders
untouched.

Some changes cannot be chosen safely by the tool. Review anything marked **Needs review** or
**Translation at risk**, then start the finished game and test the changed maps and menus.

> Keep the hidden `.dazedtl` folder inside your translated game. DazedTL uses it to make future
> updates safer. Do not delete it just because you do not recognize it.

Packed RPG Maker Ace and WOLF game updates are not supported here yet.

## Translation

This is the manual translation screen. Workflow opens it for you at the correct time.

Use it directly when you want to redo one file, continue an earlier job, or translate a game type
that does not have its own Workflow.

## Images

Use this for Japanese words that are part of a picture, such as a title, button, or sign.

1. Choose the game folder.
2. Use **Decrypt** for protected RPG Maker pictures or **Make editable** for ordinary PNG pictures.
3. Click **Copy skill** and paste the instructions into your AI helper.
4. Review the edited pictures.
5. Use **Patch selected** to put only the pictures you chose back into the game.

The original game pictures are not changed until you click a Patch button. DazedTL also keeps
backups, but you should keep your own untouched copy of the game.

## Batches

This shows large Claude translation jobs that may take a while to finish. Open a finished job here
to continue it on the Translation tab. If you only use Normal mode, you may never need this tab.

## Skills

These are detailed written instructions given to the translation AI and your AI helper. Most users
should leave the shared instructions alone. Game-specific names and writing rules belong in
Workflow Step 2.

## Configuration

This is where you save your AI service, private API key, model, text width, and game-specific
options.

Change one setting at a time, then test on a small part of the game. If dialogue runs off the side
of its box, lower the text width or use Rewrap in the RPG Maker Workflow.

## Folders you may see

| Folder | What it contains |
|---|---|
| `files` | Working copies of the text you selected |
| `translated` | Text after translation |
| `log` | Progress details and error information |
| `.dazedtl` inside a game | Backups and information DazedTL needs later; keep this folder |

You normally do not need to edit these folders by hand.
