# UI/system glossary - decisions and open questions

Produced by the UI-terms recovery workflow (two independent readers over the
811 distinct UI/choice/database strings, then a completeness critic).
Kept verbatim: these are the rulings behind tl/_sources/ui_terms.json, and the
overflow and open-question items are work for the in-game pass.

## 1

COMPLETENESS METHOD AND RESULT. The digest declares 811 distinct strings in its header and contains exactly 811 tag-prefixed records, so one tag line = one string and every untagged line is a continuation. I verified this at byte level: the file uses CRLF as record separator and 98 lone CR bytes as in-string newlines; joining continuation records with a newline reconstructs each source string exactly. Of the 811, four are exact repeats (歩くポルノ{W2} / このデカパイに税をかけろ / 許されざるデカパイ{W2} / デカパイ感謝{W2} each appear once under DataBase.json and again under CDataBase.json), so 807 distinct strings. The merged glossary returns all 807, one row each. missing_count = 0: the two readers between them covered every translatable line. The arithmetic closes exactly - 817 draft rows = 806 rows for distinct strings + 3 extra rows created by mis-splitting + 8 duplicate rows from the reader overlap, minus Data\ which the drafts put only in do_not_translate.

## 2

MIS-SPLIT ROWS MERGED (structural fix). Three source strings are multi-line and the drafts filed each half as its own row: 「{W34}所持金{W35}」+「<R>{W33}{W36}{W34} {W13}」, 「{W33}所持数{W35}」+「{W37}<R>{W33}{W38}」, and 「{W46}<C>{W34}【入手アイテム】」+「{W33}」. Byte inspection proves these are single strings (the shop rows carry an in-string newline; the loot header carries an in-string BLANK LINE, so its jp is 【入手アイテム】 + two newlines + {W33}). They are returned merged, with the layout halves copied byte-identical. If your patcher keys on the whole string, the split rows would never have matched anything.

## 3

DUPLICATE ROWS DEDUPLICATED. Reader A stopped at file line 500 and reader B started at line 489, so eight database descriptions were translated twice with diverging English. One reading has been chosen for each: 牛神から搾ったミルク -> 'Greatly raises Lewdness.'; チンコの傷 -> 'Medicine that instantly heals cock wounds.'; まかない -> 'Don't sneer at staff meals.'; 使用済みゴム。ばっちぃ。 -> 'A used rubber. Icky.' (ばっちぃ is baby-talk, and 'Filthy' is reserved for ドスケベ); よくわからない古い物 -> 'Some old thing you can't identify.'; 釣りキチ愛用の竿 -> 'The rod favored by the fishing nut.'; 深いところに住むキス -> 'A sillago that lives in deep water.'; ミルクと使用済みゴム was identical in both.

## 4

SOURCE-TEXT ERROR IN A DRAFT KEY. One draft row had jp 「は舌でレロニレロした！」 with a stray ニ; the file reads 「は舌でレロレロした！」. Corrected. That row would never have matched the game string.

## 5

CROSS-HALF TERMINOLOGY CONFLICTS RESOLVED. (1) 媚毒: reader A used 'aphrodisiac poison' (five places), reader B 'love poison' (one). Unified to 'aphrodisiac poison', keeping 媚薬 = plain 'aphrodisiac' so the two source words stay distinguishable. (2) 精液 vs ザーメン: reader A locked 精液 = semen / ザーメン = cum (the clinical/crude split the author actually uses); reader B rendered 精液 as 'cum' in the 付着した popups. Unified to semen, so 精液が付着した！ / {W0}精液{W1}が付着した！ / {W0}精液が付着した！{W1} now all read 'semen'. (3) マネーノドラゴン: 'Money Dragon' in the class-change choice vs 'Moneyno Dragon' in the 極意 item. Unified to 'Money Dragon' - the same job must not have two English names.

## 6

COLLISIONS FIXED (two different Japanese strings mapping to one English string). 個/本 both 'pcs' -> 本 is now ' units'. いいえ/ダメ both 'No' -> ダメ is now 'No, don't' (still a refusal, still distinct from 無理！'No way!', イヤだ 'I refuse', 断る 'Decline'). リセット/リセットする both 'Reset' -> the する form is now 'Reset it', matching 使用する 'Use it' and 鑑定する 'Appraise it'. 何もしない (battle command) / なにもしない (event choice) both 'Do nothing' -> the event choice is now 'Stay still', which is also the exact opposite of its partner option 腰を振る 'Move your hips'. そうだ/その通り{W2} both 'That's right' -> その通り{W2} is now 'Exactly{W2}'. つづきから/コンティニュー both 'Continue' -> コンティニュー is now 'Continue Game'; these sit in two different title menus, so if you would rather keep the loanword plain, flip the pair rather than reintroducing the collision.

