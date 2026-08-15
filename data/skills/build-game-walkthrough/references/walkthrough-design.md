# Walkthrough Application Design

This is the portable presentation contract. It preserves the visual language of the approved HOLLOWWALD walkthrough while adding four page-like top tabs. Apply game identity through tokens and restrained decoration, not a different layout.

## Contents

- Information architecture
- Required shell
- Visual language
- Main Route components
- Optional Content components
- Bosses components
- Scenes & CG components
- View routing and cross-links
- Responsive and accessible behavior
- Interaction baseline
- Prohibited drift
- Validation checklist

## Information architecture

Use exactly these durable view keys, labels, and panel IDs:

| View key | Label | Panel ID | Milestone state |
|---|---|---|---|
| `main-route` | Main Route | `view-main-route` | Complete |
| `optional-content` | Optional Content | `view-optional-content` | Complete |
| `bosses` | Bosses | `view-bosses` | Complete |
| `scenes-cg` | Scenes & CG | `view-scenes-cg` | Complete |

Place the four `.primary-tab` controls in `.primary-tabs` at the top of the application reading area. Each control uses `data-view-target` with the exact view key and links to its panel hash. Do not add more top-level categories in this milestone.

Each `.guide-view` owns its header and content. All four views are complete and none may carry `data-placeholder="true"`. Counts and summaries must come from the evidence ledger rather than asset filenames or installed plugin defaults.

## Required shell

Retain this hierarchy and class hooks:

```text
body
├── .skip-link
├── .scroll-progress
├── .topbar
│   ├── responsive menu control
│   ├── game title + .topbar-location
│   └── focused-reading, search, and theme icon controls
├── .sidebar
│   ├── .brand
│   ├── search trigger
│   ├── .section-nav for the active view
│   └── .sidebar-progress + checklist reset
├── .sidebar-scrim
├── main.page
│   ├── nav.primary-tabs
│   └── article.guide-content
│       ├── section.guide-view#view-main-route
│       │   ├── .hero
│       │   └── .route-chapter groups
│       │       └── .route-section sections containing .route-step articles
│       ├── section.guide-view#view-optional-content
│       │   ├── .optional-hero
│       │   └── .optional-group sections containing .optional-entry articles
│       ├── section.guide-view#view-bosses
│       │   ├── .boss-hero
│       │   └── .boss-group sections containing .boss-entry articles
│       ├── section.guide-view#view-scenes-cg
│       │   ├── .scenes-hero
│       │   ├── .scene-system#scenes-cg-system
│       │   └── .scene-group sections containing .scene-entry articles
│       └── footer
├── .search-dialog
├── .resume-toast
└── .back-to-top
```

Use semantic `header`, `aside`, `nav`, `main`, `article`, `section`, `details`, `dialog`, and `footer` elements. Use inline SVG for control icons.

## Visual language

Use these shared geometry defaults:

```css
--sidebar: 19rem;
--topbar: 4.25rem;
--content: 52rem;
--radius: 1.1rem;
```

The approved look is calm editorial content inside an application shell:

- Warm, subtly graded page background; opaque or lightly translucent raised surfaces.
- Fixed full-height left sidebar and compact fixed top bar on desktop.
- Centered reading column at `min(100%, var(--content))`, without a second page-sized floating card.
- System sans-serif body type and system serif display headings. Never fetch fonts.
- Thin borders, generous vertical rhythm, rounded corners, restrained shadows, and a green-family default accent unless game evidence supports another accessible palette.
- Large rounded hero with layered radial decoration, uppercase eyebrow, serif display title, short summary, visible AI disclaimer, and four compact evidence-based stats. For this milestone, use route facts such as verified steps, source-backed chapters, objective sections, and mandatory encounters; never use guessed totals.
- Display-face section headings with a small uppercase eyebrow and top divider.
- Compact icon controls with accessible names rather than permanently visible captions.
- Callouts with a single colored left border: danger for mandatory encounters, gold for useful detours, purple for choices, blue for navigation/evidence, and accent for return-later notes.
- Bordered tables in their own horizontal scroller; never allow page-wide horizontal scrolling.

