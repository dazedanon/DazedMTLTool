# SFX, onomatopoeia and moan strings

The kana strings no glossary covers: `アアッ♥`, `んほぉぉっ♡♡`, `ぐちゅ`, `ドキドキ`,
`ガーン`. In an eroge or a manga-style game these are a large minority of all units
and they break three things at once - the model leaves kana in the output, the
residual-JP validator flags correct lines, and the placeholder validator fails lines
the model legitimately restructured.

Read this alongside `references/llm-pipeline.md` (prompt rules, offline repair) and
`references/glossary-and-prompts.md` (censor masks, QA classes). Evidence pointers
are into `DAZEDTL_ROOT` as `DAZEDTL_ROOT/path:line`.

---

## 1. No kana survives into output, not even as decoration

**Every kana sound string comes out as English letters.** This is the single
highest-volume failure. On one shipped R18 run **74 of 5,056 units** came back with
small kana kept as slur decoration: `Ogh゛っ♡`, `cock milk゛ぅぅぅっ♡♡♡`. The model
is not failing to translate. It is treating the kana as *styling* on an
already-English word, so a generic "translate everything" instruction does not touch
it. The prompt rule has to name the characters and say they are **sounds**.

| Source glyph | What it is | Render as |
|---|---|---|
| `っ` `ッ` | glottal catch / cut-off | `-`, or double the following consonant |
| `ぅ ぉ ぇ ぃ ぁ` | the preceding vowel dragged out | double the vowel, or add `-h` |
| `ー` | long vowel | double the vowel |
| `゛` (dakuten, or an ASCII `"` used as one) | distortion / rasp | **may stay as-is** |
| `♥ ♡ ★ ○ ♪ ~` | tone decoration | **stay exactly, in place, same count** |

Worked examples, which belong verbatim in the prompt because register is what the
model gets wrong without them:

```
アアッ♥        -> Aahh♥
んほぉぉっ♡♡    -> Nhoooh♡♡
Ogh゛っ♡        WRONG - kana survived
Ogh゛-♡         right
```

Prompt text that recovered 68 of those 74 (`references/llm-pipeline.md`):

> No kana may survive into the output, not even as decoration. っ/ッ is a glottal
> catch, ぅ ぉ ぇ ぃ ぁ are a vowel dragged out. Render them with Latin letters -
> a doubled vowel, an -h, a hyphen - and delete the kana. `Ogh゛っ♡` is wrong,
> `Ogh゛-♡` is right. The dakuten ゛ may stay, it reads as distortion.

**Fix the last handful offline, never with a third model round-trip.** A stranded
small kana is a deterministic transliteration. Map `ぁぃぅぇぉ` to `a i u e o`,
`ゃゅょ` to `ya yu yo`, `っ/ッ` to `-` after a letter and to nothing between
decorations. **Bail out unchanged if any full-size kana or kanji is present** - that
is a real miss and must go back to the model rather than be papered over. Convert
fullwidth `！？。` the same offline way, but **leave U+3000 (`　`) alone**: inside a
moan it is a pacing gap between gasps, and collapsing it runs the phrases together.

---

### Laughs and other character sounds

Latin-letter voice spellings can preserve characterization while satisfying the no-kana rule.
Apply the live shared system prompt's "Laughs and Character Sounds" guidance in both direct and API work: a voiced `ふふ` may remain "Fufu," with distinct source forms such as `うふふ` and `おほほ` retaining their sound shape.
Preserve the source's repetition, breath, pauses, and intensity without assigning a fixed emotion to a spelling.
This does not authorize leaving ordinary Japanese words untranslated or romanizing all SFX.
Distinguish audible laughter from narration about laughing and from an ambiguous breath or movement sound.
Dictionary hints such as "chuckle," "smirk," or "heh" describe possible meanings; they must not override the current source or erase a distinctive voiced laugh.
Store recurring speaker-specific choices in the existing character glossary and preserve them during polishing and review.

---

## 2. Censor masks stay masked

`〇` (U+3007) and `●` standing in for a word are a **deliberate authorial choice**,
not damage and not residual Japanese.

```
ま〇こ  -> pu〇sy      (not "pussy", not "ma〇ko", not "pu○○y" with the count changed)
うん〇  -> sh〇t
●●●     -> ●●●        (a character named by mask keeps the mask)
```

Two consequences, both needed or the pipeline fights itself:

- Say it in the prompt. Without an explicit rule the model "helpfully" uncensors.
- **Exclude U+3007 and `●` from the residual-JP validator class.** Flagging them
  sends correct lines to a retry that can only reproduce them. Keep `々` `〆` in the
  class - those are real Japanese marks that should not survive.
- **Then add the check that exclusion removes.** Once masks are whitelisted, no
  check looks at them at all, in either direction. Compare their PRESENCE:

  ```python
  bool(MASK.search(u["src"])) != bool(MASK.search(u["tl"]))   # -> flag
  ```

  On a finished corpus, 7 of 11 mask-bearing units failed that: **4 invented** a
  mask the author had not used - and inconsistently, since the same word was
  unmasked in 7 of its 8 other appearances - and **3 dropped** one the author
  had (`レイ〇` spelled out in full). Neither is visible to a residual-JP check,
  a placeholder check or a length check. Mirror position too where the word
  allows it: `レイ〇` -> `r〇pe`, not `rape` with a mask bolted on the end.

