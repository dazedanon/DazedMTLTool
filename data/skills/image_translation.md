# Localize Editable Bitmap UI

<task_context>
Translate player-visible source-language text embedded in the editable bitmap UI assets for the
{{ENGINE_NAME}} image profile under this folder, recursively:

`{{EDITABLE_IMAGES_FOLDER}}`

Use this game or project folder as read-only context for glossary entries, image usages, scripts, data,
runtime coordinates, scaling, opacity, and dynamic values:

`{{GAME_ROOT}}`

Apply this engine-profile guidance:

{{ENGINE_CONTEXT}}

Use this file as the authoritative glossary for every translation:

`{{VOCAB_FILE}}`

Read the glossary file (`.dazedtl/glossary.txt`) before translating any image. Reuse its established names, terms, spelling,
capitalization, and style consistently. If it is missing or does not cover a term, report that
gap and follow the remaining translation precedence below.

The user approves deterministic edits to the PNGs already present under the editable image
folder, creation or update of the single work log required below, and maintenance of reusable
image-editing resources under this project-local directory:

`{{GAME_ROOT}}/.dazedtl/image_translation_resources`

Do not modify runtime game images or unrelated project files; the Image Manager will patch
validated edits later. Keep verified originals under `.dazedtl/image_backups`, user-supplied clean
art under `.dazedtl/clean_images`, reusable resources under the directory above, and disposable
candidates under that resource directory's `work/` subtree or in an isolated temporary directory.
None of these may be placed inside the editable image folder where the Image Manager could mistake
them for patchable assets. Work through all editable PNGs without asking for confirmation unless a
hard safety rule below requires review.

Runtime assets may be read or decoded in memory or into an isolated temporary directory when
needed to reconstruct an editable image, when permitted by the engine-profile guidance. This does
not authorize modifying those runtime assets. Prefer the project's own clean source layers over
attempting to recover artwork from a flattened text-bearing PNG.
</task_context>

Translate embedded bitmap text by reconstructing the smallest safe UI regions and rendering
approved target text. Treat each bitmap as a structured interface asset, not merely an OCR
surface. Prefer deterministic reconstruction when it can preserve the source visual language and
produce exact target text. Generative editing requires explicit user authorization. Once it is
authorized, use a hybrid workflow by default: generation may supply difficult clean surfaces,
textures, panels, or isolated wordmarks, while exact typography, protected geometry, alpha, and
final compositing remain deterministic whenever practical. A complete component or asset surface
may be repainted when smaller reconstruction methods produce a visibly broken result, but this
does not authorize changing portraits or meaningful scene artwork; those require separate,
explicit approval.

## Required outcome

Produce localized images that:

- Preserve the original dimensions, format, color mode, and alpha channel.
- Preserve the source alpha topology and translucent underpainting outside explicitly approved
  changes, with no seams that appear only when the asset is composited in game.
- Change only approved text or panel regions.
- Leave portraits and protected artwork pixel-identical when feasible.
- Preserve empty spaces used for runtime-drawn values.
- Fit translated text without clipping or collisions.
- Keep the complete post-effect wordmark inside the measured safe component shape, not merely
  inside a rectangular text canvas.
- Preserve the distinct visual language and emphasis of every text role.
- Preserve native component silhouette, perspective, edge direction, anchors, and compactness;
  a clean but oversized or differently shaped replacement is still incorrect.
- Preserve meaningful background illustrations, including faint watermarks and art visible only
  through a translucent reading surface.
- Retain recoverable originals.
- Preserve the reusable inputs and exact rendering decisions needed for consistent future edits.
- Maintain one concise Markdown work log covering every image and text region reviewed.
- Include a concise validation report.

## Workflow

### 1. Establish scope

Recursively enumerate the PNGs in the editable image folder. Identify:

- Visible source-language text and intended in-place output paths.
- Authoritative glossary files.
- Related image variants that share a layout.
- Exact duplicates that can reuse one accepted render, identified by content hash rather than filename alone.
- Near-duplicate families that share geometry but differ by progression state, marker, icon, portrait, or unlocked artwork.
- Stress cases within each family: the longest target strings, smallest native components,
  irregular or sloped faces, low-alpha text, and variants with different anchors or controls.
