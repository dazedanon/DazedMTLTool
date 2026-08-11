# DazedTL — Project Setup

You are analysing a Japanese game project to produce and maintain configuration artifacts for
DazedTL. Work in the game repository. Scan files; do not invent content you did not see.

---

## Task

In **one user-facing run**, complete the two internal phases below, write the final Glossary,
Translation quirks, and Game skill to their DazedTL paths, then report what changed. Do not stop
after Phase 1 or ask the user to launch another skill. Do **not** translate the game or broadly edit
its files. The only editing exceptions are those three guidance files and a qualifying deterministic
micro-repair under the RPG Maker speaker rules below. Recommend formatting and pipeline settings
only in the designated configuration block.

Default: update every guidance file and report section specified for the selected engine.
Regenerate mode: if the user asks for only one guidance artifact, update **only** its destination
file and report that result using the same ownership rules; do not touch the other guidance files.

---

## Ownership (no duplication)

| Block | Owns | Must NOT include |
|-------|------|------------------|
| `glossary` | Named characters (gender, role, **per-character** speech register) + worldbuilding terms and stable translation-relevant facts saved at `.dazedtl/glossary.txt` | Global dialect / person rules; honorific policy; speaker-format flags; formatting; speculative plot interpretation |
| `speaker_settings` | Manual tool flag ENABLE/SKIP decisions + short evidence | Character bios; quirks; full glossary |
| `translation_quirks` | Cross-cutting voice rules (battle-log person, global dialect, item-description style, recurring humor/wordplay policy, **unusual** honorific habits) | Per-character register; one-off jokes; "always keep -san" (tool base prompt already does); codes/wrap/line counts; speaker flags |
| `game_skill` | **Translation Frame** for the API (theme / era / register / naming / optional myth) saved at `.dazedtl/skills/game.md` | File inventories; quirks bullets; glossary; per-character register; IDE scaffolding; restating base honorific/formatting policy |
| `investigation_report` | Confirmed editorial families, unresolved research backlog, and searched coverage | Duplicated glossary/quirks content; generic categories; QA clearance; proposed game-file edits |
| `rpgmaker_settings` (RPG Maker only) | Manual code-408 decision + measured wrap/font recommendations | Translation prose; glossary; voice rules; speculative settings without evidence |

Hard rules:
1. Per-character voice → `glossary` only.
2. Category-wide / cross-cutting voice → `translation_quirks` only.
3. Default honorifics policy is owned by the tool base prompt - only note **unusual** honorific habits in quirks.
4. `game_skill` is the title's Translation Frame for the translation API - keep it compact; do not reprint quirks or glossary.
5. `speaker_settings` is manual config, not lore or pasteable guidance.
6. `rpgmaker_settings` is measured manual setup advice, not content to merge into the translation prompt.
7. Phase 1 may collect candidate hypotheses but must not confirm systemic editorial families.
   Phase 2 alone owns their global research and final disposition.

---

## Phase 1 — Baseline setup

Establish characters, world terms, speaker handling, the Translation Frame, and engine settings.
While scanning for those responsibilities, collect concrete candidate hypotheses for Phase 2.
Do not globally research them yet and do not place an unverified recurring-humor or systemic-term
rule in the final Glossary or Translation quirks.

### Shared scan strategy

Map / event files can be huge. Do **not** read them sequentially end-to-end.

1. Read small DB files in full first (richest, always small).
2. For large event/map files: **search/grep**; take a distributed sample from early, middle, and
   late maps plus common events; stop ordinary setup sampling when patterns stabilize.
3. One scan feeds every output block - do not rescan from scratch per block.

Do not review every line. Use cheap corpus-wide frequency/alternative summaries, recurring
speakers, and distributed scene samples to harvest concrete candidates involving systemic humor,
callbacks, coined words, titles, common nouns mistaken for names, or other patterns isolated
translation could mishandle. Pass candidates internally to Phase 2 with their Japanese anchors or
recognizable scene pattern and a specific next search. Generic prompts such as “check for jokes”
are not candidates.

<!-- engine:rpgmaker -->

