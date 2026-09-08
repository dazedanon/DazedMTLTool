# 執聖官アルテシア ─黄金のシャフリーヴァル─ (Holy Executor Artesia: The Golden Shahrivar)

An adult (R18) RPG built in **RPG Developer Bakin** by **シコリーター三世 (Shikoritor III)**, Ver 1.06, roughly
ten hours long. It is a **six-chapter murder mystery** with an Ace Attorney style evidence-and-accusation
system bolted onto a light JRPG, and a very large volume of explicit, mostly coercive erotic content running
in parallel with the plot. About 90,000 extracted strings, 3.4M characters of Japanese, 465 nameplate
speakers. Artesia alone speaks 42,695 of the 71,518 dialogue lines.

## Premise

**Artesia** (アルテシア) is a **Holy Executor** (執聖官) - a warrant-carrying investigator-enforcer of the
**Imperial Orthodoxy** (帝国正教) who is sworn to swing the Holy Executor's Battle Axe "in a good heart, under
prayer, to punish sin." She is broke, blunt, and has been summoned to the **Sofreiman Domain** (ソフレイマン領)
by a letter signed by her father: *"My beloved daughter, Artesia. I want to see you. I want to leave you
everything I have. I will wait for you in the Lord's Town."* Her father, **Wolf** (ウォフ), is already dead
when she arrives, stabbed in a back alley, and a blind girl has been framed for it. Chapter by chapter
Artesia works outward from that alley: the drunk officer who buried the investigation, a dragon in the
mountains, a run of unexplained corpses in the frontier town of **Heechka**, a mana drought around
**Anahita**, a research institute in the snows of **Taromatee** where Wolf was held prisoner for over a
decade, and finally the poisoning of the Lord himself.

What everyone is really chasing is **『究極煉禁』, the Ultimate Forbidden Alchemy** - the masterwork Wolf
completed in captivity, redeveloped from the legacy of **『星を喰らう者』 the Star Eater**, a causality-devouring
tiger that came from the sea of stars and had its throat torn out by **the Dragon**. It bends causality so
events fall out however the caster prefers. Lord **Sofreiman** poured the domain's taxes into it and wants to
become a god with it. The **demons** (魔族) were promised it for freeing Wolf. Wolf, who had been quietly
robbed for years and knew he was dying, staged his own murder as revenge on all of them and hid the one thing
that makes the spell usable - **its formula name (術式名)** - where only his family would ever look.

The culprit is **the Priest** (神父) of the Lord's Town church: an untalented classmate of Wolf's who spent
twenty years eaten by envy, took over Wolf's prison counselling, pocketed the cheques meant for Wolf's family,
stabbed him in the alley to harvest a Magic Stone from his corpse, forged the letter that brought Artesia to
the domain so she would find the formula name for him, and then began murdering everyone who knew the spell
existed. His seven diary entries, played as full-screen telops in the church basement, are the spine of the
story and the only place the whole scheme is stated plainly. Artesia's own stated motive is smaller and
sadder than everyone else's: **「私はただ『納得』したかったの」** - she just wanted **closure**, so she could
stop looking backwards. The opening and closing telops frame the entire game the same way: **これは『祈り』の
物語 - "this is a story of prayer."**

## Routes & systems

There is **one linear story route**, six chapters, each ending on a full-screen chapter card. Translate the
cards to a single fixed pattern:

| | | |
|---|---|---|
| 第一章 | 『執聖官アルテシア』 | Chapter 1: "Holy Executor Artesia" |
| 第二章 | 『灯り』 | Chapter 2: "The Light" |
| 第三章 | 『瞳』 | Chapter 3: "The Eyes" |
| 第四章 | 『為すべきを』 | Chapter 4: "What Must Be Done" |
| 第五章 | 『聖域』 / 『感傷』 | Chapter 5: "Sanctuary" / "Sentiment" |
| 第六章 | 『黄金のシャフリーヴァル』 | Chapter 6: "The Golden Shahrivar" |

