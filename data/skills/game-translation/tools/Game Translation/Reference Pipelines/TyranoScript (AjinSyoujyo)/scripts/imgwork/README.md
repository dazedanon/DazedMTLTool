# Image translation - 亜人少女

Text baked into PNGs, redrawn in place. Outputs go to `tools/translated_images/`,
mirroring their paths inside `app.asar`, and `tl.py deploy` copies them into the
same `override/` tree as the translated scripts - the loader shim swaps a PNG by
exactly the same path rule it uses for a `.ks`, so a redrawn image needs no extra
wiring.

**Sources are never written to.** Every script re-reads from
`tools/extracted/images/` on each run, so a wording change is a re-run, not
archaeology, and a botched attempt can never compound.

## The house style

The game already ships a bilingual convention: on the wardrobe banners the
Japanese stays and a small English word sits under it in a Roman serif -
`kigaeui/fukusoukuro.png` reads 服装 / *clothes*, `fukusyokukuro.png` 服飾 /
*accessory*, `hairk.png` 髪型 / *hair*. It applies that convention unevenly,
though: half the wardrobe buttons have no English at all, every 服装 variant
reads a bare "clothes" whatever is in the brackets, both 下着（他）and 下着（上）
read "underclothes_top", and all three undress buttons read "Remove".

So there are two treatments, chosen by the plate, not by preference:

* Where the Japanese sits in the upper part of a plate and the shipped design
  already puts a sub-line under it, the Japanese **stays** and only the sub-line
  is set, in the same place and the same style (`ajin.bilingual()`).
* Everywhere else the Japanese is **replaced outright**. On a 22px caption strip
  or a small command button there is no room for a second line.

English is set in **Times** (`timesbd` where the original is heavy). The game
draws all its own UI in a mincho-ish serif, so a gothic sans reads wrong.

## The method that works

**The invariant: an edit may only touch pixels that were part of the plate.**

A rectangular fill breaks it, and that is not a small thing. These plates have
rounded corners, torn grunge edges and photographs pressed right against them, so
a rectangle painted over the glyph bounds squares the corners off and spills onto
the photo - `shokuji.png` and `youbou.png` shipped that way first, with a black
slab visibly larger than the bar it replaced.

The fix is a **clip applied at paint time**, not a cleverer box. On each row the
paint runs only between the first and last pixel of the plate's own tone on that
row: a rounded corner has a short run and stays rounded, a row above or below the
plate has no run at all and is left alone.

With the clip in place the box no longer has to be careful, and that collapses
the rest of the problem:

1. **Find the plate** as the largest connected blob of one flat tone.
2. **Erase the whole plate** through the clip. No type measurement, no growing -
   every row is repainted, so no antialiased tip can survive as a ghost, and the
   silhouette is preserved by the clip. Measuring the type is only needed when
   something on the plate must be *kept*, such as a leading symbol or an icon.
3. **Fit the English** to about 62% of the plate height, which is what the
   Japanese occupies.

Plates the blob search gets wrong are pinned as a **seed**: a small rectangle of
bare plate that says which blob and what tone. It must sit clear of the type - a
seed lying on a glyph reads white and finds nothing.

Dead ends, recorded so they are not tried again:

* Row/column projections to find the plate - a bright photograph and a
  character's eyelashes both read as type.
* A connected component as the edit mask - a character tall enough to touch both
  plate edges *cuts the plate in two*: 食事 splits its plate into three pieces
  and the largest is a sliver.
* Dropping small components to ignore grunge - flecks on a torn edge are the same
  colour as type and often the same size as a stroke of a thin kana.

### Check alpha before deciding what "erase" means

`tansakuui`'s action plates look like white type on a black panel. They are white
type on **nothing** - the interior is alpha 0 and the black is the game's
background showing through. Filling them with black would have shipped an opaque
slab. `alpha_range()` first, every time.

## Files

