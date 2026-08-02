#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Durable provider Batch history and spend-safe management operations.

Active run files (queue / state / results) still live in util.translation.
This module keeps an append-only index so batch ids and custom_id maps survive
fetch and clear, enabling cancel / usage / redownload / resume without
re-submitting (and re-billing) work.
"""

from __future__ import annotations

import copy
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from util.translation import (
    BATCH_LOCK,
    BATCH_QUEUE_FILE,
    BATCH_RESULTS_FILE,
    BATCH_STATE_FILE,
    BatchFileCorruptionError,
    _batch_file_lock,
    _get_anthropic_client,
    _read_batch_file,
    _write_batch_file,
    getPricingConfig,
)
from util.batch_providers import (
    _google_client as get_google_client,
    cancel_batch as provider_cancel_batch,
    download_results as provider_download_results,
    get_client as get_provider_client,
    retrieve_batch as provider_retrieve_batch,
)
from util.provider_costs import cache_write_multiplier

BATCH_HISTORY_FILE = Path("log/batch_history.json")

# Local lifecycle statuses normalized across provider-specific API statuses.
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
    data = _read_batch_file(BATCH_HISTORY_FILE, strict=True)
    if not data:
        return _empty_history()
    if not isinstance(data.get("batches"), list):
        raise BatchFileCorruptionError(
            f"Batch history is corrupt: {BATCH_HISTORY_FILE} "
            "(missing batches list). The operation was blocked to preserve "
            "existing recovery data."
        )
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


def _client_for_entry(entry: dict):
    """Use an evaluation row's saved credential without persisting its secret."""
    provider = entry.get("provider") or "anthropic"
    key_name = str(entry.get("key_name") or "")
    if key_name:
        from util import api_keys as api_key_vault

        secret = api_key_vault.get_secret(key_name) or ""
        # The provider job belongs to the endpoint used at submission time.
        # Fall back to the credential's current endpoint only for legacy rows.
        endpoint = (
            str(entry.get("endpoint") or "").strip()
            or api_key_vault.get_endpoint(key_name)
            or ""
        )
        if not secret and not api_key_vault.is_keyless(key_name):
            raise ValueError(f"Saved API key {key_name!r} is unavailable")
        return get_provider_client(
            provider, api_key=secret or "not-needed", api_url=endpoint or None
        )
    return _get_anthropic_client() if provider == "anthropic" else get_provider_client(provider)


def _google_client_for_entry(entry: dict):
    """Resolve the native Gemini Files client from the job's saved key."""
    key_name = str(entry.get("key_name") or "")
    if key_name:
        from util import api_keys as api_key_vault

        secret = api_key_vault.get_secret(key_name) or ""
        if not secret:
            raise ValueError(f"Saved API key {key_name!r} is unavailable")
        return get_google_client(api_key=secret)
    return get_google_client()


def active_key_name_for_environment() -> str:
    """Return the active vault name only when it matches the submitted route."""
    try:
        from util import api_keys as api_key_vault

        name = api_key_vault.get_active_name()
        if not name:
            return ""
        secret = api_key_vault.get_secret(name) or ""
        endpoint = (api_key_vault.get_endpoint(name) or "").rstrip("/")
        env_secret = os.getenv("key", "")
        env_endpoint = os.getenv("api", "").rstrip("/")
        if api_key_vault.is_keyless(name):
            return name if endpoint and endpoint == env_endpoint else ""
        if secret != env_secret:
            return ""
        if endpoint and endpoint != env_endpoint:
            return ""
        return name
    except Exception:
        return ""


def entry_for_batch(batch_id: str) -> Optional[dict]:
    """Return one durable history entry without exposing its stored secret."""
    return _find_entry(read_history(), batch_id)


def client_for_batch(
    batch_id: str,
    provider: str = "anthropic",
    key_name: str = "",
    endpoint: str = "",
):
    """Resolve a batch's submitted credential, falling back for legacy rows."""
    entry = entry_for_batch(batch_id)
    if entry is not None:
        resolved = dict(entry)
        resolved["provider"] = provider or resolved.get("provider")
        if key_name:
            resolved["key_name"] = key_name
        if endpoint and not resolved.get("endpoint"):
            resolved["endpoint"] = endpoint
        return _client_for_entry(resolved)
    if key_name:
        return _client_for_entry({
            "provider": provider,
            "key_name": key_name,
            "endpoint": endpoint,
        })
    return _get_anthropic_client() if provider == "anthropic" else get_provider_client(provider)


def google_client_for_batch(batch_id: str, key_name: str = ""):
    """Resolve Gemini's native Files client using the submitted credential."""
    if key_name:
        return _google_client_for_entry({"provider": "gemini", "key_name": key_name})
    entry = entry_for_batch(batch_id)
    return _google_client_for_entry(entry or {})


