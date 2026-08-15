# Walkthrough Evidence Contract

Use this schema with `scripts/validate_walkthrough.py`. The evidence ledger exists to make player-facing route instructions traceable to the translated game's executable sources, not to make technical IDs part of the directions.

## Contents

- Top-level schema
- Project language context
- Route structure
- Route claims
- Optional Content groups and entries
- Boss groups and entries
- Scenes & CG catalog, groups, and entries
- Source snapshots
- Markdown and HTML binding
- Verification boundary
- Research rules

## Top-level schema

Create `<game>/.dazedtl/walkthrough/evidence.json`:

```json
{
  "schema_version": 12,
  "milestone": "complete-four-view-walkthrough",
  "project_context": {},
  "route_structure": {},
  "route_claims": [],
  "optional_content": {
    "source_label": "Game journal and executable event lifecycle",
    "groups": [],
    "entries": []
  },
  "bosses": {
    "source_label": "Battle events, troop phases, enemy and skill records, and fixed outcomes",
    "groups": [],
    "entries": []
  },
  "scenes_cg": {
    "source_label": "Player-facing scene catalog, live triggers, unlock state, and viewer dispatch",
    "catalog": {},
    "groups": [],
    "entries": []
  }
}
```

The completed milestone supports one claim per Main Route step, one record per Optional Content entry, one dossier per boss, and one record per illustrated scene/catalog entry. Keep claim, group, entry, boss, scene, and source IDs stable after publication so saved hashes and review notes survive regeneration.

## Project language context

Snapshot the canonical glossary and quirks files when they exist. This proves which project language rules were current when the guide was authored:

```json
{
  "project_context": {
    "glossary": {
      "file": ".dazedtl/glossary.txt",
      "sha256": "64-lowercase-hex-characters"
    },
    "quirks": {
      "file": ".dazedtl/skills/quirks.md",
      "sha256": "64-lowercase-hex-characters"
    }
  }
}
```

Use a SHA-256 digest of the exact file bytes. Omit a key only when its canonical file does not exist. The validator rejects missing, stale, renamed, or invented snapshots, checks gendered character entries for conflicting nearby pronouns, and flags plausible one-letter drift from longer canonical character names in player-facing prose.

The glossary and quirks are authoritative editorial context, not executable route evidence. Do not cite them to prove that a battle is mandatory, an item is awarded, a door opens, or a story branch progresses. Continue to cite the relevant event and database sources for those facts.

## Route structure

Bind Main Route organization to the hierarchy the player actually sees:

```json
{
  "route_structure": {
    "mode": "chapters-and-sections",
    "source_label": "Game chapters and in-game objectives",
    "chapters": [
      {
        "id": "prologue",
        "label": "Prologue — Awakening",
        "section_ids": ["objective-reach-town"],
        "sources": [
          {
            "id": "prologue-boundary",
            "type": "event-command",
            "file": "data/Map001.json",
            "event_id": 2,
            "page_index": 0,
            "command_index": 8,
            "expected": {"code": 121, "parameters": [20, 20, 0]},
            "supports": "The opening event enables the game-authored Prologue story phase."
          }
        ]
      }
    ],
    "sections": [
      {
        "id": "objective-reach-town",
        "label": "Reach Town",
        "claim_ids": ["leave-opening-room"],
        "sources": [
          {
            "id": "objective-reach-town-label",
            "type": "file-excerpt",
            "file": "js/plugins.js",
            "contains": "DestinationText\\\":\\\"Reach Town",
            "supports": "The active destination system names this objective Reach Town."
          }
        ]
      }
    ]
  }
}
```

`mode` is `chapters-and-sections` or `sections`. Use `chapters-and-sections` when the game has a source-backed Prologue/chapter/story-phase layer, then nest exact objectives or neutral story sections beneath it. Use `sections` when no higher chapter layer exists. An unused chapter plugin does not disprove a chapter system; audit scenario switches, variables, objective-group transitions, title cards, and their activation events before choosing the mode. Conversely, numbered region assets alone do not prove narrative chapter boundaries.

In `chapters-and-sections` mode, every section must belong to exactly one chapter. In both modes, every claim must belong to exactly one section. Keep IDs stable, use exact game-authored labels when available, and give every chapter and section at least one source snapshot proving its label or boundary.

## Route claims

Each claim has:

- `id`: globally unique kebab-case identifier.
- `kind`: one of `navigation`, `objective`, `pickup`, `equipment`, `boss`, `choice`, or `gate`.
- `status`: `verified`.
- `guide_phrases`: one or more exact, short player-facing phrases that must occur in both Markdown and published HTML.
- `sources`: one or more source snapshots.

Example:

