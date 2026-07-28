# RPG Maker Workflow Behavior Inventory

This inventory is the behavior-preservation contract for the GUI overhaul. A
layout or styling change must not change these effects, confirmations, worker
boundaries, or destinations.

## Shell

| Control/event | Existing behavior to preserve |
|---|---|
| Direct step selection | Changes the hidden page stack to the selected visible step. |
| Continue | Marks the current step complete and moves to the next visible step. |
| Back | Moves to the previous visible step without marking it complete. |
| Leaving Project | Auto-imports the checked selection only when it differs from the last completed or pending import. |
| Ace detection | Hides unsupported Images and Playtest steps and redirects away from them if necessary. |
| Help | Opens the existing rich-text help for the current step. |
| Activity | Displays the existing workflow log; clearing it does not alter task state. |

## Step 0: Project

| Action | Effect |
|---|---|
| Browse / Enter | Saves the selected folder and detects MV, MZ, or Ace. May start a read-only scan worker. |
| Encrypted Ace detection | Offers the existing explicit decrypter action; it does not decrypt merely by detecting. |
| Select all / Clear selection / Database only | Changes only checklist state and writes a log entry. |
| Import selected files | Confirms replacement when required, clears `files/` except `.gitkeep`, and copies exactly the checked files through `_ImportWorker`. |
| Multi-row checkbox change | Applies the changed checked state to the current Ctrl/Shift row selection. |

## Step 1: Prepare

| Action | Effect |
|---|---|
| Format game data | Runs the existing `dazedformat` worker against the detected game data. |
| Format plugins.js | Runs `jsbeautifier` against the explicitly shown plugin file. |
| Install GameUpdate | Copies the bundled folder using RPG Maker exclusions and writes patch configuration when applicable. |
| Run available tasks | Runs the eligible existing tasks sequentially and logs skipped prerequisites. |
| Collapse | Changes visibility only; paths and task state remain unchanged. |

## Step 2: Setup

| Action | Effect |
|---|---|
| Import selected files | Invokes the same Step 0 import path. |
| Clear translated | Confirms and deletes contents of `translated/` while preserving `.gitkeep`. |
| Collect names | Applies speaker flags, selects event files, and starts the existing Parse Speakers translation mode. |
| Copy setup skill | Copies the existing project-setup skill with game context. |
| Speaker flags | Persist and apply through the existing config integration. |
| Glossary Save / Reload | Reads or writes the game Glossary through shared Glossary utilities. |
| Quirks/Game Skills Save / Reload | Reads or writes the selected game's skill files. |

## Step 3: Translation Phase 1

| Action | Effect |
|---|---|
| Translation mode | Selects Normal or Batch for all workflow phase launch actions. |
| Save line widths | Writes the four measured width values to `.env`. |
| Code 408 checkbox | Persists the user decision and adds code 408 only to the Phase 1 profile when enabled. |
| Translate database | Applies the Phase 0 database profile, selects database files, and starts translation. |
| Translate dialogue | Applies the Phase 1 dialogue/choice profile, selects event files, and starts translation. |
| Build variable cache | Applies the Phase 1b code-111 profile, selects event files, and starts cache-building translation. |

## Step 4: Translation Phase 2

| Action | Effect |
|---|---|
| Copy advanced-text audit | Copies the existing risky-code audit skill without changing configuration. |
| Save range | Writes `CODE122_VAR_MIN/MAX` through config integration. |
| Code/plugin/pattern checks | Preserve current auto-apply behavior and exact config keys. |
| Advanced disclosure | Changes visibility only; checked state is retained. |
| Translate selected text | Applies the selected Phase 2 configuration, selects event files, and starts translation. |

## Step 5: Export

| Action | Effect |
|---|---|
| Copy glossary to game | Copies the current Glossary to the selected game root. |
| Copy plugin/Ruby translation skill | Copies the engine-specific audit-and-edit prompt. |
| Export selected files | Confirms, then exports translated JSON matching names currently in `files/`. |
| Export all translated files | Confirms, then exports every translated result. |
| Ace export | Preserves the existing RV2JSON update/packing path. |

## Step 6: Rewrap

| Action | Effect |
|---|---|
| Load saved line widths | Loads current `.env` width defaults without editing game data. |
| Scope/filter/presets | Change only the in-memory file selection. |
| Preview rewrap | Runs deterministic rewrap analysis with `apply=False`. |
| Apply rewrap | Runs the same options with `apply=True` against the resolved game data folder. `_original` remains protected. |
| Copy final QA skill | Copies the existing RPG Maker QA skill. |
| Build public release ZIP | Confirms destination and runs the existing sanitized release worker. |

## Step 7: Images

| Action | Effect |
|---|---|
| Refresh readiness | Reads image readiness, encryption-key availability, Glossary, and workspace placement. |
| Copy glossary to game | Uses the same Glossary copy action as Export. |
| Open Image Manager | Saves the current game folder and switches the host window to the shared Images page. |

## Step 8: Playtest

| Action | Effect |
|---|---|
| Save defaults | Writes the selected hotkeys, scale, and editor settings through existing configuration logic. |
| Apply settings to game | Updates already installed playtest plugins with the selected settings. |
| Find editors / Choose… | Changes editor configuration only. |
| Install/Remove TL Inspector | Uses the existing installer and confirmation behavior. |
| Install/Remove Forge | Uses the existing engine-specific Forge installer and confirmation behavior. |
| Install both plugins | Invokes the existing combined installation sequence. |

## Worker and mutation invariants

- Worker references remain owned until completion so Qt threads are not
  destroyed while running.
- Concurrent export and rewrap remain blocked as before.
- Destructive actions retain their confirmations and default-safe response.
- Visual capture mode never calls any action in this inventory.
- Status and Activity presentation may change; action ordering and underlying
  service calls may not.

## Automated action harness

Run the behavior-preservation harness independently with:

```bash
venv/bin/python scripts/run_workflow_action_harness.py
```

The harness has two layers:

1. A virtual action probe clicks 49 production controls across all nine steps
   and verifies their Qt signals still reach the inventoried endpoints. It also
   covers Enter-to-detect, speaker checkboxes, editor Save/Reload actions,
   disclosures, help, and navigation.
2. Real handlers run inside an isolated working directory using disposable
   MV, MZ, and Ace project fixtures. External worker threads, subprocesses,
   dialogs, installers, and host-page changes are substituted with recording
   boundaries so the suite cannot touch a real game or translation workspace.

The handler contracts cover exact import/export scopes, safe confirmation
defaults, worker ownership, preparation routing, speaker and phase
configuration, Parse Speakers navigation, Phase 2 auto-save keys, rewrap
scan/apply parity, release ZIP launch, and playtest installer routing.
