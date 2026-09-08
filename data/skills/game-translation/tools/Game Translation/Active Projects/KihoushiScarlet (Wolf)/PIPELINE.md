# 騎紅士スカーレット (Crimson Knight Scarlet) - JP→EN pipeline

Wolf RPG Editor, ver 1.03, by シコリーター三世. R18 RPG, ~1-2 h.
Translation via **Claude Sonnet 5** on the **Message Batches API**.

## State of the corpus

| | |
|---|---|
| Engine | Wolf RPG Editor (`Data.wolf` 961 MB, already unpacked to a loose `Data/`) |
| Text units | **74,289** across 93 files |
| Distinct `(kind, source)` | **7,680** - a **9.67×** dedup |
| Source characters | 4.24 M total, 289 k distinct |
| Nameplate speakers | 167, all locked in the glossary with a gender. Protagonist スカーレット holds 44,772 units (60%) |
| Biggest file | `MapData/Map027.mps` - 49,357 units, only 3,712 distinct |
| Control codes | 86 distinct, 224,799 occurrences, masked to `{Wn}` sentinels |
| Held out | **none**. The holdout was cleared and the 1,081 units restored - see *Scope* below |
| Status | **SHIPPED** - 73,623 / 73,623 shipped units English (100%), 0 Japanese |
| Actual bill | **$31.02** over 6 batches. $30.45 of it was the first two, before the caching bug was found; the whole remainder cost $0.57 |

`Map027` is the H-scene map and is where the dedup comes from: the single most
repeated unit is an onomatopoeia line that occurs **640 times**.

## Layout

```
pristine/          the untranslated BasicData + MapData, copied out of the game
                   folder. NOTHING here is ever written. This is the baseline the
                   inject rebases against and the restore path.
out/*.json         wolf strings-extract per file + names.json (the glossary track)
batch.json         wolf mt-export --sentinel-mask - the single translation store
tl/glossary.json   locked characters / terms / do-not-translate
tl/game_prompt.md  the game bible, pasted into every request
tl/locks.json      line ids whose text was hand-authored (fanout leaves them alone)
tl/holdout.json    units deliberately NOT sent to the API, with the reason
tl/_sources/       the glossary's inputs; edit these, never the generated files
tl/_batch_state.json   resume state for the in-flight Message Batch
digest/            corpus digests the glossary was built from
build/DataEN/      the injected English tree
build/build-stamp.json  what DataEN was built from; deploy refuses a stale tree
scripts/claude_translate.py   the Sonnet 5 batch driver
scripts/build.py              import -> inject -> font -> relayout -> verify -> deploy
scripts/qa.py                 the passes no validator replaces
scripts/make_glossary.py      deterministic glossary merge + audit
scripts/make_digests.py       rebuild digest/ and stamp it against batch.json
scripts/remap_sentinels.py    repair {Wn} numbering after a re-export
docs/ui-term-notes.md         the UI glossary's rulings, overflow risks, open questions
```

**Never depend on anything under `Desktop\Games\`** - that folder is a working copy
and gets deleted. `pristine/` is the copy that survives.

## Run it

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-..."
cd "C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\KihoushiScarlet (Wolf)"

python scripts\make_digests.py check                      # digest/ matches batch.json?
python scripts\make_glossary.py build                     # glossary.json + game_prompt.md
python scripts\make_glossary.py audit                     # must print AUDIT OK
python scripts\claude_translate.py dryrun --show-sample   # cost preview, no spend
python scripts\claude_translate.py selftest               # offline wiring proof, no API
python scripts\claude_translate.py dryrun --exact         # calibrate against count_tokens
python scripts\claude_translate.py run                    # names phase, then text phase
python scripts\claude_translate.py validate
python scripts\claude_translate.py retry
python scripts\claude_translate.py batches usage          # the REAL bill, once

python scripts\build.py all                               # import→inject→font→relayout→verify
python scripts\build.py deploy                            # mirror into the game folder
# ... play it ...
python scripts\build.py restore                           # put the Japanese back

python scripts\qa.py ui-pairs      > logs\ui-pairs.txt      # READ THIS BY EYE
python scripts\qa.py nameplates                            # speaker box intact?
python scripts\qa.py parallel-drift                        # 男A / 男B drifted apart?
python scripts\qa.py glued                                 # "Nerois that alright?"
python scripts\qa.py speaker-voice > logs\speaker-voice.txt
```

