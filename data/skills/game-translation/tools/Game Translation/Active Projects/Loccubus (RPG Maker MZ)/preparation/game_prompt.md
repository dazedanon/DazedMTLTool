# Loccubus translation preparation

## Premise and permitted scope

Loccubus v1.0 is a fantasy game built around custom MUUI screens in RPG Maker MZ 1.9.0.
Its primary source is Simplified Chinese, with a Japanese localization and unfinished English infrastructure.
This project prepares reviewed nonsexual interface text for English localization.
The story includes sexual content involving minors, which is excluded from translation and from the authoring queue.
Do not expand the queue into those scenes or infer adult status from a content rating.
Source locations, without reproduced scene text, are recorded in `reports/content_exclusions.json`.

## Systems and localization

MUUI draws much of the interface from nested JSON files, independently of the standard RPG Maker menus.
The game already supports tagged dictionary lookups and separate common-event routes for each locale.
Chinese is the authoritative source for this project.
Japanese may help identify names in permitted material, but is advisory and must not silently replace Chinese wording.
The existing English dictionary is a small stock template, not evidence that this game has been translated.
English event-route slots still contain source-language text.

## Tone

Write clear, natural English interface labels and direct confirmation questions.
Use familiar RPG menu terminology and preserve the action the player is taking.
Keep Save, Load, Options, Cancel, and Confirm distinct.
Do not invent lore, routes, character relationships, or gameplay consequences.
Do not introduce Japanese honorifics into Chinese source text.
Render Chinese forms of address by their meaning and relationship when encountered in permitted material.

## Names and identity

Consult `glossary.json` for name spellings, gender evidence, role, register, aliases, and provisional decisions.
The default database actors are not evidence of the narrative cast.
Do not merge unidentified speakers, generic customers, or lettered instances into named characters.
Retain an undisclosed identity until the source reveals it.
The glossary does not authorize any excluded scene.

## Output contract

Author translations locally using the masked `text` and exact `id` and `source_hash` in the exported batch.
Return one JSONL record per edited unit with `id`, `source_hash`, and `target`.
Preserve every `⟦n⟧` token exactly once in its supplied order.
Add appropriate English spacing around tokens that insert words or numbers.
Do not insert raw escape codes or copy Chinese/Japanese characters into the target.
The name box is separate from the message body.
Do not add a speaker prefix, explanations, markdown fences, or quotation marks that the field does not request.
Use actual JSON-escaped newlines only where the field instruction permits them.
Leave unedited targets empty.

## Technical ownership

The adapter owns dictionary keys, JSON paths, JavaScript delimiters, placeholders, control flow, asset names, and geometry.
Translate only the supplied display text.
For `locale_ui`, surrounding hash delimiters belong to the lookup key and are deliberately absent from the translation input.
Do not restore those delimiters into the English dictionary value.
For `save_ui` fragments, preserve meaningful trailing spaces before the dynamic slot number.
Never translate commands, component IDs, font family names, variable/switch names, or resource paths.

## Source context

Any supplied preceding source context is reference material only.
Do not treat it as approved English terminology or copy its source-language spellings into output.
The glossary controls approved terms; unresolved evidence stays unresolved.
