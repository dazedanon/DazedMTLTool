# TODO

## Custom game prompt

- Keep the default prompt (`prompt.txt`) as the base for every game.
- Add an optional **per-game custom prompt** in the UI that merges with the default (custom rules layered on top of shared instructions, not a full replacement unless explicitly chosen).
- Surface this in settings / project setup so each game folder can carry its own tone, terminology notes, or content warnings without forking the global prompt.

## Batch history tab

- Add a **Batch** tab (or dedicated panel) in the GUI to manage past Anthropic batch runs saved locally.
- Persist batch metadata locally (batch id, submit time, file set, status, cost estimate, etc.) alongside existing `log/batch_*.json` artifacts (`batch_state.json`, `batch_results.json`, `batch_requests.json`).
- Actions:
  - **List batches** — browse all batches the tool has submitted or tracked for this project.
  - **Redownload** — fetch results again from Anthropic for a completed batch (e.g. after a crash before consume, or to recover results). **Not in sketch yet.**
  - **Cancel batch** — cancel an in-flight batch where the API allows it (`in_progress` → `canceling` → `ended`).
  - **Usage / cost** — sum real billed tokens from batch results (input, output, cache read/write, thinking).
  - Resume / link into the existing collect → submit → consume flow when a batch is still pending or fetched but not consumed.

### Sketch: CLI batch manager (adapt for DazedMTLTool)

Reference from sibling tooling (`batches.py`). Port to this repo using `_get_anthropic_client()` / `fetchTranslationBatches()` in `util/translation.py` and `log/batch_state.json` (maps to sketch's `tl/_batch_state.json`).

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batches.py — list and cancel Anthropic Message Batches (the ones DazedMTLTool
submits). Handy when a run is stuck polling or you submitted by mistake.

    set ANTHROPIC_API_KEY=sk-...   # or key= in .env

    python tooling/batches.py                 # list recent batches (default)
    python tooling/batches.py list --limit 50
    python tooling/batches.py cancel <batch_id> [<batch_id> ...]
    python tooling/batches.py cancel --all     # cancel every in-progress batch
    python tooling/batches.py cancel --mine    # cancel batch(es) in log/batch_state.json
    python tooling/batches.py usage [batch_id] # real billed tokens + estimated cost

    # TODO: redownload <batch_id>  — re-fetch results into log/batch_results.json

Only an in-progress batch can be cancelled; cancellation finishes any in-flight
requests (in_progress -> canceling -> ended). Already-ended batches can't be
cancelled.
"""
import os
import sys
import argparse
import collections

# Adapt imports to DazedMTLTool:
#   from util.translation import _get_anthropic_client, BATCH_STATE_FILE, _read_batch_file, fetchTranslationBatches

CANCELABLE = {"in_progress"}


def _counts(b):
    rc = getattr(b, "request_counts", None)
    if not rc:
        return ""
    parts = []
    for k in ("processing", "succeeded", "errored", "canceled", "expired"):
        v = getattr(rc, k, None)
        if v:
            parts.append(f"{k[:4]}={v}")
    return " ".join(parts)


def _mine_batch_ids():
    """Return batch ids from log/batch_state.json (DazedMTLTool format)."""
    # state = _read_batch_file(BATCH_STATE_FILE) or {}
    # return [b["id"] for b in state.get("batches", [])]
    ...


def cmd_list(client, limit):
    mine = set(_mine_batch_ids())
    print(f"{'BATCH ID':<28} {'STATUS':<12} {'CREATED':<22} COUNTS")
    print("-" * 90)
    n = 0
    for b in client.messages.batches.list(limit=limit):
        n += 1
        mark = "  <- yours" if b.id in mine else ""
        created = str(getattr(b, "created_at", "") or "")[:22]
        print(f"{b.id:<28} {b.processing_status:<12} {created:<22} {_counts(b)}{mark}")
    ...


def cmd_cancel(client, ids, do_all, do_mine, limit):
    # targets from ids, --mine (log/batch_state.json), or --all (in_progress only)
    # client.messages.batches.cancel(bid)
    ...


def cmd_usage(client, bid, model):
    # Sum usage across client.messages.batches.results(bid)
    # Price with getPricingConfig(model) + 50% batch discount on I/O
    ...


# cmd_redownload(client, bid):
#     # TODO: client.messages.batches.results(bid) -> merge into log/batch_results.json
#     # Wire custom_id map from batch_state.json entries
#     ...
```

**GUI tab (later):** same operations as buttons on a saved local history table — list, cancel, usage, redownload, resume consume.

## Local translation cache (game retranslate)

- Persist every successful translation locally so a full retranslate from scratch can reuse prior results instead of paying again.
- **Cache key:** hash the translation **payload** (source Japanese text sent to the model) plus target language — same approach as the existing global cache in `util/translation.py` (`get_cache_key`, `log/translation_cache.json`).
  Payload keys naturally dedupe identical lines across files and survive re-extract / re-import as long as the source string is unchanged.
- **Scope:** consider a per-game cache file under the game project (e.g. `<game_root>/translation_cache.json` or alongside `wolf_json/`) in addition to (or merged with) the tool-wide `log/translation_cache.json`, so caches travel with the game folder and are easy to back up.
- **Write path:** on every successful translate (live and batch consume), store `{cache_key: translation}` before or as results land in `translated/`.
- **Read path:** before calling the API, check cache; on hit, skip the request and apply the cached translation (respecting file-specific re-expansion where the payload is Japanese-only).
- **Retranslate workflow:** when the user re-imports fresh JSON and runs Translate again, cache hits should fill `translated/` automatically for unchanged source lines; only new or edited source text should incur API cost.
- **UI (later):** cache stats (hits / misses / estimated savings), export/import, clear cache for one game, optional “prefer cache” toggle.
- **Invalidation:** optional metadata (model id, prompt version) in the key or entry if we need to avoid reusing stale translations after prompt or model changes.

## According to someone from f95, the patcher breaks if a folder's name has an apostrophe