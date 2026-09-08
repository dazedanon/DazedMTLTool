# Prompt handoff contract

This describes future prompt composition. It contains no API client, model
selection, credentials, requests, retries or translation execution.

For each requested field, compose the stable guidance in this order:

1. `system_prompt.md`: output contract, source fidelity and protected tokens.
2. `translation_frame.json`: genre/era/register/naming orientation.
3. `game_prompt.md`: premise, cast context, progression and narrative rules.
4. `quirks.md`: verified cross-cutting language and assembly requirements.
5. The relevant `field_instructions.json` value and applicable assembly note.
6. The matched glossary slice and required helper terms for the selected units.
7. Requested IDs, masked sources and their readable translation context.

Guidance ownership prevents divergent duplicate rules. The glossary owns names
and terms; character entries own gender, role, register and aliases. The bible
owns world context. Quirks own cross-cutting source traps. Field instructions
own output shape by use. A unit's explicit verified correction has narrow
authority over its specified source error. Do not generate new “corrections.”

Resolve paired name/scene IDs to source context when composing a later batch.
Include full participating expressions and all equipment-target ranks; include
the merchant's held fourth source record as context only. Carry along applicable
name records with all five identity/register fields, not just JP-to-EN pairs.
`matched_glossary` is a convenience substring candidate list: review overlaps
by longest phrase and context, not indiscriminate text replacement. A title is
not a character alias. Supply formula stat terminology such as Attack where
the Japanese shorthand 攻撃 occurs.

Each requested ID receives exactly one decoded string in `{"t":{...}}`.
Technical lookup sites, held units and glossary-locked names are excluded from
free translation. Planning groups are not ready-made service payloads; later
batch sizing must include guidance, glossary, context and output headroom.
No narration/dialogue deduplication is prepared.

After translation, validate exact IDs, sentinel order/multiplicity, restored
source controls, quantities and negation, term consistency, helper match sets,
all assembly variants, font glyph coverage and runtime layout. Keep model-blind
review exports with the actual authoritative prompt and matched glossary slices.
Do not mark a catalog site reviewed before that site's meaning and use have been
checked. A preparation validation pass does not certify translated text.

