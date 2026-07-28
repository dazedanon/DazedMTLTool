# RPG Maker Workflow GUI Overhaul Plan

## Status

Implemented and verified on 2026-07-28. The workflow behavior remains stable;
this project changes its presentation, interaction hierarchy, and
visual-development tooling while preserving the existing translation pipeline.
The current build is the visual-review candidate; future visual changes should
use the iteration protocol and capture harness defined below.

### Completion record

- All nine RPG Maker pages now use the shared vertical shell, standard headers,
  semantic actions, tokenized spacing, and collapsible Activity panel.
- A follow-up structural pass introduced numbered task stages on every page.
  Project follows choose/select/import; Prepare separates its three optional
  helpers; Phase 1 follows configure/database/dialogue/cache; and the remaining
  pages expose similarly explicit task sequences through final verification.
- A final control-layout pass aligns the navigation rail into fixed number and
  label columns, gives related actions shared flexible width tiers, standardizes
  control heights and form-label columns, and aligns checkbox and field grids
  without clipping labels at larger font scales.
- The explicit Qt palette and stylesheet cover dark canvases, popups, editors,
  selections, focus, disabled controls, and scrollbars.
- Sanitized ready/empty/busy/warning/error/complete/disabled fixture states are
  available without reading user settings or invoking workflow actions.
- The final structural stress audit rendered every step at 1280x720, 1440x900,
  and 2048x1226 with 100%, 150%, and 200% fonts in ready, warning, and error
  states. Its 243 step inspections contain zero geometry violations.
- The repository test suite passes: 535 tests, including the new theme,
  navigation, disclosure-state, activity-persistence, and image-diff tests.
- The action harness clicks 49 production control routes across all nine steps
  and runs 16 real-handler contracts against disposable MV, MZ, and Ace
  fixtures with workers, dialogs, subprocesses, and installers substituted.
- MV/MZ and Ace action contracts are recorded in the companion behavior
  inventory. Platform-native manual review remains appropriate before a release
  build, especially on Windows, but is not required to continue token-driven
  visual iteration.

## Goal

Make the RPG Maker workflow feel like one coherent guided application rather
than nine separately styled utility pages. The completed workflow must be:

- visually consistent across every step and state;
- easier to scan without removing advanced functionality;
- comfortable in dark mode, including native Qt popup and disabled states;
- usable at the application's supported window sizes, DPI settings, and font
  scales;
- measurable down to widget geometry, layout margins, spacing, and typography;
- safe to iterate on through deterministic screenshots and layout reports; and
- behaviorally compatible with the existing RPG Maker MV, MZ, and Ace workflow.

The visual system and capture tooling should be reusable by the WOLF workflow,
but migrating WOLF is not part of this project.

## Current baseline and reasons for the overhaul

The RPG Maker workflow currently has nine steps in `gui/workflow_tab.py`, a
permanent right-side log, a hidden `QTabWidget`, and a custom horizontal step
strip. The functionality is mature, but presentation rules are distributed
throughout the file.

The initial audit found:

- more than 60 distinct hex colors in the workflow, including many
  near-duplicates;
- spacing values ranging across 2, 3, 4, 6, 8, 10, 12, 14, 16, 18, 24, and 30
  pixels;
- repeated inline definitions for cards, buttons, labels, checkboxes, lists,
  scroll areas, and status messages;
- conflicting application-level and workflow-level widget styles;
- workflow backgrounds that depend on inherited application styling and can
  render as a light canvas when the page is instantiated independently;
- inconsistent page density, action placement, button emphasis, headings, and
  status presentation;
- fixed heights and widths that can become fragile under font scaling; and
- a nine-item horizontal step strip whose labels are cramped at narrower window
  sizes.

Before implementation begins, capture the current integrated workflow at every
step. These images form the visual baseline, not the desired design.

## Scope

### Included

- The RPG Maker workflow container and its nine workflow steps.
- The engine-selector bar when RPG Maker is active.
- Workflow navigation, page headers, task cards, fields, action rows, statuses,
  advanced sections, lists, editors, and the workflow log.
