# DazedTL GUI/UX Contract

**Contract version:** 1.5
**Supported theme:** dark  
**Source of truth:** `gui/theme.py` and `gui/ui_components.py`

This contract defines how every active DazedTL screen is structured, worded,
styled, reviewed, and regression-tested. It is intentionally editable: change
the contract and its tokens first, then update components, screens, fixtures,
and baselines in the same change.

## 1. Product principles

1. **Lead with the user's task.** Pages and sections describe outcomes, not
   implementation names or internal phases.
2. **One visual language.** The same hierarchy, control roles, spacing, state
   colors, and interaction rules apply throughout the application.
3. **Progressive disclosure.** Keep the common path visible. Put genuinely
   advanced or diagnostic controls behind a clearly named disclosure without
   resetting their state.
4. **Safe by construction.** Visual refactors do not alter workers, mutation
   boundaries, confirmations, file scope, or signal order.
5. **Dark mode is designed, not inherited.** Every canvas, popup, selection,
   disabled state, tooltip, dialog, and scrollbar has an explicit dark-theme
   treatment.
6. **Geometry is testable.** Layout quality includes exact margins, spacing,
   alignment, target size, clipping, overlap, and font scaling.
7. **Status is never color-only.** State uses readable text plus an icon,
   border, label, or other non-color cue.

## 2. Application information architecture

Every top-level destination follows this order:

```text
Application navigation
  Page header: title + one-sentence purpose + optional page action
  Primary task or content
    Section/card heading
    Short guidance only when it changes a decision
    Fields, choices, or data
    Local actions
  Status or activity region
```

- The left application rail owns movement between Guide, Workflow, Images,
  Version Update, Translation, Batches, Skills, Configuration, and Evaluation.
- A page may add one secondary navigation level when it represents real peer
  sections, such as Configuration categories. Do not add navigation for a
  single form or for actions.
- Guided multi-step work uses the workflow rail, numbered stage cards, footer
  navigation, and collapsible Activity panel from `gui/workflow_components.py`.
- Ordinary pages use `PageHeader`, `SectionCard`, semantic action buttons, and
  the shared form rules from `gui/ui_components.py`. They are organized around
  the page's dominant job rather than presented as miniature workflows.

### Page archetypes

Choose the layout from the user's dominant job before choosing components:

| Archetype | Dominant region | Supporting regions |
|---|---|---|
| Guided workflow | Current step and its completion action | Step rail, help, activity, previous/next |
| Browser + inspector | Searchable list/grid and selected-item preview | Source selector, filters, contextual actions, status |
| Editor | Editable document or file set | File/topic navigation, save/reload actions, validation status |
| Monitor/history | Table, live activity, or result log | Compact action toolbar and selected-item details |
| Settings | Aligned forms grouped by user decision | Presets, reset/save actions, concise guidance |

Cards express grouping; they do not determine information architecture. Do not
give every group equal size. The dominant region expands, supporting regions
remain compact, and contextual actions sit beside or directly below the content
they affect.

## 3. Design tokens

Do not add literal theme colors or ad hoc spacing to active GUI code. Use the
named values in `gui/theme.py`.

### Color roles

| Role | Purpose |
|---|---|
| `canvas` | Page and editor background |
| `chrome` | Application rails, navigation, and persistent headers |
| `surface_1` | Cards and secondary controls |
| `surface_2` | Inputs, elevated controls, and popups |
| `surface_hover` | Hovered neutral surface |
| `border` / `border_strong` | Ordinary and emphasized boundaries |
| `text_primary` | Titles and high-priority content |
| `text_secondary` | Ordinary labels and body copy |
| `text_muted` | Descriptions and metadata |
| `text_disabled` | Disabled or unavailable content |
| `accent` / `accent_text` | Primary action and active navigation |
| `focus` | Keyboard focus |
| `success` / `warning` / `danger` | Semantic state only |
| `selection` | Selected rows, text, tabs, and menu items |

