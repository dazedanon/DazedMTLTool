"""Conservative, durable reservation before every paid prototype request."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

MAX_BUDGET_MICRO_USD = 5_000_000
REQUEST_RESERVE_MICRO_USD = 20_000
MAX_PROMPT_BYTES = 100_000
MAX_OUTPUT_TOKENS = 4096
MODEL = "gpt-6-luna"


class BudgetLedger:
    """Keep reservations even after timeouts/crashes; never silently refund spend.

    At the verified 2026-09-29 standard Luna rates, even charging every input
    byte as a token at the cache-write rate ($0.125/M), plus 2,048 tokens of
    overhead and 4,096 output tokens ($0.50/M), is below $0.015. Reserve $0.02
    per request. Tools, long-context requests, automatic retries and priority
    processing are disabled. This is a conservative local limit, not billing.
    """

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS requests (id INTEGER PRIMARY KEY, job TEXT, reserved INTEGER, input_tokens INTEGER, output_tokens INTEGER)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def reserve(self, job_id: str, prompt: str) -> int:
        if len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise ValueError("This request exceeds the API test broker's input limit; select shorter text.")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            used = db.execute("SELECT COALESCE(SUM(reserved), 0) FROM requests").fetchone()[0]
            if used + REQUEST_RESERVE_MICRO_USD > MAX_BUDGET_MICRO_USD:
                raise ValueError("The US$5 development API budget is exhausted. No request was sent.")
            cursor = db.execute("INSERT INTO requests(job, reserved) VALUES (?, ?)", (job_id, REQUEST_RESERVE_MICRO_USD))
            return cursor.lastrowid

    def record_usage(self, request_id: int, input_tokens: int, output_tokens: int):
        with self.connect() as db:
            db.execute("UPDATE requests SET input_tokens=?, output_tokens=? WHERE id=?",
                       (input_tokens, output_tokens, request_id))

    def summary(self):
        with self.connect() as db:
            count, reserved, inputs, outputs, unknown = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(reserved),0), COALESCE(SUM(input_tokens),0), "
                "COALESCE(SUM(output_tokens),0), SUM(CASE WHEN input_tokens IS NULL THEN 1 ELSE 0 END) FROM requests"
            ).fetchone()
        return {"cap_usd": 5, "reserved_usd": reserved / 1_000_000, "requests": count,
                "usage_estimate_usd": (inputs * 0.125 + outputs * 0.50) / 1_000_000,
                "unknown_requests": unknown or 0}
