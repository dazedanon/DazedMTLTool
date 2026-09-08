# Text Fitting - measuring the box before you wrap to it

Translated text that is correct and still unreadable is the most common way a patch
ships broken. EN runs 1.3-2× the JP, the boxes were authored around full-width
glyphs, and the failure is silent: the player just never sees the end of a line.

**Matching the source's line count is not enough.** A 1-line JP source that becomes
a 1-line EN string has "drifted" by zero lines and can still run off the screen.
Width is the binding constraint that most pipelines miss.

**But width is not the only constraint, and the two fight each other.** A widget
with a *fixed height* has a hard visible-row limit, and a row past it is clipped or
spills into a second box. RPG Maker's message window is the common case: a plugin
parameter reading `WindowHeight = this.fittingHeight(3) + 8` means exactly three
rows, forever. So:

- Horizontal capacity sets the **largest safe wrap width**.
- A fixed row limit sets a **floor** on how much text each line must carry.
- **Narrowing the wrap to fix a horizontal overflow produces more lines and makes a
  vertical overflow worse.** Never present a narrower wrap as the fix for clipping
  at the bottom. Against a fixed row limit the fix is often MORE text per line.

A wrap setting is valid only when every rendered line fits horizontally **and** the
rendered row count stays inside the visible-row limit. Report both numbers when you
recommend one. If nothing satisfies both, the answer is pagination, manual reflow,
or raising the widget's own height - not a narrower wrap.

Before any of that, establish **which kind of box you have**: fixed and clipped,
scrolling, paging, or auto-sizing to content. Only fixed boxes have a row limit, and
only auto-sizing boxes make line count genuinely cosmetic. Classify the window
before quoting any number.

This is a layout problem, so solve it deterministically. Do not pay a model to wrap
text - pay it only when the words genuinely do not fit at any breaking.

## Treat each visible field as its own layout check

A tooltip heading beside an icon and its description below it have different
budgets, even when they share a plate. Enumerate heading, body, cost/footer,
dynamic value and help block separately, with their actual font, inset, scale
and visible bounds. Include untranslated ASCII siblings in the same draw path.
A passing count for descriptions does not cover headings.

Keep a glossary name intact when a modest local layout repair fits it. For a
single-line title, one option is a shrink-only uniform scale:

```
available = plate_width - title_inset - right_margin
scale = min(1, available / max(1, measured_title_width))
```

Apply this only to the affected heading draw call and preserve its vertical
position within the original heading line. Check a per-game readability floor;
if the required scale is too small, widen/reflow the widget or agree on a shorter
canonical label. Do not apply a global body-font reduction for one long title.
Calibrate with the source and capture the result. Nightfall's missed heading
led to an 89-title sweep and five repairs; details are in
[engine-gamemaker.md](engine-gamemaker.md).

### Expand the values the player actually sees

Measure substituted strings, not placeholder templates. Derive the reachable
rank/value variants from code or data, including word-valued substitutions that
may be wider than numbers, and review singular grammar at one. When a helper
panel combines several entries, measure that assembled block and the code that
allocates its height: a source newline count may reserve fewer rows than the
English wrapper draws. Keep these checks separate from token preservation.

## Step 1 - measure the box, two independent ways

### Geometrically, from the UI

For Unity uGUI/TMP, the number you need is the **visible** width, which is often not
the RectTransform width:

```
CanvasScaler: m_ReferenceResolution 800x450, m_ScreenMatchMode 1 (Expand)
  -> the canvas is always 800 units wide, at any window size or aspect
Dialogue RectTransform: m_SizeDelta.x = 959..1025, anchored centre
  -> ~80 units hang off EACH side of the screen
```

That gap is why TMP's own word wrap does not save you: `m_enableWordWrapping: 1` is
set, but it only engages at 959 units, well past the right edge. Text "fits the
rect" and is still cut off. Check `m_enableWordWrapping` **and** whether the rect is
wider than the canvas.

A full-width CJK glyph is ~1em = fontSize units. Score it 2 cells and a Latin
character 1 cell (they average ~0.5em), so one cell ≈ fontSize/2 units:

```
budget_cells = 2 * visible_canvas_width / fontSize
budget_lines = rect_height / (fontSize * 1.2)        # TMP default line spacing
```

At 800 units / fontSize 30 → **53 cells**. A 107-unit-tall box → **3 lines**.

### From the engine's own config, never with a pixel number

**Never copy pixels straight into a character-count setting.** A wrap width is in
cells, a window is in pixels, and the conversion is a measurement you have to make.
Resolve resolution and window outer size from the engine config and the plugin
sources (RPG Maker: `System.json` `advanced.screenWidth`/`screenHeight`, plus any
plugin that overrides the message window), then subtract:

```
padding, text inset, face/portrait reservation, icon widths,
column splits, plugin-added margins        -> usable pixels
```

Convert to a character count by measuring representative English glyphs in the
**actual font file**, or state the conservative average glyph width you used.

Derive the row limit as usable height divided by the **largest applicable line
height**, not the base font's. One `\FS[36]` run in a size-24 window costs more
than one row, and when a single shared setting must cover several font variants,
size it against the largest effective font.

### Empirically, from the source

The widest Japanese line the developer actually shipped in that box demonstrably
renders. Take the max JP line width per bucket, in the same cell metric.

**But the max is the wrong statistic, because authors overflow their own boxes.**
`wolf relayout --width auto` returned **88 cells** on one game and put English off
the right edge of the screen. Replace the max with a CENSUS: count *distinct source
strings* per line width, not lines, and look for the **cliff** rather than the peak.

    cells      66  68  70  72  74  76 | 78  80  86
    lines     360 330 162 522  46 133 |  12   1  12
    distinct   37  30  32  15  10   4 |   1   1   1

The box is 76. Past it the entire 85,501-line corpus holds **three** distinct
strings, each repeated, each shipped clipped in the Japanese original. Reading
*lines* hides this completely: a 9.7x dedup means 15 distinct strings account for
all 522 at 72, so the pile-up looks like a box boundary that is not there. Expand
every hand-pagination marker before measuring, too - a line the author manually
broke with a pad-plus-newline is two drawn lines, and measuring it joined invents a
width nothing renders. And before believing anything above the cliff, check whether
those lines are drawn SMALLER: if the corpus carries no font-size code at all,
nothing can legitimately hold them.

**Use the min of the two.** They agreeing is what makes the number trustworthy:
53 geometric vs 54 from the corpus, on a real game, is a strong signal. When they
disagree the corpus is usually the wrong one: one bucket's own Japanese implied 72
cells against a size-30 box, which means the developer's longest lines are clipped
in the original. Taking the min keeps you inside the box instead of inheriting
their bug.

If the renderer is instantiated from a prefab at runtime you may not find its
geometry at all - the object named `字幕/Subtitle` turned out to be the options-menu
*toggle*, not the subtitle renderer. Fall back to the corpus, and prefer the
conservative number: clipping loses words, and in an auto-sizing or scrolling box
wrapping more than necessary costs nothing. In a **fixed-row** box it is not free -
every cell you give up is text pushed toward the row limit, so there the conservative
width is bounded from below too.

### When the font size is unknown: calibrate from ONE clipped line

The geometric route needs a px-per-cell, and plenty of engines do not state
one. RPG Maker VX Ace draws at `Font.default_size` in `Font.default_name`, and
a game that assigns neither - common - leaves both to the engine default and to
whichever font the player happens to have. The window width is in the scripts,
the cell size is nowhere.

**Get it from the game, in one screenshot.** Inject a line you know is too
long, photograph it, count the characters that survived, and solve:

    a faced VX Ace line runs from new_line_x to (Graphics.width - padding)
    640 - 12 - 112                       = 516 px of drawable run
    "I trust you understand not a single person leaves this"  (54 chars)
    rendered  "...leaves t"              = 51 half-width characters
    516 / 51                             = 10.1 px per cell

Then confirm it against a real font rather than stopping at the arithmetic: MS
Gothic at 20 px clips that exact string at exactly 51 of 54, which pins
`Font.default_size = 20` and the cell at 10 px. `616 / 10 = 61` cells unfaced,
`504 / 10 = 50` faced.

Without that step the corpus is the only input, and on that game the corpus was
**wrong**: it said 66 and 56 cells, which at a 10 px cell are 660 px and 560 px
in boxes of 616 and 504. 255 of the author's own lines lose a character or two
off the right edge in the original, and a budget inherited from them clipped
the very first faced line in the game. This is the "developer's longest lines
are clipped" case above, met in the wild - and the screenshot is what turns
that warning into a number.

**The author's own line breaks cannot stand in for that screenshot.** The
tempting derivation is to sweep px-per-cell and pick the size at which the
author's breaks stop looking premature. There is no answer to find. Over 44,056
author-placed breaks in one game, the rate at which the next word would still
have fitted was 99.97% at 16 px and 90.52% at 24 px, falling monotonically and
bottoming out nowhere, because a Japanese author breaks at PHRASE boundaries and
not at the margin. **A curve with no minimum is the diagnostic**: the signal is
punctuation rather than geometry, and no amount of corpus buys you the cell size.

What the corpus CAN calibrate is geometry it was laid out against, never text it
contains. A group of labels agreeing on one centre pins a size (below), and one
line photographed mid-clip pins it exactly. Break positions do neither.

### When there is no shared box: the per-unit envelope

Bucket-wide budgets only work where every unit feeds the *same* widget (dialogue,
subtitles). Menus and prefabs are hundreds of individually-sized widgets, and one
budget for all of them is meaningless.

For those, constrain per unit: **the English may not occupy more space than the
Japanese did**, because that text demonstrably fitted.

```
envelope(unit) = (max JP line width, JP line count)
```

This is what caught a bonus-card panel whose JP ran 16/14/12 cells and whose EN came
back 17/20/19: TMP wrapped each line in two and the six-line result grew upward over
the card's title. Cards with wider Japanese were unaffected, exactly what a
per-unit envelope predicts and a bucket-wide budget cannot express.

Scope the envelope narrowly (e.g. only the 3-line message form that is the card
layout). Applied to a whole bucket it also catches wide warning banners that have
plenty of room, and compresses them for no reason - 62 false positives vs 3 real.

**Require the source to have been filling the box before you trust it as a bound.**
The envelope's whole premise is "this text fitted, so this much fits", which says
nothing when the author only wrote a few characters. `◆開発 / くじら1%` is 10 cells
in a credits panel with room for sixty, and holding the English to 10 would compress
it for no reason. A floor of ~18 cells on the source's widest line cut the same sweep
from 29 flagged units to 13, all genuine. Two shapes to gate on:

```
apply the envelope when   the source is multi-line          (a laid-out panel)
                    and   its widest line >= ~18 cells      (it was filling the box)
skip it when              the source is one short label     (a widget with slack)
```

`受付` at 8 cells becoming `Receptionist` at 12 renders fine, and every single-line
label in the game says the same thing: labels sit in widgets with slack, panels do
not.

## Measure visible length, not `len()`

**Strip everything that occupies no pixels before counting, and measure the widest
physical line rather than the string.** `\C[2]Hello\C[0]` counts twelve characters
wider than it draws, so an unstripped wrapper refuses lines that fit and breaks
lines that had room. Every wrap decision becomes uncorrelated with the screen.

Strip in this order. The list is the union of RPG Maker and Wolf shapes and serves
both engines:

1. bracketed codes: `\r[..]` ruby, `\c[..]`, `\cself[..]`, `\f[..]`, generic `\word[..]`
2. `\^` and the single-character escapes from the set `! " . \ <space> @ < > -`
3. bare `\letter`
4. transport placeholders: `__CODE_n__`, `__WOLF_CODE_\d+__`
5. legacy doubled forms: `[\\]+[cC]\[\d+\]`, `[\\]+[fF](\[\d+\])?`
6. catch-all `[\\]+.`
7. collapse whitespace runs, then strip

**Judge a multi-line value by its widest physical line.** Normalize `\r\n` and `\r`
to `\n`, split, take the max. Measuring the total instead gives real overflows a
place to hide inside multi-line values, and gets correctly fitting coloured or
ruby-annotated lines shredded by a bulk wrap pass. Use the *same* function for the
fit gate and for the wrapper, or the two disagree about which lines need work.

### The nameplate row is not a body row

Where the engine bakes the speaker into line 1, split the value into
`(window prefix, nameplate, body)` and measure and reflow **only the body**. The
nameplate renders above or outside the message box, so counting it makes every
spoken line look one row too tall, and a max-lines fit then shrinks fonts across the
whole game for no reason. A preview should paint that row with a marker and refuse
to ever flag it as overflow.

Make the split robust: normalize `\r\n` and `\r` first so CRLF nameplates still
split, and fall back to matching the stored `speaker` field against line 1 with any
leading font codes stripped, `re.sub(r"^(\\f\[\d+\])+", "", line1)`.

## Step 2 - the wrapping algorithm

**Two algorithms, and the box decides which.** Use the balanced-line DP below when
the box has room to spare and even-looking lines are the goal (subtitles, dialogue
in an auto-sizing or scrolling box). Use **greedy MAX-FILL** when a fixed row limit
is the binding constraint, because filling each line before breaking is what keeps
the row count down. The greedy version, with CJK 2-cell counting, kinsoku binding
and widow control, is in `engine-srpg-studio.md` under "THE WRAPPING ALGORITHM".
Its kinsoku and widow passes are engine-agnostic and worth bolting onto whichever
line-breaker you pick.

Balanced-line DP over word atoms. Cost per line is squared deviation from the ideal
length, minus a bonus for breaking after sentence punctuation:

```
cost(line) = ((width - ideal)/ideal)^2
           - 0.45  if the break falls after . ! ? … 。 ♥ ♪ ~
           - 0.15  if after , 、 - : ;
           + 1000 * (width - max_width)     if over budget      <-- REQUIRED
```

**The overflow term is not optional.** Without it the punctuation bonus buys an
unusable line: one string came back as `[30, 30, 54]` cells against a 53 budget
because breaking after `…is there…?` scored better than three balanced lines that
all fit. Width must dominate every aesthetic term.

**Charge the LAST line too - and prefer the formulation where you cannot forget
to.** Knuth-Plass leaves the final line free, which is right for a page of prose
and wrong for a 2-to-4 row message box: with no cost on the tail, the DP fills
line 1 to the brim and drops whatever is left onto line 2. That shipped

```
"Let me divine the path you should walk. It'll cost you 500G how"
"about it?"
```

- a legal break, inside the box, passing every width check, and obviously wrong
on screen. It is the same defect as "an awkward line break" on the playtest list,
arriving from the algorithm rather than from the author.

There are two ways to write this DP and only one of them can make that mistake:

| formulation | tail | verdict |
|---|---|---|
| minimise over **free line count**, cost = slack per line | free by default | **can orphan.** Weight the tail at ~0.6 - at 0.0 you get the orphan, at 1.0 it splits a short one-line unit in two to "balance" it |
| minimise for a **fixed `n_lines`**, cost = deviation from `total / n_lines` | charged inherently | **immune.** Every line including the last is measured against the same ideal |

`tools/Game Translation/Text Fitting/layout.py` is the second kind and gets that
string right unmodified. If you hand-roll the first kind - as a from-scratch
pipeline did, and paid for - the tail weight is not optional. Copy `layout.py`
unless you need something it does not do (it is not aware of masked control-code
sentinels or of a game font's own advance widths, so a pipeline measuring with
`fontTools` may still want its own line-breaker).

**The tail weight and the punctuation bonus are both needed, and neither alone is
enough.** With the tail charged but no punctuation bonus, the same string came out
`45/27` - balanced, still breaking between "It'll" and "cost". With both, it
breaks at the sentence: `39/33`. The reader hears the break, so putting it where
the sentence already stops is free and putting it mid-clause is not.

Atoms, not characters:
- Masked control codes (`⟦0⟧`) are single atoms. Never split one.
- Split on ASCII space/tab **and** the full-width space, but keep the separator with
  its atom: `　` (U+3000) is a pacing gap between gasps, not padding, and rejoining
  with a plain space changes how a line reads aloud.
- A separator *before* the first atom is a deliberate indent (an inner thought
  carried across lines). Glue it to that atom rather than dropping it.

## Step 3 - order of operations

```
1. restore the source's line count        (keeps the box rhythm and row footprint)
2. fit the box                            (mandatory)
     a. wrap each line independently, preserving the writer's breaks
     b. if that overruns the height, re-flow the whole string into the fewest
        lines that satisfy the width
3. re-apply the source's 　 indents        (cosmetic)
```

Step 1 is not merely cosmetic. In a fixed-row box the source's row count is also
evidence of what fits, and in a hand-laid-out panel it is the block's footprint
against surrounding art (see "Blank lines are structure").

### A wrapping widget has TWO budgets, and width is the one you will measure

The overflow check that measures rendered WIDTH cannot see a row-count failure,
because **every line in a row-count failure fits.** A pipeline reporting
`overflow: 0` can be shipping a panel that visibly repeats a line, and it will
keep reporting zero however hard you stare at it.

The case that taught this: a skill panel drew `MP Cost: 40` **twice** - once
spilling past the panel border, once in its proper place below. The slot
declared three rows, and the author had written the MP cost INTO the
description field behind a hard newline. So the author's own content owned row
three, the translated body got rows one and two, and English needing a third
row pushed the MP line to a fourth. Nothing was too wide. Nothing was
untranslated. The width check was right and useless.

Three things to take from it:

* **Count rows against the narrowest slot, at the scale the text will SHIP at**
  - a widget resized by a scale override wraps at `size.X / scale`, so reading
  the source's own scale measures a render that will not happen.
* **Part of the row budget may not be yours.** Where the author concatenates a
  field into a translatable string, your usable budget is `rows - 1`, and
  nothing in the string you were handed says so. Look at what the SOURCE put on
  each row before deciding how many you may use.
* **Separate the two failure populations when you report them**, because they
  fail differently and one of them is mostly not yours: a surplus row is
  DUPLICATED where the widget re-draws it and merely CLIPPED where the widget
  clips. The loud one is the bug report; the quiet one is usually pre-existing,
  and conflating them makes a font change look like it broke 65 things when it
  broke 22.

Re-measure this after ANY change to the font, the scale, or the wrap width. It
is the check most likely to go quietly red, because the thing it guards is a
count rather than a distance.

### A gate that shares a premise with the fix will CONFIRM the bug

The row-count check above was written in the same sitting as the fix it guards,
and both were built on "the description slot is the one drawing
`\currentitemdes`". That was wrong: the same database record is drawn by
several codes - `\currentskilldes` for skills, `\selectshopitemdes` for shops,
`\currentdictionarydes` for the compendium. The resize landed on the item
panels, the audit measured the item panels, the audit reported **zero**, and the
skill panel on the player's screen was byte-for-byte as broken as before. They
sent the identical screenshot a second time.

A new check is at its weakest precisely when you are most pleased with it,
because you have just finished reasoning your way to the fix and the check
inherits every assumption that reasoning made. Two habits are enough:

* **Derive the check's scope from the DATA, not from the constant you just
  typed.** Enumerate the widgets out of the layout by shape - "wraps, and draws
  a code that looks like a description" - so a panel nobody knew about is
  measured rather than missed. Print the enumeration (`--slots`), because a
  scope you cannot see is a scope you cannot audit.
* **Make the check reproduce the reported defect BEFORE you apply the fix.** A
  check that has never once gone red has not been tested; it has been written.
  If it cannot show you the bug the player photographed, it is not guarding
  that bug.

The generalisation is not about text fitting at all: whenever you write a check
and a fix from the same understanding, the check tests the understanding rather
than the software. Point it at the artifact instead - the built tree, the
running screen - where the fix's premise gets no vote.

Why 2a before 2b: flattening destroys deliberate breaks. `Rapid Fire・Starting
Coins×2 / Damage×0.5` became `Rapid Fire・Starting / Coins×2 Damage×0.5`, reading as
one garbled stat instead of two.

Why 2b exists at all: per-line wrapping can only *add* lines. Two 56-cell lines each
split in half give four, when re-flowing the same words freely fits three. A fourth
line is drawn outside the panel and is not seen, so height wins over break fidelity.

Why 3 is conditional: `　` is two cells, so restoring an indent can push a line that
was exactly at budget back over. Keep the indent only if it still fits. Decoration
loses to a clipped word.

## Step 4 - make it idempotent, then prove it

Running the pass twice must report zero changes. Two shapes of oscillation:

- Step 1 pulls width-driven extra lines back down to the source count, step 2 splits
  them again at different points, forever. Skip a unit that is already inside the box
  and not collapsed against its source.
- The early-out must consider everything the pass would do, including the indent
  restore, or the unit is "changed" every run.

Guard it with a test that runs the pass twice and asserts the second is a no-op.

### Idempotency can be an ACCIDENT of the wrap, and improving the wrap destroys it

The nastiest shape, because nothing in the code says so. A pager that cuts a
message into pages by chunking rows blindly survives a second pass **only because
greedy fill is start-index deterministic**: a break depends solely on which word a
line starts at, so any contiguous run of greedy rows re-merges and re-wraps to
exactly itself, and the chunker may therefore cut anywhere. Replace greedy with a
balanced wrap - strictly better typography - and balanced rows are shorter, so
re-wrapping a chunk of them yields different lines and pass 2 stops agreeing with
pass 1. **Fixing the pager is a prerequisite for improving the wrap, not an
independent quality item.**

The same edge bites one character at a time: appending a closing quote to a page's
last row changes that run's merged text, so the box no longer re-wraps to itself.
Any edit made to a laid-out row must be followed by re-normalising the page the way
the next pass will read it, and rejected if that costs a row.

Two habits make this safe rather than lucky:

- **Verify the fixed point at runtime, per unit, instead of arguing it.** Re-lay
  every emitted box exactly as the next run reads it - its own re-derived geometry,
  its own pre-fixup - and only write a layout whose every box comes back unchanged.
  Ladder the fallback: new algorithm → old algorithm → leave the unit as authored.
  A clever improvement that is wrong on one message then degrades instead of
  shipping broken.
- **Count and report the fall-through.** The last rung emits the unit with no
  wrapping and no page split at all, which is exactly how a 113-cell row reaches a
  76-cell box. A silent fallback reads as "covered everything" while it is the one
  path that ships unlaid-out text.

### A bulk pass has no reviewer, so put a postcondition on every path

**If the original had a newline and a non-blank body and the candidate has no
newline or a blank body, return the original unchanged.** This is not theoretical.
A group-wrap bug interacting with nameplate splitting left thousands of spoken lines
as `\f[N]Name\n` with an empty body, visible only in-game, because a bulk layout
pass rewrites every line in a bucket with no human review.

