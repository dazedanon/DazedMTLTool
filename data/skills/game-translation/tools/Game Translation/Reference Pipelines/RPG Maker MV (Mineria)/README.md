# mvtl - 魔王ミネリアと名もなき村のエロトラップダンジョン

*Demon Lord Mineria and the Nameless Village's Ero Trap Dungeon* -
RPG Maker **MV**, 18+, trial build v1.0, circle さざめき通り.

Extract -> translate (Claude batch or live) -> validate -> inject -> ship.

```
www/data/*.json  ──extract──▶  tl/units/*.json  +  tl/glossary.json
                                     │
                                run  (Claude Message Batches, 50% off)
                                     │
out/www/data     ◀──inject───  tl/units/*.json
www/js/plugins.js ◀─in place──  tl/plugins_js.json
```

The game folder is **volatile**: everything durable lives here, and every path
into the game is resolved from `mvtl/config.py`. Point it somewhere else with
`--game` or `MINERIA_GAME_ROOT`.

---

## Status

**Translated.** Sonnet 5, live + 1h cache, 68 requests, zero errors, zero parse
failures, 100% cache hit rate. Billed **$1.15** against a **$1.14** estimate.

| | |
|---|---|
| Units | **2,866** - 100% translated |
| Residual Japanese in player-facing text | **0** |
| Broken control codes / placeholders / overflows | **0** |
| Leaked sentinels in the injected output | **0** |
| Structural verify | **PASS** - 9,144 command lists, 40,677 commands, 0 differences |
| plugins.js | 29 UI leaves + 3 measured layout overrides, applied in place |
| Title image | done |
| Release archive | `out/release/patch`, 47 files, denylist clean |

Still to do, and neither can be automated: **read `out/ui_review.txt`**, and
**play it** against `docs/PLAYTEST.md`.

---

## Run it

```powershell
# 0. one-time
pip install anthropic tiktoken pillow fonttools lzstring scipy
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # or: ant auth login

# 1. look before you spend
python tl.py census                       # what is in the game data
python tl.py dryrun --show-sample         # scope, cost, a real prompt. No API call.
python tl.py smoke                        # ONE request on a median chunk. Cents.
python tl.py selftest                     # offline round trip. No API, no writes.
python tl.py noop                         # an empty store must inject byte-identically

# 2. translate
python tl.py run                          # names, then everything, via batch
#   or, for a small remainder or a stalled queue, 2x the price and minutes not hours:
python tl.py live

# 3. check
python tl.py validate                     # completeness / codes / overflow
python tl.py retry                        # re-translate everything that failed
python tl.py tighten                      # re-request only what overflows its box, with its budget
python tl.py polish --apply               # one repeated line, one English rendering

# 4. ship
python tl.py inject                       # -> out/www/data
python tl.py verify                       # PROVE no saved index moved
python tl.py scan                         # grep the INJECTED files
python tl.py ui -o out/ui_review.txt      # READ THIS FILE
python tl.py mock -o out/mock.png         # composite the message box, real font
python tl.py plugins apply                # in-place UI labels + layout overrides
python images/title.py                    # the title logo
python tl.py release -o out/release

# 5. after release
python tools/translate_save.py --apply    # make existing JP saves load
python tools/tag_evidence.py              # release tags, from the corpus
python tools/forum_post.py --dry-run      # then --apply to fill ForumPostGen
```

`run` is one-shot. To drive it by hand, or to resume after Ctrl-C:
`submit` -> `status` -> `fetch`. The store remembers the batch id, so `fetch`
works any time after the batch ends, and results stay on the server for 29 days -
a parse failure is fixable and re-fetchable with **no re-billing**.

**`request_counts` is not a progress bar.** A run can read
`processing=68, succeeded=0` for its whole life while the usage page shows the
tokens already spent. Never cancel a stalled-*looking* batch and re-run it live
without checking usage first: you would pay twice.

---

## What is here

