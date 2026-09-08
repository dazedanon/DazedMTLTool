# Cross-cutting voice rules

These are habits that run through the whole script and are not owned by any one
character. Per-character register lives in `glossary.json`; the premise, the
cast and the tone mandate live in `game_prompt.md`. Nothing is restated here
that either of those already says.

## Onomatopoeia and moans

No kana may survive, not even as decoration.
`っ` / `ッ` is a glottal catch; `ぅ ぉ ぇ ぃ ぁ` is a vowel dragged out.
Render both with Latin letters - a doubled vowel, an `-h`, a hyphen - and delete
the kana. `Ogh゛っ❤` is wrong; `Ogh-❤` is right. The dakuten `゛` may stay: it
reads as distortion.

The recurring sound set in this corpus and the rendering to keep consistent:

| source | English |
|---|---|
| `グオオオオ` | `Guooooh` (the Orcs' signature, always four-plus O's) |
| `バウバウ` | `Bau bau` (the dog - it is a silly bark and should read silly) |
| `んおっ` `んぐぅ` | `Ngh-` `Nnghh` |
| `ひにゃぁぁ` `にゃっ` | `Hnyaaah` `Nya-` (she slurs into cat noises when overloaded) |
| `あぁぁあ` `はあ、はあ` | `Aaahh` `Haah... haah` |
| `イく` `イっちゃう` | `I'm cumming` `I'm gonna cum` |
| `ぴちゃ` `ぐちゅ` `くちゅ` `ぬぷ` | wet English sounds - `Schlk` `Squelch` `Shlick` `Nnp` |

## Slurred speech is a mechanic, not a typo

Under high Lewdness the source deliberately corrupts her consonants:
`イかしゃれて` (< イかされて), `もどりゃにゃくなっひゃう` (< 戻らなくなっちゃう).
Reproduce the *slur* in English rather than the clean sentence - drop
consonants, double vowels, break words - so the reader can hear how far gone
she is. A grammatically tidy line here loses the only signal the scene has.

## Hearts are punctuation

`❤` `♥` `♡` are load-bearing and appear in runs (`❤❤❤`). Keep the exact count
and the exact position. They are not in the shipped font and render from a
browser fallback, which is already true of the Japanese build - that is not a
bug to fix.

## The full-width space is a pacing gap

`　` inside a line is a beat between gasps, not indentation. Render it as a
space. Collapsing it runs the phrases together and kills the rhythm. Trailing
ones at end of line are padding and are dropped by the extractor before the
model ever sees them.

## Third-person "the Demon Lord"

Villagers and monsters discuss `魔王様` in the third person to Mineria's face
without knowing who she is. Keep the third person - the dramatic irony is the
joke, and turning it into direct address destroys it.

## Item descriptions carry their numbers

Every consumable description ends in a parenthetical the player reads as data:
`（100G）`, `（上限3個）`, `淫乱度を10下げる`. The number and the unit must
survive exactly, and the parenthetical stays parenthesised. These are two-line
fields, so keep the source's own line break where it has one.

## Running gags worth deciding once

- **The stupid dog.** `馬鹿犬` / `バカ犬` recurs across the castle, the village,
  the cave and the forest. Pick one English rendering - "stupid mutt" - and keep
  it, including in the taunt `負け犬の元魔王様` where the dark mage puns on
  *dog*: "Well, well - if it isn't the *former* Demon Lord, whipped like a
  stray." The pun must land in the English, not only in a note.
- **"Not a bad idea, for a human."** Mineria repeatedly compliments human
  ingenuity while being insulting about humans. Keep the backhandedness.
- **Erogon's name** is a pun on エロ. It reads as a pun in English unchanged, so
  do not naturalise it away.
