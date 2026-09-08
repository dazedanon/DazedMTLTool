Manual offline image controls translation
========================================

Seventeen images were manually translated and redrawn in their original text
regions: config subtitles 402–404, stock title buttons 410–414, game controls
415–421, plugin splash 422, and theme preview 471. Existing English headings,
paper borders, arrows, palette transparency, and illustration pixels outside the
reviewed regions are retained.

Run `python translation/images/render_controls.py` from the game folder. It
always starts with `images/source`, uses the shared `imgtl.py` toolkit, and makes
no network, OCR, translation, or image generation API calls. Transcriptions and
English targets are recorded together in `controls_translations.json`.

The paper control backgrounds are the measured flat RGBA color
`(214, 194, 183, 255)`. Config subtitles occupy a separate alpha band below their
already-English logos. The stock buttons use bounded glyph masks and local
inpainting within their brown gradients. Preview screenshot text uses bounded
glyph masks, retaining its existing paper texture; its tiny save thumbnail is
updated from the translated version of the same demonstration screen.

Indexed GIF and PNG inputs retain their original palette. Only the reviewed edit
zones receive quantized new pixels, and all remaining palette indices are copied
unchanged. A pristine RGB palette snapshot is explicitly restored before saving:
Pillow can otherwise leave an RGBA palette after transparency conversion, which
GIF encoding interprets incorrectly. The encoded outputs are reopened and their
RGBA pixels compared to the pristine source, so this failure cannot pass QA.

All seventeen whole outputs were viewed at 2x. Every text region was also viewed
at 3x, with original native/3x source crops used for transcription. No Japanese
residue, clipped English, opaque alpha boxes, or damaged borders was found.
The full theme preview and its enlarged text regions were inspected separately.
Encoded output dimensions and modes match the originals; all seventeen report
zero changed pixels outside the intended regions. Rerendering reproduced the
same reviewed output hashes. `controls_review.json` binds visual approval to
source and output hashes, so any changed wording or render revokes approval.

The independent tail census covers 251 file records, representing 208 distinct
images across contact sheets 10–18. All frames of the six animated tail images
were inspected; they contain hearts, notes, or next-page dots without text. The
shirt lettering is already Latin **Kiwi** and remains unchanged. Full details
are in `census_tail.json`.
