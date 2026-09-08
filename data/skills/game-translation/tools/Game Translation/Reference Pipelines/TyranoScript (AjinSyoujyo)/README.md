# 亜人少女 ～異能少女との同棲生活～ - JP→EN translation toolkit

Game: **亜人少女** (ラーレゲームス / Lare Games, 2026), R18.
Engine: **TyranoScript v5 in Electron 7.1.2** - `resources/app.asar` (745 MB)
holding `data/scenario/*.ks` + `tyrano/`.

Status: **translated and deployed.** 5,078 of 5,088 units are English (the other
10 are engine keys, deliberately frozen); 284 UI images are redrawn; validation
reports 0 hard failures and 0 layout overflows. Run on Sonnet 5 via the Message
Batches API for **$1.03** all-in.

Every image the scripts load that carries Japanese UI text has been swept.
`config/`, `hideoutui/`, `saveload/`, `button/`, `cautionui/`, `mesbox/`, `yui/`
and `womb/` needed nothing - they are icon-only or already English - and the
wardrobe banners, the config screen and the hideout banners already ship the
game's own bilingual style. What is left is a play-test.

---

## What this game is, text-wise

No localisation system, no name box, no CSV tables. Everything is in the
TyranoScript source, in five different shapes - and each one is handled at
source rather than by a runtime hook.

| Kind | Units | Where it lives |
|---|---:|---|
| `dialogue` | 4,238 | bare message lines in `.ks`, scene-grouped, never deduped |
| `code` | 451 | JS string literals inside `exp=` / `cond=` / `&`-expressions / `[iscript]` |
| `choice` | 208 | `[glink text=]`, `[button text=]` - menu buttons |
| `ptext` | 106 | `[ptext text=]` - free-positioned on-screen labels |
| `js` | 56 | engine + plugin `.js` (save captions, playtime units, dialogs) |
| `punct` | 22 | fullwidth `！？。` with no kana - converted offline, no API call |
| `hint` / `notice` / `ruby` / `title` / `edit` | 7 | tooltips, toasts, furigana, window title, name-entry default |

Two of these are easy to miss and both matter:

**`code`.** `[eval exp="f.hidename=['扉','演算機','廃品',…]"]` builds the hideout
menu, and `[ptext text="&'同棲' + f.daily_count + '日目'"]` builds the day
counter by concatenation. These are string literals inside code, they are drawn
on screen, and a naive extractor either skips them or translates the whole
expression and breaks the game. The extractor scans *inside* the expression and
emits one unit per literal, with the whole expression attached as prompt context
so a fragment can be made to read correctly in place.

**`[iscript]` blocks.** `system/exp.ks` holds five ranked arrays of lewd words
(genitals / semen / anal / orgasm), LV0 to LV4, spliced into dialogue at random
by `[emb]`. 100+ units of real content that only a JS-literal scan finds.

### What is deliberately *not* translated

Every Japanese string that does not become a unit is written to
`extracted/excluded.jsonl` with a reason. Nothing is dropped silently.

| Reason | Count | Why |
|---|---:|---|
| `author-comment` | 1,408 | `;` comments - the engine never renders them |
| `code-identifier` | 90 | Japanese *inside a variable name*, e.g. `f.orgasm_in_a中に_count` |
| `non-text-param` | 32 | `[image storage=]`, `[button graphic=]`, `[glink target=]` |
| `label-identifier` | 26 | `*ネモタスク0` and friends - jump targets |
| `asset-path` | 25 | `tansaku/南西（奥）.png` - real files on disk |
| `plugin-not-loaded` | 6 | plugin folders the game never `[plugin]`-loads |
| `unparsed-line` | 1 | `system/exp.ks:366` has an unterminated quote (dead `f.hote` data) |

Ten more strings are extracted but **locked**: `完了したタスク`, `ネモタスク0-8`.
They double as jump-target labels, so translating them would break control flow.
They are marked `manual` and never sent to the model.

If a game update introduces a new `(tag, param)` pair carrying Japanese, it is
excluded *and* reported as `unknown-site` in the extract report, so it surfaces
instead of being silently mistranslated. Right now that count is **0**.

---

## Delivery

`resources/app` is checked **before** `app.asar` - confirmed by reading the
search-path list out of the shipped binary itself:

```
const searchPaths = ['app', 'app.asar', 'default_app.asar'];
```

So the default patch is a **1.8 MB drop-in folder**, not a 745 MB repack:

```
resources/app/
  main.js             loader shim: same window setup as the original, plus
                      interceptFileProtocol('file') for the overridden paths
  package.json        name/window copied verbatim from the original
  override/           the 56 translated files, mirroring their asar paths
```

`main.js` loads `index.html` from *inside* `app.asar`, so every relative path the
game uses still resolves into the original archive; only the paths present in
`override/` are swapped. `path.join(asarPath, …)` and `fs.existsSync` resolve
into the archive - verified against the game's own Electron runtime.

