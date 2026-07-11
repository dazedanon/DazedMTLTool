# DazedMTLTool — Project Setup

You are analysing a Japanese game project to produce configuration artifacts for DazedMTLTool.
Work in the game repository. Scan files; do not invent content you did not see.

---

## Task

In **one pass**, discover everything needed for translation setup and emit the labeled output blocks below.
Do **not** translate the game. Do **not** rewrite formatting codes, wrap widths, or tool pipeline settings.

Default: emit **all four** blocks.
Regenerate mode: if the user asks for only one block (`glossary`, `speakers`, `translation_quirks`, or `game_skill`), emit **only** that block using the same schema and exclusivity rules.

---

## Ownership (no duplication)

| Block | Owns | Must NOT include |
|-------|------|------------------|
| `glossary` | Named characters (gender, role, **per-character** speech register) + worldbuilding terms | Global dialect / person rules; honorific policy; speaker-format flags; formatting |
| `speakers` | Tool flag ENABLE/SKIP + short evidence | Character bios; quirks; full glossary |
| `translation_quirks` | Cross-cutting voice rules (battle-log person, global dialect, item-description style, **unusual** honorific habits) | Per-character register; "always keep -san" (tool base prompt already does); codes/wrap/line counts; speaker flags |
| `game_skill` | **Translation Frame** for the API (theme / era / register / naming / optional myth) saved at `skills/game.md` | File inventories; quirks bullets; glossary; per-character register; IDE scaffolding; restating base honorific/formatting policy |

Hard rules:
1. Per-character voice → `glossary` only.
2. Category-wide / cross-cutting voice → `translation_quirks` only.
3. Default honorifics policy is owned by the tool base prompt - only note **unusual** honorific habits in quirks.
4. `game_skill` is the title's Translation Frame for the translation API - keep it compact; do not reprint quirks or glossary.
5. `speakers` is config, not lore.

---

## Shared scan strategy

Map / event files can be huge. Do **not** read them sequentially end-to-end.

1. Read small DB files in full first (richest, always small).
2. For large event/map files: **search/grep**; sample early story maps; stop when patterns stabilize.
3. One scan feeds all four blocks - do not rescan from scratch per block.

<!-- engine:rpgmaker -->

### RPG Maker file strategy

**DB (read in full):**
- `Actors.json` (mandatory for major characters, actor IDs, `\\N[n]` mappings)
- `Classes.json`, `Troops.json`, `Skills.json`, `Items.json`, `Armors.json`, `Weapons.json`, `States.json`, `System.json`

**Events (grep / sample):**
- `CommonEvents.json`, `Troops.json`, `Map001.json`–`Map010.json` (early maps first)
- Prefer code `401` dialogue + nearby `101` speaker/name params; `405` scrolling text when present
- Speaker markup evidence: `【Name】`, `[Name]`, `Name：`, `\\n<Name>`, `\\k<Name>`, colour-wrapped name lines

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
DazedMTLTool **merges this file into the translation system prompt** (before quirks).

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

<!-- /engine:rpgmaker -->

<!-- engine:wolf -->

### Wolf file strategy (stub)

When analysing a WolfDawn / WOLF project later: use `wolf_json/` extracts (`names.json`, DB sheets, map/common scenes). Prefer foundation DB + narrative sheets; grep large map dumps. Same four-block ownership rules apply.

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
