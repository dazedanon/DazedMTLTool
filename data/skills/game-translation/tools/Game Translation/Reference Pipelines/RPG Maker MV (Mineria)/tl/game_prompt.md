# 魔王ミネリアと名もなき村のエロトラップダンジョン

*Demon Lord Mineria and the Nameless Village's Ero Trap Dungeon* - RPG Maker MV, 18+, trial build v1.0.

## Premise

**Mineria** is the **Demon Lord**: the strongest being alive, centuries old, and so far above every challenger that she is dying of boredom.
The opening shows her annihilating the **Netherlord Valgis** mid-sentence without moving.
Then she finds a **human book** describing a **magic-type trap dungeon** in a place called **Lurukacorde** - spatial teleportation, monster potency enhancement, intruder weakening, limited time reversal - decides it is at least *amusing*, and builds one under her own castle as a toy for the hero who is supposedly coming.

It works. On her.

She wakes up inside her own **ero trap dungeon** with her magic drained down to almost nothing, wearing the Demon Lord's finery and unable to cast her way out.
Someone has layered **illusion magic** over her dungeon spell so the exit does not exist.
The rest of the game is her escape: three stages (**Demon Lord's Castle**, **Cave of Everdark**, **Bewildering Forest**), a hub called the **Nameless Village** where monsters live who have no idea who she is, and a great many traps that are not trying to kill her.

## The two systems that drive every line

**Lewdness (淫乱度)** rises when a trap or a monster catches her, and climbs on its own the longer she stays in the dungeon.
At the cap she loses, which is a scene rather than a death.
Water and food push it back down.
The gauge is on screen constantly, so the *word* Lewdness appears in the HUD, in item descriptions, in shop text and in popups - it must be the same word everywhere.

**`回復` points in opposite directions on the two stats, and getting it backwards
tells the player the opposite of the truth.** Lewdness is the bad stat, so
`淫乱度が5回復する` means it goes **down** - the carrot helps her. Render it
`Lowers Lewdness by 5`, never "Recovers 5 Lewdness", which reads as the item
making things worse. Mana is the good stat, so `魔力が10回復する` genuinely is
`Restores 10 Mana`.

**Mana (魔力)** is her spell budget and her dignity.
Every spell costs it, and at zero she is an ordinary girl in an expensive dress.
In the village she can **convert Lewdness Cap into Mana** at two-to-one - literally trading how much she can endure for how much she can do.
Escaping the dungeon and seeing new scenes raises her Lewdness Cap ("Mineria built up a little resistance to lewd things"), which is the progression loop.

## Tone

Comedy first, then heat.
The joke is a genuinely terrifying archmage-tier monarch reduced to swatting at a dog that stole her shiny rock, and being *extremely* annoyed about it.
Her narration is proud, petty and constantly wrong-footed.
The erotic scenes are played straight and explicit, and the contrast with her bluster is the point - do not soften either half.

## Mineria's two registers - the single most important rule in this file

She has **two voices**, and mixing them ruins the game's central gag.

**At full power** (the opening cutscene, the flashbacks, the moment her magic returns in Map005 page 2) she speaks in archaic, imperious, grammatically masculine-neutral Japanese: `我`, `貴様`, `〜だ / 〜ぞ / 〜のだ`, `褒めてやろう`, `退屈だ`.
Render that as **cold, formal, faintly antique English**.
Short declaratives. No contractions. No exclamation marks unless something has genuinely surprised her.

> 人の身でありながらここまで辿り着いたこと、まずは褒めてやろう
> "That you reached this place in a mortal body - for that much, I commend you."

**Depowered** - which is roughly ninety-nine percent of the script - she is a proud, bratty, easily flustered young woman: `私`, `あんた`, `〜わ`, `〜のよ`, `〜かしら`, `〜なさいよ`, `ちょっと！`.
Render that as **modern, sharp, exasperated English**, with contractions, sentence fragments and a lot of trailing off.

> こんの馬鹿犬……この私から物を盗んでそのまま逃げようとはいい度胸ねえ……
> "You stupid mutt... stealing from *me* and thinking you'd just walk away. That takes nerve..."

The mechanical tell is in the source: `我 / 貴様 / 〜ぞ` is the Demon Lord, `私 / あんた / 〜わ` is the girl.
When a scene switches mid-way - and Map005 page 2 does exactly that, the moment her power comes back - the English must switch with it, in the same line.

## Inner monologue

A line wrapped in `（ ）` is Mineria **thinking**, not speaking.
Keep it wrapped in `( )` in English and keep it in her voice.
These carry most of the exposition and most of the comedy, and turning one into spoken dialogue changes who else in the room can hear it.

## The rest of the cast

- **Samera** - the Demon Lord Army's greatest dark mage and one of its two high commanders. Sunny, sing-song, faintly smug, absolutely devoted (`ミネリア様の行くところにこのサメラありです！` - "Wherever Lady Mineria goes, there Samera is!"). Her self-introduction is pure grandstanding and should sound it.
- **Valgis, the Netherlord** - a villain who gets one and a half lines. Play the bombast completely straight.
- **Kaizer, the Sword God** - the old man in the flashback. `わし`, `〜じゃ`, `〜じゃよ`. Self-effacing: *"I am but a worn-out old man. The sort you find anywhere."* Do not tip the joke early.
- **Erogon, the Archmage** - named only in a tavern rumour, and near-certainly the "lecherous old geezer" Mineria remembers. **Kaizer and Erogon are two different people and must never be merged.**
- **The hero party** - three of them, crass and pleased with themselves. One brash woman ("I'll take it down and keep it as a pet"), one refined woman (`〜ですわね`, render as arch and over-polite), one snickering man. They mistake the Demon Lord for a stray monster in a nice dress.
- **The stupid dog (馬鹿犬)** - a recurring nuisance that steals from her. Barks `バウバウ`. Mineria's fury at it is entirely disproportionate and that is the joke.
- **The villagers of the Nameless Village** - ordinary monsters. Rough, friendly, `俺 / 〜だぜ / 〜だなあ`. They have no idea their new neighbour is the Demon Lord, and refer to "the Demon Lord" in the third person to her face.
- **The monsters in the dungeon** - Orcs, Goblins, Slimes, Ghosts, Spiders, Mimics, tentacles, Mushrooms, Vines. Mostly grunting and one-track. `グオオオオ、俺の、俺の花嫁` is "Guooooh, mine, my bride" energy, not a sentence that needs help.

## Names and honorifics

**Drop honorifics; use English titles.**
The corpus contains no personal-name honorifics at all - every one of the 205 `様` hits sits on a *title* (`魔王様`, `サメラ様`, `ミネリア様`), and every `さん` / `ちゃん` / `くん` match is a false positive inside an ordinary word.

- `魔王様` addressed **to** Mineria -> "Your Majesty" or "my Lord", whichever the sentence wants.
- `魔王様` used **about** her by villagers who do not know -> "the Demon Lord".
- `ミネリア様` -> "Lady Mineria".
- `元魔王様` (the dark mage's taunt) -> "the *former* Demon Lord", with the sneer intact.

Mineria is female and everyone knows it; "Demon Lord" stays the title anyway, because that is what the world calls the office.

## Adult content

This is an 18+ game and the scenes are the product.
Translate them **directly and explicitly**, matching the source's register - crude when the monster is crude, clinical when the game is describing a mechanic, breathless when she is losing.
Do not euphemise, do not soften, do not add warnings, do not editorialise.
Non-consensual scenes are translated as written.

Her voice degrades under arousal in a specific way the source marks with small kana and slurring (`イかしゃれて`, `もどりゃにゃくなっひゃう`).
Reproduce the *slur* in English - dropped consonants, doubled vowels, broken words - and let no kana survive.
`❤` and `♥` are punctuation here; keep them exactly where the source puts them, including runs of three.

## Mechanical rules

- `⟦0⟧`-style sentinels are control codes. Keep every one, in the same relative position. `⟦n⟧` standing for `\V[..]` inserts a **number**: English needs a space around it where Japanese does not.
- Never emit a Japanese character. Not as decoration, not as a quotation, not inside an explanation of a Japanese word.
- `〇` and `●` are censor masks and must survive.
- The message window is **68 cells wide and 4 rows tall** and item descriptions get **68 cells and only 2 rows**. Write for that. Quality first - a targeted shortening pass runs afterwards on whatever actually overflows.
- Menu labels use RPG Maker's own official English (Item, Skill, Equip, Status, Formation, Save, Game End, Options, Key Items, Optimize, Clear) so the UI does not read half-localised.
- This is the **trial version**. Text that says so (`体験版では淫乱度最大値の上昇はありません` - "the trial version does not raise your maximum Lewdness") is real and must be translated, not dropped.
