# DazedTL — Project Setup

You are analysing a Japanese game project to produce configuration artifacts for DazedTL.
Work in the game repository. Scan files; do not invent content you did not see.

---

## Task

In **one pass**, discover everything needed for translation setup and emit the labeled output blocks below.
Do **not** translate the game or edit its files. Recommend formatting and pipeline settings only in
the designated configuration block.

Default: emit every block specified for the selected engine.
Regenerate mode: if the user asks for only one block, emit **only** that block using the same
schema and exclusivity rules.

---

## Ownership (no duplication)

| Block | Owns | Must NOT include |
|-------|------|------------------|
| `glossary` | Named characters (gender, role, **per-character** speech register) + worldbuilding terms | Global dialect / person rules; honorific policy; speaker-format flags; formatting |
| `speakers` | Tool flag ENABLE/SKIP + short evidence | Character bios; quirks; full glossary |
| `translation_quirks` | Cross-cutting voice rules (battle-log person, global dialect, item-description style, **unusual** honorific habits) | Per-character register; "always keep -san" (tool base prompt already does); codes/wrap/line counts; speaker flags |
| `game_skill` | **Translation Frame** for the API (theme / era / register / naming / optional myth) saved at `skills/game.md` | File inventories; quirks bullets; glossary; per-character register; IDE scaffolding; restating base honorific/formatting policy |
| `rpgmaker_config` (RPG Maker only) | Code-408 Phase 1 decision + measured wrap/font recommendations | Translation prose; glossary; voice rules; speculative settings without evidence |

Hard rules:
1. Per-character voice → `glossary` only.
2. Category-wide / cross-cutting voice → `translation_quirks` only.
3. Default honorifics policy is owned by the tool base prompt - only note **unusual** honorific habits in quirks.
4. `game_skill` is the title's Translation Frame for the translation API - keep it compact; do not reprint quirks or glossary.
5. `speakers` is config, not lore.
6. `rpgmaker_config` is measured setup advice, not content to merge into the translation prompt.

---

## Shared scan strategy

Map / event files can be huge. Do **not** read them sequentially end-to-end.

1. Read small DB files in full first (richest, always small).
2. For large event/map files: **search/grep**; sample early story maps; stop when patterns stabilize.
3. One scan feeds every output block - do not rescan from scratch per block.

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

### Speakers analysis (for `speakers` block)

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
- `FACENAME101` — last resort only when no always-on and neither flag above; face filename in `101` param[0], empty param[4]. If ENABLE, list every unique face filename from `101` param[0].

### Glossary rules (for `glossary` block)

- Separator: plain hyphen-minus `-` only (never em/en dash).
- Descriptions entirely in English; refer to other characters by English name.
- Commit to one spelling - never `Sylfia / Sylphia`.
- Characters: gender, role, speech register, personality, player-chosen name (Actors.json ID 1).
- Real named actors get full `# Game Characters` entries, not only `\\N[n]` placeholders.
- Worldbuilding: factions, lore locations, unique systems/titles - exclude skill/item/weapon/armour names and generic RPG words.

### Quirks rules (for `translation_quirks` block)

Find translation-only quirks, for example:
- Battle log / system messages consistently 3rd person (or other fixed person)
- Global dialect (old-timer speech, archaic narration)
- Recurring item/skill description style
- Unusual honorific habits (who uses what with whom)

Exclude: formatting codes, wrap, line counts, speaker flags, character name lists.

Output as short imperative bullets suitable to paste into `skills/quirks.md`.

### Game skill rules (for `game_skill` block)

