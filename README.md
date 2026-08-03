# DazedTL

DazedTL is a desktop game-translation toolkit for translating Japanese games
with OpenAI, Gemini, Mistral, Anthropic, and compatible AI providers. Its guided
workflows cover importing game data, building translation context, translating
and reviewing text, patching images, playtesting, and carrying translations
forward when a game is updated.

## Supported engines and formats

- RPG Maker MV, MZ, and VX Ace
- WOLF RPG Editor, including the guided WolfDawn workflow
- SRPG Studio
- Ren'Py, TyranoScript, Kirikiri, NScripter, and Unity
- CSV, JSON, text, subtitle, regex-driven, and prepared Aquedi4 data

Support depth varies by engine. RPG Maker MV/MZ and WOLF have the most complete
guided workflows; the Translation page provides adapters for the other formats.

## Requirements

- Python 3.12, 3.13, or 3.14
- An API key for at least one supported translation provider
- Windows, Linux, or macOS

Download Python from [python.org](https://www.python.org/downloads/). On Windows,
enable **Add python.exe to PATH** during installation. Verify the installation in
a new terminal with:

```text
python -V
```

## Quick start

1. Download or clone the repository into its own folder.
2. Launch DazedTL:
   - Windows: double-click `START.bat`.
   - Linux or macOS: run `./START.sh`.
   - Linux desktop: double-click `DazedTL.desktop` and allow launching when
     prompted.
3. Open **Configuration** and add a provider, API key, and model.
4. Open **Guide**, then choose the RPG Maker or WOLF workflow for a guided
   project, or use **Translation** for another supported format.

The launchers create a virtual environment and install missing dependencies.
Advanced users may configure the same settings in a private `.env` copied from
`.env.example`.

## Feature map

| Area | Purpose |
|---|---|
| **Guide** | Built-in setup, workflow, recovery, and playtesting documentation |
| **Workflow** | Guided RPG Maker and WOLF project translation |
| **Images** | Extract, edit, review, and safely patch translatable images |
| **Translation** | Direct translation with engine-specific adapters |
| **Batches** | Submit and resume supported provider batch jobs |
| **Evaluation** | Compare models on the same deterministic translation sample |
| **Version Update** | Carry an existing translation into a newer official game build |
| **Skills** | Manage shared and per-game translation instructions |
| **Configuration** | Provider, model, engine, wrapping, and workflow defaults |

The Version Update feature uses two Git branches for every engine and file
format. `original` records official releases and `translation` receives
each release commit by cherry-pick. If those branches do not exist, the GUI can
create them from a translated game and its matching clean original. Conflicting
files default to the new official copy and are listed for translation review.
Before approval, the GUI shows a file-change overview and normalizes valid
UTF-8 `.json` files with the same four-space formatter used by translation
workflows. JSON that cannot be safely formatted remains unchanged and is shown
as a warning. Bootstrap normalizes both branch baselines so initialization does
not create formatting-only diffs. Existing `.gitignore`, repository exclude,
and global Git ignore rules are honored for every imported tree. No
engine-aware or semantic merge is performed.

## Guides and help

The in-app **Guide** is the canonical user documentation. Its source is kept in
[`data/help/`](data/help/):

- [Start here](data/help/00-welcome.md)
- [Set up Git safely](data/help/01-git-setup.md)
- [Set up an AI helper](data/help/02-ai-helper.md)
- [RPG Maker workflow](data/help/03-workflow-rpg.md)
- [WOLF workflow](data/help/04-workflow-wolf.md)
- [Other pages and features](data/help/05-other-tabs.md)
- [Complete first-translation example](data/help/06-examples.md)
- [Problems and resuming work](data/help/08-problems-resuming.md)
- [Backups and recovery](data/help/09-backups-recovery.md)
- [Playtesting checklist](data/help/10-playtest-checklist.md)

## Translation context

Each selected game receives its own `<game>/glossary.txt`. Use it for character
names, recurring terms, and other choices that should remain consistent. Game
skills live beside the game under `<game>/skills/`:

- `game.md` describes the game's setting, register, and naming frame.
- `quirks.md` records cross-cutting voice and formatting habits.
- Additional Markdown files may provide project-specific instructions.

DazedTL also ships a local definitions-only Japanese sound-effect reference.
Only entries matched in the current source are added to a translation request;
the feature does not contact an online dictionary.

## Repository layout

| Path | Purpose |
|---|---|
| `assets/` | Application artwork |
| `data/` | Shipped help, skills, glossary seed, and reference data |
| `docs/` | Maintainer contracts, plans, roadmap, and audits |
| `files/` | Imported source files for direct translation |
| `gameupdate/` | Standalone player patch/update component |
| `gui/` | Application UI and workflow code |
| `log/` | Translation logs, caches, history, and resumable run state |
| `modules/` | Engine and format translation adapters |
| `scripts/` | Launch, maintenance, capture, and test utilities |
| `tests/` | Core and extended regression suites |
| `translated/` | Direct-translation output |
| `util/` | Shared services and engine tooling |

Runtime contents under `files/`, `translated/`, and `log/` are intentionally
ignored by Git. They may contain active project data and are not disposable
repository clutter.

## Development and maintenance

Start with [development and repository maintenance](docs/development.md).
Current product work is recorded in the [roadmap](docs/roadmap.md), while the
[repository audit](docs/repository-audit.md) records branch, stash, and Git
object retention decisions.

Run the default checks with:

```bash
ruff check .
./tests/run_tests.sh core
```

Qt, workflow, or navigation changes also require:

```bash
./tests/run_tests.sh extended
```

Review regenerable workspace artifacts without deleting them:

```bash
python scripts/clean_workspace.py --all --keep-captures 5 --keep-history 10
```

Add `--apply` only after inspecting every listed target. The cleaner does not
target imported source, translated output, translation caches, evaluation
archives, virtual environments, Git branches, or stashes.

## Troubleshooting

- **A launcher closes immediately:** Confirm `python -V` reports Python
  3.12–3.14 and that Python is available on `PATH`.
- **Dependencies are missing:** Delete the project's `.venv` directory and run
  the platform launcher again. It will rebuild the environment.
- **An API request fails:** Recheck the provider, endpoint, key, model, and
  account quota under Configuration.
- **A translation was interrupted:** Use the built-in Batch History or the
  relevant workflow page before moving or deleting any files under `log/`.
- **Detailed provider diagnostics are needed:** Temporarily enable
  `debugRequestLogs=true` in `.env`. These logs contain complete prompt payloads;
  disable the option and remove the logs afterward with
  `python scripts/clean_workspace.py --debug-logs --apply`.

## Credits and bundled assets

- [Sinflower](https://github.com/Sinflower) — RV2JSON and UberWolf tooling
- Sakura and Kao_SSS — TL Inspector
- Len — Forge MV/MZ integration, Mistral support, adaptive rate limiting, and
  batch translation mode

Bundled asset sources, checksums, licenses, and unresolved redistribution status
are recorded in [the third-party asset inventory](docs/third-party-assets.md).
Do not publish a release while that inventory contains a release blocker.

The DazedTL source is available under [GPL-3.0](LICENSE.md).
