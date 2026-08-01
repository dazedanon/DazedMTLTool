#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for durable batch history and spend-safe ops."""

from __future__ import annotations

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
            "HISTORY": BH.BATCH_HISTORY_FILE,
            "results_mem": T._batch_results,
            "pending": dict(T._batch_queue_pending),
        }
        T.BATCH_QUEUE_FILE = tmp / "batch_requests.json"
        T.BATCH_STATE_FILE = tmp / "batch_state.json"
        T.BATCH_RESULTS_FILE = tmp / "batch_results.json"
        T.BATCH_LOCK_FILE = tmp / "batch_files.lock"
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

    def test_submitted_when_state_has_batches(self):
        T._write_batch_file(
            T.BATCH_STATE_FILE,
            {"batches": [{"id": "msgbatch_1", "custom_ids": {"req-000000": "k1"}}]},
        )
        self.assertEqual(T.batchRunState(), "submitted")

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


class ProviderSubmissionTests(BatchHistoryTestBase):
    def test_openai_submission_persists_provider_and_recovery_map(self):
        T.queue_batch_request(
            '{"Line1":"猫"}',
            "English",
            {"model": "gpt-5.6-terra", "messages": []},
            provider="openai",
        )
        T.flush_batch_queue()

        with mock.patch(
            "util.batch_providers.submit_batch",
            return_value={"id": "batch_openai_1", "input_file_id": "file_1"},
        ) as submit:
            ids = T.submitTranslationBatches(file_set=["Map001.json"])

        self.assertEqual(ids, ["batch_openai_1"])
        self.assertEqual(submit.call_args.args[0], "openai")
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(state["provider"], "openai")
        self.assertEqual(state["batches"][0]["provider"], "openai")
        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["provider"], "openai")
        self.assertTrue(entry["custom_ids"])


class RedownloadTests(BatchHistoryTestBase):
    def test_redownload_rebuilds_results_from_custom_ids(self):
        custom_ids = {"req-000000": "keyA", "req-000001": "keyB"}
        BH.upsert_history_entry(
            "msgbatch_rd",
            status=BH.STATUS_ENDED,
            model="claude-sonnet-4-5",
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

        with mock.patch.object(BH, "_get_anthropic_client", return_value=client):
            with mock.patch.object(BH, "getPricingConfig", return_value={"inputAPICost": 3.0, "outputAPICost": 15.0}):
                info = BH.redownload_batch("msgbatch_rd")

        self.assertEqual(info["succeeded"], 2)
        results = T._read_batch_file(T.BATCH_RESULTS_FILE)
        self.assertIn("keyA", results)
        self.assertIn("keyB", results)
        self.assertEqual(results["keyA"]["text"], '{"Line1":"Hi"}')
        state = T._read_batch_file(T.BATCH_STATE_FILE)
        self.assertEqual(state.get("status"), "fetched")
        self.assertEqual(T.batchRunState(), "fetched")
        entry = BH.read_history()["batches"][0]
        self.assertEqual(entry["status"], BH.STATUS_FETCHED)
        self.assertEqual(entry["custom_ids"], custom_ids)


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


class UsageTests(BatchHistoryTestBase):
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


if __name__ == "__main__":
    unittest.main()
