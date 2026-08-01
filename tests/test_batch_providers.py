#!/usr/bin/env python3
"""Provider-neutral Batch API adapter tests."""

from __future__ import annotations

import json
import gc
import unittest
import weakref
from types import SimpleNamespace
from unittest import mock

import util.batch_providers as BP
import util.translation as T


class _OpenAIFiles:
    def __init__(self, output=""):
        self.output = output
        self.uploaded = ""

    def create(self, *, file, purpose):
        self.uploaded = file.read().decode("utf-8")
        self.purpose = purpose
        return SimpleNamespace(id="file-input")

    def content(self, _file_id):
        return SimpleNamespace(text=self.output)


class _Batches:
    def __init__(self, batch):
        self.batch = batch
        self.created = None

    def create(self, **kwargs):
        self.created = kwargs
        return SimpleNamespace(id="batch-1")

    def retrieve(self, _batch_id):
        return self.batch

    def cancel(self, _batch_id):
        return SimpleNamespace(status="cancelling")


class BatchProviderDetectionTests(unittest.TestCase):
    def test_detects_native_routes_only(self):
        self.assertEqual(BP.detect_batch_provider("claude-sonnet-4-6", ""), "anthropic")
        self.assertEqual(
            BP.detect_batch_provider("gpt-5.6-terra", "https://api.openai.com/v1", "openai"),
            "openai",
        )
        self.assertEqual(
            BP.detect_batch_provider("gemini-3.1-pro", "", "gemini"), "gemini"
        )
        self.assertIsNone(
            BP.detect_batch_provider("gpt-5.6-terra", "https://proxy.example/v1", "openai")
        )

    def test_openai_builder_preserves_live_payload_features(self):
        with mock.patch.dict("os.environ", {}, clear=False):
            params = T.buildOpenAIRequest(
                "system", '{"Line1":"猫"}', ["prior"], 0.05, "json",
                "gpt-5.6-terra", 1, vocab_text="\n猫 (Cat)", api_provider="openai",
            )
        self.assertEqual(params["reasoning_effort"], "none")
        self.assertEqual(params["response_format"]["type"], "json_schema")
        self.assertIn("猫 (Cat)", params["messages"][0]["content"])
        self.assertTrue(any(m.get("content") == "prior" for m in params["messages"]))


class OpenAIBatchAdapterTests(unittest.TestCase):
    def test_submit_uploads_official_jsonl_shape(self):
        files = _OpenAIFiles()
        batches = _Batches(SimpleNamespace())
        client = SimpleNamespace(files=files, batches=batches)
        result = BP.submit_batch(
            "openai",
            [{"custom_id": "req-1", "params": {"model": "gpt-5.6-terra", "messages": []}}],
            client=client,
        )
        row = json.loads(files.uploaded)
        self.assertEqual(row["method"], "POST")
        self.assertEqual(row["url"], "/v1/chat/completions")
        self.assertEqual(row["custom_id"], "req-1")
        self.assertEqual(files.purpose, "batch")
        self.assertEqual(batches.created["completion_window"], "24h")
        self.assertEqual(result["input_file_id"], "file-input")

    def test_status_and_result_are_normalized(self):
        output = json.dumps({
            "custom_id": "req-1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": '{"Line1":"Cat"}'}}],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 20,
                        "prompt_tokens_details": {"cached_tokens": 40},
                    },
                },
            },
            "error": None,
        }) + "\n"
        batch = SimpleNamespace(
            status="completed", output_file_id="file-out", error_file_id=None,
            request_counts=SimpleNamespace(total=1, completed=1, failed=0),
        )
        client = SimpleNamespace(files=_OpenAIFiles(output), batches=_Batches(batch))
        status = BP.retrieve_batch("openai", "batch-1", client=client)
        results, errors, usage = BP.download_results(
            "openai", "batch-1", {"req-1": "cache-key"}, client=client
        )
        self.assertTrue(status["ended"])
        self.assertEqual(status["counts"]["succeeded"], 1)
        self.assertFalse(errors)
        self.assertEqual(results["cache-key"]["text"], '{"Line1":"Cat"}')
        self.assertEqual(usage["cache_read_input_tokens"], 40)
        self.assertEqual(usage["input_tokens"], 60)

    def test_cancel_uses_provider_batch_endpoint(self):
        batches = _Batches(SimpleNamespace())
        result = BP.cancel_batch(
            "openai", "batch-1", client=SimpleNamespace(batches=batches)
        )
        self.assertEqual(result["api_status"], "cancelling")


