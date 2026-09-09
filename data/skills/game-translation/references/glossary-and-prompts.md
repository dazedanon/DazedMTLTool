# Glossary & Game Bible Design

The glossary is the **contract** that keeps names and terms from drifting.
In DazedTL, `.dazedtl/glossary.txt`, `.dazedtl/skills/game.md`, `.dazedtl/skills/quirks.md` and custom skills own those decisions. The live shared context compiler assembles them for every request. Preserve hand-edited guidance. Historical JSON and bible examples below explain the source pipelines; adapt them to the shared ownership contract.
This is the single highest-leverage part of a good translation.

Reference examples on disk (copy the closest genre), all under `tools/Game Translation/Reference Pipelines/` (= `RP/`):
- `RP/SRPG Studio (Belphegor)/tl/` - gold standard, 500+ char cast, gender corrections, alias merges, SRPG terms.
- `RP/Unreal (FortuneBride)/tl/` - mid cast, mental-state system, adult eroge register.
- `RP/Unity Mono (NTR Soccer)/tl/` - small slice-of-life cast, keeps honorifics.
- `RP/RPG Maker MVMZ (BroodGeneral)/tl/` - RPG Maker, Claude-batch style.

## Which file owns which rule in DazedTL

| File | Owns | Keep elsewhere |
|---|---|---|
| `.dazedtl/glossary.txt` | Names, gender or uncertainty, roles, individual register, identity/reveal scope, world terms | Global voice and tool configuration |
| `.dazedtl/skills/quirks.md` | Cross-cutting voice and recurring motifs with literal Japanese anchors | Individual biographies, one-off jokes, layout numbers |
| `.dazedtl/skills/game.md` | Compact theme, era, register policy, naming policy, evidenced mythology | Cast lists, duplicated quirks or glossary entries |
| Other `.dazedtl/skills/*.md` | User-chosen, narrowly scoped translation instructions | Pipeline implementation and research inventories |
| `.dazedtl/len-method/work/` notes | Longer synopsis, routes, research, extraction metadata, QA evidence | Another authoritative copy of the glossary or translation prompt |

Use the shared Setup skill and its investigation phase before finalizing guidance.
`DAZEDTL_ROOT/scripts/len_translation.py context` refreshes the current assembled
instructions; `--sources` adds the same matched glossary, SFX and reference evidence
used by DazedTL. These are the inputs to adapted drivers, so a sample pipeline's prompt
builder must not silently override them.

## Historical glossary.json schema (import once)

```json
{
  "meta": { "game": "...", "source": "how it was built", "note": "design intent" },
  "names": {
    "<JP name / name-box string>": {
      "en": "English name",
      "gender": "male | female | unknown",
      "role": "one line of story context (disambiguates similar names)",
      "register": "voice cues: particles, formality, verbal tics (わらわ/じゃ, 俺/だぜ, keigo, っス...)",
      "aliases": ["other JP forms that map to the SAME english name"],
      "note": "concise identity/voice evidence and traps (included in shared glossary context)"
    }
  },
  "terms": { "<JP term>": "<locked EN term>" },
  "do_not_translate": [ "dev warnings", "binary garbage", "markup tokens", "asset ids" ]
}
```

### Name entry = a 5-field lock

1. **en** - the one English spelling used everywhere.
2. **gender** - drives pronoun resolution (JP omits pronouns, so the model infers 彼/彼女/こいつ from this field). **Correct it even when the name misleads** (a male "Gina", a male "Gloria") and record supporting dialogue in the glossary note.
3. **role** - story context so the model does not conflate two similar characters.
4. **register** - the character's DNA: specific particles, formality, tics. This is what makes voices distinct across thousands of lines.
5. **aliases** - JP spelling variants that use the same public English identity. Keep anonymous, disguised and pre-reveal identities in separate named entries with their own surface spellings. Also explicitly record pairs that are **distinct and must NOT merge** (e.g. "Baigou" vs "Baigou Khan").

`register` and `gender` are not decoration and are not interchangeable.
A character whose register contradicts his gender needs BOTH fields plus a concise `note`. The shared compiler includes that note with the matched glossary row; keep it here instead of repeating it in the game frame or bible.

**Register-gender trap, real case.**
ルイ/Louis is the troupe captain, a **man**, who speaks in an entirely feminine register: あたし, 〜かしら, 〜わよ, drawn-out エステルちゃ〜ん.
The narration uses 彼 for him.
Without an explicit note the model renders him as a woman on every single line.

```json
"ルイ": {
  "en": "Louis", "gender": "male", "role": "captain of the troupe",
  "register": "feminine register despite being male - あたし, 〜かしら, 〜わよ, drawn-out エステルちゃ〜ん",
  "note": "MALE - the narration uses 彼 for him. Use he/him while keeping the flamboyant, camp voice."
}
```

**Withheld-identity trap, same game.**
ハイメ/Jaime the jester **is** レオン/Leon, a runaway heir, and the game withholds this until a late reveal.
Both names stay distinct rows and neither may be normalised into the other.
A glossary that merges aliases by default spoils the reveal in the first scene the jester speaks.
Any alias-merge automation needs an explicit `do_not_merge` list, and the bible repeats it in prose under Name-box notes.

Auto-seed genders and roles with `tools/Game Translation/Text QA and Glossary/autofill_glossary.py` (speaker-name keyword heuristics: 兵士=Soldier/Male, 王女=Princess/Female, plus dialogue gender markers - male 俺/僕/だぜ/お前/てめえ, female あたし/わよ/だわ/かしら/のよ), **then hand-correct**.
Heuristics are a starting point, not truth, and Louis above is exactly what they get wrong.

### Nameplate lookup keys: NFKC, OCR lookalikes, and a honorific whitelist

**Expand every nameplate into an ordered list of lookup keys before deciding a name is new.**
Include each slash alias, its NFKC normalization so full-width `コア1Ａ` matches the curated `コア1A`, a kanji-to-katakana lookalike swap (`二` -> `ニ`, because that kanji is a common font and OCR stand-in on nameplates, so `二ーナ` resolves to `ニーナ`), and the honorific-stripped base.