`run` is resumable: Ctrl-C is safe, `fetch` picks the results back up, and the
resume ladder means a second `run` only bills what is genuinely still pending.

## Result

Deployed into the game folder. A generic walk of the DEPLOYED data - re-extracting
every `.dat` / `.project` / `.mps` and classifying each unit, not re-running the
extractor that produced the batch - reports:

```
units in the shipped tree  : 73,623
English                    : 73,623   (100%)
Japanese                   :      0
```

Gates at ship time: `strings-inject` **73,624 applied, 0 guard-skipped, 0 drifted**;
`names-inject` **1,432 renames, 0 drifted/unmatched**; `verify-roundtrip` **93 ok,
0 diff, 0 error**; `verify-semantic` **no new danglers vs baseline**; `font-check`
**0 of 966 glyphs missing**; `validate` **74,289/74,289 translated, 0 residual
Japanese, 0 broken sentinels, 0 broken page breaks, 0 disagreeing dedup groups, 42
soft warnings**; `qa parallel-drift` **0 diverged**; the greedy-lexer sweep
**0 collisions**.

Still to do before calling it a release: play it (the five-item matrix below), read
`logs/ui-pairs.txt` by eye, and ship a save-compatibility pass.

## Scope: the holdout was cleared - the corpus is complete

An earlier revision kept 1,081 units (1.45%) off the automated path: the speakers
**【ガキ】** (924 lines), **【ガキ共】** (144), **【下町のガキ】** (7), **【不良ガキ】** (3),
**【不良キッズ】** (2), and the enemy row **中1**. Those units were translated in the
final batch, and the holdout has since been **cleared**:

* `tl/holdout.json` is empty.
* The `FLOOR_SPEAKERS` constant in `claude_translate.py`, which re-injected those five
  speakers into the holdout on every load regardless of the file, is **gone**.
  `tl/holdout.json` is now the only source of held-out units, and an empty file means
  the whole corpus is on the automated path.
* The 1,081 translations were restored from `build/batch-before-holdout-restore.bak`,
  which is the same store with those lines still filled. `build/batch-before-holdout-clear.bak`
  is the state immediately before that restore.

`validate` now reports 74,289 / 74,289 with no held-out line. The holdout machinery
(`speakers` / `db_names` / `line_ids` in `tl/holdout.json`) still works if anything
needs excluding again - it is declared, not silent: `dryrun`, `run`, `validate` and
`selftest` each print the held-out count and keep those units out of the pass/fail
gate rather than counting them as done.

The same reasoning is why `tl/game_prompt.md` §0 carries a routing note instead of
the sexual-register and moan-rendering sections the rest of the bible would
otherwise have had. Everything else in it - names, terms, the 【】 convention,
control codes, layout, comedic register, honorifics, and a full **non-sexual**
onomatopoeia system - is present and is the majority of the useful surface.

## The six decisions this pipeline makes, and why

### 1. Dedup on `(kind, source)`, fanned out by OVERWRITE

74,289 units, 7,680 distinct. One representative per group is billed; `fanout`
copies its translation onto every sibling.

The fanout **overwrites** rather than filling blanks. Filling only empty siblings
looks right on the first pass and is silently useless on every pass after it: on a
`retry`, every sibling already carries the text that failed, so the representative
gets repaired and the rest keep the defect. Hand edits are protected by listing
their line id in `tl/locks.json`, not by the fanout being timid.

The risk dedup exists to avoid is one source spoken by two different characters
getting one pronoun. Here the speaker is **inside the source** (`【スカーレット】\n「…」`),
so grouping on the source already groups on the speaker. `--no-dedupe` is one flag away.

### 2. Sentinel masking, not textual instructions

