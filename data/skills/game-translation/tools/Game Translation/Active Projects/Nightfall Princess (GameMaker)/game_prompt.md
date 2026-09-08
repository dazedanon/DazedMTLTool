# Nightfall Princess - game bible

## Premise

**魔降る夜の姫 / Nightfall Princess** is an adult fantasy combat game with three
playable heroines, a temple hub, staged battles, equipment and skill builds,
and paid quests. A princess fights demons; a travelling merchant comes to the
temple to offer weapons and missions. The other heroines are a fairy saint and
a goddess. Source evidence does not establish a named kingdom, a historical
period, a developed pantheon or a hidden identity reveal. Do not add them.

## Progression and systems

The heroines have separate stage progress. The hub gives access to equipment,
quests and a replay gallery. The numbers in `Stage`, `Difficulty`, quest labels
and result counters refer to different displayed concepts; do not collapse them
to one word. Equipment and skills have paired name and description records.
The glossary names those records; a repeated display name does not merge their
game IDs or their effects.

Descriptions use three distinct trigger families: limited activations per
battle, timed activations and triggers after a number of kills. Read their
glossary terms and the complete description rather than assuming that every
number measures seconds. HP and the pleasure gauge are also distinct. A higher
pleasure limit increases the amount tolerated, and pleasure recovery reduces
the current gauge. Reaching the limit costs HP. Never present a decrease in
the undesirable gauge as a penalty merely because the Japanese uses 回復.

## Tone and source handling

Use fluent English with the same point of view and degree of specificity as
the supplied source. The scene-caption track is predominantly third-person
narration, not dialogue spoken by the person named in it. Keep source agency,
coercion, refusal and uncertainty accurate; do not turn an involuntary event
into consent, add reactions or embellish descriptions. Keep ordinary quest
objectives and combat help clear and functional.

The merchant's introduction is direct speech addressed to the princess.
Its courteous delivery should remain recognizably different from descriptions
and system notices. Cast-specific register is owned by the name entries in
`glossary.json`; do not fabricate heroine dialects from their titles or appearance.

## Cast and reference rules

There are three distinct named heroines. Their canonical English spellings,
gender, roles and register evidence are in the glossary supplied with the batch.
The credited names recur in gallery labels and prose. The travelling merchant
is a generic role label, not a newly invented personal name.

Titles remain titles: 王女 is the princess, 聖女 is the saint and 女神 is the
goddess. Do not replace every title by the person's proper name. When 王女様 is
direct address, use `Your Highness`; in third-person reporting, use an appropriate
reference to the princess. No text evidence makes the merchant's grammatical
gender mandatory. Prefer the role or a neutral construction where needed.

Do not assign pronouns from name spelling or speech style. Do not infer age
from small stature, a fairy species label, or mother-roleplay terminology.
Avoid invented character biographies and new kinship relationships.

## Terminology

Use the matched slice of `glossary.json`. Names, enemy labels, equipment names,
skill names, quest labels, combat effects and stats have been curated before
translation. Use label capitalization in name fields and normal English grammar
in prose, except that technical helper keywords must retain their exact canonical
capitalization wherever the unit requires them. Terms are meaning contracts,
not an instruction to perform indiscriminate substring replacement.

## Mechanical translation rules

Protected `⟦GM:0000⟧` tokens represent original runtime substitutions or line
breaks. Their per-unit map is authoritative. Preserve every token exactly once
per original occurrence and in the same order. Formula coefficients, signs,
percentages, repetition counts and time units must keep their meaning.

Some UI strings are concatenated around runtime numbers. Translate the marked
fragment as part of its supplied full expression; retain needed boundary spaces.
Do not write a complete sentence for each fragment independently. Known cases
can use natural prefix/value/suffix phrasing without dropping a fragment.

Use ordinary English punctuation compatible with the declared style. Do not
leave kana or kanji in the output, add decorative symbols, or change censored
versus uncensored source wording. Never translate technical identifiers. Only
the current input IDs are requested. Font dimensions, clipping budgets, source
reachability and patch operations are handled by project configuration and QA,
not by guessing a maximum text length.
