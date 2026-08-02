from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from gui.config_tab import API_URL_PRESETS, ModelFetchThread
from gui.evaluation_tab import EvaluationTab
from util import evaluation


class EvaluationTabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        patches = (
            mock.patch("gui.evaluation_tab.evaluation.latest_run", return_value=None),
            mock.patch("gui.evaluation_tab.evaluation.list_runs", return_value=[]),
            mock.patch("gui.evaluation_tab.api_key_vault.ensure_vault"),
            mock.patch(
                "gui.evaluation_tab.api_key_vault.list_names",
                return_value=["OpenAI", "Gemini", "Claude", "DeepSeek"],
            ),
            mock.patch("gui.evaluation_tab.api_key_vault.get_active_name", return_value="OpenAI"),
            mock.patch(
                "gui.evaluation_tab.api_key_vault.get_endpoint",
                side_effect=lambda name: {
                    "OpenAI": "https://api.openai.com/v1",
                    "Gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "Claude": "https://api.anthropic.com/v1",
                    "DeepSeek": "https://api.deepseek.com/v1/",
                }.get(name, ""),
            ),
            mock.patch(
                "gui.evaluation_tab.api_key_vault.is_keyless", return_value=False
            ),
            mock.patch.dict(os.environ, {"model": "configured-model"}),
            mock.patch.object(
                EvaluationTab, "_schedule_candidate_model_scan", autospec=True
            ),
        )
        self.patchers = list(patches)
        for patcher in self.patchers:
            patcher.start()
        self.tab = EvaluationTab()
        self.tab.show()
        self.app.processEvents()

    def tearDown(self):
        self.tab.close()
        self.app.processEvents()
        for patcher in reversed(self.patchers):
            patcher.stop()

    def test_defaults_expose_model_dropdowns_and_simple_safe_actions(self):
        self.assertEqual(
            self.tab.test_size_combo.currentData(), (360, 10, 12, 3)
        )
        self.assertEqual(self.tab.budget_spin.value(), 10.0)
        self.assertEqual(self.tab.custom_target_spin.value(), 360)
        self.assertEqual(self.tab.custom_sample_size_spin.value(), 10)
        self.assertEqual(
            self.tab.custom_sample_size_spin.maximum(), 2_147_483_647
        )
        self.assertEqual(self.tab.custom_repeated_samples_spin.value(), 12)
        self.assertEqual(self.tab.custom_repetitions_spin.value(), 3)
        self.assertFalse(self.tab.custom_target_spin.isEnabled())
        size_widgets = {
            "Total test lines": self.tab.custom_target_spin,
            "Lines per sample": self.tab.custom_sample_size_spin,
            "Repeated samples": self.tab.custom_repeated_samples_spin,
            "Runs per repeated sample": self.tab.custom_repetitions_spin,
        }
        for name, widget in size_widgets.items():
            tooltip = self.tab.BENCHMARK_SIZE_TOOLTIPS[name]
            label = self.tab.benchmark_size_labels[name]
            self.assertEqual(label.text(), f"{name} ⓘ")
            self.assertEqual(label.toolTip(), tooltip)
            self.assertEqual(widget.toolTip(), tooltip)
        self.assertEqual(
            [row["model"].currentText() for row in self.tab._candidate_widgets],
            ["configured-model"],
        )
        self.assertEqual(
            [row["endpoint"].text() for row in self.tab._candidate_widgets],
            ["https://api.openai.com/v1"],
        )
        self.assertTrue(
            all(row["model"].isEditable() for row in self.tab._candidate_widgets)
        )

    def test_custom_template_enables_sample_and_repeat_controls(self):
        self.tab.test_size_combo.setCurrentIndex(
            self.tab.test_size_combo.count() - 1
        )

        for widget in (
            self.tab.custom_target_spin,
            self.tab.custom_sample_size_spin,
            self.tab.custom_repeated_samples_spin,
            self.tab.custom_repetitions_spin,
        ):
            self.assertTrue(widget.isEnabled())

        self.tab.custom_target_spin.setValue(240)
        self.tab.custom_sample_size_spin.setValue(8)
        self.tab.custom_repeated_samples_spin.setValue(15)
        self.tab.custom_repetitions_spin.setValue(5)
        self.assertEqual(self.tab.custom_target_spin.value(), 240)
        self.assertEqual(self.tab.custom_sample_size_spin.value(), 8)
        self.assertEqual(self.tab.custom_repeated_samples_spin.value(), 15)
        self.assertEqual(self.tab.custom_repetitions_spin.value(), 5)
        self.assertEqual(
            [row["execution"].currentData() for row in self.tab._candidate_widgets],
            ["batch"],
        )
        self.assertEqual(self.tab._candidate_widgets[0]["key"].currentText(), "OpenAI")
        self.assertTrue(all(row["scan"].isEnabled() for row in self.tab._candidate_widgets))
        self.assertTrue(self.tab.prepare_btn.isEnabled())
        self.assertFalse(self.tab.submit_btn.isEnabled())
        self.assertFalse(self.tab.export_btn.isEnabled())
        self.assertFalse(self.tab.copy_review_skill_btn.isEnabled())
        self.assertFalse(self.tab.history_combo.isEnabled())
        self.assertTrue(self.tab.import_evaluation_btn.isEnabled())
        valid_header = self.tab.table.horizontalHeaderItem(
            self.tab.COLUMNS.index("Valid")
        )
        consistency_header = self.tab.table.horizontalHeaderItem(
            self.tab.COLUMNS.index("Consistency")
        )
        self.assertIn("does not measure translation quality", valid_header.toolTip())
        self.assertIn("more repeatable, not better", consistency_header.toolTip())
        self.assertTrue(all(
            max(map(len, tooltip.splitlines())) <= 62
            for tooltip in self.tab.COLUMN_TOOLTIPS.values()
        ))
        self.assertEqual(self.tab.COLUMNS[-1], "Best overall")
        for name, label in self.tab.COLUMN_LABELS.items():
            header = self.tab.table.horizontalHeaderItem(
                self.tab.COLUMNS.index(name)
            )
            self.assertEqual(header.text(), f"{label} ⓘ")
        self.assertGreaterEqual(
            self.tab.table.horizontalHeader().minimumHeight(),
            self.tab.table.horizontalHeader().fontMetrics().lineSpacing() * 2 + 12,
        )
        self.assertTrue(all(
            self.tab.table.horizontalHeaderItem(self.tab.COLUMNS.index(name))
            .toolTip()
            for name in (
                "Meaning Accuracy", "Glossary & Prompt",
                "Natural & Contextual", "Best overall",
            )
        ))
        self.assertEqual(
            self.tab.source_edit.placeholderText(),
            "Select an RPG Maker MV/MZ game folder…",
        )
        self.assertIn("Game data found:", self.tab.source_resolution_label.text())

    def test_content_presets_and_custom_map_selection_are_explicit(self):
        inventory = {
            "eligible_segments": 360,
            "eligible_scenes": 100,
            "eligible_files": 4,
            "source_counts": {},
            "map_files": {"Map001.json": 70, "Map002.json": 90},
            "code_heavy_source_counts": {
                source_id: 0 for source_id in evaluation.ALL_CONTENT_SOURCES
            },
            "map_file_code_heavy_counts": {
                "Map001.json": 5,
                "Map002.json": 7,
            },
            "code_heavy_segments": 12,
        }
        inventory["source_counts"] = {
            source_id: 0 for source_id in evaluation.ALL_CONTENT_SOURCES
        }
        inventory["source_counts"].update({
            "map_events": 160,
            "common_events": 40,
            "skills": 80,
            "items": 80,
        })
        inventory["code_heavy_source_counts"].update({"map_events": 12})
        self.tab._content_inventory = inventory
        self.tab._populate_content_tree(inventory)

        self.tab.content_preset_combo.setCurrentIndex(
            self.tab.content_preset_combo.findData("database")
        )
        database = self.tab._content_selection()
        self.assertEqual(database["preset"], "database")
        self.assertEqual(set(database["sources"]), set(evaluation.DATABASE_CONTENT_SOURCES))
        self.assertFalse(self.tab.content_tree.isEnabled())

        self.tab.content_preset_combo.setCurrentIndex(
            self.tab.content_preset_combo.findData("custom")
        )
        for item in self.tab._content_source_items.values():
            item.setCheckState(0, Qt.Unchecked)
        self.tab._content_source_items["map_events"].setCheckState(0, Qt.Checked)
        self.tab._content_map_items["Map001.json"].setCheckState(0, Qt.Unchecked)
        self.tab._content_map_items["Map002.json"].setCheckState(0, Qt.Checked)
        self.tab.code_heavy_item.setCheckState(0, Qt.Unchecked)

        custom = self.tab._content_selection()
        self.assertEqual(custom["sources"], ["map_events"])
        self.assertEqual(custom["map_files"], ["Map002.json"])
        self.assertFalse(custom["include_code_heavy"])
        self.assertEqual(self.tab._selected_content_count(custom), 83)
        self.assertTrue(self.tab.content_tree.isEnabled())

    def test_game_folder_selection_shows_resolved_json_location(self):
        with tempfile.TemporaryDirectory() as temporary:
            game = Path(temporary)
            data = game / "www" / "data"
            data.mkdir(parents=True)
            (data / "Map001.json").write_text("{}", encoding="utf-8")

            self.tab.source_edit.setText(str(game))
            self.tab._update_source_resolution()

            self.assertIn("Game data found:", self.tab.source_resolution_label.text())
            self.assertIn(str(data.resolve()), self.tab.source_resolution_label.text())
            self.assertIn(
                f"glossary: {game.resolve() / 'glossary.txt'}",
                self.tab.source_resolution_label.text(),
            )

    def test_invalid_game_folder_explains_expected_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.tab.source_edit.setText(temporary)
            self.tab._update_source_resolution()

            self.assertIn("data/ or www/data/", self.tab.source_resolution_label.text())

    def test_copy_review_skill_includes_csv_path_and_bias_warning(self):
        with tempfile.TemporaryDirectory() as temporary:
            review_path = Path(temporary) / "blind_review.csv"
            review_path.write_text(
                "segment_id,scene_id,stratum,source,A,B,ranking,notes\n",
                encoding="utf-8-sig",
            )
            self.tab.current_run_dir = Path(temporary)
            self.tab._last_review_path = review_path
            self.tab._update_actions({"status": "completed"})
            self.assertTrue(self.tab.copy_review_skill_btn.isEnabled())
            QApplication.clipboard().clear()
            system_path = Path(temporary) / "review_system_prompt.md"
            glossary_path = Path(temporary) / "review_glossary.txt"
            sfx_path = Path(temporary) / "review_sfx_reference.txt"
            with (
                mock.patch("gui.evaluation_tab.QMessageBox.warning") as warning,
                mock.patch(
                    "gui.evaluation_tab.evaluation.export_blind_review_context",
                    return_value=(system_path, glossary_path, sfx_path),
                ),
            ):
                self.tab.copy_review_skill()

            prompt = QApplication.clipboard().text()
            self.assertIn(str(review_path.resolve()), prompt)
            self.assertNotIn("{{BLIND_REVIEW_CSV}}", prompt)
            self.assertIn(str(system_path), prompt)
            self.assertIn(str(glossary_path), prompt)
            self.assertIn(str(sfx_path), prompt)
            self.assertNotIn("{{REVIEW_SYSTEM_PROMPT}}", prompt)
            self.assertNotIn("{{REVIEW_GLOSSARY}}", prompt)
            self.assertNotIn("{{REVIEW_SFX_REFERENCE}}", prompt)
            self.assertIn("authoritative review criteria", prompt)
            self.assertIn("AI judging is not objective", prompt)
            self.assertIn("blind_key.json", prompt)
            self.assertIn("biased", warning.call_args.args[2])

    def test_export_review_uses_selected_candidate_subset(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            output = run_dir / "selected-review.csv"
            selected_ids = ["candidate-1", "candidate-3"]
            coverage = {
                "total_segments": 10,
                "eligible_segments": 8,
                "excluded_segments": 2,
                "total_samples": 5,
                "eligible_samples": 4,
                "excluded_samples": 1,
                "candidate_ids": selected_ids,
            }
            self.tab.current_run_dir = run_dir
            with (
                mock.patch.object(
                    self.tab, "_choose_review_candidates",
                    return_value=selected_ids,
                ),
                mock.patch(
                    "gui.evaluation_tab.evaluation.blind_review_coverage",
                    return_value=coverage,
                ) as review_coverage,
                mock.patch(
                    "gui.evaluation_tab.QFileDialog.getSaveFileName",
                    return_value=(str(output), "CSV files (*.csv)"),
                ),
                mock.patch(
                    "gui.evaluation_tab.evaluation.export_blind_review",
                    return_value=output,
                ) as export_review,
                mock.patch("gui.evaluation_tab.QMessageBox.information"),
                mock.patch.object(self.tab, "_update_actions"),
            ):
                self.tab.export_review()

            review_coverage.assert_called_once_with(run_dir, selected_ids)
            export_review.assert_called_once_with(
                run_dir, str(output), selected_ids
            )
            self.assertEqual(self.tab._last_review_path, output)

    def test_history_lists_and_selects_previous_evaluations(self):
        older = Path("/tmp/evaluation-older")
        newer = Path("/tmp/evaluation-newer")
        runs = [
            {
                "run_dir": newer,
                "run_id": "newer",
                "created_at": "2026-08-02T12:00:00+00:00",
                "status": "completed",
                "models": ["model-a", "model-b"],
                "modes": ["batch", "live"],
                "selected_segments": 360,
                "reviewed": 100,
                "reviewed_samples": 100,
                "reviewed_lines": 357,
                "review_complete": True,
            },
            {
                "run_dir": older,
                "run_id": "older",
                "created_at": "2026-08-01T12:00:00+00:00",
                "status": "completed",
                "models": ["model-c", "model-d"],
                "modes": ["batch", "batch"],
                "selected_segments": 120,
                "reviewed": 0,
            },
        ]
        with mock.patch(
            "gui.evaluation_tab.evaluation.list_runs", return_value=runs
        ):
            self.tab._refresh_history(older)

        self.assertEqual(self.tab.history_combo.count(), 2)
        self.assertIn("model-a, model-b", self.tab.history_combo.itemText(0))
        self.assertIn("Batch, Live", self.tab.history_combo.itemText(0))
        self.assertIn(
            "Review complete (357 eligible lines)",
            self.tab.history_combo.itemText(0),
        )
        self.assertEqual(self.tab._selected_history_run(), older)
        self.assertTrue(self.tab.history_combo.isEnabled())
        self.assertTrue(self.tab.export_evaluation_btn.isEnabled())
        with mock.patch.object(self.tab, "_open_run") as open_run:
            self.tab.history_combo.activated.emit(self.tab.history_combo.currentIndex())
        open_run.assert_called_once_with(older)

    def test_history_selects_current_prepared_run_without_saving_it(self):
        prepared = Path("/tmp/current-prepared-evaluation")
        saved = Path("/tmp/saved-completed-evaluation")
        saved_run = {
            "run_dir": saved,
            "run_id": "saved",
            "created_at": "2026-08-01T12:00:00+00:00",
            "status": "completed",
            "models": ["saved-model"],
            "modes": ["batch"],
            "selected_segments": 360,
            "reviewed": 0,
        }
        prepared_run = {
            "run_dir": prepared,
            "run_id": "prepared",
            "created_at": "2026-08-02T12:00:00+00:00",
            "status": "prepared",
            "models": ["current-model"],
            "modes": ["batch"],
            "selected_segments": 120,
            "reviewed": 0,
        }
        self.tab.current_run_dir = prepared
        with (
            mock.patch(
                "gui.evaluation_tab.evaluation.list_runs",
                return_value=[saved_run],
            ),
            mock.patch(
                "gui.evaluation_tab.evaluation.run_history_entry",
                return_value=prepared_run,
            ),
        ):
            self.tab._refresh_history(prepared)

        self.assertEqual(self.tab._selected_history_run(), prepared)
        self.assertIn("current-model", self.tab.history_combo.currentText())
        self.assertIn("Prepared", self.tab.history_combo.currentText())
        self.assertFalse(self.tab.export_evaluation_btn.isEnabled())

    def test_key_suggestions_are_provider_specific(self):
        self.tab._add_candidate_row("gemini", "gemini-3.6-flash")
        self.tab._add_candidate_row("anthropic", "claude-sonnet-5")
        self.assertEqual(
            self.tab._candidate_widgets[0]["key"].currentText(), "OpenAI"
        )
        self.assertEqual(
            self.tab._candidate_widgets[1]["key"].currentText(), "Gemini"
        )
        self.assertEqual(
            self.tab._candidate_widgets[2]["key"].currentText(), "Claude"
        )

    def test_provider_presets_match_configuration(self):
        self.assertEqual(
            [
                action.text()
                for action in self.tab._candidate_widgets[0]["preset"].menu().actions()
            ],
            [name for name, _url in API_URL_PRESETS],
        )

        row = self.tab._candidate_widgets[0]
        deepseek_action = next(
            action for action in row["preset"].menu().actions()
            if action.text() == "DeepSeek"
        )
        deepseek_action.trigger()
        self.assertEqual(row["endpoint"].text(), "https://api.deepseek.com/v1/")
        self.assertEqual(row["key"].currentText(), "DeepSeek")

    def test_models_can_be_added_removed_and_reassigned(self):
        self.tab._add_candidate_row("gemini", "gemini-3.6-flash")
        self.assertEqual(len(self.tab._candidate_widgets), 2)
        added = self.tab._candidate_widgets[-1]
        self.assertEqual(
            added["endpoint"].text(),
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        )
        self.assertEqual(self.tab._provider_for_endpoint(added["endpoint"].text()), "gemini")
        self.assertEqual(added["model"].currentText(), "gemini-3.6-flash")
        self.tab._remove_candidate_row(added)
        self.assertEqual(len(self.tab._candidate_widgets), 1)

    def test_saved_run_restores_benchmark_setup(self):
        state = {
            "budget_usd_per_model": 7.5,
            "candidates": [
                {
                    "endpoint": "https://api.openai.com/v1",
                    "key_name": "OpenAI",
                    "model": "gpt-restored",
                    "execution": "batch",
                },
                {
                    "endpoint": "https://api.anthropic.com",
                    "key_name": "Claude",
                    "model": "claude-restored",
                    "execution": "live",
                },
            ],
        }
        manifest = {
            "requested_segments": 600,
            "sample_size": 10,
            "requested_stability_samples": 18,
            "repetitions": 3,
        }

        self.tab._restore_benchmark_setup(state, manifest)

        self.assertEqual(
            self.tab.test_size_combo.currentData(), (600, 10, 18, 3)
        )
        self.assertEqual(self.tab.budget_spin.value(), 7.5)
        self.assertEqual(
            [row["model"].currentText() for row in self.tab._candidate_widgets],
            ["gpt-restored", "claude-restored"],
        )
        self.assertEqual(
            [row["key"].currentText() for row in self.tab._candidate_widgets],
            ["OpenAI", "Claude"],
        )
        self.assertEqual(
            [row["execution"].currentData() for row in self.tab._candidate_widgets],
            ["batch", "live"],
        )

    def test_saved_run_restores_custom_content_filter(self):
        state = {"budget_usd_per_model": 10, "candidates": []}
        manifest = {
            "requested_segments": 360,
            "sample_size": 10,
            "requested_stability_samples": 12,
            "repetitions": 3,
            "content_selection": {
                "preset": "custom",
                "sources": ["skills", "items"],
                "map_files": [],
                "include_code_heavy": False,
            },
        }

        self.tab._restore_benchmark_setup(state, manifest)

        self.assertEqual(self.tab.content_preset_combo.currentData(), "custom")
        self.assertEqual(
            self.tab._content_selection(),
            evaluation.normalize_content_selection(manifest["content_selection"]),
        )
        self.assertTrue(self.tab.content_tree.isEnabled())

    def test_imported_run_does_not_preselect_a_local_api_key(self):
        state = {
            "credential_binding_required": True,
            "budget_usd_per_model": 10,
            "candidates": [{
                "id": "candidate-1",
                "endpoint": "https://api.openai.com/v1",
                "key_name": "",
                "model": "imported-model",
                "execution": "batch",
                "status": "prepared",
            }],
        }
        manifest = {
            "requested_segments": 360,
            "sample_size": 10,
            "requested_stability_samples": 12,
            "repetitions": 3,
        }

        self.tab._restore_benchmark_setup(state, manifest)

        self.assertEqual(self.tab._candidate_widgets[0]["key"].currentIndex(), -1)
        self.assertEqual(self.tab._candidate_widgets[0]["key"].currentText(), "")

    def test_custom_url_uses_openai_compatible_protocol(self):
        row = self.tab._candidate_widgets[0]
        row["endpoint"].setText("http://127.0.0.1:8000/v1")
        row["model"].clear()
        row["model"].addItem("local-translation-model")
        with mock.patch(
            "gui.evaluation_tab.api_key_vault.is_keyless", return_value=True
        ):
            candidate = self.tab._candidate_config()[0]
        self.assertEqual(candidate["provider"], "openai")
        self.assertEqual(candidate["endpoint"], "http://127.0.0.1:8000/v1")
        self.assertTrue(candidate["keyless"])

    def test_provider_and_key_changes_schedule_automatic_model_scan(self):
        scheduler = EvaluationTab._schedule_candidate_model_scan
        scheduler.reset_mock()
        row = self.tab._candidate_widgets[0]
        self.tab._apply_endpoint_preset(
            row, "https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        self.assertTrue(any(row in call.args for call in scheduler.call_args_list))

        scheduler.reset_mock()
        row["key"].setCurrentText("Claude")
        self.app.processEvents()
        self.assertTrue(any(row in call.args for call in scheduler.call_args_list))

    def test_scanned_models_preserve_manual_selection(self):
        row = self.tab._candidate_widgets[0]
        self.tab._apply_candidate_models(row, ["gpt-listed-b", "gpt-listed-a"])
        self.assertEqual(row["model"].currentText(), "configured-model")
        self.assertEqual(
            [row["model"].itemText(index) for index in range(row["model"].count())],
            ["configured-model", "gpt-listed-a", "gpt-listed-b"],
        )

    def test_scanned_models_keep_selection_when_provider_still_offers_it(self):
        row = self.tab._candidate_widgets[0]
        self.tab._apply_candidate_models(
            row, ["gpt-listed-b", "configured-model", "gpt-listed-a"]
        )
        self.assertEqual(row["model"].currentText(), "configured-model")

    def test_worker_completion_restores_actions_after_thread_stops(self):
        completed = []
        self.tab._run_task(lambda _log: "done", completed.append)
        worker = self.tab._worker
        self.assertIsNotNone(worker)
        self.assertFalse(self.tab.prepare_btn.isEnabled())

        self.assertTrue(worker.wait(2_000))
        self.app.processEvents()

        self.assertEqual(completed, ["done"])
        self.assertIsNone(self.tab._worker)
        self.assertTrue(self.tab.prepare_btn.isEnabled())

    def test_cancel_button_requests_live_worker_interruption(self):
        worker = mock.Mock()
        worker.isRunning.return_value = True
        self.tab._worker = worker
        self.tab._worker_cancelable = True
        self.tab._set_busy(True)

        self.assertTrue(self.tab.cancel_btn.isEnabled())
        self.tab.cancel_evaluation()

        worker.requestInterruption.assert_called_once_with()
        self.assertFalse(self.tab.cancel_btn.isEnabled())
        self.tab._worker = None
        self.tab._worker_cancelable = False

    def test_paused_live_run_enables_resume_without_batch_polling(self):
        self.tab._display_state({
            "status": "partially_submitted",
            "candidates": [{
                "id": "candidate-1",
                "model": "local-model",
                "provider": "openai",
                "endpoint": "http://127.0.0.1:8000/v1",
                "execution": "live",
                "status": "running_live",
                "estimate": {"cost_usd": 0.0},
            }],
        })

        self.assertTrue(self.tab.submit_btn.isEnabled())
        self.assertFalse(self.tab.refresh_btn.isEnabled())
        self.assertFalse(self.tab._poll_timer.isActive())

    def test_long_evaluation_model_dropdown_is_bounded_and_scrollable(self):
        row = self.tab._candidate_widgets[0]
        combo = row["model"]
        self.tab._apply_candidate_models(
            row, [f"provider-model-{index:03d}" for index in range(100)]
        )
        self.tab.resize(1280, 720)
        self.app.processEvents()
        combo.showPopup()
        self.app.processEvents()

        view = combo.view()
        screen = self.app.screenAt(combo.mapToGlobal(combo.rect().center()))
        self.assertLessEqual(view.height(), combo._popup_height_limit())
        self.assertLessEqual(view.window().height(), view.height() + 8)
        self.assertGreater(view.verticalScrollBar().maximum(), 0)
        self.assertLessEqual(
            view.window().frameGeometry().bottom(), screen.availableGeometry().bottom()
        )
        combo.hidePopup()

    def test_model_scan_uses_selected_provider_key_and_endpoint(self):
        self.tab._add_candidate_row("gemini", "gemini-3.6-flash")
        row = self.tab._candidate_widgets[1]
        fake_worker = mock.Mock()
        fake_worker.isRunning.return_value = False
        with (
            mock.patch(
                "gui.evaluation_tab.api_key_vault.get_entry",
                return_value={
                    "secret": "hidden-secret",
                    "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "keyless": False,
                },
            ),
            mock.patch(
                "gui.evaluation_tab.ModelFetchThread", return_value=fake_worker
            ) as worker_class,
        ):
            self.tab._fetch_candidate_models(row)

        worker_class.assert_called_once_with(
            "hidden-secret",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
            parent=self.tab,
            provider="gemini",
        )
        fake_worker.start.assert_called_once_with()

    def test_explicit_provider_scan_does_not_probe_other_providers(self):
        worker = ModelFetchThread("hidden-secret", "", provider="anthropic")
        with (
            mock.patch.object(worker, "_fetch_openai") as openai_fetch,
            mock.patch.object(
                worker, "_fetch_anthropic", return_value=["claude-listed"]
            ) as anthropic_fetch,
            mock.patch.object(worker, "_fetch_gemini") as gemini_fetch,
        ):
            worker.run()

        anthropic_fetch.assert_called_once_with()
        openai_fetch.assert_not_called()
        gemini_fetch.assert_not_called()

    def test_terminal_provider_status_displays_as_completed_after_processing(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.tab.current_run_dir = Path(temporary)
            self.tab._display_state({
                "status": "completed",
                "candidates": [{
                    "id": "candidate-1",
                    "model": "claude-opus-5",
                    "provider": "anthropic",
                    "endpoint": "https://api.anthropic.com",
                    "status": "completed",
                    "api_status": "ended",
                    "estimate": {"cost_usd": 1.0},
                    "summary": {},
                }],
            })
            self.assertEqual(self.tab.table.item(0, 3).text(), "Completed")
            self.assertTrue(self.tab.import_btn.isEnabled())

    def test_blind_quality_metrics_display_before_best_overall(self):
        self.tab._display_state({
            "status": "completed",
            "human_review": {
                "points": {"candidate-1": 210},
                "quality_points": {
                    "meaning_accuracy": {"candidate-1": 230},
                    "glossary_prompt": {"candidate-1": 220},
                    "natural_contextual": {"candidate-1": 200},
                },
            },
            "candidates": [{
                "id": "candidate-1",
                "model": "reviewed-model",
                "provider": "openai",
                "status": "completed",
                "estimate": {"cost_usd": 1.0},
                "summary": {},
            }],
        })

        self.assertEqual(
            self.tab.table.item(
                0, self.tab.COLUMNS.index("Meaning Accuracy")
            ).text(),
            "230",
        )
        self.assertEqual(
            self.tab.table.item(
                0, self.tab.COLUMNS.index("Glossary & Prompt")
            ).text(),
            "220",
        )
        self.assertEqual(
            self.tab.table.item(
                0, self.tab.COLUMNS.index("Natural & Contextual")
            ).text(),
            "200",
        )
        self.assertEqual(
            self.tab.table.item(0, self.tab.COLUMNS.index("Best overall")).text(),
            "210",
        )

    def test_model_excluded_from_blind_review_does_not_show_zero_wins(self):
        candidates = [
            {
                "id": candidate_id,
                "model": model,
                "provider": "openai",
                "status": "completed",
                "estimate": {"cost_usd": 1.0},
                "summary": {},
            }
            for candidate_id, model in (
                ("candidate-1", "terra"),
                ("candidate-2", "luna"),
                ("candidate-3", "sol"),
            )
        ]
        self.tab._display_state({
            "status": "completed",
            "human_review": {
                "reviewed_candidate_ids": ["candidate-1", "candidate-3"],
                "points": {
                    "candidate-1": 0,
                    "candidate-2": 0,
                    "candidate-3": 0,
                },
                "wins": {
                    "candidate-1": 0,
                    "candidate-2": 0,
                    "candidate-3": 0,
                },
            },
            "candidates": candidates,
        })

        best_overall = self.tab.COLUMNS.index("Best overall")
        self.assertEqual(self.tab.table.item(0, best_overall).text(), "0")
        self.assertEqual(self.tab.table.item(1, best_overall).text(), "—")
        self.assertEqual(self.tab.table.item(2, best_overall).text(), "0")

    def test_failed_evaluation_displays_failure_and_keeps_recovery_actions(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.tab.current_run_dir = Path(temporary)
            self.tab._display_state({
                "status": "failed",
                "candidates": [{
                    "id": "candidate-1",
                    "model": "broken-model",
                    "provider": "gemini",
                    "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/",
                    "status": "failed",
                    "api_status": "completed",
                    "estimate": {"cost_usd": 1.0},
                    "summary": {
                        "total_segments": 10,
                        "valid_rate": 0.0,
                    },
                }],
            })
            self.assertEqual(self.tab.table.item(0, 3).text(), "Failed")
            self.assertTrue(self.tab.export_btn.isEnabled())
            self.assertTrue(self.tab.import_btn.isEnabled())

    def test_import_explains_that_blind_export_is_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            self.tab.current_run_dir = Path(temporary)
            with (
                mock.patch("gui.evaluation_tab.QMessageBox.information") as info,
                mock.patch("gui.evaluation_tab.QFileDialog.getOpenFileName") as picker,
            ):
                self.tab.import_review()
            info.assert_called_once()
            self.assertIn("Export the blind review first", info.call_args.args[2])
            picker.assert_not_called()

    def test_compact_width_keeps_all_result_columns_visible(self):
        self.tab.resize(900, 720)
        self.app.processEvents()
        self.tab._refresh_responsive_geometry()
        self.assertGreaterEqual(
            self.tab.setup_card.height(), self.tab.setup_card.sizeHint().height()
        )
        self.assertGreater(self.tab.page_scroll.verticalScrollBar().maximum(), 0)
        for widgets in self.tab._candidate_widgets:
            self.assertGreaterEqual(widgets["endpoint_field"].width(), 320)
            self.assertGreaterEqual(widgets["key"].width(), 220)
            self.assertGreaterEqual(widgets["model"].width(), 260)
        for widget in (self.tab.test_size_combo, self.tab.budget_spin):
            self.assertGreaterEqual(widget.width(), 132)
        result_width = sum(
            self.tab.table.columnWidth(index)
            for index in range(self.tab.table.columnCount())
        )
        self.assertLessEqual(result_width, self.tab.table.viewport().width())
        self.assertEqual(
            self.tab.table.horizontalScrollBarPolicy(), Qt.ScrollBarAlwaysOff
        )
        self.assertEqual(self.tab.table.horizontalScrollBar().maximum(), 0)


if __name__ == "__main__":
    unittest.main()
