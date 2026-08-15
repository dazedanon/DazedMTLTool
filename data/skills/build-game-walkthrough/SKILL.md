---
name: build-game-walkthrough
description: "Build a detailed, source-traceable game walkthrough as one offline HTML application with four complete top-level views: Main Route, Optional Content, Bosses, and Scenes & CG. Use when Codex must audit local game events and databases, write player-usable routes and catalogs without guessing from coordinates or filenames, and expose expandable evidence for every entry."
---

# Build a Game Walkthrough

Build the walkthrough for the selected DazedTL project:

- Game root: `{{GAME_ROOT}}`
- Engine hint: `{{ENGINE}}`

Treat the engine hint as a lead. Detect the actual engine and data layout before research.

## Load the project's language rules first

Before indexing events or drafting any prose, read these project files completely when they exist:

- `<game>/.dazedtl/glossary.txt`
- `<game>/.dazedtl/skills/quirks.md`

They are authoritative for player-facing names, character identities and pronouns, relationships, location spellings, fixed terminology, and project-specific English usage. Build a compact `project-context.md` in the walkthrough working directory that records every named character and place used by all four views plus every quirk that can affect guide prose. Do not rely on memory or infer a pronoun from an actor sprite, dialogue tone, or name.

Snapshot both available files in `evidence.json` under `project_context` as required by the evidence contract. Re-read and re-audit the prose whenever either snapshot changes. These files control wording; they do not replace executable game sources for proving route progression, rewards, gates, or branches.

Before publication, search the complete player-facing guide for every named character used in completed views. Check names, pronouns, roles, and relationship language against `project-context.md`, then check all location and fixed-term spellings against the glossary and quirks. Treat any conflict as a blocker.

## Deliver this milestone

Publish one offline `<game>/WALKTHROUGH.html` as a self-contained responsive HTML application with exactly four top-level views:

1. **Main Route** — complete and useful in this milestone.
2. **Optional Content** — complete verified coverage of major side events, activities, services, exploration detours, and postgame investigations in this milestone.
3. **Bosses** — complete verified coverage of story bosses, side-event bosses, multi-form encounters, rematches, and game-defined superboss/Apex systems in this milestone.
4. **Scenes & CG** — complete verified coverage of the game's player-facing illustrated scene, recollection, and CG catalog.

Use top tabs to switch views without loading another file. Make each view behave like a distinct page: it owns its heading, local navigation, URL/hash state, and search destinations. Keep all IDs globally unique so later entries can be added without breaking saved links.

Keep boss stat/strategy dossiers in Bosses and companion, relationship, encounter, defeat, recollection, and CG entries in Scenes & CG even when those systems are optional. Main Route must link directly to Optional Content entries at their declared first-availability anchors, every Bosses dossier encountered on that route, and each Scenes & CG group when it first becomes actionable. Every destination links back to its declared route or optional source. Never publish a dead link.

## Start from executable evidence

Do not inherit the structure, scope, claims, chapter boundaries, or completion assumptions of an existing walkthrough. Existing guide text may provide search terms only. Re-prove every retained fact from the game.

1. Inventory maps, map names, transfers, event pages, page conditions, common events, choices, switches, variables, mandatory battles, items, weapons, armor, key items, and progression gates.
2. Find the real new-game entry and trace the mandatory route forward through transfers and state changes.
3. Build a route graph before drafting prose. At each branch, follow every path far enough to distinguish mandatory progression, alternate valid progression, optional content, a temporary dead end, and a return-later gate.
4. Reverse-check important outcomes. For a required item, gate, choice, or boss result, locate every relevant acquisition, condition, branch, and state write rather than trusting the first matching string.
5. Record each player-facing route step in `evidence.json` before presenting it as fact. Read [`references/validation-evidence.md`](references/validation-evidence.md) completely and use its schema.
6. If static analysis cannot establish an exact walking line or visual landmark, omit that precision and keep the instruction at the verified destination, interaction, gate, or outcome. Never turn a coordinate, event name, or likely intent into a confident direction, and never publish an internal live-play caveat as player guidance.

## Inventory active game systems before deep research

Do a bounded reconnaissance pass before choosing system-specific research. Do not reverse-engineer every installed plugin, module, or subsystem.

