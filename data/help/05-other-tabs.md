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

### Do not confuse the two update buttons

- **Check for Updates** updates the DazedTL program itself.
- **Version Update** moves your translation to a newer release of a game.

They do not update each other.

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

For difficult image work, DazedTL recommends Codex with **GPT-5.6 Sol** when available. Smaller
models can handle simple images, but may struggle with small writing, unusual fonts, or fitting the
English neatly into the original design.

The original game pictures are not changed until you click a Patch button. DazedTL also keeps
backups, but you should keep your own untouched copy of the game.

## Batches

This shows large Claude translation jobs that may take a while to finish. Open a finished job here
to continue it on the Translation tab. If you only use Normal mode, you may never need this tab.

## Version Update

This page keeps official game releases and translations on two Git branches. Select your
translated game first. DazedTL immediately checks for the `original` and `translation` branches
and reads their recorded versions.

If the branches are missing, select the clean original game that matches the current translation
and enter its version. **Create original + translation branches** records both trees without
replacing translated content. Valid JSON is normalized on both branch baselines so initialization
does not create whole-file formatting changes. Files excluded by the repository's Git ignore
rules remain on disk but are not committed. When bootstrap begins, it installs the bundled
GameUpdate `.gitignore` before creating either commit. Existing project-specific rules are kept
after the bundled rules so they still take precedence.

For a later release, select the clean new official game, enter its version, and click **Preview
changes**. If the developer instead supplies a smaller patch with instructions to copy its folders
over the game and overwrite files, select the extracted patch folder and enable **This is a patch
folder**. Files omitted from a patch are preserved; use a complete official game folder when an
update needs to delete files. Select the translated game's root folder, not its `data` subfolder;
otherwise patch paths would be nested one level too deep.

The overview lists added, modified, deleted, and potentially overlapping files. Valid
JSON is shown as normalized before commit so Git can compare individual lines. A JSON file that
cannot be safely formatted is left unchanged and displayed as a warning. Files excluded by Git
are listed separately and are not included in the release commit. Review the overview, then click
**Approve and apply**. The official release is committed to `original` and
cherry-picked into `translation`. When both versions changed the same file, the official file
wins so game structure remains intact; the Activity list tells you which files need translation
review.

RPG Maker `plugins.js` is formatted with the same formatter used by Prepare before Git compares
versions. This prevents formatting alone from turning the plugin configuration into one giant
conflict and preserves translation-only plugin registrations when official settings change.

The preview also reports official changes that are already identical on the translation branch.
If every patch file is already present, the tool clearly records a metadata-only version marker;
it does not present that marker as a content-changing patch.
The official release delta and the resulting translation impact are displayed as separate counts.

Commit unfinished translation work before updating. If a cherry-pick is interrupted, this page
can either finish it with official files or abort it and restore the translation branch.

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
| `.dazedtl` inside a game | Portable translation guidance plus local backups and tool state; keep this folder |

Git should track `.dazedtl/glossary.txt`, `.dazedtl/settings.json`, and Markdown files under
`.dazedtl/skills/`. DazedTL keeps the rest of `.dazedtl` ignored because it contains local working
files, backups, and caches. You normally do not need to edit those local folders by hand.
