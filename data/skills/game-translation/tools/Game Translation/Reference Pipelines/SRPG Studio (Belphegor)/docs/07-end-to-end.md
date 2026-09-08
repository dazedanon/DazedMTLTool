# Full translation walkthrough — start to finish, and distribution

This is the runnable end-to-end recipe: take a fresh Japanese **Belphegor** install and produce a shipped **full-loose** English translation. "Full loose" means the published `game.exe` is binary-patched to read loose override files (the `Project\` JSON tree, loose `Fonts\`, loose `Script\`/`Plugin\` `.js`, loose `Graphics\` `.srk`) on top of the **original Japanese `data.dts`** — so the final translator edits plain files and sees the change on the next launch, with **no repack and no recompile**. There is **no `translation.bin`** (deleted; the exe reads the folder directly — see `memory/translation-folder.md` and Patch 5b in `memory/exe-patches.md`).

All paths below are written relative to the game root `C:\Users\sw\Desktop\Games\Belphegor\` and the kit at `FullLooseKit\`. The pipeline driver `tl.py` ships in the kit at `FullLooseKit\tools\tl.py`; it drives the `srpgtl` package (the modules shipped as `FullLooseKit\tools\srpgtl\`) and needs an Anthropic API key for the batch-translation steps.

> The data/text pipeline (`extract -> run -> inject`) is the same engine whether you are building a packed `data_EN.dts` or the loose `Project\` tree. The **difference for full-loose** is the final assembly: you do **not** repack `data.dts`; you emit a `Project\` folder, ship loose `.js`/`.srk`/font, and patch the stock exe. The packed-`data.dts` path (`memory/deploy-checklist.md`) is the *legacy/patcher* path; this section is the loose path.

---

## Prerequisites

```powershell
pip install anthropic tiktoken
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

You also need, beside the exe-patcher, two committed binaries (both already in `FullLooseKit\tools\loosekit\`): `probe.bin` (the hand-assembled JP→EN lookup that runs on every database string) and `load_table.bin` (the compiled runtime folder reader). And the unpacker: `FullLooseKit\tools\SRPG_Unpacker\SRPG_Unpacker.exe` (`v0.1.2`; `--help` lists `-c` create-patch, `-a` apply-patch, `-o` output, `--repack-srk`).

Keep an untouched copy of the original `data.dts` (the shipped `data.dts` stays Japanese forever) and of the stock exe (`game.exe.orig.bak`, SHA-256 `afd79d5b…`, asserted by `patch_exe.py`).

---

## Step 1 — Unpack `project.dat` (the database) into the editable tree

`data.dts`'s tail is the `ProjectSection` = the whole database (all names, descriptions, dialogue, events). First get the plaintext `project.dat`, then create the per-file JSON patch tree the text pipeline reads.

```powershell
# data.dts -> extracted\  (gives Graphics\, Script\, Plugin\, and project.dat)
FullLooseKit\tools\SRPG_Unpacker\SRPG_Unpacker.exe data.dts -o extracted

# project.dat -> the native JSON tree (items.json, Maps\map_000.json, Base\…, ~250 files)
FullLooseKit\tools\SRPG_Unpacker\SRPG_Unpacker.exe extracted\project.dat -c -o tooling\patch
```

**Produces:** `tooling\patch\*.json` — the canonical SRPG database tree. This is the same shape the final `Project\` folder will have. Also keep a pristine JP `project.dat` for Step 5 (the kit expects it at `tooling\_jpbase\project.dat`; confirmed present in this install).

> **Gotcha:** `-a` (apply-patch) is the *terminal* step for a patch — its output `project.dat` re-encodes strings and is **not** re-parseable by `-c` again (`docs/reference/EXTRACTION_CHANGES.md`). Always re-`-c` from a pristine JP `project.dat`, never from an apply output.

---

## Step 2 — Extract plugin/engine JS strings (the second text layer)

A lot of player-facing text is hardcoded in `.js` literals (`StringTable`, `EC_DefineString`), unreachable by the `project.dat` patch. Extract it to a sidecar JSON.

```powershell
python FullLooseKit\tools\jstools\js_text_tool.py extract extracted -o tooling\js_strings.json
```

**Produces:** `tooling\js_strings.json` — one entry per Japanese literal (`{id, line, context, preview, original, translation:""}`), keyed by literal index, comments skipped, asset/ID strings left for you to leave blank. **682 strings across 21 files** in this game; biggest are `Plugin\02 俺オリジナル\文字変更.js` (226, the active `StringTable` override) and `Script\constants\constants-stringtable.js` (215). See `docs/reference/JS_TRANSLATION.md`.

> **Gotcha:** entries in `各種ボイス.js` and similar are **internal voice-trigger IDs**, not UI — translating them breaks the game. The pipeline's denylist (`extract.py` `plugin_blacklist` / `_internal_ctx`) auto-skips any string ever used as an asset filename, `=== 'id'` comparison, voice key, or debug-log arg, even if the same text is a display label elsewhere.

---

## Step 3 — Build the store, translate (LLM), inject

The pipeline (`tooling\tl.py` → `srpgtl`) translates the `project.dat` tree **and** `js_strings.json` together in one batch with a shared character glossary, via the Anthropic Message Batches API.

```powershell
cd tooling
python tl.py extract                  # patch\ + js_strings.json -> tl\ store + glossary
# >>> EDIT tl\glossary.json BY HAND: verify character genders/roles/spellings <<<
python tl.py dryrun --show-sample     # scope + cost + a sample prompt, no API call
python tl.py run                      # names-first, then everything; polls to done (resumable)
python tl.py validate                 # completeness / residual-JP / control-code checks
python tl.py retry                    # (optional) re-translate hard failures with scene context
python tl.py inject                   # store -> translated patch\*.json + js_strings.json
```

- **`extract`** writes `tooling\tl\` (per-map `dlg_*.json` dialogue with speakers; deduped `names.json`/`desc.json`/`ui.json`/`info_misc.json`/`customparams.json`/`plugins.json`; `glossary.json`). Re-running it is safe — it **preserves** existing translations and the glossary.
- **`run`** is one-shot and Ctrl-C-safe (resume with `python tl.py fetch`); manual control is `submit` → `status` → `fetch`. Cost (`dryrun` reports it): ~$6–7 on `claude-sonnet-4-6` default, ~$9–12 on `--model claude-opus-4-8`.
- **`inject`** (`inject.py`) does the load-bearing work: restores masked control codes (`\C[n]`, `\v[n]`, `\B`, `\f` → `⟦k⟧` and back), applies the **max-fill reflow** (`_reflow` — every line fills to width before breaking, kills orphan tail-words; see `memory/text-wrap-max-fill.md`), page-aligns dialogue to the 3-line message box (`_page_align`, keeps `【Name】` speaker headers atop their page), packs InfoWindow briefings (`_page_pack`), wraps the narrow shop greeting cluster `info_misc:1056–1157` at 32 cells, and substitutes glossary names everywhere. Default message width is 54 cells; dictionary pages wrap at 44.

**Produces:** translated `tooling\patch\*.json` (in place) and a filled `tooling\js_strings.json`.

> **Gotchas:** (a) `inject` is idempotent — it rebuilds substitutions from the original JP every time, so re-running never double-translates. (b) `speaker`/`comment`/`fontName` are never translated; speaker name boxes come from the **unit-name** entries via the glossary. (c) Keep the `【Name】` headers in multi-speaker H-scene text — dropping them merges speakers into one box (`memory/hscene-speaker-headers.md`).

---

## Step 4 — Translate images (loose `.srk`)

Baked-in image text (title logo, status/class/growth/skill labels) is translated as PNGs, overlaid into the unpacked `Graphics\`, then **re-encoded per-file to loose `.srk`** so each ships individually.

```powershell
# typeset the translated PNGs (per category)
python FullLooseKit\tools\imagetools\typeset_title.py     # ... and typeset_status/class/growth/skill/meter/misc.py
python FullLooseKit\tools\imagetools\inject_images.py     # translatedimages\*.png -> extracted\Graphics\**\<same-basename>.png

# re-encode the modified Graphics back to loose .srk (NOT a new data.dts)
FullLooseKit\tools\SRPG_Unpacker\SRPG_Unpacker.exe extracted -o tooling\data_EN.dts --repack-srk
```

`--repack-srk` writes the loose `Graphics\*.srk` next to its output. The game loads **loose `..\Graphics\*.srk` over `data.dts`** per file, so you ship only the changed `.srk` (`memory/image-deploy-loose-srk.md`).

> **Gotcha:** `inject_images.py` matches by **basename** and refuses ambiguous/dimension-mismatched slots — a translated PNG must be the exact pixel size of the slot it replaces, or it's skipped (`--dry-run` reports matches first).

---

## Step 5 — Build the `Project\` tree (`make_folder.py --store`)

This is the **full-loose** payload that replaces a packed `data_EN.dts`. `make_folder.py` unpacks the **pristine JP** `project.dat` and writes the native JSON tree with every translatable Japanese string wrapped `{"jp":"…","en":"…"}` — and `--store` fills the `en` side **through the same `inject` reflow** as Step 3, so dialogue in the folder matches what the data path would have shown.

As shipped, `make_folder.py` computes `ROOT = HERE\..\..` = the `FullLooseKit` folder, so `--out` defaults to `FullLooseKit\Project` and `--project` defaults to `FullLooseKit\tooling\_jpbase\project.dat` (which does **not** exist in the kit). A bare command therefore does **not** drop `Project\` at a game root — pass explicit paths:

```powershell
python FullLooseKit\tools\loosekit\make_folder.py --project <game>\tooling\_jpbase\project.dat --out <game>\Project --store <game>\tooling\tl
```

**Produces:** the `Project\` tree at the `--out` path (`items.json`, `Maps\map_000.json`, …, ~250 files), e.g.:

```json
"name": {"jp": "ベルフェゴール", "en": "Belphegor"},
"desc": {"jp": "王家の証　…", "en": "Royal Proof — Survive once per stage with 1 HP"}
```

Only Japanese-containing strings are wrapped; `speaker`/`comment`/`fontName` stay plain (speaker names translate via the unit-name entries). A **blank `en` (or any string absent from the folder) passes through to the original JP `data.dts`** — so a fresh folder shows pure Japanese and fills in as you translate.

> **Gotchas:** (a) **Always use `--store tooling\tl`, not `--en <old folder>`** — `--en` copies the raw translator wraps (orphan tail-words); `--store` runs `inject` so you get the max-fill reflow + page-align + glossary names (`memory/translation-folder.md`). (b) `make_folder.py` auto-discovers the unpacker (`_find_unpacker()`), preferring the kit's `tools/SRPG_Unpacker/SRPG_Unpacker.exe`; pass `--unpacked <dir>` only if you unpacked elsewhere. (c) Pass the pristine JP DB explicitly as `--project <game>\tooling\_jpbase\project.dat` (the kit ships no default project.dat) — and confirm it's the *original* JP DB, not an apply output.

---

## Step 6 — Place the loose plugins (UTF-16LE) and Graphics

The edited `.js` (translated in Steps 2–3 and hand-tuned) ship loose under the game-root `Script\` and `Plugin\`, **keeping their subfolders** (`Script\constants\…`, `Plugin\02 俺オリジナル\文字変更.js`) — Patch 2's cave reads subfolder-relative archive paths, so the loose tree must mirror the archive layout. The pre-edited set lives in `FullLooseKit\assets\plugins\Script\` and `…\Plugin\`.

**CRITICAL encoding gotcha:** every loose `.js` MUST be **UTF-16LE with a `FF FE` BOM**. The engine's loose reader (`sub_4749B0`) decodes a non-UTF-16 file via the ANSI codepage (CP1252), not UTF-8 — so a UTF-8 file mojibakes every non-ASCII char (`—` → `â€"`) and a UTF-8 BOM throws `ParseScriptText "property 'ï»¿' is null"` at boot. Verified: the shipped `Plugin\02 俺オリジナル\文字変更.js` starts `ff fe …`. Convert each edited `.js` `utf-8-sig` → `\xff\xfe` + `utf-16-le` before placing it loose (see Patch 2 in `memory/exe-patches.md`).

Copy the changed loose `Graphics\*.srk` from Step 4 to the game-root `Graphics\` (only the ones you changed).

---

## Step 7 — Patch the stock `game.exe` (one pass)

`patch_exe.py` turns an **unmodified v1.23** exe into the full loose build, verifying every site and embedding `probe.bin` + `load_table.bin`.

```powershell
python FullLooseKit\tools\loosekit\patch_exe.py game.exe.orig.bak -o game.exe
```

It applies (each site asserted against the known stock bytes, else it refuses):

| Patch | What it does |
|---|---|
| **P1** | never force-quit on a momentarily-missing resource (`ResourceErrorNotify` flag forced 0 at file `0x38D86`) |
| **P2** | load loose `Script\`/`Plugin\` `.js` over the `data.dts` copies — **per-entry REPLACE** (additive would double-run the alias/wrapper plugins → gameplay bugs). Cave at VA `0x4A8620`, trampoline `0x456223` |
| **P3** | load a loose `project.dat` over the one in `data.dts` (new `.mod` section, VA `0x557000`; dormant — the live build ships none, latent capability only) |
| **P5b** | read the editable `Project\` JSON tree at runtime, FNV-hash JP→EN, translate every DB string at parse time — **no `translation.bin`, no build step**. Hook at `0x474167` → probe in the RWX `.mtl` section; loader walks `<gamedir>\Project` |
| **P6** | load a loose `Fonts\<name>.ttf` over the embedded (broken) M+ 2m font (cave VA `0x5581B8`; also neutralizes a stale base-reloc at RVA `0x227B`) |
| **P7** | OS window caption read live from `Project\titles.json` (`windowTitle` en → jp → engine original); hook at `0x438967` → title cave in `.mtl`. Nothing baked in |
| **P8** | apply `Project\fonts.json` `fontSize` edits onto the parsed FONTDATA records at font-init (the one non-string field; hook at `0x40218C` → cave in `.mtl`) — live from the folder, no loose `project.dat` |

**Produces:** the patched `game.exe` (this worked example's `game.exe.full`). `data.dts` is untouched — the loose files do all the translating.

> **Gotcha:** the input must be the **stock** exe (SHA `afd79d5b…`); `patch_exe.py` warns on a different hash and still verifies each patch site, but feeding it an already-patched exe will fail the byte asserts. Build from `game.exe.orig.bak`, never re-patch.

---

## Step 8 — Assemble and verify the loose distribution

Place everything at the game root and launch:

```powershell
# Translate and Play.bat  — no build step; just starts game.exe
.\"Translate and Play.bat"
```

To verify the **edit-relaunch promise**: open any `Project\*.json`, change an `en` value, relaunch — the new text is in memory next launch (no rebuild). A blank `en` shows the JP from `data.dts`.

---

## Distribution manifest — exactly what the player gets

Ship a zip with the **patched `game.exe` loose at the zip root** (the player copies it into their game folder; Windows prompts to replace). Do **not** route the exe through any patcher's extra-files channel and never ship `game.ini` (would reset keybinds/fullscreen). The full payload over a stock JP install:

| Item | Path (game root) | Notes |
|---|---|---|
| Patched exe | `game.exe` | at the **zip root**; P1+P2+P3+P5b+P6+P7+P8 |
| **Original JP database** | `data.dts` | **unchanged Japanese** — byte-identical to the JP original (`570,546,646` bytes here). The loose files translate it at runtime |
| Loose translation tree | `Project\` | native `project.dat` JSON tree, `{"jp","en"}` wrapped; blank `en` = stays JP |
| Loose font | `Fonts\M+ 2m.ttf` | overrides the embedded broken font (P6) |
| Loose scripts | `Script\…` (subfolders) | edited engine UI strings, **UTF-16LE + BOM** |
| Loose plugins | `Plugin\…` (subfolders) | edited plugin UI / `StringTable`, **UTF-16LE + BOM** |
| Loose images | `Graphics\…\*.srk` | only the changed `.srk` (P-per-file override) |
| Launcher | `Translate and Play.bat` | optional convenience; plain `game.exe` works |

**No `translation.bin`** anywhere (confirmed absent in this install) — Patch 5b reads the `Project\` folder directly. **No `data_EN.dts`** in the player payload; that file is an internal build artifact of Step 4 only (its purpose is to spit out the loose `.srk`).

### The promise
> Edit a `Project\*.json` `en` value (or a loose `.js`, or a `Graphics\*.srk`), relaunch, and it shows — **no repack, no recompile.** Translation is plain-file editing over an untouched Japanese `data.dts`.

### Deploy discipline
The legacy *packed* path in `memory/deploy-checklist.md` (regenerate a pristine-JP patch → `inject` → `-a` → repack `data_EN.dts` → refresh the bsdiff patcher) is **not** the full-loose path. For full-loose, "done" means all of: the `Project\` tree rebuilt with `--store` (Step 5), the changed loose `.js` re-converted to UTF-16LE (Step 6), the changed `.srk` re-copied (Steps 4/6), and — only if you changed a patch site — the exe rebuilt from stock (Step 7). The exe and `data.dts` rarely change; a typical text fix is a single `Project\` edit that the player sees on next launch.
