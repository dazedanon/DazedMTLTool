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
./tests/run_tests.sh integration # persisted jobs/provider orchestration
./tests/run_tests.sh extended  # Qt/workflow/navigation changes
./tests/run_tests.sh imagetl   # OpenCV/ImageTL extras required
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

## Sequential native OpenAI batches

Native OpenAI Batch queues exceeding the conservative estimated-input cap are
submitted one provider chunk at a time. The default is **600,000 tokens**;
`openaiBatchTokenLimit` in `.env` overrides it with a positive integer. This is
a local estimate, not a discovered account allowance. Choose a cap below your
model's allowance with room for other queued jobs. OpenAI enforces its separate
[queued-prompt-token limits](https://developers.openai.com/api/docs/guides/batch#rate-limits).
Other providers and OpenAI-compatible endpoints keep their existing behavior.

The estimator counts the complete serialized request, including system prompt,
history, payload, response schema and extra body fields, using the existing
queue tokenizer plus 5% and 32 tokens of overhead. Request-count and JSONL-size
limits still apply. A single request larger than the token cap blocks submission
with instructions to reduce batch size/context and re-collect.

Each successful provider create is atomically checkpointed with its ID and
custom-ID mapping before returning. `partially_submitted` means some requests
are paid and others remain in the durable queue. `sequential_token_limit` and
`queued_request_count` preserve the run's cap and full scope in state/history.
The cross-process submission lock covers the status gate and create operation.
Resume polls the paid chunk before submitting the next unsent slice. A failed,
expired, cancelled or request-error chunk blocks later submissions and writes.
Fetch merges all chunks only after success; missing/error results retain the
queue. Batch History must preserve partial state and reject partial downloads,
including when an individual chunk is already marked ended.

These log messages are normal:

- `sequential OpenAI cap`
- `More queued requests remain`
- `Current provider chunk completed. Submitting the next queued chunk...`

Use **Resume** in Batch Translate or Batch History after stopping the application.
Do not discard a partial queue to continue it. CLI callers resume through
`runTranslationBatches()`; direct fetch refuses partial sequential runs. The queue cannot
be reconstructed from provider IDs alone after its unsent requests are deleted.

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