`mt-export --sentinel-mask` replaced all 86 control codes and every positional
whitespace run with backslash-free `{Wn}` tokens *before* the model ever sees them.
This is not belt-and-braces: the **JSON transport**, not the model, is what corrupts
codes. `\f` decodes to a form feed, `\r` to a carriage return, and `\cself` is an
*invalid* JSON escape that kills the whole request's parse and takes 60 good
translations with it. Sentinels contain no backslash, so that failure mode is
physically impossible. Verified: 0 sources carry a backslash except two literal
`Data\` paths, which are in `do_not_translate`.

The guard therefore counts **sentinels**, and additionally counts blank-line page
breaks - several textboxes are packed into one string separated by `\n\n`, and a
model that collapses one destroys pagination beyond any relayout's power to recover.

### 3. Prompt caching is OFF, and that is a measured decision

This is the one the first run got wrong, so it is written down with the bill attached.

The reasoning that looked right: the system prompt is byte-identical across every
request, so put the whole glossary behind a 1 h cache breakpoint and pay **one** cache
write plus N-1 reads at a tenth of the input rate. Estimated $3.79 against $10.21
uncached.

What the 192-request text batch actually billed:

| | tokens | cost |
|---|---:|---:|
| cache_write | 6,238,116 | **$24.95** |
| cache_read | 5,320,746 | $1.06 |
| input | 440,463 | $0.44 |
| output | 287,398 | $1.44 |
| | | **$27.89** |

The 56,911-token prefix was **written 110 times and read 93**. Message Batch requests
are processed in **parallel**, so most of them start before any cache entry exists.
A cache write costs 2x base input, which is 4x the batch input rate, so caching a
large prefix under batch parallelism is *worse than not caching at all*: the identical
run with no `cache_control` would have been **$12.80**, and with the term glossary
chunk-filtered rather than resident it is around **$4**.

So: `--cache off` is the default, the term glossary is filtered per chunk again, and
the dryrun cost model applies a measured **0.57 write fraction** instead of assuming
one write. Re-scored against the real bill it now predicts $27.64 against $27.89.

Caching still pays for interactive or serial traffic, where the first request genuinely
warms the prefix for the rest. `--cache 1h` re-enables it.

**The general lesson, which the skill already warned about and this run paid for
anyway: check the estimate against the bill ONCE, early.** The output estimate was
fine (287 k against 331 k predicted). The input model was wrong by 6x, and nothing
in the run's own output would have said so - only `batches usage` did.

### 4. `claude-sonnet-5`, no sampling params, thinking off

Sonnet 5 **rejects `temperature`/`top_p`/`top_k` with a 400**, so none are sent;
depth is `output_config.effort`, defaulting to `low` because translation is direct
high-volume work. `thinking` is explicitly `disabled` for the same reason -
`--thinking adaptive` and `--effort medium` are the quality knobs if a read-through
says the output needs them.

Caching: the **whole** system prompt - instructions, the 17.5 k-char game bible, and
the complete 167-name / 1,231-term glossary - is byte-identical across all 204
requests and sits before the cache breakpoint with a **1 h TTL**, because batch
requests are processed minutes apart and a 5-minute TTL would miss most of them.

The predecessor pipeline filtered the term glossary per chunk to keep the *dynamic*
block small. Measured here that was the wrong trade: chunk-filtering 1,231 terms
still matched most chunks and produced **2.03 M** dynamic input tokens across the
run, where sending everything once behind the breakpoint costs one 40 k cache write
plus 203 reads at a tenth of the input rate. It is cheaper (**$3.79 vs $10.21**) and
the model sees the complete glossary on every request instead of a slice.

### 5. Names first, then text

Phase 1 translates the 662 database names alone. Phase 2 feeds those translations
back in as extra glossary terms, so a skill name embedded in a usage message matches
the skill name in the menu. The engine looks DB rows up **by name**, so two Japanese
names collapsing to one English string is a runtime break, not a style nit -
`names-check` is run before injecting for exactly that.

### 6. Font: `MSゴシック` → `ＭＳ ゴシック`

`Game.dat` asks for the halfwidth `MSゴシック`. GDI's `CreateFontW` matches on the
face name only and **silently falls back to Arial**: 43 of 54 probed glyphs missing,
every ★ ♡ ・ and every kanji a box, with no error anywhere. The fullwidth form is the
real face name, ships on every Windows, and probes **0 of 1692 missing** across this
game's whole corpus. `build.py font` makes the change and `wolf font-check` proves it.

This was the first thing checked, before any extraction, because it is the single
biggest false lead in a Wolf translation.

## What is already verified

- **Binary round-trip.** A no-op inject (empty translations) reproduces all 227
  files **byte for byte** against `pristine/`. Extract → inject is lossless.
- **Pseudo-localization.** `wolf pseudo` pushed deterministic gibberish through the
  real pipeline: 75,121 applied, **0 skipped, 0 drifted**, in `build/Data-pseudo`.
  Run the game off that tree for 5 minutes to break things on throwaway text.
- **Selftest.** `claude_translate.py selftest` builds every request, fake-fills them,
  fans out, and validates - **74,289 filled = 74,289** now that the holdout is
  cleared (it was 73,208 filled + 1,081 held out), 0 index-map errors,
  0 sentinel/JP/pagebreak failures. It calls the same `build_all` / `apply_results` /
  `fanout` / `hard_issues` that decide what ships - a suite that only exercised the
  primitives would certify its own bugs.
- **The whole build chain runs.** `inject → font → relayout → verify` was exercised
  end to end on the untranslated tree: `verify-roundtrip` **93 ok, 0 diff, 0 error**;
  `verify-semantic` **no new danglers vs baseline**; the residual sweep reports
  **73,622 of 73,627 units still Japanese**, which is the correct answer for an
  untranslated build and is the proof the sweep can *fire*. A scan that reports
  nothing has to show it could have reported something - absence of evidence and a
  broken reader look identical, and only one of them is loud.
- **The QA checks fire too.** Run against the fake-filled selftest batch,
  `qa.py nameplates` finds all 167 speakers with the 【 】 shape intact,
  `parallel-drift` finds 7,534 parallel groups with 1 divergence, and
  `speaker-voice` samples every speaker. `glued` was **re-scoped after measuring its
  own noise**: over all 86 sentinels it returned **59,249** hits, nearly all colour
  spans and icons that must stay flush. Reading the legend and firing only on the
  **64** tokens that are `\cself` / `\cdb` / `\udb` / `\v` value inserts takes it to
  **142**. A list nobody reads is not a check. The same classification is fed to the
  model, so it knows which `{Wn}` to put a space around and which to leave tight.
- **The soft-warning checks were re-scoped against their own false-positive rate.**
  On the finished corpus they opened at **1,413** flags, which is a list nobody
  reads. Three of them were measuring the wrong string:
  * *misgender* scanned the whole source for a glossary name, so it matched the
    **nameplate**. The female protagonist heads 60% of the corpus and talks about a
    male partner throughout, so "'スカーレット' is female but tl uses he/him" fired on
    1,133 correct lines. Looking for the name in the **body** only - a speaker naming
    themself says nothing about who a third-person pronoun refers to - takes it to 26.
  * *male noun addressed to 'you'* scanned the translated nameplate too, so
    **【Milking Man】**, **【Wank Guy】** and **【Lewd Gentleman】** flagged themselves.
    Scanning `_body_of(tl)` takes 91 to 13.
  * *glued insert* fired on all 86 sentinels rather than the 64 value-inserting ones,
    so it reported `\c[]` colour spans and `\i[126]` icons that must stay flush -
    the same re-scoping `qa.py glued` already had.

  Result: **1,413 -> 42**, and all 42 print in one screen and were read. They are
  false positives (`バカ` and `紳士` are glossary "names" matching inside
  `バカデカチチ女` and `俺は紳士だから`; the three CHOICE commas sit in separate string
  args, which Wolf does not split on). The one real class the pass found was six map
  and enemy names still carrying a fullwidth `・` separator - `Goblin Den・2` - now
  ` - ` and locked in `tl/locks.json`.
- **The glossary audit passes.** `make_glossary.py audit`: **0** English collisions
  between database row names, **0** dead entries, **0** of 167 nameplate speakers
  unlocked, **0** names without a gender, **0** denylist entries drawn as a
  player-facing unit. The 9 remaining collisions are display-only labels the author
  spelled two ways for one person (`受付お姉さん` / `受付のお姉さん`), which is the
  correct merge, so they are reported and do not fail the gate.
- **Box geometry: 76 cells × 4 rows, CENSUSED rather than maxed.** `--width auto`
  returned **88** and put English off the right edge of the screen. The max is the
  wrong statistic, because the author overflows his own box. Counting *distinct*
  source strings per line width over 85,501 JP message lines - sentinels expanded,
  so a hand-paginated line is measured as the two lines it draws as:

  | cells | 66 | 68 | 70 | 72 | 74 | 76 | 78 | 80 | 86 |
  |---|---|---|---|---|---|---|---|---|---|
  | lines | 360 | 330 | 162 | 522 | 46 | 133 | 12 | 1 | 12 |
  | **distinct** | 37 | 30 | 32 | 15 | 10 | **4** | 1 | 1 | 1 |

  a smooth decay to 76 and then a cliff: past it the whole corpus holds **three**
  distinct strings, each repeated, each shipped clipped in the Japanese original.
  Reading *lines* instead of *distinct* is what hides this - the 9.7x dedup means 15
  distinct strings account for all 522 at 72. Nothing is drawn smaller (the legend
  carries no `\f[N]` at all), so no widget can legitimately hold 86.

  `BOX_CELLS = "76"` in `build.py`; `--max-rows` and the insert budget stay `auto`
  (4 rows, `sub-width 35`). Cost of the change: continuation boxes **+4 -> +16**.
  Verified by re-extracting the built tree and stripping codes with the pipeline's
  own `WOLF_CODE_RE`: **max 85 cells, 5 lines over 76 of 97,561 (0.005%)**, and all
  5 are in a CommonEvent panel `relayout` does not own. `--width-face` is the same
  76 (this game does not narrow for a face). It also auto-detected the bare
  speaker-line convention - **184 recurring speakers head 94% of messages** - and
  keeps those first lines as name headers, repeated on page splits, instead of
  reflowing the nameplate into the body. Description boxes measured per type:
  `DataBase` 0→62×2, 2→73×3, 3→42×2, 4→62×3, 6→44×1, 20→62×2;
  `CDataBase` 28→37×2, 30→39×2, 32→16×1.
- **`names-check`** on the fresh extract: no name conflicts across 93 files;
  13 whitespace-positioned lines and 2 multi-textbox entries, both classes already
  covered (sentinel masking and the pagebreak guard respectively).
- **Font**, as above.
- **Rename safety.** `names.json` reports `dynamic_lookups: 0` - the game builds no
  lookup name at runtime, so every rename is statically provable. Of 662 names, 628
  are `safe` (display only), 34 are `refs` (looked up by name, but `names-inject`
  renames the references in the same pass), and **0 are `verify`**. 576 engine
  registry entries were auto-excluded as editor labels. `verify-semantic` checked
  6,818 by-name Database operands and found **2 pre-existing danglers in the shipped
  Japanese** - those are baselined in `build/semantic-baseline.txt`, so only a NEW
  dangler fails. The absolute list is always a superset: index-mode ops carry their
  name as a dead annotation, and stock JP games ship mismatches.

  `names-inject` output is a **matched set**. It renames the DB row, the stored row
  name, and every by-name operand together. Copying one file out of a later inject
  generation over an earlier one splits the set and the game dies with
  `【DB操作】タイプN には以下のデータ名は存在しません`. `build.py inject` always
  rebuilds the whole tree from `pristine/` for that reason.
- **DB triage: nothing to configure.** The three databases hold only 594 units across
  18 sheets - 418 in the engine's standard sheets, 176 in this game's own (`評判`,
  `評判ジョブアクション`, `ワープポイント設定`, `職業設定`), and **no narrative sheet
  at all**. `wolf roles` classifies 216 string fields (61 name / 60 content / 95
  internal) with zero overrides needed, so no `wolfdawn-roles.json` is required. This
  is a `classic_rpg` archetype: 73,695 event units against 594 database units. The
  story lives in events, which is why `Map027` alone is two thirds of the game.
- **`field-names-detect`: 0 sites.** No event in this game draws a database *field
  name* via `Database(dataID=-3)`, so the whole "untranslatable-by-the-tools, unsafe
  to rename in schema" class does not apply here. Worth knowing, because the fix for
  it is event-side surgery.

### Wrap quality: widows, fragment continuations, and the orphan closing quote

Three defects reported from screenshots, all of them in `wolf relayout` itself
(`crates/wolf-decompiler/src/relayout.rs`), all fixed there rather than worked around.
Measured on the built tree, before → after:

| | before | after |
|---|---:|---:|
| widow rows | 2,964 | **300** |
| single-word widows | 1,984 | **0** |
| messages ending in a ≤12-cell row | 2,493 | 97 |
| boxes closing a quote they never opened | 225 | **0** |
| max row width / rows over 76 | 85 / 5 | 85 / 5 (unchanged) |

**1. Widows.** `wrap_row` was a plain greedy fill, so a row that overflowed by one
word put that word alone on the next line. It is now greedy-THEN-balanced: greedy
still decides the line COUNT, then a DP re-breaks the same words into exactly that
many lines minimising the sum of squared unused cells **including the last line**.
Charging the last line is the whole trick - with a free tail the optimum IS the
greedy widow. Pinning k to greedy's count is what keeps the blast radius at zero:
`min_fit_width`, the names-wrap ladder and `relayout_description` all read
`wrap_row(..).len()`, and none of them can move. It declines and returns greedy byte
for byte on ten guards (any greedy row already over width, `<C>`/`<R>`, empty token,
no widow to fix, DP infeasible, a produced row that would read as a deliberate row,
still-widowed result...).

**2. Fragment continuation boxes.** The deliberate-row path chunked rows blindly
(`rows.chunks(budget)`), so a continuation box got whatever spilled - `other problems
too."` alone. `pack_blocks` now fills pages with WHOLE blocks, and an oversized prose
block routes through `prose_pages` (sentence packing) instead of straight to
`text_pages`. `split_sentences` also had to learn to see past a closing quote: it
required the ender to be followed immediately by whitespace, so in a corpus that is
almost entirely quoted dialogue **no** sentence was a boundary and the sentence-aware
pager could never fire.