---

## 3. Validator interactions: where SFX produces false failures

SFX lines trip three checks that are correct everywhere else.

| Check | Why SFX breaks it | Fix |
|---|---|---|
| Residual Japanese | censor glyphs `〇` `●`, and a `"`/`゛` slur mark | whitelist those glyphs, keep `々〆` flagged |
| Placeholder set integrity | the model legitimately **restructures** a moan, reordering or merging fragments around a sentinel, so count/identity/order shift | compare placeholder **multiset**, not order, and demote a mismatch on an SFX-classified unit to a soft warning (`DAZEDTL_ROOT/util/translation.py:522`) |
| Identical-to-source | `♥♡` -only or `……` -only units are correctly unchanged | exempt units with no kana and no kanji |

Also expect the JSON parser to choke here specifically: the JP source uses an ASCII
`"` as a dakuten on slurred moans (`あ"っ`) and the model carries it into English
(`"...enjoy the show? Aa"♥"`). Repair rule in `references/llm-pipeline.md` - a `"`
only *closes* a value when the next non-space character is `,` `}` or `:`.

Soft warnings worth keeping, not blocking: leftover cosmetic `っ/ッ/・`, punctuation
drift, over-expansion above 3-6x.

---

## 4. Split by class: closed-class erotic kana in the static prompt, open-ended manga SFX in a dictionary

The two sets have different sizes and different economics, so they ship differently.

**Erotic onomatopoeia is a small closed class. Hardcode it in the always-on system
prompt.** A general manga corpus does not cover it. Audited against j-ono (660
entries), `くちゅ` `あん` `はぁ` `ドキドキ` `ガーン` are present but `ぴちゃ` `ぐちゅ`
`じゅぽ` `ぬぷ` `くぱぁ` `ずぷ` are **all absent**, and `んっ` and `いく` are missing
as variants. Those are the highest-frequency strings in an H-scene. Do not extend
the dictionary for them - put them in the cached static block, where they cost
nothing per batch (`DAZEDTL_ROOT/data/skills/system.md:84`):

```
ぴちゃ, ぐちゅ, じゅぽ, くちゅ, ぬぷ, くぱぁ, ずぷ, etc.
  -> equivalent evocative English sounds or descriptive phrases
あぁ, んっ, はぁ, ふぁ, いく, イっちゃう, イくっ
  -> "Aah...", "Ngh...", "Hah...", "I'm cumming...", "I'm gonna cum..."
```

Worked outputs matter more than the kana list. Without a target register the model
picks a clinical one.

**Manga SFX is open-ended. Match a dictionary against the batch and send only the
hits.** Sections 5 to 7.

---

## 5. Dynamic SFX dictionary: match-then-send, never ship the whole thing

A usable corpus is 450 KB (j-ono: 660 entries, 3,595 kana variants, 837 senses).
Pasting it into every prompt is unaffordable and long enough to bury the actual
source lines.

**Index and match** (`DAZEDTL_ROOT/util/sfx_reference.py`):

- `by_initial: dict[first_char -> list[(variant, entry_order, entry)]]`.
- Sort each bucket by `(-len(variant), entry_order, variant)` so the **longest
  spelling wins at any position**. Without this you gloss `ドキ` ("thump") on a line
  that reads `ドキドキ` ("heart pounding").
- Scan NFKC-normalized text position by position: look up the bucket for
  `text[pos]`, take the first candidate where `text.startswith(variant, pos)` and the
  boundary test (section 6) passes, record it, set `pos = end`.
- NFKC on both sides means half-width katakana `ﾄﾞｷﾄﾞｷ` matches `ドキドキ` for free.

**Caps, and why each one exists** (`DAZEDTL_ROOT/util/sfx_reference.py:20`):

```python
MAX_MATCHED_ENTRIES     = 12   # return early on hit. one moan-heavy H-scene batch
                               # otherwise floods context with 60 near-identical entries
MAX_DISPLAY_VARIANTS    = 8
MAX_SENSES_PER_ENTRY    = 6
MAX_EQUIVALENTS_PER_SENSE = 8
```

Dedup by entry id. Put **the spelling that actually matched first** in the variant
list so the model sees its own hit at the head:

```
- ドキドキ / どきどき / ドキンドキン
```

Cache the whole-file load (`lru_cache` keyed on the resolved path). On a missing or
malformed dictionary **return `""` and translate without it** - a reference-data
problem must never fail the run.

---

## 6. Boundary rules are asymmetric: hiragana must be isolated, katakana need only a non-katakana neighbour

Hiragana SFX spellings collide with ordinary grammar. The j-ono entry `する` (a
rustling sound) matches the verb `する` inside `勉強する`, and with no boundary rule
the model starts rendering ordinary verbs as sound effects
(`DAZEDTL_ROOT/util/sfx_reference.py:65`).

