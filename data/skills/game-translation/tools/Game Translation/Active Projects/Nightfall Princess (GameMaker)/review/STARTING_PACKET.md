# Frozen starting packet: Nightfall Princess translation preparation

Task: independently discover recurring linguistic/mechanical translation quirks
from the unchanged Japanese source. This is preparation, not translation.
No API code or API calls are requested. Do not edit files or delegate.
Do not read another reviewer's report, and do not read subsequently created
glossary/prompt files. Starting guidance is orientation, not evidence.

## Raw artifacts

Workspace: `C:/Users/sw/Desktop/Games/Nightfall Princess`.
Source archive: `data.win`, SHA256
`2c22ad3c7dd540f4e870c195935a206eeafc58665c458673c88c3acb9a5ab611`.
Engine: GameMaker VM bytecode 17; UTMT infers feature version 2023.8.0.0,
not a verified exact compiler patch release.

- `RE/NightfallPrincess/catalog.json`: 630 CJK literal-site candidates with
  original source, code IDs and neighboring disassembly; no translations.
- `RE/NightfallPrincess/source.snapshot.json`: all 2,730 pooled strings,
  instruction references and font metrics.
- `RE/NightfallPrincess/verified-decompile/CodeEntries/*.gml`: 227 parent GML
  files, including nested functions.
- `Readme.txt`: original title, controls and voiced-character credits.
- Skill guidance: `C:/Users/sw/.claude/skills/game-translation/references/glossary-and-prompts.md`.
  The relevant section is "Systemic-quirk discovery"; broader guidance is orientation.

## Source-derived synopsis (orientation)

The game uses a fantasy war setting in which a princess fights demons and
a travelling merchant offers weapons and missions. Quest text separately
addresses a fairy saint and a goddess. The inventory includes combat skills,
equipment, talents, quest descriptions and adult scene dialogue.

Provenance: `gml_Object_obj_dialog_Create_0.gml`,
`gml_GlobalScript_scr_text_quest.gml`, and the named `scr_name_*`/`scr_text_*`
files. Do not infer a mythology, historical era, official Latin names or
unwritten backstory from this synopsis.

## Corpus map

Most source text is in `gml_GlobalScript_scr_text_h`, `scr_text_skill`,
`scr_text_equip`, `scr_text_quest`, `scr_name_equip`, `scr_name_skill`,
`scr_enemy_name`, `scr_text_talent`, `scr_text_talent_down`, `scr_name_talent`,
`scr_name_quest`. Remaining candidates are in `obj_gallery`, `obj_quest`,
`obj_shop`, `obj_hall`, `obj_dialog`, `obj_end`, `obj_equip`, `obj_ui`,
and `obj_state` event files. Read consumers/callers to resolve semantics.

## Unchanged starting guidance and hypotheses

No game-specific glossary, bible or quirks file existed before this task.
No proposed quirk family or correction is supplied; derive candidates yourself.

## Return contract

Return a concise independent report. For each proposed recurring quirk, give
the literal Japanese anchor, two independent examples or explicit callback,
file/line provenance, a source-verified translation implication, reachability
evidence or uncertainty, and exceptions. Report verified-clean families
separately. Unreachable/test strings and uncertain observations belong in a
backlog, not in mandatory translation policy. Do not claim full game review.
Keep any adult-content examples to the minimum necessary for linguistic analysis.