**Strip only `様|先生|博士|君`, anchored at the end, repeatable.**
Never strip `さん`, `ちゃん`, `氏` or `殿`.
They are lexicalized into real words, and stripping them collapses `おじさん` onto a curated `おじ (Uncle)` row and `源氏`/`御殿` onto `源`/`御`.

Filter collected speaker names through these keys before any model call.
A preflight over `["コア1Ａ", "二ーナ", "クィーン"]` against a glossary already holding the curated forms must make **zero** calls and leave the glossary file byte-identical.
For a slash row such as `ニーナ / ネーナ・エヴァンス (Nena Evans)`, register both aliases, give the short alias the short gloss `Nena` while the long alias keeps `Nena Evans`, carry an English title only when the source alias carries one (`ニーナ様` -> `Lady Nena`, plain `ニーナ` -> `Nena`), and protect surname particles so `ヴァン` against `van Helsing` does not collapse to `van`.
Without this, every font variant of a name becomes a new glossary row with its own model-invented spelling and one character ships under three English names.

### Disputed spellings: six-tier evidence hierarchy

Score a contested name highest tier first.

1. Trustworthy creator statement or an in-game Latin spelling.
2. Corpus structure and demonstrated naming-family morphology.
3. Attested lexical or proper-name candidates in plausible source languages.
4. Independent lore convergence, including explicit wordplay or callbacks.
5. Kana phonetics, with the EXACT mismatch stated per candidate.
6. A conservative naturalized fallback, explicitly labeled editorial.

**Repeated nameplates, database fields and self-introductions establish identity and segmentation only and say nothing about Latin orthography.**
Do not validate a spelling because every occurrence inherited the same provisional guess - that is exactly what a machine-generated known-speakers block produces across a whole corpus.
Related lines from one role, motif, institution or scene premise count as ONE evidence class, not many.
Decide each component of a multi-part name independently: a common-noun reading supported only by one matching trait, dictionary existence, phonetic fit, or a language inferred from the other component is weak and loses to the conservative naturalized reading, but stays eligible and wins when independent signals converge.
An attested proper name is a conservative candidate, not an automatic winner, and a minor transcription irregularity is contrary evidence rather than a veto.
When it is close, keep the conservative reading and backlog the exact missing evidence - names are unrenamable once a patch ships and players learn them.
Naturalize for English rather than transcribing every kana mora.
For a confirmed faux-name or name-based joke, the English target itself must carry the joke unless adaptation would distort identity or tone. Leaving the wordplay only in the description is a defect.

### terms = consistency lock

Map every recurring game-specific noun to a fixed English string: mechanics (`三すくみ`=weapon triangle, `特効`=effective damage), items and skills, proper nouns and place names (fixed Hepburn), and genre vocabulary.
Without this the model says "Bride Candidate" in one scene and "Candidate Bride" in the next.
For adult games, lock the explicit terms too (`中出し`=creampie, `調教`=training, `媚薬`=aphrodisiac) so register stays consistent and blunt.

### Base glossary: ~85 reusable rows before any game-specific work

The same four classes are wrong in every ungoverned MTL patch.

1.
**Honorifics as an anti-translation list.** `さん (san)`, `様/さま (sama)`, `君/くん (kun)`, `ちゃん (chan)`, `たん (tan)`, `先輩/せんぱい (senpai)`, `先生/せんせい (sensei)`, plus kana and kanji spellings of nii-san and nee-san.
Put the deliberate exceptions in the same block so the model does not over-romanize: `兄者 (elder brother)` and `おじさん (old man)` are glossed to English because they are not honorifics in English usage.
2. **RPG Maker stock database and UI strings**, matched to RPG Maker's own official English so the UI does not read half-localized: `初めから (Start)`, `逃げる (Escape)`, `大事なもの (Key Items)`, `最強装備 (Optimize)`, `最大ＨＰ (Max HP)` with the fullwidth `ＨＰ`, `魔力攻撃 (M. Attack)`, `ME 音量 (ME Volume)`. Add the format-string row `%1 の%2を獲得！ (Gained %1 %2)`, which teaches placeholder **reordering** by example.
3.
**Ambiguity clusters that all collapse to one English word under MTL.** `悪魔/魔神/魔人 -> Demon/Devil/Demon`, `淫魔/夢魔 -> both Succubus`, `幽霊/幽鬼 -> Ghost/Revenant`, and the celestial hierarchy `権天使/能天使/力天使/主天使/智天使 -> Principality/Power/Virtue/Dominion/Cherub`, which no model produces reliably from the kanji alone.
Pin enemy type labels the same way: `人型 Humanoid`, `獣型 Beast`, `触手型 Tentacle`, `軟体型 Slime`, `虫型 Insect`.
4. **Damage elements and the `M.` abbreviation convention.**

**Append the base below a sentinel line at read time instead of copying it into the project file.**
Read `<game>/.dazedtl/glossary.txt`, keep only the text ABOVE the separator as the user's section, and re-append the currently shipped base below it:

```
# ── Base Glossary (auto-appended from glossary_base.txt - do not edit below) ──
```

Without the sentinel, refreshing the shipped base either duplicates 87 rows into every project glossary on each run or silently overwrites character entries the user spent hours curating.
With it, a base updated between releases propagates to every existing project, and the per-batch matcher treats base and custom rows identically.
**Provide a per-project opt-out** (an env flag where any of `{0,false,no,off}` returns only the custom half), because the RPG Maker rows are wrong for a non-RPG-Maker game where `逃げる (Escape)` would be a mistranslation.
Seed an empty project with a `# Add character glossary entries here` placeholder above the separator, and return the base alone when no project glossary exists yet.

## Game bible research and the compact translation frame

Older pipelines kept a large `game_prompt.md` with premise, routes, tone, cast and
mechanical rules. For DazedTL, keep longer premise/route research in workspace notes.
Promote confirmed translation decisions into their single owned guidance file above.
Do not repeat the cast, term locks or quirks inside `game.md`; use its compact frame.
Document when a term is already printed on translated images and review those assets
when changing that glossary decision.

## Historical driver prompt shape (use the shared compiler in DazedTL)

