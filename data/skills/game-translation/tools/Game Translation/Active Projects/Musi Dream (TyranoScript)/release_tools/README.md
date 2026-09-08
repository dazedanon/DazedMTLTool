# Musi Dream English patch

This unofficial Japanese-to-English patch contains manually authored translations; no translation API was used. It is not presented as an official or creator-endorsed translation.

The patch translates all 509 extracted runtime text units across 574 occurrences, including dialogue, narration, choices, nameplates, and engine messages. It also replaces 30 image files with manually lettered English versions, including the title, tutorials, hints, controls, browser captions, and template labels. Image edits preserve the original filenames, canvas dimensions, and transparency modes.

One image, the Hdouga video listing (`data/bgimage/ev_Hdouga.jpg`), remains unchanged because it contains sexual depictions explicitly labeled as minors.

## Install

Extract the patch ZIP and open PowerShell in the extracted patch folder. Close the game, then run the following command, replacing the example path with the folder containing your `musi_dream.exe`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install.ps1 -GameRoot 'C:\path\to\musi_dream-win32-x64'
```

The installer uses the game's bundled runtime. No Python, separate Node installation, API key, download, or internet connection is needed. Keep the scripts, `manifest.json`, and `payload` folder together.

After installation, double-click `musi_dream.exe` to play. The original readme likewise instructs players to extract the game ZIP and launch that executable.

Existing original saves are supported. Loading a save refreshes its cached visible message, nameplate, and choices with the English text. Save files are not rewritten by the installer.

## Restore Japanese

Close the game and run:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\restore.ps1 -GameRoot 'C:\path\to\musi_dream-win32-x64'
```

Installation keeps the exact original archive at `resources\app.asar.original`. Keep this backup and the patch package for restoration. The installer verifies the original game, patch files, and rebuilt archive before replacing `resources\app.asar`. It rejects unknown game versions or independently modified archives. Installing the identical patch again is safe; restoration also accepts an already restored original.

To update from an earlier English patch, first restore Japanese using that earlier patch's `restore.ps1`, then install the new patch. Restoration also returns every replaced image to its exact original bytes.

If an operation reports an error, read its message before trying again. A failed build can leave a uniquely named `.tmp` candidate for inspection. The installer does not delete files, and the original backup remains available.

## Original game credits

Production and illustration: **歩路地（ほろち） / Horochi**. Circle: **250歩の路地** ([creator page](https://ci-en.dlsite.com/creator/4024)).

Sound-effect material credits, as listed in the original readme:

- オコジョ彗星
- On-Jin ～音人～ ([website](https://on-jin.com/))
- フリーBGM DOVA-SYNDROME

Keep the game's original `read_me.txt`, credits, and notices. This patch does not replace them or grant a new license to the game or its assets.
