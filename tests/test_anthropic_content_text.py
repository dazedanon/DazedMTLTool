#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Anthropic content-block text extraction."""

import unittest
from types import SimpleNamespace

from util.translation import _anthropic_content_text


class AnthropicContentTextTests(unittest.TestCase):
    def test_empty_content(self):
        self.assertEqual(_anthropic_content_text(None), "")
        self.assertEqual(_anthropic_content_text([]), "")

    def test_text_block_only(self):
        content = [SimpleNamespace(type="text", text='{"0":"Hello"}')]
        self.assertEqual(_anthropic_content_text(content), '{"0":"Hello"}')

    def test_skips_thinking_block_without_text(self):
        # Mirrors Anthropic ThinkingBlock: has .thinking, no .text.
        thinking = SimpleNamespace(type="thinking", thinking="internal notes")
        text = SimpleNamespace(type="text", text='{"0":"Alice"}')
        self.assertEqual(_anthropic_content_text([thinking, text]), '{"0":"Alice"}')

    def test_accessing_first_block_text_would_fail(self):
        thinking = SimpleNamespace(type="thinking", thinking="notes")
        text = SimpleNamespace(type="text", text="ok")
        content = [thinking, text]
        with self.assertRaises(AttributeError):
            _ = content[0].text
        self.assertEqual(_anthropic_content_text(content), "ok")


if __name__ == "__main__":
    unittest.main()
