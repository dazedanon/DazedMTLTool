# Renderer text fit audit

Measured 2026-09-06T08:16:52.095945+00:00. **0 overflowing displays; 442/442 catalog display units covered; 0 coverage errors.**

Parsed payload SHA-256: `ed1e7171635f0a0eab6b40b36008dc6fa9434ce6846364612e3b09b2807743a0`.

## Coverage and measurements

The coverage consists of 420 story dialogue units, three configuration sample units, 14 distinct choices, four display names, and one catalog punctuation unit. Unchanged source ellipses are also included in complete display pages. All pages are assembled across text, dynamic embeddings, and explicit line breaks until page/clear/branch boundaries; script blocks are skipped.

| Display | Measured occurrences/pages | Largest content height | Constraint |
|---|---:|---:|---|
| normal | 201 | 90.00 px | 870 x 118 px content area |
| bubble | 227 | 131.00 px | Source character width and dynamic height; 1280 x 720 viewport |
| sample | 2 | 29.00 px | 760 x 62 px |
| choice | 33 | 50.00 px | Source size/position; both 4 px column outlines reserved |
| name | 4 | 42.00 px | 360 px width at 26 px font |

## Runtime model

Measurement used the running repacked game's Chromium renderer and computed font family. The normal message font is 28 px with a 36 px line-height declaration, plus the actual 8 px paragraph padding. Chromium's resulting line boxes are measured directly. Source font overrides, normal word wrapping, inline per-character spans, and the inline next-page marker (19 px rendered width plus 3 px left margin) are included. Normal two-line pages measure 90 px. The configuration sample includes its 10 px marker.

Bubble measurement reproduces max/fixed widths and the engine's initial height calculation before its per-character font-size override. It checks the final text and marker against the bubble interior, and the bubble plus tail against the viewport. The character body font remains the source-defined 20, 24, or 28 px. No font or geometry changes are applied.

Nameplates are forced visible only inside the isolated hidden measurement host, with nowrap text for measuring their single-line width. The widest name is Small-Time Ytuber Himarii: 316.56 / 360 px. Every nonempty record has nonzero geometry.

The same renderer model measures source Japanese as a baseline; no source baseline overflow was found. The temporary offscreen nodes are removed in a finally block. The audit does not advance dialogue or alter game state.

## Thrust controls

All 33 choice occurrences fit. The two left/right column origins are 169 px apart; reserving both 4 px outlines leaves a 161 px label border-box budget. The widest revised left-column control is 154.28 px, leaving 6.72 px between outlines.

| Label | Width including padding and trailing NBSP |
|---|---:|
| Deep, slow | 131.56 px |
| Shallow, fast | 147.41 px |
| Deep, fast | 124.69 px |
| Shallow, slow | 154.28 px |
| Short, deep | 135.75 px |

## Remaining observations

- `data/scenario/scene1.ks:43`: final text row is `mind...`; it fits without clipping.
- `data/scenario/scene6_sanran.ks:1568`: final text row is `happened.`; it fits without clipping.
- `data/scenario/scene7_ending.ks:48`: final text row is `there!!`; it fits without clipping.
- `data/scenario/scene7_ending.ks:185`: final text row is `paralysis...`; it fits without clipping.
- `data/scenario/scene7_ending.ks:240`: final text row is `unclear.`; it fits without clipping.
- `data/scenario/scene7_ending.ks:333`: final text row is `fingers.`; it fits without clipping.
- `data/scenario/scene7_ending.ks:366`: final text row is `visible.`; it fits without clipping.
- `data/scenario/scene7_ending.ks:424`: final text row is `attack.`; it fits without clipping.

57 complete displays have a line within 5% of its horizontal budget; each is flagged in the JSON observations inventory. These are measured fits; multi-line pages may naturally fill their first line.

f.piston measured with 8 below 9, 58 below 60, and 888888 in unbounded >60 branches; six digits is a stress case, not a logical maximum.

The report validates text geometry and wrapping. Runtime route progression, save/load behavior, and scene composition are covered by the parent's separate live tests.

## Reproduce

Refresh `manual/runtime_audit/parsed_output.json` from the current build, then run from the game workspace:

```powershell
python translation/manual/fit_audit.py --port 9222
```
