# LoserLifeATest

IL2CPP BepInEx test plugin for Loser Life.

This is intentionally not a real translation plugin yet. It replaces extracted `TMP_Text` and legacy `UnityEngine.UI.Text` strings with `A` so we can verify runtime text coverage.

The important part: by default it only replaces strings found in `translations/known_texts.b64`, generated from `tooling/outputs/japanese_text_all_occurrences.csv`. It also accepts composed runtime strings when all Japanese fragments are known, which covers item tips like `tip + item type + stack size + number`.

Exact extracted strings become `A`, including any numbers that were part of that original static text. Dynamic values are preserved only for non-exact composed runtime strings. For example, a covered runtime string shaped like `{item name} x {amount}` becomes `A x 5`, and `{amount} + count suffix` becomes `5A`. If Japanese text remains visible in-game, that text is probably missing from the extraction set or being rendered outside TMP/UI Text.

## Coverage

- Harmony prefixes on TMP and UI Text setters.
- Harmony prefix on `TMP_Text.SetText(string, bool)`.
- Optional `Awake` / `OnEnable` postfix refreshes for deserialized scene and prefab text when those methods exist in the IL2CPP interop assembly.
- A lightweight `DontDestroyOnLoad` sweeper runs once at startup and once on scene changes by default. Continuous timed scanning is off unless enabled in config.

## Build And Deploy

From the game root:

```powershell
.\tooling\build_loserlife_atest.ps1
```

The build wrapper uses local game BepInEx assemblies and deploys to:

```text
BepInEx\plugins\LoserLifeATest\LoserLifeATest.dll
BepInEx\plugins\LoserLifeATest\translations\known_texts.b64
```

## Config

BepInEx will generate the config after the first game launch:

```text
BepInEx\config\com.sw.loserlife.atest.cfg
```

Useful settings:

- `Replacement`: default `A`.
- `ReplaceEmptyText`: default `false`.
- `RequireExtractedMatch`: default `true`.
- `AllowCompositeExtractedMatch`: default `true`.
- `PreserveDynamicValues`: default `true`; only affects non-exact composed runtime strings.
- `LogUnmatchedJapanese`: default `true`.
- `EnableSweeper`: default `true`.
- `ContinuousSweeper`: default `false`.
- `SweepOnSceneChange`: default `true`.
- `SweepIntervalSeconds`: default `15`; only used when `ContinuousSweeper` is true.
- `Verbose`: default `false`.
