# Mistral Translation Runner

This workspace translates extracted WOLF RPG text with the Mistral Chat Completions API.

Use `translate_mistral.py` for live translation. The older PowerShell runner is kept only as a reference.

Default mode translates:

```text
TextExport\strings_japanese.csv
```

That includes dialogue, title/menu/UI text, database strings, item/skill text, battle logs, map signs, and other Japanese strings found by the exporter.

## Files

- `prompt.md` - strict translation prompt and JSON contract.
- `glossary.md` - game-specific names, terms, tone notes, honorifics, UI terms, and adult terminology.
- `translate_mistral.py` - recommended API runner with batching, resume, retries, de-dupe, history, validation, ETA, console progress, and token/cost reporting.
- `build_strict_safe_event_translations.py` - filters translation JSONLs down to WOLF's safest player-facing event text: message commands, choices, and obvious picture-text only. It can recover CommonEvent message translations from older/shifted exports by matching repaired source text back to the original offsets.
- `build_runtime_db_command_keys.py` - builds exact protected rows for fragile WOLF runtime command strings: string-variable values (`122:0`), string-condition keys (`212:0`, `213:0`), DB Operation schema lookups (`250:1`, `250:3`), and common-event call targets (`300:0`).
- `sync_runtime_lookup_terms.py` - post-translation consistency pass for WOLF lookup safety. It keeps `.project` schema/runtime identifiers, fragile string-variable/condition command values, DB Operation type/item keys, and common-event call target names original, while syncing DB data-name lookups to the translated DB data name.
- `build_visible_db_ui_translations.py` - second-stage visible-name/menu/UI builder. It adds translated DB/title/UI rows and syncs only `CID 250` data-name lookup slot `2` to those translated DB data names. Type/field lookup slots stay original.
- `runtime_lookup_locks.jsonl` - game-specific runtime lookup terms that must remain original in map/common-event key contexts.
- `runtime_command_keys.jsonl` - generated exact-offset protections for runtime command lookup keys.
- `translate_mistral.ps1` - legacy runner kept for reference.

The Python runner uses the OpenAI Python SDK against Mistral's OpenAI-compatible base URL:

```text
https://api.mistral.ai/v1
```

## Dry Run

Preview full-game batches without calling the API:

```powershell
python .\_tooling\mistral_translate\translate_mistral.py --dry-run --max-rows 24
```

Preview dialogue-only batches:

```powershell
python .\_tooling\mistral_translate\translate_mistral.py --dry-run --input-csv .\TextExport\dialogues.csv --output-jsonl .\TextExport\mistral_dialogue_translations.jsonl --max-rows 24
```

## Translate

Set your API key for the current PowerShell session:

```powershell
$env:MISTRAL_API_KEY = "your_key_here"
```

Run a small smoke test:

```powershell
python .\_tooling\mistral_translate\translate_mistral.py --model mistral-medium-3-5 --reasoning-effort none --batch-size 8 --retry-delay-ms 30000 --max-rows 24 --stop-on-failure
```

Run the full-game translation:

```powershell
python .\_tooling\mistral_translate\translate_mistral.py --model mistral-medium-3-5 --reasoning-effort none --batch-size 12 --retry-delay-ms 30000 --requests-per-minute 2
```

Default outputs:

```text
TextExport\mistral_fullgame_translations.jsonl
TextExport\mistral_fullgame_translations.failed.jsonl
```

Before injection, build the lookup-safe JSONL:

```powershell
python .\_tooling\mistral_translate\build_runtime_db_command_keys.py --export-dir .\TextExport --append-to-protected
python .\_tooling\mistral_translate\sync_runtime_lookup_terms.py --source-csv .\TextExport\strings_all.csv --translation-jsonl .\TextExport\mistral_fullgame_translations.jsonl --output-jsonl .\TextExport\mistral_fullgame_translations.synced.jsonl
python .\_tooling\mistral_translate\build_strict_safe_event_translations.py --source-csv .\TextExport_original_db_command_scan\strings_all.csv --command-strings-csv .\TextExport_original_db_command_scan\command_strings.csv --dialogues-csv .\TextExport_original_db_command_scan\dialogues.csv --translation-jsonl .\TextExport\mistral_fullgame_translations.synced.jsonl --extra-translation-jsonl .\TextExport_injected\mistral_remaining_translations.jsonl --output-jsonl .\TextExport\strict_safe_event_translations.jsonl
```

For the first stable build, inject `strict_safe_event_translations.jsonl` into `Data_Original`. This intentionally leaves database/system strings and runtime lookup keys original, while translating the safest message/choice/picture-text surface. Validate the export after injection by comparing command strings structurally: the only changed command IDs should be `101`, `102`, and confirmed picture-text slots. Use the broader synced JSONL only after a separate DB/display-field audit.

After the dialogue-safe build works, add visible DB/title/menu/name text:

```powershell
python .\_tooling\mistral_translate\build_visible_db_ui_translations.py --output-jsonl .\TextExport\visible_db_ui_translations.jsonl
.\_tooling\wolf_text_inject\target\release\wolf_text_inject.exe Data_Original .\TextExport\visible_db_ui_translations.jsonl Data_visible_db_ui_test --asset-root Data_Original --dry-run
.\_tooling\wolf_text_inject\target\release\wolf_text_inject.exe Data_Original .\TextExport\visible_db_ui_translations.jsonl Data_visible_db_ui_test --asset-root Data_Original
```

