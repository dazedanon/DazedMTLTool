# Repair WOLF Injection Check Issues

<task_context>
Repair the currently reported WOLF RPG Editor translation issues directly in:

`{{TRANSLATED_DIR}}`

You are authorized to edit those JSON files in place. Do not return replacement JSON for the user
to paste or import manually.

Use this game folder as read-only context when event meaning or runtime behavior is unclear:

`{{GAME_ROOT}}`

The complete issue list from DazedTL follows. Work through every `FIX` item. Review font-only
items, but preserve intentional Manual-wrap or names-wrap font changes.

{{ISSUES}}
</task_context>

## Required workflow

1. Open each listed JSON file and resolve its locator structurally:
   - Maps/CommonEvents: matching `scene.event`, optional `scene.page`, then line `cmd` and `str`.
   - Databases: matching group `type`, then line `row` and `field`.
   - Game.dat: matching line `key`.
2. Compare that entry's authoritative `source` with its current translated `text`.
3. Edit only the affected `text` value in place. Never edit `source`, IDs, commands, metadata,
   array order, object structure, or unrelated translations.
4. Preserve the existing English meaning and voice. This is control-code repair, not a broad
   retranslation pass.
5. Parse every edited JSON file after saving it. Continue until every listed `FIX` item has a
   concrete correction; do not merely describe proposed edits.

## WOLF repair rules

- Preserve executable control-code semantics, counts, and order. Codes may move only when English
  grammar requires it and the same runtime phrase remains affected.
- Distinguish an executable code such as `\i[31]`, `\!`, `\.`, or `\^` from a displayed literal
  example written with an extra backslash. Do not interchange them.
- Replace a literal backslash-plus-`n` with a real JSON newline only when the source has the
  corresponding physical line break. Never convert literal `\n` globally.
- Remove accidental backslashes before ordinary English quote marks. Let the JSON serializer
  escape quotes; the runtime string itself must not contain an added backslash.
- Keep an `@N` window prefix exactly once at the beginning when the source has one.
- If a shipped source code is unclosed, such as `\i[200`, the translation may add the obvious
  closing `]` only when all normalized control codes still match. Do not copy the malformed suffix.
- Font-only differences can be intentional. Leave a leading body font or translated font-size
  change intact when it came from wrapping and no other control behavior changed.
- Preserve blank-line groups and window prefixes. Do not collapse or invent display pages.
- Never bypass validation by deleting Japanese `source`, copying `source` into `text`, enabling a
  global drift flag, or changing the pristine originals.

## Completion

Report the files and locators actually changed, any font-only items deliberately left unchanged,
and any item that could not be resolved safely. Tell the user to return to DazedTL and run Check
again. Your response is only a summary; DazedTL does not need it pasted back. Do not claim success
for an item you only reviewed.
