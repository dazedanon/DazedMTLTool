# rpgmvtl — RPG Maker MV/MZ batch translation tooling

Translates this RPG Maker **MZ** game (`data/*.json`) JP→EN using the
**Anthropic Message Batches API** (Claude). Built as a clean
extract → translate → inject pipeline.

```
data/*.json  ──extract──▶  tooling/tl/ (store + glossary)
                               │
                             run (Claude batch)  ← fills translations
                               │
tooling/out/data  ◀──inject──  tooling/tl/
```

> Configured for **サキュバス将軍の兵力増産所 / "Brood General Succubus"** (RPG Maker MZ).
> The engine default is `mz`: dialogue speakers come from each Show-Text (code 101)
> command's `parameters[4]` name box (this game uses **no** `\kw[]` windows). Paths
> default to `data/` (MZ layout); they auto-fall back to `www/data` for MV games.

## Quick start

```powershell
# 1. one-time: install deps + set your key
pip install anthropic tiktoken
$env:ANTHROPIC_API_KEY = "sk-ant-..."

# 2. pull translatable text out of the game
python tooling/tl.py extract

# 3. preview scope + cost (no API call)
python tooling/tl.py dryrun --show-sample

# 4. translate via Claude batch (submits, polls, writes results into the store)
python tooling/tl.py run

# 5. sanity-check the translations
python tooling/tl.py validate

# 6. write the translated data back out (drop-in replacement)
python tooling/tl.py inject
#    -> tooling/out/www/data  (copy over www/data, or use --in-place)
```

`run` is one-shot. If you'd rather drive it manually (or resume after a
Ctrl-C): `submit` → `status` → `fetch`. The store remembers the batch, so
`fetch` works any time after the batch ends.

## Commands

| command | what it does |
|---|---|
| `extract` | Scan `www/data`, build `tooling/tl/<File>.json` + `glossary.json`. Re-runnable; preserves existing translations by unit id. |
| `dryrun` | Token/cost estimate + a sample prompt. No API key needed. |
| `run` | Translate names first, then all text, polling to completion, writing results into the store. |
| `submit` / `status` / `fetch` | Manual three-step version of `run` (one combined batch). |
| `validate` | Completeness, residual-Japanese, identical-to-source, and control-code-integrity checks. |
| `inject` | Apply the store to a fresh copy of `www/data`. Idempotent. `--in-place` patches the game directly (after a timestamped backup). |
| `selftest` | Offline extract→fake-translate→validate. Proves the round-trip with no API. |

Useful flags: `--model`, `--max-units` (segments per request, default 80),
`--retranslate-all` (redo everything), `--width`/`--list-width` (wrap),
`--notes`, `--code-122`, `--code-356` (extract riskier content; off by default),
`--store`/`--data`/`--out` (paths).

## How it works (and how it improves on the DazedMTLTool reference)

* **Clean 3-stage separation.** Extraction, translation, and injection are
  independent and replayable. Injection always rebuilds from the *original*
  data, so it is **idempotent** — re-running never double-wraps or double-substitutes.
* **True batching with prompt caching.** One cached system block + one cached
  per-game glossary block are shared across every request (50% batch discount +
  cache reads). The reference issues many small synchronous calls.
* **Control codes can't break.** Inline codes (`\i[..] \c[..] \v[..] \ow[..]
  \r[a,b]`, pause codes, `%1`…) are masked to `⟦n⟧` placeholders before the
  model sees them and restored on inject. `validate` flags any unit whose
  placeholders changed.
* **Speaker-aware (MZ native name box).** In RPG Maker MZ the speaker is
  `parameters[4]` of each Show-Text (code 101) command. Extract reads it, seeds
  it into the glossary, and tags the dialogue with the speaker for context;
  inject rewrites `parameters[4]` through the glossary so the name box and prose
  always agree. (MV `\kw[name]` / `\nw[name]` / `【name】` windows are still
  parsed as a fallback for MV games.)
* **Names first.** `run` translates character names before the dialogue batch,
  so the glossary is populated when the dialogue prompts reference it.
* **Stable unit ids** mean you can re-extract after a game update and keep every
  translation you already have.

## The store format

`tooling/tl/<File>.json` holds `units`. Each unit is one translatable thing
with a JSON-pointer `ptr` into the source file, the masked source `src`, the
restore table `codes`, and `tl` (filled by `run`).

Character names live in `glossary.json` and are the single source of truth for
consistency. Each name is a rich entry so the model can resolve pronouns and
voice correctly:

```json
"names": {
  "アインアイク": {"en": "Einaike", "gender": "female", "role": "succubus general (protagonist)", "register": "dutiful, proud", "note": ""}
},
"terms": { "種付け": "breeding" }
```

`run` translates the names first (inferring gender), then injects the whole
glossary — names + genders + any `role`/`register`/`aliases` you add, plus
`terms` that appear in each chunk — into every request. **Edit `glossary.json`
by hand before/after the names pass** to lock in preferred spellings, fix an
inferred gender, or add speech-register notes; everything there flows straight
into the prompt. Seeded genders for this game are *guesses* — verify them.

The system prompt itself (in `batch.py`) carries the localization rules ported
from the reference: gender→pronoun resolution (incl. コイツ → "this
bastard/bitch"), honorific preservation, `=`/`＝` name handling, and explicit
adult-content register/onomatopoeia guidance, with few-shot examples.

### Per-game prompt (`tooling/tl/game_prompt.md`)

An optional `game_prompt.md` (or `.txt`) in the store dir is appended to the
default system prompt **as part of the cached prefix** (1h TTL, so async batch
requests still hit the cache). Use it for game-specific setting, tone,
per-character voice, and terminology/romanization rules. This game ships with
one already written (the breeding-facility premise; the Einaike/Furfur/Charon/
Vine/Moloch voices; the demon-race roster + general titles; the explicit,
non-consensual eroge register rules). `dryrun` reports whether it loaded.

## Notes / safety

* Defaults only touch clearly player-visible text (dialogue, choices, item/skill/
  enemy/class/state names + descriptions, system terms, map names). Scripts
  (355), plugin commands (356), control-variable strings (122) and comments
  (108) are **off** by default — enable per-flag if a specific game needs them.
* `inject` without `--in-place` writes a complete `data` copy to
  `tooling/out/data`; copy it over the game's `data` (back up first). With
  `--in-place` it backs up `data` to `data_backup_<timestamp>` first.
* This game is RPG Maker **MZ**; the engine default (`mz`) is set accordingly.
  Scripts (355 — heavily used here for stat logic), control-variable strings
  (122), MZ plugin commands (357) and comments (108) are **off** by default;
  enable per-flag only if a specific need appears (most player-facing text is in
  401 dialogue, 102 choices, and the database name/description fields).