### RPG Maker file strategy

**DB (read in full):**
- `Actors.json` (mandatory for major characters, actor IDs, `\\N[n]` mappings)
- `Classes.json`, `Troops.json`, `Skills.json`, `Items.json`, `Armors.json`, `Weapons.json`, `States.json`, `System.json`

**Events (grep / sample):**
- `CommonEvents.json`, `Troops.json`, `Map001.json`–`Map010.json` (early maps first)
- Prefer code `401` dialogue + nearby `101` speaker/name params; `405` scrolling text when present
- Speaker markup evidence: `【Name】`, `[Name]`, `Name：`, `\\n<Name>`, `\\k<Name>`, colour-wrapped name lines

**Runtime/UI evidence:**
- `js/plugins.js` plus source for enabled plugins in `js/plugins/`
- `js/rpg_windows.js`, `js/rpg_scenes.js`, `js/rpg_managers.js`, or MZ equivalents
- `System.json` resolution/font fields, custom fonts, window skins, and relevant image dimensions

--- attach your game data files / open the game repo before continuing ---

### Speakers analysis (for the manual Speaker settings section)

Code `101` opens the text window. Code `401` is a dialogue line. Multiple `401`s form one message box.

**Always-on formats (NO FLAG needed):**
- `101` param[4] name
- `\\n<Name>` or `\\k<Name>` (angle brackets)
- `【Name】` alone or with dialogue
- `[Name]` alone or with dialogue
- `\\c[N]Name\\c[0]` colour-wrapped name on its own `401` line
- `Name：` full-width colon name line

**Critical:** `\\N[X]` / `\\n[X]` (square brackets + number) are actor variable codes, NOT speaker formats. Do not count them as always-on speaker hits.