- Images without player-visible text, which must remain untouched.

Build a family inventory before rendering.
Record which labels and art states are valid in each variant explicitly instead of inferring presence from loose pixel counts or filename numbering.
Do not use filename tokens such as `Dummy`, `template`, `mockup`, `test`, `placeholder`, or
`unused` as evidence that a bitmap can be preserved. Inspect its visible pixels and project usage.
When complete source-language removal is in scope, translate visible source text in an editable
asset unless the user explicitly excludes it, even when the file appears to be an authoring or
reference composite.

The task context grants editing authority only for existing PNGs inside the editable image folder,
its single required `image_translation_log.md` file, verified backups under
`.dazedtl/image_backups`, and reusable support files under
`.dazedtl/image_translation_resources`. Treat `.dazedtl/clean_images` as read-only supplied input
unless the user explicitly asks to change it.

### 1a. Load reusable project resources

Before designing or rendering anything, inspect:

`{{GAME_ROOT}}/.dazedtl/image_translation_resources`

If it exists, read its manifest or index first and reuse its accepted renderer, layouts, clean-art
mappings, exact fonts, masks, approved isolated wordmarks, runtime keepouts, and diagnostics. Run
any bundled resource validator before relying on hashes or paths. A resource package records prior
decisions; it does not override the current glossary, the verified original, or visible evidence.
Report and repair stale paths, missing licensed fonts, hash drift, or contradictory layout data
instead of silently falling back or starting an inconsistent second workflow.

If the directory does not exist, create it when the task produces non-trivial reusable decisions
or assets. Do not create empty placeholder subdirectories.

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
- The alpha plane at original resolution and in a contrast-enhanced view, including soft fades,
  holes, ornaments, low-alpha color, and any existing hard edges.
- Visible source-language text.
- Repeated panel geometry.
- Character art and other protected regions.
- The visual treatment of each text role: font character, weight, fill or gradient, outline,
  shadow, inner or outer glow, bloom, blur, opacity, offset, and antialiasing.
- Whether each label is freestanding over the artwork or contained by an existing panel.
- The source baseline or wordmark direction and, for sloped or irregular containers, the measured
  component edge direction and safe interior shape at native resolution.
- Whether a panel contains faint, translucent, partially obscured, or progression-dependent
  artwork beneath its text.

Create contact sheets when multiple variants share a layout.
View each target at original resolution before choosing coordinates, and create enlarged crops for small labels, borders, counters, or glyph remnants that are hard to judge in a full-screen sheet.
For a flattened composite assembled from reusable components, inventory and review the complete
parent image as its own asset. Localizing a known child component does not prove the parent is
clean: its flattened antialiasing may differ, the localized wordmark may have a wider footprint,
and sibling controls or labels may also be embedded elsewhere in the composition.
Treat distinctive effects as required design constraints, not optional decoration.
A luminous pink title, for example, must remain luminous and pink; flat white text or a newly invented dark pill is not an equivalent treatment.

Do not decide that a low-contrast region is blank merely because its artwork is subtle. Compare
contrast-enhanced views when necessary, and inspect representative pages from the beginning,
middle, and end of each image sequence. Memo, codex, gallery, and recollection pages commonly
change from a neutral enemy icon on early pages to unlocked scene artwork on later pages.
Likewise, do not judge a translucent asset only against an editor checkerboard. Determine the
runtime backdrop, scaling/filtering, and picture opacity when available; these can expose alpha
or matte defects that are inconspicuous in the standalone PNG.

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

Never use a rejected or merely convenient localized candidate as a clean donor. Donors must come
from a verified original or backup, a project-supplied clean layer, or an explicitly accepted and
hashed reusable resource. Match layout, alpha silhouette, ornaments, and art state—not RGB
similarity alone.

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

1. Authoritative project glossary.
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

Review translations as one coherent screen after the literal meaning is established.
Prefer natural UI wording that preserves the source tone and function over awkward word-for-word phrasing, and keep related labels, counters, descriptions, and glossary terms internally consistent.

### 7. Classify the background

Choose the least destructive valid removal method.