**To uninstall: delete `resources/app`.** Nothing else on disk is touched.

Two fallbacks, in case the shim ever misbehaves:

* `deploy --mode full` - extract the whole archive to `resources/app` and copy
  the translated files over it. 745 MB, zero engine trickery.
* `deploy --mode asar` - repack a complete `app.asar` for redistribution. The
  repack is read back and every one of the 4,168 entries is diffed against its
  true source; `verified: byte-exact` in the output means exactly that.

TyranoScript's own `.tpatch` auto-updater (`ajin_syoujyo.tpatch` next to the exe,
`patch_apply_auto=true` in `Config.tjs`) is deliberately **not** used: its asar
branch fires two un-awaited async IIFEs at the 745 MB archive and then deletes
the patch file.

---

## Commands

```powershell
pip install -r tools/requirements.txt
$env:ANTHROPIC_API_KEY = "sk-ant-..."      # or: ant auth login

python tools/tl.py unpack --images   # app.asar -> extracted/app  (+ extracted/images)
python tools/tl.py extract           # -> tl/ store + extracted/ reports
python tools/tl.py selftest          # offline round-trip proof, writes nothing
python tools/scripts/tests/test_pipeline.py     # 33 unit tests, no network
python tools/tl.py punct             # 22 punctuation-only units, offline, free
python tools/tl.py dryrun --show-sample         # scope + cost + a real prompt

python tools/tl.py names             # cast pass -> writes into glossary.json
#   ... review tl/glossary.json by hand before going further ...

python tools/tl.py run               # submit + poll + fetch  (cheapest)
#   or: submit / status --watch / fetch      (each step resumable)
#   or: live --workers 4                     (2x cost, minutes not hours)

python tools/tl.py validate --flag   # residual JP / placeholders / layout
python tools/tl.py retry             # re-run whatever validation flagged
python tools/tl.py inject            # -> translated/
python tools/tl.py deploy            # -> the game's resources/app
```

`run` is one-shot. `submit` → `status` → `fetch` is the manual equivalent, and
`fetch` works any time after the batch ends - Ctrl-C during polling is safe.

### Batches can sit queued for hours

`processing=112, succeeded=0` is the **queue depth, not a completion ratio**. The
documented cap is 24 hours and "most complete within 1 hour" is guidance, not a
promise. If the queue stalls, `tl.py live` finishes the same work through the
same request builder and the same parser, at 2× the price and with visible
per-request progress.

---

## Translation setup

**Model** `claude-opus-5`, **reasoning effort `low`**, Message Batches API. Low
effort is right for straight translation; the API default of `high` multiplies
output tokens for no quality gain. No sampling params are sent - Opus 5 rejects
`temperature` with a 400.

The system prompt carries **two cache breakpoints**:

```
system[0]  localisation rules + game_prompt.md    ~10 K tokens, 1h TTL
system[1]  glossary.json, rendered                 ~1.5 K tokens, 1h TTL
messages   the units for this request
```

Two, not one: the glossary is edited constantly during a run, and a second
breakpoint means an edit rewrites only the glossary block instead of
invalidating the bible. The 1-hour TTL matters for batch - async requests are
processed minutes apart and would miss a 5-minute window. The live driver uses
the 5-minute TTL instead, and fires its first request **alone** so it writes the
cache before the pool fans out to read it.

Dialogue goes out in play order, 60 units per request, breaking on file
boundaries with 3 preceding lines carried as do-not-translate context. Scene
boundaries are a soft hint: this game has hundreds of two-line scenes and one
request per scene multiplied the request count five-fold for no context gain
(510 requests → 113, and the estimate fell from $8.99 to $3.81).

Measured scope: **113 requests, 5,056 units, 88,933 JP characters.**

### What the run actually cost, and where the estimates were wrong

`msgbatch_01TMdvKjDDmpzosZLMhBmihW`, Sonnet 5, submitted 14:53 UTC, ended 16:26.
Real billed usage: **input 182,865, output 134,638, cache write 4,256, cache read
476,672 - 99% of cached tokens were re-reads**, so the two breakpoints did their
job. That is **$0.91**, plus ~$0.12 for the names pass, two retries and two
fit passes: **$1.03 all-in**.

Two estimator errors worth remembering:

* **A single tokens-per-character ratio over a mixed prompt is badly wrong.** The
  1.1/char proxy is right for Japanese and 4x too heavy for English, so the
  rules-and-bible prefix was estimated at 11,509 tokens against 4,261 real.
  `estimate_tokens` now counts the two scripts separately.
* **The output ratio belongs to the output *contract*, not the game.** 2.36
  carried over from a pipeline whose contract returned an object per unit with
  speaker and notes fields; this one returns a bare `id -> string` map and came
  in at **1.38**. Measured input, by contrast, was accurate to 0.3%.

