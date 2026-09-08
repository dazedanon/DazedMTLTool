"""Synchronous driver: the same requests, run now, with visible progress.

Costs 2x the batch price and returns in minutes instead of hours. Worth it for a
small remainder, for a stalled queue, or while tuning the prompt.

One subtlety: with prompt caching, concurrency and cache hits fight on the first
few requests. The first request is therefore fired alone so that it *writes* the
cache; only then does the pool fan out and read it.
"""
from __future__ import annotations

import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import prompts
from .store import Glossary, Store

MAX_ATTEMPTS = 5


def client():
    try:
        import anthropic
    except ImportError:  # pragma: no cover
        raise SystemExit("pip install anthropic")
    return anthropic.Anthropic()


def _retry_after(error: Exception, attempt: int) -> float:
    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    raw = headers.get("retry-after") if hasattr(headers, "get") else None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return min(60.0, 2 ** attempt + random.random() * 2)


def _call(api, request: prompts.Request, bible: str, glossary: Glossary,
          model: str, effort: str) -> tuple[dict[str, str], dict[str, int]]:
    import anthropic

    params = prompts.build_params(request, bible, glossary, model, effort, "5m")
    last: Exception | None = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            with api.messages.stream(**params) as stream:
                message = stream.get_final_message()
            text = "".join(b.text for b in message.content
                           if getattr(b, "type", "") == "text")
            use = message.usage
            usage = {
                "input": use.input_tokens or 0,
                "output": use.output_tokens or 0,
                "cache_write": getattr(use, "cache_creation_input_tokens", 0) or 0,
                "cache_read": getattr(use, "cache_read_input_tokens", 0) or 0,
            }
            return prompts.parse_reply(text), usage
        except anthropic.RateLimitError as exc:
            last = exc
            time.sleep(_retry_after(exc, attempt))
        except anthropic.APIStatusError as exc:
            last = exc
            if 400 <= exc.status_code < 500 and exc.status_code != 429:
                raise
            time.sleep(min(45.0, 2 ** attempt + random.random()))
        except anthropic.APIConnectionError as exc:
            last = exc
            time.sleep(min(45.0, 2 ** attempt + random.random()))
    raise RuntimeError(f"{request.key}: gave up after {MAX_ATTEMPTS} attempts ({last})")


def run(store: Store, bible: str, glossary: Glossary, model: str, effort: str,
        requests: list[prompts.Request], workers: int = 4,
        save_every: int = 5, progress=print) -> dict[str, Any]:
    if not requests:
        return {"applied": 0, "requests": 0, "problems": [], "usage": {}}

    api = client()
    totals = {"applied": 0, "failed": 0}
    usage = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    problems: list[str] = []
    lock = threading.Lock()
    done = 0

    def handle(request: prompts.Request) -> None:
        nonlocal done
        try:
            table, use = _call(api, request, bible, glossary, model, effort)
        except Exception as exc:                     # noqa: BLE001 - reported, not raised
            with lock:
                totals["failed"] += 1
                problems.append(f"{request.key}: {exc}")
                done += 1
                progress(f"  [{done}/{len(requests)}] {request.key} FAILED: {exc}")
            return
        with lock:
            for key in usage:
                usage[key] += use.get(key, 0)
            if not table:
                totals["failed"] += 1
                problems.append(f"{request.key}: reply did not parse")
            else:
                count, issues = prompts.apply_reply(request, table)
                totals["applied"] += count
                problems.extend(issues)
            done += 1
            progress(f"  [{done}/{len(requests)}] {request.key} "
                     f"+{len(table)} (cache_read={use.get('cache_read', 0)})")
            if done % save_every == 0:
                store.save()

    # Fire one request alone so it writes the cache, then fan out to read it.
    handle(requests[0])
    store.save()
    rest = requests[1:]
    if rest:
        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            list(pool.map(handle, rest))
    store.save()

    return {"applied": totals["applied"], "failed": totals["failed"],
            "requests": len(requests), "problems": problems, "usage": usage}