- A centralized dark palette and workflow component styles.
- A deterministic screenshot, geometry-report, overlay, and comparison tool.
- Empty, ready, disabled, busy, successful, warning, and error presentation.
- Keyboard focus, contrast, font scaling, DPI scaling, and narrow-window
  behavior.
- Preservation tests for all existing actions and workflow state transitions.
- Help text changes needed to match the new layout.

### Not included

- Changing phase profiles or translation behavior.
- Changing which files are imported, exported, rewritten, packed, or patched.
- Changing API providers, translation modes, prompt content, or pricing logic.
- Redesigning the Translation, Images, Configuration, or WOLF workflow pages.
- Adding a light theme. Dark mode is the supported design target for this
  project.
- Rewriting the application in another GUI framework.

## Non-negotiable safety rules

1. A visual refactor must not execute, reorder, or silently combine workflow
   actions.
2. The capture tool must never read a real API key, mutate `.env`, use the
   user's saved game path, import files, start workers, or write into a game.
3. Real project paths and game content must not appear in committed screenshots.
4. Existing signals, worker lifetimes, confirmations, and destructive-action
   warnings remain intact.
5. Advanced controls may be collapsed, but they must remain discoverable and
   must not reset when collapsed.
6. Status must never be communicated by color alone. Use text plus an icon,
   border, or state label.
7. Every supported font scale must remain operable. Scrolling is acceptable;
   clipped controls and unreachable actions are not.

## Target information architecture

The workflow should use a stable three-part shell:

```text
+------------------+--------------------------------------+------------------+
| Step rail        | Current step                         | Activity         |
|                  |                                      |                  |
| 0 Project        | Step label                           | Workflow log     |
| 1 Prepare        | Page title                    Help   | and progress     |
| 2 Setup          | One-sentence purpose                 |                  |
| 3 Phase 1        |                                      | Collapsible      |
| 4 Phase 2        | Task card                            |                  |
| 5 Export         | Task card                            |                  |
| 6 Rewrap         |                                      |                  |
| 7 Images         |                                      |                  |
| 8 Playtest       |                                      |                  |
|                  +--------------------------------------+                  |
|                  | Back                         Continue|                  |
+------------------+--------------------------------------+------------------+
```

### Step rail

- Replace the equally divided horizontal strip with a vertical rail.
- Use the existing nine steps and order.
- Show step number, short name, and state: current, complete, warning, or not
  started.
- Use a check icon and text treatment for completion, not green text alone.
- Keep keyboard navigation and direct step selection.
- Use a 176 px expanded width. At constrained widths, allow a compact 56 px
  number/icon rail with tooltips rather than shrinking labels until unreadable.

### Page header

Every page uses the same structure:

1. small `Step N of 9` eyebrow;
2. concise page title;
3. one sentence explaining the outcome of the page;
4. a text-and-icon Help action in the same location; and
5. an optional page-level status or `Optional` badge.

The title should not include `Step N` because the step indicator already owns
that information.

### Content column

- Center the content within the available area.
- Use a maximum readable width around 1040 px while allowing dense lists and
  editors to consume the full available width.
- Use task cards as the primary grouping mechanism.
- Keep task order vertical and outcome-oriented.
- Put advanced or uncommon controls in labeled disclosure sections.
- Avoid decorative separators when spacing and card boundaries already express
  grouping.

### Navigation footer

- Keep Back and Continue in a stable footer.
- Continue is the single emphasized navigation action.
- The footer must not obscure scrolling content.
- If leaving a step performs existing automatic behavior, preserve it and make
  that behavior clear in nearby copy.

### Activity panel

- Replace the permanently wide log with a collapsible Activity panel.
- Show a compact activity control with unread/error count when collapsed.
- Default to collapsed below 1320 px window width.
- Remember the user's expanded/collapsed preference, except when responsive
  constraints require collapse.
- Give running work a concise summary and progress above the detailed log.
- Preserve Clear Log and existing log output.
- Never hide a new error silently: update the activity badge and make the panel
  easy to open.

