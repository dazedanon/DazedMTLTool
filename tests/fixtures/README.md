# Map `_original` fixture

## Files

- **`Map_original_fixture.json`** — Minimal RPG Maker MV map (17×13) with one event exercising every `_original` code path: 401, 405, 102, 101, and 122.
- **`Map_original_fixture_manifest.json`** — Expected `_original` values after translation (used by tests).

## Event layout (event id 1, page 0)

| Order | Code | Purpose |
|------:|------|---------|
| 1–2 | 401 | Color speaker line `\C[2]テスト子\C[0]` + following dialogue |
| 3–4 | 401 | Merged multi-line dialogue (two 401s → one batch) |
| 5–6 | 101, 405 | Empty face setup + scrolling text line |
| 7 | 102 | Three choices (middle choice has `if(...)` prefix) |
| 8–9 | 108, 408 | Choice-help marker (`選択肢ヘルプ`) + help comment line |
| 10–11 | 101, 401 | Name box with `\C[2]アリス\C[0]` + dialogue |
| 10–11 | 122 | Variable string `` `変数の中身` `` and `` `セミコロン`; `` |

## Run the test

Using the project venv (recommended):

```bash
./tests/run_tests.sh
```

Or explicitly:

```bash
./tests/run_tests.sh tests.test_mvmz_source_original -v
./tests/run_tests.sh tests.test_mvmz_source_original.TestFixtureMapOriginal -v
```

Manual equivalent (must run from project root, with venv activated):

```bash
cd /path/to/DazedMTLTool
source .venv/bin/activate   # or: source venv/bin/activate
python -m unittest tests.test_mvmz_source_original -v
```

Do **not** use `pytest` unless you install it yourself — this project uses the stdlib `unittest` runner.

If you see `ModuleNotFoundError: No module named 'colorama'` (or similar), activate the venv or use `./tests/run_tests.sh` instead of system `python3`.

Tests mock `translateAI` / `getSpeaker` — no API key required. Enable `CODE122` for the duration of the run.

## Manual check

Copy the fixture into `files/` and run the tool with batch/consume or live translate, then diff against the manifest’s `expected_original` fields in `translated/Map_original_fixture.json`.