1. Inventory the engine's system registry and likely extension points: enabled plugin/module manifests, configuration files, menu commands, database note conventions, custom data files, and prominent script or plugin commands.
2. Separate `installed` from `active`. Treat a system as active only when enabled configuration is joined by executable use such as a reachable menu entry, event/common-event/troop call, populated game configuration, runtime hook, or player-facing data. A file existing on disk is not enough.
3. Classify each active system by walkthrough relevance: progression/navigation, optional-content lifecycle, combat/character progression, rewards/economy, scenes, presentation-only, or unrelated to the current milestone.
4. Assign one bounded decision: `deep-audit` when the system can materially change a published claim or recommendation; `trace-on-demand` when only a specific use site matters; or `ignore` with a short reason when it cannot affect the completed views. Let the evidence and current milestone determine the choice rather than a fixed plugin-name checklist.
5. For a deep audit, map only the behavior needed by the walkthrough. Use a focused script when structured configuration, nested parameters, graphs, or many repeated records make manual tracing unreliable. Stop once availability, dependencies, effects, and player-facing consequences needed by the guide are established.
6. Before closing reconnaissance, run four portable gap checks against the active systems and executable events. These are questions, not assumptions that every game implements the same feature:
   - **Companion and support roster:** when named allies, recruits, or finale-support actors exist, enumerate the complete roster from the game's authoritative party/support checks. For each one, reverse-trace the successful route, retryable deferrals, irreversible refusals, missable timing windows, alternate completions, and the exact point after which support can no longer be earned. Do not call an NPC recruited merely because their personal event completed.
   - **Progression-critical capabilities:** enumerate every vehicle, traversal power, key service, license, or world-state upgrade checked by mandatory destinations. Reverse-trace each capability through every required item, dungeon, boss, intermediate unlock, and hand-in. A nominally open world does not make a ship, airship, bridge repair, or equivalent gate optional when the ending route reads it.
   - **Danger and encounter ordering:** when regions can be entered in several orders, compare their reachable enemy/boss runtime profiles, equipment or character-progression milestones, and special battle rules. Build a source-backed danger ladder that tells the player which regions and bosses form sensible early, middle, late, and apex bands without inventing exact levels. Treat healing cycles, regeneration, instant-loss conditions, equipment destruction, puzzle counters, forced actions, and usable item bypasses as possible ordering-changing mechanics to discover—not a fixed checklist of mechanics every game must have.
   - **Progression shops and capacity:** when a shop family, socket/slot system, skill capacity, crafting tier, or analogous loadout limit is active, enumerate every reachable provider and every capacity increase. Trace what opens each shop, what meaningful tier it sells, whether a key or side chain is required, and which mandatory or optional milestones increase capacity.
7. Convert every applicable gap check into explicit `required_topics` under the affected deep-audit system. A topic names the player-facing outcome that must be covered—such as a vehicle milestone, recruit, danger band, special mechanic, shop tier, or slot increase—not merely the file or plugin inspected. Bind each topic to the guide record IDs and evidence source IDs that cover it through `system_reconnaissance.coverage` in `evidence.json`. If an authoritative roster or progression chain has an uncovered topic, research is incomplete.
8. Save `systems-inventory.json` in the private walkthrough work area. For each candidate record its source/configuration signal, active-use proof, player-facing entry point if any, affected views, decision, required topics when deep-audited, and the focused artifacts produced by that audit.

## Inventory Optional Content before writing it

Do not assume that a game's visible quest menu is the whole optional catalog. Perform a repeatable discovery pass that can transfer to other games and engines:

Start with a broad category checklist: named side quests and quest chains; optional areas, dungeons, and settlements; recruitments and party-member detours; crafting, upgrade, shop, travel, and other service unlocks; minigames, arenas, training, and repeatable activities; collectible or key-item turn-in chains; optional-boss and bounty systems; relationship or scene routes; postgame and new-game-plus events. This is an inventory checklist, not permission to put everything in Optional Content: classify boss dossiers and scene catalogs into their dedicated views, and do not turn ordinary loose treasure into an entry unless it belongs to a named chain, unlock, or major fixed outcome.

1. Locate every configured quest, journal, request, task, bounty, objective, achievement, relationship, and postgame plugin or data table. Parse nested plugin parameters instead of relying on a text search alone.
2. Identify the state carrier for every entry: variables, switches, self-switches, quest objects, script calls, plugin commands, common events, or database flags. Decode the actual state values for hidden, available, active, updated, reportable, completed, failed, and expired entries from the implementation when possible.
3. Scan every map event, common event, troop page, and script call for writes to those carriers. Record the complete lifecycle: discovery or acceptance, each objective update, branch-specific progression, completion, failure or missability, and any reset/new-game-plus behavior.
4. Reverse-search every stated requirement and reward. Verify required items, quantities, party members, prior quests, story gates, currency, weapons, armor, skills, services, new shops, travel points, repeatable encounters, achievements, and follow-on quest unlocks from executable commands and database records.
5. Build a dependency graph. Detect chains opened by another side event, companion-gated starts, simultaneous quest batches, region gates, postgame-only flags, optional choices that converge, and quests whose final target is not reachable when the journal entry first appears. For every entry, intersect all start predicates with the chronological Main Route and select the first claim where they can all be satisfied. Check the immediately preceding claim and record the gate that still prevents access there. Do not substitute the first recommended visit, the end of a regional objective, or a convenient chapter grouping for earliest availability.
6. Classify each discovered entry into the correct top-level view. General side quests, service unlocks, exploration detours, and postgame investigations belong in Optional Content. Detailed optional-boss stats and tactics belong in Bosses; relationship, intimate, and CG events belong in Scenes & CG. Optional Content explains how those paths unlock and links to each completed boss dossier it contains.
7. Reconcile the configured inventory with the event-write inventory. Investigate configured entries with no reachable activation, state variables reused by test maps, active events with no journal record, and duplicate or stale translated titles. Exclude development/test content only after proving it is unreachable or superseded.
8. Save a compact inventory in the private walkthrough work area with each entry's canonical title, category, state carrier, start source, update sources, completion source, dependencies, first Main Route anchor, whether its link belongs before or after that step, the preceding blocked state, and fixed outcomes. Treat missing major lifecycle or availability evidence as a blocker for publishing that entry.