## 7

PADDING ERROR FIXED. The job-screen hint bar 「決定キー：転職 ←・→・サブキー：画面切り替え キャンセルキー：戻る」 separates its three groups with HALFWIDTH spaces (U+0020), not fullwidth ones; the draft substituted U+3000, which widens the strip by two cells. The English now uses the source's halfwidth spaces. The field hotkey bar 「T：乳首チラ見せ　O：オナニー　A：ジョブアクション」 genuinely does use U+3000 and keeps it.

## 8

ARROWS RESTORED IN THE TWO EQUIP-ORDER HINTS. 鎧→服→クマ→樽 and 樽→鎧→植木 had their → converted to ASCII '->', while → was kept verbatim in the arrowed choices (→つきあう, →さようなら, →アフターへ). The full-width arrow is content in both places, so both now keep →.

## 9

CONCATENATION RULES CARRIED THROUGH AND RE-CHECKED PER FRAGMENT. Fragments that a runtime name is prepended to keep a LEADING SPACE: の攻撃！/の全体攻撃！/の強斬り！/の烈・強斬り！/のハラパンツァー！/のドグマロード！/のチェスト！, every は…した／を唱えた battle-log line, には効果がなかった！, には当たらなかった！, に失敗した！, がなかった！, が足りない！, 入手！, the {W10}/{W12}/{W47}上がった・下がった tails, and the counters 個・枚・本・人. Fragments that read as an English possessive take NO leading space, because the apostrophe must butt against the inserted name: の{W4}が…回復した／減少した, のステータスが上昇した！, の特性ボーナスアップ！, every の-type status line, and the three は-lines that are naturally possessive in English (は魔法を封印された／は魔法が封印されている／は攻撃力が減少した). Head halves {W4}の / {W13}の / {W4}が / {W13}が keep their trailing space; the {W13}の最大{W4}が heads do not, because their tails already begin with one.

## 10

PLACEHOLDER SPACING. Where a {Wn} value sits against English words a space was added on the value side ('Lewdness {W39}', 'Max {W39}{W13}{W10}', 'Who will use {W6}', '{W4} obtained {W12} {W13}!'), but never inside a level or unit reading ('Mouth Dev Lv{W52}', '{W51}ml', '{W0}Horny Gauge +{W1}'). Three messages differ only in what the {W0}/{W1} highlight pair encloses and the English follows the enclosure, not the word order: 「{W0}精液{W1}が付着した！」 -> 'Splattered with {W0}semen{W1}!' (noun only), 「{W0}精液が付着した！{W1}」 -> '{W0}Splattered with semen!{W1}' (whole sentence), 「{W0}ムラムラゲージ{W1}が上昇した」 -> 'The {W0}Horny Gauge{W1} rose' (article outside the highlight). A mechanical placeholder-position check passes a wrong rendering here.

## 11

PADDING PRESERVED VERBATIM. Trailing U+3000 on 最大{W4} {W13}{W14}　 and 最大{W39} {W13}{W14}　; leading and inner U+3000 on 　{W14}　入手！; trailing halfwidth space on 最大{W39}{W13}{W10} ; the leading halfwidth indents on the eight config rows and on the two status blocks; the LEADING NEWLINE on 「\n 残り x {W10}」 (the source string really does start with a line break - the draft dropped it); 「 お茶する」 which is distinguished from 「お茶する」 by one leading space alone; 「　スタート」 with one U+3000; and 「  ゲーム終了」 with two halfwidth spaces in the same menu. Because the English is shorter than the Japanese in the centred cases, these will drift left and the padding may need retuning once the font is known.

## 12

do_not_translate PRUNED AND COMPLETED. Removed 'i[126]': it is a RAW, unmasked Wolf inline-icon reference that leaked into 「いつもムラムラしてるi[126]」, and I cannot prove the player never sees it - if the backslash was missing in the source the player sees the literal text. It survives byte for byte inside that row instead, spaced off the preceding word, and its untagged twin 「いつもムラムラしてる{W2}」 is kept worded identically. Worth reporting upstream so the masker catches i[NNN] next run. Kept and completed: all 49 {Wn} sentinels actually present in this file (the draft listed an arbitrary 8), the Wolf alignment tags <R> and <C>, which the renderer consumes, and 'Data\', a filesystem path prefix. Note that 'Data\' is also returned as a term with an identical English value so that every line in the file has a row.

## 13