def key_name_for_batch(batch_id: str) -> str:
    entry = entry_for_batch(batch_id)
    return str((entry or {}).get("key_name") or "")


_ESTIMATE_SPLIT_FIELDS = frozenset({
    "cache_write_tokens",
    "cache_read_tokens",
    "dynamic_tokens",
    "input_tokens",
    "output_tokens",
    "batch_cached_cost",
    "batch_nocache_cost",
    "live_cost",
})


def _split_cost_estimate(
    cost_estimate: Optional[dict], request_count: int
) -> Optional[dict]:
    """Allocate an aggregate estimate across provider splits without duplication."""
    if not cost_estimate:
        return None
    estimate = copy.deepcopy(cost_estimate)
    total_requests = int(estimate.get("requests", 0) or 0)
    if total_requests <= 0 or request_count >= total_requests:
        return estimate
    fraction = request_count / total_requests
    estimate["requests"] = request_count
    for field in _ESTIMATE_SPLIT_FIELDS:
        value = estimate.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            estimate[field] = value * fraction
    return estimate


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
                    "provider": "anthropic",
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
    provider: str = "anthropic",
    file_set: Optional[list] = None,
    cost_estimate: Optional[dict] = None,
    key_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> None:
    """Record newly submitted provider batches into durable history."""
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
            provider=info.get("provider") or provider,
            endpoint=info.get("endpoint") or endpoint or "",
            cache_key_version=info.get("cache_key_version"),
            key_name=(
                key_name
                if key_name is not None
                else active_key_name_for_environment()
            ),
            request_count=len(custom_ids),
            file_set=file_set,
            cost_estimate=_split_cost_estimate(cost_estimate, len(custom_ids)),
            custom_ids=custom_ids,
            run_id=info.get("run_id"),
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
    local = STATUS_CANCELED if api_status in ("ended", "cancelled") else STATUS_CANCELING
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
    """Retrieve live provider status and update the history row."""
    history = read_history()
    existing = _find_entry(history, batch_id) or {}
    provider = existing.get("provider") or "anthropic"
    client = _client_for_entry(existing)
    normalized = provider_retrieve_batch(provider, batch_id, client=client)
    api_status = normalized["api_status"]
    counts_dict = normalized["counts"]

    entry = None
    with _batch_file_lock():
        history = _read_history_unlocked()
        entry = _find_entry(history, batch_id)
        prev_status = (entry or {}).get("status")

    # Map API status onto local lifecycle without clobbering fetched/consumed.
    local_status = None
    if prev_status in (STATUS_FETCHED, STATUS_CONSUMED):
        local_status = prev_status
    elif api_status in ("in_progress", "validating", "finalizing"):
        local_status = STATUS_SUBMITTED
    elif api_status in ("canceling", "cancelling"):
        local_status = STATUS_CANCELING
    elif normalized["ended"]:
        if api_status == "cancelled" or (
            counts_dict and (counts_dict.get("canceled") or 0) > 0
            and (counts_dict.get("succeeded") or 0) == 0
        ):
            local_status = STATUS_CANCELED
        elif api_status == "failed":
            local_status = STATUS_ERROR
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
    results = []
    canceled_active = []
    history = read_history()
    for bid in batch_ids:
        try:
            entry = _find_entry(history, bid) or {}
            provider = entry.get("provider") or "anthropic"
            client = _client_for_entry(entry)
            status_info = provider_retrieve_batch(provider, bid, client=client)
            api_status = status_info["api_status"]
            if api_status not in CANCELABLE_API:
                results.append({"id": bid, "ok": False, "error": f"not cancelable ({api_status})"})
                upsert_history_entry(bid, notes=f"cancel skipped: {api_status}", api_status=api_status)
                continue
            canceled = provider_cancel_batch(provider, bid, client=client)
            new_status = canceled["api_status"]
            mark_batches_canceled([bid], api_status=new_status)
            canceled_active.append(bid)
            results.append({"id": bid, "ok": True, "api_status": new_status})
        except Exception as exc:
            results.append({"id": bid, "ok": False, "error": str(exc)})
            # A local retrieval/network failure says nothing authoritative
            # about the provider job. Preserve its active status so normal
            # refresh and a later cancel attempt can recover it.
            upsert_history_entry(bid, notes=f"cancel failed: {exc}")

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


