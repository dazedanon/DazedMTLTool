"""Provider adapters for asynchronous translation batches.

The translation pipeline consumes one small, provider-neutral shape.  Native
Anthropic uses Message Batches; OpenAI and Gemini use OpenAI-compatible JSONL
Chat Completions batches.  Gemini intentionally uses the Google Files API for
upload/download because those two operations are not exposed by Google's
OpenAI compatibility layer.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

import anthropic
import openai


PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_OPENAI = "openai"
PROVIDER_GEMINI = "gemini"

TERMINAL_OPENAI_STATUSES = frozenset({
    "completed", "failed", "expired", "cancelled",
})


def detect_batch_provider(model: str = "", api_url: str | None = None,
                          api_provider: str | None = None) -> str | None:
    """Return the supported batch backend for the current route."""
    model_l = str(model or "").lower()
    url = (os.getenv("api", "") if api_url is None else str(api_url or "")).strip().lower()
    provider = (os.getenv("API_PROVIDER", "openai") if api_provider is None
                else str(api_provider or "openai")).strip().lower()

    is_claude = any(part in model_l for part in ("claude", "sonnet", "haiku", "opus"))
    if is_claude and (not url or "anthropic.com" in url):
        return PROVIDER_ANTHROPIC
    if provider == "gemini" or "generativelanguage.googleapis.com" in url:
        return PROVIDER_GEMINI
    if provider == "openai" and (not url or "api.openai.com" in url):
        return PROVIDER_OPENAI
    return None


def batch_provider_label(provider: str | None) -> str:
    return {
        PROVIDER_ANTHROPIC: "Anthropic",
        PROVIDER_OPENAI: "OpenAI",
        PROVIDER_GEMINI: "Google Gemini",
    }.get(provider, str(provider or "Provider"))


def batch_limits(provider: str) -> tuple[int, int]:
    """Return conservative (request count, encoded bytes) limits."""
    if provider == PROVIDER_OPENAI:
        return 50_000, 200 * 1024 * 1024
    if provider == PROVIDER_GEMINI:
        # Gemini JSONL input files may be 2 GB. Stay below that and keep the
        # existing request cap as a conservative client-side split point.
        return 100_000, 1900 * 1024 * 1024
    return 100_000, 200 * 1024 * 1024


def _api_key() -> str:
    key = os.getenv("key", "").strip()
    if not key:
        raise RuntimeError("Batch translation requires the 'key' env var (see .env).")
    return key


def get_client(provider: str):
    """Create the SDK client needed for status/create/cancel operations."""
    key = _api_key()
    if provider == PROVIDER_ANTHROPIC:
        return anthropic.Anthropic(api_key=key)
    if provider == PROVIDER_GEMINI:
        return openai.OpenAI(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    if provider == PROVIDER_OPENAI:
        return openai.OpenAI(api_key=key)
    raise ValueError(f"Unsupported batch provider: {provider}")


def _google_client():
    try:
        from google import genai
    except ImportError as exc:
        raise RuntimeError(
            "Gemini batching requires google-genai. Install project requirements first."
        ) from exc
    return genai.Client(api_key=_api_key())


def _write_jsonl(requests: Iterable[dict]) -> Path:
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".jsonl", delete=False
    )
    path = Path(handle.name)
    try:
        with handle:
            for request in requests:
                handle.write(json.dumps(request, ensure_ascii=False, separators=(",", ":")))
                handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return path


def _openai_batch_body(provider: str, params: dict) -> dict:
    """Materialize one OpenAI-format JSONL body for a provider batch.

    Gemini's live OpenAI compatibility endpoint accepts strict JSON Schema,
    but its batch-file validator currently rejects nested schema ``type``
    fields.  Match the live client's existing compatibility fallback by using
    JSON-object mode for Gemini batches; the consume pass still performs the
    normal line-count, control-code, and untranslated-content validation.
    """
    body = dict(params)
    extra_body = body.pop("extra_body", None)
    if isinstance(extra_body, dict):
        body.update(extra_body)

    if provider == PROVIDER_GEMINI:
        model = str(body.get("model") or "")
        if model.startswith("models/"):
            body["model"] = model.removeprefix("models/")
        response_format = body.get("response_format") or {}
        if response_format.get("type") == "json_schema":
            body["response_format"] = {"type": "json_object"}
    return body


def submit_batch(provider: str, requests: list[dict], *, client=None) -> dict:
    """Submit normalized ``{custom_id, params}`` requests and return metadata."""
    client = client or get_client(provider)
    if provider == PROVIDER_ANTHROPIC:
        batch = client.messages.batches.create(requests=[
            {"custom_id": item["custom_id"], "params": item["params"]}
            for item in requests
        ])
        return {"id": batch.id}

    rows = []
    for item in requests:
        # ``extra_body`` is an OpenAI Python SDK transport option, not an API
        # field. A raw JSONL row must contain those vendor fields at top level,
        # matching the body the SDK sends for a live Gemini request.
        body = _openai_batch_body(provider, item["params"])
        rows.append({
            "custom_id": item["custom_id"],
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        })
    path = _write_jsonl(rows)
    try:
        if provider == PROVIDER_GEMINI:
            google_client = _google_client()
            try:
                from google.genai import types
                config = types.UploadFileConfig(
                    display_name=path.name, mime_type="jsonl"
                )
            except (ImportError, AttributeError):
                config = {"display_name": path.name, "mime_type": "jsonl"}
            uploaded = google_client.files.upload(file=str(path), config=config)
            input_file_id = uploaded.name
        else:
            with open(path, "rb") as stream:
                uploaded = client.files.create(file=stream, purpose="batch")
            input_file_id = uploaded.id
        batch = client.batches.create(
            input_file_id=input_file_id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        return {"id": batch.id, "input_file_id": input_file_id}
    finally:
        path.unlink(missing_ok=True)


def _request_counts(batch: Any) -> dict:
    counts = getattr(batch, "request_counts", None)
    if counts is None:
        return {k: 0 for k in ("processing", "succeeded", "errored", "canceled", "expired")}
    if hasattr(counts, "completed") or hasattr(counts, "failed"):
        total = int(getattr(counts, "total", 0) or 0)
        completed = int(getattr(counts, "completed", 0) or 0)
        failed = int(getattr(counts, "failed", 0) or 0)
        return {
            "processing": max(0, total - completed - failed),
            "succeeded": completed,
            "errored": failed,
            "canceled": 0,
            "expired": 0,
        }
    return {
        key: int(getattr(counts, key, 0) or 0)
        for key in ("processing", "succeeded", "errored", "canceled", "expired")
    }


def retrieve_batch(provider: str, batch_id: str, *, client=None) -> dict:
    client = client or get_client(provider)
    if provider == PROVIDER_ANTHROPIC:
        batch = client.messages.batches.retrieve(batch_id)
        raw_status = getattr(batch, "processing_status", "") or ""
        ended = raw_status == "ended"
    else:
        batch = client.batches.retrieve(batch_id)
        raw_status = getattr(batch, "status", "") or ""
        ended = raw_status in TERMINAL_OPENAI_STATUSES
    counts = _request_counts(batch)
    if raw_status == "expired" and not counts["expired"]:
        counts["expired"] = counts["processing"]
        counts["processing"] = 0
    elif raw_status == "cancelled" and not counts["canceled"]:
        counts["canceled"] = counts["processing"]
        counts["processing"] = 0
    return {
        "id": batch_id,
        "api_status": raw_status,
        "ended": ended,
        "counts": counts,
        "raw": batch,
    }


def cancel_batch(provider: str, batch_id: str, *, client=None) -> dict:
    client = client or get_client(provider)
    if provider == PROVIDER_ANTHROPIC:
        batch = client.messages.batches.cancel(batch_id)
        status = getattr(batch, "processing_status", "canceling") or "canceling"
    else:
        batch = client.batches.cancel(batch_id)
        status = getattr(batch, "status", "cancelling") or "cancelling"
    return {"id": batch_id, "api_status": status, "raw": batch}


def _empty_usage() -> dict:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": 0,
    }


def _openai_result(
    row: dict, provider: str = PROVIDER_OPENAI
) -> tuple[dict | None, str | None]:
    response = row.get("response") or {}
    body = response.get("body") or {}
    if row.get("error") or int(response.get("status_code") or 0) >= 400:
        detail = row.get("error") or body.get("error") or response
        return None, str(detail)[:500]
    choices = body.get("choices") or []
    if not choices:
        return None, "successful response contained no choices"
    message = choices[0].get("message") or {}
    text = message.get("content") or ""
    if isinstance(text, list):
        text = "".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in text
        )
    # Gemini promises OpenAI-format batch output, but compatibility responses
    # have also used camelCase usage fields. Accept both, plus native Google
    # usageMetadata names, so a successful run cannot silently become $0.00.
    usage = (
        body.get("usage")
        or body.get("usageMetadata")
        or body.get("usage_metadata")
        or {}
    )
    prompt = int(
        usage.get("prompt_tokens")
        or usage.get("promptTokens")
        or usage.get("promptTokenCount")
        or 0
    )
    completion = int(
        usage.get("completion_tokens")
        or usage.get("completionTokens")
        or usage.get("candidatesTokenCount")
        or 0
    )
    total = int(
        usage.get("total_tokens")
        or usage.get("totalTokens")
        or usage.get("totalTokenCount")
        or 0
    )
    prompt_details = usage.get("prompt_tokens_details") or usage.get("promptTokensDetails") or {}
    cached = int(
        prompt_details.get("cached_tokens")
        or prompt_details.get("cachedTokens")
        or usage.get("cachedContentTokenCount")
        or 0
    )
    thinking = 0
    if provider == PROVIDER_GEMINI:
        thinking = int(usage.get("thoughtsTokenCount") or 0)
        if not thinking and total:
            # Gemini's OpenAI compatibility response may only expose the
            # inclusive total. The remainder is billed thinking output.
            thinking = max(0, total - prompt - completion)
    result = {
        "text": text,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_read_input_tokens": cached,
        "cache_creation_input_tokens": 0,
        "thinking_tokens": thinking,
    }
    return result, None


def _download_file_text(provider: str, file_id: str, *, client=None) -> str:
    if not file_id:
        return ""
    if provider == PROVIDER_GEMINI:
        # Keep the owning Client alive until the download finishes.  ``Files``
        # does not retain that owner, and google-genai's Client.__del__ closes
        # its HTTP transport.  Calling ``_google_client().files.download(...)``
        # can therefore collect the temporary Client before ``download`` sends
        # the request, producing: "Cannot send a request, as the client has
        # been closed."
        google_client = _google_client()
        data = google_client.files.download(file=file_id)
        return data.decode("utf-8") if isinstance(data, bytes) else str(data)
    content = client.files.content(file_id)
    text = getattr(content, "text", None)
    if text is not None:
        return text
    data = getattr(content, "content", content)
    return data.decode("utf-8") if isinstance(data, bytes) else str(data)


def download_results(provider: str, batch_id: str, custom_ids: dict,
                     *, client=None) -> tuple[dict, list, dict]:
    """Return ``(cache-key results, errors, aggregate usage)``."""
    client = client or get_client(provider)
    if provider == PROVIDER_ANTHROPIC:
        return _download_anthropic(client, batch_id, custom_ids)

    batch = client.batches.retrieve(batch_id)
    output_id = getattr(batch, "output_file_id", None)
    error_id = getattr(batch, "error_file_id", None)
    results, errors, totals = {}, [], _empty_usage()
    for line in _download_file_text(provider, output_id, client=client).splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        cid = row.get("custom_id")
        key = custom_ids.get(cid)
        if key is None:
            continue
        result, error = _openai_result(row, provider)
        if error:
            errors.append((cid, error))
            continue
        results[key] = result
        totals["input_tokens"] += max(
            0, result["prompt_tokens"] - result["cache_read_input_tokens"]
        )
        totals["output_tokens"] += result["completion_tokens"]
        totals["cache_read_input_tokens"] += result["cache_read_input_tokens"]
        totals["thinking_tokens"] += result.get("thinking_tokens", 0)
    for line in _download_file_text(provider, error_id, client=client).splitlines():
        if line.strip():
            row = json.loads(line)
            errors.append((row.get("custom_id") or "unknown", str(row.get("error") or row)[:500]))
    return results, errors, totals


def _download_anthropic(client, batch_id: str, custom_ids: dict):
    results, errors, totals = {}, [], _empty_usage()
    for row in client.messages.batches.results(batch_id):
        key = custom_ids.get(row.custom_id)
        if key is None:
            continue
        result = row.result
        if result.type != "succeeded":
            err = getattr(result, "error", None)
            errors.append((row.custom_id, f"{result.type}: {str(err or '')[:400]}"))
            continue
        message = result.message
        text = "".join(getattr(block, "text", "") or "" for block in message.content)
        usage = message.usage
        inp = int(getattr(usage, "input_tokens", 0) or 0)
        out = int(getattr(usage, "output_tokens", 0) or 0)
        cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        thinking = int(getattr(usage, "thinking_tokens", 0) or 0)
        results[key] = {
            "text": text,
            "prompt_tokens": inp + cr + cw,
            "completion_tokens": out,
            "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": cw,
            **({"thinking_tokens": thinking} if thinking else {}),
        }
        totals["input_tokens"] += inp
        totals["output_tokens"] += out
        totals["cache_read_input_tokens"] += cr
        totals["cache_creation_input_tokens"] += cw
        totals["thinking_tokens"] += thinking
    return results, errors, totals
