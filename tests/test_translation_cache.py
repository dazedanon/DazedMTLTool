import os
import tempfile
import unittest
from pathlib import Path

import util.translation as T


class CacheTestBase(unittest.TestCase):
    """Isolate the on-disk cache to a temp dir and reset the in-memory cache."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig_file = T.CACHE_FILE
        self._orig_lock = T.CACHE_LOCK_FILE
        self._orig_cache = T._cache
        T.CACHE_FILE = tmp / "translation_cache.json"
        T.CACHE_LOCK_FILE = tmp / "translation_cache.lock"
        T._cache = {}

    def tearDown(self):
        T.CACHE_FILE = self._orig_file
        T.CACHE_LOCK_FILE = self._orig_lock
        T._cache = self._orig_cache
        self._tmp.cleanup()


class CacheKeyTests(CacheTestBase):
    def test_same_payload_and_language_is_stable(self):
        payload = '{"Line1": "テスト"}'
        self.assertEqual(
            T.get_cache_key(payload, "English"),
            T.get_cache_key(payload, "English"),
        )

    def test_language_changes_the_key(self):
        payload = '{"Line1": "テスト"}'
        self.assertNotEqual(
            T.get_cache_key(payload, "English"),
            T.get_cache_key(payload, "Spanish"),
        )

    def test_identical_japanese_collides_across_files(self):
        # Two files producing the same Japanese-only payload share a key. This is
        # exactly why the cached value must be Japanese-only (no file-specific
        # neighbours), so the read path can re-expand it per file.
        payload = '{"Line1": "おはよう"}'
        self.assertEqual(
            T.get_cache_key(payload, "English"),
            T.get_cache_key(payload, "English"),
        )


class CacheRoundTripTests(CacheTestBase):
    def test_list_value_preserved_exactly(self):
        payload = '{"Line1": "あ", "Line2": "い"}'
        value = ["A", "B"]
        T.cache_translation(payload, value, "English")
        self.assertEqual(T.peek_cached_translation(payload, "English"), value)

    def test_string_value_preserved(self):
        payload = '{"Line1": "名前"}'
        T.cache_translation(payload, "Name", "English")
        self.assertEqual(T.peek_cached_translation(payload, "English"), "Name")

    def test_miss_returns_none_from_peek(self):
        self.assertIsNone(T.peek_cached_translation("nope", "English"))

    def test_persists_to_disk(self):
        payload = '{"Line1": "保存"}'
        T.cache_translation(payload, ["Save"], "English")
        self.assertTrue(T.CACHE_FILE.exists())
        # Drop the in-memory copy; a fresh read must come from disk.
        T._cache = {}
        self.assertEqual(T.peek_cached_translation(payload, "English"), ["Save"])


class PendingMarkerTests(CacheTestBase):
    def test_miss_writes_pending_then_peek_sees_it_as_none(self):
        payload = '{"Line1": "待機"}'
        # First lookup is a miss: returns None and leaves a pending marker.
        self.assertIsNone(T.get_cached_translation(payload, "English"))
        # peek treats a pending marker as "not ready" -> None (never blocks).
        self.assertIsNone(T.peek_cached_translation(payload, "English"))

    def test_own_pending_does_not_deadlock(self):
        # A second call from the same pid/thread must not block on its own marker.
        payload = '{"Line1": "再入"}'
        self.assertIsNone(T.get_cached_translation(payload, "English"))
        self.assertIsNone(T.get_cached_translation(payload, "English"))

    def test_real_value_after_pending_is_returned(self):
        payload = '{"Line1": "結果"}'
        self.assertIsNone(T.get_cached_translation(payload, "English"))
        T.cache_translation(payload, ["Result"], "English")
        self.assertEqual(T.get_cached_translation(payload, "English"), ["Result"])


class MergeTests(CacheTestBase):
    def test_pending_never_overwrites_real_translation(self):
        real = {"k": ["done"]}
        overlay = {"k": T._pending_cache_entry()}
        merged = T._merge_translation_caches(real, overlay)
        self.assertEqual(merged["k"], ["done"])

    def test_real_translation_overwrites_pending(self):
        base = {"k": T._pending_cache_entry()}
        overlay = {"k": ["done"]}
        merged = T._merge_translation_caches(base, overlay)
        self.assertEqual(merged["k"], ["done"])

    def test_new_keys_are_added(self):
        merged = T._merge_translation_caches({"a": [1]}, {"b": [2]})
        self.assertEqual(merged, {"a": [1], "b": [2]})

    def test_stale_pending_can_be_replaced_by_pending(self):
        stale = T._pending_cache_entry()
        stale["time"] = 0  # far in the past -> stale
        fresh = T._pending_cache_entry()
        merged = T._merge_translation_caches({"k": stale}, {"k": fresh})
        self.assertIs(merged["k"], fresh)


class ExpandCleanToBatchTests(unittest.TestCase):
    """The core of the cache fix: cached values are Japanese-only and must be
    re-expanded with the *current* batch's skipped originals."""

    def test_no_skips_returns_clean_values_in_order(self):
        tItem = ["あ", "い", "う"]
        out = T.expand_clean_to_batch(["A", "B", "C"], tItem, {}, {})
        self.assertEqual(out, ["A", "B", "C"])

    def test_no_japanese_originals_reinserted_per_file(self):
        # Same Japanese-only cache value ["A", "C"], but each file supplies its
        # own English neighbour at index 1 — proving no cross-file leakage.
        tItem = ["あ", "Hello", "う"]
        clean = ["A", "C"]
        out = T.expand_clean_to_batch(clean, tItem, {}, {1: "Hello"})
        self.assertEqual(out, ["A", "Hello", "C"])

        tItem2 = ["あ", "World", "う"]
        out2 = T.expand_clean_to_batch(clean, tItem2, {}, {1: "World"})
        self.assertEqual(out2, ["A", "World", "C"])

    def test_corrupted_originals_reinserted(self):
        tItem = ["あ", "\ufffd bad", "う"]
        out = T.expand_clean_to_batch(["A", "C"], tItem, {1: "\ufffd bad"}, {})
        self.assertEqual(out, ["A", "\ufffd bad", "C"])

    def test_mixed_corrupted_and_no_japanese(self):
        tItem = ["あ", "\ufffd", "Name", "え"]
        out = T.expand_clean_to_batch(
            ["A", "E"], tItem, {1: "\ufffd"}, {2: "Name"}
        )
        self.assertEqual(out, ["A", "\ufffd", "Name", "E"])

    def test_result_length_always_matches_batch(self):
        tItem = ["あ", "x", "う", "y"]
        out = T.expand_clean_to_batch(["A", "C"], tItem, {}, {1: "x", 3: "y"})
        self.assertEqual(len(out), len(tItem))

    def test_short_clean_values_falls_back_to_source(self):
        # Defensive: a stale/short cache value must not raise; it falls back to
        # the source line for any positions it can't fill.
        tItem = ["あ", "い", "う"]
        out = T.expand_clean_to_batch(["A"], tItem, {}, {})
        self.assertEqual(out, ["A", "い", "う"])


class SaveLoadTests(CacheTestBase):
    def test_save_preserves_entries_from_other_workers(self):
        # Simulate another worker having written an entry to disk.
        T._write_cache_to_disk({"other": ["kept"]})
        T._cache = {"mine": ["added"]}
        T.save_cache()
        on_disk = T._read_cache_from_disk()
        self.assertEqual(on_disk.get("other"), ["kept"])
        self.assertEqual(on_disk.get("mine"), ["added"])

    def test_load_merges_disk_and_memory(self):
        T._write_cache_to_disk({"disk": ["d"]})
        T._cache = {"mem": ["m"]}
        loaded = T.load_cache()
        self.assertEqual(loaded.get("disk"), ["d"])
        self.assertEqual(loaded.get("mem"), ["m"])


if __name__ == "__main__":
    unittest.main()
