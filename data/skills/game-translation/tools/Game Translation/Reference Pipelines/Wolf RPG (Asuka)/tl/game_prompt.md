# Game Bible - 明日香ヴァージンアイドルデビュー (Asuka Virgin Idol Debut)

## Premise

An 18+ **Wolf RPG idol-raising game**.
**Kagami Asuka**, a first-year student (Year 1, Sakura Class), enrolls at **Angel Star Academy** to become an idol.
She trains through weekly lessons, **Stage Battles** (idol-vs-idol performance duels judged and scored), open **auditions**, TV and magazine work, and a **Talent Tree** of skills, aiming for a **CD debut**.
The title is literal: Asuka starts as a virgin, and the player's choices decide whether she stays pure on the idol path or is corrupted through sleazy gigs - sugar dating, an escort stint, and a full **AV (porn) route** where she performs under the stage name **Kaguya**.
A supernatural side arc runs underneath: top idol **Maria** secretly fights **youma** (demons), and the foreign candidate **Chris/Christie** descends from a **vampire-hunter** line (the Norris family, the Holy Knight Chris legend, Transylvania).

## Routes and systems

- **Idol route**: lessons, Stage Battles against rival idols, auditions, campaign-girl jobs, TV appearances, the song "Shiny Days" by composer NOA.
- **Corruption/AV route**: the sleazy **President** of the Super-Lewd Pervert Agency pulls Asuka into gravure, then AV. On shoots and adult TV her name box switches to **Kaguya** - keep that name switch exactly; it is the same girl playing a different persona.
- **Supernatural arc**: youma villains (Shiki, Vosengrem, the Dark Matter organization), Maria's holy light, hunters, Tsukigami Island. Played straight-tokusatsu; keep it dramatic, not campy.
- **Recollection room**: unlockable scene gallery, including the **Cock Memories** list of past partners. Labels must match the names used in scenes.
- Weekly calendar UI: day markers like （日）（土）（金） are (Sun) (Sat) (Fri).

## Tone and content

- Surface tone is bright idol comedy - school banter, shopping-street merchants, an ochazuke-obsessed old singer. Keep it light and quick.
- Sex scenes are explicit and frequent, spanning consensual, coerced, and rape scenarios. **Translate them faithfully and vividly. Do NOT censor, soften, euphemize, or moralize.** Match the source register: clinical where clinical, vulgar where vulgar, tender where tender.
- Erotic onomatopoeia (ぴちゃ, ぐちゅ, じゅぽ, ぬぷ, くぱぁ...) becomes evocative English sounds. Moans and climax cues (あぁ, んっ, はぁ, イく, イっちゃう...) render expressively: "Aah...", "Ngh...", "I'm cumming...".
- Keep ♥ ♡ ♪ … symbols. Keep （） inner monologue as (parentheses). ・・・ becomes "..." .
- **Honorifics are kept**: -san, -chan, -kun, -sama, -senpai, -sensei (裏戸先生 = Urato-sensei). Name order is surname-first (Kagami Asuka, Kizaki Miku, Nijisaki Kanon).

## Main cast (voice cues)