For every companion recruitment or finale-support entry, publish a compact failure analysis alongside the successful route. Distinguish choices that only postpone acceptance from permanent lockouts, distinguish completing a personal quest from setting the actual recruit/support flag, and name the last player-visible opportunity before the route closes. If the game has no failure path, say so only after proving that the route remains retryable or automatic. Record this as the entry's source-bound `recruitment` object instead of hiding it in research notes.

Aim to capture all major actionable content through static analysis. A player may still need to adjust their local movement inside a map when exact geometry is not provable, but they should not have to discover the quest chain, prerequisite, destination, required item, completion interaction, or meaningful reward on their own.

## Inventory Bosses before writing them

Treat the game's own battle and category systems as the starting point, then reconcile them with every reachable encounter. Do not assume that an enemy named in a bestiary is a boss, and do not miss an untagged story battle simply because its database category is ordinary.

1. Scan every map event, common event, and troop page for battle-processing commands, scripted battle starts, reinforcements, transformations, forced escapes, turn conditions, HP thresholds, and victory/defeat handling. Resolve every troop to all enemy records it can contain during the fight.
2. Inventory configured boss classifications: enemy note tags, category keys, bestiary groups, bounty lists, Apex/superboss systems, achievements, quest targets, and postgame rematch menus. Reconcile that configured inventory with the reachable battle inventory and document deliberate exclusions such as ordinary elites, development encounters, or unreachable records.
3. Classify each dossier as `story-boss`, `side-boss`, or the game's explicit superboss category. Preserve the canonical player-facing category name in prose. Merge repeated encounters, alternative opponents, summoned adds, and transformations when they are parts of one player-facing confrontation or one named character's progression; keep materially different bosses separate.
4. For every phase, snapshot the enemy's name, parameters, actions, traits, experience, gold, and database drops. Build one encounter-action inventory that merges **all** of the enemy record's ordinary actions with every troop-page, common-event, script, and plugin-forced action; never select only the highest-rated or first few actions as a proxy for the fight. Include passive regeneration, turn-end processing, state-enabled moves, chained skills, full or percentage recovery, enemy-HP changes, instant-loss branches, equipment/clothing destruction, unusual victory rules, and usable item/event counters when the active game implements them. Audit troop pages conditioned on player switches, variables, equipment, clothing, status, or party state even when they do not look like enemy AI: they can reveal a player-triggered counter, forced self-action, instant enemy defeat, or alternate resolution that completely changes the strategy. For each forced action, trace the page or script condition, repeat/span behavior, acting battler, target rule, skill, and phase applicability; never assume the ordinary enemy action list is the complete moveset. Resolve each published action through its skill record, every named status through its state record, note-driven follow-ups or substitutions through the relevant plugin/troop logic, and element IDs through the system database. Trace the engine's real action-selection and targeting rules—including rating/priority filtering, action counts, random or fixed targeting, forced actions, cooldowns, and plugin overrides—whenever they affect whether a move is guaranteed, merely possible, predictable, or safely countered. Interpret every scope and target rule against the encounter-local active battlers established in step 7: an all-opponents skill in a solo duel hits the lone duelist, and repeated random-target hits may all concentrate there. Trace setup states into the actions they enable, chained skills into their follow-ups, buffs into their actual parameter/action effects, and turn or HP conditions into the resulting danger window. Reconcile every material mechanic into player advice or mark it source-bound as non-strategic in the private boss inventory. Do not publish a raw move description when the data can establish why the move matters.
5. Trace the encounter outcome outside the enemy record. Verify fixed event rewards, first-victory rewards, quest completion, route gates, safe-loss or branch-convergence behavior, repeatability, and rematch unlocks from the relevant event commands. Clearly separate database drops from fixed event rewards.
6. Bind each boss to every Main Route claim or Optional Content entry that reaches it. Put the first usable availability statement in player terms—chapter, objective, named area, or linked quest—not map IDs, coordinates, or editor event names. Link both directions.
7. Reconstruct the active battle party separately for every battle command and materially different phase before building its player-tool inventory. Start at the last known story party, then trace the complete executable pre-battle path—including choice branches, party add/remove commands, formation locks, battle-member caps, reserve/frontline rules, temporary actors, substitutions, initialization, common events, scripts, and plugin hooks—through the exact moment combat begins. Continue past battle end far enough to distinguish participants from companions temporarily removed to watch, actors restored only afterward, and branch-specific opponents or parties. A recruited companion, nearby speaker, on-map follower, reserve member, or member available in the wider chapter is not an active combat tool unless this encounter can put that actor into a battle slot. Record default/guaranteed, formation- or branch-conditional, removed, and temporary participants, the maximum active battlers, and their source chain in each phase's private participant audit. If alternative opponents use different party setups, give them separate participant inventories even when they share one dossier.

   Separate game-wide roster rules from encounter-local setup. State a verified active-battler cap, reserve behavior, or Formation rule once in the Bosses introduction. In each dossier, name only the fixed/earliest active party, meaningful later substitutes, and encounter-specific removals or locks. Do not repeat the same global roster sentence across dossiers or phases.

   Build the per-encounter player-tool inventory only from those active battlers. Start from the active-system inventory, then trace only the combat and character-progression systems that can matter here: actor and class records, level-appropriate learned skills, active skill-tree/job/talent/passive systems, equipment-granted skills, fixed equipment and Graces already awarded, reachable shops and their current page conditions, directly available crafting/upgrade systems, and relevant consumables or resistance accessories usable by an active battler. Intersect class learnings with a verified level; a level-1 learning is available when that actor joins, while a higher-level learning needs level evidence or a conditional label. For a temporary party member, trace the complete encounter lifecycle: initialization or reset, party entry, level/EXP synchronization, starting HP/MP/TP and battle-start resource rules, retained state or equipment, and every exit branch. Do not describe a temporary actor as a `guest` unless the game itself uses that player-facing term. A skill is usable advice only when its cost can actually be paid at the relevant time: prove the starting resource and any gain, regeneration, inventory, currency, or charge path; if it is not ready at battle start, say exactly what must be built or acquired before it becomes usable. When skills, items, equipment, or commands share a displayed name, disambiguate the menu/command, cost, and inventory consumption in player prose instead of allowing one record to masquerade as another. For a configurable progression system, trace node costs, prerequisites, currency/SP acquisition, unlock behavior, and whether learned abilities remain available after equipment changes, but publish a chosen branch as conditional unless the game forces it. For an equipment-granted skill, prove both that an active battler joined with or could obtain the equipment and that the equipment grants the named skill.

   Run the same encounter-time loadout viability pass for **every** equipment-bound candidate, including starting, default, forced, currently equipped, early-game, and temporary-party equipment; none of those labels is an exception or an automatic recommendation. Establish the encounter's actual availability window, then inventory the compatible equipment the player can reasonably have by that fight. Optional encounters that can be delayed need both their earliest loadout and any materially stronger equipment obtainable before the player is likely to finish them. Compare all combat-relevant parameters, traits, granted/lost skills, elements, statuses, costs, actor scaling, role, and the enemy's defenses or mechanics. Judge the candidate skill's marginal encounter value against the loadout opportunity cost and record one decision: `recommend`, `conditional-tradeoff`, or `suppress`. A starting-equipment skill may be published only after it survives this pass; joining with the item or having the skill in the command list proves availability, not usefulness. Suppress it when a stronger reachable loadout or a learned/system skill answers the encounter better. Use `conditional-tradeoff` only when the narrower benefit can plausibly outweigh the loss, and explain both sides in player prose. Do not encode named equipment, universal stat cutoffs, or a fixed preference for weapon skills, learned skills, offense, defense, or healing; let the verified game and encounter determine the decision.

   Availability alone does not make any tool good advice. Do not stop at shops or universal commands when character-specific evidence exists. Classify every published tool as `guaranteed`, `purchasable`, or `conditional/already owned`; a shop listing proves availability, not ownership. For a later rematch, solo sequence, temporary party member, optional encounter with a broad completion window, or phase reached in another chapter, rebuild the inventory and loadout audit for that encounter instead of recycling an earlier party or loadout.
