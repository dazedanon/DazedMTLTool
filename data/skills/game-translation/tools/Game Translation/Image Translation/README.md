# Image Translation Toolkit

PIL toolkit for translating text baked into game images in place - matching the
original background, font style, and colors (no caption overlays).

- `imgtl.py` - probes (alpha/band/cluster/bbox/zoom, plus `grid()` for reading
  coordinates straight off a labelled overlay), erasers (clear / fill / patch /
  tile / per-row gradient / `rowclip_fill` for rounded and torn plates), glyph
  masks and inpainting for text that sits on art you must keep
  (`glyph_mask`, `glyph_mask_pure`, `inpaint_rows`, `inpaint_diffuse`,
  `sibling_clean` + `apply_clean` to rebuild a shared background from variants),
  set classification (`family_key`, `cjk_lines`), overlay snapshot-restore (red
  tutorial circles), styled text (stroke outline, glow, gradient logo, soft
  shadow, handwriting fonts, msgothic symbol fallback, `rich_text` for body copy
  with inline emphasis runs), and the **hand-lettered overlay kit** (bottom of
  the file): `components`/`comp_sheet`/`clear_components` for exact
  erase-by-component on transparent canvases, `comp_stamp`/`put_stamp` to reuse
  the author's own hand-drawn hearts and stars, `text_angle` for handwritten
  baselines, `coverage`/`styled_tile`/`marker_line` for outlined marker text at
  any angle with proportional stroke ratios and a drawn censor ring (the
  handwriting faces have no U+25CB glyph), `line_gap` for collision arithmetic,
  `ellipse_from_rows`/`surface_fit`/`surface_eval` to rebuild a gradient plate
  from a model instead of an inpaint, `composite_mask` to prove that a
  flattened CG is an overlay baked onto art (its mask is then the overlay's own
  alpha - exact and free), `inpaint_pyramid`/`inpaint_large` for a hole too big for any
  single-scale fill, `seal_islands` and `poly_background` for the two
  things that otherwise leave a glyph-shaped ghost, `soft_plate` as a last
  resort only, and `glyph_strip` to settle an ambiguous kana against the same author's hand
  elsewhere in the set.

Requires `numpy`; the mask/inpaint helpers and the overlay kit also need
`scipy`; the large-hole helpers (`inpaint_pyramid`, `inpaint_large`) also
need `opencv-contrib-python`.

**Read the full workflow + edge-case playbook first:**
`~\.claude\skills\game-translation\references\image-translation.md`

Quick start:

```python
import sys; sys.path.insert(0, '.')
import imgtl
imgtl.SRC = r"...\Images\ToTranslate"   # originals (never written)
imgtl.OUT = r"...\Images"               # translated outputs
from imgtl import *

im = load('menu.png')
print(alpha_range(im))                  # 0 in min alpha => transparent canvas
clear_rect(im, (10, 20, 200, 44))
text(im, (12, 32), "New Game", 'arialbd', 18, (30,30,30,255),
     stroke=3, stroke_fill=(255,255,255,235), anchor='lm')
save(im, 'menu.png')
```

Graffiti overlay quick start (erase by component, redraw at the source angle):

```python
im = load('rakugaki.png')
lab, recs = components(im)              # classify every id: text vs decoration
comp_sheet(im, lab, KEEP_IDS, 'keeps.png')      # eyeball: decorations only?
heart = comp_stamp(im, lab, 10, ymin=62)        # author's heart, cut clean
im = clear_components(im, lab, TEXT_IDS)
marker_line(im, 'CUM ON', (524, 272), (596, 344), 42,
            imgtl.FONTS['comicbd'], (255,255,255,255), (255,75,181,255))
put_stamp(im, heart, (618, 374))
save(im, 'rakugaki.png')
```

First shipped uses: Asuka Virgin Idol Debut (Wolf RPG) - 36 images, all types
(transparent overlays, paper pages, dark panels, bubbles, logos, glow cut-ins,
hand-drawn sketch, autograph), verified by a 35-agent visual comparison pass.
Kihoushi Scarlet (Wolf RPG) - nine images across two sittings: six
hand-lettered graffiti overlays (up to 180 components, five text angles,
vertical columns), a radial-gradient badge rebuilt from a fitted model, a
flattened copy of one overlay recovered through `composite_mask`, a title
screen whose Japanese covered 90% of the artwork behind it, reconstructed
with `inpaint_large` + `poly_background`, and a translucent banner.
Worked examples kept at
`Tools\Game Translation\Active Projects\KihoushiScarlet (Wolf)\images\`.

## Completed manual/offline example: Musi Dream

Read `C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Musi Dream (TyranoScript)/images/README.md`.
That workspace retains the four `render_*.py` families, local
`web_reconstruction.py` palette-label repair, glossary/brief, pristine sources,
reviewed outputs, masks, crops and hash-bound manifests. Its `manual/image_*.py`
checks distinguish native decoding from visible game screens. All lettering and
translation were completed without OCR, translation or image-generation APIs.

Inspect and adapt the project recipes before running: they contain game paths,
specific geometry and sometimes top-level writes. `web_reconstruction.recover`
is a project helper, not part of shared `imgtl.py`. The shared `load()` converts
to RGBA and `save()` uses the filename's encoder; use explicit Pillow operations
when retaining an indexed palette/transparency, an ICC profile or PNG content at
a preserved `.jpg` path. Follow the image reference for the complete review and
runtime validation workflow.
