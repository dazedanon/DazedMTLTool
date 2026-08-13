# Shared Walkthrough Design

This bundled document is the canonical, portable design contract for generated walkthroughs. Do not require a screenshot, previously published guide, network resource, framework, font, or other external design reference.

## Contents

- Required shell
- Geometry and responsive behavior
- Shared component appearance
- Interaction contract
- Theme variation
- Prohibited structural drift
- Required validation

## Required shell

Keep this landmark and component hierarchy. Additional accessible wrappers are allowed, but do not replace or rename the required hooks.

```text
body
├── .skip-link
├── .scroll-progress
├── .topbar
│   ├── menu control (responsive)
│   ├── game title + .topbar-location
│   └── focused-reading, search, and theme icon controls
├── .sidebar
│   ├── .brand
│   ├── search trigger
│   ├── .section-nav
│   └── .sidebar-progress + checklist reset
├── .sidebar-scrim
├── main.page
│   └── article.guide-content
│       ├── .hero
│       │   ├── eyebrow
│       │   ├── display title
│       │   ├── short summary
│       │   ├── visible AI disclaimer
│       │   └── .hero-stats with four coverage statistics
│       ├── complete walkthrough sections
│       └── footer
├── .search-dialog
├── .resume-toast
└── .back-to-top
```

Use semantic `header`, `aside`, `nav`, `main`, `article`, `section`, `dialog`, and `footer` landmarks where applicable. Use inline SVG for control icons so the single published HTML remains offline.

## Geometry and responsive behavior

Define shared geometry with CSS custom properties:

```css
--sidebar: 19rem;
--topbar: 4.25rem;
--content: 52rem;
--radius: 1.1rem;
```

- Fix the full-height sidebar to the left on desktop.
- Fix the top bar above the page and begin it at the sidebar's right edge.
- Offset `.page` by the sidebar width and top-bar height.
- Center `.guide-content` at `min(100%, var(--content))` within responsive gutters. Do not wrap the entire reading column in a second floating article card.
- At approximately `64rem` viewport width, move the top bar to the full width, remove the page offset, hide the sidebar off canvas, show a menu icon, and open the sidebar as a drawer over `.sidebar-scrim`.
- At approximately `36rem`, reduce the top-bar height and page gutters, keep the hero single-column, and arrange hero statistics in two columns.
- Keep every interactive target at least 44 by 44 CSS pixels on touch layouts.
- Contain wide tables in keyboard-focusable horizontal scrollers. Never make the whole page scroll sideways.
- Use safe-area insets where controls approach phone or handheld screen edges.

The desktop layout must read as one continuous application shell: fixed navigation on the left, compact controls above, and a calm centered reading column. The phone layout must read as the same shell collapsed into a top bar and drawer—not a different design.

## Shared component appearance

- Use a body sans-serif stack and a system serif display stack. Do not fetch fonts.
- Render the hero as a large rounded panel with a subtle border, layered radial decoration, restrained shadow, uppercase eyebrow, large serif title, summary, disclaimer, and four compact statistic cards.
- Render major section headings in the display face with a small uppercase `Section` eyebrow and top divider.
- Render immediate subsections as smaller display headings in the accent color.
- Render the AI disclaimer as an information callout inside the hero.
- Use consistent callout panels with one colored left border: danger for bosses, choice color for decisions, gold for optional/before-leaving notes, information color for navigation, and accent color for return-later notes.
- Use native `details` and `summary` for spoilers. Show a plus indicator that rotates when open.
- Use custom checkboxes with a visible checked mark, line-through completed text, persistent local state, and sidebar completion count/meter.
- Use bordered, rounded table containers; tint headers with the accent-soft token and alternate body rows subtly.
- Use a thin fixed scroll-progress line across the viewport.
- Highlight the active sidebar link with an accent-soft background and a narrow accent bar.
- Keep top-bar actions as compact icon buttons. Put explanatory text in accessible labels, not permanently visible button captions.

## Interaction contract

- Populate `.section-nav` with major headings and their immediate subsections. Make the navigation list independently scrollable.
- Update `.topbar-location` and active navigation as the reader scrolls.
- Persist checkboxes, theme, focused-reading preference, and last heading in local browser storage. Namespace keys per game.
- Cycle one theme control through system, dark, and light modes. Do not use three separate theme buttons.
- Focused-reading mode must hide the desktop sidebar and expand the page without removing guide content.
- Open full-guide search in `.search-dialog`; support contextual results, result highlighting, keyboard focus, Escape, and `/` as the desktop shortcut.
- On a later visit, offer `.resume-toast` for the last meaningful heading. Do not force-scroll without consent.
- Reveal `.back-to-top` only after substantial scrolling.
- Close the mobile drawer after navigation, scrim activation, or Escape.
- Respect `prefers-reduced-motion`.
- Keep the entire document readable, navigable by ordinary links, printable, and semantically ordered when JavaScript is disabled.

## Theme variation

Keep layout CSS and behavior shared. Express game identity through tokens and a few decorative elements only:

- Background, surface, ink, muted, line, accent, gold, danger, choice, and information colors.
- Light and dark values for those tokens.
- A small CSS-only brand mark.
- Hero radial-gradient colors or a similarly restrained CSS-only motif.
- Game title, guide summary, and four evidence-based coverage statistics.

Choose theme cues supported by game art/data or use neutral genre cues. Maintain WCAG-readable contrast. Do not change navigation placement, content width, breakpoints, control types, component hierarchy, or interaction behavior merely to make a game feel different.

## Prohibited structural drift

Do not replace the shared shell with:

- A sticky horizontal strip of text controls.
- A permanently visible inline search field in the top bar.
- Bottom chip navigation as the primary phone navigation.
- A floating article card paired with a separate floating sidebar card.
- Multiple visible light/dark/system buttons.
- A top bar without current-location feedback.
- A sidebar without nested navigation or checklist progress.
- A hero without the disclaimer and four coverage statistics.
- External UI frameworks, CDNs, remote fonts, or image dependencies.

## Required validation

Before publishing:

1. Verify every required hook exists: `.topbar`, `.topbar-location`, `.sidebar`, `.brand`, `.section-nav`, `.sidebar-progress`, `.page`, `.guide-content`, `.hero`, `.hero-stats`, `.search-dialog`, `.resume-toast`, and `.back-to-top`.
2. Verify the desktop sidebar is fixed and the page/top bar are offset by its width.
3. Verify the sidebar becomes an off-canvas drawer and a menu control appears at the responsive breakpoint.
4. Verify the phone layout has no horizontal page overflow and all controls remain reachable at 320 CSS pixels wide.
5. Verify search, theme cycling, reader mode, checklist persistence/reset, active navigation, resume, back-to-top, and drawer closing.
6. Verify focus visibility, accessible names, dialog focus behavior, reduced motion, contrast, and semantic heading order.
7. Verify print styles remove application chrome, reveal spoiler bodies, preserve checkboxes, and prevent table clipping.
8. Verify the generated HTML contains no external requests and remains fully readable with JavaScript disabled.
9. Render desktop and phone screenshots. Compare their geometry and hierarchy directly to this contract.