```json
{
  "id": "leave-opening-room",
  "kind": "navigation",
  "status": "verified",
  "guide_phrases": [
    "Speak to Mina beside the front door, then leave through that door."
  ],
  "sources": [
    {
      "id": "opening-choice",
      "type": "event-command",
      "file": "data/Map001.json",
      "event_id": 4,
      "page_index": 0,
      "command_index": 12,
      "expected": {
        "code": 201,
        "parameters": [0, 2, 8, 11, 2, 0]
      },
      "supports": "Using the front-door event transfers the party to the named town map."
    }
  ]
}
```

Keep `guide_phrases` narrowly tied to what the cited sources prove. Split a step when one sentence combines unrelated claims that require different evidence or confidence.

## Optional Content groups and entries

`optional_content` is the verified catalog of actionable detours and postgame content. It is not a transcription of one quest menu: build it only after reconciling configured journals and plugins with the map events, common events, scripts, state writes, requirements, and rewards that implement them.

Group entries by the Main Route chapter in which they first become available, or by one specific route anchor when no chapter is appropriate:

```json
{
  "optional_content": {
    "source_label": "Game journal and executable event lifecycle",
    "groups": [
      {
        "id": "optional-prologue",
        "label": "Prologue opportunities",
        "route_chapter_id": "prologue",
        "entry_ids": ["lost-delivery"]
      },
      {
        "id": "optional-postgame",
        "label": "Postgame investigations",
        "route_anchor_id": "finish-the-story",
        "entry_ids": ["sealed-archive"]
      }
    ],
    "entries": [
      {
        "id": "lost-delivery",
        "title": "Lost Delivery",
        "kind": "side-event",
        "status": "verified",
        "route_anchor_id": "reach-town-square",
        "route_anchor_position": "after",
        "prerequisite_entry_ids": [],
        "guide_phrases": [
          "Speak to Mina in the town square, recover the parcel from the riverside storehouse, then bring it back to her."
        ],
        "sources": []
      }
    ]
  }
}
```

Each group has:

- `id`: a globally unique kebab-case identifier.
- `label`: a player-facing availability heading.
- `entry_ids`: one or more Optional Content entry IDs, each assigned to exactly one group.
- Exactly one availability binding: `route_chapter_id` or `route_anchor_id`.

Each entry has:

- `id`: a globally unique kebab-case identifier, distinct from route and group IDs.
- `title`: the canonical player-facing journal or event name.
- `kind`: `side-event`, `optional-area`, `service-unlock`, `activity`, `collection`, or `postgame-event`. Boss dossiers and relationship/CG scene entries remain in their dedicated views.
- `status`: `verified`.
- `route_anchor_id`: the Main Route claim where the entry first becomes actionable, not merely where its data record exists.
- `route_anchor_position`: `before` when the notice must appear before the player undertakes the anchor step, or `after` when completing that step creates the availability state.
- `prerequisite_entry_ids`: the complete direct dependency list, or an empty list.
- `guide_phrases`: one or more exact actionable phrases present in both Markdown and HTML.
- `sources`: globally unique source snapshots proving the major lifecycle.

The source set must establish the entry's real start, important intermediate updates or branch convergence, requirements, completion, and meaningful fixed outcomes. Cite database records as well as event commands when an item or reward is identified only by ID. For a long chain, prefer several focused sources to one incidental match. If the game exposes a journal title but no reachable start or completion, investigate and classify it in private research instead of publishing it as a complete player route.

Dependencies describe other Optional Content entries. Story, party, region, and postgame gates stay in player prose and evidence, while `route_anchor_id` and `route_anchor_position` establish the first Main Route cross-link. A prerequisite does not replace the anchor: both must be correct. Prove earliest availability by tracing every start predicate, then check the previous Main Route claim and identify the still-unsatisfied gate. The first time the recommended route happens to visit an area is not proof that content was unavailable earlier.

## Boss groups and entries

`bosses` is the reconciled encounter catalog, not a dump of every enemy whose note contains a category tag. Include source-backed story bosses, bosses reached through Optional Content, rematches, and the game's explicit Apex/superboss category. Combine forms and repeated encounters into one dossier when that is how a player understands the fight or character.

