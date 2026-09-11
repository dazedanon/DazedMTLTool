# What the Other Tabs Do

Use **Workflow** for most jobs. The other tabs are useful when you need a specific tool.

## Len’s Method

Use this tab to translate a whole game with an AI coding assistant. Len’s playbook covers
engine detection, extraction, guidance, translation, fitting, injection, images,
playtesting and building a local translation patch.

1. Choose the game's root folder, task and image scope.
2. Choose **Agent / Sub Direct Translation** or **API Batch Translation** before copying a prompt.
3. For Direct, copy its starting prompt and paste it into your coding assistant with the game folder open.
4. For API Batch, open **API Settings** to choose the provider/model.
   If requests have not been prepared, choose preparation only and run that prompt first.
   Return here for **Estimate prepared requests**, review the quote and accept it to enable the API translation prompt.
5. Follow counted progress and remaining active-work estimates in the Len panel.
   Use **View detailed log** for evidence or **Refresh progress** for an immediate update.

One starting prompt includes setup. You do not need to copy guidance between tabs or run
a separate setup prompt. **Optional: project tools and references** contains the shared
editors, reference translations and **Git version tracking** for this game.

For RPG Maker, the assistant uses Workflow's preparation sequence: JSON formatting,
plugin-configuration formatting, GameUpdate installation, Git setup, then speakers
and game guidance. Existing per-game updater settings and project metadata are kept.
Ace uses its extracted JSON for formatting; other engines retain their own setup tools.

Git setup uses the selected untranslated game as the starting original and records a
translated branch, preserving existing repositories and native game bytes. DazedTL
preparation such as `TranslationUpdateCheck` does not require a separate original copy.
The assistant can create a backup from the selected folder before translating. A game
that has actually been translated and has no suitable baseline still needs an
untranslated source. Keep the backup even when using Git.
`main` contains only the runtime translation patch and minimal repository metadata.
`original` holds the corresponding untranslated files for backup and version updates.
The assistant synchronizes these paths before patch checkpoints, keeping translation-only additions off `original`.
All `.dazedtl` working records, guidance and QA evidence remain local; keep separate workspace backups.
Git setup and local checkpoints are included in the starting task. Online publishing is separate.

To reuse names and vocabulary from multiple prequels, list their folders or a prepared
corpus folder in **Instructions**, such as “Use the translations in /path/to/prequels
as terminology references for this game.” The same starting prompt tells your assistant
to inspect those references, put verified recurring terms in the shared glossary, and
register aligned translations. It preserves the original reference files and records
conflicting spellings for review.

Glossary, Game frame, Quirks, custom skills and reference translations are shared with
Workflow. Changes saved in either route apply to the next compiled translation context.
For MV/MZ map and database writes, the starting prompt requires Workflow-compatible
`_original` source metadata and preservation through reinjection and QA corrections.
The assistant adapts the injector to stage JSON before the source-preserving write.
Other native formats use separately backed-up source/injection sidecars where extra keys are
unsupported. This is handled within the same task.

The base glossary checkbox controls whether Len’s batches include DazedTL’s stock terms.
Setup includes the shared localization investigation and character identity safeguards.

For dialogue, the assistant carries the speaker alongside each line. This brings in
that character's glossary and voice notes even when the line does not mention their
name. Unidentified speakers stay unknown. The speaker labels are context for the
assistant; they are not added to dialogue unless the source actually contains them.

Direct translation uses your coding assistant's access and plan limits, with no DazedTL API key.
The word “Sub” does not instruct the assistant to delegate; your task instructions determine that.
API Batch shows the estimated cost, model, request count, tokens and rates before enabling the translation prompt.
Before extraction is complete, the estimate is unavailable rather than $0; the preparation prompt makes no translation API calls.
The quote excludes retries, billed reasoning, images, assistant work, QA and provider waiting, and is not a spending cap.
Changed settings, scope or request inputs require a fresh quote.
The assistant reuses supported engine/API adapters and checks their final requests before submission; Len does not automatically submit every engine through the Translation tab.
Some engine tools need additional dependencies documented in the skill.