Two earlier bailouts on the same theme: a nameplate line whose body is *already*
empty is returned untouched rather than re-processed, and a non-empty body that
wraps to blank output keeps the original.

**Gate the pass so it only touches lines it has a reason to touch**: skip a line
unless it carries a font code, actually overflows, or would come out laid out
differently than it is now (`wrapped_as_is != text`). Turn the gate off only when
the operator explicitly requests a body font, so short lines still receive the
leading font code. The gate is what makes repeated calibrate-apply-retest cycles
safe and keeps re-runs from churning lines that are already correct.

## Step 5 - what wrapping cannot fix

Some units are simply too long: no breaking fits `total_width` into
`max_lines × max_width`. Report those separately, do not silently clip them, and
send them to a **shortening pass**: give the model the JP, the current EN, and the
exact budget in lines × cells, and ask for a tighter rewrite.

Prompt essentials: cut filler not content (drop intensifiers, contract, prefer the
shorter synonym, trim discourse padding), keep every fact, name, number, keep tone,
register and explicitness unchanged, keep control codes and honorifics. Loop it -
it converges over 2-4 rounds, and the last stubborn one or two are faster to write
by hand than to re-prompt.

## Calibrate the budget against the AUTHOR's lines, not your derived maximum

Deriving the box geometry gives you a CEILING. Using that ceiling as the wrap
target is a mistake, and it fails in a way that looks like success: every
per-unit check passes, because every line is inside the number you computed.

A player reported a line running off the message box. It was
`"Those idle little moments had become something irreplaceable to him."` -
**exactly 68 characters**, against a derived budget of exactly 68. The
translation had arrived correctly broken across two lines and the wrapper
JOINED them, because 68 read as a perfect fit. Re-deriving the geometry only
confirmed the arithmetic (the window plugin really was `boxWidth - 40*2`,
padding 12, `newLineX` 4, no `\FS`/`\{` escape in that scene, no plugin
overriding `mainFontSize`), so a few pixels of the real window were never
accounted for - and from a screenshot they never will be.

**Measure the source corpus instead.** Render every one of the author's own
lines with the real font at the real size and take the distribution:

```
author JP  n=18137  max 800  p99 600  p95 520   >640px  43   >660px  28
EN before  n=17076  max 780  p99 670  p95 630   >640px 559   >660px 235
EN after   n=17510  max 780  p99 630  p95 600   >640px   8   >660px   6
```

The author's p99 is 600 px and only 0.15% of their lines pass 660 - so their
working ceiling is ~64 cells, and the 70 the geometry allows is a number they
never use. Filling the derived maximum had made the English systematically
wider than the Japanese it replaced. Anything above the author's ceiling is
also where you find lines *they* shipped clipped, so it is not evidence the box
is bigger.

**Then price the change in ROWS before making it**, because narrowing the width
pushes text onto more lines and the row count is usually the hard limit:

```
width  units over max_rows
  68     0        <- the old budget
  64     0        <- free
  62     2
  60     4
```

64 was free; 62 would have pushed two units to 5 rows in a 4-row window, and the
only fixes there are shortening the text (degrades the translation) or adding a
message page (changes command counts and breaks save compatibility). That makes
64 the floor - a measured constraint, not a preference. Re-wrapping at it moved
2,133 lines and left the structural proof untouched, because a re-wrap only
redistributes text inside the slots a unit already owns.

### A game may switch FONTS mid-game, and the second font is not measured

Do not assume `advanced.mainFontFilename` is the font your text renders in.
This game's recollection room issues `Keke_AnyTimeFontChange` between `ドット`
(`x12y12pxMaruMinyaM`, monospace, every Latin glyph exactly 0.5 em) and `普通`
(`f910-shin-comic`, **proportional**, Latin advances 0.225-0.942 em). A
one-cell-per-Latin-character measurer is exact for the first and wrong for the
second.

Check which one actually binds before rebuilding the measurer. Compared across
11,240 English lines, the proportional font ran up to **1.254x** wider on short
runs of repeated letters (`"Nnnnnnnhhhh——————...♡"`) but NARROWER on long ones -
86 lines over 660 px against the monospace font's 236. So the monospace font
stayed the binding constraint, and the fix was the budget, not the model. Grep
`data/` for the font-change plugin command to find the switch at all; nothing
else in the pipeline will tell you it exists.

## Shrinking the font changes the budget, so re-derive it every step

Where the box is a fixed pixel width and the engine honours inline size codes, a
smaller font buys character budget. **Re-wrap at the rescaled width on each shrink
step, never at the original width.** Without the per-step rescale the loop converges
on a font far smaller than needed and English dialogue ends up microscopic.

```
wrap the body at the calibrated `width`
while soft_lines > max_lines:                       # hard cap: 64 iterations
    current = font size inferred from the text
    if current <= min_font: bail                    # 8 is a sane floor
    rescale every inline font code to current - 1
    width_eff = max(1, round(width * native / current))
    re-wrap at width_eff
```

`native` is the box's design font size: from the caller, else inferred from the
text, else a documented default such as 18. **Take `native` from the Japanese
source's own font code when the translation carries none**, so shrink ratios stay
anchored to the design size rather than to whatever the model emitted. If the text
has no font code at all and still overruns the line budget, inject the native size
first and then reflow. `max_lines <= 0` means wrap-only with no shrink. Without the
floor and the iteration cap a pathological line shrinks to unreadable or spins.

## A text outline does not scale, so shrinking the font thins the glyph into it

Before lowering a font size to buy room, check what is drawn AROUND the glyphs.
In RPG Maker MZ `Bitmap.outlineWidth` is `3` and almost nothing changes it, so
`_drawTextOutline` strokes a 3px round-join halo at **every** font size while
the glyph strokes scale with the size. Shrinking the font therefore does not
scale the text down - it thins the letterforms underneath a halo that stays put:

```
28px  strokes ~2.33px  vs 3px outline   letters hold
24px  strokes  2.00px  vs 3px outline   halo eats the strokes, counters of
22px  strokes ~1.83px  vs 3px outline   a/e/o fill in -> reads as mush
```

Two sizes shipped on a game before a player called both "blurry", because the
reasoning had been purely about the glyph grid. That grid analysis was correct
and irrelevant: `x12y12pxMaruMinyaM.ttf` has unitsPerEm 1200 with every outline
coordinate on a 50-unit grid, so it rasterises with **zero** antialiased pixels
at 12/24/36/48 - and 24 still looked far worse than the unaligned 28 the author
shipped. **Stroke-to-outline ratio beats pixel alignment.** A pixel-exact raster
is worth nothing if the outline is thicker than the strokes it surrounds.

Verify by rendering, not by reasoning: draw the real string with the real font
through the real pipeline (outline stroke first at its real width and alpha,
then the fill), upscale NEAREST, and look at it. The ordering is obvious at 3x
and no amount of arithmetic substitutes for it.

So on any pixel-font game, **prefer moving the text to shrinking it.** Where the
widget exposes a per-item position - `EventLabel`'s `<LB_X:n>`, a picture's x,
a window's origin - an offset costs zero legibility and zero translation
quality, while a smaller font costs both. Reach for the size only when there is
nowhere to move to.

## Lay out a row, don't nudge one label

When captions are centred on their own object (`Sprite.anchor.x = 0.5`), a
single overflowing label is the visible symptom of a layout problem, and fixing
just that one leaves its neighbours to collide later. Treat each ROW as a small
1-D packing problem instead - only same-row items can touch, since different
rows are already separated vertically:

- keep every item inside the container (`MARGIN` from each edge)
- keep `GAP` px between neighbours
- otherwise stay as close to the item's home position as those allow
- treat any caption still in the source language as a FIXED obstacle: the
  author's layout applies to it, and that is also what keeps an empty-store
  no-op test honest, since then every label is immovable

Relax to a fixed point rather than solving in closed form. The constraints pull
against each other, rows hold a handful of items, and 64 iterations of "push
overlapping pairs apart, then clamp to the edges" is both shorter and more
obviously correct than the case analysis. Doing this let a game keep its
author's font size at **0 off-map and 0 overlaps**, where the shrunken font had
still left one collision.

Measure the result with an audit that reports both failure modes separately -
off-container and same-row overlap - and run it at the old size too, so the
change is a comparison and not a hope.

## Counting pitfalls

- **Trailing `\r`.** CSV cells routinely end with one, and many parsers drop every
  `\r` before display. Counting it invents a phantom empty line and produces
  "2 → 1" warnings on correct translations. Normalise CRLF, then drop **one**
  trailing terminator before counting.
- **U+FEFF is not whitespace to .NET.** `String.Trim()` leaves a BOM in place, so a
  key carrying one never matches. Strip it explicitly when normalising.
- **Engine auto-size is a fallback, not a fix.** Shrink-to-fit makes each box a
  different size and looks worse than a good break. Reach for it for the long tail
  of individually-sized widgets you cannot measure, not for dialogue. A *controlled*
  shrink under a fixed row limit is a different thing and is sometimes the only
  answer - see the shrink loop above.

## Validation

Re-measure after wrapping and report per bucket:

```
line counts:            1L=2328  2L=2281  3L=409     (none over the box height)
lines wider than box:   0
```

Feed the same budget into `validate` so the layout warning is width-aware. Once
wrapping legitimately adds lines to respect width, a bare line-count difference is
noise, not signal (433 warnings → 13 on a real run). Warn on lines *lost* against
the source, or lines still too wide. Extra lines added to fit are correct.

**Keep one definition of the box.** When `reflow` capped the width geometrically and
`shorten` did not, one reported 9 unfittable units while the other insisted
everything already fit. Derive it once, import it everywhere.

## Reference implementation

`tools/Game Translation/Text Fitting/layout.py` - atomiser, DP wrapper with the
overflow penalty, `fit_box`, `restore_indent`, cell-width function. Engine-agnostic,
its only assumption is the 2:1 full-width/Latin cell metric. Tests alongside it in
`test_layout.py`. Driven end-to-end from
`RP/Unity Mono PlayMaker (CoinPussy)/tl.py` (`reflow` / `shorten`).

## Calibrate the box once, then key it to a format bucket

**Store a calibrated width against the widget class the line belongs to, never
against the file or scene it was found in.** One global width silently under-wraps
face-window dialogue and over-wraps full-width narration. One width per file
re-solves the same box hundreds of times.

Calibration itself is cheap: an overflow is observed in-game, a fragment of the line
is retyped to locate it, and whatever width, max-lines and font are dialled in get
stored against that line's *format bucket* and applied bucket-wide.

| Content | Bucket key |
|---|---|
| dialogue, confident and low-confidence speaker tags alike | one `__format:spoken__` - they render in the same box |
| every other event-side tag (`ui`, `narration`, `choice`, …) | `__format:<tag>__`, `tag = re.sub(r"[^a-z0-9_]+", "_", src)` |
| database lines | by sheet, `group.typeName` |
| glossary / name entries | by DB category note |
| `Game.dat` | one bucket |

```json
{"default_width": 36,
 "sheets": {"__format:spoken__": {"width": 50, "max_lines": 3,
                                  "font": null, "speaker_src": "…"}}}
```

Migrate legacy keys on read.

