# Start Here

DazedTL helps turn Japanese game text into English with an online AI service. It works best with
**RPG Maker** and **WOLF RPG** games. You do not need to know programming.

## Read these pages first

Read the four pages under **DEFINITELY READ THESE** from top to bottom:

1. **Start Here**
2. **Set Up Your AI Helper**—required
3. **Set Up Git**—optional, but strongly recommended
4. **Full Translation Example**

Everything under **EXTRA INFORMATION** is optional. Open those pages when you need more detail or
have a problem. You do not need to memorize them.

## Before you begin

### Keep an untouched game

Make a copy of the entire game folder and never edit that copy. Work on a second copy instead. On
Windows, right-click the game folder, choose **Copy**, then **Paste** it somewhere with enough free
space.

The **game folder** is usually the folder containing `Game.exe`.

### Start DazedTL

On Windows, double-click `START.bat`. On Linux or macOS, use `START.sh` or the desktop shortcut. If
you are reading this inside DazedTL, it is already running.

The first start may take a while while DazedTL prepares what it needs. You normally do not need to
install or configure Python yourself.

### Add your translation key

An **API key** is a private password that lets DazedTL use an online AI company. Never share it or
include it in screenshots.

Open **Configuration → General**. Choose the company, paste its API key, choose a model, and click
**Save**. The beginner choices in this version are:

| Choice | Good for |
|---|---|
| **Claude Sonnet 4.6** | Strong paid option; supports cheaper Batch jobs for large translations |
| **Mistral Medium 3.5** | Free option; use Normal translation mode |

Choose **Claude (Anthropic)** for a Claude key or **Mistral** for a Mistral key. Online translation
may cost money, so the example starts with one small map.

## What you will do

1. Open the working game copy in DazedTL and your AI helper.
2. Let DazedTL copy out a small amount of game text.
3. Give the helper DazedTL's setup instructions.
4. Translate the small test.
5. Put the English back into the working game.
6. Play it, fix problems, and repeat with a little more text.

Continue to **Set Up Your AI Helper**.