The batch sat at `processing=113, succeeded=0` for its entire 93-minute run and
then flipped to 113 succeeded in one step - the counters are not a progress bar.
The console's usage graph *was* live, and showed the input being consumed within
minutes of submission.

| Model | batch+cache | batch only | live+cache | live only |
|---|---|---|---|---|
| Opus 5 | $3.81 | $6.68 | $7.58 | $13.37 |
| Sonnet 5 | $1.52 | - | $3.03 | - |
| Haiku 4.5 | $0.76 | - | $1.52 | - |

Rates are transcribed in `scripts/tyranotl/pricing.py` from the published table
(checked 2026-08-19), all five columns Anthropic publishes, with the batch
discount derived by halving. **Sonnet 5's $2/$10 is the introductory rate that
runs through 2026-08-31** - update the table after that. Output is estimated at
2.36× source tokens, the ratio measured on a finished run of this size; input
estimates track within 1%, output is where estimates break.

### The two JSON failures worth handling

Both are already handled in `prompts.parse_reply`, with regression tests:

1. **An unescaped `"` inside a value.** The Japanese uses an ASCII double quote
   as a dakuten on slurred moans (`あ"っ`) and the model carries it into English.
   A `"` only *closes* a value when the next non-space character is `,`, `}`,
   `:` or `]`; anything else is literal text and gets escaped.
2. **Self-correction.** The reply emits a partial object, reconsiders in prose,
   then emits the real one. Every *balanced* top-level object is extracted and
   the one with the most keys wins - a first-`{`-to-last-`}` span would swallow
   the prose.

Quotes are repaired first: the brace scan depends on correct string boundaries.

---

## The engine trap: spaces die inside quoted attributes

**TyranoScript deletes every literal space inside a quoted tag attribute.** From
`kag.parser.js`, `makeTag()`:

```js
if (flag_quot_c != "") { "="==c && (c="#"); " "==c && (c=""); tmp_str += c }
```

It does that because it then splits the whole tag on spaces to separate the
parameters. `=` is swapped for `#` and restored afterwards; the space is simply
dropped and never comes back. Japanese never noticed - it does not use spaces.
English arrives as `Thistitlecontainscross-sectionviews.`

This hits **every** attribute-carried string: `glink text=`, `ptext text=`,
`notice text=`, `button hint=`, `title name=`, `edit initial=`, and the JS string
literals inside `exp=` / `cond=` - `f.hidename=['Bench Press']` was becoming
`'BenchPress'`. It does **not** hit message-box dialogue, `[iscript]` bodies, or
the engine `.js` files, none of which `makeTag` ever sees.

The fix is **U+00A0**. Checked against the game's own parser by running it under
`ELECTRON_RUN_AS_NODE=1 ajin_syoujyo.exe`:

| written as | survives `makeTag` | renders as a space in |
|---|---|---|
| `U+0020` | no - deleted | - |
| **`U+00A0`** | **yes** | `.html()`, `.text()`, `document.title` |
| `&nbsp;` | yes, as literal text | `.html()` only |
| `U+3000` | yes | everywhere, but double width |

`inject.inside_kag_attribute()` decides which sites get the substitution, and
`tests/test_pipeline.py::TestAttributeSpaces` pins the behaviour. Two side
effects worth knowing:

* It also restores spacing the *author* wrote and the engine was eating -
  `text="仕 事 受 注"` had been rendering as `仕事受注`.
* `selftest`'s identity check now compares with U+00A0 normalised **on both
  sides**: the shipped `tyrano/libs.js` already contains U+00A0 in its own
  indentation, so normalising only one side reports a false diff.

Any future TyranoScript game will hit this. It belongs in the reference pipeline
when this toolkit is copied into `Tools\`.

## The second engine trap: inline word-inserts have no spaces

Some inline tags expand to a **word** at run time - `[name2]` becomes the
player's name, `[ig_tntn]` picks a noun out of a randomised array, `[emb]`
evaluates any expression. Japanese needs no space around an inserted word, so
the source has none, and a faithful translation keeps none:

```
[emb exp="f.name2"]で宜しいでしょうか。   ->   [emb exp="f.name2"]Is that alright?
```

which reaches the screen as **"NeroIs that alright?"**.

Which tags insert a word is read out of the project's own `macro.ks` rather than
guessed (`codes.inline_emitters`): a macro qualifies when its whole body is one
`[emb]`, so `[p]`, `[r]` and the face-change macros are never touched, and
`like_lv1` - which emits an entire line - is correctly excluded. Watch the regex:
the lewd-word macros index with `[emb exp="f.ingo_tinko[f.ingo_LV][tf.rd]"]`, and
a naive `\[emb[^\]]*\]` stops at the first `]` and misses them.

Two places need the fix, because they see different things:

* `tl.py spacing` handles inserts **inside** a unit, where the tag arrives as a
  sentinel. Spaces go either side unless the neighbour is an apostrophe, a
  hyphen or a decoration - `[[0]]'s cock` and `[[0]]-chan` stay tight.
