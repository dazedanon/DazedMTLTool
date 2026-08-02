#!/usr/bin/env python3
"""Regression tests for typed translation request context."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import util.translation as T


class DebugRequestLoggingTests(unittest.TestCase):
    """Exact prompt payloads stay private by default and bounded when enabled."""

    def test_request_payload_logging_is_opt_in(self):
        with tempfile.TemporaryDirectory() as raw:
            original_cwd = Path.cwd()
            try:
                os.chdir(raw)
                with (
                    mock.patch.dict(os.environ, {}, clear=True),
                    mock.patch.object(T, "DEBUG", False),
                ):
                    T._write_request_debug_log(
                        "openai", {"messages": [{"content": "private text"}]}, None
                    )
            finally:
                os.chdir(original_cwd)

            self.assertFalse((Path(raw) / "log" / "request_debug.log").exists())

    def test_enabled_debug_logs_rotate_to_bounded_backups(self):
        with tempfile.TemporaryDirectory() as raw:
            original_cwd = Path.cwd()
            try:
                os.chdir(raw)
                with (
                    mock.patch.dict(os.environ, {"debugRequestLogs": "true"}, clear=True),
                    mock.patch.object(T, "DEBUG_LOG_MAX_BYTES", 128),
                    mock.patch.object(T, "DEBUG_LOG_BACKUP_COUNT", 2),
                ):
                    for index in range(5):
                        T._write_request_debug_log(
                            "openai", {"request": index, "text": "x" * 80}, None
                        )
            finally:
                os.chdir(original_cwd)

            path = Path(raw) / "log" / "request_debug.log"
            self.assertTrue(path.is_file())
            self.assertTrue(path.with_name("request_debug.log.1").is_file())
            self.assertTrue(path.with_name("request_debug.log.2").is_file())
            self.assertFalse(path.with_name("request_debug.log.3").exists())


class RequestContextSerializationTests(unittest.TestCase):
    @staticmethod
    def _content_text(content):
        if isinstance(content, str):
            return content
        return "\n\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict)
        )

    def test_openai_source_context_is_not_assistant_history(self):
        params = T.buildOpenAIRequest(
            "Translate Japanese to English.",
            '{"Line1":"次の行"}',
            ['果歩 "前の行"'],
            0.0,
            "json",
            "gpt-5.6-terra",
            1,
            api_provider="openai",
            context_kind=T.CONTEXT_SOURCE,
        )

        messages = params["messages"]
        context = next(
            item for item in messages
            if "Preceding Japanese Source Context" in str(item.get("content"))
        )
        self.assertEqual(context["role"], "user")
        self.assertIn("glossary is authoritative", context["content"])
        self.assertFalse(any(
            item["role"] == "assistant" and "果歩" in str(item.get("content"))
            for item in messages
        ))
        self.assertFalse(any(
            "Translation History" in str(item.get("content")) for item in messages
        ))

    def test_claude_source_context_is_labeled_untranslated(self):
        params = T.buildClaudeRequest(
            "Translate Japanese to English.",
            '{"Line1":"次の行"}',
            ['果歩 "前の行"'],
            "json",
            "claude-sonnet-4-6",
            1,
            context_kind=T.CONTEXT_SOURCE,
        )

        context = params["messages"][0]
        self.assertEqual(context["role"], "user")
        self.assertIn("Preceding Japanese Source Context", context["content"])
        self.assertIn("untranslated", context["content"])
        self.assertNotIn("Translation History", context["content"])

    def test_default_context_is_untranslated_source_not_assistant_history(self):
        params = T.buildOpenAIRequest(
            "Translate Japanese to English.",
            '{"Line1":"次の行"}',
            ['果歩 "前の行"'],
            0.0,
            "json",
            "gpt-5.6-terra",
            1,
            api_provider="openai",
        )

        self.assertTrue(any(
            item["role"] == "user"
            and "Preceding Japanese Source Context" in str(item.get("content"))
            for item in params["messages"]
        ))
        self.assertFalse(any(
            item["role"] == "assistant" and "果歩" in str(item.get("content"))
            for item in params["messages"]
        ))

    def test_explicit_request_instructions_remain_separate_from_source(self):
        params = T.buildOpenAIRequest(
            "Translate Japanese to English.",
            '{"Line1":"短い名前"}',
            "Keep the translation brief.",
            0.0,
            "json",
            "gpt-5.6-terra",
            1,
            api_provider="openai",
            context_kind=T.CONTEXT_INSTRUCTIONS,
        )

        context = params["messages"][1]
        self.assertEqual(context["role"], "user")
        self.assertIn("Request Instructions:", context["content"])
        self.assertNotIn("Japanese Source Context", context["content"])

    def test_provider_request_can_carry_instructions_and_source_together(self):
        params = T.buildOpenAIRequest(
            "Translate Japanese to English.",
            '{"Line1":"次の行"}',
            ['果歩 "前の行"'],
            0.0,
            "json",
            "gpt-5.6-terra",
            1,
            api_provider="openai",
            request_instructions="Keep every line gender-neutral.",
        )

        contents = [str(item.get("content")) for item in params["messages"]]
        self.assertTrue(any("Request Instructions:" in item for item in contents))
        self.assertTrue(any(
            "Preceding Japanese Source Context" in item for item in contents
        ))

        claude = T.buildClaudeRequest(
            "Translate Japanese to English.",
            '{"Line1":"次の行"}',
            ['果歩 "前の行"'],
            "json",
            "claude-sonnet-4-6",
            1,
            request_instructions="Keep every line gender-neutral.",
        )
        claude_contents = [
            str(item.get("content")) for item in claude["messages"]
        ]
        self.assertTrue(any(
            "Request Instructions:" in item for item in claude_contents
        ))
        self.assertTrue(any(
            "Preceding Japanese Source Context" in item
            for item in claude_contents
        ))

    def test_claude_and_openai_share_the_same_logical_translation_prompt(self):
        kwargs = {
            "system": "Translate Japanese to English.",
            "user": '{"Line1":"次の行"}',
            "history": ['果歩 "前の行"'],
            "formatType": "json",
            "numLines": 1,
            "vocab_text": "Relevant Vocabulary:\n果歩 (Kaho)",
            "context_kind": T.CONTEXT_SOURCE,
            "request_instructions": "Keep every line gender-neutral.",
        }
        claude = T.buildClaudeRequest(
            model="claude-sonnet-4-6", **kwargs
        )
        openai = T.buildOpenAIRequest(
            model="gpt-5.6-terra", penalty=0.0,
            api_provider="openai", **kwargs
        )

        self.assertEqual(
            self._content_text(claude["system"]),
            self._content_text(openai["messages"][0]["content"]),
        )
        self.assertEqual(claude["messages"], openai["messages"][1:])
        self.assertFalse(any(
            message["role"] == "assistant"
            for message in claude["messages"] + openai["messages"][1:]
        ))
        self.assertIn("Relevant Vocabulary", self._content_text(claude["system"]))

    def test_batch_split_marks_preceding_source_as_source_context(self):
        config = T.TranslationConfig(
            model="claude-sonnet-4-6",
            prompt="Translate Japanese to English.",
            vocab="",
            batchSize=2,
        )
        captured = []

        def capture(_system, _user, history, *_args, **kwargs):
            captured.append((
                history,
                kwargs.get("context_kind"),
                kwargs.get("request_instructions"),
            ))
            return {"model": config.model, "messages": []}

        with (
            mock.patch.object(T, "get_batch_phase", return_value="collect"),
            mock.patch.object(T, "getBatchProvider", return_value="anthropic"),
            mock.patch.object(T, "peek_cached_translation", return_value=None),
            mock.patch.object(T, "buildClaudeRequest", side_effect=capture),
            mock.patch.object(T, "queue_batch_request"),
            mock.patch.object(T, "flush_batch_queue"),
            mock.patch.object(T, "save_cache"),
        ):
            T.translateAI(
                ['果歩 "一"', 'カミナ "二"', '凛 "三"'], [], config
            )

        self.assertEqual(captured[0], ([], T.CONTEXT_SOURCE, []))
        self.assertEqual(
            captured[1],
            (['果歩 "一"', 'カミナ "二"'], T.CONTEXT_SOURCE, []),
        )

    def test_scalar_instruction_persists_across_every_batch_chunk(self):
        config = T.TranslationConfig(
            model="claude-sonnet-4-6",
            prompt="Translate Japanese to English.",
            vocab="",
            batchSize=2,
        )
        captured = []

        def capture(_system, _user, history, *_args, **kwargs):
            captured.append((history, kwargs.get("request_instructions")))
            return {"model": config.model, "messages": []}

        with (
            mock.patch.object(T, "get_batch_phase", return_value="collect"),
            mock.patch.object(T, "getBatchProvider", return_value="anthropic"),
            mock.patch.object(T, "peek_cached_translation", return_value=None),
            mock.patch.object(T, "buildClaudeRequest", side_effect=capture),
            mock.patch.object(T, "queue_batch_request"),
            mock.patch.object(T, "flush_batch_queue"),
            mock.patch.object(T, "save_cache"),
        ):
            T.translateAI(
                ["一行目", "二行目", "三行目"],
                "Keep every line gender-neutral.",
                config,
            )

        self.assertEqual(captured, [
            ([], ["Keep every line gender-neutral."]),
            (["一行目", "二行目"], ["Keep every line gender-neutral."]),
        ])

    def test_live_split_also_uses_preceding_japanese_source(self):
        config = T.TranslationConfig(
            model="gpt-5.6-terra",
            prompt="Translate Japanese to English.",
            vocab="",
            batchSize=2,
        )
        captured = []

        def translate(_system, _user, history, *_args, **kwargs):
            captured.append((
                history,
                kwargs.get("context_kind"),
                kwargs.get("request_instructions"),
            ))
            line_count = _args[3]
            output = {
                f"Line{index}": f"Translated line {index}"
                for index in range(1, line_count + 1)
            }
            return T._AnthropicCompat(
                json.dumps(output), 0, 0, 0, 0
            )

        with (
            mock.patch.object(T, "get_batch_phase", return_value=None),
            mock.patch.object(T, "getBatchProvider", return_value=None),
            mock.patch.object(T, "get_cached_translation", return_value=None),
            mock.patch.object(T, "translateText", side_effect=translate),
            mock.patch.object(T, "cache_translation"),
            mock.patch.object(T, "save_cache"),
        ):
            T.translateAI(
                ['果歩 "一"', 'カミナ "二"', '凛 "三"'], [], config
            )

        self.assertEqual(captured[0], ([], T.CONTEXT_SOURCE, []))
        self.assertEqual(
            captured[1],
            (['果歩 "一"', 'カミナ "二"'], T.CONTEXT_SOURCE, []),
        )

    def test_legacy_scalar_context_is_inferred_as_request_instructions(self):
        config = T.TranslationConfig(
            model="gpt-5.6-terra",
            prompt="Translate Japanese to English.",
            vocab="",
        )
        captured = []

        def translate(_system, _user, history, *_args, **kwargs):
            captured.append((
                history,
                kwargs.get("context_kind"),
                kwargs.get("request_instructions"),
            ))
            return T._AnthropicCompat('{"Line1":"Short name"}', 0, 0, 0, 0)

        with (
            mock.patch.object(T, "get_batch_phase", return_value=None),
            mock.patch.object(T, "getBatchProvider", return_value=None),
            mock.patch.object(T, "get_cached_translation", return_value=None),
            mock.patch.object(T, "translateText", side_effect=translate),
            mock.patch.object(T, "cache_translation"),
            mock.patch.object(T, "save_cache"),
        ):
            T.translateAI("短い名前", "Keep the translation brief.", config)

        self.assertEqual(
            captured,
            [([], T.CONTEXT_SOURCE, ["Keep the translation brief."])],
        )

    def test_scalar_instruction_persists_across_every_live_chunk(self):
        config = T.TranslationConfig(
            model="gpt-5.6-terra",
            prompt="Translate Japanese to English.",
            vocab="",
            batchSize=2,
        )
        captured = []

        def translate(_system, _user, history, *_args, **kwargs):
            captured.append((history, kwargs.get("request_instructions")))
            line_count = _args[3]
            output = {
                f"Line{index}": f"Translated {index}"
                for index in range(1, line_count + 1)
            }
            return T._AnthropicCompat(json.dumps(output), 0, 0, 0, 0)

        with (
            mock.patch.object(T, "get_batch_phase", return_value=None),
            mock.patch.object(T, "getBatchProvider", return_value=None),
            mock.patch.object(T, "get_cached_translation", return_value=None),
            mock.patch.object(T, "translateText", side_effect=translate),
            mock.patch.object(T, "cache_translation"),
            mock.patch.object(T, "save_cache"),
        ):
            T.translateAI(
                ["一行目", "二行目", "三行目"],
                "Keep every line gender-neutral.",
                config,
            )

        self.assertEqual(captured, [
            ([], ["Keep every line gender-neutral."]),
            (["一行目", "二行目"], ["Keep every line gender-neutral."]),
        ])

    def test_combined_context_document_rolls_source_and_keeps_instructions(self):
        config = T.TranslationConfig(
            model="gpt-5.6-terra",
            prompt="Translate Japanese to English.",
            vocab="",
            batchSize=2,
        )
        captured = []

        def translate(_system, _user, history, *_args, **kwargs):
            captured.append((history, kwargs.get("request_instructions")))
            line_count = _args[3]
            output = {
                f"Line{index}": f"Translated {index}"
                for index in range(1, line_count + 1)
            }
            return T._AnthropicCompat(json.dumps(output), 0, 0, 0, 0)

        with (
            mock.patch.object(T, "get_batch_phase", return_value=None),
            mock.patch.object(T, "getBatchProvider", return_value=None),
            mock.patch.object(T, "get_cached_translation", return_value=None),
            mock.patch.object(T, "translateText", side_effect=translate),
            mock.patch.object(T, "cache_translation"),
            mock.patch.object(T, "save_cache"),
        ):
            T.translateAI(
                ["一行目", "二行目", "三行目"],
                {
                    "instructions": ["Translate these as dialogue choices."],
                    "source_items": ["導入の質問"],
                },
                config,
            )

        self.assertEqual(captured, [
            (["導入の質問"], ["Translate these as dialogue choices."]),
            (["一行目", "二行目"], ["Translate these as dialogue choices."]),
        ])

        # The legacy WOLF code-102 path must construct the same typed document
        # instead of embedding its Japanese previous line inside an instruction.
        import modules.wolf as wolf

        class _Progress:
            total = 0

            def refresh(self):
                return None

            def update(self, _amount):
                return None

        choice_contexts = []

        def engine_translate(engine_text, engine_context, *_args):
            if engine_text == ["はい", "いいえ"]:
                choice_contexts.append(engine_context)
            translated = (
                list(engine_text)
                if isinstance(engine_text, list)
                else engine_text
            )
            return [translated, [0, 0]]

        events = [
            {"code": 101, "stringArgs": ["前の台詞"]},
            {"code": 102, "stringArgs": ["はい", "いいえ"]},
        ]
        with (
            mock.patch.object(wolf, "translateAI", side_effect=engine_translate),
            mock.patch.multiple(
                wolf,
                CODE101=True,
                CODE102=True,
                CODE122=False,
                CODE150=False,
                CODE210=False,
                CODE250=False,
                CODE300=False,
                FIXTEXTWRAP=False,
            ),
        ):
            wolf.searchCodes(events, _Progress(), None, "Map001.json")

        self.assertTrue(choice_contexts)
        self.assertTrue(all(
            context == {
                "instructions": [
                    f"Reply with the {wolf.LANGUAGE} translation of the dialogue choice"
                ],
                "source_items": ["前の台詞"],
            }
            for context in choice_contexts
        ))


if __name__ == "__main__":
    unittest.main()
