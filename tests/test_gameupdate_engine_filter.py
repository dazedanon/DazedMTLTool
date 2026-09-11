"""Regression tests for keeping UberWolf tools exclusive to WOLF games."""

from __future__ import annotations

import subprocess
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

        # Len must produce the same prepared files as the Workflow actions, with
        # saved per-game configuration intact and no provider/GUI dependency.
        from gui.workflow_workers import JsonFormatWorker, JsFormatWorker
        from util.project_preparation import (GAMEUPDATE_PRESERVE_EXISTING, prepare_rpgmaker,
                                               write_gameupdate_config, install_startup_check)
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            bundle = base / "bundle"
            (bundle / "gameupdate").mkdir(parents=True)
            for name, text in {
                "GameUpdate.bat": "launcher", "README.md": "default readme", ".gitignore": "default rules",
                "previous_patch_sha.txt": "other game's state", "UberWolfCli.exe": "wolf only",
                "gameupdate/patch-config.txt": "repo=template", "gameupdate/patch.sh": "# helper",
                "gameupdate/TranslationUpdateCheck.js": "// checker fixture",
            }.items():
                (bundle / name).write_text(text)
            env = base / "defaults.env"
            env.write_text("gameUpdateForge=gitlab\ngameUpdateUsername=FixtureAuthor\ngameUpdateHost=example.invalid\ngameUpdateBranch=main\n")
            for variant in ("MV", "MZ"):
                games = [base / f"{variant}-{method}" for method in ("workflow", "len")]
                for game in games:
                    content = game / "www" if variant == "MV" else game
                    (content / "data").mkdir(parents=True)
                    (content / "js").mkdir()
                    (content / "data/System.json").write_bytes(b'\xef\xbb\xbf' + json.dumps({"gameTitle": "日本語", "_original": {"gameTitle": "元の名"}}).encode())
                    (content / "js/plugins.js").write_text('var $plugins=[{"name":"GamePlugin","status":false,"parameters":{"label":"日本語"}}];')
                    (game / ".gitignore").write_text("# game-specific rules\n")
                    (game / "README.md").write_text("Game installation instructions")
                    if variant == "MV":
                        (game / "gameupdate").mkdir()
                        (game / "gameupdate/patch-config.txt").write_text("repo=reviewed-game\nusername=CustomAuthor\n")
                with patch("util.translation_update_check.installer.DEFAULT_PLUGIN_SRC", bundle / "gameupdate/TranslationUpdateCheck.js"):
                    workflow, selected = games
                    content = workflow / "www" if variant == "MV" else workflow
                    outcomes = []
                    for worker in (JsonFormatWorker(str(content / "data")), JsFormatWorker(str(content / "js/plugins.js"))):
                        worker.done.connect(lambda ok, msg: outcomes.append(ok))
                        worker.run()
                    self.assertEqual(outcomes, [True, True])
                    worker = _FileCopyWorker(str(bundle), str(workflow), skip_names=_RPG_GAMEUPDATE_COPY_SKIP_NAMES,
                                             preserve_existing=GAMEUPDATE_PRESERVE_EXISTING)
                    worker.run()
                    write_gameupdate_config(workflow, env_path=env)
                    self.assertTrue(install_startup_check(workflow)[0])
                    report = prepare_rpgmaker(selected, gameupdate_source=bundle, env_path=env)
                    self.assertEqual(report["formatted_json"], 1)
                    self.assertTrue(report["plugins_formatted"])
                    expected = {p.relative_to(workflow): p.read_bytes() for p in workflow.rglob("*") if p.is_file()}
                    actual = {p.relative_to(selected): p.read_bytes() for p in selected.rglob("*") if p.is_file()}
                    self.assertEqual(actual, expected)
                    self.assertFalse((selected / "UberWolfCli.exe").exists())
                    self.assertFalse((selected / "previous_patch_sha.txt").exists())
                    self.assertEqual((selected / ".gitignore").read_text(), "# game-specific rules\n")
                    config = (selected / "gameupdate/patch-config.txt").read_text()
                    self.assertIn("reviewed-game" if variant == "MV" else "FixtureAuthor", config)
                    prepare_rpgmaker(selected, gameupdate_source=bundle, env_path=env)
                    self.assertEqual({p.relative_to(selected): p.read_bytes() for p in selected.rglob("*") if p.is_file()}, actual)
                    content = selected / "www" if variant == "MV" else selected
                    (content / "data/broken.json").write_text("{bad json")
                    with self.assertRaises(ValueError), patch("util.project_preparation.copy_files") as copied:
                        prepare_rpgmaker(selected, gameupdate_source=bundle, env_path=env)
                    copied.assert_not_called()
            ace = base / "Ace"
            (ace / "Data").mkdir(parents=True)
            (ace / "Data/System.rvdata2").write_bytes(b"native source fixture")
            with self.assertRaises(ValueError):
                prepare_rpgmaker(ace, gameupdate_source=bundle, env_path=env)
            (ace / "ace_json").mkdir()
            (ace / "ace_json/System.json").write_text('{"title":"Japanese"}')
            outside = base / "outside"
            outside.mkdir()
            (outside / "System.json").write_text('{"keep":"original bytes"}')
            with self.assertRaises(ValueError):
                prepare_rpgmaker(ace, data_path="../outside", gameupdate_source=bundle, env_path=env)
            self.assertEqual((outside / "System.json").read_text(), '{"keep":"original bytes"}')
            report = prepare_rpgmaker(ace, gameupdate_source=bundle, env_path=env)
            self.assertFalse(report["plugins_formatted"])
            self.assertEqual((ace / "Data/System.rvdata2").read_bytes(), b"native source fixture")
            generic = base / "Generic"
            (generic / "data").mkdir(parents=True)
            (generic / "data/strings.json").write_text('{"text":"Japanese"}')
            with self.assertRaises(ValueError):
                prepare_rpgmaker(generic, gameupdate_source=bundle, env_path=env)
            self.assertEqual((generic / "data/strings.json").read_text(), '{"text":"Japanese"}')

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