8. Write a separate `How to win` section for every phase or encounter variant. Reason about that encounter as a whole from its verified mechanics and the current party; let the evidence determine the useful advice. Do not use portable tactical gates such as “recommend Guard only for multi-target attacks,” coefficient cutoffs, scope counts, or fixed state/severity thresholds as substitutes for encounter analysis. A scheduled single-target attack may justify guarding everyone when its target is unpredictable and the selection rules make it certain; a party-wide attack may not justify Guard when another verified counter is better. Connect advice to the resulting threat pattern: identify preparation windows, recovery turns, add priority, phase/resource carryover, buff removal, ailment prevention/removal, or a hard turn deadline only when the sources establish it. Name specific usable character skills, equipment-granted skills, accessories, and items from the player-tool inventory whenever they materially answer the mechanic. Treat the tool list as optional: publish it only when at least one specific recommendation improves the strategy, and omit the `Tools available` subheading when no such recommendation exists. Never add Attack, Guard, healing, or another universal command merely to fill the list, but never suppress one merely because it is universal. Cite its effect and the encounter-specific evidence that makes its use valuable. Never recommend an elemental exploit the current party cannot yet produce without labeling it conditional. Do not invent levels, builds, visual tells, AI priorities, or guaranteed strategies.
9. Save `boss-inventory.json` in the private walkthrough work area with the classification rule, dossier ID, canonical title, encounter sources, troop IDs, enemy/form IDs, route/optional bindings, a per-phase participant audit, phase mechanics and interactions, tool availability by encounter, per-candidate loadout audits (candidate equipment, compatible alternatives, relevant stat/trait/skill differences, decision, and reason), fixed outcomes, and exclusions. Retain removed participants and suppressed equipment-skill candidates in these private audits so omissions are deliberate and reviewable. A boss is publishable only when the encounter identity, every displayed phase, participant set, threat explanation, strategy statement, recommended tool, loadout decision, and stated outcome all have source snapshots.

