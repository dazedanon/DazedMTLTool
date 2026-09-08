# Translation handoff and later checks

These items do not prevent completing preparation. They record concrete limits
and work to resolve before translating the affected unit or certifying a patch.
No code changes or API work are requested by this document.

| Item | Current disposition | Next action |
|---|---|---|
| HOLY-MARK / `CODE:28:154` | Hold one help definition | Choose source-faithful 0.5 or a documented gameplay-accurate 0.75 correction after final coefficient review. The current draft makes neither substitution. |
| MERCHANT-4 / `CODE:243:47` | Hold undisplayed fourth record; source context retained | `obj_dialog_Step_0:11` clears the dialogue at index 4. Decide later whether a translation-only patch preserves this source behavior or a separately scoped game fix exposes the fourth line. End the visible third record naturally without importing the held fourth record's content. |
| RICOCHET / `CODE:28:99` | Hold apparently dormant help | Find a description that supplies 跳弾 before claiming release visibility. Do not rename 魔法追撃 to this term just to make help appear. |
| HELP-KEYS | 17 planned exact technical overrides | Apply alongside translated display terms, then compare helper-match sets at every skill/equipment rank. Validate both missing and extra matches. |
| ENGLISH-WRAP | Layout verification pending | `scr_newline` and merchant typewriter wrap by character after width overflow; inspect English words, panel heights, longest names and all three equipment-46 inserts. Consider word-aware wrapping only if later scope calls for it. |
| SIGNED-HP | Assembly strategy prepared | Review both sign branches in the stage tooltip using the nonempty prefix/suffix plan; keep arithmetic unchanged. |
| EXTRA-DELIMITER | One planned punctuation site | The CJK-letter census omitted the Japanese enemy-list separator. Apply the supplemental per-site comma-space plan; do not replace the original pooled string globally. |
| NAME-SPELLINGS | Editorially locked | Flavia, Irara and Luminia are local editorial spellings. Credits provide Japanese names; no official English name list was present. |

Text-only counts do not cover lettering baked into textures. No image-text edit
or image pass is prepared. Font face identifiers and resource names stay intact.
This project is prepared for English, but runtime fitting and final residual
Japanese checks require the later translated build.

