# Legacy cached-display migration

The generated `save_compat_append.js` is appended once to the translated
`tyrano/plugins/kag/kag.menu.js`. It introduces no new archive entry and does not
remap scenario indices. Parent integrates and performs live QA; this subtask did
not write the baseline save or deploy game content.

## Evidence and permitted changes

The actual baseline slot0 is `scene1.ks`, saved index8, current line9. Its message
is a saved JSON DOM tree: message0/message_inner/P/current_span/plain SPAN with
individual `.char` spans. The speaker is a separate `chara_name_area` P. At the
baseline position, migration renders `Yaaay! It's finally over!` and
`Small-Time Ytuber Himarii`.

`kag.menu.js`'s `loadGameData` restores saved `data.layer` and `data.stat` before
resuming the scenario; replacing script text alone cannot refresh that screen.
`tyrano/libs.js`'s `makeElementFromSave` renders child text leaves and retained
tag/style/class/attribute data. The helper therefore changes only recognized
display nodes, retaining outer and current_span styles and copying the original
simple per-character span style onto the replacement characters. It preserves
glyph/image children outside those text runs.

Exact mutation allowlist:

- `stat.current_message_str`, `stat.current_save_str`, slot `title`.
- `stat.current_speaker`, only for the four literal display-name mappings and
  only when the value is not a registered key in `stat.charas` or `stat.jcharas`.
- Literal nameplate text and its text leaf, only inside message layers.
- Plain renderer-created character runs, only below `message_inner` in
  `map_layer_fore.messageN` / `map_layer_back.messageN`.
- Plain visible leaves in `layer_free` nodes whose `data-event-tag` is `glink`.

It does not replace strings in arbitrary saved fields, character IDs, `charas`,
`jcharas`, variables, counters, labels, macros, call stacks, asset paths,
coordinates, event parameters or other attributes. `data-event-pm` stays verbatim,
including its original Japanese display copy and technical jump target. Only the
visible choice leaf changes. Backlog caption markup permits only inner text of
the engine's known `backlog_chara_name` and `backlog_text` elements to change;
their opening tags and classes remain verbatim. A literal-name prefix in a plain
caption is translated even when the body is already English. This covers the
mixed snapshot produced by an old migrated save advancing to a new English line.

`getSaveData` wraps the engine getter to refresh slot captions in the returned
in-memory object, including observed empty-slot Japanese labels. It makes no
storage calls. File hashes and anti-tamper identifiers are not rewritten. The
existing engine may subsequently save its normal in-memory data through its own
authorized save operations.

## Data generation

`save_compat_generate.cjs SOURCE_APP PAYLOAD COMPLETE_PACKET COMPLETE_REPLY OUTPUT`
loads the original and injected scenarios through this game's KAG parser and
requires matching indices/element types/source lines. It records source/English
prose pairs at exact scenario indices. Duplicate source strings with differing
English use the current scenario and current page bounds derived from parser
indices; only source strings having one English value globally qualify for the
fallback. Ambiguous same-page matches whose English differs are left alone.

Nameplates and choices come from the reviewed manual packet/reply. Placeholder
tokens are restored before HTML entities are decoded to the actual saved DOM
text. This matters for the source choice `深くゆっくり&nbsp;`, whose saved `.text`
is `深くゆっくり\u00a0`. No translation sentinel is allowed in the generated helper.
Choice maps contain actual NBSP, not the masked placeholder or literal entity.

If parent revises injected prose or manual replies, regenerate the append before
building the archive. Regeneration overwrites this generated file; installation
must append it once to a clean translated kag.menu.js, not append on top of an
already appended helper.

## Verification

`save_compat_test.cjs` executes the generated shipping code itself in a JS VM,
using the real baseline decoded save as the fixture. The source save is read only;
the test asserts its before/after SHA-256 is identical. Parent QA changes other
slots in that file between runs, so the report records each run's current hash.

Passing evidence in `save_compat_test.json` covers:

- Actual saved message, nameplate, combined slot caption and markup caption.
- Every stat key outside the three explicitly allowed display keys unchanged.
- Every non-display slot key unchanged, including index, date, image and state.
- Every serialized DOM event attribute unchanged.
- Normal choice and the masked/NBSP choice with Japanese event parameters.
- A Japanese technical variable key and its numeric value unchanged.
- Saved-root hash retained by getSaveData; old empty-slot captions refreshed.
- Repeated migration idempotent.
- The actual mixed slot2 generated by parent's live load/advance/save sequence.
- Simulated old-save load, next English line, and new save-caption construction;
  literal current_speaker stays English while registered-name fixtures are refused.
- All **425** generated source text occurrences resolve to intended English in
  real-shaped saved message fixtures, including all **4** ambiguous repeated
  prose occurrences through scenario/index scope.

The helper deliberately declines unexpected saved DOM shapes, rich per-character
decorations or unresolved ambiguous text. The real baseline has the recognized
plain shape. Parent's live load, bubble and choice screens remain the final
rendering check.
