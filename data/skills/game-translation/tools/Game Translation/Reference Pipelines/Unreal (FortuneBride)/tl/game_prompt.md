# No Ecstasy, No Life (FortuneBride) — Translation Bible

## Premise
**ノーエクスタシー・ノーライフ** (*No Ecstasy, No Life*, project "FortuneBride") is an **adult (R18) first-person slot-machine/roguelite eroge** set in a Japanese school. The jaded male protagonist **Ren (蓮)** and his childhood friend **Konoha (夏凪木葉, Natsunagi Konoha)** are drugged via chocolate from the creepy new **Principal** and wake in a red, Buddhist-altar-styled **chapel** (the abandoned mountain chapel from a school ghost rumor). A voice from a monitor — the **GM** — forces them into a "**Bride Candidate** selection" ritual-game: Konoha is strapped into a **cabinet** and Ren must drive her to climax through a **slot machine** whose reels send stimulation to body parts (feet, ears/neck, mouth, breasts, clitoris, vagina, anus). Earn **Pleasure Points**, deposit the **quota** into the **offering box** before each **Death Deadline** or Ren dies (floor opens). Rewards come from the **well**; **Charms** are bought in the **shop** with **tickets** and stored on **shelves**; a **typewriter** prints three buff **cards** after each deadline.

The cult behind it (the **Erotic Plasma Order**, run via **NightDance Inc.**) believes women hold a dormant **Future Receptor** (未来受容体) — a "third eye" nerve cluster around the pineal gland that only activates ("**awakening**", 開眼) through extreme ecstasy ("**Jet Ecstasy**"). Between deadlines the GM offers escalating sexual "proposals" (kiss → handjob → blowjob → missionary with condom → cowgirl → reverse cowgirl → standing from behind → raw creampie → anal) in exchange for free shop restocks, dressing each in deadpan pseudo-scientific cult logic.

## Mental-state system (drives the four endings)
Charms carry **mental-state traits** that recolor Konoha's psyche along four paths, each with three **steps**:
- **Normal (ノーマル)** — untouched, her real self.
- **Rebellion (反抗)** — burning rejection and disgust.
- **Ahe (アヘ)** — reason melted by pleasure (ahegao); clingy, lewd, lovestruck.
- **Void (虚無)** — all attachment spent; empty, flat, monosyllabic.
Priority when tied: Void < Rebellion < Ahe. The ending scene replays the same rooftop wake-up beat in four voices — keep the parallel phrasing recognizably parallel across the four endings.

## Tone & content
Explicit adult eroge; render sexual content directly and crudely where the JP is crude (creampie, raw, handjob, blowjob, ahegao). Don't euphemize the GM's clinical-lewd register — the comedy/menace is the contrast between lab-report vocabulary and what he's actually proposing. School scenes are slice-of-life with dry inner monologue; the ritual scenes are horror-tinged. Text in （） is Ren's inner monologue/narration — keep the parentheses. ♥/♪ stay. Hidden prefixes like `___`/`__` at line start are typewriter pause markers — never delete or translate them.

## Cast (voice cues)
- **Ren (蓮)** — male protagonist/narrator; name-box is 俺 early and 蓮 later (same person, keep "Ren" once named, "I/me" in narration). Jaded loner slacker, deadpan (しょーもな), short clipped protests in the ritual (ふざけるなよ); flustered around Konoha's feelings; a virgin and admits it.
- **Konoha (木葉 / full name 夏凪木葉, Natsunagi Konoha)** — female childhood friend/heroine; bright, popular, ace of the track team, always top of the class; casual girlish speech (じゃん, 〜なよ), teases Ren but genuinely devoted (childhood marriage promise). In the ritual she goes from terrified to trembling consent to increasingly open desire — keep her lines halting, with commas and trailing particles (…いいよ？ / 欲しい、な). Ending variants: Normal=warm tsukkomi, Rebellion=venomous disgust, Ahe=breathless clingy lewd, Void=flat and hollow.
- **GM** — the voice/figure on the monitor; gender unstated (translate neutrally, "it/he" → prefer avoiding pronouns or use "he"). Polite-condescending lecturing male register (〜たまえ, 〜かね, だ/である) mixing cult scripture with fake neuroscience; calls Ren 蓮君 ("Ren-kun" → "Ren, my boy"/"dear Ren" flavor, or plain "Ren"), calls Konoha 花嫁候補 "the Bride Candidate" or 木葉さん. Keep name-box as "GM".
- **？？？** — "???"; pre-reveal Konoha on the rooftop, and the Principal's first line. Translate the box as "???".
- **Principal (校長)** — drained, eerie, over-polite (ですよ); speaks in cult riddles ("awakening", "a fine bride").
- **Teacher (先生)** — classroom drone lecturing Erotic Plasma doctrine as exam material; dry textbook register.

## Terminology (translate consistently — see glossary.json)
死の期限=Death Deadline, 未来受容体=Future Receptor, 第三の目=third eye, 開眼=awakening, 完全開眼者=Fully Awakened One, 花嫁候補=Bride Candidate, 花嫁=Bride, ジェット・エクスタシー=Jet Ecstasy, エロティックプラズマ団=Erotic Plasma Order, 快楽ポイント=Pleasure Points, ノルマ=quota, 賽銭箱=offering box, 井戸=well, チャーム=Charm, 精神状態特性=mental-state trait, ノーマル/反抗/アヘ/虚無=Normal/Rebellion/Ahe/Void, 階梯=step, タイプライター=typewriter, 札=card, 筐体=cabinet, シンボル=symbol, パターン=pattern, 特性=trait, チケット=ticket, 補充=restock, リロール=reroll, 礼拝堂=chapel, 儀式=ritual, NightDance社=NightDance Inc., 調整（チューニング）=tuning, 同期（シンクロ）=sync, スキン=condom, ラテックスの膜=latex membrane, 生=raw, 中出し=creampie.

## Mechanical rules
- Preserve rich-text/markup exactly: `<Green>…</>`, `<LightGreen>…</>`, `<Red>…</>`, `<img id="Ticket"/>`, `{Ticket}`-style placeholders, `\n`.
- Never output kana/kanji in the English. Numbers and stat lines stay compact.
- **Be concise**: strings are injected into fixed byte spans (an ASCII translation must fit in ~2× the JP character count). Prefer the shortest natural phrasing; trim filler before sacrificing meaning. UI labels especially: terse imperatives ("Buy", "Back", "Equip").
- Do not translate dev/debug warnings (Blueprint warnings, "DAに…" asset errors) or binary-garbage strings — leave their translation empty.
