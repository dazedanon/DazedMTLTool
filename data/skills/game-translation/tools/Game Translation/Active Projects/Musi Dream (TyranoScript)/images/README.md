# Manual image translation workspace

The census covers all 517 image entries (448 distinct byte hashes) in the pristine
game archive, including images outside the standard Tyrano image directories.
The visual review includes animated frames, alpha-cropped character parts,
browser thumbnails, tutorial insets, and shipped templates. Clothing marked
**Kiwi**, fictional service logos already written in English, and decorative
symbols retain their original lettering.

The four rendering families produce 28 translated images; two exact duplicates
receive the same translated bytes, for 30 image replacements. The Hdouga listing
image is excluded because it contains sexual depictions explicitly labeled as
minors. This limitation appears in the release instructions and coverage report.

All translation and lettering are manual and offline. No OCR, translation,
image generation, or other network service is used. `PROMPT.md` and
`image_glossary.json` preserve the brief and terminology.

From the project directory:

```powershell
python images/render_controls.py
python images/render_ui.py
python images/render_title.py
python images/render_web.py
python images/assemble.py
python scripts/package.py --game-root 'C:\Users\sw\Desktop\Games\musi_dream-win32-x64'
```

Renderers always read `images/source`, never the installed patch. Per-family
source/target records, measured regions, fitting choices, masks and magnified
before/after crops are retained here. Approved hashes bind reviews to the exact
output. Wording or rendering changes require a new visual review; `assemble.py`
and the build reject unreviewed outputs.

`assemble.py` merges the four family manifests, checks source identity, fans out
only byte-identical originals, and writes `coverage.json` and `manifest.json`.
`scripts/build.py` checks image hashes against the original ASAR entries before
copying any image into the payload. The installer then verifies every archive
entry and its integrity metadata after repacking.

PNG encoding is used for some original `.jpg` paths to preserve pixels outside
the lettering masks. The game identifies image content by its bytes; the runtime
decode report verifies those actual archive URLs. Indexed controls preserve
their original palette and transparency. Canvas dimensions and click regions
remain unchanged.

Runtime evidence lives in `reports/image_decode.json`, `reports/image_runtime.json`
and the final release validation report. Native image checks do not alone prove
the controls are readable at their scaled in-game sizes; the runtime screenshots
and route checks provide that separate evidence.

The installed image release passed all 30 native decode checks. Fourteen active
assets were also inspected at their actual scene sizes: title and start/load
controls, both hints, insertion tutorial and controls, both warning icons,
mission, browser, removed notice, and concluding caption. The other 16 shipped
template/unused assets have native decode and enlarged visual review coverage.
The normal route reached all nine scenes and returned to the title; menus,
legacy/English saves, text fit, and exact Japanese restoration also passed.
`runtime_review.json` pins the reviewed screenshots to their hashes.

The theme preview retains its original Generic RGB ICC profile. Runtime QA
converts that profile independently to sRGB with LittleCMS before comparison;
Chromium differs by at most one RGB level from conversion rounding, with exact
alpha and encoded bytes. Other images match exactly after premultiplication.