| Background | Preferred method |
| --- | --- |
| Flat UI card | Repaint the complete card |
| Rounded panel | Rebuild the rounded panel |
| Solid background | Fill the bounded text region |
| Simple gradient | Interpolate or clone a clean patch |
| Repeating texture | Clone a nearby matching region |
| Native segmented or beveled UI | Rebuild the original component geometry, including borders, dividers, tabs, and texture |
| Small label over pixel art | Use a tightly bounded palette-matched plaque only when clean deterministic reconstruction is unavailable |
| Freestanding text over a regular pattern | Restore only the glyph pixels from the surrounding pattern, then redraw equivalent outlined text |
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

For non-rectangular text containers, also record a safe polygon, mask, or measured edge equations
and the intended baseline angle. Rectangular text bounds are a useful first constraint, but they
do not prove that rotated or shadowed text stays inside a sloped plaque, ribbon, speech bubble, or
irregular button.

Do not let bright roofs, walls, highlights, flowers, arrows, or other background pixels expand a text estimate.
Size any required backing region from the larger of the complete source-glyph footprint, including its outline, and the measured target-text footprint, then add only the minimum safe padding, normally about 2 to 4 pixels per side for small UI labels.

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

Rebuild the actual UI component rather than filling a broad bounding rectangle.
Preserve arrow tails, beveled edges, rounded corners, split label/value cells, divider lines, compact anatomy tabs, and repeating panel patterns.
Repaint label and value subcells independently when a counter contains both static text and a number.
If a native panel texture is regular, reconstruct or tile that texture inside the original shape instead of flattening it to one sampled color.

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

### 9a. Treat transparency as artwork

For every non-opaque asset, treat both color and alpha as visual source material. Preserve source
alpha exactly wherever no approved element changes. Expected alpha changes normally belong only
to removed source glyphs, replacement text and effects, or a deliberately reconstructed native
panel; a broad rectangular cleanup area is not implicitly approved by its RGB bounds.

- Inspect the source alpha plane before editing and diff it against the candidate afterward.
- Build background, underpainting, ornaments, text, glow, and alpha as explicit layers. Do not
  flatten a temporary matte color into transparent or partially transparent pixels.
- Use alpha-aware compositing. When custom math is necessary, blend partially transparent color
  in premultiplied-alpha space and convert back exactly once; do not independently interpolate
  straight RGB and alpha across soft edges or accidentally premultiply twice.
- Preserve meaningful RGB beneath zero and low alpha, or edge-pad it consistently from adjacent
  visible color when reconstruction requires new transparent edge pixels. Hidden matte colors
  can become halos after scaling, filtering, or later compositing.
- When removing glyphs from translucent underpainting, reconstruct continuous color and alpha
  from a verified clean layer or a semantically matching donor. Feathering may soften a valid
  transition, but it must not merely disguise the corners of a rectangular replacement plate.
- Reuse a donor variant only when its alpha silhouette, ornaments, background state, and intended
  artwork match the target. Similar RGB appearance alone is insufficient.
- Source alpha is not automatically immutable where it encodes the source glyph silhouette. When
  a longer translation requires it, reconstruct the complete native component and its alpha
  inside an explicitly approved component mask; preserve alpha exactly everywhere else.

Document every intentional non-text alpha change in the work log, including the source or model
used to reconstruct it. If continuous alpha cannot be recovered confidently, skip and report.

### 10. Fit typography

Use real font metrics. Fit text in this order:

1. Use a font that matches the original visual weight.
2. Prefer a condensed family for narrow UI panels.
3. Measure the rendered target string.
4. Keep a readable size floor appropriate to the asset's runtime scale.
5. Expand a safe label horizontally to the measured target width before shrinking the text below that readable floor.
6. Wrap only when the UI clearly permits multiple lines.
7. Shorten wording only when meaning remains accurate.
8. Skip or request review if no safe fit exists.

Reproduce outlines, shadows, glows, gradients, and translucency consistent with the original
asset. Preserve character-name colors and other meaningful visual distinctions. When the exact
font is unavailable, choose the closest font by shape and weight, but still match the original
effect stack and visual prominence.

When authoritative wording is too long for a native component, prefer a deliberate line break
when the design permits it or a documented family-specific abbreviation that preserves meaning.
Do not stretch the component, distort the type, or shift neighboring controls merely to force the
longest string into one line.