```json
{
  "bosses": {
    "source_label": "Battle events, troop phases, enemy and skill records, and fixed outcomes",
    "groups": [
      {
        "id": "boss-story",
        "label": "Main Story Bosses",
        "entry_ids": ["door-warden"]
      }
    ],
    "entries": [
      {
        "id": "door-warden",
        "title": "Door Warden",
        "kind": "story-boss",
        "status": "verified",
        "route_claim_ids": ["leave-opening-room"],
        "optional_entry_ids": [],
        "guide_phrases": [
          "The Door Warden confronts you before Town.",
          "Door Warden has no encoded elemental weakness or resistance.",
          "Defeating it opens the front door."
        ],
        "phases": [
          {
            "label": "Door Warden",
            "enemy_id": 12,
            "participants": {
              "mode": "fixed",
              "active_actor_ids": [1, 3],
              "conditional_actor_ids": [],
              "removed_actor_ids": [],
              "max_active_battlers": 2,
              "text": "Battle setup: Mina fights beside the protagonist.",
              "source_ids": ["mina-joins", "door-warden-battle"]
            },
            "stats": {"HP": 1200, "SP": 80, "ATK": 42, "DEF": 35},
            "exp": 250,
            "gold": 100,
            "drops": "Warden Shard (1 in 4)",
            "element_read": "Door Warden — weakness: Fire (150%) damage taken.",
            "threats": [
              {
                "text": "Shield Bash is the low-HP danger: it combines a heavy physical hit with Stun, so its target can lose the turn needed to recover.",
                "source_ids": ["door-warden-enemy", "door-warden-shield-bash", "door-warden-stun"]
              }
            ],
            "how_to_win": {
              "tools": [],
              "plan": [
                {
                  "text": "Top off before the low-HP Shield Bash window, then Guard with any injured ally who cannot safely take the hit.",
                  "source_ids": ["door-warden-enemy", "door-warden-shield-bash", "door-warden-guard"]
                }
              ]
            }
          }
        ],
        "sources": []
      }
    ]
  }
}
```

Each group has a globally unique kebab-case `id`, a visible `label`, and one or more `entry_ids`. Every boss belongs to exactly one group.

Each boss entry has:

- `id`: a globally unique kebab-case dossier ID, distinct from route, optional, and group IDs.
- `title`: the canonical player-facing boss or encounter name.
- `kind`: `story-boss`, `side-boss`, or `apex-monster`. Use the closest portable kind in data and preserve a game's own category label in rendered prose.
- `status`: `verified`.
- `route_claim_ids`: every Main Route step that contains a documented encounter with this boss, or an empty list.
- `optional_entry_ids`: every Optional Content entry that leads to this boss, or an empty list. At least one route or optional binding is required.
- `guide_phrases`: exact availability, weakness/resistance, threat explanation, any published tool-availability statement, battle-plan statement, unusual encounter rule, and outcome phrases present in Markdown and HTML. Exact stat values are validated through table-cell bindings instead of a duplicate prose sentence.
- `phases`: one or more enemy/form records. Every phase must have a nonempty `label`, positive `enemy_id`, a source-bound `participants` object, a nonempty `stats` object, one or more source-bound `threats`, and a source-bound `how_to_win` object containing a `tools` list and a nonempty `plan` list. `tools` may be empty when no specific tool materially improves the advice. Experience, gold, drops, and elemental read should be carried when the game exposes them.
- `participants`: the encounter-local battle party after all pre-battle branches, party mutations, reserve/frontline rules, and battle-member caps. It contains `mode` (`fixed`, `solo`, or `variable`), nonempty `active_actor_ids`, optional `conditional_actor_ids`, optional `removed_actor_ids`, positive `max_active_battlers`, player-facing `text`, and local `source_ids`. Actor IDs must be unique across the three lists. The maximum cannot be smaller than the default active set or larger than the combined active and conditional set. `solo` requires exactly one active actor, no conditional actors, and a maximum of one. Cite the exact battle plus party add/remove, substitution, temporary initialization, formation, cap, or branch commands that establish the set. Do not infer participation from recruitment status or dialogue presence, and do not describe reserves as simultaneously active.
- `threats`: player-facing explanations of why an encoded action, interaction, phase rule, or deadline changes the fight. Each row has `text` and one or more local `source_ids` pointing to the enemy/action/state/plugin evidence used for that explanation.
- `how_to_win.tools`: optional exact character skills, equipment-granted skills, items, accessories, or fixed rewards realistically available at that encounter. Do not add a universal command as filler. Each published row has an explicit `availability` label, player-facing `text`, and local `source_ids` proving the party member or acquisition path, encounter-time resource readiness, and the effect being recommended. For a temporary party member, include initialization/entry and relevant battle-start resource rules. If another skill, item, equipment record, or command has the same displayed name, identify which one the row means and whether it consumes inventory. An equipment-granted tool additionally needs a completed loadout audit in private `boss-inventory.json`; its sources must cover the candidate and the materially competitive compatible equipment available during the encounter's real availability window, not only the equipment that grants the desired skill. Starting/default equipment receives no exemption.
- `how_to_win.plan`: actionable tactics connecting the threat pattern to those available tools. Each row has player-facing `text` and local `source_ids` for both mechanic and counter.
- `sources`: globally unique snapshots proving every displayed encounter, phase, stat, threat interpretation, recommended tool and its availability, transform/reinforcement rule, and fixed outcome.

