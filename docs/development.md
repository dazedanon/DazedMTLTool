# Development and repository maintenance

Install runtime and development dependencies into the project virtual
environment:

```bash
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Run the correctness lint locally with `ruff check .`. The same command runs in
CI and through the optional pre-commit hook. Ruff's configuration lives in
`pyproject.toml`; the initial baseline covers parse errors, invalid syntax, and
undefined names. Formatting, unused imports, and broader style families are
intentionally not enforced yet.

Use the smallest relevant test while iterating, then run the repository suites:

```bash
./tests/run_tests.sh core
./tests/run_tests.sh extended  # Qt/workflow/navigation changes
./tests/run_tests.sh full      # releases or shared test infrastructure
```

## Runtime retention

The application keeps the newest ten `log/history/translationHistory_*.txt`
files during normal CLI and GUI translation. Completed model evaluations use
their own bounded history; submitted and resumable evaluation work is retained.

The maintenance script adds a conservative second layer for interrupted runs:

```bash
python scripts/clean_workspace.py --runtime
```

That dry run lists translation histories beyond the newest ten and `.tmp` files
under `log/` older than 24 hours. Use `--keep-history` or `--stale-tmp-hours` to
change those thresholds. Add `--apply` only after reviewing every path. The
runtime category never targets translation caches, `translations.txt`, batch
state, evaluation archives, `files/`, or `translated/`.

## Documentation ownership

- `README.md`: installation, quick start, feature map, and links.
- `data/help/`: canonical end-user workflows shown inside the application.
- `docs/`: maintainer contracts, architecture, audits, and implementation plans.
- `gameupdate/README.md`: the standalone GameUpdate component.

The Guide screenshots under `data/help/images/` are sanitized captures of real
widgets. Regenerate the complete annotated set after relevant Configuration or
RPG Maker workflow changes:

```bash
./.venv/bin/python scripts/build_tutorial_screenshots.py
```

Review every generated image before committing it. The builder uses temporary
settings and fixture paths, never a real API key or game project.

Keep upstream asset revisions, hashes, and license status current in
`docs/third-party-assets.md` whenever a bundled executable, plugin, or font is
refreshed.
