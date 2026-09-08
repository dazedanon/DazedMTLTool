# Image Translation (text baked into game images)

Use this workflow for authorized image work, including requests naming a UI
screen, a screenshot, or **all images with text**. A broad image request authorizes
the full image census; it does not require approval for each filename. A text-only
request does not itself authorize replacing unrelated artwork. Follow the scope
and work mode in [SKILL.md](../SKILL.md).

For **manual/no-API work**, transcribe and translate locally, using local image
tools for measurements, masks and lettering. Do not call hosted OCR, translation
or image-generation services. The Musi Dream example below used no such services.

Pipeline for translating game images in place - menus, calendars, logos, speech-bubble screenshots, letters, web-page mockups, cut-ins, autographs - **matching the original background, font style, and colors. No caption/subtitle overlays.** Proven on the Asuka Virgin Idol Debut set (36 images, every type), the Ajin Syoujyo UI set (56 label plates on photographs), and the Kihoushi Scarlet set (a graffiti overlay of 11 hand-lettered phrases at five angles plus a gradient badge, then eight more: five dense overlays up to 180 components, a flattened copy of one of them, a title screen, and a translucent banner).

Where the game already uses bilingual labels, preserve or match that established
convention when it fits the requested scope. Respect an explicit keep list;
avoid adding a new subtitle band merely to hide difficult lettering.

**Toolkit:** `tools/Game Translation/Image Translation/imgtl.py`.
Read its adjacent `README.md`, then copy the helper beside the per-game recipes.
It provides probes, erasers, masks and styled text with Pillow/NumPy; some helpers
also need SciPy or OpenCV. Inspect the actual function signature before adapting
an example: this reference also describes algorithms from other applications,
including morphology/OCR workflows that are not implemented by `imgtl.glyph_mask`.
The shared `load()` converts to RGBA and `save()` selects an encoder from the
filename. Indexed palettes, ICC metadata and an explicit encoding require the
Pillow handling demonstrated in the project recipes below.

| Task | Shared helper entrypoints |
|---|---|
| Measure/view | `alpha_range`, `ink_bbox`, `ybands`, `xclusters`, `zoom`, `grid` |
| Select/erase text | `glyph_mask`, `glyph_mask_pure`, `inpaint_rows`, `inpaint_diffuse` |
| Reuse verified clean art | `sibling_clean(crops, masks, spread_thr=14)` returns clean pixels and an unreliable mask; `apply_clean` uses both |
| Keep decorations | `components`, `comp_sheet`, `clear_components`, `comp_stamp`, `put_stamp` |
| Fit/render | `font`, `text_width`, `text`, `coverage`, `marker_line` |

Read the recipes before selecting parameters. `marker_line` takes measured
endpoints and a target band height; that height is not the final font size.

Related: `text-fitting.md` states the measuring principle these fit ladders apply,
and `glossary-and-prompts.md` owns the terms the labels must match. Where UI images
have already been redrawn with chosen English terms, the glossary is load-bearing
for the text pipeline too and the game bible must say so.

## Reusable manual pipeline: Musi Dream

Stable project: `tools/Game Translation/Active Projects/Musi Dream (TyranoScript)/`.
Read `images/README.md` and `images/PROMPT.md` first. This is a completed manual
example: 517 archive image entries / 448 distinct hashes, 28 rendered outputs
plus two exact-duplicate copies, and one explicitly excluded asset. Preserve the
coverage limitations in `images/coverage.json`; these counts are not defaults
for another game.

| Need | Project file to adapt |
|---|---|
| Archive-wide census, dimensions/modes/frames, duplicate identities | `images/inventory.py`, `images/inventory.json`, `images/coverage.json` |
| Buttons, state pairs and indexed controls | `images/render_controls.py` |
| Hints, warnings, mission panel and flattened tutorial insets | `images/render_ui.py` |
| Gradient/outlined title lettering and measured art reconstruction | `images/render_title.py` |
| Browser mockups, small thumbnail lettering and shared page chrome | `images/render_web.py` |
| Flat-color silhouette reconstruction under a glyph mask | `images/web_reconstruction.py`, function `recover(source, mask, box)` |
| Per-family review records, exact-duplicate fanout and merged manifest | `images/assemble.py`, `images/*_review.json`, `images/*_manifest.json` |
| Detached native decode against the installed ASAR | `manual/image_runtime.py` |
| Actual scene, transient-state and menu screenshots | `manual/image_visible.py`, `manual/image_targeted_check.py`, `manual/image_menu_check.py` |
| Bind reviewed screenshots and separate QA reports | `manual/image_report.py`, `images/runtime_review.json` |
| Package reviewed images and verify installed bytes | `scripts/build.py`, `scripts/package.py`, `reports/image_runtime.json` |

These are working examples, not portable commands to run against an arbitrary
game. Inspect paths, archive identity, asset IDs, fonts, CDP target and scene
assumptions before copying. Several scripts execute at import time and write
outputs or drive the game; do not import them merely to list functions. Retain
the copied `imgtl.py` and local helpers with the recipes. `web_reconstruction.py`
also contains a measured Musi Dream banner special case that needs new geometry
on another image; it is not a general shared-tool function. The old test fixture
was removed after QA and source metadata retains a historical game path. Rebind
the supported original archive and recreate an isolated game/save fixture before
rerunning runtime checks. `image_visible.py` uses the default CDP port 9222 and
lacks the native decoder's URL guard: verify its target explicitly.