* `inject.pad_inline_inserts` handles inserts **against** a unit's edge.
  `split_affixes` peels a leading or trailing tag run off so the model sees clean
  text, which puts the emitter *outside* the unit where the first pass cannot
  reach it. This was the case in the screenshot.

The rule is also in the prompt now, so a future run should not need either pass.
Sweep the result with the check in this file's history: 121 inline word-inserts
in the translated scripts, 0 junctions missing a space.

## Invariants the pipeline enforces

* **Injection is a pure span splice.** Every site stores `(file, line, start,
  end)` plus the original characters at that span. `selftest` re-reads all 56
  touched files, asserts every span still matches, splices the originals back in
  and compares bytes: **56 files, 6,922 spans, 0 differ.**
* **The lexer is byte-faithful.** Line separators are carried per line - this
  project mixes CRLF (31 files) and LF (17) - and no BOM is added or removed.
* **The token map belongs to the occurrence, not the unit.** Two lines can mask
  to the same string while standing for different tags; keying tokens by unit
  silently restored the wrong tag on 338 lines before this was fixed.
* **Placeholders are validated on every returned string.** A dropped, added or
  renumbered sentinel is a hard failure that flags the unit for `retry`.
* **Key strings never become English.** Labels and jump targets are collected
  first, and any `code`/`js` unit whose text collides with one is frozen.
* **Stable unit ids** (`sha1(kind + source)`), so re-extracting after a game
  update carries every finished translation forward.
* **Censor glyphs are not residual Japanese.** `〇` masking an obscenity and the
  standalone dakuten `゛` hung on a vowel both survive into English on purpose.

---

## Layout

```
tools/
  README.md                  this file
  requirements.txt
  tl.py                      the CLI
  tl/
    glossary.json            8 locked names + 46 terms + 6 notes  <- edit by hand
    game_prompt.md           the game bible (cached prefix)
    <Bucket>.json            the store, one file per scenario folder
    _batch_state.json        transient batch bookkeeping
  extracted/
    app/                     the text side of the asar (scripts, engine, plugins)
    images/                  every image in the game, for the art pass
    <Bucket> reports:
      extract_report.txt     the integrity summary
      excluded.jsonl         every rejected string + the reason
      jp_all_strings.txt     every unique masked source string
      image_review.csv/.txt  images ranked by likelihood of baked-in Japanese
      image_sheets/          per-folder contact sheets (open index.html)
  translated/                injected output, mirroring the asar paths
  patch_src/main.js          the Electron loader shim
  scripts/
    unpack_app.py            ASAR extractor (text / images / all)
    image_review.py          the image ranking + contact sheets
    imgwork/
      imgtl.py, ajin.py      the shared drawing toolkit + this game's helpers
      relabel.py             plate finding and the per-row clipped erase
      sheet.py               per-folder contact sheets
      build_title.py         title menu banners
      build_base_ui.py       home-screen menu tiles
      build_tansakuui.py     the scavenge screen's three buttons
      build_screens.py       status, storage and scavenge-result frames
      build_hsceneui.py      H-scene command buttons
      build_wardrobe.py      wardrobe / market buttons (sub-line and swap modes)
      build_cards.py         appearance selection cards
    tests/test_pipeline.py   33 offline regression tests
    tyranotl/
      kslex.py               byte-faithful .ks reader, tag/attr scanner
      codes.py               JP detection, tag+HTML masking, validation
      sites.py               the (tag, param) classification table
      jsstr.py               JS string-literal scanner with comment masking
      extract.py             the extractor
      store.py               store + glossary
      inject.py              span splice + the reversibility proof
      prompts.py             request builder + JSON repair (shared by both drivers)
      batch.py               Message Batches driver
      live.py                threaded synchronous driver
      pricing.py             published rates + the four-way cost model
      layout.py              measured text fitting against the game's own font
      rewrap.py              the line-layout pass: overflowing [r] breaks and
                             glued line junctions (runs at the end of `inject`)
      validate.py            hard failures and soft warnings
      deploy.py              patch / full / asar delivery + asar verification
```

---

## Line layout

Translating the text without touching the layout leaves five faults behind,
because TyranoScript joins consecutive scenario lines into one run and breaks it
only where the author wrote `[r]`.

None of these belong in `inject`, which stays a mechanical span splice: injecting
a unit's own source has to reproduce the file byte for byte, which is what
`tl.py selftest` checks. They are edits to the English, applied after it.

**Glued words.** Two text lines in a row concatenate with nothing between them -
correct for Japanese, wrong for English:

```
...an entirely different physiology.They sustain their vital functions...
```

A trailing space cannot fix it. `parseScenario` runs `$.trim()` on every line
before it looks at anything, and jQuery's `rtrim` is `/^[\s\uFEFF\xA0]+|.../`,
so it takes U+00A0 with it - the non-breaking space that survives the *attribute*
trap dies here. What survives is KAG's own marker: a leading `_` is stripped
**after** the trim, so `_ and Lewdness...` keeps its space.

