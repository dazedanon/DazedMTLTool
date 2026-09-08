# Field instructions

## system_ui

These are standard RPG Maker terms, type labels, and message templates.
Use the glossary and the exact field context to distinguish menu actions from parameter labels.
Preserve placeholders, quantities, and dynamic actor/item/stat references.
Battle message placeholders may include a subject inserted by the engine; do not supply an additional name or change grammatical person blindly.
Source duplicates are shared only within the same field family in this catalog.

## locale_ui

These are reviewed save/load and scene-skip interface labels from MUUI.
Translate the provided text into a concise label or complete confirmation question as appropriate.
Do not add hash delimiters: the original `#...#` lookup key is retained by the dictionary builder.
Confirm and Cancel must remain distinct actions.
Do not split button labels into multiple lines unless the measured widget supports it.

## plugin_ui

These are explicitly reviewed display parameters in `js/plugins.js`.
Return text only, with no JSON-in-string serialization or manual quote escaping.
The adapter preserves the surrounding plugin parameter structure.

## save_ui

These literals form runtime save-slot names and empty/occupied status labels.
The fragment for a numbered slot ends with a space before a runtime number.
Retain that separator and do not copy the JavaScript template expression into the target.
