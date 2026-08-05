"""Font discovery for image export - no OpenCV required.

Protects the Linux default-font path: Arch/Fedora layouts are found even when
the Debian absolute candidates miss. Render tests that need a real FreeType
face live in test_imagetools_render.py.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from util.imagetools import fonts


class DefaultFontTests(unittest.TestCase):
    """Export needs a default face even when Debian-style paths are absent."""

    def setUp(self):
        self._env = os.environ.pop("IMGTL_FONT", None)

    def tearDown(self):
        if self._env is None:
            os.environ.pop("IMGTL_FONT", None)
        else:
            os.environ["IMGTL_FONT"] = self._env

    def test_arch_layout_is_used_when_debian_candidates_miss(self):
        root = Path(tempfile.mkdtemp(prefix="imgtl-fonts-"))
        self.addCleanup(shutil.rmtree, root, True)
        arch = root / "TTF"
        arch.mkdir()
        face = arch / "DejaVuSans.ttf"
        face.write_bytes(b"not-a-real-font")

        with (
            patch.object(fonts, "BUNDLED_FONT_DIR", root / "missing-bundled"),
            patch.object(fonts, "_SYSTEM_CANDIDATES", ()),
            patch.object(fonts, "_BOLD_CANDIDATES", ()),
            patch.object(fonts, "_SYSTEM_FONT_DIRS", (root,)),
        ):
            self.assertEqual(Path(fonts.default_font()), face)

    def test_imgtl_font_override_wins(self):
        root = Path(tempfile.mkdtemp(prefix="imgtl-fonts-"))
        self.addCleanup(shutil.rmtree, root, True)
        override = root / "Custom.ttf"
        override.write_bytes(b"not-a-real-font")
        os.environ["IMGTL_FONT"] = str(override)
        with (
            patch.object(fonts, "BUNDLED_FONT_DIR", root / "missing-bundled"),
            patch.object(fonts, "_SYSTEM_CANDIDATES", ()),
            patch.object(fonts, "_BOLD_CANDIDATES", ()),
            patch.object(fonts, "_SYSTEM_FONT_DIRS", ()),
        ):
            self.assertEqual(Path(fonts.default_font()), override)


if __name__ == "__main__":
    unittest.main()
