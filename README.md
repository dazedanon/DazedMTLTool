# DazedTL

An AI-powered game translation tool with a GUI. Translate RPG Maker, Ren'Py, Tyrano, Wolf RPG, Kirikiri, and other game engines from Japanese to English using GPT, Gemini, [Mistral](https://docs.mistral.ai/api), or other compatible AI models.

## Credits

- **[Sinflower](https://github.com/Sinflower)** — [RV2JSON](https://github.com/Sinflower/RV2JSON) — enables RPGMaker Ace games to be translated the same way as MV/MZ by converting rvdata2 files to JSON and back. A curated copy is bundled offline in `util/ace/offline/` and updates with DazedTL.
- **Sakura & Kao_SSS** — TL Inspector (`util/tl_inspector/`) — in-game translation source inspector and live-edit plugin for RPG Maker MV/MZ playtesting.
- **Len** — [Forge](https://gitgud.io/zero64801/forge-mvmz) MV/MZ playtest plugin (`util/forge/`), Mistral API support (provider integration and adaptive rate limiting), and batch translation mode.

## Table of Contents

- [Supported Engines](#supported-engines)
- [Requirements](#requirements)
- [Installing Python](#installing-python)
- [Quick Start](#quick-start)
- [Using the GUI](#using-the-gui)
- [Glossary & Prompt](#glossary--prompt)
- [Tips](#tips)
- [Mistral API (free tier)](#mistral-api-free-tier)
- [Batch Translation (Claude, GPT, and Gemini)](#batch-translation-claude-gpt-and-gemini)
- [Translation Model Evaluation](#translation-model-evaluation)
- [Folder Structure](#folder-structure)
- [Finding Untranslated Text (Snipping Tool OCR)](#finding-untranslated-text-snipping-tool-ocr)
- [RPG Maker Translation Workflow](#rpg-maker-translation-workflow)
- [Wolf RPG (WolfDawn) Translation Workflow](#wolf-rpg-wolfdawn-translation-workflow)
- [Using Copilot & VSCode](#using-copilot--vscode)
- [Version Control with Git](#version-control-with-git)
- [Troubleshooting](#troubleshooting)

## Supported Engines

- RPG Maker (MV, MZ, Ace, and more)
- Wolf RPG Editor
- Ren'Py
- TyranoBuilder / TyranoScript
- Kirikiri
- NScripter
- CSV / Text files

---

## Requirements

- **Python 3.12 – 3.14** — See [Installing Python](#installing-python) below if you don't have it yet.
- **An AI API Key** — You'll need an API key from [OpenAI](https://platform.openai.com/settings/organization/api-keys), [Google Gemini](https://aistudio.google.com/apikey), [Mistral](https://docs.mistral.ai/api) (free tier available — no credit card), or a compatible provider.

---

## Installing Python

If you already have Python 3.12–3.14 installed and working, skip to [Quick Start](#quick-start).

### Step 1 — Download

Go to [python.org/downloads](https://www.python.org/downloads/) and download **Python 3.13** (or any version from 3.12 to 3.14).

### Step 2 — Install (Important!)

When the installer opens, **check both boxes at the bottom before clicking Install**:

- ✅ **"Add python.exe to PATH"** — This is the most important step. Without it, your system won't be able to find Python.
- ✅ **"Use admin privileges when installing pip"**

Then click **Install Now**. The default settings are fine for everything else.

### Step 3 — Verify

Open a **new** terminal window (don't reuse an old one — it won't see the new PATH) and run:

```
python -V
```

You should see something like `Python 3.13.x`. Then check pip:

```
pip -V
```

You should see something like `pip 24.x.x from ...`.

### If `python` or `pip` is not recognized

This means Python wasn't added to your PATH. You have two options:

**Option A — Reinstall (easiest)**
1. Open the Python installer again (or redownload it).
2. Select **Modify**.
3. Click **Next** on the first screen.
4. On the Advanced Options screen, check **"Add Python to environment variables"**.
5. Click **Install**. Then open a **new** terminal and try again.

**Option B — Add to PATH manually**
1. Press `Win+R`, type `sysdm.cpl`, press Enter.
2. Go to the **Advanced** tab → **Environment Variables**.
3. Under **System variables**, find `Path` and click **Edit**.
4. Click **New** and add the path where Python was installed. Typically:
   - `C:\Users\YourName\AppData\Local\Programs\Python\Python313\`
   - `C:\Users\YourName\AppData\Local\Programs\Python\Python313\Scripts\`
5. Click **OK** on all dialogs, then open a **new** terminal and try `python -V` again.

> **Tip:** If `python` works but `pip` doesn't, try `python -m pip -V` instead. If that works, you can use `python -m pip install` anywhere you'd normally use `pip install`.

---

## Quick Start

### 1. Download the Tool

1. Click the green **Code** button at the top of this page and select **Download ZIP**.
2. Extract the ZIP to a folder of your choice (e.g., `C:\DazedTL`).

### 2. Set Up Your API Key

1. Inside the tool folder, find `.env.example` and make a copy of it named `.env`.
2. Open `.env` in any text editor (Notepad works fine) and fill in your API details:
   - `api` — Your API base URL (for Nvidia use `https://integrate.api.nvidia.com/v1/`, for Mistral use `https://api.mistral.ai/v1/`).
   - `key` — Your API key.
   - `organization` — Your organization key (make something up if using a self-hosted or non-OpenAI API).
   - `API_PROVIDER` — Use `openai` for OpenAI-compatible providers (including Nvidia), `gemini` for Gemini, or `mistral` for Mistral (only needed when `api` is left empty).
   - `model` — For Nvidia/custom OpenAI-compatible endpoints, enter the model name manually (example: `deepseek-ai/deepseek-v4-pro`).
3. The rest of the settings (wordwrap, batch size, etc.) can be left as defaults for now. You can tweak them later.

> **Trying Mistral?** Set `API_PROVIDER=mistral`, add your key, use `mistral-medium-3.5`. Free tier details in [Mistral API (free tier)](#mistral-api-free-tier).

### 3. Launch the GUI

**Windows:** Double-click `START.bat`. It will create a virtual environment, install dependencies, and open the GUI.

**Linux/macOS:** Run `./START.sh`, or double-click `DazedTL.desktop` (choose **Allow Launching** when your file manager asks). From then on, either method works.

That's it! Use the same launcher each time you want to open the tool.

---

## Using the GUI

The GUI has several tabs that handle different parts of the translation process:

### Config Tab
This is where you configure your API settings, wordwrap widths, and other options. Most of these mirror what's in the `.env` file, but you can adjust them visually.

### Translation Tab
The main tab for translating files.

1. **Add files** — Place the game files you want to translate into the `files` folder (inside the tool directory).
2. **Select a module** — Pick the engine that matches your game (e.g., RPG Maker MV/MZ, Wolf RPG, Ren'Py, etc.).
3. **Click Translate** — The tool will process each file and output translated versions to the `translated` folder.
4. **Copy the results** — Move the translated files from `translated` back into your game's data folder.

### Version Update Tab

Use this tab when an official game update needs to be applied to an existing
translation. Select the current translated game, the new official version, and
the old official version. If no saved baseline exists and Old official is left
blank, the updater can read a local Git `original` or `origin/original` branch
without checking it out. Scan the sources, then use **Create Recommended Update**
to produce a separate updated copy without resolving anything first. Safe local edits
are merged automatically; uncertain files use the new official version by default and
are listed as translation risks that can be reconciled afterward or overridden in bulk.
When the same official build was already applied, the tab automatically runs a read-only recovery
audit using retained source history or a fingerprint-verified `original` branch. Restoring changes
later reverted in Git still requires an explicit **Reapply Recovered Changes** action. Recovery
labels definite versus possible reverts, verifies staged files and RPG Maker JSON before publish,
and retains a bounded eight-run history with the baselines those reports require.
Alternatively, choose **Update the current translated folder**. The updater builds a
complete sibling staging copy before replacing the working folder and retains the prior
translation beside it as a rollback backup.

The updater compares the entire game folder, including plugins, images, audio,
fonts, executables, and other assets. RPG Maker MV/MZ data receives a semantic
three-way merge, including a plugin-name-aware merge for `js/plugins.js`; other
unpacked games use a conservative engine-agnostic file
merge. Packed RPG Maker VX Ace and WOLF projects are detected and held for a
future normalization adapter rather than updated unsafely.
JSON formatting differences are normalized in memory and do not require
rewriting any input game folder.

Repository metadata is excluded from update decisions. Audio and unmodified
runtime images follow the new official version. Images patched through the
Images tab use their stored pre-translation backups, allowing the updater to
preserve a translated image unless its official source changed or was removed.

### Engine Config Tab
Engine-specific settings. RPG Maker has the most mature support — you can toggle exactly which event codes to translate (dialogue, choices, variables, plugin commands, etc.). The defaults cover ~95% of a game's text out of the box. See the [RPG Maker Translation Workflow](#rpg-maker-translation-workflow) section for a detailed step-by-step guide.

Other engines (Wolf RPG, Ren'Py, Tyrano, etc.) have less granular support and may require more manual tweaking or post-editing depending on the game.

### RPG Maker / Wolf / CSV Tabs
Specialized tabs with extra options for those specific engines.

---

## Glossary & Prompt

### Glossary file: &lt;game&gt;/glossary.txt
The Glossary gives the AI context about your game—character names, genders, recurring terms, and similar details. The better your Glossary, the more consistent the translation.

When you select a game, `<game>/glossary.txt` is created automatically from `data/glossary_base.txt` if it does not exist yet. Each game therefore keeps its own glossary. Add entries like:

```plaintext
# Game Characters
水無月 士乃 (Minazuki Shino) - Female
暗黒斎 (Dark Kokusai) - Male
フトシ (Futoshi) - Male
```

Format: Japanese name, English name in parentheses, then gender.

> **Note:** A very large Glossary can increase API costs and potentially reduce quality. Focus on the most important characters and terms.

### Local Japanese SFX reference

DazedTL ships a local, definitions-only snapshot of the MIT-licensed
[J-Ono Data](https://github.com/ObakeConstructs/j-ono-data) collection under
`data/sfx_reference/`. For each translation batch, the tool matches Japanese
sound effects in the source and sends only the relevant possible meanings. The
reference is explicitly non-authoritative: the model chooses the sense and
natural target-language wording from the scene instead of performing fixed
search-and-replace.

The local asset includes kana variants, meanings, and English semantic
equivalents. Romaji remains in the asset for provenance and possible future
search features, but is not sent to translation models. Manga examples and
images are not included. Translation never contacts an online dictionary.

The feature is enabled by default and can be turned off with **Configuration →
General Settings → SFX Reference**. Only matched entries consume prompt tokens;
one-kana entries are suppressed and short entries use conservative boundaries
to avoid ordinary-dialogue collisions.

### data/skills/system.md
This is the system prompt skill sent to the AI on every translation call. A default `data/skills/system.md` is included and works well for most games. You generally don't need to edit it unless you want to customize the translation style.

Per-game overlays (when a game folder is selected in Workflow) live next to the game:
- `<game>/skills/game.md` - Translation Frame (theme / era / register / naming)
- `<game>/skills/quirks.md` - cross-cutting voice habits
- optional extra `<game>/skills/*.md` custom overlays

---

## Tips

- **Check `log/translations.txt`** after a run to see what was translated. You can copy useful terms from it into the selected game's `glossary.txt` for consistency in future runs.
- **Start small** — Translate a few files first to make sure the output looks good before doing the whole game.
- **Wordwrap** — If text overflows or looks awkward in-game, adjust the `width` setting in `.env` or the Config tab. `60` is a good default for most RPG Maker games.
- **Version control** — Using [Git](https://git-scm.com/) with the game folder is highly recommended. It lets you track every change the translation makes, compare with original files, and roll back if needed.

---

## Mistral API (free tier)

Mistral's [API is free for now](https://docs.mistral.ai/api) (no credit card), and the tool has proper support for it — not just a generic OpenAI-compatible URL. Mistral rate-limits pretty aggressively per model, so there's an adaptive limiter that reads the live headers and paces requests automatically. That lets you crank up `fileThreads` without the run dying to 429s.

`mistral-medium-3.5` is the recommended model for translation. Avoid `mistral-medium-latest` — it still points at the older 3.1 release.

Quick setup in `.env`:

```
API_PROVIDER=mistral
api="https://api.mistral.ai/v1/"
key="your-mistral-api-key"
model="mistral-medium-3.5"
```

When the API URL points at `api.mistral.ai`, requests are paced automatically. Mistral enforces a **per-minute request limit** and a **per-minute token limit**, both **per-model** — e.g. `mistral-medium` allows 25 req/min while `ministral-3b` allows 750/min. The limiter reads both limits from the live `x-ratelimit-*` response headers, spaces requests so it never overruns the per-minute budget, and honours `Retry-After` on 429s. Override the seeds with `mistralReqPerSec`, `mistralTokPerMin`, and `mistralTokenHeadroom` in `.env` if needed (rarely).

> **Note:** Batch mode supports native Anthropic Claude, OpenAI GPT, and Google Gemini routes. Mistral and unrecognized OpenAI-compatible endpoints run live translation.

---

## Batch Translation (Claude, GPT, and Gemini)

Batch mode — see [Credits](#credits).

When using a supported native Claude, GPT, or Gemini route, the CLI offers a third mode
that translates through the provider's asynchronous Batch API—typically at **50% of the live price**.
Batches usually finish within an hour (24h worst case), so use it for large jobs where you don't
need results immediately.

Provider references: [Anthropic Message Batches](https://platform.claude.com/docs/en/build-with-claude/batch-processing),
[OpenAI Batch API](https://developers.openai.com/api/docs/guides/batch), and
[Gemini Batch API (OpenAI compatibility)](https://ai.google.dev/gemini-api/docs/openai#batch).

```
python start.py
 -> 3. Batch Translate (Provider Batch API, typically 50% off)
```

How it works (all engine modules are supported automatically):

1. **Pass 1 (collect)** — files are processed normally, but instead of calling the API each
   request is queued to `log/batch_requests.json`. Requests are byte-identical to live ones:
   the static `data/skills/system.md` block is cached with a 1h TTL, matched Glossary entries,
   matched local SFX suggestions, and translation history ride along per request, while
   structured output enforces the exact line count.
   Speaker/variable names still translate live during this pass (they get embedded into the
   dialogue payloads, so both passes must resolve them identically) — they're a tiny share
   of the volume.
2. **Cost estimate** — before anything is submitted you get a cost breakdown
   (batch + cache / batch worst-case / live price) and a y/n confirmation.
3. **Submit / poll / fetch** — the batch is submitted, polled until it ends
   (`batchPollInterval` env var controls the interval, default 60s), and the results are
   saved to `log/batch_results.json`. Ctrl-C while polling is safe — the batch keeps
   processing server-side.
4. **Pass 2 (consume)** — files are processed again; every payload is filled from the batch
   results through the normal validation pipeline (line counts, placeholders, content
   checks). A missing, stale-context, or invalid result stops safely and preserves the
   original text; it never turns into an unconfirmed full-price live request. Start normal
   Translate explicitly if you want to retry those files at live pricing.

Context note: in live mode the rolling translation history contains the previous batch's
English lines; in batch mode requests are independent, so the history carries the previous
batch's *source* lines instead. The model still sees the surrounding scene, the Glossary
(`glossary.txt`) keeps names and terms consistent, and matched SFX suggestions provide
context-dependent meanings without forcing fixed wording.

Cost tracking is exact: per-file and total costs printed after the consume pass use the real
billed token counts (cache reads at 0.1x, cache writes at 2x, output at the output rate) with
the 50% batch discount applied.

`python selftest_batch.py` round-trips the whole flow offline (no API key needed) if you want
to verify the pipeline after making changes.

---

## Translation Model Evaluation

The **Evaluation** page compares any two or more models through native Batch APIs
or immediate live requests without translating an entire game.
Benchmark setup reopens with the most recently saved run's models, keys, modes,
source, size, and budget. Before the first run exists, it starts with one model
using the currently configured model and active saved API key; add at least one
more model before preparing the comparison.
Every row can use its own API URL, saved key, and model dropdown. Official
OpenAI, Claude, Gemini, DeepSeek, Mistral, and Nvidia URLs are available from
the adjacent **Presets** menu; other URLs use an OpenAI-compatible API. Model discovery runs
automatically when the URL, preset, or saved key changes; **Scan** remains as a
manual retry, and its results populate the model dropdown. Each row can run as
**Batch** or **Live**. Batch requires compatible model-list, Files, and Batch
routes, while Live supports chat-completions-only and keyless local servers. The
selected RPG Maker MV/MZ game folder is scanned for eligible event text,
database text, and control-code-heavy lines. **Content selection** offers a
general-purpose Balanced mix, dialogue/events only, database only, or a Custom
tree containing Map files, Common Events, Troops, Actors, Classes, Skills,
Items, Weapons, Armors, Enemies, States, and map names. Custom mode can select
individual `MapNNN.json` files and include or exclude control-code-heavy event
lines; eligible Japanese-line counts are shown beside every available source.
The resulting sample rotates across files and takes one contiguous same-scene
chunk, up to **Lines per sample**, on each file's turn. This preserves useful
dialogue context without letting one large map dominate or spreading the test
into tiny allocations across every map. Its deterministic ordering is seeded by
a fingerprint of the selected game's corpus, so the same game and settings
reproduce the same selection while a different game receives a different stable
ordering. Each model gets the same source, system
prompt, matched glossary, previous Japanese source lines, output schema, and
hidden consistency-check schedule. Prompt and glossary context are built by the
normal translation engine from the selected game's `glossary.txt`,
`skills/game.md`, `skills/quirks.md`, and optional custom game skills.

Select the folder containing the game itself. Evaluation automatically uses
`data/` for RPG Maker MZ or `www/data/` for RPG Maker MV and shows the resolved
JSON location before preparing the test. Selecting a direct JSON data folder,
including the tool's existing `files/` folder, also works. Evaluation currently
uses the workflow's configured game root for translation context when `files/`
is selected. If no matching game root can be resolved, preparation is blocked
instead of silently falling back to the shipped base glossary. Evaluation
currently supports MV/MZ JSON projects; XP, VX, and VX Ace binary data are not
supported.

Preparing a benchmark is offline. **Test template** keeps understandable Quick,
Standard, and Thorough presets and adds Custom controls for total test lines,
same-scene lines per sample, repeated sample count, and total runs per repeated
sample. A sample is translated as one ordered block and is also the unit shown
and scored in blind review; its lines are not scored independently. Repeats are
used for whole-block consistency, while non-repeated samples run once. Preparation
reports how many eligible lines, samples, and files were found and selected.
If a content filter contains fewer lines than the chosen template, preparation
shows the exact shortfall and requires confirmation before switching to the
reduced Custom size; selections below 60 eligible lines are rejected. The run
manifest freezes the resolved content filter, corpus fingerprint, sampling
seed, and exact selected segment IDs so a saved evaluation remains auditable.
Before paid jobs are sent, the page shows a likely upper bound and a theoretical
ceiling for every model and asks for confirmation. The default hard limit is $10
per model: the likely upper bound must remain below an 80% safety threshold, and
the theoretical ceiling must fit the full budget. Every request has the same
4,096-token response ceiling; live theoretical ceilings also include all three
automatic attempts. Results are checked
for missing lines, Japanese residue, and broken
placeholders/control codes. Hover **Valid ⓘ** or **Consistency ⓘ** for the exact
meaning of each score. Each row of the final CSV contains one source JSON array
and one aligned translation array per randomized candidate. Model identities are
shuffled independently per sample. Reviewers rank each complete block for Meaning
Accuracy, Glossary & Prompt compliance, Natural & Contextual English, and Best
Overall. Every ranking uses `>` and `=` for equivalent tiers (`A>B>C`, `A=B>C`,
or `A=B=C`). Rankings receive fixed-sum
Borda points: three strict ranks score 2/1/0, while tied candidates average the
points for the positions they occupy. The single whole-sample ranking is applied
to every line in that sample when totals are calculated, preserving per-line
weight without asking the reviewer for separate line judgments. After exporting
it, **Copy review
skill** copies path-specific instructions for an AI second opinion; the tool
warns that AI judging may be biased and is not a replacement for human review.
Exporting the CSV creates the hidden scoring key; complete its ranking column
before importing it back into the same run. Legacy `winner`/`TIE` review CSVs
remain importable, but re-exporting is required to capture complete rankings.
Prepared and provider-active work is kept under `log/evaluation_work/`; a new
preparation replaces older work that was never submitted. Only evaluations
whose model results completed successfully are moved into `log/evaluations/`.
The saved-evaluation picker also shows submitted work so provider jobs can be
reconnected after restarting the app. Prepared runs stay temporary; terminal failed runs
remain visible so their diagnostics and partial results can be inspected or exported.
Completed history is capped at the newest 50 runs, with the oldest completed
run removed when the limit is exceeded. Saved API-key secrets are never copied
into either location.

Evaluation Batch jobs are also registered in Batch History. They are marked
as Evaluation jobs and can be monitored or canceled there, but cannot be
resumed or consumed as normal game translation batches. Live rows finish in
the Evaluation page and do not create Batch History entries.

Every run remains available from the saved-evaluation picker in **Evaluation
results**; preparing a new benchmark does not replace earlier results. A selected run can be exported
as a portable `.dazedeval` archive and imported on another installation. The
archive contains its frozen manifest, result files, validation summaries, and
blind-review state, but never saved API-key secrets. Imports always create a
new history entry rather than overwriting an existing run. An imported run
that still has provider jobs in progress remains paused until the user chooses
**Refresh results** and confirms reconnecting its saved API URLs.

Batch requests do not share memory with one another. All required context is
therefore embedded in every individual request. In the evaluator, that context
is frozen in the manifest before any provider-specific request is generated.

---

## Folder Structure

| Folder | Purpose |
|---|---|
| `files/` | Place game files here before translating |
| `translated/` | Translated output appears here |
| `log/` | Translation logs and cache |
| `modules/` | Engine-specific translation scripts |
| `gui/` | GUI source code |

---

## Finding Untranslated Text (Snipping Tool OCR)

When playtesting a translated game, you'll inevitably find text that was missed or needs fixing. The fastest way to grab Japanese text from the screen and search for it in the game files is with the **Windows 11 Snipping Tool** — its built-in OCR is far better than most dedicated OCR tools for Japanese text.

### How to Use It

1. Press **Win+Shift+S** to open the Snipping Tool and take a screenshot of the untranslated text in-game.
2. The screenshot opens in the Snipping Tool editor. Click the **Text Actions** button (the icon with lines of text) in the toolbar.
3. The tool will detect and highlight all text in the image. You can now **click and drag** to select specific text, or click **Copy all text** to grab everything.
4. Paste the copied Japanese text into VSCode's search (`Ctrl+Shift+F` to search across all files) to find exactly where it lives in the game data.
5. Fix or re-translate that file as needed.

### Why Snipping Tool?

- **Built into Windows 11** — no extra software to install.
- **Excellent Japanese OCR** — handles kanji, hiragana, and katakana very accurately, even from stylized game fonts.
- **Quick workflow** — screenshot → copy text → paste into search, all in a few seconds.

> **Tip:** If you're on Windows 10 or the Text Actions button doesn't appear, make sure Snipping Tool is updated via the Microsoft Store. Alternatively, [ShareX](https://getsharex.com/) with its OCR feature is a good free option.

---

## RPG Maker Translation Workflow

Here's the recommended step-by-step process for translating an RPG Maker MV/MZ game. This is also shown inside the GUI's RPG Maker tab.

| Step | Action |
|------|--------|
| **1** | **Parse speakers → Glossary** — Use the Parse Speakers feature to add character names from the game files to the selected game's `glossary.txt`. |
| **2** | **Identify speaker genders** — Figure out which characters are male/female and update the Glossary accordingly. This helps the AI use correct pronouns. |
| **3** | **Translate Actors.json, MapInfos.json** — These are small files with character and map names. Good to do first. |
| **4** | **Translate Items, System, Weapons, etc.** — All the data files that aren't maps or events. Place them in `files/`, translate, then copy results back. |
| **5** | **Find speaker names** — Enable CODE 101 (Speakers), check for bracketed names, or use the "First Line = Speaker" option to capture speaker names properly. |
| **6** | **Replace `\n[0-999]` variables** — Some games use variable codes like `\n[1]` for character names. Replace these with the actual actor names so the AI can translate around them. |
| **7** | **Translate Maps & CommonEvents** — The bulk of the game's dialogue. Start with a small map to test, then do the rest. You can use **Estimate** in the GUI to check the cost before running. |
| **8** | **Edit plugins for menus/text** — Some UI text lives in `plugins.js` or plugin parameters. You may need to manually translate these in a text editor. |
| **9** | **Translate CODE 122 vars, 356 plugins as needed** — Enable these codes in the RPG Maker tab if the game stores dialogue in variables or plugin commands. |
| **10** | **Playtest → find issues → fix → repeat** — Play through the game, screenshot any untranslated text, search for it in the game files, and re-translate as needed. |

> **Note:** Some text (e.g., CODE 122 variables) may only update when starting a new save file.

---

## Wolf RPG (WolfDawn) Translation Workflow

WOLF RPG Editor games are handled by a dedicated, guided workflow built on the bundled [WolfDawn](https://gitgud.io/zero64801/wolfdawn) `wolf` CLI.
It unpacks the game's `.wolf` archives, extracts every translatable string to JSON, translates it with the same AI pipeline used elsewhere, then injects the results back into the game byte-exact.

Open the **Workflow** tab and choose **Wolf RPG (WolfDawn)** from the engine selector at the top.

| Step | Action |
|------|--------|
| **0 Project** | Select the game root folder (browse or Enter — detection also runs when you reopen the tab). If `wolf_json/` does not exist yet, the tool automatically unpacks `.wolf` archives when needed and extracts text into the game's `wolf_json/` folder (maps, common events, databases, `Game.dat`, Evtext, and `names.json`). A checklist lists every JSON file in `wolf_json/`; tick the ones you want and click **Import** (or leave Step 0 — checked files auto-import into the tool's `files/` folder, matching the RPG Maker workflow). Extraction snapshots pristine binaries into `wolf_json/originals/` for idempotent inject in Step 7. |
| **1 Pre-process** | Optional: **dazedformat** normalises JSON in `wolf_json/` and `files/` (`json.dump`, indent 4) for clean git diffs; **Copy gameupdate/** installs the updater scripts, patch scripts, `.gitignore`, and `UberWolfCli.exe` into the game root for git-based patching (players auto-unpack `Data.wolf` on first GameUpdate). Paths auto-fill from Step 0. |
| **2 Glossary** | Build the Glossary (`glossary.txt`) before translating: copy the WOLF-tailored prompt into Cursor/Copilot with the extracted `files/` JSON, let it discover character names, speech registers, and lore terms, then paste the result into the in-tab editor and save. Item/skill/enemy value names (`names.json`) are translated in Step 3 and added to the Glossary automatically during Phase 0—do not list them here. |
| **3 Names** | Translate `names.json` (item/skill/enemy/map value names). WolfDawn tags each name with a per-entry **safety** badge (`safe`, `refs`, or `verify`). Phase 0 translates only `safe` entries; `refs` and `verify` names stay Japanese so inject skips them. Review the category breakdown for this game, pick **Translation mode** (Normal or Batch), and run **Translate safe names (Phase 0)**. |
| **4 Database** | Review the **discovery summary** to see where this game's text lives (standard RPG sheets vs custom dialogue tables). Database sheets are classified as foundation (items, skills, descriptions — translate first) or narrative (custom event/profile sheets — translate after foundation). Use **Translate foundation DB** then **Translate narrative DB**, or tick specific sheets and run **Translate checked sheets only**. Optional: copy the **DB structure prompt** for an AI audit and import the returned JSON into `wolf_json/db_profile.json`. |
| **5 Maps/Events** | Translate map scripts (`.mps`), common events (`CommonEvent.dat`), `Game.dat`, and Evtext. Run after Steps 3–4 so Glossary and database terms are consistent. Configure speaker handling for low-confidence nameplate guesses. Batch mode is recommended for large `CommonEvent.dat` files. |
| **6 Precheck** | Runs name reconcile + consistency check, then dry-runs selected JSON for safety-guard skips; fix those lines before writing binaries. |
| **7 Inject** | Always **Inject all** translated JSON from `translated/` into Data/ in one pass (keeps `names.json` and DB/map files in sync). Optional **Convert Japanese punctuation to ASCII**. Font-size drift from wrap is allowed automatically. Optional **Layout-restore** re-applies source whitespace pads. |
| **8 Package** | Run from loose `Data/` (backs up `Data.wolf` → `.bak`) or repack `Data.wolf` so you can playtest and see overflow in-game. Optionally rewrite existing `.sav` files so old Japanese saves load in the translated build. |
| **9 Fix wrap** | After packaging, paste overflowing in-game text to **search** `translated/` JSON and jump to the database sheet and row (sheet names match Step 4 and `names.json` notes, e.g. `├■街の噂（MOB）`). Edit the line, set wrap width, **Wrap this row** or **Wrap all overflowing rows in this sheet**, save, then **Inject all** (Step 7) and re-package to verify. Per-sheet widths are remembered in `wolf_json/wrap_profile.json`. **Advanced:** **wolf relayout** for event message boxes (maps/CommonEvent only — not bulletin-style DB UI) and **wolf desc-relayout** for standard 説明 description fields. |

### Recommended order by game layout

After Step 0 extract, the **Database** tab discovery report classifies your game:

| Layout | What to do |
|--------|------------|
| **DB-heavy** (most dialogue in custom database sheets) | Names → foundation DB → narrative DB → maps/events |
| **Classic RPG** (most dialogue in maps/common events) | Names → foundation DB → maps/events (skip narrative DB if none) |
| **Hybrid** | Names → foundation DB → narrative DB → maps/events |

> **`wolf` binary:** Prebuilt `wolf` CLIs for Windows and Linux are bundled offline under `util/wolfdawn/bin/<platform>/`, so no toolchain or build step is needed. They update when you update DazedTL. If your platform's binary is missing, update the tool or ask the maintainer to refresh the bundled copy.

> **Legacy modules:** The older `Wolf RPG` / `Wolf RPG 2` modules (configured in the Engine Config tab) still exist for edge cases, but the WolfDawn workflow above is the recommended path.

---

## Using Copilot & VSCode

[VSCode](https://code.visualstudio.com/) is a free code editor, and with [GitHub Copilot](https://marketplace.visualstudio.com/items?itemName=GitHub.copilot) you get an AI assistant built right into it. This is incredibly useful for translation work — you can ask the AI to help modify game files or even tweak the tool's modules without needing to know how to code.

### Setup

1. Install [VSCode](https://code.visualstudio.com/).
2. Install the **GitHub Copilot** extension (`Ctrl+Shift+X` → search "GitHub Copilot").
3. Sign in with your GitHub account (Copilot has a free tier).

### Editing Game Files with AI

Open your game folder in VSCode (`Right Click` → `Open with Code`) and use Copilot Chat (`Ctrl+Shift+I`) to ask for changes. Examples:

- *"Replace all `\n[1]` with `Shino` in this file"*
- *"Translate all the Japanese menu text in this plugins.js file to English"*
- *"This dialogue has broken line breaks — fix the formatting"*

You can also select a block of text, right-click, and choose **Copilot → Fix / Explain / Modify** to work on just that selection.

### Modifying Tool Modules

Open the DazedTL folder in VSCode and ask Copilot to make changes to the translation modules. Examples:

- *"Add a new regex pattern to skip lines that start with //"*
- *"Change the wordwrap logic to break on full-width punctuation"*
- *"Explain what CODE 356 does in rpgmakermvmz.py"*

Copilot can read the surrounding code and suggest context-aware edits — you just review and accept. This makes it easy to customize the tool for specific games without deep Python knowledge.

### Tips

- Use **Ctrl+Shift+I** to open Copilot Chat and ask questions about any file you have open.
- Use **Ctrl+I** for inline editing — select code, describe what you want changed, and Copilot will rewrite it in place.
- Use [Git](https://git-scm.com/) with your game folder so you can always undo changes if something breaks. The [GitLens](https://marketplace.visualstudio.com/items?itemName=eamodio.gitlens) extension makes this even easier.

---

## Version Control with Git

Git tracks every change you make to your game files, so you can compare translations against the originals and roll back mistakes. This is optional but **highly recommended** — it has saved countless hours of work.

### Install Git

1. Download and install [Git](https://git-scm.com/). The default settings during installation are fine.
2. Open a terminal and verify it's installed: `git -v`

### Set Up Git in Your Game Folder

1. Open your **game folder** (where `Game.exe` lives) in VSCode — right-click the folder → **Open with Code**.
2. Open the terminal in VSCode (`Ctrl+`` ` ``) and run:
   ```
   git init
   ```
   This creates a new Git repository in that folder.

### Create a .gitignore

Not every file needs to be tracked. Create a file called `.gitignore` in the game folder with contents like this:

```plaintext
# Ignore everything except text-based game files
*.*
# Allow these file types
!*.json
!*.txt
!*.js
!*.csv
!*.ks
!*.tjs
!*.rb
!*.rvdata2
# Other useful files
!.gitignore
```

This tells Git to only track the file types that matter for translation.

### Save Your First Commit

1. Click the **Source Control** icon on the left sidebar (or press `Ctrl+Shift+G`).
2. You'll see all the game files listed. Type `Initial Commit` in the message box and click **Commit** → **Yes** (to stage all files).
3. Your original files are now saved.

### Create an "original" Branch

This lets you always compare your translated files against the untouched originals.

1. Press `Ctrl+Shift+P` → type **Create Branch** → name it `original` → press Enter.
2. Press `Ctrl+Shift+P` → type **Checkout** → select `main` (or `master`).

Now you're back on the main branch. Any translations you make here can be compared against the `original` branch at any time.

### Comparing Changes

After translating and copying files back into the game folder:

1. Open **Source Control** — you'll see all modified files listed.
2. Click any file to see a side-by-side diff of what changed.
3. Commit your changes with a message like `Translated Items, Weapons, Actors`.

To compare with the original untranslated files:
- Right-click any file → **Open Changes** → **Open Changes with Branch** → select `original`.

### Recommended Extension

Install [GitLens](https://marketplace.visualstudio.com/items?itemName=eamodio.gitlens) (`Ctrl+Shift+X` → search "GitLens") for a much richer Git experience — commit history, file annotations, branch comparisons, and more.

---

## Troubleshooting

- **`START.bat` closes immediately** — Make sure Python 3.12–3.14 is installed and added to your PATH. Open a terminal and run `python -V` to check.
- **API errors** — Double-check your API key and organization in `.env`. Make sure you have credits/quota with your provider.
- **Missing dependencies** — Delete the `.venv` folder and run `START.bat` again. It will recreate the environment and reinstall everything.