## Dark-mode visual contract

Dark mode must be explicit rather than an accidental result of parent-widget
inheritance. The workflow root, step rail, page viewport, cards, inputs, popups,
tooltips, log, and dialogs must each receive an intentional surface role.

### Proposed palette

These are the initial tokens. Tune them from integrated screenshots, but do not
introduce page-specific substitutes without documenting a new semantic role.

| Token | Initial value | Use |
|---|---:|---|
| `canvas` | `#1E1E1E` | Main workflow viewport and log |
| `chrome` | `#252526` | Step rail, engine bar, footer, activity header |
| `surface-1` | `#2D2D30` | Cards and secondary buttons |
| `surface-2` | `#353539` | Inputs, nested panels, popup lists |
| `surface-hover` | `#3E3E42` | Neutral hover state |
| `border` | `#45454A` | Default boundary |
| `border-strong` | `#5A5A60` | Focus-adjacent or emphasized boundary |
| `text-primary` | `#F2F2F2` | Titles and primary values |
| `text-secondary` | `#C8C8C8` | Body copy and labels |
| `text-muted` | `#A6A6A6` | Hints and metadata |
| `text-disabled` | `#77777A` | Disabled content only |
| `accent` | `#0E639C` | Primary button fill and selected control |
| `accent-hover` | `#1177BB` | Primary hover |
| `accent-text` | `#75BEFF` | Links and low-area accent text |
| `focus` | `#75BEFF` | Keyboard focus outline |
| `success` | `#73C991` | Success icon/text |
| `warning` | `#F2C94C` | Warning icon/text |
| `danger` | `#F48771` | Error icon/text and destructive outline |
| `danger-fill` | `#A1260D` | Confirmed destructive primary action |
| `selection` | `#264F78` | List/editor text selection |

Against `canvas`, the proposed primary, secondary, muted, accent, success,
warning, and danger text colors all exceed a 4.5:1 contrast ratio. White text on
the proposed primary and danger button fills also exceeds 4.5:1. Disabled text
is intentionally lower contrast but must never carry required information.

### Color usage rules

- Use near-white for page and task headings. Do not color every heading teal.
- Reserve blue for selection, focus, links, and the primary action.
- Reserve green for a completed or successful state, never for a routine action
  merely because it is safe.
- Reserve amber for caution or review-required states.
- Reserve red for errors and destructive actions.
- Avoid pure black backgrounds and large areas of pure white text.
- Prefer surface elevation and borders over differently colored cards.
- Selected navigation should use a surface change plus an accent rail, not a
  large saturated fill.
- Hover, pressed, focused, checked, disabled, and selected states must all be
  visually distinct.
- Icons inherit the semantic foreground color and must remain legible at 16 px.
- Paths and code-like values use a monospace font but keep the standard text
  colors.

### Qt-specific dark-mode requirements

- Extract the global application stylesheet from `main()` into a reusable
  function so production and capture mode apply exactly the same base theme.
- Set a matching `QPalette` for `Window`, `WindowText`, `Base`,
  `AlternateBase`, `Text`, `Button`, `ButtonText`, `Highlight`,
  `HighlightedText`, `ToolTipBase`, `ToolTipText`, and placeholder text where
  supported.
- Explicitly style `QAbstractItemView` popups used by combo boxes. Platform
  defaults must not produce white menus with white or muted text.
- Explicitly style scroll-area viewport widgets. A transparent scroll area must
  not reveal the platform's light default background.
- Check `QMessageBox`, help dialogs, tooltips, context menus, disabled inputs,
  selection colors, scrollbar tracks, and spin-box buttons independently.
- Avoid broad `QWidget` selectors inside components when an object-name selector
  can prevent styles leaking into descendants.
- Remove malformed or conflicting QSS while centralizing the theme.
- Render with Qt Fusion for deterministic reference images, then manually check
  native behavior on Windows and Linux.

## Layout and typography tokens

### Spacing

Use a 4 px base grid:

| Token | Value | Typical use |
|---|---:|---|
| `space-1` | 4 px | Icon/text or tightly related metadata |
| `space-2` | 8 px | Controls within a row |
| `space-3` | 12 px | Related content within a card |
| `space-4` | 16 px | Card padding and ordinary sections |
| `space-6` | 24 px | Page padding and major groups |
| `space-8` | 32 px | Rare, high-level separation |

Two- and three-pixel values are allowed only for one-pixel border compensation
or icon optical alignment, with a comment explaining the exception.

### Geometry

- Compact control height: 32 px at 1.0 font scale.
- Standard control height: 36 px at 1.0 font scale.
- Prominent navigation/action height: 40 px at 1.0 font scale.
- Card corner radius: 6 px.
- Input/button corner radius: 4 px.
- Standard icon size: 16 px; page/status icon size: 20 px.
- Interactive targets must be at least 32 by 32 px.
- Use minimum heights derived from font metrics rather than fixed maximum
  heights when text can scale.
- Do not use fixed widths for ordinary text buttons. Use content size plus
  standard horizontal padding and only set a minimum where alignment requires
  it.

### Typography

Define semantic font roles rather than styling individual labels:

| Role | Initial size at 1.0 | Weight |
|---|---:|---:|
| Page title | 18 px | 600 |
| Task title | 14 px | 600 |
| Body/control | 13 px | 400 |
| Label | 12 px | 600 |
| Metadata/help | 12 px | 400 |
| Log/code | 12 px | 400 monospace |

The application's font-scale setting remains authoritative. Layouts must grow
from font metrics rather than scaling text inside fixed-height containers.

## Reusable workflow components

Create a small component layer instead of constructing styled fragments on each
page. Exact class names can change during implementation, but responsibilities
must remain clear.

| Component | Responsibility |
|---|---|
| `WorkflowShell` | Step rail, page stack, activity panel, responsive behavior |
| `WorkflowStepRail` | Step selection and current/complete/warning states |
| `WorkflowPage` | Scroll viewport, header, content column, footer |
| `WorkflowPageHeader` | Eyebrow, title, purpose, Help, optional badge |
| `TaskCard` | Title, description, content area, action/status row |
| `FieldRow` | Consistent label, control, suffix, help, validation placement |
| `ActionRow` | Primary, secondary, destructive, and trailing status alignment |
| `StatusBanner` | Info, success, warning, and error presentation |
| `DisclosureSection` | Optional or advanced content without losing state |
| `ActivityPanel` | Summary, progress, detailed log, clear/collapse actions |
| `WorkflowButton` factory | Primary, secondary, quiet, and destructive variants |

All reusable widgets receive stable `objectName` values so screenshots,
geometry reports, QSS selectors, and tests can identify them.

Do not turn every row into a subclass. Introduce a component only when it owns a
repeated visual or behavioral contract.

## Step-by-step page blueprint

### Step 0: Project

- Card 1: game folder field, Browse action, and detected engine/status.
- Card 2: detected files with filter/selection summary and a properly labeled
  toolbar (`All`, `None`, `Core database`, `Import selected`).
- Keep the list as the primary flexible-height element.
- Present empty, scanning, detected, unsupported, and error states explicitly.
- Make automatic import-on-leave behavior visible in supporting copy.

### Step 1: Prepare

- Mark the page itself Optional rather than repeating that fact throughout.
- Present Format JSON, Format plugins, and Copy GameUpdate as separate task
  cards with consistent descriptions and action placement.
- Put path overrides inside each card's Advanced disclosure when auto-detection
  supplied a path.
- Keep `Run all preparation tasks` as a page-level convenience action, visually
  distinct from the individual actions.

### Step 2: Setup

- Card 1: source import/reset and speaker parsing.
- Card 2: speaker-detection flags, with human labels and technical config names
  as secondary text or tooltips.
- Card 3: Project Setup handoff and copy action.
- Card 4: Vocab, Quirks, and Game Skills editor tabs.
- Give editor Save/Reload actions a stable footer within the editor card.
- Do not let the editor consume navigation or hide its unsaved state.

