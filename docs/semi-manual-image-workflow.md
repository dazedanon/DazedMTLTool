# Semi-Manual Image Translation

## Status

Implemented. Reached from the Images page with **Edit text…**, beside the
existing **Copy skill**. Everything it needs beyond the base install is
downloaded on demand the first time it is opened.

## Goal

Translate the text baked into a game's artwork without handing the bitmaps to
anything that repaints them. An OCR engine reads every image, the user confirms
the boxes and the text, DazedTL translates the confirmed export through its
normal pipeline, and only then are the original glyphs erased and the
translation drawn in their place.

## The two image routes

The Images page now offers two ways to translate the same PNGs, and they answer
different questions.

| | **Copy skill** | **Edit text…** |
|---|---|---|
| What is handed over | the bitmaps | the strings |
| Who translates | a coding agent, in its own session | DazedTL's translation engine |
| Who redraws | the agent | this tool |
| Cost accounting | none | the usual per-run accounting |
| Glossary and project prompt | whatever the agent is told | the same as every other engine |
| Good for | freeform artwork, logos, anything needing judgement about the picture | UI text, menus, labels, diagrams |

Neither replaces the other, and neither changes the other's behaviour. Both work
from the same `.dazedtl/images/` workspace that the manager already produces.

## The three steps

Opening the editor gives a modal window with three tabs, and the later two stay
dark until the work that justifies them exists.

1. **Textboxes / OCR** — every editable PNG is read, boxes are drawn and
   numbered in reading order, and anything questionable is flagged amber. Merge,
   split, delete and redraw are first-class: an OCR engine groups lines into
   paragraphs about 80% correctly, so correcting the grouping is the job, not an
   afterthought. Nothing leaves this step until an image is **Confirmed**.
2. **Translation** — the confirmed boxes are exported as `image_text.json` and
   run through the **Image Text** engine, which is a normal entry in the
   translation registry. Live and Batch both work, and the log, progress, cost
   accounting, estimate mode, project prompt and glossary all behave exactly as
   they do on the Translation page. One request per image, deliberately:
   batching across pictures let one image's tone and vocabulary bleed into
   another's.
3. **Render** — the inpainting method, colour, outline, size, alignment and font
   are measured from the image and pre-filled, each labelled *Measured from the
   image · N% confident* until touched. Tracking, horizontal and vertical scale,
   bold and italic sit beside them, neutral until asked for, in Photoshop's
   units so a number copied off that panel means the same thing here. Boxes can
   be added, merged, split and deleted from this step too, because a box that is
   a line too short is something you find out by looking at the render. A pencil
   and eraser handle whatever measurement will never get right; strokes land
   **under** the English, so a touch-up can repair background but never cover the
   translation. The preview renders through the same code path that writes the
   file.

   The eraser has three behaviours, after Photoshop: on its own it removes your
   own marks, **Ctrl** erases the picture itself to transparency, and **Shift**
   paints the block's measured background over it. The cut is a layer of its own
   under `.dazedtl/cut/` — an RGBA image has nowhere to put "take this away",
   since alpha 0 already means "I did not touch this".

Only `target` is ever written back into the exchange file. Boxes and source text
belong to the toolkit and pass through untouched, so a translation run can never
move a text box.

## Erasing what was there

Six ways to rebuild the artwork under a removed glyph, on one picker:

| Method | Needs | Speed | Good for |
|---|---|---|---|
| `telea`, `ns` | nothing — ships with OpenCV | 0.01 s | flat or near-flat backgrounds |
| `patchmatch` | a prebuilt library, ~12 MB | 16 s | screentone, hatching, real texture |
| `lama_manga` | onnxruntime + 197 MB | 1.6 s | the best of these on game and manga art |
| `lama` | onnxruntime + 198 MB | 2.1 s | photographic backgrounds |
| `aot` | onnxruntime + 22 MB | 0.2 s | fast, weaker on saturated colour |

Seconds per box, measured on seven blocks over illustration at 1280×720.
PatchMatch scales with box area far more steeply than the rest, so it is the
only one whose cost is worth thinking about before pressing render.

The two classical fills diffuse surrounding colour inwards, which is honest on a
flat background and a smear on a patterned one. Asking for a method that is not
installed reconstructs the fast way **and says so in the block's note**, rather
than failing.

A block that has never been touched gets `aot` where the model is installed and
`telea` where it is not — `inpaint.preferred()`, probed once per session and
re-probed after a download. Naming a model as *the* default outright would put
every untouched block onto something that may not be there, and the complaint
would arrive at render time on somebody who chose nothing.

Two things about the models were settled by measurement rather than by reading
reference code, and both are pinned as tests rather than left as comments.
**They disagree about what their numbers mean**: LaMa takes 0..1 and returns
0..255, the manga fine-tune returns 0..1, and AOT wants −1..1 at both ends with
its hole zeroed first. And **reading one wrong at both ends is invisible** — it
is an affine transform going in and its inverse coming out, so it cancels, and
what it costs is quality, silently. No picture can test for that, which is why
`ModelConventionTests` states the conventions as facts.

