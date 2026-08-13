# Blind character-name evidence

This fixture contains Japanese source strings only. There is no English glossary, proposed answer,
or creator-supplied Latin spelling.

## Subject C

- Namecut card: `空を想う異端 / ユステーザ・ロア`
- Self-identification: `私はユステーザ・ロア、旅人だ。`
- Alternate self-identification: `ユステーザ・ロアだ。どうやら知っているようだが。`
- Database full-name field: `ユステーザ・ロア`.
- Character context: `学問──ことに歴史に対する興味関心は普通の旅人とは異なるかもしれない。`
- Church-related dialogue: `シスターになれという意味か？ 私には向いていないと思うが……`
- Epistemic dialogue: `あなたの説が誤っているとは言わないし、むしろ正しいと思っているが、絶対にそうだとは限らないな？`
- Epistemic dialogue: `確証を得たいな……今の話だけでは、謎が解明したとは言えない。`
- Moral dialogue: `ただ、悪を許せなかっただけだ。`
- Moral judgment: `そして、君は善だ。`
- Qualification: `その通りだ。私は、私の基準で述べているだけ。`

## Task

Use the character-name evidence method in the supplied localization-investigation skill. Research
credible dictionaries and naming references in plausible source languages. Recommend one
player-facing Latin-alphabet full name. Do not invent an official spelling.

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