## Inventory Scenes & CG before writing it

Start from the active-system inventory and discover the game's own scene organization. Do not assume a particular recollection plugin, relationship model, switch layout, common-event range, room map, menu name, or asset naming scheme.

1. Find every reachable player-facing entry point for illustrated scene replay, recollection, CG viewing, memories, or galleries. Prove the menu command, object, map, event, or script that opens it. Separate adjacent systems such as dialogue replay, BGM playback, achievements, and ordinary cutscenes unless the game itself includes them in the same illustrated catalog.
2. Enumerate the catalog from its authoritative slots, configured records, viewer entries, or executable dispatch table. Record the exact displayed title, source-backed group, ordering, locked and unlocked behavior, and replay/viewer path. Do not enumerate files named `cg*`, pictures shown during unrelated events, or installed-but-unused plugin data and call that complete coverage.
3. For every entry, trace both directions. From the catalog, resolve its lock requirements, replay dispatch, and every illustrated set it exposes. From the live game, find the reachable trigger, exact gate predicates, choices or branches, and unlock-state write that make the entry available. The normal in-world acquisition path is the guide's primary subject; entering a recollection room, using an unlock-all option, finishing the game to open a complete gallery, or selecting the replay tile is a catalog shortcut or replay method, not the scene's live trigger. Treat an umbrella catalog requirement such as “continue the interaction event” or “progress the story” as a lead, not finished player guidance: follow the executable chain and replace it with the nearest player-visible location, interaction, journal milestone, prior scene, and story boundary that actually unlock this entry. When several entries share the same umbrella label, distinguish their individual stages. If the game does not expose an exact action, state the narrowest proven boundary without inventing precision. A title match alone is not an unlock trace.
4. Classify acquisition explicitly. Use `normal-play` when the illustrated event occurs through reachable story, exploration, relationship, choice, battle-loss, or optional-content logic outside the replay interface. Use `gallery-only` only for a catalog reference collection or viewer record after a reverse call/picture/state search finds no standalone live event; preserve that negative reconciliation in `scene-inventory.json`. Do not relabel an untraced scene `gallery-only` to bypass research.
   For a battle-triggered catalog entry, use the `combat-scene` kind and trace the viewer routine back through the live state/status carrier, triggering skill or action, enemy action list, troop composition, and reachable encounter map or battle event. Publish exact player-visible enemy names, a recognizable area or encounter, and the action/state sequence that produces the scene. A common-event or animation name such as “human,” “tentacle,” “combat 6,” or “matching opponent” is implementation evidence, not player guidance. If a scene needs two enemies or a setup-follow-up combination, name both and explain their order. If the reverse trace finds no enemy or reachable battle that can invoke the viewer routine, classify it `gallery-only` rather than inventing a combatant.
5. Audit catalog-wide completion help separately. When the game lets the player unlock or view the entire catalog after an ending, in a recollection room, through a debug-like completion option, or by another verified shortcut, explain it once near the start of Scenes & CG. Keep it out of normal scene requirements and acquisition steps. Individual entries lead with `How to get it normally`; only genuine `gallery-only` entries explain selection in the viewer.
6. Reverse-check every player-visible requirement. Follow story progress, relationship values, party membership, items, equipment, currency, outcomes, defeat branches, prior scenes, and optional-content dependencies through the active systems that actually govern them. If a status screen, item, or companion interaction reveals hidden values, explain how the player can inspect them only when the game proves that path.
7. Reconcile title differences between the live trigger and the replay catalog. Preserve the exact catalog/replay name as `catalog_title`, but do not force a generic, numbered, untranslated, or implementation-facing label to serve as the guide heading. Give `title` a concise, source-backed player-recognizable name built from the character, enemy, encounter, location, objective, or distinguishing stage the player actually uses to find it. When the two differ, show the catalog title once beneath the heading so the player can still match the in-game menu. Keep trigger aliases separate and source-traceable. Do not silently merge distinct entries because their wording is similar, and do not invent specificity the live trace cannot prove.
8. Audit behavior that changes how a player unlocks or records a scene—view/skip choices, no-penalty defeat handling, rest randomization, scene toggles, new-game-plus resets, and automatic unlock modes—but publish it only when executable evidence shows that it affects this catalog. A similarly named option is not proof; never recommend enabling or disabling a setting merely because it mentions scenes.
9. Count catalog entries from authoritative catalog slots and count illustrated sets from the viewer references belonging to each entry. Treat one selected base image or animation set as one illustrated set rather than counting its animation frames or filesystem variants. State exactly what the number means and do not claim a count when the viewer cannot establish it.
10. Group entries by a game-authored or player-meaningful source-backed category such as character, relationship route, encounter, defeat, story phase, or gallery page. Bind each group to the earliest Main Route context where its entries become actionable, with a `before` or `after` placement justified by the actual gate. A group is organizational; it does not imply every entry unlocks at once.
11. Write compact player-facing entries: a specific guide title, the exact catalog title when it differs, a `How to get it normally` path, every displayed requirement expanded into actionable player terms, useful trigger alias, replay/viewer behavior, and illustrated-set count. For a `combat-scene`, put every required enemy directly in the guide title, then name the encounter area and explain the exact setup the player must allow. Preserve the catalog's umbrella requirement in Evidence, and bind the expanded path to live sources outside the catalog interface. Do not summarize intimate content or expose switches, variables, event IDs, plugin calls, filenames, or coordinates outside Evidence.
12. Save `scene-inventory.json` in the private walkthrough work area with the catalog boundary, dedicated interface files, entry points, any completion shortcut, configured and reachable entries, acquisition classification, reverse-search result, group/order mapping, live triggers and completions, state carriers and separate persistent unlock writes when they exist, requirements, aliases, replay/viewer dispatch, illustrated-set references, route bindings, behavior flags, and deliberate exclusions. For every `combat-scene`, retain the exact combatant names, encounter locations, trigger mechanic, enemy/action/state/troop chain, and encounter-access sources. Missing requirement, normal acquisition, trigger, live completion, title, replay, or viewer evidence blocks a `normal-play` entry; missing combat attribution blocks a `combat-scene`; missing proof that an entry is truly viewer-only blocks `gallery-only` classification. Do not invent a per-entry unlock state in a game whose catalog is globally available.