**Split words.** `[ruby]` attaches its reading to the *next character only* -
right for a kanji, wrong for a word. `[ruby text="ザーメン"]精液` is 精液 glossed
with its slangy reading; both halves come out as "semen", so the tag survives
only to break the word in two, "s" wearing the ruby and "emen" left behind:

```
could I have some   s emen?
```

A gloss whose reading and base translate to the same word carries nothing, so
the tag goes. There is exactly one in this game, but the rule is general.

**Lines set flush to the measure.** A run landing between 95% and 100% of the box
comes out as one line filling the measure edge to edge, with nothing to
distinguish a full line from a clipped one:

```
...someone in my family taught me that kind of thing. It's not really my own true natu
```

That one is 1789px in an 1800px box - it fits, by eleven pixels, which is inside
the error of any measurement made outside the browser. Splitting it at the word
boundary nearest the middle gives two half-width lines (911px and 867px) that
read as deliberate and cannot be pushed over by a rounding difference. Only runs
that would otherwise be a *single* line are split; one that already wraps is left
to the engine, which balances it better than a fixed rule could.

The break has to be written into a line that has tags threaded through it, so the
pass keeps a map from text offset to line offset - without it the `[r]` lands
inside `[elsif exp="..."]` and corrupts the condition.

**A beat with nothing else on the line.** `______[p]` is the author's
trailing-off marker standing alone as a whole message. It carries no Japanese,
so the extractor never took it as a unit and `polish` never saw it. Converted
here because this is the only pass that works on lines rather than units.

**Orphaned fragments.** A hand-placed `[r]` behind a line that now overflows
turns the overflow into an orphan on a line of its own:

```
Affection rises through physical contact and using
the syringe,                                          <- 242px of a 1090px line
and Lewdness rises when you have sex.
```

Dropping that `[r]` lets the engine wrap the paragraph as a whole, filling both
lines. Removing a break can only reduce the line count, never raise it, so this
stays safe against a message box three lines tall. `[lr]` also waits for a
click - that is pacing the author chose, not layout the translation broke - so
it is downgraded to `[l]` rather than deleted.

Measuring the overflow needs three things to be right, and all three are read
from the game rather than assumed:

| | |
|---|---|
| **which box** | `show_mesS` is 1210px wide against `show_mesL`/`H`/`T` at 1920, so the same sentence wraps in one and not the other. The `show_mes*` macros are parsed out of `system/macro.ks` and each file is scanned forward for the last one called. A file that calls none - `hint.ks` is one - inherits its caller's box; unresolved falls back to the narrowest, which is the safe way to be wrong. |
| **which font** | `mfrules` in `tyrano/css/font.css` resolves to Source Han Serif JP, shipped as both `MyFont1.otf` and `MyFont2.woff` - same face, same units-per-em - so measuring the otf measures what the player sees. Size from `[deffont size=]`. |
| **one visual line** | text accumulates across tags and across source lines until `[r]`/`[lr]`/`[p]`/`[l]`. Inline emitters count as a word. A branch, jump or screen clear discards the buffer instead of measuring it, since the two halves may never be on screen together. |

The pass runs automatically at the end of `tl.py inject` (`--no-rewrap` to skip)
and can be inspected on its own:

```
python tools/tl.py rewrap           # report only
python tools/tl.py rewrap --apply   # report and write
```

On this game it drops 22 breaks, splits 44 flush lines, spaces 81 junctions,
removes 1 ruby tag and converts 3 lone markers.

### The author's trailing-off marker

`＿` (U+FF3F FULLWIDTH LOW LINE) is not punctuation the Unicode tables know as
punctuation, and it is not a Japanese character, so it passed the residual-JP
check untouched and reached the screen looking like a fill-in-the-blank:

```
You'd better rest quietly in your room＿＿＿ hm?
```

It is this author's trailing-off marker - a drawn-out silence, used where a
Western script puts an ellipsis - in 114 units across 23 files. `tl.py polish`
converts it. One block in `rankou.ks` uses the same character for something else
entirely, separating a speaker's name from their line, and that use is told
apart by the run of spaces that always follows it and becomes a colon.

### Stray sentinel brackets

Comparing the *sets* of `⟦n⟧` placeholders is not enough on its own. A reply
that drops one bracket, or invents a named one, leaves the set unchanged and
ships the brackets to the screen - five units did, including `Got 5 ⟦item⟧` on
the scavenge results. `codes.stray_sentinel` catches both and `validate` now
treats it as a hard failure.

The `⟦item⟧` case is worth remembering: the line is `[emb …]を5個手に入れた`, so
the item name is *emitted before* the text and the English has to read on from
it rather than reach back for it - "x5 acquired", not "Got 5 <item>". A unit
that is only a fragment of its sentence cannot reorder around its emitters.

