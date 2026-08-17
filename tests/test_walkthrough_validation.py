"""Regression tests for the walkthrough publication contract."""

from __future__ import annotations

import importlib.util
import hashlib
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


class WalkthroughValidationTests(unittest.TestCase):
    def _write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def test_pronoun_window_does_not_turn_heal_into_he(self) -> None:
        issues: list[dict[str, object]] = []
        text = "Weeu " + ("x" * 176) + " Heal"

        walkthrough_validator._validate_glossary_pronouns(
            text,
            "Guide",
            [{"name": "Weeu", "gender": "female", "source": ".dazedtl/glossary.txt"}],
            issues,
        )

        self.assertEqual([], issues)

    def _html(self, *, source_id: str = "front-door-transfer", bosses_class: str = "guide-view") -> str:
        tabs = "".join(
            f'<a class="primary-tab" data-view-target="{view}" href="#{panel}">{label}</a>'
            for view, panel, label in (
                ("main-route", "view-main-route", "Main Route"),
                ("optional-content", "view-optional-content", "Optional Content"),
                ("bosses", "view-bosses", "Bosses"),
                ("scenes-cg", "view-scenes-cg", "Scenes &amp; CG"),
            )
        )
        return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Fixture Walkthrough</title><style>body {{ color: #222; }}</style></head>
<body>
  <a class="skip-link" href="#guide-content">Skip to walkthrough</a>
  <div class="scroll-progress"><span></span></div>
  <header class="topbar"><span class="topbar-location">Opening</span></header>
  <aside class="sidebar">
    <div class="brand">Fixture</div>
    <nav class="section-nav"><a href="#step-reach-town">Reach Town</a></nav>
    <div class="sidebar-progress">0 / 1</div>
  </aside>
  <button class="sidebar-scrim" type="button">Close navigation</button>
  <main class="page">
    <nav class="primary-tabs">{tabs}</nav>
    <article class="guide-content" id="guide-content">
      <section class="guide-view" id="view-main-route" data-view="main-route">
        <header class="hero"><h1>Fixture Main Route</h1><div class="hero-stats"><div class="hero-stat">1</div><div class="hero-stat">1</div><div class="hero-stat">0</div><div class="hero-stat">1</div></div></header>
        <section class="route-chapter" id="group-prologue" data-chapter-id="prologue" data-chapter-label="Prologue">
          <header><p>Game chapter</p><h2 id="prologue">Prologue</h2></header>
          <section class="route-section" id="section-objective-reach-town" data-section-id="objective-reach-town" data-section-label="Reach Town">
            <header><p>In-game objective</p><h3 id="objective-reach-town">Reach Town</h3></header>
            <article class="route-step" id="step-reach-town" data-claim-id="reach-town">
              <h4 id="reach-town">Leave through the front door</h4>
            <ol class="walkthrough-steps" data-walkthrough-id="reach-town">
              <li data-step-role="start">Start at the front door in Home.</li>
              <li data-step-role="travel">Use the front door to leave Home.</li>
              <li data-step-role="confirmation">You arrive in Town.</li>
            </ol>
            <aside><a data-guide-link data-guide-kind="optional" data-guide-link-position="after" href="#town-errand">Town Errand</a> is now available.</aside>
            <aside><a data-guide-link data-guide-kind="scene" data-guide-link-position="after" href="#scene-group-mina">Mina scenes</a> are now available. <a data-guide-link data-guide-kind="scene" data-guide-link-position="after" href="#scene-town-memory">Town Memory</a></aside>
            <p><a data-guide-link data-guide-kind="boss" href="#boss-door-warden">Door Warden</a> boss dossier.</p>
            <label class="task-row"><input class="task-checkbox" type="checkbox" data-task-id="reach-town"> Mark complete</label>
            <details class="evidence" data-evidence-id="reach-town">
              <summary>Evidence</summary>
              <p data-evidence-status="verified">Verified from game data</p>
              <ul>
                <li data-source-id="home-map-name">The route begins on the map named Home.</li>
                <li data-source-id="{source_id}">The front door transfers the party to the town map.</li>
                <li data-source-id="town-map-name">The destination map is named Town.</li>
              </ul>
            </details>
            </article>
          </section>
        </section>
      </section>
      <section class="guide-view" id="view-optional-content" data-view="optional-content">
        <h1>Optional Content</h1>
        <section class="optional-group" data-optional-group-id="optional-prologue" data-optional-group-label="Prologue Detours">
          <h2 id="optional-prologue">Prologue Detours</h2>
          <article class="optional-entry" id="optional-entry-town-errand" data-optional-id="town-errand">
            <h3 id="town-errand">Town Errand</h3>
            <ol class="walkthrough-steps" data-walkthrough-id="town-errand">
              <li data-step-role="start">After reaching Town, speak to Mina in the town square.</li>
              <li data-step-role="obtain">Recover the parcel from the riverside storehouse, then bring it back to Mina.</li>
              <li data-step-role="completion">Mina accepts the parcel and Town Errand is complete.</li>
            </ol>
            <label><input class="task-checkbox" type="checkbox" data-task-id="town-errand"> Done</label>
            <details class="evidence" data-evidence-id="town-errand">
              <summary>Evidence</summary>
              <p data-evidence-status="verified">Verified from game data</p>
              <ul>
                <li data-source-id="town-errand-journal">The journal names this optional event Town Errand.</li>
                <li data-source-id="town-errand-start">Mina in the town square starts Town Errand.</li>
                <li data-source-id="town-errand-parcel">The event requires the parcel from the riverside storehouse.</li>
                <li data-source-id="town-errand-complete">Returning the parcel to Mina completes Town Errand.</li>
              </ul>
            </details>
          </article>
        </section>
      </section>
      <section class="{bosses_class}" id="view-bosses" data-view="bosses">
        <h1>Bosses</h1>
        <section class="boss-group" data-boss-group-id="boss-story" data-boss-group-label="Story Bosses">
          <h2 id="boss-story">Story Bosses</h2>
          <article class="boss-entry" id="boss-entry-door-warden" data-boss-id="door-warden">
            <h3 id="boss-door-warden">Door Warden</h3>
            <p>The Door Warden confronts you before Town.</p>
            <section class="boss-phase" data-boss-phase-index="1">
              <p>Battle setup: the protagonist fights alone.</p>
              <p>Door Warden has no encoded elemental weakness or resistance.</p>
              <table><tbody><tr>
                <td data-boss-stat="Form">Door Warden</td>
                <td data-boss-stat="HP">100</td>
                <td data-boss-stat="SP">10</td>
                <td data-boss-stat="EXP">20</td>
                <td data-boss-stat="Gold">5</td>
                <td data-boss-stat="Database drops">None</td>
              </tr></tbody></table>
              <p>Shield Bash is dangerous because Stun can cost the target its next action.</p>
              <p>Use Fire damage when available, then Guard before Shield Bash.</p>
            </section>
            <p>Defeating it opens the front door.</p>
            <p><a data-guide-link href="#reach-town">Main Route: Reach Town</a></p>
            <label><input class="task-checkbox" type="checkbox" data-task-id="door-warden"> Defeated</label>
            <details class="evidence" data-evidence-id="door-warden">
              <summary>Evidence</summary>
              <p data-evidence-status="verified">Verified from game data</p>
              <ul>
                <li data-source-id="door-warden-battle">The front-door event starts the Door Warden battle.</li>
                <li data-source-id="door-warden-troop">The troop contains the Door Warden enemy.</li>
                <li data-source-id="door-warden-enemy">The enemy record pins the Door Warden's stats and actions.</li>
                <li data-source-id="door-warden-action">The skill record defines Shield Bash and its Stun effect.</li>
                <li data-source-id="door-warden-guard">The skill record defines the standard Guard command.</li>
              </ul>
            </details>
          </article>
        </section>
      </section>
      <section class="guide-view" id="view-scenes-cg" data-view="scenes-cg">
        <header class="scenes-hero"><h1>Scenes &amp; CG</h1><p>1 verified entry and 1 illustrated set.</p></header>
        <section class="scene-system" id="scenes-cg-system">
          <h2>Using the Memory Gallery</h2>
          <p>Choose Reminisce at the bedroom journal to enter the Memory Gallery.</p>
          <p>After a cleared ending, Unlock All opens every gallery entry; the cards below still explain how to encounter scenes during normal play.</p>
          <details class="evidence" data-evidence-id="scenes-cg-system">
            <summary>Evidence</summary>
            <p data-evidence-status="verified">Verified from game data</p>
            <ul>
              <li data-source-id="scene-catalog-entry">The bedroom journal opens the Memory Gallery.</li>
              <li data-source-id="scene-catalog-slots">The gallery's configured slots define its illustrated catalog.</li>
              <li data-source-id="scene-catalog-unlock-all">The gallery exposes its completion shortcut after a cleared ending.</li>
            </ul>
          </details>
        </section>
        <section class="scene-group" data-scene-group-id="scene-group-mina" data-scene-group-label="Mina">
          <h2 id="scene-group-mina">Mina</h2>
          <p><a data-guide-link href="#reach-town">Main Route: Reach Town</a></p>
          <article class="scene-entry" id="scene-entry-scene-town-memory" data-scene-id="scene-town-memory" data-acquisition-mode="normal-play" data-catalog-title="Town Memory">
            <h3 id="scene-town-memory">Town Memory</h3>
            <p>Town Memory appears in the Memory Gallery after every listed requirement is met.</p>
            <section class="scene-acquisition" data-acquisition-mode="normal-play">
              <h4>How to get it normally</h4>
              <p>Reach Town, then speak to Mina at the fountain to play Town Memory during the journey.</p>
              <ul><li>Reach Town and speak to Mina at the fountain.</li></ul>
            </section>
            <p>1 illustrated set</p>
            <label><input class="task-checkbox" type="checkbox" data-task-id="scene-town-memory"> Unlocked</label>
            <details class="evidence" data-evidence-id="scene-town-memory">
              <summary>Evidence</summary>
              <p data-evidence-status="verified">Verified from game data</p>
              <ul>
                <li data-source-id="scene-town-memory-requirements">The locked entry displays the complete player-facing requirement.</li>
                <li data-source-id="scene-town-memory-title">The unlocked catalog names the entry Town Memory.</li>
                <li data-source-id="scene-town-memory-replay">The catalog dispatches the Town Memory replay.</li>
                <li data-source-id="scene-town-memory-trigger">A reachable fountain interaction triggers Town Memory.</li>
                <li data-source-id="scene-town-memory-unlock">Completing the live event unlocks its catalog entry.</li>
                <li data-source-id="scene-town-memory-cg">The viewer includes one illustrated set for Town Memory.</li>
              </ul>
            </details>
          </article>
        </section>
      </section>
      <footer>Fixture</footer>
    </article>
  </main>
  <dialog class="search-dialog"></dialog>
  <div class="resume-toast"></div>
  <button class="back-to-top" type="button">Top</button>
</body>
</html>
"""

    def _build_project(self, root: Path) -> tuple[Path, Path, Path]:
        data = root / "data"
        data.mkdir()
        empty_conditions = {
            "switch1Valid": False,
            "switch2Valid": False,
            "variableValid": False,
            "selfSwitchValid": False,
            "itemValid": False,
            "actorValid": False,
        }
        self._write_json(
            data / "Map001.json",
            {
                "events": [
                    None,
                    {
                        "name": "Front Door",
                        "pages": [
                            {
                                "conditions": empty_conditions,
                                "list": [
                                    {"code": 201, "indent": 0, "parameters": [0, 2, 8, 11, 2, 0]},
                                    {"code": 301, "indent": 0, "parameters": [0, 1, True, False]},
                                    {"code": 121, "indent": 0, "parameters": [5, 5, 0]},
                                    {"code": 111, "indent": 0, "parameters": [0, 5, 0]},
                                    {"code": 0, "indent": 0, "parameters": []},
                                ],
                            }
                        ],
                    },
                ]
            },
        )
        self._write_json(data / "MapInfos.json", [None, {"name": "Home"}, {"name": "Town"}])
        self._write_json(
            data / "Troops.json",
            [None, {"id": 1, "name": "Prologue", "members": [{"enemyId": 1, "x": 0, "y": 0}]}],
        )
        self._write_json(
            data / "Enemies.json",
            [
                None,
                {
                    "name": "Door Warden",
                    "params": [100, 10, 12, 8, 5, 5, 7, 6],
                    "exp": 20,
                    "gold": 5,
                    "dropItems": [],
                    "actions": [
                        {
                            "skillId": 3,
                            "rating": 5,
                            "conditionType": 1,
                            "conditionParam1": 3,
                            "conditionParam2": 3,
                        }
                    ],
                    "traits": [],
                },
            ],
        )
        self._write_json(
            data / "Skills.json",
            [
                None,
                None,
                {
                    "name": "Guard",
                    "scope": 11,
                    "effects": [{"code": 21, "dataId": 2, "value1": 1, "value2": 0}],
                    "note": "standard defense command",
                },
                {
                    "name": "Shield Bash",
                    "description": "A heavy strike that can Stun.",
                    "scope": 1,
                    "hitType": 1,
                    "damage": {"type": 1, "elementId": -1, "formula": "a.atk * 4 - b.def * 2"},
                    "effects": [{"code": 21, "dataId": 11, "value1": 1, "value2": 0}],
                    "note": "",
                },
            ],
        )
        self._write_json(
            data / "SceneCatalog.json",
            [
                None,
                {"entryPoint": "Bedroom journal"},
                {"slots": ["Town Memory"]},
                {"requirements": ["Reach Town", "Speak to Mina"]},
                {"title": "Town Memory"},
                {"replay": "town-memory"},
                {"trigger": "Mina fountain"},
                {"unlock": "town-memory"},
                {"illustratedSet": "town-memory-a"},
                {"unlockAll": "after-cleared-ending"},
            ],
        )
        self._write_json(
            data / "LiveScenes.json",
            [
                None,
                {"trigger": "Mina fountain"},
                {"unlock": "town-memory"},
            ],
        )
        scripts = root / "js"
        scripts.mkdir()
        (scripts / "plugins.js").write_text(
            'DestinationText":"Reach Town"\n'
            'OptionalTitle":"Town Errand"\n'
            'OptionalStart":"Mina in Town square"\n'
            'OptionalItem":"Parcel from riverside storehouse"\n'
            'OptionalComplete":"Return parcel to Mina"\n',
            encoding="utf-8",
        )
        pictures = root / "img" / "pictures"
        pictures.mkdir(parents=True)
        chapter_card = pictures / "Prologue.bin"
        chapter_card.write_bytes(b"fixture prologue title card")

        context_root = root / ".dazedtl"
        context_root.mkdir()
        glossary = context_root / "glossary.txt"
        glossary.write_text(
            "# Game Characters\n"
            "ミナ (Mina) - Female guide who waits by the door.\n"
            "インティーグ (Intrigue) - Guide of unspecified gender.\n",
            encoding="utf-8",
        )
        quirks = context_root / "skills" / "quirks.md"
        quirks.parent.mkdir()
        quirks.write_text("- Use established character names and identities.\n", encoding="utf-8")

        work = context_root / "walkthrough"
        work.mkdir(parents=True)
        walkthrough = work / "WALKTHROUGH.md"
        walkthrough.write_text(
            "# Fixture Main Route\n\n"
            "<!-- route-chapter:prologue -->\n"
            "## Prologue\n\n"
            "<!-- route-section:objective-reach-town -->\n"
            "### Reach Town\n\n"
            "<!-- route-claim:reach-town -->\n"
            "#### Leave through the front door\n\n"
            "1. Start at the front door in Home.\n"
            "2. Use the front door to leave Home.\n"
            "3. You arrive in Town.\n\n"
            "# Optional Content\n\n"
            "<!-- optional-group:optional-prologue -->\n"
            "## Prologue Detours\n\n"
            "<!-- optional-entry:town-errand -->\n"
            "### Town Errand\n\n"
            "1. After reaching Town, speak to Mina in the town square.\n"
            "2. Recover the parcel from the riverside storehouse, then bring it back to Mina.\n"
            "3. Mina accepts the parcel and Town Errand is complete.\n"
            "# Bosses\n\n"
            "<!-- boss-group:boss-story -->\n"
            "## Story Bosses\n\n"
            "<!-- boss-entry:door-warden -->\n"
            "### Door Warden\n\n"
            "The Door Warden confronts you before Town.\n\n"
            "Battle setup: the protagonist fights alone.\n\n"
            "Door Warden has no encoded elemental weakness or resistance.\n\n"
            "Shield Bash is dangerous because Stun can cost the target its next action.\n\n"
            "Use Fire damage when available, then Guard before Shield Bash.\n\n"
            "Defeating it opens the front door.\n\n"
            "# Scenes & CG\n\n"
            "## Using the Memory Gallery\n\n"
            "Choose Reminisce at the bedroom journal to enter the Memory Gallery.\n\n"
            "After a cleared ending, Unlock All opens every gallery entry; the cards below still explain how to encounter scenes during normal play.\n\n"
            "<!-- scene-group:scene-group-mina -->\n"
            "## Mina\n\n"
            "<!-- scene-entry:scene-town-memory -->\n"
            "### Town Memory\n\n"
            "Town Memory appears in the Memory Gallery after every listed requirement is met.\n\n"
            "Reach Town, then speak to Mina at the fountain to play Town Memory during the journey.\n\n"
            "- Reach Town and speak to Mina at the fountain.\n",
            encoding="utf-8",
        )
        evidence = work / "evidence.json"
        self._write_json(
            evidence,
            {
                "schema_version": 18,
                "milestone": "complete-four-view-walkthrough",
                "dependency_closure": {
                    "artifact": "dependency-closure.json",
                    "index_artifact": "state-dependency-index.json",
                    "required_chain_ids": ["town-errand-chain"],
                    "bindings": [
                        {"guide_record_id": "town-errand", "chain_id": "town-errand-chain"}
                    ],
                },
                "system_reconnaissance": {
                    "inventory_artifact": "systems-inventory.json",
                    "deep_audit_artifacts": ["route-graph.json"],
                    "decisions": {"world-travel": "deep-audit"},
                    "coverage": [
                        {
                            "system_id": "world-travel",
                            "topics": [
                                {
                                    "id": "town-access",
                                    "guide_record_ids": ["reach-town"],
                                    "source_ids": ["front-door-transfer"],
                                }
                            ],
                        }
                    ],
                },
                "project_context": {
                    "glossary": {
                        "file": ".dazedtl/glossary.txt",
                        "sha256": hashlib.sha256(glossary.read_bytes()).hexdigest(),
                    },
                    "quirks": {
                        "file": ".dazedtl/skills/quirks.md",
                        "sha256": hashlib.sha256(quirks.read_bytes()).hexdigest(),
                    },
                },
                "route_structure": {
                    "mode": "chapters-and-sections",
                    "source_label": "Game chapters and in-game objectives",
                    "chapters": [
                        {
                            "id": "prologue",
                            "label": "Prologue",
                            "section_ids": ["objective-reach-town"],
                            "sources": [
                                {
                                    "id": "prologue-label",
                                    "type": "database-record",
                                    "file": "data/Troops.json",
                                    "record_id": 1,
                                    "expected": {"name": "Prologue"},
                                    "supports": "The game groups its opening encounters under Prologue.",
                                },
                                {
                                    "id": "prologue-title-card",
                                    "type": "file-hash",
                                    "file": "img/pictures/Prologue.bin",
                                    "sha256": hashlib.sha256(chapter_card.read_bytes()).hexdigest(),
                                    "supports": "The inspected title card visibly identifies the Prologue.",
                                }
                            ],
                        }
                    ],
                    "sections": [
                        {
                            "id": "objective-reach-town",
                            "label": "Reach Town",
                            "claim_ids": ["reach-town"],
                            "sources": [
                                {
                                    "id": "objective-reach-town-label",
                                    "type": "file-excerpt",
                                    "file": "js/plugins.js",
                                    "contains": 'DestinationText":"Reach Town"',
                                    "supports": "The game's objective system names this route phase Reach Town.",
                                }
                            ],
                        }
                    ],
                },
                "route_claims": [
                    {
                        "id": "reach-town",
                        "kind": "navigation",
                        "status": "verified",
                        "guide_phrases": [
                            "Start at the front door in Home.",
                            "Use the front door to leave Home.",
                            "You arrive in Town.",
                        ],
                        "walkthrough_steps": [
                            {
                                "role": "start",
                                "text": "Start at the front door in Home.",
                                "source_ids": ["home-map-name"],
                            },
                            {
                                "role": "travel",
                                "text": "Use the front door to leave Home.",
                                "source_ids": ["front-door-transfer"],
                            },
                            {
                                "role": "confirmation",
                                "text": "You arrive in Town.",
                                "source_ids": ["front-door-transfer", "town-map-name"],
                            },
                        ],
                        "sources": [
                            {
                                "id": "home-map-name",
                                "type": "database-record",
                                "file": "data/MapInfos.json",
                                "record_id": 1,
                                "expected": {"name": "Home"},
                                "supports": "The route begins on the map named Home.",
                            },
                            {
                                "id": "front-door-transfer",
                                "type": "event-command",
                                "file": "data/Map001.json",
                                "event_id": 1,
                                "page_index": 0,
                                "command_index": 0,
                                "expected": {"code": 201, "parameters": [0, 2, 8, 11, 2, 0]},
                                "supports": "The front door transfers the party to the town map.",
                            },
                            {
                                "id": "town-map-name",
                                "type": "database-record",
                                "file": "data/MapInfos.json",
                                "record_id": 2,
                                "expected": {"name": "Town"},
                                "supports": "The destination map is named Town.",
                            },
                        ],
                    }
                ],
                "optional_content": {
                    "source_label": "Game journal events",
                    "groups": [
                        {
                            "id": "optional-prologue",
                            "label": "Prologue Detours",
                            "route_chapter_id": "prologue",
                            "entry_ids": ["town-errand"],
                        }
                    ],
                    "entries": [
                        {
                            "id": "town-errand",
                            "title": "Town Errand",
                            "kind": "side-event",
                            "status": "verified",
                            "route_anchor_id": "reach-town",
                            "route_anchor_position": "after",
                            "prerequisite_entry_ids": [],
                            "guide_phrases": [
                                "After reaching Town, speak to Mina in the town square.",
                                "Recover the parcel from the riverside storehouse, then bring it back to Mina.",
                                "Mina accepts the parcel and Town Errand is complete.",
                            ],
                            "walkthrough_steps": [
                                {
                                    "role": "start",
                                    "text": "After reaching Town, speak to Mina in the town square.",
                                    "source_ids": ["town-errand-start"],
                                },
                                {
                                    "role": "obtain",
                                    "text": "Recover the parcel from the riverside storehouse, then bring it back to Mina.",
                                    "source_ids": ["town-errand-parcel"],
                                },
                                {
                                    "role": "completion",
                                    "text": "Mina accepts the parcel and Town Errand is complete.",
                                    "source_ids": ["town-errand-complete"],
                                },
                            ],
                            "sources": [
                                {
                                    "id": "town-errand-journal",
                                    "type": "file-excerpt",
                                    "file": "js/plugins.js",
                                    "contains": 'OptionalTitle":"Town Errand"',
                                    "supports": "The journal names this optional event Town Errand.",
                                },
                                {
                                    "id": "town-errand-start",
                                    "type": "file-excerpt",
                                    "file": "js/plugins.js",
                                    "contains": 'OptionalStart":"Mina in Town square"',
                                    "supports": "Mina in the town square starts Town Errand.",
                                },
                                {
                                    "id": "town-errand-parcel",
                                    "type": "file-excerpt",
                                    "file": "js/plugins.js",
                                    "contains": 'OptionalItem":"Parcel from riverside storehouse"',
                                    "supports": "The event requires the parcel from the riverside storehouse.",
                                },
                                {
                                    "id": "town-errand-complete",
                                    "type": "file-excerpt",
                                    "file": "js/plugins.js",
                                    "contains": 'OptionalComplete":"Return parcel to Mina"',
                                    "supports": "Returning the parcel to Mina completes Town Errand.",
                                },
                            ],
                        }
                    ],
                },
                "bosses": {
                    "source_label": "Battle encounters and enemy records",
                    "groups": [
                        {
                            "id": "boss-story",
                            "label": "Story Bosses",
                            "entry_ids": ["door-warden"],
                        }
                    ],
                    "entries": [
                        {
                            "id": "door-warden",
                            "title": "Door Warden",
                            "kind": "story-boss",
                            "status": "verified",
                            "route_claim_ids": ["reach-town"],
                            "optional_entry_ids": [],
                            "guide_phrases": [
                                "The Door Warden confronts you before Town.",
                                "Battle setup: the protagonist fights alone.",
                                "Door Warden has no encoded elemental weakness or resistance.",
                                "Shield Bash is dangerous because Stun can cost the target its next action.",
                                "Use Fire damage when available, then Guard before Shield Bash.",
                                "Defeating it opens the front door.",
                            ],
                            "phases": [
                                {
                                    "label": "Door Warden",
                                    "enemy_id": 1,
                                    "participants": {
                                        "mode": "solo",
                                        "active_actor_ids": [1],
                                        "conditional_actor_ids": [],
                                        "removed_actor_ids": [],
                                        "max_active_battlers": 1,
                                        "text": "Battle setup: the protagonist fights alone.",
                                        "source_ids": ["door-warden-battle"],
                                    },
                                    "stats": {"HP": 100, "SP": 10},
                                    "exp": 20,
                                    "gold": 5,
                                    "drops": "None",
                                    "element_read": "Door Warden has no encoded elemental weakness or resistance.",
                                    "threats": [
                                        {
                                            "text": "Shield Bash is dangerous because Stun can cost the target its next action.",
                                            "source_ids": ["door-warden-enemy", "door-warden-action"],
                                        }
                                    ],
                                    "how_to_win": {
                                        "tools": [],
                                        "plan": [
                                            {
                                                "text": "Use Fire damage when available, then Guard before Shield Bash.",
                                                "source_ids": ["door-warden-enemy", "door-warden-action", "door-warden-guard"],
                                            }
                                        ],
                                    },
                                }
                            ],
                            "sources": [
                                {
                                    "id": "door-warden-battle",
                                    "type": "event-command",
                                    "file": "data/Map001.json",
                                    "event_id": 1,
                                    "page_index": 0,
                                    "command_index": 1,
                                    "expected": {"code": 301, "parameters": [0, 1, True, False]},
                                    "supports": "The front-door event starts the Door Warden battle.",
                                },
                                {
                                    "id": "door-warden-troop",
                                    "type": "database-record",
                                    "file": "data/Troops.json",
                                    "record_id": 1,
                                    "expected": {"members": [{"enemyId": 1, "x": 0, "y": 0}]},
                                    "supports": "The troop contains the Door Warden enemy.",
                                },
                                {
                                    "id": "door-warden-enemy",
                                    "type": "database-record",
                                    "file": "data/Enemies.json",
                                    "record_id": 1,
                                    "expected": {
                                        "name": "Door Warden",
                                        "params": [100, 10, 12, 8, 5, 5, 7, 6],
                                        "exp": 20,
                                        "gold": 5,
                                        "dropItems": [],
                                        "actions": [
                                            {
                                                "skillId": 3,
                                                "rating": 5,
                                                "conditionType": 1,
                                                "conditionParam1": 3,
                                                "conditionParam2": 3,
                                            }
                                        ],
                                        "traits": [],
                                    },
                                    "supports": "The enemy record pins the Door Warden's stats and actions.",
                                },
                                {
                                    "id": "door-warden-action",
                                    "type": "database-record",
                                    "file": "data/Skills.json",
                                    "record_id": 3,
                                    "expected": {
                                        "name": "Shield Bash",
                                        "description": "A heavy strike that can Stun.",
                                        "scope": 1,
                                        "hitType": 1,
                                        "damage": {"type": 1, "elementId": -1, "formula": "a.atk * 4 - b.def * 2"},
                                        "effects": [{"code": 21, "dataId": 11, "value1": 1, "value2": 0}],
                                        "note": "",
                                    },
                                    "supports": "The skill record defines Shield Bash and its Stun effect.",
                                },
                                {
                                    "id": "door-warden-guard",
                                    "type": "database-record",
                                    "file": "data/Skills.json",
                                    "record_id": 2,
                                    "expected": {
                                        "name": "Guard",
                                        "scope": 11,
                                        "effects": [{"code": 21, "dataId": 2, "value1": 1, "value2": 0}],
                                        "note": "standard defense command",
                                    },
                                    "supports": "The skill record defines the standard Guard command.",
                                },
                            ],
                        }
                    ],
                },
                "scenes_cg": {
                    "source_label": "Player-facing scene catalog and executable unlock path",
                    "catalog": {
                        "id": "scenes-cg-system",
                        "title": "Using the Memory Gallery",
                        "entry_count": 1,
                        "cg_image_count": 1,
                        "interface_files": ["data/SceneCatalog.json"],
                        "completion_shortcut": "After a cleared ending, Unlock All opens every gallery entry; the cards below still explain how to encounter scenes during normal play.",
                        "guide_phrases": [
                            "Choose Reminisce at the bedroom journal to enter the Memory Gallery.",
                            "After a cleared ending, Unlock All opens every gallery entry; the cards below still explain how to encounter scenes during normal play.",
                        ],
                        "source_roles": {
                            "entry_point": ["scene-catalog-entry"],
                            "scope_boundary": ["scene-catalog-slots"],
                            "completion_shortcut": ["scene-catalog-unlock-all"],
                        },
                        "sources": [
                            {
                                "id": "scene-catalog-entry",
                                "type": "database-record",
                                "file": "data/SceneCatalog.json",
                                "record_id": 1,
                                "expected": {"entryPoint": "Bedroom journal"},
                                "supports": "The bedroom journal opens the Memory Gallery.",
                            },
                            {
                                "id": "scene-catalog-slots",
                                "type": "database-record",
                                "file": "data/SceneCatalog.json",
                                "record_id": 2,
                                "expected": {"slots": ["Town Memory"]},
                                "supports": "The gallery's configured slots define its illustrated catalog.",
                            },
                            {
                                "id": "scene-catalog-unlock-all",
                                "type": "database-record",
                                "file": "data/SceneCatalog.json",
                                "record_id": 9,
                                "expected": {"unlockAll": "after-cleared-ending"},
                                "supports": "The gallery exposes its completion shortcut after a cleared ending.",
                            },
                        ],
                    },
                    "groups": [
                        {
                            "id": "scene-group-mina",
                            "label": "Mina",
                            "route_anchor_id": "reach-town",
                            "route_anchor_position": "after",
                            "entry_ids": ["scene-town-memory"],
                        }
                    ],
                    "entries": [
                        {
                            "id": "scene-town-memory",
                            "title": "Town Memory",
                            "catalog_title": "Town Memory",
                            "kind": "character-scene",
                            "status": "verified",
                            "group_id": "scene-group-mina",
                            "route_anchor_id": "reach-town",
                            "route_anchor_position": "after",
                            "prerequisite_scene_ids": [],
                            "story_gate_claim_ids": ["reach-town"],
                            "acquisition_mode": "normal-play",
                            "acquisition_steps": [
                                "Reach Town, then speak to Mina at the fountain to play Town Memory during the journey."
                            ],
                            "requirements": ["Reach Town and speak to Mina at the fountain."],
                            "aliases": [],
                            "viewer_mode": "replay-and-cg-gallery",
                            "cg_image_count": 1,
                            "guide_phrases": [
                                "Town Memory appears in the Memory Gallery after every listed requirement is met.",
                                "Reach Town, then speak to Mina at the fountain to play Town Memory during the journey.",
                                "Reach Town and speak to Mina at the fountain.",
                            ],
                            "source_roles": {
                                "requirements": ["scene-town-memory-requirements"],
                                "availability": ["scene-town-memory-trigger"],
                                "replay_title": ["scene-town-memory-title"],
                                "replay_call": ["scene-town-memory-replay"],
                                "normal_acquisition": ["scene-town-memory-trigger"],
                                "live_trigger": ["scene-town-memory-trigger"],
                                "live_completion": ["scene-town-memory-unlock"],
                                "unlock": ["scene-town-memory-unlock"],
                                "cg_viewer": ["scene-town-memory-cg"],
                            },
                            "sources": [
                                {
                                    "id": "scene-town-memory-requirements",
                                    "type": "database-record",
                                    "file": "data/SceneCatalog.json",
                                    "record_id": 3,
                                    "expected": {"requirements": ["Reach Town", "Speak to Mina"]},
                                    "supports": "The locked entry displays the complete player-facing requirement.",
                                },
                                {
                                    "id": "scene-town-memory-title",
                                    "type": "database-record",
                                    "file": "data/SceneCatalog.json",
                                    "record_id": 4,
                                    "expected": {"title": "Town Memory"},
                                    "supports": "The unlocked catalog names the entry Town Memory.",
                                },
                                {
                                    "id": "scene-town-memory-replay",
                                    "type": "database-record",
                                    "file": "data/SceneCatalog.json",
                                    "record_id": 5,
                                    "expected": {"replay": "town-memory"},
                                    "supports": "The catalog dispatches the Town Memory replay.",
                                },
                                {
                                    "id": "scene-town-memory-trigger",
                                    "type": "database-record",
                                    "file": "data/LiveScenes.json",
                                    "record_id": 1,
                                    "expected": {"trigger": "Mina fountain"},
                                    "supports": "A reachable fountain interaction triggers Town Memory.",
                                },
                                {
                                    "id": "scene-town-memory-unlock",
                                    "type": "database-record",
                                    "file": "data/LiveScenes.json",
                                    "record_id": 2,
                                    "expected": {"unlock": "town-memory"},
                                    "supports": "Completing the live event unlocks its catalog entry.",
                                },
                                {
                                    "id": "scene-town-memory-cg",
                                    "type": "database-record",
                                    "file": "data/SceneCatalog.json",
                                    "record_id": 8,
                                    "expected": {"illustratedSet": "town-memory-a"},
                                    "supports": "The viewer includes one illustrated set for Town Memory.",
                                },
                            ],
                        }
                    ],
                },
            },
        )
        self._write_json(
            work / "systems-inventory.json",
            {
                "schema_version": 1,
                "game": "Fixture",
                "systems": [
                    {
                        "id": "world-travel",
                        "name": "World travel",
                        "status": "enabled-and-active",
                        "decision": "deep-audit",
                        "required_topics": [
                            {"id": "town-access", "label": "Reach the first town"}
                        ],
                    }
                ],
            },
        )
        self._write_json(
            work / "state-dependency-index.json",
            walkthrough_validator.build_index(root),
        )
        self._write_json(
            work / "dependency-closure.json",
            {
                "schema_version": 1,
                "game": "Fixture",
                "chains": [
                    {
                        "id": "town-errand-chain",
                        "title": "Town Errand dependency chain",
                        "coverage_status": "complete",
                        "terminal_node_ids": ["town-errand-complete"],
                        "nodes": [
                            {
                                "id": "leave-home",
                                "kind": "player-action",
                                "text": "Leave Home through the front door.",
                                "source_ids": ["front-door-transfer"],
                                "predecessor_ids": [],
                            },
                            {
                                "id": "town-errand-complete",
                                "kind": "terminal",
                                "text": "Town Errand is available in Town.",
                                "source_ids": ["town-errand-journal"],
                                "predecessor_ids": ["leave-home"],
                            },
                        ],
                        "invalidators": [],
                        "unresolved_leaf_ids": [],
                        "tracked_carriers": [
                            {
                                "kind": "switch",
                                "id": 5,
                                "classified_sites": [
                                    {
                                        "site_id": "map-001-event-001-page-000-command-0002-switch-0005",
                                        "node_ids": ["town-errand-complete"],
                                    },
                                    {
                                        "site_id": "map-001-event-001-page-000-command-0003-switch-0005",
                                        "node_ids": ["town-errand-complete"],
                                    },
                                ],
                                "excluded_sites": [],
                            }
                        ],
                    }
                ],
            },
        )
        publication = root / "WALKTHROUGH.html"
        publication.write_text(self._html(), encoding="utf-8")
        return walkthrough, evidence, publication

    def _validate(self, root: Path, walkthrough: Path, evidence: Path, publication: Path) -> dict:
        return walkthrough_validator.validate_project(root, walkthrough, evidence, publication)

    def test_verified_claim_and_four_view_publication_pass(self):
        """Protect all four completed views and the exact four-view milestone contract."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "passed", report["issues"])
            self.assertEqual(report["summary"]["verified"], 1)
            self.assertEqual(report["summary"]["optional_verified"], 1)
            self.assertEqual(report["summary"]["boss_verified"], 1)
            self.assertEqual(report["summary"]["scene_verified"], 1)
            self.assertEqual(report["summary"]["scene_cg_images"], 1)
            self.assertEqual(set(report["publication"]["views"]), set(walkthrough_validator.REQUIRED_VIEWS))

    def test_route_and_optional_records_reject_vague_one_row_summaries(self):
        """Protect player routes from collapsing back into endpoint-only summaries."""
        cases = (
            (("route_claims", 0), "confirmation", "route-claim-invalid"),
            (("optional_content", "entries", 0), "completion", "optional-entry-invalid"),
        )
        for path, terminal_role, issue_code in cases:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                walkthrough, evidence, publication = self._build_project(root)
                manifest = json.loads(evidence.read_text(encoding="utf-8"))
                record = manifest
                for key in path:
                    record = record[key]
                record["walkthrough_steps"] = [
                    {
                        "role": terminal_role,
                        "text": record["guide_phrases"][-1],
                        "source_ids": [record["sources"][-1]["id"]],
                    }
                ]
                self._write_json(evidence, manifest)

                report = self._validate(root, walkthrough, evidence, publication)

                self.assertEqual(report["status"], "failed")
                issue = next(row for row in report["issues"] if row["code"] == issue_code)
                self.assertIn("at least three source-bound rows", " ".join(issue["failures"]))

    def test_publication_requires_ordered_walkthrough_lists(self):
        """Protect the visible step-by-step presentation, not only its evidence manifest."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                publication.read_text(encoding="utf-8").replace(
                    'class="walkthrough-steps" data-walkthrough-id="town-errand"',
                    'class="walkthrough-summary" data-walkthrough-id="town-errand"',
                    1,
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            self.assertTrue(
                any(row["code"] == "optional-walkthrough-list-invalid" for row in report["issues"])
            )

    def test_changed_boss_enemy_snapshot_blocks_publication(self):
        """Protect published boss stats from silently surviving changed enemy data."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            enemies = json.loads((root / "data" / "Enemies.json").read_text(encoding="utf-8"))
            enemies[1]["params"][0] = 999
            self._write_json(root / "data" / "Enemies.json", enemies)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "boss-entry-invalid")
            self.assertIn("field 'params' changed", " ".join(issue["failures"]))

    def test_scene_entry_requires_source_bound_illustrated_sets(self):
        """Protect catalog counts from drifting away from the viewer references that prove them."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["scenes_cg"]["entries"][0]["source_roles"]["cg_viewer"] = []
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "scene-entry-invalid")
            self.assertIn("source_roles.cg_viewer", " ".join(issue["failures"]))

    def test_scene_normal_acquisition_cannot_be_the_gallery_interface(self):
        """Protect scene guides from presenting recollection access as the normal live trigger."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            entry = manifest["scenes_cg"]["entries"][0]
            trigger = next(source for source in entry["sources"] if source["id"] == "scene-town-memory-trigger")
            trigger.update(file="data/SceneCatalog.json", record_id=6)
            unlock = next(source for source in entry["sources"] if source["id"] == "scene-town-memory-unlock")
            unlock.update(file="data/SceneCatalog.json", record_id=7)
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "scene-entry-invalid")
            self.assertIn("outside the catalog/recollection interface", " ".join(issue["failures"]))

    def test_combat_scene_requires_player_visible_enemy_and_encounter_attribution(self):
        """Protect combat-scene cards from exposing only a numbered animation or generic opponent."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["scenes_cg"]["entries"][0]["kind"] = "combat-scene"
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "scene-entry-invalid")
            failures = " ".join(issue["failures"])
            self.assertIn("combatants", failures)
            self.assertIn("encounter_locations", failures)
            self.assertIn("combat_mechanic", failures)
            self.assertIn("combat_enemy", failures)
            self.assertIn("combat_trigger", failures)
            self.assertIn("encounter_access", failures)

    def test_combat_scene_guide_title_must_name_every_required_enemy(self):
        """Protect scene navigation from retaining a generic numbered combat heading."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            entry = manifest["scenes_cg"]["entries"][0]
            requirement = "On Lead Mine Road, fight Ghost S and Dominated Warrior."
            mechanic = "Let Ghost S restrain Fumika, then allow Dominated Warrior's follow-up attack."
            entry.update(
                title="Combat 6",
                catalog_title="Combat 6",
                kind="combat-scene",
                requirements=[requirement],
                acquisition_steps=[mechanic],
                combatants=["Ghost S", "Dominated Warrior"],
                encounter_locations=["Lead Mine Road"],
                combat_mechanic=mechanic,
                guide_phrases=[requirement, mechanic],
            )
            entry["source_roles"].update(
                combat_enemy=["scene-town-memory-trigger"],
                combat_trigger=["scene-town-memory-trigger"],
                encounter_access=["scene-town-memory-trigger"],
            )
            self._write_json(evidence, manifest)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8") + f"\n### Combat 6\n\n{requirement}\n\n{mechanic}\n",
                encoding="utf-8",
            )
            publication.write_text(
                publication.read_text(encoding="utf-8")
                .replace('data-catalog-title="Town Memory"', 'data-catalog-title="Combat 6"')
                .replace('<h3 id="scene-town-memory">Town Memory</h3>', '<h3 id="scene-town-memory">Combat 6</h3>')
                .replace(
                    '<p>Town Memory appears in the Memory Gallery after every listed requirement is met.</p>',
                    f'<p>{requirement} {mechanic}</p>',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "scene-entry-invalid")
            failures = " ".join(issue["failures"])
            self.assertIn("combat-scene title must name combatant 'Ghost S'", failures)
            self.assertIn("combat-scene title must name combatant 'Dominated Warrior'", failures)

    def test_specific_scene_guide_title_preserves_the_exact_catalog_title(self):
        """Protect distinct guide and catalog titles as one rendered, source-traceable entry."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["scenes_cg"]["entries"][0]["title"] = "Mina at the Town Fountain"
            self._write_json(evidence, manifest)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8").replace(
                    "### Town Memory\n\n",
                    "### Mina at the Town Fountain\n\nRecollection title: Town Memory\n\n",
                ),
                encoding="utf-8",
            )
            publication.write_text(
                publication.read_text(encoding="utf-8").replace(
                    '<h3 id="scene-town-memory">Town Memory</h3>',
                    '<h3 id="scene-town-memory">Mina at the Town Fountain</h3><p class="scene-catalog-title"><strong>Recollection title:</strong> Town Memory</p>',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "passed", report["issues"])

    def test_scene_group_requires_link_from_declared_route_anchor(self):
        """Protect scene availability links from drifting away from their route context."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    '<a data-guide-link data-guide-kind="scene" data-guide-link-position="after" href="#scene-group-mina">',
                    '<a href="#scene-group-mina">',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("scene-main-route-link-invalid", codes)

    def test_scene_entry_requires_link_from_its_exact_availability_anchor(self):
        """Protect individual scene timing from being hidden behind a broad catalog-group link."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    '<a data-guide-link data-guide-kind="scene" data-guide-link-position="after" href="#scene-town-memory">',
                    '<a href="#scene-town-memory">',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("scene-entry-main-route-link-invalid", codes)

    def test_scene_availability_cannot_precede_its_story_gate(self):
        """Protect chronological scene notices from appearing before their proven story gate."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            earlier = json.loads(json.dumps(manifest["route_claims"][0]))
            earlier["id"] = "opening-door"
            earlier["guide_phrases"] = ["The opening door is ready."]
            for source in earlier["sources"]:
                source["id"] = f'opening-{source["id"]}'
            manifest["route_claims"].insert(0, earlier)
            manifest["route_structure"]["sections"][0]["claim_ids"].insert(0, "opening-door")
            scene = manifest["scenes_cg"]["entries"][0]
            scene["route_anchor_id"] = "opening-door"
            manifest["scenes_cg"]["groups"][0]["route_anchor_id"] = "opening-door"
            self._write_json(evidence, manifest)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8").replace(
                    "<!-- route-claim:reach-town -->",
                    "<!-- route-claim:opening-door -->\nThe opening door is ready.\n\n<!-- route-claim:reach-town -->",
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("scene-availability-order-invalid", codes)

    def test_scene_availability_cannot_be_delayed_past_its_proven_boundary(self):
        """Protect open-world scene notices from being postponed to a convenient later route visit."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            later = json.loads(json.dumps(manifest["route_claims"][0]))
            later["id"] = "late-cleanup"
            later["guide_phrases"] = ["Late cleanup begins."]
            for source in later["sources"]:
                source["id"] = f'late-{source["id"]}'
            manifest["route_claims"].append(later)
            manifest["route_structure"]["sections"][0]["claim_ids"].append("late-cleanup")
            scene = manifest["scenes_cg"]["entries"][0]
            scene["route_anchor_id"] = "late-cleanup"
            manifest["scenes_cg"]["groups"][0]["route_anchor_id"] = "late-cleanup"
            self._write_json(evidence, manifest)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8")
                + "\n<!-- route-claim:late-cleanup -->\nLate cleanup begins.\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "scene-availability-order-invalid")
            self.assertIn("later than", " ".join(issue["failures"]))

    def test_main_route_cross_tab_links_require_their_content_kind(self):
        """Protect the red, orange, and purple route-link categories from becoming ambiguous."""
        cases = {
            "boss": (
                'data-guide-kind="boss" href="#boss-door-warden"',
                'data-guide-kind="scene" href="#boss-door-warden"',
                "boss-main-route-link-kind-invalid",
            ),
            "optional": (
                'data-guide-kind="optional" data-guide-link-position="after" href="#town-errand"',
                'data-guide-kind="boss" data-guide-link-position="after" href="#town-errand"',
                "optional-main-route-link-kind-invalid",
            ),
            "scene": (
                'data-guide-kind="scene" data-guide-link-position="after" href="#scene-town-memory"',
                'data-guide-kind="optional" data-guide-link-position="after" href="#scene-town-memory"',
                "scene-entry-main-route-link-kind-invalid",
            ),
        }
        for label, (old, new, expected_code) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                walkthrough, evidence, publication = self._build_project(root)
                publication.write_text(self._html().replace(old, new), encoding="utf-8")

                report = self._validate(root, walkthrough, evidence, publication)

                self.assertEqual(report["status"], "failed")
                codes = {row["code"] for row in report["issues"]}
                self.assertIn(expected_code, codes)

    def test_rendered_boss_stat_must_match_the_single_canonical_table(self):
        """Protect the visible stat table without requiring a duplicate prose stat line."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    '<td data-boss-stat="HP">100</td>',
                    '<td data-boss-stat="HP">999</td>',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("boss-stat-value-mismatch", codes)

    def test_boss_threat_and_strategy_rows_must_cite_local_sources(self):
        """Protect player-facing boss advice from becoming unsupported prose."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            phase = manifest["bosses"]["entries"][0]["phases"][0]
            phase["threats"][0]["source_ids"] = ["missing-boss-source"]
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "boss-entry-invalid")
            self.assertIn("cites unknown source_ids", " ".join(issue["failures"]))

    def test_boss_phase_requires_source_bound_encounter_participants(self):
        """Protect solo and temporary-party fights from inheriting the wider story party."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            phase = manifest["bosses"]["entries"][0]["phases"][0]
            phase.pop("participants")
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "boss-entry-invalid")
            self.assertIn("participants must be an object", " ".join(issue["failures"]))

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            participants = manifest["bosses"]["entries"][0]["phases"][0]["participants"]
            participants["max_active_battlers"] = 2
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "boss-entry-invalid")
            self.assertIn("without exceeding", " ".join(issue["failures"]))

    def test_boss_dossier_requires_link_from_declared_route_encounter(self):
        """Protect route-to-boss navigation from drifting away from the encounter it documents."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    '<a data-guide-link data-guide-kind="boss" href="#boss-door-warden">Door Warden</a>',
                    '<a href="#boss-door-warden">Door Warden</a>',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("boss-main-route-link-invalid", codes)

    def test_changed_optional_source_snapshot_blocks_publication(self):
        """Protect optional-event instructions from silently surviving changed game data."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["optional_content"]["entries"][0]["sources"][0]["contains"] = (
                'OptionalTitle":"Missing Errand"'
            )
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "optional-entry-invalid")
            self.assertIn("exact excerpt is no longer present", " ".join(issue["failures"]))

    def test_companion_entry_requires_source_bound_success_and_failure_paths(self):
        """Protect recruit guides from omitting the actual join outcome or irreversible failure analysis."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["optional_content"]["entries"][0]["kind"] = "companion-recruitment"
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "optional-entry-invalid")
            self.assertIn("recruitment object", " ".join(issue["failures"]))

    def test_companion_entry_requires_complete_dependency_chain_binding(self):
        """Protect a verified recruit suffix from being published as a complete recruitment route."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            entry = manifest["optional_content"]["entries"][0]
            entry["kind"] = "companion-recruitment"
            entry["recruitment"] = {
                "success_steps": [
                    {
                        "text": entry["guide_phrases"][0],
                        "source_ids": ["town-errand-journal"],
                    }
                ],
                "failure_modes": [
                    {
                        "kind": "retryable",
                        "text": entry["guide_phrases"][0],
                        "source_ids": ["town-errand-journal"],
                    }
                ],
            }
            manifest["dependency_closure"]["bindings"] = []
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "dependency-closure-invalid")
            self.assertIn("companion recruitment", " ".join(issue["failures"]))

    def test_complete_dependency_chain_rejects_unresolved_leaf(self):
        """Protect coverage-complete claims from hiding an opaque or untraced prerequisite."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            closure_path = evidence.parent / "dependency-closure.json"
            closure = json.loads(closure_path.read_text(encoding="utf-8"))
            chain = closure["chains"][0]
            chain["nodes"][0]["kind"] = "unresolved"
            chain["unresolved_leaf_ids"] = [chain["nodes"][0]["id"]]
            self._write_json(closure_path, closure)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "dependency-chain-invalid")
            self.assertIn("complete chains cannot contain unresolved leaves", " ".join(issue["failures"]))

    def test_tracked_carrier_requires_every_indexed_site_to_be_classified(self):
        """Protect dependency reviews from silently ignoring another read or write of the same state carrier."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            closure_path = evidence.parent / "dependency-closure.json"
            closure = json.loads(closure_path.read_text(encoding="utf-8"))
            closure["chains"][0]["tracked_carriers"][0]["classified_sites"].pop()
            self._write_json(closure_path, closure)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "dependency-chain-invalid")
            self.assertIn("unclassified", " ".join(issue["failures"]))

    def test_dependency_index_captures_state_and_flow_sites(self):
        """Protect the reusable index from missing the branch, state, battle, and transfer primitives closures need."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._build_project(root)

            index = walkthrough_validator.build_index(root)

            carrier_roles = {
                (row["carrier"]["kind"], row["carrier"]["id"], row["role"])
                for row in index["carrier_sites"]
            }
            flow_kinds = {row["kind"] for row in index["flow_sites"]}
            self.assertIn(("switch", 5, "write"), carrier_roles)
            self.assertIn(("switch", 5, "read"), carrier_roles)
            self.assertTrue({"battle", "transfer"}.issubset(flow_kinds))

    def test_dependency_index_can_focus_a_high_frequency_decisive_carrier(self):
        """Protect complete closure audits from losing a decisive carrier to index compaction."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            self._build_project(root)
            map_path = root / "data" / "Map001.json"
            map_data = json.loads(map_path.read_text(encoding="utf-8"))
            commands = map_data["events"][1]["pages"][0]["list"]
            commands[:0] = [
                {"code": 121, "indent": 0, "parameters": [6, 6, 0]}
                for _ in range(501)
            ]
            self._write_json(map_path, map_data)

            compact = walkthrough_validator.build_index(root)
            focused = walkthrough_validator.build_index(root, {("switch", 6)})

            self.assertIn(
                {"kind": "switch", "id": 6, "site_count": 501},
                compact["omitted_high_frequency_carriers"],
            )
            self.assertFalse(
                any(row["carrier"] == {"kind": "switch", "id": 6} for row in compact["carrier_sites"])
            )
            self.assertEqual(
                501,
                sum(
                    row["carrier"] == {"kind": "switch", "id": 6}
                    for row in focused["carrier_sites"]
                ),
            )

    def test_deep_audit_required_topic_must_bind_guide_and_source_records(self):
        """Protect selected deep audits from being marked complete without player-facing coverage."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["system_reconnaissance"]["coverage"] = []
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(
                row for row in report["issues"] if row["code"] == "system-deep-audit-coverage-invalid"
            )
            self.assertIn("coverage", " ".join(issue["failures"]))

    def test_unknown_optional_prerequisite_blocks_publication(self):
        """Protect players from being sent through a dependency that has no guide entry."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            manifest["optional_content"]["entries"][0]["prerequisite_entry_ids"] = [
                "missing-prerequisite"
            ]
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("optional-prerequisite-missing", codes)

    def test_optional_entry_requires_link_from_declared_route_anchor(self):
        """Protect first-availability links from drifting to the wrong Main Route step."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    '<a data-guide-link data-guide-kind="optional" data-guide-link-position="after" href="#town-errand">Town Errand</a>',
                    '<a data-guide-link data-guide-kind="optional" data-guide-link-position="after" href="#optional-prologue">Town Errand</a>',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            codes = {row["code"] for row in report["issues"]}
            self.assertIn("optional-main-route-link-invalid", codes)

    def test_optional_entry_requires_declared_before_or_after_placement(self):
        """Protect timely detour notices from always drifting below a completed route step."""
        link_line = (
            '            <aside><a data-guide-link data-guide-kind="optional" data-guide-link-position="after" '
            'href="#town-errand">Town Errand</a> is now available.</aside>\n'
        )
        cases = {
            "wrong declared position": (
                lambda source: source.replace(
                    'data-guide-link-position="after" href="#town-errand"',
                    'data-guide-link-position="before" href="#town-errand"',
                ),
                "optional-main-route-link-position-invalid",
            ),
            "wrong document order": (
                lambda source: source.replace(link_line, "").replace(
                    '            <ol class="walkthrough-steps" data-walkthrough-id="reach-town">',
                    link_line + '            <ol class="walkthrough-steps" data-walkthrough-id="reach-town">',
                ),
                "optional-main-route-link-order-invalid",
            ),
        }
        for label, (mutate, expected_code) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                walkthrough, evidence, publication = self._build_project(root)
                publication.write_text(mutate(self._html()), encoding="utf-8")

                report = self._validate(root, walkthrough, evidence, publication)

                self.assertEqual(report["status"], "failed")
                codes = {row["code"] for row in report["issues"]}
                self.assertIn(expected_code, codes)

    def test_changed_source_snapshot_blocks_publication(self):
        """Protect route facts from silently surviving changed executable game data."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            transfer_source = next(
                source
                for source in manifest["route_claims"][0]["sources"]
                if source["id"] == "front-door-transfer"
            )
            transfer_source["expected"]["parameters"][1] = 99
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            claim_issue = next(issue for issue in report["issues"] if issue["code"] == "route-claim-invalid")
            self.assertIn("command parameters changed", " ".join(claim_issue["failures"]))

    def test_changed_chapter_title_card_is_rejected(self):
        """Protect visually inspected chapter labels from silently outliving their source asset."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            (root / "img" / "pictures" / "Prologue.bin").write_bytes(b"changed title card")

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "route-chapter-invalid")
            self.assertIn("file hash changed", " ".join(issue["failures"]))

    def test_missing_view_and_rendered_evidence_source_are_rejected(self):
        """Protect usable tabs and the visible claim-to-source audit trail."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html(source_id="wrong-source", bosses_class="unfinished-view"),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = {issue["code"] for issue in report["issues"]}
            self.assertEqual(report["status"], "failed")
            self.assertIn("guide-views-invalid", codes)
            self.assertIn("rendered-evidence-sources-mismatch", codes)

    def test_route_step_must_stay_in_its_source_backed_section(self):
        """Protect game-authored objective organization from drifting during HTML rendering."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    'data-section-id="objective-reach-town"',
                    'data-section-id="invented-chapter"',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = {issue["code"] for issue in report["issues"]}
            self.assertEqual(report["status"], "failed")
            self.assertIn("route-step-section-context-invalid", codes)
            self.assertIn("rendered-section-undeclared", codes)

    def test_route_section_heading_must_be_a_direct_navigation_target(self):
        """Protect objective-level sidebar navigation from disappearing during rendering."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    '<h3 id="objective-reach-town">',
                    '<h3 id="unlinked-objective">',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = {issue["code"] for issue in report["issues"]}
            self.assertEqual(report["status"], "failed")
            self.assertIn("route-section-heading-link-invalid", codes)

    def test_route_section_must_stay_in_its_source_backed_chapter(self):
        """Protect game-authored chapter boundaries from drifting during HTML rendering."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace(
                    'data-chapter-id="prologue"',
                    'data-chapter-id="invented-chapter"',
                ),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = {issue["code"] for issue in report["issues"]}
            self.assertEqual(report["status"], "failed")
            self.assertIn("route-section-chapter-context-invalid", codes)
            self.assertIn("rendered-chapter-undeclared", codes)

    def test_unverified_claim_is_rejected_instead_of_exposing_live_play_checks(self):
        """Protect players from internal live-play caveats while keeping core route claims verified."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            manifest = json.loads(evidence.read_text(encoding="utf-8"))
            claim = manifest["route_claims"][0]
            claim["status"] = "requires-playtest"
            self._write_json(evidence, manifest)

            report = self._validate(root, walkthrough, evidence, publication)

            self.assertEqual(report["status"], "failed")
            issue = next(row for row in report["issues"] if row["code"] == "route-claim-invalid")
            self.assertIn("status must be one of", " ".join(issue["failures"]))

    def test_misbound_route_checkbox_is_rejected(self):
        """Protect persisted checklist progress from silently binding to the wrong route step."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            publication.write_text(
                self._html().replace('data-task-id="reach-town"', 'data-task-id="wrong-step"'),
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = {issue["code"] for issue in report["issues"]}
            self.assertEqual(report["status"], "failed")
            self.assertIn("route-task-binding-invalid", codes)
            self.assertIn("rendered-task-undeclared", codes)

    def test_player_copy_rejects_coordinates_and_developer_ids(self):
        """Protect directions from exposing data that only an event editor can see."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8")
                + "Continue from Map001 at (8, 11).\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = [issue["code"] for issue in report["issues"]]
            self.assertEqual(report["status"], "failed")
            self.assertIn("technical-locator-in-player-copy", codes)

    def test_player_copy_rejects_mechanical_progression_jargon(self):
        """Protect the Main Route from reading like an event-state audit instead of a player guide."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8")
                + "The victory branch advances the route state.\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = [issue["code"] for issue in report["issues"]]
            self.assertEqual(report["status"], "failed")
            self.assertIn("mechanical-progression-language", codes)

    def test_player_copy_rejects_engine_control_codes(self):
        """Protect browser prose from leaking RPG engine formatting escapes."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8")
                + r"Bring \C[24]Red Wine\C[0] to the bedroom."
                + "\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = [issue["code"] for issue in report["issues"]]
            self.assertEqual(report["status"], "failed")
            self.assertIn("engine-control-code-in-player-copy", codes)

    def test_changed_project_glossary_blocks_publication(self):
        """Protect generated prose from silently outliving its glossary and quirks context."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            (root / ".dazedtl" / "glossary.txt").write_text(
                "# Game Characters\nミナ (Mina) - Male guide who waits by the door.\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = [issue["code"] for issue in report["issues"]]
            self.assertEqual(report["status"], "failed")
            self.assertIn("project-context-invalid", codes)

    def test_glossary_gender_rejects_conflicting_pronoun(self):
        """Protect known character identities when natural guide prose uses later pronouns."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8")
                + "\nMina leads you outside. Stay with him until the next scene.\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = [issue["code"] for issue in report["issues"]]
            self.assertEqual(report["status"], "failed")
            self.assertIn("glossary-pronoun-conflict", codes)

    def test_glossary_name_rejects_near_miss(self):
        """Protect canonical project names from plausible-looking one-letter drift."""
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            walkthrough, evidence, publication = self._build_project(root)
            walkthrough.write_text(
                walkthrough.read_text(encoding="utf-8")
                + "\nSpeak to Intigue before entering the Meeting Hall.\n",
                encoding="utf-8",
            )

            report = self._validate(root, walkthrough, evidence, publication)

            codes = [issue["code"] for issue in report["issues"]]
            self.assertEqual(report["status"], "failed")
            self.assertIn("glossary-name-near-miss", codes)


if __name__ == "__main__":
    unittest.main()