**3. The orphan closing quote.** A split left box 1 opening a quote it never closed
and box 2 closing one it never opened. `balance_split_quotes` re-opens it on the
continuation, and closes the box before it **only where the break lands on a sentence
end** - the English rule for a quotation that runs past a break is that every new
paragraph of the same speaker RE-OPENS while the closing mark waits for the end of the
speech, so the missing closer is the signal that the same person is still talking.
Closing regardless produced `...for drinking water,"` - punctuation asserting the
speech stopped where it plainly had not. Audited over every split seam in the game:
**4 sentence-end seams close, 132 mid-sentence seams stay open, 0 close
mid-sentence, 0 orphan closers** (one message falls back to the legacy layout and
keeps its authored quoting). The mark is added only where it FITS and only if the page
still re-normalises to the same row count. That second condition was learned the hard way:
appending the quote to a row changes the run's merged text, the box stops re-reading
as itself, and the fixed-point ladder then dropped the whole message through
**unwrapped** - one 113-cell row shipped before the width sweep caught it.

Also fixed while here: `role_overrides_take_precedence` and
`registry_skip_defaults_and_overrides` in `strings.rs` both drive PROCESS-GLOBAL role
overrides and cargo runs tests in parallel threads, so one test's reset to the
defaults could land inside the other's assertions. They now share a mutex - the clash
was on the RESET, not on the labels the tests had already made unique.