**Print the blast radius before writing anything.** "N lines in this bucket, M
currently overflowing" is what catches a mis-identified bucket before it rewrites
3000 lines.

**Make the lookup fuzzy on purpose.** Text retyped off a screenshot never matches
the stored JSON byte for byte: lowercase both sides, fold curly apostrophes and
backticks to `'`, and if the direct substring test fails, re-test with all
whitespace collapsed - the stored line carries different soft breaks than the
rendered one. Search the translated tree, the raw files and the extract work dir
together, and on glossary/name files match the Japanese `source` too so a row is
reachable from either language.

## RPG Maker: two dialogue widths, and code 101 picks between them

**A face graphic on code 101 costs roughly 10 cells of message width, so wrap the
401s under it to a reduced budget.** Compute and supply a separate `faceWidth`
alongside the full-width `width`. A single global width tuned on faceless lines
overflows every face-graphic message, and nothing catches it until someone plays a
face scene - one of the most common shipped-patch defects.

Standard 101 parameters are `[faceFile, faceIndex, background, position]`, and MZ
appends the speaker name at `parameters[4]`. A 101 with `0 < len(parameters) < 4` is
the variant form where `parameters[0]` IS the name, so reading index 4
unconditionally crashes or misreads every MV-format command.

```python
if len(cmd.parameters) >= 4 and cmd.parameters[0]:   # non-empty face filename
    width = FACE_WIDTH                               # = WIDTH - 10
# clear the flag on the first command that is neither 401 nor -1
```

Set the flag even when 101 name translation is disabled - the layout consequence
does not depend on whether you touch the name. Evaluate it **after** speaker
resolution, so a speaker derived from the face name still narrows the box. On the
reference game: 50 cells with a face against 60 without.

Two things this test cannot see:

- **Plugin portraits.** Bust and standing-picture systems never pass through code
  101, so no `parameters[0]` check finds them. Document the detection gap and cover
  it by lowering the global `width` conservatively or with custom handling.
- **Icons and inline images.** `\I[n]` draws at a real pixel width. Counting it as
  zero-width text under-wraps every icon-heavy line.

When lifting the name out of a 101 for a `[Speaker]:` prefix, strip leading `\c[n]`
runs and unwrap `【Name】` to its inner text. The brackets are name-window styling
and must not leak into the prefix or into the glossary key.

Validate by simulating the final wrap over a deliberate stress set - short, median,
long, icon-heavy, control-code-heavy, font-changed (`\{`, `\}`, `\FS[n]`, custom
font codes, plugin scaling) and values with explicit hard line breaks - and report
both the widest rendered line and the row count for each case.

## Height and width are not the same failure - grade them separately

Before treating a row overflow as a defect, read the engine's draw loop and
find out what it actually does. VX Ace:

```ruby
def process_new_line(text, pos)
  ...
  if need_new_page?(text, pos)
    input_pause          # wait for a click
    new_page(text, pos)  # clear, redraw the face, carry on
```

A message taller than `visible_line_number` is **paginated**: the player
clicks, the rest is drawn, nothing is lost, and no commands are added so a
saved interpreter index stays valid. Meanwhile `process_normal_character`
advances x and draws without ever testing the right edge, so a line wider than
the contents bitmap is simply **cut off**.

Grading both as hard failures makes the pipeline pay a model to compress prose
the engine would have handled - a `tighten` pass that shortens correct text for
no reason. Grading neither loses words. Make width a hard failure and height a
soft note that reports how many extra page breaks the player will see, with a
threshold (two full pages of clicking for one line of dialogue IS worth
shortening).

Other engines differ: an auto-wrapping box makes width soft, and a fixed-height
box with no pagination makes height hard. The rule is to look, not to assume.

And "the engine" may not have one answer. On **Bakin** the behaviour is a pair of
per-widget data flags rather than a property of the runtime: `useMultiLineText`
turns on word-wrap to the declared `size.X`, and `useClipping` decides whether
text past the box is cut or merely drawn over the neighbour.

**A row cap in the same settings object may not apply to the widget you are
looking at.** Bakin's `MenuSettings.maxLineNum` reads like a universal limit and
is not: only the MESSAGE renderer consumes it, via `ReadMessage`/`splitByLines`.
The layout `TextRenderer` never references it and wraps by WIDTH alone, so a
wrapping label neither paginates nor drops rows - it keeps drawing them, bounded
only by `size.Y` and clipping. Grep the renderer for the field before you model
it as a cap; a limit nobody reads is not a limit.

On one Bakin game that split 4,204 text widgets into 13% that wrap (width soft,
height bounded by `size.Y`), 45% **clipped - text lost**, and 42% overflowing
visibly. Measure the flags, bucket the widgets, and grade each bucket by its own
rule; a single verdict for the game would have been wrong for 87% of it either
way.

