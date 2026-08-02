# Roadmap

## Translation-cache portability and controls

The global cache is implemented in `util.translation`: successful live and
batch-consume results are persisted in `log/translation_cache.json`, payload and
request context contribute to the key, cache hits avoid provider calls, and
Japanese-only cached values are re-expanded against the current file.

Remaining product work:

- Add an optional per-game cache so reusable translations travel with project
  backups without replacing the tool-wide cache.
- Show cache hits, misses, and estimated savings in the UI.
- Add explicit per-game export, import, and clear operations.
- Decide whether model and prompt revisions need additional invalidation
  metadata beyond the current payload, language, glossary, and request context.
