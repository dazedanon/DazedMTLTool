# Set Up Your AI Helper

This step is required. DazedTL translates the normal game text, while the AI helper reads the game
folder and helps with names, writing rules, menus, pictures, and Japanese text that was missed.

You do not need to know how to program. **Cline Nightly works in both Cursor and VS Code**, so use
whichever editor you prefer.

## Recommended free setup: Mistral with Cline Nightly

You can use the same Mistral API key in DazedTL and Cline. Mistral currently lets you enable Free
mode without a credit card.

### 1. Get your free Mistral API key

1. Open **[Mistral Studio](https://console.mistral.ai/)** and create an account or sign in.
2. Make sure Studio is using **Free** mode.
3. Open **API keys** and click **Create new key**.
4. Give the key a name such as `DazedTL`, then click **Create**.
5. Copy the key and keep it somewhere private. Mistral only shows a new key once.

An API key works like a password. Do not post it, send it to another person, or include it in a
screenshot.

### 2. Choose Cursor or VS Code

Install one of these editors:

- **[Cursor](https://cursor.com/downloads)**; or
- **[Visual Studio Code](https://code.visualstudio.com/Download)**.

Run the installer, then open the editor you chose.

### 3. Open the game folder

1. In Cursor or VS Code, click **File → Open Folder**.
2. Choose your working copy of the game—the folder that normally contains `Game.exe`.
3. If the editor asks whether you trust the folder, confirm only if this is the game folder you
   chose.

Opening the correct folder is important. It lets Cline see the game files when you ask for help.

### 4. Install Cline Nightly

These steps are the same in Cursor and VS Code:

1. Click the **Extensions** button on the left side of the editor. It looks like four small blocks.
   You can also press **Ctrl+Shift+X**.
2. Search for **Cline Nightly**.
3. Choose **[Cline (Nightly)](https://marketplace.visualstudio.com/items?itemName=saoudrizwan.cline-nightly)**
   and click **Install**.
4. Click the Cline icon on the left side of the editor. If it does not appear, close and reopen the
   editor.

### 5. Connect Cline to Mistral

1. In the Cline panel, click the **gear** button to open Settings.
2. For **API Provider**, choose **Mistral**.
3. Paste your Mistral API key into the **API Key** box.
4. Choose the Mistral model you want to use. For this version of DazedTL, the suggested free model
   is **Mistral Medium 3.5** (`mistral-medium-3.5`).
5. Set **Thinking** to **Medium**. Thinking gives the Agent more time to work through a task. Lower
   it if you want faster answers; raise it when a difficult task needs more care.
6. Click **Done** at the top of the Cline panel.

### 6. Make sure it works

Send Cline this test message:

> Look through this folder and tell me what kind of game it appears to be. Do not change any files.

Cline may ask for permission to read files. Approve the request if it only wants to read from the
game folder you opened. If it identifies the game or describes its folders, it is ready.

## Alternative: Cursor's built-in Agent

You do not need Cline if you prefer Cursor's own Agent and have access to its AI service.

1. Open Cursor and sign in so its AI features are available.
2. Click **File → Open Folder** and choose your working copy of the game.
3. Wait while Cursor finishes learning what is in the folder. A large game may take a few minutes.
4. Press **Ctrl+I** to open Agent chat.
5. Send this test message: `Tell me the name of the folder I have open.`

If Cursor answers correctly, its built-in Agent is ready.

## Other supported Agents: Codex and Claude Code

Both **Codex** and **Claude Code** can be installed in either Cursor or VS Code. Use one of these if
you already have access through a paid account or prefer it over Cline.

### Codex

1. Open **Extensions** in Cursor or VS Code with **Ctrl+Shift+X**.
2. Install the official **[Codex extension](https://developers.openai.com/codex/ide)**.
3. Click the Codex icon and sign in.
4. Open the game folder and send the same test message used above.

When the model choice is available, **GPT-5.6 Sol** (`gpt-5.6-sol`) is DazedTL's recommended Codex
model for difficult work. It is especially useful for translating images because it can inspect
images at their original size and handle the careful visual judgment needed for text placement.

Smaller or cheaper models may work for simple images, but they are more likely to struggle with
small lettering, stylized fonts, crowded layouts, or matching the original design. Review every
edited image before patching it into the game.

### Claude Code

1. Open **Extensions** in Cursor or VS Code with **Ctrl+Shift+X**.
2. Search for **Claude Code** and install the official Anthropic extension.
3. Open the Claude Code panel and sign in.
4. Open the game folder and send the same test message used above.

See Anthropic's **[Claude Code editor guide](https://code.claude.com/docs/en/ide-integrations)** if
you need the install link or cannot find its panel.

## Use the helper with DazedTL

Keep the same game folder open in Cursor or VS Code while you work.

Whenever DazedTL shows a button such as **Copy setup skill**, **Copy skill**, or **Copy
advanced-text audit**:

1. Click the Copy button in DazedTL.
2. Return to your Agent chat.
3. Paste the copied instructions and send them.
4. Let the Agent read the game folder and finish the task.
5. Copy any labeled answers back into the matching boxes in DazedTL.

### Where the Project Setup answers go

The Agent's answer may contain these labels. Put each part in the matching place:

| Label from the Agent | Where it goes in DazedTL |
|---|---|
| `glossary` | The **Glossary** box |
| `speakers` | Use it to set the speaker choices shown above the boxes |
| `translation_quirks` | The **Translation quirks** box |
| `game_skill` | The **Game skill** box |
| `rpgmaker_config` | The RPG Maker choices for code 408, text width, and fonts |

The labels are directions, so do not paste the Agent's entire answer into every box. If a label is
missing or unclear, ask the Agent to show the answer again with those exact labels.

Read what the Agent plans to do before approving a file change or command. If you are unsure, ask
it to explain the change in simple language first.

## If something does not work

- **Cline icon is missing:** Close and reopen Cursor or VS Code. You can also press
  **Ctrl+Shift+P**, type `Cline: Open In New Tab`, and press Enter.
- **Invalid API key:** Return to Mistral Studio, create a new key, and paste the new key into Cline
  Settings.
- **Too many requests:** Free accounts have limits. Wait a little while, then try again.
- **The Agent cannot see the game:** Use **File → Open Folder** and choose the folder containing
  `Game.exe`, then start a new chat.