That also decides what the fitting pass DOES. Where the widget does NOT reflow,
a single-line label cannot be re-flowed at all and the only remedy is
shortening - an engine can leave you with **no reflow option**, and then Step 5
is the whole job rather than the residue. Where it DOES reflow, whether you may
pre-wrap is not a matter of taste: it depends on whether the engine's wrap is
width-triggered (see "A pre-wrap is only safe if the engine's wrap is
WIDTH-TRIGGERED"). Bakin's is, so pre-wrapping there is safe and worthwhile.

## Rewrapping an already-translated patch

**Rewrap by inserting `\n` inside the existing `parameters[0]` of each 401. Never
split, merge, or re-index commands.** A save file stores a command index, so any
added or dropped command moves it. A page of `[101, 401, 401, 0]` stays
`[101, 401, 401, 0]`, each 401 keeps its own stored source, and
`parameters[0].replace("\n", " ")` must reproduce the pre-wrap text exactly. That
makes the pass lossless and repeatable at any width: wrap to 12, then widen to 40,
and `" ".join(rows) == text`.

This is also the binding constraint on the "join consecutive 401s for translation,
re-split on inject" rule - **the re-split must yield exactly the source command
count.**

Scope the traversal to a fixed allowlist rather than everything that looks like
text: display fields `Actors.profile` and `{Armors,Items,Skills,States,Weapons}
.description`, event codes `{122, 324, 325, 357, 401, 405}`, and skip `_original`
keys. `DAZEDTL_ROOT/util/rpgmaker_rewrap.py:30`

### Rewrap traps

- **`\n` is a line break only when not followed by `[`.** Expand with
  `re.sub(r"\\n(?!\[)", "\n", rendered)` before measuring. Without the negative
  lookahead, `\n[3]` (the actor-name control code) is read as a break and the width
  measurement is nonsense. `DAZEDTL_ROOT/util/rpgmaker_rewrap.py:689`
- **`<br>` must round-trip.** If the body contains `<br>` and no real newline,
  replace `<br>` with a space, wrap, then convert the resulting `\n` back to `<br>`.
  Wrapping a `<br>` string with a newline wrapper produces something the plugin
  renders as one long line. `DAZEDTL_ROOT/util/rpgmaker_rewrap.py:661`
- **A name-window control does not consume a body row, a literal speaker line
  does.** Counting rows for the row-overflow veto means splitting on `\n|<br>` and
  stripping a leading speaker line *only* when it is a name-window control
  (`\n<Name>` / `\k<Name>`), not when it is a literal `[Speaker]` line.
  `DAZEDTL_ROOT/util/rpgmaker_rewrap.py:693`
- **Row protection is right everywhere except 401.** Skipping text that would
  overflow the visible row count applies to code 405 scrolling text, database list
  and help fields, and notetag bodies. A message box pages rather than clipping, so
  code 401 is explicitly exempt.

### Preserve the container, rewrap only the body

Notetag bodies keep their delimiters (`<infowindow:…>`, `<dPlnText:…>`,
`<SG説明:…>` and the SG Client variant, `<sub_[123]:…>`, `<ExtendDesc:…>`,
`<ClassMessage>…</ClassMessage>`, `<コメント:…>`). Run a registry of patterns that
captures **only the body group** so plugin tags stay byte-exact, track an `occupied`
span list so two patterns cannot claim overlapping text, and splice edits back in
**reverse offset order** so earlier replacements do not invalidate later offsets.
`DAZEDTL_ROOT/util/rpgmaker_rewrap.py:610`

Bullet-led bodies wrap differently: keep `◆ ・ • ●` header lines on their own line
and word-wrap the body under them. `DAZEDTL_ROOT/util/dazedwrap.py:126`

A code-122 backtick expression takes the *literal two-character* `\n` and keeps its
`` ` `` open and `` `.`` close. A real newline there is a JavaScript syntax error.

## The box may not be a box - four sources of truth for a width budget

Before measuring anything, work out *what actually bounds this widget*. Get this
wrong and the check passes text that visibly clips, which is exactly what
happened on the Ajin Syoujyo main screen: three labels shipped broken with the
layout validator reporting zero overflows.

**1. A declared box.** `[glink width="600"]`, a Unity `RectTransform`, a fixed
span in an exe patch. Easy case, and the only one most pipelines model.

**2. No box at all - the widget sizes to its content.** A `glink` with no
`width=` grows to fit its text and runs into whatever is beside it. Assuming the
engine's *default* width here is the trap: 600 px default meant every label under
576 px passed, so "Advance to Next Day" sailed through and overlapped the screen
edge. With nothing declared, the shipped Japanese's own rendered width is the
budget - it is the only evidence of how much room the author left.

**3. A background image.** The day counter was drawn at `x=20` on
`blui/taskbar.png`, a **220 px** image. There is no attribute to read: the budget
is the picture's width, and no amount of text-fitting logic finds it unless you
go and look at what is underneath. Whenever a label sits on a plate, panel or
bar, inspect the asset and measure its **painted panel**, not automatically the
whole canvas. Transparent margins and a separate title can make those different
bounds. Transform the panel and the text ink into the same screen coordinates.

**4. A column in a data table**, drawn by a generic layout macro - see the next
section. The budget is the widest Japanese *in that column*.

For case 2 you can do better than the source width by measuring the **gap to the
next widget on the same row** - scan the file for other positioned tags with a
similar `y` and take the nearest larger `x`. Two cautions from doing it:

* Only trust the gap when the **Japanese fits inside it**. If the shipped source
  already exceeds the measured gap, those two widgets are not really adjacent
  (different scenes in one file, a conditional branch) and the number is
  meaningless. Fall back to the source width.
* A row tolerance of ±25 px will still pair unrelated widgets. On 59 flagged
  candidates only 10 had a trustworthy neighbour.

**Ship the ranked list rather than tuning the heuristic further.** Sort by
"measured neighbour" first, then by overflow ratio, and write `file:line`, both
widths and the limit to a review file. Ten entries worth a human glance beats a
detector that is confidently wrong about fifty.

## A painted subrectangle can be narrower than both canvas and viewport

Tropical Chase's results background was 816x624, but its purple body occupied
`[185,94,624,525)` (439x431). Numbers outside that body still fit the viewport,
so the original layout check passed a visible defect. The corrected native
check independently selects panel pixels by their color/alpha, selects text
ink from its rendered bitmap, transforms both bounds into screen space, and
requires a declared margin on all four sides. An empty selection is an error,
never a zero-overflow result. Calibrate the pixel predicate against a viewed
asset; rounded or irregular panels need a safe interior/mask, not their full
axis-aligned bounding box.

Reserve for **calculated totals**, which can have more digits than their input
counters. Cover partial tally stages and bonus/ending variants as well as the
final total. Preserve the reported ordinary values as a failing-before fixture.
Here, 42/56 old cases failed; the corrected display passed 112 cases across two
result maps, 14 stages and four counter profiles, with at least 24 px on each
side. These are this game's measurements, not universal layout defaults.

The repair widened only the painted body, retained the original gradient,
alpha and title, and centered the actual text sprite. Ordinary and five-digit
counter cases retained the original font size; exceptional totals used uniform
scaling. Pixels outside the allowed body region were identical (maximum channel
delta 0). Keep derived bitmaps owned by the sprite, dispose them on replacement
and destruction, and leave shared ImageManager assets and saved picture
coordinates alone. Check the actual consumer after a render update.

Reusable pure pixel/geometry tool: `tools/Game Translation/Text Fitting/panel_bounds.cjs`.
Its CLI recalculates margins from recorded native observations and ignores their
stored `pass` flags. It rejects empty bounds, invalid numbers, duplicate cases,
missing engine-health observations and unsupported rotation/skew. Replay is
not a new native render; the stable Tropical Chase pipeline contains the native
fixtures, before/after observations and the collector used to obtain them.

## One string, two widgets: the NARROW one is the budget

A name can be drawn in more than one place, and only the tightest draw decides
what fits. A VX Ace world map declares each destination once and draws it
twice:

```ruby
add_command(master[i][0][0], :ok, ...)      # Window_Command, window_width 140
draw_text(0, 0, contents_width, line_height, title)   # info window, 500 px
```

That is **11 cells** in the list and **47** in the title, from one string. The
name was translated against the wide one and shipped as `Baron, Royal Capit` in
the list. Nothing in the data hints that two widgets share the value - the only
way to find it is to grep the scripts for every read of that array.

So when a budget comes from a widget, check whether anything ELSE reads the
same field, and take the minimum. Where the two are far apart, the short form
is the one that ships and the long form belongs in whatever prose sits next to
it: the map pin reads `Orochi` and the description under it opens "A shrine
dedicated to the guardian deity".

**And check whether the widget you are squeezing has a second row you are not
using.** The same script declared `EXPLAN[n] = [line1, line2]` and drew both,
with the author's own comment saying so - but every entry filled only the first
element, so the descriptions had been compressed into 47 cells when 94 were
available. Reading the draw call, not the data, is what finds that.

## Text that lives in a data table: budget per COLUMN, not per table

A lot of on-screen text is not a tag attribute or a UI string at all - it is a
literal inside a table the game declares once and draws with a generic layout
macro:

```
f.item        = [ ["pk_t", "ピンクの注射器", "", 5, "tansakuui/pk_t.png", …], … ]
f.koko_status = [ ["隠れてオナニーした回数", 0], … ]
```

Same shape as an RPG Maker database, a Wolf DB, a Unity `ScriptableObject` array
or a CSV `TextAsset`. Tracing every draw site for every column is archaeology
against a moving target, and you will miss some.

**Use the shipped Japanese as the budget: whatever room the widest Japanese entry
in a column had, the English has too and no more.** Group the units by the
`(table, column)` they were declared in - parse `f.x = [ … ]` spans out of the
source, then count the commas before each literal's offset in its row.

**Per column is the whole point.** Budgeting per *table* is useless: these rows
mix a 250 px item name with a 1,100 px description, so a table-level budget lets
every short label grow to the longest description's width and reports nothing.
Splitting by column took a "0 problems" table-level scan to 51 real candidates.

### Sibling columns drawn at the same anchor

The other collision this exposes has nothing to do with neighbouring *widgets*:

```
[ptext text="&tf.koko_status[0]" x="&tf.x" y="&tf.y" size="26"]
[ptext text="&tf.koko_status[1]" x="&tf.x" y="&tf.y" size="26" align="right" width="320"]
```

Label and value share an `x`, and the value is right-aligned inside a 320 px box. So
the label's real budget is *the box minus the value*, and when it exceeds that
the two overlap mid-word - `Times masturbated in se0cret`, `Amount cum inside her
0Vagina`. Look for two draws at the same anchor with opposite alignment. That
pattern is a two-column row, and only one of the pair is free to grow.

### Don't strip sentinels before looking for a defect

Scanning translated descriptions for a lowercase→uppercase junction (a dropped
sentence break, since Japanese runs sentences together with no space) returned 29
hits, every one a false alarm. The scan had stripped sentinels first, and each
junction had a `<br>` sitting in it: `…epoxy resin⟦0⟧Obtained when…` renders as
two lines and is correct.

Strip sentinels to **measure width**. Never strip them to **judge a junction** -
the thing you removed is often exactly what makes the junction fine.

## The author's hard line breaks are now in the wrong place

Fitting text is not only about the string being too wide. In any engine where
the author wrapped the original **by hand**, every one of those breaks was
chosen against the *Japanese* metrics, and after translation they are all in the
wrong place. Japanese sets about half as wide as the English replacing it, so a
run that used to fill a line now overflows on its own - and the hard break
behind it turns that overflow into an orphan:

```
Affection rises through physical contact and using
the syringe,                                          <- the orphan
and Lewdness rises when you have sex.
```

The width check passes: no single line is over budget once the engine has
wrapped. The screen is still wrong. **Wrapping the text and placing the breaks
are two different problems, and only the first one shows up in an overflow
count.**

The fix is to delete the hard break wherever the run in front of it already
overflows, and let the engine wrap the paragraph as a whole. Removing a break
can only ever *reduce* the line count, never raise it, so it is safe even
against a message box that is only three lines tall.

Applies to `[r]` in TyranoScript/KAG, `\n` in RPG Maker and Wolf message
commands, and any engine whose scripts carry pre-wrapped prose.

### Four faults, not one

Chasing this on the reference game turned up four distinct ways English breaks a
hand-laid-out message. Each needs a different edit, and only the first is what
anyone looks for:

| Fault | What the player sees | Edit |
|---|---|---|
| **Orphan** | one or two words alone on a line | delete the break |
| **Glued words** | `physiology.They sustain` | mark the junction so a space survives |
| **Split word** | `could I have some s emen?` | drop the tag splitting it |
| **Flush line** | text filling the measure edge to edge | insert a break at mid-word-boundary |

**A flush line is a defect, not a pass.** A run measuring 95-100% of the box
"fits" only within the error of a measurement made outside the browser - and it
reads as a clipped line whether or not it is one. The reference game had a line
at 1789px in an 1800px box: eleven pixels of margin, decided by rounding you do
not control. Splitting at the word boundary nearest the middle gives two
half-width lines that read as deliberate and cannot be tipped over by a
different font hinting pass. Do this **only** where the run would otherwise be a
single line. A run that already wraps is better left to the engine, which
balances it more sensibly than a fixed rule.

### Pick the default from the asymmetry of the error

Which box a line is drawn in is often *state*, not a constant: the reference
game sets it with a macro call (`show_mesS` at 1090px of text against
`show_mesL`/`H`/`T` at 1800px), so the same sentence overflows in one scene and
not the next. Track the last one called, forward through the file. Files that
never call one at all inherit from whoever jumped to them.

When that resolves ambiguously, **pick the default by asking which way of being
wrong is recoverable.** Assume the narrowest box: if the guess is wrong, a break
was removed that did not need to be, and the engine simply re-wraps the
paragraph. Assume the widest and the orphan stays on screen, because nothing
downstream puts a break back. The cheap error and the expensive error are not
symmetric, and that decides the default - not which guess is more often right.

### A break tag that also carries pacing

`[lr]` is `[r]` plus a click-wait. Deleting it removes a beat the author
deliberately placed, which is not a layout problem the translation created.
Downgrade it to `[l]` instead: the wait stays, the newline goes. Check the tag
list for this before treating all break tags alike - most engines have at least
one that means two things.

### Where this pass belongs

Not in the injector. Injection stays a mechanical span splice whose defining
property is that re-injecting a unit's own source reproduces the file **byte for
byte** - that proof is what makes the whole extraction trustworthy, and it dies
the moment injection starts making editorial decisions about line breaks. Layout
repair is a separate pass over the already-injected English, run after, with its
own report and its own `--apply`.

The invariant underneath that rule, stated so you can check it rather than
follow it by rote: **the byte-exact no-op proof must not be able to see the
repair.** A pipeline whose renderer builds the English string and hands it to a
separate writer can run the repair inside the renderer, provided the no-op path
does not call the renderer at all - re-injecting the source text goes straight
from `unit.raw` to the writer. That is structural, not a flag someone has to
remember to unset, and it keeps 329-of-329 byte-identical with the repair on.

### A pre-wrap is only safe if the engine's wrap is WIDTH-TRIGGERED

Choosing the breaks yourself in a box that also word-wraps sounds like a fight
with the engine, and sometimes it is. The deciding question is what the engine's
wrap does to a line that already fits:

```csharp
// Bakin, MessageReader.MessageEntry.wordWrap
if (this.measureStringSingleLine(i, 0, 32767).X > (float)width) { ...split... }
```

It only touches lines whose measured width **exceeds** the box. So lines that
each fit pass through untouched, and the renderer draws exactly what you chose.
An engine that instead joins the paragraph and re-breaks it unconditionally
makes your breaks advisory, and the pass is at best pointless.

Read the wrap function and confirm which kind you have. Then verify it per
string rather than trusting the reading: **re-run the engine's own wrap over
your output and require the line list back identical.** Any candidate line still
over the box is rejected and the string left as it was - a repair the engine
then re-wraps is worse than the greedy break it replaced.

### Refuse any line whose drawn width you cannot know

A control code inside the line is a reason to leave that line alone, and the two
failure modes are unrelated:

- **Width you cannot compute.** Bakin's `\z[200]` sets `MessageParts.size` to
  200%, scaling every part after it. Codes are stripped before wrapping so they
  cost nothing themselves, but a size code makes the *text* around it a
  different width than you measured. A "balanced" split there is a guess
  wearing a measurement's clothes.
- **A bracket that can contain a space.** `\NPL[Sister Agatha]` is one atom to
  the engine and two tokens to `line.split()`. Break there and the code is cut
  in half. This one is corruption, not cosmetics.

Both are cheap to refuse and the cost is measurable, so measure it: on a
90k-unit game, **31 of 83,999 dialogue bodies contained a code at all - 0.04%**.
Report that number next to the repair count. A refusal you can quantify is a
decision; an unquantified one becomes folklore, and someone later "fixes" it.

The same reasoning excludes a whole widget class: a text kind whose box width
you have not measured must never be rebalanced. On that game the telop node was
a third layout node with no measured width that called `wordWrap` **without**
the pagination pass, so a mis-sized repair would have overflowed silently
instead of costing a key press. Where two candidate widths exist and no
screenshot picks between them, balance to the **narrower** one - output that
fits the small box fits the large one, and the reverse is not true.

## Blank lines are structure, and a lost one reads as a collision

A blank line inside a panel is not spacing you can drop - it separates a body from
its parenthetical footnotes and it sets the block's **total height**. Models discard
them constantly, because "translate each line" has no obvious answer for an empty
one.

The failure does not look like a layout bug. On the reference game a help panel
overlapped a character portrait anchored beside it, which reads as *text too wide*.
It was not. The Japanese was 8 lines - 5 body, a blank, 2 parentheticals - and the
English came back as 6 continuous lines. Two rows shorter, so the block sat
differently against art that had not moved, and collided.

The shape of the text is the tell:

```
JP body lines   44 / 55 / 55 / 55 / 50 cells     narrow at the top, where the art is
EN body lines   60 / 62                          widest exactly where there was least room
```

The author wrote narrow lines at the top *because* the portrait is there. Merging
five lines into two threw that away along with the blank.

**Rebuild the source's block structure, and re-wrap each block to the line count it
originally had.** That restores the footprint exactly - same rows, same profile -
rather than merely making each line short enough:

```
1. split source and translation into blocks on blank lines
2. assign translation lines to blocks: match a trailing run of parentheticals
   where the source's last block is parenthetical; otherwise proportionally
3. re-wrap each block to its source block's line count
4. rejoin with the blank lines back in place
```

Then make the fitter respect it: **never flatten across an interior blank line**,
even when re-flowing the whole string would save a row. Height is normally allowed
to win over break fidelity (Step 3), but not by destroying structure - wrap within
each block and report honestly if it still does not fit.

Sweep for the whole class rather than the instance you were shown. Counting units
where the source has an interior blank and the translation does not found **8**, of
which one had been reported. The check is three lines and belongs in `validate`.

## Re-flow after shortening, or the model's breaks are the ones that ship

A shortening pass returns text that fits, so the fitter leaves it alone - and the
line breaks in it are whatever the model happened to emit. Those tend to sit
mid-clause, because the model was optimising length, not rhythm:

```
Watch out for attacks like bombs! They     <- sentence ends, line continues
can blow away coins or spell big
trouble! Shoot them down early!
```

Re-running the solver at the **same line count and width** costs nothing and lets
the punctuation bonus do its job:

```
Watch out for attacks like bombs!
They can blow away coins or spell
big trouble! Shoot them down early!
```

Gate it on improvement - only take the candidate if it ends more lines on sentence
boundaries than the original - so it can never make a hand-tuned break worse. Run
it after `shorten`, before packaging.

## Before shortening the text, check whether the bound is a constant or a parameter

The instinct on finding a label wider than its plate is to shorten the label.
Look first at how the plate got its size, because sometimes the budget is a
number in the script and you can simply raise it.

The reference game's room-expansion screen draws each label **twice** - a
`[ptext]` for the words, and an `[image]` at the same x/y for the plate behind
them, its width spelled out as a literal:

```
[ptext layer="0" x="1550" y="65" size="25" text="&'Scrap Lv:' + f.hide[2]" ...]
[image layer="0" x="1550" y="65" storage="ho.png" height="40" width="120"]
```

That `120` was measured against `廃品Lv:`. It is not a property of the art - the
same `ho.png` is stretched to whatever width each call asks for - so the fix is
to re-measure each plate against its English and rewrite the number. Ten plates,
no wording changed, and it is a computed pass rather than a hand-tuned table, so
it survives any later re-translation.

**The general question is who decides the bound.** A texture atlas region, a
fixed sprite, a hard byte span - those force you to shorten. A `width=`
attribute, a stretched nine-slice, a layout container with a settable size -
those are editable, and editing them is strictly better than compressing English
into a box that did not need to be that size.

Corollary: when the plate is drawn by a *separate tag* from the label, no
validator that inspects the label alone will ever see the mismatch. Pair them by
the coordinates they share.

### The screen edge is a bound nothing declares

`[ptext]` neither wraps nor clips. It draws at its `x` and keeps going, so a
label near the right edge runs off it - `Storage Lv:0` at x=1850 is 148px wide
and ends at 1998 on a 1920px screen. Widening its plate cannot help, and there
was nowhere to grow into: the row's own icon occupies 1697..1813. The label had
to *move*, to the left of the icon.

Deriving a width is mechanical. Deciding where a widget goes when it has no room
is not. Keep the automatic pass automatic and put the handful of relocations in
an explicit table:

```python
#: (file, first word of the label) -> new x, for labels with no room to grow into
MOVES = {("data/scenario/home/hideout.ks", "Storage"): 1516}
```

## The original may already be broken

`倉庫Lv:0` rendered as `倉庫L` against the screen edge **in the shipped Japanese
game**. The translation did not cause that overflow, it only made it obvious.

Two things follow, and the second is the one that bites:

- Fix it anyway. You are the one shipping the screen now.
- **The shipped Japanese is a width budget only where the Japanese itself
  fits.** Taking the source's own width as the safe bound is the right default
  for a widget with no declared box - but it is a measurement of what the author
  got away with, not a guarantee. Where a source string already runs past a
  container or the screen, inheriting its width inherits the bug.

Check the original whenever you find a layout defect. It costs one render and it
tells you whether you are fixing your regression or the author's.

## Verify by compositing the screen yourself

You often cannot launch the game - no display, no input, an installer, a crash
on a headless box. You can still draw the screen, because the script gives you
every coordinate the engine uses:

```python
for tag in codes.TAG_RE.finditer(text):
    if name == "button":  canvas.paste(icon,  (x, y), icon)
    elif name == "image": canvas.paste(plate.resize((w, h)), (x, y), plate)
# labels last, so they sit on top of their plates like the engine draws them
draw.text((x, y), label, font=ImageFont.truetype(game_font, size), fill=ink)
```

Paste the icons, stretch the plates to their declared widths, draw the labels in
the game's own font at their declared sizes, and mark anything crossing the
screen edge. An overflow in that mock is an overflow on screen, because it is
the same arithmetic - and rendering the **Japanese** through the same code gives
you the before/after pair that tells you which defects you introduced.

This is worth building the moment a screen has more than a couple of positioned
widgets. It catches collisions and clipping that per-widget measurement cannot,
since it is the only check that sees widgets in relation to each other.

**Validate the compositor against a screenshot you already have, before you
trust it to judge anything.** A mock that cannot reproduce the known-bad state
cannot certify the good one. Reproducing a user's screenshot exactly is what
turns "this looks about right" into a measurement.

### If you CAN launch it, capture the screen and measure it in PIXELS

A composite is a model of the renderer. A screenshot is the renderer. When the
two disagree the screenshot wins, and on a Windows build you can take one
without a human:

```powershell
$p = Get-Process -Name '<player exe>'
[W]::GetClientRect($p.MainWindowHandle, [ref]$r)   # client area, not the frame
[W]::ClientToScreen($p.MainWindowHandle, [ref]$pt)
$g.CopyFromScreen($pt.X, $pt.Y, 0, 0, $size)       # -> PNG
```

Then measure the PNG rather than eyeballing it. For a column of framed buttons:
rows where nearly every pixel is bright are the frame lines, and sparse bright
rows between two of them are text ink. The gap between the two centres is the
error, in pixels, with no judgement involved.

**Recover the scale from a known quantity so the reading survives any window
size.** Here the buttons were 45px apart by design and 82.5px apart in the
capture, giving 1.833 - and every measurement then converts to design pixels.
Without that step a maximised window silently invalidates the numbers.

This is what settles questions the layout data cannot answer on its own. Three
separate times on one game the arithmetic said a label was centred and the
screen said otherwise, because the engine's native text metrics were not the
font's published ones. Measuring the screen turned an unknown constant into
`-0.277 x font size`.

### Re-capture after the fix, and expect to iterate

A layout correction derived from a model is a hypothesis. Ship it, capture
again, measure again. On the same game the first vertical fix overshot by 5px,
in the opposite direction from the report - and only a second measurement
showed it, because the first had been reasoned rather than measured. Budget for
two or three rounds and make each one cheap: one script that captures, measures
and prints the offset is worth more than a careful argument about metrics.

## An impossible budget means your model is wrong, not that the text overflows

The fastest way to check a geometry model is to look at the budgets it produces
before you look at the overflows. A first pass over the reference game's choice
buttons assumed every screen was the same three-column grid and reported **46**
labels too wide. Most of the report looked like this:

```
+312   280/-32   x=2      system/macro.ks:427   Outfit memory
+264   233/-31   x=1      base/base.ks:245      Unlock All Switch
+225   195/-30   x=0      system/clock.ks:16    Advance 5 min
+530   530/0     x=600    home/tansaku.ks:441   Play it safe (low risk, low return)
```

A budget of **-32 pixels** is not a very tight widget. It is a column model
applied to a screen that has no columns, and every row it produced was noise.
Only the request screens are a grid. Everywhere else a button has the screen
from its `x` to the right edge. Naming the two files that are grids and
defaulting to the screen edge took the report from 46 to **2**, and both of
those were real.

**Assert your budgets are positive and plausible before you trust a single
overflow.** A budget at or below zero, or one narrower than the shipped
Japanese, means the geometry is wrong. This is worth more than any amount of
tuning, because a report full of false positives is not a slightly worse report
- it is one nobody reads, which is how the two genuine overflows nearly shipped.

And do not assume one screen's layout is the game's layout. Grids, free
positioning and stacked lists coexist in the same UI, and the model has to say
which screens it applies to.

## Numbers glue to words too, and the check must render rather than reason

The word-insert rule has a numeric twin. A label built by concatenation drops a
counter straight into a sentence, and Japanese needs no space there:

```
&'Add a fair amount' + f.koko_status[45][2] + ' used'    ->  Add a fair amount3 used
&'Western food' + f.koko_status[44][1]                   ->  Western food7
```

Every automated check passes it. It is English, it has no placeholders, no
residual Japanese, and it fits its widget.

**Detect it by rendering, not by describing the join.** A first pass reasoned
structurally - "a literal ending in a letter followed by an expression needs a
space" - and produced 33 hits of which most were noise:

```
tf.tag + 'With her hair...'          <- tf.tag is a formatting prefix, no space wanted
'      &nbsp' + f.item[…][3]         <- &nbsp is an entity, already a space
```

The rule cannot know that, because the fault is not a property of the
expression's shape. Substitute a stand-in value for each variable, join the
pieces, and look at the **string a player would read**:

```python
def rendered(raw):
    return "".join(unprotect(expand(v)) if kind == "lit" else "7"
                   for kind, v in tokens(raw))

def glued(shown):                       # a digit pressed against a letter
    return any((a.isalpha() and b.isdigit()) or (a.isdigit() and b.isalpha())
               for a, b in zip(shown, shown[1:]))
```

The rendered form also makes review possible - `Add a fair amount7 used` is
obviously wrong at a glance, where `'Add a fair amount' + expr + ' used'` is not.

This is the same principle as compositing a screen to check its layout, one
level down: **evaluate the thing the player sees, then judge it.** Reasoning
about the construction misses what the construction produces.

## Abbreviate on labels, never in prose

Widget labels can be compressed in ways message text cannot. `以上` reads as
"or higher" in a sentence and as "+" on a button, and the button version is what
makes a requirement line fit:

```
Affection 2500 or higher, Lewdness 4800 or higher     629px   overflows
Affection 2500+, Lewdness 4800+                       411px   fits
```

The trap is that these are often **the same extracted unit**. The reference
game's request screen builds its labels by concatenation, so one fragment
`以上、淫乱度` serves 52 sites - and a rewrite matched on the *source string*
also caught five message-text sentences, turning "Can be unlocked at ⟦1⟧ or
higher Affection" into "at ⟦1⟧+ Affection" in the middle of prose.

**Gate a width-driven rewrite on the unit's form, not on its source text.** An
attribute value on a widget may be abbreviated, a bare message line may not.
Where one fragment genuinely serves both, it has to be split into two units
before either can be fixed - and a fragment shared across dozens of sites can
only be shortened if the short form reads correctly at *every* one of them.

## The source line is the evidence, not the screen geometry

Deriving a width bound from screen geometry looks rigorous and is often wrong.
On a TyranoScript game, free-positioned `[ptext]` labels were checked against
`screen_width - x - margin`. That reported **34 overflows, of which 28 were
false**, because several of the *Japanese* labels are already wider than that
bound. The engine evidently draws them somewhere the naive model does not
describe.

If the shipped Japanese exceeds your computed limit, **your model of the box is
wrong** - and the Japanese itself is the best evidence of how much room exists:

```python
limit = max(geometry_limit, measure(japanese_source, size) * 1.05)
```

Anything no wider than the source fits wherever the source fitted. Keep the
geometry bound as the floor for widgets whose Japanese *does* fit inside it.

This is the opposite rule to **use the min of the two** earlier in this file, and
the observation that triggers both is the same one: the shipped Japanese is wider
than the geometry says. The min is right when the author really does clip their
own lines, the max is right when your model of the box is wrong, and the corpus
cannot tell you which - it is the same data either way. Photograph the widest
Japanese line in that widget. If it renders whole the geometry bound is wrong and
the source is the bound. If it is cut the author overflows and the geometry bound
stands.

Corollary: an over-tight bound is not harmless. Each false overflow costs a
re-request that shortens text which never needed shortening, and the model
happily obliges.

### A hand-positioned label loses its CENTRING when you replace the text

Many engines have no "centre this text in its box" flag. Where an author wanted
a label centred - on a plate, a bar, a button - they nudged its x by hand, once
per label, against the width of the SOURCE string. Replace the text and the x
does not move, so every one of those labels drifts by half the width
difference. Nothing overflows, nothing clips, every width check passes, and the
screen looks wrong in the way a player describes as "the text is out of its
box".

On a Bakin main menu the drift was up to **31px** on a 192px plate - a sixth of
it, and far more than enough to read as broken:

    idx  text          pos.X   drawn(JP)   centre
     17  アイテム           47        96      95.0
     19  装備             72        48      96.0
     20  ファストトラベル       18       154      94.8   (drawn at scale.X 0.8)
     23  コンフィグ          35       120      95.0

The repair is arithmetic, not editorial:

    new_x = old_x + (drawn(source) - drawn(translation)) / 2

which preserves each label's OWN centre rather than snapping the group to a
common one, so a label the author deliberately placed off-centre stays there.

**Never shift a single label on suspicion - require a GROUP.** One label at a
left anchor might be hand-centred, or might be plainly left-aligned at a
margin, and shifting a left-aligned label is a regression you introduced. From
a group they are trivially separable: siblings whose x values DIFFER while
their source centres AGREE can only be hand-centring, because left alignment
would have given them all the same x. Refuse everything else and report the
count.

### CJK has no descenders, so Latin needs MORE height at the same size

A button sized for Japanese can be too short for English even when the English
is half the width. This is the trap: you check width, the English is
comfortably narrower, you conclude the label is fine - and on screen the glyphs
cross the top and bottom of the button.

CJK sits inside its em square and never dips below the baseline. Latin hangs
`g`, `p`, `q`, `y` under it and pushes caps above the CJK cap line. Measured on
one game at an identical nominal size:

    アイテム 19px   Item   18px          装備 22px   Equip  22px
    コンフィグ 20px   Config 22px          セーブ 20px   Save   18px

Nearly equal - and that is the point. The Japanese only half filled the button
horizontally, so it *looked* to have room, while vertically both languages fill
it. Replace short wide CJK with tall narrow Latin and the button reads as
overstuffed even though nothing got wider.

**Measure the INK box, not the advance width, and check it against the drawn
frame rather than the declared box.** The declared plate was 35px tall; its art
drew the frame across 78% of that, leaving ~27px of interior against a 28px
line box. Neither number is in any attribute - one came from the rom, the other
from the alpha channel of the button texture.

The remedy is a size, not a rewrite: shrink the label until its ink clears the
frame. Where the engine exposes a per-widget scale, that is a data change of
the same kind as a position. **Prefer a scale the author already used** - here
the author had hand-set 0.8 on the two buttons whose Japanese ran longest, so
applying 0.8 to all of them both fixed the fit and made the row uniform, which
it had never been.

And judge it by COMPOSITING, not arithmetic. Render the real plate art with the
real font at each candidate scale and look. Validate the compositor first by
reproducing a screenshot you already have - a mock that cannot reproduce the
known-bad state cannot be trusted to certify the good one.

### One anchor field often sets BOTH alignments - check before blaming the y

A label sitting low in its button looks like a y-offset bug and often is not.
Engines commonly fold horizontal and vertical alignment into a single `origin` /
`anchor` enum, so the field you read as "left aligned" is also saying "vertically
centred", and centred *in the label's own box* rather than in the plate beneath
it. The two coincide only when

    pos.Y == (plateHeight - boxHeight) / 2

On one game the boxes were 45px tall on a 35px plate at `pos.Y = 2`, centring the
text at 24.5 against a plate centre of 17.5 - seven pixels low, with the
descenders clipped by the container's own window. Seven labels did it and the
eighth did not, because the author had given that one a `Top*` origin, which is
aligned differently and happened to land centred. **The odd one out was the
correct one** - a good reminder that the outlier in a broken set is worth reading
before it is normalised away.

Two things make this repair safe, and both are worth checking in your engine:

* **For a `Middle*` label the text height CANCELS.** Centre is `pos.Y +
  boxHeight/2` whatever the string says, so the correction is pure geometry and
  survives retranslation. For `Top*` it does not cancel - centring depends on
  the engine's own line-height metric, which you are probably approximating -
  so report those rather than moving them.
* **`pos.Y` is also how authors STACK labels on one plate.** A first pass
  matched 240 labels; a save-slot screen put five fields on one 80px plate at
  `pos.Y` 4 and 38, and centring them would have piled them on top of each
  other. Act only where a label is ALONE on its plate, and count what you
  declined.

Finding the plate at all needs the widget TREE. Flattened dumps are the norm
(one engine's `ParseAllItems` returns a flat list) and a flat dump cannot answer
"what is this label drawn on top of". Emit a parent link, and read the plate
size off the CONTAINER that defines it - the sub-item's own `size` may be
overwritten at run time and not be the plate at all.

### Centring the LINE BOX is not centring the TEXT - measure the ink offset

An engine that vertically centres text centres its LINE HEIGHT inside the box.
That height is taller than the visible ink and rarely symmetric about it, so a
label whose line box is perfectly centred can still read as sitting high. The
maths looks provably right and the screen disagrees.

**Do not try to derive the correction from the font's metric tables.** On one
game every candidate was wrong by a factor of five:

    hhea       predicts  -0.9 px
    OS/2 win   predicts  -0.6 px
    OS/2 typo  predicts  +0.1 px
    MEASURED             -5.3 px

The engine measured through its own native layer, which matched none of them.

**Measure it off a screenshot instead**, and it is easy to automate: in a
vertical band across a column of buttons, rows where nearly every pixel is
bright are the plate's frame lines, and sparse bright rows between two of them
are text ink. The gap between the two centres is the constant. Recover the
scale from a known design pitch so the reading works at any window size, and
store the result as a FRACTION of the drawn font size - ascent, descent and cap
height all scale linearly, so one measurement covers every size.

Read labels **without descenders**. A `g` or `q` extends the ink box downward
and drags its centre with it: on the same row of buttons the descender-free
labels read -9.8 px and the two with descenders read -7.0 and -6.5.

That fraction also survives a MODERATE change of weight inside a family, so a
constant measured before you settle the font question usually does not have to
be re-measured after it. Read the table below for where that stops being true. Measured with PIL on descender-free text,
`(line_centre - ink_centre) / px` is

    Yu Gothic Light      +0.0547
    Yu Gothic Regular    +0.0547
    Yu Gothic Medium     +0.0547
    Yu Gothic Bold       +0.0625

so the Light-to-Medium change forced below costs nothing, while a move into
Bold would move the constant by 14% and has to be re-measured. This does not
reopen "do not derive the correction from the metric tables" above. They are
two different quantities. The ENGINE's centring offset is whatever its native
layer does and only a screenshot reports it, while ink-within-the-line-box is a
property of the face and is stable enough to read off the font file.

Two traps around this, both of which cost a shipped iteration:

* **Every pass has to use the size the label will actually SHIP at.** A resize
  pass and a reposition pass computed from different assumptions is a bug that
  reports success: here the vertical pass read the source `scale`, computed the
  offset for a size the label no longer rendered at, and the resulting shift
  fell under the minimum-movement threshold - so it moved nothing and said so
  cheerfully.
* **A constant measured on ONE screen does not license changing every screen.**
  Adding the offset term took a 15-label candidate list to **207**, across half
  a dozen screens nobody had ever rendered. Gate the pass on an explicit list of
  screens that have been captured and measured, and add to it only after
  capturing the next one.

### Two candidate widths and no way to tell which is live: take the SMALLER

A screen can declare more than one box for the same text and give you nothing
to say which one the engine actually uses. One Bakin game declared both a
690x140 and a 670x136 Message node, both reachable through the same
`MessageReader.ReadMessage`, with no screenshot of the plain Message box to
settle it.

Where the engine's wrap is WIDTH-TRIGGERED the choice is free, and in one
direction only: a line balanced to 670 still fits a 690 box, so it is never
re-broken whichever node is live. Balance to 690 and the 670 box re-wraps you,
which is exactly the orphaned tail you were repairing. So take the smaller
candidate for the repair even when a wider one is better evidenced, and keep the
calibrated width for the measurement it was calibrated for.

The rule does not extend to a widget that does NOT paginate. The same game's
telop node had no measured width and called `wordWrap` without `splitByLines`,
so a mis-sized repair there overflows silently instead of costing a key press.
Those 13 units were left alone and reported rather than guessed at.

### Scope a layout repair by WIDGET SHAPE, not by screen

Once a layout correction is calibrated the temptation is to apply it
everywhere, and every scoping instinct short of "one widget" turned out to be
too broad. On one game the same fix was scoped three ways before it was honest:

    unscoped                     207 labels, across six screens never rendered
    by node                      487 labels, incl. the DIALOGUE NAMEPLATE, because
                                 those screens merely CONTAINED the widget
    by widget shape (186x98)      26 labels, every one the widget reported

A shape is one widget: verified once, identical everywhere it appears. A node is
a whole screen, and a screen contains things you were not asked to touch.

Pair the shape gate with an **intent gate** drawn from the author's own data.
For a container that holds several labels at deliberate positions, only correct
one whose box the author had ALREADY centred in its region - that is them saying
"centred here", leaving only your offset to fix. A label placed off-centre was
placed there on purpose. And compute the region properly: a panel split by a
rule is two cells, so a heading centred in the top cell is not centred in the
panel, and "centring" it drags it through the rule.

### The correction is TWO terms, and the intent gate only guards ONE of them

`want = region_centre - size.Y/2 - ink_offset` reads like one formula, but the
two halves have different justifications and different scopes:

* the **centring** term moves a box the author left off-centre on its plate.
  It is a change to the author's layout, so it needs the intent evidence above.
* the **ink** term compensates for YOUR font substitution shifting the glyphs
  inside a line box the author positioned correctly. It repairs damage the
  patch did, so it needs no permission from the author's data at all.

Keep them separable, because **a widget the centring gate rightly declines can
still need the ink term.** On one game's battle-result screen the level number
sat in a downward triangle; the centring pass refused the whole container - not
one of its four labels was centred in its band, so every position in it was
deliberate - and refusing was correct. But the substituted font had still lifted
the digit out of the triangle. The fix was the ink term alone, applied to that
one widget with the derivation written down. Had the pass been forced to run,
it would have dragged all four labels to the container's centre and destroyed
the layout.

Corollary: an author's position that looks wrong may be right for a shape you
have not modelled. That digit's line box was centred at y=18 in a 52px band -
8px above the geometric centre, which reads as an error until you notice 18 is
the CENTROID of the downward triangle drawn behind it, which is where a number
looks centred in a wedge.

### You can verify a layout nudge without launching the game

The label's background art is reachable: the widget names a window/plate
resource by id, the resource table maps that id to a path, and the art is on
disk. Composite it yourself - stretch the plate to the widget's declared size,
draw the label in the substituted font at its declared size, and put the BEFORE
and AFTER side by side.

The 9-slice insets are usually not worth recovering. Render the plate twice,
once squashed uniformly and once with generous native caps, and check the two
models agree on the ANSWER. They bracket the truth, and you only need the sign
and rough size of the correction. If they disagree, that is the signal to go
get the real insets.

Two things this mock will not tell you. It centres on the glyph's **ink** box
while the engine centres on its **advance** width, so horizontal readings carry
a few pixels of error - do not act on horizontal drift you only saw in a mock.
And a plate model that is approximate vertically is still approximate: use it
to confirm a direction you derived, not to derive one.

Distinguish the container kinds while you are at it. A BUTTON's label belongs
centred on the button by definition and needs no further evidence. A PANEL's
does.

One implementation trap worth naming: if the container kinds take different
branches, make sure a branch that returns early still applies the preconditions
the other one relies on. Here the panel branch skipped the "is this even
centre-aligned?" test and duly "centred" a right-aligned value - a bug that
reports success.

### A centred group is the best font-size instrument you will get

That same group calibrates the font. N labels of differing widths agreeing on
one centre overdetermines the size - N-1 independent constraints on one
unknown - so the size is whichever makes the group cohere:

    size    centre spread across seven labels
    20px            10.0 px
    22px             5.6 px
    24px             1.2 px   <-
    26px             3.5 px

This beats measuring glyphs in a screenshot, and unlike a screenshot it is
**self-checking**: a wrong size shows up as a group that fails to cohere rather
than as silently wrong offsets written into the game. Assert it in the test
suite - re-run the detection at plus and minus one step and require both to
cohere worse - so a later config edit cannot quietly break it.

It also caught something no single measurement would have: this game draws
**message text and layout text through different FACES** - and the numbers your
measuring library needs differ (22px and 24px here) even though the engine is
nominally 24 on both: one face is hinted natively at 24, the other is a 72px
face whose advances are divided by three. Calibrate each path separately, and
say which is which rather than reporting "two font sizes". One
"font size" for the whole game is an assumption, not a fact, and where two
renderers exist there can be two defaults.

### The EXCLUSION RATE is the diagnostic - a workaround that hides a metrics bug

Excluding slots the author already overflows is the right per-widget rule, and
it is also the perfect place for a wrong font size to hide. The exclusion is
silent by design, every remaining check passes, and the pipeline reports a
confident zero.

Watch the **rate**, not the count. On a Bakin game the validator reported

    slots ALREADY over their declared box in the shipped JAPANESE: 220 of 551

one of them declaring 26px while drawing 503px. That was read as a quirk of the
game for a long time. It is not a plausible author: **nobody overflows 40% of
their own boxes.** The font size was a guess (no Bakin build exposes one) and it
was 2px too large in a box 20px too narrow. Calibrated against a single in-game
screenshot, the same run reports

    slots ALREADY over their declared box in the shipped JAPANESE: 70 of 551

with nothing else changed. The count falling by two thirds is corroboration that
costs nothing to obtain. (It later fell again, to 38, once the budget arithmetic
itself was corrected from `size.X * scale.X` to `size.X / scale.X` - the same
lesson arriving twice. The exclusion count is a reading of your MODEL, so quote
it with what produced it and re-derive it after any change to the model.)

**Print the exclusion as a percentage and treat a high one as a metrics alarm.**
Single digits mean the author was sloppy in a few places, which is normal.
Anything approaching a third means your font, your size or your box width is
wrong, and every width-derived number downstream - overflow flags, nameplate
budgets, field budgets - is measured against the wrong ruler. Re-derive them all
after a calibration change; do not assume a metrics fix is confined to the
check that surfaced it.

## A font NAME is a bet on the player's machine - check the glyphs, not just the width

Engines that name an installed system font (`GameSettings.gameFont`,
`[deffont face=]`, a CSS family) are not choosing a typeface, they are choosing
**whichever font the player happens to have**. If the named family is absent the
OS substitutes silently, and the substitute decides which characters exist at
all.

That is invisible to every check in this file. On one game the source used
U+2661 WHITE HEART SUIT **229,107 times**; the requested family was Japanese-only,
and the substitute in play had no glyph for it. Every one drew as a tofu box
while the text was correct, the codes intact, nothing overflowing and no residual
source language. The defect surfaced only when somebody looked at the screen.

**Diff the shipped corpus against the font's cmap.** It is a dozen lines with
`fontTools`, it runs in seconds, and it is the only check that sees this:

```python
cs = [f.getBestCmap() for f in fonts]
missing = {ch for ch in shipped_characters
           if not any(ord(ch) in c for c in cs)}
```

**Do not "fix" it by swapping the character.** Test that instinct before acting
on it - the plausible substitutes often have no replacement either. Here YaHei,
JhengHei and SimSun each lacked ♡ *and* ♥ *and* ♪, so there was no heart to fall
back to at any codepoint.

Fix it by NAMING a font that has the glyphs. Rank candidates by four things at
once, and reject any that fails one:

* **present** - shipped with the OS in every locale, not part of a removable
  language pack. (A family sharing a file with a UI font is a good sign: the UI
  variants usually survive when the text variants are optional.)
* **complete** - verified from its cmap, not assumed from its name.
* **already measured** - if it is the font your metrics were calibrated against,
  naming it converts every width in the pipeline from an assumption into a fact.
* **the weight the author asked for** - a family is not one face. The three
  criteria above are all satisfied by the lightest member, and following them
  as written selected Yu Gothic Light against the author's 游明朝 Demibold. No
  width check sees that, and every player does: thin stems are exactly what an
  upscaled raster destroys.

Weight is not free, so price it rather than argue it. Over 83,999 units wrapped
at 670 px, units needing more than 3 rows:

    Yu Gothic Light        834   0.99%
    Yu Gothic Regular     1370   1.63%
    Yu Gothic Medium      1365   1.63%
    Yu Gothic Bold        1849   2.20%
    bundled M+SmileBoom   2498   2.97%

Matching the author's weight costs about 0.6 points of pagination, which buys a
legible face cheaply. Quote that number against the face you will SHIP: pagination
is a property of the WEIGHT, not of the decision to name a system font, and a
reader who takes 0.99% as "the cost of naming one" is wrong by more than the
whole bundled-versus-named gap.

If the engine can load a font the game SHIPS, that is the only guaranteed
answer - but price it the same way. Here the bundled face cost 2.97% against the
1.63% of the weight actually asked for, so it stayed the documented fallback
rather than the default.

And read the engine's font resolution before trusting either branch. Here an
empty name did reach the bundled file, while a `"Meiryo"` default that looked
like the fallback sat after an early return and was unreachable.

## A field shown twice is the author's; the OVERFLOW is yours

An author may embed a value in a description AND have the layout draw it from a
getter - a skill's MP cost written into the flavour text while the panel also
renders a cost row. The duplication looks like a translation bug and is not: the
source did it too. What the translation broke is the FIT, because the embedded
line only worked while the prose fitted the remaining rows.

Measure the three states before choosing a fix - source, translation, and
translation minus the embedded line:

    over the row limit in SOURCE      :  3 / 31
    over the row limit in TRANSLATION : 19 / 31
    ...with the embedded line removed :  2 / 31

**That last number is a trap.** Deleting the redundant line fixes almost
everything in one edit, and it is only safe if the getter is present EVERYWHERE
the field is shown. On one game four layout nodes drew the description with a
cost row and a fifth - a user-made variant claiming the same usage slot - drew
it with none. With two user nodes competing for one usage there was no way to
prove the bare one never renders, so deleting the line risked deleting the only
place the value appeared. **Shorten the prose instead: correct in every node,
loses nothing, and needs no assumption to hold.**

Two things worth knowing before you start rewriting:

* **Usable width is well under `rows x width`.** Two 360px rows is 720px on
  paper; word granularity put the real ceiling near **640px**, because after any
  legal first break the remainder must still fit. Rewrites comfortably under the
  paper budget still needed an extra row.
* **Try a balanced re-break first** - the same DP as the orphan pass. Where the
  text genuinely fits the row count and greedy wrapping merely wasted the room,
  it costs no words at all. When the DP returns "no split exists", that is the
  honest signal that the text itself has to give.

And check which layout node is LIVE before reasoning about any of it. Engines
that let a user override a built-in screen can carry several nodes claiming the
same usage; the one you are looking at may not be the one you are editing.

## Measure with the game's own font

Games ship their face (`data/others/*.otf`, an `@font-face` in the theme CSS, a
`[deffont face=]`). Load *that* with `ImageFont.truetype(...).getlength()`, not a
system default and not a per-character estimate - the estimate was 15-20% out on
this game's face, which is the difference between "fits" and "clipped".

## Text baked into an image: fit the ink, not the font's line box

Mechanics and the full fit ladder live in `image-translation.md`. The measuring
principle is here because it is the same principle as every other box in this file.

**Express every size the pipeline touches in pixels of ink, and convert to point
size by binary search per typeface.** The ratio of cap height to point size is the
typeface's business, not a 1.35 constant - a 40pt face draws capitals about 28px
tall. Search point size over `1..max(8, cap * 4)`, measuring `font.getbbox("H")`
bottom minus top each step, and keep the largest size whose cap height is
`<= target`. Cache it (`lru_cache(512)`), since a fit ladder calls it constantly.

**Fit against the ink extent, not the font's line box.** Measure
`(width, height, ink_top)` off glyph bounding boxes, laying lines on a common
baseline grid where each line's origin is exactly one `line_height` below the last
with no per-line nudging, so a line with no ascenders is not shoved up. A single
line of capitals occupies about 70% of **its line box**, so budgeting by the line
box stops the type a third of the box height short and the size control refuses to
grow. (Do not confuse this with `image-translation.md`'s `comfortable =
size_for_cap(font, round(cap * 0.70))`, where the 70% is of the **original measured
cap height** and is a deliberate step down for breathing room. Same number, unrelated
meanings.) Carry `ink_top` through to the renderer so it centres the painted extent
where the original ink was measured.

**Scale the measured stroke with the fitted size**: `stroke * size / reference`,
clamped to `1..original`. The measured stroke belongs to the Japanese, which is
usually set larger than the English replacing it, and a stroke that does not shrink
closes the counters. And **subtract `2 * stroke` from the available room before
dividing out any horizontal or vertical scale factors** - the stroke is drawn
around the stretched tile, not stretched with it.