The encounter source must prove that the troop is actually started by reachable game logic; an enemy database record alone is insufficient. Snapshot the troop composition for the initial fight, the enemy record fields used in the table, each skill and state record used in a threat explanation, plugin or troop logic needed to prove chained/setup behavior, system element names used to decode traits, troop pages used for transformations or reinforcements, every troop-page or script-forced action that materially affects the encounter, and event commands used for fixed rewards or special loss behavior. Forced-action evidence must identify its trigger, repeat/span behavior, acting battler, forced skill, target rule, and applicable phase; an enemy action record cannot stand in for a forced command that is absent from that record. When strategy depends on a move being forced, targetable, random, interruptible, or avoidable, also pin the engine or plugin selection/targeting logic that establishes that behavior; a schedule condition alone does not prove the move is chosen. A recommended tool also needs its item/equipment/skill record and a source proving the player can obtain or already has it by that encounter. For a temporary party member, also prove initialization or reset, entry and removal branches when material, encounter-start HP/MP/TP, and the engine or plugin rule that changes or preserves those resources at battle start. Distinguish fixed event rewards from database drops and disambiguate same-named skills, items, equipment, and commands in both the evidence and player copy.

The participant chain must cover party mutations and substitutions before battle, the battle command, and restoration afterward when it proves that a companion was only removed temporarily. A recommended character tool must belong to an actor in `active_actor_ids`, or in `conditional_actor_ids` with matching conditional prose. A recommended item must be usable by one of those active battlers under the engine's battle-item rules. Interpret action scope, random targeting, recovery pressure, and available commands against this encounter-local set rather than the wider story party.

For every equipment-bound candidate, record the materially competitive reachable loadouts, relevant parameter/trait/skill differences, and the resulting `recommend`, `conditional-tradeoff`, or `suppress` decision in private `boss-inventory.json`; preserve suppressed candidates there instead of silently discarding the comparison. If an optional encounter can be delayed across equipment milestones, audit that wider availability window and avoid presenting starter gear as the assumed current loadout.

## Scenes & CG catalog, groups, and entries

`scenes_cg` is the reconciled player-facing illustrated catalog, not a filesystem inventory. Its scope comes from the game's reachable recollection, memory, gallery, or replay interface and the executable entries that interface exposes. Record excluded neighboring systems—such as dialogue/BGM replay or ordinary cutscenes—in private research when they could otherwise be mistaken for catalog entries.

```json
{
  "scenes_cg": {
    "source_label": "Player-facing scene catalog, live triggers, unlock state, and viewer dispatch",
    "catalog": {
      "id": "scenes-cg-system",
      "title": "Using the Memory Gallery",
      "entry_count": 1,
      "cg_image_count": 2,
      "interface_files": ["data/SceneCatalog.json"],
      "completion_shortcut": "After a cleared ending, the gallery's Unlock All option opens every entry; the individual cards below explain how to encounter each scene during normal play.",
      "guide_phrases": [
        "Choose Reminisce at the bedroom journal to enter the Memory Gallery.",
        "After a cleared ending, the gallery's Unlock All option opens every entry; the individual cards below explain how to encounter each scene during normal play."
      ],
      "source_roles": {
        "entry_point": ["scene-catalog-entry"],
        "scope_boundary": ["scene-catalog-slots"],
        "completion_shortcut": ["scene-catalog-unlock-all"]
      },
      "sources": []
    },
    "groups": [
      {
        "id": "scene-group-mina",
        "label": "Mina",
        "route_anchor_id": "reach-town",
        "route_anchor_position": "after",
        "entry_ids": ["scene-town-memory"]
      }
    ],
    "entries": [
      {
        "id": "scene-town-memory",
        "title": "Town Memory",
        "kind": "character-scene",
        "status": "verified",
        "group_id": "scene-group-mina",
        "acquisition_mode": "normal-play",
        "acquisition_steps": ["Reach Town, then speak to Mina at the fountain to play Town Memory during the journey."],
        "requirements": ["Reach Town and speak to Mina at the fountain."],
        "aliases": ["A Memory by the Fountain"],
        "viewer_mode": "replay-and-cg-gallery",
        "cg_image_count": 2,
        "guide_phrases": [
          "Town Memory appears in the Memory Gallery after every listed requirement is met.",
          "Reach Town, then speak to Mina at the fountain to play Town Memory during the journey.",
          "Reach Town and speak to Mina at the fountain."
        ],
        "source_roles": {
          "requirements": ["scene-town-memory-requirements"],
          "replay_title": ["scene-town-memory-title"],
          "replay_call": ["scene-town-memory-replay"],
          "normal_acquisition": ["scene-town-memory-trigger"],
          "live_trigger": ["scene-town-memory-trigger"],
          "live_completion": ["scene-town-memory-unlock"],
          "unlock": ["scene-town-memory-unlock"],
          "cg_viewer": ["scene-town-memory-cg-a", "scene-town-memory-cg-b"]
        },
        "sources": []
      }
    ]
  }
}
```

