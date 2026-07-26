# Localize Editable Bitmap UI

<task_context>
Translate player-visible source-language text embedded in the editable bitmap UI assets for the
{{ENGINE_NAME}} image profile under this folder, recursively:

`{{EDITABLE_IMAGES_FOLDER}}`

Use this game or project folder as read-only context for vocabulary, image usages, scripts, data,
runtime coordinates, scaling, opacity, and dynamic values:

`{{GAME_ROOT}}`

Apply this engine-profile guidance:

{{ENGINE_CONTEXT}}

Use this file as the authoritative glossary for every translation:

`{{VOCAB_FILE}}`

Read `vocab.txt` before translating any image. Reuse its established names, terms, spelling,
capitalization, and style consistently. If it is missing or does not cover a term, report that
gap and follow the remaining translation precedence below.

The user approves deterministic edits to the PNGs already present under the editable image
folder and creation or update of the single work log required below. Do not modify runtime game
images or any other project files; the Image Manager will patch validated edits later. Store
backups and temporary candidates outside the editable image folder so they cannot be mistaken for
patchable assets. Work through all editable PNGs without asking for confirmation unless a hard
safety rule below requires review.

Runtime assets may be read or decoded in memory or into an isolated temporary directory when
needed to reconstruct an editable image, when permitted by the engine-profile guidance. This does
not authorize modifying those runtime assets. Prefer the project's own clean source layers over
attempting to recover artwork from a flattened text-bearing PNG.
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
- Preserve meaningful background illustrations, including faint watermarks and art visible only
  through a translucent reading surface.
- Retain recoverable originals.
- Maintain one concise Markdown work log covering every image and text region reviewed.
- Include a concise validation report.

## Workflow

### 1. Establish scope

Recursively enumerate the PNGs in the editable image folder. Identify:

- Visible source-language text and intended in-place output paths.
- Authoritative glossary or vocabulary files.
- Related image variants that share a layout.
- Images without player-visible text, which must remain untouched.

The task context grants editing authority only for existing PNGs inside the editable image folder
and its single required `image_translation_log.md` file.

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
- Whether a panel contains faint, translucent, partially obscured, or progression-dependent
  artwork beneath its text.

Create a contact sheet when multiple variants share a layout. View each target at original
resolution before choosing coordinates. Treat distinctive effects as required design constraints,
not optional decoration. A luminous pink title, for example, must remain luminous and pink; flat
white text or a newly invented dark pill is not an equivalent treatment.

Do not decide that a low-contrast region is blank merely because its artwork is subtle. Compare
contrast-enhanced views when necessary, and inspect representative pages from the beginning,
middle, and end of each image sequence. Memo, codex, gallery, and recollection pages commonly
change from a neutral enemy icon on early pages to unlocked scene artwork on later pages.

### 4. Locate clean artwork and source layers

Before choosing any removal method for text over artwork, search the read-only project for a
clean version of every covered visual element. Check:

- Runtime images with matching prefixes, encounter numbers, abbreviations, or character names.
- Enemy battlers, recollections, cut-ins, gallery images, portraits, and layered battle sprites.
- Alternate pages or variants that reveal how the same composition is assembled.
- Code, data, scene, or script references that map an editable filename to a runtime use.
- Additional runtime variants or source layers made accessible by the engine-profile guidance.

Build an explicit mapping from each editable variant to its clean source art. Preserve semantic
and progression differences: for example, use the enemy icon on introductory pages and the
matching recollection illustration only on pages where that illustration is meant to appear.
Confirm the mapping against the flattened source visually; filenames and numbering alone are not
proof. Do not substitute a later unlocked image merely because it is easier to obtain.

If a clean source layer exists, reconstruct the composition from that layer. Do not mask, blur,
clone over, or cover the flattened artwork first.

### 5. Inspect runtime drawing logic

Search the read-only game or project folder for every image filename and any code, data, scene,
or script definition that displays it. Determine:

- Image position, scale, and runtime opacity.
- Runtime-drawn counters, percentages, names, or other values.
- Exact coordinates, font sizes, and alignment of dynamic text.
- Variant-selection logic.
- Whether static text is compared or read back elsewhere.

Treat runtime value locations as protected keepout regions. Do not bake values into the bitmap.
If runtime behavior cannot be established, preserve suspicious blank areas and report the
uncertainty.

### 6. Transcribe and translate

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

### 7. Classify the background