### Widget labels have no wrapping at all

A `[glink]` is an absolutely-positioned button that sizes to its text, so a label
too long for the space beside it runs off the screen rather than wrapping. The
requests screen is a three-column grid at x=20/650/1280, and
`Affection 2500 or higher, Lewdness 4800 or higher` is 629px plus ~50px of button
padding - from x=1280 that ends at 1959 on a 1920 screen, and the last word is
simply gone.

The fix is the wording, not the layout: `Affection 2500+, Lewdness 4800+` is
411px. `+` reads as "or higher" in a requirements list and nowhere else, so the
shorthand is confined to widget labels - the same phrase in message prose keeps
the long form.

`scratchpad/check_glinks.py`-style measuring is worth redoing after any wording
change: every `[glink]` is checked against the room between its `x` and either
the next column or the screen edge, and it found two more labels over by 39px
and 12px that had nothing to do with the requests grid.



### Plates whose width is written in the script

The room-expansion screen draws each label twice - a `[ptext]` for the words and
an `[image storage="ho.png"]` at the same x/y for the black plate behind them,
with the plate's `width` spelled out as a number. Those numbers were measured
against the Japanese, so English spills past the plate, and `Storage Lv:` at
x=1850 ends at 1998 on a 1920px screen. `[ptext]` neither wraps nor clips; it
just draws.

`tyranotl/widgets.py` re-measures each plate against its English and rewrites
the width. Five of the six only needed that. The sixth has nothing to its right
at all - its own icon occupies 1697..1813 - so the label moves to the *left* of
the icon, the only free space on that row; that one placement is a judgement
call and sits in a `MOVES` table rather than being derived.

Worth knowing: **the Japanese was clipped there too**. `倉庫Lv:0` rendered as
`倉庫L` against the screen edge in the original game, so this is a pre-existing
bug the translation only made more obvious.

Verify it without launching the game with `scratchpad/mock_hideout.py`, which
composites the icons, plates and labels onto a 1920x1080 canvas at the exact
coordinates the script gives - the same thing the engine does, so an overflow in
the mock is an overflow on screen.


### Two labels sharing a row

A `[ptext]` neither wraps nor clips, and nothing on a screen knows about
anything else on it. Where the original put two of them side by side, the left
one's width was measured against the Japanese, and English simply runs into its
neighbour. Two shapes of this exist, and they want opposite fixes.

**A value that follows the words.** The upgrade screens end each bonus row with
a blue `+N`, drawn as its own `[ptext]` at an x chosen to clear the Japanese
description. `毎日お金が` is 112px and ends at 287, so the value went at 375;
"Money increases daily" ends at 472 and lands on top of it. `widgets.space()`
re-measures the description and pushes the value to just past it. It only ever
moves a value right and only when it has to, so the four rows that already
cleared are untouched. The blue is `0x00a2ff`, used nowhere else in the game and
only on that row, so the colour names these values exactly.

**A value threaded into a gap.** The black market's trade header is one label
with wide gaps - `現在の取引LV：　　信頼度:　　取引額:` - and the numbers are
drawn *into* the gaps by separate `[ptext]`s at fixed x. Every column was cut to
land just before its value: `現在の取引LV：` ends at 1241 and the level is drawn
at 1238. English is wider, so `Current Trade LV:` runs past 1238 and every value
ends up buried in the wrong word. Pushing anything right cannot fix this - the
values are boxed in on both sides.

`widgets.columns()` rebuilds the row. It splits the label at its gap runs into
one `[ptext]` per column, lays them out left to right keeping each gap at its
Japanese width, and moves every value to the gap it belongs to. Which gap that
is comes from the Japanese, which is the only record of the intended layout: the
Japanese columns are measured, and a value is assigned to whichever gap it sits
in there. The pieces go on one line, so no line numbers move and saves still
resolve (see the save-compat section).

Three things keep it from firing where it should not:

- only *literal* text can hold a column separator. `&'+' +  f.hide[7]` has two
  spaces between its operators and reads as a gap if you search the raw
  attribute, but nothing is drawn there.
- a gap only counts if a value is actually drawn into it. Wide spacing with
  nothing threaded through is padding, and re-cutting it would move words that
  were never in anyone's way.
- a `[ptext]` on a commented line is not on screen and so not on a row. One sits
  in the trade header, and counting it would lay the columns out around
  something nothing draws.

Rows are scoped to the enclosing `*label`, or to the `[macro]` body in macro.ks,
which has no labels at all. Six upgrade screens draw their bonus row at y=910
and are never on screen together; grouping by y alone invents collisions that
cannot happen, and hides real ones behind them.

Find them with `scratchpad/check_rows.py`, which measures every `[ptext]`
against the next one along its row and reports what overlaps. It reads
`&nbsp;` as one space rather than six characters and stands a counter in at two
digits - get either wrong and it reports a screenful of rows that are fine.

