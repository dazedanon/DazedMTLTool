# Localize an Applied Game Update

<task_context>
Work directly in the translated game at:

`{{GAME_ROOT}}`

Review the already-applied official game update registered as version `{{VERSION}}`.

Use all portable translation guidance available for this game. Read these files before editing:

- Glossary: `{{GLOSSARY_FILE}}`
- Game translation frame: `{{GAME_SKILL_FILE}}`
- Cross-cutting voice and formatting quirks: `{{QUIRKS_FILE}}`
- Any additional Markdown overlays in: `{{GAME_SKILLS_DIR}}`

Treat curated glossary choices and compatible established translations in the game as authoritative.
Use the game frame for setting, register, and naming; use quirks and custom overlays for voice,
formatting, and project-specific rules. If a listed file is absent, continue with the remaining
evidence and report the missing context.

The user authorizes surgical edits to the translated worktree and its portable guidance files when
the workflow below justifies them. Preserve unrelated user changes. Do not switch branches, edit the
`original` branch, reset or clean the worktree, rewrite history, or create a commit.
</task_context>

## Required outcome

- Translate every player-visible source-language string introduced, restored, or replaced by the
  applied official update when its location can be established safely.
- Fix mistranslations, awkward wording, terminology drift, voice drift, formatting damage, and
  update-caused inconsistencies in the affected content.
- Match the target language, fluency, tone, characterization, spelling, capitalization, and naming
  already established by the rest of the translation.
- Preserve executable behavior, identifiers, data structure, control codes, placeholders, escape
  sequences, line/page boundaries, and intentional formatting.
- Leave unrelated pre-existing translation content alone except for directly related repeated terms
  that must be aligned to keep the update consistent.

## Workflow

1. Inspect the repository and preserve its state.
   - Record the current branch and `git status` before editing.
   - Locate the most recent translated-branch commit whose subject begins with `patch:` and whose
     message contains a `DazedTL-Version` trailer matching `{{VERSION}}`. A baseline or translation
     registration commit is not an applied update.
   - Use that commit, its parent, and its changed-file diff to establish the update scope. Include
     files replaced wholesale by official-first conflict resolution, not only cleanly merged hunks.
   - If the matching update commit or a safe file scope cannot be established, stop without editing
     and report the ambiguity.

2. Build translation context.
   - Read every available guidance file listed above in full.
   - Inspect established translations for the same characters, terms, UI roles, event families, and
     nearby scenes. Search related content across the game when a line cannot be translated reliably
     in isolation.
   - Resolve conflicting evidence in this order: explicit user-curated glossary or skill guidance,
     clearly established usage in the current translation, then the source text in context. Report
     any material conflict that cannot be resolved safely.

3. Inventory update-touched text before editing.
   - Review added and changed text-bearing files and changed sections from the update commit.
   - Find source-language residue in player-visible dialogue, narration, choices, descriptions,
     names, menus, help, system messages, and other runtime text.
   - Distinguish visible text from code, comments, internal keys, filenames, metadata, debug-only
     strings, and language that is intentionally displayed untranslated.
   - For a whole-file replacement, compare the new file with its pre-update translated counterpart
     so surviving translations are retained and newly official text is not missed.

4. Translate and repair in place.
   - Produce natural, context-aware target-language writing rather than a literal or isolated
     machine translation.
   - Preserve each speaker's established voice, relationships, pronouns, address forms, and level
     of formality. Preserve UI brevity and gameplay meaning where applicable.
   - Reuse glossary spellings exactly. Check repeated occurrences and grammatical variants before
     deciding that two different renderings are intentional.
   - Edit only player-visible values and the smallest directly related consistency fixes. Never
     alter source/reference fields, IDs, command types, array order, object shape, or unrelated data.
   - Keep control-code semantics and counts intact. Move a code only when target-language grammar
     requires it and the same runtime span remains affected.
   - Preserve MV/MZ `\ac` center alignment. Normalize `\ac` directly before Latin text to `\ac `,
     even after a newline, because RPG Maker otherwise consumes the following word as part of the
     escape-code name (`\acWhat` hides `What`). Repair it by inserting the delimiter, not by deleting
     the centering code. A following control such as `\ac\C[...]` is already safely delimited.
   - Do not corrupt or guess inside opaque binary/container formats. Report those files and identify
     the extraction or game-specific tool needed for a safe follow-up.

5. Keep portable guidance consistent.
   - Add a glossary entry only when the update establishes a reusable name or term and the chosen
     translation is supported by context. Preserve existing sections and unrelated entries.
   - Update `quirks.md`, `game.md`, or a custom overlay only when the update provides durable,
     cross-cutting evidence that future translations need. Make the smallest compatible edit and do
     not replace curated guidance wholesale.
   - Do not change established guidance merely to rationalize a one-off wording choice.

6. Validate the result.
   - Parse every edited structured file and run the cheapest relevant project or engine validation
     available in the game folder.
   - Review the final diff for scope, syntax, control-code preservation, unintended whitespace, and
     unrelated changes.
   - Search the update-touched player-visible scope again for remaining source-language residue.
     Explain every intentional remainder or unsafe item instead of silently skipping it.
   - Confirm that the current branch and pre-existing user changes are preserved and that no commit
     was created.

## Completion

Summarize the update files and guidance files changed, the important consistency decisions made,
validation performed, intentional untranslated items, and anything that still needs manual or
engine-specific review. Do not claim complete coverage when any update-touched text-bearing file
could not be inspected safely.
