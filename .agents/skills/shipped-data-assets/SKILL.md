---
name: shipped-data-assets
description: Keep shipped data assets present in git branch archives and tool updates. Use when adding or changing defaults under data/, editing their .gitignore rules, changing the update installer, or updating bundled-data coverage in tests/test_bundled_updates.py.
---

# Shipped Data Assets

Tool auto-update downloads a git branch archive. Files matched by `.gitignore` are omitted from that archive and never reach users.

## Maintain shipped defaults

- Add a `.gitignore` negation for every shipped path under `data/`, following existing patterns such as:
  - `!data/skills/**`
  - `!data/help/**`
  - `!data/vocab_base.txt`
  - `!data/translation_contexts.json`
- Do not rely on `UpdateThread.should_install` alone; ignored files never appear in the downloaded archive.
- Extend `_SHIPPED_DATA_FILES` or `ShippedDataTrackingTests` in `tests/test_bundled_updates.py` when adding a shipped path.
- Keep user-local files ignored and protected, including `data/vocab.txt`, `data/last_update_sha.txt`, `data/wolf_*.json`, and `data/api_keys.json`.

## Verify tracking

Run `git check-ignore -- <shipped-path>` for each affected file. A shipped path must exit with status 1, indicating that it is not ignored.

Run the bundled-update tests after changing shipped paths, ignore rules, or installer behavior:

```bash
python -m unittest tests.test_bundled_updates.ShippedDataTrackingTests
```
