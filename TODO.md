# TODO

## Local translation cache (game retranslate)

- Persist every successful translation locally so a full retranslate from scratch can reuse prior results instead of paying again.
- **Cache key:** hash the translation **payload** (source Japanese text sent to the model) plus target language - same approach as the existing global cache in `util.translation` (`get_cache_key`, `log/translation_cache.json`).
  Payload keys naturally dedupe identical lines across files and survive re-extract / re-import as long as the source string is unchanged.
- **Scope:** consider a per-game cache file under the game project (e.g. `<game_root>/translation_cache.json` or alongside `wolf_json/`) in addition to (or merged with) the tool-wide `log/translation_cache.json`, so caches travel with the game folder and are easy to back up.
- **Write path:** on every successful translate (live and batch consume), store `{cache_key: translation}` before or as results land in `translated/`.
- **Read path:** before calling the API, check cache; on hit, skip the request and apply the cached translation (respecting file-specific re-expansion where the payload is Japanese-only).
- **Retranslate workflow:** when the user re-imports fresh JSON and runs Translate again, cache hits should fill `translated/` automatically for unchanged source lines; only new or edited source text should incur API cost.
- **UI (later):** cache stats (hits / misses / estimated savings), export/import, clear cache for one game, optional "prefer cache" toggle.
- **Invalidation:** optional metadata (model id, prompt version) in the key or entry if we need to avoid reusing stale translations after prompt or model changes.