The discovery pass is intentionally system-led. Inventory what the game actively uses, then perform only the focused deep audits needed to explain its catalog accurately. Do not hardcode one game's relationship labels, plugin APIs, event ranges, or unlock rules into the reusable process.

Before rendering any view, normalize engine-authored text into browser prose. Remove purely presentational control codes such as color, icon, font-size, outline, and positioning tags after extracting any semantic value they carry; resolve name, variable, party-member, currency, and item substitutions from their verified records rather than deleting them. Validate both Markdown and public HTML for leaked engine escape sequences. Raw RPG Maker codes such as `\C[n]` must never appear outside Evidence.

## Write a route a player can follow

Before naming chapters or sections, audit every game-authored organization system: explicit Prologue/Chapter labels, chapter plugins and calls, numbered story-phase switches or variables, destination/objective displays, main-journal entries, title cards, and their update events. Do not conclude that chapters are absent merely because one chapter plugin is unused; trace the broader scenario controls and the sequence in which objective groups become active.

- When the game has both real chapters/story phases and active objectives, render `Chapter → Objective → Route step`. Preserve explicit chapter numbering and use source-backed story-phase text as a subtitle when available.
- When the game has real chapters but no named objectives, render `Chapter → Story section → Route step` and derive section boundaries from progression gates.
- When the game has no real chapter layer, use exact active main-objective or destination text as the top-level sections.
- Use neutral `Story section` headings only when the game has no player-visible hierarchy, and derive those boundaries from verified progression gates.
- Never label an editorial grouping `Chapter` merely because chapters would be convenient. A configured plugin with placeholder data or no event calls is not sufficient by itself, and sequentially named region assets are not chapters unless story progression also treats them as chapter boundaries.

Record the chosen hierarchy in `evidence.json.route_structure`. Every chapter must own at least one section; every section must own at least one route claim. Cite the game sources that define each label or boundary and render the exact bound labels. Organize route steps chronologically beneath their source-backed objective sections and chapters.

Use the following as an internal completeness check for every route step:

- **Start:** the player-visible place, situation, or previous objective that identifies the starting state.
- **Action:** what to interact with, whom to speak to, which connected exit to take, or what mandatory encounter to clear.
- **Confirmation:** the visible result that proves the player is on the intended route, such as a scene, objective update, party change, unlocked doorway, or named destination.
- **Useful pickups:** weapons, armor, key items, healing resources, or other meaningful fixed pickups directly along or immediately beside the route.
- **Exit:** where the step leaves the player and what the next step begins from.

Do not publish those five labels as a form. Turn the research into one or two connected paragraphs that read like a human-written guide. Begin from the situation created by the previous step, tell the player what to do, and end on a visible cue that naturally leads into the next step. Use a small `Worth grabbing` callout only when a pickup would interrupt the paragraph.

Keep authoring language separate from evidence language:

- Player copy describes scenes, conversations, opened paths, party changes, destination names, and rewards.
- Evidence explains event branches, state writes, source records, and why the claim is supported.
- Never tell a player that an event “advances a state,” “calls a completion process,” or “sets a branch.” Translate that result into what the player actually sees.
- Avoid repeating the same sentence as an Action and then again as a Confirmation. A confirmation should be a useful orientation cue such as “After the scene, you will be back in the chapel with Weeu in the party.”
- Vary sentence length and transitions. Let consecutive steps feel like a continuous journey rather than isolated database entries.
- Read each finished route section aloud. If it sounds like a checklist generated from fields, rewrite it before publication.

Do not omit information a player needs to recover their position; preserve it through prose rather than visible metadata labels.

### Navigation rules

