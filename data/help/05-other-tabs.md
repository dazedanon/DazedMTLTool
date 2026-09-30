# What the Other Tabs Do

Use **Workflow** for most jobs. The other tabs are useful when you need a specific tool.

## Len’s Method

Use this tab to translate a whole game with an AI coding assistant. Len’s playbook covers
engine detection, extraction, guidance, translation, fitting, injection, images,
playtesting and building a local translation patch.

1. Choose the game's root folder, **Agent Translation** or **API Batch Translation**, and any scope options.
   API mode uses the provider/model saved in **API Settings**.
2. Click **Copy translation prompt** and paste it into your coding assistant with the game folder open.
   The skill starts or resumes the work automatically and handles every phase through local patch delivery.
3. Follow counted progress and remaining active-work estimates in the Len panel.
   Use **View detailed log** for evidence or **Refresh progress** for an immediate update.

In API mode, the assistant prepares requests and presents their cost in the same conversation.
It obtains any missing spending approval before submission, then continues through collection and QA.
There is no task selector, return trip for estimates or second translation prompt.
The panel displays saved progress from the assistant; it does not keep an ended assistant session running.
If interrupted, use the same prompt to resume from saved work.

**Optional: project tools and references** contains the shared
editors, reference translations and **Git version tracking** for this game.

For RPG Maker, the assistant uses Workflow's preparation sequence: JSON formatting,
plugin-configuration formatting, GameUpdate installation, Git setup, then speakers
and game guidance. Existing per-game updater settings and project metadata are kept.
Ace uses its extracted JSON for formatting; other engines retain their own setup tools.
**Install Forge for in-game testing (MV/MZ)** is on by default and saved per game.
The assistant installs the bundled Forge during setup with Workflow's playtest settings.
Uncheck it to skip installation; an existing copy is kept. The option is disabled
for Ace and other engines. No extra confirmation is needed after choosing it.

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

## Translation Evaluation

Each model row has its own **Reasoning effort** and **Output token limit**.
The low-cost default selects a supported setting and shows the effective level in the dropdown.
Models that require reasoning do not offer Off; unknown models use provider defaults.
You can add the same model more than once with different efforts or output limits to compare the results.

The output limit applies to each request and includes both reasoning and translation tokens.
Raising it increases the theoretical cost ceiling shown before submission.
The text estimate excludes unpredictable reasoning costs; the ceiling includes the full selected output limit and automatic attempts.

Prepare the benchmark again after changing a model's settings.
Saved evaluations and exported evaluation archives retain the selected settings, and results identify each model's effort and output limit.

Sampling aims for at least eight independent dialogue scenes when the selected content permits it.
The line count per sample is a maximum; small budgets may produce shorter contiguous blocks to
cover more scenes. Preparation shows the largest scene's share and reports limited dialogue coverage.

**Export blind review** includes each sample's preceding Japanese dialogue and the exact matched
prompt, glossary and SFX context. Exact duplicate output blocks are grouped; fully identical
samples start with tied rankings. A tie means equal preference, not necessarily correct translation.
Use **Copy review skill** for the review instructions. Complete all four rankings on judged rows,
or select `insufficient_context` / `needs_human_review` and leave all rankings blank. Record concrete
errors and severity in `error_evidence`; do not score individual lines separately.

Set the reviewer name/session and AI/Human type before **Import reviewed CSV**. The **Review statistics**
tab shows judged and abstained coverage, category scores, pairwise wins/ties/losses, recorded errors,
and scores that weight scenes equally. Its 95% intervals resample whole scenes and do not measure
judge bias. With fewer than two judged scenes an interval is unavailable. Quality scores cover only
complete valid outputs; consider the existing **Valid** and cost columns too. Randomized A/B/C labels
change identity across rows and should never be totaled as if they were fixed models.

After importing a baseline, **Export judge check** selects a quarter of its non-identical judged
samples plus all samples flagged for human follow-up. It changes every candidate's position and
omits previous verdicts. Review it in a fresh AI session or with a qualified Japanese reviewer,
then import it to see agreement and disagreements without replacing baseline quality scores.
The comparison's **Needs human follow-up** filter finds uncertain samples, major/critical errors,
and judge disagreements. Reimporting a corrected baseline invalidates checks exported against the
old decisions; export a fresh check. Saved evaluation archives retain review history and mappings.

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
# Paired translation evaluation (v3)