def _price_usage(usage: dict, model: str, provider: str = "anthropic") -> float:
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
    write_multiplier = cache_write_multiplier(provider, model)
    raw = (
        cr * br * 0.10
        + cw * br * write_multiplier
        + inp * br
        + (out + thinking) * orr
    )
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
    """Sum real billed tokens from provider results and persist onto history."""
    history = read_history()
    entry = _find_entry(history, batch_id)
    if entry is None:
        raise ValueError(f"Unknown batch id (not in local history): {batch_id}")

    provider = entry.get("provider") or "anthropic"
    client = _client_for_entry(entry)
    status_info = provider_retrieve_batch(provider, batch_id, client=client)
    api_status = status_info["api_status"]
    if not status_info["ended"]:
        raise ValueError(f"Batch {batch_id} is not ended (status={api_status})")

    custom_ids = dict(entry.get("custom_ids") or {})
    google_client = (
        _google_client_for_entry(entry) if provider == "gemini" else None
    )
    _results, errors, usage = download_batch_results(
        batch_id, custom_ids, client=client, provider=provider,
        google_client=google_client,
    )
    succeeded, errored = len(_results), len(errors)
    use_model = model or entry.get("model") or ""
    cost = _price_usage(usage, use_model, provider) if use_model else None
    updated = upsert_history_entry(
        batch_id,
        usage=usage,
        actual_cost=cost,
        api_status=api_status,
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
    provider="anthropic",
    google_client=None,
) -> tuple[dict, list, dict]:
    """Download one ended batch into a cache-key -> result map.

    Returns (results, errored_list, usage_totals).
    """
    if provider != "anthropic":
        return provider_download_results(
            provider, batch_id, custom_ids, client=client,
            google_client=google_client,
        )
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


def _translation_group_entries(history: dict, entry: dict) -> list[dict]:
    """Return every provider split belonging to one translation run.

    Evaluation rows also have run ids, but their recovery is owned by the
    evaluation workflow. Legacy translation rows have no grouping metadata and
    therefore remain safely recoverable one batch at a time.
    """
    run_id = str(entry.get("run_id") or "")
    if not run_id or entry.get("workflow") == "evaluation":
        return [entry]
    return [
        row for row in history.get("batches", [])
        if row.get("workflow") != "evaluation"
        and str(row.get("run_id") or "") == run_id
    ] or [entry]


def _entry_batch_info(entry: dict) -> dict:
    return {
        "id": entry.get("id"),
        "custom_ids": dict(entry.get("custom_ids") or {}),
        "provider": entry.get("provider") or "anthropic",
        "key_name": str(entry.get("key_name") or ""),
        "endpoint": str(entry.get("endpoint") or ""),
        "cache_key_version": int(entry.get("cache_key_version", 1) or 1),
        "run_id": entry.get("run_id"),
    }


def _assert_recovery_target_unlocked(entries: list[dict]) -> None:
    """Block a history action from replacing an unrelated active recovery run."""
    state = _read_batch_file(BATCH_STATE_FILE, strict=True)
    queue = _read_batch_file(BATCH_QUEUE_FILE, strict=True)
    _read_batch_file(BATCH_RESULTS_FILE, strict=True)
    if not state and not queue:
        return

    target_ids = {str(row.get("id")) for row in entries if row.get("id")}
    target_run_ids = {str(row.get("run_id")) for row in entries if row.get("run_id")}
    target_run_id = next(iter(target_run_ids), "") if len(target_run_ids) == 1 else ""
    active_run_id = str(state.get("run_id") or "")
    active_ids = {
        str(batch_id) for batch_id in (state.get("batch_ids") or []) if batch_id
    }
    active_ids.update(
        str(batch.get("id"))
        for batch in (state.get("batches") or [])
        if batch.get("id")
    )

    same_run = bool(
        target_run_id
        and active_run_id == target_run_id
        and (not active_ids or active_ids.issubset(target_ids))
    )
    legacy_owned = bool(active_ids and active_ids.issubset(target_ids))
    if same_run or legacy_owned:
        return
    raise ValueError(
        "Another translation batch run is active. Finish or clear that run "
        "before activating this Batch History entry."
    )


