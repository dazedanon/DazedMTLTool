# DazedMTLTool

An AI-powered game translation tool with a GUI. Translate RPG Maker, Ren'Py, Tyrano, Wolf RPG, Kirikiri, and other game engines from Japanese to English using GPT or compatible AI models.

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

- **Python 3.12 – 3.14** — [Download here](https://www.python.org/downloads/). During installation, **check "Add Python to PATH"**.
- **An AI API Key** — You'll need an API key from [OpenAI](https://platform.openai.com/settings/organization/api-keys), [Google Gemini](https://aistudio.google.com/apikey), or a compatible provider.

> **Tip:** You can verify Python is installed by opening a terminal and running `python -V`. It should print something like `Python 3.13.x`.

---

## Quick Start

### 1. Download the Tool

1. Click the green **Code** button at the top of this page and select **Download ZIP**.
2. Extract the ZIP to a folder of your choice (e.g., `C:\DazedMTLTool`).

### 2. Set Up Your API Key

1. Inside the tool folder, find `.env.example` and make a copy of it named `.env`.
2. Open `.env` in any text editor (Notepad works fine) and fill in your API details:
   - `key` — Your API key.
   - `organization` — Your organization key (make something up if using a self-hosted or non-OpenAI API).
   - `API_PROVIDER` — Set to `openai` or `gemini` depending on your provider.
3. The rest of the settings (wordwrap, batch size, etc.) can be left as defaults for now. You can tweak them later.

### 3. Launch the GUI

**Double-click `START.bat`**. It will:
- Create a virtual environment automatically.
- Install all dependencies.
- Launch the GUI.

That's it! From now on, just double-click `START.bat` to open the tool.

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
Engine-specific settings. For example, RPG Maker lets you toggle which event codes to translate (dialogue, choices, variables, etc.). The defaults cover the most common text (~95% of a game), so you usually don't need to change these.

### RPG Maker / Wolf / CSV Tabs
Specialized tabs with extra options for those specific engines.

---

## Vocab & Prompt

### vocab.txt
This file gives the AI context about your game — character names, genders, recurring terms, etc. The better your vocab file, the more consistent the translation.

Open `vocab.txt` (or copy `vocab.txt.example` to `vocab.txt` if it doesn't exist) and add entries like:

```plaintext
# Game Characters
水無月 士乃 (Minazuki Shino) - Female
暗黒斎 (Dark Kokusai) - Male
フトシ (Futoshi) - Male
```

Format: Japanese name, English name in parentheses, then gender.

> **Note:** A very large vocab file can increase API costs and potentially reduce quality. Focus on the most important characters and terms.

### prompt.txt
This is the system prompt sent to the AI. A default `prompt.txt` is included and works well for most games. You generally don't need to edit it unless you want to customize the translation style.

---

## Tips

- **Check `log/translations.txt`** after a run to see what was translated. You can copy useful terms from it into `vocab.txt` for consistency in future runs.
- **Start small** — Translate a few files first to make sure the output looks good before doing the whole game.
- **Wordwrap** — If text overflows or looks awkward in-game, adjust the `width` setting in `.env` or the Config tab. `60` is a good default for most RPG Maker games.
- **Version control** — Using [Git](https://git-scm.com/) with the game folder is highly recommended. It lets you track every change the translation makes, compare with original files, and roll back if needed.

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

## RPG Maker Translation Workflow

Here's the recommended step-by-step process for translating an RPG Maker MV/MZ game. This is also shown inside the GUI's RPG Maker tab.

| Step | Action |
|------|--------|
| **1** | **Parse speakers → vocab.txt** — Use the Parse Speakers feature to pull character names from the game files into `vocab.txt`. |
| **2** | **Identify speaker genders** — Figure out which characters are male/female and update `vocab.txt` accordingly. This helps the AI use correct pronouns. |
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
- *"Make this module also handle .yaml files"*
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
!*.yaml
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