- Write for a player who cannot see map IDs, event IDs, tile coordinates, switches, variables, or event-editor names.
- Prefer visible names, connected-room relationships, doors, stairs, bridges, intersections, NPC names, signs, and scene outcomes actually supported by data.
- Coordinates prove relative placement only. They do not prove north/south/east/west, visibility, passability, elevation, or the route around obstacles.
- Use compass language only when the game itself establishes orientation or the complete map/passability trace proves it. Otherwise stay at the verified room, destination, connected exit, interaction, or outcome level.
- Never invent landmarks, colors, room appearance, puzzle feedback, exact walking lines, level targets, or strategy.
- Use exact translated player-facing names. Keep technical identifiers inside the collapsed Evidence disclosure only.

### Route boundaries

Include:

- Mandatory objectives, interactions, transfers, choices, battles, and progression items.
- Alternate mandatory-entry routes when more than one path genuinely progresses the story.
- Fixed equipment and useful pickups on the route or on a clearly described immediate detour.
- A concise save/preparation warning before mandatory encounters, limited to facts supported by available mechanics and inventory.
- A short link to each completed Optional Content entry at its verified first-availability point.

Keep in their dedicated views:

- Complete collectible sweeps, relationship/companion scene routes, CG catalogs, achievement audits, and 100% completion claims. The Main Route may link to a completed entry or group without duplicating its full instructions.
- Detailed boss stats or tactics beyond what is necessary to keep the main route usable. Those belong in the completed Bosses view.

## Keep every step traceable

Give every Main Route step one stable kebab-case claim ID. Put this marker immediately before the step in `WALKTHROUGH.md`:

```markdown
<!-- route-claim:leave-opening-room -->
```

Give the matching HTML step `.route-step[data-claim-id="leave-opening-room"]`. End the step with:

```html
<details class="evidence" data-evidence-id="leave-opening-room">
  <summary>Evidence</summary>
  ...one list item per source, each with its matching data-source-id...
</details>
```

Evidence disclosures are for auditability, not player directions. Explain what each source proves in plain language, then show its technical locator. Do not paste dialogue dumps, scripts, or large event records.

Give every Optional Content group and entry globally unique stable IDs. Bind them in `WALKTHROUGH.md` with `optional-group` and `optional-entry` markers, and render matching `.optional-group[data-optional-group-id]` and `.optional-entry[data-optional-id]` elements. Every optional entry must name its first Main Route anchor and declare `route_anchor_position` as `before` when the player should see the detour before undertaking that step or `after` when completing the step causes the unlock. List prerequisite entry IDs, preserve the complete actionable chain in natural prose, show meaningful fixed rewards or unlocks, include one saved checklist control, and end with an expandable Evidence disclosure. Never place every optional callout mechanically at the bottom of its anchor step. Follow [`references/validation-evidence.md`](references/validation-evidence.md) for the exact schema and HTML bindings.

Give every Bosses group and dossier globally unique stable IDs. Bind them in `WALKTHROUGH.md` with `boss-group` and `boss-entry` markers, and render matching `.boss-group[data-boss-group-id]` and `.boss-entry[data-boss-id]` elements. Each dossier must declare all `route_claim_ids` and `optional_entry_ids` that reach it, contain at least one verified phase, display one saved checklist control, and end with an Evidence disclosure. The route/optional sources link to `#boss-<boss-id>` and the dossier links back to each source entry. Follow the evidence contract for exact stat, action, source, and HTML bindings.

Give every Scenes & CG group and entry globally unique stable IDs. Bind them in `WALKTHROUGH.md` with `scene-group` and `scene-entry` markers, and render matching `.scene-group[data-scene-group-id]` and `.scene-entry[data-scene-id][data-acquisition-mode]` elements. Each entry must declare its group, specific guide title, exact catalog title, `normal-play` or proven `gallery-only` acquisition mode, its earliest verified Main Route anchor and `before`/`after` position, prerequisite scene IDs, story-gate claim IDs, actionable acquisition steps, player-visible requirements, replay/viewer mode, illustrated-set count, source-role mapping, one saved checklist control, and one Evidence disclosure. Trace every executable availability predicate and prove the preceding route state still blocks the scene; do not infer timing from group membership, catalog order, or the route's first convenient regional visit. The Main Route links once to every completed entry at that exact anchor, may also link to its organizational group at the earliest member anchor, and the group links back. Follow the evidence contract for exact catalog, chronology, count, evidence-role, and HTML bindings.

## Build durable artifacts

Preserve the game and all user-authored files. Keep working files under `<game>/.dazedtl/walkthrough/`:

- `WALKTHROUGH.md` — editable source for all four views.
- `evidence.json` — source snapshots, route-claim ledger, optional dependency graph, boss dossiers, scene catalog, and view bindings.
- `route-graph.json` — maps/events and progression edges used during research.
- `systems-inventory.json` — bounded inventory of installed candidates, active-use proof, view relevance, and deep-audit/trace/ignore decisions.
- `boss-inventory.json` — private reconciliation of configured boss systems, reachable encounters, forms, classifications, and guide bindings.
- `scene-inventory.json` — private reconciliation of catalog slots, live triggers, requirements, unlock state, aliases, viewer references, illustrated-set counts, bindings, and exclusions.
- `project-context.md` — the completed-view subset of authoritative glossary identities, spellings, and quirks used during writing.
- `validation-report.json` — deterministic validator output.
- Focused research notes or a local renderer needed to regenerate the publication.