Express light/dark variants with CSS custom properties for background, surface, ink, muted, line, accent, gold, danger, choice, information, and shadows. Cycle one theme control through system, dark, and light.

## Primary tabs

Make `.primary-tabs` a prominent, restrained tab rail immediately below the fixed top bar and above the active view. On desktop it aligns with the reading column. It may become horizontally scrollable on narrow screens, but the page itself must not scroll sideways.

- Use real anchor links so the panels remain reachable without JavaScript.
- Add `role="tablist"` to the container and appropriate tab/panel relationships when JavaScript upgrades the experience.
- Show a clear selected state using accent color, surface contrast, and a bottom indicator—not pill clutter.
- Keep every tab target at least 44 CSS pixels high on touch layouts.
- Preserve labels verbatim. Do not collapse them into ambiguous icons.
- Persist the active view and reflect it in the URL hash.

## Main Route components

When chapters exist, render the source-backed hierarchy from `evidence.json.route_structure` as `.route-chapter` groups containing `.route-section` sections and individual `.route-step` articles. A chapter uses matching `data-chapter-id` and `data-chapter-label`, with its exact label in a directly linkable `h2`. Each nested objective/story section uses matching `data-section-id` and `data-section-label`, with its exact label in a directly linkable `h3`. Route-step headings are `h4`. The sidebar lists chapter headings first and indents objective headings beneath them.

For a game without a chapter layer, omit `.route-chapter`, render each `.route-section` label as a directly linkable `h2`, and keep route-step headings at `h3`. Never present an invented chapter number or title.

A route step should read like a natural passage from a player guide, not a database report or five-field form.

Start/Action/Confirmation/Pickup/Exit is a research checklist, not published UI. Blend Start, Action, Confirmation, and Exit into one or two connected paragraphs. Put an immediately useful pickup in a restrained `Worth grabbing` callout. Do not render labels such as `Start:`, `Action:`, `Confirmation:`, or `Exit:` on every step.

Keep source mechanics inside Evidence. Public prose should say what the player sees—for example, “The scene ends with Weeu joining the party”—instead of “the event advances the objective and enables the party-member state.” Use transitions between steps so a chapter reads continuously when the headings are ignored.

Each `.route-step` must contain:

- A stable `id` for direct links.
- One `data-claim-id` matching `evidence.json`.
- A short action-oriented heading.
- Natural player-facing route prose with a visible outcome woven into the passage.
- An optional compact callout for a mandatory encounter, choice, or useful detour.
- Exactly one checklist input inside a label: `<input class="task-checkbox" type="checkbox" data-task-id="claim-id">`. Its `data-task-id` must equal the route step's `data-claim-id`; use `.task-row` on the label for the shell styling.
- One final collapsed `.evidence` disclosure.

Style route steps with spacing and a subtle divider rather than making every step a heavy card. Preserve the continuous editorial reading flow.

Evidence disclosures are visually secondary:

- Use `<details class="evidence" data-evidence-id="...">` and `<summary>Evidence</summary>`.
- Begin with a small `Verified from game data` status label.
- Render one `<li data-source-id="...">` per manifest source.
- Explain what the source establishes before showing a compact monospace locator.
- Keep research limitations and discarded navigation guesses out of the player-facing disclosure. Narrow public directions to verified main details instead.
- Allow internal IDs and coordinates only inside this disclosure.
- Do not expose raw JSON, full event command lists, or long dialogue excerpts.

Completed cross-view entries use globally unique destination IDs. A working cross-link carries `data-guide-link` and an ordinary `href="#destination-id"`. Main Route links also carry `data-guide-kind="boss"`, `optional`, or `scene`; the shared shell presents them as clear red, orange/gold, or purple/pink pills with a destination arrow. Keep the surrounding callout in the matching semantic color. Never emit an anchor to material absent from the ledger and publication.

