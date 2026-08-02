"""User-facing formatting for provider API failures."""

from __future__ import annotations

import re


def concise_api_error(exc: BaseException, *, limit: int = 500) -> str:
    """Return a bounded plain-text API error without rendering HTML pages."""
    response = getattr(exc, "response", None)
    status = getattr(exc, "status_code", None) or getattr(
        response, "status_code", None
    )
    raw = str(exc).strip()
    lowered = raw.casefold()
    is_html = any(
        marker in lowered
        for marker in ("<!doctype html", "<html", "</html>", "<body")
    )
    if is_html:
        status_text = f" ({status})" if status else ""
        if status == 404:
            return (
                "API endpoint not found (404). The provider may not support "
                "the requested operation."
            )
        return f"The API returned an HTML error page{status_text}."
    message = re.sub(r"\s+", " ", raw) or type(exc).__name__
    return message[:max(1, int(limit))]