| Variant shape | Regex | Rejected when |
|---|---|---|
| pure hiragana | `^[ぁ-ゔー]+$` | either neighbour is **any Japanese text char**: kana, `一-龠`, or `ー々〆〤` |
| pure katakana | `^[ァ-ヴー]+$` | either neighbour is **katakana or `ー`** only |
| mixed script | - | never, accept unconditionally |

So `どきどき` matches in `どきどき……` but not in `どきどきしている`, while `ドキドキ`
still matches inside `胸がドキドキする` where hiragana surrounds it.

**Drop any variant with a kana count <= 1 before it enters the index, and do not
count `ー` as kana.** That kills `あ`, `ん`, `あー`, `うー` - 154 of j-ono's 3,595
variants. Keep them and `あ` matches essentially every line of dialogue in the game,
making the SFX block pure noise on 100% of batches.

---

## 7. Frame the SFX block as suggestion, deliberately unlike the glossary

Same request, opposite contracts. The glossary block opens `Here are glossary
entries with the approved spelling and translation. ` The SFX block opens with the
reverse (`DAZEDTL_ROOT/util/sfx_reference.py:245`):

```
Japanese SFX reference (contextual suggestions, not approved fixed translations).
Choose the sense that fits the scene and render it naturally in the requested target language.
The English equivalents below are semantic hints, not required output wording.
```

Give SFX glosses glossary-style authority and the model locks onto the first
equivalent, so every `ドキドキ` in the game becomes the same word.

- **Keep every sense of an ambiguous entry** rather than picking one. 124 of 660
  j-ono entries are multi-sense, up to 6. That is what lets `ガーン` be a shock-thud
  on one line and a despair-sting on the next.
- **Spell the kind label out.** A bare type letter teaches the model nothing.
  Expand `o=sound, v=voice or vocal sound, s=state or condition, m=motion or
  movement, e=emotion or feeling, c=visual or meta cue`:

```
  - equivalents: ah, oh; meaning: surprise, recognition, or realization; kind: voice or vocal sound
```

- **Exclude the dictionary's romaji field even when the snapshot carries it.** Showing `dokidoki` invites the model to transliterate instead of localize.
  This keeps generic dictionary readings out of the hints; it does not forbid expressive voice spellings selected under "Laughs and other character sounds" above.
- Say **"the requested target language"**, not "English". The shipped glosses are
  English while the target may not be.

---

## 8. Building the bundled snapshot: five transforms, then pin it

Never ship the raw upstream JSON. Each transform below corrupts the prompt if
skipped (`DAZEDTL_ROOT/scripts/update_sfx_reference.py:46`).

1. **Resolve `refer` chains.** A definition may carry `"refer": "<other_id>:<1-based-index>"`
   and inherit that record's equivalents, meanings and type. Recurse, passing a
   `stack` tuple so a cyclic reference **raises instead of hanging**. Skip this and
   every refer-chained entry ships with no glosses at all.
2. **Strip the `"s"` same-marker.** Some records use the literal one-letter meaning
   `"s"` as an internal "same as above" marker. Blank it, or you send
   `meaning: s` to the model.
3. **Order variants hiragana-first**: `variants = hiragana + [k for k in katakana if k not in hiragana]`.
4. **Validate `type` against the closed set `{o,v,s,m,e,c,""}`** and make an unknown
   letter a hard error, not a silent pass-through.
5. **Drop senses with neither equivalents nor meanings**, and raise on a record left
   with zero senses.

Pin what you converted. Embed `source.sha256` of the raw upstream bytes plus the
pinned revision, and hard-fail the loader on `schema_version != 1`. That is how you
detect an upstream revision drifting under you.

```
Upstream revision: 673f9f51651122e89948f5ef25794c78efe29f50
Upstream path:     json/j-ono-data.json
Upstream SHA-256:  d8f10a6399c39c64a92a0427975b00e3210e9c2d779711818493d3b02db95b84
License:           MIT
```

**Exclude the manga example metadata and images entirely, and assert `"example"`
never appears in the shipped file.** That is the license boundary - only the JSON is
MIT.

---

## Symptom index

| Symptom | Section |
|---|---|
| `Ogh゛っ♡`, `milk゛ぅぅぅっ♡♡` in output | 1 |
| `♥` count changed or moved | 1 |
| gasps run together after fullwidth cleanup | 1 (U+3000) |
| model uncensored `ま〇こ` | 2 |
| residual-JP flags a correct line | 2, 3 |
| placeholder mismatch on a moan line | 3 |
| JSON parse fails on `Aa"♥"` | 3 |
| `ぴちゃ` / `ぐちゅ` shipped untranslated | 4 |
| `勉強する` rendered as a sound effect | 6 |
| SFX block appears on every batch and is useless | 6 (kana count <= 1) |
| every `ドキドキ` in the game is the same English word | 7 |
| entry ships with no glosses | 8 (`refer`) |
| `meaning: s` reaches the model | 8 |