### 10a. Suggested three-gate workflow for preservation-sensitive plaques

When text sits on a native plaque or name tag whose geometry should remain unchanged, consider
this three-gate workflow before repainting the complete component. It is a recommendation for
preservation-sensitive cases, not a replacement for clean-layer recomposition or justified
whole-panel reconstruction.

1. **Clean only the source text.** Build a mask for the complete source glyph face, outline, and
   shadow, then recover only those masked pixels from a verified clean layer or compatible
   same-layout donors. Render and inspect a text-free intermediate before adding the translation.
   Pixel comparison should show zero changes outside the approved cleanup mask; reject residual
   glyph fragments, rectangular fills, altered borders, or changed plate geometry.
2. **Choose typography and effects independently.** Measure the source font character, weight,
   fill, outline, shadow, antialiasing, and baseline direction before positioning the target.
   Measure the plaque's relevant edge slope as well as the source lettering; align the target
   baseline to the native component rather than choosing a plausible-looking angle in isolation.
   Decide the target font, size range, effect stack, and rotation direction from that evidence. Do
   not use a backing rectangle to compensate for uncertain cleanup or placement.
3. **Place and validate the final effected wordmark.** Render the target on its own transparent
   layer with generous internal canvas space. Measure its alpha bounds *after* outline, shadow,
   rotation, filtering, and downsampling; unrotated font metrics are not sufficient. Require a
   small transparent safety margin on every render-layer edge (normally at least 2 to 4 native
   pixels). Treat that rectangular margin and fit inside the native plaque as separate checks. For
   a sloped or irregular face, compare every final-effect alpha pixel against an inset safe polygon
   or mask; a wordmark can clear its canvas while still crossing the component edge. If any alpha
   touches either boundary, correct the angle first when it does not match the measured face, then
   reposition or shrink and render again rather than accepting a clipped stroke or shadow.

Apply the gates separately to layout variants with different anchors. Review the longest labels
at original size and runtime scale over checkerboard, dark, and representative runtime backdrops
before treating a shared family layout as accepted. Do not claim clipping is fixed from font
metrics or canvas bounds alone; inspect the final composite against the actual component edges.

### 10b. Use authorized hybrid generative reconstruction

Use ordinary deterministic reconstruction by default. Use generation only after the user has
explicitly authorized generative output. After authorization, choose the narrowest generative
scope that produces a clean result, but do not preserve a failing localized patch merely because
it changes fewer pixels. A clean full-component or full-surface intermediate can be more faithful
than seams, glyph-shaped debris, or an oversized cover.

1. Keep the verified original or backup canonical and render every generated experiment outside
   the editable image tree. Generated candidates are never self-approving.
2. Lock invariants before generation: dimensions, component silhouette, perspective, anchors,
   borders, icons, portraits, character identity, scene-art crop, runtime keepouts, and alpha
   behavior. Protected portraits and meaningful scene artwork remain out of generative scope
   unless the user separately authorizes changing them.
3. Choose among these scopes from narrowest to broadest: an isolated wordmark; a clean text-free
   texture or panel face; a complete native UI component; or a complete asset surface. Use the
   broader scopes only when deterministic cleanup, clean-layer recovery, and narrower generation
   cannot preserve the source visual language cleanly.
4. For an isolated stylized wordmark, provide the source as a style reference and request only the
   exact translated text on a perfectly flat removable key or genuine transparent background.
   Require generous padding and prohibit characters, scenery, taglines, badges, watermarks, extra
   words, and every other source-image element.
5. For a clean text-free base, ask for the native panel or texture without any lettering, then add
   exact target copy deterministically. A generated clean base is an intermediate reconstruction,
   not permission to replace protected content or drift the component geometry.
6. State required text verbatim and reject any generated spelling, punctuation, or extra-word
   error. Do not hide or paint over a wrong letter. Keep final target typography deterministic
   whenever generation cannot guarantee exact copy, consistent family styling, or precise fit.
7. Match the source's letter-face colors, gradient, highlights, outline stack, dimensional shadow,
   energy, and silhouette. A generated output that fails preservation may still serve as a style
   reference or isolated texture donor, but never as an accepted full replacement.