**Idempotency is checked, not argued.** `relayout_wscript` re-lays every emitted box
exactly as the next run reads it and only writes a layout whose every box comes back
unchanged; the ladder is balanced → legacy → leave as authored. It also closed a
PRE-EXISTING hole: the continuation state-code prefix was emitted in front of a
leading `　` pad, so `\c[2]　text` stopped satisfying `deliberate_row` on the next
pass. Proven on the real tree - a second and third relayout pass both change **0
messages in 0 files**. 123 Rust tests, was 108.

*Note the interaction with `deindent`:* running `relayout` again on the DEPLOYED tree
does reflow, because `deindent` strips the 　 markers after relayout has used them.
That is not instability - `build.py` always rebuilds from `pristine/`.

### The pad was doing TWO jobs, and removing it broke the other one

Stripping the 　 pads from the store fixed the indent and then produced a *second*
screenshot: a message the author had broken into three rows of 26/42/42 cells came
back as one 76-cell line running under the standing portrait that scene draws.

`wolf relayout`'s `deliberate_row()` is `blank || code-only || starts_with('　')`.
That pad is the author's **"this break is mine, keep it"** marker. A message with one
has each row wrapped on its own; a message without one has **every row merged and
refilled to the full box width**. Removing the pads upstream silently converted
26,281 units from "keep the author's layout" to "reflow as free prose".

