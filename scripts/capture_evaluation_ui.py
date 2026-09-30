#!/usr/bin/env python3
"""Capture Evaluation in the real application shell with explicit DPI/font scaling.

Uses an isolated, synthetic run and inert placeholders for unrelated pages. No
provider requests, user settings, or existing evaluations are read or changed.
Images are native Qt grabs: --size is logical pixels, --dpr controls raster size.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch


def seed_run(root):
    from tests import evaluation_pairwise_cases as cases
    from util import evaluation

    run = cases.fixture(root, "sample-evaluation", groups=36)
    state, manifest = evaluation.load_run(run)
    dialogue = [
        ("[San]: ここは……", ("[San]: This place...", "[San]: Where are we...?", "[San]: This place...")),
        ("[Weeu]: 一気に都市の中まで来れたっぽいね。", (
            "[Weeu]: Looks like we made it straight into the city.",
            "[Weeu]: Oh. Looks like we made it straight into the city.",
            "[Weeu]: Looks like we made it right into the city.")),
        ("[San]: ウィーウさんはこの辺りにも詳しいんですか？", (
            "[San]: Do you know this area well too, Weeu-san?",
            "[San]: Do you know your way around here too, Weeu-san?",
            "[San]: Are you familiar with this area too, Weeu-san?")),
        ("[Weeu]: いや、私は近くで活動しているだけだよ。", (
            "[Weeu]: Nah, I only really operate in the nearby area.",
            "[Weeu]: No, I just work around here.",
            "[Weeu]: Not really. My work keeps me close by.")),
        ("[San]: 静かですね。誰かいると思ったのに。", (
            "[San]: It is quiet. I thought people would still be here.",
            "[San]: So quiet... I expected someone to be here.",
            "[San]: It is quiet here. I thought someone might be around.")),
        ("[Weeu]: 今はほとんど廃墟みたいなものさ。", (
            "[Weeu]: It is practically a ghost town now.",
            "[Weeu]: The city is almost completely abandoned now.",
            "[Weeu]: There is barely anyone left in this city.")),
        ("[San]: ここが空洞の地なんですね。", (
            "[San]: So this is the Hollow Land.",
            "[San]: This is the Hollow Land, then.",
            "[San]: So we have reached the Hollow Land.")),
        ("[Weeu]: トランテラは特別なんだ。", (
            "[Weeu]: Tranterra is special.", "[Weeu]: Tranterra is an exception.",
            "[Weeu]: There is something special about Tranterra.")),
        ("[San]: もう少し調べてみましょう。", (
            "[San]: Let us look around a little more.", "[San]: We should investigate further.",
            "[San]: Let us take another look around.")),
    ]
    results = [evaluation._read_json(run / c["result_file"]) for c in state["candidates"]]
    for request in manifest["logical_requests"]:
        for n, (source, translations) in enumerate(dialogue, start=1):
            sid = f"{request['id']}-line-{n}"
            request["sources"].append(source)
            request["segment_ids"].append(sid)
            manifest["segments"].append(dict(id=sid, source=source, scene_id=request["scene_id"], stratum="dialogue"))
            for candidate_index, result in enumerate(results):
                result["executions"][f"rep-1:{request['id']}"]["lines"].append(
                    dict(segment_id=sid, translation=translations[candidate_index], valid=True))
        request["history"] = ["[Weeu]: もうすぐ着くよ。"]
        request["glossary"] = "空洞の地 → Hollow Land\nトランテラ → Tranterra\nウィーウ → Weeu"
    for n, (candidate, result) in enumerate(zip(state["candidates"], results)):
        candidate.update(model=("gpt-6-sol", "gpt-6-astra", "gpt-6-luna")[n], provider="openai",
                         reasoning_effort=("xhigh", "low", "none")[n], max_output_tokens=(16384, 16384, 4096)[n])
        candidate["summary"]["actual_cost_usd"] = (0.48, 0.92, 0.15)[n]
        evaluation._atomic_write_json(run / candidate["result_file"], result)
    state["created_at"] = "2026-09-28T15:57:00"
    state["corpus_summary"] = {"selected_segments": 360, "review_samples": 36}
    evaluation._atomic_write_json(run / "state.json", state)
    evaluation._atomic_write_json(run / "manifest.json", manifest)
    # Keep blind ordering and judgments identical when comparing capture sizes.
    ids = iter(uuid.UUID(int=n) for n in range(1, 10000))
    with (patch("util.evaluation_pairwise_io.uuid.uuid4", side_effect=lambda: next(ids)),
          patch("util.evaluation_pairwise_io.random.SystemRandom", return_value=random.Random(42))):
        review_path = evaluation.export_paired_review(run)
    cases.write(review_path, cases.fill(cases.read(review_path)))
    evaluation.import_blind_review(run, review_path, reviewer="Synthetic preview")
    return run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/tmp/evaluation-preview"))
    parser.add_argument("--size", default="1437x852", help="Window client size in logical pixels")
    parser.add_argument("--dpr", type=float, default=2.0, help="Device pixel ratio, independent of font scale")
    parser.add_argument("--font-scale", type=float, default=1.0)
    args = parser.parse_args()
    width, height = map(int, args.size.split("x"))
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QT_SCALE_FACTOR"] = str(args.dpr)
    os.environ["QT_FONT_DPI"] = "96"
    os.environ["DAZEDTL_TEST_OFFLINE"] = "1"
    os.environ["model"] = "gpt-6-sol"
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from PyQt5.QtCore import QCoreApplication, QEvent, QSettings, Qt
    from PyQt5.QtWidgets import QApplication, QWidget
    with patch("dotenv.load_dotenv", return_value=False):
        from gui.main import DazedMTLGUI
        from gui.evaluation_tab import EvaluationTab
        from util import evaluation

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication([])
    app.setStyle("Fusion")
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        run = seed_run(root)
        class CaptureWindow(DazedMTLGUI):
            def setup_tabs(self):
                self.project_root = root
                for index in range(10):
                    if index == self.PAGE_EVALUATION:
                        self.evaluation_tab = EvaluationTab(self)
                        self.evaluation_tab._initial_load_scheduled = True
                        page = self.evaluation_tab
                    else:
                        page = QWidget()
                    self.content_stack.addWidget(page)

            def restore_window_state(self):
                pass

            def save_window_state(self):
                pass

            def start_background_update_check(self):
                pass

            def setup_font_scaling(self):
                self.apply_font_scaling(args.font_scale)

        with (
            patch("gui.main.QSettings", return_value=QSettings(str(root / "settings.ini"), QSettings.IniFormat)),
            patch("gui.evaluation_tab.api_key_vault.ensure_vault"),
            patch("gui.evaluation_tab.api_key_vault.list_names", return_value=["OpenAI"]),
            patch("gui.evaluation_tab.api_key_vault.get_active_name", return_value="OpenAI"),
            patch("gui.evaluation_tab.api_key_vault.get_endpoint", return_value="https://api.openai.com/v1"),
            patch("gui.evaluation_tab.api_key_vault.is_keyless", return_value=False),
            patch.object(EvaluationTab, "_schedule_candidate_model_scan"),
        ):
            window = CaptureWindow()
            window.resize(width, height)
            window.switch_page(window.PAGE_EVALUATION)
            tab = window.evaluation_tab
            tab.current_run_dir = run
            state, manifest = evaluation.load_run(run)
            tab._restore_benchmark_setup(state, manifest)
            tab._populate_history([evaluation.run_history_entry(run)], select_run=run)
            tab._display_state(state)
            # Restored model cards are new widgets; use the real runtime scaling path.
            window.apply_font_scaling(args.font_scale)
            window.show()
            captures = []

            def capture(name, widget=window):
                for _ in range(10):
                    app.processEvents()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                pixmap = widget.grab()
                pixmap.save(str(args.output / f"{name}.png"))
                captures.append({"name": name, "logical_size": [widget.width(), widget.height()],
                                 "raster_size": [pixmap.width(), pixmap.height()],
                                 "device_pixel_ratio": pixmap.devicePixelRatioF(),
                                 "font_point_size": app.font().pointSizeF(),
                                 "table_viewport": [tab.comparison_table.viewport().width(), tab.comparison_table.viewport().height()],
                                 "translation_horizontal_scroll_max": tab.comparison_table.horizontalScrollBar().maximum()})

            capture("overview")
            tab.results_tabs.setCurrentIndex(tab._comparison_tab_index)
            if tab._comparison_load_worker:
                tab._comparison_load_worker.wait(3000)
            capture("translations")
            tab.comparison_samples_btn.click()
            capture("sample-browser", tab.comparison_browser)
            tab.comparison_browser.accept()
            tab.comparison_notes_btn.click()
            capture("sample-review", tab.comparison_review_dialog)
            tab.comparison_review_dialog.accept()
            tab.comparison_context_btn.click()
            capture("sample-context", tab.comparison_context_dialog)
            tab.comparison_context_dialog.accept()
            tab.review_tools_btn.click()
            capture("review-workflow", tab.review_dialog)
            tab.review_dialog.accept()
            tab.new_evaluation_btn.click()
            capture("setup", tab.setup_dialog)
            tab.setup_dialog.accept()
            tab.comparison_filter.setCurrentIndex(tab.comparison_filter.findData("all"))
            for index, sample in enumerate(tab._comparison_filtered_samples):
                if sample.get("paired_holdout_locked"):
                    tab.comparison_sample_list.setCurrentRow(index)
                    break
            capture("reserved")
            metadata = {"font_scale": args.font_scale, "requested_dpr": args.dpr,
                        "logical_dpi": app.primaryScreen().logicalDotsPerInch(),
                        "platform": app.platformName(), "style": app.style().objectName(),
                        "fixture": "synthetic", "capture_area": "application client area, excluding window-manager decorations",
                        "captures": captures}
            (args.output / "capture.json").write_text(json.dumps(metadata, indent=2))
            print(json.dumps(metadata, indent=2))
            window.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
