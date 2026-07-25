"""Regression tests for keeping UberWolf tools exclusive to WOLF games."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from gui.workflow_tab import (
    _FileCopyWorker,
    _GAMEUPDATE_COPY_SKIP_NAMES,
    _RPG_GAMEUPDATE_COPY_SKIP_NAMES,
    _WOLF_ONLY_GAMEUPDATE_NAMES,
)


ROOT = Path(__file__).resolve().parents[1]


class GameUpdateGuiCopyTests(unittest.TestCase):
    def _copy_with(self, skip_names: frozenset[str]) -> tuple[Path, tempfile.TemporaryDirectory]:
        tmp = tempfile.TemporaryDirectory()
        base = Path(tmp.name)
        src = base / "source"
        dst = base / "game"
        src.mkdir()
        (src / "GameUpdate.bat").write_text("launcher", encoding="utf-8")
        (src / "UberWolfCli.exe").write_bytes(b"wolf-cli")
        (src / "UberWolfCli.LICENSE.txt").write_text("license", encoding="utf-8")

        result = []
        worker = _FileCopyWorker(str(src), str(dst), skip_names=skip_names)
        worker.done.connect(lambda count, errors: result.append((count, errors)))
        worker.run()

        self.assertEqual(result, [(1 if _WOLF_ONLY_GAMEUPDATE_NAMES <= skip_names else 3, [])])
        return dst, tmp

    def test_rpg_copy_omits_uberwolf_files(self):
        dst, tmp = self._copy_with(_RPG_GAMEUPDATE_COPY_SKIP_NAMES)
        try:
            self.assertTrue((dst / "GameUpdate.bat").is_file())
            for name in _WOLF_ONLY_GAMEUPDATE_NAMES:
                self.assertFalse((dst / name).exists())
        finally:
            tmp.cleanup()

    def test_wolf_copy_keeps_uberwolf_files(self):
        dst, tmp = self._copy_with(_GAMEUPDATE_COPY_SKIP_NAMES)
        try:
            for name in _WOLF_ONLY_GAMEUPDATE_NAMES:
                self.assertTrue((dst / name).is_file())
        finally:
            tmp.cleanup()


class GameUpdateSelfUpdateTests(unittest.TestCase):
    def test_powershell_patch_gates_uberwolf_on_wolf_detection(self):
        text = (ROOT / "gameupdate/gameupdate/patch.ps1").read_text(encoding="utf-8")

        self.assertIn("function Test-WolfGameRoot", text)
        self.assertIn("$isWolfGame = Test-WolfGameRoot -Root $Root", text)
        self.assertIn("(-not $isWolfGame) -and ($file.Name -in $wolfOnlyNames)", text)

    def test_shell_patch_gates_uberwolf_and_is_valid_bash(self):
        path = ROOT / "gameupdate/gameupdate/patch.sh"
        text = path.read_text(encoding="utf-8")

        self.assertIn("is_wolf_game()", text)
        self.assertIn('[ "$wolf_patch" -ne 1 ]', text)
        subprocess.run(["bash", "-n", str(path)], check=True)


if __name__ == "__main__":
    unittest.main()