### Hard breaks placed for Japanese

A `[ptext]` does not wrap, so where a label needs two lines the author wrote the
break himself with `<br>`. Those breaks were placed against Japanese widths. On
the scrap-collection screen the first line then measures 713px against a panel
(`houp.png`) that is 650px wide, and the sentence runs off the dark UI onto the
lit background behind it.

`widgets.rebreak()` re-places the breaks. The rule is **the narrowest box the
words still fit in the same number of lines**:

- the same number of lines, because the block must not grow downward into
  whatever is drawn below it. The Japanese line count is the author's own
  statement of how tall the block may be.
- the narrowest such box, because it both pulls the text back inside the panel
  and balances the lines. A greedy fill at the old width runs every line to the
  margin and leaves the last one holding two words.

Found by binary search on the width, since greedy wrapping is monotone in it.

Two things it deliberately leaves alone. A label whose English is wider than the
Japanese but has room to its right is not a fault - `caution.ks` draws its
option text at x=450 with nothing beside it, and re-breaking would make it worse.
And a trailing `<br>` with nothing after it is not a second line: one label ends
with one, and counting it would licence splitting a single English line in two.

`scratchpad/check_br.py` lists every hard-broken label with its English lines
measured against the Japanese box.


### Taking a new game build

An upstream update is not like one of our patches: the author adds and removes
whole *lines*, so the "every edit stays inside a line" invariant the save
migration rests on does not hold. Order of work:

1. `scripts/asarhdr`-style header diff first - compare entry lists and sizes
   between the old and new `app.asar`. 1.0.2 touched 14 scenarios and added
   `update.ks`; **no image changed**, so the 284 redrawn PNGs stayed valid.
2. Copy only the changed files over `extracted/app`, never re-extract the whole
   tree - the text-mode unpack does not include `data/others/MyFont1.otf`, and
   losing it silently drops `layout.measure` to a crude fallback.
3. `tl.py extract` merges the store; anything it reports as new is genuinely new
   text. A typo fix upstream (`ぽっぺた` -> `ほっぺた`) reappears as a new unit with
   the same English.
4. Translate, `inject`, then **measure the save migration** against the
   previously deployed tree, which is the baseline that matters:

       ELECTRON_RUN_AS_NODE=1 ./ajin_syoujyo.exe scripts/test_waitpoints.js            <previous override/data/scenario> translated/data/scenario

   `test_remap.js` walks every element and calls any change of line a miss,
   which overstates the risk. `test_waitpoints.js` asks the real question: of
   the elements a save can actually sit on, how many resume in the same moment
   of the story? For 1.0.0 -> 1.0.2 that is 52.2% with no migration, 63.2% on
   line+ordinal alone, and 95.2% once the message text is used.
5. `scripts/test_realsaves.js <save.sav> <scenario dir>` replays the actual save
   file. Do this too - the corpus and the real thing disagree.
6. `scripts/check_residual.py` on the injected tree: an update ships strings no
   earlier pass ever saw.


---

## Testing: why saves do not survive a patch

A TyranoScript save (`kag.menu.snapSave`) stores two things that matter here:

| | |
|---|---|
| `data.layer` | the **rendered HTML** of every layer, restored verbatim by `setLayerHtml` on load. The text on screen right after loading is whatever was there when the save was made - one click forward re-renders it from the patched script. Cosmetic. |
| `data.current_order_index` | an **integer index** into the parsed element array of the current scenario, and load resumes with `nextOrderWithIndex(...)`. Dropping or inserting a single `[r]` changes how many elements the file parses to, so a save taken later in *that file* resumes at the wrong element. Not cosmetic. |

The save also carries `stat.current_line`, the source line number, and the
pipeline never changes line numbers - injection is a span splice and every
`rewrap` edit is in-line. That is what makes the fix below possible.

### Keeping saves working: `patch_src/save_compat.js`

Ships in **every** build, release included, because a published patch update
that voids players' saves is not shippable. Delivered as two ordinary override
files - the script, and the game's own `index.html` with one `<script>` line
added before `</body>`, which is after every engine script in `<head>` and
before `kag.init()` clones the prototypes at DOM ready. So it patches
`tyrano.plugin.kag.menu` and `.ftag` directly, with no polling.

It records position by *line* instead of by index:

| | |
|---|---|
| **new saves** | `snapSave` is wrapped to stamp `data.__compat` with the line, the element's ordinal within that line, and its tag name. That identifies the element exactly, even on a line whose element count changed. |
| **older saves** | nothing stamped, so it falls back to `stat.current_line` and takes the element on that line nearest the stored index. |

Measured with `scripts/test_remap.js` (run it under the game's own Electron:
`ELECTRON_RUN_AS_NODE=1 ./ajin_syoujyo.exe tools/scripts/test_remap.js <old> <new>`)
across all 22 scenarios this patch shifted, 24,019 elements, each treated as a
save point:

