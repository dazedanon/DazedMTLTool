#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for Anthropic content-block text extraction."""

import unittest
from types import SimpleNamespace

from util.translation import _anthropic_content_text


class AnthropicContentTextTests(unittest.TestCase):
    def test_extracts_text_from_supported_content_shapes(self):
        thinking = SimpleNamespace(type="thinking", thinking="internal notes")
        cases = (
            ("none", None, ""),
            ("empty", [], ""),
            (
                "text only",
                [SimpleNamespace(type="text", text='{"0":"Hello"}')],
                '{"0":"Hello"}',
            ),
            (
                "thinking before text",
                [thinking, SimpleNamespace(type="text", text='{"0":"Alice"}')],
                '{"0":"Alice"}',
            ),
        )
        for label, content, expected in cases:
            with self.subTest(label):
                self.assertEqual(_anthropic_content_text(content), expected)


if __name__ == "__main__":
    unittest.main()
