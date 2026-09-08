# SheepClickerTL

BepInEx 6 IL2CPP plugin that translates SheepClicker text at runtime by
intercepting `TMP_Text.text` / `Text.text` setters and replacing the value
when a translation entry exists.

## Layout

```
SheepClickerTL/
├─ Plugin.cs            # BepInEx entry point
├─ TranslationStore.cs  # JSON loader + lookup
├─ TextPatches.cs       # Harmony patches on text setters
├─ SheepClickerTL.csproj
└─ translations/
   ├─ dialogues.json    # output of parse_dialogues.py
   └─ texts.json        # output of parse_text.py
```

## Build

1. Install BepInEx 6 (`BepInEx-Unity.IL2CPP-win-x64`) into
   `C:\Users\sw\Desktop\SheepClicker`. Launch the game once so BepInEx
   generates the interop assemblies in `SheepClicker_Data\Managed`
   (or wherever your BepInEx config writes them — see the `<ManagedDir>`
   property in the csproj).

2. Build:
   ```
   dotnet restore
   dotnet build -c Release
   ```

3. Output `SheepClickerTL.dll` plus `translations/*.json` is auto-deployed
   to `<GameDir>\BepInEx\plugins\SheepClickerTL\` if BepInEx is installed.

## Workflow

1. Run the python tools against the AssetRipper export:
   ```
   python parse_dialogues.py
   python parse_text.py
   ```
2. Fill English values into `dialogues.json` / `texts.json`.
3. Drop them into `translations/` and rebuild (or copy directly to
   `BepInEx\plugins\SheepClickerTL\translations\` — they're loaded fresh
   on game start).

## Config (BepInEx/config/com.sw.sheepclicker.tl.cfg)

- `Verbose=false` — log every translated string.
- `FallbackContains=false` — if a string isn't an exact match, scan all
  translation keys for a substring match. Slow; off by default.

## Notes

- The setter prefix mutates `value` in-place, so the rest of the engine
  (layout, text effects, accessibility) sees only the translated string.
- `TranslationStore.Normalize` makes lookups forgiving of `\\n` vs `\n`
  vs CRLF differences between the CSV source and what's loaded at runtime.
- Untranslated entries (empty values in JSON) are skipped at load time
  rather than counted as misses, so missing translations don't slow
  lookups.