8. Inspect the actual output dimensions, color mode, and alpha. Never interpret a baked
   checkerboard as transparency. Reject or deterministically recompose wrong-size canvases,
   opaque fake transparency, key-color fringe, altered silhouettes, or hidden matte halos.
9. Treat tiny sprites and compact UI as preservation-sensitive. Work enlarged when helpful, then
   restore the exact source canvas, reviewed alpha, and native-scale filtering deterministically;
   judge the result again at original and runtime size.
10. Remove the source wordmark independently using a clean layer, verified donor, or approved
    deterministic reconstruction. Never rely on the new wordmark or a generated repaint to conceal
    old glyphs; inspect above, below, between, and beyond the source letters.
11. Composite accepted generated layers deterministically onto a candidate derived from the
    verified original or backup. Reuse one accepted wordmark or panel reconstruction across a
    family instead of regenerating inconsistent copies, while retaining legitimate per-variant
    geometry, icon, and art-state differences.
12. Compare generated and deterministic candidates at original and runtime scale over the required
    backdrops. Reject portrait or identity drift, changed crop, changed perspective, oversized
    panels, hidden art, source-glyph ghosts, inconsistent typography, or anything less faithful
    than the source. Do not install a materially generative candidate until the user has been given
    an inspectable proof and has visually approved it.

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
For translucent assets, the representative gate also requires clean alpha-only views and clean
diagnostic composites; structural metadata such as `RGBA` or “alpha present” is not sufficient.

After the representative gate passes, render the entire candidate set from the backup.
Use one shared renderer and one accepted layout for exact duplicates and template families while applying explicit per-variant label and art-state inventories so that reuse does not erase progression differences.

When user visual approval is required, present proof in a form the user can actually inspect while
continuing the conversation: prefer a direct inline native-scale or enlarged runtime-background
composite and also provide the candidate path. Do not rely solely on a gallery thumbnail, a canvas
view that may hide the conversation, or a verbal claim that numerical checks passed.

### 13. Validate before installation

Perform all applicable checks:

- Decode the candidate successfully.
- Confirm exact expected dimensions.
- Confirm format, bit depth, and channel layout.
- Confirm alpha remains present when required.
- For every non-opaque candidate, inspect a contrast-enhanced alpha-only view and an alpha diff
  against the verified source. Confirm alpha changes stay within the approved reconstruction mask
  and contain no unexplained rectangles, long axis-aligned edges, isolated corners, bands, or
  step changes.
- Composite every non-opaque candidate over black, white, midtone, and strongly colored diagnostic
  backdrops, plus a checkerboard and the actual runtime background when available. Inspect these
  composites at original resolution and intended runtime scale and opacity.
- Compare source and candidate over the same backdrops. Inspect every mask boundary and corner for
  seams, matte halos, color fringe, ornament discontinuities, and altered translucent paint.
- Exercise the game's expected scaling/filtering path, or a close deterministic equivalent, so
  low-alpha hidden-color defects cannot pass merely because the unscaled PNG looks clean.
- Compare protected crops against the original with a zero-pixel-difference target.
- Confirm changed pixels remain inside approved regions.
- For surgical cleanup, inspect the text-free intermediate and require zero changed pixels outside
  the approved source-glyph cleanup mask before adding target text. In the final candidate, require
  zero changes outside the union of that cleanup mask and the approved target/effect mask.
- Inspect every variant in a contact sheet.
- Inspect important images at original resolution.
- Reopen every flattened composite or authoring mockup at native scale after all child-component
  replacements. Check the entire parent for ghost text beneath the translation, source pixels just
  outside the child's original footprint, and untranslated sibling labels or footer controls.
- Inspect enlarged crops around every reconstructed boundary and every end of a source string for clipped paint, leaked outlines, and partial source glyphs.
- Simulate dynamic values at their runtime coordinates.
- Check for clipping, ghosted source glyphs, bad baselines, and collisions.
- Measure the complete post-effect alpha after rotation, shadow, filtering, and downsampling. Check
  both transparent canvas padding and clearance inside the actual component safe shape. For sloped
  or irregular containers, validate against the inset polygon or mask pixel by pixel and confirm
  the baseline follows the measured native edge direction.
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
- Treat OCR as a suspect generator, not an acceptance metric. Manually inspect credible hits in
  composited RGB and alpha-aware views; stylized target-language letters, halftone patterns,
  ornaments, and ASCII rules can produce confident false source-language detections.

