"""The Image Text module must send one request per image.

Batching across images let a dense tutorial diagram's tone and vocabulary bleed
into a two-word menu tab, and one bad line poisoned strings from unrelated
files. These tests capture what each request actually contained.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("model", "gpt-4o-mini")
os.environ.setdefault("language", "English")


def _module():
    """Import the module late; it reads env and the prompt file at import."""
    import modules.imagetext as imagetext

    return imagetext


class GroupingTests(unittest.TestCase):
    def setUp(self):
        self.imagetext = _module()

    def _data(self):
        return {
            "format": "dazedtl-image-text",
            "images": [
                {
                    "image": "menu.png",
                    "regions": [
                        {"id": "a", "source": "はじめる", "target": ""},
                        {"id": "b", "source": "つづきから", "target": ""},
                    ],
                },
                {
                    "image": "tutorial.png",
                    "regions": [
                        {"id": "c", "source": "ここをクリック", "target": ""},
                        {"id": "d", "source": "already done", "target": "Done"},
                    ],
                },
            ],
        }

    def test_regions_are_grouped_by_image(self):
        grouped = self.imagetext._pending_by_image(self._data())
        self.assertEqual([name for name, _ in grouped], ["menu.png", "tutorial.png"])
        self.assertEqual([len(r) for _, r in grouped], [2, 1])

    def test_already_translated_regions_are_skipped(self):
        grouped = self.imagetext._pending_by_image(self._data())
        ids = [r["id"] for _, regions in grouped for r in regions]
        self.assertNotIn("d", ids)

    def test_an_image_with_nothing_pending_is_dropped_entirely(self):
        data = {"images": [{"image": "done.png",
                            "regions": [{"id": "x", "source": "a", "target": "A"}]}]}
        self.assertEqual(self.imagetext._pending_by_image(data), [])

    def test_a_dense_image_splits_within_itself(self):
        size = self.imagetext.GROUP_SIZE
        data = {"images": [{
            "image": "dense.png",
            "regions": [{"id": str(i), "source": f"文{i}", "target": ""}
                        for i in range(size + 3)],
        }]}
        grouped = self.imagetext._pending_by_image(data)
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(grouped[0][1]), size + 3)


class RequestIsolationTests(unittest.TestCase):
    """The real guarantee: capture every call and prove none spans two images."""

    def setUp(self):
        self.imagetext = _module()
        self.root = Path(tempfile.mkdtemp(prefix="imgtext-"))
        self.addCleanup(__import__("shutil").rmtree, self.root, True)
        (self.root / "files").mkdir()
        self.cwd = os.getcwd()
        os.chdir(self.root)
        self.addCleanup(os.chdir, self.cwd)

    def _write(self, data) -> str:
        (self.root / "files" / "image_text.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        return "image_text.json"

    def _run(self, data):
        calls = []

        def fake(sources, instruction, *args, **kwargs):
            calls.append((list(sources), instruction))
            return [[f"EN{i}" for i in range(len(sources))], [1, 1]]

        filename = self._write(data)
        with patch.object(self.imagetext, "translateAI", side_effect=fake):
            self.imagetext.ESTIMATE = ""
            result = self.imagetext.openFiles(filename)
        return calls, result[0]

    def test_each_request_covers_exactly_one_image(self):
        data = {"images": [
            {"image": "menu.png", "regions": [
                {"id": "a", "source": "はじめる", "target": ""},
                {"id": "b", "source": "つづき", "target": ""}]},
            {"image": "tutorial.png", "regions": [
                {"id": "c", "source": "ここをクリック", "target": ""}]},
            {"image": "shop.png", "regions": [
                {"id": "d", "source": "購入", "target": ""}]},
        ]}
        calls, _ = self._run(data)
        self.assertEqual(len(calls), 3, "expected one request per image")
        self.assertEqual([len(sources) for sources, _ in calls], [2, 1, 1])

    def test_each_request_names_its_image(self):
        data = {"images": [
            {"image": "menu.png", "regions": [{"id": "a", "source": "はじめる", "target": ""}]},
            {"image": "shop.png", "regions": [{"id": "b", "source": "購入", "target": ""}]},
        ]}
        calls, _ = self._run(data)
        self.assertIn("menu.png", calls[0][1])
        self.assertIn("shop.png", calls[1][1])
        # and must not mention the other one
        self.assertNotIn("shop.png", calls[0][1])

    def test_every_request_says_it_is_image_text(self):
        data = {"images": [
            {"image": "menu.png", "regions": [{"id": "a", "source": "はじめる", "target": ""}]},
        ]}
        calls, _ = self._run(data)
        instruction = calls[0][1].lower()
        self.assertIn("baked into", instruction)
        self.assertIn("same image", instruction)

    def test_a_dense_image_is_split_but_never_merged_with_a_neighbour(self):
        size = self.imagetext.GROUP_SIZE
        data = {"images": [
            {"image": "dense.png", "regions": [
                {"id": f"d{i}", "source": f"文{i}", "target": ""} for i in range(size + 2)]},
            {"image": "tiny.png", "regions": [{"id": "t", "source": "はい", "target": ""}]},
        ]}
        calls, _ = self._run(data)
        self.assertEqual(len(calls), 3)          # size, 2, then 1
        self.assertEqual([len(s) for s, _ in calls], [size, 2, 1])
        self.assertIn("part 1 of 2", calls[0][1])
        self.assertIn("part 2 of 2", calls[1][1])
        # the tiny image's request is its own and mentions only itself
        self.assertIn("tiny.png", calls[2][1])
        self.assertNotIn("dense.png", calls[2][1])

    def test_translations_land_on_the_right_regions(self):
        data = {"images": [
            {"image": "menu.png", "regions": [
                {"id": "a", "source": "はじめる", "target": ""},
                {"id": "b", "source": "つづき", "target": ""}]},
            {"image": "shop.png", "regions": [{"id": "c", "source": "購入", "target": ""}]},
        ]}
        _, out = self._run(data)
        self.assertEqual([r["target"] for r in out["images"][0]["regions"]], ["EN0", "EN1"])
        self.assertEqual(out["images"][1]["regions"][0]["target"], "EN0")

    def test_source_line_breaks_are_flattened_for_the_request(self):
        """The renderer re-wraps, so Japanese breaks must not reach the model."""
        data = {"images": [{"image": "a.png", "regions": [
            {"id": "a", "source": "一行目\n二行目", "target": ""}]}]}
        calls, out = self._run(data)
        self.assertEqual(calls[0][0], ["一行目 二行目"])
        # but the stored source keeps its breaks
        self.assertEqual(out["images"][0]["regions"][0]["source"], "一行目\n二行目")


if __name__ == "__main__":
    unittest.main()
