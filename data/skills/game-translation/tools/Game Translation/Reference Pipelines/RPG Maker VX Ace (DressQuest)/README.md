# acetl - Dress Quest (RPG Maker VX Ace)

*Dress Quest ~エリスと七つのドレス~*, circle ぽいずん, v1.13, 18+.
Extract -> translate (Claude Sonnet 5, batch or live) -> validate -> inject.

```
Data/*.rvdata2  ──extract──▶  tl/units/*.json  +  tl/glossary.json
   (Ruby Marshal)                    │
                              run  (Message Batches, 50% off)
                                     │
out/Data/*.rvdata2  ◀──inject──  tl/units/*.json
Data/Scripts.rvdata2 ◀─in place─  tl/scripts_rb.json
```

The game folder is volatile. Everything durable lives here, and every path into
the game is resolved from `acetl/config.py` (`--game`, or
`DRESSQUEST_GAME_ROOT`).

---

## Status

**Translated.** Claude Sonnet 5, Message Batches + 1h cache, 411 requests,
zero failed requests, zero parse failures.

| | |
|---|---|
| Units | **14,750 - 100% translated** |
| Residual Japanese in player-facing text | **0** |
| Broken control codes / placeholders / overflows | **0** |
| Leaked sentinels in the injected output | **0** |
| Strings byte-identical to the source in the output | **0** |
| Speaker name plates | 225/225 |
| Structural verify | **PASS** - 7,712 command lists, 133,423 commands, 0 differences, 22,871 strings changed |
| Marshal round trip | 231/231 files byte-identical |
| No-op inject | PASS - an empty store injects byte-identically |
| RGSS3 script strings | 51 Vocab literals, applied in place, read back and verified |
| Repeated lines unified | 460 clusters (1,316 units); 139 left for a human |
| Cross-track conflicts | 6, all deliberate (map pins shorten, stat windows abbreviate) |
| Tests | 72, all passing |
| Billed | **$8.36** total - $8.16 the text batch, $0.03 names, $0.04 smoke, $0.13 retries and tighten |

Still to do, and neither can be automated: **read `out/ui_review.txt`**, and
**play it** against `docs/PLAYTEST.md`.

### The bill came in at $8.16 against a $3.58 estimate. Here is why.

The estimate assumed a perfect cache: one write of the shared prefix, 410
reads. The run measured **2,492,100 cache-write tokens against 1,114,425
reads - a 30.9% hit rate**, and cache writes at the 1h multiplier (2x base
input) were $4.98 of the $8.16.

The cause is not a broken prefix. It was byte-stable, as designed. It is that
**the Batch API starts its requests concurrently**, so nearly all 411 arrived
before any of them had finished writing the cache. The arithmetic that matters:

    a 1h cache write costs 2.00x base input, a read costs 0.10x
    (1 - f) * 2.00 + f * 0.10 < 1.00   ->   f > 53%

At 31% the caching cost **$1.49 more than sending the same tokens uncached**.

Two fixes are in the code now. `driver.submit` sends ONE request live before
creating the batch, at about two cents, so the prefix exists and the other 410
read it; and `tl.py dryrun` prints the cold-cache number beside the optimistic
one instead of quoting only the happy path. For a small run, the 5m TTL (1.25x
write, break-even at 22%) is the safer choice.

The input estimate itself was sound - the error was entirely in the cache
model, and the output ratio came in at **1.15**, below the 1.38 the contract
assumes.

---

## Run it

