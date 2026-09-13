# Direct translation and efficient context preparation

Use this for Agent / Sub Direct Translation and local request compilation in either mode.
Direct work runs through the coding assistant's existing access; no DazedTL provider client, API key or hosted image generation is needed.
The user's instructions determine whether other agents may participate.
Translation mode never overrides a request to work alone.

## Establish the work units once

Use occurrence IDs tied to file/scene/field and retain source, speaker, surrounding source context and translation provenance.
Do not deduplicate dialogue globally by Japanese text alone: the same line can require different voice, gender or meaning.
UI terms can share an accepted decision when their meaning and rendering constraints match.
Maintain a source census independent of the extractor; a successful extraction loop does not prove completeness.
Keep unknown fields, unresolved source readings and excluded assets in an explicit ledger.

As a starting point, group about 200–300 short units by scene/speaker continuity, adapting down for long passages, dense controls or context/output limits.
Use smaller batches after a validation failure, and increase only when the measured result remains reliable.
Do not split a scene merely to hit a fixed batch size.
Translate names and terminology before dependent dialogue when that prevents repeated revision.

## Compile a sequence without rereading the same corpus for every batch

For one batch, the existing `context --sources ... --speakers ...` command remains available.
For many batches, write a plan containing the reviewed source payloads and exact source/guidance input paths relative to the game:

```json
{
  "complete": false,
  "inputs": [".dazedtl/len-method/work/source-units.json"],
  "batches": [{
    "id": "map001-scene01",
    "sources": {"line01": "はい。"},
    "speakers": {"line01": "リリ"},
    "source_context": ""
  }]
}
```

`instruction_key` is optional; choose an existing field template from the live `data/translation_contexts.json`, never invent a key.
Omit it when no field-specific template applies.
`speakers` and `source_context` are also optional, but provide known dialogue context.
Set `complete` true only when the plan includes every request needed for the selected translation scope and source coverage is independently audited.
A partial plan can support direct work, but it cannot be quoted as a complete API job.

```bash
python DAZEDTL_ROOT/scripts/len_translation.py context-many \
  --game-root /path/to/game --input /path/to/plan.json \
  --output /path/to/game/.dazedtl/len-method/api-requests.json
```

The helper compiles shared guidance and reference matches once for the sequence, then checks them again before returning.
Each batch context remains identical to the single-batch compiler output.
Changed dependencies abort compilation; this is an operation-local reuse, not a permanent cache of old instructions.
The saved plan binds source inputs, scope and the request compiler/templates to hashes.
The live helper never invokes a translation provider or exports credentials.

Consume the full system, glossary, SFX, field instructions, preceding source context, speaker-bearing `user` payload and advisory reference translations.
Retain the batch ID and `request_sha256` beside saved results and retry records.
Compact whitespace or use a lossless structured view to reduce overhead; do not truncate glossary notes, discard fields or summarize instructions to make a request fit.
Before adopting an optimized compiler/display, compare every resulting field and source ID against the existing path on representative batches, then benchmark it with the same data.
A faster context compiler does not establish a faster model or end-to-end translation rate.

## Save small results; validate at the right scale

Apply the shared source-checked dialogue pass before saving a batch. At cross-batch checkpoints,
read split exchanges together so reply continuity and voice survive the batch boundary.

After each batch, save accepted outputs atomically and check IDs, untranslated/empty results, placeholder multisets, protected codes and local layout bounds.
Do not recompute the whole source/reference census or run every global rendering check merely because another small batch finished.
As a starting point, perform a cross-batch review and checkpoint after roughly 1,000–1,500 units, or sooner when a glossary decision, renderer, extractor, control-code handling or source scope changes.
Run the complete structural/coverage checks at the final milestone and whenever a change invalidates their assumptions.
Use incremental validation only when the validator can identify its affected dependency set.

Cache validation evidence by source/output, glossary/context, validator version, renderer/font and target-build fingerprints as applicable.
Reuse an unchanged check's actual saved evidence; never manufacture a source/review fingerprint just to reuse an output.
If any relevant dependency changes, invalidate the affected downstream checks and report them pending until rerun.
For MV/MZ, all final writes still pass through `write-rpgmaker-json`; an external store or faster injector does not replace `_original` preservation.
Keep the same original command structure and save identity unless an explicitly validated adapter provides the required mapping.

Update the GUI and the user using `progress-reporting.md` at every saved milestone and at least every 10 minutes.
Before a long wait or QA segment, state the remaining scope, estimate basis and next visible checkpoint.
Use targeted native checks for changed behavior; do not turn an ordinary translation follow-up into an unrequested full playthrough.
