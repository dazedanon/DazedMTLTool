# 執聖官アルテシア Ver1.06 - translation pipeline

RPG Developer Bakin, build **r64268** (2024-07-31).
Second Bakin title in the corpus, and materially different from the first: see
"What differs from the reference pipeline" below before reusing anything.

    game   c:\Users\sw\Desktop\Games\執聖官アルテシアVer1.06     (a WORKING COPY - may be deleted)
    tools  C:\Users\sw\Desktop\Tools\Game Translation\Active Projects\Artesia (Bakin)

Nothing here depends on the game folder except `config.game_dir`, which is used
only to bind to the engine's own `common.dll` and to install a built patch.

---

## Status

| gate | result |
|---|---|
| `roundtrip` | 328 of 329 rom files byte-identical (the exception is documented and never written) |
| **`noop` inject** | **329 of 329 byte-identical** - extraction and injection are lossless over all 90,195 units |
| `selftest` | 112 checks, 0 failures - including the validator itself, and a whole-package sweep for a call whose definition was dropped |
| adversarial review | 12 findings, all fixed; a further 8 surfaced only once real translations existed - see "What the review caught" |
| **canary in-game** | built, installed, launched, `MainWindowTitle: [CANARY WINDOW]`, game reverted |
| game bible + glossary | **written** - `tl\game_prompt.md` (23k chars), `tl\quirks.md` (8.5k), 166 locked terms, 465 speakers named |
| **translation** | **DONE - 90,195 of 90,195 units (100%)** on `claude-sonnet-5` batch, 196 requests, 94.9% cache hit, **$6.63** |
| validation | every blocking check **0**: residual-jp, placeholder, control-code, overflow, degenerate, invented-backslash, invented-sentinel and all six engine traps |
| **English build in-game** | launched, `MainWindowTitle: [Holy Executor Artesia]`, 311 maps present under English names |
| **font metrics** | CALIBRATED against an in-game screenshot: Yu Gothic Light 22px in the 690px node. The 24px/670px guess made the validator accuse the author of overflowing 220 of their own 551 boxes; at the real metrics that is 70 |
| **menu positions** | 8 menu labels recentred horizontally on the author's own centre, resized to 0.80 so the Latin ink clears the frame, and 14 labels game-wide vertically centred on their plate; all verified from the OUTPUT rom |
| **font** | `GameSettings.gameFont` rewritten to `Yu Gothic Light`. The author names a font only a Japanese Windows has, and the substitute in play had no glyph for U+2661 - a character the SOURCE uses **229,107 times** |
| **layout repair** | 5,694 strings rebalanced, **5,809 orphan lines removed**, 0 defects over all 90,188 write sites (`tools\rebalance_verify.py`) - words, line counts and pagination all unchanged |

Total spend, including three smoke tests, the names pass and three shortening
retries: **about $7.20**.

### Cost, and where it actually goes

`claude-sonnet-5`, batch, effort `low`, 5m cache, 399 requests, 24,519 pending
units (24,703 dedup groups less the 184 that are pre-filled and locked).
**$6.18 if the cache is read on every request after the first, $11.54 if it is
written on every one.** Both are printed by `dryrun` on purpose: a batch
fans out independently, so most requests write rather than read, and measured
batches land at a 31-42% hit rate. Expect something around $7-8.

The reason the two bounds are so far apart is that **the cached prefix is bigger
than the payload**. Rules + bible + quirks is 11,717 tokens and the payload is
1.29M dynamic input against 8.75M prefix tokens once the roster fills. Three
levers, in the order they are worth pulling:

| lever | effect | why it is set where it is |
|---|---|---|
| `max_units` 80 -> 160 | ~halves the prefix cost, ~$3 | left at 80: inside the skill's 40-90 dialogue guidance, and a parse failure at 160 units loses twice the work. Raise it AFTER `smoke` passes |
| `roster_field_chars` | 12,317 -> 10,399 tok at 146 rows | set to 150. The glossary FILE keeps the full evidence; the cached block is a compressed one-liner by design |
| `roster_min` 25 | 465 speakers -> 146 rows | the tail is not unenforced, it arrives through per-request matched terms |

**Re-run `dryrun` after `tl.py names`.** The roster is empty until then, and
filling it takes the prefix from 11.7k to ~22k - the exact "a roster that grows
changes the estimate under you" trap.

---

## Before the first paid command

**Set `ANTHROPIC_API_KEY`.** Claude Code's own
`~/.claude/.credentials.json` is an OAuth token for the CLI and is **not** read
by the Anthropic SDK, so a working Claude Code says nothing about whether this
pipeline can authenticate. `artl/client.py` checks up front and fails with one
sentence rather than letting a 400-request run fail 400 times with a 401.

Everything up to and including `dryrun` and `selftest` needs no credentials.

## Run it

    py tl.py unpack        data.rbpack -> proj\   (descrambled rom tree)
    py tl.py roundtrip     GATE
    py tl.py export        proj\ -> work\units.jsonl + scripts.jsonl
    py tl.py layout        widget geometry -> layout.tsv
    py tl.py extract       work\ -> tl\units\*.json, seeds 465 speakers
    py tl.py noop          GATE
    py tl.py speakers      -> speakers.txt
    <write tl\game_prompt.md, tl\quirks.md, fill tl\glossary.json>
    py tl.py dryrun --show-sample
    py tl.py selftest
    py tl.py smoke         ONE real request, saves nothing
    py tl.py names         phase 1, into the glossary
    py tl.py submit        phase 2, the batch
    py tl.py watch         poll then fetch
    py tl.py validate
    py tl.py retry
    py tl.py ui            READ ui_review.txt
    py tl.py repeats       [--apply]
    py tl.py inject        -> out\   (runs the layout repair)
    py tl.py scan-output
    py tools\rebalance_verify.py   GATE - the repair moved whitespace only
    py tools\orphan_audit.py       what is left, and what it cost
    py tl.py patch         -> dist\
    py tools\canary.py install / uninstall

`live` replaces `submit`+`watch` at 2x the price and returns in minutes.

---

## What differs from the reference pipeline (Bakin / Miyutsure, r73294)

Every one of these was measured on this build, not inherited.

**1. There is no localization feature at all.** No `[Localizable]` attribute in
`common.dll`, no `LocalizeData` ExtraChunk, no `StringAttr.guid`. The reference
game's whole "audit the built-in table before believing it" section is moot
here - there is no table. Which fields hold player text is therefore a
MEASUREMENT, and `BakinTL census` / `BakinTL attrcensus` are what produce it.

**2. The rbpack header has no `hasLabel` bool.** The splash label follows the
discarded int64 directly, so the reference reader read the label's 7-bit length
prefix as the bool. `tools\rbpack.py` tries both layouts and lets the DRM MD5
decide.

