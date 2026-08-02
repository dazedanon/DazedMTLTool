import types
import unittest
from unittest import mock

from openai import APIStatusError, RateLimitError

import util.translation as T
from util.translation import AdaptiveLimiter, _header_float, _header_int


class FakeClock:
    """Deterministic stand-in for the ``time`` module.

    ``sleep`` advances the clock instead of waiting, so pacing/backoff paths
    resolve instantly and predictably.
    """

    def __init__(self, start=1000.0):
        self.t = start

    def monotonic(self):
        return self.t

    def time(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds


def make_exc(cls, **attrs):
    """Build an openai exception without running its real constructor."""
    err = cls.__new__(cls)
    for key, value in attrs.items():
        setattr(err, key, value)
    return err


class FakeRaw:
    def __init__(self, headers, parsed):
        self._headers = headers
        self._parsed = parsed

    @property
    def headers(self):
        return self._headers

    def parse(self):
        return self._parsed


class FakeCreate:
    """Callable that replays a scripted sequence of returns/raises."""

    def __init__(self, behaviors):
        self.behaviors = behaviors
        self.calls = []

    def __call__(self, **params):
        self.calls.append(params)
        behavior = self.behaviors[len(self.calls) - 1]
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def fake_openai(create):
    completions = types.SimpleNamespace(
        with_raw_response=types.SimpleNamespace(create=create)
    )
    return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))


class HeaderHelperTests(unittest.TestCase):
    def test_header_parsing_cases(self):
        cases = (
            ("first present integer", _header_int, {"b": "125.9"}, ("a", "b"), 125),
            ("missing integer", _header_int, {}, ("a",), None),
            ("blank integer", _header_int, {"a": "  "}, ("a",), None),
            ("garbage integer", _header_int, {"a": "abc"}, ("a",), None),
            ("fractional float", _header_float, {"a": "0.42"}, ("a",), 0.42),
        )
        for label, parser, headers, names, expected in cases:
            with self.subTest(label):
                self.assertEqual(parser(headers, *names), expected)


class AdaptiveLimiterUpdateTests(unittest.TestCase):
    def _limiter(self):
        # Seeded at 0.5 RPS / 50k TPM, matching the production default.
        return AdaptiveLimiter(0.5, 50000, 4000)

    def test_canonical_headers_correct_pace_and_budget(self):
        lim = self._limiter()
        lim.update({
            "x-ratelimit-limit-requests": "125",
            "x-ratelimit-limit-tokens": "500000",
            "x-ratelimit-remaining-tokens": "498000",
        })
        self.assertAlmostEqual(lim.req_per_sec, 125 / 60.0)
        self.assertAlmostEqual(lim.min_interval, 60.0 / 125)
        self.assertEqual(lim.tok_per_min, 500000)
        self.assertEqual(lim.tokens_remaining, 498000)

    def test_legacy_minute_spelling_still_works(self):
        lim = self._limiter()
        lim.update({
            "x-ratelimit-limit-req-minute": "25",
            "x-ratelimit-limit-tokens-minute": "60000",
            "x-ratelimit-remaining-tokens-minute": "59000",
        })
        self.assertAlmostEqual(lim.req_per_sec, 25 / 60.0)
        self.assertEqual(lim.tok_per_min, 60000)
        self.assertEqual(lim.tokens_remaining, 59000)

    def test_true_per_second_header_used_undivided(self):
        lim = self._limiter()
        lim.update({"x-ratelimit-limit-req-second": "2"})
        self.assertAlmostEqual(lim.req_per_sec, 2.0)

    def test_empty_or_missing_headers_leave_seed_untouched(self):
        for headers in (None, {}):
            lim = self._limiter()
            lim.update(headers)
            self.assertAlmostEqual(lim.req_per_sec, 0.5)
            self.assertEqual(lim.tok_per_min, 50000)

    def test_garbage_values_ignored(self):
        lim = self._limiter()
        lim.update({"x-ratelimit-limit-requests": "abc"})
        self.assertAlmostEqual(lim.req_per_sec, 0.5)

    def test_exhausted_request_budget_holds_off(self):
        clock = FakeClock()
        with mock.patch.object(T, "time", clock):
            lim = self._limiter()
            lim.update({"x-ratelimit-remaining-requests": "0"})
            self.assertGreaterEqual(lim.next_request_at, clock.monotonic() + 60.0)


