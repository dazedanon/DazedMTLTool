from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from unittest import mock

from util import batch_providers, evaluation


ROOT = Path(__file__).resolve().parents[1]


class EvaluationSourceFolderTests(unittest.TestCase):
    def test_rpg_maker_mz_game_root_resolves_data_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            data = game / "data"
            data.mkdir()
            (game / "game.rmmzproject").write_text("RPGMZ 1.0.0", encoding="utf-8")
            (data / "Items.json").write_text("[]", encoding="utf-8")

            self.assertEqual(evaluation.resolve_rpgmaker_data_dir(game), data.resolve())

    def test_rpg_maker_mv_game_root_resolves_www_data_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            data = game / "www" / "data"
            data.mkdir(parents=True)
            (game / "Game.rpgproject").write_text("RPGMV 1.6.2", encoding="utf-8")
            (data / "Map001.json").write_text("{}", encoding="utf-8")

            self.assertEqual(evaluation.resolve_rpgmaker_data_dir(game), data.resolve())

    def test_direct_json_folder_remains_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            (data / "CommonEvents.json").write_text("[]", encoding="utf-8")

            self.assertEqual(evaluation.resolve_rpgmaker_data_dir(data), data.resolve())

    def test_unrelated_folder_gets_actionable_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "data/ or www/data/"):
                evaluation.resolve_rpgmaker_data_dir(temporary)

    def test_manifest_accepts_game_root_and_records_resolved_data_folder(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            data = game / "data"
            data.mkdir()
            records = [None] + [
                {"id": index, "name": f"道具{index}", "description": "説明です。"}
                for index in range(1, 41)
            ]
            (data / "Items.json").write_text(
                json.dumps(records, ensure_ascii=False), encoding="utf-8"
            )

            manifest = evaluation.build_manifest(
                game,
                target_segments=60,
                stability_segments=20,
                repetitions=1,
                system_prompt="Translate Japanese to English.",
                glossary="",
            )

            self.assertEqual(manifest["source_dir"], str(data.resolve()))
            self.assertEqual(manifest["target_segments"], 60)


class EvaluationManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = evaluation.build_manifest(ROOT / "files")

    def test_default_corpus_is_stratified_and_repeated_deterministically(self):
        manifest = self.manifest
        self.assertEqual(len(manifest["segments"]), 360)
        self.assertEqual(
            Counter(segment["stratum"] for segment in manifest["segments"]),
            Counter({
                "event_text": 234,
                "database": 72,
                "code_heavy": 54,
            }),
        )
        self.assertGreater(len(manifest["logical_requests"]), 1)
        self.assertGreater(len(manifest["executions"]), len(manifest["logical_requests"]))
        repetitions = Counter(item["repetition"] for item in manifest["executions"])
        self.assertEqual(repetitions[1], len(manifest["logical_requests"]))
        self.assertEqual(repetitions[2], repetitions[3])
        summary = manifest["corpus_summary"]
        self.assertGreater(summary["eligible_segments"], summary["selected_segments"])
        self.assertGreater(summary["selected_files"], 10)
        rebuilt = evaluation.build_corpus(ROOT / "files")
        self.assertEqual(
            [item["id"] for item in rebuilt],
            [item["id"] for item in manifest["segments"]],
        )

    def test_an_unrelated_small_game_folder_is_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [None] + [
                {"id": index, "name": f"道具{index}", "description": "説明です。"}
                for index in range(1, 41)
            ]
            (root / "Items.json").write_text(
                json.dumps(records, ensure_ascii=False), encoding="utf-8"
            )
            corpus = evaluation.build_corpus(root, target_segments=60)
        self.assertEqual(len(corpus), 60)
        self.assertEqual({item["source_location"]["file"] for item in corpus}, {"Items.json"})

    def test_every_request_has_locked_context_and_bounded_source_history(self):
        audit = evaluation.context_audit(self.manifest)
        self.assertTrue(audit["all_have_system"])
        self.assertTrue(audit["all_have_source"])
        self.assertTrue(audit["history_limit_ok"])
        for request in self.manifest["logical_requests"]:
            logical = {
                "system": request["system"],
                "glossary": request["glossary"],
                "history": request["history"],
                "user": request["user"],
                "schema_line_count": request["schema_line_count"],
            }
            self.assertEqual(request["logical_hash"], evaluation._sha256(logical))

    def test_provider_adapters_change_settings_not_logical_context(self):
        request = self.manifest["logical_requests"][0]
        candidates = [dict(item) for item in evaluation.DEFAULT_CANDIDATES]
        params = {
            item["provider"]: evaluation._provider_params(item, request)
            for item in candidates
        }
        self.assertEqual(params["openai"]["reasoning_effort"], "none")
        self.assertEqual(
            params["openai"]["max_completion_tokens"],
            evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST,
        )
        self.assertNotIn("temperature", params["gemini"])
        self.assertNotIn("extra_body", params["gemini"])
        self.assertEqual(
            params["gemini"]["max_tokens"],
            evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST,
        )
        self.assertEqual(
            params["gemini"]["reasoning_effort"],
            "minimal",
        )
        gemini_batch_body = batch_providers._openai_batch_body(
            "gemini", params["gemini"]
        )
        self.assertNotIn("google", gemini_batch_body)
        self.assertNotIn("extra_body", gemini_batch_body)
        self.assertEqual(gemini_batch_body["reasoning_effort"], "minimal")
        self.assertEqual(params["anthropic"]["thinking"], {"type": "disabled"})
        self.assertEqual(
            params["anthropic"]["max_tokens"],
            evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST,
        )
        self.assertEqual(
            params["anthropic"]["output_config"]["format"]["schema"]
            ["required"],
            [f"Line{i}" for i in range(1, request["schema_line_count"] + 1)],
        )

    def test_locked_batch_pricing_handles_sonnet_intro_expiry(self):
        self.assertEqual(
            evaluation.pricing_for("gpt-5.6-terra")["output"], 7.50
        )
        self.assertEqual(
            evaluation.pricing_for("gemini-3.6-flash")["input"], 0.75
        )
        self.assertEqual(
            evaluation.pricing_for(
                "claude-sonnet-5", on_date=date(2026, 8, 31)
            )["input"],
            1.00,
        )
        self.assertEqual(
            evaluation.pricing_for(
                "claude-sonnet-5", on_date=date(2026, 9, 1)
            )["input"],
            1.50,
        )

    def test_default_estimates_stay_below_safe_budget(self):
        for candidate in evaluation.DEFAULT_CANDIDATES:
            estimate = evaluation.estimate_candidate(self.manifest, candidate)
            self.assertGreater(estimate["cost_usd"], 0)
            self.assertLess(estimate["cost_usd"], 8.0)
            self.assertLess(estimate["maximum_cost_usd"], 10.0)

    def test_live_estimate_uses_undiscounted_rates(self):
        batch_candidate = dict(evaluation.DEFAULT_CANDIDATES[0])
        live_candidate = {**batch_candidate, "execution": "live"}
        batch_estimate = evaluation.estimate_candidate(
            self.manifest, batch_candidate
        )
        live_estimate = evaluation.estimate_candidate(self.manifest, live_candidate)
        self.assertAlmostEqual(
            live_estimate["cost_usd"], batch_estimate["cost_usd"] * 2
        )
        self.assertAlmostEqual(
            live_estimate["maximum_cost_usd"],
            batch_estimate["maximum_cost_usd"] * 2,
        )

    def test_live_evaluation_finishes_without_creating_batch_job(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            candidate = {
                "id": "candidate-1",
                "provider": "openai",
                "endpoint": "http://127.0.0.1:8000/v1",
                "model": "local-model",
                "label": "local-model",
                "key_name": "Local",
                "execution": "live",
                "status": "prepared",
                "estimate": {"cost_usd": 0.0},
            }
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "live-test",
                "status": "prepared",
                "candidates": [candidate],
            })

            def response(_provider, params, **_kwargs):
                required = params["response_format"]["json_schema"]["schema"]["required"]
                return {
                    "text": json.dumps({key: "English text" for key in required}),
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                    "thinking_tokens": 0,
                }

            with (
                mock.patch.object(evaluation, "_clients", return_value=(object(), None)),
                mock.patch.object(
                    evaluation.batch_api,
                    "execute_live_request",
                    side_effect=response,
                ) as execute,
                mock.patch.object(evaluation.batch_api, "submit_batch") as submit,
            ):
                state = evaluation.submit_run(
                    run_dir, {"candidate-1": "local-key"}
                )

            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["candidates"][0]["status"], "completed")
            self.assertNotIn("batch_id", state["candidates"][0])
            self.assertEqual(execute.call_count, len(self.manifest["executions"]))
            submit.assert_not_called()

    def test_missing_provider_requests_reduce_validity(self):
        processed, summary = evaluation._process_results(self.manifest, {}, [])
        self.assertFalse(processed)
        self.assertEqual(summary["received_requests"], 0)
        self.assertEqual(summary["missing_requests"], len(self.manifest["executions"]))
        self.assertEqual(summary["valid_segments"], 0)
        self.assertEqual(summary["validation_failures"], summary["total_segments"])
        self.assertEqual(summary["valid_rate"], 0.0)

    def test_terminal_batch_with_no_successes_marks_candidate_and_run_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            executions = self.manifest["executions"]
            candidate = {
                "id": "candidate-1",
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "label": "Broken model",
                "key_name": "OpenAI",
                "endpoint": "https://api.openai.com/v1",
                "status": "submitted",
                "batch_id": "batch-broken",
                "custom_ids": {
                    f"eval-{index:06d}": item["id"]
                    for index, item in enumerate(executions, start=1)
                },
            }
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "failed-batch-test",
                "status": "submitted",
                "candidates": [candidate],
            })
            errors = [
                (custom_id, "Request contains an invalid argument.")
                for custom_id in candidate["custom_ids"]
            ]
            usage = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
                "thinking_tokens": 0,
            }
            with (
                mock.patch.object(evaluation, "_clients", return_value=(object(), None)),
                mock.patch.object(
                    evaluation.batch_api,
                    "retrieve_batch",
                    return_value={
                        "api_status": "completed",
                        "ended": True,
                        "counts": {
                            "processing": 0,
                            "succeeded": 0,
                            "errored": len(executions),
                            "canceled": 0,
                            "expired": 0,
                        },
                    },
                ),
                mock.patch.object(
                    evaluation.batch_api,
                    "download_results",
                    return_value=({}, errors, usage),
                ),
                mock.patch("util.batch_history.upsert_history_entry") as upsert,
            ):
                state = evaluation.refresh_run(
                    run_dir, {"candidate-1": "hidden-key"}
                )

            failed = state["candidates"][0]
            self.assertEqual(state["status"], "failed")
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["summary"]["received_requests"], 0)
            self.assertEqual(
                failed["summary"]["provider_errors"], errors
            )
            self.assertIn("0/", failed["failure_reason"])
            self.assertEqual(upsert.call_args_list[-1].kwargs["status"], "failed")

    def test_load_run_normalizes_legacy_all_error_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", {
                "segments": [],
            })
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "legacy-failed-test",
                "status": "completed",
                "candidates": [{
                    "id": "candidate-1",
                    "label": "Broken model",
                    "status": "completed",
                    "summary": {
                        "expected_requests": 3,
                        "received_requests": 0,
                        "provider_errors": [
                            ["eval-1", "invalid"],
                            ["eval-2", "invalid"],
                            ["eval-3", "invalid"],
                        ],
                    },
                }],
            })

            state, _manifest = evaluation.load_run(run_dir)

            self.assertEqual(state["status"], "failed")
            self.assertEqual(state["candidates"][0]["status"], "failed")
            self.assertIn("0/3", state["candidates"][0]["failure_reason"])

    def test_submitted_evaluation_jobs_are_registered_in_shared_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            candidates = [
                {
                    "id": f"candidate-{index}",
                    "provider": "openai",
                    "model": model,
                    "label": model,
                    "key_name": f"Key {index}",
                    "endpoint": "",
                    "status": "prepared",
                    "estimate": {"cost_usd": 1.0},
                }
                for index, model in enumerate(("gpt-5.6-terra", "gpt-4.1"), start=1)
            ]
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "eval-history-test",
                "status": "prepared",
                "candidates": candidates,
            })
            with (
                mock.patch.object(evaluation, "_clients", return_value=(object(), None)),
                mock.patch.object(
                    evaluation.batch_api,
                    "submit_batch",
                    side_effect=(
                        {"id": "batch-eval-1", "input_file_id": "file-1"},
                        {"id": "batch-eval-2", "input_file_id": "file-2"},
                    ),
                ),
                mock.patch("util.batch_history.upsert_history_entry") as upsert,
            ):
                state = evaluation.submit_run(
                    run_dir, {"candidate-1": "key-1", "candidate-2": "key-2"}
                )
        self.assertEqual(state["status"], "submitted")
        self.assertEqual(upsert.call_count, 2)
        self.assertTrue(all(
            call.kwargs["workflow"] == "evaluation" for call in upsert.call_args_list
        ))