### Step 3: Translation Phase 1

- Card 1: translation mode with its cost/timing explanation represented as an
  info or warning message, not loose colored lines.
- Card 2: wrapping preflight using aligned field rows.
- Cards 3-5: Phase 0, Phase 1, and Phase 1b, each with purpose, prerequisites,
  action, and result status in the same positions.
- Emphasize the next eligible phase rather than showing all run buttons as equal.

### Step 4: Translation Phase 2

- Card 1: audit/prompt prerequisite and code-122 range.
- Card 2: enabled risky-code families.
- Advanced disclosure: plugin handlers and script patterns.
- Preserve select-all controls, but label them and place them beside the list
  they affect.
- Provide selection counts and a visible caution state before Run Phase 2.
- Keep the run action reachable without requiring the user to scroll through
  both long lists after selections are made.

### Step 5: Export

- Avoid leaving a small card floating in a mostly empty page.
- Card 1: optional plugin/Ruby-script preparation with engine-specific copy.
- Card 2: export choice with clear explanations of Active Files versus All
  Translated.
- Show destination and readiness before enabling export.
- Give successful export a persistent summary and a direct path to Rewrap.

### Step 6: Rewrap

- Card 1: categories and widths, organized as aligned rows.
- Advanced disclosure: event codes and row protection.
- Card 2: file scope, filter, presets, selection count, and file list.
- Sticky task action row: Scan, Rewrap, and current result status.
- Card 3: scan results and QA/release actions, appearing when relevant.
- Ensure the page scrolls as one understandable document rather than exposing
  nested areas with ambiguous scroll ownership.

### Step 7: Images

- Card 1: readiness checklist with status per prerequisite.
- Card 2: the four-stage image flow represented compactly.
- Primary action: Open Images. Secondary action: Copy vocab.
- Use the available vertical space intentionally without stretching short copy
  into a large empty panel.

### Step 8: Playtest

- Card 1: shared playtest settings.
- Card 2: TL Inspector status and install/uninstall actions.
- Card 3: Forge status and install/uninstall actions.
- `Install both` is a convenience action after both individual states are clear.
- Credits remain readable metadata rather than disabled-looking text.
- Preserve Ace visibility rules.

## Visual analysis and iteration tooling

### Capture command

Add `scripts/capture_workflow_ui.py` with a command similar to:

```bash
venv/bin/python scripts/capture_workflow_ui.py \
  --output .tmp-ui/rpgmaker-workflow \
  --sizes 1440x900,1280x720 \
  --font-scales 1.0,1.5
```

The command must:

1. create a deterministic Qt Fusion application;
2. apply the exact production dark palette and application QSS;
3. host the workflow inside the real engine-selector container;
4. use sanitized fixture data and an isolated temporary `QSettings` store;
5. disable timers, background update checks, file operations, and workers;
6. render every step after layouts and deferred events settle;
7. save individual PNGs and a labeled contact sheet;
8. save a geometry JSON report; and
9. optionally compare the render against an approved baseline.

Capture output should include at least:

```text
.tmp-ui/rpgmaker-workflow/
    current/
        1440x900-1.0/step-00-project.png
        ...
        1280x720-1.5/step-08-playtest.png
        contact-sheet.png
        geometry.json
    diff/
        contact-sheet.png
        summary.json
```

The normal output directory remains ignored. Approved sanitized reference
images may be stored under `tests/ui_baselines/rpgmaker_workflow/fusion/` after
review.

### Fixture states

The capture tool needs deterministic fixture profiles:

- `empty`: no project detected;
- `ready-mz`: populated MZ project, files, editor content, plugin handlers, and
  valid image/playtest readiness;
- `ready-ace`: Ace-specific labels and hidden unsupported steps;
- `busy`: active task and progress;
- `warning`: risky-code and readiness warnings;
- `error`: representative validation/action failure;
- `complete`: completed-step rail, successful export, and activity entries; and
- `disabled`: unavailable actions and dependent controls.