```
tl.py                  the CLI
mvtl/
  config.py            every per-game ruling, with the evidence in the comment
  codes.py             JP detection, portrait split, sentinel mask/restore
  measure.py           widths from the game's OWN font, not a width table
  wrap.py              balanced-line DP; width and rows as simultaneous limits
  store.py             the unit store and the glossary
  fileio.py            read/write a data file in its own serialization
  extract.py           four phases, different files, different code profiles
  inject.py            idempotent, rebuilds from pristine, never changes a command count
  prompts.py           base rules + the cached roster + per-kind instructions
  requests.py          chunking and request construction - SHARED by both drivers
  parse.py             the two model-JSON failure modes, both recoverable
  validate.py          what blocks injection, and what only asks for a look
  client.py            credentials and billed-token accounting
  driver.py            batch and live, one builder, one parser, one apply path
  estimate.py          scope and cost before spending anything
  plugins_js.py        the in-place plugins.js track + the menu-help mirror
  qa.py                UI dump, injected-output scan, message-box mock
tl/
  glossary.json        THE CONTRACT - characters, terms, do-not-translate
  game_prompt.md       the game bible (premise, the two-register rule, cast)
  quirks.md            cross-cutting voice: onomatopoeia, slurring, hearts
  plugins_js.json      the plugin UI ledger
  units/*.json         one doc per source file
tools/
  seed_stock_ui.py     RPG Maker's own English for its own strings. No API call.
  trace_parser.py      what the ENGINE does to a translated string
  translate_save.py    make an existing Japanese save load on the patch
  build_release.py     a build for players, not for you
  tag_evidence.py      release tags from the CORPUS, in both languages
  forum_post.py        fill ForumPostGen's autosave from what is already known
images/
  probe_title.py       measure before touching a pixel
  title.py             the one image with baked text
tests/
  test_codes.py        the cases that are real failures someone hit
  test_requests.py     the request set is well formed BEFORE a run pays for it
tools/verify_structure.py  proof that the patch cannot move a saved index
docs/CENSUS.md         the evidence behind every ruling above
docs/PLAYTEST.md       the five-item matrix and the release checklist
```

---

## Decisions worth knowing before you change something

**The command count never changes.** A save stores an *index* into the event
command list, so tombstoning the absorbed 401s of a run - the usual RPG Maker
write-back - moves every later index and resumes existing saves at the wrong
line. The wrapped English is redistributed across exactly the commands the run
already had. Runs are 1-4 long and the window holds 4 rows, so this always fits.

**Two tracks, never mixed.** `data/*.json` flows store -> export -> game.
`js/plugins.js` is edited **in place** in the game folder. Mixing them means an
export silently reverts an in-place edit.

**Speaker attribution refuses to guess.** There is no name box and no face
graphic in this game. A line with a portrait code is Mineria; a line without one
gets an empty speaker rather than inheriting from an earlier 101 - which is how
lines get attributed to the wrong character after a conditional branch. The one
exception (trap-encounter common events) is proved over the corpus in
`docs/CENSUS.md`, not assumed.

**Stock UI strings are seeded, not translated.** All 96 System.json strings are
RPG Maker's own published English and are marked `locked`, so no pass touches
them. A model asked to translate `最強装備` in isolation produces "The Strongest
Equipment Set", which is correct and wrong.

**`LL_MenuScreenCustomMV.menuHelpTexts[].symbol` must equal the English in
`System.json terms.commands`.** The plugin keys its help table on the displayed
command name. `tl.py plugins check` proves it; `tl.py plugins mirror` fixes it.

**Widen the widget before you compress the English.** The map HUD gauge drops
its `/max` readout when the label no longer fits, silently. `gaugeA.width` went
195 -> 250 and `gaugeB.x` 235 -> 290 rather than shortening "Lewdness" to fit.
Where a bound is *not* a parameter - the menu status window is a hardcoded
240px - the label is abbreviated on the **widget only** (`Lewd Cap`), and prose
keeps the full term (`Lewdness Cap`). That is a decision, recorded in the
glossary, not drift.

**`\Helen` is invisible, not wrong.** MV lexes an escape as `\` plus a *run* of
letters, so a backslash the model invents swallows the following word. Every
text-level check passes it. `bare-escape-eats-word` is a hard failure, and
`tools/trace_parser.py` demonstrates the mechanism against the shipped engine
rather than against a copy of it.

**A plugin popup argument must survive `split(" ")`.** `command356` splits on
ASCII space only, so one space in the text field truncates the popup to its
first word. Spaces are converted to U+00A0 on inject; the shipped font has NBSP
at half width, so it renders as an ordinary space.

---

## The two things automation cannot do

**Read `out/ui_review.txt`.** A few hundred lines, minutes to skim, and it is
the only pass that catches a short verb rendered as the wrong part of speech.
`訂正する` ("go back and re-enter") came back as **"Correct"** on another game,
which reads as agreement and sends the player the opposite way. It is English,
it is short, it has no placeholders and no residual Japanese - every automated
check passes it.

**Play it.** `docs/PLAYTEST.md` has the five-item matrix to run after *every*
export, and the reason the recollection room does not count.