```
imgtl.py            the shared toolkit, copied from Tools\Game Translation\
ajin.py             game-specific helpers: hfill, fit_centered, bilingual,
                    plus the serif fonts the game's own UI implies
relabel.py          find plate -> measure type -> grow -> fill -> fit
sheet.py            contact sheets for bulk classification
probe_boxes.py      draws proposed erase boxes on a sheet, to check before writing
build_title.py      data/image/title        12 files
build_base_ui.py    data/image/base_ui      37 files
build_tansakuui.py  data/image/tansakuui     7 files
build_screens.py    data/fgimage             4 files  full-screen frames
build_hsceneui.py   data/image/hsceneui     40 files
build_wardrobe.py   kigaeui + blui buttons  74 files  sub-line and swap modes
build_cards.py      kigaeui + blui cards   110 files  appearance thumbnails
```

Run any `build_*.py` directly; each is idempotent and rebuilds from source.

## Verification

Every family is checked twice: `probe_boxes.py` before writing, and a
before/after contact sheet after. Anything doubtful is re-rendered at 2-3× and
looked at again - the ghosts in `shokuji_u`, `youbou*` and `tansaku_siro` were
all invisible at 1:1 on a contact sheet and obvious at 2×.

## The plate donor

Some plates cannot be reconstructed by any fill, because they are not one
colour: the H-scene buttons carry a grey grunge wisp, the status header has a
diagonal edge with a photograph showing through, the black tabs have a lighter
border strip down one side. Three ways out, in order of preference:

1. **A group donor.** Every tile of a given size is the same plate art with the
   type in a different place, so a per-pixel estimate across the group recovers
   the bare plate and the erase becomes "repaint whatever differs from it". Take
   the **mode**, not the minimum and not the median: the glyphs carry a dark drop
   shadow, so the minimum tracks the shadow (every erase came out a dark ghost of
   the Japanese), and the median fails on pixels where more than half the tiles
   happen to be inked (white specks). A despeckle pass catches the rest.
2. **A clean scanline**, where the plate's structure is one straight edge. Copy
   from a row clear of the type, and pick the side the edge leans *away* from -
   a row on the wrong side hands back plate for exactly the columns that need
   photo.
3. **A local median inpaint**, where there is no donor at all. Keeps the grunge,
   at the cost of a faint halo where a glyph's outline reaches past the mask.

## State

Every image the scripts load that carries Japanese UI text has been redrawn:
284 files.

| Folder | Files | Redrawn | Notes |
|---|---:|---:|---|
| `data/image/title` | 27 | 12 | 6 labels x idle/hover; the pink pill buttons are unused |
| `data/image/base_ui` | 46 | 37 | 17 labels; `_r` locked states have no text |
| `data/image/tansakuui` | 120 | 7 | rest are item icons, crates, arrows |
| `data/image/hsceneui` | 45 | 40 | 前戯.png is a dead asset, and inverted |
| `data/image/blui` | 154 | 102 | cards, tabs and market buttons; 48 are dead copies |
| `data/image/kigaeui` | 224 | 82 | cards + category buttons; the banners already ship English |
| `data/fgimage` | - | 4 | status, storage and scavenge-result frames |
| `data/image/config` | 30 | 0 | already bilingual (BGM音量 / Music Volume) |
| `data/image/hideoutui` | 28 | 0 | icons, and banners that already read 改装 / Upgrade |
| `data/image/saveload` | 34 | 0 | slot numerals, "Data Load", "Back" |
| `data/image/button` | 28 | 0 | already English (AUTO, SAVE, SKIP...) |
| `cautionui`, `mesbox`, `yui`, `womb`, `kaisou_cg` | 47 | 0 | arrows, frames, locks, artwork |

The `tansaku/北.png`-style compass references in `system/exp.ks` point at files
that **do not exist in the archive** - dead data alongside the malformed
`f.hote` line. Nothing to redraw.