class GeminiBatchAdapterTests(unittest.TestCase):
    def test_submit_uses_google_file_upload_and_materializes_extra_body(self):
        uploaded = {}

        class Files:
            def upload(self, *, file, config):
                with open(file, "r", encoding="utf-8") as stream:
                    uploaded["row"] = json.loads(stream.read())
                uploaded["config"] = config
                return SimpleNamespace(name="files/gemini-input")

        google_client = SimpleNamespace(files=Files())
        batches = _Batches(SimpleNamespace())
        openai_client = SimpleNamespace(batches=batches)
        params = {
            "model": "models/gemini-3.1-pro",
            "messages": [],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "translation_response",
                    "strict": True,
                    "schema": {"type": "object"},
                },
            },
            "extra_body": {"google": {"thinking_config": {"thinking_budget": 0}}},
        }
        with mock.patch.object(BP, "_google_client", return_value=google_client):
            result = BP.submit_batch(
                "gemini", [{"custom_id": "req-1", "params": params}], client=openai_client
            )
        body = uploaded["row"]["body"]
        self.assertNotIn("extra_body", body)
        self.assertEqual(body["model"], "gemini-3.1-pro")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(body["google"]["thinking_config"]["thinking_budget"], 0)
        self.assertEqual(result["input_file_id"], "files/gemini-input")

    def test_download_keeps_google_client_alive_until_request_finishes(self):
        class Files:
            def __init__(self):
                self.owner = None

            def download(self, *, file):
                gc.collect()
                if self.owner() is None:
                    raise RuntimeError("Cannot send a request, as the client has been closed.")
                self.file = file
                return b'{"custom_id":"req-1"}\n'

        class GoogleClient:
            def __init__(self):
                self.files = Files()
                self.files.owner = weakref.ref(self)

        with mock.patch.object(BP, "_google_client", side_effect=GoogleClient):
            text = BP._download_file_text("gemini", "files/gemini-output")

        self.assertEqual(text, '{"custom_id":"req-1"}\n')

    def test_camel_case_usage_and_hidden_thinking_are_counted(self):
        output = json.dumps({
            "custom_id": "req-1",
            "response": {
                "status_code": 200,
                "body": {
                    "choices": [{"message": {"content": '{"Line1":"Cat"}'}}],
                    "usage": {
                        "promptTokens": 100,
                        "completionTokens": 20,
                        "totalTokens": 155,
                    },
                },
            },
        }) + "\n"
        batch = SimpleNamespace(
            status="completed", output_file_id="files/out", error_file_id=None,
            request_counts=SimpleNamespace(total=1, completed=1, failed=0),
        )
        client = SimpleNamespace(files=_OpenAIFiles(), batches=_Batches(batch))

        with mock.patch.object(
            BP,
            "_download_file_text",
            side_effect=lambda _provider, file_id, **_kwargs: output if file_id else "",
        ):
            _results, errors, usage = BP.download_results(
                "gemini", "batch-1", {"req-1": "cache-key"}, client=client
            )

        self.assertFalse(errors)
        self.assertEqual(usage["input_tokens"], 100)
        self.assertEqual(usage["output_tokens"], 20)
        self.assertEqual(usage["thinking_tokens"], 35)


if __name__ == "__main__":
    unittest.main()
