---
name: build-game-walkthrough
description: Build a spoiler-conscious, evidence-based 100% game walkthrough as a self-contained responsive HTML file by auditing local game code and data. Use when a translated RPG Maker or WOLF RPG project needs player-facing story routing, side content, collectibles, puzzles, combat guidance, achievements, postgame, and New Game+ coverage.
---

# Build a Game Walkthrough

Use the selected project supplied by DazedTL:

- Game root: `{{GAME_ROOT}}`
- Engine hint: `{{ENGINE}}`

Work autonomously through research, authoring, cross-checking, and rendering. Do not stop after producing research notes or a Markdown draft.

## Protect the project

- Treat the game root as the complete audit scope.
- Preserve all existing game, translation, and user-authored files.
- Create working material only under `<game>/.dazedtl/walkthrough/`.
- Publish only `<game>/WALKTHROUGH.html` at the game root.
- Add a narrow Git ignore exception for `WALKTHROUGH.html` only when the existing ignore rules would otherwise hide it. Do not rewrite unrelated ignore rules.
- If walkthrough files already exist, inspect and improve them instead of discarding verified work.

## Establish evidence

1. Detect the actual engine and game version; treat the engine hint only as a starting point.
2. Inventory all relevant maps, transfers, event pages, common events, variables, switches, journal entries, achievements, enemies, troops, drops, items, skills, states, puzzles, optional areas, postgame gates, and replay flags that actually exist in the project.
3. Audit independent bounded areas in parallel when subagents are available: main progression; maps and fixed pickups; side content and relationships; combat, achievements, postgame, and New Game+.
4. Resolve disagreements against the executable data. Record remaining uncertainty explicitly.

Use hard evidence throughout:

- Do not invent visual landmarks, colors, minimaps, directions, level requirements, expiration rules, rewards, or route behavior.
- A coordinate proves relative placement, not what a player sees. Use compass/area language only when supported, and mark exact walking approaches as unverified when static data cannot establish them.
- Keep internal map IDs, coordinates, event IDs, switches, and variables out of player-facing directions.
- Use the game's own translated terminology. Do not assume that a familiar system, collectible, fast-travel object, or quest category exists or impose a generic name on it.
- Label combat preparation as a code-derived recommendation unless verified through live play.
- Distinguish a battle configured to allow defeat from a defeat branch that actually advances the story.
- Describe NG+ content as exclusive only when the dedicated replay conditions gate it.

## Cover the complete game

Make the main route sufficient for 100% completion without consulting a technical appendix. Include:

- A chronological main-story route with recognizable, evidence-supported starting points and alternate-entry instructions.
- Fixed treasure and fast-travel points, when present, integrated at the moment they become reachable.
- **Before Leaving** audits with running collectible totals.
- A spoiler-light side-content timeline showing earliest confirmed availability.
- Every side quest, optional area, optional boss, relationship route, choice, achievement, puzzle, postgame chain, ending, and New Game+ behavior found in the data.
- Neutral choice explanations. Recommend a branch only when it is demonstrably required for a stated completion definition; otherwise let the player choose.
- Puzzle hints before direct solutions.
- Concise party-role guidance for each story period and code-derived tactics for every mandatory, optional, and enhanced boss.
- Readiness benchmarks based on mechanics and available equipment, not invented level thresholds.
- A final audit of the completion systems that exist, such as journal entries, achievements, bonds, bosses, collectibles, fast-travel points, unique treasure, compendium entries, postgame, and replay readiness.

Use consistent callouts:

- **Optional Detour**
- **Return Later**
- **Boss Ahead**
- **Choice Ahead**
- **Before Leaving**
- **Navigation Note**

Protect readers from spoilers. Keep major future events vague until the route reaches them. Reveal ordinary encounter names, immediate rewards, and relevant tactics at the arena; collapse genuine future identity, phase, ending, or early-completion revelations.

## Build the artifacts

Keep these ignored authoring files under `<game>/.dazedtl/walkthrough/`:

- `WALKTHROUGH.md` as the editable source.
- Focused research reports and any local build script needed to regenerate the publication.

Create `<game>/WALKTHROUGH.html` as a single offline file containing all markup, styles, scripts, and walkthrough content. It must not require the Markdown source, a server, internet access, remote fonts, CDNs, frameworks, or other assets.

Include:

- Responsive phone, tablet, desktop, and handheld layouts.
- Touch-friendly chapter navigation and a desktop sidebar.
- Full-guide search.
- Reading progress and optional continue-from-last-section behavior.
- Persistent checklists using local browser storage with an explicit reset action.
- Native spoiler-safe collapsible sections.
- System, light, and dark themes.
- Focused reading mode.
- Accessible semantic markup, keyboard focus, readable contrast, and reduced-motion support.
- Horizontal table containment on narrow screens.
- Print/PDF styles.
- Complete readability without JavaScript; only enhanced interactions may depend on it.

Place this visible disclaimer near the beginning:

> **AI-generated guide:** This walkthrough was created with AI by analyzing the translated game's code and data. It has not been fully verified through a live playthrough, so code-derived navigation and strategy recommendations may contain errors or differ from the experience in game.

## Validate before finishing

- Reconcile every claimed total with the source events and rewards.
- Verify first availability and route order for each collectible and optional event.
- Check that every internal HTML anchor resolves and every element ID is unique.
- Confirm that the HTML makes no external requests and remains useful with JavaScript disabled.
- Parse or syntax-check inline JavaScript.
- Render at desktop and phone widths when a local browser is available; correct clipping, overflow, unreadable controls, and table behavior.
- Scan the player-facing guide for developer locators and unsupported visual assumptions.
- Preserve a concise list of static-analysis limitations rather than converting uncertainty into fact.

Finish by reporting the published HTML path, ignored authoring path, major verified totals, validation performed, and any remaining live-play uncertainties.