## Optional Content components

Open the view with a compact `.optional-hero` that explains its ordering rule: entries appear where the Main Route first makes them actionable. Do not repeat the Main Route's four-stat hero or imply an unverified completion percentage.

Render `evidence.json.optional_content.groups` as `.optional-group[data-optional-group-id]` sections with a matching `data-optional-group-label` and directly linkable group heading. A group may represent a source-backed chapter's opportunities or a specific postgame/ending anchor; it must not invent a second chapter system.

Render each catalog record as `.optional-entry[data-optional-id]` with:

- A globally unique `id` used by its exact Main Route cross-link.
- A small type/status line and canonical title.
- Natural player-facing prose that covers how to begin, what materially advances the chain, where to finish, and how the player knows it is done.
- A visible dependency note when another optional entry must be completed first.
- A restrained outcome block for fixed rewards, services, follow-on unlocks, or durable choices; never show a guessed reward.
- Exactly one checklist input whose `data-task-id` matches the optional entry ID.
- One final collapsed Evidence disclosure, using the same status/source binding as Main Route.

For a `companion-recruitment` entry, put the successful route first, then show a compact `How this can fail` block. Label retryable deferrals as retryable, make permanent refusals and missable points of no return unmistakable, and say which concrete interaction sets the actual recruit/support outcome. Do not bury this distinction in Evidence or imply that a personal quest automatically recruits the character. For a `progression-guide`, favor a short ordered ladder or table when it materially clarifies regional danger, shop tiers, vehicles, or capacity milestones; keep every row source-backed and link detailed boss tactics to Bosses rather than duplicating them.

The private dependency closure controls whether a long route is publishable, but do not render its graph, carrier inventory, or coverage terminology as player UI. Translate the complete node sequence into natural chronological prose. Preserve every meaningful choice, capture, battle outcome, item-custody warning, retry point, and permanent failure condition while hiding switches, variables, command indices, and graph mechanics inside Evidence.

Optional entries may use bordered editorial cards because each is a self-contained detour. Keep the typography and spacing calm; do not turn the view into a dashboard of tiny statistics. Put spoilers required to follow the event in the entry itself and keep implementation details in Evidence.

At the `route_anchor_id` step, add one concise callout with a working link to the entry. Render `route_anchor_position: before` above the route prose as `Optional detours before continuing`; render `after` below the outcome as `New optional content`. When several entries open at the same point, group the links in one restrained callout. The link should answer “what can I do now?” without forcing the player to finish the surrounding regional objective first.

Apply the same exact-anchor treatment to Scenes & CG entries. Link each newly available scene directly rather than hiding its timing behind a broad group link. If many scenes open together, keep the callout concise and place the individual purple/pink links in a collapsed `.route-link-batch`; its summary must state how many scene routes opened. A group link may accompany them for browsing, but it never substitutes for the per-entry links.

## Bosses components

Open the view with a compact `.boss-hero` that explains the evidence boundary: encounters and mechanics are verified from game data, multi-form fights are kept together, and fixed rewards are distinct from database drops. State any verified game-wide active-roster cap and reserve/Formation behavior here once. A restrained legend may name the published dossier groups; do not claim completion percentages or recommend guessed levels.

Render `evidence.json.bosses.groups` as `.boss-group[data-boss-group-id]` sections with a matching `data-boss-group-label` and directly linkable `h2`. Use player-meaningful, source-derived group labels such as Main Story Bosses, Side-Event Bosses, the game's explicit superboss category, or a verified rematch system. Grouping is organizational and must not invent a new in-game rank.

Render every dossier as `.boss-entry[data-boss-id]` with:

- A stable article ID and a directly linkable `h3` whose ID is `boss-<boss-id>`.
- A compact type/status line and an exact player-facing title.
- A `Where and when` paragraph tied to its Main Route or Optional Content source.
- Working links back to every declared source entry; those source entries link to the dossier in return.
- One phase section per materially distinct enemy form or component shown to the player. Keep transformations and required adds in encounter order.
- A compact `Battle setup` line for each phase, derived from its participant audit. Name fixed or solo battlers and describe meaningful later substitutes or encounter-specific locks when an optional encounter can be delayed. Put the game's global battle-member cap and reserve/Formation semantics in the view introduction instead of repeating the same sentence in every dossier. Do not list a companion who is removed to watch from outside combat.
- One horizontally scrollable stat table for exact HP, SP, core parameters, experience, gold, and database drops. Do not repeat the same values in a prose stat sentence, and never collapse fixed event rewards into the drops column. Bind every visible cell to its phase/stat key so validation compares the rendered value with evidence.
- A prominent weakness/resistance read derived from enemy traits and the system element table. Say when no elemental rate is encoded rather than inventing a weakness.
- A short `What to watch for` list derived from enemy schedules, skills, states, formulas, and chained/setup logic. Explain the battle consequence—such as a setup unlocking a party-wide landing attack, random hits concentrating on one ally, a buff creating an extra-action burst, a drain exhausting the party, or a turn-scaling move imposing a deadline—not merely the move's target and condition. Omit an interpretation when the data does not establish it.
- A distinct `How to win` section with a required `Battle plan` and an optional `Tools available` block. Show the tools block only when at least one specific character skill, equipment-granted skill, item, weapon, armor, accessory, or fixed reward materially improves the advice. Label published tools as guaranteed, purchasable, or conditional and bind them to an encounter-local active battler plus acquisition/database evidence. Never surface a starting/default weapon skill merely because it is present: publish equipment-bound advice only after the encounter-time loadout audit compares compatible alternatives and finds it worth the stat, trait, skill, and role tradeoff. Let the helper judge tactics from the complete encounter rather than applying cross-game rules based on target scope, formula coefficients, turn numbers, status counts, or a fixed preference for one kind of tool. Interpret party-wide and random-target mechanics using the actual participant count. Do not show Attack, Guard, healing, or another universal command merely because it is always available, and do not suppress it merely because it is universal; weave it into the plan when the game's verified selection, targeting, timing, damage, and alternatives make it useful. Tie each plan step to a verified threat and the party and tools available at that encounter, including solo sequences and later rematches.
- A restrained outcome block for fixed rewards, route gates, safe-loss behavior, rematch unlocks, or quest completion.
- Exactly one checklist input whose `data-task-id` matches the boss ID.
- One final collapsed Evidence disclosure containing all encounter, phase, action, trait, transform, and outcome sources.

Boss dossiers may use bordered editorial cards because each is a self-contained reference entry. Phase sections should read vertically; only the stat table scrolls horizontally. On wide layouts, `What to watch for` and `How to win` may sit side by side, but stack them on narrow screens. Keep numeric density inside the table and lead the prose with decisions a player can act on. Do not expose troop IDs, enemy IDs, map IDs, command indices, or coordinates outside Evidence.

## Scenes & CG components

Open with a compact `.scenes-hero` that states the catalog boundary and exact evidence-backed totals for entries and illustrated sets. Say what those totals count. Do not imply that dialogue replay, BGM playback, ordinary cutscenes, animation frames, or unrelated image files are included unless the game puts them in the same catalog.

Render one `.scene-system#scenes-cg-system` overview explaining how the player opens the catalog and any verified system-level help that materially clarifies unlocks. If the game has an ending-based unlock-all path, complete recollection room, or other catalog-wide shortcut, state it once here so completion-focused players know it exists. Frame it as an alternate viewing/completion method; the entries below still lead with their normal in-world acquisition. Examples may also include a relationship-status readout or view/skip behavior, but only when the current game's active systems prove it. End the overview with one Evidence disclosure; keep settings, state carriers, and implementation identifiers inside Evidence.