Worse, the marker was already being lost on most of the corpus before any of this:
the model rendered the same pad two ways, **8,315 lines kept 　 and 20,118 folded it
to an ASCII space**, and only the fullwidth one is a marker. Over two thirds of the
author's own breaks were being discarded from the first build onward.

So the pad is now **restored** on the way in and **stripped on the way out**:

* `restore_row_markers()` (in `apply_results` and `repair`) re-fullwidths the pad
  wherever the source's line at the same index carries one - copy-from-source, never
  invention. 18,542 units repaired; **0** lines needed a pad the model had dropped
  entirely, and the 292 units whose line count no longer matches the source are left
  alone because there is nothing to align.
* `build.py deindent` takes it back out of the BUILT tree after relayout has consumed
  it - 29,777 lines in 54 files - through `strings-inject`, the same guarded path as
  the translation itself. The edit only ever makes a line narrower, so it cannot
  violate a width or row budget. A block whose FIRST line is indented is a column
  skeleton (the `[]` status card) and keeps its pads; ASCII-only runs are left
  alone, because they are not relayout's marker.

This is the general rule the first attempt broke: **layout repair is a pass over the
injected output, never a mutation of the store the injector reads.** The store keeps
the author's markers; the built tree is what the player sees.

Effect: relayout now reflows **22,072** messages instead of 43,363 (it is honouring
the author's rows again) at +239 continuation boxes, and the built tree measures
**max 85 cells, 5 lines over 76 of 108,364**, all 5 in a CommonEvent panel relayout
does not own.

**Open, and needs one screenshot to settle:** English still runs wider than the
Japanese *inside* each preserved row - over the messages whose extract still aligns
1:1, **39% have a widest row ≥ JP+10 cells and 12% ≥ JP+20**. On a scene with no
portrait that is free; on a portrait scene the author's own row width is the only
portrait-aware budget there is, since the bust is a `Picture` command (`Picture/kao*.png`,
66 files use one) that relayout cannot see. If a portrait screen still clashes, the
fix is a per-message envelope capped at the author's widest row for that message,
which needs `wolf relayout` to take a per-message width.

### The stray indent on line 2 - a defect a screenshot found and no check did

A player screenshot of 【女A】 on Map008 showed the second line of the box starting
with a blank gap. Japanese aligns a quoted continuation line under the opening
「 with one IDEOGRAPHIC SPACE; English opens with a halfwidth `"`, so the pad
becomes a **two-cell indent under a half-cell mark**. Every automated check passed
it: English, no residual Japanese, no placeholder drift, inside the box.

It was not one line. A census over the store found **8,433 shipped lines** in the
class, and the model had rendered the same pad two ways - **8,340** kept the
fullwidth 　 and **20,860** folded it to an ASCII space. `relayout` hid the second
half by trimming the pad off any message it happened to reflow, so the defect
survived *exactly on the lines that already fitted* - which is why it reads as
random.

`drop_quote_indent(src, tl)` removes it, in `apply_results` (so a new translation
never carries it) and in `repair` (which cleared the store: **7,752 + 18,531**
units). It asks the SOURCE rather than guessing, because a leading space is not
always a pad:

* a block whose FIRST line is itself indented is a column skeleton, not dialogue -
  the `\v[]` status card, `" [Scarlet]\n \s[4]"`, `"\n Left x \cself[11]"` - and is
  left alone entirely;
* a halfwidth pad is stripped only where the source's line at the same index
  carries exactly one 　.

Two lines resisted, both on the reported screen. The author had hand-paginated
them with `{W63}` - a masked pad expanding to eleven 　, a newline, and one more
　: pad out the rest of the line, break it, indent the next one. `relayout`
discards the padding half and keeps the break and the indent. Since that token is
**pure Japanese-metric pagination** and English repaginates from scratch, it is
droppable markup for the same reason ruby is, so `pagination_pads()` now keeps any
whitespace sentinel *containing a newline* out of the must-preserve multiset, and
the two lines were rewritten with a plain break and locked. A whitespace pad with
**no** newline stays protected - it may be centring a label.

Result, measured by re-extracting the built tree rather than re-reading the store:
**8,433 indented lines -> 19**, all in `CommonEvent.dat`, and none of them dialogue -
6 Wolf base-system error messages that only appear when the base system is
misconfigured, and 4 layout skeletons that must keep their pads. The check stays
behind as a soft warning, so a re-translated line cannot bring the pad back
silently.

### Bugs this setup caught before any spend

**Colliding `custom_id`s dropped the title screen.** `sanitize_id()` folds every
non-ASCII character to `-`, so `map_タイトル` and `map_メイン街` both produced
`map_----`. Keyed on that, one file's `id_maps` entry overwrote the other's and
`スタート` / `コンティニュー` / `ゲーム終了` - the first three strings a player ever
reads - were silently missing from the batch. custom_ids are now globally sequenced
and uniqueness is asserted. The selftest's `filled / total` line is what surfaced it.

**The sentinel numbering moved under the glossary.** `mt-export --sentinel-mask`
numbers tokens in the order it meets them, so the numbering belongs to the *file
list*, not the game. Re-exporting with `out/names.json` included changed the meaning
of **50 of 86** tokens: `{W49}` went from `\i[126]` (an icon, never padded) to
`\cself[34]` (a value insert, which English must space around). The glossary had
already been written against the old numbering, and nothing fails loudly when that
happens - keys stop matching, and any key that still matches teaches the model the
wrong thing. Fixed by `remap_sentinels.py`, which remaps by the CODE rather than the
number (545 occurrences renumbered), and prevented by `make_digests.py check`, which
stamps the legend hash and refuses a stale digest.

**The corpus is not LF-only.** 64,108 units use bare LF but 109 use CRLF, almost all
database descriptions. `\n{2,}` therefore saw only **2 of the 4** page breaks,
because `\r\n\r\n` puts a `\r` between the newlines. The guard now matches
`(?:\r?\n){2,}`, `apply_results` restores the source's CRLF when the model answers in
LF and the repair is unambiguous, and 88 glossary keys were re-pointed at the
corpus's CRLF form - before that they were present, plausible, and never once applied.

**The denylist was blinding the residual-Japanese check.** The term reader put
asset-registry row names on `do_not_translate`, and several are ordinary words:
`射精`, `絶頂`, `正解`, `回復`, `カメラ`, `ピストン`. `hard_issues` stripped every
denylisted term before scanning, so those words would have been invisible across
**2,643 prose units** while every counter stayed green. A denylist is scoped to a
POSITION, not to a string; here the position is "the whole unit is this key", and the
audit now reports the 23 entries that also occur inside prose so the scoping is visible.

**An author typo the patch would have been blamed for.** `いつもムラムラしてるi[126]`
carries a raw `i[126]` - the developer dropped the backslash, so the engine never
lexes it as an icon code and the player reads the literal text. It ships that way in
the Japanese original. It survives byte for byte in the English.


## Still to do

1. **Fill `tl/glossary.json` and `tl/game_prompt.md`** - the glossary workflow writes
   both. `dryrun` prints `game prompt: *** MISSING ***` until then; do not spend
   money before it is loaded.
2. **Run the translation**, then `validate` → `retry` until hard issues are 0.
3. ~~**Measure the box width in-game.**~~ **Done** - `--width auto` was measuring the
   author's own overflow, not the box. Pinned to `BOX_CELLS = 76` in `build.py`; see
   *Box geometry* above for the census that fixes the number and the re-extraction
   that proves it. The Latin-half-a-cell model turned out to be fine; the max was
   the problem.
4. **Read every UI label as `JP → EN` side by side.** A few hundred lines. This is the
   only pass that catches a short verb rendered as the wrong part of speech - English,
   short, no placeholders, no residual Japanese, every automated check green, and it
   sends the player the wrong way.
5. **Playtest after every export**, not once at the end: launch, load a save, open
   *every* menu (database text renders only there), walk the changed maps, save and
   reload. Never sign off a scene from a gallery/recollection room.
6. **Save compatibility.** Wolf bakes strings including the title into saves;
   `wolf save-update` rewrites them. Do this before the first public release.
7. **Exe strings are a separate, opt-in track.** A handful of gamepad button labels
   (`ボタン1..15`), a few menu strings and Config.exe's dialog live as UTF-16LE in
   `Game.exe` / `Config.exe`, not in game data. A naive scan is worthless here - it
   returns 122,586 "Japanese" strings from `Game.exe`, nearly all of them the Wolf
   engine's own editor text plus CJK-looking mojibake from reading UTF-16 at the
   wrong byte parity (`潃扭湩剥湧` is `CombineRgn`). Use WolfDawn Studio's **Exe Text**
   section, which pre-fills the known set and byte-patches same-length English in
   place with a `.wolfdawn-bak` backup. Not wired into this pipeline.
8. **Images are out of scope** unless asked for by name. A prior session already did
   title/overlay art in `images/`; that is a separate track and is not wired into
   this patch's payload.

## Delivery

The engine reads a loose `Data/` folder **before** `Data.wolf`, and this game already
ships unpacked, so `build.py deploy` mirrors `build/DataEN/{BasicData,MapData}` straight
over the game's. It **mirrors** - it deletes the destination subtree before copying -
because copying never deletes, and a payload file dropped from the source otherwise
survives in the game folder and keeps being loaded while every gate stays green.

`build.py restore` puts `pristine/` back.
