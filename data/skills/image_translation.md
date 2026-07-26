# Localize Editable Bitmap UI

<task_context>
Translate player-visible source-language text embedded in the editable RPG Maker bitmap UI
assets under this folder, recursively:

`{{EDITABLE_IMAGES_FOLDER}}`

Use this game project as read-only context for vocabulary, image usages, event data, plugins,
scripts, runtime coordinates, scaling, opacity, and dynamic values:

`{{GAME_ROOT}}`

Use this file as the authoritative glossary for every translation:

`{{VOCAB_FILE}}`

Read `vocab.txt` before translating any image. Reuse its established names, terms, spelling,
capitalization, and style consistently. If it is missing or does not cover a term, report that
gap and follow the remaining translation precedence below.

The user approves deterministic edits to the PNGs already present under the editable image
folder. Do not modify runtime game images or any other project files; the Image Manager will
patch validated edits later. Store backups and temporary candidates outside the editable image
folder so they cannot be mistaken for patchable assets. Work through all editable PNGs without
asking for confirmation unless a hard safety rule below requires review.
</task_context>

Translate embedded bitmap text by reconstructing the smallest safe UI regions and rendering
approved target text. Treat each bitmap as a structured interface asset, not merely an OCR
surface. Do not use generative image editing or inpainting.

## Required outcome

Produce localized images that:

- Preserve the original dimensions, format, color mode, and alpha channel.
- Change only approved text or panel regions.
- Leave portraits and protected artwork pixel-identical when feasible.
- Preserve empty spaces used for runtime-drawn values.
- Fit translated text without clipping or collisions.
- Preserve the distinct visual language and emphasis of every text role.
- Retain recoverable originals.
- Include a concise validation report.

## Workflow

### 1. Establish scope

Recursively enumerate the PNGs in the editable image folder. Identify:

- Visible source-language text and intended in-place output paths.
- Authoritative glossary or vocabulary files.
- Related image variants that share a layout.
- Images without player-visible text, which must remain untouched.

The task context grants editing authority only for existing PNGs inside the editable image
folder.

### 2. Preserve originals

Create or verify a backup before changing any material asset.

- Keep the original filename and relative directory structure in the backup.
- Never overwrite the only copy.
- Reuse an existing verified backup rather than replacing it with a modified file.
- Render candidate output to a temporary path outside the editable image folder first.

### 3. Inspect every source image

Record:

- Width and height.
- Format and bit depth.
- RGB/RGBA channel layout.
- Alpha behavior.
- Visible source-language text.
- Repeated panel geometry.
- Character art and other protected regions.
- The visual treatment of each text role: font character, weight, fill or gradient, outline,
  shadow, inner or outer glow, bloom, blur, opacity, offset, and antialiasing.
- Whether each label is freestanding over the artwork or contained by an existing panel.

Create a contact sheet when multiple variants share a layout. View each target at original
resolution before choosing coordinates. Treat distinctive effects as required design constraints,
not optional decoration. A luminous pink title, for example, must remain luminous and pink; flat
white text or a newly invented dark pill is not an equivalent treatment.

### 4. Inspect runtime drawing logic

Search the read-only game project for every image filename and the code or event data that
displays it. Determine:

- Image position, scale, and runtime opacity.
- Runtime-drawn counters, percentages, names, or other values.
- Exact coordinates, font sizes, and alignment of dynamic text.
- Variant-selection logic.
- Whether static text is compared or read back elsewhere.

Treat runtime value locations as protected keepout regions. Do not bake values into the bitmap.
If runtime behavior cannot be established, preserve suspicious blank areas and report the
uncertainty.

### 5. Transcribe and translate

List each visible source string with its role and location. Use this precedence:

1. Authoritative project vocabulary.
2. Existing approved translations.
3. Contextual translation based on the surrounding UI.
4. A conservative literal translation when context is limited.

Preserve:

- Numbers that are already language-neutral.
- Percent signs and other functional symbols.
- Placeholder-like text such as `???`.
- Runtime value slots.
- Intentional capitalization conventions.

Do not rely on OCR alone. Verify OCR output visually, especially for stylized Japanese fonts.

### 6. Classify the background

Choose the least destructive valid removal method.

| Background | Preferred method |
| --- | --- |
| Flat UI card | Repaint the complete card |
| Rounded panel | Rebuild the rounded panel |
| Solid background | Fill the bounded text region |
| Simple gradient | Interpolate or clone a clean patch |
| Repeating texture | Clone a nearby matching region |
| Bokeh/noisy field | Clone and feather a clean patch |
| Text over artwork | Use a precise mask only when safe |
| Text crossing a character | Skip and report unless the user supplies a safe method |

Prefer whole-panel reconstruction for structured UI. It avoids blurred remnants and
source-glyph ghosts.

### 7. Define an explicit layout

For each reconstructed panel, record its bounds, corner radius, fill color, opacity model,
border, and shadow.

For each translated string, record its text, anchor or baseline, maximum permitted bounds,
font file and size, fill or gradient, outline, shadow, inner and outer glow layers, blur radius,
spread, opacity, offset, blend behavior, alignment, and minimum padding. Sample effect colors
from the source and reproduce multi-layer effects in separate deterministic passes.

