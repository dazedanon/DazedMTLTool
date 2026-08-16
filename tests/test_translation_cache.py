import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_cache_key_dimensions(self):
        dialogue_payload = '{"Line1": "そうです"}'
        source_lines = ["果歩 \"前の行\""]
        cases = (
            (
                "language",
                ('{"Line1": "テスト"}', "English"),
                {},
                ('{"Line1": "テスト"}', "Spanish"),
                {},
                False,
            ),
            (
                "matched glossary",
                ('{"Line1": "カイン"}', "English", "カイン (Kain)"),
                {},
                ('{"Line1": "カイン"}', "English", "カイン (Cain)"),
                {},
                False,
            ),
            (
                "conversation history",
                (dialogue_payload, "English"),
                {"request_context": ["He agreed."]},
                (dialogue_payload, "English"),
                {"request_context": ["She disagreed."]},
                False,
            ),
            (
                "source versus instruction fields",
                (dialogue_payload, "English"),
                {"request_context": T._typed_request_context(source_lines, [])},
                (dialogue_payload, "English"),
                {"request_context": T._typed_request_context([], source_lines)},
                False,
            ),
            (
                "instruction text",
                (dialogue_payload, "English"),
                {
                    "request_context": T._typed_request_context(
                        source_lines, ["Keep it brief."]
                    )
                },
                (dialogue_payload, "English"),
                {
                    "request_context": T._typed_request_context(
                        source_lines, ["Use a formal register."]
                    )
                },
                False,
            ),
            (
                "empty matched context",
                ('{"Line1": "名前のない文章"}', "English"),
                {},
                ('{"Line1": "名前のない文章"}', "English", ""),
                {},
                True,
            ),
        )
        for label, left_args, left_kwargs, right_args, right_kwargs, equal in cases:
            with self.subTest(label):
                left = T.get_cache_key(*left_args, **left_kwargs)
                right = T.get_cache_key(*right_args, **right_kwargs)
                self.assertEqual(left == right, equal)

    def test_unrelated_full_glossary_changes_do_not_change_matched_key(self):
        payload = '{"Line1": "カイン"}'
        first_vocab = "# Game Characters\nカイン (Cain)\nアベル (Abel)\n"
        second_vocab = "# Game Characters\nカイン (Cain)\nシア (Shia)\n"
        first_matched = T.buildMatchedVocabText(
            T.parseVocabWithCategories(first_vocab), payload
        )
        second_matched = T.buildMatchedVocabText(
            T.parseVocabWithCategories(second_vocab), payload
        )
        self.assertEqual(
            T.get_cache_key(payload, "English", first_matched),
            T.get_cache_key(payload, "English", second_matched),
        )

    def test_sfx_reference_is_separate_and_part_of_dynamic_cache_context(self):
        config = T.TranslationConfig(
            model="test",
            language="English",
            prompt="Translate to English.",
            vocab="",
            useSfxReference=True,
        )
        payload = '{"Line1":"胸がドキドキする"}'
        _system, glossary, sfx, _user = T.createContextParts(
            config, payload, "json"
        )
        self.assertEqual(glossary, "")
        self.assertIn("ドキドキ", sfx)
        self.assertNotEqual(
            T.get_cache_key(payload, "English", ""),
            T.get_cache_key(payload, "English", glossary + sfx),
        )

    def test_disabled_sfx_reference_keeps_dynamic_context_empty(self):
        config = T.TranslationConfig(
            model="test", prompt="Translate English.", vocab="",
            useSfxReference=False,
        )
        _system, glossary, sfx, _user = T.createContextParts(
            config, '{"Line1":"ドキドキ"}', "json"
        )
        self.assertEqual(glossary + sfx, "")


class CacheRoundTripTests(CacheTestBase):
    def test_cached_value_shapes_are_preserved(self):
        cases = (
            ("list", '{"Line1": "あ", "Line2": "い"}', ["A", "B"]),
            ("string", '{"Line1": "名前"}', "Name"),
        )
        for label, payload, value in cases:
            with self.subTest(label):
                T.cache_translation(payload, value, "English")
                self.assertEqual(T.peek_cached_translation(payload, "English"), value)

    def test_miss_returns_none_from_peek(self):
        self.assertIsNone(T.peek_cached_translation("nope", "English"))

    def test_persists_to_disk(self):
        payload = '{"Line1": "保存"}'
        T.cache_translation(payload, ["Save"], "English")
        self.assertTrue(T.CACHE_FILE.exists())
        # Drop the in-memory copy; a fresh read must come from disk.
        T._cache = {}
        self.assertEqual(T.peek_cached_translation(payload, "English"), ["Save"])

    def test_glossary_change_does_not_reuse_cached_translation(self):
        payload = '{"Line1": "カイン"}'
        T.cache_translation(payload, ["Kain"], "English", "カイン (Kain)")

        self.assertEqual(
            T.peek_cached_translation(payload, "English", "カイン (Kain)"),
            ["Kain"],
        )
        self.assertIsNone(
            T.peek_cached_translation(payload, "English", "カイン (Cain)")
        )

    def test_different_history_does_not_reuse_cached_translation(self):
        payload = '{"Line1": "そうです"}'
        T.cache_translation(
            payload,
            ["Yes."],
            "English",
            request_context=["He agreed."],
        )

        self.assertEqual(
            T.peek_cached_translation(
                payload, "English", request_context=["He agreed."]
            ),
            ["Yes."],
        )
        self.assertIsNone(
            T.peek_cached_translation(
                payload, "English", request_context=["She disagreed."]
            )
        )

    def test_restored_japanese_control_parameter_is_masked_for_validation(self):
        source = r"\SE[タイプライター]こんにちは"
        protected_source, replacements = T.protect_script_codes(source)
        cached = r"\SE[タイプライター]Hello"
        protected_cached = T._reprotect_cached_codes(cached, replacements)

        valid, invalid, reasons = T.validate_translation_content(
            [protected_source],
            [protected_cached],
            r"[一-龠ぁ-ゔァ-ヴーａ-ｚＡ-Ｚ０-９\uFF61-\uFF9F]+",
        )

        self.assertTrue(valid, reasons)
        self.assertFalse(invalid)
        self.assertIn("__PROTECTED_0__", protected_cached)


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

    def test_failed_translation_scope_releases_its_pending_marker(self):
        payload = '{"Line1": "失敗"}'
        key = T.get_cache_key(payload, "English")

        with T._cache_reservation_scope():
            self.assertIsNone(T.get_cached_translation(payload, "English"))
            self.assertTrue(T._is_pending_cache_entry(T._read_cache_from_disk()[key]))

        self.assertNotIn(key, T._read_cache_from_disk())
        self.assertNotIn(key, T._cache)

    def test_reservation_scope_stays_active_across_retries(self):
        payload = '{"Line1": "再試行"}'
        key = T.get_cache_key(payload, "English")
        attempts = 0

        @T._cache_reservation_scope()
        @T.retry(exceptions=RuntimeError, tries=2, delay=0, logger=None)
        def translate_with_retry():
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                self.assertIsNone(T.get_cached_translation(payload, "English"))
                raise RuntimeError("transient provider failure")
            entry = T._read_cache_from_disk().get(key)
            self.assertTrue(T._is_own_pending_cache_entry(entry))
            return "translated"

        self.assertEqual(translate_with_retry(), "translated")
        self.assertEqual(attempts, 2)
        self.assertNotIn(key, T._read_cache_from_disk())


