"""Behavior tests for the local AI-helper QA task engine."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                        {"code": 401, "indent": 0, "parameters": ["She left."], "_original": "彼女は去った。"},
                        {"code": 401, "indent": 0, "parameters": ["I understand."], "_original": "分かった。"},
                        {"code": 0, "indent": 0, "parameters": []},
                    ]}]},
                    {"pages": [{"list": [
                        {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "Mira"]},
                        {"code": 401, "indent": 0, "parameters": ["Wait, Luna—indeed!"], "_original": "待って、ルナデス！"},
                        {"code": 401, "indent": 0, "parameters": ["She left."], "_original": "彼女は去った。"},
                        {"code": 401, "indent": 0, "parameters": ["I understand."], "_original": "分かった。"},
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
        expanded_targets = {"彼女は去った。": [], "分かった。": []}
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
                    for line in item["lines"]:
                        if line.get("source") in expanded_targets and "id" in line:
                            expanded_targets[line["source"]].append(line)
                elif item["kind"] == "motif-family":
                    motif = (bundle, item)
        self.assertEqual(len(scene_locations), 2)
        self.assertEqual(len(context_ids), 1)
        self.assertEqual(len(expanded_targets["彼女は去った。"]), 2)
        self.assertTrue(all(
            "repeated-third-person-context" in line["context_expansion"]
            for line in expanded_targets["彼女は去った。"]
        ))
        self.assertEqual(len(expanded_targets["分かった。"]), 2)
        self.assertEqual(
            {line["speaker"] for line in expanded_targets["分かった。"]},
            {"Luna", "Mira"},
        )
        self.assertTrue(all(
            "cross-speaker-pronoun-context" in line["context_expansion"]
            for line in expanded_targets["分かった。"]
        ))
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
        motif_variant_ids = {
            variant["id"] for variant in motif_item["variants"]
        }
        deep_by_id = {item["id"]: item for item in deep_items}
        self.assertLessEqual(motif_variant_ids, set(deep_by_id))
        self.assertTrue(all(
            "motif-scene-contradiction" in deep_by_id[variant_id]["deep_reasons"]
            for variant_id in motif_variant_ids
        ))
        self.assertTrue(all(
            "nearby_commands" not in variant
            for variant_id in motif_variant_ids
            for context in deep_by_id[variant_id]["motif_contexts"]
            for variant in context["variants"]
        ))
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

        subjective_review = {
            "id": escalated["id"],
            "disposition": "actionable",
            "severity": "medium",
            "family_key": "motif:ルナです",
            "evidence": "The full scene proves this callback loses the name joke.",
            "correction": "Luna's the name!",
            "apply_identities": [],
        }
        editorial_basis = {
            "defect": "Readers cannot recognize the established callback.",
            "source_support": "The source and full scene repeat the same joke mechanism.",
            "not_preference": True,
        }
        for category in rpgmaker_qa.EDITORIAL_JUDGMENT_CATEGORIES:
            with self.subTest(category=category):
                with self.assertRaisesRegex(
                    rpgmaker_qa.QAResultError, "needs editorial_basis"
                ):
                    rpgmaker_qa._validate_deep_result(
                        {"items": [escalated]},
                        {
                            "schema": rpgmaker_qa.DEEP_RESULT_SCHEMA,
                            "reviews": [{**subjective_review, "category": category}],
                        },
                    )
        with self.assertRaisesRegex(rpgmaker_qa.QAResultError, "only a preference"):
            rpgmaker_qa._validate_deep_result(
                {"items": [escalated]},
                {
                    "schema": rpgmaker_qa.DEEP_RESULT_SCHEMA,
                    "reviews": [{
                        **subjective_review,
                        "category": "wordplay",
                        "editorial_basis": {
                            **editorial_basis,
                            "not_preference": False,
                        },
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
                    **({
                        "editorial_basis": editorial_basis,
                    } if actionable else {}),
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
        motif_finding = next(
            item for item in findings["findings"]
            if item["cluster_id"] == escalated["id"]
        )
        self.assertTrue(motif_finding["editorial_basis"]["not_preference"])

        real_build_manifest = rpgmaker_qa.build_manifest

        def build_with_new_detector_evidence(*args, **kwargs):
            manifest = real_build_manifest(*args, **kwargs)
            manifest["records"][0]["mechanical"]["flags"].append(
                "new-detector-evidence"
            )
            unhashed = dict(manifest)
            unhashed.pop("content_sha256", None)
            manifest["content_sha256"] = rpgmaker_qa._sha256(
                rpgmaker_qa._canonical_bytes(unhashed)
            )
            return manifest

        with (
            patch.object(
                rpgmaker_qa,
                "build_manifest",
                side_effect=build_with_new_detector_evidence,
            ),
            patch.object(
                rpgmaker_qa,
                "verify_manifest",
                return_value={"valid": True, "errors": []},
            ),
        ):
            refinalized, state = rpgmaker_qa.rebuild_findings_from_results(
                rebuilt, self.root / "refinalized-tasks"
            )
        self.assertEqual(state["stage"], "complete")
        refinalized_task = json.loads(
            (refinalized / "task.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            refinalized_task["rebuilt_from"]["kind"],
            "mechanical-evidence-only-final-rebuild-v1",
        )
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
        verbose_current = (
            "This overly verbose description says that the item restores health completely."
        )
        verbose_correction = (
            "This clearer description says that the item restores magical power."
        )
        items[1]["description"] = verbose_current
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
                    "correction": verbose_correction if actionable else None,
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
            if item["current"] == verbose_current
        )
        baseline = json.loads((task / "inventory.json").read_text(encoding="utf-8"))
        baseline_record = next(
            item for item in baseline["records"] if item["live"] == verbose_current
        )
        self.assertIn(
            "suspicious-length-ratio", baseline_record["mechanical"]["flags"]
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
        self.assertEqual(updated[1]["description"], verbose_correction)
        self.assertEqual(updated[1]["_original"]["description"], actionable_source)
        self.assertEqual(updated[3]["description"], "Heals health.")
        self.assertIn('\n    {\n        "id": 1,', updated_text)

        editorial_replacement = "Restores magical power."
        editorial_review = self.root / "final-editorial.json"
        _write(editorial_review, {
            "schema": rpgmaker_qa.EDITORIAL_REVIEW_SCHEMA,
            "task": str(task),
            "approved_findings": 1,
            "accepted_as_written": 0,
            "revisions_required": 1,
            "rejected": 0,
            "reviews": [{
                "finding_id": approved,
                "verdict": "revise",
                "replacement": editorial_replacement,
                "reason": "Final publication edit.",
            }],
        })
        rpgmaker_qa.create_editorial_correction_map(task, editorial_review)
        rpgmaker_qa.create_correction_map(task, [approved])
        with self.assertRaisesRegex(ValueError, "does not match approved corrections"):
            rpgmaker_qa.dry_run_editorial_correction_map(task)
        with patch.object(rpgmaker_qa, "QA_POLICY_VERSION", "new-policy"):
            with self.assertRaisesRegex(ValueError, "QA rules changed"):
                rpgmaker_qa.dry_run_correction_map(task)
            editorial_map = rpgmaker_qa.create_editorial_correction_map(
                task, editorial_review
            )
            self.assertEqual(len(editorial_map["operations"]), 1)
            editorial_preview = rpgmaker_qa.dry_run_editorial_correction_map(task)
            self.assertEqual(editorial_preview["operation_count"], 1)
            editorial_regression = rpgmaker_qa.apply_editorial_correction_map(task)
        self.assertTrue(editorial_regression["valid"])
        self.assertTrue(rpgmaker_qa.regression_check(task)["valid"])
        final_items = json.loads(items_path.read_text(encoding="utf-8-sig"))
        self.assertEqual(final_items[1]["description"], editorial_replacement)

    def test_editorial_regression_reports_only_length_ratio_as_warning(self):
        identity = "Items.json#/1/_original/description@test"
        before = {
            "content_sha256": "before",
            "records": [{
                "identity": identity,
                "source_sha256": "source",
                "live": "Before",
                "mechanical": {"flags": []},
            }],
        }
        after = {
            "content_sha256": "after",
            "records": [{
                "identity": identity,
                "source_sha256": "source",
                "live": "After",
                "mechanical": {"flags": ["suspicious-length-ratio"]},
            }],
        }
        corrections = {"operations": [{
            "identity": identity,
            "replacement": "After",
        }]}
        with (
            patch.object(rpgmaker_qa, "build_manifest", return_value=after),
            patch.object(
                rpgmaker_qa,
                "verify_manifest",
                return_value={"valid": True, "errors": []},
            ),
        ):
            normal = rpgmaker_qa._regression_check_loaded(
                {"data_root": str(self.data), "focus": "database"},
                before,
                corrections,
            )
            editorial = rpgmaker_qa._regression_check_loaded(
                {"data_root": str(self.data), "focus": "database"},
                before,
                corrections,
                nonblocking_introduced_flags=frozenset({
                    "suspicious-length-ratio"
                }),
            )
        self.assertFalse(normal["valid"])
        self.assertEqual(len(normal["errors"]), 1)
        self.assertTrue(editorial["valid"])
        self.assertEqual(editorial["errors"], [])
        self.assertEqual(len(editorial["warnings"]), 1)


if __name__ == "__main__":
    unittest.main()