For navigation: use [Workflow](#workflow),
[Flat-color artwork](#flat-color-artwork-continue-shapes-without-mixing-the-palette),
[Review and runtime proof](#review-and-runtime-proof), or
[Deployment](#deployment). The later sections retain worked recipes for specific
backgrounds and text styles. Numerical thresholds are measured examples to
calibrate on the new source, not universal defaults.

## Workflow

1. **Inventory the authorized scope.** Enumerate archive entries as well as loose
   files, including plugin/theme folders, alternate states and animation frames.
   Record exact relative path, source SHA-256, decoded format, dimensions, mode,
   alpha, palette/profile and frame metadata. Classify text-free, already-English,
   translated, pending and excluded assets separately. A white-looking preview
   does not distinguish opaque white from transparency: inspect alpha first.
2. **Read the source as a whole screen.** Use the available image viewer, then
   native crops and enlarged views for small text, insets and shadows. Preserve
   filename/cell mappings on contact sheets. Transcribe before editing; check
   ambiguous handwriting against the same author's known glyphs. Ask about a
   consequential reading only if the available source cannot resolve it.
3. **Map consumers and variants.** Determine which exact entry the game loads,
   its display size, crop, click area and state variants. Same filename stems,
   similar silhouettes and perceptual hashes suggest families; only identical
   source bytes justify automatic whole-output copying. Reuse existing approved
   lettering or clean donor regions after verifying alignment and variant art.
4. **Record source, target and layout separately.** Keep block IDs, reading order,
   source/English, glossary terms, protected symbols and measured geometry. Use
   `images/PROMPT.md` and `image_glossary.json` as examples. Tiny captions and inset
   screenshots are part of their parent image, not optional leftovers.
5. **Build from pristine source.** Measure ink plus outline/shadow, keep erasure
   masks separate from the new text's draw bounds, choose a repair for the actual
   background, and save the erased base before lettering. Preserve original art,
   palette/alpha, borders and hotspots. Keep outputs in a separate directory.
6. **Review before deployment.** Compare source, erased base and final output;
   inspect at native size and 2-3x for glyph fragments or damaged edges, then at
   actual game scale for legibility. A contact sheet or successful fit calculation
   alone is insufficient. Pin approval to exact source/output hashes and retain
   the crops and reviewer findings. Any changed output requires renewed review.
7. **Assemble and test the actual payload.** Merge reviewed family manifests,
   fan out only verified duplicates, validate geometry and intended change regions,
   then install through the proven engine path. Verify packed/installed bytes,
   native decoding and the visible game states separately; see the proof section.

Track state per image/block: inventoried -> transcribed/reviewed -> translated ->
rendered -> visually reviewed -> runtime checked. These are separate claims.
The assistant can perform review within the authorized task; do not invent a
mandatory user sign-off for every image. Request user input for an unresolved
reading or material preference, or when the user explicitly reserved approval.

When delegating, assign disjoint files or families and a shared glossary. Give
reviewers the source and output with their hashes, and ask them to report concrete
defects. Keep one owner for the merged inventory/manifest. A stale approval flag
must not survive a wording, mask, font or render change merely because a filename
is unchanged. Do not label an agent review a human review.

### Indexed controls: preserve the palette as well as appearance

For a `P`-mode button, retain the original index plane, RGB palette and transparency
metadata. Render new lettering separately, quantize it to that palette without
dithering when matching the source, and paste changed indices only within approved
zones onto an original copy. Reopen the saved file and check palette, transparency,
dimensions and unchanged indices outside those zones.

Musi Dream's `images/render_controls.py` and `images/CONTROLS_QA.md` show this
procedure, including Pillow's RGBA-palette trap: restore the RGB palette explicitly
before saving. An output looking correct on one background does not establish
palette or transparency preservation. If the palette cannot represent the needed
lettering, treat a mode change as an explicit, runtime-tested format decision.

## Packed sprites: the export canvas may exceed stored pixels

A padded sprite export can look correct while its stored atlas crop discards
the wider English. Carry both canvas geometry and source/target crop metadata
through editing. Detect changed pixels outside the stored rectangle before
importing; expand or remap storage when needed while preserving logical bounds,
origins and unrelated assets. Do not silently crop the translation to old ink.

Validate the archive you will ship at two levels: decoded atlas pixels, including
unchanged neighbors outside the edit masks, and re-exported full-canvas sprites
against the reviewed PNGs. Atlas equality alone misses an incorrect crop or
offset. Font glyphs may share those atlas pages, so font-metric checks alone do
not protect their artwork. See [engine-gamemaker.md](engine-gamemaker.md) for the
tested UTMT procedure and the three cropped labels that exposed this failure.

## An erase that removes nothing fails silently

Every other mistake announces itself. This one does not: the mask comes back
empty, the erase is a no-op, the English is drawn straight **on top of** the
Japanese, the file's hash changes, and it reads as a successful render until a
human looks at it. It happened twice on a 1,300-image run, both times to code
that had already worked on twenty other families.

- **Wrong polarity.** The mask looked for ink *brighter* than the plate. The
  quest cards are dark type on cream paper, so the bright core was empty and the
  `if not core.any(): return core` guard handed back an empty mask. Compute
  **both** cores and keep whichever has a plausible ink fraction (roughly 0.4% to
  50% of the box). Never inherit the polarity from a sibling family.
- **Template coordinates that drifted.** Five header ribbons shared one
  `✦ ─ text ─ ✦` design, same span, same dash rows. The sixth sat 20px lower.
  Reusing the family constant cleared empty space, drew the English into it, and
  left the Japanese untouched below - and it was the last defect found, after
  every automated check had passed.
- **The inpaint that returned its input.** At 100% mask coverage `cv2.inpaint`
  returns the crop untouched and raises nothing. See the context policy below.

So **assert the erase consumed ink**: sum the mask over the box before drawing
and fail loudly on zero. Report an empty mask as a *failure with a sentence*
("nothing was erased"), never as a clean pass - a block that has a translation
and found nothing to erase is almost always a wrong setting. Better, derive each
file's geometry from the file (scan for the rule row, the plate tone, the ink
bbox) and treat the family constant as a fallback rather than the source of
truth.

## Logo type: erase the INK, not the fill

Display type is fill + white ring + black outer ring, and the ink runs ~25px
past the fill bbox on 72px glyphs (measure the rings with scanline runs, then
size the erase from fill cores + measured rings + margin). An erase box sized
off the fill fails in BOTH directions at once: ink outside the box survives as
black fragments, and ink the box edge cuts through sits on the diffusion
boundary and anchors it - glyph-shaped smears across the whole repair. Every
width check passes, the file hash changes, and it reads as a successful
render at 1:1. This is why the 2x inspection is non-negotiable.

Detectors for the rings cannot run bare: "white" must mean the ring's
near-pure white, not a light plate's tint, "black" must stay nearly neutral so
dark art does not join, and a hard geometric cap - nothing farther from a fill
pixel than the measured ink reach is ever erased - makes the whole mask safe
against detector slop. Keep white/black only where their connected component
contains fill, so dark tiles touching the ring stay art.

And redraw in the source's construction, not an approximation of it: paint
per ring pass over ALL rows (every black outer, then every white, then every
fill) so stacked rows whose rings merge read as one block, the way the source
glyphs merge. A soft offset shadow where the source has a hard outer ring
reads as a different logo pasted on.

## A translucent plate refills from ITSELF

A logo plate (white at ~75% over the art) is background to preserve, but
where dense glyphs covered it edge to edge, almost no plate survives around
the mask - and a whole-box diffusion then pulls the art from above and below
the band straight through the erased glyphs: a hole in the plate, not a
repair. Clip the inpaint domain to the measured plate rectangle so the only
anchors are plate pixels, run that per plate, and only then fill the leftover
ink (ring tips on raw art) with full-context anchors. Measure the plate
rectangle with row/column luminance profiles on glyph-free strips - the
"obvious" extent is routinely wrong (the two Mineria plates nearly touch,
separated by 5px, and plate 1 ends at x 910, not the canvas edge).

Prove the whole edit with a regression diff at the end: |out - src| outside
the intended zones must be zero, and each changed cluster inside them must be
your own drawn text or erase. That is what catches the layer that drew 1px
past its box - or a repair that quietly moved something it should not have.

## OCR and text detection

OCR is optional assistance; the Musi Dream run used manual visual transcription.
In a no-API task, stay with manual reading or an already available local OCR
engine compatible with the requested mode. An endpoint requiring no account is
still a network service. For an authorized OCR application, use a registry of
engines rather than one hard dependency. Prior integrations included Google Lens
via the unofficial `chrome-lens-py` endpoint and optional local RapidOCR; inspect
the actual adapter and its availability instead of assuming either is installed. `available()` must never raise, and a status call should explain
*why* an engine is missing. Call `importlib.invalidate_caches()` before probing
an import: pip-installing while the app is open leaves site-packages stale and a
freshly installed engine reads as missing.

Historical accuracy on nine hand-transcribed regions (a small local comparison,
not a current provider ranking or an accuracy guarantee):

| Engine | 1x | 2x |
|---|---|---|
| mistral-ocr | 59.0% | 92.6% |
| Google Lens | 98.3% | **99.3%** |

The tested Lens adapter reported rotation. Preserve rotation from whichever
detector you use; vertical strips require oriented geometry or manual correction.

**Take three levels out of one reading:** blocks (the translation unit, so a
paragraph reads as a paragraph instead of line by line), lines (what a block
splits into when the grouping is wrong), and words (a glyph-tight erase mask, so
you do not blank the whole box and take the artwork with it).

**Input preparation, both rules measured:**

- Composite RGBA onto a background that contrasts with the ink before OCR.
  White works for dark type; pale/white lettering needs a darker preview. Keep
  the original alpha untouched. Hidden RGB under alpha 0 is not reliable context.
- **Upscale by an integer factor only**, `factor = int(1500 // max(w, h))`,
  skipping entirely if that is under 2. Fractional Lanczos measurably hurts OCR:
  2.5x and 1.8x both scored worse than 1x and one run collapsed into a
  repetition loop.

**Read the detector's box convention before slicing anything.** Lens reports a
**centre-rotated** box normalized per axis by its *own* image dimension, so a
154x21 report on a vertical UI strip is 21 wide and 154 tall on screen. Rotate
the four corners and take their axis-aligned bounds, which is the only form a
numpy slice can address, and multiply `center_x`/`width` by image width and
`center_y`/`height` by image height. Reading it naively puts every
vertical-strip box in the wrong place, and the erase then destroys artwork while
leaving the text. Because the coordinates are normalized, an upscale needs no
coordinate correction.

Flag very small detections for enlarged review; size alone is not evidence of an
artifact. Small thumbnail captions can contain real text.

**Where the API returns blocks but no per-line geometry**, recover lines by
clustering the word boxes whose **centre** falls inside the block: sort across
the text direction (by y for horizontal, by x for a quarter-turned strip), start
a new cluster when the gap exceeds `0.6 * median word thickness`, and reverse
the cluster order for vertical right-to-left reading. **Veto the whole result
and return nothing unless the cluster count equals the reported line count** - a
wrong pairing puts text on the wrong box.

When the engine reports no confidence, generate deterministic **review flags**
to sort the queue. Do not present a heuristic score as calibrated confidence:

| Flag | Test |
|---|---|
| `tiny` | min side < 8 or max side < 12 |
| `overlap` | intersects another block |
| `single` | one character |
| `punct` | no alnum |
| `skew` | \|angle\| mod 180 more than 5 degrees from 0/90/180 |
| `sparse` | ink share < 0.02 |

## Translating the extracted strings

**Cut requests at the IMAGE boundary first. Never batch across images.** Group
pending regions per image and never mix two. A group size cap (20 regions) may
split a single dense image into `part N of M`, but it may never merge two
images. The reason is measured: batching across images let a dense tutorial
diagram bleed tone and vocabulary into a two-word menu tab, and one bad line
poisoned strings from unrelated files.

The per-request instruction must name the image file, state the line count, say
these lines are one screen the player sees at once, demand same-count
same-order output, demand brevity because the text must fit the space the
original occupied ("a menu button is not a sentence"), and order numbers,
percent signs, `???` placeholders and non-language symbols (hearts, stars,
arrows, musical notes) preserved exactly **including their position in the
line**.

Join source wrapping within one prose block before translating, then reflow
English to its measured region. Preserve semantic boundaries between headings,
list items, separate captions and animation frames; do not flatten an entire
screen into one paragraph. Store original source/geometry unchanged.

Write back only the `target` field. Boxes and `source` pass through untouched so
a translation run can never move a text box.

## Label plates on photographs: clip at paint time, don't chase the box

The single most expensive lesson of the Ajin Syoujyo set. A menu tile is a photo
with a **label plate** over it - a black or grey bar carrying white type, with
**rounded corners and torn grunge edges**, and the photo pressed right against it.

**The invariant: an edit may only touch pixels that were part of the plate.**

A rectangular fill breaks it, and the damage is obvious next to the original: the
corners square off, the grunge is swallowed, and the fill spills onto the photo -
a slab visibly larger than the bar it replaced. Two files shipped that way before
a human spotted it.

**The fix is a clip applied at paint time, not a cleverer box.** For each row
inside the box, paint only between the first and last pixel of the plate's own
tone *on that row*:

```python
for y in range(y0, y1):
    run = [x for x in range(x0, x1) if is_plate_tone(px[x, y])]
    if not run:                 # a row above/below the plate - leave it alone
        continue
    for x in range(min(run), max(run) + 1):
        px[x, y] = fill          # type between the two ends is what we erase
```

A rounded corner has a short run and stays rounded. A row that holds no plate is
untouched. Grunge outside the box is never reached.

**With the clip in place the box stops mattering**, and that collapses the rest
of the problem: erase the *whole plate*, don't measure the type at all. Every row
is repainted, so no antialiased tip can survive as a ghost. Only measure the type
when something on the plate must be **kept** (a leading symbol, an icon).

Then fit the English to ~60% of the plate height - roughly what CJK type occupies
in its own plate. Fitting to the box height makes it look oversized.

### Finding the plate

Largest **connected blob** of one flat tone. Blob, not projection.

| Tried | Why it fails |
|---|---|
| Row/column projections | a bright photo and a character's eyelashes both read as type |
| One connected component as the *edit mask* | a character tall enough to touch both plate edges **cuts the plate in two** - 食事 splits its plate into three pieces and the largest is a sliver |
| Dropping small components to ignore grunge | flecks on a torn edge are the same colour as type and often the same size as a thin kana's stroke |
| Growing the box until its edges are clean | it grows straight into the grunge, which is as far from the plate tone as type is |

**Pin a seed, never an extent.** For the few plates the blob search gets wrong -
a grey hover plate lying on a grey photo, a dimmed state whose type is grey -
give it a small rectangle of **bare plate**. It says *which* blob and *what tone*.
The plate's size is still measured. Pinning a generous extent is what let the
fill run past the plate in the first place ("a generous plate costs nothing" is
false - the grow step runs straight to its edges).

A seed must sit **clear of the type**: a seed lying on a glyph reads white and
finds nothing. Take the seed's **mode**, not its mean - a seed band usually clips
a few pixels of type at its ends.

For a dimmed/unavailable state, fill from the *seed* colour, not the box mode:
the dim is a translucent wash over the same bar, and the box's mode is the dark
underneath, so filling with it un-dims the plate.

### Check alpha before deciding what "erase" even means

Ajin Syoujyo's scavenging plates look like white type on a black panel. They are
white type on **nothing** - the interior is alpha 0 and the "black" is the game's
background showing through. Filling them black would have shipped an opaque slab
over the scene. Worse, the dimmed variants have a *faint translucent wash*
(alpha 28) that must be reproduced, not cleared to 0.

`alpha_range()` first, every time.
A full-width notification band is the same trap at larger scale: the reference banner looked like flat dark grey and was `(0,0,0,142)` over the scene, so an opaque refill would have shipped a slab.
Sample the modal RGBA of a text-free row and refill with exactly that - the erase is then a plain rectangle and provably exact.
Bound that rectangle by MEASURED ink runs, not eyeballed coordinates, when inline symbols must survive: scanning the band's ink columns put the two `※` marks at 278-305 and 958-986, where the guessed box had left a sliver of a kana standing and clipped the right-hand mark. Then take the erase colour as the **modal
RGBA** inside the frame, which is the wash on dimmed plates and `(0,0,0,0)` on
live ones.

## Hand-lettered graffiti overlays: erase by COMPONENT, not by mask

A scribble overlay - marker handwriting at arbitrary angles on a transparent canvas, mixed with doodles the artist drew around it - looks like the hardest erase in the catalogue and is actually the easiest, because the alpha plane has already segmented it.
Label the alpha (`components()`): every phrase, heart, star and pen-stroke is its own connected component.
Classify EVERY id once as text or decoration - the reference overlay was 79 ids: 60 text, 18 decoration, 1 badge - then erase the text ids to alpha 0 (`clear_components`) and never touch the rest.
Prove the classification before erasing by rendering BOTH halves on grey (`comp_sheet` on the keeps, then on the complement).
The keep sheet answers "is this exactly the decorations?"; the erase sheet answers the question it cannot - "is this exactly the text?" - and on a 68-component overlay it caught a `す` filed as a heart, a stroke of a doodle filed as text, and an English word about to be erased.
Two classes are keeps that read as text at a glance and are easy to get wrong: **strings the author already wrote in English** (a `SEX` in the middle of a Japanese phrase, a `free HOLE♡` label) and **tally marks** (`正`, `丁`) which are counting glyphs, not language.
Erasing either is a defect no residual-Japanese check will ever report.

The method carries its own verification, and each gate is one pixel-diff:
- decorations byte-identical: `(src != out)` over the keep components, ~0 (the reference shipped at 38 px, all deliberate layering of new text over a pen stroke, matching the source's own layering)
- no survivors: text-component pixels still opaque in the erased base, exactly 0
- render the erased base with NO English drawn and look at it - the one image that shows every leftover at once

Three merge traps, all from strokes touching:
- a glyph joined to a decoration reads as ONE component (a kana flowing into a heart).
  Split with a y-cut and keep the largest piece per side (`comp_stamp(ymin=)`).
- anything touching a plate is absorbed into the PLATE's component and silently survives a component erase.
  Handle plate-crossing text with the plate rebuild below, never by component.
- hand-drawn marks cut out by RECTANGLE ship slivers of the neighbouring glyph - it happened twice in one session (a kana tail, a kanji stroke).
  Cut stamps by their component mask, never by box.

**Reuse the author's own marks.**
Never substitute a font heart for a hand-drawn one - cut the originals out (`comp_stamp`) and re-stamp them at the new line ends (`put_stamp`), scaled per site.
Hearts beside vertical JP columns are drawn UPRIGHT in the source, so do not rotate them with the text.

### The overlay's flattened twin is a second file, and its mask is free

A game that ships a graffiti overlay often also ships the **baked** version - the same doodles composited onto the CG for a still, a photo prop, or a gallery frame.
It is the same text, it is a separate file, and translating only the overlay ships a scene that is half translated.
Check the folder for a sibling with a matching stem before quoting the work, and report what you find in one line.

Prove the relationship rather than assuming it: over the overlay's fully opaque pixels, the flattened file should reproduce its colours exactly (`composite_mask` returns that agreement - 0.9994 on the reference pair, 0.09 on a non-pair).
Once proven, the flattened file is the EASY one, because the mask is the overlay's own alpha - exact, free, and needing none of the glyph-mask guesswork a flattened image would otherwise force.
The recipe is three lines: inpaint the flattened file under that mask to recover the clean art, composite the TRANSLATED overlay onto it, done.
For thin isolated strokes, try per-component repair with enough clean context.
Diffusion estimates missing art; it is not exact recovery, particularly where
strokes cross silhouettes. Inspect the erased base and prefer a clean donor or
shape reconstruction when those boundaries matter.

### Angled and vertical text

Recover a baseline angle with an entropy search (`text_angle`): the angle whose perpendicular projection histogram is most concentrated.
PCA is wrong on any two-line block (the axis follows the stack, not the baselines) and automatic band-splitting fails outright because handwritten lines touch.
Do not burn rounds on either: take the axis from entropy, then read each line's ENDPOINTS off a `grid()` zoom by hand.
A whole overlay is a dozen segments, minutes of work, and the segment spec (p0, p1, box height) fixes angle, length and position at once (`marker_line`).

Vertical Japanese becomes English rotated 90 degrees clockwise: p0 at the top, p1 at the bottom, head tilts right like a Western book spine.
Two side-by-side JP columns read right-to-left, and the same rotation stacks two English lines right-to-left automatically, so line 1 of the translation takes the RIGHT column's segment.
A column too short for its phrase extends along its own axis into measured-empty space, or splits into two parallel segments - both beat squeezing the type below legibility.

Collisions are arithmetic, not eyeballing.
Two parallel segments overlap when the perpendicular distance between their midlines is under the sum of their half-heights plus both outlines (`line_gap`) - checking the number up front replaced five render-and-look rounds.
Check new text against KEPT decorations the same way: the regression diff caught an English line covering 196 px of a star burst that looked clear at 1:1, and a 20 px re-route fixed it.

### Rendering marker text

Stroke widths are RATIOS of the drawn glyph height, never absolute pixels.
JP marker graffiti measures its contrast outline at ~0.10 of glyph height and core fattening at ~0.03, and an absolute 6 px outline eats a 22 px cap - that one bug made every short line illegible on the first render.
`marker_line` rasterises an L-mode coverage mask, scales it to the segment, dilates for fatten and outline, and colours LAST - resizing coloured RGBA first smears whatever RGB sits under alpha 0 into the glyph edges.
English condenses happily: stretching marker caps (comicbd) vertically to ~2.8x natural reads fine, but a stretched DISPLAY face fuses at letter junctions when the outline dilates, so beyond ~2x add tracking (~0.05 em) and thin the outline to ~0.06.
Keep the source's censor gag: a censored JP body word becomes the censored EN one with the same U+25CB, drawn as a cap-height ring inside the coverage mask, because comicbd and Inkfree have NO glyph for it.
Draw that ring THINNER than the face's own `O` (about 0.15 of its diameter): at a matched weight `SC○RLET` reads as a typo, and at a lighter one it reads as a censor, which is the whole point of the gag.
Mirror the source's inconsistency instead of tidying it - the reference author censored `乳マ○コ` on one image and wrote `乳マンコ` uncensored on the next, and normalising either way edits the joke.
Render one test line with every symbol the layout needs before committing to a face - PIL has no fallback, and a missing glyph is a tofu box in the output.

## A smooth gradient plate is rebuilt from a MODEL, not an inpaint

A badge or medallion - radial gradient, coloured rim, display type covering most of it - defeats inpainting structurally: the plate is mostly type, diffusion has nothing to anchor on, and the result is blur.
Fit the plate instead.
On the reference badge (ellipse, blue radial gradient, yellow rim, black inner ring) the whole rebuild is four measurements:

1. **Silhouette**: `binary_opening(fill_holes(alpha > 128), disk(12))` - the opening strips handwriting that touches the plate.
   `fill_holes(background | rim)` alone LEAKS wherever a glyph breaks the rim ring, which on the reference was everywhere.
2. **Geometry**: fit the ellipse on rows whose outermost opaque pixel is still RIM-coloured, and only those (`ellipse_from_rows`).
   Type crossing the rim bulges the silhouette and a fit over all rows chases the bulges: rms 42 over all rows, 1.6 over clean rows.
3. **Gradient**: a polynomial colour surface, degree 7 in normalised ellipse coordinates, fitted per channel on surviving background pixels (`surface_fit`) - rms under 1, visually seamless.
   Classify background by HUE COMPLEMENT (on the reference, "bluish": `R<62 and B>R+8`), not by enumerating text colours - the type carried its own gradient, so its dark end matched no swatch list.
4. **Rim bands**: distance-transform inward from the silhouette edge, paint bands by depth (yellow to 6 px, black ring to 11 px, gradient inside), widths read off one clean scanline.

Two failure modes that each shipped a visible defect before being caught:

- **Type crossing the rim is invisible to the interior mask.**
  The glyph mask lives inside an eroded interior, so tips that poke past the rim onto the canvas survive every interior-based erase - the skill's "anything peeled out of the unit is invisible to per-unit checks", in pixels.
  Sweep a box around the plate for text-coloured pixels OUTSIDE the interior and route them through the same rebuild: inside the silhouette, band or gradient by depth, outside it, alpha 0.
- **A rebuilt boundary that disagrees with its untouched neighbours prints a step.**
  Damaged rows rebuilt from the bulged mask met clean rows keeping their own edge, and the rim showed a 2 px ledge.
  Anchor the model per row: interpolate the model-vs-actual edge offset across damaged rows from the clean rows on both sides, smoothed.

Repaint only pixels that need it (glyph mask plus the crossing sweep, dilated ~4) and leave every clean pixel alone - that is also what keeps the final regression diff meaningful.
Type ON such a plate usually has its own construction: the reference title was a pink fill darkening to lower-right (a linear surface fit on glyph pixels), a yellow outline offset (+2, +2) so the rim reads lit from below, and a thin black ring - rebuild that order with `styled_tile`'s `out_off` and `ring`.

## Display type over artwork: measure the coverage, then fill coarse-to-fine

A game title is the hardest erase there is, and the number that decides what is
possible is **how much of its own band the type covers**.
Measure it before choosing anything: the reference title covered **76% of its band
before any dilation, 90% of the band over the character art, in ONE connected
115k-px hole**.
At that coverage there is nothing local left to copy from, and every single-scale
method fails - all of these were run and looked at, not assumed:

| Method | What it did |
|---|---|
| `inpaint_diffuse` (isotropic) | averaged the dark backdrop across the skin - an X-shaped smear |
| `inpaint_rows` | horizontal stripes through the character |
| nearest-colour / Voronoi | crisp but cut wedges of backdrop across the art |
| `cv2.xphoto` FSR | a flat brown block |
| `cv2.inpaint` Telea / NS alone | plausible only within a few px of the rim |

**Check for a clean copy first.** A game sometimes ships the artwork without the
title baked in. Scanning 1,181 images for one whose text-free region matches took
under a minute and would have settled the whole job; here none existed, but the
check is far cheaper than the reconstruction.

**A coarse-to-fine pyramid worked for that large-hole example**
(`inpaint_pyramid`); use the flat-color technique below for crisp silhouettes.
Six `pyrDown`s reduce that 700px hole to a few pixels, where a fill carries a real
colour field, and each level up re-imposes the pixels that survived.
Blend it into Telea by depth into the hole (`inpaint_large`): sharp continuation
near the rim where local structure is still known, smooth field deep inside where
it genuinely is not.
Be honest about what that buys - low frequency is all that survives 90% coverage,
so the result is a soft area, not a recovered picture. In that example the new
type covered most of it; this does not make the technique acceptable for every
logo. Review the erased base and final at game size. Tropical Chase produced an
obvious blurred block, so that repair was rejected. When the user permits image
generation as a fallback, localize the logo crop with the built-in image tool,
then composite only its declared footprint into the pristine source. Preserve
all pixels outside that footprint, review the blend boundary and subtitle, and
reuse the same English logo for its credit-screen variant. Keep the generation
prompt, input/output hashes and local compositing recipe. An explicit offline-only
request still governs which fallback methods are available.

**Do not reach for a plate over the artwork.** Extending a vignette across the
band and setting the type on it hides the problem and dims art the Japanese never
touched; it was tried, and it looked like a box slapped on the picture. Fill it
properly instead.

### Three things that decide whether the fill is clean

- **Stranded islands of "known" pixels inside the hole are leftover glyph rim,
  not artwork.** Any fill that samples them paints their colour outward - here a
  dark blob and a green speck in the middle of an otherwise clean result. Fold
  every enclosed component under ~140px into the hole (`seal_islands`).
- **A colour threshold finds the fill and misses the OUTLINE.** The reference
  subtitle was white with a dark rim over a dark backdrop; the rim matched no
  colour test and survived every fill as a glyph-shaped ghost that four rounds of
  tuning could not remove. Where the background is a smooth gradient, fit it
  (`poly_background`, rms ~1 per channel) and define the hole as **anything that
  deviates from the model** - that catches fill, outline and shadow at once.
- **Bound that deviation term to the ink's own neighbourhood.** Unbounded it
  marks genuine artwork as hole wherever the picture differs from the backdrop
  model, and it erased a band straight across the character's chest. Intersect it
  with a ~26px dilation of the glyph core.

### Seed the mask on pixels that can ONLY be glyph

Before any of the below, check what else in the picture your ink test matches.
A red title on a game about a red-haired character is the trap: `R > G+55 and
R > B+55` looks like "saturated red" and matched **82% of the character's face**,
because skin sits at R-G 108 / R-B 121 while the title's own light band sits at
R-G 83 / R-B 34 - the skin is MORE red-dominant than half the type. The fill then
smeared her eyes, and no amount of tuning the fill fixes a mask that is wrong.

Seed only on what is unambiguous - here saturated red (`R>200, G<90, B<80`) or
neutral white (`spread < 30`), which together dropped face matches to 0.56% - and
recover the rest of the glyph (its light band, outline and shadow) by deviation
**within a dilation of that seed**. Anchoring on a seed is what keeps a
deviation test from eating artwork; an unbounded one erased a band across the
character's chest, and a band that merely reached past the ink's last column
clipped her eye.

Then check it: count how many pixels of a face, or any region the type never
touched, your final mask changed. 399 of 72,800 is a mask; 5,195 is a smear.

### Find the whole ink footprint, or the fill will stain

The thing a reader actually notices is not the hard part of the hole - it is a
soft, glyph-shaped stain over the EASY part, the flat backdrop beside the type.
It has one cause: a colour threshold finds the fill and misses the **dark
outline and the drop shadow**. Those stay "known", so every fill happily
propagates their colour inward.

Find the ink by **local backdrop estimate**, not by colour and not by a fitted
surface: `|image - nconv_background(image, ~core_dilated)| > ~8` catches fill,
outline, shadow and antialiased rim in one test (`nconv_background`).

A fitted polynomial is the trap here, and it cost several rounds. Degree 6 over
a 240px band interpolates the gradient at rms ~1 and then **diverges across a
100px hole** - it predicted R=255 in the middle of a near-black backdrop. Both
the mask built from it and every residual measured against it were nonsense,
which is why a "50% of pixels deviate" reading meant nothing. Normalised
convolution has no such failure mode.

Two more traps in the same area:

- **A per-pixel agreement test is not a REGION.** Deep inside a thick stroke the
  first fill misses any background estimate by more than the threshold, those
  pixels drop out of the "flat" set, keep their approximate fill, and print a
  ghost in exactly the shape of the glyph. Close the agreement mask and
  hole-fill it before using it.
- **Bound any deviation term to the ink's own neighbourhood.** Unbounded, it
  marks genuine artwork as hole wherever the picture differs from the backdrop
  and erases a band straight across the character.

### Measure the clean plate against a never-texted control

"It looks clean at 1:1" is not a check, and neither is a Laplacian: the leftover
stain is LOW frequency, so a sharpness metric scored the stained plate at
**0.00% rough** while the stain was plainly visible. Score deviation from a heavy
blur instead (`smoothness`), over the repaired area AND over an equally sized
patch of the same artwork that never had text on it. Parity with that control is
the pass mark - the reference title finished at mean 0.92 / max 10.3 against a
control of 1.18 / 33.2, i.e. measurably smoother than genuine untouched
background. To see what a reader sees, amplify: `(gray - blur(gray, 25)) * 6 +
128` makes a soft stain obvious and is the view to iterate against.

### Pick the method per pixel by AGREEMENT, not by a hand-drawn split

Half such a band is usually flat backdrop (where the model is exact) and half is
artwork (where that example used a pyramid approximation), and their boundary is a curve
no rectangle follows. Trying to detect that region directly cost several rounds
and produced ragged edges.

The cheap answer is to fill once, then **ask where the fitted background model
agrees with what came out**, and repaint exactly there.
Agreement is the region test: over backdrop the two match to a few levels, over
skin they disagree wildly, so the model can never be painted over artwork.
Feather the agreement mask before compositing so its edge cannot print a seam.

Verify by the same rule as any erase: source-title pixels that are byte-identical
in the output. 311 of 89,407, largest cluster 27px, is coincidence, not surviving
glyphs - and nothing outside the band changed at all.

## Erase strategy by background

| Background | Method | Gotchas |
|---|---|---|
| Transparent canvas | `clear_rect` to alpha 0 | Never fill white. Text on transparency often has a white halo/stroke baked in - reproduce with `stroke_fill` when redrawing. |
| Hand-lettered overlay on transparency | erase by COMPONENT (`clear_components`, section above) | Rectangle erases eat the doodles you must keep. The census also yields the stamps and the proof-of-erase gates. |
| Flat opaque color | `fill_rect` with the **sampled** color | Sample per region - "white" panels are often 250-ish, headers a different cream than bodies. |
| Paper/noise texture | `tile_paper` from a **verified-clean** patch | The one hard rule: the source patch must contain nothing but texture. A source band that clips a panel edge stamps dark streaks across every fill. Low-contrast noise hides tile seams. |
| Striped texture | `patch_rect` with **same-x** source | Vertical stripes: copy from the same columns, different rows (letters, stationery). |
| Vertical-gradient panel | `rowfill` - per-row median from clean columns of the same row | Exclude overlay pixels (red circles) from the sample via `skip=`. Also reproduces underline/highlight streaks that cross the row: sample a column the streak passes through. |
| Horizontal-gradient band | per-**column** median sampled between the glyphs (below) | The only probe allowed to sample inside the box. |
| Busy art (speech bubbles) | Locate the bubble by its **fill color** first, then fill only well inside it | A dark-text bbox probe inside a bubble region catches the dark map showing through the **rounded corners** and returns the whole box - then your fill squares the corners off and paints over art. Bubble tails too. |

**PIL trap:** `ImageDraw.rectangle` fills **inclusive** of x1,y1. Two separate 1-px artifacts in production came from forgetting this (a seam column at a fill boundary, a border's top row eaten by a fill that "stopped at" the border).

### Classifying the background: sample a ring OUTSIDE the box

**Never classify from pixels inside the confirmed box.** A tight box is all ink,
so sampling inside reports "complex artwork" on every region, sends every block
to inpainting, and smears UI art that a flat fill would have erased perfectly.

Sample the frame outside the box at `pad = max(2, min(box.h, box.w) // factor)`
for `factor in (3, 2, 1)`, stopping at the first pad that yields >= 24 pixels.
Fewer than 24 even at `pad=1` means the box touches the image edge, so give up
and return keep-background at confidence 0.2. Then a fixed cascade, each branch
carrying a heuristic score to prioritize review. These values are ranking
weights, not measured probabilities of a correct classification:

| Test | Result |
|---|---|
| share of ring pixels with `alpha > 24` is `< 0.12` | transparent, conf 0.98 |
| `spread(ring) < 7.0` | solid, conf 0.95 |
| re-sample with a **side ring**, then `flat_share(ring, colour, tol=20) >= 0.90` | solid, conf 0.9 if >= 0.97 else 0.8 |
| per-row gradient, then per-column gradient | gradient |
| nothing matched | inpaint, conf 0.35 |

`spread` is the mean absolute deviation from the per-channel median. **Follow the
mean test with a share test**, because `spread` is a mean and one neighbouring
icon clipping a box corner drags a plainly white frame over the threshold. The
**side ring** is the 10px strips left and right of the box on the box's own rows
only: a title inside a coloured header band has plain page above and below it,
and the full frame out-votes the band by area.

Never let a classifier auto-select a cloned donor strip. It picks one only where
the field is flat, and a flat field is better served by a solid fill. That
reasoning does **not** extend to paper texture or vertical stripes, where
`tile_paper` and same-x `patch_rect` remain the right answer - keep the donor
strategies as explicit choices.

### Per-column gradient: sample between the glyphs

For a heading set in a coloured header band there is no clean margin to read, and
the band is barely taller than the text. Filling it with one averaged colour
leaves a visible band, and inpainting is slower and blurrier than the exact
answer, which is one colour per column.

Per column x: **dilate the ink mask with a 7x7 `MORPH_ELLIPSE` first**, or the
median includes the antialiased fade, lands between ink and paper, and repaints
the glyph as a legible ghost. Take the uncovered pixels with `alpha > 24`,
require at least `max(3, height // 8)` of them, and abandon the whole gradient
reading if any column's `spread > 9.0`. Then three checks:

- at least `max(2, width * 0.25)` columns must have a reading. Requiring every
  column to speak for itself rejects ordinary headings whose strokes run the
  full box height.
- **the longest run of columns with no clean sample must be
  `<= max(12, width // 12)`.** A long run is not a hidden gradient, it is artwork
  sitting inside the box, and allowing it bit a white rectangle out of an
  illustration whose edge clipped a caption.
- linearly interpolate surviving gaps across all four channels between the
  nearest known columns on each side, clamping to the nearest known value at the
  ends.

Erase by writing `column_colors[x]` into each masked pixel of that column, and
compute the ink mask itself against the per-column reference broadcast as a
`[1, W, 4]` array rather than against one scalar colour.

## Erasing text that sits on art you must keep

`fill_rect` needs a background you can name. Much of a game's text has none:
labels over portraits, over gradients, over a plate crossed by a diagonal light
streak. Repainting a rectangle there destroys the art. Repaint **only the glyph
pixels** instead and let the surrounding pixels supply the colour.

### Building the mask

**Compute the mask on a crop expanded 2px beyond the confirmed box.** The
antialiased rim sits just outside the box, and a mask built inside the tight box
and pasted in leaves it behind as a coloured ghost of the old text.

**Where the background has no single colour, find glyphs with morphology rather
than a threshold or an edge filter.** Run `MORPH_CLOSE` and `MORPH_OPEN` with an
ellipse kernel of `span = clamp(5, 31, min(h, w) // 2)` forced odd. Close removes
everything darker and thinner than the kernel, open removes everything lighter,
so `(closed - image)` summed over RGB `> 45` is the darker marks and
`(image - opened) > 45` is the lighter ones. A plain blur will not substitute: on
a line of text the window holds more text than background and the reading
inverts.

Each filter also reports the other polarity's background wholesale, so the
combining rule is: **if both masks cover `<= 0.35` of the crop, union them** (the
region genuinely holds light and dark marks), **otherwise keep the smaller mask
and discard the larger, which is the paper.**

**Run the same two filters over the alpha plane too**, with its own single-plane
threshold of 20, and union the result in, but only when
`max(alpha) - min(alpha) > 20`. Text cut into a translucent panel is the panel's
exact colour and is invisible to any RGB reading. Without this, every RPG Maker
battle name plate of opaque glyphs cut into a 70% black bar reads as zero ink and
erases nothing.

Guard the reference-colour path: if a threshold-against-background selection
covered more than **0.70** of the box, treat that as evidence the reference
colour is wrong rather than that the box is solid text, and fall back to the
reference-free polarity reading.

Drop connected components that are both large (`area >= 300`) **and** thick (max
`DIST_L2` `distanceTransform` inside the component `> max(5.0, min(w, h) * 0.45)`).
Thickness alone deletes dense kanji and punches a ghost-shaped hole in the mask.

**Grow the core to the shadow.** A plain luminance-delta mask is too greedy over
artwork: it swallows eye whites, skin highlights and bright ornament, and the
inpaint then drags those across the image. Take the near-white (or near-black)
*core*, dilate it a few pixels, and add only the pixels in that ring that are
darker than the plate. Two numbers decide whether it works:

- `dark_delta` small (about 10) with `halo` large (about 10) is what catches a
  **soft drop shadow**. Miss it and the shadow survives as dark blobs around the
  English. That reads as smearing and sends you hunting the wrong bug - it is not
  the inpaint failing, it is un-erased shadow.
- Where lit and dimmed states share geometry, build the mask from the **lit**
  file and apply it to both. The dim state's grey-on-brown type sits below every
  sensible threshold, and a per-file mask silently leaves it in place.

**Refill the counters when a single-polarity read returns an outline ring.** If
the reading keeps the dark stroke of white-outlined type instead of the fill, the
erase covers a ring instead of a letter, the Japanese fill sits in the middle of
each hole, and every downstream measurement (text colour, cap height, outline
width) describes the stroke rather than the type. The shipped symptom is English
drawn solid black over a name that was white.

Find enclosed regions by padding the mask by 1 with `BORDER_CONSTANT` 0, running
`connectedComponents` on the inverse at `connectivity=4`, and keeping every label
that is not the label at `[0,0]` - that one is the outside background, so
everything else is enclosed. The discriminator between a real counter (the inside
of an `o`) and the interior of an outlined glyph is that **a counter IS the
background whatever the background is doing, while an outlined glyph's interior
is one flat colour that is emphatically not the background.** Union only the
second. Gates: bail if holes cover more than 0.5 of the mask, require at least 12
hole pixels, require `spread(inside) <= 14.0`, and require
`distance(dominant_color(inside), background) > 90` in L1 RGB.

**Expand the mask only far enough to cover the measured antialiased fringe.**
A 5x5 ellipse worked in the measured example; it is not a safe universal setting
for tiny captions, neighboring icons or touching decorations. Check the expanded
mask against protected pixels before any fill. A glyph does not end where the ink mask
does - it fades out over two or three pixels within about 3% of the background,
below any sane ink threshold. Measured, the residual was a max error of 24/765
and was plainly visible on screen. If inpainting is the only strategy that comes
out clean on a flat field, this dilation is the reason it is winning.

**Intersect the mask with the union of the OCR word boxes padded 3px.** A block
rectangle is the bounding box of its lines, so an icon beside a label or a piece
of the illustration inside the same rectangle survives only if the mask is
word-limited. But **defer to the plain box when the word mask covers less than
50% of the padded crop** - a box the user drew by hand or enlarged to catch
missed text has no words to speak for it.

### Choosing the fill

| Structure behind the glyphs | Fill |
|---|---|
| Flat, or horizontal banding | interpolate along each row between the nearest unmasked pixels - exact on bands, cheap |
| Smooth gradients or narrow holes over continuous shading | try diffusion with clean context; inspect for smears and boundary drift |
| Flat-color illustration, crisp silhouette or diagonal banner | clean donor, palette-label continuation or a shape fitted to surviving edges; see below |

Row interpolation across a diagonal streak turns it into horizontal stripes, and
that is the most common cause of "why does this look smeared".

**When variants share a background, rebuild from the siblings.** N cards with the
same artwork and different text repair each other: for each card, replace its own
glyph pixels with the per-pixel median of the others, ignoring each card's own
glyphs (stack the crops, set each card's masked pixels to NaN, `nanmedian`). It
is exact wherever the art is genuinely shared, and it beats any inpaint.

The guard that makes it safe: **where the siblings disagree, the art is not
shared.** Take the per-pixel spread as well, and wherever it is high fall back to
the inpaint. Without that check the median pastes one character's portrait into
another's card, and it surfaces only in the corner where the text happened to
overlap the art.

### Flat-color artwork: continue shapes without mixing the palette

White text over a small cartoon thumbnail exposed a different failure from a
soft gradient: RGB diffusion blended unrelated fills into pale smears and bent
silhouette edges. The defect was most visible in the **erased base**, before new
lettering concealed it. More iterations of the same diffusion did not repair it.

First seek an aligned text-free donor, including another state or a larger copy
used inside a tutorial. Prove agreement in surviving regions and exclude changed
art. Test an untouched control strip, not merely a donor's average brightness.
Musi Dream's mission repair verified a repeating wallpaper period before copying;
its title repair checked the sibling donor against an unlettered strip. Paste
only through the edit mask. If no donor exists, use source structure to choose
a reconstruction:

- For a few flat colors, `images/web_reconstruction.py` samples dominant surviving
  colors, assigns pixels to palette labels, and interpolates the labels' membership
  fields through the glyph hole. It selects a winning label, smooths the boundary,
  and adds a narrow coverage transition before mapping back to source colors.
  This continues silhouettes without averaging whole regions into new colors.
  Palette-label smoothing remains a heuristic; hidden artwork is an estimate,
  so inspect edges rather than treating the helper's result as ground truth.
- For a straight banner edge or simple plate, fit the line/curve from unobscured
  points and reconstruct only the missing portion. The example's manually fitted
  diagonal banner is a per-image exception, not a reusable coordinate test.

Keep context, erase mask and new text bounds separate. The helper can read a wide
context, but only the declared glyph mask is composited back into the source.
Preserve all unaffected pixels and alpha. Calibrate palette thresholds, context,
boundary smoothing and fringe width on the source; this method is unsuitable as
a universal replacement for textured or shaded art. Review edge continuity at
native size and enlarged, then inspect the final thumbnail at its game scale.

### Inpainting: context, alpha, and the silent no-op

**Choose context from the surviving artwork and the method.** Classical Telea
and Navier-Stokes need clean pixels beyond the complete glyph/halo mask; a tight
OCR box can exclude the very edge needed to continue a shape. Increase context
when the repair has no usable boundary, while compositing only the intended mask. Every model or patch-based method gets
context padded by **1x the block's longest side** - a model has nothing to say
about a hole with no picture around it and PatchMatch has nothing to copy.

**Give even a classical fill 0.5x context when `(mask | alpha==0).mean() > 0.90`.**
At 100% mask `cv2.inpaint` returns the crop untouched and raises nothing.
Measured, the fullest crop that still worked was 97.4% and the one that silently
did nothing was 100%. A tight box around a word is mostly word, so this is the
normal case and not a corner case.

**Then verify the fill actually changed pixels:**

```python
moved = (repaired != rgb).any(axis=2)[hole].sum()
```

If nothing moved, treat the repair as failed and inspect the mask/context.
Try a wider clean context or another method within scope; ask the user only if
missing source information prevents a sound repair.

Choose any model-based filler from representative source/output trials in an
authorized workflow. One prior AOT trial on a 259x441 hole returned a dark embossed
blob; that observation does not establish a universal AOT/LaMa size threshold.

**Repair alpha when the old lettering changed it.** On a translucent plate,
leaving opaque glyph alpha behind preserves a word-shaped shadow after RGB is
erased. Use the measured underlying plate alpha or a justified local repair;
leave alpha unchanged when only RGB lettering needs replacement. Transparent
overlays need clearing only for the text, preserving their other components.
A mask-scoped alpha replacement has this form:

```python
view[:, :, 3] = np.where(hole, fill_alpha(view[:, :, 3], hole), view[:, :, 3])
```

Leaving lettering-induced alpha unchanged can preserve a silhouette of the
Japanese after RGB repair. On a name plate of opaque white glyphs
cut into a 70% black bar, the colour comes back as bar and the opacity stays 255,
so over the game background the result is a hard black shadow in exactly the
shape of the words that were supposed to be gone. It looks perfect in an image
viewer on white.

**Add fully transparent pixels to the model's mask rather than feeding them as
context:** `unknown = hole | (view[:, :, 3] == 0)`. The RGB stored under alpha 0
is whatever the exporter left there, usually black, and a reconstruction that
believes it walks that black inwards and darkens the repair. Note the asymmetry -
the model is given `unknown`, but only `hole` is composited back, because the
alpha-0 pixels keep their own invisibility.

Cache reconstructions on `(method, window, crc32(view), crc32(hole))`,
FIFO-capped. A reconstruction is a pure function of exactly those four, so the
hit is exact rather than approximate, and without it turning one type knob
re-runs the model over every block on the image.

### A value that touches its label cannot be split by a gap scan

`最大MP+1` has no gap between the label's last glyph and the `+`. Erasing "up to
where the value starts" leaves a sliver of the last kanji. Erasing through it
eats the value. The value is almost always a different colour from the label, so
`snap_pixels` every saturated pixel in the span, wipe the whole thing, and
`restore_pixels` them back.

## Measuring the original type

**Profile the fill ALONG THE GLYPH before calling it flat, and do it per
component.** Display type is rarely one colour, and a line-wide row average
destroys exactly the evidence: averaging every glyph at a given y mixes the top
of one stroke with the bottom of another and returns a convincing flat number.
On the reference title screen that mistake shipped twice in one image - a red
logo whose light band sits at 48-52% of the glyph height, and a subtitle that
measured "flat 222 grey" three separate ways while plainly reading as chrome.
Label the fill mask, bin each pixel by its normalised height WITHIN its own
component, and read the ramp off that.

**Then cross-section a single stroke to find out which kind of shading it is**,
because a per-glyph gradient and a bevel look alike in a thumbnail and are
rendered completely differently. Print raw luminance down a column through a
stroke. A **gradient** ramps steadily from the glyph top to its bottom. A
**bevel** shows a short bright run at the leading edge of every stroke and a
flat body after it - the reference subtitle was flat 205 grey with a 254 white
run 4-6px deep on top edges only, lit from above, which is why the per-component
profile came out flat and the picture still looked like silver. Reproduce a
bevel as `coverage - shift(coverage, k)` composited over the flat body, not as a
vertical ramp; the median fill and the p90 of the topmost fill pixels give you
the two colours (`bevel_line` in the Kihoushi Scarlet worked example).

**Read the type's colour and its opacity off the same ink mask by two different
methods, never one.** They are independent properties, and taking both from one
bucket of pixels gets the second one wrong with no control on any panel to put
it back.

**Colour: an adaptive-depth erosion core.** Erode the mask with a `(2r+1)^2`
ellipse trying `r=2` then `r=1`, accepting the first peel whose remaining area is
`>= max(12, 0.15 * original_ink)` and otherwise returning the mask untouched. The
peel depth must be adaptive - a fixed 2px peel reads a large outlined heading
correctly and destroys a 13px caption whose strokes are 2px to begin with,
leaving a handful of junction pixels that average to grey. Then take the
**dominant** colour of that core: bucket RGB by `// 12`, pick the most populated
bucket by count, and return the median of only the pixels in that bucket. A plain
median or `Counter` over the whole mask is dragged toward the background by the
antialiased rim.

**Opacity: `np.percentile(alpha[mask], 90)` over the whole mask**, not the core
and not the dominant bucket. Everything that moves a glyph's alpha moves it down
(antialiased rim, cut-out type), so the pixels that are most there speak for the
type. Taking opacity from the winning colour bucket meant 23 pixels of black
outline lying across a 70% band set the entire translation to 70% opacity.

Match the source fill, outline and glow opacity separately. If overlapping
render passes create an unwanted seam, correct the compositing/mask overlap;
do not erase an intentional difference between a solid glyph and a soft halo.

### Outline, shadow and glow are measured INSIDE the ink

**Not in the band beyond it.** An outline contrasts with the background by
definition, so it is already part of the mask, and probing outside finds the
background every time. The symptom is that no outline is ever detected and
white-on-dark UI text ships with no stroke and becomes unreadable over its
background.

Take `rim = mask & ~erode(mask)` and bail if either the core or the rim has fewer
than 12 pixels, since strokes that thin carry no visible outline. The candidate
is `dominant_color(crop[rim])`, rejected unless `distance(colour, fill) > 140`
and `distance(colour, background) > 60`.

**The load-bearing test is the detour check.** Every glyph has a rim differing
from its fill - that is what antialiasing is - and what separates a real stroke
is where the rim colour sits in colour space. A soft edge lies on the line
between fill and background, so if

```
distance(fill, rim) + distance(rim, background) <= distance(fill, background) * 1.25 + 20
```

the rim is antialiasing and no outline is reported. Without it every antialiased
glyph reports a phantom outline and the render draws a real 1-2px stroke in a
colour that was never in the art.

Walk the width outward: for `r` in 2..5, `band = peel(mask, r-1) & ~peel(mask, r)`,
stopping when that annulus has fewer than 12 pixels or its dominant colour is
more than L1 90 from the first ring's colour. Measure stroke, drop shadow and
glow as one thing and redraw them as one stroke - at UI text sizes a soft glow
and a hard outline of the same colour land within a pixel of each other.

### Rescuing a fill colour hidden between the outline strokes

**Trigger the rescue on legibility, not on position.** White type with a dark
outline over bright artwork breaks colour measurement: the lighter relief mask
holds the artwork's own brights and loses to the darker one, so the type measures
as its own outline or as the grey blend around it, and the English ships in a
grey that sinks into exactly the background the original was outlined to stand
off from. On one profile screen this hit 31 blocks out of 80.

Run it only when `distance(text_color, background) <= 350` in L1 RGB and only
when the background classified as inpaint. That threshold is calibrated, not
guessed: every broken reading sat within 285 of its background and every correct
reading that must not be touched sat at 417 or more.

Decide which polarity the ink came from by comparing `|mask & darker|` with
`|mask & lighter|` and take the **opposite** mask, because pooling both sides
lets the artwork's darks out-vote the fill. Dilate the ink mask with a 7x7
ellipse, take `band = opposite & near & ~mask & (alpha > 24)`, then drop pixels
within L1 90 of the measured background - against a dark ring everything beside
it, the paper included, reads as a light mark. Accept the recovered colour only
if the band has `>= max(24, 0.12 * ink_mass)` pixels (an antialiased rim never
reaches 12%), `flat_share(pixels, colour, tol=45) >= 0.35`,
`distance(colour, background) > 90`, and `distance(colour, outline_color) > 90`.
Believe it downstream only if `distance(hidden, text_color) > 140`.

Then swap roles: the old mask becomes the stroke. Otsu-threshold the luma
(`0.299/0.587/0.114`) of the mask pixels, take the half whose dominant colour is
farther from the recovered fill so nothing is assumed about polarity, and set
`width = round(p90 of DIST_L2 distanceTransform inside the mask)` clamped to 1..5.

## Preserve, don't repaint

- **Overlays drawn OVER text** (tutorial red circles, arrows): `snap_pixels` the overlay color inside your edit boxes before erasing, edit, `restore_pixels` after drawing - the overlay ends on top in original draw order. Then check the EN text still **fits inside** the highlight (shorten wording or drop 1pt if it crosses the stroke).
- **Leading symbols** (○ ■ ★ bullets): keep the original pixels, erase only from the symbol's right edge (find it with `xclusters`), draw EN after it. Don't re-render symbols Latin fonts lack.
- **Hand-drawn inline symbols** (hearts, stars, arrows the artist wrote INTO the line): cut them out by component (`comp_stamp`) and re-stamp at the translated line ends (`put_stamp`) - a font ♡ beside marker handwriting reads as a paste-up, and a rectangle crop ships a sliver of the neighbouring glyph.
- **Decorations with no meaning**: kaomoji `(´∀`人)` `＼(^o^)／`, ASCII-art dividers `○●――`, ■-square rows, full-width digits `１：`, already-EN text (NOW PRINTING, OK) - keep as-is. For a line that mixes decoration + JP (e.g. `■■ブッ飛び賞金50万円!!■■`), locate the decoration groups by column ink-density and replace only the JP span between them.
- **UI icons** (refresh arrows, etc.): don't let an erase box eat them. If clipped, restore the icon region by copying from the source image.
- **Intentionally blurred/mosaic text** (fake chat spam): preserve deliberate
  illegibility rather than inventing content. Classify apparent filler from the
  source and runtime context; ask only if unresolved uncertainty affects the
  requested translation.
- **Logos**: respect explicit keep choices and already-English brand lettering.
  An authorized all-image-text pass includes eligible Japanese logos; match their
  existing construction without requiring another approval per asset.
- **Hand-drawn boxes/borders wobble.** Shrink erase rects inward, and if a border still loses a row, copy the border rows back from the source (probe which rows are pure border at text-free columns first).
- **Signatures/autographs**: full-canvas strokes reach the frame - probe ink extents (they went from y=10 to y=419 inside a 430px board here), clear the whole inner board, recreate with a script font + the original's motifs (heart, music note), slight rotation.

## Slots the engine fills in

Japanese counters wrap the number: `残り [N] 日`, `階層 [N] 階`,
`訓練回数：[N] 回`. The gap between the two halves is where the engine draws the
value. It is a keepout. Baking anything into it breaks the display, and so does
closing it up because the English label came out shorter.

English rarely needs the trailing counter word. Put the label in the leading
half, **erase the trailing half and leave it empty**, and keep the gap exactly
where it was: `Sessions:  [N]`, `Floor [N]`. Where the Japanese wraps the number
across two axes - a medallion reading 残り above, N in the middle, 日 below -
split the English into two words around it (`DAYS` above, `LEFT` below) rather
than squeezing a whole phrase into one half.

Spot them by looking for a label with an implausible gap in its middle, then
confirm against the engine's own draw call before filling anything in. And when
the baked-in number shares the region you are erasing, exclude it from the mask
by connected-component area: the number is a single large component, the kana
around it are small ones.

## Text rendering recipes (imgtl.py)

| Original style | Recipe |
|---|---|
| Bold gothic | `arialbd` + optional `stroke_fill` white halo |
| Gothic w/ thick white outline (catchphrase cards) | `stroke=4, stroke_fill=white` |
| Monospace-italic calendar labels | `consolaz` (Consolas Bold Italic) - matches JP gothic-italic look |
| Mincho serif cut-ins w/ red glow | `glow_text` with `timesbd`: blurred colored halo passes + thin edge + solid core |
| Metallic/gradient logo (受精スロット style) | `logo_text`: gradient through text mask + thick light outline + hard offset shadow + shear/rotate. **Sample** gradient top/bottom, outline, shadow colors from original glyph pixels (top rows vs bottom rows). |
| Soft-shadow subtitle | `shadow_text` (blur ~1.0, alpha ~140 - heavier reads embossed) |
| Chrome / silver subtitle (very common on JP title screens) | flat grey body + a white run on the leading edge of every stroke: `edge = clip(cov - roll(cov, k), 0, 1)`, k ~0.13 of the cap height. A vertical white-to-grey ramp is the wrong model and reads as plastic. |
| Handwriting | `segoepr` (print), `segoescb` (cursive/signature), `inkfree` |
| JP symbols needed (♪ ♡ ■ ★) | `jp_font()` = msgothic.ttc via index. **PIL has no font fallback** - a missing glyph renders as a box, so any symbol goes through a JP font. |
| Fat rounded marker graffiti, any angle | `marker_line` (comicbd + proportional strokes + stretch) - full rules in the graffiti section above |
| Censored word (マ○コ style) | keep the gag: `coverage()` draws the ○ as a cap-height ring so it fattens and outlines with its letters |

- **Shorten heading framing only when it is redundant.** A simple topic label
  may need only `X`; a choice prompt or result heading may need `Choose X` or
  `X Results` to preserve the original action or meaning. Judge in the screen's
  context rather than dropping every heading suffix to gain width.
- **Anchors**: `lm` for left-aligned band centers, `mm` for centered labels/badges, `rm` right-aligned, `ls` baseline - used to draw the bottom sliver of a scrolled-off heading (draw the full text with the baseline just above the canvas edge so only the glyph bottoms show, hollow style: white fill + gray stroke).
- **Multi-frame phrases**: a 4-kanji phrase flashed one-kanji-per-frame (処女喪失) becomes word chunks per frame reading in display order (VIR / GIN / ITY / LOST).
- **Sibling screenshots of the same page** should share the same English for
  genuinely shared labels. Compare their source text and geometry first: tutorial
  instructions, highlighted states and inset art can differ. Update the shared
  wording consistently while preserving each variant's distinct content.
- **Choice/label padding**: full-width-space (　) centering padding is layout - keep it around the translated label.

### Stretched, stroked text: one coverage channel, coloured last

**Rasterise to an L-mode coverage mask and colour it at the very end.** The order
is load-bearing at every step.

1. Rasterise the glyphs onto an L-mode tile sized
   `inner / (width_scale/100, height_scale/100)`, where `inner` is the block minus
   `2 * stroke` on each axis, so the rasteriser is always asked for a shape the
   outline actually has.
2. LANCZOS-resize that coverage to `inner`, applying horizontal and vertical
   stretch independently. Photoshop semantics: 50% height gives letters half as
   tall and exactly as wide. Folding height into the point size scales both and
   the control cannot do its job.
3. **Apply the stroke only now**, so a 2px stroke is 2px on all four sides of a
   squeezed letter rather than 1px at the sides. The stroke is
   `cv2.dilate(coverage, disc)` composited under the fill, which is what
   Photoshop means by Stroke: Outside.
4. **Stamp one flat colour behind the coverage mask at the very end.** Resizing an
   RGBA image mixes the colour channels as stored, and what is stored under alpha
   0 is black, so a white letter stretched as RGBA picks up a grey fringe out of
   the emptiness around it that looks like bad antialiasing.

Build the dilation kernel yourself from `hypot` over a meshgrid with
`<= radius + 0.5`, **not** `getStructuringElement`: `MORPH_ELLIPSE` at 3x3 is a
plus sign, and the four missing diagonals are exactly the corners of a stem, so a
1px stroke comes out with four bare specks on every upright.

**Stroke every edge.** Do not try to detect which edges deserve one by
flood-filling the tile to tell counters from inter-letter gaps - a flood cannot
pass a pixel with any ink, so where two antialiased rims meet, an invisible
30%-alpha bridge fences the gap off and white-on-white type runs into itself. A
closing counter is a reason to turn the width down, not to get clever.

Keep a fast path at zero tracking: one `draw.text` call preserves the face's own
kerning pairs, while nonzero tracking places every character by hand. Store
tracking in thousandths of an em so it survives the fit ladder changing the size,
and cap the working tile (4096px) since a 10% scale otherwise asks for a tile ten
times the block.

### Fitting: a named ladder whose rungs are reported

Prefer concise wording over tiny fonts. Report the actual font, ink height,
stroke, wrapping and scale used, including how much smaller the result is than
the source. Pillow's font-size argument is pixels, not physical points. A fixed
7px floor or a fraction of the source size is not a universal legibility limit:
the game's display scale, contrast and neighboring type decide it.

Use a measured fitting ladder: original readable size -> shorter faithful wording
or sensible wrapping -> proven empty draw space -> modest size/spacing changes
reviewed at game scale. If it remains unreadable, revise the wording or layout
within scope rather than silently accepting a successful bounding-box fit.
Measure painted ink with `textbbox`, including stroke, bearings and descenders;
use `textlength`/advance widths for wrap decisions. Check a raster before clipping
it to a destination tile, since clipping can conceal overflow. Include rotation,
tracking and line gaps in the final bounds. Render at final size, or rasterize
only the new glyph masks at a higher scale and downsample those masks. Do not
resize and resample the entire source image merely to antialias the English.

Every rung must fit against what will actually be drawn, so pass `stroke_width`
(only when an outline colour exists), tracking, and the horizontal and vertical
scales into the measurement. Allow wrapping only when the box is tall enough for
two lines (`room_height >= size * 2`) and never for vertical blocks.

A **diagnostic overflow preview** can turn the fitting ladder off: draw the requested size
and grow the *block* around its own centre to hold it, padded 1px each side for
antialiasing, clamped to the image, with a note naming how many px wider or
taller it went and whether the image edge clipped it. A size control that quietly
stops responding when the ink touches the block edge reads as a broken tool.
This is a diagnostic view, not a release result: clipped or overlapping text must
be repaired and pass the normal fit/readability checks before approval.

### Growing a label into space proven empty

Two kanji become seven letters, and forcing that into the Japanese ink box drops
the type well below every other label in the game, which is more visible than the
extra width.

A pixel counts as free on two independent conditions. First it must match this
block's own measured background: `alpha <= 24` for a transparent background, or
L1 distance from the sampled fill `<= 40`, unioned with the alpha test. Second it
must belong to no other block - project the neighbours, and for every other box
whose y-range overlaps this one, mark columns `[other.x, other.x2)` blocked. **A
column is free only if every one of the block's own rows in it is free**
(`strip.all(axis=0)`), so a single artwork pixel anywhere in the column stops the
growth.

Walk left from `box.x` and right from `box.x2` while columns stay free, cap the
result at 1.8x the original width, and if capped **re-centre on the original
centre** rather than letting the label drift to whichever side happened to be
emptier. Disable growth outright for vertical blocks (a rotated strip drawn
rotated pushes the text off its own baseline) and for inpaint, keep, patch and
horizontal-gradient backgrounds, which have no single colour to test against.

**Growth decides where glyphs may be drawn, never what gets rubbed out.** State
it in the code twice. Coupling the two makes a wider draw box eat the artwork
beside the label.

## Grid/cell overlays (calendars, tables, schedule boards)

Overlay images composed over a grid background in-engine have **invisible cell boundaries** - text that looks fine on the transparent overlay overflows day cells in-game. Offline width checks against the JP label's own span are NOT enough (the JP may itself slightly overflow, and the true cell is often narrower than the JP text block).

- **Calibrate from an in-game screenshot**: take two labels far apart with known overlay coordinates, match them to their screenshot positions to get scale+offset, then map the grid lines back into overlay coordinates (Asuka: overlay rendered ~1:1, columns at `x = 97 + 78k` in a 828px overlay - a day cell was 78px, not the ~90px the JP label block suggested).
- Rebuild with **hard per-column limits** (`boundary + 3px grace`), auto-dropping font size (11 -> 10 -> 9) and wrapping to 2-3 short lines per label. Assert every rendered line end <= its limit and print a report.
- **Fit vertically too**: wrapped lines extend below the JP single-line label and clip on the row's bottom border. Calibrate row boundaries the same way (Asuka: `y = 135 + 53k`), shift the block up so the last line clears `row_bottom - 3` (capped ~9px above the JP anchor - the day number sits above), and when a shifted line's rows overlap the kept symbol, indent that line past the symbol instead of letting its erase rect eat the symbol.
- **Verify offline by compositing** the derived grid lines over each output - catches overflow without launching the game.
- Symbol edges under tight JP kerning: gap-scans fail when the symbol and first glyph touch (<=1px gap) or overlap columns (a C's curve inside the star's bbox). Measure **1px-resolution column ink runs** per label and hardcode the split. When glyphs overlap the symbol, trim a couple of symbol-edge pixels rather than leave a glyph sliver.
- Calibrate against the running game before release when available. Ask the user
  for runtime evidence only when it cannot be obtained locally. Keep the per-label
  geometry and rebuild recipe explicit so a later correction is a reproducible run.

## Working through a folder of 3,000 images

A few mechanical steps make a large set tractable, and all of them are worth
scripting once and keeping.

**Crop to the ink before you look at anything.** A picture-layer PNG is mostly
transparent: a 1280x720 canvas holding a 190x60 pill. Contact sheets of whole
canvases are unreadable, contact sheets of the alpha bounding box are legible at
native resolution and pack ten times denser. Compute `ink_bbox` once for every
file, cache it, and key every later step off it.

**Group by geometry with a hash of the alpha silhouette** (`family_key`).
Filename suffixes catch some state variants and miss the rest. The *silhouette*
of the ink crop is identical across lit/dimmed/selected states and different
across artworks, so `md5(alpha > 24) + bbox` groups them for free. On the
reference set 2,095 candidates fell into 1,176 families, and a family is not
just fewer reads - it is one erase box, one font, one anchor, with only the
string changing per member.

Two things will quietly wreck that key, and both were measured:

- **Do not quantise the alpha finely.** A three-level empty/partial/solid key
  grouped only 2 of 5 known lit/dimmed pairs, because one plate sits at alpha 250
  lit and 251 dimmed and the bucket boundary ran between them. The bare
  silhouette grouped 5 of 5.
- **A fully opaque image has no silhouette**, so every full-screen card hashes
  alike - 354 unrelated cards landed in one family. Detect that case and key off
  a **dhash of the luminance** instead: it compares neighbouring cells rather
  than absolute values, so it survives a lit/dim brightness shift while still
  separating different artwork.

Bias toward splitting throughout. A split family costs one extra representative
to look at. A wrong merge silently applies one widget's erase recipe to another.

**Contact sheets for classification.** Numbered grids, ~15 cells a sheet, each
cell composited on a mid-grey checker with its filename and pixel size printed
under it, plus a JSON manifest keyed by cell number. One image read classifies
fifteen files. This is how 3,411 images collapsed to "56 actually carry text".

**Probe sheets before writing anything.** Draw the *proposed* erase box on each
image and put those on a sheet. Every wrong box shows up at once, and you fix the
table instead of discovering the damage in the output. On the base_ui set this
caught a box sitting on a character's eyes and another on a bra strap.

**Rank before you look.** Filename (a clue, not proof of text pixels), folder
role, and aspect/size profile get you a shortlist. Be honest about the weakest
signal: "sits in a UI folder" over-counted 753 candidates where the true figure
was ~150 - a wardrobe folder is 224 pictures *of clothes*, not 224 labels.

**Compare hover/state variants.** Suffixes such as `_s`, `_r`, `siro`, `kuro`,
`_on` or `2` are candidates, not proof of identical art. Verify geometry, text,
palette and alpha before sharing masks. Exact source hashes permit byte fanout;
state-specific tint or opacity needs its own preserved render. The reference
673-file set contained 389 distinct artworks, not 673 interchangeable files.

**Check what the scripts actually reference.** A `[plugin]`-style usage scan found
13 of 27 title-screen buttons were an unused alternate set. Static scans
under-report dynamically-built names, so use this to *prioritise*, not to exclude.
Parse the engine's own show-picture calls rather than grepping for filename
stems: RPG Maker code 231 gave 2,562 live picture names, where substring matching
had called almost everything "referenced".

**Rank by the CJK signal, not by "has small components".** Counting small
connected components scores detailed artwork above text and is useless. What
separates CJK from artwork is that the glyphs are **square and all one size**:
inside a row of ink, split the column profile into groups and count the ones
whose width is within about 30% of the row height and whose fill is between 10%
and 80%. Two or more of those in a row is text.

Understand its false negatives before you lean on it. It misses **text over
artwork** (the ink mask is polluted), **two-glyph labels** (that is the floor),
and anything proportional. Use it to rank and to QA, never to exclude - exclusion
still needs eyes.

**Use the detector to prioritize residual-text review, not certify its absence.**
Run it on source controls containing known small/pale Japanese and on outputs.
English and ornament can also form square groups: all 214 flags in one 1,301-file
run were false positives. That rate shows why the count alone proves neither
coverage nor correctness; visually review the edited set and known blind spots.

**Match its ink threshold to the game's actual ink, or it checks nothing.** That
gate keyed on near-white (`min(RGB) >= 214`) and near-black. This game's header
ribbons are drawn in cream, `(219, 203, 168)`, whose min channel is 168 - so
every ribbon in the game was invisible to the check, including the one file that
had really failed. Sample the ink colour from a few representative families
first and set the thresholds from that, or build the mask at several thresholds
and union the hits. Then read the flagged crops at native resolution: the point
of the gate is the crops, not the count.

**Neither gate replaces the full visual sweep of the edited set.** Sheets of the
*ink crops* of everything you changed, roughly 24 per sheet, is 55 reads for
1,300 files. That is what caught the one real defect on the reference run.

## Discipline that saved reruns

- **Always re-edit from SOURCE after a botched attempt.** Never stack a fix onto a damaged output - the damage compounds. Purely additive follow-ups (`load_out`) are the only exception.
- **Stop iterating on a detector after two failed rounds and measure instead.** Six rounds went into a plate detector that kept trading one family's correctness for another's. The fix was a per-row clip that made detection stop mattering. If round three is still regressing, the model of the problem is wrong, not the thresholds. Read a coordinate grid over the image and hardcode a table - the skill's own advice, and it is cheaper than it feels.
- Keep every edit as a **rerunnable script** (per-image or per-family) so a late wording change is a re-run, not archaeology. Park the per-game workspace (pristine originals, the script, fitted models, outputs) under a stable project folder outside the game (the bundled snapshots used `Active Projects/<game>/images/`) - game folders are volatile by policy, and the parked script is what makes next month's wording change a one-command re-run. This is also what makes the toolkit itself disposable: a bad in-place patch destroyed the shared helper module mid-run, and rebuilding it cost nothing because every family script read from the pristine SRC and could simply be re-run. Not one output was lost.
- **Read a coordinate grid, don't count pixels in your head.** A zoom with labelled x/y gridlines drawn over it turns "measure the plate" into reading two numbers off the picture, and it is faster than any probe for one-off layouts. Keep `grid()` beside `zoom()` and reach for it first.
- Batch by technique (transparent text → logos/glow → bubbles → documents → handwriting), viewing outputs after each batch. Every batch here surfaced at least one probe-vs-reality surprise.
- Verification severity triage: leftover JP / damaged art / wrong meaning = fix. Style-nit = judgment call. "Translation liberty" flags from agents = usually fine.

## Review and runtime proof

Keep a coverage ledger for all in-scope source entries and a separate release
manifest for replacements. A useful manifest binds exact source/output SHA-256,
original archive identity, path, dimensions, mode/format and review evidence.
Include protected regions, measured text bounds and duplicate provenance in the
per-family records. Assembly must reject stale hashes, unresolved entries,
overlapping ownership, unreviewed output and unexpected payload files.

For source regions outside declared edits, compare decoded pixels and preserve
palette/transparency/profile metadata where applicable. Keep source, erased base,
final output, mask and zooms together. Re-encoding changes file bytes, so distinguish
source-to-output pixel preservation from reviewed-output-to-installed byte identity.
For example, converting a JPEG output back to JPEG can alter every clean pixel.

Use separate evidence for these questions:

| Check | What it proves |
|---|---|
| Full image census | All entries classified; text-free, already-English and exclusions remain visible |
| Source/base/output visual review | Meaning, complete erasure, retained art and lettering style |
| Native runtime decode | The actual installed entry decodes with expected geometry and pixels |
| Visible scene review | Correct consumer/state, readable scale, clipping, overlays and click geometry |

Musi Dream's `manual/image_runtime.py` uses detached images/canvases through CDP;
it verifies native decode without putting every asset on the game stage. Its
`--preflight-only` option checks files without contacting a browser and cannot
produce a passing runtime claim. `manual/image_visible.py` and the targeted/menu
checks supply distinct scene evidence. `manual/image_report.py` joins these with
hash-pinned screenshot review; it is not a substitute for looking at the screens.
The completed release has 30 native decode checks, 14 active assets reviewed in
context and 16 other assets with native/source-output review. Do not describe the
last group as played or visibly used.

Compare **encoded installed bytes first**. For a canvas readback, compare
premultiplied RGBA so invisible RGB and alpha round-trip rounding do not masquerade
as art damage. Preserve/check alpha separately. Honor embedded ICC profiles:
Musi Dream's Generic RGB preview required an independent LittleCMS conversion
to sRGB before comparison with Chromium. Only that color-managed case allowed
at most one RGB level of conversion rounding; alpha and encoded bytes were exact.
Do not turn a justified conversion allowance into a blanket pixel tolerance.

For scene QA, verify the actual game/asset path and use an isolated save fixture.
Wait for transitions and image decode, but capture short warning states while
they are present. Confirm ancestor visibility and cover layers, not only a DOM
image's dimensions. Use normal controls to inspect captions behind dialogue and
trigger hover on the element that actually owns the handler. Keep targeted scene
entry checks distinct from normal-route playthrough evidence; see the Tyrano
reference for the engine-specific fixture and consumer details.

Record required exclusions by exact path and reason without reproducing excluded
content. Match a later screenshot against the ledger before treating it as a new
miss. Continue permitted image work and keep excluded assets out of the translated
payload; a complete text catalog does not erase an image limitation.

## Deployment

Resolve the engine's actual image consumer and exact relative path; basename
matching alone is insufficient. Back up originals and verify installed output
hashes. Wolf can read loose `Data/` assets in supported layouts; packed sprites
need the engine adapter and re-export checks above, and encrypted assets need the
matching encrypted runtime path below.

For Tyrano, `[bg]`, non-base `[image]`, buttons and theme CSS can resolve the same
stem under different directories. Musi Dream's active tutorial was a foreground
copy, not its similarly named background image. Its executable loads `app.asar`
first, so the reviewed images use the existing-entry ASAR installer, not an
assumed loose override. See [engine-tyranoscript.md](engine-tyranoscript.md).

Musi Dream preserves some `.jpg` paths while encoding their edited contents as
PNG to avoid lossy recompression. This worked in its Chromium runtime; validate
that behavior before using it in another engine. Preserve indexed controls with
their palette and transparency, rather than assuming an RGBA save is equivalent.
Rebuild, package and test the exact reviewed set. A later Git checkout must retain
those bytes; verify it against the manifest instead of relying on working copies.

### RPG Maker MV/MZ: a 16-byte header plus a 16-byte XOR

MV/MZ do not encrypt the file. They prefix a fixed 16-byte header
`52 50 47 4D 56 00 00 00 00 03 01 00 00 00 00 00` ("RPGMV\0…") and XOR only the
**first 16 bytes of the real payload** with the key, then change the extension.

| Step | Operation |
|---|---|
| Decrypt | assert the header, XOR bytes `[16,32)` with `key[0..16]`, concatenate the untouched remainder |
| Encrypt | XOR the first 16 bytes of the PNG, prepend the header |
| Key | `www/data/System.json` -> `encryptionKey`, 32 hex chars |
| Extensions | `.rpgmvp` (MV, strip 7 chars for the logical name), `.png_` (MZ, strip 5) |

Parse System.json as JSON but fall back to
`re.search(r'"encryptionKey"\s*:\s*"([a-fA-F0-9]{32})"')` because the file can be
malformed, then validate `re.fullmatch(r"[a-fA-F0-9]{32}")` before
`bytes.fromhex`.

**The operational trap: when the game is built with encrypted images the runtime
loads `foo.rpgmvp` and IGNORES a `foo.png` sitting next to it.** A translator who
drops the edited PNG into `img/` sees no change and concludes the edit failed.
Sweep the runtime tree for exactly that case and move the stray PNG into the
editable workspace, quarantining it when a different workspace copy already
exists. Keep editable PNGs in a workspace mirror, never beside the runtime asset,
and back up the original encrypted bytes before the first re-encrypt.

`DAZEDTL_ROOT/util/rpgmaker_images.py:28-33` (header, key length, extensions), `:50-68`
(key read with regex fallback), `:151-169` (decrypt/encrypt), `:274-303` (stray
PNG sweep and quarantine), `:553-586` (backup before overwrite).

### RPG Maker MZ: image families, transparency and runtime caches

Tropical Chase (MZ 1.9.0) exposed these useful checks:

- **Separate baked text from live numbers.** A translated results image does
  not prove TextPicture counters fit on it. This game's 816x624 canvas contained
  a 439x431 painted body. The repaired runtime widened only that body and kept
  the title/other pixels unchanged; all 112 native tally variants then fit.
  Check the actual composition, calculated totals and painted bounds as described
  in [text fitting](text-fitting.md#a-painted-subrectangle-can-be-narrower-than-both-canvas-and-viewport).
- **Measure the consumed frame.** Its MOG title buttons are 200x100 PNGs with
  two 200x50 states. Preserve both frames and inspect selection in the actual
  title menu; a whole-atlas thumbnail does not prove the visible button fits.
- **Inspect transparent captions on contrasting backgrounds.** Black item
  captions looked legible in a white image preview and vanished over a black
  runtime backdrop. A small white outline kept the English readable while
  retaining the original transparent canvas. Credit panels separately used
  black at alpha 173: erase lettering back to that value, not alpha 0 or 255.
- **Distinguish stale caches from failed installation.** In the shipped engine,
  ImageManager.clear() clears _cache but retains _system. A fresh Bitmap.load()
  decoded the installed English splash while loadSystem() still returned the
  Japanese bitmap loaded before installation. Compare installed encrypted hashes
  first, then use a cold start to verify the actual splash sequence. Do not
  overwrite a correct patch merely because a running process kept old pixels.

For black letters with a white outline, mask both. Thresholding only the black
fill left Japanese-shaped white residue on all seven map legends. A verified
nearby sea patch supplied a cleaner repair for the complete lettering footprint;
each map's own red location marker and leader remained untouched.

When a production NW.js build offers no usable debugging endpoint, a temporary
startup QA script can collect Bitmap.snap() captures and native Bitmap.load()
readbacks inside the shipped executable. Keep it out of the patch, redirect
StorageManager.fileDirectoryPath() before test writes, ignore stale queued
requests on a new launch, and restore the exact startup-file bytes in a finally
block as soon as the hook confirms loading. Bound the fixture to the local
workspace and close it afterward. A picture shown at its command 231/232
geometry proves placement; it does not prove its normal route, backdrop or
message overlays were exercised. Require visible/open window evidence before
claiming an overlay check. See [NW.js manifest documentation](https://docs.nwjs.io/References/Manifest%20Format/)
for supported startup injection fields.

### When an official update ships, do not overwrite your redrawn images

**If you have no clean copy of the previous official version of an image, leave
your file alone.** Without the previous original you cannot *prove* the official
asset changed, so overwriting is a guess, and translated title screens, UI
atlases and redrawn CGs are exactly the files a naive "official tree wins" rule
silently reverts.

The rule in operational form: for each path present in your translation, absent
from the committed clean-original baseline, present in the incoming official
tree, not owned by your tooling, and classified as Image/Audio/Video/Font, remove
that path from the proposed official tree before merging. It then exists in
neither the baseline nor the new tree, so the merge simply leaves the
translator's file on disk. Filter the same paths out of any asset change list and
record them in the pending sync plan so a resumed run filters them too.

Record on the manifest which baseline you have (`bootstrap` / `current-game` /
`previous-official`) plus a `has_unbased_tracked_assets` flag. `current-game`
plus unbased assets means the baseline is repairable, so keep offering the
operator the optional "select the clean previous official folder" input until
they supply it. **Distinguish "the official file changed" from "I have no
evidence either way" and refuse to act on the second.**
