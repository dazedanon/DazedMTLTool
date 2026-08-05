"""Tests for the semi-manual image translation toolkit.

The mirror is redirected before anything imports ``exchange``: an export run
against a temporary fixture writes into DazedTL's real ``files/`` folder
otherwise, and once destroyed a real export the user was part-way through
translating. Redirecting is not enough on its own, so
``ExportGuardTests`` asserts it.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import tempfile
import importlib.util
import unittest
from pathlib import Path

_MIRROR = tempfile.mkdtemp(prefix="imgtl-test-files-")
os.environ["IMGTL_FILES_DIR"] = _MIRROR
atexit.register(shutil.rmtree, _MIRROR, True)

# The semi-manual image workflow's dependencies are downloaded on demand
# (util/imagetools/resources.py), so a checkout that has never opened it does
# not have them. Skip rather than fail: an ImportError here would read as
# "this branch broke the suite" on a tree where nothing is wrong.
if importlib.util.find_spec("cv2") is None:
    raise unittest.SkipTest(
        "semi-manual image extras are not installed - run "
        "python -m util.imagetools.resources --default"
    )

import numpy as np

from util.imagetools import exchange
from util.imagetools.geometry import Box
from util.imagetools.job import (
    CONFIRMED,
    ERROR,
    NEEDS_REVIEW,
    PENDING,
    TRANSLATED,
    ImageEntry,
    Job,
    TextBlock,
    apply_flags,
    review_flags,
)
from util.imagetools.ocr import (
    Block,
    Line,
    Reading,
    Word,
    rotated_box,
    worth_keeping,
)
from util.imagetools.ocr.rapid import group_lines


def block(text: str, x: int, y: int, w: int, h: int, angle: float = 0.0) -> TextBlock:
    return TextBlock("b" + text[:4], Box.from_xywh(x, y, w, h), text, "", angle, [])


class GeometryTests(unittest.TestCase):
    def test_box_coerces_numpy_integers(self):
        """np.int32 leaks in from OpenCV and json.dump refuses it."""
        box = Box(np.int32(1), np.int32(2), np.int32(5), np.int32(9))
        self.assertEqual([type(v) for v in box.as_tuple()], [int] * 4)
        json.dumps(box.as_xywh())

    def test_union_and_intersects(self):
        a, b = Box.from_xywh(0, 0, 10, 10), Box.from_xywh(5, 5, 10, 10)
        self.assertTrue(a.intersects(b))
        self.assertEqual(a.union(b).as_xywh(), [0, 0, 15, 15])
        self.assertFalse(a.intersects(Box.from_xywh(20, 20, 4, 4)))


class RotatedBoxTests(unittest.TestCase):
    """Lens reports extent along the text baseline, not along the image axes."""

    def test_upright_box_is_unchanged(self):
        box = rotated_box(50.0, 30.0, 100.0, 20.0, 0.0)
        self.assertEqual(box.as_xywh(), [0, 20, 100, 20])

    def test_quarter_turn_swaps_the_extent(self):
        # A 154x21 run of vertical text is 21 wide and 154 tall on screen.
        # Bounds are floored/ceiled outwards so a glyph is never clipped, so
        # each side may be a pixel over - the swap is what matters.
        box = rotated_box(100.0, 100.0, 154.0, 21.0, -90.0)
        self.assertAlmostEqual(box.w, 21, delta=1)
        self.assertAlmostEqual(box.h, 154, delta=1)
        self.assertGreater(box.h, box.w * 5)

    def test_the_naive_reading_would_be_wrong(self):
        box = rotated_box(100.0, 100.0, 154.0, 21.0, -90.0)
        self.assertNotEqual(box.as_xywh()[2:], [154, 21])


class ArtefactFilterTests(unittest.TestCase):
    def test_a_hairline_block_is_dropped(self):
        """Lens returns a 14x2 block containing '-' on one of the test images."""
        self.assertFalse(worth_keeping("-", Box.from_xywh(236, 141, 14, 2)))

    def test_real_text_is_kept(self):
        self.assertTrue(worth_keeping("当院オリジナル", Box.from_xywh(259, 28, 91, 14)))

    def test_blank_text_is_dropped(self):
        self.assertFalse(worth_keeping("   ", Box.from_xywh(0, 0, 100, 20)))


class LineGroupingTests(unittest.TestCase):
    """The offline fallback returns lines; paragraphs are grouped here."""

    def test_stacked_lines_of_one_size_become_one_block(self):
        lines = [
            Line("first line", Box.from_xywh(10, 10, 120, 16)),
            Line("second line", Box.from_xywh(10, 28, 118, 16)),
            Line("third line", Box.from_xywh(10, 46, 100, 16)),
        ]
        blocks = group_lines(lines)
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0].text, "first line\nsecond line\nthird line")
        self.assertEqual(blocks[0].box.as_xywh(), [10, 10, 120, 52])

    def test_a_heading_does_not_absorb_the_body(self):
        lines = [
            Line("HEADING", Box.from_xywh(10, 10, 140, 30)),
            Line("body text", Box.from_xywh(10, 44, 120, 14)),
        ]
        self.assertEqual(len(group_lines(lines)), 2)

    def test_a_far_apart_line_starts_a_new_block(self):
        lines = [
            Line("top", Box.from_xywh(10, 10, 100, 16)),
            Line("bottom", Box.from_xywh(10, 200, 100, 16)),
        ]
        self.assertEqual(len(group_lines(lines)), 2)

    def test_a_separate_column_is_not_merged(self):
        lines = [
            Line("left", Box.from_xywh(10, 10, 60, 16)),
            Line("right", Box.from_xywh(400, 28, 60, 16)),
        ]
        self.assertEqual(len(group_lines(lines)), 2)


class FlagTests(unittest.TestCase):
    def test_overlapping_blocks_are_flagged_on_both(self):
        entry = ImageEntry("a.png")
        entry.blocks = [block("one", 10, 10, 80, 20), block("two", 40, 15, 80, 20)]
        apply_flags(entry)
        self.assertIn("overlap", entry.blocks[0].flags)
        self.assertIn("overlap", entry.blocks[1].flags)

    def test_a_tidy_block_is_not_flagged(self):
        entry = ImageEntry("a.png")
        entry.blocks = [block("こんにちは", 10, 10, 90, 18)]
        apply_flags(entry)
        self.assertEqual(entry.blocks[0].flags, [])

    def test_tiny_and_single_character_blocks_are_flagged(self):
        entry = ImageEntry("a.png")
        entry.blocks = [block("x", 0, 0, 6, 5)]
        apply_flags(entry)
        self.assertIn("tiny", entry.blocks[0].flags)
        self.assertIn("single", entry.blocks[0].flags)

    def test_a_quarter_turn_is_not_treated_as_skew(self):
        entry = ImageEntry("a.png")
        entry.blocks = [block("縦書き", 0, 0, 20, 150, angle=-90.0)]
        apply_flags(entry)
        self.assertNotIn("skew", entry.blocks[0].flags)

    def test_an_odd_angle_is_flagged(self):
        entry = ImageEntry("a.png")
        entry.blocks = [block("slanted", 0, 0, 100, 40, angle=23.0)]
        apply_flags(entry)
        self.assertIn("skew", entry.blocks[0].flags)


class JobTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-job-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_round_trip_preserves_blocks_and_status(self):
        job = Job(self.root)
        job.sync(["a.png", "b.png"])
        entry = job.find("a.png")
        entry.blocks = [block("こんにちは世界", 10, 10, 200, 20)]
        entry.blocks[0].lines = [Line("こんにちは世界", Box.from_xywh(10, 10, 200, 20))]
        entry.status = CONFIRMED
        job.save()

        reloaded = Job.load(self.root)
        again = reloaded.find("a.png")
        self.assertEqual(again.status, CONFIRMED)
        self.assertEqual(again.blocks[0].source_text, "こんにちは世界")
        self.assertEqual(again.blocks[0].lines[0].text, "こんにちは世界")

    def test_sync_keeps_existing_review_work(self):
        """Re-scanning a folder must never discard blocks already reviewed."""
        job = Job(self.root)
        job.sync(["a.png"])
        job.find("a.png").blocks = [block("keep me", 0, 0, 50, 20)]
        job.find("a.png").status = CONFIRMED

        added, removed = job.sync(["a.png", "b.png"])
        self.assertEqual((added, removed), (1, 0))
        self.assertEqual(job.find("a.png").blocks[0].source_text, "keep me")
        self.assertEqual(job.find("a.png").status, CONFIRMED)

    def test_sync_drops_images_that_are_gone(self):
        job = Job(self.root)
        job.sync(["a.png", "b.png"])
        added, removed = job.sync(["a.png"])
        self.assertEqual((added, removed), (0, 1))
        self.assertEqual([e.relpath for e in job.images], ["a.png"])

    def test_sync_keeps_images_it_was_not_asked_about(self):
        """Opening a subset must not delete the rest of the job.

        The Images tab passes the *highlighted* rows, and treating that as the
        whole job destroyed six images' boxes, corrected text and confirmations
        the moment someone highlighted one image and pressed "Edit text...".
        An entry only leaves when its file has left the workspace.
        """
        for name in ("a.png", "b.png"):
            (self.root / name).write_bytes(b"not really a png")
        job = Job(self.root)
        job.sync(["a.png", "b.png"])
        job.find("b.png").blocks = [block("hours of review", 0, 0, 50, 20)]
        job.find("b.png").status = CONFIRMED

        added, removed = job.sync(["a.png"])
        self.assertEqual((added, removed), (0, 0))
        self.assertEqual(job.find("b.png").blocks[0].source_text, "hours of review")
        self.assertEqual(job.find("b.png").status, CONFIRMED)

    def test_adopting_a_reading_replaces_blocks_and_marks_for_review(self):
        job = Job(self.root)
        job.sync(["a.png"])
        entry = job.find("a.png")
        entry.status = PENDING
        reading = Reading(
            blocks=[Block("読み", Box.from_xywh(1, 2, 30, 12), 0.0,
                          [Line("読み", Box.from_xywh(1, 2, 30, 12))])],
            words=[Word("読み", Box.from_xywh(1, 2, 30, 12))],
            engine="lens",
        )
        entry.adopt(reading)
        self.assertEqual(entry.status, NEEDS_REVIEW)
        self.assertEqual(entry.engine, "lens")
        self.assertEqual(len(entry.blocks), 1)
        self.assertEqual(len(entry.words), 1)

    def test_a_saved_job_is_valid_json(self):
        job = Job(self.root)
        job.sync(["a.png"])
        job.find("a.png").blocks = [block("テスト", 0, 0, 40, 12)]
        path = job.save()
        json.loads(path.read_text(encoding="utf-8"))


class ExportGateTests(unittest.TestCase):
    """Only confirmed images may reach the translator. That is the whole point."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-exp-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.job = Job(self.root)
        self.job.sync(["a.png"])
        entry = self.job.find("a.png")
        entry.blocks = [block("こんにちは", 10, 10, 120, 18)]

    def test_an_unconfirmed_image_is_not_exported(self):
        self.job.find("a.png").status = NEEDS_REVIEW
        self.assertEqual(exchange.build(self.job)["images"], [])

    def test_a_pending_image_is_not_exported(self):
        self.job.find("a.png").status = PENDING
        self.assertEqual(exchange.build(self.job)["images"], [])

    def test_a_confirmed_image_is_exported_with_a_budget(self):
        self.job.find("a.png").status = CONFIRMED
        payload = exchange.build(self.job)
        self.assertEqual(len(payload["images"]), 1)
        region = payload["images"][0]["regions"][0]
        self.assertEqual(region["source"], "こんにちは")
        self.assertGreater(region["max_chars"], 0)
        self.assertEqual(region["orientation"], "horizontal")

    def test_a_skipped_block_is_left_out(self):
        entry = self.job.find("a.png")
        entry.status = CONFIRMED
        entry.blocks[0].skip = True
        self.assertEqual(exchange.build(self.job)["images"], [])

    def test_vertical_blocks_are_marked_vertical(self):
        entry = self.job.find("a.png")
        entry.status = CONFIRMED
        entry.blocks = [block("縦書き", 0, 0, 20, 150, angle=-90.0)]
        region = exchange.build(self.job)["images"][0]["regions"][0]
        self.assertEqual(region["orientation"], "vertical")


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-imp-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.job = Job(self.root)
        self.job.sync(["a.png"])
        entry = self.job.find("a.png")
        entry.status = CONFIRMED
        entry.blocks = [block("こんにちは", 10, 10, 120, 18)]
        self.block_id = entry.blocks[0].block_id

    def _write(self, target: str) -> Path:
        path = self.root / "hand.json"
        payload = exchange.build(self.job)
        payload["images"][0]["regions"][0]["target"] = target
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_translations_come_back_and_flip_the_status(self):
        result = exchange.read(self.job, self._write("Hello"))
        self.assertEqual(result.applied, 1)
        entry = self.job.find("a.png")
        self.assertEqual(entry.blocks[0].target_text, "Hello")
        self.assertEqual(entry.status, TRANSLATED)

    def test_a_translation_matching_the_source_is_skipped(self):
        """Re-rendering the same string in a different face looks worse."""
        exchange.read(self.job, self._write("こんにちは"))
        self.assertTrue(self.job.find("a.png").blocks[0].skip)

    def test_a_blank_translation_is_reported_not_applied(self):
        result = exchange.read(self.job, self._write("   "))
        self.assertEqual(result.applied, 0)
        self.assertEqual(len(result.empty), 1)
        self.assertEqual(self.job.find("a.png").blocks[0].target_text, "")

    def test_geometry_in_the_file_cannot_overwrite_the_job(self):
        """A model rewriting more than it was asked to must not move boxes."""
        path = self.root / "tampered.json"
        payload = exchange.build(self.job)
        region = payload["images"][0]["regions"][0]
        region["target"] = "Hello"
        region["box"] = [999, 999, 5, 5]
        region["source"] = "totally different"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        exchange.read(self.job, path)
        block_ = self.job.find("a.png").blocks[0]
        self.assertEqual(block_.box.as_xywh(), [10, 10, 120, 18])
        self.assertEqual(block_.source_text, "こんにちは")

    def test_an_unknown_id_is_reported_rather_than_raising(self):
        path = self.root / "stale.json"
        payload = exchange.build(self.job)
        payload["images"][0]["regions"][0]["id"] = "gone"
        payload["images"][0]["regions"][0]["target"] = "Hello"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        result = exchange.read(self.job, path)
        self.assertEqual(result.applied, 0)
        self.assertTrue(result.unknown)


