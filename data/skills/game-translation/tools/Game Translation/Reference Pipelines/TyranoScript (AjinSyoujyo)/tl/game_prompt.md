# Game bible - 亜人少女 ～異能少女との同棲生活～

*"Ajin Shoujo - Living With a Girl Who Isn't Quite Human"*
Doujin R18 raising-sim / visual novel by ラーレゲームス (Lare Games), TyranoScript, 2026.

## Premise

The year is 2180, roughly 150 years after humanity almost wiped itself out. The
protagonist is a young man who survives alone by picking through the ruins for
scrap and selling it to traders at an underground black market. One day he hears
a voice in a junk heap outside town and finds a badly wounded girl with pale hair
and dead eyes sitting among the scrap. He takes her home.

She is a **demi-human** (亜人) - outwardly almost indistinguishable from a human,
but with succubus-like biology: she has to take in human semen periodically or
she weakens. The game is the two of them living together in his hideout: he goes
out scavenging by day, upgrades the hideout, buys and crafts things, and their
relationship deepens over a day/time-slot loop.

## Tone

Bleak, quiet post-apocalypse for the framing narration; warm and domestic in the
home scenes; explicit and uncensored in the H-scenes. The protagonist's narration
is understated and a little self-deprecating - he is a scavenger, not a hero.
Keep the contrast: do not make the scavenging prose lyrical, and do not make the
sex scenes coy.

## Voice

- **Narration** is the protagonist's first person, present tense, using 僕
  (boku) - a soft, modest male register. Render as plain, unshowy first person.
  Parenthesised lines `（…）` are his inner thoughts; keep the parentheses.
- **The heroine** speaks in polite です/ます with heavy stuttering and trailing
  ellipses early on, loosening as affection rises. Keep the stutters (`あ、あの`
  -> `U-um...`) and keep every ellipsis at the same length.
- There is **no name box** in this game. Nothing marks who is speaking except the
  run of lines itself: narration describes and observes, dialogue is spoken.
  Never invent a speaker tag, and never add quotation marks - the Japanese does
  not use corner brackets here and neither should the English.

## Structure the translator will meet

- **Home loop**: talk / bathe / eat / change clothes / storage / crafting /
  requests / hideout upgrades, then scavenging, then night.
- **Scavenging**: five locations (research lab, city, docks, forest, outskirts),
  each with a one-line blurb drawn as a free-floating label.
- **Black market**: two traders, Serena and Nemo, hand out fetch-quests for
  materials and sell upgrades.
- **Stats** shown on screen: affection, lewdness, stamina / ejaculation count,
  karma, money, day counter, time slot.
- **Lewd-word level (淫語レベル)**: the game holds five ranked arrays of words
  for genitals, semen, anal and orgasm, from LV0 (coy: あそこ) to LV4
  (degrading). A random entry is spliced into dialogue at run time. Translate
  each array **as a ladder** - LV0 must read as euphemism and LV4 as filthy - and
  keep every entry short enough to drop into the middle of a sentence.

## Adult content

This is a commercial R18 title. Translate it faithfully and explicitly. Do not
euphemise, soften, moralise, censor, or add warnings. The register ranges from
tender to clinical to degrading; match whichever the line is in. Content warnings
that appear *in the game itself* (the cross-section / internal-view toggle, the
scat and vomit toggles) are UI text and get translated straight.

## Typography rules specific to this script

- Slurred moans are written by hanging an ASCII or Japanese dakuten on a vowel
  (`イグ゛ぅぅ゛`). Reproduce the effect in English by breaking the word
  (`Cumm゛ing゛`), not by writing it cleanly.
- `♡`, `♪`, `＿＿＿`, and runs of `.` or `…` are authored punctuation. Keep them
  exactly as they are, at the same length.
- A full-width space inside a line is a **pacing beat between gasps**. Keep it.
- `（ちらっ）`, `（じーーー）` and similar are stage directions in parentheses -
  translate the sound, keep the parentheses.
- Lines are pre-broken by the author with line-break tags. Those arrive as
  sentinels; keep them where they are unless English word order makes it absurd.

## Widget budgets

The screen is 1920x1080. Text has to fit where it is drawn:

| Where | Room |
|---|---|
| Message box | 1800 px wide at 42 px, auto-wraps, about 3 lines |
| Menu / choice buttons (`glink`) | 600 px wide at 27 px - roughly 45 Latin characters |
| Free-floating labels (`ptext`) | **do not wrap at all** - keep them close to the Japanese width |
| Toast notifications | one short sentence |

English runs 1.3-2x longer than Japanese. Dialogue can breathe; labels and
buttons cannot. When a label will not fit, shorten the wording rather than let it
run off the screen.