class AdaptiveLimiterAcquireTests(unittest.TestCase):
    def test_requests_spaced_by_min_interval(self):
        clock = FakeClock()
        with mock.patch.object(T, "time", clock):
            lim = AdaptiveLimiter(2.0, 10_000_000, 4000)  # min_interval = 0.5s
            lim.acquire(10)  # first clears immediately
            self.assertEqual(clock.t, 1000.0)
            lim.acquire(10)  # second waits one interval
            self.assertAlmostEqual(clock.t, 1000.5)
            self.assertEqual(lim.tokens_remaining, 10_000_000 - 20)

    def test_token_gate_waits_for_window_reset(self):
        clock = FakeClock()
        with mock.patch.object(T, "time", clock):
            lim = AdaptiveLimiter(1000.0, 10000, 2000)
            lim.tokens_remaining = 2500  # near depletion: 2500 - 1000 <= 2000
            original_reset = lim.window_reset
            lim.acquire(1000)
            # It blocked until the minute window rolled over.
            self.assertGreaterEqual(clock.t, original_reset)
            # After the reset the budget refills, then this call is charged.
            self.assertEqual(lim.tokens_remaining, 10000 - 1000)


class CallMistralTests(unittest.TestCase):
    def setUp(self):
        self._saved_limiter = T._mistral_limiter
        T._mistral_limiter = None  # force a fresh limiter from the seeds
        self.clock = FakeClock()
        self._patches = [
            mock.patch.object(T, "time", self.clock),
            mock.patch.dict(T.os.environ, {}, clear=False),
        ]
        for patch in self._patches:
            patch.start()

    def tearDown(self):
        for patch in self._patches:
            patch.stop()
        T._mistral_limiter = self._saved_limiter

    def _params(self, **extra):
        base = {"messages": [{"content": "テスト"}], "max_tokens": 100}
        base.update(extra)
        return base

    def test_success_returns_response_and_syncs_limiter(self):
        sentinel = object()
        create = FakeCreate([
            FakeRaw({"x-ratelimit-limit-requests": "125"}, sentinel),
        ])
        with mock.patch.object(T, "openai", fake_openai(create)):
            result = T.callMistral(self._params())
        self.assertIs(result, sentinel)
        self.assertEqual(len(create.calls), 1)
        self.assertAlmostEqual(T._get_mistral_limiter().req_per_sec, 125 / 60.0)

    def test_rate_limit_then_success_retries(self):
        sentinel = object()
        rate_limited = make_exc(
            RateLimitError,
            response=types.SimpleNamespace(headers={"retry-after": "0.01"}),
        )
        create = FakeCreate([
            rate_limited,
            FakeRaw({"x-ratelimit-limit-requests": "60"}, sentinel),
        ])
        with mock.patch.object(T, "openai", fake_openai(create)):
            result = T.callMistral(self._params())
        self.assertIs(result, sentinel)
        self.assertEqual(len(create.calls), 2)

    def test_json_schema_downgraded_to_json_object(self):
        sentinel = object()
        bad_format = make_exc(APIStatusError, status_code=400)
        create = FakeCreate([
            bad_format,
            FakeRaw({}, sentinel),
        ])
        params = self._params(response_format={"type": "json_schema"})
        with mock.patch.object(T, "openai", fake_openai(create)):
            result = T.callMistral(params)
        self.assertIs(result, sentinel)
        self.assertEqual(create.calls[1]["response_format"], {"type": "json_object"})


if __name__ == "__main__":
    unittest.main()
