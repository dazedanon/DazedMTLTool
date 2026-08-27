---
name: setup-generic-game
description: Inspect a game project with an unknown or custom file structure and create or update its DazedTL glossary, translation quirks, and game translation frame. Use when DazedTL's engine-specific Workflow does not describe the project reliably.
---

# Set up generic DazedTL game context

Work in this project root:

`{{GAME_ROOT}}`

The file structure, engine, dialogue representation, and naming conventions are unknown. Discover
them from the project instead of assuming RPG Maker, WOLF, JSON, or any fixed event schema. Make a
reasonable evidence-based pass over the material that is actually accessible.

## Outcome

Create or update these three portable guidance files in one run:

- `.dazedtl/glossary.txt`
- `.dazedtl/skills/game.md`
- `.dazedtl/skills/quirks.md`

Do not translate or broadly edit game files. The three guidance files above are the only intended
edits. Preserve compatible user-authored guidance and make surgical changes rather than replacing
an existing file wholesale.

## Discover the project

Start with a bounded inventory of file names, extensions, sizes, and directories. Ignore version
control metadata, caches, generated build output, and `.dazedtl` except when reading the existing
guidance files. Identify likely player-visible text using evidence from the project:

- Prefer manifests, schemas, source code, resource loaders, and small structured databases that
  explain how text is stored or displayed.
- Search for Japanese text across likely text-bearing files. Read small high-value files fully and
  sample large collections across early, middle, and late portions instead of reading everything
  sequentially.
- Inspect enough local context around a match to distinguish dialogue, narration, UI text,
  identifiers, developer comments, and unused data.
- Follow project-specific references when they reveal speakers, sequence, placeholders, control
  codes, or runtime display behavior. Do not infer a rigid schema from a few coincidental fields.
- Treat opaque archives and proprietary binaries as inaccessible unless the repository already
  contains a safe, obvious extractor or decoded representation. Do not invent content to fill gaps.

Use any existing translation as supporting evidence, but treat original Japanese as authoritative.
If evidence is sparse, keep the guidance conservative and explicitly report the limitation.

## Keep each file focused

### Glossary

The game-specific section of `.dazedtl/glossary.txt` owns stable proper names and terminology:

- Named characters, roles, gender or pronouns when supported, relationships, and per-character
  speech register.
- Factions, locations, titles, coined systems, recurring objects, and worldbuilding terms whose
  consistent English rendering matters.
- Use entries shaped like `Japanese (English) - concise English note` and commit to one spelling.

Do not put global prose rules, formatting instructions, speculative plot claims, generic words, or
one-off lines in the Glossary. If the file contains DazedTL's base-glossary separator, preserve the
separator and everything below it byte-for-byte.

### Game frame

`.dazedtl/skills/game.md` owns a compact translation frame for the whole title. Include only fields
supported by evidence, normally one short line each:

- Theme / setting
- Era / technology level
- Overall English register
- High-level naming policy
- Myth or folklore basis, only when a specific influence is supported

Do not repeat character entries, quirks, file inventories, research notes, or instructions for the
coding agent. DazedTL merges this file into the translation system prompt before Quirks.

### Translation quirks

`.dazedtl/skills/quirks.md` owns short imperative rules that apply across multiple passages, such
as a consistent narration person, global dialect, description style, recurring catchphrase or
wordplay strategy, or unusual honorific behavior. Require multiple supported examples or an
explicit callback before making a pattern global. Include distinctive Japanese anchors in a
recurring joke or catchphrase rule when available.

Do not put per-character register, isolated jokes, glossary lists, inferred file structure,
wrapping limits, or unsupported formatting rules here.

## Apply and verify

1. Read all existing guidance before editing.
2. Create `.dazedtl/skills/` and missing files when necessary.
3. Merge only evidence-supported additions or corrections into each file.
4. Reread all three saved files. Confirm that intended guidance is present, unrelated content was
   preserved, and the Glossary base section is unchanged.

Report the project areas inspected, important limitations, and whether each guidance file was
created, updated, or left unchanged. Do not return replacement blocks for the user to paste; write
the files directly.
