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

    def test_direct_data_folder_resolves_its_own_game_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary) / "game"
            data = game / "www" / "data"
            data.mkdir(parents=True)
            (data / "Map001.json").write_text("{}", encoding="utf-8")

            self.assertEqual(
                evaluation.resolve_evaluation_game_root(data), game.resolve()
            )

    def test_extracted_files_use_configured_workflow_game_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / "files"
            extracted.mkdir()
            (extracted / "Items.json").write_text("[]", encoding="utf-8")
            game = root / "game"
            data = game / "data"
            data.mkdir(parents=True)
            (data / "Items.json").write_text("[]", encoding="utf-8")

            self.assertEqual(
                evaluation.resolve_evaluation_game_root(
                    extracted, fallback_game_root=game
                ),
                game.resolve(),
            )

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
            self.assertEqual(manifest["game_root"], str(game.resolve()))
            self.assertEqual(manifest["target_segments"], 60)

    def test_manifest_uses_selected_games_normal_prompt_and_glossary_context(self):
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
            (game / "glossary.txt").write_text(
                "# Terms\n道具 (Relic)\n", encoding="utf-8"
            )
            skills = game / "skills"
            skills.mkdir()
            (skills / "game.md").write_text(
                "Use the game's established item voice.", encoding="utf-8"
            )

            manifest = evaluation.build_manifest(
                game,
                target_segments=60,
                stability_segments=20,
                repetitions=1,
            )

            self.assertEqual(manifest["game_root"], str(game.resolve()))
            self.assertTrue(all(
                "Use the game's established item voice." in request["system"]
                for request in manifest["logical_requests"]
            ))
            self.assertTrue(any(
                "道具 (Relic)" in request["glossary"]
                for request in manifest["logical_requests"]
            ))

    def test_custom_sample_size_repeat_count_and_runs_are_recorded(self):
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
                stability_segments=0,
                stability_samples=5,
                repetitions=4,
                batch_size=4,
                system_prompt="Translate Japanese to English.",
                glossary="",
            )

        self.assertEqual(manifest["sample_size"], 4)
        self.assertEqual(manifest["requested_stability_samples"], 5)
        self.assertEqual(manifest["stability_samples"], 5)
        self.assertEqual(manifest["repetitions"], 4)
        self.assertTrue(all(
            1 <= len(request["segment_ids"]) <= 4
            for request in manifest["logical_requests"]
        ))
        self.assertEqual(
            len(manifest["executions"]),
            len(manifest["logical_requests"]) + 5 * 3,
        )

    def test_repeated_samples_require_multiple_runs(self):
        with self.assertRaisesRegex(ValueError, "at least 2 runs"):
            evaluation.build_manifest(
                ROOT / "files",
                stability_samples=1,
                repetitions=1,
            )


