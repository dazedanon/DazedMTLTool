# Blind character-name evidence

This fixture contains Japanese source strings only. There is no English glossary, proposed answer,
or creator-supplied Latin spelling.

## Subject D

- Nameplate and database name: `ベル`
- Self-identification: `ベルだよ。鐘が鳴ったから来たの？`
- Sibling names in the same household record: `チャイム`, `ゴング`
- Parent's explanation: `三人とも、違う鐘の音から名前をもらったの。`
- Recurring callback: `ベルを鳴らしたら、ベルが来た！`
- Subject D's reply: `その冗談、名前をつけられてから何度目だと思う？`
- Personal emblem described in the source: `ベルの紋章は小さな鐘。`

## Task

Use the character-name evidence method in the supplied localization-investigation skill. Research
credible dictionaries and naming references in plausible source languages. Recommend one
player-facing Latin-alphabet name. Do not invent an official spelling.

Return one JSON object only, with these string fields:

- `subject_id`
- `recommendation`
- `confidence`
- `lexical_language`
- `lexical_source_word`
- `lexical_meaning`
- `lexical_source_url`
- `kana_discrepancy`
- `rationale`