The catalog object has the fixed ID `scenes-cg-system`, a player-facing title, exact published entry and illustrated-set totals, one or more exact `guide_phrases`, globally unique source snapshots, a `source_roles` mapping, and `interface_files` listing the dedicated maps/data files that implement the catalog or recollection surface. Do not put a mixed-use common-event database in `interface_files` merely because the catalog calls a common event; list the dedicated interface sources so the validator can reject a catalog interaction reused as live acquisition evidence. `entry_point` proves how the player reaches the catalog. `scope_boundary` proves which authoritative slots or records define its included entries and any material exclusion boundary.

When the game has a verified catalog-wide unlock-all or completion shortcut, add its exact player-facing explanation as `completion_shortcut`, include that same string once in `guide_phrases`, and bind a `completion_shortcut` source role. Render it once in the `.scene-system` overview. Omit the field and role when the game has no such behavior. Individual `normal-play` entries must not repeat it or use it as a requirement. Add other roles such as relationship-status display, skip behavior, defeat handling, reset behavior, or settings only when that game actually uses them and the guide discusses them.

Each group has a globally unique kebab-case `id`, a visible `label`, a complete ordered `entry_ids` list, and one Main Route availability binding. `route_anchor_position` is `before` when the player should know about the group before taking the step or `after` when completing the step first makes the group actionable. Every scene belongs to exactly one group; group membership is organizational and does not claim that all entries share one unlock time.

Each scene entry has:

- `id`: a globally unique kebab-case ID, distinct from every route, optional, boss, catalog, and group ID.
- `title`: the canonical player-facing catalog/replay title.
- `kind`: `relationship-scene`, `character-scene`, `story-scene`, `encounter-scene`, `defeat-scene`, `gallery-entry`, or `other-scene`. Preserve a more specific game-authored category in visible prose when useful.
- `status`: `verified`.
- `group_id`: the one group that contains the entry.
- `acquisition_mode`: `normal-play` for a scene reached through executable story, exploration, interaction, choice, relationship, optional-content, or defeat logic outside the catalog interface; `gallery-only` only for a viewer/reference record proven to have no standalone live event.
- `acquisition_steps`: one or more exact player-facing steps for the normal live path. For `gallery-only`, explain that the record is a viewer-only collection and how to recognize it without repeating the catalog-wide completion shortcut.
- `requirements`: one or more exact, player-facing requirements for that acquisition path. Translate executable gates into actions and visible states without exposing internal IDs.
- `aliases`: trigger-time title variants that help identify the live event, or an empty list.
- `viewer_mode`: a nonempty kebab-case description of what the catalog opens, such as `replay-and-cg-gallery`, `replay`, or `still-gallery`; this is descriptive, not a fixed plugin enum.
- `cg_image_count`: the nonnegative number of illustrated sets explicitly selected by this entry's viewer. Count sets, not animation frames or similarly named files.
- `guide_phrases`: the exact availability statement, every acquisition step, every requirement, and any other material player-facing behavior rendered in Markdown and HTML.
- `source_roles`: local evidence bindings. `normal-play` requires `requirements`, `normal_acquisition`, `replay_title`, `replay_call`, `live_trigger`, and `live_completion`; at least one source for each live role must be outside `catalog.interface_files` and must not duplicate a catalog-system locator. Add `unlock` when the live event writes a separate persistent catalog state; omit it when the catalog has no per-entry locking and the live scene simply completes. `gallery-only` requires `requirements`, `replay_title`, `replay_call`, and `gallery_access`, must use kind `gallery-entry`, and must not claim live acquisition/completion roles. Both modes also require `cg_viewer` when `cg_image_count` is positive. A role describes what the source proves, not which engine construct must carry it. For example, `replay_call` may cite an event command, plugin command, script dispatch, or configured gallery record.
- `sources`: globally unique snapshots proving every source role and published behavior. `cg_viewer` must cite exactly one source per counted illustrated set.

Implementation details such as switches, variables, common-event IDs, plugin keys, and asset filenames may be retained in private `scene-inventory.json` or evidence locators, but they are not portable required fields and must not appear in player prose. A source role cannot cite an ID outside the entry's own sources.

## Source snapshots

Every source requires a unique kebab-case `id`, a supported `type`, a project-relative `file`, a nonempty `supports` explanation, and a source-specific snapshot. Paths must remain inside the game root.

### Event command

Use for RPG Maker map events and common events:

```json
{
  "id": "door-transfer",
  "type": "event-command",
  "file": "data/Map001.json",
  "event_id": 4,
  "page_index": 0,
  "command_index": 12,
  "expected": {"code": 201, "parameters": [0, 2, 8, 11, 2, 0]},
  "supports": "The door transfers the player to Town."
}
```

For `CommonEvents.json`, `event_id` is the common-event array index and `page_index` must be `0`. Snapshot both `code` and the complete `parameters` array. If a conclusion depends on page conditions, branch choices, or a state write, cite those commands separately rather than citing only the final transfer.

### Database record

Use for exact item, weapon, armor, enemy, skill, state, map, or other database fields:

```json
{
  "id": "iron-sword-name",
  "type": "database-record",
  "file": "data/Weapons.json",
  "record_id": 7,
  "expected": {"name": "Iron Sword", "price": 250},
  "supports": "The fixed reward is the weapon named Iron Sword."
}
```

Include only fields material to the walkthrough claim. The validator compares every listed field exactly.

### File excerpt

Use for engine data or scripts not represented by the structured forms above:

```json
{
  "id": "plugin-gate",
  "type": "file-excerpt",
  "file": "js/plugins/StoryGate.js",
  "contains": "StoryGate.unlock(\"north_pass\")",
  "supports": "The plugin command unlocks the north-pass story gate."
}
```

Use the shortest distinctive excerpt that proves the claim. Do not use an existing walkthrough, research note, generated report, translation memory, or localization glossary as evidence.

### File hash

Use for a player-visible binary asset whose text or visual state was inspected directly, such as a chapter title card:

```json
{
  "id": "chapter-card",
  "type": "file-hash",
  "file": "img/pictures/Chapter01.png",
  "sha256": "64-lowercase-hex-characters",
  "supports": "The displayed title card reads Chapter 1 — Departure."
}
```

Pair a title-card hash with the event command that displays it so the ledger proves both the visible label and its story boundary. A hash only pins the inspected bytes; it does not replace inspection or make an inferred label true.

### Map layout observations

Coordinates and event positions may be cited inside Evidence to establish adjacency or relative placement, but they do not establish what a player sees or how obstacles affect movement. When visibility, direction, passability, elevation, or an exact walking path cannot be proven, omit that precision. Keep the instruction at the verified named area, connected exit, interaction, gate, or outcome.

## Markdown and HTML binding

### Main Route

Immediately precede every source-backed chapter, route section, and Main Route step in `WALKTHROUGH.md` with their markers:

```markdown
<!-- route-chapter:prologue -->
## Prologue — Awakening

<!-- route-section:objective-reach-town -->
### Reach Town

<!-- route-claim:leave-opening-room -->
#### Leave the house
```

Render the chapter, section, step, and disclosure as:

```html
<section class="route-chapter" id="group-prologue" data-chapter-id="prologue" data-chapter-label="Prologue — Awakening">
  <header><p>Game chapter</p><h2 id="prologue">Prologue — Awakening</h2></header>
  <section class="route-section" id="section-objective-reach-town" data-section-id="objective-reach-town" data-section-label="Reach Town">
    <header><p>In-game objective</p><h3 id="objective-reach-town">Reach Town</h3></header>
    <article class="route-step" id="step-leave-opening-room" data-claim-id="leave-opening-room">
      <h4>Leave the house</h4>
      <p>Speak to Mina beside the front door, then leave through that door.</p>
      <details class="evidence" data-evidence-id="leave-opening-room">
        <summary>Evidence</summary>
        <p class="evidence-status" data-evidence-status="verified">Verified from game data</p>
        <ul>
          <li data-source-id="opening-choice">
            <span>Using the front-door event transfers the party to the named town map.</span>
            <code>data/Map001.json · event 4 · page 1 · command 13</code>
          </li>
        </ul>
      </details>
    </article>
  </section>
</section>
```

In `sections` mode, omit `.route-chapter`, render section labels as `h2`, and render route-step headings as `h3`.

The technical display uses player-friendly one-based page/command numbering if desired; the manifest always uses zero-based array indices. The validator binds claims and rendered sources through `data-*` IDs, not by parsing the display label.

Do not place internal file/event/switch/variable locators in `WALKTHROUGH.md` player prose. The HTML renderer adds those only inside the collapsed disclosure.

### Optional Content

Immediately precede every optional group and entry in `WALKTHROUGH.md` with matching markers:

```markdown
<!-- optional-group:optional-prologue -->
## Prologue opportunities

<!-- optional-entry:lost-delivery -->
### Lost Delivery

Speak to Mina in the town square, recover the parcel from the riverside storehouse, then bring it back to her.
```

Render them inside the completed Optional Content view:

```html
<section class="optional-group" id="optional-group-optional-prologue" data-optional-group-id="optional-prologue" data-optional-group-label="Prologue opportunities">
  <h2 id="optional-prologue">Prologue opportunities</h2>
  <article class="optional-entry" id="optional-lost-delivery" data-optional-id="lost-delivery">
    <p class="optional-meta">Side event</p>
    <h3>Lost Delivery</h3>
    <p>Speak to Mina in the town square, recover the parcel from the riverside storehouse, then bring it back to her.</p>
    <p class="optional-reward"><strong>Reward:</strong> Traveler's Brooch</p>
    <label class="task-row"><input class="task-checkbox" type="checkbox" data-task-id="lost-delivery"> Mark Lost Delivery complete</label>
    <details class="evidence" data-evidence-id="lost-delivery">
      <summary>Evidence</summary>
      <p class="evidence-status" data-evidence-status="verified">Verified from game data</p>
      <ul><li data-source-id="lost-delivery-completion">…</li></ul>
    </details>
  </article>
</section>
```

The group heading ID and entry article ID are the durable deep-link destinations. Every Optional Content entry gets exactly one saved checklist input and exactly one Evidence disclosure. The Main Route step named by `route_anchor_id` must contain exactly one working link whose placement matches the ledger, such as `<a data-guide-link data-guide-link-position="after" href="#optional-lost-delivery">`. Put a `before` callout above the route prose and an `after` callout below its outcome. Do not link from an earlier chapter merely because the quest is configured there, do not delay a link until a recommended regional visit when its gates open earlier, and do not emit a link to an unfinished Scenes & CG destination.

### Bosses

Immediately precede every boss group and dossier in `WALKTHROUGH.md` with matching markers:

```markdown
<!-- boss-group:boss-story -->
## Main Story Bosses

<!-- boss-entry:door-warden -->
### Door Warden
```

Render each dossier inside the completed Bosses view:

```html
<section class="boss-group" data-boss-group-id="boss-story" data-boss-group-label="Main Story Bosses">
  <h2 id="boss-story">Main Story Bosses</h2>
  <article class="boss-entry" id="boss-entry-door-warden" data-boss-id="door-warden">
    <h3 id="boss-door-warden">Door Warden</h3>
    <p>The Door Warden confronts you before Town.</p>
    <p><a data-guide-link href="#leave-opening-room">Main Route: Leave the house</a></p>
    <label class="task-row"><input class="task-checkbox" type="checkbox" data-task-id="door-warden"> Defeated</label>
    <details class="evidence" data-evidence-id="door-warden">
      <summary>Evidence</summary>
      <p class="evidence-status" data-evidence-status="verified">Verified from game data</p>
      <ul><li data-source-id="door-warden-enemy">…</li></ul>
    </details>
  </article>
</section>
```

The group heading uses the exact group ID. The dossier heading uses `boss-<boss-id>`, giving route and optional links a durable destination. Every dossier gets exactly one matching checklist and Evidence disclosure. Each declared route or optional source must contain a working `data-guide-link` to the dossier, and the dossier must link back to every declared source entry. The validator treats missing, extra, or misbound links as publication failures.

### Scenes & CG

Introduce the catalog overview in Markdown, then immediately precede every scene group and scene entry with matching markers:

```markdown
## Using the Memory Gallery

<!-- scene-group:scene-group-mina -->
## Mina

<!-- scene-entry:scene-town-memory -->
### Town Memory
```

Render the overview and entries inside the completed Scenes & CG view:

```html
<section class="scene-system" id="scenes-cg-system">
  <h2>Using the Memory Gallery</h2>
  <p>Choose Reminisce at the bedroom journal to enter the Memory Gallery.</p>
  <details class="evidence" data-evidence-id="scenes-cg-system">…</details>
</section>
<section class="scene-group" data-scene-group-id="scene-group-mina" data-scene-group-label="Mina">
  <h2 id="scene-group-mina">Mina</h2>
  <p><a data-guide-link href="#reach-town">Main Route context</a></p>
  <article class="scene-entry" id="scene-entry-scene-town-memory" data-scene-id="scene-town-memory" data-acquisition-mode="normal-play">
    <h3 id="scene-town-memory">Town Memory</h3>
    <p>Town Memory appears in the Memory Gallery after every listed requirement is met.</p>
    <section class="scene-acquisition" data-acquisition-mode="normal-play">
      <h4>How to get it normally</h4>
      <p>Reach Town, then speak to Mina at the fountain to play Town Memory during the journey.</p>
      <ul class="scene-requirements"><li>Reach Town and speak to Mina at the fountain.</li></ul>
    </section>
    <p class="scene-cg-count">2 illustrated sets</p>
    <label class="task-row"><input class="task-checkbox" type="checkbox" data-task-id="scene-town-memory"> Mark unlocked</label>
    <details class="evidence" data-evidence-id="scene-town-memory">…</details>
  </article>
</section>
```

