"""Behavior tests for the local AI-helper QA task engine."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from util import rpgmaker_qa


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=4) + "\n", encoding="utf-8"
    )


class RPGMakerQAEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.game = self.root / "game"
        self.data = self.game / "data"
        self.data.mkdir(parents=True)
        (self.game / ".dazedtl" / "skills").mkdir(parents=True)
        (self.game / ".dazedtl" / "glossary.txt").write_text(
            "薬 (Potion)\n", encoding="utf-8"
        )
        (self.game / ".dazedtl" / "skills" / "game.md").write_text(
            "Keep item effects exact.\n", encoding="utf-8"
        )
        (self.game / ".dazedtl" / "skills" / "quirks.md").write_text(
            "", encoding="utf-8"
        )
        _write(
            self.data / "Items.json",
            [
                None,
                {
                    "id": 1,
                    "name": "Potion",
                    "description": "Restores health.",
                    "_original": {"name": "薬", "description": "体力を回復する。"},
                },
                {
                    "id": 2,
                    "name": "Key",
                    "description": "Opens the door.",
                    "_original": {"name": "鍵", "description": "扉を開ける。"},
                },
            ],
        )

    def _prepare(self, **kwargs):
        return rpgmaker_qa.prepare_task(
            self.game,
            self.data,
            "database",
            self.root / "tasks",
            **kwargs,
        )[0]

    def _accept_clean_screen(self, task: Path, *, suspect_source: str = "") -> None:
        while True:
            assignment = rpgmaker_qa.next_bundle(task, "screen-worker")
            if assignment is None:
                break
            bundle = json.loads(Path(assignment["path"]).read_text(encoding="utf-8"))
            exceptions = [{
                "id": item["id"],
                "verdict": "suspect",
                "categories": ["meaning"],
                "note": "Meaning may be incorrect.",
            } for item in bundle["items"] if item["source"] == suspect_source]
            result = self.root / f"{assignment['id']}-result.json"
            _write(result, {
                "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": assignment["id"],
                "bundle_sha256": assignment["sha256"],
                "reviewed_all": True,
                "exceptions": exceptions,
                "motif_reviews": [],
            })
            rpgmaker_qa.accept_result(task, result)

    def test_clean_receipts_cover_every_screen_item_and_claims_do_not_overlap(self):
        task = self._prepare(screen_item_limit=1)
        first = rpgmaker_qa.next_bundle(task, "worker-one")
        second = rpgmaker_qa.next_bundle(task, "worker-two")
        self.assertNotEqual(first["id"], second["id"])
        assigned = rpgmaker_qa.status(task)["screen"]
        self.assertEqual(assigned["bundles_assigned"], 2)
        self.assertEqual(
            assigned["assigned_workers"], ["worker-one", "worker-two"]
        )

        for assignment in (first, second):
            result = self.root / f"{assignment['id']}.json"
            _write(result, {
                "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": assignment["id"],
                "bundle_sha256": assignment["sha256"],
                "reviewed_all": True,
                "exceptions": [],
                "motif_reviews": [],
            })
            state = rpgmaker_qa.accept_result(task, result)
        self.assertEqual(state["screen"]["accepted"], 2)
        self.assertEqual(state["screen"]["total"], 4)

    def test_screen_result_rejects_unknown_identity_without_advancing_coverage(self):
        task = self._prepare()
        assignment = rpgmaker_qa.next_bundle(task, "worker")
        result = self.root / "invalid.json"
        _write(result, {
            "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
            "bundle_id": assignment["id"],
            "bundle_sha256": assignment["sha256"],
            "reviewed_all": True,
            "exceptions": [{
                "id": "not-in-this-bundle",
                "verdict": "suspect",
                "categories": ["meaning"],
                "note": "Wrong line",
            }],
            "motif_reviews": [],
        })
        with self.assertRaises(rpgmaker_qa.QAResultError):
            rpgmaker_qa.accept_result(task, result)
        self.assertEqual(rpgmaker_qa.status(task)["screen"]["accepted"], 0)

    def test_abandoned_claim_can_be_released_without_changing_coverage(self):
        task = self._prepare(screen_item_limit=1)
        assignment = rpgmaker_qa.next_bundle(task, "interrupted-worker")
        state = rpgmaker_qa.release_bundle(task, assignment["id"])
        self.assertEqual(state["screen"]["accepted"], 0)
        reclaimed = rpgmaker_qa.next_bundle(task, "replacement-worker")
        self.assertEqual(reclaimed["id"], assignment["id"])

    def test_inconsistent_source_alternatives_are_screened_without_forced_deep_review(self):
        items = json.loads((self.data / "Items.json").read_text(encoding="utf-8"))
        items.append({
            "id": 3,
            "name": "Medicine",
            "description": "Restores mana.",
            "_original": {"name": "薬", "description": "魔力を回復する。"},
        })
        _write(self.data / "Items.json", items)
        task = self._prepare()
        matching = []
        for path in (task / "bundles" / "screen").glob("*.json"):
            bundle = json.loads(path.read_text(encoding="utf-8"))
            matching.extend(
                item for item in bundle["items"] if item["source"] == "薬"
            )
        self.assertEqual(len(matching), 2)
        self.assertTrue(all("inconsistent-source" in item["risk"] for item in matching))
        self.assertEqual(
            {tuple(item["same_source_alternatives"]) for item in matching},
            {("Medicine",), ("Potion",)},
        )

        self._accept_clean_screen(task)
        state = rpgmaker_qa.advance(task)
        self.assertEqual(state["deep"]["total"], 0)
        self.assertEqual(state["stage"], "ready-finalize")

    def test_only_strong_override_enters_deep_after_a_clean_screen(self):
        items = json.loads((self.data / "Items.json").read_text(encoding="utf-8"))
        items.append({
            "id": 3,
            "name": "Everyone",
            "description": "Use two potions.",
            "_original": {"name": "みんな", "description": "薬を3個使う。"},
        })
        _write(self.data / "Items.json", items)
        task = self._prepare()
        screen_items = []
        for path in (task / "bundles" / "screen").glob("*.json"):
            screen_items.extend(json.loads(path.read_text(encoding="utf-8"))["items"])
        everyone = next(item for item in screen_items if item["source"] == "みんな")
        self.assertNotIn("negation", everyone["risk"])
        initial = rpgmaker_qa.status(task)
        self.assertEqual(initial["deep"]["projected"], 1)

        self._accept_clean_screen(task)
        state = rpgmaker_qa.advance(task)
        self.assertEqual(state["deep"]["total"], 1)
        assignment = rpgmaker_qa.next_bundle(task, "deep-worker")
        bundle = json.loads(Path(assignment["path"]).read_text(encoding="utf-8"))
        self.assertEqual(bundle["items"][0]["source"], "薬を3個使う。")
        self.assertIn("visible-number-mismatch", bundle["items"][0]["deep_reasons"])

    def test_dialogue_scenes_are_indivisible_and_motifs_require_receipts(self):
        (self.game / ".dazedtl" / "skills" / "quirks.md").write_text(
            "- Preserve the recurring ルナです / ルナデス name joke.\n",
            encoding="utf-8",
        )
        _write(
            self.data / "Map001.json",
            {
                "events": [
                    None,
                    {"pages": [{"list": [
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Luna"]},
                        {"code": 401, "indent": 0, "parameters": ["I'm Luna."], "_original": "ルナです。"},
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Mira"]},
                        {"code": 401, "indent": 0, "parameters": ["Luna, indeed!"], "_original": "ルナデス！"},
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Luna"]},
                        {"code": 401, "indent": 0, "parameters": ["Huh?"], "_original": "え？"},
                        {"code": 0, "indent": 0, "parameters": []},
                    ]}]},
                    {"pages": [{"list": [
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Mira"]},
                        {"code": 401, "indent": 0, "parameters": ["Wait, Luna—indeed!"], "_original": "待って、ルナデス！"},
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Luna"]},
                        {"code": 401, "indent": 0, "parameters": ["Huh?"], "_original": "え？"},
                        {"code": 0, "indent": 0, "parameters": []},
                    ]}]},
                ]
            },
        )
        task = rpgmaker_qa.prepare_task(
            self.game,
            self.data,
            "dialogue",
            self.root / "tasks",
            screen_char_budget=2_000,
            screen_item_limit=1,
        )[0]

        bundles = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted((task / "bundles" / "screen").glob("*.json"))
        ]
        scene_locations = {}
        motif = None
        context_ids = []
        for bundle in bundles:
            for item in bundle["items"]:
                if item["kind"] == "scene":
                    self.assertNotIn(item["scene_id"], scene_locations)
                    scene_locations[item["scene_id"]] = bundle["bundle_id"]
                    self.assertEqual(bundle["scene_count"], 1)
                    self.assertEqual(
                        item["line_count"], len(item["lines"]),
                    )
                    self.assertEqual(
                        item["target_count"],
                        sum("id" in line for line in item["lines"]),
                    )
                    self.assertTrue(all(
                        "source" in line and "translation" in line
                        for line in item["lines"]
                    ))
                    context_ids.extend(
                        line["context_id"] for line in item["lines"]
                        if "context_id" in line
                    )
                elif item["kind"] == "motif-family":
                    motif = (bundle, item)
        self.assertEqual(len(scene_locations), 2)
        self.assertEqual(len(context_ids), 1)
        self.assertIsNotNone(motif)
        motif_bundle, motif_item = motif
        self.assertGreaterEqual(len(motif_item["variants"]), 3)
        suspect_id = None

        def scene_exceptions(bundle):
            nonlocal suspect_id
            exceptions = []
            for item in bundle["items"]:
                for line in item.get("lines") or []:
                    if line.get("source") != "待って、ルナデス！" or "id" not in line:
                        continue
                    suspect_id = line["id"]
                    exceptions.append({
                        "id": suspect_id,
                        "verdict": "suspect",
                        "categories": ["wordplay", "consistency"],
                        "note": "This callback conflicts with the established Luna-name joke.",
                    })
            return exceptions

        assignment = rpgmaker_qa.next_bundle(task, "motif-worker")
        while assignment["id"] != motif_bundle["bundle_id"]:
            clean_bundle = json.loads(Path(assignment["path"]).read_text(encoding="utf-8"))
            result = self.root / f"{assignment['id']}-clean.json"
            _write(result, {
                "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": assignment["id"],
                "bundle_sha256": assignment["sha256"],
                "reviewed_all": True,
                "exceptions": scene_exceptions(clean_bundle),
                "motif_reviews": [],
            })
            rpgmaker_qa.accept_result(task, result)
            assignment = rpgmaker_qa.next_bundle(task, "motif-worker")

        invalid = self.root / "missing-motif-review.json"
        _write(invalid, {
            "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
            "bundle_id": assignment["id"],
            "bundle_sha256": assignment["sha256"],
            "reviewed_all": True,
            "exceptions": [],
            "motif_reviews": [],
        })
        with self.assertRaisesRegex(
            rpgmaker_qa.QAResultError, "every assigned motif"
        ):
            rpgmaker_qa.accept_result(task, invalid)

        valid = self.root / "motif-review.json"
        _write(valid, {
            "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
            "bundle_id": assignment["id"],
            "bundle_sha256": assignment["sha256"],
            "reviewed_all": True,
            "exceptions": [],
            "motif_reviews": [{
                "id": motif_item["id"],
                "disposition": "preserved",
                "note": "All variants preserve the Luna-name joke.",
                "suspect_ids": [],
            }],
        })
        state = rpgmaker_qa.accept_result(task, valid)
        self.assertEqual(state["screen"]["motif_families"], {"accepted": 1, "total": 1})
        while True:
            assignment = rpgmaker_qa.next_bundle(task, "motif-worker")
            if assignment is None:
                break
            bundle = json.loads(Path(assignment["path"]).read_text(encoding="utf-8"))
            result = self.root / f"{assignment['id']}-remaining.json"
            _write(result, {
                "schema": rpgmaker_qa.SCREEN_RESULT_SCHEMA,
                "bundle_id": assignment["id"],
                "bundle_sha256": assignment["sha256"],
                "reviewed_all": True,
                "exceptions": scene_exceptions(bundle),
                "motif_reviews": [],
            })
            rpgmaker_qa.accept_result(task, result)
        self.assertIsNotNone(suspect_id)
        source_status = rpgmaker_qa.status(task)
        self.assertEqual(source_status["screen"]["exceptions"], 1)

        rebuilt, rebuilt_state = rpgmaker_qa.rebuild_deep_from_screen(
            task, self.root / "rebuilt-tasks"
        )
        self.assertNotEqual(rebuilt, task)
        self.assertEqual(
            rebuilt_state["screen"]["accepted"], source_status["screen"]["total"]
        )
        self.assertEqual(rebuilt_state["stage"], "deep")
        deep_items = [
            item
            for path in (rebuilt / "bundles" / "deep").glob("*.json")
            for item in json.loads(path.read_text(encoding="utf-8"))["items"]
        ]
        escalated = next(
            item for item in deep_items
            if any(
                evidence["target_id"] == suspect_id
                for evidence in item.get("screen_evidence") or []
            )
        )
        self.assertEqual(
            escalated["screen_evidence"][0]["note"],
            "This callback conflicts with the established Luna-name joke.",
        )
        self.assertTrue(any(
            line["source"] == "待って、ルナデス！"
            for scene in escalated["screen_scene_contexts"]
            for line in scene["lines"]
        ))
        self.assertEqual(
            escalated["motif_contexts"][0]["disposition"], "preserved"
        )
        with self.assertRaisesRegex(
            rpgmaker_qa.QAResultError, "rebut preserved screen evidence"
        ):
            rpgmaker_qa._validate_deep_result(
                {"items": [escalated]},
                {
                    "schema": rpgmaker_qa.DEEP_RESULT_SCHEMA,
                    "reviews": [{
                        "id": escalated["id"],
                        "disposition": "clean",
                        "severity": None,
                        "category": "",
                        "family_key": "",
                        "evidence": "",
                        "correction": None,
                        "apply_identities": [],
                    }],
                },
            )

        while True:
            assignment = rpgmaker_qa.next_bundle(rebuilt, "deep-worker")
            if assignment is None:
                break
            bundle = json.loads(Path(assignment["path"]).read_text(encoding="utf-8"))
            reviews = []
            for item in bundle["items"]:
                actionable = item["id"] == escalated["id"]
                reviews.append({
                    "id": item["id"],
                    "disposition": "actionable" if actionable else "clean",
                    "severity": "medium" if actionable else None,
                    "category": "wordplay" if actionable else "",
                    "family_key": "motif:ルナです" if actionable else "",
                    "evidence": (
                        "The full scene proves this callback loses the Luna-name joke."
                        if actionable else ""
                    ),
                    "correction": "Luna's the name!" if actionable else None,
                    "apply_identities": [],
                })
            result = self.root / f"{assignment['id']}-motif-deep.json"
            _write(result, {
                "schema": rpgmaker_qa.DEEP_RESULT_SCHEMA,
                "bundle_id": assignment["id"],
                "bundle_sha256": assignment["sha256"],
                "reviews": reviews,
            })
            rpgmaker_qa.accept_result(rebuilt, result)
        rpgmaker_qa.finalize(rebuilt)
        findings = json.loads((rebuilt / "findings.json").read_text(encoding="utf-8"))
        final_motif = findings["motif_families"][0]
        self.assertEqual(final_motif["disposition"], "suspect")
        self.assertEqual(final_motif["screen_review"]["disposition"], "preserved")
        self.assertEqual(
            final_motif["deep_reconciliation"]["actionable_variant_ids"],
            [escalated["id"]],
        )
        self.assertEqual(len(final_motif["deep_reconciliation"]["finding_ids"]), 1)

        refinalized, state = rpgmaker_qa.rebuild_findings_from_results(
            rebuilt, self.root / "refinalized-tasks"
        )
        self.assertEqual(state["stage"], "complete")
        self.assertEqual(
            json.loads((refinalized / "findings.json").read_text(encoding="utf-8"))[
                "motif_families"
            ],
            findings["motif_families"],
        )

    def test_status_rejects_a_task_with_a_stale_engine_fingerprint(self):
        task = self._prepare()
        task_document = json.loads((task / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(
            rpgmaker_qa.status(task)["engine_fingerprint"],
            task_document["engine_fingerprint"],
        )
        task_document["engine_fingerprint"] = "stale-rules"
        _write(task / "task.json", task_document)
        with self.assertRaisesRegex(ValueError, "QA rules changed"):
            rpgmaker_qa.status(task)

    def test_deep_finding_applies_only_after_map_and_preserves_original(self):
        items_path = self.data / "Items.json"
        items = json.loads(items_path.read_text(encoding="utf-8"))
        items.append({
            "id": 3,
            "name": "Potion Plus",
            "description": "Heals health.",
            "_original": {"name": "上薬", "description": "体力を回復する。"},
        })
        _write(items_path, items)
        items_path.write_bytes(b"\xef\xbb\xbf" + items_path.read_bytes())
        task = self._prepare()
        self._accept_clean_screen(task, suspect_source="体力を回復する。")
        screened = rpgmaker_qa.status(task)
        self.assertEqual(screened["screen"]["exceptions"], 2)
        self.assertEqual(screened["deep"]["projected"], 2)
        state = rpgmaker_qa.advance(task)
        self.assertGreater(state["deep"]["total"], 0)

        actionable_source = "体力を回復する。"
        while True:
            assignment = rpgmaker_qa.next_bundle(task, "deep-worker")
            if assignment is None:
                break
            bundle = json.loads(Path(assignment["path"]).read_text(encoding="utf-8"))
            reviews = []
            for item in bundle["items"]:
                actionable = item["source"] == actionable_source
                reviews.append({
                    "id": item["id"],
                    "disposition": "actionable" if actionable else "clean",
                    "severity": "high" if actionable else None,
                    "category": "meaning" if actionable else "",
                    "family_key": "source:体力を回復する。" if actionable else "",
                    "evidence": "The source says it restores MP." if actionable else "",
                    "correction": "Restores MP." if actionable else None,
                    "apply_identities": [],
                })
            result = self.root / f"{assignment['id']}-deep.json"
            _write(result, {
                "schema": rpgmaker_qa.DEEP_RESULT_SCHEMA,
                "bundle_id": assignment["id"],
                "bundle_sha256": assignment["sha256"],
                "reviews": reviews,
            })
            rpgmaker_qa.accept_result(task, result)

        complete = rpgmaker_qa.finalize(task)
        self.assertEqual(complete["stage"], "complete")
        findings = json.loads((task / "findings.json").read_text(encoding="utf-8"))
        self.assertEqual(len(findings["findings"]), 2)
        self.assertEqual(len(findings["finding_families"]), 1)
        self.assertEqual(
            set(findings["finding_families"][0]["finding_ids"]),
            {item["id"] for item in findings["findings"]},
        )
        approved = next(
            item["id"] for item in findings["findings"]
            if item["current"] == "Restores health."
        )
        rpgmaker_qa.create_correction_map(task, [approved])
        preview = rpgmaker_qa.dry_run_correction_map(task)
        self.assertTrue(preview["valid"])
        self.assertEqual(preview["operation_count"], 1)
        regression = rpgmaker_qa.apply_correction_map(task)
        self.assertTrue(regression["valid"])

        updated_raw = (self.data / "Items.json").read_bytes()
        self.assertTrue(updated_raw.startswith(b"\xef\xbb\xbf"))
        updated_text = updated_raw.decode("utf-8-sig")
        updated = json.loads(updated_text)
        self.assertEqual(updated[1]["description"], "Restores MP.")
        self.assertEqual(updated[1]["_original"]["description"], actionable_source)
        self.assertEqual(updated[3]["description"], "Heals health.")
        self.assertIn('\n    {\n        "id": 1,', updated_text)


if __name__ == "__main__":
    unittest.main()