Choose the least destructive valid removal method.

| Background | Preferred method |
| --- | --- |
| Flat UI card | Repaint the complete card |
| Rounded panel | Rebuild the rounded panel |
| Solid background | Fill the bounded text region |
| Simple gradient | Interpolate or clone a clean patch |
| Repeating texture | Clone a nearby matching region |
| Bokeh/noisy field | Clone and feather a clean patch |
| Text over cleanly sourced artwork | Rebuild from the clean art layer, then render text |
| Text over flattened artwork only | Use a precise mask only when demonstrably safe |
| Text crossing a character | Skip and report unless the user supplies a safe method |

Prefer whole-panel reconstruction for structured UI. It avoids blurred remnants and
source-glyph ghosts. However, an art-bearing reading surface is not a disposable flat panel.
Whole-panel reconstruction is valid there only if every meaningful illustration and decoration
is restored from clean sources with the correct placement, opacity, and page-specific state.

### 8. Define an explicit layout

For each reconstructed panel, record its bounds, corner radius, fill color, opacity model,
border, and shadow.

For each translated string, record its text, anchor or baseline, maximum permitted bounds,
font file and size, fill or gradient, outline, shadow, inner and outer glow layers, blur radius,
spread, opacity, offset, blend behavior, alignment, and minimum padding. Sample effect colors
from the source and reproduce multi-layer effects in separate deterministic passes.

For each protected region, record its bounds and required policy: pixel-identical, no text, or
no overlap.

For each reconstructed background illustration, also record its clean source path, crop, scale,
anchor, opacity, compositing order, and the page or state in which it is allowed to appear.

Do not improvise coordinates independently for images that share a template. Define a base
layout and apply only variant-specific overrides.

### 9. Reconstruct panels

Use sampled colors from the original panel when practical. Account for how the game displays
the asset:

- Preserve source alpha behavior when the image contains its own translucency.
- An opaque replacement card may blend correctly when the game applies runtime opacity to the
  whole picture.

Replace enough of the panel to remove every source glyph. Avoid semi-transparent overlays that
leave source text visible beneath them. Do not cover frame borders, portraits, or unrelated
decoration.

When a reading surface contains background art, rebuild in this order:

1. Reconstruct the clean paper, card, gradient, or texture.
2. Composite the correct clean enemy icon or illustration at its source-equivalent crop, scale,
   position, and opacity.
3. Restore safe borders and decorations from clean sources or protected source crops.
4. Render the translated text last.

Do not use an opaque wash to hide source text if it also hides a meaningful illustration. Do not
use a blurred copy of the flattened source as an underprint: blurred glyphs remain glyph-shaped
and the illustration loses detail. Chroma masks and glyph masks are fallback techniques, not a
substitute for source-layer discovery; reject them if outlines, halos, or tinted glyph fragments
remain at original resolution.

Preserve the original relationship between text and background. Do not add a backing rectangle,
pill, card, or heavy shadow when the source text was freestanding. Reconstruct the background
behind the old glyphs, then render the translation with an equivalent outline, glow, bloom, and
layering. Only rebuild a panel when that panel was already part of the source design.

### 10. Fit typography

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

### 11. Protect dynamic values

Reserve the exact runtime-drawn areas discovered from available project or runtime data. Test likely
maximum values such as `0`, `99`, `100`, `999`, and any known project-specific maximum. Ensure
translated labels and suffixes cannot collide with right-aligned or centered runtime values.

### 12. Render representative candidates first

Render from the verified original or backup, never from an earlier candidate. Prefer a
deterministic raster backend such as ImageMagick, Pillow, OpenCV, or Skia. Keep operations
explicit and repeatable.

Before rendering the full batch, render and inspect at least one representative of every
background class, geometry, and progression state. For a multi-page memo set, this normally
includes an early icon page and a later illustration page, plus examples whose art is pale,
dark, highly saturated, or close to the text color. Do not proceed to the full batch until these
samples show all intended artwork and no source glyphs at original resolution.

After the representative gate passes, render the entire candidate set from the backup.

### 13. Validate before installation

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
- Confirm that every source background illustration still exists in the candidate and remains
  recognizable at intended runtime scale.
- Confirm that introductory and unlocked pages use the correct state-specific art rather than a
  single image repeated across all pages.
- For reconstructed art, compare source and candidate for subject identity, crop, placement,
  scale, opacity, compositing order, and visual prominence.
