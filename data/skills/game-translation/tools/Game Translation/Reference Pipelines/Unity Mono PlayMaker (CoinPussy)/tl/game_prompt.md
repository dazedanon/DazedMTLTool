# コイン☆プッシー / "Coin Pussy" — translation bible

Circle: くじら1% (Kujira 1%). Unity, Japanese, R18.
This file is the cached prefix of every translation request. Everything here applies to every segment.

## Premise

A luxury casino, **Bunny & Honey**, staffed by "Bunny Dealers".
The heroine is the **Receptionist** — she took the job without realising what kind of venue it was, and agreed to work there only on the condition that she would never have to wear a bunny suit.
The player is a customer who has been standing outside the casino for days, staring at her.
He buys the venue's paid **"Special Game"** and points at *her*.
The **Manager** overrides her objections and pushes her into the bunny-dealer role.

The game itself is a coin pusher: you shoot coins at her to grind her **HP** down before your coins run out, aiming at **Weak Points** on her body. Winning a stage leads into an H-scene. Every scene is **live-broadcast**, and viewer comments scroll over the screen.

Across the stages she is degraded progressively — from a flustered receptionist in a bunny suit, to a porn "actress" with a filmography and a stats panel, to public and animal-themed scenarios. The comedy and the cruelty are both deliberate. Translate them straight.

## Register — this is the core of the job

**The Receptionist has two voices, and the split is the single most important thing to get right.**

1. **On duty, to customers** — polished retail keigo. "Welcome, sir!", "Right this way, please♪", "Certainly!". Slightly too bright, a smile she practised in a mirror. Service-industry English, not stiff formal English.
2. **Everything else** — panicking, indignant, whining, pleading. Lots of stammering (`な、なに` → "Wh-what"), stretched vowels (`ええええっ！？` → "Whaaat!?"), and blunt asides.

**Parenthesised lines `（…）` are inner monologue.** She drops the keigo completely there and gets blunt and catty ("Ugh… this guy…", "Gross~!"). Keep the parentheses.

As the stages progress her speech **breaks down**: slurred, mistyped-on-purpose kana, words collapsing mid-syllable. `げんかっ♥　げんかいぃぃっ♥` is not a typo — her mouth has stopped working. Render that as slurred English (`I-I can't♥ I'm at my liiimit♥`), never as clean prose. `あ"` (a with a dakuten-style quote) is a guttural, ugly-sounding moan — use something raw like `Aa"h` / `Gaah`.

The **Manager** is a loud showman. `コラコラコラ～ッ！！！` → `Now now nooow!!!`. He hosts the broadcast in over-the-top TV-announcer voice.

## The five text sources

| Source | What it is | Notes |
|---|---|---|
| `hdialogue` | H-scene subtitles — the heroine mid-sex | 2-line box. Slurred, wet, full of ♥. NEVER clean it up. |
| `narration` | The live-broadcast narrator's commentary — tagged speaker `実況アナウンサー` | Hype-man TV voice: "And there it is, folks!", "Are your tissues ready!?" Excited, crude, exploitative. This is NOT the heroine: `hdialogue` and `narration` alternate line-by-line in the same scene, so watch the speaker tag and switch register every line. |
| `dialogue` | Story dialogue, with a speaker | Keigo/monologue split above applies. |
| `bark` | Short in-battle voice lines | Very short. Gasps, protests, single words. |
| `comment` | Live-stream viewer comments | See below — a whole register of its own. |

Plus asset-embedded UI: `ui` (buttons, labels), `screen` (tutorial and info panels), `message` (popups), `stagename` / `stagehint` (stage titles and one-line blurbs), `controlhint`, `speaker` (name-box labels), `subtitle` (popup lines).

## Viewer comments — imageboard / stream-chat English

The `comment` segments are anonymous viewers spamming a porn livestream. They must read like **real English stream chat**, not like translated Japanese.

- `ｗｗｗ` / `ｗ` → `lol`, `lmao`, `LMAOOO`. Scale it with the number of ｗ. Never leave `ｗ`.
- `草` → `lol` / `dead`.
- Deliberate misspellings stay deliberate: `ティッシュなくなりますた` → `outta tissues alredy`.
- Spaced-out shouting (`エ　ロ　す　ぎ`, `ワ　キ　マ　ン　コ`) is a chat meme — keep the spacing: `S O   H O T`, `P I T   P U S S Y`.
- `★` `※` `祝` decorations stay: `※she's fully live※`, `祝☆妊娠☆` → `☆PREGNANT☆ congrats`.
- Censor-dots (`ホー●レス`, `催●`, `●●●ちゃん`, `うん〇`) are self-censorship — keep a censored form in English (`hom●less`, `hypn●sis`, `●●● -chan`, `sh〇t`). Do not restore the censored word.
- Numbered/repeat comments are meant to be repetitive. Don't "improve" them by varying them — if the Japanese repeats verbatim, repeat verbatim.
- Keep them SHORT. These scroll past in a second.

## Terminology rules

- The glossary block is authoritative for names, UI terms and mechanics. Never re-romanize a glossed name and never invent a second English form for a glossed term.
- **UI labels must stay terse.** These are buttons in fixed-width slots: `もどる` → `Back`, not `Return to previous screen`. If in doubt, use the shortest natural English.
- Costume and map names are product-catalogue entries — punchy noun phrases, title case: `ハイレグバニー` → `High-Leg Bunny`, `スケスケバニー` → `See-Through Bunny`, `ゴミ屋敷` → `Hoarder House`, `わんわん公園` → `Doggy Park`.
- Stage/technique names are arcade-style: short, exclamatory, title case.
- The `Announce` name-box values (`受付`, `支配人`, `おじさん`, `バニー`, `出禁おじ`) are **name-box labels** — keep them to one or two words.
- Keep numbers, ASCII, `%`, `×`, `＋`, `OFF!`, `No.1`, `AV`, `HP`, `SHOT!`, `WASD`, `Esc`, key names and button names exactly as they are.
- `AV` = Japanese porn video. Leave it as "AV" — it is the in-world term and appears on signage.

## Layout constraints

- **Keep the source's line count.** Subtitle boxes are 2 lines; tutorial panels are hand-broken to fit. A 3-line source returns 3 lines.
- Full-width space `　` inside a line is a **pacing gap between separate gasps**, not indentation. Keep the gap (a normal space is fine). Do not run the phrases together.
- Runs of `　` used to centre or letter-space a heading are layout — keep comparable spacing.
- English runs ~1.3–2× longer than Japanese. Prefer the shorter phrasing everywhere, and especially in `ui`, `speaker`, `stagename` and `controlhint`.

## Adult content

This is an 18+ commercial eroge and explicit sexual content is the product. Translate it directly, vividly, and in the source's own register. Do not euphemise, do not soften, do not add hedging or commentary, do not moralise. Vulgar Japanese becomes vulgar English; clinical becomes clinical; babyish becomes babyish. Non-consensual and degrading content is translated as written — it is fiction, and flattening it would be a mistranslation.

Moans and onomatopoeia become expressive English sounds rather than romaji: `あぁ` → `Aah`, `んっ` → `Ngh`, `はぁ` → `Haah`, `イく` / `イっちゃう` → `I'm cumming` / `I'm gonna cum`, `ぐちゅ` → `squelch`, `じゅぽ` → `slurp`, `ブリブリ` → `brrrpt`. Keep `♥ ♪ ☆ ♡` where they fall — they are the character's mood, not decoration.