Publish only `<game>/WALKTHROUGH.html` at the game root. If it already exists, preserve independently verified research but rebuild the presentation and claim ledger to this contract.

## Use the walkthrough design

Read [`references/walkthrough-design.md`](references/walkthrough-design.md) completely before building HTML. It captures the required HOLLOWWALD-derived visual language plus the new four-view exception. Do not require the original HOLLOWWALD file, a screenshot, network access, a framework, a CDN, or remote fonts at generation time.

Start from [`assets/walkthrough-shell.html`](assets/walkthrough-shell.html). Copy it into the private working directory, replace its documented `{{...}}` slots, and preserve its view keys, hooks, router, accessibility behavior, and storage namespacing. Extend the shell instead of recreating it. Change theme tokens and restrained hero decoration for the game; do not fork the layout or interaction code without a verified accessibility need.

The HTML must remain a single self-contained file. With JavaScript enabled, show one active view. Without JavaScript, show all four views in semantic order and keep ordinary anchors usable.

Keep this disclaimer visible near the top of Main Route:

> **AI-generated guide:** This walkthrough was created with AI by analyzing the translated game's code and data. Main progression, optional-event chains, boss mechanics, scene requirements, gates, and rewards are source-traceable; directions intentionally focus on verified destinations and interactions rather than tile-perfect walking paths.

## Validate before publishing

Treat every change to this skill's discovery, classification, evidence, strategy, prose, or rendering behavior as a regeneration event. Rebuild the complete one-file walkthrough from its source artifacts—including every already-completed view—even when feedback names only one entry. Re-run deterministic validation, recount the published records, and manually re-audit every view the changed behavior can affect before presenting the result. Never patch only the reported example and imply that the rest of the walkthrough received the same correction. If a completed view was not regenerated or re-audited, say so explicitly instead of calling the walkthrough updated.

For RPG Maker MV/MZ, run from this skill directory:

```bash
python3 scripts/validate_walkthrough.py --game-root <game>
```

Treat validation errors as blockers. Publish only verified route claims and catalog entries. When exact navigation cannot be proven from static data, narrow the prose instead of weakening the claim or exposing a live-play warning.

Also verify manually:

- Starting from each step's stated Start, a player can identify the next action without technical data.
- Every configured major optional entry has been classified, and every published optional entry has a verified start, lifecycle, completion, dependency set, Main Route anchor, and meaningful fixed outcome.
- Main Route headings mirror the game's complete chapter/objective hierarchy; no story phase is flattened away and no editorial section is mislabeled as an official chapter.
- Every character name, pronoun, relationship, location name, and fixed term agrees with the snapshotted glossary and quirks.
- Every route transfer, gate, mandatory battle, useful pickup, and branch outcome is backed by the cited sources.
- Every system used to support a published claim is marked active in `systems-inventory.json`; every deep audit is bounded to a completed-view need, and installed-but-unused systems are not treated as game mechanics.
- All four tabs work with mouse, touch, keyboard, direct hashes, Back, and Forward.
- Search activates the destination's owning view before scrolling to it.
- Completed views contain no dead cross-links, raw coordinates, or developer identifiers.
- Every boss dossier has verified encounter, phase/enemy, displayed action/trait, and outcome evidence; route and Optional Content links match its declared bindings in both directions.
- Every boss encounter's ordinary and forced actions have been reconciled; every material forced action is either explained in the threat/strategy or deliberately classified as non-strategic in private research.
- Every recommended temporary-party tool is backed by lifecycle and encounter-start resource evidence, and every player-visible name collision is explicitly disambiguated.
- Every Scenes & CG catalog entry declares `normal-play` or a proven `gallery-only` classification. Normal entries have requirement, normal-acquisition, live-trigger, live-completion, catalog-title, replay/viewer, and illustrated-set evidence outside the catalog interface, plus a separate unlock write only when the game actually uses one. A generic catalog label is preserved for menu matching but replaced by a source-backed specific guide heading whenever the live trace makes that possible. Battle-triggered `combat-scene` entries additionally put every exact combatant in the heading, name the encounter area, explain the setup/action sequence, and cite combat-enemy, combat-trigger, and encounter-access evidence; no generic animation label substitutes for an enemy identity. Any catalog-wide completion shortcut appears once in the overview rather than replacing or repeating the normal paths.
- Scene-system advice is limited to behavior proven to affect the catalog. Relationship readouts, view/skip behavior, rest settings, defeat handling, and other game-specific mechanics are neither assumed nor suppressed by a portable rule.
- The page has no external requests and remains readable without JavaScript.
- Desktop and phone renders preserve the shared shell, hierarchy, contrast, focus visibility, and lack of horizontal overflow.

Finish by reporting the published path, working-artifact path, source-backed chapter and objective-section counts, verified route-step, Optional Content entry, boss-dossier, scene-entry, and illustrated-set counts, excluded-category counts, and validation status.
