# TextTranslatorCpp — generic UE4SS runtime text translator

A game-agnostic UE4SS C++ mod that translates a UE game's player-facing text at
runtime by hooking `FText`/`FString` as they are displayed. Drop-in base for
localizing any UE4/UE5 title — supply a translation table, build, and enable.

This is the cleaned, game-neutral base derived from a shipped, working translator
(image-replacement code removed, all game-specific names genericized). The text
pipeline is unchanged and proven.

## What it does

- Hooks text-render paths (`TextBlock`/`RichTextBlock`/`TextRenderComponent`),
  text-format parameters, UMG widget construction, and `UDataTable` rows.
- Maintains a live registry of text widgets and corrects native C++ `SetText`
  calls (which bypass hooks) by comparing the `FText` internal data pointer each
  tick — so text never "flashes" the source language.
- Translates `FText` (display text) only by default; `FString` values are game
  logic and are left alone unless inside `DataTable` rows. (Toggle with flags.)
- Hardened against the usual UE reflection hazards: load-state guards, SEH
  shields, weak-pointer-validated caches, re-entrancy locks, hook-depth guard.

## Layout

```
TextTranslatorCpp/
  CMakeLists.txt          target = TextTranslatorCpp, links UE4SS
  src/dllmain.cpp         the whole mod (single TU)
  translation_extra.csv   sample manual-overrides table (template)
  enabled.txt             empty file; its presence enables the mod
```

## Build

Build inside an [RE-UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) C++ mods tree
(same as any `CppUserModBase` mod):

1. Place this folder under the UE4SS source's `cppmods/` (or your existing mods
   CMake tree) and add it to the parent `CMakeLists.txt` / `xmake.lua`.
2. Configure + build the `TextTranslatorCpp` target against the `UE4SS` library.
3. The output DLL is deployed as `…/ue4ss/Mods/TextTranslatorCpp/dlls/main.dll`.

## Install (per game)

```
<Game>/Binaries/Win64/
  dwmapi.dll                       ← UE4SS proxy/injector
  ue4ss/UE4SS.dll                  ← UE4SS core
  ue4ss/Mods/TextTranslatorCpp/
    enabled.txt                    ← empty file = enabled
    dlls/main.dll                  ← this mod
    translation.csv                ← main table (see below)
    translation_extra.csv          ← optional manual overrides
```

## Translation data

The mod loads `translation.csv` and (optionally) `translation_extra.csv` from its
own mod folder. Both are read for two columns — **`source`** and **`translation`**;
any other columns are ignored, so the big CSV emitted by an extraction pipeline
works directly.

- `translation.csv` — bulk table. Must contain a header row with at least
  `source` and `translation` columns. Rows whose `translation` is empty are
  skipped (untranslated).
- `translation_extra.csv` — simple hand-maintained overrides, just:
  ```
  source,translation
  ウィンドウ,Windowed
  フルスクリーン,Fullscreen
  ```

Matching is exact first, then markup-stripped / unquoted / tag-aware fallbacks,
plus `{Placeholder}` format-pattern matching for parameterized strings.

## Console commands (need the UE4SS console enabled)

| command | effect |
|---|---|
| `ttcpp_reload` | reload both CSVs and re-sweep tables/templates |
| `ttcpp_sweep` | force a one-off object/property sweep |
| `ttcpp_flag <name> [0\|1]` | toggle/print a subsystem: `params`, `sweeps`, `registry`, `datatables`, `templates` |
| `ttcpp_debug_on` / `ttcpp_debug_off` | runtime text logging + miss collection |
| `ttcpp_dump_texts` / `ttcpp_clear_texts` | dump / clear collected runtime text |
| `ttcpp_dump_misses` | dump source strings seen but not translated (great for filling `translation_extra.csv`) |
| `ttcpp_combos` | dump combo-box (dropdown) option sets |
| `ttcpp_only` / `ttcpp_all` | restrict / unrestrict scanning scope |

## Porting checklist

1. Extract the game's text → produce a `translation.csv` with `source`,`translation`.
2. Build the DLL, deploy as above, add `enabled.txt`.
3. Launch with the console on; use `ttcpp_dump_misses` to find anything still
   in the source language and add it to `translation_extra.csv`.