The catalog overview has exactly one verified Evidence disclosure and contains every catalog `guide_phrase`, including any completion shortcut once. Every group heading exposes its exact group ID; every entry heading exposes its exact scene ID. Every entry has exactly one matching `.scene-acquisition` section, checklist, and Evidence disclosure and visibly renders its exact `cg_image_count`. The Main Route anchor contains exactly one `data-guide-link` to each declared group at the declared `before` or `after` position, and the group links back to that route claim. The validator rejects missing entries, mismatched totals, unbound evidence roles, catalog-interface evidence masquerading as normal acquisition, repeated completion shortcuts in normal entries, uncounted viewer sets, extra/dead links, and entries outside the Scenes & CG view.

## Verification boundary

- `verified` means every material part of the published player-facing phrase is supported by source snapshots and the relevant branch trace.
- For Optional Content, `verified` also means the major lifecycle, direct dependencies, availability anchor, completion interaction, and stated fixed outcomes have been traced.
- For Bosses, `verified` also means every displayed phase, stat, action, elemental read, drop, fixed reward, transformation, special outcome, and route/optional binding has been traced.
- For Scenes & CG, `verified` also means the catalog boundary, exact title, acquisition classification, displayed requirements, normal acquisition/live trigger/live completion for `normal-play` and any separate persistent unlock write the game actually uses (or a reconciled lack of a standalone event for `gallery-only`), replay/viewer dispatch, illustrated-set count, and group/route binding have been traced.
- Exact walking lines, visual prominence, and route efficiency are not required publication claims. Do not add them unless the data proves them.
- Research notes about omitted precision may stay in private working files or a non-rendered `navigation_note`; they are not claim statuses and must not appear in HTML Evidence.

Never use `assumed`, `likely`, `requires-playtest`, or an untracked confidence state. A plausible claim is either strengthened to `verified`, narrowed to what is provable, or omitted.

## Research rules

- Trace forward from the triggering event and backward from the claimed outcome.
- Treat a catalog phrase such as “continue the event” as catalog evidence, not a complete route. Cite the executable gate, the state transition that reaches it, and any player-visible journal/location/story milestone used to expand that phrase.
- Begin system-specific tracing from the private active-system inventory. Require enabled configuration plus executable or player-facing use before treating a plugin/module as active, and deep-audit only systems that can materially affect a completed view.
- Cite all material sides of a branch: choice labels, branch condition/state, reward or transfer, and the later gate when relevant.
- Cite both the acquisition command and database record for a named important item when the command identifies it only by ID.
- Cite the battle-processing command, initial troop record, every displayed enemy form, every displayed skill/action, relevant system element mapping, phase-changing troop pages, material troop/script-forced actions, and fixed outcome events for a boss dossier. Reconcile the ordinary enemy action list with forced actions before deciding the threat pattern.
- For a recommended learned or equipment-granted combat tool, cite the active progression system or acquisition chain, prerequisites and spendable resource when configurable, encounter-start resource readiness, the ability effect, and the relevant encounter-time equipment comparison. For a temporary party member, trace initialization, entry/removal lifecycle, resource reset/preservation, and battle-start behavior. A true availability statement does not by itself verify that the recommendation is useful.
- When two player-facing records share a name, cite both records and make the command, cost, and inventory behavior unambiguous in the guide.
- Cite page conditions and state writes for progression gates; do not infer causality from similarly named switches.
- Keep one evidence claim focused enough that a reviewer can explain why every source is present.
- Reconcile configured optional records with executable activation and completion writes. Record unreachable, test-only, duplicate, superseded, boss-dossier, and scene-only exclusions in private research so missing catalog entries are deliberate rather than accidental.
- Reconcile every authoritative illustrated catalog slot with its normal acquisition path, reachable live trigger, unlock state, replay/viewer dispatch, and counted illustrated sets. Search reverse common-event calls, picture/viewer calls, state writes, battle-loss branches, and map triggers before classifying a record `gallery-only`. Do not derive completeness from asset filenames, installed plugin defaults, or similarly named options. Trace relationship, skip, rest, defeat, reset, and other scene mechanics only when the active game uses them and they affect a published entry.
- When discovery, classification, evidence, strategy, prose, or rendering behavior changes, regenerate the complete walkthrough and all affected private manifests. Re-audit every already-completed view touched by that behavior; never update only the reported example and treat unchanged entries as reviewed.
- Re-run validation after any game-data, Markdown, evidence, or HTML change. A snapshot mismatch means the guide must be re-audited, not that the expected snapshot should be updated automatically.