Render `evidence.json.scenes_cg.groups` as `.scene-group[data-scene-group-id]` sections with matching `data-scene-group-label` and directly linkable `h2` IDs. Use game-authored or player-meaningful source-backed groups such as characters, relationships, encounters, defeats, story phases, or gallery pages. Group headings divide a long catalog; they do not claim every contained entry becomes available together.

Render every catalog record as `.scene-entry[data-scene-id][data-acquisition-mode]` with:

- A stable article ID and a directly linkable `h3` whose ID exactly matches the scene ID. The heading uses the specific guide title rather than a generic numbered catalog label.
- A compact type/status line. When the guide title differs from the exact catalog title, show `Recollection title: <catalog title>` once beneath the heading for menu matching; do not repeat it throughout the card.
- One `.scene-acquisition[data-acquisition-mode]` section. For `normal-play`, title it `How to get it normally` and give the nearest verified player-visible sequence through the live game, followed by a short `Requirements` list that translates every gate into actionable terms. Do not replace this with the ending, recollection-room entrance, unlock-all method, or replay-tile interaction described in the overview. Do not repeat an umbrella catalog summary such as “continue this interaction event” when the live chain identifies a location, named interaction, prior scene, journal instruction, or story milestone. Preserve that summary in Evidence and cite the executable path used to expand it. For a proven `gallery-only` reference collection, title the section `Gallery-only` and plainly say that the catalog exposes no standalone in-world scene.
- For `combat-scene`, put every exact enemy in the heading and name a recognizable encounter area before explaining the required restraint, state, telegraph, loss, or follow-up sequence. Use a sourced mechanic or stage in the heading when one enemy has multiple scenes. Never make the player decode a generic catalog title such as “Combat 6,” a state label, or an animation routine. If no reachable enemy invokes the routine, render it as a proven `gallery-only` entry instead.
- A trigger-time alias only when it differs and helps the player recognize the live event.
- A restrained viewer note and exact `illustrated sets` count. Count the entry's selected sets, not frames, variants, or loose filesystem assets.
- Exactly one checklist input whose `data-task-id` matches the scene ID.
- One final collapsed Evidence disclosure covering catalog requirements/title, normal acquisition and live trigger/unlock behavior for `normal-play`, the reconciled viewer-only classification for `gallery-only`, replay/viewer dispatch, and every counted illustrated set.

Use compact editorial cards in a single-column catalog. Avoid thumbnails: the HTML must be self-contained, and guide navigation does not require reproducing the game's CGs. Keep descriptions practical and discreet—tell the player how to unlock and replay an entry, not what intimate content occurs. At each group's declared Main Route anchor, render one concise `Scenes & CG now available` callout before or after the route prose as specified. Link the group back to that route context.

## View routing and cross-links

Enhance ordinary anchors with a small hash router:

1. Determine the requested view from a tab hash or the closest `.guide-view` containing the destination ID.
2. Activate that view, update selected-tab state, rebuild or filter `.section-nav`, and then scroll to the destination.
3. Use `history.pushState` for user navigation and respond to `hashchange`/`popstate` so Back and Forward work.
4. On first load, honor a valid deep link. Fall back to Main Route for an unknown hash without throwing.
5. Search all four completed views. Before scrolling to a result, activate its owning view.
6. Do not create separate per-view copies of search, theme, progress, or drawer logic.

Add a short inline script in the document head that marks JavaScript availability. Hide inactive panels only after that marker exists. Without JavaScript, display all panels in document order and let tab anchors jump normally.

## Responsive and accessible behavior