```
You are a professional JP->EN game localizer. Translate the given Japanese strings into
natural English following the game bible and glossary EXACTLY.

{system from the shared DazedTL context compiler}

## Glossary - names (use these spellings, never romanize differently)
- <JP> => <EN> (<gender>; <role>) voice: <register>
...
## Glossary - terms (always translate consistently)
- <JP> = <EN>
...
## Do not translate
- <do_not_translate entries>

## Output format
Return ONLY a JSON object: {"t":{"<id>":"<english>",...}} with one entry per input id.
Rules:
- Natural, concise; UI labels terse.
- Preserve markup exactly: <engine-specific tokens>, \n, leading/trailing whitespace.
- Keep （） inner monologue; ♥♪ flavor (ASCII ! ? ... fine).
- Never output Japanese characters in translations.
- Do not add quotes, speaker names, or notes not in the source.
```

### Send the MATCHED glossary slice, never the whole glossary

Match the glossary against the current request text and send only the hits, regrouped under their original category headers, prefixed with `Here are glossary entries with the approved spelling and translation. `

Matching must be **script-aware, not substring**.
Build a negative-lookaround pattern from the term's own script class, so a pure-katakana term gets:

```
(?<![ァ-ヴーｦ-ﾟ])キス(?![ァ-ヴーｦ-ﾟ])
```

and `キス` stops firing inside `テキスト`.
Give pure-hiragana and pure-kanji terms the same treatment against their own class (`火` inside `火曜日` is the kanji case) and fall back to plain substring only for mixed-script terms.
Naive substring matching floods the prompt with irrelevant approved terms that cost tokens and actively mislead.

