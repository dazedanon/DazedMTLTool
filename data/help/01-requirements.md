# Before You Start

You need the game, an AI translation key, and enough room on your computer for another copy of the
game. An AI helper program is also strongly recommended for setup and cleanup.

## 1. Keep a safe copy of the game

Make a copy of the entire game folder and leave that copy untouched. On Windows, right-click the
folder, choose **Copy**, right-click an empty area, and choose **Paste**. If anything goes wrong,
you can return to that safe copy.

If you are not sure what the **game folder** is, it is usually the folder containing `Game.exe`.

## 2. Start DazedTL

On Windows, double-click `START.bat`. On Linux or macOS, use `START.sh` or the desktop shortcut. If
you are reading this inside DazedTL, this part is already done.

The first start may take a while because DazedTL prepares the extra files it needs. You do not
need to set up Python yourself when these launchers work.

## 3. Add an AI translation key

An **API key** is a private password that lets DazedTL use an online AI service. You get one from
the AI company you choose. Keep it secret and do not share screenshots that show it.

In DazedTL, open **Configuration → General**, then choose the company and enter:

- your API key;
- the model name;
- the service address, if DazedTL asks for it.

The recommended choices shown in this version of DazedTL are:

| Choice | Good for |
|---|---|
| **Claude Sonnet 4.6** | Strong quality; paid; can use cheaper Batch jobs for large amounts of text |
| **Mistral Medium 3.5** | Free option; use Normal translation mode |

If you use Claude, choose **Claude (Anthropic)** as the provider. If you use Mistral, choose
**Mistral**. The company that gives you the key may charge for each translation, so begin with one
small map instead of the whole game.

## 4. Install an AI helper for the harder cleanup

Some game text is hidden in places DazedTL cannot safely change by itself. An AI helper can read
the game folder and help find that text. You can use:

- **[Cursor](https://cursor.com/)**; or
- **[VS Code](https://code.visualstudio.com/)** with GitHub Copilot or a similar helper.

In either program, choose **File → Open Folder**, then select the game folder. Later, DazedTL gives
you text to copy into the helper's chat. You do not need to write code yourself.

You can translate without this helper, but names, menus, and leftover Japanese text may take more
work to fix.

## Helpful extra tool

The Windows Snipping Tool can copy Japanese words from a screenshot. This is useful when you see
Japanese in the game but do not know which file contains it.
