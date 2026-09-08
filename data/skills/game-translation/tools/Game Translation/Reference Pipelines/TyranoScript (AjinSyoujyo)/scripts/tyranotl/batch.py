"""Message Batches driver: submit -> poll -> fetch, resumable at every step.

A batch can sit queued for hours - ``processing=118, succeeded=0`` is the queue
depth, not a completion ratio. ``submit`` writes ``_batch_state.json`` and
returns; ``fetch`` works any time afterwards, so Ctrl-C during ``status`` polling
is always safe. If the queue stalls, ``tl.py live`` finishes the same work
synchronously through the same request builder and parser.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from . import pricing, prompts
from .store import Glossary, Store


def client():
    try:
        import anthropic
    except ImportError:  # pragma: no cover - environment problem, not logic
        raise SystemExit("pip install anthropic")
    return anthropic.Anthropic()


class State:
    """Bookkeeping for one submitted batch. Requests carry short integer ids;
    the id->unit map stays local and is reattached on fetch."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = {}

    def load(self) -> "State":
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        return self

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def clear(self) -> None:
        self.data = {}
        if self.path.exists():
            self.path.unlink()


def submit(store: Store, state: State, bible: str, glossary: Glossary, model: str,
           effort: str, requests: list[prompts.Request], limit: int | None = None) -> str:
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request as BatchRequest

    if limit:
        requests = requests[:limit]
    if not requests:
        raise SystemExit("nothing to translate")

    payload = []
    index_map: dict[str, list[str]] = {}
    for number, request in enumerate(requests):
        custom_id = f"r{number:05d}"
        index_map[custom_id] = request.ids
        params = prompts.build_params(request, bible, glossary, model, effort, "1h")
        payload.append(BatchRequest(custom_id=custom_id,
                                    params=MessageCreateParamsNonStreaming(**params)))

    batch = client().messages.batches.create(requests=payload)
    state.data = {
        "batch_id": batch.id,
        "model": model,
        "effort": effort,
        "submitted": len(payload),
        "index_map": index_map,
        "kinds": {f"r{n:05d}": r.kind for n, r in enumerate(requests)},
    }
    state.save()
    return batch.id


def status(state: State) -> dict[str, Any]:
    batch_id = state.data.get("batch_id")
    if not batch_id:
        raise SystemExit("no batch in flight; run `tl.py submit` first")
    batch = client().messages.batches.retrieve(batch_id)
    counts = batch.request_counts
    return {
        "id": batch.id,
        "processing_status": batch.processing_status,
        "processing": counts.processing,
        "succeeded": counts.succeeded,
        "errored": counts.errored,
        "canceled": counts.canceled,
        "expired": counts.expired,
    }


def poll(state: State, interval: int = 60, quiet: bool = False) -> dict[str, Any]:
    while True:
        info = status(state)
        if not quiet:
            print(f"  {info['processing_status']}: processing={info['processing']} "
                  f"succeeded={info['succeeded']} errored={info['errored']}", flush=True)
        if info["processing_status"] == "ended":
            return info
        time.sleep(interval)


def fetch(store: Store, state: State) -> dict[str, Any]:
    batch_id = state.data.get("batch_id")
    if not batch_id:
        raise SystemExit("no batch in flight")
    index_map: dict[str, list[str]] = state.data["index_map"]
    kinds: dict[str, str] = state.data.get("kinds", {})
    units = store.by_id()

    applied = 0
    parsed = failed = 0
    problems: list[str] = []
    usage = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}

    for result in client().messages.batches.results(batch_id):
        kind = result.result.type
        if kind != "succeeded":
            failed += 1
            problems.append(f"{result.custom_id}: batch result {kind}")
            continue
        message = result.result.message
        use = getattr(message, "usage", None)
        if use is not None:
            usage["input"] += getattr(use, "input_tokens", 0) or 0
            usage["output"] += getattr(use, "output_tokens", 0) or 0
            usage["cache_write"] += getattr(use, "cache_creation_input_tokens", 0) or 0
            usage["cache_read"] += getattr(use, "cache_read_input_tokens", 0) or 0

        text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")
        table = prompts.parse_reply(text)
        if not table:
            failed += 1
            problems.append(f"{result.custom_id}: reply did not parse")
            continue
        parsed += 1
        ids = index_map.get(result.custom_id, [])
        request = prompts.Request(
            key=result.custom_id, kind=kinds.get(result.custom_id, "dialogue"),
            phase="text", units=[units[i] for i in ids if i in units])
        count, issues = prompts.apply_reply(request, table)
        applied += count
        problems.extend(issues)

    store.save()
    return {"applied": applied, "parsed": parsed, "failed": failed,
            "problems": problems, "usage": usage}


def dryrun(requests: list[prompts.Request], bible: str, glossary: Glossary,
           model: str, effort: str, show_sample: bool = False) -> dict[str, Any]:
    prefix = prompts.RULES + "\n" + prompts.SPEAKERLESS_NOTE + "\n" + bible
    # Both system blocks carry a cache breakpoint, so the whole system prompt is
    # the cached prefix and only the per-request body is fresh input.
    prefix_tokens = pricing.estimate_tokens(prefix) + pricing.estimate_tokens(glossary.render())

    variable_in = 0
    source_chars = 0
    units = 0
    for request in requests:
        body = prompts.user_message(request)
        variable_in += pricing.estimate_tokens(body)
        source_chars += sum(len(u.src) for u in request.units)
        units += len(request.units)
    out_tokens = int(pricing.estimate_tokens("x" * source_chars) * pricing.MEASURED_OUTPUT_RATIO)

    costs = pricing.four_ways(model, prefix_tokens, len(requests), variable_in, out_tokens)
    info = {
        "requests": len(requests),
        "units": units,
        "source_chars": source_chars,
        "prefix_tokens": prefix_tokens,
        "variable_input_tokens": variable_in,
        "estimated_output_tokens": out_tokens,
        "costs": costs,
    }
    if show_sample and requests:
        info["sample"] = prompts.user_message(requests[0])
    return info