Create contact sheets organized by both template and progression state. A full-set visual sweep
is required even when structural and pixel checks pass; hashes cannot detect an illustration
that was intentionally but incorrectly covered during reconstruction, and no candidate that
fails a hard check may be installed.

### 14. Install atomically

After validation:

- Copy or move the candidate over its matching file in the editable image folder.
- Preserve the backup outside that folder.
- Re-run structural checks on the installed file.
- Compare each installed file against its validated candidate byte-for-byte or by cryptographic hash.
- Open at least one important installed asset from its final path to confirm that validation did not stop at the temporary candidate.

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

### 15a. Preserve reusable editing resources

Use this canonical project-local root:

`{{GAME_ROOT}}/.dazedtl/image_translation_resources`

Keep a concise `manifest.json` or equivalent index with project-relative paths and cryptographic
hashes. Store only the subdirectories the project needs:

- `scripts/` for deterministic renderers, validators, mask builders, and contact-sheet tools.
- `layouts/` for machine-readable text, coordinates, bounds, font sizes, effect stacks, clean-layer
  mappings, runtime keepouts, and variant overrides when these are not already the renderer's
  source of truth.
- `fonts/` for the exact font binaries required to reproduce accepted output, together with their
  licenses. Reference an existing stable project font in place when duplication is unnecessary.
- `assets/` for reusable isolated layers such as approved wordmarks, repaired clean patches, masks,
  or overlays that cannot be reproduced cheaply from the documented inputs.
- `diagnostics/` for the accepted contact sheets, alpha views, runtime composites, and other small
  visual references that materially help later comparison.
- `work/` for regenerable candidates. Treat this subtree as disposable and never as the only copy
  of an accepted source or reusable asset.

Keep user-supplied clean artwork in `{{GAME_ROOT}}/.dazedtl/clean_images` and verified originals in
`.dazedtl/image_backups`; reference and hash them from the resource manifest rather than
duplicating them without need. Record every clean input's target mapping and semantic role.

Preserve enough information to reproduce the accepted result exactly: translated strings,
coordinates and anchors, font files and hashes, sizes, colors, strokes, gradients, shadows, alpha
and compositing behavior, source/back-up hashes, runtime scale and opacity, dependencies, and the
accepted output hashes. Prefer executable deterministic renderers plus a small manifest over a
prose-only recipe.

Do not copy an unlicensed or ambiguously licensed system font into the project. When copying is
permitted, save its license beside it. Otherwise record the exact family, source path, version or
hash, and a tested fallback, and report that exact reproduction depends on the original font being
available. Never allow an unreported font substitution.

After an accepted revision, update the renderer or layout data, manifest hashes, useful
diagnostics, and work log together. Actually run saved scripts and the resource validator. Do not
store secrets, model credentials, unrelated game data, package caches, or large disposable output.

### 16. Report concisely

Report:

- Files changed.
- Number of translated text elements.
- Representative `before -> after` examples.
- Preserved dynamic or ambiguous elements.
- Backup location.
- Reusable-resource location and what was saved or updated there.
- Validation performed.
- Work-log location.

If any image or text region has a `skipped` or `review` disposition, append a
`### Skipped / review items` section as the literal final section of the user-facing response.
Do not put a closing sentence, follow-up offer, or any other content after it.

In that final section:

1. Group entries by image and list every skipped or review region, the reason it was not changed,
   and what was preserved. Keep the list concise, but do not hide or summarize away individual
   skipped images.
2. End with `Possible next steps:` and list only relevant options the user can explicitly choose:
   - **Try it anyway** — attempt a best-effort deterministic edit despite the stated risk. Explain
     what artwork, alpha, layout, or runtime behavior might be affected, and obtain permission
     before proceeding.
   - **Use generative AI** — try an isolated generated wordmark or label first, or a broader
     generative edit only when the user explicitly authorizes it. State that model safety rules
     may reject some inputs and that generated output still requires deterministic compositing
     and validation.
   - **Provide clean source art or layers** — request a title-free background, layered source,
     alternate asset, or other clean reconstruction input.
   - **Manual artist review** — recommend a human paint-over or source-file edit when neither
     deterministic nor permitted generative methods can preserve the artwork safely.