- Compare source and candidate side by side at original resolution and at the intended runtime
  scale. Confirm that glow color, halo footprint, contrast, translucency, and hierarchy retain
  the same visual role and emphasis.
- Reject generic replacement styling that makes a distinctive title or label look flatter,
  darker, brighter, heavier, or more panel-bound than the source.
- Verify the candidate came from the original, not another modified output.

Create contact sheets organized by both template and progression state. A full-set visual sweep
is required even when structural and pixel checks pass; hashes cannot detect an illustration
that was intentionally but incorrectly covered during reconstruction.

Do not install a candidate that fails a hard check.

### 14. Install atomically

After validation:

- Copy or move the candidate over its matching file in the editable image folder.
- Preserve the backup outside that folder.
- Re-run structural checks on the installed file.
- Hash the installed result when reproducibility matters.

### 15. Write the image work log

Create or update exactly one UTF-8 Markdown log at:

`{{EDITABLE_IMAGES_FOLDER}}/image_translation_log.md`

Keep the log lightweight and reviewable. Do not create per-image logs or embed images, binary
data, or long command output. Include a short run summary with the backup location and validation
status, followed by one table row per text region with these columns:

| Image | Region / role | Coordinates `(x, y, width, height)` | Original text | Translated text | Disposition | Notes |
| --- | --- | --- | --- | --- | --- | --- |

Use image paths relative to the editable image folder and source-image pixel coordinates. Use a
disposition such as `translated`, `preserved`, `skipped`, or `review`. Keep notes brief, recording
only useful context such as a dynamic-value keepout, glossary gap, reconstruction method, or
validation concern. Add one image-level row with `none` coordinates for a reviewed image that has
no player-visible text, so the log accounts for every PNG in scope.

If the log already exists, update or replace stale rows for images processed in the current run
instead of duplicating them. Preserve still-relevant rows for images outside the current run.
Escape Markdown table separators and represent intentional line breaks with `<br>` so the table
remains readable.

### 16. Report concisely

Report:

- Files changed.
- Number of translated text elements.
- Representative `before -> after` examples.
- Preserved dynamic or ambiguous elements.
- Backup location.
- Validation performed.
- Work-log location.

Do not paste full image files, large encoded data, or unrelated source code.

## Hard safety rules

- Never alter a portrait or protected artwork merely to make text removal easier.
- Never cover, flatten, or discard faint background art merely to simplify source-text removal.
- Never treat low contrast or partial transparency as evidence that a region is blank.
- Never reveal later progression artwork on earlier pages when the source used a neutral icon.
- Never bake runtime counters or percentages into a static asset.
- Never use a translucent cover that leaves readable source glyphs beneath it.
- Never use blurred source text as a background texture or underprint.
- Never assume blank space is unused when project source can be inspected.
- Never substitute a font silently when exact layout depends on it.
- Never discard a distinctive glow, gradient, outline, shadow, or transparency merely because
  plain text is easier to render.
- Never introduce a generic pill, panel, or badge behind freestanding source text.
- Never install before reviewing the actual rendered candidate.
- Never overwrite the only original.
- Never claim pixel preservation without running a pixel comparison.
- Never modify files outside the editable image folder except for isolated backup and temporary
  validation artifacts. Inside the editable image folder, create no new non-image artifact except
  the single required `image_translation_log.md` work log.

## Decision rules

Use whole-panel reconstruction when text is contained in a reproducible UI card, several labels
share one panel, or localized patching would leave artifacts. If the panel contains meaningful
art, whole-panel reconstruction additionally requires a clean source and an explicit art-layer
recomposition plan.

Use clean-layer recomposition whenever flattened text overlaps an illustration and the project
contains the enemy, recollection, portrait, cut-in, or layered sprite used to build it. This takes
precedence over masks, cloning, blurring, and opaque covers.

Use localized patch replacement when the background is simple and panel reconstruction would
alter too much, or a clean neighboring texture can be cloned safely.

Skip and request review when:

- Text overlaps a character, unique illustration detail, or irregular border.
- Text overlaps flattened artwork and no clean source or demonstrably safe deterministic
  reconstruction is available.
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
- Every intended background illustration remains present, recognizable, and matched to the
  correct progression state.
- Every translated text role retains the source asset's visual identity and relative emphasis.
- Originals remain recoverable.
- `image_translation_log.md` accounts for every reviewed image and text region without duplicate
  current-run entries.
