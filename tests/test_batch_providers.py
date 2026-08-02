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
from util.api_errors import concise_api_error


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
    def test_html_api_failure_is_reduced_to_plain_text(self):
        error = RuntimeError(
            "Error code: 404 - <!DOCTYPE html><html><body>Not Found</body></html>"
        )
        error.status_code = 404

        message = concise_api_error(error)

        self.assertIn("404", message)
        self.assertNotIn("<", message)

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
        system_content = params["messages"][0]["content"]
        self.assertTrue(any(
            "猫 (Cat)" in str(block.get("text"))
            for block in system_content
            if isinstance(block, dict)
        ))
        self.assertEqual(
            params["extra_body"]["prompt_cache_options"], {"mode": "explicit"}
        )
        batch_body = BP._openai_batch_body("openai", params)
        self.assertNotIn("extra_body", batch_body)
        self.assertEqual(
            batch_body["prompt_cache_options"], {"mode": "explicit"}
        )
        self.assertTrue(any(
            "Preceding Japanese Source Context" in str(m.get("content"))
            and "prior" in str(m.get("content"))
            for m in params["messages"]
        ))
        self.assertFalse(any(
            m.get("role") == "assistant" and "prior" in str(m.get("content"))
            for m in params["messages"]
        ))

    def test_keyless_custom_openai_client_uses_sdk_placeholder(self):
        with mock.patch.object(BP.openai, "OpenAI") as client_class:
            BP.get_client(
                "openai", api_key="", api_url="http://127.0.0.1:8000/v1"
            )
        client_class.assert_called_once_with(
            api_key="not-needed", base_url="http://127.0.0.1:8000/v1"
        )

    def test_client_can_disable_sdk_retries_for_owned_retry_policy(self):
        with mock.patch.object(BP.openai, "OpenAI") as client_class:
            BP.get_client(
                "openai",
                api_key="key",
                api_url="https://api.openai.com/v1",
                max_retries=0,
            )

        client_class.assert_called_once_with(
            api_key="key",
            base_url="https://api.openai.com/v1",
            max_retries=0,
        )

    def test_gemini_builder_and_batch_adapter_use_correct_extension_nesting(self):
        with mock.patch.dict(
            "os.environ", {"GEMINI_THINKING_BUDGET": "0"}, clear=False
        ):
            params = T.buildOpenAIRequest(
                "system", '{"Line1":"猫"}', [], 0, "json",
                "gemini-2.5-flash", 1, api_provider="gemini",
            )
        self.assertEqual(
            params["extra_body"]["extra_body"]["google"]
            ["thinking_config"]["thinking_budget"],
            0,
        )
        body = BP._openai_batch_body("gemini", params)
        self.assertNotIn("google", body)
        self.assertEqual(
            body["extra_body"]["google"]["thinking_config"]["thinking_budget"],
            0,
        )


class OpenAIBatchAdapterTests(unittest.TestCase):
    def test_live_request_returns_batch_compatible_result_shape(self):
        response = {
            "choices": [{"message": {"content": '{"Line1":"Cat"}'}}],
            "usage": {
                "prompt_tokens": 50,
                "completion_tokens": 10,
                "prompt_tokens_details": {
                    "cached_tokens": 20,
                    "cache_write_tokens": 15,
                },
            },
        }
        create = mock.Mock(return_value=response)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        result = BP.execute_live_request(
            "openai",
            {"model": "local", "messages": [], "response_format": {"type": "json_object"}},
            client=client,
        )
        self.assertEqual(result["text"], '{"Line1":"Cat"}')
        self.assertEqual(result["prompt_tokens"], 50)
        self.assertEqual(result["cache_read_input_tokens"], 20)
        self.assertEqual(result["cache_creation_input_tokens"], 15)

    def test_live_request_retries_only_schema_rejection(self):
        class SchemaRejected(Exception):
            status_code = 400

        response = {
            "choices": [{"message": {"content": '{"Line1":"Cat"}'}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 1},
        }
        create = mock.Mock(
            side_effect=[SchemaRejected("response_format json_schema unsupported"), response]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        BP.execute_live_request(
            "openai",
            {
                "model": "local",
                "messages": [],
                "response_format": {"type": "json_schema"},
            },
            client=client,
        )

        self.assertEqual(create.call_count, 2)
        self.assertEqual(
            create.call_args_list[1].kwargs["response_format"],
            {"type": "json_object"},
        )

    def test_live_request_does_not_retry_transport_failure(self):
        create = mock.Mock(side_effect=TimeoutError("connection timed out"))
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )

        with self.assertRaises(TimeoutError):
            BP.execute_live_request(
                "openai",
                {
                    "model": "local",
                    "messages": [],
                    "response_format": {"type": "json_schema"},
                },
                client=client,
            )

        self.assertEqual(create.call_count, 1)

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
                        "prompt_tokens_details": {
                            "cached_tokens": 40,
                            "cache_write_tokens": 30,
                        },
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
        self.assertEqual(usage["cache_creation_input_tokens"], 30)
        self.assertEqual(usage["input_tokens"], 30)

    def test_cancel_uses_provider_batch_endpoint(self):
        batches = _Batches(SimpleNamespace())
        result = BP.cancel_batch(
            "openai", "batch-1", client=SimpleNamespace(batches=batches)
        )
        self.assertEqual(result["api_status"], "cancelling")


class GeminiBatchAdapterTests(unittest.TestCase):
    def test_submit_uses_google_upload_and_preserves_gemini_extra_body(self):
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
            "extra_body": {
                "extra_body": {
                    "google": {"thinking_config": {"thinking_budget": 0}}
                }
            },
        }
        with mock.patch.object(BP, "_google_client", return_value=google_client):
            result = BP.submit_batch(
                "gemini", [{"custom_id": "req-1", "params": params}], client=openai_client
            )
        body = uploaded["row"]["body"]
        self.assertNotIn("google", body)
        self.assertEqual(body["model"], "gemini-3.1-pro")
        self.assertEqual(body["response_format"], {"type": "json_object"})
        self.assertEqual(
            body["extra_body"]["google"]["thinking_config"]["thinking_budget"], 0
        )
        self.assertEqual(result["input_file_id"], "files/gemini-input")

    def test_legacy_single_level_extension_never_becomes_top_level_google(self):
        body = BP._openai_batch_body("gemini", {
            "model": "gemini-3.6-flash",
            "messages": [],
            "extra_body": {
                "google": {"thinking_config": {"thinking_level": "minimal"}}
            },
        })
        self.assertNotIn("google", body)
        self.assertEqual(
            body["extra_body"]["google"]["thinking_config"]["thinking_level"],
            "minimal",
        )

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