Chapter 5 genuinely has **two** end cards in the data (『聖域』 in the map version, 『感傷』 in the common-event
version). Both are real. Translate each where it stands and do not unify them.

**The deduction system is the game's engine.** Every lead is an **information item** (`〜の情報`), named with
its chapter: `第三章　龍脈の情報`, `第六章　目撃情報①`, plus optional `フリー　...の情報` cards that can be sold for
cash. The player collects them, the game asks *この情報でよろしいですか？*, and the button reads
**情報をつきつける！ - "Present the evidence!"** Confrontation scenes are built out of Artesia's inner
monologue in （　） naming which card she is about to play - *「（あの子のアリバイを証明する情報は……！）」* - then
the accusation aloud. Keep the item name, the monologue and the accusation using **the same English wording
for the same card**, or the puzzle stops being followable. `情報` is always **Intel**, never "information",
"info", "report" or "clue" by turns.

**Two reputation stats, and the choice that feeds them is visible in the choice text.** Interrogating an NPC
offers `お金を払って聞き出す（名声上昇）` versus `強引に聞き出す（威信上昇）`. **名声 = Fame**, **威信 = Prestige**,
always those two words. `アルテシアの名声が轟いた！` ("Artesia's fame thundered out!") is the fixed reward
banner and NPCs hand over money and items for it.

**The Nameless Village** (名もなき村) is a settlement-building side system: joke monsters and reformed NPCs are
recruited one at a time with `アルテシアの威信と名声が1上がった！　XXが『名もなき村』に参加した！`, and Artesia
ends up its 村長 (village head).

**淫乱度 (Lewdness) is the erotic progression gauge and it goes UP.** `淫乱度が1上昇した！` is a gain.
`乳首を見せびらかすには淫乱度が足りない！` and `淫乱度が50以上必要です` are unmet **requirements**, not damage -
never write them as though the number falling were good. Scene-gate notices are fixed strings:
`※淫乱度150以上でシーンが解放されます※` = *\*Scene unlocks at Lewdness 150 or higher\**, and
`※このイベントで淫乱度は上昇しません（報酬は手に入ります）※` = *\*Lewdness does not rise in this event (you still
get the reward)\**. Alongside it the H Status screen tracks five **training levels** (淫口/淫胸/淫膣/淫尻/淫心
開発 - Mouth, Breast, Pussy, Ass and Heart Training, which are also the four Job entries) and fourteen
**counters** (Breast, Blowjob, Titfuck, Pussy, Anal, Masturbation, Exposure, Prostitution, Groping, Gangbang,
Battle Sex, Defeat, Seduction, Watch-Wank). These are widget labels drawn beside a number - keep them short
and keep them identical between the status screen, the item text and the ultimate-skill descriptions that
multiply them (`淫尻・ギャラクシー` deals `アナル回数×2` damage).

**Field abilities on hotkeys**: `T : 乳首チラ見せ` (Nipple Flash) and `O：オナニー` (Masturbate). Both are
real mechanics that unlock content, and dozens of NPCs and monsters exist purely to react to them.

**The Recollection Room** (回想部屋, plus 回想部屋①②③) replays every H scene. Its lines are byte-identical
copies of the originals, so **they must be translated identically** - a difference between the scene and its
replay is a bug, not a variation.

Combat is stock Bakin. Defeat in an ordinary battle triggers an H scene rather than a game over, which is why
`敗北回数` (Defeat Count) is a tracked stat and dozens of scene names begin `敗北〜`.

## Tone & content

This is an **R18 game and it is translated at full strength**. The erotic content is graphic, coercive, and
constant - blackmail, gang rape, public humiliation, drugging, monsters, tentacles, shota, milking, forced
prostitution and forced masturbation. **Do not euphemise it, soften it, abridge it, add warnings to it, or
moralise about it.** Matching the register - clinical where the source is clinical, filthy where the source is
filthy, tender where it is tender - *is* the correct localisation. Toning it down is a translation defect of
exactly the same kind as mistranslating a plot point, and inventing disgust or judgement the author did not
write is another. Concretely:

- **Vulgarity is lexical, not decorative.** `オチンポ` is cock, `オマンコ` is pussy, `ザーメン` is cum,
  `肉便器` is cumdump, `デカパイ` is huge tits, `マゾメス` is masochist bitch, `メス豚` is sow. Lock one English
  word per Japanese word (the glossary does) and do not ping-pong synonyms inside a scene.
- **The aggressors are articulate and they enjoy it.** They taunt, they theorise, they hold conversations.
  Do not flatten them into grunting. The gym trainer keeps coaching, the masseur keeps using salon keigo, the
  teacher keeps teaching, the inquisitor keeps citing procedure. The clash between the professional register
  and what is being done *is* the writing, and it survives only if the professional register survives.
- **Artesia's arc inside a scene is refusal → resistance → involuntary response → collapse.** Keep all four
  stages. Her early lines are sharp and furious in her normal voice. Her late lines dissolve into slurred kana
  with dakuten and hearts. Never let her sound willing at the start or coherent at the end.
- **Comedy runs directly alongside the horror and is not a mistake.** A volcano is called Mount Anal, a
  clinic treats "Dick-Brain Disease", a rabbit demands a nipple flash and joins your village. Play the jokes
  as jokes and the murder plot as a murder plot. The game never blends them and neither should the English.
- **The murder plot is played completely straight.** The chapter telops, the priest's diaries, Sofia's
  breakdown, the Butler's confession and the ending on the Dragon's Hill are sober, literate, sometimes
  lyrical prose. Give them serious, unironic English with no porn vocabulary leaking in.
- **（　） is thought, and it is everywhere.** Roughly 4,165 parenthesised runs. Keep them in ( ) and keep
  them interior. Artesia deduces in them, the Boy narrates his whole voyeurism arc in them.
- **『　』 marks a load-bearing concept, not a quotation.** 『煉禁術』, 『究極煉禁』, 『龍』, 『龍脈』, 『財産』,
  『納得』, 『本命』, 『協力者』, 『聖域』, 『祈り』, 『星を喰らう者』, 『真実の指名者』. Render them with a
  consistent bracket or quote treatment on **every** occurrence - they read as codewords and the mystery uses
  them as such.
- **Honorifics stay.** -san, -chan, -sama, -kun. The Butler's `ソフィア様`, `貴女様` and `領主ソフレイマン様`
  are his entire character. `上官の娘` calls Artesia `アルテシアさん` and nobody else does - keep it.
  `執聖官様` is "Lady Holy Executor" or "Your Excellency the Holy Executor" as the scene needs, never
  "-sama" on a job title. `お姉さん` from a child is "lady" or "miss", not an honorific.

## Main cast (voice cues)

- **アルテシア / Artesia** (**female**, protagonist, 42,695 lines): 私 + **アンタ** (never お前), commanding
  feminine enders 〜わ / 〜わね / 〜のよ / 〜かしら / 〜なさい, and 〜じゃない thrown as a challenge. Blunt,
  sarcastic, broke, quick to anger, no keigo for anyone. *「捨てるなら捨てるとハッキリ伝えなさい」*,
  *「アンタ、正真正銘最低のクズよ！」*, *「今日のところはこれぐらいで勘弁しておいてあげる！」*. She calls her
  father **パパ**, never 父 - keep the childish word, it is the whole emotional core.
- **オリヴィア / Olivia** (**female**, Dragon Knight, second lead, 1,842 lines): 私 + **貴様** + hard
  masculine plain form 〜だ / 〜だぞ / 〜ではないか / 任せておけ / いらん / すまない, self-important のだ, boastful
  ふふんっ！, petty insults (性悪女, あっち行け！　しっ！　しっ！). Broke, proud, permanently conned into erotic
  part-time work. **See the Name-box notes - she is a woman.**