For each protected region, record its bounds and required policy: pixel-identical, no text, or
no overlap.

Do not improvise coordinates independently for images that share a template. Define a base
layout and apply only variant-specific overrides.

### 8. Reconstruct panels

Use sampled colors from the original panel when practical. Account for how the game displays
the asset:

- Preserve source alpha behavior when the image contains its own translucency.
- An opaque replacement card may blend correctly when the game applies runtime opacity to the
  whole picture.

Replace enough of the panel to remove every source glyph. Avoid semi-transparent overlays that
leave source text visible beneath them. Do not cover frame borders, portraits, or unrelated
decoration.

Preserve the original relationship between text and background. Do not add a backing rectangle,
pill, card, or heavy shadow when the source text was freestanding. Reconstruct the background
behind the old glyphs, then render the translation with an equivalent outline, glow, bloom, and
layering. Only rebuild a panel when that panel was already part of the source design.

### 9. Fit typography

Use real font metrics. Fit text in this order:

1. Use a font that matches the original visual weight.
2. Prefer a condensed family for narrow UI panels.
3. Measure the rendered target string.
4. Reduce font size only within a reasonable visual range.
5. Wrap only when the UI clearly permits multiple lines.
6. Shorten wording only when meaning remains accurate.
7. Skip or request review if no safe fit exists.

Reproduce outlines, shadows, glows, gradients, and translucency consistent with the original
asset. Preserve character-name colors and other meaningful visual distinctions. When the exact
font is unavailable, choose the closest font by shape and weight, but still match the original
effect stack and visual prominence.

### 10. Protect dynamic values

Reserve the exact runtime-drawn areas discovered from source code or event data. Test likely
maximum values such as `0`, `99`, `100`, `999`, and any known project-specific maximum. Ensure
translated labels and suffixes cannot collide with right-aligned or centered runtime values.

### 11. Render candidates

Render from the verified original or backup, never from an earlier candidate. Prefer a
deterministic raster backend such as ImageMagick, Pillow, OpenCV, or Skia. Keep operations
explicit and repeatable.

### 12. Validate before installation

Perform all applicable checks:

- Decode the candidate successfully.
- Confirm exact expected dimensions.
- Confirm format, bit depth, and channel layout.
- Confirm alpha remains present when required.
- Compare protected crops against the original with a zero-pixel-difference target.
- Confirm changed pixels remain inside approved regions.
- Inspect every variant in a contact sheet.
- Inspect important images at original resolution.
- Simulate dynamic values at their runtime coordinates.
- Check for clipping, ghosted source glyphs, bad baselines, and collisions.
- Compare source and candidate side by side at original resolution and at the intended runtime
  scale. Confirm that glow color, halo footprint, contrast, translucency, and hierarchy retain
  the same visual role and emphasis.
- Reject generic replacement styling that makes a distinctive title or label look flatter,
  darker, brighter, heavier, or more panel-bound than the source.
- Verify the candidate came from the original, not another modified output.

Do not install a candidate that fails a hard check.

### 13. Install atomically

After validation:

- Copy or move the candidate over its matching file in the editable image folder.
- Preserve the backup outside that folder.
- Re-run structural checks on the installed file.
- Hash the installed result when reproducibility matters.

### 14. Report concisely

Report:

- Files changed.
- Number of translated text elements.
- Representative `before -> after` examples.
- Preserved dynamic or ambiguous elements.
- Backup location.
- Validation performed.

Do not paste full image files, large encoded data, or unrelated source code.

## Hard safety rules

- Never alter a portrait or protected artwork merely to make text removal easier.
- Never bake runtime counters or percentages into a static asset.
- Never use a translucent cover that leaves readable source glyphs beneath it.
- Never assume blank space is unused when project source can be inspected.
- Never substitute a font silently when exact layout depends on it.
- Never discard a distinctive glow, gradient, outline, shadow, or transparency merely because
  plain text is easier to render.
- Never introduce a generic pill, panel, or badge behind freestanding source text.
- Never install before reviewing the actual rendered candidate.
- Never overwrite the only original.
- Never claim pixel preservation without running a pixel comparison.
- Never modify files outside the editable image folder except for isolated backup and temporary
  validation artifacts.

## Decision rules

Use whole-panel reconstruction when text is contained in a reproducible UI card, several labels
share one panel, or localized inpainting would leave artifacts.

Use localized patch replacement when the background is simple and panel reconstruction would
alter too much, or a clean neighboring texture can be cloned safely.

Skip and request review when:

- Text overlaps a character, unique illustration detail, or irregular border.
- Runtime coordinates cannot be established and collision risk is meaningful.
- Translation cannot fit without materially changing meaning.
- Alpha behavior is uncertain and the asset is composited at runtime.

## Completion criteria

Consider the task complete only when:

- All source strings in scope have a translated, preserved, skipped, or review disposition.
- Every installed bitmap passes structural validation.
- Protected regions pass their required pixel checks.
- Dynamic values have adequate space.
- Visual inspection finds no clipping or source-text ghosts.
- Every translated text role retains the source asset's visual identity and relative emphasis.
- Originals remain recoverable.
