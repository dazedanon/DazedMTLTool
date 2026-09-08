# ひと夏の思い出 - English Patch

English fan-translation for **ひと夏の思い出** (*A Summer to Remember*) by
**はちみつサンド**.

---

## What this patches

- **The full story** - all three days, every line, plus the choice buttons.
- **The whole interface** - title screen, day select, credits, every settings
  tab, Free Mode's camera help text, and the expression/voice dropdowns.
- **The title logo.**

## Install

1. Copy **`winhttp.dll`**, **`.doorstop_version`**, **`doorstop_config.ini`**,
   **`dotnet\`** and **`BepInEx\`** from this archive into your game folder -
   the one containing `Hitonatsu.exe`. Overwrite when asked.
2. Run **`Hitonatsu.exe`**.

**The first launch takes 30 to 90 seconds** and may look frozen. It is not - the
loader is generating interop assemblies once. Every later launch is normal speed.

You do **not** need .NET installed. The runtime ships inside `dotnet\`.

## Uninstall

Delete `winhttp.dll`, `.doorstop_version`, `doorstop_config.ini`, `dotnet\` and
`BepInEx\`. The game is untouched and reverts to Japanese.

## How it works

Nothing in the game is modified. No file is repacked, no archive is rebuilt, and
no original asset ships in this archive. A BepInEx plugin swaps each line for its
English equivalent as the game draws it, so the patch is a drop-in folder and
removing it restores the original exactly.

## Notes

- Adult content is translated faithfully and is not censored or softened.
- The story is told across three days; the green orbs on the title screen replay
  what you have already seen.
- If a line still shows in Japanese, please report it with a screenshot - the
  plugin can log those itself, so they are easy to fix.

## Credits

Original game and all assets: **はちみつサンド**.
The game's own credits (models, audio, textures) are reproduced in-game under
Credits and belong to their respective authors.

Translation produced with the Mistral API and reviewed against a locked glossary
and game bible. Built on BepInEx 6 and HarmonyX.