```powershell
# 0. one-time
pip install anthropic tiktoken pillow fonttools
$env:ANTHROPIC_API_KEY = "sk-ant-..."     # or: ant auth login

# 1. look before you spend
python tl.py census                       # what is in the game data
python tl.py extract                      # Data/*.rvdata2 -> tl/units/
python tools/seed_stock_ui.py --apply     # RPG Maker's own English. No API call.
python tools/seed_glossary.py             # the names we are certain about
python tl.py dryrun --show-sample         # scope, cost, a real prompt. No API call.
python tl.py selftest                     # offline round trip. No API, no writes.
python tl.py noop                         # an empty store must inject byte-identically
python tl.py smoke                        # ONE request on a median chunk. Cents.

# 2. translate
python tl.py run                          # names first, then everything, via batch
#   or, for a small remainder or a stalled queue - 2x the price, minutes not hours:
python tl.py live

# 3. check
python tl.py validate                     # completeness / codes / overflow
python tl.py retry                        # re-translate everything that failed
python tl.py tighten                      # re-request only what overflows, with its budget
python tl.py polish --apply               # one repeated line, one English rendering

# 4. ship
python tl.py inject                       # -> out/Data
python tl.py verify                       # PROVE no saved index moved
python tl.py scan                         # grep the INJECTED .rvdata2 files
python tl.py ui                           # -> out/ui_review.txt. READ THIS FILE.
python tl.py mock -o out/mock.png         # composite the message box
python tl.py scripts apply                # the in-place UI strings
python tl.py release -o out/release

# 5. after release
python tools/translate_save.py --apply    # make existing Japanese saves load
```

`run` is one-shot. To drive it by hand or resume after Ctrl-C:
`submit` -> `status` -> `fetch`. The store remembers the batch id, results stay
on the server for 29 days, and a parse failure is fixable and re-fetchable with
**no re-billing**.

**`request_counts` is not a progress bar.** A run can read
`processing=412, succeeded=0` for its whole life while the usage page shows the
tokens already spent. Never cancel a stalled-*looking* batch and re-run it live
without checking usage first: you would pay twice.

---

## What is here

```
tl.py                  the CLI
acetl/
  rvmarshal.py         Ruby Marshal 4.8 reader/writer, byte-exact
  rvdata.py            pointers into the Marshal tree; event lists
  config.py            every per-game ruling, with the count in the comment
  codes.py             JP detection, the \NAME[] tag, sentinel mask/restore
  measure.py           width in half-width cells, not guessed pixels
  wrap.py              balanced-line DP; width and rows as simultaneous limits
  store.py             the unit store and the glossary
  extract.py           two phases, different files, different code profiles
  inject.py            idempotent, rebuilds from pristine, never changes a command count
  prompts.py           base rules + the cached roster + per-kind instructions
  requests.py          chunking and request construction - SHARED by both drivers
  parse.py             the two model-JSON failure modes, both recoverable
  validate.py          what blocks injection, and what only asks for a look
  client.py            credentials and billed-token accounting
  driver.py            batch and live, one builder, one parser, one apply path
  estimate.py          scope and cost before spending anything
  scripts_rb.py        the in-place RGSS3 script track
  qa.py                UI dump, injected-output scan, message-box mock
tl/
  glossary.json        THE CONTRACT - 224 names, 28 terms, do-not-translate
  game_prompt.md       the game bible (premise, the two-register rule, cast)
  quirks.md            cross-cutting voice: onomatopoeia, 「」, hearts, censor marks
  scripts_rb.json      the RGSS3 literal ledger
  units/*.json         one doc per source file
tools/
  seed_stock_ui.py     RPG Maker's own English for its own strings. No API call.
  seed_glossary.py     the names a human should decide, not the model
  verify_structure.py  proof that the patch cannot move a saved index
  translate_save.py    make an existing Japanese save load, in English
  build_release.py     a build for players, not for you
  patch_scripts_code.py anchored CODE patches to Scripts.rvdata2
  check_scripts_syntax.py  `ruby -c` over every script section
tests/                 72 tests: Marshal, codes, wrap, extract, inject, requests
docs/CENSUS.md         the evidence behind every ruling
docs/PLAYTEST.md       the five-item matrix and the release checklist
```

---

## Decisions worth knowing before you change something

**The Marshal layer, not RV2JSON.** `RV2JSON.exe -c` then `-u` with no edits
returns 28 of 231 files changed. `acetl/rvmarshal.py` round-trips all 231 byte
for byte, so `tl.py noop` can compare FILE BYTES and any difference at all is
the injector doing something it was not told to do. That is a much stronger
statement than comparing parsed trees, and it is the foundation of the
save-compatibility claim.

**The command count never changes.** A VX Ace save marshals
`$game_map.interpreter`, including `@index` - an index into the command list it
was running - and `Game_Interpreter#setup` re-binds `@list` from the patched
map on load. Wrapped English is redistributed across exactly the commands the
run already had; Ace joins a box's 401s with `\n`, so k lines across c commands
still render k rows.

