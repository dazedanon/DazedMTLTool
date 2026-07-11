#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable Anthropic Message Batch history and spend-safe management ops.

Active run files (queue / state / results) still live in util.translation.
This module keeps an append-only index so batch ids and custom_id maps survive
fetch and clear, enabling cancel / usage / redownload / resume without
re-submitting (and re-billing) work.
"""

from __future__ import annotations

import copy
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from util.translation import (
    BATCH_LOCK,
    BATCH_QUEUE_FILE,
    BATCH_RESULTS_FILE,
    BATCH_STATE_FILE,
    _batch_file_lock,
    _get_anthropic_client,
    _read_batch_file,
    _write_batch_file,
    getPricingConfig,
)

BATCH_HISTORY_FILE = Path("log/batch_history.json")

# Local lifecycle statuses (not 1:1 with Anthropic processing_status).
STATUS_QUEUED = "queued"
STATUS_SUBMITTED = "submitted"
STATUS_CANCELING = "canceling"
STATUS_ENDED = "ended"
STATUS_FETCHED = "fetched"
STATUS_CONSUMED = "consumed"
STATUS_CANCELED = "canceled"
STATUS_ERROR = "error"

TERMINAL_STATUSES = frozenset({
    STATUS_CONSUMED,
    STATUS_CANCELED,
    STATUS_ERROR,
})
CANCELABLE_API = frozenset({"in_progress"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _empty_history() -> dict:
    return {"batches": []}


def _read_history_unlocked() -> dict:
    """Read history under an existing batch file lock."""
    data = _read_batch_file(BATCH_HISTORY_FILE)
    if not data:
        return _empty_history()
    if not isinstance(data.get("batches"), list):
        print(f"[BATCH] Corrupt history (missing batches list): {BATCH_HISTORY_FILE}", flush=True)
        return _empty_history()
    return data


def _write_history_unlocked(data: dict) -> None:
    _write_batch_file(BATCH_HISTORY_FILE, data)


def read_history() -> dict:
    """Return the full history document (copy-safe for callers)."""
    with _batch_file_lock():
        return copy.deepcopy(_read_history_unlocked())


def _find_entry(history: dict, batch_id: str) -> Optional[dict]:
    for entry in history.get("batches", []):
        if entry.get("id") == batch_id:
            return entry
    return None


def upsert_history_entry(batch_id: str, **fields: Any) -> dict:
    """Create or update one history row. Returns the updated entry (copy)."""
    with BATCH_LOCK:
        with _batch_file_lock():
            history = _read_history_unlocked()
            entry = _find_entry(history, batch_id)
            now = _utc_now()
            if entry is None:
                entry = {
                    "id": batch_id,
                    "created_at": now,
                    "updated_at": now,
                    "status": STATUS_SUBMITTED,
                    "model": "",
                    "request_count": 0,
                    "file_set": [],
                    "cost_estimate": None,
                    "custom_ids": {},
                    "usage": None,
                    "actual_cost": None,
                    "notes": "",
                    "request_counts": None,
                    "api_status": None,
                }
                history.setdefault("batches", []).append(entry)
            for key, value in fields.items():
                if value is not None or key in ("notes", "usage", "actual_cost", "cost_estimate", "request_counts"):
                    entry[key] = value
            entry["updated_at"] = now
            _write_history_unlocked(history)
            return copy.deepcopy(entry)


def record_submit(
    batches: list[dict],
    *,
    model: str = "",
    file_set: Optional[list] = None,
    cost_estimate: Optional[dict] = None,
) -> None:
    """Record newly submitted Anthropic batches into durable history."""
    file_set = list(file_set or [])
    for info in batches:
        bid = info.get("id")
        if not bid:
            continue
        custom_ids = dict(info.get("custom_ids") or {})
        upsert_history_entry(
            bid,
            status=STATUS_SUBMITTED,
            model=model or (cost_estimate or {}).get("model") or "",
            request_count=len(custom_ids),
            file_set=file_set,
            cost_estimate=copy.deepcopy(cost_estimate) if cost_estimate else None,
            custom_ids=custom_ids,
            api_status="in_progress",
            notes="",
        )


def record_fetch(
    batch_ids: Iterable[str],
    *,
    succeeded: int = 0,
    errored: int = 0,
    usage: Optional[dict] = None,
    actual_cost: Optional[float] = None,
) -> None:
    """Mark batches as fetched after results land locally."""
    note = f"fetched ok={succeeded} err={errored}"
    for bid in batch_ids:
        fields = {
            "status": STATUS_FETCHED,
            "api_status": "ended",
            "notes": note,
        }
        if usage is not None:
            fields["usage"] = copy.deepcopy(usage)
        if actual_cost is not None:
            fields["actual_cost"] = actual_cost
        upsert_history_entry(bid, **fields)


def mark_batches_consumed(batch_ids: Iterable[str]) -> None:
    """Mark history rows consumed after a successful consume + clear."""
    for bid in batch_ids:
        upsert_history_entry(bid, status=STATUS_CONSUMED, notes="consumed")


def mark_batches_canceled(batch_ids: Iterable[str], *, api_status: str = "canceling") -> None:
    local = STATUS_CANCELED if api_status == "ended" else STATUS_CANCELING
    for bid in batch_ids:
        upsert_history_entry(
            bid,
            status=local,
            api_status=api_status,
            notes=f"cancel requested ({api_status})",
        )


def list_local_batches(*, refresh_live: bool = False) -> list[dict]:
    """Return history entries newest-first. Optionally refresh non-terminal via API."""
    history = read_history()
    entries = list(history.get("batches") or [])
    if refresh_live:
        for entry in entries:
            status = entry.get("status")
            if status in TERMINAL_STATUSES or status == STATUS_CONSUMED:
                continue
            if status in (STATUS_FETCHED, STATUS_QUEUED):
                continue
            try:
                refresh_batch_status(entry["id"])
            except Exception as exc:
                upsert_history_entry(entry["id"], notes=f"refresh failed: {exc}")
        history = read_history()
        entries = list(history.get("batches") or [])
    entries.sort(key=lambda e: e.get("created_at") or "", reverse=True)
    return entries


def refresh_batch_status(batch_id: str) -> dict:
    """Retrieve live Anthropic status and update the history row."""
    client = _get_anthropic_client()
    b = client.messages.batches.retrieve(batch_id)
    api_status = getattr(b, "processing_status", None) or ""
    counts = getattr(b, "request_counts", None)
    counts_dict = None
    if counts is not None:
        counts_dict = {
            k: getattr(counts, k, 0) or 0
            for k in ("processing", "succeeded", "errored", "canceled", "expired")
        }

    entry = None
    with _batch_file_lock():
        history = _read_history_unlocked()
        entry = _find_entry(history, batch_id)
        prev_status = (entry or {}).get("status")

    # Map API status onto local lifecycle without clobbering fetched/consumed.
    local_status = None
    if prev_status in (STATUS_FETCHED, STATUS_CONSUMED):
        local_status = prev_status
    elif api_status == "in_progress":
        local_status = STATUS_SUBMITTED
    elif api_status == "canceling":
        local_status = STATUS_CANCELING
    elif api_status == "ended":
        # Ended after cancel vs normal end - inspect counts when available.
        if counts_dict and (counts_dict.get("canceled") or 0) > 0 and (counts_dict.get("succeeded") or 0) == 0:
            local_status = STATUS_CANCELED
        else:
            local_status = STATUS_ENDED

    fields: dict[str, Any] = {
        "api_status": api_status,
        "request_counts": counts_dict,
    }
    if local_status:
        fields["status"] = local_status
    return upsert_history_entry(batch_id, **fields)


def cancel_batches(batch_ids: Iterable[str]) -> list[dict]:
    """Cancel in-progress batches. Never submits new work.

    Also updates active batch_state so resume does not keep polling canceled ids.
    """
    client = _get_anthropic_client()
    results = []
    canceled_active = []
    for bid in batch_ids:
        try:
            b = client.messages.batches.retrieve(bid)
            api_status = getattr(b, "processing_status", "") or ""
            if api_status not in CANCELABLE_API:
                results.append({"id": bid, "ok": False, "error": f"not cancelable ({api_status})"})
                upsert_history_entry(bid, notes=f"cancel skipped: {api_status}", api_status=api_status)
                continue
            b = client.messages.batches.cancel(bid)
            new_status = getattr(b, "processing_status", "canceling") or "canceling"
            mark_batches_canceled([bid], api_status=new_status)
            canceled_active.append(bid)
            results.append({"id": bid, "ok": True, "api_status": new_status})
        except Exception as exc:
            results.append({"id": bid, "ok": False, "error": str(exc)})
            upsert_history_entry(bid, notes=f"cancel failed: {exc}", status=STATUS_ERROR)

    if canceled_active:
        _remove_active_batch_ids(canceled_active)
    return results


def _remove_active_batch_ids(batch_ids: list[str]) -> None:
    """Drop canceled ids from active state so poll/resume does not wait on them."""
    id_set = set(batch_ids)
    with BATCH_LOCK:
        with _batch_file_lock():
            state = _read_batch_file(BATCH_STATE_FILE)
            batches = [b for b in (state.get("batches") or []) if b.get("id") not in id_set]
            if not batches:
                # No active submitted batches left.
                if state.get("status") == "fetched" or state.get("batch_ids"):
                    state["batches"] = []
                    _write_batch_file(BATCH_STATE_FILE, state)
                else:
                    try:
                        if BATCH_STATE_FILE.exists():
                            BATCH_STATE_FILE.unlink()
                    except Exception:
                        pass
            else:
                state["batches"] = batches
                _write_batch_file(BATCH_STATE_FILE, state)


def _usage_from_message(u) -> dict:
    cr = getattr(u, "cache_read_input_tokens", 0) or 0
    cw = getattr(u, "cache_creation_input_tokens", 0) or 0
    inp = getattr(u, "input_tokens", 0) or 0
    out = getattr(u, "output_tokens", 0) or 0
    # Adaptive thinking may surface under several names depending on SDK version.
    thinking = (
        getattr(u, "thinking_tokens", None)
        or getattr(u, "output_thinking_tokens", None)
        or 0
    ) or 0
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw,
        "thinking_tokens": thinking,
    }


def _price_usage(usage: dict, model: str) -> float:
    """Price real batch usage with cache multipliers and 50% batch discount."""
    pricing = getPricingConfig(model)
    br = pricing["inputAPICost"] / 1_000_000
    orr = pricing["outputAPICost"] / 1_000_000
    cr = usage.get("cache_read_input_tokens", 0) or 0
    cw = usage.get("cache_creation_input_tokens", 0) or 0
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    thinking = usage.get("thinking_tokens", 0) or 0
    # Thinking tokens are billed as output on Anthropic.
    raw = cr * br * 0.10 + cw * br * 2.00 + inp * br + (out + thinking) * orr
    return raw * 0.50


def _sum_usage_from_results(client, batch_id: str, custom_ids: dict) -> tuple[dict, int, int]:
    """Stream batch results and sum usage. Returns (usage, succeeded, errored)."""
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }
    succeeded = 0
    errored = 0
    for r in client.messages.batches.results(batch_id):
        res = r.result
        if res.type != "succeeded":
            errored += 1
            continue
        succeeded += 1
        part = _usage_from_message(res.message.usage)
        for k, v in part.items():
            totals[k] = totals.get(k, 0) + (v or 0)
    # custom_ids unused for summing but kept for API symmetry / future filters
    _ = custom_ids
    return totals, succeeded, errored


def usage_for_batch(batch_id: str, model: Optional[str] = None) -> dict:
    """Sum real billed tokens from Anthropic results and persist onto history."""
    history = read_history()
    entry = _find_entry(history, batch_id)
    if entry is None:
        raise ValueError(f"Unknown batch id (not in local history): {batch_id}")

    client = _get_anthropic_client()
    # Ensure batch has ended before streaming results.
    b = client.messages.batches.retrieve(batch_id)
    api_status = getattr(b, "processing_status", "") or ""
    if api_status != "ended":
        raise ValueError(f"Batch {batch_id} is not ended (status={api_status})")

    custom_ids = dict(entry.get("custom_ids") or {})
    usage, succeeded, errored = _sum_usage_from_results(client, batch_id, custom_ids)
    use_model = model or entry.get("model") or ""
    cost = _price_usage(usage, use_model) if use_model else None
    updated = upsert_history_entry(
        batch_id,
        usage=usage,
        actual_cost=cost,
        api_status="ended",
        notes=f"usage ok={succeeded} err={errored}",
    )
    return {
        "id": batch_id,
        "usage": usage,
        "actual_cost": cost,
        "succeeded": succeeded,
        "errored": errored,
        "model": use_model,
        "entry": updated,
    }


def _result_entry_from_message(msg) -> dict:
    text = "".join(getattr(b, "text", "") or "" for b in msg.content)
    u = msg.usage
    part = _usage_from_message(u)
    cr = part["cache_read_input_tokens"]
    cw = part["cache_creation_input_tokens"]
    inp = part["input_tokens"]
    out = part["output_tokens"]
    entry = {
        "text": text,
        "prompt_tokens": inp + cr + cw,
        "completion_tokens": out,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cw,
    }
    if part.get("thinking_tokens"):
        entry["thinking_tokens"] = part["thinking_tokens"]
    return entry


def download_batch_results(
    batch_id: str,
    custom_ids: dict,
    *,
    client=None,
) -> tuple[dict, list, dict]:
    """Download one ended batch into a cache-key -> result map.

    Returns (results, errored_list, usage_totals).
    """
    client = client or _get_anthropic_client()
    results, errored = {}, []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }
    for r in client.messages.batches.results(batch_id):
        key = custom_ids.get(r.custom_id)
        if key is None:
            continue
        res = r.result
        if res.type != "succeeded":
            detail = res.type
            err = getattr(res, "error", None)
            if err is not None:
                inner = getattr(err, "error", err)
                detail = (
                    f"{res.type} | {getattr(inner, 'type', '')}: "
                    f"{str(getattr(inner, 'message', '') or err)[:200]}"
                )
            errored.append((r.custom_id, detail))
            continue
        msg = res.message
        results[key] = _result_entry_from_message(msg)
        part = _usage_from_message(msg.usage)
        for k, v in part.items():
            usage_totals[k] = usage_totals.get(k, 0) + (v or 0)
    return results, errored, usage_totals


def redownload_batch(batch_id: str) -> dict:
    """Re-fetch results into batch_results.json using stored custom_ids. No re-submit."""
    history = read_history()
    entry = _find_entry(history, batch_id)
    if entry is None:
        raise ValueError(f"Unknown batch id (not in local history): {batch_id}")
    custom_ids = dict(entry.get("custom_ids") or {})
    if not custom_ids:
        raise ValueError(f"Batch {batch_id} has no stored custom_ids - cannot redownload")

    client = _get_anthropic_client()
    b = client.messages.batches.retrieve(batch_id)
    api_status = getattr(b, "processing_status", "") or ""
    if api_status != "ended":
        raise ValueError(f"Batch {batch_id} is not ended (status={api_status})")

    results, errored, usage = download_batch_results(batch_id, custom_ids, client=client)
    model = entry.get("model") or ""
    cost = _price_usage(usage, model) if model else None

    import util.translation as T

    with T.BATCH_LOCK:
        with _batch_file_lock():
            merged = _read_batch_file(BATCH_RESULTS_FILE)
            merged.update(results)
            _write_batch_file(BATCH_RESULTS_FILE, merged)
            # Activate fetched state without re-submit; keep custom_ids in history.
            _write_batch_file(
                BATCH_STATE_FILE,
                {"status": "fetched", "batch_ids": [batch_id], "batches": []},
            )
            # Queue is no longer needed for consume.
            try:
                if BATCH_QUEUE_FILE.exists():
                    BATCH_QUEUE_FILE.unlink()
            except Exception:
                pass
        T._batch_results = None

    record_fetch([batch_id], succeeded=len(results), errored=len(errored), usage=usage, actual_cost=cost)
    return {
        "id": batch_id,
        "succeeded": len(results),
        "errored": len(errored),
        "errors": errored[:20],
        "usage": usage,
        "actual_cost": cost,
    }


def activate_for_resume(batch_id: str) -> str:
    """Ensure active files match a history entry for Translation-tab resume.

    Returns the batchRunState string to pass as batch_resume_state:
    'submitted' | 'fetched'.
    """
    history = read_history()
    entry = _find_entry(history, batch_id)
    if entry is None:
        raise ValueError(f"Unknown batch id: {batch_id}")

    status = entry.get("status")
    custom_ids = dict(entry.get("custom_ids") or {})

    if status in (STATUS_FETCHED, STATUS_ENDED, STATUS_CONSUMED):
        # Prefer local results; redownload if missing.
        with _batch_file_lock():
            results = _read_batch_file(BATCH_RESULTS_FILE)
        if not results:
            if status == STATUS_CONSUMED:
                raise ValueError(
                    f"Batch {batch_id} was already consumed and local results are gone. "
                    "Use Redownload first."
                )
            redownload_batch(batch_id)
        else:
            with BATCH_LOCK:
                with _batch_file_lock():
                    _write_batch_file(
                        BATCH_STATE_FILE,
                        {"status": "fetched", "batch_ids": [batch_id], "batches": []},
                    )
        return "fetched"

    if status in (STATUS_SUBMITTED, STATUS_CANCELING, STATUS_ENDED):
        # Restore active state so poll/fetch can continue.
        with BATCH_LOCK:
            with _batch_file_lock():
                state = _read_batch_file(BATCH_STATE_FILE)
                batches = list(state.get("batches") or [])
                existing = {b.get("id") for b in batches}
                if batch_id not in existing:
                    batches.append({"id": batch_id, "custom_ids": custom_ids})
                state = {
                    "batches": batches,
                    "submitted_at": state.get("submitted_at") or entry.get("created_at"),
                    "model": entry.get("model") or state.get("model") or "",
                    "file_set": entry.get("file_set") or state.get("file_set") or [],
                    "cost_estimate": entry.get("cost_estimate") or state.get("cost_estimate"),
                }
                _write_batch_file(BATCH_STATE_FILE, state)
        if status == STATUS_ENDED:
            # Already ended on Anthropic - fetch path via resume submitted → poll sees ended.
            return "submitted"
        return "submitted"

    if status == STATUS_CANCELED:
        raise ValueError(f"Batch {batch_id} was canceled - nothing to resume")

    raise ValueError(f"Batch {batch_id} cannot be resumed from status={status}")


def missing_result_count() -> tuple[int, int]:
    """Return (present, expected) result counts for the active fetched run.

    expected is summed from history request_count for active fetched batch ids.
    """
    with _batch_file_lock():
        results = _read_batch_file(BATCH_RESULTS_FILE)
        state = _read_batch_file(BATCH_STATE_FILE)
        history = _read_history_unlocked()

    present = len(results)
    ids = list(state.get("batch_ids") or [])
    if not ids:
        ids = [b.get("id") for b in (state.get("batches") or []) if b.get("id")]
    expected = 0
    for bid in ids:
        entry = _find_entry(history, bid)
        if entry:
            expected += int(entry.get("request_count") or len(entry.get("custom_ids") or {}))
    if not expected:
        expected = present
    return present, expected


def active_fetched_batch_ids() -> list[str]:
    """Batch ids associated with the current fetched active run."""
    with _batch_file_lock():
        state = _read_batch_file(BATCH_STATE_FILE)
    ids = list(state.get("batch_ids") or [])
    if ids:
        return ids
    return [b.get("id") for b in (state.get("batches") or []) if b.get("id")]


def on_clear_active_files(*, had_results: bool, fetched_ids: Optional[list] = None) -> None:
    """Called from clearBatchFiles - mark fetched ids consumed, never wipe history."""
    if not had_results and not fetched_ids:
        return
    ids = list(fetched_ids or [])
    if not ids and had_results:
        # Fall back: mark any currently-fetched history rows as consumed.
        history = read_history()
        ids = [e["id"] for e in history.get("batches", []) if e.get("status") == STATUS_FETCHED]
    if ids:
        mark_batches_consumed(ids)