class EvaluationContentSelectionTests(unittest.TestCase):
    @staticmethod
    def _segment(filename: str, index: int, category: str, source: str | None = None):
        return {
            "id": f"{filename}:scene-{index}:item-1",
            "scene_id": f"{filename}:scene-{index}",
            "stratum": "code_heavy" if index % 11 == 0 else "event_text",
            "source_category": category,
            "source": source or f"台詞{index}",
            "initial_history": [],
            "source_location": {"file": filename, "item": 1},
        }

    def test_custom_map_filter_uses_only_selected_map_files(self):
        pool = [
            self._segment(filename, index, "map_events")
            for filename in ("Map001.json", "Map002.json")
            for index in range(1, 81)
        ]
        selected = evaluation.build_corpus(
            ".",
            target_segments=60,
            content_selection={
                "preset": "custom",
                "sources": ["map_events"],
                "map_files": ["Map002.json"],
            },
            _pool=pool,
        )

        self.assertEqual(len(selected), 60)
        self.assertEqual(
            {item["source_location"]["file"] for item in selected},
            {"Map002.json"},
        )

    def test_file_balancing_prevents_one_large_file_from_dominating(self):
        pool = [
            self._segment(filename, index, "map_events")
            for filename in ("Map001.json", "Map002.json", "Map003.json")
            for index in range(1, 91)
        ]

        selected = evaluation._balanced_take(
            pool, 60, sampling_seed="stable-game-seed"
        )

        self.assertEqual(
            Counter(item["source_location"]["file"] for item in selected),
            Counter({"Map001.json": 20, "Map002.json": 20, "Map003.json": 20}),
        )

    def test_sampling_uses_full_scene_chunks_instead_of_touching_every_file(self):
        pool = []
        for file_index in range(1, 21):
            filename = f"Map{file_index:03d}.json"
            scene_id = f"{filename}:event-1:page-1:call-1"
            for line_index in range(1, 11):
                pool.append({
                    "id": f"{scene_id}:item-{line_index}",
                    "scene_id": scene_id,
                    "stratum": "event_text",
                    "source_category": "map_events",
                    "source": f"台詞{file_index}-{line_index}",
                    "initial_history": [],
                    "source_location": {
                        "file": filename,
                        "item": line_index,
                    },
                })

        selected = evaluation.build_corpus(
            ".",
            target_segments=60,
            sample_size=10,
            content_selection={"preset": "events"},
            _pool=pool,
        )
        grouped = evaluation._assign_review_samples(selected, pool, 10)
        sample_sizes = Counter(
            item["review_sample_id"] for item in grouped
        ).values()

        self.assertEqual(
            len({item["source_location"]["file"] for item in selected}), 6
        )
        self.assertEqual(list(sample_sizes), [10] * 6)

    def test_game_fingerprint_changes_stable_order_between_games(self):
        first = [
            self._segment("Map001.json", index, "map_events", f"一作目{index}")
            for index in range(1, 101)
        ]
        second = [
            self._segment("Map001.json", index, "map_events", f"二作目{index}")
            for index in range(1, 101)
        ]

        first_ids = [item["id"] for item in evaluation.build_corpus(
            ".", target_segments=60,
            content_selection={"preset": "events"}, _pool=first,
        )]
        rebuilt_ids = [item["id"] for item in evaluation.build_corpus(
            ".", target_segments=60,
            content_selection={"preset": "events"}, _pool=first,
        )]
        second_ids = [item["id"] for item in evaluation.build_corpus(
            ".", target_segments=60,
            content_selection={"preset": "events"}, _pool=second,
        )]

        self.assertEqual(first_ids, rebuilt_ids)
        self.assertNotEqual(evaluation.corpus_fingerprint(first), evaluation.corpus_fingerprint(second))
        self.assertNotEqual(first_ids, second_ids)

    def test_manifest_records_filter_seed_inventory_and_exact_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            records = [None] + [
                {
                    "id": index,
                    "name": f"技{index}",
                    "description": "説明です。",
                }
                for index in range(1, 41)
            ]
            (root / "Skills.json").write_text(
                json.dumps(records, ensure_ascii=False), encoding="utf-8"
            )
            manifest = evaluation.build_manifest(
                root,
                target_segments=60,
                repetitions=1,
                content_selection={
                    "preset": "custom",
                    "sources": ["skills"],
                    "include_code_heavy": False,
                },
                system_prompt="Translate Japanese to English.",
                glossary="",
            )

        self.assertEqual(manifest["content_selection"]["sources"], ["skills"])
        self.assertEqual(manifest["sampling_seed"], manifest["corpus_sha256"])
        self.assertEqual(
            manifest["selected_segment_ids"],
            [segment["id"] for segment in manifest["segments"]],
        )
        self.assertEqual(
            {segment["source_category"] for segment in manifest["segments"]},
            {"skills"},
        )
        self.assertEqual(
            manifest["corpus_summary"]["content_inventory"]["source_counts"]["skills"],
            80,
        )

    def test_too_small_filtered_pool_has_actionable_error(self):
        pool = [
            self._segment("Map001.json", index, "map_events")
            for index in range(1, 80)
        ] + [
            {
                **self._segment("Skills.json", index, "skills"),
                "stratum": "database",
            }
            for index in range(1, 20)
        ]
        with self.assertRaisesRegex(ValueError, "select more sources"):
            evaluation.build_corpus(
                ".",
                target_segments=60,
                content_selection={
                    "preset": "custom",
                    "sources": ["skills"],
                },
                _pool=pool,
            )


class EvaluationManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = evaluation.build_manifest(ROOT / "files")

    def test_default_corpus_is_stratified_and_repeated_deterministically(self):
        manifest = self.manifest
        self.assertEqual(len(manifest["segments"]), 360)
        self.assertTrue(all(segment.get("source_category") for segment in manifest["segments"]))
        self.assertGreater(len(manifest["logical_requests"]), 1)
        self.assertGreater(len(manifest["executions"]), len(manifest["logical_requests"]))
        repetitions = Counter(item["repetition"] for item in manifest["executions"])
        self.assertEqual(repetitions[1], len(manifest["logical_requests"]))
        self.assertEqual(repetitions[2], repetitions[3])
        summary = manifest["corpus_summary"]
        self.assertGreater(summary["eligible_segments"], summary["selected_segments"])
        self.assertGreaterEqual(summary["selected_files"], 1)
        self.assertLessEqual(summary["selected_files"], summary["eligible_files"])
        rebuilt = evaluation.build_corpus(ROOT / "files")
        self.assertCountEqual(
            [item["id"] for item in rebuilt],
            [item["id"] for item in manifest["segments"]],
        )
        self.assertTrue(all(
            len(request["segment_ids"]) <= evaluation.DEFAULT_SAMPLE_SIZE
            for request in manifest["logical_requests"]
        ))

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

    def test_review_samples_never_cross_scene_or_source_gaps(self):
        pool = [
            {
                "id": f"segment-{index}",
                "scene_id": "scene-1",
                "stratum": "event_text",
                "source": f"line-{index}",
                "initial_history": [],
            }
            for index in range(1, 5)
        ]
        selected = [pool[0], pool[1], pool[3]]

        grouped = evaluation._assign_review_samples(selected, pool, 10)

        sample_ids = [item["review_sample_id"] for item in grouped]
        self.assertEqual(sample_ids[0], sample_ids[1])
        self.assertNotEqual(sample_ids[1], sample_ids[2])
        self.assertEqual(
            [item["source"] for item in grouped],
            ["line-1", "line-2", "line-4"],
        )

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

    def test_consistency_scores_the_complete_sample_block(self):
        manifest = {
            "repetitions": 2,
            "stability_request_ids": ["logical-0001"],
            "logical_requests": [{
                "id": "logical-0001",
                "segment_ids": ["segment-1", "segment-2"],
            }],
        }
        processed = {
            "rep-1:logical-0001": {
                "logical_request_id": "logical-0001",
                "lines": [
                    {"segment_id": "segment-1", "translation": "One", "valid": True},
                    {"segment_id": "segment-2", "translation": "Two", "valid": True},
                ],
            },
            "rep-2:logical-0001": {
                "logical_request_id": "logical-0001",
                "lines": [
                    {"segment_id": "segment-1", "translation": "One", "valid": True},
                    {"segment_id": "segment-2", "translation": "Changed", "valid": True},
                ],
            },
        }

        stability = evaluation._stability_score(manifest, processed)

        self.assertEqual(stability["samples_with_all_repetitions"], 1)
        self.assertEqual(stability["exactly_stable_samples"], 0)
        self.assertEqual(stability["exact_sample_stability_rate"], 0.0)
        self.assertEqual(stability["exactly_stable_segments"], 1)

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

    def test_legacy_noncompleted_runs_move_out_of_completed_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            completed = self._make_run(project, "completed-run")
            active = self._make_run(project, "active-run")
            state = evaluation._read_json(active / "state.json")
            state["status"] = "submitted"
            state["candidates"][0]["status"] = "submitted"
            evaluation._atomic_write_json(active / "state.json", state)
            legacy_pointer = project / "log" / "evaluations" / "latest.json"
            evaluation._atomic_write_json(legacy_pointer, {"run_dir": str(active)})
            incomplete = project / "log" / "evaluations" / "incomplete-run"
            incomplete.mkdir()

            result = evaluation.maintain_evaluation_storage(project)
            moved = project / "log" / "evaluation_work" / "active-run"

            self.assertTrue(completed.is_dir())
            self.assertFalse(active.exists())
            self.assertTrue(moved.is_dir())
            self.assertFalse(incomplete.exists())
            self.assertFalse(
                (project / "log" / "evaluation_work" / "incomplete-run").exists()
            )
            self.assertEqual(result["discarded"], [incomplete])
            self.assertFalse(legacy_pointer.exists())
            self.assertIn(moved, [target for _source, target in result["moved"]])
            self.assertEqual(
                {item["run_id"] for item in evaluation.list_runs(project)},
                {"completed-run", "active-run"},
            )
            self.assertEqual(evaluation.latest_run(project), moved)

    def test_completed_history_is_pruned_to_newest_fifty(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            for index in range(55):
                run = self._make_run(project, f"run-{index:02d}")
                state = evaluation._read_json(run / "state.json")
                state["archived_at"] = f"2026-08-{index + 1:02d}T12:00:00+00:00"
                evaluation._atomic_write_json(run / "state.json", state)

            removed = evaluation.prune_completed_evaluations(project)
            remaining = evaluation.list_runs(project)

            self.assertEqual(len(removed), 5)
            self.assertEqual(len(remaining), evaluation.MAX_SAVED_EVALUATIONS)
            self.assertEqual(remaining[0]["run_id"], "run-54")
            self.assertFalse(
                (project / "log" / "evaluations" / "run-00").exists()
            )

    def test_prepared_runs_use_work_storage_and_are_not_saved_history(self):
        manifest = {
            "manifest_sha256": "a" * 64,
            "corpus_summary": {"selected_segments": 60},
            "source_dir": "/game/data",
            "executions": [],
            "logical_requests": [],
        }
        candidates = [{
            "provider": "openai",
            "endpoint": "https://api.openai.com/v1",
            "model": "test-model",
            "key_name": "OpenAI",
            "execution": "batch",
        }]
        estimate = {
            "cost_usd": 0.01,
            "maximum_cost_usd": 0.02,
        }
        second_manifest = {**manifest, "manifest_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as temporary, mock.patch(
            "util.evaluation.build_manifest", side_effect=(manifest, second_manifest)
        ), mock.patch(
            "util.evaluation._validate_candidates"
        ), mock.patch(
            "util.evaluation.estimate_candidate", return_value=estimate
        ):
            project = Path(temporary)
            first, _state = evaluation.prepare_run(project, project, candidates)
            second, _state = evaluation.prepare_run(project, project, candidates)

            self.assertEqual(first.parent.name, "evaluation_work")
            self.assertFalse(first.exists())
            self.assertTrue(second.is_dir())
            self.assertEqual(evaluation.list_runs(project), [])
            self.assertIsNone(evaluation.latest_run(project))

    def test_completed_managed_run_moves_into_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            work = project / "log" / "evaluation_work" / "finished-run"
            evaluation._atomic_write_json(work / "manifest.json", {})
            state = {
                "run_id": "finished-run",
                "created_at": "2026-08-01T12:00:00+00:00",
                "updated_at": "2026-08-01T12:30:00+00:00",
                "status": "completed",
                "managed_storage": True,
                "storage": "working",
                "candidates": [],
            }
            evaluation._atomic_write_json(work / "state.json", state)

            archived = evaluation._archive_completed_run(work, state)
            saved, _manifest = evaluation.load_run(archived)

            self.assertFalse(work.exists())
            self.assertEqual(
                archived.parent, project / "log" / "evaluations"
            )
            self.assertEqual(saved["storage"], "completed")
            self.assertEqual(evaluation.locate_run(project, "finished-run"), archived)

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
        self.review_id = "logical-0001"
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

    def test_three_candidate_ranking_points_are_fixed_sum(self):
        cases = {
            "A>B>C": {"A": 2, "B": 1, "C": 0},
            "A=B>C": {"A": 1.5, "B": 1.5, "C": 0},
            "A>B=C": {"A": 2, "B": 0.5, "C": 0.5},
            "A=B=C": {"A": 1, "B": 1, "C": 1},
        }
        for ranking, expected in cases.items():
            with self.subTest(ranking=ranking):
                tiers = evaluation._parse_blind_ranking(
                    ranking, ["A", "B", "C"]
                )
                points = evaluation._ranking_points(tiers)
                self.assertEqual(points, expected)
                self.assertEqual(sum(points.values()), 3)

    def test_export_randomizes_labels_and_import_resolves_hidden_ranking(self):
        review_path = evaluation.export_blind_review(
            self.run_dir, self.run_dir / "external" / "review.csv"
        )
        self.assertTrue((self.run_dir / "blind_review.csv").is_file())
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            {
                json.loads(rows[0][label])[0]
                for label in ("A", "B", "C", "D")
            },
            {
                "translation-gpt", "translation-gemini",
                "translation-sonnet", "translation-other",
            },
        )
        self.assertIn("ranking", rows[0])
        self.assertNotIn("winner", rows[0])
        rows[0]["ranking"] = "B>A=C>D"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        hidden = json.loads((self.run_dir / "blind_key.json").read_text(encoding="utf-8"))
        expected = hidden[self.review_id]["B"]
        review = evaluation.import_blind_review(self.run_dir, review_path)
        self.assertEqual(review["wins"][expected], 1)
        self.assertEqual(review["points"][expected], 3)
        self.assertEqual(review["partial_ties"], 1)
        self.assertEqual(review["reviewed"], 1)
        self.assertIn(
            ",B>A=C>D,",
            (self.run_dir / "blind_review.csv").read_text(encoding="utf-8-sig"),
        )

    def test_multi_line_sample_is_exported_and_scored_once_as_a_block(self):
        manifest_path = self.run_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        second = {
            "id": "segment-2",
            "scene_id": "scene-1",
            "stratum": "dialogue",
            "source": "犬だ。",
        }
        manifest["segments"].append(second)
        request = manifest["logical_requests"][0]
        request["segment_ids"].append("segment-2")
        request["sources"] = ["猫だ。", "犬だ。"]
        evaluation._atomic_write_json(manifest_path, manifest)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        for candidate in state["candidates"]:
            result_path = self.run_dir / candidate["result_file"]
            result = json.loads(result_path.read_text(encoding="utf-8"))
            first = result["executions"]["rep-1:logical-0001"]["lines"][0]
            result["executions"]["rep-1:logical-0001"]["lines"].append({
                "segment_id": "segment-2",
                "translation": first["translation"] + "-second",
            })
            evaluation._atomic_write_json(result_path, result)

        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sample_id"], self.review_id)
        self.assertEqual(rows[0]["line_count"], "2")
        self.assertEqual(json.loads(rows[0]["source"]), ["猫だ。", "犬だ。"])
        self.assertTrue(all(
            len(json.loads(rows[0][label])) == 2
            for label in ("A", "B", "C", "D")
        ))

        rows[0]["ranking"] = "A>B>C>D"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        review = evaluation.import_blind_review(self.run_dir, review_path)
        self.assertEqual(review["reviewed"], 1)
        self.assertEqual(review["reviewed_lines"], 2)
        self.assertEqual(sum(review["wins"].values()), 1)
        self.assertEqual(sum(review["points"].values()), 12)
        self.assertEqual(
            review["scoring"], "fixed-sum-borda-average-per-line-v2"
        )

    def test_import_rejects_changed_sample_line_count(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["line_count"] = "10"
        rows[0]["ranking"] = "A>B>C>D"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(ValueError, "Protected line count changed"):
            evaluation.import_blind_review(self.run_dir, review_path)

    def test_import_ranking_averages_tied_positions_without_inflation(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["ranking"] = "A=B>C>D"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        hidden = json.loads((self.run_dir / "blind_key.json").read_text(encoding="utf-8"))
        review = evaluation.import_blind_review(self.run_dir, review_path)

        scores = {
            label: review["points"][candidate_id]
            for label, candidate_id in hidden[self.review_id].items()
        }
        self.assertEqual(scores, {"A": 2.5, "B": 2.5, "C": 1, "D": 0})
        self.assertEqual(sum(scores.values()), 6)
        self.assertEqual(review["wins"], {
            candidate_id: 0 for candidate_id in hidden[self.review_id].values()
        })
        self.assertEqual(review["partial_ties"], 1)

    def test_import_rejects_incomplete_or_duplicate_ranking(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["ranking"] = "A>B>B>D"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(ValueError, "use every label exactly once"):
            evaluation.import_blind_review(self.run_dir, review_path)

    def test_import_accepts_legacy_winner_csv(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        legacy_fields = [
            "winner" if field == "ranking" else field
            for field in rows[0].keys()
        ]
        legacy_row = {
            ("winner" if field == "ranking" else field): value
            for field, value in rows[0].items()
        }
        legacy_row["winner"] = "B"
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=legacy_fields)
            writer.writeheader()
            writer.writerow(legacy_row)

        hidden = json.loads((self.run_dir / "blind_key.json").read_text(encoding="utf-8"))
        review = evaluation.import_blind_review(self.run_dir, review_path)
        scores = {
            label: review["points"][candidate_id]
            for label, candidate_id in hidden[self.review_id].items()
        }

        self.assertEqual(scores["B"], 3)
        self.assertEqual({scores[label] for label in ("A", "C", "D")}, {1})
        self.assertEqual(review["wins"][hidden[self.review_id]["B"]], 1)

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
        self.assertEqual(coverage["total_samples"], 1)
        self.assertEqual(coverage["eligible_samples"], 1)

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