Produce the per-game translation skill saved at `skills/game.md`.
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
- Game skill (API): ``skills/game.md``
- Quirks (API): ``skills/quirks.md`` (never ``translation_quirks.txt``)
- Optional custom API overlays: other ``skills/*.md`` except those two

### Phase 1 and layout analysis (for `rpgmaker_config` block)

#### Code 408

Code `408` is a continuation of an editor comment. It is normally internal, but plugins can parse
`108`/`408` comment blocks and display their contents to players.

1. Inventory code-408 values and group them with their preceding code-108 command.
2. Search enabled plugin sources and event-handling code for the discovered comment tags,
   prefixes, or parsing APIs. Do not infer runtime visibility from Japanese text alone.
3. Choose `ENABLE` only when evidence shows that code-408 content is rendered or otherwise shown
   to players. Show representative plugin + event locators and an affected count.
4. Choose `SKIP` when values are editor notes, disabled-plugin metadata, or have no runtime
   consumer. If evidence is inconclusive, choose `SKIP` and state what must be playtested.
5. Tell the user to set the **Translate code 408 plugin/comment text** checkbox in Phase 1 to the
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

Emit this additional RPG Maker-only block:

### Block `rpgmaker_config`

Label the fence language as `rpgmaker_config`. Inside:

```text
CODE408 : ENABLE|SKIP - <runtime evidence, affected count, and confidence>

Dialogue : width=<full width> ; faceWidth=<code-101 face width> ; font=<px or keep current (measured px)> ; rows=<count>
List/Help: listWidth=<DazedTL width> ; font=<px or keep current (measured px)> ; rows=<count or varies>
Notes    : noteWidth=<DazedTL width> ; font=<px or keep current (measured px)> ; rows=<count or varies>

Evidence:
- <resolution/window/font/plugin locator, horizontal capacity, visible-row limit, and tested fit>

Exceptions / playtests:
- <variant windows, uncertain plugin behavior, or messages requiring pagination>
```

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

### Speakers analysis (for `speakers` block)

WolfDawn already tags who speaks. High-confidence nameplates (`literal_line1`) are always reshaped - nothing to decide.

The only flag is whether **low-confidence** first-line guesses (`speaker_src = literal_line1_lowconf`) are real speaker names for this game:
- short first line with **no** preceding face window
- might be a nameplate, or the start of dialogue / narration

Inspect a sample of those entries in maps / CommonEvent:
- `ENABLE` if low-confidence first lines are overwhelmingly real speaker names
- `SKIP` if many are dialogue or narration (reshaping would mislabel lines)

Do **not** emit RPG Maker flags (`INLINE401SPEAKERS`, `FIRSTLINESPEAKERS`, `FACENAME101`).

**Wolf `speakers` schema (use this instead of the shared RPG Maker flag list):**

```
Patterns detected:
- ...

Flag decisions:
LOWCONF_FIRSTLINE : ENABLE|SKIP - <one-line reason>

Examples:
- ...
```

### Glossary rules (for `glossary` block)

- Separator: plain hyphen-minus `-` only (never em/en dash).
- Descriptions entirely in English; refer to other characters by English name.
- Commit to one spelling - never `Sylfia / Sylphia`.
- Characters: gender, role, speech register, personality; note player-chosen names (variable / input).
- Worldbuilding: factions, lore locations (mentioned in dialogue but not map labels), unique systems/titles.
- Exclude: skill / item / weapon / armour names from `names.json`, generic RPG words, unnamed NPCs.

### Quirks rules (for `translation_quirks` block)

Find translation-only quirks, for example:
- Battle log / system messages with a fixed person or register
- Global dialect (archaic narration, cute speech markers game-wide)
- Recurring item/skill description style
- Unusual honorific habits

Exclude: wrap geometry, inject layout, `names.json` harvest, speaker LOWCONF checkbox, character name lists.

Output as short imperative bullets suitable to paste into `skills/quirks.md`.

### Game skill rules (for `game_skill` block)

Produce the per-game translation skill saved at `skills/game.md`.
DazedTL **merges this file into the translation system prompt** (before quirks).

**Translation Frame only** (one compact line per field; evidence-based):
- `世界観 (Theme / setting)` - genre, world type, core atmosphere
- `時代感 (Era / technology level)` - medieval / modern / sci-fi / historical / etc.
- `文体方針 (Register policy)` - overall English style
- `固有名詞方針 (Naming policy)` - invented names, titles, ranks, honorifics (high-level only)
- `神話・伝承 (Myth / folklore basis)` - **omit unless** evidence supports a specific tradition

Do **not** include voice-rules pointers, tool-boundary essays, file inventories, per-character register (glossary), or quirks bullets.

**Paths:**
- Game skill (API): ``skills/game.md``
- Quirks (API): ``skills/quirks.md``
- Optional custom API overlays: other ``skills/*.md`` except those two

<!-- /engine:wolf -->

---

## Output format

Emit **only** labeled fenced code blocks (plus a one-line heading before each block for navigation).
No essay outside the blocks.

### Block `glossary`

Label the fence language as `glossary`. Inside:

```
# Game Characters
Japanese (English) - description

# Worldbuilding Terms
Japanese (English) - description
```

### Block `speakers`

Label the fence language as `speakers`. Inside:

```
Patterns detected:
- ...

Flag decisions:
INLINE401SPEAKERS : ENABLE|SKIP — <one-line reason>
FIRSTLINESPEAKERS : ENABLE|SKIP — <one-line reason>
FACENAME101       : ENABLE|SKIP — <one-line reason>

Examples:
- ...

Face filenames (only if FACENAME101 ENABLE):
- ...
```

### Block `translation_quirks`

Label the fence language as `translation_quirks`. Inside: imperative bullet list only (no preamble).

### Block `game_skill`

Label the fence language as `game_skill`. Inside: markdown for `skills/game.md` (Translation Frame only).

```markdown
# <Game title> - Translation Frame

## Translation Frame
世界観 (Theme / setting) - <one compact line>
時代感 (Era / technology level) - <one compact line>
文体方針 (Register policy) - <one compact line>
固有名詞方針 (Naming policy) - <one compact line>
神話・伝承 (Myth / folklore basis) - <one compact line, or omit this line entirely if unsupported>
```

If known speakers were prepended in a `<known_speakers>` block above this skill, prefer those names in the glossary, then cross-check Actors.json for other major named actors.
