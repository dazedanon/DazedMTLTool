"""Regression tests for deterministic walkthrough claim validation."""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_VALIDATOR_PATH = _REPO_ROOT / "data" / "skills" / "build-game-walkthrough" / "scripts" / "validate_walkthrough.py"
_SPEC = importlib.util.spec_from_file_location("walkthrough_validator", _VALIDATOR_PATH)
assert _SPEC is not None and _SPEC.loader is not None
walkthrough_validator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = walkthrough_validator
_DONT_WRITE_BYTECODE = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    _SPEC.loader.exec_module(walkthrough_validator)
finally:
    sys.dont_write_bytecode = _DONT_WRITE_BYTECODE


def _database(*names: str) -> list[dict | None]:
    return [None, *({"name": name} for name in names)]


class WalkthroughValidationTests(unittest.TestCase):
    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def _build_project(self, root: Path) -> tuple[Path, Path]:
        data = root / "data"
        data.mkdir()
        plugins = root / "js"
        plugins.mkdir()
        achievement_data = json.dumps([json.dumps({"key": "S1", "title": "Mission", "description": "Begin."})])
        (plugins / "plugins.js").write_text(
            "var $plugins = "
            + json.dumps(
                [
                    {
                        "name": "FixtureAchievement",
                        "status": True,
                        "description": "Achievement fixture",
                        "parameters": {"baseAchievementData": achievement_data},
                    }
                ]
            )
            + ";\n",
            encoding="utf-8",
        )
        self._write_json(data / "System.json", {"gameTitle": "Fixture", "switches": ["", *([""] * 209), "Route marker"]})
        self._write_json(data / "Items.json", _database("Scholar's Insignia"))
        self._write_json(
            data / "Weapons.json",
            _database("Scissor's Dagger", "Great Warrior's Sword"),
        )
        self._write_json(
            data / "Armors.json",
            _database("Scissor's Garb", "Great Warrior's Armor"),
        )
        self._write_json(
            data / "Troops.json",
            _database("Great Warrior Baru Balta", "Scissor, Bandit Leader"),
        )
        for filename in (
            "Actors.json",
            "Classes.json",
            "Enemies.json",
            "Skills.json",
            "States.json",
        ):
            self._write_json(data / filename, [None])

        empty_conditions = {
            "switch1Valid": False,
            "switch2Valid": False,
            "variableValid": False,
            "selfSwitchValid": False,
            "itemValid": False,
            "actorValid": False,
        }
        choice_commands = [
            {"code": 102, "indent": 0, "parameters": [["Side with the Bandits", "Side with the Barbarians"], -1, 0, 2, 0]},
            {"code": 402, "indent": 0, "parameters": [0, "Side with the Bandits"]},
            {"code": 121, "indent": 1, "parameters": [210, 210, 0]},
            {"code": 117, "indent": 1, "parameters": [1]},
            {"code": 402, "indent": 0, "parameters": [1, "Side with the Barbarians"]},
            {"code": 301, "indent": 1, "parameters": [0, 2, True, True]},
            {"code": 404, "indent": 0, "parameters": []},
            {
                "code": 357,
                "indent": 0,
                "parameters": [
                    "FixtureAchievement",
                    "gainAchievement",
                    "Gain achievement",
                    {"key": "S1"},
                ],
            },
            {"code": 0, "indent": 0, "parameters": []},
        ]
        reward_commands = [
            {"code": 111, "indent": 0, "parameters": [0, 210, 0]},
            {"code": 127, "indent": 1, "parameters": [1, 0, 0, 1, False]},
            {"code": 128, "indent": 1, "parameters": [1, 0, 0, 1, False]},
            {"code": 411, "indent": 0, "parameters": []},
            {"code": 127, "indent": 1, "parameters": [2, 0, 0, 1, False]},
            {"code": 128, "indent": 1, "parameters": [2, 0, 0, 1, False]},
            {"code": 412, "indent": 0, "parameters": []},
            {"code": 126, "indent": 0, "parameters": [1, 0, 0, 1]},
            {"code": 0, "indent": 0, "parameters": []},
        ]

        def event(name: str, commands: list[dict]) -> dict:
            return {
                "name": name,
                "pages": [{"conditions": empty_conditions, "list": commands}],
            }

        self._write_json(
            data / "Map001.json",
            {"events": [None, event("Sunward Hill", choice_commands)]},
        )
        self._write_json(
            data / "Map002.json",
            {"events": [None, event("Sacred Mount Vinculum: Chapel", reward_commands)]},
        )
        self._write_json(
            data / "CommonEvents.json",
            [
                None,
                {
                    "name": "Bandit Battle",
                    "list": [
                        {"code": 301, "indent": 0, "parameters": [0, 1, True, True]},
                        {"code": 0, "indent": 0, "parameters": []},
                    ],
                },
                {
                    "name": "Objective Gate",
                    "list": [
                        {"code": 111, "indent": 0, "parameters": [1, 83, 0, 1000, 5]},
                        {"code": 115, "indent": 1, "parameters": []},
                        {"code": 412, "indent": 0, "parameters": []},
                        {"code": 111, "indent": 0, "parameters": [1, 84, 0, 1000, 5]},
                        {"code": 115, "indent": 1, "parameters": []},
                        {"code": 412, "indent": 0, "parameters": []},
                        {"code": 0, "indent": 0, "parameters": []},
                    ],
                },
            ],
        )

        walkthrough = root / "WALKTHROUGH.md"
        walkthrough.write_text(
            "Activate **Sunward Hill** `[W01]` and collect "
            "**Scholar's Insignia** `[I01]`. Earn **Mission** `[S1]`.\n\n"
            "Legend: **Choice Ahead** — a decision with different outcomes.\n\n"
            "Complete both objectives.\n\n"
            "**Choice Ahead — The Scum's Plight:** save first.\n\n"
            "- **Side with the Bandits:** fight **Great Warrior Baru Balta**; "
            "receive **Scissor's Dagger** and **Scissor's Garb**.\n"
            "- **Side with the Barbarians:** fight **Scissor, Bandit Leader**; "
            "receive **Great Warrior's Sword** and **Great Warrior's Armor**.\n",
            encoding="utf-8",
        )
        (root / "WALKTHROUGH.html").write_text(
            "<html><body><h1>Guide</h1><p>Activate <strong>Sunward Hill</strong> "
            "<code>[W01]</code> and collect <strong>Scholar's Insignia</strong> "
            "<code>[I01]</code>. Earn <strong>Mission</strong> <code>[S1]</code>.</p>"
            "<p>Side with the Bandits: Great Warrior Baru Balta; Scissor's Dagger; "
            "Scissor's Garb. Side with the Barbarians: Scissor, Bandit Leader; "
            "Great Warrior's Sword; Great Warrior's Armor.</p></body></html>",
            encoding="utf-8",
        )
        evidence = root / "evidence.json"
        self._write_json(
            evidence,
            {
                "schema_version": 1,
                "badges_reviewed": True,
                "achievement_unlocks_reviewed": True,
                "badges": {"W01": "Sunward Hill"},
                "acquisitions": [
                    {
                        "name": "Scholar's Insignia",
                        "kind": "item",
                        "expected_total": 1,
                        "badges": {"prefix": "I", "first": 1, "last": 1, "width": 2},
                        "sources": [
                            {
                                "badge": "I01",
                                "source": {
                                    "file": "data/Map002.json",
                                    "event_id": 1,
                                    "page_index": 0,
                                    "command_index": 7,
                                },
                            }
                        ],
                    }
                ],
                "switch_sets": [
                    {
                        "id": "one-marker",
                        "expected_total": 1,
                        "switch_ids": [210],
                        "guide_phrases": ["Complete both objectives"],
                    }
                ],
                "achievement_switch_sets": [
                    {
                        "id": "one-native-achievement",
                        "first_switch_id": 210,
                        "last_switch_id": 210,
                        "expected_total": 1,
                        "source": {"file": "data/Map002.json", "event_id": 1, "page_index": 0},
                        "guide_phrases": ["Mission"],
                    }
                ],
                "requirements": [
                    {
                        "id": "two-objective-gate",
                        "expected_total": 2,
                        "source": {
                            "file": "data/CommonEvents.json",
                            "event_id": 2,
                            "page_index": 0,
                        },
                        "guide_phrases": ["Complete both objectives"],
                        "entries": [
                            {"variable_id": 83, "operator": "==", "value": 1000},
                            {"variable_id": 84, "operator": "==", "value": 1000},
                        ],
                    }
                ],
                "choices": [
                    {
                        "name": "The Scum's Plight",
                        "source": {"file": "data/Map001.json", "event_id": 1, "page_index": 0},
                        "initial_state": {"switches": {"210": False}},
                        "reward_scope": [
                            "Scissor's Dagger",
                            "Scissor's Garb",
                            "Great Warrior's Sword",
                            "Great Warrior's Armor",
                        ],
                        "branches": [
                            {
                                "label": "Side with the Bandits",
                                "state": {"switches": {"210": True}},
                                "fights": ["Great Warrior Baru Balta"],
                                "rewards": ["Scissor's Dagger", "Scissor's Garb"],
                            },
                            {
                                "label": "Side with the Barbarians",
                                "state": {"switches": {"210": False}},
                                "fights": ["Scissor, Bandit Leader"],
                                "rewards": ["Great Warrior's Sword", "Great Warrior's Armor"],
                            },
                        ],
                    }
                ],
            },
        )
        return walkthrough, evidence

    def test_else_branch_rewards_are_forward_and_reverse_validated(self):
        """Protect the exact conditional-Else error that swapped choice rewards."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence = self._build_project(root)
            report = walkthrough_validator.validate_project(root, walkthrough, evidence, root / "WALKTHROUGH.html")
            self.assertEqual(report["status"], "passed", report["issues"])
            self.assertEqual(report["summary"]["coverage"]["unresolved"], 0)
            self.assertEqual(report["achievements"]["definitions"]["S1"]["title"], "Mission")
            self.assertEqual(report["acquisitions"][0]["observed_total"], 1)
            self.assertEqual(report["switch_sets"][0]["expected_total"], 1)
            self.assertEqual(report["achievements"]["switch_sets"][0]["observed_total"], 1)
            self.assertTrue(report["event_graph"]["common_event_calls"])
            branches = report["choices"][0]["branches"]
            self.assertEqual(
                branches[0]["observed_reward_scope"],
                ["Scissor's Dagger", "Scissor's Garb"],
            )
            self.assertEqual(
                branches[1]["observed_reward_scope"],
                ["Great Warrior's Armor", "Great Warrior's Sword"],
            )

            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["choices"][0]["branches"][0]["rewards"] = [
                "Great Warrior's Sword",
                "Great Warrior's Armor",
            ]
            self._write_json(evidence, manifest)
            failed = walkthrough_validator.validate_project(root, walkthrough, evidence, root / "WALKTHROUGH.html")
            self.assertEqual(failed["status"], "failed")
            self.assertIn(
                "reward-branch-mismatch",
                {issue["code"] for issue in failed["issues"]},
            )

    def test_badges_require_one_canonical_full_name(self):
        """Protect player-visible names from opaque or contradictory badge-only prose."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence = self._build_project(root)
            walkthrough.write_text(
                "Warp to `[W02]`. Use **Sunward Hill** `[W01]`, then **Sacred Mount Vinculum: Chapel** `[W01]`.\n",
                encoding="utf-8",
            )
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["badges"] = {"W01": "Sunward Hill"}
            manifest["choices"] = []
            self._write_json(evidence, manifest)

            report = walkthrough_validator.validate_project(root, walkthrough, evidence)
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("badge-without-full-name", codes)
            self.assertIn("badge-name-contradiction", codes)
            self.assertIn("expected-badge-missing", codes)

    def test_coverage_ledger_exposes_stale_html_wrong_totals_and_unproven_order(self):
        """Protect reports from presenting unchecked or contradicted claims as clean."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["acquisitions"][0]["expected_total"] = 2
            manifest["acquisitions"][0].pop("sources")
            manifest["requirements"][0]["entries"].pop()
            self._write_json(evidence, manifest)
            (root / "WALKTHROUGH.html").write_text("<html><body>Stale guide</body></html>", encoding="utf-8")

            report = walkthrough_validator.validate_project(root, walkthrough, evidence, root / "WALKTHROUGH.html")
            self.assertEqual(report["status"], "failed")
            codes = {issue["code"] for issue in report["issues"]}
            self.assertIn("acquisition-total-mismatch", codes)
            self.assertIn("requirement-set-mismatch", codes)
            self.assertIn("markdown-html-parity-mismatch", codes)
            self.assertGreater(report["summary"]["coverage"]["contradicted"], 0)
            self.assertIn(
                "acquisition_route_order",
                {row["category"] for row in report["live_play_checklist"]},
            )
            checklist = root / "live-play-checklist.md"
            walkthrough_validator._write_live_play_checklist(checklist, report)
            self.assertIn("acquisition_route_order", checklist.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