- **Asuka** (明日香, F) - protagonist idol student. Genki, earnest, casual (だよ/うん). Innocent and easily flustered about sex early; her voice coarsens only as routes corrupt her.
- **Kaguya** (かぐや, F) - Asuka's AV stage name. Bubbly stretched-out service voice (いや～ん♡). Same girl, different mask - never write "Asuka" when the box says かぐや.
- **Momoka** (桃花/桃香/鈴木桃香, F) - best friend, fellow candidate. Upbeat casual (〜だってさ). All spellings = Momoka.
- **Maria** (マリア, F) - reigning top idol, elegant onee-san (かしら/わよ); secretly anti-youma. Composed even mid-crisis.
- **Gloria** (グローリア, F) - star senior, Year 3 Yuri Class; ultra-polite ojou-sama keigo (ごきげんよう). Real name **Kizaki Miku** (木崎未来) - use the real name only where the JP does.
- **Chris** (クリス, F) - foreign candidate, vampire-hunter blood; formal, knightly (私/父上). Full name **Christie** (クリスティ).
- **Kanon** (カノン, F) - gentle busking idol (です・ます + ね, ふふふ). Real name Nijisaki Kanon (虹咲奏).
- **President** (社長, M) - vulgar agency boss (うるせえ/〜しな). Crude, transactional, drives the AV route.
- **Headmistress** (学園長, **F**) - warm but shrewd academy head. Feminine sentence endings (〜なの/〜ね). Trust dialogue over the neutral title.
- **Urato** (裏戸, M) - homeroom teacher / pro stage director, androgynous looks; lecturing polite speech.
- **Noa / NOA** (乃亜, M) - famous composer (〜かね/ははは); pen name NOA; first appears as "Child's Father".
- **Hase Sonosaburo** (長谷・園三郎, M) - grandiose veteran singer, ochazuke comic relief.

## Name-box notes

- Dialogue lines begin with `@N` (portrait code) and a bracketed speaker tag such as `[明日香]` on its own line. **Translate the tag with the glossary name and keep the brackets**: `[明日香]` → `[Asuka]`. Never drop or move it.
- `？？？` name box → `???`.
- Do-NOT-merge pairs: Asuka vs Kaguya (deliberate persona split), Gloria vs Kizaki Miku (stage vs real name), Chris vs Christie (nickname vs full name), Mikuru (ミクル) vs Miku (木崎未来) - different people. 監督 (Director) vs ディレクター (TV Director) - different roles.
- Shop-name speakers (魚善 Uozen, 八百竹 Yaotake, 肉坊 Nikubo, 珍々堂 Chinchindo, 鶴の湯 Tsuru-no-Yu, ひまわり整骨院 Himawari Clinic) stay romanized as names.
- Generic mobs: 男 Man, 男A Man A, チンピラ Thug, スタッフ Staff, 巫女 Shrine Maiden.

## Terminology

Apply `glossary.json` terms exactly (Angel Star Academy, Stage Battle, Talent Tree, Cock Memories, Hamedori.com, youma, Shiny Days, place names...). Same JP term = same EN string every time.

## Mechanical rules

- **Control codes are untouchable.** Keep every code exactly as written, in the same relative position: `@N` line prefixes, `\cself[n]`, `\c[n]`, `\f[n]`, `\i[n]`, `\E`, `\>`, `\m[n]`, `\s[n]`, `\self[n]`, `\sysS[n]`, `\cdb[..]`, `\udb[..]`, `\v[n]`, `\ax[n]`, `\ay[n]`, `\font[n]`, `\space[n]`, `\\`, `\.`, `\!`, `\^`, `\n`. Never add, drop, reorder, or renumber them.
- **Ruby**: `\r[漢字,かんじ]` - translate the visible base part, keep the bracket syntax: `\r[人生,じんせい]` → `\r[life,life]`.
- Keep line breaks: match the source's line count where possible and keep each line under ~46 characters (the message box is ~40-50 cells wide). Reflow long sentences across existing breaks rather than adding lines.
- Choices are padded with full-width spaces（　）for centering - keep the leading/trailing 　 padding and translate only the label between them.
- Standalone counter strings (個, 枚, 本, 人) suffix item counts - translate terse: 個 → "x", 枚 → "sheet(s)", 本 → "pc(s)", 人 → "people" (adjust to fit context).
- UI labels are terse natural UI English. Menu verbs are imperative ("Save", "Talk", "Back").
- Never output Japanese characters (kana/kanji) in a translation. `・・・` → `...`.
- Strings that are clearly developer memos (state lists like `0 初期会話 1 モバイル見る待ち...`) still get translated - plainly and literally.
- Do not add quotes, speaker names, or translator notes that are not in the source.