**Flags (only when some speakers lack an always-on format):**
- `INLINE401SPEAKERS` — name immediately before `「` on a `401` line (e.g. `エレナ「今日は…`)
- `FIRSTLINESPEAKERS` — first `401` is a short plain name (< 40 chars, has Japanese); next line starts with `「` `"`` `（` `*` `[`; often empty face on `101`
- `FACENAME101` — last resort only when no always-on and neither flag above. It maps the face
  **filename alone** from `101` param[0] to a speaker when param[4] is empty; the tool does not use
  the face index to disambiguate characters.

Before enabling `FACENAME101`:
1. Inspect only messages with a non-empty face filename and empty param[4]. Exclude narration,
   notifications, sound effects, chirps, and other lines that do not need a named speaker.
2. Cross-tabulate each candidate filename against all code-101 uses, including messages that
   already have explicit param[4] names. Require the filename to identify one speaker consistently.
3. Choose `SKIP` when the filename is a generic/shared sheet, appears with multiple explicit
   speakers, needs the face index to identify a character, or only rescues one or two isolated
   exceptions. A nearly universal explicit-name pattern with a stray unnamed line is not evidence
   for enabling this global fallback.
4. Choose `ENABLE` only when multiple genuine unnamed dialogue groups can be recovered through
   stable one-to-one `filename -> speaker` mappings. If enabled, list only those proven mappings,
   not every face filename in the project.

#### Deterministic speaker micro-repairs

Prefer a tiny direct data repair over enabling a broad heuristic flag when all of these conditions
hold:
- At most three entries need the same simple repair.
- The exact speaker is proven by adjacent narration, the same event's explicit names, or other
  direct local evidence. Do not treat the face filename itself as proof.
- The repair only fills an empty code-101 param[4]; it does not translate dialogue, invent a name,
  normalize intentional aliases or story-stage labels, or alter faceless narration.
- The target files are writable and the edit preserves their existing JSON formatting.

Apply a qualifying repair immediately without asking for confirmation. Modify only the empty
param[4] values, parse the changed JSON, and rescan all face-backed messages. If every remaining
face-backed message has an explicit name, choose `FACENAME101: SKIP` and state that the fallback is
not needed after the repair. If any identity is ambiguous or the scope exceeds this narrow rule,
make no edits and report the evidence normally.

### Glossary rules (for the written Glossary)

- Separator: plain hyphen-minus `-` only (never em/en dash).
- Descriptions entirely in English; refer to other characters by English name.
- Commit to one spelling - never `Sylfia / Sylphia`.
- Characters: gender, role, speech register, personality, player-chosen name (Actors.json ID 1).
- Real named actors get full `# Game Characters` entries, not only `\\N[n]` placeholders.
- Worldbuilding: factions, lore locations, unique systems/titles, and concise stable facts needed to disambiguate their translations - exclude speculative plot interpretation, skill/item/weapon/armour names, and generic RPG words.

### Quirks rules (for the written Translation quirks)

Find translation-only quirks, for example:
- Battle log / system messages consistently 3rd person (or other fixed person)
- Global dialect (old-timer speech, archaic narration)
- Recurring item/skill description style
- Recurring humor mode, catchphrase treatment, or wordplay strategy when several source examples support one cross-cutting rule
- Unusual honorific habits (who uses what with whom)

Exclude: formatting codes, wrap, line counts, speaker flags, character name lists, and one-off jokes
that should be localized from their own context instead of becoming global policy.

Write short imperative bullets to `.dazedtl/skills/quirks.md`.
For every recurring joke, catchphrase, or wordplay rule, include one or more distinctive Japanese
source anchors from that game in the same bullet. QA uses those literal anchors to gather the
complete motif family deterministically; do not use a generic grammatical fragment that would
match unrelated dialogue.

### Game skill rules (for the written Game skill)

Produce the per-game translation skill saved at `.dazedtl/skills/game.md`.
DazedTL **merges this file into the translation system prompt** (before quirks).

**Translation Frame only** (one compact line per field; evidence-based):
- `世界観 (Theme / setting)` - genre, world type, core atmosphere
- `時代感 (Era / technology level)` - medieval / modern / sci-fi / historical / etc.
- `文体方針 (Register policy)` - overall English style (plain RPG, mythic, courtly, modern casual, military, gothic, …)
- `固有名詞方針 (Naming policy)` - invented names, titles, ranks, honorifics, myth-derived terms (high-level only; default honorific keep-policy stays in the tool base prompt)
- `神話・伝承 (Myth / folklore basis)` - **omit unless** evidence supports a specific tradition or source family

Do **not** include:
- Voice-rules pointers, tool-boundary essays, or IDE instructions
- Repo file inventories / "files that matter"
- Per-character register (glossary) or battle-log / dialect bullets (quirks)
- Verbatim quirks or glossary entries

**Paths:**
- Game skill (API): ``.dazedtl/skills/game.md``
- Quirks (API): ``.dazedtl/skills/quirks.md`` (never ``translation_quirks.txt``)
- Optional custom API overlays: other ``.dazedtl/skills/*.md`` except those two

### Phase 1 and layout analysis (for the manual RPG Maker settings section)

#### Code 408

Code `408` is a continuation of an editor comment. It is normally internal, but plugins can parse
`108`/`408` comment blocks and display their contents to players. DazedTL extracts code-408 text
only from recognized player-facing code-108 markers; currently supported: {{SUPPORTED_CODE408_MARKERS}}.

1. Inventory code-408 values and group them with their preceding code-108 command.
2. Search enabled plugin sources and event-handling code for the discovered comment tags,
   prefixes, or parsing APIs. Compare every player-facing marker found with DazedTL's supported
   marker list. Do not infer runtime visibility from Japanese text alone.
3. Report the total code-408 inventory, the count under supported markers, and the confirmed
   player-visible count. Inspect matching values for real game text, debug text, placeholders, or
   isolated test content. Unsupported marker blocks remain untouched even when code 408 is enabled.
4. Choose `ENABLE` when a supported marker has player-facing text worth translating. Choose `SKIP`
   when no supported marker is present, its plugin is disabled, or matching values are only debug,
   test, or placeholder content. If runtime visibility is inconclusive, choose `SKIP` and state what
   must be playtested.
5. Explicitly report every confirmed or suspected player-facing marker that is not currently
   supported. Preserve the exact code-108 marker text and list its plugin consumer/evidence,
   code-408 block and line counts, representative map/event locators, and confidence. Tell the user
   to add or request support for each listed marker in DazedTL before translation. If none are found,
   say `No unsupported player-facing code-408 markers found`; never omit this result.
6. Tell the user to set the **Include displayed comment text (code 408)** checkbox in Phase 1 to the
   recommended state. This is a user choice; do not edit tool configuration yourself.

#### Window geometry, wrapping, and fonts

Calculate recommendations separately for `Dialogue`, `List/Help`, and `Notes`. Use actual game
geometry rather than generic RPG Maker defaults whenever project code is available.

1. Resolve the game resolution and each relevant window's outer width/height, padding, text inset,
   line height, columns, face/portrait reservation, icons, and plugin-added margins.
2. Resolve the actual font face and base size plus runtime changes such as `\\{`, `\\}`,
   `\\FS[n]`, custom font codes, bold/outline changes, and plugin-specific scaling. Treat icons and
   inline images as pixel width, not zero-width text.
3. Calculate usable pixels: inner window size minus padding, portraits/faces, columns, icons, and
   other fixed reservations. Derive visible row capacity from usable height and the largest
   applicable line height.
4. Convert usable pixels to DazedTL's character-count wrap setting by measuring representative
   English glyphs in the real font when possible. Otherwise use a conservative documented average
   glyph width. Never copy a pixel width directly into `width`, `listWidth`, or `noteWidth`.
5. Simulate final wrapping for representative short, median, long, control-code-heavy, icon-heavy,
   font-changed, and explicitly line-broken values. Use the largest effective font when one shared
   setting must cover several variants. Accept a recommendation only when each rendered line fits
   horizontally and the rendered line count stays within the actual visible-row limit.
6. Treat horizontal capacity and visible rows as simultaneous constraints. Distinguish fixed or
   clipped windows from scrolling, paging, and auto-sizing windows. If no readable font and wrap
   width satisfies both constraints, flag the value for pagination/manual reflow or a game-side
   window change; do not reduce wrap width as a supposed fix for vertical overflow because that
   usually creates more lines.
7. Detect standard message faces from non-empty code-101 parameter 0 values. Calculate both the
   full dialogue width and the reduced `faceWidth`; DazedTL selects `faceWidth` automatically for
   those message groups. For plugin portraits outside code 101, document the detection gap and use
   a conservative global width or recommend custom handling.
8. Recommend one conservative shared width and one readable font size for each category. If the
   current font should remain unchanged, say `keep current` and report its measured size. Cite the
   files/functions/plugin parameters supporting every recommendation and give a confidence level.

Report these recommendations under **Manual changes > RPG Maker settings**. They are settings the
user must review or change, so do not put them in a code fence:

- `CODE408 : ENABLE|SKIP` with runtime evidence, affected count, and confidence.
- Unsupported CODE408 markers: each exact code-108 marker with plugin/runtime evidence, block and
  line counts, example locators, confidence, and an explicit request to add tool support; otherwise
  state that none were found.
- `Dialogue : width=<full width> ; faceWidth=<code-101 face width> ; font=<px or keep current
  (measured px)> ; rows=<count>`.
- `List/Help: listWidth=<DazedTL width> ; font=<px or keep current (measured px)> ; rows=<count or
  varies>`.
- `Notes    : noteWidth=<DazedTL width> ; font=<px or keep current (measured px)> ; rows=<count or
  varies>`.
- Evidence: resolution/window/font/plugin locators, horizontal capacity, visible-row limit, and
  tested fit.
- Exceptions/playtests: variant windows, uncertain plugin behavior, or messages requiring manual
  pagination or reflow.

<!-- /engine:rpgmaker -->

<!-- engine:wolf -->

### Wolf file strategy

WolfDawn extractions live under `files/` as JSON lists of `{source, text}` entries.
Analyse `source` only.

**DB / system (read in full first):**
- `DataBase.project.json`, `CDataBase.project.json`, `SysDatabase.project.json` - richest small source of character/actor names, classes, factions, lore titles
- `CommonEvent.dat.json` - common events (dialogue + system text)
- `Game.dat.json` - game/system strings (title, terms)
- `Evtext.json` - external event text when present

**Maps (grep / sample, do not read huge files sequentially):**
- `<Map>.mps.json` - per-map events; main story dialogue; often very large
- Prefer grep of `source` for speaker patterns and recurring proper nouns
- Scan lowest-numbered maps first - early maps usually carry the most story

**Exclude from glossary analysis:**
- `names.json` - item / skill / enemy value names (translated separately in Step 3 Names; do **not** list them in the glossary)

--- attach the extracted JSON in files/ here before continuing ---

### Speakers analysis (for the manual Speaker settings section)

WolfDawn already tags who speaks. High-confidence nameplates (`literal_line1`) are always reshaped - nothing to decide.

The only flag is whether **low-confidence** first-line guesses (`speaker_src = literal_line1_lowconf`) are real speaker names for this game:
- short first line with **no** preceding face window
- might be a nameplate, or the start of dialogue / narration

Inspect a sample of those entries in maps / CommonEvent:
- `ENABLE` if low-confidence first lines are overwhelmingly real speaker names
- `SKIP` if many are dialogue or narration (reshaping would mislabel lines)

Do **not** emit RPG Maker flags (`INLINE401SPEAKERS`, `FIRSTLINESPEAKERS`, `FACENAME101`).

**Wolf speaker-settings schema (use this instead of the shared RPG Maker flag list):**

Report the detected patterns, the `LOWCONF_FIRSTLINE: ENABLE|SKIP` decision with a one-line reason,
and representative examples under **Manual changes > Speaker settings**. These are findings and a
manual checkbox decision, so do not put them in a code fence.

### Glossary rules (for the written Glossary)

- Separator: plain hyphen-minus `-` only (never em/en dash).
- Descriptions entirely in English; refer to other characters by English name.
- Commit to one spelling - never `Sylfia / Sylphia`.
- Characters: gender, role, speech register, personality; note player-chosen names (variable / input).
- Worldbuilding: factions, lore locations (mentioned in dialogue but not map labels), unique systems/titles, and concise stable facts needed to disambiguate their translations.
- Exclude speculative plot interpretation from glossary descriptions.
- Exclude: skill / item / weapon / armour names from `names.json`, generic RPG words, unnamed NPCs.

### Quirks rules (for the written Translation quirks)

Find translation-only quirks, for example:
- Battle log / system messages with a fixed person or register
- Global dialect (archaic narration, cute speech markers game-wide)
- Recurring item/skill description style
- Recurring humor mode, catchphrase treatment, or wordplay strategy when several source examples support one cross-cutting rule
- Unusual honorific habits

Exclude: wrap geometry, inject layout, `names.json` harvest, speaker LOWCONF checkbox, character name lists,
and one-off jokes that should be localized from their own context instead of becoming global policy.

Write short imperative bullets to `.dazedtl/skills/quirks.md`.
For every recurring joke, catchphrase, or wordplay rule, include one or more distinctive Japanese
source anchors from that game in the same bullet. QA uses those literal anchors to gather the
complete motif family deterministically; do not use a generic grammatical fragment that would
match unrelated dialogue.

### Game skill rules (for the written Game skill)

Produce the per-game translation skill saved at `.dazedtl/skills/game.md`.
DazedTL **merges this file into the translation system prompt** (before quirks).

**Translation Frame only** (one compact line per field; evidence-based):
- `世界観 (Theme / setting)` - genre, world type, core atmosphere
- `時代感 (Era / technology level)` - medieval / modern / sci-fi / historical / etc.
- `文体方針 (Register policy)` - overall English style
- `固有名詞方針 (Naming policy)` - invented names, titles, ranks, honorifics (high-level only)
- `神話・伝承 (Myth / folklore basis)` - **omit unless** evidence supports a specific tradition

Do **not** include voice-rules pointers, tool-boundary essays, file inventories, per-character register (glossary), or quirks bullets.

**Paths:**
- Game skill (API): ``.dazedtl/skills/game.md``
- Quirks (API): ``.dazedtl/skills/quirks.md``
- Optional custom API overlays: other ``.dazedtl/skills/*.md`` except those two

<!-- /engine:wolf -->

{{LOCALIZATION_INVESTIGATION_PHASE}}

---

## Apply guidance files and report

Before responding, directly update these files without asking for approval:

1. `.dazedtl/glossary.txt` - update only the game-specific section. Preserve the auto-appended base
   separator and everything below it byte-for-byte. Preserve unrelated and user-authored entries.
2. `.dazedtl/skills/quirks.md` - merge the final cross-cutting guidance, preserving unrelated and
   user-authored rules.
3. `.dazedtl/skills/game.md` - merge the compact Translation Frame, preserving unrelated compatible
   material and removing only content that conflicts with the evidence or this skill's ownership rules.

Create missing `.dazedtl/skills/` directories and guidance files when necessary. Use surgical edits,
not wholesale replacement of an existing file. Reread all three files after writing and verify that
the intended guidance is present, unrelated content remains, and the Glossary base section is intact.
Do not tell the user to copy or paste generated blocks.

In default mode, use this exact top-level report order in ordinary Markdown without code fences:

1. **Guidance files updated**
2. **Localization investigation**
3. **Manual changes**
4. **Evidence, repairs, and playtests**

In regenerate mode, report **Guidance files updated** for the requested artifact plus only directly
relevant investigation or evidence; do not repeat unrelated setup analysis.

### 1. Guidance files updated

For each of the three paths, state `Created`, `Updated`, or `Unchanged`, summarize the entries or
sections affected, and confirm reread verification. If a file could not be written, report the exact
blocker; do not substitute a copy/paste block.

### 2. Localization investigation

Summarize the Phase 2 result without duplicating the written Glossary or Translation quirks:

- **Confirmed actionable defects** - families with current text requiring correction, including
  priority, discovery agreement, counts, representative locators, and correction strategy.
- **Verified-clean families** - investigated families whose current handling is already sound;
  include discovery agreement and never count these as inconsistencies, defects, or correction
  families.
- **Research backlog** - plausible but unresolved hypotheses, confidence, evidence, and the exact
  next search or context needed. This is not a QA clearance.
- **Coverage** - file classes and map ranges searched, independently recounted occurrence totals,
  completion of all three isolated passes, and inaccessible or intentionally excluded material.

If no systemic family is confirmed or no backlog remains, state that explicitly. Do not claim the
game is fully reviewed or clean.

### 3. Manual changes

Do not use a code fence in this section. State each action as **Change** or **Keep**, name the exact
DazedTL control or setting, give the target value, and append a short reason.

For RPG Maker, include **Speaker settings** first:

- `INLINE401SPEAKERS`: ENABLE or SKIP.
- `FIRSTLINESPEAKERS`: ENABLE or SKIP.
- `FACENAME101`: ENABLE or SKIP. When enabled, list only proven filename-to-speaker mappings.

Then include **RPG Maker settings** with the code-408 decision, unsupported marker support requests,
and Dialogue, List/Help, and Notes wrap/font values specified above. Tell the user to enter the
recommended widths in Workflow and click **Save line widths**; DazedTL stores them with the selected
game and reloads them automatically when switching projects.

For Wolf, include **Speaker settings** with `LOWCONF_FIRSTLINE: ENABLE|SKIP` and representative
examples. Do not emit RPG Maker settings.

### 4. Evidence, repairs, and playtests

Do not use a code fence in this section. Keep it brief and include only applicable items:

- Patterns and representative examples supporting the manual speaker decisions.
- Deterministic speaker repairs already applied, with file and event/list locators and the value
  written to code-101 param[4]. Clearly label these **Already applied - no manual action**.
- Runtime/window/font/plugin evidence supporting RPG Maker settings.
- Exceptions, uncertainty, unsupported features, and exact playtests the user should perform.

If known speakers were prepended in a `<known_speakers>` block above this skill, prefer those names
in the glossary, then cross-check Actors.json for other major named actors.