class EvaluationHistoryTests(unittest.TestCase):
    def _make_run(self, project: Path, run_id: str = "run-one") -> Path:
        run_dir = project / "log" / "evaluations" / run_id
        result_file = Path("results/candidate-1.json")
        evaluation._atomic_write_json(run_dir / "manifest.json", {
            "source_dir": str(project / "game"),
            "corpus_summary": {"selected_segments": 120},
            "segments": [],
            "executions": [],
            "logical_requests": [],
            "stability_request_ids": [],
            "repetitions": 3,
        })
        evaluation._atomic_write_json(run_dir / result_file, {
            "candidate_id": "candidate-1",
            "summary": {"valid_rate": 1.0},
            "executions": {},
        })
        evaluation._atomic_write_json(run_dir / "state.json", {
            "version": evaluation.EVALUATION_VERSION,
            "run_id": run_id,
            "created_at": "2026-08-01T12:00:00+00:00",
            "updated_at": "2026-08-01T12:30:00+00:00",
            "status": "completed",
            "api_key": "must-never-be-exported",
            "corpus_summary": {"selected_segments": 120},
            "candidates": [{
                "id": "candidate-1",
                "model": "local-model",
                "execution": "live",
                "key_name": "Local key name",
                "result_file": str(result_file),
                "status": "completed",
            }],
            "human_review": {
                "reviewed": 25,
                "ties": 2,
                "wins": {"candidate-1": 23},
            },
        })
        evaluation._atomic_write_json(
            run_dir / "blind_key.json", {"segment-1": {"A": "candidate-1"}}
        )
        return run_dir

    def test_history_lists_every_run_instead_of_only_latest(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            self._make_run(project, "older-run")
            newer = self._make_run(project, "newer-run")
            state = json.loads((newer / "state.json").read_text(encoding="utf-8"))
            state["created_at"] = "2026-08-02T12:00:00+00:00"
            evaluation._atomic_write_json(newer / "state.json", state)

            runs = evaluation.list_runs(project)

        self.assertEqual([run["run_id"] for run in runs], ["newer-run", "older-run"])
        self.assertEqual(runs[0]["models"], ["local-model"])
        self.assertEqual(runs[0]["reviewed"], 25)

    def test_evaluation_archive_round_trip_never_overwrites_existing_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            run_dir = self._make_run(project)
            archive_path = Path(temporary) / "portable.dazedeval"
            exported = evaluation.export_run_archive(run_dir, archive_path)

            with zipfile.ZipFile(exported) as archive:
                self.assertIn("manifest.json", archive.namelist())
                self.assertIn("state.json", archive.namelist())
                metadata = json.loads(archive.read("evaluation_export.json"))
                self.assertFalse(metadata["contains_api_secrets"])
                self.assertNotIn(
                    b"must-never-be-exported", archive.read("state.json")
                )

            imported = evaluation.import_run_archive(project, exported)
            imported_state, _manifest = evaluation.load_run(imported)

            self.assertTrue(run_dir.is_dir())
            self.assertNotEqual(imported, run_dir)
            self.assertEqual(imported_state["imported_from_run_id"], "run-one")
            self.assertEqual(imported_state["human_review"]["reviewed"], 25)
            self.assertTrue((imported / "results/candidate-1.json").is_file())
            self.assertEqual(len(evaluation.list_runs(project)), 2)

    def test_import_rejects_archive_path_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "unsafe.dazedeval"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "evaluation_export.json",
                    json.dumps({"archive_version": evaluation.EVALUATION_ARCHIVE_VERSION}),
                )
                archive.writestr("manifest.json", "{}")
                archive.writestr("state.json", '{"run_id":"unsafe"}')
                archive.writestr("../outside.json", "{}")

            with self.assertRaisesRegex(ValueError, "unsafe path"):
                evaluation.import_run_archive(root / "project", archive_path)
            self.assertFalse((root / "outside.json").exists())

    def test_imported_active_job_requires_explicit_resume(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            run_dir = self._make_run(project, "active-run")
            state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
            state["status"] = "submitted"
            state["candidates"][0]["status"] = "submitted"
            state["candidates"][0].pop("result_file", None)
            evaluation._atomic_write_json(run_dir / "state.json", state)
            archive = evaluation.export_run_archive(
                run_dir, Path(temporary) / "active.dazedeval"
            )

            imported = evaluation.import_run_archive(project, archive)
            paused, _manifest = evaluation.load_run(imported)
            resumed = evaluation.resume_imported_run(imported)

            self.assertEqual(paused["status"], "imported_paused")
            self.assertEqual(resumed["status"], "submitted")


class BlindReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.run_dir = Path(self.temporary.name)
        self.segment = {
            "id": "segment-1",
            "scene_id": "scene-1",
            "stratum": "dialogue",
            "source": "猫だ。",
        }
        manifest = {
            "segments": [self.segment],
            "executions": [{
                "id": "rep-1:logical-0001",
                "logical_request_id": "logical-0001",
                "repetition": 1,
            }],
            "logical_requests": [{
                "id": "logical-0001", "segment_ids": ["segment-1"]
            }],
        }
        candidates = []
        for index, model in enumerate(("gpt", "gemini", "sonnet", "other"), start=1):
            candidate_id = f"candidate-{index}"
            result_file = Path("results") / f"{candidate_id}.json"
            payload = {
                "executions": {
                    "rep-1:logical-0001": {
                        "repetition": 1,
                        "lines": [{
                            "segment_id": "segment-1",
                            "translation": f"translation-{model}",
                        }],
                    }
                }
            }
            evaluation._atomic_write_json(self.run_dir / result_file, payload)
            candidates.append({
                "id": candidate_id,
                "model": model,
                "status": "completed",
                "result_file": str(result_file),
            })
        evaluation._atomic_write_json(self.run_dir / "manifest.json", manifest)
        evaluation._atomic_write_json(self.run_dir / "state.json", {
            "run_id": "blind-test",
            "status": "completed",
            "candidates": candidates,
        })

    def tearDown(self):
        self.temporary.cleanup()

    def test_export_randomizes_labels_and_import_resolves_hidden_winner(self):
        review_path = evaluation.export_blind_review(
            self.run_dir, self.run_dir / "external" / "review.csv"
        )
        self.assertTrue((self.run_dir / "blind_review.csv").is_file())
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {rows[0][label] for label in ("A", "B", "C", "D")},
            {
                "translation-gpt", "translation-gemini",
                "translation-sonnet", "translation-other",
            },
        )
        rows[0]["winner"] = "B"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        hidden = json.loads((self.run_dir / "blind_key.json").read_text(encoding="utf-8"))
        expected = hidden["segment-1"]["B"]
        review = evaluation.import_blind_review(self.run_dir, review_path)
        self.assertEqual(review["wins"][expected], 1)
        self.assertEqual(review["reviewed"], 1)
        self.assertIn(
            ",B,", (self.run_dir / "blind_review.csv").read_text(encoding="utf-8-sig")
        )

    def test_coverage_reports_rows_excluded_by_candidate_validation(self):
        manifest_path = self.run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["segments"].append({
            "id": "segment-2",
            "scene_id": "scene-2",
            "stratum": "dialogue",
            "source": "犬だ。",
        })
        evaluation._atomic_write_json(manifest_path, manifest)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        for index, candidate in enumerate(state["candidates"]):
            result_path = self.run_dir / candidate["result_file"]
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["executions"]["rep-1:logical-0001"]["lines"].append({
                "segment_id": "segment-2",
                "translation": f"translation-dog-{index}",
                "valid": index != 0,
            })
            evaluation._atomic_write_json(result_path, result)

        coverage = evaluation.blind_review_coverage(self.run_dir)
        self.assertEqual(coverage["total_segments"], 2)
        self.assertEqual(coverage["eligible_segments"], 1)
        self.assertEqual(coverage["excluded_segments"], 1)

    def test_export_rejects_all_error_candidate_without_overwriting_csv(self):
        state_path = self.run_dir / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        candidate = state["candidates"][1]
        summary = {
            "expected_requests": 1,
            "received_requests": 0,
            "provider_errors": [[
                "eval-000001", "Request contains an invalid argument."
            ]],
        }
        candidate["summary"] = summary
        evaluation._atomic_write_json(state_path, state)
        result_path = self.run_dir / candidate["result_file"]
        evaluation._atomic_write_json(result_path, {
            "summary": summary,
            "executions": {},
        })
        review_path = self.run_dir / "blind_review.csv"
        review_path.write_text("existing review\n", encoding="utf-8")

        with self.assertRaisesRegex(
            ValueError, "0/1 requests received.*invalid argument"
        ):
            evaluation.export_blind_review(self.run_dir, review_path)

        self.assertEqual(
            review_path.read_text(encoding="utf-8"), "existing review\n"
        )
        self.assertFalse((self.run_dir / "blind_key.json").exists())


if __name__ == "__main__":
    unittest.main()
