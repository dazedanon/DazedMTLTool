# Requirements

You need three things working together: this tool, an AI translation API, and an IDE with an agent.

## 1. Python

Python **3.12 – 3.14**.
Launch with `START.bat` (Windows) or `START.sh` / the desktop launcher (Linux/macOS).
Those scripts create a venv and install dependencies for you.

## 2. AI API key

In **Configuration → General**, set:

- Provider / API base URL
- API key
- Model name

You can also edit the `.env` file next to the tool.
OpenAI-compatible endpoints and Gemini work too; pick a model based on budget:

| Goal | Recommendation |
|------|----------------|
| **Best cheap high-quality TLs + Batch mode** | **Claude Sonnet 4.6** (`claude-sonnet-4-6`) via Anthropic - Batch is ~50% off live price |
| **Free** | **Mistral** (`mistral-medium-3.5`) - free tier, no credit card; live only (no Batch discount) |

### Recommended: Claude Sonnet 4.6

Use this for most games when you can pay for API usage.
Strong translation quality at a good price, and it unlocks **Batch** mode for large maps / CommonEvents.

```plaintext
api=https://api.anthropic.com/v1
key=YOUR_ANTHROPIC_KEY_HERE
model=claude-sonnet-4-6
```

In Configuration, pick **Claude (Anthropic)** as the provider if you prefer the UI over `.env`.

### Free: Mistral

```plaintext
API_PROVIDER=mistral
api=https://api.mistral.ai/v1/
key=YOUR_MISTRAL_KEY_HERE
model=mistral-medium-3.5
```

Avoid `mistral-medium-latest` - it still points at an older release.
Mistral runs live translation with built-in rate limiting; use **Normal** mode (Batch is Anthropic/Claude only).

## 3. AI agent + IDE (required for a good workflow)

The Workflow tab expects you to use an AI coding agent for setup work that the translation API does not do alone:

- Building glossary / vocab from the game
- Choosing speaker flags
- Writing quirks and a Translation Frame
- Editing `plugins.js` UI strings (MV/MZ) or Ace `ace_json/scripts/*.rb`
- Searching for leftover Japanese after playtest

Use either:

| Tool | Notes |
|------|--------|
| **[Cursor](https://cursor.com/)** | Agent chat with the game folder open - preferred for Project Setup |
| **[VS Code](https://code.visualstudio.com/)** + Copilot (or another agent) | Same idea: open the game repo, paste Workflow prompts |

### Example: open the game in Cursor

1. In Cursor: **File → Open Folder** and select the game root (where `Game.exe` or Wolf `Data` lives).
2. In DazedMTLTool Workflow Step 2, click **Copy Project Setup**.
3. Paste into Cursor chat with the game files available (or `@`-mention key JSON files).
4. Paste the agent's labeled blocks back into the Workflow editors.

Without an IDE agent, you can still run raw Translation tab jobs, but glossary quality and plugin/UI cleanup will be much harder.

## Optional but strongly recommended

- **Git** in the game folder so you can diff and roll back bad edits
- **Windows Snipping Tool OCR** (or ShareX) for grabbing leftover Japanese while playtesting