- At approximately `64rem`, expand the top bar to full width, remove the page offset, move the sidebar off canvas, show the menu control, and open the sidebar over a scrim.
- At approximately `42rem`, reduce top-bar height and gutters, stack the hero, use two columns for hero stats, and make tabs safely horizontally scrollable.
- At `320px`, keep all controls reachable, evidence locators wrapping, and the body free of horizontal overflow.
- Apply safe-area insets where controls approach handheld edges.
- Provide strong `:focus-visible` treatment, semantic heading order, readable contrast, keyboard-operable tabs/dialog/drawer, and reduced-motion behavior.
- Keep table scrollers keyboard focusable.
- When JavaScript hides panels, manage `hidden`, `aria-selected`, and focus without leaving focus inside an inactive view.
- Print every view in order, expand evidence and spoilers, and remove application chrome.

## Interaction baseline

Preserve the approved shell behaviors:

- Active-section sidebar navigation and current-location feedback.
- Full-guide search with contextual results, keyboard focus, Escape, and `/` shortcut on desktop.
- Reading progress and Back to Top.
- Persistent checklists with explicit reset.
- Optional resume from the last meaningful destination; never force-scroll.
- Focused reading mode.
- System/dark/light theme cycling.
- Mobile drawer closing after navigation, scrim activation, or Escape.
- Namespaced local-storage keys per game and versioned state where structure may evolve.

## Prohibited drift

Do not replace the shell with a generic documentation site, dashboard, card grid, sticky text-button strip, permanently visible search field, bottom-chip navigation, or separate HTML pages. Do not make every paragraph a card. Do not add a framework, CDN, remote font, external image, or network request.

Do not use the old all-in-one table of contents as the primary information architecture. The four top tabs are the durable boundary; the sidebar is local navigation within the active view.

## Validation checklist

Before publishing:

0. If skill behavior or guide-generation logic changed, regenerate the entire single-file publication and all affected private artifacts from source. Re-audit every already-completed affected view; a hand-edited example is not evidence that the behavior propagated.
1. Confirm all required shell hooks, exact tabs, exact panels, unique IDs, and absence of placeholder views.
2. Confirm Main Route is the initial view and each tab/deep link/Back/Forward transition updates selected state and content correctly.
3. Confirm every `.route-step` has exactly one matching evidence claim and disclosure.
4. Confirm every rendered evidence source matches the manifest and every working `data-guide-link` resolves. Main Route cross-tab links use `data-guide-kind="boss"`, `optional`, or `scene` so the shared shell renders them as distinct red, orange, or purple/pink destinations.
5. Confirm every Optional Content group and entry matches the evidence ledger, has one checklist and disclosure, and receives exactly one link from its declared Main Route anchor.
6. Confirm every Bosses group and dossier matches the evidence ledger, has one checklist and disclosure, and has exact two-way links to every declared Main Route or Optional Content source.
7. Confirm the Scenes & CG overview, groups, specific guide titles, exact catalog titles, acquisition modes, normal acquisition steps, requirements, aliases, viewer modes, illustrated-set totals, checklists, and disclosures match the evidence ledger. Confirm any catalog-wide completion shortcut appears once in the overview, every `normal-play` entry leads with its live path outside the catalog interface, every differing catalog title appears once beneath its guide heading, every `combat-scene` heading names all sourced combatants while the card names its encounter area and explains the trigger sequence, `gallery-only` is backed by a completed reverse search, umbrella summaries were expanded wherever the executable chain provides a more actionable step, every entry has one exact Main Route availability link, every group binds to its earliest member and links back, prerequisite scenes and story gates never occur later than the published notice, and every counted set has a viewer source.
8. Confirm the page makes no external request, public prose contains no leaked engine control codes, and ordinary anchors/all content work without JavaScript.
9. Exercise search across all four completed views, theme, focused reading, checklists/reset, progress, resume, drawer, and Back to Top.
10. Render desktop and phone views. Check hierarchy, tab overflow, drawer behavior, optional, boss, and scene cards, evidence wrapping, controls, boss-table scrollers, and page overflow.
11. Check keyboard order, focus visibility, accessible names, dialog focus, selected-tab semantics, contrast, and reduced motion.
12. Print or print-preview; confirm all views and expanded evidence remain readable.
