from __future__ import annotations

import csv
import json
import tempfile
import threading
import unittest
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path
from unittest import mock

from util import batch_providers, evaluation


ROOT = Path(__file__).resolve().parents[1]


class EvaluationAtomicWriteTests(unittest.TestCase):
    def test_atomic_json_write_retries_transient_replace_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            real_replace = evaluation.os.replace
            replace_attempts = 0

            def intermittently_locked(source, destination):
                nonlocal replace_attempts
                replace_attempts += 1
                if replace_attempts < 3:
                    raise PermissionError("checkpoint is temporarily locked")
                return real_replace(source, destination)

            with (
                mock.patch.object(
                    evaluation.os, "replace", side_effect=intermittently_locked
                ),
                mock.patch.object(evaluation.time, "sleep") as sleep,
            ):
                evaluation._atomic_write_json(path, {"finished": 46})

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), {"finished": 46}
            )
            self.assertEqual(replace_attempts, 3)
            self.assertEqual(
                [call.args[0] for call in sleep.call_args_list], [0.05, 0.1]
            )
            self.assertEqual(list(Path(temporary).iterdir()), [path])

    def test_atomic_json_write_does_not_retry_unrelated_os_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "checkpoint.json"
            with (
                mock.patch.object(
                    evaluation.os, "replace", side_effect=OSError("disk error")
                ),
                mock.patch.object(evaluation.time, "sleep") as sleep,
            ):
                with self.assertRaisesRegex(OSError, "disk error"):
                    evaluation._atomic_write_json(path, {"finished": 46})

            sleep.assert_not_called()
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_submit_lock_rejects_a_second_submitter(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            with evaluation._evaluation_submit_lock(run_dir):
                with self.assertRaisesRegex(RuntimeError, "already being submitted"):
                    with evaluation._evaluation_submit_lock(run_dir):
                        pass

    def test_refresh_uses_the_same_run_mutation_lock(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run-one"
            with evaluation._evaluation_submit_lock(run_dir):
                with self.assertRaisesRegex(RuntimeError, "already being submitted"):
                    evaluation.refresh_run(run_dir, {})

            self.assertFalse((run_dir / ".submit.lock").exists())


class EvaluationSourceFolderTests(unittest.TestCase):
    def test_event_capture_uses_selected_glossary_without_leaking_runtime_state(self):
        import modules.rpgmakermvmz as mvmz

        page = {
            "list": [
                {"code": 101, "indent": 0, "parameters": ["", 0, 0, 2, "騎士"]},
                {"code": 401, "indent": 0, "parameters": ["こんにちは、世界。"]},
                {"code": 0, "indent": 0, "parameters": []},
            ]
        }
        original_vocab = mvmz.VOCAB
        original_config_vocab = mvmz.TRANSLATION_CONFIG.vocab
        with mvmz._speakerCacheLock:
            original_cache = dict(mvmz._speakerCache)
        try:
            mvmz.VOCAB = "# Speakers\n騎士 (Wrong Cached Name)\n"
            mvmz.TRANSLATION_CONFIG.vocab = mvmz.VOCAB
            with mvmz._speakerCacheLock:
                mvmz._speakerCache.clear()
                mvmz._speakerCache["騎士"] = "Stale Cache"

            segments = evaluation._capture_page_data(
                page,
                "Map001.json",
                {"event": 1, "page": 1},
                glossary="# Speakers\n騎士 (Selected Knight)\n",
            )

            self.assertEqual(
                [segment["source"] for segment in segments],
                ["[Selected Knight]: こんにちは、世界。"],
            )
            self.assertEqual(mvmz.VOCAB, "# Speakers\n騎士 (Wrong Cached Name)\n")
            self.assertEqual(mvmz.TRANSLATION_CONFIG.vocab, mvmz.VOCAB)
            with mvmz._speakerCacheLock:
                self.assertEqual(mvmz._speakerCache, {"騎士": "Stale Cache"})
        finally:
            mvmz.VOCAB = original_vocab
            mvmz.TRANSLATION_CONFIG.vocab = original_config_vocab
            with mvmz._speakerCacheLock:
                mvmz._speakerCache.clear()
                mvmz._speakerCache.update(original_cache)

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

    def test_oversized_sample_is_rejected_before_provider_submission(self):
        request = {
            "id": "logical-too-large",
            "segment_ids": [f"segment-{index}" for index in range(2_000)],
            "system": "Translate Japanese to English.",
            "glossary": "",
            "sfx_reference": "",
            "history": [],
            "user": "あ" * 10_000,
        }

        with self.assertRaisesRegex(ValueError, "Lines per sample is too high"):
            evaluation._validate_request_output_capacity([request])


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
        cls._fixture = tempfile.TemporaryDirectory()
        cls.data_root = Path(cls._fixture.name)
        records = [None] + [
            {
                "id": index,
                "name": f"名{index}",
                "description": f"文{index}",
                "message1": f"技{index}",
                "message2": f"術{index}",
            }
            for index in range(1, 101)
        ]
        (cls.data_root / "Skills.json").write_text(
            json.dumps(records, ensure_ascii=False), encoding="utf-8"
        )
        cls.manifest = evaluation.build_manifest(cls.data_root)

    @classmethod
    def tearDownClass(cls):
        cls._fixture.cleanup()

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
        rebuilt = evaluation.build_corpus(self.data_root)
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

    def test_custom_small_samples_use_only_the_previous_production_chunk(self):
        pool = [
            {
                "id": f"segment-{index}",
                "scene_id": "scene-1",
                "stratum": "event_text",
                "source": f"line-{index}",
                "initial_history": [],
            }
            for index in range(1, 10)
        ]

        grouped = evaluation._assign_review_samples(pool, pool, 3)
        requests = evaluation._build_logical_requests(
            grouped, "Translate Japanese to English.", "", 3, False
        )

        self.assertEqual(
            [request["history"] for request in requests],
            [
                [],
                ["line-1", "line-2", "line-3"],
                ["line-4", "line-5", "line-6"],
            ],
        )

    def test_every_request_has_locked_context_and_bounded_source_history(self):
        audit = evaluation.context_audit(self.manifest)
        self.assertTrue(audit["all_have_system"])
        self.assertTrue(audit["all_have_source"])
        self.assertTrue(audit["source_context_typed"])
        self.assertTrue(audit["instructions_typed"])
        self.assertTrue(audit["history_limit_ok"])
        for request in self.manifest["logical_requests"]:
            logical = {
                "system": request["system"],
                "glossary": request["glossary"],
                "sfx_reference": request["sfx_reference"],
                "history": request["history"],
                "context_kind": request["context_kind"],
                "instructions": request["instructions"],
                "user": request["user"],
                "schema_line_count": request["schema_line_count"],
            }
            self.assertEqual(request["logical_hash"], evaluation._sha256(logical))
            self.assertEqual(request["context_kind"], "source_context")

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
        self.assertEqual(
            params["openai"]["extra_body"]["prompt_cache_options"],
            {"mode": "explicit"},
        )
        self.assertTrue(any(
            "prompt_cache_breakpoint" in block
            for message in params["openai"]["messages"]
            if isinstance(message.get("content"), list)
            for block in message["content"]
        ))
        live_openai = evaluation._provider_params(
            {**candidates[0], "execution": "live"}, request
        )
        self.assertTrue(any(
            "prompt_cache_breakpoint" in block
            for message in live_openai["messages"]
            if isinstance(message.get("content"), list)
            for block in message["content"]
        ))
        self.assertIn(
            "prompt_cache_key", live_openai["extra_body"]
        )
        alternate_schema = {
            **request,
            "schema_line_count": int(request["schema_line_count"]) + 1,
        }
        self.assertNotEqual(
            live_openai["extra_body"]["prompt_cache_key"],
            evaluation._provider_params(
                {**candidates[0], "execution": "live"},
                alternate_schema,
            )["extra_body"]["prompt_cache_key"],
        )
        openrouter = evaluation._provider_params(
            {
                **candidates[0],
                "endpoint": "https://openrouter.ai/api/v1",
                "execution": "live",
            },
            request,
        )
        self.assertNotIn("extra_body", openrouter)
        self.assertEqual(
            openrouter["max_tokens"], evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST
        )
        self.assertIsInstance(openrouter["messages"][0]["content"], str)
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
        self.assertFalse(any(
            "cache_control" in block
            for block in params["anthropic"]["system"]
        ))
        self.assertEqual(
            params["anthropic"]["max_tokens"],
            evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST,
        )
        self.assertEqual(
            params["anthropic"]["output_config"]["format"]["schema"]
            ["required"],
            [f"Line{i}" for i in range(1, request["schema_line_count"] + 1)],
        )
        live_anthropic = evaluation._provider_params(
            {**candidates[2], "execution": "live"}, request
        )
        self.assertTrue(any(
            "cache_control" in block
            for block in live_anthropic["system"]
        ))
        live_cache = next(
            block["cache_control"]
            for block in live_anthropic["system"]
            if "cache_control" in block
        )
        self.assertEqual(live_cache["ttl"], "5m")

    def test_claude_batch_submits_uncached_without_live_prewarm(self):
        request = self.manifest["logical_requests"][0]
        manifest = {
            **self.manifest,
            "logical_requests": [request],
            "executions": [{
                "id": "rep-1:logical-0001",
                "logical_request_id": request["id"],
                "repetition": 1,
            }],
        }
        candidate = {
            **dict(evaluation.DEFAULT_CANDIDATES[2]),
            "id": "candidate-claude",
            "status": "prepared",
            "estimate": {"cost_usd": 1.0},
        }
        submitted_params = []

        def submit(_provider, requests, **_kwargs):
            submitted_params.extend(item["params"] for item in requests)
            return {"id": "batch-claude"}

        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(
                evaluation, "_clients", return_value=(object(), None)
            ),
            mock.patch.object(
                evaluation.batch_api, "execute_live_request"
            ) as execute_live,
            mock.patch.object(
                evaluation.batch_api, "submit_batch", side_effect=submit
            ),
            mock.patch("util.batch_history.upsert_history_entry"),
        ):
            evaluation._submit_candidate(
                Path(temporary),
                {"run_id": "uncached-claude-batch"},
                manifest,
                candidate,
                evaluation._request_lookup(manifest),
                "secret",
                lambda _message: None,
                None,
                lambda _candidate: None,
            )

        self.assertEqual(candidate["batch_id"], "batch-claude")
        execute_live.assert_not_called()
        self.assertNotIn("cache_prewarm", candidate)
        self.assertNotIn("prewarm_usage", candidate)
        self.assertTrue(submitted_params)
        self.assertFalse(any(
            "cache_control" in block
            for params in submitted_params
            for block in params["system"]
        ))

    def test_locked_batch_pricing_handles_sonnet_intro_expiry(self):
        self.assertEqual(
            evaluation.pricing_for("gpt-5.6-terra")["output"], 6.00
        )
        self.assertEqual(
            evaluation.pricing_for("gpt-5.6-terra")["input"], 1.00
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

    def test_openrouter_candidate_uses_router_live_pricing(self):
        response = mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps({
            "data": {
                "pricing": {
                    "prompt": "0.00000009",
                    "completion": "0.00000018",
                    "input_cache_read": "0.000000018",
                }
            }
        }).encode("utf-8")
        evaluation._openrouter_pricing_cache.clear()
        self.addCleanup(evaluation._openrouter_pricing_cache.clear)

        with mock.patch.object(
            evaluation.urllib.request, "urlopen", return_value=response
        ) as urlopen:
            rates = evaluation._candidate_rates({
                "provider": "openai",
                "endpoint": "https://openrouter.ai/api/v1/",
                "model": "deepseek/deepseek-v4-flash-0731",
                "execution": "live",
            })
            cached_rates = evaluation._candidate_rates({
                "provider": "openai",
                "endpoint": "https://openrouter.ai/api/v1/",
                "model": "deepseek/deepseek-v4-flash-0731",
                "execution": "live",
            })

        self.assertEqual(
            rates,
            {"input": 0.09, "cached_input": 0.018, "output": 0.18},
        )
        self.assertEqual(cached_rates, rates)
        urlopen.assert_called_once()

    def test_openrouter_batch_candidate_is_rejected_before_pricing(self):
        candidates = [
            {
                "provider": "openai",
                "endpoint": "https://openrouter.ai/api/v1/",
                "model": "deepseek/deepseek-v4-pro",
                "key_name": "OpenRouter",
                "execution": "batch",
            },
            {
                "provider": "openai",
                "endpoint": "http://127.0.0.1:8000/v1",
                "model": "local-model",
                "key_name": "Local",
                "keyless": True,
                "execution": "live",
            },
        ]

        with self.assertRaisesRegex(ValueError, "OpenRouter.*Live"):
            evaluation._validate_candidates(candidates)

    def test_usage_pricing_applies_provider_cache_write_rates(self):
        usage = {
            "input_tokens": 0,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 1_000_000,
            "output_tokens": 0,
            "thinking_tokens": 0,
        }
        openai_cost = evaluation._price_usage(
            {
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "execution": "batch",
            },
            usage,
        )
        anthropic_cost = evaluation._price_usage(
            {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "execution": "batch",
            },
            usage,
        )
        anthropic_live_cost = evaluation._price_usage(
            {
                "provider": "anthropic",
                "model": "claude-sonnet-5",
                "execution": "live",
            },
            usage,
        )

        self.assertEqual(openai_cost, 1.25)
        self.assertEqual(anthropic_cost, 2.00)
        self.assertEqual(anthropic_live_cost, 2.50)

    def test_no_cache_baseline_reprices_all_input_at_base_rate(self):
        candidate = {
            "provider": "openai",
            "model": "gpt-5.6-terra",
            "execution": "batch",
        }
        usage = {
            "input_tokens": 100_000,
            "cache_read_input_tokens": 600_000,
            "cache_creation_input_tokens": 300_000,
            "output_tokens": 100_000,
        }

        self.assertEqual(
            evaluation._no_cache_cost(candidate, usage), 1.6
        )

    def test_default_estimates_stay_below_safe_budget(self):
        for candidate in evaluation.DEFAULT_CANDIDATES:
            estimate = evaluation.estimate_candidate(self.manifest, candidate)
            self.assertGreater(estimate["cost_usd"], 0)
            self.assertLess(estimate["cost_usd"], 8.0)
            self.assertLess(estimate["maximum_cost_usd"], 10.0)

    def test_claude_batch_estimate_excludes_cache_write_and_prewarm(self):
        candidate = dict(evaluation.DEFAULT_CANDIDATES[2])
        estimate = evaluation.estimate_candidate(self.manifest, candidate)
        rates = estimate["rates"]
        expected_ceiling = (
            estimate["input_tokens"] * 1.25 * rates["input"]
            + len(self.manifest["executions"])
            * evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST
            * rates["output"]
        ) / 1_000_000

        self.assertAlmostEqual(estimate["maximum_cost_usd"], expected_ceiling)
        self.assertNotIn("prewarm_tokens", estimate)
        self.assertNotIn("prewarm_cost_usd", estimate)

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
            batch_estimate["maximum_cost_usd"]
            * 2
            * evaluation.LIVE_REQUEST_MAX_ATTEMPTS,
        )
        self.assertEqual(batch_estimate["automatic_attempts"], 1)
        self.assertEqual(
            live_estimate["automatic_attempts"],
            evaluation.LIVE_REQUEST_MAX_ATTEMPTS,
        )

    def test_likely_upper_bound_never_exceeds_theoretical_ceiling(self):
        candidate = dict(evaluation.DEFAULT_CANDIDATES[0])
        with mock.patch.object(
            evaluation, "countTokens", return_value=(100, 100_000)
        ):
            estimate = evaluation.estimate_candidate(self.manifest, candidate)

        self.assertLessEqual(
            estimate["cost_usd"], estimate["maximum_cost_usd"]
        )
        self.assertEqual(
            estimate["output_tokens"],
            len(self.manifest["executions"])
            * evaluation.MAX_OUTPUT_TOKENS_PER_REQUEST,
        )

    def test_submit_refreshes_estimate_and_blocks_over_budget_before_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            candidate = {
                **dict(evaluation.DEFAULT_CANDIDATES[0]),
                "id": "candidate-1",
                "key_name": "OpenAI",
                "status": "prepared",
                "estimate": {
                    "cost_usd": 0.01,
                    "maximum_cost_usd": 0.02,
                },
            }
            evaluation._atomic_write_json(
                run_dir / "manifest.json", self.manifest
            )
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "stale-estimate",
                "status": "prepared",
                "budget_usd_per_model": 1.0,
                "candidates": [candidate],
            })
            refreshed = {
                "cost_usd": 0.01,
                "maximum_cost_usd": 2.0,
                "automatic_attempts": 1,
            }
            with (
                mock.patch.object(
                    evaluation, "estimate_candidate", return_value=refreshed
                ),
                mock.patch.object(evaluation, "_clients") as clients,
                mock.patch.object(evaluation.batch_api, "submit_batch") as submit,
            ):
                with self.assertRaisesRegex(ValueError, "theoretical ceiling"):
                    evaluation.submit_run(
                        run_dir, {"candidate-1": "secret"}
                    )

            clients.assert_not_called()
            submit.assert_not_called()

    def test_refresh_upgrades_legacy_live_retry_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            candidate = {
                **dict(evaluation.DEFAULT_CANDIDATES[0]),
                "id": "candidate-live",
                "key_name": "OpenAI",
                "execution": "live",
                "status": "prepared",
                "estimate": {"cost_usd": 0.01},
            }
            evaluation._atomic_write_json(
                run_dir / "manifest.json", self.manifest
            )
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "legacy-live-estimate",
                "status": "prepared",
                "budget_usd_per_model": 100.0,
                "candidates": [candidate],
            })

            state, _manifest = evaluation.refresh_run_estimates(run_dir)

            self.assertEqual(
                state["candidates"][0]["estimate"]["automatic_attempts"],
                evaluation.LIVE_REQUEST_MAX_ATTEMPTS,
            )
            persisted = evaluation._read_json(run_dir / "state.json")
            self.assertEqual(
                persisted["candidates"][0]["estimate"]["automatic_attempts"],
                evaluation.LIVE_REQUEST_MAX_ATTEMPTS,
            )

    def test_failed_live_candidate_does_not_hide_submitted_batch(self):
        candidates = [
            {"status": "failed", "execution": "live"},
            {"status": "submitted", "execution": "batch"},
        ]

        self.assertEqual(
            evaluation._run_completion_status(candidates), "submitted"
        )

    def test_running_live_candidate_keeps_mixed_run_actionable(self):
        candidates = [
            {"status": "submitted", "execution": "batch"},
            {"status": "running_live", "execution": "live"},
        ]

        self.assertEqual(
            evaluation._run_completion_status(candidates), "partially_submitted"
        )

    def test_refresh_finishes_mixed_live_and_batch_candidates(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", {})
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "mixed-terminal",
                "status": "submitted",
                "candidates": [
                    {"id": "live", "execution": "live", "status": "completed"},
                    {
                        "id": "batch", "execution": "batch", "status": "completed",
                        "batch_id": "batch-1",
                    },
                ],
            })

            state = evaluation.refresh_run(run_dir, {})

        self.assertEqual(state["status"], "completed")

    def test_refresh_preserves_partially_submitted_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", {})
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "partial",
                "status": "partially_submitted",
                "candidates": [
                    {
                        "id": "batch-1", "provider": "openai", "label": "one",
                        "status": "submitted", "batch_id": "batch-1",
                    },
                    {
                        "id": "batch-2", "provider": "openai", "label": "two",
                        "status": "prepared",
                    },
                ],
            })
            with (
                mock.patch.object(
                    evaluation, "_clients", return_value=(object(), None)
                ),
                mock.patch.object(
                    evaluation.batch_api,
                    "retrieve_batch",
                    return_value={
                        "api_status": "in_progress",
                        "ended": False,
                        "counts": {
                            "processing": 1, "succeeded": 0, "errored": 0,
                            "canceled": 0, "expired": 0,
                        },
                    },
                ),
                mock.patch("util.batch_history.upsert_history_entry"),
            ):
                state = evaluation.refresh_run(run_dir, {"batch-1": "key"})

        self.assertEqual(state["status"], "partially_submitted")
        self.assertEqual(
            [candidate["status"] for candidate in state["candidates"]],
            ["submitted", "prepared"],
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
                mock.patch.object(
                    evaluation, "_clients", return_value=(object(), None)
                ) as clients,
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
            clients.assert_called_once()
            client_args, client_kwargs = clients.call_args
            self.assertEqual(client_args[0]["id"], "candidate-1")
            self.assertEqual(client_args[1], "local-key")
            self.assertEqual(client_kwargs, {"max_retries": 0})
            submit.assert_not_called()

    def test_live_evaluation_disables_hidden_sdk_retries(self):
        candidate = {
            "provider": "openai",
            "endpoint": "https://api.openai.com/v1",
        }
        client = object()
        with mock.patch.object(
            evaluation.batch_api, "get_client", return_value=client
        ) as get_client:
            resolved, google_client = evaluation._clients(
                candidate, "secret", max_retries=0
            )

        self.assertIs(resolved, client)
        self.assertIsNone(google_client)
        get_client.assert_called_once_with(
            "openai",
            api_key="secret",
            api_url="https://api.openai.com/v1",
            max_retries=0,
        )

    def test_resuming_remaining_candidates_does_not_replay_failed_live_candidate(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "skip-failed-live",
                "status": "partially_submitted",
                "candidates": [
                    {
                        "id": "failed-live",
                        "provider": "openai",
                        "endpoint": "https://api.openai.com/v1",
                        "model": "failed-model",
                        "label": "failed-model",
                        "key_name": "OpenAI",
                        "execution": "live",
                        "status": "failed",
                        "estimate": {"cost_usd": 1.0},
                    },
                    {
                        "id": "pending-batch",
                        "provider": "openai",
                        "endpoint": "https://api.openai.com/v1",
                        "model": "batch-model",
                        "label": "batch-model",
                        "key_name": "OpenAI",
                        "execution": "batch",
                        "status": "prepared",
                        "estimate": {"cost_usd": 1.0},
                    },
                ],
            })
            with (
                mock.patch.object(
                    evaluation,
                    "estimate_candidate",
                    return_value={
                        "cost_usd": 0.01,
                        "maximum_cost_usd": 0.02,
                        "automatic_attempts": 1,
                    },
                ),
                mock.patch.object(evaluation, "_execute_live_candidate") as execute,
                mock.patch.object(
                    evaluation, "_clients", return_value=(object(), None)
                ),
                mock.patch.object(
                    evaluation.batch_api,
                    "submit_batch",
                    return_value={"id": "batch-new"},
                ),
                mock.patch("util.batch_history.upsert_history_entry"),
            ):
                state = evaluation.submit_run(
                    run_dir,
                    {"failed-live": "key", "pending-batch": "key"},
                )

        execute.assert_not_called()
        self.assertEqual(state["candidates"][0]["status"], "failed")
        self.assertEqual(state["candidates"][1]["batch_id"], "batch-new")

    def test_stop_before_submission_prevents_candidates_from_starting(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            candidates = [
                {
                    "id": "live-first",
                    "provider": "openai",
                    "model": "live-model",
                    "label": "live-model",
                    "key_name": "OpenAI",
                    "endpoint": "https://api.openai.com/v1",
                    "execution": "live",
                    "status": "prepared",
                    "estimate": {"cost_usd": 1.0},
                },
                {
                    "id": "batch-second",
                    "provider": "openai",
                    "model": "batch-model",
                    "label": "batch-model",
                    "key_name": "OpenAI",
                    "endpoint": "https://api.openai.com/v1",
                    "execution": "batch",
                    "status": "prepared",
                    "estimate": {"cost_usd": 1.0},
                },
            ]
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "stop-before-next-candidate",
                "status": "prepared",
                "candidates": candidates,
            })
            with (
                mock.patch.object(
                    evaluation,
                    "estimate_candidate",
                    side_effect=lambda _manifest, candidate: {
                        "cost_usd": 0.01,
                        "maximum_cost_usd": 0.02,
                        "automatic_attempts": (
                            evaluation.LIVE_REQUEST_MAX_ATTEMPTS
                            if candidate.get("execution") == "live"
                            else 1
                        ),
                    },
                ),
                mock.patch.object(
                    evaluation,
                    "_execute_live_candidate",
                ) as execute,
                mock.patch.object(evaluation.batch_api, "submit_batch") as submit,
            ):
                state = evaluation.submit_run(
                    run_dir,
                    {"live-first": "key", "batch-second": "key"},
                    should_stop=lambda: True,
                )

        execute.assert_not_called()
        submit.assert_not_called()
        self.assertEqual(state["candidates"][0]["status"], "prepared")
        self.assertEqual(state["candidates"][1]["status"], "prepared")
        self.assertEqual(state["status"], "prepared")

    def test_each_model_runs_on_a_concurrent_worker(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            candidates = [
                {
                    "id": f"candidate-{index}",
                    "provider": "openai",
                    "model": f"live-model-{index}",
                    "label": f"live-model-{index}",
                    "key_name": "OpenAI",
                    "endpoint": "https://api.openai.com/v1",
                    "execution": "live",
                    "status": "prepared",
                    "estimate": {"cost_usd": 1.0},
                }
                for index in (1, 2)
            ]
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "parallel-models",
                "status": "prepared",
                "candidates": candidates,
            })
            rendezvous = threading.Barrier(2, timeout=2)
            worker_threads: set[int] = set()

            def finish_together(
                _root, _state, _manifest, candidate, *_args, **_kwargs
            ):
                worker_threads.add(threading.get_ident())
                rendezvous.wait()
                candidate["status"] = "completed"
                return True, run_dir / "results" / f"{candidate['id']}.partial.json"

            with (
                mock.patch.object(
                    evaluation,
                    "estimate_candidate",
                    return_value={
                        "cost_usd": 0.01,
                        "maximum_cost_usd": 0.02,
                        "automatic_attempts": evaluation.LIVE_REQUEST_MAX_ATTEMPTS,
                    },
                ),
                mock.patch.object(
                    evaluation,
                    "_execute_live_candidate",
                    side_effect=finish_together,
                ),
            ):
                state = evaluation.submit_run(
                    run_dir,
                    {"candidate-1": "key", "candidate-2": "key"},
                )

        self.assertEqual(len(worker_threads), 2)
        self.assertEqual(state["status"], "completed")
        self.assertTrue(all(
            candidate["status"] == "completed"
            for candidate in state["candidates"]
        ))

    def test_parallel_failure_preserves_another_models_paid_batch_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            candidates = [
                {
                    "id": f"candidate-{index}",
                    "provider": "openai",
                    "model": f"batch-model-{index}",
                    "label": f"batch-model-{index}",
                    "key_name": "OpenAI",
                    "endpoint": "https://api.openai.com/v1",
                    "execution": "batch",
                    "status": "prepared",
                    "estimate": {"cost_usd": 1.0},
                }
                for index in (1, 2)
            ]
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "parallel-partial-failure",
                "status": "prepared",
                "candidates": candidates,
            })

            def submit(_provider, _requests, *, client, **_kwargs):
                if client == "candidate-1":
                    return {"id": "paid-batch-1"}
                raise RuntimeError("second provider unavailable")

            with (
                mock.patch.object(
                    evaluation,
                    "estimate_candidate",
                    return_value={
                        "cost_usd": 0.01,
                        "maximum_cost_usd": 0.02,
                        "automatic_attempts": 1,
                    },
                ),
                mock.patch.object(
                    evaluation,
                    "_clients",
                    side_effect=lambda candidate, _secret: (
                        candidate["id"], None
                    ),
                ),
                mock.patch.object(
                    evaluation.batch_api, "submit_batch", side_effect=submit
                ),
                mock.patch("util.batch_history.upsert_history_entry"),
            ):
                state = evaluation.submit_run(
                    run_dir,
                    {"candidate-1": "key", "candidate-2": "key"},
                )

            saved, _manifest = evaluation.load_run(run_dir)

        self.assertEqual(state, saved)
        self.assertEqual(saved["status"], "partially_submitted")
        self.assertEqual(saved["candidates"][0]["batch_id"], "paid-batch-1")
        self.assertEqual(saved["candidates"][1]["status"], "prepared")
        self.assertIn(
            "second provider unavailable",
            saved["candidates"][1]["submission_error"],
        )
        self.assertEqual(
            saved["submission_errors"][0]["candidate_id"], "candidate-2"
        )

    def test_duplicate_candidate_ids_block_submission_before_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            candidate = {
                "id": "duplicate-id",
                "provider": "openai",
                "model": "batch-model",
                "label": "batch-model",
                "key_name": "OpenAI",
                "endpoint": "https://api.openai.com/v1",
                "execution": "batch",
                "status": "prepared",
                "estimate": {"cost_usd": 1.0},
            }
            evaluation._atomic_write_json(run_dir / "manifest.json", self.manifest)
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "duplicate-candidate-ids",
                "status": "prepared",
                "candidates": [candidate, {**candidate, "label": "second"}],
            })
            with (
                mock.patch.object(
                    evaluation,
                    "estimate_candidate",
                    return_value={
                        "cost_usd": 0.01,
                        "maximum_cost_usd": 0.02,
                        "automatic_attempts": 1,
                    },
                ),
                mock.patch.object(evaluation, "_clients") as clients,
                mock.patch.object(
                    evaluation.batch_api, "submit_batch"
                ) as submit,
            ):
                with self.assertRaisesRegex(ValueError, "Duplicate.*candidate id"):
                    evaluation.submit_run(run_dir, {"duplicate-id": "key"})

            clients.assert_not_called()
            submit.assert_not_called()

    def test_live_evaluation_resumes_from_per_request_checkpoint(self):
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
                "run_id": "live-resume-test",
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
            ):
                interrupted = evaluation.submit_run(
                    run_dir,
                    {"candidate-1": "local-key"},
                    should_stop=lambda: execute.call_count >= 1,
                )
                self.assertEqual(interrupted["status"], "partially_submitted")
                self.assertEqual(
                    interrupted["candidates"][0]["live_completed_requests"], 1
                )
                checkpoint = (
                    run_dir / "results" / "candidate-1.live.partial.json"
                )
                self.assertTrue(checkpoint.is_file())
                archive_path = evaluation.export_run_archive(
                    run_dir, run_dir / "live-partial.dazedeval"
                )
                with zipfile.ZipFile(archive_path) as archive:
                    self.assertIn(
                        "results/candidate-1.live.partial.json",
                        archive.namelist(),
                    )

                completed = evaluation.submit_run(
                    run_dir, {"candidate-1": "local-key"}
                )

            self.assertEqual(completed["status"], "completed")
            self.assertEqual(
                execute.call_count, len(self.manifest["executions"])
            )
            self.assertFalse(checkpoint.exists())

    def test_live_checkpoint_is_bound_to_the_frozen_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            candidate = {
                "id": "candidate-1",
                "provider": "openai",
                "endpoint": "https://api.openai.com/v1",
                "model": "gpt-test",
                "label": "gpt-test",
                "execution": "live",
                "status": "running_live",
            }
            state = {
                "version": evaluation.EVALUATION_VERSION,
                "run_id": "bound-checkpoint",
                "status": "partially_submitted",
                "manifest_sha256": self.manifest["manifest_sha256"],
                "candidates": [candidate],
            }
            checkpoint = run_dir / "results" / "candidate-1.live.partial.json"
            evaluation._atomic_write_json(checkpoint, {
                **evaluation._candidate_artifact_identity(candidate, self.manifest),
                "manifest_sha256": "0" * 64,
                "raw_results": {},
                "errors": [],
                "usage": {},
            })

            with (
                mock.patch.object(evaluation, "_clients", return_value=(object(), None)),
                mock.patch.object(evaluation.batch_api, "execute_live_request") as execute,
            ):
                with self.assertRaisesRegex(ValueError, "wrong manifest sha256"):
                    evaluation._execute_live_candidate(
                        run_dir,
                        state,
                        self.manifest,
                        candidate,
                        evaluation._request_lookup(self.manifest),
                        "local-key",
                        lambda _message: None,
                    )

            execute.assert_not_called()

    def test_live_evaluation_retries_transient_request_errors(self):
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
                "run_id": "live-retry-test",
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

            responses = [RuntimeError("HTTP 429: rate limited"), response]

            def retry_once(provider, params, **kwargs):
                result = responses.pop(0)
                if isinstance(result, Exception):
                    raise result
                return result(provider, params, **kwargs)

            with (
                mock.patch.object(evaluation, "_clients", return_value=(object(), None)),
                mock.patch.object(
                    evaluation.batch_api,
                    "execute_live_request",
                    side_effect=retry_once,
                ) as execute,
                mock.patch.object(evaluation.time, "sleep") as sleep,
            ):
                state = evaluation.submit_run(run_dir, {"candidate-1": "local-key"})

            self.assertEqual(state["status"], "completed")
            self.assertEqual(
                execute.call_count, len(self.manifest["executions"]) + 1
            )
            sleep.assert_called_once_with(1)
            self.assertNotIn("live_retryable_error", state["candidates"][0])

    def test_live_evaluation_leaves_exhausted_transient_error_resumable(self):
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
                "run_id": "live-retry-resume-test",
                "status": "prepared",
                "candidates": [candidate],
            })

            with (
                mock.patch.object(evaluation, "_clients", return_value=(object(), None)),
                mock.patch.object(
                    evaluation.batch_api,
                    "execute_live_request",
                    side_effect=ConnectionError("temporary network failure"),
                ) as execute,
                mock.patch.object(evaluation.time, "sleep"),
            ):
                interrupted = evaluation.submit_run(
                    run_dir, {"candidate-1": "local-key"}
                )

            live_candidate = interrupted["candidates"][0]
            self.assertEqual(interrupted["status"], "partially_submitted")
            self.assertEqual(live_candidate["status"], "running_live")
            self.assertEqual(execute.call_count, evaluation.LIVE_REQUEST_MAX_ATTEMPTS)
            self.assertIn("temporary network failure", live_candidate["live_retryable_error"])
            self.assertNotIn("provider_errors", live_candidate)

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
                ),
            ):
                completed = evaluation.submit_run(
                    run_dir, {"candidate-1": "local-key"}
                )

            self.assertEqual(completed["status"], "completed")
            self.assertNotIn("live_retryable_error", completed["candidates"][0])

    def test_missing_provider_requests_reduce_validity(self):
        processed, summary = evaluation._process_results(self.manifest, {}, [])
        self.assertFalse(processed)
        self.assertEqual(summary["received_requests"], 0)
        self.assertEqual(summary["missing_requests"], len(self.manifest["executions"]))
        self.assertEqual(summary["valid_segments"], 0)
        self.assertEqual(summary["validation_failures"], summary["total_segments"])
        self.assertEqual(summary["valid_rate"], 0.0)

    def test_received_but_wholly_invalid_output_marks_candidate_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "results").mkdir()
            first_execution = self.manifest["executions"][0]
            candidate = {
                "id": "candidate-invalid",
                "provider": "openai",
                "model": "gpt-5.6-terra",
                "status": "submitted",
            }

            summary = evaluation._complete_candidate(
                run_dir,
                self.manifest,
                candidate,
                {first_execution["id"]: {"text": "{}"}},
                [],
                {},
            )

            self.assertEqual(summary["received_requests"], 1)
            self.assertEqual(summary["valid_segments"], 0)
            self.assertEqual(candidate["status"], "failed")
            self.assertIn("No valid translated segments", candidate["failure_reason"])

    def test_completion_includes_legacy_prewarm_and_reports_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            (run_dir / "results").mkdir()
            first_execution = self.manifest["executions"][0]
            request = evaluation._request_lookup(self.manifest)[
                first_execution["logical_request_id"]
            ]
            candidate = {
                **dict(evaluation.DEFAULT_CANDIDATES[2]),
                "id": "candidate-claude-cost",
                "prewarm_usage": {
                    "input_tokens": 10,
                    "cache_read_input_tokens": 100,
                    "cache_creation_input_tokens": 100,
                },
            }
            batch_usage = {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 800,
                "cache_creation_input_tokens": 100,
            }
            raw_results = {
                first_execution["id"]: {
                    "text": json.dumps({
                        f"Line{index}": "English text"
                        for index in range(
                            1, int(request["schema_line_count"]) + 1
                        )
                    })
                }
            }

            summary = evaluation._complete_candidate(
                run_dir,
                self.manifest,
                candidate,
                raw_results,
                [],
                batch_usage,
            )

        expected_prewarm = evaluation._price_usage(
            {**candidate, "execution": "live"},
            candidate["prewarm_usage"],
            cache_ttl="1h",
        )
        self.assertEqual(summary["cache_read_rate"], 0.8)
        self.assertEqual(summary["usage"]["cache_read_input_tokens"], 900)
        self.assertAlmostEqual(summary["prewarm_cost_usd"], expected_prewarm)
        self.assertAlmostEqual(
            summary["actual_cost_usd"],
            summary["batch_cost_usd"] + expected_prewarm,
        )
        self.assertAlmostEqual(
            summary["no_cache_cost_usd"],
            evaluation._no_cache_cost(candidate, batch_usage),
        )

    def test_corrupt_repetition_is_invalid_and_remains_reviewable(self):
        manifest = {
            "executions": [{
                "id": "rep-1:logical-0001",
                "logical_request_id": "logical-0001",
                "repetition": 1,
            }],
            "logical_requests": [{
                "id": "logical-0001",
                "segment_ids": ["segment-1"],
                "sources": ["[ルシア]: …………………………………………………………。"],
                "protected_sources": ["[ルシア]: …………………………………………………………。"],
                "replacements": [{}],
                "logical_hash": "hash-1",
            }],
        }
        raw_results = {
            "rep-1:logical-0001": {
                "text": json.dumps({"Line1": "[Lucia]: " + "." * 50})
            }
        }

        processed, summary = evaluation._process_results(
            manifest, raw_results, []
        )
        line = processed["rep-1:logical-0001"]["lines"][0]

        self.assertFalse(line["valid"])
        self.assertIn("Excessive character repetition", line["issues"][0])
        self.assertIn("Excessive character repetition", line["warnings"][0])
        self.assertEqual(summary["valid_segments"], 0)
        self.assertEqual(summary["validation_failures"], 1)
        self.assertEqual(summary["warning_segments"], 1)

    def test_response_line_count_mismatch_invalidates_the_request_lines(self):
        manifest = {
            "executions": [{
                "id": "rep-1:logical-0001",
                "logical_request_id": "logical-0001",
                "repetition": 1,
            }],
            "logical_requests": [{
                "id": "logical-0001",
                "segment_ids": ["segment-1", "segment-2"],
                "sources": ["はい", "いいえ"],
                "protected_sources": ["はい", "いいえ"],
                "replacements": [{}, {}],
                "logical_hash": "hash-1",
            }],
        }
        raw_results = {
            "rep-1:logical-0001": {
                "text": json.dumps({"Line1": "Yes"})
            }
        }

        processed, summary = evaluation._process_results(
            manifest, raw_results, []
        )
        lines = processed["rep-1:logical-0001"]["lines"]

        self.assertTrue(all(not line["valid"] for line in lines))
        self.assertTrue(all("Line count differs" in line["issues"][0] for line in lines))
        self.assertEqual(summary["valid_segments"], 0)

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

    def test_load_run_rejects_changed_hashed_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            manifest = {
                "version": evaluation.EVALUATION_VERSION,
                "created_at": "2026-08-01T12:00:00+00:00",
                "segments": [],
            }
            manifest["manifest_sha256"] = evaluation._manifest_digest(manifest)
            state = {
                "run_id": "changed-manifest-test",
                "status": "prepared",
                "manifest_sha256": manifest["manifest_sha256"],
                "candidates": [],
            }
            manifest["segments"] = [{"id": "unexpected-change"}]
            evaluation._atomic_write_json(run_dir / "manifest.json", manifest)
            evaluation._atomic_write_json(run_dir / "state.json", state)

            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                evaluation.load_run(run_dir)

    def test_load_run_rejects_hashless_current_version_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", {
                "version": evaluation.EVALUATION_VERSION,
                "segments": [],
            })
            evaluation._atomic_write_json(run_dir / "state.json", {
                "version": evaluation.EVALUATION_VERSION,
                "run_id": "hashless-modern-run",
                "status": "prepared",
                "candidates": [],
            })

            with self.assertRaisesRegex(ValueError, "missing its saved manifest hash"):
                evaluation.load_run(run_dir)

    def test_load_run_keeps_pollable_state_when_another_candidate_failed(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            evaluation._atomic_write_json(run_dir / "manifest.json", {})
            evaluation._atomic_write_json(run_dir / "state.json", {
                "run_id": "mixed-state-test",
                "status": "submitted",
                "candidates": [
                    {
                        "id": "candidate-1",
                        "status": "completed",
                        "summary": {
                            "expected_requests": 2,
                            "received_requests": 0,
                            "provider_errors": [],
                        },
                    },
                    {"id": "candidate-2", "status": "submitted"},
                ],
            })

            state, _manifest = evaluation.load_run(run_dir)

            self.assertEqual(state["candidates"][0]["status"], "failed")
            self.assertEqual(state["status"], "submitted")

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
            "version": 1,
            "run_id": run_id,
            "created_at": "2026-08-01T12:00:00+00:00",
            "updated_at": "2026-08-01T12:30:00+00:00",
            "status": "completed",
            "api_key": "must-never-be-exported",
            "corpus_summary": {"selected_segments": 120},
            "candidates": [{
                "id": "candidate-1",
                "model": "local-model",
                "provider": "openai",
                "endpoint": "https://api.openai.com/v1",
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
        self.assertEqual(runs[0]["reviewed_samples"], 25)
        self.assertEqual(runs[0]["reviewed_lines"], 25)

    def test_history_keeps_terminal_failed_runs_visible(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            failed = self._make_run(project, "failed-run")
            state = evaluation._read_json(failed / "state.json")
            state["status"] = "failed"
            state["candidates"][0]["status"] = "failed"
            evaluation._atomic_write_json(failed / "state.json", state)

            evaluation.maintain_evaluation_storage(project)
            runs = evaluation.list_runs(project)

        self.assertEqual([run["run_id"] for run in runs], ["failed-run"])
        self.assertEqual(runs[0]["status"], "failed")

    def test_latest_run_does_not_prefer_an_old_active_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            active = self._make_run(project, "old-active-run")
            active_state = evaluation._read_json(active / "state.json")
            active_state["status"] = "partially_submitted"
            active_state["candidates"][0]["status"] = "submitted"
            evaluation._atomic_write_json(active / "state.json", active_state)
            evaluation.maintain_evaluation_storage(project)

            completed = self._make_run(project, "new-completed-run")
            completed_state = evaluation._read_json(completed / "state.json")
            completed_state["created_at"] = "2026-08-02T12:00:00+00:00"
            evaluation._atomic_write_json(completed / "state.json", completed_state)

            latest = evaluation.latest_run(project)

        self.assertEqual(latest, completed.resolve())

    def test_legacy_noncompleted_runs_move_out_of_completed_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            completed = self._make_run(project, "completed-run")
            active = self._make_run(project, "active-run")
            state = evaluation._read_json(active / "state.json")
            state["status"] = "submitted"
            state["candidates"][0]["status"] = "submitted"
            state["created_at"] = "2026-08-02T12:00:00+00:00"
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

    def test_prepared_runs_use_work_storage_and_survive_restart_history(self):
        manifest = {
            "corpus_summary": {"selected_segments": 60},
            "source_dir": "/game/data",
            "executions": [],
            "logical_requests": [],
        }
        manifest["manifest_sha256"] = evaluation._manifest_digest(manifest)
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
        second_manifest = {
            **manifest,
            "source_dir": "/game/second-data",
        }
        second_manifest["manifest_sha256"] = evaluation._manifest_digest(
            second_manifest
        )
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
            runs = evaluation.list_runs(project)
            self.assertEqual([run["run_dir"] for run in runs], [second.resolve()])
            self.assertEqual(runs[0]["status"], "prepared")
            self.assertEqual(evaluation.latest_run(project), second.resolve())

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

    def test_failed_completed_archive_remains_visible_and_retries(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            work = project / "log" / "evaluation_work" / "finished-run"
            evaluation._atomic_write_json(work / "manifest.json", {
                "source_dir": str(project / "game"),
                "corpus_summary": {"selected_segments": 0},
            })
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

            with mock.patch.object(
                Path, "rename", side_effect=PermissionError("directory locked")
            ):
                retained = evaluation._archive_completed_run(work, state)
                runs = evaluation.list_runs(project)

            saved, _manifest = evaluation.load_run(retained)
            self.assertEqual(retained, work)
            self.assertTrue(saved["archive_pending"])
            self.assertEqual(saved["storage"], "working")
            self.assertEqual([run["run_id"] for run in runs], ["finished-run"])

            maintenance = evaluation.maintain_evaluation_storage(project)
            archived = project / "log" / "evaluations" / "finished-run"
            saved, _manifest = evaluation.load_run(archived)
            self.assertFalse(work.exists())
            self.assertTrue(archived.is_dir())
            self.assertEqual(maintenance["moved"], [(work, archived)])
            self.assertNotIn("archive_pending", saved)
            self.assertNotIn("archive_error", saved)

    def test_storage_maintenance_does_not_archive_a_locked_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary)
            work = project / "log" / "evaluation_work" / "finished-run"
            evaluation._atomic_write_json(work / "manifest.json", {})
            evaluation._atomic_write_json(work / "state.json", {
                "run_id": "finished-run",
                "status": "completed",
                "managed_storage": True,
                "storage": "working",
                "candidates": [],
            })

            with evaluation._evaluation_submit_lock(work):
                maintenance = evaluation.maintain_evaluation_storage(project)

            self.assertTrue(work.is_dir())
            self.assertEqual(maintenance["moved"], [])

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

    def test_import_rejects_changed_hashed_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive_path = root / "changed.dazedeval"
            manifest = {
                "version": evaluation.EVALUATION_VERSION,
                "segments": [],
            }
            manifest["manifest_sha256"] = evaluation._manifest_digest(manifest)
            state = {
                "run_id": "changed-run",
                "status": "prepared",
                "manifest_sha256": manifest["manifest_sha256"],
                "candidates": [],
            }
            manifest["segments"] = [{"id": "changed-after-hashing"}]
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr(
                    "evaluation_export.json",
                    json.dumps({
                        "archive_version": evaluation.EVALUATION_ARCHIVE_VERSION
                    }),
                )
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            with self.assertRaisesRegex(ValueError, "integrity check failed"):
                evaluation.import_run_archive(root / "project", archive_path)

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
            with self.assertRaisesRegex(ValueError, "bind local API keys"):
                evaluation.resume_imported_run(imported)
            evaluation.bind_imported_credentials(imported, {
                "candidate-1": {
                    "key_name": "Local OpenAI",
                    "endpoint": "https://api.openai.com/v1",
                },
            })
            resumed = evaluation.resume_imported_run(imported)

            self.assertEqual(paused["status"], "imported_paused")
            self.assertEqual(resumed["status"], "submitted")

    def test_imported_prepared_run_requires_exact_local_credential_binding(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            archive_path = root / "prepared.dazedeval"
            manifest = {
                "version": evaluation.EVALUATION_VERSION,
                "segments": [],
                "logical_requests": [],
                "executions": [],
            }
            manifest["manifest_sha256"] = evaluation._manifest_digest(manifest)
            state = {
                "version": evaluation.EVALUATION_VERSION,
                "run_id": "prepared-import",
                "status": "prepared",
                "manifest_sha256": manifest["manifest_sha256"],
                "candidates": [{
                    "id": "candidate-1",
                    "label": "Imported model",
                    "model": "gpt-test",
                    "provider": "openai",
                    "endpoint": "https://attacker.example/v1",
                    "key_name": "OpenAI",
                    "keyless": False,
                    "execution": "batch",
                    "status": "prepared",
                }],
            }
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("evaluation_export.json", json.dumps({
                    "archive_version": evaluation.EVALUATION_ARCHIVE_VERSION,
                }))
                archive.writestr("manifest.json", json.dumps(manifest))
                archive.writestr("state.json", json.dumps(state))

            imported = evaluation.import_run_archive(project, archive_path)
            imported_state, _manifest = evaluation.load_run(imported)
            self.assertTrue(imported_state["credential_binding_required"])
            self.assertEqual(imported_state["candidates"][0]["key_name"], "")

            with self.assertRaisesRegex(ValueError, "exact API URL"):
                evaluation.bind_imported_credentials(imported, {
                    "candidate-1": {
                        "key_name": "OpenAI",
                        "endpoint": "https://api.openai.com/v1",
                    },
                })

            bound = evaluation.bind_imported_credentials(imported, {
                "candidate-1": {
                    "key_name": "Explicit attacker endpoint key",
                    "endpoint": "https://attacker.example/v1/",
                },
            })
            self.assertNotIn("credential_binding_required", bound)
            self.assertEqual(
                bound["candidates"][0]["key_name"],
                "Explicit attacker endpoint key",
            )


class SfxEvaluationContextTests(unittest.TestCase):
    def test_logical_request_freezes_sfx_separately_from_glossary(self):
        segments = [{
            "id": "segment-sfx",
            "scene_id": "scene-sfx",
            "stratum": "dialogue",
            "source": "胸がドキドキする",
            "review_sample_id": "sample-sfx",
            "review_history": [],
        }]
        requests = evaluation._build_logical_requests(
            segments, "Translate to English.", "", 30, True
        )
        self.assertEqual(requests[0]["glossary"], "")
        self.assertIn("ドキドキ", requests[0]["sfx_reference"])

        disabled = evaluation._build_logical_requests(
            segments, "Translate to English.", "", 30, False
        )
        self.assertEqual(disabled[0]["sfx_reference"], "")


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
                "id": "logical-0001", "segment_ids": ["segment-1"],
                "system": "Preserve the established character voice.",
                "glossary": "猫 (Cat) - approved character name",
                "sfx_reference": (
                    "Japanese SFX reference (contextual suggestions, not approved fixed translations).\n"
                    "- ドキドキ\n  - equivalents: heartbeat, heart pounding"
                ),
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

    @staticmethod
    def _fill_rankings(row: dict, overall: str, **quality: str) -> None:
        for metric in evaluation.REVIEW_QUALITY_METRICS:
            row[f"{metric}_ranking"] = quality.get(metric, overall)
        row["ranking"] = overall

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

    def test_export_rejects_result_file_shared_by_two_candidates(self):
        state_path = self.run_dir / "state.json"
        state = evaluation._read_json(state_path)
        state["candidates"][1]["result_file"] = state["candidates"][0]["result_file"]
        evaluation._atomic_write_json(state_path, state)

        with self.assertRaisesRegex(ValueError, "share the same result file"):
            evaluation.export_blind_review(self.run_dir)

    def test_export_rejects_result_owned_by_another_candidate(self):
        state = evaluation._read_json(self.run_dir / "state.json")
        result_path = self.run_dir / state["candidates"][0]["result_file"]
        result = evaluation._read_json(result_path)
        result["candidate_id"] = state["candidates"][1]["id"]
        evaluation._atomic_write_json(result_path, result)

        with self.assertRaisesRegex(ValueError, "wrong candidate id"):
            evaluation.export_blind_review(self.run_dir)

    def test_export_randomizes_labels_and_import_resolves_hidden_ranking(self):
        review_path = evaluation.export_blind_review(
            self.run_dir, self.run_dir / "external" / "review.csv"
        )
        self.assertTrue((self.run_dir / "blind_review.csv").is_file())
        self.assertEqual(
            (review_path.parent / evaluation.REVIEW_SYSTEM_PROMPT_FILENAME)
            .read_text(encoding="utf-8").strip(),
            "Preserve the established character voice.",
        )
        self.assertIn(
            "猫 (Cat)",
            (review_path.parent / evaluation.REVIEW_GLOSSARY_FILENAME)
            .read_text(encoding="utf-8"),
        )
        sfx_context = (
            review_path.parent / evaluation.REVIEW_SFX_REFERENCE_FILENAME
        ).read_text(encoding="utf-8")
        self.assertIn("ドキドキ", sfx_context)
        self.assertIn("contextual suggestions", sfx_context)
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
        self.assertTrue(all(
            f"{metric}_ranking" in rows[0]
            for metric in evaluation.REVIEW_QUALITY_METRICS
        ))
        self.assertNotIn("winner", rows[0])
        self._fill_rankings(
            rows[0], "B>A=C>D",
            meaning_accuracy="A>B>C>D",
            glossary_prompt="B>A>C>D",
            natural_contextual="C>B>A>D",
        )
        rows[0]["notes"] = "B best preserves the speaker's intent."
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
        self.assertEqual(
            review["quality_points"]["meaning_accuracy"]
            [hidden[self.review_id]["A"]],
            3,
        )
        self.assertEqual(
            review["quality_points"]["glossary_prompt"]
            [hidden[self.review_id]["B"]],
            3,
        )
        self.assertEqual(
            review["quality_points"]["natural_contextual"]
            [hidden[self.review_id]["C"]],
            3,
        )
        self.assertIn(
            ",B>A=C>D,",
            (self.run_dir / "blind_review.csv").read_text(encoding="utf-8-sig"),
        )
        comparison = evaluation.load_comparison_data(self.run_dir)
        sample = comparison["samples"][0]
        self.assertTrue(comparison["has_imported_review"])
        self.assertEqual(sample["sources"], ["猫だ。"])
        self.assertEqual(
            sample["review"]["overall"][0],
            [hidden[self.review_id]["B"]],
        )
        self.assertEqual(
            sample["review"]["metrics"]["meaning_accuracy"][0],
            [hidden[self.review_id]["A"]],
        )
        self.assertEqual(
            sample["review"]["notes"],
            "B best preserves the speaker's intent.",
        )

    def test_comparison_retains_invalid_and_missing_primary_outputs(self):
        state = evaluation._read_json(self.run_dir / "state.json")
        invalid_path = self.run_dir / state["candidates"][0]["result_file"]
        invalid = evaluation._read_json(invalid_path)
        line = invalid["executions"]["rep-1:logical-0001"]["lines"][0]
        line.update({
            "translation": "invalid-but-visible",
            "valid": False,
            "issues": ["Placeholder mismatch"],
        })
        evaluation._atomic_write_json(invalid_path, invalid)
        missing_path = self.run_dir / state["candidates"][1]["result_file"]
        missing = evaluation._read_json(missing_path)
        del missing["executions"]["rep-1:logical-0001"]
        evaluation._atomic_write_json(missing_path, missing)

        sample = evaluation.load_comparison_data(self.run_dir)["samples"][0]

        self.assertTrue(sample["has_problems"])
        self.assertEqual(
            sample["lines"][0]["outputs"]["candidate-1"]["translation"],
            "invalid-but-visible",
        )
        self.assertFalse(
            sample["lines"][0]["outputs"]["candidate-1"]["valid"]
        )
        self.assertTrue(
            sample["lines"][0]["outputs"]["candidate-2"]["missing"]
        )

    def test_import_rejects_blank_review_without_overwriting_existing_review(self):
        review_path = evaluation.export_blind_review(
            self.run_dir, self.run_dir / "external" / "review.csv"
        )
        canonical = self.run_dir / "blind_review.csv"
        canonical.write_text("existing reviewed content\n", encoding="utf-8")
        state_path = self.run_dir / "state.json"
        state = evaluation._read_json(state_path)
        existing_review = {
            "reviewed": 1,
            "points": {"candidate-1": 3},
        }
        state["human_review"] = existing_review
        evaluation._atomic_write_json(state_path, state)

        with self.assertRaisesRegex(ValueError, "no completed rankings"):
            evaluation.import_blind_review(self.run_dir, review_path)

        self.assertEqual(
            canonical.read_text(encoding="utf-8"), "existing reviewed content\n"
        )
        saved = evaluation._read_json(state_path)
        self.assertEqual(saved["human_review"], existing_review)

    def test_import_rejects_modified_source_or_candidate_cells(self):
        for field, replacement, message in (
            ("source", json.dumps(["rewritten source"]), "source text changed"),
            ("A", json.dumps(["rewritten candidate"]), "candidate text"),
            ("segment_ids", json.dumps(["other-segment"]), "segment IDs changed"),
        ):
            with self.subTest(field=field):
                review_path = evaluation.export_blind_review(self.run_dir)
                with open(
                    review_path, "r", encoding="utf-8-sig", newline=""
                ) as stream:
                    rows = list(csv.DictReader(stream))
                self._fill_rankings(rows[0], "A>B>C>D")
                rows[0][field] = replacement
                with open(
                    review_path, "w", encoding="utf-8-sig", newline=""
                ) as stream:
                    writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)

                with self.assertRaisesRegex(ValueError, message):
                    evaluation.import_blind_review(self.run_dir, review_path)

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

        self._fill_rankings(rows[0], "A>B>C>D")
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        review = evaluation.import_blind_review(self.run_dir, review_path)
        self.assertEqual(review["reviewed"], 1)
        self.assertEqual(review["reviewed_lines"], 2)
        self.assertEqual(sum(review["wins"].values()), 1)
        self.assertEqual(sum(review["points"].values()), 12)
        self.assertTrue(all(
            sum(scores.values()) == 12
            for scores in review["quality_points"].values()
        ))
        self.assertEqual(
            review["scoring"], "fixed-sum-borda-average-per-line-v2"
        )

    def test_import_rejects_changed_sample_line_count(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["line_count"] = "10"
        self._fill_rankings(rows[0], "A>B>C>D")
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
        self._fill_rankings(rows[0], "A=B>C>D")
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
        self._fill_rankings(rows[0], "A>B>B>D")
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(ValueError, "use every label exactly once"):
            evaluation.import_blind_review(self.run_dir, review_path)

    def test_import_requires_every_quality_ranking(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self._fill_rankings(rows[0], "A>B>C>D")
        rows[0]["glossary_prompt_ranking"] = ""
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaisesRegex(ValueError, "Missing glossary_prompt_ranking"):
            evaluation.import_blind_review(self.run_dir, review_path)

    def test_import_accepts_legacy_winner_csv(self):
        review_path = evaluation.export_blind_review(self.run_dir)
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        quality_fields = {
            f"{metric}_ranking" for metric in evaluation.REVIEW_QUALITY_METRICS
        }
        legacy_fields = [
            "winner" if field == "ranking" else field
            for field in rows[0].keys() if field not in quality_fields
        ]
        legacy_row = {
            ("winner" if field == "ranking" else field): value
            for field, value in rows[0].items() if field not in quality_fields
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
        manifest["logical_requests"].append({
            "id": "logical-0002",
            "segment_ids": ["segment-2"],
        })
        manifest["executions"].append({
            "id": "rep-1:logical-0002",
            "logical_request_id": "logical-0002",
            "repetition": 1,
        })
        evaluation._atomic_write_json(manifest_path, manifest)
        state = json.loads((self.run_dir / "state.json").read_text(encoding="utf-8"))
        for index, candidate in enumerate(state["candidates"]):
            result_path = self.run_dir / candidate["result_file"]
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["executions"]["rep-1:logical-0002"] = {
                "logical_request_id": "logical-0002",
                "repetition": 1,
                "lines": [{
                    "segment_id": "segment-2",
                    "translation": f"translation-dog-{index}",
                    "valid": index != 0,
                }],
            }
            evaluation._atomic_write_json(result_path, result)

        coverage = evaluation.blind_review_coverage(self.run_dir)
        self.assertEqual(coverage["total_segments"], 2)
        self.assertEqual(coverage["eligible_segments"], 1)
        self.assertEqual(coverage["excluded_segments"], 1)
        self.assertEqual(coverage["total_samples"], 2)
        self.assertEqual(coverage["eligible_samples"], 1)

    def test_failed_candidate_can_be_omitted_from_export_and_import(self):
        state_path = self.run_dir / "state.json"
        state = evaluation._read_json(state_path)
        failed = state["candidates"][-1]
        failed["status"] = "failed"
        failed["result_file"] = ""
        state["status"] = "failed"
        evaluation._atomic_write_json(state_path, state)

        choices = evaluation.blind_review_candidates(self.run_dir)
        self.assertFalse(choices[-1]["available"])
        self.assertEqual(choices[-1]["status"], "failed")
        selected_ids = [candidate["id"] for candidate in state["candidates"][:3]]

        coverage = evaluation.blind_review_coverage(
            self.run_dir, selected_ids
        )
        self.assertEqual(coverage["candidate_ids"], selected_ids)
        self.assertEqual(coverage["eligible_samples"], 1)

        review_path = evaluation.export_blind_review(
            self.run_dir, candidate_ids=selected_ids
        )
        with open(review_path, "r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertIn("C", rows[0])
        self.assertNotIn("D", rows[0])
        self._fill_rankings(rows[0], "A>B>C")
        with open(review_path, "w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        review = evaluation.import_blind_review(self.run_dir, review_path)
        self.assertEqual(review["reviewed_candidate_ids"], selected_ids)
        self.assertEqual(review["points"][failed["id"]], 0)
        self.assertEqual(
            sum(review["points"][candidate_id] for candidate_id in selected_ids),
            3,
        )

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