PART-OF-SPEECH DECISIONS RETAINED FROM THE DRAFTS AND RE-VERIFIED: 設定完了 = 'Done' (apply-and-exit button, not a status report); やめておく = 'Better not' (a decline, never 'Stop'/'Quit'); 乗る/乗らない = 'Go along with it'/'Turn it down'; 我慢する = the verb 'Hold back'; ある/ない = 'Yes, I have'/'No, I haven't'; 無理！ = 'No way!'; 連打 続行/停止 = toggle VALUES 'Keep repeating'/'Stop repeating'; 貸す = 'Lend it' not 'Borrow'; 受ける = 'Accept' not 'Receive'; 違う = 'That's wrong' not 'Different'; 綺麗 = 'Clean' (paired with 汚い) not 'Beautiful'; 通る = 'Pass through'; 済ます = 'Get it over with'; 力になる = 'Lend a hand'; 力が入らない = 'No strength left'; 普通に攻撃 = 'Attack normally' (a command description, not the noun); はじめから/つづきから = 'New Game'/'Continue'. Causatives kept distinct from their plain verbs: 使わせる = 'Let him use it', カリカリさせる/させない = 'Let him rub it'/'Don't let him rub it', 働いてもらう = 'Put them to work' vs 働く = 'Work', 昏睡させる = 'knock an NPC out cold'. One further POS fix of my own: 犯さない was a bare 'Don't', which does not read as an option; it is now 'Don't fuck him', the true mirror of 犯す = 'Fuck him', and the brief forbids euphemising anyway.

## 14

UNRESOLVED TERM, NEEDS IN-GAME VERIFICATION: 「発生済み環境ウィル」. ウィル occurs exactly once in the whole digest set and no database category matches, so there is no context to disambiguate it - it could be a truncated ウィルス ('environmental virus', which would fit the 媚毒 contamination premise) or a coined noun for the random field events the list collects (お尻を叩かれた！ and friends). I left the draft's literal 'Env. Wills Triggered' rather than invent, but this is the one label in the file I would not ship without seeing the screen.

## 15

PROPER NOUNS THAT MUST BE AGREED PROJECT-WIDE, not settled here: クローサリア = 'Clossaria' (two map blurbs); 騎紅士 = 'Crimson Knight', which has to match the game title 騎紅士スカーレット, the CDataBase job entry and the 騎紅士の極意 item; the jobs シーセーバー / カオスハンター / マネーノドラゴン = Sea Saver / Chaos Hunter / Money Dragon, which must match db_names.txt where they also appear as [safe] entries; 縦割り洞窟 = 'Vertical Cave' and アナル・リザード = 'Anal Lizard', both of which also live in db_names.txt; エロナオシ山 = 'Mt. Eronaoshi' (a transliteration - the name reads as 'ero-fixing mountain' and a translated name may serve the joke better).

## 16

STAT-NAME OVERLAP LEFT DELIBERATELY: 魔防御, 魔防力 and 精神防御 all render as 'magic defense', and 魔力 and 精神攻撃力 both live in the 'magic'/'magic attack' space. The author uses these as synonyms for the same two stats, so collapsing them is correct inside descriptions - but the canonical stat NAMES are in db_names.txt (主人公ステータス), and whichever wording you fix there should be echoed back into these description rows.

## 17

OVERFLOW RISKS, unchanged from the drafts and worth measuring in-engine before release. Reputation quips (budget looks like roughly 24-28 halfwidth cells): 'Looks like she'd swing at you out of nowhere' (43), 'Don't talk to my dick! Look me in the eye!' (41), 'She wears the lewd swimsuit, so it's fine' (40), 'Calls it treatment, then knocks you out' (38), 'Isn't she stealing people's stuff...' (35), 'Ten homers a season is her ceiling' (33), 'High satisfaction from those tits' (33), 'Worsens my aphrodisiac poison' (29, and longer than the draft's 'love poison' - shorten this one first if the column clips). Battle log: "'s magic attack and magic defense returned to normal!" (52) is the longest runtime line and grows again once a 7-8 character name is prepended; if it wraps badly, shorten 'returned to normal' to 'back to normal' across all eight expiry messages at once. Menu columns near or over 20 cells: 'Don't give up, keep plugging away' (32), 'Full-frontal ding-a-ling' (24), 'Enter the hot spring', 'Rest your tits on it', 'Squeeze out the milk' (20 each). Status/job screens: 'Total Semen Drained' (19), 'Env. Wills Triggered' (20), 'Not the begging type' / 'Not the whoring type' (20).

## 18

COSMETIC INCONSISTENCY LEFT ALONE, flagged rather than churned: ellipsis style. Reader A converted 「……」 to ASCII '...' inside the long lewdness-tier monologues but kept 「……」 in short UI strings (援助失敗……); reader B did the same split unevenly (hint notes use '...', 最近街民の持ち物が… keeps '……'). Nothing is wrong per string, but the glossary is not internally uniform. Pick one house style and sweep it in one pass rather than per row. The same applies to the drawn-out kana: ～～～～ became repeated letters ('revoooolt'), たぁ～くさん became 'looooads'.

