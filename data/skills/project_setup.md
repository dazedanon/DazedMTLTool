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
| `game_skill` | Game identity, which files matter, pointer to `skills/quirks.md`, what the tool owns | Verbatim quirks list; verbatim glossary; restating formatting/honorific base policy |

Hard rules:
1. Per-character voice → `glossary` only.
2. Category-wide / cross-cutting voice → `translation_quirks` only.
3. Default honorifics policy is owned by the tool base prompt - only note **unusual** honorific habits in quirks.
4. `game_skill` **references** `skills/quirks.md` only; do not reprint those rules or cite legacy names like `translation_quirks.txt`.
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

Produce a durable IDE skill for this title saved at `skills/translation.md`:
- Short game identity (tone/genre/content notes)
- Which files matter for dialogue/DB in this repo
- A **Voice rules** section that points only at ``skills/quirks.md`` (authoritative)
- What not to change (codes, formatting - tool-owned via base prompt)
- Do **not** reprint quirks or the glossary

**Path names (required):**
- Voice quirks file: ``skills/quirks.md`` (never ``translation_quirks.txt`` or any other legacy name)
- This IDE skill file: ``skills/translation.md``
- Optional user overlays (if mentioned): other ``skills/*.md`` files except ``quirks.md`` / ``translation.md``

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

Label the fence language as `game_skill`. Inside: full markdown for `skills/translation.md`.

Required skeleton (fill in the blanks; keep the Voice rules path exactly):

```markdown
# <Game title> - Translation skill

## Identity
<1-3 sentences: tone, genre, content notes>

## Files that matter
- <dialogue / events paths for this repo>
- <database paths>

## Voice rules
Follow `skills/quirks.md` as the authoritative cross-cutting voice guide for this title.
Do not invent alternate quirk filenames.

## Tool boundaries
- DazedMTLTool owns formatting codes, wrap, line counts, and honorifics defaults via its base system skill.
- Per-character register lives in the glossary (`vocab.txt`), not here.
- Do not reprint quirks or glossary entries in this file.
```

If known speakers were prepended in a `<known_speakers>` block above this skill, prefer those names in the glossary, then cross-check Actors.json for other major named actors.