Validate the resulting `command_strings.csv` structurally. Expected changed command slots are `101:*`, `102:*`, confirmed picture-text slot `150:0`, and DB data-name lookup slot `250:2` only. `250:1` type names and `250:3` field/item names must remain original.

Dialogue-only output example:

```powershell
python .\_tooling\mistral_translate\translate_mistral.py --input-csv .\TextExport\dialogues.csv --output-jsonl .\TextExport\mistral_dialogue_translations.jsonl --model mistral-medium-3-5 --batch-size 12
```

## Resume Behavior

The script resumes automatically from the chosen output JSONL. Use `--no-resume` to ignore existing output.

- Every successful translated row is written immediately.
- If the script crashes, is interrupted, or the app closes, rerun the same command and already-written row IDs are skipped.
- If a batch fails because of rate limits, bad JSON, missing placeholders, or another validation problem, those rows are not written to the output JSONL.
- At the end of a run, untranslated rows are retried in retry passes.
- On the next launch, untranslated rows are retried first because they are still absent from the output JSONL.
- Existing output is also used to seed `translation_history`.

## Useful Options

- `--input-csv .\TextExport\strings_japanese.csv` translates full-game Japanese strings.
- `--input-csv .\TextExport\dialogues.csv` translates dialogue rows with speaker/event context.
- `--map-only` translates only map dialogue rows when using `dialogues.csv`.
- `--common-only` translates only common-event rows when using `dialogues.csv`.
- `--max-rows 100` limits a test run.
- `--start-after-id 1000` starts after an exported row id.
- `--batch-size 8` lowers context/cost per request.
- `--batch-size 16` improves context but can cost more per retry.
- `--history-size 10` sends the last translated lines as continuity context.
- `--max-retries 2` retries the current batch before deferring it.
- `--end-retry-rounds 5` retries any still-untranslated rows at the end of the run.
- `--retry-delay-ms 30000` controls retry/backoff delay for rate limits or network errors.
- `--requests-per-minute 2` enforces a sliding-window 2 RPM limit.
- `--no-end-retry` disables end-of-run retry passes.
- `--no-dedupe` translates every row individually instead of reusing exact repeated templates.
- `--stop-on-failure` stops immediately if a batch fails validation.
- `--model mistral-medium-3-5` chooses the Mistral model.
- `--reasoning-effort none` keeps Medium 3.5 thinking off for cheaper, cleaner JSON output.
- `--reasoning-effort high` enables Medium 3.5 adjustable reasoning for difficult retry/spot-fix runs, at higher token cost.
- `--input-cost-per-1m 1.5` overrides the input-token price used for estimates.
- `--output-cost-per-1m 7.5` overrides the output-token price used for estimates.

The runner prints a file-scoped progress line:

```text
BasicData/CDataBase.dat: white progress bar 0/312 0.00% | T 0/24029 | ETA -- | starting
```

When a file finishes, the current line is left in the console and a Dazed-style result line is printed:

```text
BasicData/CDataBase.dat: [Input: 111][Output: 22][Cost: $0.0003][Total: $0.0003][0.7s] ✓
```

On resumed runs, the per-file `[Total: ...]` value is seeded from the existing output JSONL, so it keeps counting from earlier runs instead of starting at zero again.

At the end, the runner scans the output JSONL and prints the total translation cost for the whole completed TL, including rows translated in earlier resumed runs:

```text
TOTAL TL: [Input: 123456][Output: 45678][Cost: $0.5278][Requests: 197][1h 42m] ✓
```

Retry sleeps stay on the same progress line, for example `API failed after 2s; retry in 30s`. Once at least one successful API request finishes, ETA is estimated from the observed end-to-end batch cycle time, including any real RPM/RPS waits that happened during the run.

Live API calls always obey both local limits: the configured sliding-window RPM ceiling and a hard maximum of 1 request per second. Long-running requests count against the window naturally, so the runner will not sleep unnecessarily after enough wall-clock time has already passed. The RPM window also uses a 1-second safety margin before considering an old request expired.

Mistral server-side limits are not just RPM; they also include RPS/concurrency and tokens per minute. If the API returns 429, the runner now keeps the response headers, honors `Retry-After`/rate-limit reset headers when present, and removes the rejected request from the local RPM history so retries are based on the last accepted request starts rather than the failed 429 attempt.

WOLF ruby examples such as `\r[base,ruby]` are preserved as WOLF commands during extraction. The runner avoids decoding those as carriage returns, and sample-map tutorial fragments get a small cleanup pass for common leftover Japanese examples like `本`, `人生`, and `あいうえお`.

If a model response drops a protected placeholder, the runner only auto-repairs very obvious adjacent control-code examples. The missing token must be a control-only marker like `\\.`, `\\!`, `\\^`, or `\\\\`, and it must have been directly adjacent to another placeholder in the source. Otherwise the batch retries instead of guessing, so placeholders are not moved across translated words.

## Reinsertion Contract

Use `translation_template` as the translated body.

The reinserter should replace placeholders by using the row's token map:

```json
{
  "source_template": "{CTRL1}\nThe source line",
  "translation_template": "{CTRL1}\nThe translated line",
  "tokens": {
    "CTRL1": "\\s[15]"
  }
}
```

Every `{CTRLn}` in `source_template` must appear exactly once in `translation_template`.