**`\NAME[...]` is a nametag, not text.** The game's own script consumes it in
`convert_escape_characters` and draws it in a separate window. It is split off
before the model sees the line, costs zero width, and is rebuilt with the
English name from the glossary on inject. A speaker with no English spelling
ships a Japanese plate over English dialogue, which no per-unit check can see -
`validate` lists them separately.

**The wrap budget is the author's own envelope, not a font calculation.** No
script sets `Font.default_size` and no font ships with the game, so the cell
size is not knowable from the data. What IS knowable: 14,148 unfaced lines stop
at 66 cells and 6,319 faced lines stop at 56, and the 10-cell gap is exactly the
112 px face indent. English that fits inside those cannot clip where this
game's Japanese did not.

**The archive wins, so the archive has to go.** RGSS3 serves
`Data\*.rvdata2` out of `Game.rgss3a` whenever that file is present, and
ignores a loose file of the same name. A patch dropped beside the archive does
nothing at all, silently - the game just starts in Japanese. Install is
extract, overwrite, then MOVE the archive out.

**A doujin script can depend on a Ruby incidental, and a mobile host
breaks it.** `Scene_Replay#usable_event?` has no explicit return on its success
path, so its value is the trailing `if` branch - which ends in `p debug`.
Desktop RGSS3 returns the argument from `p`, so the recollection gallery works;
JoiPlay stubs the console print, every event is rejected, and pressing OK on
the empty gallery raises NoMethodError. `tools/patch_scripts_code.py` carries
the fix. When a player reports a crash, first prove the patch is neutral -
reimplement the game's own filter over the pristine and patched data and
compare counts - then read the script for a value that is true only by
accident.

**The two tracks can disagree, and only a cross-track check sees it.** Each
track is internally consistent, so every per-unit check passes while the same
town is spelled two ways: `マッスルーム` shipped as "Mussroom" in 85 lines of
dialogue and "Muscleroom" on the world map. `tl.py validate` now joins the
tracks on the source string and reports the disagreements - never blocking,
because a map pin legitimately shortens what prose spells out. When they do
disagree, settle it from the Japanese, not from the majority: the single
outlier was the correct one both times.

**`scripts apply` before every release.** `build_release.py` takes
`Scripts.rvdata2` from the GAME folder, which is right - that is the in-place
track's only home - but it means refreshing the working game folder from a
clean copy silently throws the script track away while the workspace still
looks finished. The symptom is a release with Japanese menus over perfect
English dialogue.

**Two tracks, never mixed.** `Data\*.rvdata2` flows store -> inject ->
`out\Data`. `Data\Scripts.rvdata2` is edited **in place** through
`tl/scripts_rb.json`. Mixing them means an inject silently reverts a script
edit, or a script edit is lost on the next inject.

**Nothing in the script ledger is translated until a human marks it.** 384
Japanese literals, classified `display` / `key` / `unknown`, all
`translate: false` by default. A `when` operand, a hash key or a save-data key
looks exactly like a label and breaks silently, so the default has to be "no".

**Stock UI strings are seeded, not translated.** 55 System units and 51 `Vocab`
literals are RPG Maker's own published English, marked `locked` so no pass
touches them. A model asked to translate `最強装備` in isolation produces "The
Strongest Equipment Set" - correct, and wrong.

**Speaker attribution refuses to guess.** A box with no `\NAME[]` gets an empty
speaker rather than inheriting the last one. The face graphic is used only for
the width budget: every face sheet in this game is the heroine in one of her
dresses.

---

## The two things automation cannot do

**Read `out/ui_review.txt`.** A few hundred lines, minutes to skim, and the only
pass that catches a short verb rendered as the wrong part of speech. `訂正する`
("go back and re-enter") came back as "Correct" on another game - English,
short, no placeholders, no residual Japanese, every automated check green, and
it sends the player the opposite way.

**Play it.** `docs/PLAYTEST.md` has the five-item matrix to run after *every*
export, the two measurements that need a running game, and the reason the
recollection room does not count.