The game’s `.dazedtl/len-method` folder holds its settings, handoff, context and progress
report. App updates refresh the maintained Len skill and tools; project-specific adaptations
stay in the game workspace. Resuming preserves previous work. After moving a game, select
its new folder and copy the starting prompt again to refresh paths.

The assistant updates counted text, review and image progress from saved records.
The panel also shows phase checkpoints, the last update, a blocker and the next action.
Before extraction, totals stay unmeasured; afterward, provisional percentages show progress through discovered units until full coverage is audited; excluded images stay out of scope. Changed tracked
inputs or scope show a warning until the agent rechecks and reports again. Progress
survives prompt refreshes.
The assistant updates it after milestones and at least every 10 minutes during active work, with measured throughput or explicit remaining phase estimates.
QA targets the affected screens and behavior; a full playthrough is optional unless requested.
English MV/MZ output uses `en_US`, with checks for English name entry and locale-sensitive plugins.
Completion requires reviewed strings, images within scope
and in-game validation; a complete string count alone is insufficient.

## Translation

This is the manual translation screen. Workflow opens it for you at the correct time.

Use it directly when you want to redo one file, continue an earlier job, or translate a game type
that does not have its own Workflow.

For a game without a guided Workflow, choose its project folder under **Translation context**.
Click **Copy setup skill** and run the copied instructions in your AI helper with that project
accessible. The helper discovers the project's own file structure and writes its Glossary, Game
frame, and Quirks directly under `.dazedtl`. Click **Review files** to reload and edit those files
in one tabbed window before translating. The selected project context is then applied automatically;
there is no separate glossary override.

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

This shows Claude, GPT, and Gemini Batch jobs that may take a while to finish. Open a finished job
here to continue it on the Translation tab. If you only use Normal mode, you may never need this
tab.

## Version Update

This page keeps official game releases and translations on two Git branches. Select your
translated game first. DazedTL immediately checks for the `original` and `translation` branches
and reads their recorded versions.

If the branches are missing, click **Set up version tracking**, select the clean original game that
matches the current translation, and enter its version. **Create version tracking** records both
trees without replacing translated content. Valid JSON is normalized on both branch baselines so
initialization does not create whole-file formatting changes. Files excluded by the repository's
Git ignore rules remain on disk but are not committed. When setup begins, it installs the bundled
GameUpdate `.gitignore` before creating either commit. Existing project-specific rules are kept
after the bundled rules so they still take precedence.

For a later release, select the clean new official game, enter its version, and click **Preview
update**. If the developer instead supplies a smaller patch with instructions to copy its folders
over the game and overwrite files, select the extracted patch folder and enable **This is a patch
folder**. Files omitted from a patch are preserved; use a complete official game folder when an
update needs to delete files. Select the translated game's root folder, not its `data` subfolder;
otherwise patch paths would be nested one level too deep.

The overview lists added, modified, deleted, and potentially overlapping files. Valid
JSON is shown as normalized before commit so Git can compare individual lines. A JSON file that
cannot be safely formatted is left unchanged and displayed as a warning. Files excluded by Git
are listed separately and are not included in the release commit. Review the overview, then click
**Apply update**. The official release is committed to `original` and
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

Keep the hidden `.dazedtl` folder inside the translated game. DazedTL uses its portable guidance
and local tool state during later work; do not delete it just because you do not recognize it.
Packed RPG Maker Ace and WOLF game updates are not supported here yet.

### Do not confuse the two update buttons

- **Check for Updates** updates the DazedTL program itself.
- **Version Update** moves your translation to a newer release of a game.

They do not update each other.

## Skills

These are detailed written instructions given to the translation AI and your AI helper. Most users
should leave the shared instructions alone. Game-specific names and writing rules belong in
Workflow Step 3.

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

For standard Workflow projects, Git should track `.dazedtl/glossary.txt`, `.dazedtl/settings.json`, and Markdown files under
`.dazedtl/skills/`. DazedTL keeps the rest of `.dazedtl` ignored because it contains local working
files, backups, and caches. You normally do not need to edit those local folders by hand.
Len runtime-patch projects keep all `.dazedtl` work local and separately backed up, as described above.
