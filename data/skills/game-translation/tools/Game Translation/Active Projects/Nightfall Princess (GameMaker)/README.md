# Nightfall Princess - English translation preparation

> Current translation: the manual English text and menu/HUD patch is complete and installed. See [manual-translation/README.md](manual-translation/README.md) for the editable work, validation and restoration instructions. The preparation inventory below is retained as the original source record.

Prepared from the original Japanese GameMaker VM archive on 2026-09-05 using the
game-translation skill and three independent source reviews. This folder is the
self-contained editorial project. The stable working copy belongs at:

`C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)`

## Editorial files

| File | Purpose |
|---|---|
| [glossary.json](glossary.json) | Hand-maintained names, gender, roles, register, aliases, 293 terms and technical exclusions. Covers all 245 classified name sites. |
| [translation_frame.json](translation_frame.json) | Source-derived theme, era, register and naming policy. |
| [game_prompt.md](game_prompt.md) | Game bible: premise, progression, narrator/cast context and terminology rules. |
| [quirks.md](quirks.md) | Verified recurring language traps and formatting policy. |
| [system_prompt.md](system_prompt.md) | Fidelity, protected-token and JSON output contract. |
| [field_instructions.json](field_instructions.json) | Separate instructions for names, descriptions, narration, dialogue, UI and inserted target phrases. |
| [prompt_assembly.md](prompt_assembly.md) | How to combine relevant guidance and context for a later translation batch. |
| [assembly_notes.md](assembly_notes.md) | Complete fragment/substitution contracts, including signed HP modifiers. |
| [review/quirk-review.md](review/quirk-review.md) | Three-review convergence, independent coordinator verification, evidence and exceptions. |
| [review/OPEN_ITEMS.md](review/OPEN_ITEMS.md) | Three held records and concrete later integration/layout checks. |

The character spellings are editorial choices: **Flavia**, **Irara**, **Luminia**.
The merchant has a role/register record without an invented personal name or
gender. Most scene text is third-person narration; it does not establish heroine
dialogue voices. Proper names and titles remain distinct.

## Prepared inventory

All 630 raw CJK instruction-site candidates are retained with original source
and null translations:

- 245 name sites have deterministic glossary locks, prepared but not applied.
- 365 units are queued for translation with fields, GML references and context.
- 17 help lookup literals have synchronized technical override plans.
- Three records are held: a dormant helper, an undisplayed merchant line and an
  isolated help-formula discrepancy. Their reasons and source context are retained.

The 110 narration units retain separate scene IDs, phases and alias information.
Skill, equipment, quest and stat descriptions have paired name context. The two
role-specific Range descriptions are correctly attached to Range, not Move Speed.
157 templates contain 158 protected `#` occurrences, including an equipment
template that substitutes three different target phrases. A separate punctuation
plan covers one enemy-list delimiter omitted by the CJK-letter export.

`catalog.prepared.json`, `glossary_locks.json`, `technical_overrides.json`,
`translation_plan.json`, `preparation-report.json` and `review/anchor-counts.json`
are deterministic derivatives. `translation_plan.json` contains planning groups,
not network requests. Do not hand-edit generated files or regenerate the glossary.
Prepared catalogs are **not** translation outputs; keep future translated work
in separately named files so it cannot be overwritten by a preparation rebuild.

## Offline validation

The existing engine toolkit lives at
`C:/Users/sw/Desktop/Tools/Game Translation/GameMaker`.
No API client, credentials, model choice, translation requests or game patch
are included in this preparation work.

From this folder, run:

```powershell
python prepare.py --check
```

After an editorial change, `python prepare.py` rebuilds only the derived files.
Optionally append `--archive "path/to/original/data.win"` to verify the source
archive hash read-only. Python's standard library and the installed `gmtt.py`
are sufficient; no network is needed. A derived-file mismatch fails the check.

Validation covers source identity, all candidate IDs, GML literal locations,
name coverage, paired Range overrides, exact token round trips, unset translation
flags, font ASCII coverage and duplicate JSON keys. It does not certify future
translations, word wrapping or runtime reachability for every record.

## Source and later handoff

`source/` preserves the raw catalog, complete source snapshot, census, original
token-count report, original readme/credits and 227 recovered GML files. Their
hashes are recorded in `source/manifest.json`. The frozen reviewer packet retains
the original workspace paths as historical provenance; active preparation reads
only this folder and the stable engine toolkit.

Original `data.win`: 153,903,396 bytes; SHA-256
`2c22ad3c7dd540f4e870c195935a206eeafc58665c458673c88c3acb9a5ab611`.
The original game archive and executable are not copied here or modified.
The source snapshot records bytecode 17 and an inferred 2023.8 feature level,
which is not proof of an exact original GameMaker compiler version.

Next translation work can use the prepared 365-unit queue and locked names,
resolving only the affected held items before their inclusion. A later patch
must coordinate help needles, verify all substituted forms, check English word
wrapping/glyphs, re-extract the output and prove only intended sites changed.
Texture lettering has not been inventoried or edited in this text-only preparation.

