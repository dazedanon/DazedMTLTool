# NTR Soccer — English Translation Toolkit + BepInEx Mod

Game: **NTR Soccer** (Hizure, Unity 2022.3.62 **Mono**, BepInEx 5.4.23.5)
Toolkit modeled on `FortuneBride1.12/tooling` (Mistral pipeline) and
`Projects/SheepClickerTL` (BepInEx dictionary mod).

## TL;DR — it's installed and ready to test

Just launch `NTR_Soccer.exe`. The mod is already built and installed at
`BepInEx/plugins/NTRSoccerEnglish/` and verified to load
(`BepInEx/LogOutput.log` shows 12 hooks + 2,595 dictionary entries).

## The big discovery

The developer shipped a **complete official English localization inside the
game**: the Pixel Crushers Dialogue Database stores English in its base
`Dialogue Text`/`Name` fields with `ja`/`zh`/`zh-tw`/`ko` as localization
variants, and the UI TextTable has an English `Default` column. Every scene
just hard-locks the Dialogue System to `language: ja` (and the choice is
persisted in `PlayerPrefs["Language"]`).

Verified text coverage (nothing else in the game contains Japanese — checked
all 13,117 exported assets, scenes, prefabs, decompiled C# and PlayMaker FSM
binary data):

| Source | JP strings | Official EN |
|---|---|---|
| Dialogue Database (20 conversations, 2,689 entries) | 2,527 | 2,527 |
| Dialogue Database actors (33) | 32 | 32 |
| UI Localization Text Table (228 fields) | ~60 unique | all but 5 |
| **Total unique JP** | **2,595** | **2,590** |

The 5 gaps (情報/希/連絡先/シャツ/スカート) were translated with
`mistral-medium-latest` and validated (no JP output, placeholders preserved).

## The mod — `BepInEx/plugins/NTRSoccerEnglish/`

Two independent layers (both configurable in
`BepInEx/config/com.sw.ntrsoccer.english.cfg`, generated on first run):

1. **ForceEnglishLanguage** (default on) — Harmony prefixes on
   `DialogueSystemController.SetLanguage`, `UILocalizationManager.set_currentLanguage`,
   `Localization.set_language` and `TextTable.set_currentLanguageID` rewrite
   every language to `""` / ID 0 (base = official English), and the saved
   `PlayerPrefs["Language"]` is cleared.
   This alone translates all dialogue, names, response menus and UI.
   For TextTable fields with a blank Default, Pixel Crushers falls back to
   the field name — which is also English ("Info", "Contacts", ...).
2. **EnableTextHook** (default on) — SheepClickerTL-style dictionary hook on
   `TMP_Text.text` / `TMP_Text.SetText` / `UI.Text.text` setters plus
   Awake/OnEnable passes, loaded with all 2,595 JP→EN pairs from
   `translations/translations_final.json`. Handles exact, newline-normalized,
   `{0}`-format-pattern and concatenation-composed matches. Any Japanese
   string that still gets through is logged once to
   `BepInEx/plugins/NTRSoccerEnglish/untranslated.txt` — check that file
   after playing; anything in it can be added to the dictionary JSON.

Other config options: `EnableAutoSize` (shrink-to-fit text, off by default),
`VerboseLogging`, `FallbackContainsReplace`.

## Folder layout

```
tools/
  README.md                  <- this file
  extracted/                 <- ALL player-facing text, organized
    dialogue.csv/.json       every dialogue entry (conv, entry, actor, ja, en)
    actors.csv/.json         actor names ja/en
    ui_texttable.csv/.json   UI table fields (ja/en/zh/ko)
    jp_all_strings.txt       every unique JP string, one per line
    jp_to_en.json            JP -> official EN map
    needs_translation.json   JP strings that had no official EN (input to Mistral)
    extract_report.txt       integrity summary
  translated/
    translations_final.json  merged JP->EN dictionary (official + Mistral) = what the mod ships
    mistral_state.json       resumable Mistral state
    mistral_report.txt       validation report
  tl/
    game_prompt.md           translation bible (premise, tone, markup rules)
    glossary.json            locked names (from the dev's own EN) + terms
    mistral_keys.txt         API keys, one per line — do NOT distribute this file
                             (or set env MISTRAL_API_KEYS=key1,key2 instead)
  scripts/
    extract_text.py          AssetRipper YAML -> extracted/*
    mistral_translate.py     Mistral driver (see below)
  mod/NTRSoccerEnglish/      mod source (Plugin, LanguagePatches, TextPatches,
                             TranslationStore) + build.ps1
  logs/recon/                exploration reports of the game + prior tooling
```

## Pipeline commands (re-runnable)

```powershell
cd "C:\Users\sw\Desktop\Games\NTR Soccer\tools"
python scripts\extract_text.py                 # re-extract from AssetRipper export
python scripts\mistral_translate.py run        # translate whatever lacks official EN
python scripts\mistral_translate.py run --all  # force-retranslate EVERYTHING via Mistral
python scripts\mistral_translate.py status
python scripts\mistral_translate.py merge      # rebuild translations_final.json
.\mod\NTRSoccerEnglish\build.ps1               # rebuild + reinstall dll & dictionary
```

Mistral notes (measured live 2026-07-02 via response headers): each of the two
free-tier keys gets `x-ratelimit-limit-req-minute: 50` and
`x-ratelimit-limit-tokens-minute: 25000`; the script runs one worker pool per
key, paces itself off the live `x-ratelimit-remaining-*` headers, honors
`Retry-After` on 429, retries 5xx/network with capped exponential backoff,
streams results to `mistral_state.json` after every batch (atomic writes —
rerun `run` to resume from wherever it stopped), rejects any output containing
Japanese or with mismatched placeholders (`[pic=N]`, `<color=...>`, `{0}`,
`\n`), and auto-repairs rejects in per-item retry rounds.

## Removal

Delete `BepInEx/plugins/NTRSoccerEnglish/`. (To get Japanese back in-game,
also let the game re-save its language or set `ForceEnglishLanguage = false`
first and pick ja in the game if it exposes a picker.)
