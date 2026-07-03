# DazedMTLTool

An AI-powered game translation tool with a GUI. Translate RPG Maker, Ren'Py, Tyrano, Wolf RPG, Kirikiri, and other game engines from Japanese to English using GPT, Gemini, [Mistral](https://docs.mistral.ai/api), or other compatible AI models.

## Credits

- **[Sinflower](https://github.com/Sinflower)** — [RV2JSON](https://github.com/Sinflower/RV2JSON) — enables RPGMaker Ace games to be translated the same way as MV/MZ by converting rvdata2 files to JSON and back. A copy is bundled offline in `util/ace/offline/`; newer builds are downloaded when online.
- **Sakura & Kao_SSS** — TL Inspector (`util/tl_inspector/`) — in-game translation source inspector and live-edit plugin for RPG Maker MV/MZ playtesting.
- **Len** — [Forge](https://gitgud.io/zero64801/forge-mvmz) MV/MZ playtest plugin (`util/forge/`), Mistral API support (provider integration and adaptive rate limiting), and batch translation mode (Anthropic Message Batches API).

## Table of Contents

- [Supported Engines](#supported-engines)
- [Requirements](#requirements)
- [Installing Python](#installing-python)
- [Quick Start](#quick-start)
- [Using the GUI](#using-the-gui)
- [Vocab & Prompt](#vocab--prompt)
- [Tips](#tips)
- [Mistral API (free tier)](#mistral-api-free-tier)
- [Batch Translation (Anthropic, 50% off)](#batch-translation-anthropic-50-off)
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
2. Extract the ZIP to a folder of your choice (e.g., `C:\DazedMTLTool`).

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

**Linux/macOS:** Run `./START.sh`, or double-click `DazedMTLTool.desktop` (choose **Allow Launching** when your file manager asks). From then on, either method works.

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

### Engine Config Tab
Engine-specific settings. RPG Maker has the most mature support — you can toggle exactly which event codes to translate (dialogue, choices, variables, plugin commands, etc.). The defaults cover ~95% of a game's text out of the box. See the [RPG Maker Translation Workflow](#rpg-maker-translation-workflow) section for a detailed step-by-step guide.

Other engines (Wolf RPG, Ren'Py, Tyrano, etc.) have less granular support and may require more manual tweaking or post-editing depending on the game.

### RPG Maker / Wolf / CSV Tabs
Specialized tabs with extra options for those specific engines.

---

## Vocab & Prompt

### data/vocab.txt
This file gives the AI context about your game — character names, genders, recurring terms, etc. The better your vocab file, the more consistent the translation.

On first run, `data/vocab.txt` is created automatically from `data/vocab_base.txt` if it does not exist yet. Add entries like:

```plaintext
# Game Characters
水無月 士乃 (Minazuki Shino) - Female
暗黒斎 (Dark Kokusai) - Male
フトシ (Futoshi) - Male
```

Format: Japanese name, English name in parentheses, then gender.

> **Note:** A very large vocab file can increase API costs and potentially reduce quality. Focus on the most important characters and terms.

### data/prompt.txt
This is the system prompt sent to the AI. A default `data/prompt.txt` is included and works well for most games. You generally don't need to edit it unless you want to customize the translation style.

---

## Tips

- **Check `log/translations.txt`** after a run to see what was translated. You can copy useful terms from it into `data/vocab.txt` for consistency in future runs.
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

> **Note:** Batch mode (50% off) is Anthropic/Claude only. Mistral runs live translation through the rate limiter above.

---

## Batch Translation (Anthropic, 50% off)

Batch mode — see [Credits](#credits).

When using a Claude model, the CLI offers a third mode that translates through the
[Anthropic Message Batches API](https://platform.claude.com/docs/en/build-with-claude/batch-processing.md)
— every token (input, output, and prompt-cache reads/writes) is billed at **50% of the live price**.
Batches usually finish within an hour (24h worst case), so use it for large jobs where you don't
need results immediately.

```
python start.py
 -> 3. Batch Translate (Anthropic Batches API, 50% off)
```

How it works (all engine modules are supported automatically):

1. **Pass 1 (collect)** — files are processed normally, but instead of calling the API each
   request is queued to `log/batch_requests.json`. Requests are byte-identical to live ones:
   the static `prompt.txt` block is cached with a 1h TTL, matched vocab and translation
   history ride along per request, and structured output enforces the exact line count.
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
   checks). Anything the batch missed or that fails validation falls back to the live API
   automatically, so the output is always complete.

Context note: in live mode the rolling translation history contains the previous batch's
English lines; in batch mode requests are independent, so the history carries the previous
batch's *source* lines instead. The model still sees the surrounding scene, and `vocab.txt`
keeps names and terms consistent — so keep your vocab file in good shape for batch runs.

Cost tracking is exact: per-file and total costs printed after the consume pass use the real
billed token counts (cache reads at 0.1x, cache writes at 2x, output at the output rate) with
the 50% batch discount applied.

`python selftest_batch.py` round-trips the whole flow offline (no API key needed) if you want
to verify the pipeline after making changes.

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
| **1** | **Parse speakers → vocab** — Use the Parse Speakers feature to pull character names from the game files into `data/vocab.txt`. |
| **2** | **Identify speaker genders** — Figure out which characters are male/female and update `data/vocab.txt` accordingly. This helps the AI use correct pronouns. |
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
| **0 Project** | Select the game folder, **Unpack** the `.wolf` archives into a loose `Data/` folder, then **Extract text** (maps, common events, databases, `Game.dat`, external event text, and the project-wide name glossary). Everything is staged into `files/` for translation. **Set up git tracking** by copying the `gameupdate/` folder (updater scripts, `patch.sh`/`patch.ps1`, and a `.gitignore` that excludes the original game files) into the game root, so the translation project can be tracked with git and later shipped as a git-based patch players apply themselves. Finally, **Format extracted JSON** (dazedformat) normalises `wolf_json/` and `files/` to the same layout the translator writes back (`json.dump`, indent 4) — run it once and commit it as your baseline so later injects produce clean, line-level git diffs instead of reformatting whole files. |
| **1 Glossary** | Build both glossaries before translating. **1a - Character & Worldbuilding Glossary (`vocab.txt`):** copy the WOLF-tailored prompt into Cursor/Copilot with the extracted `files/` JSON, let it discover character names, speech registers, and lore terms, then paste the result into the in-tab editor and save (the shared `vocab.txt` is used by every translation batch to keep names and voice consistent). **1b - Name Value Glossary (`names.json`):** translate the name glossary first, since WOLF references item/skill/enemy names by value across many files. |
| **2 Translate** | Pick the **Translation mode** (Normal or Batch - Batch uses the Anthropic Batches API, ~50% cheaper, Claude only), then run the `Wolf RPG (WolfDawn)` module over `files/`. The chosen mode also applies to the Step 1b name glossary run. Only the `text` fields are filled in; `source` is preserved so injection can verify each line. |
| **3 Inject** | Write the translations back into the game's `Data/` binaries **and** refresh the git-tracked `wolf_json/` with the translated JSON, so the game project's git diff shows both the JSON source and the injected binaries. Toggle `--en-punct` (convert Japanese punctuation to ASCII) and `--allow-code-drift` (relax the inline-code guard) as needed, and use **Check name consistency** to catch names translated differently across files. **Quick inject** lists the files you've translated so far (present in `translated/`) so you can tick just a few, inject them straight into `Data/`, and review the git diff / test in-game - ideal for iterating. **Inject all translations** writes every document and re-applies the name glossary across `Data/` for the final build. |
| **4 Package** | Either run from the loose `Data/` folder (backs up `Data.wolf` → `Data.wolf.bak`), or **Repack** a fresh `Data.wolf`, inheriting the original archive's encryption. |
| **5 Saves** | *(Optional)* Update existing `.sav` files so old Japanese saves load cleanly in the translated build. Originals are backed up automatically. |

> **`wolf` binary:** A prebuilt `wolf` CLI is bundled under `util/wolfdawn/bin/<platform>/`, so no build step is needed on supported platforms. If no bundled binary is present for your platform, the tool falls back to compiling it from the vendored source with `cargo build --release`, which requires a [Rust toolchain](https://rustup.rs/); the freshly built binary is then saved into the bundle for reuse. A clear error is shown if neither a bundled binary nor `cargo` is available.

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

Open the DazedMTLTool folder in VSCode and ask Copilot to make changes to the translation modules. Examples:

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