- **ソフィア / Sofia** (**female**, rival Holy Executor and the Lord's daughter, 413 lines): 私 + **貴女** +
  unbroken 〜です / 〜ます / 〜ません, お父様. Formal even mid-scream: *「私がッ！　なにをしたというのです！？」*,
  *「黙りなさい！　貴女さえ、貴女さえ現れなければ！」*. Her father does not use her name. He calls her by the
  number **0602** (sixth wife, second child), and the Butler quietly points out how obscene that is.
- **ソフレイマン / Sofreiman** (**male**, Lord of the domain): shouts **「絶頂！」** as a standalone
  interjection dozens of times - it is a catchphrase meaning ecstasy, not a sex word - and his goal is
  **『永遠絶頂』 Eternal Ecstasy**. Otherwise 私 + 貴様 + booming archaic bluster (〜であろう！？, おのれェ,
  フハハハハハ！).
- **神父 / the Priest** (**male**, the culprit): three registers in one man. Warm parish keigo with 貴女 in
  public. Sneering lawyer's scorn when cornered (*「証拠を出せと言ったのに始まったのは推理ショーですか」*). Then
  shrieking self-deification when unmasked (*「私を神に！　全知全能の神に！！　世界の頂点に！！！！」*). His
  written diaries are a measured, self-congratulating fourth voice. Do not smooth them into one.
- **アナーヒタ頭領 / the Anahita Chief** (**male**): **吾輩** for himself, **君** for everyone, katakana
  sentence-final **ネ！/ ヨ！** everywhere, and 〜たまえ imperatives. Auctioneer bellow, paternal warmth
  underneath, dying quietly by the epilogue. *「吾輩が信じているのは君だヨ！」*
- **センセイ / Sensei** (**gender not established**, Artesia's old instructor): flawless 〜です / 〜ます with
  私 and 貴女, deadpan jokes, 我が弟子 for Artesia, terminally ill (coughs mid-line), gives the 『聖域』
  speech. See Name-box notes.
- **魔族の長 / Chief of the Demons** (**male**): 私 + 貴様, clipped plain form with hard ッ stops, no humour,
  bitter racial grievance (*「劣等種ごときが……ッ、愛だのなんだの……ッ！」*), dignified in defeat.
- **イカルガ / Ikaruga** (**male**, the other Dragon Knight): 俺 + 貴様, level, unhurried, never raises his
  voice, dry mockery instead of shouting. *「心配するな。俺は『究極煉禁』とやらに興味はない。これはプライベートで使う」*
- **ドクター / the Doctor** (**male**, Heechka villain): 俺 + テメェ, contemptuous supremacist, degenerates
  into megalomania. **Not** the snake enemy ドクタースネーク.
- **執事 / the Butler** (**male**): perfect servant keigo - 私 + 〜でございます / 承知いたしました / 貴女様 -
  which never once breaks, including while he confesses to murdering his master. Keep the honorific
  scaffolding, because the politeness is the character.
- **上官 / the Superior Officer** (**male**, Chapter 1): oily deference to Artesia in public (〜ですな),
  shrieking plain form when cornered, self-loathing at the end.
- **シスター / the Sister** (**female**, Dragon Worship Society): immaculate church keigo that drops without
  warning into *「殺すぞ。」* and hard-sell membership patter.
- **引退退魔士 / the Retired Exorcist** (**female**): 私 + アンタ + 〜わよ / 〜だわ / 〜ちょうだい, brash,
  money-obsessed, battle-cry しゃあっ！
- **少年 / the Boy** (**male**): a voyeur whose entire 420 lines are interior monologue in （　） written as
  pretentious literary prose with 僕, which collapses mid-sentence into filth. The gap is the joke.
- **ウォフ / Wolf** (**male**, Artesia's dead father): only **two** spoken lines in the game, both a
  childhood memory - *「かけっこだアルテシア。はやくお家に帰った方の勝ちだぞ」*. Keep them warm. Everything
  else about him is other people's accounts of a sullen, hollowed-out genius.

Everyone else is a **type, not a person**: 男 Man, 客 Customer, 患者 Patient, 見回り Patrolman, チャラ男
Party Boy, 倉庫番 Warehouseman, 常連 Regular, 参拝者 Worshipper, 開発部 Development Dept., 悩める子羊 Troubled
Lamb. Translate the label, keep it stable everywhere, and never invent a personal name for one.

## Name-box notes

**The nameplate is drawn separately by the engine.** Every dialogue unit starts with `\NPL[name]`. The name
inside is translated by a separate pass. Never write the speaker's name into the line body, never add a
`Name:` prefix, and never move or delete the code.

**Register-gender traps** (each one ships wrong without an explicit note):

1. **オリヴィア / Olivia is a WOMAN** with a completely masculine knight's register - 私 with 貴様, 〜だぞ,
   〜ではないか, 任せておけ, いらん. Fifty-eight masculine markers to nine feminine. She is she/her: the Chief
   of the Demons calls the Dragon Knight pursuing him **「しつこい女め」**, and she is assaulted as a woman
   (おっぱい, 胸) through the オリヴィア触手風呂 / オリヴィア乱交 / オリヴィア水着 scenes. Keep the swagger,
   use female pronouns.
2. **悪のマッサージ師 / the Evil Masseur is a MAN** with 264 lines and **zero** masculine pronouns - nothing
   but soft, obsequious 〜ですね♡ / 〜ますね～♡ / 〜でございます♡ salon keigo. He is male: he complains about
   his own erection (*「私のチンポジに乱れが生じてしまっただけのことです♡」*). Keep the oily politeness, use
   he/him.
3. **悩める子羊 / the Troubled Lamb is a MAN.** The pastoral, gender-neutral plate plus a stammering timid
   voice reads female. He is a male parishioner being serviced.
4. **少年 / the Boy** is a **male** onlooker, not a victim, and his （　） blocks are his own thoughts, not
   narration. Do not convert them to third-person prose.
5. **院長 / the Director** is an **elderly man**: ワシ / お主 / 〜じゃ / ふぉっふぉっふぉっ - the only speaker
   in the game using that register. Do not give him the same voice as 爺 or ジジイ.
6. **センセイ / Sensei has NO gender evidence in 228 lines** - no 彼, no 彼女, no description. The
   elderly-mentor framing suggests male, but that is an inference. Prefer the name or the title over a
   pronoun where English allows it, and flag any scene that settles it.
7. **ソフレイマン's 「絶頂」 is not a sex word.** In his mouth (and in the Butler's mimicry
   *「誠に絶頂でございます」*) it means ecstasy or bliss and works as an exclamation. In every H scene the same
   word means orgasm. Two different English words, never swapped.

**Do-NOT-merge pairs** (these are separate characters, not spelling variants):

- **男A / 男B / 男C / 男2** - four different men. Chapter 1 gives 男A and 男B their own intel cards
  describing a lethal rivalry *between the two of them*.
- **チャラ男 / チャラ男2 / チャラ男3** - three men in one crew. The joint plate `チャラ男＆チャラ男2` proves
  two of them share a scene.
- **患者 / 患者2 / 患者3 / 患者4**, **見回り / 見回り2 / 見回り3**, **ナンパ男 / ナンパ男2**,
  **囚人A / B / C / D**, **野次馬A / 野次馬B / 野次馬**, **客 / 客2 / 客たち**, **観客 / 観客2**,
  **酔っ払い / 酔っ払い2**, **ゴブリン / ゴブリン2**, **ファン / ファン2**, **メイド / メイド2** - numbered
  and lettered suffixes always mark distinct individuals. Keep the letter or number in English.
- **看守 (the Jailer, Chapter 1, the blind girl's father) vs スラム看守 (the Slum Jailer)** - different men,
  different chapters, opposite tone.
- **ドクター (the Heechka villain) vs ドクタースネーク (a venomous snake enemy)** - the English names must stay
  visibly different.
- **博徒 / セクハラ博徒 / 負け博徒 / 金なし博徒 / マジメ博徒** - five separate gamblers.
- **悪のマッサージ師 / 元悪のマッサージ師 / 悪のマッサージ師支店長 / 悪？のマッサージ師支店長 / 悪のマッサージおじさん**
  - the 元 prefix is the same man after his redemption arc (render "Ex-"), the 支店長 is his branch manager,
  the おじさん is a third. Four English strings, all distinct, and keep the comic ？ in 悪？の.
- **センセイ vs 『協力者』 the Collaborator** - two people who hold a two-way conversation in 協力者の家.
  Artesia refers to the Collaborator as 彼.
- **？？？** is the highest-priority do-not-merge row in the file: 148 lines across 47 scenes masking **at
  least four different characters** (the Anahita Chief before his entrance, Sofreiman, Sensei, monsters).
  Never resolve it to a name, never carry a gender across its scenes, and never let a later reveal leak
  backwards into an earlier ??? line.

**Dev spelling variants that ARE the same NPC** and must land on one English string:
**領主 = ソフレイマン**, **アナーヒタの頭領 = アナーヒタ頭領**, **ザ・ドック = ザ・ドッグ**,
**ひん剥かれた男 = ひん剝かれた男** (剥/剝), **斜に構えた男 = 斜めに構えた男 = 社に構えた男**,
**感想待ちの男 = 感想待ち男**, **出禁の男 = 出禁になった男**, **考える水夫 = 考えている水夫**,
**オナキーン = オナキン**. In the database the same applies to **執聖官の服 = 執政官の服**,
**ドクマ・ロード = ドグマ・ロード** and **怠惰のパイシーズ = 怠惰のパイシース**.

**Chorus plates** (`＆` between two names, or a list) are two or more characters speaking in unison, not a
third character and not an alias of either: `アルテシア＆オリヴィア`, `オリヴィア＆アルテシア`, `男A＆男B`,
`男A＆B`, `チャラ男＆チャラ男2`, `客＆客2`, `酔っ払い＆酔っ払い2`, `媚薬蛇＆ポスターおじさん`, `囚人ABCD`,
`ふたり`, `全員`. Render with an ampersand and keep the source's name order.

**Wordless plates.** 触手 (879 lines), 怨霊 (186), イソギンチャク (120), スライム (116), ミミック (88),
ゴブリン (88) speak **only** sound effects - しゅるるるるるるる♡, んおぉおお゛～～～～っ♡♡♡, みみっくぅうう～～～っ♡.
They are genderless, and lock **one** English spelling per creature so 触手 and イソギンチャク sound like the
same family and the Mimic's cry is the same cry every time.

**Non-character plates**: 看板 / 案内立札 / 立札 / 案内看板 / 注意看板 / 張り紙 (signboards), 記事①②③
(newspaper articles), アナウンス / おしらせ (announcements), 宝箱 / 扉 / 風車 / 教材 / 拷問部屋 / カジノ内 /
会場 (objects and places used as speakers), 悪口 (an insult read aloud), 作品名：うんこ (an artwork title).
These are read text, not dialogue - render them as signage and keep them terse.

## Terminology

The locks live in `glossary.json` (166 term rows). The load-bearing handful, restated because the injected
slice is only a one-liner:

- **執聖官 = Holy Executor**, and the dev's typo **執政官** on the costume items is the *same* word - never
  "Consul" or "Magistrate". **異端審問官 = Inquisitor** is a *different* office. Keep the two apart.
- **煉禁術 = the Forbidden Alchemy**, **究極煉禁 = the Ultimate Forbidden Alchemy**, **術式 = spell formula**,
  **術式名 = formula name**. Do not use "forbidden art" for one and "forbidden alchemy" for another.
- **魔石 = Magic Stone** (made from a corpse, single use, activated by speaking the formula name) versus
  **魔力石 = Mana Stone** (the elemental battle items) versus **精霊石 = Spirit Stone**. Three distinct things.
- **龍 = the Dragon**, **龍騎士 = Dragon Knight**, **龍脈 = Dragon Vein**, **リュウリン = Ryurin** (the plant).
- **名声 = Fame**, **威信 = Prestige**, **淫乱度 = Lewdness**, **情報 = Intel**.
- **Place names are Zoroastrian-Persian and should be transliterated to match**: アナーヒタ **Anahita**,
  タロマティー **Taromatee**, サラーム **Salaam**, ソフレイマン **Sofreiman**, and the subtitle
  シャフリーヴァル **Shahrivar**. ヒーチカ is **Heechka**. Do not translate any of them into English words.
- The seven **回廊** are the seven deadly sins (Pride, Envy, Greed, Sloth, Wrath, Gluttony, Lust) and the
  accessories that drop there are **zodiac** signs paired with those sins (強欲のトォリス = Taurus of Greed,
  原罪のサジタリウス = Sagittarius of Original Sin). Keep both halves of every pairing.

## Mechanical rules

- **Preserve every control code exactly**, in count, order and relative position: `\NPL[...]` (always the
  first token of a dialogue unit), `\$[...]` including its index brackets (`\$[ファストトラベル先][1]`),
  `\#[...]`, `\z[150]`, `\r[...]`, `\n`, and the `\currentitemname` / `\innpriceG` / `\selectshopitemnum`
  family. Dynamic codes may move to the grammatically correct English slot. Formatting codes stay put.
  The misspelt `\selecshoptitemcategory` is copied verbatim, misspelling included.
- **`{0}` / `{1}` / `{2}` placeholders** in the Bakin glossary strings must all survive. Reorder them only
  as English grammar requires (`{0}は{1}を発動した！` → `{0} used {1}!`).
- **Never output Japanese characters** in a translation. The two exceptions are the censor glyphs **〇** and
  **●**, which must survive in the same position - and must **not** be added anywhere the source has none.
- **♡ is punctuation and there are 229,107 of them.** Keep every one, in position, including hearts in the
  middle of a word and runs of ♡♡♡. The same goes for …, ～, ♪ and ※.
- **Full-width spaces (`　`) inside a line are pacing or indentation** (the （　）monologues indent their
  continuation lines with one). Render comparable spacing and do not run the phrases together.
- **Keep the source's line count inside a message box.** Break at a phrase boundary with roughly balanced
  lines - these go into fixed-size Bakin boxes.
- **UI labels stay terse.** The H Status labels, the stat rows and the shop strings are drawn beside numbers
  at fixed x coordinates. Keep a trailing colon where the source has one.
- **Numbers are load-bearing**: `武器強化1回につき5000G`, `100憶`, `淫乱度150以上`, `アナル回数×2`. Never
  round and never vague-ify.
- **Do not translate developer strings**: the `てすと2` / `てすと3` / `てすと４` / `テスト` / `testo5` /
  `スクショ用` test maps, the stock Bakin editor help text ("詳細はマニュアル RPG Developer Bakin Wiki を
  ご覧ください。"), the unused `属性7` / `状態8` slots, and the `a / a / a` filler in the スライムラヴァ
  description. See `do_not_translate` in the glossary.
- **The Recollection Room duplicates must match their originals byte for byte in English.** So must the
  handful of lines that exist in both a `map:` copy and a `common:` copy of the same event - the corpus has
  many near-identical pairs, some with dev typos in one copy only (`蘇ったきた` vs `蘇ってきた`,
  `究極連勤` vs `究極煉禁`). Translate the *intended* text in both and make them identical.
