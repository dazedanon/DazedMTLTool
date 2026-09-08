# Do-not-translate research (HUMAN-FACING - never sent to the model)

These notes were written into `glossary.json`'s `do_not_translate`
list, which is rendered verbatim into the CACHED system prefix. Most
of them are explanations rather than literal strings, and the ones
about backslash control codes are worse than useless there: the
masker replaces every code with a sentinel before the model sees
anything, so the model never encounters a backslash - and naming
raw codes in the prompt invites it to write one, which `validate.py`
hard-fails as `invented-backslash`.

They are kept here because the RESEARCH is correct and useful to a
human reading the corpus. What the model is actually told about
codes lives in `artl/prompts.py:BASE_RULES` and is stated once.

The engine-side truth for all of this is `ENGINE-CODES.md`.

- \NPL[...] - the Bakin nameplate code. It is ALWAYS the first token of a dialogue unit and the bracket content is the speaker key. Never translate, move or drop it; the name inside is translated by the separate names pass.
- \$[...] - runtime variable injection (\$[淫乱度], \$[名声度], \$[ファストトラベル先][1], \$[おっぱい回数]). Keep the token byte-for-byte, including the index brackets; only its position in the English sentence may change.
- \#[...] - runtime coordinate/expression injection (\#[プレイヤーの位置座標X]).
- \z[...] - text-size code (\z[150]). Formatting only, stays put.
- \r[...] - ruby/reading code. Keep the token.
- \n - hard line break inside a message box. Preserve the count and position.
- \innpriceG, \currentitemname, \currentitemnum, \currentskillconsumptionhp, \currentskillconsumptionmp, \currentskillconsumptionitem, \currentlearnskillconsumptionhp, \currentlearnskillconsumptionmp, \selectskillconsumptionhp, \selectskillconsumptionmp, \selectshopitemnum, \selecshoptitemcategory - Bakin layout substitutions. Verbatim, including the misspelt \selecshoptitemcategory.
- {0}, {1}, {2} - Bakin glossary format placeholders in the battle and shop strings. Keep every placeholder, and reorder them only to fit English grammar.
- RPG Developer Bakin, SmileBoom Co.Ltd., Effekseer, MonoGame, SharpDX, YamlDotNet, FreeType, libvorbis, libogg, libsimplewebm - engine and licence strings in the readme. Do not translate.
- てすと2 / てすと3 / てすと４ / テスト / テスト街 / テストニンジャ / testo5 / スクショ用 / バトルマップ_1 - developer test maps. Their contents are duplicates of live content; do not treat them as new scenes.
- イベントシート#N.N, common:イベント_N, map:<name> / <event name> - extraction context strings, not game text.
- The layout help text beginning 「強化するアイテム選択画面のレイアウトは」 and 「イベント用フリーレイアウトに配置したメニューは」 and 「詳細はマニュアル RPG Developer Bakin Wiki をご覧ください。」 - stock Bakin editor documentation left in the project. Never player-visible.
- 属性7, 属性8, 状態7, 状態8 - unused engine attribute/condition slots left at their default names.
- a / a / a / a (the filler text in the スライムラヴァ Cast description) - dev placeholder.
- 〇 and ● - censor glyphs, not Japanese text. They must survive in the same position and must NOT be added where the source has none.
- ♡ ♥ ♪ ～ … ※ 『』 （） - punctuation and markup that carry meaning. Keep them where the source puts them.