class MergeTests(CacheTestBase):
    def test_merge_translation_cache_cases(self):
        cases = (
            (
                "pending never overwrites real",
                {"k": ["done"]},
                {"k": T._pending_cache_entry()},
                {"k": ["done"]},
            ),
            (
                "real overwrites pending",
                {"k": T._pending_cache_entry()},
                {"k": ["done"]},
                {"k": ["done"]},
            ),
            ("new keys", {"a": [1]}, {"b": [2]}, {"a": [1], "b": [2]}),
        )
        for label, base, overlay, expected in cases:
            with self.subTest(label):
                self.assertEqual(T._merge_translation_caches(base, overlay), expected)

    def test_stale_pending_can_be_replaced_by_pending(self):
        stale = T._pending_cache_entry()
        stale["time"] = 0  # far in the past -> stale
        fresh = T._pending_cache_entry()
        merged = T._merge_translation_caches({"k": stale}, {"k": fresh})
        self.assertIs(merged["k"], fresh)


class ExpandCleanToBatchTests(unittest.TestCase):
    """The core of the cache fix: cached values are Japanese-only and must be
    re-expanded with the *current* batch's skipped originals."""

    def test_expand_clean_to_batch_cases(self):
        cases = (
            (
                "no skips",
                ["A", "B", "C"],
                ["あ", "い", "う"],
                {},
                {},
                ["A", "B", "C"],
            ),
            (
                "corrupted original",
                ["A", "C"],
                ["あ", "\ufffd bad", "う"],
                {1: "\ufffd bad"},
                {},
                ["A", "\ufffd bad", "C"],
            ),
            (
                "mixed skipped originals",
                ["A", "E"],
                ["あ", "\ufffd", "Name", "え"],
                {1: "\ufffd"},
                {2: "Name"},
                ["A", "\ufffd", "Name", "E"],
            ),
            (
                "multiple non-Japanese originals",
                ["A", "C"],
                ["あ", "x", "う", "y"],
                {},
                {1: "x", 3: "y"},
                ["A", "x", "C", "y"],
            ),
            (
                "short clean values",
                ["A"],
                ["あ", "い", "う"],
                {},
                {},
                ["A", "い", "う"],
            ),
        )
        for label, clean, batch, corrupted, untranslated, expected in cases:
            with self.subTest(label):
                self.assertEqual(
                    T.expand_clean_to_batch(clean, batch, corrupted, untranslated),
                    expected,
                )

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


class SaveLoadTests(CacheTestBase):
    def test_deferred_updates_are_visible_and_commit_once(self):
        """Batch consume must not rewrite the whole cache for every result."""
        first_payload = '{"Line1": "一"}'
        second_payload = '{"Line1": "二"}'
        T._write_cache_to_disk({"existing": ["kept"]})
        T._cache = {}

        original_write = T._write_cache_to_disk
        with mock.patch.object(
            T, "_write_cache_to_disk", wraps=original_write
        ) as write_cache:
            with T.deferred_translation_cache_writes():
                self.assertIsNone(
                    T.get_cached_translation(first_payload, "English")
                )
                T.cache_translation(first_payload, ["One"], "English")
                T.cache_translation(second_payload, ["Two"], "English")
                self.assertEqual(
                    T.get_cached_translation(first_payload, "English"), ["One"]
                )
                self.assertEqual(
                    T._read_cache_from_disk(), {"existing": ["kept"]}
                )

            self.assertEqual(write_cache.call_count, 1)

        on_disk = T._read_cache_from_disk()
        self.assertEqual(on_disk["existing"], ["kept"])
        self.assertEqual(
            T.peek_cached_translation(first_payload, "English"), ["One"]
        )
        self.assertEqual(
            T.peek_cached_translation(second_payload, "English"), ["Two"]
        )

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