Near-duplicate colors are not acceptable. A new semantic need must be added to
`Colors`, contrast-checked, documented here, and used by more than one screen
unless an exception is approved.

### Spacing and geometry

Use the 4 px grid exposed by `Spacing`: 4, 8, 12, 16, 24, and 32 px.

- Page margin: 24 px at normal width; 16 px at constrained width.
- Card padding: 16 px, or 12 px for compact workspaces and dense forms.
- Related fields/actions: 8 px apart.
- Related groups inside a card: 12 px apart.
- Separate cards or major sections: 16 px apart.
- Compact, standard, and prominent control heights: 32, 36, and 40 px.
- Minimum interactive target: 32 by 32 px.
- Control radius: 4 px; card radius: 6 px.
- Standard form-label column: 112 px. A page may use one wider measured column,
  but all labels on that form must share it.

Two- and three-pixel values are reserved for borders and optical icon
alignment. Fixed text widths require a documented alignment reason and must
pass the 200% font-scale capture.

### Typography

Use semantic object names/components rather than per-label font styles.

| Role | Size | Weight |
|---|---:|---:|
| Page title | 18 px | 600 |
| Section/task title | 14 px | 600 |
| Body/control | 12 px | 400/600 |
| Purpose/help text | 12 px | 400 |
| Eyebrow/metadata | 11 px | 600 |
| Code/editor | application monospace | 400 |

Text must remain legible at 100%, 150%, and 200% application font scale.

## 4. Page and card contract

### Page header

- Title names the destination or outcome: `Translate Images`, `Configuration`.
- Purpose is one sentence explaining what can be accomplished here.
- Do not repeat the title in a card immediately below it.
- Help is a quiet or secondary action on the right when page-specific help
  exists.

### Cards and sections

- One card represents one decision, task, or coherent data view.
- Numbered cards are exclusive to genuine guided workflows with navigation,
  progress, and a meaningful current step. Ordinary tool panels are never
  numbered merely because their actions have prerequisites.
- Use `SectionCard` for peer tools, stable data views, reference content, or
  settings categories that users may visit in any order.
- Give the dominant workspace the expanding area. Supporting setup, filters,
  utilities, and status should be compact and physically attached to the
  workspace they affect.
- Card titles begin with a verb when the card is a task (`Select files`) and a
  noun when it is a stable information group (`API connection`).
- Descriptions explain consequences, prerequisites, or scope. Delete text that
  merely restates the title.
- The primary action is placed at the end of the task's natural reading order.
- Avoid nested bordered cards. Use spacing, a subheading, or a disclosure for
  hierarchy inside a card.
- Do not wrap a single list or editor in a titled card when the page header and
  the control itself already establish its purpose.

## 5. Controls and actions

### Button roles

| Variant | Use | Limit |
|---|---|---|
| `primary` | Advances or performs the card/page's main outcome | Normally one per card |
| `secondary` | Alternative or supporting action | Any justified number |
| `quiet` | Navigation, disclosure, refresh, reload, or low-emphasis utility | Must remain discoverable |
| `danger` | Destructive or difficult-to-reverse action | Requires clear scope; confirmation when material |

- Buttons use an outcome verb and an object: `Translate selected files`,
  `Save defaults`, `Remove Forge`.
- Do not expose internal modes in button text when a user outcome is clearer.
- Use sentence case. Avoid ALL CAPS, slashes, arrows as grammar, and unexplained
  abbreviations.
- Use `…` only when the action opens a chooser or requires more input.
- Related peer buttons have identical rendered width and height. Declare the
  group with `equalize_button_widths`; unrelated actions continue to size to
  content.
- Secondary and quiet buttons retain a visible one-pixel boundary in every
  state. Filled accent styling is reserved for an explicit primary action.
- A single-row action group must fit inside its container at every supported
  scale. Use shorter responsive labels or a deliberate overflow/disclosure
  pattern when necessary; never allow the final action to be clipped offscreen.
- Every visible control must remain inside its immediate parent's content
  bounds. Cards preserve their standard padding around contained controls.
