# Belphegor JP→EN translation pipeline

End-to-end machine-translation of **everything player-facing** in
*Daraku Senki: Belphegor Saga* (SRPG Studio) via the Anthropic Message Batches
API (Claude), reusing the proven `rpgmvtl` engine.

It covers all three text layers:

| layer | source | how |
|---|---|---|
| `project.dat` database + dialogue | `tooling/patch/*.json` (SRPG_Unpacker `-c`) | `tl.py` |
| hardcoded plugin/engine UI strings | `tooling/js_strings.json` (`js_text_tool.py`) | `tl.py` |
| baked-in image text | `tooling/translatedimages/` (your `typeset_*.py`) | separate |

`tl.py` translates the first two in **one batch** with a shared character
glossary + game prompt, then injects them back.

## Prerequisites

```powershell
pip install anthropic tiktoken
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```
You must already have, in `tooling/`:
- `patch/`           — `SRPG_Unpacker.exe <extracted>\project.dat -c -o tooling\patch`
- `js_strings.json`  — `python tooling\js_text_tool.py extract <extracted> -o tooling\js_strings.json`

(`<extracted>` = the folder you unpacked `data.dts` into.)

## Already built for you

The store is **pre-extracted** and the **glossary + game prompt are pre-built**:
- `tooling/tl/` — 11,776 translatable units (5.4k dialogue w/ speakers, 3.3k names,
  descriptions, UI, customParameters, 361 plugin strings) across 120 maps + global docs.
- `tooling/tl/glossary.json` — **167 characters** (gender/role/voice, hand-derived from
  reading the dialogue: 6 agents analyzed every speaker's lines) + **171 terms**.
- `tooling/tl/game_prompt.md` — setting, routes, tone, main-cast voices, terminology.

So you can go straight to `dryrun` / `run`. **Skim `glossary.json` first** to confirm
genders/spellings (a couple are deliberately `unknown`, e.g. the Chancellor Ben-Ami).

## Run it

```powershell
cd tooling
# (re-running `extract` is safe — it PRESERVES the glossary and any existing
#  translations; only needed if you regenerate patch/ or js_strings.json)
# python tl.py extract
python tl.py dryrun --show-sample    # scope + cost (~$9-12) + a sample prompt (no API call)
python tl.py run                     # names-first, then translate everything (polls to done)
python tl.py validate                # completeness / residual-JP / control-code checks
python tl.py retry                   # (optional) re-translate hard failures with scene context
python tl.py inject                  # write translations -> patch\*.json + js_strings.json
```

`run` is one-shot and resumable (Ctrl-C is safe → `python tl.py fetch`). If you
prefer manual control: `submit` → `status` → `fetch`.

## Assemble the translated game

After `inject`:

```powershell
# 1. apply the translated database/dialogue patch back into project.dat
SRPG_Unpacker.exe <extracted>\project.dat -a -o tooling\patch
# 2. apply the translated plugin/engine strings into the .js files
python tooling\js_text_tool.py apply <extracted> tooling\js_strings.json
# 3. repack the whole extracted folder into a new data.dts (BACK UP the original first!)
SRPG_Unpacker.exe <extracted> -o data.dts
```

> Note (from EXTRACTION_CHANGES.md): SRPG_Unpacker's `-a` apply step is the FINAL
> step for the patch — its output `project.dat` re-encodes strings and is not
> re-parseable by the tool (an inherent quirk, confirmed on the pristine tool).
> Keep a backup of the original `project.dat`/`data.dts`.

## What gets translated (and what is protected)

**Translated** (player-facing only):
- dialogue (`data`, with speakers), info windows, win/lose conditions, story pages
- database name + description (items, skills, weapons, classes, states, races, units…)
- UI command labels, titles, map names, rewards
- `customParameters` — only the quoted JP substrings (escort words, glossary
  conditions); the JS object structure is preserved
- plugin/engine UI strings from `js_strings.json`

**Never translated** (would break the game):
- control codes `\C[n] \v[n] \B \f` — masked to `⟦k⟧`, restored on inject
- speaker fields (ignored by `-a`; the name box comes from the unit name), event
  `comment` dev-notes, `fontName`
- plugin **asset filenames** (`*.png/.ogg`), **debug-log args**, and any string ever
  used as an **internal key / `=== 'id'` comparison / voice-trigger** — a global
  denylist skips these everywhere (verified: 0 leak into translation)

## The store (`tooling/tl/`)

- `glossary.json` — characters (name/gender/role/register/aliases) + terms. The
  single source of truth for name consistency. **Edit by hand** to lock spellings
  or fix an inferred gender; everything here flows into every request.
- `dlg_map_*.json` — per-map dialogue, scene-grouped, with speakers.
- `names.json` / `desc.json` / `ui.json` / `customparams.json` / `plugins.json` —
  deduped global buckets (one unit per unique JP string, injected to every
  occurrence).
- `game_prompt.md` — game setting / tone / character bible / terminology, cached
  on every request.

## Cost

`dryrun` reports it. For the full game (~11.8k unique segments, ~380k JP tokens)
with batch + prompt caching at `low` effort:
- **`claude-sonnet-4-6`** (the default): **≈ $6–7**
- **`claude-opus-4-8`** (`--model claude-opus-4-8`): ≈ $9–12 — more nuance

Use `--effort medium` for more reasoning (higher cost). `--retranslate-all` redoes
everything; otherwise re-runs only fill gaps.