**3. The resource index stores paths relative to `res\`** and its roots are not
the reference game's (`texture\`, `model\`, `character\3D\effekseer\`, ...).
The reference's root-anchored regex harvested nothing usable, so
`tools\index_walk.py` walks the index structurally instead: `[path][17-byte
record]` from `res_offset + 5`, next path exactly 17 bytes after the end of the
current one. Self-checking, and it terminated cleanly on entry 4,405 - all
4,405 confirmed served by the engine.

**4. There is no `Font` rom resource.** No per-widget font, no `Font.Size *
DefaultScale`, no `UseToMessageDefault`. One setting, `GameSettings.gameFont`,
and it names an **installed system font** (`游明朝 Demibold`) that is not in the
pack - so the player's screen depends on what they have installed, and so does
our measurement. `measure.py` reports every substitution rather than hiding it.

**5. `ReadMessage` has no `isWordWrap` parameter.** r73294 gained one wired to
`MenuItem.useMultiLineText`; r64268 always word-wraps the message path with
real font metrics and PAGINATES at `maxLineNum`. So the `wrap=0` this build's
layout data reports on the Message widget does not mean dialogue overflows, and
the corpus agrees: **11.8% of the shipped Japanese physical lines already
measure wider than the 690px panel**, which no author would ship if it clipped.
Overflow costs the player a key press, never text.

**6. The window title is `GameSettings.name`, not `meta.title`.** Both hold the
same Japanese string, so translating one and shipping the other looks exactly
like the whole patch failed. Found by the canary, which is the entire reason to
run one.

**7. `\H[castName]` has zero uses**, so Cast names are safe to translate on this
build. Re-check per game; do not carry the ruling across.

---

## The corpus

    90,195 units   3.44M JP characters   1,487 owners   465 nameplate speakers
    24,703 after dedup

| kind | units | distinct | what it is |
|---|---|---|---|
| `text` | 83,999 | 22,914 | dialogue and narration |
| `choice` | 2,855 | 238 | menu choices |
| `name` | 1,311 | 427 | item / skill / cast / condition / command names |
| `message` | 561 | 168 | battle and status log lines |
| `ui` | 551 | 167 | layout widget labels |
| `mapname` | 305 | 276 | location names |
| `desc` | 279 | 271 | item and skill descriptions |
| `term` | 171 | 156 | the engine's own system glossary |
| `strvar` | 103 | 93 | string-variable fragments |
| `telop` | 49 | 46 | full-screen chapter cards |
| `codearg` | 6 | 6 | display text inside a control code |
| `sptext` / `title` | 4 | 4 | fixed-coordinate labels, the game title |

### The scoping measurement that matters most

`BakinTL attrcensus` over all 6,105 scripts: of the ~20 (command, slot) pairs
that hold any string, only **12 ever hold Japanese**, and the picture is
unambiguous.

    DIALOGUE        slot 0   86,925 attrs   83,999 JP   22,914 distinct
    CHOICES         slots 1-6                2,855 JP
    MESSAGE         slot 0                     511 JP
    COMMENT         slot 0                     508 JP   <- EDITOR ONLY, excluded
    STRING_VARIABLE slot 1                     103 JP
    TELOP           slot 0                      49 JP
    SPTEXT          slot 1                       2 JP

`BakinTL census` walks every reachable object and finds 299 distinct
JP-bearing string-field paths, of which all but a dozen are editor names, asset
paths, dev-machine import paths (`C:\Users\PC_User\Desktop\アルテシア\ドット絵\...`,
2,174 of them) or folder categories. `GfxResourceBase.name` alone is 1,251
units of 3D model names never on screen.

**Both censuses are inputs, not reports.** Adding a field to the whitelist costs
money; leaving one out ships it untranslated, and no per-unit check can ever see
it - a string that was never extracted cannot fail anything.

---

## Deduplication: a measured departure from the standing rule

The skill's rule is "dialogue is scene-grouped and NOT deduped", because a line
reused in another scene can be right where it was translated and wrong
everywhere else. On this game that default costs **3.7x**, which is most of the
bill, so it was measured instead of assumed (`tools\dedup_risk.py`):

    83,999 dialogue units
    22,639 distinct bodies (nameplate stripped)
    22,914 distinct (speaker, body) pairs
    14,962 bodies reused across more than one owner   (65,817 units)
       156 bodies spoken by more than one speaker     (3,175 units)

The repeat distribution is not natural prose repetition - **10,113 sources occur
exactly 4 times and 7,156 exactly twice**, because the author duplicates whole
scenes per costume and per route variant. And the multi-speaker set is almost
entirely ellipses and moans (`……………`, `っ！`, `あっ♡`).

So dialogue IS deduped, keyed on **(speaker, body)** rather than body alone.
That costs 275 extra units and removes the pronoun class outright. What remains
- a line reused by the same speaker in a different scene - is caught after the
fact by `tl.py repeats`, which re-reviews any cluster carrying a third-person
pronoun or spoken by more than one speaker and never auto-unifies those.

Set `dedup_dialogue: false` in `artl.config.json` to fall back to the
conservative default.

---

## Control codes

The engine's table is 541 regex entries
(`Yukar.Common.Rom.GameContentParser.keyWords`, dumped to `tools\codes_raw.txt`).
**The game uses 20 shapes.** `tools\code_census.py` counts them and
`tools\backslash_audit.py` proves the inventory complete: 71,743 backslashes in
the corpus, 71,743 claimed, **zero unclaimed, zero literal `\\` pairs**.

    \NPL[name]   71,519   DISPLAY TEXT - the nameplate, 465 distinct speakers
    \$[var]         116   KEY
    \n               32   bare
    \z[n]            23   KEY
    \r[ruby]          4   resolved to its base spelling and NOT restored
    \#[var]           2   KEY
    ...content getters, a handful each

### The nameplate is markup, and that changes the whole speaker problem

`\NPL[アルテシア]` heads 85% of dialogue units. Speaker recovery is therefore
**exact**, not heuristic - the opposite of the RPG Maker pipelines, where the
nameplate is a rendered row and needs four gates to identify without eating the
first line of narration blocks. It also means:

* the 465 speakers ARE the glossary's name list, seeded automatically;
* the English name goes back INSIDE the code, so there is no `[Kurone]: `
  prefix artifact to strip;
* the nameplate has its own box - **234px at the narrowest of 36 slots, and it
  clips** - so a long English name is cut on 71,519 lines. `tl.py speakers`
  measures every name against it.

### Six traps that only ENGLISH can trigger

Recovered by decompiling `MessageReader.MessageEntry.separateByCommands`
(evidence and IL offsets in `ENGINE-CODES.md`). `tools\trap_audit.py` checks the
source corpus for the four a corpus scan can decide - the comma, the TAB, the
one-argument ruby and `\H[castName]` - and all four come back clean, so a hit in
the output is ours:

| trap | what happens |
|---|---|
| a `,` inside a bracket argument | `func()` splits on comma and consumers read `[0]`, so `\NPL[Smith, Jr.]` renders **`Smith`**. Japanese writes 、 and ，, never U+002C |
| a `]` inside a bracket argument | closes it early, the rest becomes visible text. **Checked on the VALUE, never with a whole-line regex** - the obvious regex matches across two codes on one line, and over this game's own source it flagged 22 correctly-rendering author lines |
| `\blinked` / `\blinks` | `commands` is matched by bare `StartsWith` before the char switch and then indexes `func()[0]` on an empty array |
| a real TAB | `replaceForFormat` parks `\\` on a TAB and converts every TAB back to `\` |
| a trailing `\` | CR/LF are tested before the escape flag, so it eats the next line's first character |
| `\b[x]` | every single-letter escape reads a following bracket group and DELETES it |

All six are hard failures in `validate.py`, checked on the RESTORED string, plus
two more the source can never warn you about:

* **`invented-backslash`** - the source has zero orphan backslashes, so any
  backslash not restored from a sentinel is the model's. Counted, and also
  matched against the engine's 541-keyword table so a swap (one code dropped,
  another invented) is not netted out to zero.
* **`invented-sentinel`** - a `⟦n⟧` the model ADDED. The placeholder check only
  fires when something is also missing, and on a unit with an empty codes map
  `unmask_codes` returns early, so the literal sentinel would ship on screen.
  **89,994 of 90,195 units have an empty codes map**, and `scan-output` is blind
  to it as well: an all-English line carrying a stray sentinel holds no Japanese
  and is never re-exported.

Two more are checked where the value is CONSTRUCTED rather than where it is
read, which is the only place the check can be precise. The speaker name and a
code-argument translation both go inside a bracket, so `codes.safe_code_arg`
rejects `]`, `,`, TAB and newline in the value before it is placed - and
`validate.glossary_issues` reports a bad name ONCE against the glossary row
rather than 42,695 times against the lines that character speaks.

---

## Text fitting

`BakinTL layout` reports **3,910 widgets, every one `sizeType = MANUAL`** and
`maxLineNum = 3`. Of the 2,569 that carry text, only **118 (4.6%) word-wrap**:

    wrap=0 clip=1   1,783   one line, CUT at size.X - text is LOST
    wrap=0 clip=0     668   one line, drawn past the box into its neighbour
    wrap=1            118   safe

So 95% cannot reflow and the fitting work here is **shortening**, not wrapping -
the inverse of the RPG Maker pipelines. Dialogue and telop are the exception and
are soft (see difference 5 above).

Measured budgets, from the narrowest slot drawing each getter:

    nameplate   234 px  clipped     message   670 px  3 lines, wraps + paginates
    partyname    84 px  clipped     itemname  154 px
    skillname   154 px              telop    1280 px  3 lines
    map          64 px  clipped

**The min-across-slots rule is a ranking heuristic, not an enforceable budget** -
a 64px box for a map name is obviously not the visual bound. So the overflow
check is DIFFERENTIAL: a slot is flagged only when the English is wider than the
Japanese it replaced, and the already-over count is reported separately.

### The font metrics were wrong, and the validator was accusing the author

Bakin r64268 has **no Font rom resource and no font-size field on any widget**.
There is one setting, `GameSettings.gameFont`, naming an *installed system font*
(`游明朝 Demibold`). Size is therefore not readable at all - it has to be
CALIBRATED, and the first pass simply guessed 24px in the 670px box.

The guess was wrong, and the tell was in the validator's own output: it reported
that **220 of 551 UI slots were already overflowed by the shipped Japanese**, one
of them declaring 26px while drawing 503px. An author who overflows 40% of their
own boxes is not a plausible author. That number is a metrics smoke alarm, and it
was read as a quirk of the game for far too long.

The only ground truth available was a screenshot of a real message box. Exactly
one (font, size, width) triple reproduces both the break point it shows *and* the
68-character line it fits on one row: **Yu Gothic Light at 22px in the 690px
node**. Note what that says about the font - `gameFont` asks for a Mincho that is
not installed on this machine, and the engine substituted a **sans**. A player
who has Yu Mincho sees different metrics, which is inherent to a game that names
an installed font instead of shipping one, and `measure.describe()` says so on
every run rather than hiding it.

Re-running every width-dependent check at the corrected metrics:

    author-overflowing slots   220 of 551  ->   70 of 551
    nameplate budget               360 px  ->  330 px
    overflow flags                      0  ->    0

The exclusion count falling by two thirds is independent corroboration; nothing
else was changed to produce it.

### Orphan lines: the defect every width check passes

With the metrics right, the engine's own wrap could be reimplemented exactly
(`artl/wrap.py`, transcribed from decompiled `MessageEntry.wordWrap`) and pointed
at the shipped English:

    EN   84,048 units   5,675 with an orphan (6.8%)   701 paginating
    JP   84,048 units   3,675 with an orphan (4.4%)  1,740 paginating

An orphan is a wrap tail under a third of the box - the author put a hard break
where the Japanese fitted, the English is longer, the engine wraps it, and one
word lands alone. Nothing overflows, so **every width check passes and the box
still looks machine-made.** (English paginates *less* than the Japanese here,
701 against 1,740, so the extra-key-press problem is the author's, not ours.)

`artl/balance.py` moves the break without touching a word. Two things make it
safe rather than a gamble:

* **`wordWrap` is width-triggered.** It only re-breaks a line whose measured
  width EXCEEDS the box, so a line that already fits is returned untouched.
  Choose lines that each fit and the engine renders exactly those. This is the
  condition that makes pre-wrapping legal in an engine that word-wraps, and it
  is checkable by reading the wrap function - not a property to assume.
* **The cost function charges the LAST line.** The standard Knuth-Plass measure
  leaves the final line free, because a paragraph is expected to end short. A
  three-line dialogue box is not a paragraph: with a free last line the optimum
  *is* the greedy wrap, so the first version of this pass dutifully returned its
  input unchanged and looked like a DP bug. Charging slack on every line
  minimises the sum of squared widths, whose optimum is equal lines.

    was  |You two look like you're arguing... don't you ever consider you're a |  614px
         |nuisance?                                                            |   94px
    now  |You two look like you're arguing... don't                            |  361px
         |you ever consider you're a nuisance?                                 |  341px

Refusals are as important as repairs. **Any line containing a control code is
left alone**, for two independent reasons: `\z[200]` sets `MessageParts.size` to
200% and scales every part after it, so the width is not knowable from the
string; and `\NPL[Sister Agatha]` carries a space *inside its bracket*, which a
whitespace tokeniser would split the code in half on. That costs 31 of 84,048
units (0.04%). `telop` is excluded outright - `LayoutStateTelop` is a third
layout node with no measured width that calls `wordWrap` **without**
`splitByLines`, so a mis-sized repair there overflows silently instead of costing
a key press. `message` uses 670, the smaller of the two declared Message nodes,
so its output fits whichever node is really live.

Results, verified end to end by `tools/rebalance_verify.py` against the exact
strings handed to BakinTL:

    write sites checked  90,188
    changed by the pass   5,694
    verified clean        5,694      words identical, line count identical,
    orphan lines removed  5,809      every produced line fits its box
    DEFECTS                   0

The pass runs inside `inject.render`, which the no-op path never calls -
`build_pairs(noop=True)` returns `u["raw"]` directly - so the byte-exact
round-trip gate still reads 329/329 with the repair enabled.

### The menu was mis-POSITIONED, not overflowing

A second screenshot showed the main menu with its labels sitting off their
plates. Every width check passed, and correctly: at layout metrics the English
is NARROWER than the Japanese on six of the seven menu items. Nothing
overflowed. The labels were in the wrong PLACE.

Bakin has no "centre this text in its box" flag on a `MenuItem`. Text is drawn
from `pos.X` with `origin = MiddleLeft`, so an author who wants a label centred
on its plate nudges `pos.X` by hand, once per label, against the width of the
Japanese string:

    idx  text          pos.X   drawn(JP)   centre
     17  アイテム           47        96      95.0
     18  スキル            60        72      96.0
     19  装備             72        48      96.0
     20  ファストトラベル       18       154      94.8   (scale.X 0.8)
     21  Hステータス         27       137      95.5
     22  セーブ            60        72      96.0
     23  コンフィグ          35       120      95.0

Seven strings from 48px to 154px wide landing on one centre within **1.2px**.
Replace the text and `pos.X` does not move, so each label drifts by half the
width difference - up to **31px** left, into the plate's end-cap. `artl/recentre.py`
restores it with `new_pos.X = pos.X + (drawn(JP) - drawn(EN)) / 2`, which keeps
each label's OWN centre rather than snapping the group to a common one.

**A group is required before anything moves.** One widget at `MiddleLeft` might
be hand-centred or might be plainly left-aligned at a margin, and shifting a
left-aligned label is a regression. From a GROUP they are trivially separable:
siblings whose `pos.X` values DIFFER while their source centres AGREE can only
be hand-centring, because left alignment would have given them all the same
`pos.X`. The pass refuses everything else and reports it. Across all 3,910
widgets in this game exactly **one** such group exists, so the whole fix is 7
labels - but the 7 were the entire visible defect.

### That group is also the best font-size instrument in the project

`layout_font_size` is **24px**, and the group proved it. N labels of differing
widths agreeing on a centre overdetermines the size - six independent
constraints on one unknown:

    size    centre spread across the seven labels
    20px            10.0 px
    22px             5.6 px
    24px             1.2 px   <-
    26px             3.5 px

That is a far sharper instrument than measuring glyphs in a screenshot, and it
is self-checking: a wrong size shows up as a group that fails to cohere rather
than as silently wrong offsets written into the rom. `selftest` asserts it
directly - it re-runs the detection at ±2px and requires both to cohere worse.

**So this game has TWO text sizes, and assuming one was the error underneath
everything.** The message box is 22px (the dialogue screenshot's wrap needs a
box in [678, 708), which the declared 690px Message node satisfies; at 24px it
would need [747, 774) and no declared node is that wide). Layout widgets are
24px. Two renderers, two built-in defaults, and no `Font` rom resource for
either to read.

### `size.X` was never enough to dump

The original layout dump carried `size.X` and the scale factors and nothing
else, which is why the pipeline could not see any of this. `BakinTL layout` now
also emits `pos`, `offset`, `origin`, `posType`, `image` and `useText`, because:

* **`pos`/`origin`** are what make a *collision* budget computable. 42% of this
  game's text widgets have `useClipping = 0` - they do not clip, they overlap
  their neighbour - so their real bound is the distance to the next widget, and
  without positions that distance does not exist.
* **`image`** is a background Guid. A label drawn on a plate is bounded by the
  picture, whose width no numeric attribute mentions. (On this game it is empty
  on every row - the menu plates come from elsewhere - but the field is dumped
  so the next game does not have to rediscover the question.)

Writing a position back rides the EXISTING inject path rather than a new one:
`SetField` gained a single non-string case for `posX`/`posY`, so the 7 fixes are
7 ordinary rows in `translated.jsonl` and are covered by the same byte-exact
gate as every other write. `MenuItem.pos` is an XNA `Vector2` **struct**, so the
boxed copy has to be written back or the assignment is silently lost.

### The size was wrong too, and only for LATIN

Centring the labels made a second defect visible: the glyphs crossed the
button's frame. The instinct is that the English is too long, and the data says
the opposite - at the same scale the English is roughly HALF the width of the
Japanese (Item 45px vs アイテム 96px). Width was never the problem.

**Height was, and only because Latin has descenders.** The plate is 192x35 and
its art (`window_02.png`, 9-sliced) draws its frame across y=7..56 of a 64px
texture, so the visible interior is about 27px. A 24px line box is 28px. CJK
sits inside its em square and never dips below the baseline; Latin hangs `g`,
`p`, `q` under it and pushes caps above the CJK cap line. Measured ink heights
at the same nominal size:

    アイテム 19px   Item 18px        装備 22px   Equip 22px
    コンフィグ 20px   Config 22px      セーブ 20px   Save 18px

So the English is not bigger on paper - it is bigger where the frame is
thinnest, and it fills an interior the Japanese only half used.

`MenuItem.scale.X` is the ONLY per-widget font size this engine has (one 72px
face drawn at `scale.X / 3`), so the fix is to lower it. Judged by compositing
the real plate texture with the real font - `tools/menu_mock.py`, which
reproduces the in-game screenshot before it is trusted to judge anything:

    x1.00   glyphs cross the frame on every button
    x0.90   still touching
    x0.85   two still touch
    x0.80   all eight clear

**0.80 is also the author's own number.** It is what they set by hand on
ファストトラベル and ゲームを終える, the two buttons whose Japanese ran longest.
Applying it to all eight fixes the fit and makes the menu uniform, which it was
not before. Shipped ink heights are 14-18px in a 27px interior.

### `origin` sets BOTH alignments, which is where the vertical went

With the labels centred and sized, they still sat low in their buttons - and one
of the eight did not. That asymmetry was the clue. `TextRenderer.ResetProperty`
maps `MenuItem.origin` to a horizontal AND a vertical alignment:

    MiddleLeft -> vertical Center, horizontal Left
    TopLeft    -> vertical Top,    horizontal Left

and `TextDrawer.DrawString(font, text, pos, boxSize, hAlign, vAlign, ...)` then
aligns inside the item's OWN box, not the plate under it:

    Center: y = pos.Y + size.Y/2 - textHeight/2
    Top:    y = pos.Y

Seven labels are `MiddleLeft` with a 45px box at `pos.Y = 2` on a 35px plate, so
they centre at 24.5 against a plate centre of 17.5 - **seven pixels low, with
the descenders clipped** by the sub container's own 35px window. The eighth,
Quit Game, is `TopLeft`, which lands it at 19.0 and looks centred. The odd one
out was the correctly placed one.

The correction is text-independent, which is what makes it safe:

    pos.Y = plateH/2 - size.Y/2        (-5 here)

Note the text height CANCELS for a `Middle*` label - centre is `pos.Y +
size.Y/2` whatever the string is. It does not cancel for `Top*`, where centring
would ride on our estimate of the engine's line height, so `Top*` and `Bottom*`
are reported rather than moved. Quit Game keeps its 1.5px offset for exactly
that reason: consistency at that scale is not worth a metric-sensitive
correction.

### Centring the LINE BOX is not centring the TEXT

Setting `pos.Y = plateH/2 - size.Y/2` centres what `DrawString` centres: the
line box. That is font-independent and looked provably right - and on screen the
labels came out visibly HIGH, because the engine's native line height is much
taller than the visible ink and not symmetric about it.

The size of that error is not in the font's tables. For Yu Gothic Light at the
drawn size, every candidate metric disagrees with reality:

    hhea       predicts  -0.9 px
    OS/2 win   predicts  -0.6 px
    OS/2 typo  predicts  +0.1 px
    MEASURED             -5.32 px

`Font.measureString` is native (kmyCore) and does something none of them
describe, so it was measured off the screen instead.
`tools/vcentre_calibrate.py` screenshots the running game, finds each button's
frame lines (rows where nearly every pixel is bright) and its text ink (sparse
rows between them), and reports the gap between the two centres. It recovers the
scale from the known 45px design pitch, so it works at any window size:

    button pitch 82.5 px against a design pitch of 45 -> scale 1.833
    median offset -9.8 capture px = -5.32 design px

Expressed as a fraction of the drawn size, because ascent, descent and cap
height all scale linearly with it: `layout_ink_offset_ratio = -0.277`. Read
labels WITHOUT descenders - `Item`, `Skill`, `Save` - because their ink box is
exactly the cap band; the two labels with a `g` or `q` read -7.0 and -6.5
instead of -9.8 and would bias the constant.

Two things this cost, both worth recording:

* **The override has to reach the calibration.** `vcentre` first read `scale.X`
  off the source rows, where it is still 1.0 - but these labels SHIP at 0.8. The
  offset was computed for a size they do not render at, the resulting shift fell
  under `MIN_VSHIFT_PX`, and the pass silently moved nothing. A resize and a
  reposition that are computed from different assumptions is a bug that reports
  success.
* **A constant measured on one screen does not license changing every screen.**
  Adding the offset term took the candidate list from 15 labels to **207**,
  across Config, Inn, Shop, Member, Dictionary and Title - none of which has
  ever been rendered here, and most of which sit at `pos.Y = 0` in the author's
  own data. `layout_vcentre_nodes` now limits the pass to nodes whose screen has
  actually been captured and measured. One is listed.

### A panel is not a button, so it needs the author's consent

The same ink offset applies to a label centred inside a PANEL - the inn's
`Money` box sat 6.6px high for exactly the same reason - but a panel cannot be
treated like a button. A `MENU_SUB_CONTAINER` is a button and its label belongs
centred on it by definition. A `RENDER_CONTAINER` is a panel holding several
things at deliberate positions, and centring all of them would be vandalism.

Two gates, and the scoping took three attempts to get honest:

* **The author must have shown the intent.** The money panel is 186x98 with a
  rule across it at y=48, and its heading is a 40px box at `pos.Y = 4` - box
  centre 24, which is exactly the top cell's centre. That is the author saying
  "centred here", and all that is wrong is the ink offset. A label whose box
  centre is NOT its band's centre is deliberately placed and is left alone;
  1,031 were declined on that test. Note the band: a panel split by a rule is
  two cells, and a heading centred in the top cell is not centred in the panel.
* **The panel must be an APPROVED SHAPE**, not merely in an approved node.
  Scoping by node let every Middle* label in any screen that happened to
  contain a money panel through - `BattleResult`, `MainMenu`, and the DIALOGUE
  NAMEPLATE - 487 of them. A shape is one widget, verified once and identical
  everywhere it appears. `186x98` yields 26 labels, every one of them that same
  money panel.

One more trap on the way: the panel branch returned early, before the `Middle*`
test the button branch relies on, so its first run cheerfully "centred" the
money panel's right-aligned `\money` VALUE - a `TopRight` widget the engine
does not centre at all. An early return that skips a shared precondition is a
bug that reports success.

**The vertical offset is the author's, not the translation's.** The Japanese sat
equally low, and the same habit appears on the title screen and the fast-travel
list. It is a deliberate improvement, gated on `config.layout_vcentre`.

And it needs the same discipline as the horizontal fix. A first pass matched
**240** labels; the save-slot screen puts five fields on one 80px plate at
`pos.Y` 4 and 38, and centring them would have piled them on top of each other.
`pos.Y` is also how an author STACKS labels, so the pass acts only where a
label is ALONE on its plate - 15 game-wide, 14 writable - and counts the 689 it
declined.

Getting there needed the widget TREE, which `ParseAllItems` flattens away.
`BakinTL layout` now emits `parent` and `layoutType` by matching object identity
against the flat list, so a label's plate can be found by walking up to its
`MENU_SUB_CONTAINER` and reading the plate size off the `MENU_CONTAINER` that
defines it - `size` on the sub item itself is overwritten at run time by
`MenuSubContainer.CreateWindow` and is not the plate.

Two supporting changes came out of the same pass. `recentre.adopt` pulls in a
sibling that shares a detected group's centre but not its anchor or box shape -
"Quit Game" is authored with `origin = TopLeft` and a 64x64 box while the other
seven are `MiddleLeft` 256x45, so `detect` bucketed it separately and it shipped
off centre while its neighbours were fixed. Once a group's centre is known it is
evidence in its own right. And `SetField` now writes `scaleX`/`scaleY` as well
as `posX`/`posY`, refusing a scale of 0 or one above 8 - a scale of 0 erases the
text and nothing downstream would notice.

One label was also degenerate rather than misplaced: 威信 came back as **"Prst"**,
which is not a word. It is now "Prestige" - narrower than the "Lewdness" already
rendering correctly in the same column, so it costs nothing. A survey of all 551
UI units found eleven more of the same shape and they are fixed too, the worst
being 魔力 rendered as **"MP"** directly beneath "Max MP" as a different stat.

### The font the game asks for decides which glyphs exist

`GameSettings.gameFont` names an INSTALLED system font - 游明朝 Demibold, which
only a Japanese Windows has. Everyone else gets whatever the native layer
substitutes, so **the glyph repertoire is chosen by the player's machine, not by
the game**. The substitute in play here had no U+2661 WHITE HEART SUIT, and the
source uses it **229,107 times across 50,427 units**. Every one drew as a tofu
box. Nothing else could see it: the text is correct, the codes are intact,
nothing overflows, no Japanese is left.

**Swapping the character is not a fix, and that is worth showing rather than
asserting.** The plausible substitutes have no heart at all:

    font                 ♡    ♥    ♪    ～    kana
    Yu Gothic Light      Y    Y    Y    Y    Y
    MS Gothic            Y    Y    Y    Y    Y
    Microsoft YaHei      .    .    .    Y    Y
    Microsoft JhengHei   .    .    .    Y    Y
    SimSun               .    .    .    Y    Y

There is nothing to fall back to, so the font has to be NAMED. `Yu Gothic Light`
is the only candidate that is all three of present, complete and already
measured:

* **present** - it shares `YuGothL.ttc` with `Yu Gothic UI Light`, and the Yu
  Gothic UI family is a Windows system font in every locale rather than part of
  the removable Japanese supplemental pack;
* **complete** - ♡ ♥ ♪ ～ kana kanji Latin, verified from its cmap;
* **already measured** - every metric here was calibrated against it, so naming
  it converts those from an assumption into a fact. `validate` now prints
  `font Yu Gothic Light` instead of `font SUBSTITUTED`.

The alternative is `gameFont = ""`, which makes `useSystemFont` false and loads
the game's own bundled `font.ttf` (M+SmileBoom) - GUARANTEED, because it ships
inside `data.rbpack`, and it covers everything. It is not the default because it
is a much wider bold face: at the engine's true 24px it takes dialogue
pagination from 687 units (0.8%) to **3,156 (3.8%)** and changes the game's
whole typeface. It is one config value away if a player reports tofu anyway.

(Read `GraphicsCore.createFont` carefully before trusting either branch. The
`useSystemFont = !IsNullOrEmpty(fontName)` line means an empty name really does
reach `font.ttf`; the `mGameFont = "メイリオ"` fallback below it sits *after* the
`!useSystemFont` early return and is unreachable.)

`tools/glyph_audit.py` is the check that finds this class without a screenshot:
it diffs the shipped corpus against the chosen font's cmap and reports the
substitutes' coverage alongside. `selftest` now asserts both that the requested
font resolves without substitution and that no shipped character lacks a glyph.

### A label with no Japanese is never a unit, and that is a defect

The extractor takes a string when it contains Japanese. Usually right; wrong
when the label belongs to a GROUP whose other members were translated, because
the translation changes them and not it.

The H-status screen pairs two stat labels per row, and the author aligned them
by padding the short one with a leading IDEOGRAPHIC SPACE:

    攻撃力 ＋   pos.X 121          　MP ＋   pos.X 127
    防御力 ＋   pos.X 123          　HP ＋   pos.X 132

`　魔力 ＋` carries the same padding and WAS extracted - it has kanji - so its
translation "Mana +" dropped the space and that row lines up. `　MP ＋` and
`　HP ＋` are pure Latin (U+3000, `MP`, U+FF0B), were never extracted, and still
carry a 24px indent their partners lost. Two rows aligned and two did not, which
is exactly what the screen showed.

`config.layout_literal_fixups` writes them, and `align_to_partner` also copies
`pos.X` from the translated sibling, because the author's 6-9px offset was
compensating for full-width text that is no longer there. The partner match has
to key on the trailing `＋` as well as the container and anchor - without it the
row's other four labels all qualify, nothing is aligned, and the pass does half
the job while reporting success.

**Sweep for the class, not the instance.** Layout labels that were never
extracted AND carry full-width typography: 3 strings, 125 widgets. Two are these.
The third is `　\\itemnum` (119 uses), a deliberate gap between an item name
and its count - a spacer, not a label, and deliberately left alone.

### Gendered nouns are a misgender the pronoun check cannot see

`validate` compares PRONOUNS against the SPEAKER's gender. This is neither: a
gendered NOUN applied to the ADDRESSEE.

    \\NPL[人間観察おじさん]君ってそんなやつなんだね！？
    ->  "You're really that kind of guy!?"

`やつ` is gender-neutral and the addressee is the female protagonist, so "guy" is
gender the translation invented. Fluent English, no placeholders, no residual
Japanese, fits its box - every automated check passes it.

`tools/gender_scan.py` runs two passes, and the ratio between them is the point:

    wide    male term where the Japanese word is neutral      480 hits
    narrow  male noun predicated of "YOU", second-person JP,
            speaker is not the protagonist                     11 hits, 2 real

The wide pass is mostly correct hits - the neutral word referred to a man who
really is one - and a list of 480 nobody reads is not a check. The narrow pass
is short enough to read by hand, which is what makes it useful. Both defects it
found are fixed; the 8 that remain are all about an actual third party.

### The output scan shared the extractor's blind spot

A Condition stores its battle messages TWICE - the flat `messageForAlly` family,
and again at

    Condition.EffectParamSettings.EffectParamList[].Message

a settable string property on an element of a list behind a property. **The
engine reads the nested copy.** Translating only the flat one left
`Artesia は麻痺してしまった！` on screen while every unit in the store was
translated and every check was green.

`ROM_TEXT_FIELDS` cannot reach it - that table is flat field names - so the
strings were never units. And `tl.py scan-output` could not see them either,
because it RE-EXTRACTS the injected tree and so inherits the extractor's blind
spot exactly. It printed `never extracted as a unit: 0` over 50 Japanese
strings in the shipped rom. **A check built on the extraction can only ever
confirm what the extraction can reach.**

The fix needed three pieces:

* `BakinTL effectparams` dumps the list WITH ITS INDEX, which is what makes a
  write address possible at all;
* `SetField` now resolves a dotted path -
  `EffectParamSettings.EffectParamList[3].ChangeParam` - and sets a string
  PROPERTY as well as a field, refusing the write if any hop is missing so a
  stale index can never land in the wrong element;
* the pairs are filled by SOURCE MATCH, not by translating again. All 33
  distinct nested strings are exact duplicates of strings already translated,
  so the two copies are guaranteed not to drift. A nested string with no
  translated twin is reported, never guessed at.

Both `Message` and `ChangeParam` are written: they read back identical, and
writing both is correct whether they alias or not.

### `census_gate.py` - the check that walks the rom instead of re-reading it

`BakinTL census` walks every field and property generically, so it sees what the
whitelist cannot. The catch is it sees EVERYTHING: 73,698 Japanese strings in
this game's output, almost all editor metadata. Raw census output is a haystack,
not a gate.

So `tools/census_gate.py` classifies each PATH and fails only on what it cannot
account for:

    editor-name  53,427     asset-path   5,574     tag        91
    script-attr  14,160     editor-help    285     formula    44
    code-key        111     key              6     REVIEW      0

Two rules earn their place. **`usName` is not `text`** - it is the layout
editor's own label for a widget, never drawn. And **a value whose Japanese
survives only inside a code argument is a KEY**, judged on the VALUE rather than
the path: `MenuItem.text` is a genuine display field, so excusing that whole
path would hide a real untranslated label, while excusing one value because its
Japanese is all inside `\$[...]` is safe.

**REVIEW defaulting to a failure is the whole point.** A new build, a
re-extraction or a game update can introduce a path holding player text, and the
only safe default is to fail on a path nobody has looked at.

### The MP cost was never doubled by us - the FIT was

A skill tooltip showed "MP Cost: 40" twice: once as the last line of the
description, spilling over the panel separator, and again in its own row below.

The duplication is the AUTHOR's. They embedded the cost in the description text
itself - `威信を込めた腹部への一撃。...
消費MP40` - while the layout ALSO draws it
from `\currentskillconsumptionmp`. **31 skill descriptions do this**, and the
Japanese showed it twice as well.

What the translation broke is the FIT. The description slot is 360x128,
`wordWrap=1`, so the embedded cost line only works while the prose fits the rows
above it. (`maxLineNum` is NOT the bound here - `TextRenderer` never reads it;
only the MESSAGE path does. A layout label is bounded by `size.Y` and clipping,
so the extra row is DRAWN, which is why it lands on the separator instead of
vanishing.) Measured at the real slot width:

    over 3 lines in JAPANESE :  3 / 31   (the author already overflows these)
    over 3 lines in ENGLISH  : 19 / 31
    ...with the cost line removed :  2 / 31

**Removing the embedded cost line would have fixed 17 of the 19 in one edit, and
it was the wrong call.** The tempting argument is that the separate row makes it
redundant - and it does, in `BattleSkill`, `BattleSkill_1`, `SkillSelect` and
`SkillSelect_1`. But the layout node `スキル` carries `Usage = BattleSkill`, is a
`UserResource`, draws a skill description, and has NO cost row anywhere in it.
With two user nodes competing for one usage there is no way to prove `スキル`
never renders, and if it does, dropping the line deletes the only place the cost
appears. **A fix that is correct only if an unverifiable assumption holds is not
the narrow fix, it is the risky one.**

So the prose was shortened instead - safe in every node, loses nothing, and it
is the remedy the skill prescribes for text that cannot fit. All 19 now render
in 3 lines.

Two things the measurement taught that arithmetic did not:

* **The usable width is well under `lines x width`.** 2 lines of 360px is 720px
  of capacity on paper; word granularity puts the real ceiling near **640px**,
  because after any legal first break the remainder still has to fit. Six
  rewrites that were comfortably under 720 still needed a third line.
* **A balanced re-break fixes some of these without touching a word** - the same
  DP as the dialogue orphan pass - but only where the prose genuinely fits the
  line count and greedy wrapping was wasting the room. `_split_points` returning
  None is the honest signal that no legal split exists and the text itself has
  to give.

Two author inconsistencies were preserved rather than silently corrected:
`淫心・ブローケン` describes itself as 淫口 (mouth) while counting 誘惑 (seduction),
and `淫胸・ボルテクス` says 淫胸 (breasts) while counting おまんこ. Both are the
author's own copy-paste, and the patch is not the place to reinterpret them.

### "102text" was the author's typo, hiding in the same blind spot

The battle-result gauge read `102text`. The source is

    \partystatus[0][10]text

- a stray literal `text` the author typed after the getter. It has no Japanese,
so it was never extracted, so nothing in this pipeline could reach it, and it
shipped in the Japanese release exactly the same way.

That is the never-extracted class again, with a new face: it holds not only
labels that need normalising but **the author's own mistakes**, and those are
the ones a player blames the patch for. One declared literal fixes it.

Fixing it exposed a real bug in `_literal_fixups`: it read `layout.tsv` RAW while
writing the rom form, so the TSV's escaped `\\partystatus` never matched the
configured `\partystatus` and the fixup silently did nothing. It now reads
through `budgets.load_layout`, which un-escapes, so both sides are in rom form.
**A matcher and a writer that disagree about escaping fail silently by
construction** - the count simply does not go up.

### Two positions that are NOT measured, and say so

The same screen needed the "Level" label moved down into its triangle and the
"Next" row nudged lower. Those went into `config.layout_pos_overrides` as
literals, and the inject report labels them `hand-set positions (NOT measured)`.

They are the only geometry in this pipeline that is not derived. The
battle-result screen needs a won battle to reach, so it cannot be captured and
measured the way the menu was - and a number that cannot be reproduced should be
visibly marked as such rather than sitting among the calibrated ones looking
equally solid. Both are the AUTHOR's positions, untouched by any other pass.

---

## Delivery

The launcher unpacks `data.rbpack` into `%TEMP%\bakin_engine_tmp\<random>` on
every launch and only then starts `bakinplayer.exe` with
`/TMP="<cwd>\data"|"<launcher>"|"<tempDir>"|<dataVersion>` (verified by
decompiling `Form1.doExecuteEngine`). The folder is complete before the player
process exists, so it can simply be overlaid.

`BakinTLHook` is an `AppDomainManager` registered by three lines in
`data\bakinplayer.exe.config`. It runs before `Main`, reads `launchDir` and
`tempDir` out of `/TMP=`, deletes `tempDir\map\*.rbr` (translated map names
rename the rom files) and copies `<launchDir>\translation\` over the temp
folder. **No game binary is modified**; reverting is restoring one config file.

Shipped roms go out **scrambled** (M = 13), because that is the state the
launcher leaves everything it does not descramble. `data.rbpack` is never
rebuilt: the patch is ~48 MB of roms against a 1.7 GB pack.

**Proven in-game.** `tools\canary.py build install` put eight obviously-English
strings in, the game launched, and the process reported
`MainWindowTitle: [CANARY WINDOW]`. `uninstall` restored the config
byte-for-byte.

Translating map names is what makes the patch 48 MB rather than 18 MB: it
renames 305 rom files and forces the whole map set to ship. It is still correct
to do - five layout widgets draw the map-name getter, including a 1280x160
`MapName` banner.

---

## What the review caught

An independent adversarial pass over the Python package found twelve real
defects. All are fixed, and the two worth knowing about generalise:

**The validator was dead code.** `hard_issues` referenced `_BARE_ESCAPE_RE`, a
constant the adaptation deleted while keeping its call site - so the first
translated unit would have raised `NameError` and taken `validate`, `retry` and
`inject` with it. It survived because **the 41-check suite never called
`hard_issues` once**: it exercised `codes.output_traps` directly and the whole
validation layer not at all, and the store held zero translations, so the green
gate was green about nothing. The suite now drives every branch of the
validator, which is what took it from 41 checks to 57.

**A retry could not repair a deduped group.** `apply_results` filled only
siblings whose `tl` was EMPTY. On a retry every sibling already carries the bad
text, so a full `--all` re-run would have cost the whole bill and fixed 27% of
the corpus - measured: 24,703 representatives updated, **65,492 units left
holding the failing translation**, and the leftovers then read as a same-source
conflict the pipeline itself manufactured. Siblings are now overwritten unless
locked, verified in memory at 90,195 of 90,195.

The rest, briefly: 1,426 silent-beat lines and 113 pure-sentinel widgets would
have shipped a Japanese nameplate because they have no Japanese BODY and so
could never pass validation (now locked and pre-filled, so injection still
rewrites the plate); the `bracket-in-code-arg` regex matched across two codes on
a line and flagged 22 of the author's own lines; an invented `⟦n⟧` on a
code-free unit passed every check and shipped literally; `inject` passed the
glossary where a font-metrics object was expected, which silently disabled the
overflow gate it shares with `validate`; codeargs were substituted into a code
bracket with nothing checking them; `sampling_params` exact-matched the model id
where `price_for` substring-matches, so a dated id would have 400'd every
request; `BattleCommand.rbr` does not exist (those rows live in `Cast.rbr`) and
the engine's own `getRomFileName` says otherwise, so the file map is now derived
by reading the record signatures off the tree; and `parse.normalize_reply` was
never called, losing a recovery path the reference pipelines have.

What came back clean is worth recording too: the chunker (397 chunks, 24,703
units, zero duplicates and zero drops), the cache layout, the dedup identity
across five call sites, the pricing table, every BakinTL key shape, the
`render` step order, and a sweep of `hard_issues` + `render` over all 90,195
real units with zero exceptions.

---

## Files the catalog cannot reproduce

`roundtrip` finds exactly one: a map carrying a stray `Folder` record with
signature 768 (the editor's MAP ROOT folder) saved into a map file by an older
Bakin build. The writer does not emit it, so the file comes out 88 bytes shorter
and the Map record loses its 16-byte reference.

It holds no player-facing data, but "probably harmless" is not a reason to ship
a file the tooling cannot reproduce. `config.unwritable_files` lists it, its
units are skipped, and `inject.copy_through` restores the pristine bytes. The
cost is exactly one unit: `テストニンジャ` ("Test Ninja"), a developer test map
with no events and no dialogue.

`copy_through` also restores every other rom file the patch did not change, so
the shipped patch contains only files that actually differ.

---

## Layout of this folder

    artl\                the Python pipeline
      config.py          every per-game path and ruling, with its measurement
      codes.py           masking, the nameplate, ruby, CRLF, the six traps
      extract.py         work\units.jsonl -> the store
      inject.py          the store -> {key, en} -> BakinTL, + copy-through
      store.py           the store, the glossary, the dedup ruling
      requests.py        chunking, scene packing, pricing, apply
      prompts.py         base rules, per-kind instructions, roster, matched terms
      driver.py          batch + live, one request builder
      estimate.py        scope and cost, four ways to run the job
      validate.py        what blocks injection
      qa.py / qa_scan.py the passes no validator can do
      budgets.py         which pixel box each string has to fit
      measure.py         font resolution, and honest substitution
      parse.py           four escalating strategies for a broken reply
      client.py          the SDK client and token accounting
    BakinTL\             C# - binds to the game's common.dll
    BakinApi\            C# - reflects over common.dll, for when the API moves
    BakinRes\            C# - reads assets through the engine's resource layer
    BakinTLHook\         C# - the AppDomainManager overlay
    tools\               rbpack, scramble, index walk, censuses, audits, canary
    tests\selftest.py    41 offline checks
    tl\                  the store: glossary.json, game_prompt.md, units\
    ENGINE-CODES.md      the decompiled control-code reference
    README.md            the asset extraction half

---

## What the run actually cost, against the estimate

| | estimate | actual |
|---|---|---|
| requests | 196 | 196 |
| cache hit rate | 31-42% assumed | **94.9%** |
| batch | $9.95 at a 35% hit | **$6.63** |

The hit rate is the surprise and it is worth carrying forward: the skill records
31-42% for a batch and warns that 1h caching loses money below 53%. This run hit
**94.9%** at the 5m TTL - only 10 of 196 requests wrote the prefix, 186 read it.
Two things differ from the runs behind that figure: the prefix here is 32k
tokens rather than 8.8k, and `warm_cache` sent one live request first. Whichever
it was, 5m + warm is worth keeping.

The batch also behaved exactly as documented: `processing=196, succeeded=0` for
all 69 minutes, then 196 succeeded in one step.

---

## Not done yet

* Play-testing. The five-item matrix in the skill's
  `playtesting-and-release.md` has NOT been run - launching the title screen is
  not playing the game. `tl.py ui` wrote `ui_review.txt`; read it.
* Image translation. 3,395 images are extracted to `imgout\` / `imgpng\` in the
  game folder. `tools\image_triage.py audit\resources.tsv` ranks them by rom
  type and path shape: **123 to look at first**, 1,828 PBR channel maps to skip
  outright, 2,470 unclassified. It is a ranking, not an answer - nothing there
  proves a file does or does not carry text. `NSprite`/`NSpriteSet` are excluded
  because they reference a texture by guid and their own `path` is the bare
  `.\` prefix.
  Bakin injects a replaced image by REPOINTING `ResourceItem.path` at a path the
  pack does not contain and shipping the new file scrambled - the pack is never
  rebuilt.
* Save compatibility. Bakin saves are not yet analysed; do that before the first
  public release, not after the complaints.
* **Confirm the font on a machine that HAS `游明朝 Demibold`.** Every width here
  is measured through Yu Gothic Light, the substitute this machine picked. The
  calibration is sound for that substitute and the repair is stable under it,
  but a player with the requested Mincho gets different metrics and a few of
  the 5,694 rebalanced lines will not be optimal for them. Nothing breaks -
  `wordWrap` still wraps anything too wide - it is a polish ceiling, not a
  defect. Install the font, re-run `tools\orphan_audit.py`, and if the numbers
  move materially, re-derive `font_size` against a screenshot from that machine.