## Extra resources, and why they are not in `requirements.txt`

This workflow needs numpy, OpenCV and an OCR client, and can use several hundred
megabytes of network weights. Everybody who never opens it would otherwise pay
for all of that on every install and every update.

So none of it is declared as a dependency. `util/imagetools/resources.py` holds
the manifest and does the fetching; pressing **Edit text…** shows what is
missing, what it costs and where it comes from, and nothing leaves the network
until the user agrees. The required set plus the cheap model are pre-ticked; the
two 200 MB models are offered unticked.

From a terminal, the same manifest and the same installer:

```
python -m util.imagetools.resources             # what is here, what is not
python -m util.imagetools.resources --default   # the recommended set
python -m util.imagetools.resources --all
python -m util.imagetools.resources lama_manga  # one thing by name
```

Downloads land in `data/models/` and `data/libs/`, both git-ignored. Files are
written to `<name>.part` and renamed only when complete, so an interrupted
download can never be mistaken for a finished one.

**No relaunch is needed.** New packages land in a `site-packages` already on
`sys.path`, so dropping the import caches is enough for the running process to
see them. That only holds because nothing imports numpy or OpenCV until after
the download: every route into the toolkit is a deferred import inside a
function, and `util/imagetools/__init__.py` re-exports lazily for the same
reason. A module-level `import cv2` anywhere in the always-loaded path would
quietly reintroduce the restart.

### The one thing that cannot be deferred

`util/msvc_runtime.py` is called from `gui/main.py`, `scripts/start_gui.py` and
`tests/__init__.py`, before PyQt5 loads, and it is not optional.

PyQt5 carries its own Visual C++ runtime (14.26) in `PyQt5/Qt5/bin`. Windows
resolves a DLL by base name against what is already loaded, so whichever copy
loads first is the one the entire process gets, and onnxruntime refuses to load
against 14.26 with `ERROR_DLL_INIT_FAILED`. Claiming the system runtime after Qt
has loaded does nothing at all — it has to happen first. The module is `ctypes`
and `pathlib` only, returns immediately off Windows, and no-ops when the DLLs are
not there.

## Where things live

```
util/imagetools/            the toolkit, free of PyQt so it stays testable headless
  geometry.py               Box, the one shared primitive
  job.py                    per-image review state and its status ladder
  exchange.py               image_text.json in and out
  ocr/                      Google Lens (default) and RapidOCR (offline)
  style.py                  measuring background, colour, outline, size
  render.py                 erase -> cut -> paint -> draw, and the fit ladder
  paint.py                  the manual touch-up layers
  inpaint.py                the six reconstruction backends
  fonts.py                  font discovery and cap-height fitting
  resources.py              the on-demand downloader (standard library only)

gui/image_text_editor.py    the three-tab shell
gui/imagetext_steps.py      the three steps
gui/imagetext_canvas.py     boxes, pencil, eraser
gui/imagetext_resources.py  the download prompt

modules/imagetext.py        the "Image Text" translation engine
util/msvc_runtime.py        claims the system C++ runtime before Qt
```

## Storage

The editor is a consumer of the workspace the Images page already produces, and
changes nothing about it. Its own state sits beside the editable images:

- Review state: `.dazedtl/images/.dazedtl/image_job.json`
- Pristine originals: `.dazedtl/images/.dazedtl/original/<relpath>`
- Paint layers: `.dazedtl/images/.dazedtl/paint/<relpath>.png`
- Eraser cuts: `.dazedtl/images/.dazedtl/cut/<relpath>.png`
- Exchange file: `.dazedtl/images/.dazedtl/image_text.json`, mirrored into
  DazedTL's `files/` for the translation engine to read

The mirror location can be redirected with `IMGTL_FILES_DIR`, which is what the
tests do so nothing can write into a real `files/` folder.

## Registration

`"Image Text"` is a normal row in `TRANSLATION_MODULE_SPECS`, declared by whole
filename (`image_text.json`) rather than by extension so it can never offer up a
folder of RPG Maker data.

Its branch in `util/subprocess_runner.py` **must stay above the `"Text"`
branch**. That chain dispatches on substrings, and `"Text"` is inside
`"Image Text"`; below it, the whole JSON export would be handed to the plain-text
engine and translated line by line, which destroys the file.
`ImageTextEngineTests` pins the ordering.

## Known limits

- True vertical Japanese layout (*tategaki*) is not implemented; vertical source
  text is measured and re-laid out horizontally.
- PatchMatch is published for Windows and Apple Silicon only. There is no Linux
  build, so it is hidden there rather than offered and then failed.
- PatchMatch is too slow to preview with; pick it for the final render, not
  while adjusting knobs.
- AOT is noticeably weaker on saturated colour than the two LaMa exports. This is
  the model, not the wiring — its error on the *untouched* region measures 8.41
  against 0.74 for LaMa and 0.00 for the manga fine-tune.