Use invented neutral paths such as `/fixtures/SampleGame`; never copy the
developer's current `QSettings` or repository translation content.

### Geometry report

For every visible named widget, record:

- class and object name;
- parent component;
- x, y, width, and height;
- minimum, maximum, and size-hint dimensions;
- font family, pixel/point size, weight, and metrics;
- enabled, visible, checked, and focus state;
- layout type, contents margins, spacing, alignment, and stretch; and
- semantic token names where the component exposes them.

The report should flag:

- margins or spacing outside the approved token set;
- text bounding boxes larger than their controls;
- overlapping sibling rectangles;
- interactive controls below the minimum target size;
- widgets extending outside their scroll content or viewport;
- unexpected horizontal scrollbars; and
- low-information fixed blank areas caused by unnecessary stretch or sizing.

### Inspection overlay

Support a development-only overlay through the capture command and an optional
runtime environment flag such as `DAZEDTL_UI_DEBUG=1`.

Overlay modes:

- 4 px and 8 px grid;
- component and child-widget bounds;
- text baselines;
- layout margin and spacing labels;
- current hover widget name and geometry; and
- token violations highlighted in amber.

The overlay must not ship enabled, affect layout geometry, intercept normal
mouse input, or appear in ordinary screenshots.

### Image comparison

- Use Pillow, which is already a project dependency, for contact sheets and
  image differences.
- Keep capture environment, fixture content, font, style, and dimensions fixed.
- Report changed-pixel percentage and difference bounding boxes.
- Produce visual diff images rather than only a pass/fail value.
- Do not enforce identical screenshots across operating systems. Reference
  comparisons are for the controlled Fusion environment.
- CI should enforce structural geometry rules; perceptual screenshot approval
  remains a deliberate review step to avoid font-rendering noise.

## Responsive, scaling, and accessibility matrix

### Automated capture matrix

| Size / scale | Purpose |
|---|---|
| 1440x900 at 1.0 | Primary design reference |
| 1280x720 at 1.0 | Common constrained layout |
| 1000x600 at 1.0 | Application minimum-size smoke test |
| 1440x900 at 1.5 | Large text and DPI behavior |
| 1280x720 at 2.0 | Stress test for scrolling and clipping |

Run non-image geometry smoke tests at the configured extremes of 0.5 and 3.0.
At extreme scales, the requirement is operability and reachability rather than
matching the primary composition.

### Manual platform matrix

- Windows at 100%, 125%, and 150% display scaling.
- Linux at 100% and 150% scaling using the normal launcher configuration.
- At least one narrow restored window and one maximized window per platform.
- Keyboard-only traversal through the step rail, fields, disclosures, action
  rows, footer, and activity panel.

### Accessibility checks

- Normal text contrast at least 4.5:1; large text and essential non-text
  boundaries at least 3:1.
- Visible focus ring on every interactive element.
- Logical Tab order following top-to-bottom reading order.
- No status conveyed through color alone.
- Tooltips supplement labels; they do not replace essential labels.
- Disabled actions have nearby text explaining prerequisites when the reason is
  not obvious.
- Icons used alone have accessible tooltips and stable meanings.
- Long labels and translated/system font differences do not overlap controls.

## Implementation phases

Each phase ends with a reviewable artifact and test gate. Do not begin a broad
page migration until the representative pages and shell are approved.

### Phase 0: Behavior inventory and baseline

Tasks:

1. Inventory every visible control, signal connection, worker start, setting,
   status update, and page-transition side effect in `WorkflowTab`.
2. Add targeted behavioral tests for actions that currently lack coverage,
   especially navigation, automatic import-on-leave, collapsed advanced state,
   Ace step visibility, and activity logging.
3. Extract the production application dark stylesheet into a callable without
   changing its rendered output.
4. Implement safe fixture mode and the initial screenshot/geometry capture.
5. Capture all current steps at the primary and constrained sizes.

Exit gate:

- Existing tests pass.
- The capture tool cannot mutate repository or game data.
- Baseline contact sheets and geometry reports are available for review.
- Every workflow action has a recorded preservation requirement.

### Phase 1: Tokens, palette, and primitives

Tasks:

1. Add centralized color, spacing, geometry, and typography tokens in a small
   theme module, likely `gui/theme.py`.
2. Set the application `QPalette` and repair conflicting/malformed global QSS.
3. Add the reusable workflow components, likely in
   `gui/workflow_components.py`.
4. Implement all interaction states for buttons, fields, checkboxes, lists,
   cards, statuses, tooltips, and popups.
5. Add contrast tests for the declared palette pairs.
6. Add component gallery captures for default, hover where feasible, focus,
   pressed, checked, disabled, success, warning, and danger states.

Exit gate:

- No component depends on the operating system's light palette.
- Token contrast checks pass.
- Components render consistently in isolation and inside the main window.

### Phase 2: Workflow shell

Tasks:

1. Implement the vertical step rail while retaining the existing page stack.
2. Implement the standard page header and navigation footer.
3. Implement the collapsible Activity panel and migrate existing log/progress
   widgets into it.
4. Add responsive rail and activity-panel behavior.
5. Persist only user-facing preferences; do not persist fixture/debug state.
6. Preserve direct navigation, completion marking, auto-import transition, and
   Ace visibility behavior.

Exit gate:

- All nine existing pages function inside the new shell before their contents
  are redesigned.
- Navigation and activity behavior tests pass.
- No clipping occurs at the primary and minimum reference sizes.

### Phase 3: Representative page redesign

Redesign these pages first:

1. Step 0, representing folder selection and a large checklist.
2. Step 3, representing normal sequential task cards and statuses.
3. Step 4, representing dense advanced configuration and long lists.

For each page:

1. Convert content to shared components.
2. Preserve and test every action.
3. Capture all relevant fixture states.
4. Review spacing overlay and geometry violations.
5. Compare primary, constrained, and large-font contact sheets.
6. Tune tokens or components rather than applying local one-off fixes.

Exit gate:

- The three pages establish approved patterns for simple, list-heavy, and
  advanced layouts.
- No unexplained off-token spacing or page-specific color remains.
- User approval is obtained before propagating the patterns.

### Phase 4: Remaining page migration

Migrate Steps 1, 2, 5, 6, 7, and 8 using the approved patterns. Work one page at
a time and capture after each page so regressions remain attributable.

Exit gate for each page:

- Existing behavior tests pass.
- Empty, ready, disabled, and relevant warning/error states are present.
- Screenshot and geometry review pass at 1440x900 and 1280x720.
- The page uses shared tokens/components or documents a justified exception.

### Phase 5: Dark-mode and state hardening

Tasks:

1. Audit every popup, help dialog, tooltip, menu, editor, list viewport,
   scrollbar, selected row, disabled control, and focus state.
2. Exercise busy, success, warning, error, and partial-completion fixture states.
3. Verify semantic colors are not being used decoratively.
4. Verify no state depends on color alone.
5. Run the manual Windows/Linux matrix.
6. Fix platform-specific palette leaks using semantic palette roles, not local
   hard-coded patches.

Exit gate:

- No light rectangles, illegible popup items, invisible disabled text, or
  unstyled native-looking descendants appear in the supported matrix.
- Contrast and keyboard checks pass.

### Phase 6: Scaling and density hardening

Tasks:

1. Run the full automated scaling matrix.
2. Replace remaining fixed sizes that clip scaled text.
3. Validate scroll ownership and action reachability.
4. Check long paths, long status messages, and representative localization/font
   expansion.
5. Validate compact rail and collapsed activity behavior.

Exit gate:

- No overlap, truncation of essential text, or unreachable action at supported
  scales.
- Horizontal scrolling appears only in content where it is intentional.

### Phase 7: Cleanup, documentation, and final regression

Tasks:

1. Remove superseded inline styles, factories, and dead shell code only after
   all pages have migrated.
2. Search for raw workflow color and spacing literals and either replace or
   document them.
