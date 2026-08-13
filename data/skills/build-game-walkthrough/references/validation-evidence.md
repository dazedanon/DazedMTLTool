# RPG Maker MV/MZ Walkthrough Evidence

Use this manifest contract with `scripts/validate_walkthrough.py`. Keep game-specific facts in
`<game>/.dazedtl/walkthrough/evidence.json`; never add them to the shared validator.

## Top-level fields

- `schema_version`: use `1`.
- `badges`: map guide badge IDs to exact player-facing names.
- `badges_reviewed`: set `true` only after comparing every declared mapping with executable game
  data. Never bootstrap this flag from the walkthrough itself.
- `acquisitions`: declare reverse-indexed collectible or unique-reward groups.
- `switch_sets`: declare counted world objects whose persistent state is an ordinary switch.
- `requirements`: declare exact-count gates such as “complete all four entries.”
- `requirements_reviewed`: set `true` only after confirming the guide contains no undeclared
  non-acquisition exact-count gate; otherwise an empty requirement set remains unresolved.
- `choices`: declare every named material choice and its complete branch outcomes.
- `achievement_switch_sets`: declare event-based achievement catalogs represented by switch ranges.
- `achievement_unlocks_reviewed`: set `true` only after comparing the guide's unlock explanations
  with the indexed achievement award conditions.
- `unresolved`: list navigation, strategy, runtime, or other claims that still require live play.

## Acquisition groups

Use one entry per counted database object:

```json
{
  "name": "Exact Database Name",
  "kind": "item",
  "expected_total": 12,
  "count": "quantity",
  "badges": {"prefix": "I", "first": 1, "last": 12, "width": 2},
  "sources": [
    {
      "badge": "I01",
      "source": {
        "file": "data/Map001.json",
        "event_id": 4,
        "page_index": 0,
        "command_index": 9
      }
    }
  ]
}
```

Use `count: "commands"` only when each qualifying command represents one counted acquisition
regardless of quantity. Omit `sources` when only the total and badge sequence are proven; the
validator will correctly leave route order unresolved.

For fixed treasures, campfires, and similar world objects represented by persistent switches rather
than a repeated database item, use a `switch_sets` entry with `id`, `expected_total`, the complete
`switch_ids` list, and exact `guide_phrases`. The validator requires every switch to be named in
`System.json` and turned ON by native event data. Never infer the list from display numbers alone;
aliases and copied map events are common.

## Exact-count requirements

For non-item gates, record an `id`, `expected_total`, exact source event, required guide phrases,
and one entry per required variable. The validator proves each entry by finding the source event's
inverse conditional followed by an early exit—for example, `variable 83 != 1000` followed by
“Exit Event Processing” proves continuation requires `variable 83 == 1000`. Do not use this form
when the event does not have a mechanically equivalent guard.

## Material choices

Record the exact translated choice labels, source event, starting and resulting switch state,
complete reward scope, shared outcomes, and every branch's fights, rewards, and other outcomes.
The validator follows native common-event calls, interprets page conditions and `If`/`Else`, and
reverse-indexes rewards. Transfers or script-driven state changes that it cannot close remain
unresolved.

Every player-facing callout must use `**Choice Ahead — Player-Facing Name:**`. Unnamed callouts are
errors because they cannot be paired deterministically with evidence. Branch `label` values must
copy the translated in-game options exactly, including articles and qualifier text.

## Event-based achievement catalogs

When achievements are ordinary switches rather than plugin definitions, use
`achievement_switch_sets` with `id`, `first_switch_id`, `last_switch_id`, `expected_total`, exact
award-event `source`, and `guide_phrases`. The validator proves that every switch is named and is
checked at that source. Set `achievement_unlocks_reviewed` only after the individual guide
conditions have also been compared with the enabling events; the catalog total alone is not enough.

## Coverage meanings

- `verified`: the claim matches executable data or reviewed evidence.
- `contradicted`: the claim conflicts with evidence; fix it before publishing.
- `unresolved`: stronger tracing or live play is still required.
- `unsupported`: static analysis found behavior it cannot interpret safely.
- `not_applicable`: the project does not use that system.

Accept `passed_with_unresolved` only when every checklist item is retained and clearly disclosed.
Never describe it as fully verified. Re-run the validator after rebuilding HTML so publication
parity, coverage totals, and `<game>/.dazedtl/walkthrough/live-play-checklist.md` stay current.