Choose **Paired review v3** for new reviews. **Legacy rankings v2** preserves the old
rank-based workflow and scores. Legacy full and partial ties now have distinct labels.

1. Finish generation, choose **Screening**, and export. The preview shows assessment
   and pair counts before saving. Invalid outputs stay in reliability coverage.
2. Use **Copy review skill** in a fresh judge session, then import its reviewed CSV
   with a reviewer/session name. Assess editing requirements and compare two scenes at
   a time. Slight preferences between accurate translations do not require an error.
3. Open **Model decision** for editing needs, major fidelity errors, mandatory-rule
   compliance, validity, paired preferences, observed cost and available live latency.
   Double-click a model or paired result to inspect its underlying source evidence.
4. Export **Confirmation** for the statistically plausible contenders on reserved,
   unexposed content groups. Candidates and the confirmation set are then frozen.
   Previously exported scenes cannot become fresh holdouts. A run without fresh groups
   can support screening, but needs new source material for confirmation.
5. Review **Challenge cases** separately. The default source-only selection uses
   code-bearing scenes; **Review policy** also accepts explicit challenge sample IDs.
6. Use **Reversed-order audit** and **Independent judge** for fresh checks. Disagreements
   stay disputed and do not add independent votes. Use a different reviewer/session for
   independent checks. **Load human calibration** accepts a human-authored JSON suite;
   choose **Calibration** to export it without the expected answers.
7. Export **Human adjudication** for flagged scenes when qualified review is needed.
   Import it with reviewer kind **Human**. Adjudication preserves the earlier verdicts,
   applies the human decision, and retires only stale audit records. A fresh audit can
   then check the revised baseline. Identical outputs share the adjudicated assessment.

**Review policy** sets group budgets, practical and fidelity margins, mandatory rules,
and review conventions. Changing policy starts a new campaign while retaining earlier
results. These are pilot settings, not validated claims about Japanese game translation.
Mandatory rules remain production requirements even when their linguistic impact is small.

The primary results show wins/equivalents/losses and net paired preference, not Borda
points. Equivalents stay in the denominator; abstentions do not become half-wins.
Multiple chunks from an event/page and repeated judge votes do not increase scene weight.
Uncertainty uses conservative, simultaneous bounds over independent content groups, so
small samples and all-equivalent samples cannot produce false certainty. Sampling bounds
do not include judge bias. A provisional leader is not a supported winner, and failure to
find a difference is not evidence of practical equivalence.

For ordinary win/equivalent/loss content-group outcomes, v3 uses exact binomial marginal
bounds and combines them conservatively. Fractional group averages or explicit stratum
weights use bounded-mean intervals. The error budget covers the planned pairs and both
preference and fidelity claims. Legacy scene-bootstrap scores remain legacy results.

Human calibration JSON format (the following is a structural example, not human gold):

```json
{
  "version": 1,
  "author": "Qualified reviewer's name",
  "author_kind": "human",
  "cases": [{
    "id": "calibration-01",
    "source": ["Japanese source"],
    "context": {"history": [], "system": "Applicable translation instructions", "glossary": "", "sfx_reference": ""},
    "left": ["One translation"],
    "right": ["Another translation"],
    "decision": "equivalent"
  }]
}
```

Supply actual qualified human judgments covering errors, valid alternatives, voice,
ambiguity and formatting. Calibration outcomes are excluded from model scores. AI review
remains a second opinion and requires human confirmation for consequential choices.

Calibration also needs assessment cases to check error-impact judgments. An assessment
case uses `"type":"assessment"`, `source`, `context`, and `output` arrays, plus:
`"expected":{"editing":"ready","major_linguistic":false,"critical":false,"violated_rules":[]}`.
Replace these expected values with the human judgment. Supported conclusions require
both comparison and assessment calibration for each participating judge identifier.
Use the same reviewer identifier when importing that judge's calibration; an independent
   judge uses a different identifier. Fresh sessions still must not see earlier verdicts.