class RebuildTests(unittest.TestCase):
    """A job that has lost images can be put back from its own export.

    The export holds the box, the corrected source and the translation for
    every block that ever left, which is enough to render - so a truncated job
    file is a recovery, not a re-review from scratch.
    """

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-reb-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        for name in ("a.png", "b.png"):
            (self.root / name).write_bytes(b"not really a png")
        self.job = Job(self.root)
        self.job.sync(["a.png", "b.png"])
        for name, text in (("a.png", "あいう"), ("b.png", "かきく")):
            entry = self.job.find(name)
            entry.status = CONFIRMED
            entry.blocks = [block(text, 10, 10, 120, 18)]
        self.payload = exchange.build(self.job)
        for image in self.payload["images"]:
            image["regions"][0]["target"] = "Hello"
        self.path = self.root / "export.json"
        self.path.write_text(
            json.dumps(self.payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_a_lost_image_comes_back_with_its_boxes_and_text(self):
        wanted = self.job.find("b.png").blocks[0]
        self.job.images = [e for e in self.job.images if e.relpath != "b.png"]

        images, blocks = exchange.rebuild(self.job, self.path)
        self.assertEqual((images, blocks), (1, 1))
        back = self.job.find("b.png").blocks[0]
        self.assertEqual(back.block_id, wanted.block_id)
        self.assertEqual(back.source_text, "かきく")
        self.assertEqual(back.target_text, "Hello")
        self.assertEqual(back.box.as_xywh(), wanted.box.as_xywh())

    def test_an_empty_shell_left_by_sync_is_filled_in(self):
        """Opening the editor re-adds a lost image before anything else runs.

        Skipping on presence alone therefore restored nothing at all: the shell
        was there, so rebuild considered the image fine and moved on.
        """
        self.job.images = [e for e in self.job.images if e.relpath != "b.png"]
        self.job.sync(["a.png", "b.png"])
        self.assertEqual(self.job.find("b.png").blocks, [])

        images, blocks = exchange.rebuild(self.job, self.path)
        self.assertEqual((images, blocks), (1, 1))
        self.assertEqual(self.job.find("b.png").blocks[0].source_text, "かきく")
        self.assertEqual(len(self.job.images), 2, "no duplicate entry")

    def test_images_still_in_the_job_are_left_alone(self):
        self.job.find("a.png").blocks[0].source_text = "edited since export"
        exchange.rebuild(self.job, self.path)
        self.assertEqual(
            self.job.find("a.png").blocks[0].source_text, "edited since export"
        )

    def test_an_image_whose_file_has_gone_is_not_resurrected(self):
        self.job.images = [e for e in self.job.images if e.relpath != "b.png"]
        (self.root / "b.png").unlink()
        self.assertEqual(exchange.rebuild(self.job, self.path), (0, 0))

    def test_a_rebuilt_block_keeps_its_id_so_translations_still_attach(self):
        self.job.images = [e for e in self.job.images if e.relpath != "b.png"]
        exchange.rebuild(self.job, self.path)
        result = exchange.read(self.job, self.path)
        self.assertEqual(result.applied, 2)
        self.assertFalse(result.unknown)


class SourceChoiceTests(unittest.TestCase):
    """Which copy of the exchange import reads, when there are two."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="imgtl-src-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.job = Job(self.root)
        self.job.sync(["a.png"])
        entry = self.job.find("a.png")
        entry.status = CONFIRMED
        entry.blocks = [block("あいう", 0, 0, 60, 18)]

    def _write(self, path: Path, target: str, when: float) -> None:
        payload = exchange.build(self.job)
        payload["images"][0]["regions"][0]["target"] = target
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.utime(path, (when, when))

    def test_the_copy_with_translations_wins_over_the_newer_empty_one(self):
        """Timestamp alone reported twelve blank strings on a real project.

        Export writes both copies, so a stray touch on the untranslated one
        makes it "newest" while the translations sit in the other file.
        """
        mirror = Path(os.environ["IMGTL_FILES_DIR"]) / exchange.EXCHANGE_FILENAME
        self._write(mirror, "Hello", when=1000)
        self._write(exchange.exchange_path(self.job), "", when=9000)

        result = exchange.read(self.job)
        self.assertEqual(result.applied, 1)
        self.assertEqual(self.job.find("a.png").blocks[0].target_text, "Hello")

    def test_with_work_in_both_the_newer_one_wins(self):
        mirror = Path(os.environ["IMGTL_FILES_DIR"]) / exchange.EXCHANGE_FILENAME
        self._write(mirror, "older", when=1000)
        self._write(exchange.exchange_path(self.job), "newer", when=9000)
        exchange.read(self.job)
        self.assertEqual(self.job.find("a.png").blocks[0].target_text, "newer")


class ExportGuardTests(unittest.TestCase):
    """The suite must be unable to touch DazedTL's real files/ folder.

    An export from a temporary fixture overwrote a real export once. The
    redirect that prevents it is invisible, so it is asserted rather than
    assumed.
    """

    def test_export_never_writes_into_the_real_files_folder(self):
        root = Path(tempfile.mkdtemp(prefix="imgtl-guard-"))
        self.addCleanup(shutil.rmtree, root, True)
        job = Job(root)
        job.sync(["a.png"])
        entry = job.find("a.png")
        entry.status = CONFIRMED
        entry.blocks = [block("こんにちは", 0, 0, 90, 18)]

        target, mirror = exchange.write(job)
        self.assertTrue(target.is_file())
        self.assertIsNotNone(mirror)
        self.assertTrue(
            str(mirror).startswith(_MIRROR),
            f"export escaped the test mirror and wrote to {mirror}",
        )

    def test_an_empty_override_disables_mirroring_entirely(self):
        previous = os.environ.get("IMGTL_FILES_DIR")
        os.environ["IMGTL_FILES_DIR"] = ""
        try:
            self.assertIsNone(exchange.files_path())
        finally:
            if previous is None:
                del os.environ["IMGTL_FILES_DIR"]
            else:
                os.environ["IMGTL_FILES_DIR"] = previous


class OnDemandOnlyTests(unittest.TestCase):
    """Nothing this workflow needs may leak into the base installation.

    Everyone who never opens the semi-manual workflow would otherwise pay for
    numpy, OpenCV and an OCR client on every install and every update. Keeping
    them out is the whole reason ``util/imagetools/resources.py`` exists, and
    it is the kind of thing a well-meaning "add the missing dependency" commit
    quietly undoes.

    The declaration lives in the manifest instead, which is what the download
    prompt reads.
    """

    PACKAGES = ("numpy", "opencv-python", "opencv-python-headless", "chrome-lens-py")

    def setUp(self):
        root = Path(__file__).resolve().parent.parent
        self.requirements = (root / "requirements.txt").read_text(encoding="utf-8")
        # Comments explain where these went; only real requirement lines count.
        self.required = [
            line.strip()
            for line in self.requirements.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        self.start = (root / "START.bat").read_text(encoding="utf-8", errors="replace")

    def test_they_are_not_installed_with_everything_else(self):
        for package in self.PACKAGES:
            with self.subTest(package):
                self.assertFalse(
                    [line for line in self.required if line.startswith(package)],
                    f"{package} is in requirements.txt, so every user now "
                    "downloads it whether or not they translate images",
                )

    def test_the_launcher_does_not_wait_on_them(self):
        for module in ("numpy", "cv2", "chrome_lens_py"):
            with self.subTest(module):
                self.assertNotIn(f"import {module}", self.start)

    def test_the_startup_dependency_gate_ignores_them(self):
        from util.dependencies import REQUIRED_MODULES

        for module in ("numpy", "cv2", "chrome_lens_py", "onnxruntime"):
            with self.subTest(module):
                self.assertNotIn(module, REQUIRED_MODULES.values())

    def test_they_are_declared_where_the_downloader_can_find_them(self):
        from util.imagetools import resources

        declared = {
            spec.split(">")[0].split("=")[0]
            for resource in resources.RESOURCES
            for spec in resource.pips
        }
        for package in ("numpy", "opencv-python-headless", "chrome-lens-py"):
            with self.subTest(package):
                self.assertIn(package, declared)

    def test_requirements_says_where_they_went(self):
        """A reader who greps for numpy and finds nothing needs a signpost."""
        self.assertIn("util.imagetools.resources", self.requirements)


class ImportProbeTests(unittest.TestCase):
    """A missing package and a broken one need different advice."""

    def test_a_present_module_reads_as_ready(self):
        from util.imagetools.ocr import probe_import

        ok, detail = probe_import("json", "pip install nothing")
        self.assertTrue(ok)
        self.assertEqual(detail, "ready")

    def test_a_missing_module_repeats_the_install_hint(self):
        from util.imagetools.ocr import probe_import

        ok, detail = probe_import("definitely_not_a_real_module", "pip install foo")
        self.assertFalse(ok)
        self.assertIn("pip install foo", detail)

    def test_a_module_that_raises_is_not_called_missing(self):
        """Telling someone to install what they already have is a dead end."""
        from unittest.mock import patch

        from util.imagetools.ocr import probe_import

        with patch(
            "importlib.import_module",
            side_effect=ImportError("DLL load failed while importing _core"),
        ):
            ok, detail = probe_import("anything", "pip install fixture")
        self.assertFalse(ok)
        self.assertIn("unusable", detail)
        self.assertIn("DLL load failed", detail)
        self.assertNotIn("not installed", detail)

    def test_a_missing_sub_dependency_is_named(self):
        """'needs onnxruntime' is actionable; 'not installed' would mislead."""
        from unittest.mock import patch

        from util.imagetools.ocr import probe_import

        with patch(
            "importlib.import_module",
            side_effect=ModuleNotFoundError("No module named 'onnxruntime'",
                                            name="onnxruntime"),
        ):
            ok, detail = probe_import("rapidocr_onnxruntime", "pip install rapidocr")
        self.assertFalse(ok)
        self.assertIn("onnxruntime", detail)


class ForeignExportTests(unittest.TestCase):
    def test_an_export_from_another_game_is_not_imported(self):
        """files/ holds one file at a time; the wrong one must be ignored."""
        mine = Path(tempfile.mkdtemp(prefix="imgtl-mine-"))
        theirs = Path(tempfile.mkdtemp(prefix="imgtl-theirs-"))
        self.addCleanup(shutil.rmtree, mine, True)
        self.addCleanup(shutil.rmtree, theirs, True)

        other = Job(theirs)
        other.sync(["x.png"])
        other.find("x.png").status = CONFIRMED
        other.find("x.png").blocks = [block("よそ", 0, 0, 40, 12)]
        stray = theirs / "image_text.json"
        stray.write_text(
            json.dumps(exchange.build(other), ensure_ascii=False), encoding="utf-8"
        )

        job = Job(mine)
        self.assertFalse(exchange._belongs_to(stray, job))


if __name__ == "__main__":
    unittest.main()