- **Match against the current batch only and deliberately exclude conversation history**, or terms from three batches ago get resent and produce spurious terminology in unrelated scenes.
- Split the source side of an entry on `,` and `、` so one row `様, さま (sama)` covers both spellings.
- When the payload is JSON, reduce it to its string **values** before matching (strip the ```json fence, `json.loads`, collect strings) so structural keys like `Line1` never trigger a hit.
- Parse rows with `^(.+?)\s*\(([^()]*)\)` capturing only the FIRST paren group, so a rich row like `サンク (Sank) - Male; protagonist...` still keys on `Sank`. Fall back to `^(.+?)\s+[–-]\s+(.+)$`, then to a bare line.

### The user turn is two labelled, separately fenced blocks

```
Request Instructions:
<per-field-type template>

Preceding Japanese Source Context (untranslated):
<previous chunk's SOURCE lines>
Use these lines only to understand the scene. Do not copy Japanese spellings from them
or treat them as approved terminology; the glossary is authoritative.
```

**Rolling context is the previous chunk's SOURCE, never prior translations.**
Live translations and fetched batch results overwrite the working list in place, so `previous_chunk[-maxHistory:]` read from the live list feeds chunk N+1 the ENGLISH output of chunk N.
Snapshot before any chunk is mutated (`source_batches = [list(item) for item in tList]`) and slice history from the snapshot.
Feeding back your own output compounds drift and lets one early mistranslated name propagate through a whole file.
The same rule covers attached constructs: pass the ORIGINAL Japanese question as context for its choices, never the translation you produced a moment earlier, or one bad rendering compounds into five.

Closing the source block with the demotion sentence is mandatory.
Without it the model lifts untranslated kanji straight out of the scene context into its output, which is the classic "half the line came back in Japanese" failure.

**Per-call instructions ship in EVERY chunk. Only the source history rolls forward.**
Bundling the directives into the history slot means chunk 1 of every file silently loses them and comes out in a different style.
Keep per-field instructions out of the system prompt entirely or they bust the prompt cache on every field type.
Hash the two halves independently into the cache key.

### Instruction templates encode output SHAPE, and double as micro-glossaries

One template per field type, because a name field that comes back as a sentence corrupts the data file.
The speaker-nameplate template needs four constraints in one string, and the transliterate clause is what stops `ハル` becoming "Spring":

```
Reply with only a short {language} dialogue nameplate for this speaker (e.g. Clerk, Townsman,
Electrician). Translate occupational or generic labels normally. For a proper name, transliterate
it; do not turn it into a common {language} word based only on its sound. Prefer 1-3 words with
title capitalization. Never write a sentence, role description, or explanation.
```

Key length-sensitive templates to the engine construct: `Keep your translation as brief as possible` for RPG Maker code 122 strings, `This text is a label. Use title capitalization and keep it brief. ` for code 108 comments.
**Use the instruction slot as a targeted mini-glossary for stock strings the term matcher cannot catch as whole phrases** - the battle-messages template carries `Translate 常時ダッシュ as Always Dash` and `Translate 次の%1まで as Next %1` inline.
Add `No disclaimers. ` on field types where the model editorializes.
Budget roughly 27 keys for a full RPG Maker run: `names.npc/speaker/enemy/location`, `database.item/weapon/armor/class/skill/note/type_*/element/ui_term/game_title/switch/battle_messages`, `events.choice/choice_with_context/code122_brief/label_108/generic_text`.
Store them as a two-level `section.key` map addressed as `ctx("events.choice")`, fill `{language}` from config and other `{placeholders}` from kwargs, and **raise KeyError on an unknown section, key, or missing placeholder rather than degrading to an empty instruction** - a silently blank instruction produces a plausible-looking wrong-shape answer.
Cache the template file by mtime so edits take effect without a restart.
Sending one generic "translate this" for a skill name, a 40-char UI label and a paragraph of dialogue is why patches ship menu buttons reading "The Strongest Equipment Set".

### Rules a default prompt gets wrong

Each of these is a failure a strong model produces confidently.

- **No source-language residue, even when the line is explaining a Japanese word.** `Apparently, 鉱山 is called "Mine" in English` is wrong. Paraphrase the word being glossed.
- **Verify grammatical person from the source before writing.** Second-person address (お前/君/あなた) and third-person narration get flipped into first-person dialogue routinely.
- Characters who refer to themselves by name keep that third-person self-reference in English.
- Interpret discourse and stance markers (なかなか, ～っぽい, じゃん) together rather than mapping each to a standalone English meaning, and never let them become unsupported claims about skill, habit, frequency or progress over time.
- Resolve コイツ/あいつ/こいつ by the referenced character's glossary gender.
- A `=` or `＝` inside a Japanese name marks a foreign or nickname component, wrapped in parentheses: `バンカー＝ベット` -> `Bunker (Bet)`.
- Speaker tags are always translated: `[クロネ]:` -> `[Kurone]:`.
- `__PROTECTED_0__`-style tokens keep their relative position between the translated equivalents and are never reordered or dropped. `\cself` is a runtime substitution that stays in place untranslated. The literal string `Placeholder Text` is left untouched wherever it appears (the inverse of the QA scan for translations that ARE the bare word `placeholder`).

### Layout clauses that earn their place

- **Same number of lines as the source.** State *why* ("these go into fixed-size boxes"), and that the break should fall at a phrase boundary with roughly balanced lines. The model complies ~93% of the time. Fix the rest deterministically (`references/text-fitting.md`) rather than re-prompting.
- **A full-width space (`　`) inside a line is a pacing gap, not indentation.** Render it, do not delete it and run the phrases together. A run of them centring a heading is layout, so keep comparable spacing.
- **Censor masks are MIRRORED, not just preserved - and the check has to run in both directions.** `うん〇` -> `sh〇t`, a name written `●●●` stays `●●●`. Say so, or the model "helpfully" un-censors. But "preserve the mask" is only half a rule, and a validator built from that half is blind to the other: a mask is the AUTHOR's editorial decision, so the English carries one exactly where the Japanese does **and nowhere else**. On a finished corpus that read as 100% translated with zero hard failures, 7 of the 11 units touching a mask were wrong - **4 invented** (the author wrote the word plainly and the model masked it anyway; the same word is unmasked in 7 of its 8 other appearances, so it was not even self-consistent) and **3 dropped** (the author masked `レイ〇` and the English spelled it out). Compare `bool(MASK.search(src)) != bool(MASK.search(tl))` as a standing check; it is two lines and it catches both. Adding a mask softens what the author wrote plainly, which is the same failure as euphemising; dropping one spells out a word they deliberately did not.
- Asking for brevity up front is weaker than a targeted shortening pass afterwards with the real per-unit budget in lines x cells. Translate for quality first, then tighten only what actually overflows.

The user prompt lists `id (note): "JP text"` lines under a batch header describing the scene or category.

### Caching: fingerprint the MATCHED glossary, not the whole file

Live cache key:

```
md5(f"{payload}|{language}")
  + f"|context:{sha256(cache_context)}"      # only when non-empty
  + f"|request:{sha256(normalized_request_context)}"
```

`cache_context` is the vocab text built from entries actually matched in THIS payload plus the matched SFX reference, so editing an unrelated glossary row invalidates nothing and a payload matching no entry keeps its legacy key.
Make the request context a typed document `{"instructions": [...], "source_items": [...]}` serialized with sorted keys and compact separators, so a dropped directive and source text masquerading as model output each change the key independently.

**Exclude the glossary from async batch identity entirely.**
A two-phase run writes newly harvested names into the glossary between collect and consume, so a glossary-sensitive batch key orphans every result already paid for.
Bump a `BATCH_CACHE_KEY_VERSION` and make batch queue and result identity payload plus language plus request context ONLY.
The live cache fingerprints the matched glossary. The paid batch identity does not.

**Never cache a speaker translation that failed validation, and make "unchanged" language-dependent.**
For a Chinese target accept any output with no Japanese-only kana `[ぁ-ゖァ-ヺーｦ-ﾟ]`, so `騎士` -> `骑士` passes while `セルリア` -> `セルリア` is rejected.
For a Japanese target accept anything.
Otherwise require `casefold()` inequality with the source AND no residual Japanese.
On failure, retry twice, return the source name, and **do not write it into the speaker cache** - a cached failure pins the Japanese name for the rest of the run and then into the glossary.
An exact glossary hit short-circuits both the model and a stale cache entry: a seeded cache entry `ユウ -> Yu` still loses to a curated `# Game Characters` row giving `Yuu`, with zero model calls, and a curated row outranks a generated `# Speakers` row for the same name.
During a batch collect or consume phase, return the source name with no live call at all - a synchronous request there costs money outside the batch discount and can deadlock the state machine.

## An entity nothing pins WILL drift, and gender is invented

Every name the glossary does not pin is translated independently in each batch,
and the batches disagree. This is not a model failure to fix with a better
prompt - it is a missing input.

A shipped game had **おろち様**, an unseen deity mentioned in 233 units and
present in neither `names` nor `terms`. It came out as "Orochi-sama" in 98
units, "Lord Orochi" in 91 and "Lady Orochi" in 28 - and, worse, with masculine
pronouns in 44 and feminine in 29, so a player met "him" before the boss and
"Lady ... herself" afterwards. In the same corpus **ホーリールーン** was "Holy Rune" in
79 units and "Holyrune" in 15.

**Japanese does not mark gender, so the model supplies one.** That corpus used
彼/彼女 for the deity exactly zero times across all 46 distinct lines,
and the plot turns on nobody ever having seen it. Every "he" and "she" was
invented, and each one deflated the reveal. For any entity the source leaves
unmarked - a god, a voice, an unseen villain, a narrator - put the rule in the
bible explicitly:

> おろち様 is "Great Orochi", and has NO GENDER. Do not write he, him, his, she
> or her for it - rephrase ("that god's wrath", "we'd never be shown that
> form"). Guessing invents information and deflates the reveal.

Note what that costs: **every localized honorific in English is gendered**.
Lord and Lady both assert something the source does not. If the patch localizes
honorifics (エリス様 -> "Lady Eris") then a neutral one has to be found rather
than defaulted to - "Great X" works for a deity - or the honorific is kept in
romaji as the single documented exception. Decide it once, in the bible.

**Catch it before spending.** A pre-flight pass over the extracted source costs
nothing and lists exactly what to pin: count the recurring proper nouns that no
glossary section covers - names addressed with 様 (minus kinship and rank,
which are vocabulary), plus katakana runs of four or more characters - and
report any appearing in more than ~20 units. On the finished game this reported
17 candidates, of which five were real names; pinning them is a minute's work
and it is the only thing that stops the drift at the source.
`validate.unpinned_terms` in the reference pipeline is that pass. It pairs with
the post-hoc check: one Japanese string rendered two ways across the tracks.

## Two-phase name translation

1. **Phase 1** - translate only the character names (`{"1":{"en":"...","gender":"male|female|unknown"}}`) and write results back into `glossary.json`.
2. **Phase 2** - translate dialogue and UI with the now-complete glossary in the (cached) prompt.

This guarantees a name embedded in prose ("...told Belphegor...") matches the name box.
Skip it only if the glossary is already fully hand-authored.

## A phrase split across concatenated fragments is ONE unit of meaning

`f.livestatus + f.day + '日目'` renders as `同居3日目`.
Extracted as three literals and translated independently it came back as **"Living Together1 together"** - each fragment defensible alone, the sentence nonsense.
Same shape as RPG Maker's `\v[1]` mid-sentence, Unity `string.Format` parts, or any runtime-concatenated label.

- **Show the model the whole expression** as context and mark which fragment it is translating, so the piece fits where the neighbours put it.
- **Allow a fragment to translate to nothing.** Japanese counter suffixes usually have no English counterpart: `同居` + N + `日目` is simply "Day N", so `日目` correctly becomes `""`. The store must distinguish **untranslated** (`None` - keep the Japanese) from **deliberately blank** (`""` - inject nothing), or validation flags the correct answer as a missing translation forever. Give it a distinct status and count it as done.

Expect to hand-fix a few anyway. They are rare and glaring on screen.

## Battle-log fragments need a dummy subject

`Skills.json` and `States.json` `message1`-`message4` are sentence fragments the engine prepends the actor's name to.
A bare `は触手を伸ばした！` gives the model no grammatical subject and produces garbage.
Prepend `Taro`, translate, then scrub **unconditionally, whether or not the placeholder was injected**, because it bleeds through from the model's own output even on sources that never got one:

```python
re.compile(r"\bTaro(?:['’]s)?\b", re.IGNORECASE)   # Taro, taro, TARO, Taro's
```

Then collapse runs of 2 or more spaces and strip leading and trailing spaces, tabs and quote characters, so both source shapes land on `extended a tentacle!`.
A leaked placeholder ships as `Alice Taro extended a tentacle!` in the battle log, which appears only in combat and survives every text-only review pass.

## Dedup strategy

- **Dialogue and scene info text** - stored **per scene**, grouped by event page, **NOT deduped**. The model needs a coherent run with speakers for pronoun and tone continuity. IDs like `map_000:<scene>:c3`.
- **Everything else** (names, descriptions, UI labels, item and skill names, battle conditions, menu text) - **globally deduped**: one unit per unique JP string, injected to every occurrence. Translate `回復` once, every copy updates.

## Review a displayed term with its gameplay consumers

For a disputed skill, objective or numeric help line, read the shared name,
action text, state/help entry and event condition together. Tropical Chase's
eye attack explicitly used sand, making "Blind" more accurate than "Eye Gouge";
"out of sight" missed a persistent chasing condition; a collectible achievement
also required clearing the game. Review the whole family after correcting one
member. Match tutorials to the menu labels the player actually sees.

When help contradicts executed behavior, prove the branches before recording a
source correction. Here a drink's stated "50" meant a 50% recovery across
several stat maxima. Correcting the help did not authorize changing the recovery
formula. Keep such corrections and exact mistaken nameplate sites in a separate,
source-guarded ledger rather than a broad number-drift waiver or speaker rule.

## QA / validation patterns

Automatic (block injection): completeness, residual-JP (`[぀-ヿ一-鿿]` in output), placeholder-set integrity, byte and width limits.
Soft (review): misgender, over-expansion, stranded kana (っ/ッ/・), punctuation drift.

Two exclusions worth hardcoding.
**`〇` (U+3007) and `●` are censor glyphs, not residual Japanese** - they are supposed to survive.
A **trailing `\r`** in a CSV cell is not an extra line, so normalise CRLF and drop one terminator before counting, or correct 2-line translations get flagged as collapsed.

Cheap scan worth adding: translations that are literally `placeholder`, `TODO`, `N/A`.
They pass every hard check (English, not identical to source, placeholders intact) and only surface by accident.

Manual and in-game review after MT: read dialogue in context to verify speaker identity and register, check scene tone coherence, screenshot untranslated leftovers (Windows Snipping Tool OCR -> VSCode `Ctrl+Shift+F` to find the source file).
Runtime verification: Frida-hook the engine's text-display function (e.g. trace `TextData::getText` or the TMP setter) to confirm injected English reaches the screen and matches the glossary. See the **reverse-engineering** skill for the tracing setup.

### Pronoun-vs-gender check with a next-name-mention window

A gender field nothing checks against is decoration.
Japanese drops pronouns, MT invents them, and it invents them inconsistently across a 20k-line script.

Parse names and genders out of the vocab format `JP (English) - Female - notes`:

```
^\s*[^\n()]+\((?P<name>[^()]+)\)\s*-\s*(?P<gender>Female|Male)\b     # MULTILINE|IGNORECASE
```

Dedupe by casefolded name and sort longest first so `Mina Ashford` is tried before `Mina`.
Strip comments, split the text into blocks on blank lines, normalize whitespace.
For each occurrence matched with `(?<![\w])NAME(?:['’]s)?(?![\w])`, search forward for the first opposing pronoun (`{he, him, his, himself}` for a female character, `{she, her, hers, herself}` for a male one) and report only when it lands before:

```
min(len(block), start of the next mention of ANY glossary name, match.end() + 180)
```

**Closing the window at the next character mention is what makes this usable instead of a false-positive generator.**
Without it the checker blames character A for a pronoun belonging to character B introduced later in the same paragraph.
Report each (character, pronoun) pair at most once per document, and run it over the shipped English, not the draft.

### PARALLEL entries: the same sentence about a different thing

A player asked why one intel panel ended its lines with full stops and the panel
beside it did not. Both were fluent, both fitted, neither carried residual
Japanese. Their Japanese differed by exactly ONE character, 男A against 男B, so
a same-source duplicate check compared the sources for EQUALITY and found them
unequal. Nothing in the pipeline could see them as a pair.

Mask the characters that make a parallel entry differ - latin letters, digits,
fullwidth letters, kanji numerals - and group on the remainder. Everything in
one group is the same sentence about a different thing, and the player meets the
members side by side or one screen apart.

Grade the divergence, because the two read very differently on screen:

* **wording** is the serious one, and it is usually a glossary break.
  `Odoro Cavern - 1` next to `Odoro Cave - 2`, `Lewd Cave 2` and `3` then
  `Lewd Cavern 4`, `Raises Attack by 5.` against `Raises ATK by 3`.
* **punctuation** is the quiet one, and it is what gets reported.

On one 84k-line corpus this gave 446 groups of which 17 had diverged - a list
small enough to fix by hand, and mostly MAP NAME BANNERS, which are among the
most visible strings in a game.

**Resolve by corpus majority, never by taste.** Every contested form had a
decisive majority elsewhere: 洞窟 Cave 19-0, 攻撃力 Attack 50-9, 経験値 EXP
17-1, the separator " - " 83-12. The majority is evidence about a house style
already applied dozens of times. Your preference is evidence about nothing.

**Then re-run the overflow check, because harmonising is a FIT decision too.**
Resolving 原罪のサジタリウス toward the more literal "Sagittarius of Original Sin"
was the better translation and broke the widget: 260px into a 242px box where
the Japanese sat at 198px. The looser-reading variant can be the only one that
fits. A group is not resolved until every member both matches its siblings and
clears its box.

**Do not turn this into a punctuation POLICY.** Description lines in that corpus
ran 233 with a terminal period against 155 without, and the Japanese ran 263
bare against 122 ending in 。, so there was no policy to enforce and inventing
one would have rewritten hundreds of good lines. The defect is DIVERGENCE INSIDE
A GROUP, never the presence or absence of a period.

### The pronoun with NO antecedent, which the check above cannot see

The window check needs a NAME to anchor on. The commonest invented pronoun has
none, because the Japanese named nobody either.

    逃がさないわよ……！        verb plus two particles, no object
    "I won't let HER get away...!"    about a man

Nothing already in this file can catch that. There is no name in the block to
anchor a window on, no `彼`/`彼女` to contradict, no placeholder, no residual
Japanese, and the line fits its box. Worse, the line was duplicated across two
maps and both copies read "her", so a same-source consistency check called it
consistent. It reached a player.

Detect it as an ABSENCE: the English carries a third-person pronoun and the
Japanese carries no referent at all - no `彼`/`彼女`, no `あいつ`/`こいつ`, no
kinship or role noun, no honorific. On one 84k-line corpus that matches 1,944
lines, which nobody will read, so **rank by SOURCE LENGTH**. The shorter the
Japanese, the less room it had to imply anyone, and the more certainly the
gender came from the model:

    <= 24 chars   1040
    <= 20 chars    647
    <= 16 chars    330
    <= 12 chars    113      <- a list a person can actually read

This cannot be a gate and should not pretend to be one. It has no way to know
who the line is about, so it produces a review list for someone who has played
the scene. Its value is that the question gets asked at all.

Two things fall out of running it. Most hits are correct, because the model
inferred from scene context and scene context is usually right, so report the
ratio or the list will be ignored. And the short-source tier surfaces
mistranslations that have nothing to do with gender: `……はいっ` ("...yes")
had shipped as "...No, she can't." A line short enough to have invented its
pronoun is short enough to have inverted its meaning.

### Romanization near-miss (edit distance 1)

Rieselle/Riselle, Kaguya/Kagura, Melfina/Melphina appear in different scenes because different batches were translated in different contexts.
The drifted spelling is not in the glossary at all, so every exact-match check passes it.

Take canonical names from the glossary, keep only those with `len >= 6` and no space (shorter names collide constantly, multiword names are already caught by exact match).
Pull candidate tokens from the English with `(?<![\w])[A-Z][A-Za-z'’]+(?![\w])`, stripping a trailing `'s`/`’s`.
Flag a token when it is not itself canonical, shares its casefolded first letter with a canonical name, and is exactly one edit away (bail if lengths differ by more than 1, for equal lengths count positional mismatches and require exactly 1, for a difference of 1 walk both strings allowing a single skip in the longer one).
Two exemptions kill the noise: a token equal to the canonical name minus a trailing `s`, and a token ending in an apostrophe whose stem is the canonical name.
The same-first-letter requirement plus the length floor is what stops edit-distance-1 firing on ordinary sentence-initial English words.
Report each offending token once.

### Same source, different translation

**Index `source -> set(translations)` across the whole corpus and attach the conflicting variants to the review item itself.**
Two individually fluent renderings of one source string are invisible to every per-line validator and are exactly what makes a patch feel machine-made: a menu label that changes name between screens, an item called two things.
Flag `inconsistent-source` and carry a `same_source_alternatives` list, capped at ~20, **inline on the item**, because a separate consistency report never gets acted on.

Beside it, flag `multiple-contexts` when occurrences of one string differ in `(file, event_code, speaker, display_shape)`.
That is how you notice one string serving as both a choice and a message, or used by two speakers, or living in a name box and a body.

Cheap companion cues, attention hints only: `short-ambiguous` when `len(source.strip()) <= 4`, glossary substring hits (parse `Source (Target)` with `^(.+?)\s+\((.+)\)\s*$`, match longest-source-first), a diff against a reference game that translated the identical Japanese differently, and a small set of Japanese risk regexes for negation, condition, quantity, identity, choice-or-order and wordplay matched against the **source**.
**State explicitly that these hints never by themselves mandate deep review**, or they become the queue.

#### Most of them can be unified automatically, and two kinds must not be

Flagging is not enough at scale: a 2,866-unit game produced **243** conflicts, which is more than anyone reads. Almost all of them are the same line the game genuinely repeats - a gallery or recollection room replays the story scenes, so one line exists in two or three places and **must** read identically in all of them. Those are a mechanical fix, not a review item.

Auto-unify a cluster **unless** one of the two conditions that made you skip dedup in the first place applies:

- **A variant carries a THIRD-PERSON pronoun.** Japanese drops subjects and MT invents them, so `he`/`she`/`they` may resolve to different people in different scenes. This is the same rule as re-reviewing a repeated line per scene, applied earlier and cheaper.
- **The cluster spans MORE THAN ONE SPEAKER.** Register and first person differ per speaker even when the source string does not.

Pick the winner deterministically so a re-run is a no-op: most sites first (a majority vote across the corpus), then prefer the **canonical** location over the replay one, then lowest id. On that game: **223 unified, 439 units rewritten, 20 left for a human** - and the 20 are exactly the ones where the reuse really is scene-dependent.

Re-validate afterwards. Two units sharing a source can sit in differently-sized boxes, so a winner that is longer than the variant it replaced can overflow where the old one fitted.

### `回復` points in opposite directions depending on the stat

**A "recovery" verb applied to a BAD stat means the number goes DOWN, and getting it backwards tells the player the opposite of the truth.**

This game tracks 淫乱度 (Lewdness), which you lose at. `淫乱度が5回復する` on a carrot means the carrot **helps** - Lewdness drops by 5. It came back as "Recovers 5 Lewdness" on 5 of the 6 lines that use the construction, which a player reads as the item making things worse. The same model got `魔力が10回復する` right everywhere, because Mana is a good stat and "Restores 10 Mana" is the literal reading.

The family is wide: 汚染度, 堕落度, 淫乱度, 発情度, ストレス, 疲労度, 拘束度 - any gauge whose *bad* end is the high end. Lock the direction in the glossary as a phrase, not a word:

```json
"淫乱度が回復": "Lewdness goes DOWN - 'Lowers Lewdness by N', never 'Recovers N Lewdness'",
"魔力が回復":   "Restores N Mana (Mana goes UP)"
```

and restate it in the bible, because the glossary slice is a one-liner and this needs the reason attached. No automated check catches it: the number is preserved, the English is fluent, and the meaning is inverted.

### Creature nouns are proper only if the database says so

A glossary that locks `スライム -> Slime` produces "burning through these **Vines**" mid-sentence. Check whether the term is ever a *database label* before capitalising it: if `Enemies.json` is empty and the word only ever occurs in prose - which is the case in any game where monsters are map events rather than battlers - lowercase is correct English and the model still capitalises it where a compound needs it (`オークの宝玉` to "Orc Orb").

### Publication-time consistency audit against the locked glossary

**Audit the accepted corrections, not just the source text - the fix pass is where consistency regressions get introduced.**
Every correction is fluent English a reviewer approved in isolation, and the damage only shows across the corpus.
Two blocking checks at finalize time.

```python
FIXED   = r"`([^`\n]+)`\s*→\s*\"([^\"\n]+)\""            # quirks/glossary fixed wording
LABEL   = r"\[([A-Za-z][A-Za-z0-9 /&'’-]{0,79})\]"       # [Y] in the correction
```

1.
**Fixed wording.** Support aligned multi-mappings by splitting both sides on `\s+/\s+` and zipping when the part counts match and exceed 1.
Key sources with all whitespace removed and targets with whitespace runs collapsed.
Raise when a source that has **exactly one** canonical target was rendered as something else.
The single-target guard keeps genuinely ambiguous terms out of the false-positive pile instead of flagging them forever.
2.
**Structured UI headers.** Pull `【X】` labels from the source and `[Y]` from the correction, zip only when the counts are equal and nonzero, and raise when one Japanese label maps to two distinct English renderings across the fix set, naming both and the findings they came from.
**The leading `[A-Za-z]` requirement is what stops `\C[3]` and `[1]` being read as labels.** This is how 【攻撃力】 shipping as "Attack" on one screen and "ATK" on another gets caught before publication rather than in a screenshot.

### Motif families: decide a running gag once

Per-line review always preserves an inconsistent set, because each variant is individually plausible English.

Seed families **deterministically from the project's own quirks file**, not from model judgment:
keep lines matching `recurring|running|joke|wordplay|pun|catchphrase|humou?r|冗談|駄洒落|語呂` case-insensitively, pull Japanese anchors of 2 or more characters with `[一-龠々〆〤ぁ-ゔァ-ヴー]{2,}`, drop any seed with no anchor, substring-match each anchor against every unit's Japanese source, and emit a family only where 2 or more units match.
This only works if **every recurring-joke bullet in the quirks file embeds at least one distinctive literal Japanese anchor from that game** - a generic grammatical fragment that would also match unrelated dialogue is not an acceptable anchor.

Give each family its own review bundle so one reviewer sees every variant side by side, and require exactly one verdict per family: a family called preserved may name no suspects, a family called broken must name at least one, and suspects must be a subset of that family's own variants.
**If any later per-scene reviewer files a wordplay exception on a unit in a family already marked preserved, reopen every variant in that family** - the preserved call was made by a pass that never saw the scene where the joke lands.
Hand the reopened family only source and translation pairs, dropping the per-variant context windows, or the comparison is too long to read.

### LLM judge: three model-blind snapshots with differing authority

Scoring method, sampling and rubric design are in `quality-evaluation.md`. This
section covers only the export: what each snapshot may see, and why.

**A reviewer without the glossary marks correct locked terminology as unnatural and rewards the model that invented a prettier name for the heroine.**
When exporting a review, emit three snapshots next to the review file:

| File | Content |
|---|---|
| `review_system_prompt.md` | The deduplicated distinct `system` strings across all reviewed requests, joined by blank lines. Raise if empty. |
| `review_glossary.txt` | Every distinct line of the per-request **matched** glossary slice, order-preserving dedupe through a seen-set. |
| `review_sfx_reference.txt` | The same dedupe over the matched SFX suggestions. |

Export the matched slice, not the whole glossary, so the reviewer's context stays small and relevant.
Replace an empty result with an explicit `(No glossary entries matched the reviewed source text.)` placeholder rather than shipping an empty file, or the reviewer reads absence as permission.
**Assign the three different authority in the prompt.** The system prompt's requirements and the glossary's approved names and terms are authoritative and violations must be penalized when the rule or term applies. The SFX table is contextual possibility only, and candidates may choose a different natural rendering when the scene supports it.
Without that split the reviewer penalizes every SFX rendering that differs from the suggestion table, which dominates the terminology score on SFX-heavy eroge corpora.
If the review prompt is a template, hard-fail on a missing snapshot placeholder rather than shipping a dangling `{{REVIEW_GLOSSARY}}`.

## Speaker-attribution audit (post-translation, catches ORIGINAL-GAME bugs)

Name boxes are frequently mis-tagged **in the source game** - the dev copy-pastes a message command and forgets to change `[Name]`.
The translation faithfully reproduces the error, so it surfaces as "Asuka says a line that is obviously the villain's".
Worth a dedicated pass once a route is playable. On one Wolf title it found **20 real mis-tags** across 456 dialogue scenes.

**Stage 1 - mechanical (cheap, exhaustive, zero false negatives).**
Parse the leading `[Name]` out of the JP source and out of the EN translation for every line, map through the glossary, and diff.
This proves the translation neither dropped, added, nor swapped a tag.
Expect the residual "mismatches" to be benign glossary variants (full name vs given name, honorific kept, synonym choices).
Eyeball them once, then trust the pass. Anything else is a translation bug.

**Stage 2 - semantic (agent fan-out).**
Render every scene containing at least one tagged line as compact `[idx] TAG=<jp> | JP: <body> | EN: <body>` rows, batch ~30 KB per file, one agent per batch.
Ask only for JP-vs-JP contradictions (the JP is ground truth, the EN is a reading aid).
The two bug shapes:

- **narration-in-namebox**: body is third-person prose (`肉坊は嬉々として腰を振る`, `明日香は顔が青ざめた`) sitting in someone's name box, while neighbouring narration is untagged.
- **wrong-character**: body addresses the tagged character by name (`マリアちゃんは…どうするの？` tagged マリア, `明日香さ、お願いがあるんだけど` tagged 明日香), replies to the tagged character's own previous line, or carries the opposite gender's register (female box + `俺 / てめえ / 〜ねえよ / ヒャッハー`).

Verify each finding with 3 skeptics on **different lenses** (JP grammar, scene turn-flow, dedicated false-positive hunter) and keep on 2-of-3.
Single-lens redundancy misses much less than lens diversity does.

Prompt must exclude, or you drown in noise: name variants, deliberate persona switches (stage names), `？？？` pre-reveal boxes, a character merely *mentioning* another, first-person self-narration, quoting, and untagged lines (missing boxes are usually house style, not bugs).
A register-gender trap character like Louis is a guaranteed false positive here unless the prompt carries his note.

**Applying the fix.**
Change the speaker and the portrait or face code together - engines key the portrait off a separate code (`@N` in Wolf) that was copy-pasted with the wrong name.
Derive the right code by tallying speaker-to-code frequency within that same scene.
This trips the injector's control-code guard, so it needs the drift override.
Make that safe by (a) matching each edit on its exact current string with an asserted occurrence count, and (b) re-extracting afterwards and proving *exactly N* lines changed and every one is an intended value.
**Never address these edits by line index** - injected and re-wrapped files drift out of sync with the extraction masters. Match on content or on the JP source instead.

## Plugin and struct-parameter sweep (RPG Maker `plugins.js`)

Regex extraction only reaches keys somebody already enumerated, and the residual Japanese in a game's UI lives in struct parameters nobody has seen before.

**Decode each parameter string recursively while its decoded value is still an object, an array, or another serialized string, and record every leaf by its full logical path** (`DestinationList[4].DestinationText`, `MenuStyleList[2].PageList1[0].ParamName`).
Count duplicate leaves across styles, pages and objective slots separately - an encoded array is not one string.
Record an undecodable structural value as **unresolved**, never skip it.
Escaping depth is storage syntax, not evidence that the inner text is non-visible.

Classification: `@default` can be a player-facing runtime default and is reported latent or default-only when `plugins.js` overrides it, `@text` and `@desc` are editor-only, and a disabled plugin's visible text is reported inactive or latent, never "clean".

**Never translate**: plugin names and filenames, parameter and struct member keys, identifiers, lookup values, note tags, anything read back by code, plugin commands, switch and variable names, paths, URLs, fonts, color codes, regexes, booleans, numeric strings.
These belong in `do_not_translate`.

Every candidate gets exactly one disposition from a fixed set, and no plugin is called clean until each candidate is recorded.
Post-edit verification is mandatory: re-parse `plugins.js`, recursively re-decode each edited container and check shape, entry count and leaf values, residual-scan for remaining Japanese, syntax-check edited sources, and read the diff for accidental file-wide reformatting.
Watch for the hard-coded Japanese fallback chosen when a configured name is empty and then drawn: `configuredLabel || "日本語"`.

## Systemic-quirk discovery: three isolated blind passes, then recount

A single pass anchors on the first hypothesis it is shown and simply reconfirms the glossary's own prior guesses.

Freeze one self-contained starting packet - game paths, engine and version, corpus map, a 2-5 sentence source-derived synopsis with provenance, the unchanged guidance files, and the raw candidate hypotheses.
Launch exactly three fresh subagents concurrently with no forked conversation context.
No worker sees another worker's report, none may delegate or write into the repository, and all three must return before the coordinator synthesizes anything.

Report duplicate discoveries as an agreement ratio (`1/3`, `3/3`) and treat it as convergence evidence, but **agreement does not replace corpus verification** - independently recount and re-inspect the union of proposed anchors, members, exceptions and corrections.
Label the starting guidance orientation, not evidence, and audit the existing glossary and quirks as hypotheses.
Confirm a family only on at least two independent examples or an explicit in-game callback, and discard generic categories like "there may be puns" that carry no source anchor.
A correction is actionable only when the text is player-visible AND release-reachable - hidden scaffolding, test content and uncertain reachability go to a research backlog.
Report verified-clean families separately and never count them as defects, and never claim the game is fully reviewed.
If three isolated subagents cannot run concurrently, report the blocker rather than serializing and calling it three passes.

## Shared glossary bridge

Run `DAZEDTL_ROOT/scripts/len_translation.py import-glossary --game-root <game>
--input <reviewed-glossary.json>`. It accepts `names/en` and legacy `characters/name`
entries plus terms, preserves existing rows and refuses conflicting spellings. Explicit
alias rows remain distinct, and reveal-protected identities must have their own entries.
Review additions with the same Glossary editor used by Workflow. Archive the source
JSON and use the shared files and context compiler thereafter. `do_not_translate`
identifiers stay extraction metadata and must be excluded or masked before translation.