```
no remap (what a plain patch does)   63.2% land on the right element
older save, line only                85.4%, and never the wrong line
stamped save, line + ordinal         99.2%, and never the wrong line
```

The residual 0.8% are lines whose element composition the patch itself changed -
two text runs merged where an `[r]` came out - where landing on the merged
element is the right answer rather than a miss.

Three things it has to get right, and each of them would be a silent bug:

* The remap must run **only** on the save-load path. `nextOrderWithIndex` is
  also how a macro returns to its caller, and there the recorded line means
  something else. A flag set by `loadGameData` and consumed by the very next
  call keeps them apart.
* It must correct the index **before** the original runs, because the original
  splices its `make.ks` call at `index + 1`.
* The fast path ("nothing moved, use the stored index") must check the ordinal
  as well as the line. Without that, a line holding several tags accepts a
  neighbour - it was landing on `[fi3]` instead of `[fi1]` until that was fixed.

Anything unexpected falls back to the stored index, which is the behaviour
without the file: it can degrade, it should not break a load.

### When a tag changes line

The stamp records the line a resume point sat on, and `remap` looked for that
line in the new build. If a patch moved the tag to a *different* line, no
candidate matched and it gave up, returning the stored index unchanged.

That is exactly wrong when the file also gained or lost an element earlier on.
A real save caught it: it was waiting on `[s]` on the base hub, stamped at line
247. In the next build that `[s]` sat at line 246 and one element earlier, so
the stored index resumed on the `*time_confirm` label after it - and the game
played a scene the player was not in. The save looked broken because it was.

So when the recorded line holds nothing, `remap` now scans outward from the
stored index for an element with the same name and the same place within its own
line, and takes the nearest. `DRIFT` bounds the search at 16 elements: a patch
moves a resume point by one or two, and anything further is a rewrite where
guessing would land in the wrong scene.

`scripts/test_remap.js` checks this. It no longer carries its own copy of
`remap` - it reads the three declarations straight out of `patch_src/save_compat.js`,
because a copy drifts from the shipping file and then measures code that never
runs. Its unit cases cover an unchanged resume point, a tag added above one, a
tag whose line moved, and one that drifted too far to be worth guessing at.

Worth knowing when reading a save: `stat.current_line` is 0-based, so line 246
in the save is source line 247 in the file. `scratchpad/readsave.py` prints both.

### The scene-jump menu

`tl.py inject --debug-menu` generates `data/scenario/_debug.ks` from the injected
output: every scenario file, every label, as a clickable grid, plus
`[all_clear]` and a max-stats shortcut. It splices a `scene jump` link into the
title screen and the home screen, and flips `debugMenu.visible` so the engine
prints the scenario and line of anything that errors - which it will, when you
jump into a scene that expects state it has not been given.

949 labels, 1041 links. Leave the flag off for a release build and none of it is
written. The generated file survives re-injection because `inject.write` only
rewrites the files it patches.

Two details it has to get right, both of them the same traps the rest of the
pipeline hits: every label shown in a `text=` attribute needs its spaces as
U+00A0 or `makeTag` eats them, and the entry-point splice has to be re-run after
every inject, which is why it lives behind the same command.

### A bug the menu found

Validating that every generated jump resolves turned up
`event/serenah.ks:28` - `ボロンッ[p]` had come back as `*fwip*[p]`, and
**`parseScenario` dispatches on the first character of the trimmed line**, so
the engine filed it as a label named `fwip*[p` and the sound effect never
displayed at all. `;` `*` `@` `#` and `_` all do this. `validate` now treats a
translation that opens a line with one of them as a hard failure.

---

## Still to do

1. ~~Run it.~~ Done - see above.
2. ~~The image pass.~~ Done - 284 images across `title/`, `base_ui/`,
   `tansakuui/`, `hsceneui/`, `blui/`, `kigaeui/` and the three full-screen
   frames. The builders live in `scripts/imgwork/`; each is a table plus a
   measured box, so re-running one after a game patch is a one-line change.
3. **Play-test.** Build with `--debug-menu` and use the scene jump.
   Screenshot anything still Japanese and check whether it is in
   `excluded.jsonl` (a classification bug) or in an image (the art pass).

## Notes

* Adult content is translated faithfully and uncensored. That is the correct
  localisation for an R18 commercial title, and `game_prompt.md` says so.
* A full-width space inside a line is a **pacing gap between gasps**, not
  indentation. Both the prompt and the offline punctuation pass leave it alone.
* The player names the protagonist, so his name reaches dialogue through a
  variable and arrives as a sentinel. The glossary says never to write "Nero"
  into a line that has one.
* The name-entry screen has ~20 easter-egg names (`お兄ちゃん`, `島守匠海`,
  `gaster`, …) that grant starting bonuses. They are `code` units and get
  translated consistently with the glossary, so the bonuses still fire when the
  player types the English spelling.