def redownload_batch(batch_id: str) -> dict:
    """Re-fetch one complete translation run from durable history. No re-submit."""
    history = read_history()
    entry = _find_entry(history, batch_id)
    if entry is None:
        raise ValueError(f"Unknown batch id (not in local history): {batch_id}")
    entries = _translation_group_entries(history, entry)
    for row in entries:
        if not dict(row.get("custom_ids") or {}):
            raise ValueError(
                f"Batch {row.get('id')} has no stored custom_ids - cannot redownload"
            )

    # Validate ownership before any provider work, then validate it again in
    # the write transaction in case another process activated a run meanwhile.
    with BATCH_LOCK:
        with _batch_file_lock():
            _assert_recovery_target_unlocked(entries)

    resolved = []
    for row in entries:
        row_id = str(row.get("id") or "")
        provider = row.get("provider") or "anthropic"
        client = _client_for_entry(row)
        status_info = provider_retrieve_batch(provider, row_id, client=client)
        if not status_info["ended"]:
            raise ValueError(
                f"Batch {row_id} is not ended (status={status_info['api_status']})"
            )
        google_client = (
            _google_client_for_entry(row) if provider == "gemini" else None
        )
        resolved.append((row, provider, client, google_client))

    results, errored = {}, []
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }
    fetched_parts = []
    for row, provider, client, google_client in resolved:
        row_id = str(row.get("id") or "")
        part, row_errors, row_usage = download_batch_results(
            row_id,
            dict(row.get("custom_ids") or {}),
            client=client,
            provider=provider,
            google_client=google_client,
        )
        results.update(part)
        errored.extend(row_errors)
        for key, value in row_usage.items():
            usage[key] = usage.get(key, 0) + (value or 0)
        row_model = row.get("model") or entry.get("model") or ""
        row_cost = _price_usage(row_usage, row_model, provider) if row_model else None
        fetched_parts.append((row_id, part, row_errors, row_usage, row_cost))

    model = entry.get("model") or ""
    provider = entry.get("provider") or "anthropic"
    cost = _price_usage(usage, model, provider) if model else None
    batch_ids = [str(row.get("id")) for row in entries if row.get("id")]
    cache_key_version = min(
        int(row.get("cache_key_version", 1) or 1) for row in entries
    )

    import util.translation as T

    with T.BATCH_LOCK:
        with _batch_file_lock():
            _assert_recovery_target_unlocked(entries)
            _write_batch_file(BATCH_RESULTS_FILE, results)
            _write_batch_file(
                BATCH_STATE_FILE,
                {
                    "status": "fetched", "batch_ids": batch_ids, "batches": [],
                    "run_id": entry.get("run_id"),
                    "provider": provider, "model": model,
                    "endpoint": entry.get("endpoint") or "",
                    "cache_key_version": cache_key_version,
                    "file_set": entry.get("file_set") or [],
                    "result_keys": sorted(results),
                },
            )
            if BATCH_QUEUE_FILE.exists():
                BATCH_QUEUE_FILE.unlink()
        T._batch_results = None

    for row_id, part, row_errors, row_usage, row_cost in fetched_parts:
        record_fetch(
            [row_id], succeeded=len(part), errored=len(row_errors),
            usage=row_usage, actual_cost=row_cost,
        )
    return {
        "id": batch_id,
        "batch_ids": batch_ids,
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
    entries = _translation_group_entries(history, entry)
    target_ids = {str(row.get("id")) for row in entries if row.get("id")}

    if status in (STATUS_FETCHED, STATUS_ENDED, STATUS_CONSUMED):
        # Reuse results only when the active state explicitly proves ownership.
        # Older state files have no result_keys marker and are intentionally
        # redownloaded: cache keys are model-independent, so a merely non-empty
        # result file cannot identify the provider batch that produced it.
        with _batch_file_lock():
            results = _read_batch_file(BATCH_RESULTS_FILE, strict=True)
            active_state = _read_batch_file(BATCH_STATE_FILE, strict=True)
        active_ids = set(active_state.get("batch_ids") or [])
        recorded_keys = active_state.get("result_keys")
        owns_results = (
            active_state.get("status") == "fetched"
            and active_ids == target_ids
            and isinstance(recorded_keys, list)
            and set(str(key) for key in recorded_keys) == set(results)
        )
        if not owns_results:
            if status == STATUS_CONSUMED:
                raise ValueError(
                    f"Batch {batch_id} was already consumed and its owned local results are gone. "
                    "Use Redownload first."
                )
            redownload_batch(batch_id)
        return "fetched"

    if status in (STATUS_SUBMITTED, STATUS_CANCELING, STATUS_ENDED):
        # Restore exactly this run so unrelated state can never be mixed into it.
        with BATCH_LOCK:
            with _batch_file_lock():
                _assert_recovery_target_unlocked(entries)
                previous = _read_batch_file(BATCH_STATE_FILE)
                batches = [_entry_batch_info(row) for row in entries]
                state = {
                    "batches": batches,
                    "status": "submitted",
                    "run_id": entry.get("run_id"),
                    "submitted_at": previous.get("submitted_at") or entry.get("created_at"),
                    "model": entry.get("model") or "",
                    "provider": entry.get("provider") or "anthropic",
                    "endpoint": entry.get("endpoint") or "",
                    "cache_key_version": min(
                        int(row.get("cache_key_version", 1) or 1)
                        for row in entries
                    ),
                    "file_set": entry.get("file_set") or [],
                    "cost_estimate": entry.get("cost_estimate"),
                }
                _write_batch_file(BATCH_STATE_FILE, state)
        if status == STATUS_ENDED:
            # Already ended at the provider; poll will immediately proceed to fetch.
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