- Edge-adjacent controls preserve at least 8 px of breathing room unless the
  control is intentionally edge-attached by its component contract.
- Icons supplement text. Icon-only actions require an accessible name and
  tooltip.

### Fields

- Labels use concise nouns (`Source folder`, `Translation mode`).
- Placeholder text is an example or expected format, never the only label.
- Units belong in the label or suffix, not repeated in every option.
- Fields in one logical form align to one label column and one control height.
- Checkbox text states the enabled condition positively. Put engine/event codes
  in parentheses after the human meaning when they are useful.
- Disabled controls remain readable and have a nearby prerequisite or tooltip.

### Tabs, lists, and tables

- Tab labels are short nouns and use sentence case.
- Selected, hovered, focused, and disabled states must all be explicit.
- Lists and tables provide an empty-state explanation rather than appearing
  broken or blank.
- Row actions operate only on the visible/selected scope stated by the UI.
- Interactive file collections support the platform-standard multi-selection gestures:
  Ctrl-click adds or removes individual files, Shift-click selects a contiguous
  range, and Ctrl+A selects all visible files.
- In checkable file collections, checkmarks are the authoritative action scope.
  Modifier gestures update the affected checkmarks as well as the visible
  gesture range, so Ctrl/Shift never creates a highlight-only action scope.

## 6. Copy glossary

Prefer these verbs consistently:

- `Select` for choosing existing items in the UI.
- `Choose…` for opening a native file/folder chooser.
- `Import` for copying source data into the workspace.
- `Translate` for translation runs.
- `Preview` for a read-only analysis of a later mutation.
- `Apply` for committing configured changes to the current target.
- `Export` for writing reviewed translations to a game/output.
- `Copy` for clipboard or file-copy actions.
- `Install` / `Remove` for optional tooling.
- `Save` / `Reload` for persisted editable content.
- `Refresh` for a read-only state update.
- `Build` for creating a release artifact.

Avoid `Run`, `Do`, `Process`, `Execute`, `Active`, `Core`, `TL`, and numbered
phase names unless no clearer user outcome exists. Confirmation titles and help
copy must use the same nouns as their triggering controls.

## 7. Dark-mode and state contract

- The canonical `QPalette` and application stylesheet are always applied,
  including headless captures.
- Page-local QSS may select semantic object names but may not introduce literal
  colors that duplicate the palette.
- Combo popups, menus, dialogs, message boxes, tooltips, editors, scroll-area
  viewports, and disabled inputs must be inspected independently.
- Primary text meets WCAG AA contrast against its surface. Secondary and muted
  text must remain readable; semantic colors do not replace labels.
- Success, warning, error, busy, empty, complete, and disabled states are part
  of the screen contract, not afterthoughts.

## 8. Responsive and accessibility contract

- Supported viewports: 1280×720, 1440×900, and 2048×1226.
- Supported font scales: 1.0, 1.5, and 2.0.
- Scrolling is acceptable. Clipped labels, overlapping widgets, off-screen
  actions, and unreachable controls are not.
- Layouts use stretch and size policies before fixed dimensions.
- Focus order follows visual reading order. Every interactive control is
  keyboard reachable and has a visible focus state.
- Icon-only controls have an accessible name and tooltip.
- Descriptions and state labels support text selection when users may need to
  copy a path or diagnostic.

## 9. Behavior-preservation contract

A GUI migration must retain:

- signal targets and action boundaries;
- worker ownership, cancellation, and lifetime handling;
- exact file-selection and mutation scope;
- confirmations for destructive/material actions;
- saved-setting keys and default behavior;
- engine-specific availability and validation; and
- status/error reporting.

Tests should locate controls by stable semantic object name or exact user-facing
contract text, then assert the original endpoint. A visual change is not
permission to combine actions or remove a safety prompt.

## 10. Executable quality gates

Every GUI change must run, in proportion to its scope:

1. Relevant action/behavior tests.
2. `tests/test_gui_ux_contract.py` for token, component, and semantic-role rules.
3. The page capture harness for changed destinations and states.
4. Geometry audit with zero unexplained clipping, overlap, off-token spacing,
   or undersized-target violations.
5. The complete repository test suite before handoff.

The full release matrix is every active page at the three supported viewports,
three font scales, and ready/empty-or-warning/error states. Captures use invented
paths/content, isolated settings, a temporary working directory, no API keys,
no network, and no mutation actions.

Run the executable gates from the repository root:

```bash
./.venv/bin/python -m unittest tests.test_gui_ux_contract
./.venv/bin/python scripts/capture_app_ui.py \
  --sizes 2048x1226,1440x900,1280x720 \
  --font-scales 1,1.5,2 --states default,active,disabled,error --overlay
./.venv/bin/python scripts/capture_workflow_ui.py \
  --sizes 2048x1226,1440x900,1280x720 \
  --font-scales 1,1.5,2 --states ready,error,disabled --overlay
./.venv/bin/python scripts/run_workflow_action_harness.py
./.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

Generated evidence is written below `.tmp-ui/` and is intentionally not part
of the shipped application.

## 11. Iteration protocol

1. Record the problem with a screenshot and a precise observation.
2. Identify the violated contract rule or propose a contract revision.
3. Change tokens/components before applying one-off page fixes.
4. Capture the affected page at 100%, 150%, and 200% scale.
5. Inspect geometry JSON and overlay, then inspect the image visually.
6. Verify action contracts and the full suite.
7. Update help/copy and the adoption table when labels or structure change.

Do not approve a screen from a single desktop-size screenshot.

## 12. Exceptions and contract changes

An exception must be narrow and documented beside the code with:

- the rule being overridden;
- why the standard component cannot satisfy the product need;
- the exact affected screen/control; and
- the visual/test coverage that prevents regression.

Contract changes require the contract version to advance when they alter a
normative rule, token meaning, supported matrix, or component API. Pure wording
clarifications do not require a version bump.

## 13. Adoption checklist

An active screen is migrated only when it has:

- a semantic page header and purpose;
- tokenized margins, spacing, colors, and typography;
- standardized action variants, fields, checks, tabs, and status states;
- clear and consistent user-facing copy;
- no unexplained page-local literal theme colors;
- safe ready/empty-or-warning/error fixtures;
- responsive geometry reports at all supported font scales; and
- behavior tests for every material action.

## 14. Active implementation map

| Surface | Required foundation |
|---|---|
| Application shell | `appSidebar`, semantic navigation roles, canonical palette |
| Guide | `PageHeader`, shared actions, tokenized document/list surfaces |
| RPG Maker workflow | Guided-workflow rail, stage cards, footer, Activity panel |
| WOLF workflow | Guided-workflow rail, page headers, footer, Activity panel |
| Image Manager | `PageHeader`, dominant browser workspace, compact source/filter controls, bounded preview, contextual actions |
| Version Update | `PageHeader`, repository detection, first-time branch bootstrap, official-release update, recovery, and activity cards |
| Translation | `PageHeader`, run setup plus file/progress cards, and a persistent side-by-side Translation Log; the log is primary run feedback and is never collapsed |
| Batch History | `PageHeader`, toolbar card, shared table/editor card |
| Skills & Prompts | `PageHeader`, shared editor card, tabs, actions and status |
| Configuration | `PageHeader`, labeled secondary navigation, aligned setting cards in every engine category |
| Evaluation | `PageHeader`, dynamic provider/key/model rows, simple test-size and budget controls, explicit paid-submit confirmation, peer score-summary and output-comparison views, a sample browser with aligned source/model output inspection, and bounded activity log |
| Tool Update dialog | semantic title, card, status steps, and action variants |

The application capture harness covers these top-level destinations, every
Configuration category, both workflow engines, and the Tool Update dialog. The
dedicated RPG Maker workflow harness remains the deeper per-step/action fixture.