3. Never imply that an option is guaranteed to succeed, and never perform a newly suggested
   higher-risk or generative method without the required authorization.

If nothing was skipped or marked for review, omit this section entirely.

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
- Never derive a label box from every bright pixel in a broad search region when the region also contains bright artwork.
- Never shrink target text to an unreadable size merely to preserve the source-language width.
- Never install before reviewing the actual rendered candidate.
- Never declare clipping fixed from unrotated font metrics or rectangular canvas bounds alone when
  the containing component is sloped, rounded, skewed, or otherwise irregular.
- Never exempt a bitmap from visible-text review because its filename says `Dummy`, `template`,
  `mockup`, `test`, `placeholder`, or `unused`.
- Never accept a flattened parent composite solely because its reusable child components passed;
  inspect the rendered parent for differing antialiasing, wider target footprints, ghost text, and
  untranslated sibling controls.
- Never overwrite the only original.
- Never claim pixel preservation without running a pixel comparison.
- Never treat “has an alpha channel,” transparent-corner samples, or a checkerboard-only preview
  as sufficient transparency validation.
- Never introduce a broad rectangular alpha/underpainting plate behind localized text unless that
  rectangle is verified native component geometry and its complete boundary is validated.
- Never use a rejected localized candidate as a clean donor for another asset.
- Never treat a generated checkerboard as real transparency or accept a generated canvas without
  verifying its dimensions, color mode, alpha plane, and composited edges.
- Never accept a transparent candidate with seams, matte halos, square corners, or color fringes
  on any diagnostic or available runtime background, even if its standalone preview looks clean.
- Never modify files outside the editable image folder except for verified originals under
  `.dazedtl/image_backups`, reusable support files under `.dazedtl/image_translation_resources`,
  and isolated temporary validation artifacts. Treat `.dazedtl/clean_images` as read-only unless
  the user explicitly authorizes changes. Inside the editable image folder, create no new
  non-image artifact except the single required `image_translation_log.md` work log.

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

When the user has authorized generation, use hybrid generative reconstruction when it materially
improves style fidelity or produces a clean base that deterministic removal cannot. Prefer an
isolated layer or clean component first. Escalate to a complete component or asset-surface repaint
when narrower methods leave seams, source-glyph debris, broken alpha, or distorted native
geometry, then restore exact text, canvas, protected geometry, and alpha deterministically where
needed. This does not relax protection for portraits or meaningful scene artwork.

Use a small palette-matched plaque over pixel art only when the user has authorized that treatment and the original glyphs cannot be removed safely; it must cover the complete source outline, hug the measured source or target text with minimal padding, use a readable outlined font, and avoid unrelated artwork.
Defer large artwork-integrated titles instead of covering them with an oversized box.

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
- Every installed bitmap matches the validated candidate.
- Protected regions pass their required pixel checks.
- Dynamic values have adequate space.
- Visual inspection finds no clipping or source-text ghosts, including in the longest label and
  every distinct layout variant.
- Every final wordmark's full effect alpha clears both its render canvas and the measured native
  component safe shape; non-rectangular components pass shape-aware rather than bounds-only fit.
- Every intended background illustration remains present, recognizable, and matched to the
  correct progression state.
- Every translated text role retains the source asset's visual identity and relative emphasis.
- Every non-opaque installed asset has a reviewed alpha diff and composites cleanly over diagnostic
  and available runtime backgrounds at the intended scale and opacity.
- Originals remain recoverable.
- Every materially generative installed asset has an inspectable proof and explicit user visual
  approval, and its generated inputs and deterministic recomposition are recorded reproducibly.
- The reusable-resource manifest, renderer or layouts, font references, input mappings,
  diagnostics, and accepted hashes reflect the installed revision whenever those artifacts exist
  or the current task produced reusable work.
- `image_translation_log.md` accounts for every reviewed image and text region without duplicate
  current-run entries.
- When any disposition is `skipped` or `review`, the user-facing response ends with the complete
  skipped/review list and relevant recovery options; when none exist, that section is omitted.
