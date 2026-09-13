# Translation voice and flow review

The shared translation instructions now treat natural English delivery and source-supported
character voice as part of fidelity. They permit contractions, fragments, idioms and reordered
clauses within existing text and control-code constraints, and require a dialogue read-through
followed by a Japanese source check before returning the translation. They preserve ambiguity,
emotional force, deliberate formality and awkwardness, without adding jokes or other embellishment.

The changes cover the shared API/Len prompt, RPG Maker/Wolf and generic setup, the Len translation
playbook, standalone plugin/script and post-update translation, RPG Maker QA handoffs and generated
reviewer instructions, and the blinded evaluation guidance. Character notes remain in the existing
glossary. Setup now requests concrete speech habits, listener/emotion shifts and concise supporting
examples instead of relying on personality or role labels. QA's evidence and independent-review
requirements remain in force. Its policy version advances so old review receipts do not silently
stand in for review under the revised instructions.

The dialogue pass is part of composing the initial translation; no automatic second API run is
added. Existing games acquire richer character notes when setup guidance is next updated. Refresh
compiled Len context after guidance changes; existing translations still need deliberate review
before their wording changes.

## SEQUEL thirst calibration

On 2026-09-13, reviewed three complete conversations in the local SEQUEL thirst ver.2.02
`data/CommonEvents.json`: event 114 (monster names), event 128 (Uula's confinement), and event 441
(whether to confront dangerous monsters). These contain 33 message blocks across five speakers.
Read the preserved Japanese and current English in order with the game's glossary voice notes.
All 33 preserved Japanese blocks exactly match the corresponding message blocks on the game's
`original` branch. The similarly named second local folder is also translated and was not used
as an independent Japanese baseline.

This was a local editorial comparison under the revised guidance, not a blind model benchmark or
full-game QA. The examples below are candidates for review; no game files or game guidance were
changed. They have not undergone independent editorial approval or in-game fitting.

Message numbers below are one-based within each common event. Line breaks are shown with `<br>`.

| Source location | Japanese | Existing English | Candidate |
|---|---|---|---|
| Event 114, message 3, Prim | 綺麗ですしね、見た目。<br>気持ちは分かります。 | They do look beautiful.<br>I can understand the feeling. | They do look beautiful.<br>I can see why. |
| Event 128, message 5, Uula | それでも罪人扱いには納得いってません。 | I still don't accept being treated like a criminal. | I'm still not okay with being treated like a criminal. |
| Event 441, message 3, Dire | 迂闊に手を出さん方がよさそうだ。 | Best not pick a fight carelessly. | Best not take them on lightly. |
| Event 441, message 12, Uula | 肝心なとこを聞き逃す感じですよね。 | You seem to miss the important part. | You seem to have missed the point. |

Meaning, voice and flow were considered separately:

- Prim's reaction refers back to tourists letting their guard down around beautiful monsters.
  The candidate retains her understanding without the vague English calque "the feeling." It
  does not invent a new reason for their behavior or add sarcasm to this sympathetic remark.
- Uula's objection remains a complaint about being treated as a criminal despite comfortable
  confinement. The candidate uses conversational wording consistent with her glossary's colloquial
  politeness. It does not claim she was innocent or intensify the complaint. The existing wording
  is intelligible; this is a register candidate, not an independently confirmed QA defect.
- Dire's advice remains cautious and terse. "Take them on lightly" makes the scope of the warning
  idiomatic without adding a claim about the monsters' strength or predicting certain defeat.
- Uula's closing observation refers to the point Nazuna has just missed. The candidate retains
  the source's impression/softening through "seem," uses the English idiom "missed the point,"
  and avoids adding habitual frequency such as "always" or "again."

The same comparison retained Outoku's "It cannot be helped. ... Ignorance is no excuse" in event
128 and Prim's "Might we discuss whether we should go this way at all?" in event 441. Their
formality supports the source: Outoku's authoritative register and Prim's pointed politeness.
These examples argue for context-sensitive delivery, not blanket casualization or rewriting every
grammatical sentence. Three conversations cannot establish improvement across the whole release.

## Verification

- Focused prompt, Len context, RPG Maker QA and shipped-file tests: 29 passed.
- Core: 780 tests, 5 existing skips; 1.981s against an 8s ceiling.
- Integration: 130 tests; 8.054s against a 20s ceiling.
- Existing runtime and test-count budgets passed without changes. No new tests were added to
  freeze prompt wording; existing tests cover assembly, context reuse and QA lifecycle behavior.
- Both edited skill entrypoints passed the skill validator. Changed shipped assets passed
  `git check-ignore`; `git diff --check` passed.

These checks verify instruction delivery and workflow integrity, not linguistic quality across
models or the full game. UI behavior and provider execution were not changed.
