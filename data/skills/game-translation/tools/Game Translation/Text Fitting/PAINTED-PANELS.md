# Painted-panel bounds

`panel_bounds.cjs` reads RGBA pixels, transforms half-open rectangles and checks
four margins. It does not edit images, load fonts or call an API. Browser/NW
loading exposes `GameTranslationPanelBounds`; CommonJS exports the same API.

`pixelBounds(imageData, predicate)` requires a nonempty selection. Calibrate
the predicate from the actual viewed panel; there is no universal panel color.
Exclude independent titles/decorations. For irregular or rounded panels, supply
a verified safe interior or use a mask-aware check instead of the outer box.
`transformRect(rect, {a,b,c,d,tx,ty})` handles axis-aligned affine transforms,
including mirrored scales; it rejects rotation/skew instead of falsely accepting
the enclosing box. Include sprite anchor, crop and parent transforms when
converting a bitmap region into screen coordinates. Call after rendering has
updated the actual consumer, not immediately after changing Game_Picture state.

`measure(panel, ink, minimum)` returns four margins and pass/fail.
`evaluateReport(report, minimum, expectedCases)` recomputes containment from
recorded `rows[].panel/displayed`, ignores old margins/pass flags, and rejects
missing health observations or duplicate `(map,profile,index)` identities.
Expected count is a gate, not proof of complete variant coverage: separately
enumerate the expected maps, profiles and stages as the worked fixture does.

Run with an available Node executable (an explicit full path is fine):

```powershell
& $node test_panel_bounds.cjs
& $node panel_bounds.cjs '..\Reference Pipelines\RPG Maker MZ (Tropical Chase)\evidence\results_panel_before.json' --margin 12 --expect-cases 56 --allow-missing-health
& $node panel_bounds.cjs '..\Reference Pipelines\RPG Maker MZ (Tropical Chase)\evidence\results_panel_after.json' --margin 12 --expect-cases 112
```

The before command must exit 1 (42 failing cases); after exits 0 (112 passing).
The historical before report did not record the engine error panel, so its
explicit opt-in permits geometry replay and reports `engineErrorObserved:false`.
It cannot establish engine health. New reports require that observation.
Malformed inputs exit 2. Replaying observations validates the geometry gate,
not a new native render or a new playthrough. Recorded evidence and project
assumptions live in the Tropical Chase pipeline's PIPELINE.md and provenance.
