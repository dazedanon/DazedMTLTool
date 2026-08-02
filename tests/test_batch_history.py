#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for durable batch history and spend-safe ops."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import util.translation as T
import util.batch_history as BH


class BatchHistoryTestBase(unittest.TestCase):
    """Isolate batch JSON files to a temp dir."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self._orig = {
            "QUEUE": T.BATCH_QUEUE_FILE,
            "STATE": T.BATCH_STATE_FILE,
            "RESULTS": T.BATCH_RESULTS_FILE,
            "LOCK": T.BATCH_LOCK_FILE,
            "SUBMIT_LOCK": T.BATCH_SUBMIT_LOCK_FILE,
            "HISTORY": BH.BATCH_HISTORY_FILE,
            "results_mem": T._batch_results,
            "pending": dict(T._batch_queue_pending),
        }
        T.BATCH_QUEUE_FILE = tmp / "batch_requests.json"
        T.BATCH_STATE_FILE = tmp / "batch_state.json"
        T.BATCH_RESULTS_FILE = tmp / "batch_results.json"
        T.BATCH_LOCK_FILE = tmp / "batch_files.lock"
        T.BATCH_SUBMIT_LOCK_FILE = tmp / "batch_submit.lock"
        BH.BATCH_HISTORY_FILE = tmp / "batch_history.json"
        # batch_history imports queue/state/results paths at call time via T.* —
        # but it also imported BATCH_* as names. Rebind module-level aliases.
        BH.BATCH_QUEUE_FILE = T.BATCH_QUEUE_FILE
        BH.BATCH_STATE_FILE = T.BATCH_STATE_FILE
        BH.BATCH_RESULTS_FILE = T.BATCH_RESULTS_FILE
        T._batch_results = None
        T._batch_queue_pending = {}

    def tearDown(self):
        T.BATCH_QUEUE_FILE = self._orig["QUEUE"]
        T.BATCH_STATE_FILE = self._orig["STATE"]
        T.BATCH_RESULTS_FILE = self._orig["RESULTS"]
        T.BATCH_LOCK_FILE = self._orig["LOCK"]
        T.BATCH_SUBMIT_LOCK_FILE = self._orig["SUBMIT_LOCK"]
        BH.BATCH_HISTORY_FILE = self._orig["HISTORY"]
        BH.BATCH_QUEUE_FILE = T.BATCH_QUEUE_FILE
        BH.BATCH_STATE_FILE = T.BATCH_STATE_FILE
        BH.BATCH_RESULTS_FILE = T.BATCH_RESULTS_FILE
        T._batch_results = self._orig["results_mem"]
        T._batch_queue_pending = self._orig["pending"]
        self._tmp.cleanup()


class BatchRunStateTests(BatchHistoryTestBase):
    def test_none_when_empty(self):
        self.assertIsNone(T.batchRunState())

    def test_queued_when_only_queue(self):
        T._write_batch_file(T.BATCH_QUEUE_FILE, {"k1": {"payload": "x", "language": "English", "params": {}}})
        self.assertEqual(T.batchRunState(), "queued")

    def test_corrupt_state_blocks_resume_and_submission(self):
        T._write_batch_file(
            T.BATCH_QUEUE_FILE,
            {
                "k1": {
                    "payload": "x",
                    "language": "English",
                    "params": {"model": "gpt-test"},
                    "provider": "openai",
                }
            },
        )
        T.BATCH_STATE_FILE.write_text("{truncated", encoding="utf-8")

        self.assertEqual(T.batchRunState(), "corrupt")
        with self.assertRaises(T.BatchFileCorruptionError):
            T.submitTranslationBatches()

    def test_corrupt_queue_is_not_overwritten_during_pending_flush(self):
        T.BATCH_QUEUE_FILE.write_text("{truncated", encoding="utf-8")
        T._batch_queue_pending = {"new-key": {"payload": "new"}}

        with self.assertRaises(T.BatchFileCorruptionError):
            T.flush_batch_queue()

        self.assertEqual(
            T.BATCH_QUEUE_FILE.read_text(encoding="utf-8"), "{truncated"
        )
        self.assertIn("new-key", T._batch_queue_pending)

    def test_submitted_when_state_has_batches(self):
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {"batches": [{"id": "msgbatch_1", "custom_ids": {"req-000000": "k1"}}]},
        )
        self.assertEqual(T.batchRunState(), "submitted")

    def test_partially_submitted_split_is_distinguishable(self):
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "status": "partially_submitted",
                "batches": [{"id": "batch_1", "custom_ids": {"req-000000": "k1"}}],
            },
        )
        self.assertEqual(T.batchRunState(), "partially_submitted")

    def test_fetched_when_results_present(self):
        T._write_batch_file(T.BATCH_RESULTS_FILE, {"k1": {"text": "hi"}})
        self.assertEqual(T.batchRunState(), "fetched")

    def test_fetched_when_state_status_fetched(self):
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {"status": "fetched", "batch_ids": ["msgbatch_1"], "batches": []},
        )
        self.assertEqual(T.batchRunState(), "fetched")

    def test_queued_glossary_context_change_is_detected(self):
        payload = '{"Line1": "カイン"}'
        old_vocab = "# Game Characters\nカイン (Kain)\n"
        old_context = T.buildMatchedVocabText(
            T.parseVocabWithCategories(old_vocab), payload
        )
        T.queue_batch_request(
            payload,
            "English",
            {},
            cache_context=old_context,
        )
        T.flush_batch_queue()

        stale, total = T.batchQueueStaleContextCount(
            "# Game Characters\nカイン (Cain)\n"
        )

        self.assertEqual((stale, total), (1, 1))

    def test_queued_unrelated_glossary_change_stays_current(self):
        payload = '{"Line1": "カイン"}'
        original_vocab = "# Game Characters\nカイン (Cain)\n"
        context = T.buildMatchedVocabText(
            T.parseVocabWithCategories(original_vocab), payload
        )
        T.queue_batch_request(
            payload,
            "English",
            {},
            cache_context=context,
        )
        T.flush_batch_queue()

        stale, total = T.batchQueueStaleContextCount(
            original_vocab + "アベル (Abel)\n"
        )

        self.assertEqual((stale, total), (0, 1))

    def test_same_payload_with_different_history_queues_twice(self):
        payload = '{"Line1": "そうです"}'
        T.queue_batch_request(
            payload, "English", {"model": "gpt-test"},
            provider="openai", request_context=["He agreed."],
        )
        T.queue_batch_request(
            payload, "English", {"model": "gpt-test"},
            provider="openai", request_context=["She disagreed."],
        )
        T.flush_batch_queue()

        queue = T._read_batch_file(T.BATCH_QUEUE_FILE)
        self.assertEqual(len(queue), 2)
        self.assertEqual(
            {entry["request_context"] for entry in queue.values()},
            {
                '{"instructions":[],"source_items":["He agreed."]}',
                '{"instructions":[],"source_items":["She disagreed."]}',
            },
        )

    def test_queue_serializes_source_and_instructions_together(self):
        payload = '{"Line1": "そうです"}'
        request_context = T._typed_request_context(
            ['果歩 "前の行"'], ["Keep every line gender-neutral."]
        )
        T.queue_batch_request(
            payload,
            "English",
            {"model": "gpt-test"},
            provider="openai",
            request_context=request_context,
        )
        T.flush_batch_queue()

        entry = next(iter(T._read_batch_file(T.BATCH_QUEUE_FILE).values()))
        self.assertEqual(
            json.loads(entry["request_context"]),
            {
                "instructions": ["Keep every line gender-neutral."],
                "source_items": ['果歩 "前の行"'],
            },
        )

    def test_legacy_queue_is_stale_before_submission(self):
        T._write_batch_file(T.BATCH_QUEUE_FILE, {
            "legacy-key": {
                "payload": '{"Line1":"そうです"}',
                "language": "English",
                "params": {"model": "gpt-5.6-terra", "messages": []},
                "provider": "openai",
            },
        })

        self.assertEqual(T.batchQueueStaleContextCount(""), (1, 1))

    def test_untyped_version_two_queue_is_stale_before_submission(self):
        payload = '{"Line1":"そうです"}'
        request_context = T._normalize_cache_request_context(["果歩 \"前の行\""])
        old_key = T.get_cache_key(
            payload, "English", "", request_context=request_context
        )
        T._write_batch_file(T.BATCH_QUEUE_FILE, {
            old_key: {
                "payload": payload,
                "language": "English",
                "params": {"model": "gpt-test"},
                "provider": "openai",
                "request_context": request_context,
                "cache_key_version": 2,
            },
        })

        self.assertEqual(T.batchQueueStaleContextCount(""), (1, 1))

    def test_single_kind_version_three_queue_is_stale_before_submission(self):
        T._write_batch_file(T.BATCH_QUEUE_FILE, {
            "old-v3-key": {
                "payload": '{"Line1":"そうです"}',
                "language": "English",
                "params": {"model": "gpt-test"},
                "provider": "openai",
                "request_context": (
                    '{"items":["果歩 \\"前の行\\""],"kind":"source_context"}'
                ),
                "cache_key_version": 3,
            },
        })

        self.assertEqual(T.batchQueueStaleContextCount(""), (1, 1))

    def test_legacy_queue_is_blocked_at_paid_boundary(self):
        T._write_batch_file(T.BATCH_QUEUE_FILE, {
            "legacy-key": {
                "payload": '{"Line1":"そうです"}',
                "language": "English",
                "params": {"model": "gpt-5.6-terra", "messages": []},
                "provider": "openai",
            },
        })

        with mock.patch("util.batch_providers.submit_batch") as submit:
            with self.assertRaisesRegex(ValueError, "predates combined"):
                T.submitTranslationBatches()

        submit.assert_not_called()

    def test_version_two_queue_is_blocked_at_paid_boundary(self):
        T._write_batch_file(T.BATCH_QUEUE_FILE, {
            "old-v2-key": {
                "payload": '{"Line1":"そうです"}',
                "language": "English",
                "params": {"model": "gpt-test", "messages": []},
                "provider": "openai",
                "request_context": '["果歩 \\"前の行\\""]',
                "cache_key_version": 2,
            },
        })

        with mock.patch("util.batch_providers.submit_batch") as submit:
            with self.assertRaisesRegex(ValueError, "predates combined"):
                T.submitTranslationBatches()

        submit.assert_not_called()

    def test_version_three_queue_is_blocked_at_paid_boundary(self):
        T._write_batch_file(T.BATCH_QUEUE_FILE, {
            "old-v3-key": {
                "payload": '{"Line1":"そうです"}',
                "language": "English",
                "params": {"model": "gpt-test", "messages": []},
                "provider": "openai",
                "request_context": (
                    '{"items":["果歩 \\"前の行\\""],"kind":"source_context"}'
                ),
                "cache_key_version": 3,
            },
        })

        with mock.patch("util.batch_providers.submit_batch") as submit:
            with self.assertRaisesRegex(ValueError, "predates combined"):
                T.submitTranslationBatches()

        submit.assert_not_called()

    def test_legacy_fetched_result_falls_back_without_version_marker(self):
        payload = '{"Line1":"そうです"}'
        result = {"text": '{"Line1":"Yes"}'}
        legacy_key = T.get_cache_key(payload, "English", "")
        T._write_batch_file(T.BATCH_RESULTS_FILE, {legacy_key: result})
        T._write_batch_file(T.BATCH_STATE_FILE, {"status": "fetched"})
        T._batch_results = None

        self.assertEqual(
            T.take_batch_result(
                payload, "English", "", request_context=["He agreed."],
            ),
            result,
        )

    def test_modern_fetched_result_never_falls_back_across_history(self):
        payload = '{"Line1":"そうです"}'
        legacy_key = T.get_cache_key(payload, "English", "")
        T._write_batch_file(
            T.BATCH_RESULTS_FILE,
            {legacy_key: {"text": '{"Line1":"Yes"}'}},
        )
        T._write_batch_file(T.BATCH_STATE_FILE, {
            "status": "fetched",
            "cache_key_version": T.BATCH_CACHE_KEY_VERSION,
        })
        T._batch_results = None

        self.assertIsNone(T.take_batch_result(
            payload, "English", "", request_context=["She disagreed."],
        ))

    def test_queued_sfx_context_becomes_stale_when_reference_is_disabled(self):
        payload = '{"Line1": "ドキドキ"}'
        config = T.TranslationConfig(
            model="test", prompt="Translate English.", vocab="",
            useSfxReference=True,
        )
        _system, glossary, sfx, _user = T.createContextParts(
            config, payload, "json"
        )
        T.queue_batch_request(
            payload,
            "English",
            {},
            cache_context=glossary + sfx,
        )
        T.flush_batch_queue()

        stale, total = T.batchQueueStaleContextCount(
            "", use_sfx_reference=False
        )

        self.assertEqual((stale, total), (1, 1))

    def test_fetched_result_requires_same_glossary_context(self):
        payload = '{"Line1": "カイン"}'
        old_context = "カイン (Kain)"
        result = {"text": '{"Line1":"Kain"}'}
        old_key = T.get_cache_key(payload, "English", old_context)
        T._write_batch_file(T.BATCH_RESULTS_FILE, {old_key: result})
        T._batch_results = None

        self.assertEqual(
            T.take_batch_result(payload, "English", old_context), result
        )
        self.assertIsNone(
            T.take_batch_result(payload, "English", "カイン (Cain)")
        )
        with self.assertRaisesRegex(
            T.BatchResultUnavailableError, "full-price live request"
        ):
            T.require_batch_result(payload, "English", "カイン (Cain)")

    def test_queued_batch_metadata_preserves_resume_file_scope(self):
        T.saveQueuedBatchMetadata(["Map001.json", "Map002.json"])

        self.assertEqual(T.batchRunMetadata()["status"], "queued")
        self.assertEqual(
            T.batchRunMetadata()["file_set"],
            ["Map001.json", "Map002.json"],
        )


class HistorySurvivalTests(BatchHistoryTestBase):
    def test_history_survives_fetch_marker_and_clear(self):
        custom_ids = {"req-000000": "cachekey1", "req-000001": "cachekey2"}
        BH.record_submit(
            [{"id": "msgbatch_abc", "custom_ids": custom_ids}],
            model="claude-sonnet-4-5",
            file_set=["Map001.json"],
            cost_estimate={"batch_cached_cost": 1.23, "model": "claude-sonnet-4-5"},
        )
        BH.record_fetch(["msgbatch_abc"], succeeded=2, errored=0, usage={"input_tokens": 10}, actual_cost=0.5)
        T._write_batch_file(T.BATCH_RESULTS_FILE, {"cachekey1": {"text": "A"}, "cachekey2": {"text": "B"}})
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {"status": "fetched", "batch_ids": ["msgbatch_abc"], "batches": []},
        )

        T.clearBatchFiles()

        # Active files gone…
        self.assertFalse(T.BATCH_RESULTS_FILE.exists())
        self.assertFalse(T.BATCH_STATE_FILE.exists())
        # …but history retains custom_ids and is marked consumed.
        history = BH.read_history()
        entry = history["batches"][0]
        self.assertEqual(entry["id"], "msgbatch_abc")
        self.assertEqual(entry["custom_ids"], custom_ids)
        self.assertEqual(entry["status"], BH.STATUS_CONSUMED)
        self.assertEqual(entry["file_set"], ["Map001.json"])

    def test_clear_does_not_wipe_history_file(self):
        BH.upsert_history_entry("msgbatch_keep", status=BH.STATUS_SUBMITTED, custom_ids={"a": "b"})
        T.clearBatchFiles()
        self.assertTrue(BH.BATCH_HISTORY_FILE.exists())
        self.assertEqual(len(BH.read_history()["batches"]), 1)

    def test_corrupt_history_is_not_replaced_by_upsert(self):
        BH.BATCH_HISTORY_FILE.write_text("{truncated", encoding="utf-8")

        with self.assertRaises(T.BatchFileCorruptionError):
            BH.upsert_history_entry("new-batch", status=BH.STATUS_SUBMITTED)

        self.assertEqual(
            BH.BATCH_HISTORY_FILE.read_text(encoding="utf-8"), "{truncated"
        )

    def test_evaluation_history_uses_its_saved_key_reference(self):
        sentinel = object()
        entry = {
            "provider": "openai",
            "key_name": "Eval OpenAI",
        }
        with (
            mock.patch("util.api_keys.get_secret", return_value="eval-secret"),
            mock.patch("util.api_keys.get_endpoint", return_value="https://api.openai.com/v1"),
            mock.patch("util.api_keys.is_keyless", return_value=False),
            mock.patch.object(BH, "get_provider_client", return_value=sentinel) as client,
        ):
            resolved = BH._client_for_entry(entry)
        self.assertIs(resolved, sentinel)
        client.assert_called_once_with(
            "openai", api_key="eval-secret", api_url="https://api.openai.com/v1"
        )

    def test_evaluation_history_uses_submitted_endpoint(self):
        entry = {
            "provider": "openai",
            "key_name": "Eval OpenAI",
            "endpoint": "https://submitted.example/v1",
        }
        with (
            mock.patch("util.api_keys.get_secret", return_value="eval-secret"),
            mock.patch(
                "util.api_keys.get_endpoint",
                return_value="https://changed.example/v1",
            ),
            mock.patch("util.api_keys.is_keyless", return_value=False),
            mock.patch.object(BH, "get_provider_client") as client,
        ):
            BH._client_for_entry(entry)

        client.assert_called_once_with(
            "openai",
            api_key="eval-secret",
            api_url="https://submitted.example/v1",
        )

    def test_normal_submission_records_matching_active_key_name(self):
        with (
            mock.patch("util.api_keys.get_active_name", return_value="Work OpenAI"),
            mock.patch("util.api_keys.get_secret", return_value="work-secret"),
            mock.patch("util.api_keys.get_endpoint", return_value="https://api.openai.com/v1"),
            mock.patch("util.api_keys.is_keyless", return_value=False),
            mock.patch.dict(
                "os.environ",
                {"key": "work-secret", "api": "https://api.openai.com/v1"},
            ),
        ):
            BH.record_submit(
                [{"id": "batch-keyed", "custom_ids": {"req-1": "cache-1"}}],
                provider="openai",
                model="gpt-test",
            )

        self.assertEqual(
            BH.read_history()["batches"][0]["key_name"], "Work OpenAI"
        )

    def test_submission_history_preserves_endpoint_and_cache_key_version(self):
        BH.record_submit(
            [{
                "id": "batch-routed",
                "custom_ids": {"req-1": "cache-1"},
                "cache_key_version": T.BATCH_CACHE_KEY_VERSION,
            }],
            provider="openai",
            endpoint="https://submitted.example/v1",
        )

        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["endpoint"], "https://submitted.example/v1")
        self.assertEqual(entry["cache_key_version"], T.BATCH_CACHE_KEY_VERSION)

    def test_batch_client_prefers_endpoint_saved_in_history(self):
        BH.upsert_history_entry(
            "batch-routed",
            provider="openai",
            key_name="Work OpenAI",
            endpoint="https://submitted.example/v1",
        )
        with (
            mock.patch("util.api_keys.get_secret", return_value="secret"),
            mock.patch(
                "util.api_keys.get_endpoint",
                return_value="https://changed.example/v1",
            ),
            mock.patch("util.api_keys.is_keyless", return_value=False),
            mock.patch.object(BH, "get_provider_client") as client,
        ):
            BH.client_for_batch(
                "batch-routed",
                "openai",
                "Work OpenAI",
                "https://state-copy.example/v1",
            )

        client.assert_called_once_with(
            "openai",
            api_key="secret",
            api_url="https://submitted.example/v1",
        )

    def test_split_submission_allocates_aggregate_estimate_once(self):
        estimate = {
            "requests": 4,
            "input_tokens": 400,
            "output_tokens": 80,
            "batch_cached_cost": 2.0,
            "model": "gpt-test",
        }
        BH.record_submit(
            [
                {"id": "batch-est-1", "custom_ids": {"r1": "k1", "r2": "k2"}},
                {"id": "batch-est-2", "custom_ids": {"r3": "k3", "r4": "k4"}},
            ],
            provider="openai",
            cost_estimate=estimate,
            key_name="Work OpenAI",
        )

        rows = {row["id"]: row for row in BH.read_history()["batches"]}
        self.assertEqual(rows["batch-est-1"]["cost_estimate"]["requests"], 2)
        self.assertEqual(rows["batch-est-2"]["cost_estimate"]["requests"], 2)
        self.assertEqual(
            sum(row["cost_estimate"]["batch_cached_cost"] for row in rows.values()),
            2.0,
        )


class ProviderSubmissionTests(BatchHistoryTestBase):
    def test_submission_lock_rejects_a_second_paid_submitter(self):
        with T._batch_submit_lock():
            with self.assertRaisesRegex(RuntimeError, "already being submitted"):
                T.submitTranslationBatches()

    def test_openai_submission_persists_provider_and_recovery_map(self):
        T.queue_batch_request(
            '{"Line1":"猫"}',
            "English",
            {"model": "gpt-5.6-terra", "messages": []},
            provider="openai",
        )
        T.flush_batch_queue()

        with (
            mock.patch.dict(
                "os.environ", {"api": "https://submitted.example/v1"}
            ),
            mock.patch(
                "util.batch_providers.submit_batch",
                return_value={"id": "batch_openai_1", "input_file_id": "file_1"},
            ) as submit,
        ):
            ids = T.submitTranslationBatches(file_set=["Map001.json"])

        self.assertEqual(ids, ["batch_openai_1"])
        self.assertEqual(submit.call_args.args[0], "openai")
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(state["provider"], "openai")
        self.assertEqual(state["endpoint"], "https://submitted.example/v1")
        self.assertEqual(state["batches"][0]["provider"], "openai")
        self.assertEqual(
            state["batches"][0]["endpoint"], "https://submitted.example/v1"
        )
        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["provider"], "openai")
        self.assertEqual(entry["endpoint"], "https://submitted.example/v1")
        self.assertTrue(entry["custom_ids"])

    def test_split_submission_checkpoints_and_retry_skips_paid_work(self):
        for payload in ('{"Line1":"猫"}', '{"Line1":"犬"}'):
            T.queue_batch_request(
                payload,
                "English",
                {"model": "gpt-5.6-terra", "messages": []},
                provider="openai",
            )
        T.flush_batch_queue()

        with (
            mock.patch("util.batch_providers.batch_limits", return_value=(1, 10_000_000)),
            mock.patch.object(BH, "client_for_batch", return_value=object()),
            mock.patch(
                "util.batch_providers.submit_batch",
                side_effect=(
                    {"id": "batch_paid_1", "input_file_id": "file_1"},
                    RuntimeError("second submit failed"),
                ),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "second submit failed"):
                T.submitTranslationBatches(file_set=["Map001.json"])

        checkpoint = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(checkpoint["status"], "partially_submitted")
        self.assertTrue(checkpoint["run_id"].startswith("translation-"))
        self.assertEqual([item["id"] for item in checkpoint["batches"]], ["batch_paid_1"])
        self.assertEqual(
            [item["id"] for item in BH.read_history()["batches"]],
            ["batch_paid_1"],
        )

        with (
            mock.patch("util.batch_providers.batch_limits", return_value=(1, 10_000_000)),
            mock.patch.object(BH, "client_for_batch", return_value=object()),
            mock.patch(
                "util.batch_providers.submit_batch",
                return_value={"id": "batch_paid_2", "input_file_id": "file_2"},
            ) as submit,
        ):
            ids = T.submitTranslationBatches(file_set=["Map001.json"])

        self.assertEqual(submit.call_count, 1)
        self.assertEqual(ids, ["batch_paid_1", "batch_paid_2"])
        self.assertEqual(T.batchRunMetadata()["status"], "submitted")
        final_state = T.batchRunMetadata()
        self.assertEqual(final_state["run_id"], checkpoint["run_id"])
        self.assertTrue(all(
            item["run_id"] == checkpoint["run_id"]
            for item in final_state["batches"]
        ))
        self.assertEqual(
            [item["id"] for item in BH.read_history()["batches"]],
            ["batch_paid_1", "batch_paid_2"],
        )
        self.assertEqual(
            {item["run_id"] for item in BH.read_history()["batches"]},
            {checkpoint["run_id"]},
        )

    def test_partial_resume_blocks_switching_saved_api_key(self):
        T.queue_batch_request(
            '{"Line1":"猫"}',
            "English",
            {"model": "gpt-test", "messages": []},
            provider="openai",
        )
        T.flush_batch_queue()
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "status": "partially_submitted",
                "batches": [{
                    "id": "batch-old-key",
                    "provider": "openai",
                    "custom_ids": {},
                }],
            },
        )
        BH.upsert_history_entry(
            "batch-old-key",
            provider="openai",
            key_name="Old Account",
            custom_ids={},
        )

        with (
            mock.patch.object(
                BH, "active_key_name_for_environment", return_value="New Account"
            ),
            mock.patch("util.batch_providers.submit_batch") as submit,
        ):
            with self.assertRaisesRegex(ValueError, "Old Account"):
                T.submitTranslationBatches()

        submit.assert_not_called()

    def test_active_status_poll_uses_batch_saved_client(self):
        client = object()
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "status": "submitted",
                "batches": [{
                    "id": "batch-saved-client",
                    "provider": "openai",
                    "custom_ids": {},
                }],
            },
        )
        BH.upsert_history_entry(
            "batch-saved-client",
            provider="openai",
            key_name="Original Account",
        )

        with (
            mock.patch.object(BH, "_client_for_entry", return_value=client),
            mock.patch(
                "util.batch_providers.retrieve_batch",
                return_value={
                    "api_status": "in_progress",
                    "ended": False,
                    "counts": {},
                },
            ) as retrieve,
        ):
            T.checkTranslationBatchStatuses(print_status=False)

        self.assertEqual(retrieve.call_args.kwargs["client"], client)


class RedownloadTests(BatchHistoryTestBase):
    def test_redownload_rebuilds_results_from_custom_ids(self):
        custom_ids = {"req-000000": "keyA", "req-000001": "keyB"}
        BH.upsert_history_entry(
            "msgbatch_rd",
            status=BH.STATUS_ENDED,
            model="claude-sonnet-4-5",
            endpoint="https://api.anthropic.com",
            cache_key_version=T.BATCH_CACHE_KEY_VERSION,
            custom_ids=custom_ids,
            request_count=2,
        )

        usage = SimpleNamespace(
            input_tokens=100,
            output_tokens=50,
            cache_read_input_tokens=10,
            cache_creation_input_tokens=20,
            thinking_tokens=5,
        )
        msg = SimpleNamespace(
            content=[SimpleNamespace(text='{"Line1":"Hi"}')],
            usage=usage,
        )
        ok_result = SimpleNamespace(type="succeeded", message=msg)
        row = SimpleNamespace(custom_id="req-000000", result=ok_result)
        row2_usage = SimpleNamespace(
            input_tokens=80,
            output_tokens=40,
            cache_read_input_tokens=0,
            cache_creation_input_tokens=0,
            thinking_tokens=0,
        )
        msg2 = SimpleNamespace(content=[SimpleNamespace(text='{"Line1":"Yo"}')], usage=row2_usage)
        row2 = SimpleNamespace(custom_id="req-000001", result=SimpleNamespace(type="succeeded", message=msg2))

        fake_batch = SimpleNamespace(id="msgbatch_rd", processing_status="ended")
        client = mock.MagicMock()
        client.messages.batches.retrieve.return_value = fake_batch
        client.messages.batches.results.return_value = [row, row2]
        T._write_batch_file(
            T.BATCH_RESULTS_FILE,
            {"stale-model-key": {"text": "wrong model"}},
        )

        with mock.patch.object(BH, "_get_anthropic_client", return_value=client):
            with mock.patch.object(BH, "getPricingConfig", return_value={"inputAPICost": 3.0, "outputAPICost": 15.0}):
                info = BH.redownload_batch("msgbatch_rd")

        self.assertEqual(info["succeeded"], 2)
        results = T._read_batch_file(T.BATCH_RESULTS_FILE)
        self.assertIn("keyA", results)
        self.assertIn("keyB", results)
        self.assertNotIn("stale-model-key", results)
        self.assertEqual(results["keyA"]["text"], '{"Line1":"Hi"}')
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(state.get("status"), "fetched")
        self.assertEqual(state["endpoint"], "https://api.anthropic.com")
        self.assertEqual(
            state["cache_key_version"], T.BATCH_CACHE_KEY_VERSION
        )
        self.assertEqual(set(state.get("result_keys") or []), {"keyA", "keyB"})
        self.assertEqual(T.batchRunState(), "fetched")
        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["status"], BH.STATUS_FETCHED)
        self.assertEqual(entry["custom_ids"], custom_ids)

    def test_redownload_preserves_corrupt_existing_results(self):
        BH.upsert_history_entry(
            "msgbatch_corrupt",
            status=BH.STATUS_ENDED,
            custom_ids={"req-1": "key-1"},
        )
        T.BATCH_RESULTS_FILE.write_text("{truncated", encoding="utf-8")

        with (
            self.assertRaises(T.BatchFileCorruptionError),
            mock.patch.object(BH, "provider_retrieve_batch") as retrieve,
        ):
            BH.redownload_batch("msgbatch_corrupt")

        retrieve.assert_not_called()
        self.assertEqual(
            T.BATCH_RESULTS_FILE.read_text(encoding="utf-8"), "{truncated"
        )

    def test_redownload_reconstructs_every_split_in_the_translation_run(self):
        for batch_id, custom_id, cache_key in (
            ("batch-split-1", "req-1", "key-1"),
            ("batch-split-2", "req-2", "key-2"),
        ):
            BH.upsert_history_entry(
                batch_id,
                status=BH.STATUS_ENDED,
                provider="openai",
                model="gpt-test",
                run_id="translation-run-1",
                custom_ids={custom_id: cache_key},
            )

        def download(batch_id, custom_ids, **_kwargs):
            cache_key = next(iter(custom_ids.values()))
            return ({cache_key: {"text": batch_id}}, [], {"input_tokens": 1})

        with (
            mock.patch.object(BH, "_client_for_entry", return_value=object()),
            mock.patch.object(
                BH, "provider_retrieve_batch",
                return_value={"api_status": "completed", "ended": True},
            ) as retrieve,
            mock.patch.object(BH, "download_batch_results", side_effect=download),
            mock.patch.object(BH, "_price_usage", return_value=0.01),
        ):
            info = BH.redownload_batch("batch-split-2")

        self.assertEqual(retrieve.call_count, 2)
        self.assertEqual(set(info["batch_ids"]), {"batch-split-1", "batch-split-2"})
        self.assertEqual(
            set(T._read_batch_file(T.BATCH_RESULTS_FILE)), {"key-1", "key-2"}
        )
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(state["run_id"], "translation-run-1")
        self.assertEqual(set(state["batch_ids"]), {"batch-split-1", "batch-split-2"})

    def test_redownload_does_not_replace_an_unrelated_active_run(self):
        BH.upsert_history_entry(
            "batch-history",
            status=BH.STATUS_ENDED,
            run_id="translation-history",
            custom_ids={"req-1": "history-key"},
        )
        active_state = {
            "status": "submitted",
            "run_id": "translation-active",
            "batches": [{"id": "batch-active", "custom_ids": {"req-a": "active-key"}}],
        }
        active_queue = {"active-key": {"payload": "paid work"}}
        T._write_batch_file(T.BATCH_STATE_FILE, active_state)
        T._write_batch_file(T.BATCH_QUEUE_FILE, active_queue)

        with (
            self.assertRaisesRegex(ValueError, "Another translation batch run"),
            mock.patch.object(BH, "provider_retrieve_batch") as retrieve,
        ):
            BH.redownload_batch("batch-history")

        retrieve.assert_not_called()
        self.assertEqual(T._read_batch_file(T.BATCH_STATE_FILE), active_state)
        self.assertEqual(T._read_batch_file(T.BATCH_QUEUE_FILE), active_queue)

    def test_gemini_redownload_passes_saved_native_files_client(self):
        BH.upsert_history_entry(
            "gemini-batch",
            status=BH.STATUS_ENDED,
            provider="gemini",
            key_name="Original Gemini",
            run_id="translation-gemini",
            custom_ids={"req-1": "key-1"},
        )
        sdk_client = object()
        files_client = object()
        with (
            mock.patch.object(BH, "_client_for_entry", return_value=sdk_client),
            mock.patch.object(BH, "_google_client_for_entry", return_value=files_client),
            mock.patch.object(
                BH, "provider_retrieve_batch",
                return_value={"api_status": "completed", "ended": True},
            ),
            mock.patch.object(
                BH, "download_batch_results",
                return_value=({"key-1": {"text": "ok"}}, [], {}),
            ) as download,
        ):
            BH.redownload_batch("gemini-batch")

        self.assertIs(download.call_args.kwargs["client"], sdk_client)
        self.assertIs(download.call_args.kwargs["google_client"], files_client)


class CancelTests(BatchHistoryTestBase):
    def test_cancel_updates_history_and_active_state(self):
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "batches": [
                    {"id": "msgbatch_c1", "custom_ids": {"req-000000": "k"}},
                    {"id": "msgbatch_c2", "custom_ids": {"req-000000": "k2"}},
                ]
            },
        )
        BH.upsert_history_entry("msgbatch_c1", status=BH.STATUS_SUBMITTED, custom_ids={"req-000000": "k"})
        BH.upsert_history_entry("msgbatch_c2", status=BH.STATUS_SUBMITTED, custom_ids={"req-000000": "k2"})

        before = SimpleNamespace(id="msgbatch_c1", processing_status="in_progress")
        after = SimpleNamespace(id="msgbatch_c1", processing_status="canceling")
        client = mock.MagicMock()
        client.messages.batches.retrieve.return_value = before
        client.messages.batches.cancel.return_value = after

        with mock.patch.object(BH, "_get_anthropic_client", return_value=client):
            results = BH.cancel_batches(["msgbatch_c1"])

        self.assertTrue(results[0]["ok"])
        entry = next(e for e in BH.read_history()["batches"] if e["id"] == "msgbatch_c1")
        self.assertEqual(entry["status"], BH.STATUS_CANCELING)
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        ids = [b["id"] for b in state.get("batches", [])]
        self.assertNotIn("msgbatch_c1", ids)
        self.assertIn("msgbatch_c2", ids)

    def test_cancel_transport_failure_preserves_active_status(self):
        BH.upsert_history_entry(
            "msgbatch_c1", status=BH.STATUS_SUBMITTED, api_status="in_progress"
        )
        with (
            mock.patch.object(BH, "_client_for_entry", return_value=object()),
            mock.patch.object(
                BH,
                "provider_retrieve_batch",
                side_effect=TimeoutError("temporary outage"),
            ),
        ):
            results = BH.cancel_batches(["msgbatch_c1"])

        self.assertFalse(results[0]["ok"])
        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["status"], BH.STATUS_SUBMITTED)
        self.assertEqual(entry["api_status"], "in_progress")
        self.assertIn("cancel failed", entry["notes"])


class UsageTests(BatchHistoryTestBase):
    def test_openai_cache_writes_use_gpt_5_6_multiplier(self):
        usage = {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 1_000_000,
            "thinking_tokens": 0,
        }
        with mock.patch.object(
            BH,
            "getPricingConfig",
            return_value={"inputAPICost": 5.0, "outputAPICost": 30.0},
        ):
            cost = BH._price_usage(usage, "gpt-5.6-sol", "openai")

        self.assertEqual(cost, 3.125)

    def test_usage_sums_cache_and_thinking(self):
        BH.upsert_history_entry(
            "msgbatch_u",
            status=BH.STATUS_ENDED,
            model="claude-sonnet-4-5",
            custom_ids={"req-000000": "k"},
        )
        usage = SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_read_input_tokens=500,
            cache_creation_input_tokens=100,
            thinking_tokens=50,
        )
        msg = SimpleNamespace(content=[SimpleNamespace(text="ok")], usage=usage)
        row = SimpleNamespace(custom_id="req-000000", result=SimpleNamespace(type="succeeded", message=msg))
        client = mock.MagicMock()
        client.messages.batches.retrieve.return_value = SimpleNamespace(processing_status="ended")
        client.messages.batches.results.return_value = [row]

        with mock.patch.object(BH, "_get_anthropic_client", return_value=client):
            with mock.patch.object(BH, "getPricingConfig", return_value={"inputAPICost": 3.0, "outputAPICost": 15.0}):
                info = BH.usage_for_batch("msgbatch_u")

        u = info["usage"]
        self.assertEqual(u["input_tokens"], 1000)
        self.assertEqual(u["output_tokens"], 200)
        self.assertEqual(u["cache_read_input_tokens"], 500)
        self.assertEqual(u["cache_creation_input_tokens"], 100)
        self.assertEqual(u["thinking_tokens"], 50)
        self.assertIsInstance(info["actual_cost"], float)
        self.assertGreater(info["actual_cost"], 0)
        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["usage"]["thinking_tokens"], 50)

    def test_usage_uses_client_resolved_from_history_entry(self):
        BH.upsert_history_entry(
            "batch-saved-key",
            provider="openai",
            key_name="Old Account",
            status=BH.STATUS_ENDED,
            model="gpt-test",
            custom_ids={"req-1": "cache-1"},
        )
        client = object()
        with (
            mock.patch.object(BH, "_client_for_entry", return_value=client) as resolver,
            mock.patch.object(
                BH,
                "provider_retrieve_batch",
                return_value={"api_status": "completed", "ended": True},
            ),
            mock.patch.object(
                BH,
                "download_batch_results",
                return_value=({"cache-1": {"text": "ok"}}, [], {"input_tokens": 1}),
            ) as download,
            mock.patch.object(BH, "_price_usage", return_value=0.01),
        ):
            BH.usage_for_batch("batch-saved-key")

        resolver.assert_called_once()
        self.assertEqual(download.call_args.kwargs["client"], client)


class SplitFetchAccountingTests(BatchHistoryTestBase):
    def test_each_split_records_only_its_own_usage_and_cost(self):
        batches = [
            {"id": "batch-1", "provider": "openai", "custom_ids": {"r1": "k1"}},
            {"id": "batch-2", "provider": "openai", "custom_ids": {"r2": "k2"}},
        ]
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {"status": "submitted", "model": "gpt-test", "provider": "openai", "batches": batches},
        )
        for item in batches:
            BH.upsert_history_entry(
                item["id"], provider="openai", model="gpt-test",
                key_name="Original Account",
                custom_ids=item["custom_ids"],
            )
        T._write_batch_file(
            T.BATCH_RESULTS_FILE,
            {"stale-key": {"text": "old model output"}},
        )

        clients = []
        saved_client = object()

        def download(batch_id, _custom_ids, **_kwargs):
            clients.append(_kwargs.get("client"))
            tokens = 10 if batch_id == "batch-1" else 30
            key = "k1" if batch_id == "batch-1" else "k2"
            return ({key: {"text": "ok"}}, [], {"input_tokens": tokens})

        with (
            mock.patch.object(BH, "_client_for_entry", return_value=saved_client),
            mock.patch.object(BH, "download_batch_results", side_effect=download),
            mock.patch.object(
                BH, "_price_usage", side_effect=lambda usage, _model, _provider="anthropic": usage["input_tokens"] / 100
            ),
        ):
            T.fetchTranslationBatches()

        rows = {row["id"]: row for row in BH.read_history()["batches"]}
        self.assertEqual(rows["batch-1"]["usage"]["input_tokens"], 10)
        self.assertEqual(rows["batch-2"]["usage"]["input_tokens"], 30)
        self.assertEqual(rows["batch-1"]["actual_cost"], 0.1)
        self.assertEqual(rows["batch-2"]["actual_cost"], 0.3)
        self.assertEqual(clients, [saved_client, saved_client])
        results = T._read_batch_file(T.BATCH_RESULTS_FILE)
        self.assertEqual(set(results), {"k1", "k2"})
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(set(state.get("result_keys") or []), {"k1", "k2"})

    def test_gemini_fetch_uses_saved_key_for_native_file_download(self):
        batch = {
            "id": "gemini-batch",
            "provider": "gemini",
            "key_name": "Original Gemini",
            "custom_ids": {"req-1": "key-1"},
        }
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "status": "submitted",
                "run_id": "translation-gemini",
                "model": "gemini-test",
                "provider": "gemini",
                "batches": [batch],
            },
        )
        sdk_client = object()
        files_client = object()
        with (
            mock.patch.object(BH, "client_for_batch", return_value=sdk_client),
            mock.patch.object(
                BH, "google_client_for_batch", return_value=files_client
            ) as google_resolver,
            mock.patch.object(
                BH, "download_batch_results",
                return_value=({"key-1": {"text": "ok"}}, [], {}),
            ) as download,
        ):
            T.fetchTranslationBatches()

        google_resolver.assert_called_once_with("gemini-batch", "Original Gemini")
        self.assertIs(download.call_args.kwargs["client"], sdk_client)
        self.assertIs(download.call_args.kwargs["google_client"], files_client)


class BatchEstimateTests(BatchHistoryTestBase):
    def test_openai_automatic_prefix_cache_is_estimated_separately(self):
        shared = "shared prompt token " * 1400
        for number in range(2):
            T.queue_batch_request(
                f'{{"Line1":"{number}"}}',
                "English",
                {
                    "model": "gpt-5.6-terra",
                    "messages": [
                        {"role": "system", "content": shared},
                        {"role": "user", "content": f"request {number}"},
                    ],
                },
                provider="openai",
            )
        T.flush_batch_queue()

        with mock.patch.object(
            T,
            "getPricingConfig",
            return_value={"inputAPICost": 2.0, "outputAPICost": 12.0},
        ):
            estimate = T.estimateBatchCost()

        self.assertEqual(estimate["cache_kind"], "automatic")
        self.assertTrue(estimate["uses_prompt_cache"])
        self.assertGreaterEqual(estimate["cache_write_tokens"], 1024)
        self.assertGreaterEqual(estimate["cache_read_tokens"], 1024)
        self.assertLess(
            estimate["batch_cached_cost"],
            estimate["batch_nocache_cost"],
        )


class ActivateResumeTests(BatchHistoryTestBase):
    def test_activate_submitted_restores_state(self):
        custom_ids = {"req-000000": "k"}
        BH.upsert_history_entry(
            "msgbatch_act",
            status=BH.STATUS_SUBMITTED,
            custom_ids=custom_ids,
            model="claude-sonnet-4-5",
            file_set=["a.json"],
        )
        state = BH.activate_for_resume("msgbatch_act")
        self.assertEqual(state, "submitted")
        disk = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(disk["batches"][0]["id"], "msgbatch_act")
        self.assertEqual(disk["batches"][0]["custom_ids"], custom_ids)

    def test_activate_submitted_restores_all_splits_in_the_run(self):
        for batch_id, cache_key in (
            ("batch-split-1", "key-1"),
            ("batch-split-2", "key-2"),
        ):
            BH.upsert_history_entry(
                batch_id,
                status=BH.STATUS_SUBMITTED,
                provider="openai",
                model="gpt-test",
                run_id="translation-run-1",
                custom_ids={f"req-{batch_id[-1]}": cache_key},
            )

        self.assertEqual(BH.activate_for_resume("batch-split-2"), "submitted")

        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(state["run_id"], "translation-run-1")
        self.assertEqual(
            {item["id"] for item in state["batches"]},
            {"batch-split-1", "batch-split-2"},
        )

    def test_activate_submitted_does_not_merge_an_unrelated_active_run(self):
        BH.upsert_history_entry(
            "batch-history",
            status=BH.STATUS_SUBMITTED,
            run_id="translation-history",
            custom_ids={"req-h": "history-key"},
        )
        active_state = {
            "status": "submitted",
            "run_id": "translation-active",
            "model": "active-model",
            "batches": [{"id": "batch-active", "custom_ids": {"req-a": "active-key"}}],
        }
        T._write_batch_file(T.BATCH_STATE_FILE, active_state)

        with self.assertRaisesRegex(ValueError, "Another translation batch run"):
            BH.activate_for_resume("batch-history")

        self.assertEqual(T._read_batch_file(T.BATCH_STATE_FILE), active_state)

    def test_activate_fetched_does_not_relabel_another_batch_results(self):
        BH.upsert_history_entry(
            "batch-b",
            status=BH.STATUS_FETCHED,
            custom_ids={"req-1": "shared-cache-key"},
            model="model-b",
        )
        T._write_batch_file(
            T.BATCH_RESULTS_FILE,
            {"shared-cache-key": {"text": "model A result"}},
        )
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "status": "fetched",
                "batch_ids": ["batch-a"],
                "result_keys": ["shared-cache-key"],
            },
        )

        with mock.patch.object(BH, "redownload_batch") as redownload:
            state = BH.activate_for_resume("batch-b")

        self.assertEqual(state, "fetched")
        redownload.assert_called_once_with("batch-b")

    def test_activate_fetched_reuses_explicitly_owned_results(self):
        BH.upsert_history_entry(
            "batch-b",
            status=BH.STATUS_FETCHED,
            custom_ids={"req-1": "shared-cache-key"},
            model="model-b",
        )
        T._write_batch_file(
            T.BATCH_RESULTS_FILE,
            {"shared-cache-key": {"text": "model B result"}},
        )
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {
                "status": "fetched",
                "batch_ids": ["batch-b"],
                "result_keys": ["shared-cache-key"],
            },
        )

        with mock.patch.object(BH, "redownload_batch") as redownload:
            state = BH.activate_for_resume("batch-b")

        self.assertEqual(state, "fetched")
        redownload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