3. Update RPG Maker workflow help and screenshots where applicable.
4. Run the full repository test suite.
5. Run all visual captures and produce the final before/after contact sheet.
6. Perform an end-to-end MV/MZ workflow smoke test and an Ace smoke test using
   disposable fixtures.
7. Record any intentionally deferred issues rather than silently accepting
   them.

Exit gate:

- All completion criteria below pass.
- The final visual baseline is reviewed and approved.

## Expected file changes

Likely additions and modifications:

- `gui/main.py`: reusable application theme application and palette setup.
- `gui/theme.py`: semantic palette and layout/typography tokens.
- `gui/workflow_components.py`: shared workflow visual components.
- `gui/workflow_tab.py`: new shell and migrated RPG Maker pages.
- `scripts/capture_workflow_ui.py`: deterministic captures, reports, overlays,
  and diffs.
- `tests/test_workflow_ui.py`: geometry, state, navigation, and palette tests.
- `tests/ui_baselines/rpgmaker_workflow/fusion/`: approved sanitized reference
  renders if baseline images are committed.
- `data/help/03-workflow-rpg.md`: layout-aligned help updates.

Keep the theme API reusable, but avoid changing unrelated pages merely to make
them use the new tokens during this project.

## Review protocol for every iteration

1. Run behavioral tests.
2. Render the full contact sheet at 1440x900, 1.0 scale.
3. Compare against the last approved baseline.
4. Inspect the changed pages with the 8 px grid and widget bounds.
5. Read the geometry violation report.
6. Render 1280x720 and 1.5 scale.
7. Review dark states: normal, hover/focus, disabled, warning, error, selected,
   popup, and scrollbar.
8. Record the decision: approve, revise a shared token/component, or document a
   justified page-specific exception.
9. Update the approved baseline only after review.

Do not approve a page from a cropped screenshot alone. Always check it in the
full shell with the engine bar, step rail, footer, and activity panel visible.

## Completion criteria

The overhaul is complete only when all of the following are true:

### Visual consistency

- All nine pages use the standard shell, page header, footer, task cards, field
  rows, action hierarchy, and status patterns.
- All ordinary margins and spacing use the documented tokens.
- Page-specific raw colors have been removed except for documented data-driven
  cases.
- Primary, secondary, quiet, and destructive actions are recognizable without
  reading every label.
- Empty and dense pages feel like parts of the same application.

### Dark mode

- Every workflow surface is explicitly dark in both the integrated application
  and isolated capture environment.
- Popup lists, help dialogs, tooltips, menus, editors, scrollbars, and disabled
  states are legible.
- Required palette contrast tests pass.
- Status colors have non-color reinforcement.

### Responsiveness and accessibility

- The workflow is usable at 1000x600 and visually approved at 1280x720 and
  1440x900.
- Font scales through the configured range remain operable, with no clipped or
  unreachable actions.
- Keyboard focus and traversal are visible and logical.
- No unintended horizontal scrollbar or sibling overlap is reported.

### Functional preservation

- Existing repository tests pass.
- New navigation and GUI-state tests pass.
- All inventoried actions still invoke the same underlying behavior.
- MV/MZ and Ace smoke tests complete using disposable sample projects.
- Opening, capturing, or navigating the workflow does not introduce new data
  mutation.

### Iteration capability

- One command renders all steps, states, sizes, and geometry reports safely.
- The debug overlay exposes grid, bounds, margins, spacing, and widget identity.
- Approved reference captures contain no user paths, keys, or real project
  content.
- Before/after contact sheets and a final diff summary are available for review.

## Final deliverables

1. Central dark palette and workflow design tokens.
2. Reusable workflow component library.
3. Redesigned RPG Maker workflow shell and all nine pages.
4. Collapsible responsive Activity panel.
5. Deterministic capture, contact-sheet, geometry, overlay, and image-diff tool.
6. Sanitized visual baselines and structural GUI tests.
7. Updated RPG Maker help documentation.
8. Final before/after visual review and MV/MZ plus Ace regression report.
