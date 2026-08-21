#!/usr/bin/env python3
"""Run deterministic unittest tiers and enforce their runtime budgets."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
import unittest
from collections.abc import Iterator
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# Before PyQt5, exactly as the launchers do - see util/msvc_runtime.py. It is
# repeated here rather than left to tests/__init__.py because discovery below
# passes no top_level_dir, so test modules are imported as top-level names and
# the tests package itself is never imported. A no-op off Windows.
from util.msvc_runtime import prepare as _prepare_msvc_runtime  # noqa: E402

_prepare_msvc_runtime()


# Full widget/workflow construction belongs here. New tests are core by default,
# so accidentally expensive additions fail the tighter core budget.
EXTENDED_TEST_PREFIXES = (
    "test_batch_tab.",
    "test_config_tab.ConfigTabRegressionTests.test_loads_every_option",
    "test_config_tab.ConfigTabRegressionTests.test_selecting_saved_provider",
    "test_config_tab.ConfigTabRegressionTests.test_provider_refresh",
    "test_config_tab.ConfigTabRegressionTests.test_manual_model_refresh",
    "test_config_tab.ConfigTabRegressionTests.test_save_and_reload",
    "test_config_tab.ConfigTabRegressionTests.test_reset_restores",
    "test_evaluation_tab.",
    "test_file_list_selection.",
    "test_gui_ux_contract.",
    "test_log_viewer.",
    "test_qt_icons.TestQtIcons.test_apply_button_icon",
    "test_image_manager_ui.",
    "test_translation_engine_dropdown.TranslationEngineDropdownTests.test_all_engines",
    "test_translation_engine_dropdown.TranslationEngineDropdownTests.test_translation_tab",
    "test_translation_tab_ui.TranslationTabUITests.",
    "test_version_update.VersionUpdateUITests.test_sidebar_page",
    "test_version_update.VersionUpdateUITests.test_already_applied",
    "test_version_update.VersionUpdateUITests.test_review_queue",
    "test_workflow_actions.",
    "test_workflow_ui.WorkflowShellTests.",
    "test_workflow_ui.WolfWorkflowShellTests.",
)

# The semi-manual image editor downloads OpenCV and its other heavy
# dependencies on demand. Keep those tests out of core/full even when the
# extras happen to be installed: otherwise discovery changes a three-module
# skip into hundreds of tests based on the developer's local environment.
IMAGETL_TEST_MODULES = (
    "test_image_text_editor",
    "test_imagetools",
    "test_imagetools_render",
)
IMAGETL_REQUIRED_MODULES = ("cv2", "numpy")
PROFILE_CHOICES = ("core", "extended", "imagetl", "full")


# Targets describe healthy local performance. Ceilings leave room for slower CI
# hosts without preserving the old runtime debt. Count ceilings are capacity
# guardrails, not quotas: available headroom does not relax the requirement to
# combine or parameterize overlapping cases. Raising a ceiling requires explicit
# user approval.
SUITE_TARGETS_SECONDS = {
    "core": 8.0,
    "extended": 12.0,
    "imagetl": 12.0,
    "full": 20.0,
}
SUITE_BUDGETS_SECONDS = {
    "core": 15.0,
    "extended": 30.0,
    "imagetl": 30.0,
    "full": 45.0,
}
PER_TEST_BUDGETS_SECONDS = {
    "core": 2.0,
    "extended": 3.0,
    "imagetl": 3.0,
    "full": 3.0,
}
SUITE_TEST_COUNT_BUDGETS = {
    "core": 903,
    "extended": 97,
    "imagetl": 312,
    "full": 1000,
}


def _iter_tests(suite: unittest.TestSuite) -> Iterator[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from _iter_tests(item)
        else:
            yield item


def _module_name_from_test_id(test_id: str) -> str:
    # A module-level SkipTest is represented as
    # unittest.loader.ModuleSkipped.<module>, while loaded tests start with the
    # module name. Normalize both forms so optional modules never leak into
    # another profile.
    if test_id.startswith("unittest.loader.ModuleSkipped."):
        return test_id.rsplit(".", 1)[-1]
    return test_id.partition(".")[0]


def _test_group_for_id(test_id: str) -> str:
    if _module_name_from_test_id(test_id) in IMAGETL_TEST_MODULES:
        return "imagetl"
    if any(test_id.startswith(prefix) for prefix in EXTENDED_TEST_PREFIXES):
        return "extended"
    return "core"


def _missing_imagetl_modules() -> tuple[str, ...]:
    return tuple(
        module
        for module in IMAGETL_REQUIRED_MODULES
        if importlib.util.find_spec(module) is None
    )


def load_suite(profile: str) -> unittest.TestSuite:
    tests_root = REPOSITORY_ROOT / "tests"
    if str(tests_root) not in sys.path:
        sys.path.insert(0, str(tests_root))
    if profile == "imagetl":
        module_names = list(IMAGETL_TEST_MODULES)
    else:
        module_names = [
            path.stem
            for path in sorted(tests_root.glob("test_*.py"))
            if path.stem not in IMAGETL_TEST_MODULES
        ]
    discovered = unittest.defaultTestLoader.loadTestsFromNames(module_names)
    tests = list(_iter_tests(discovered))
    if profile == "core":
        selected = [test for test in tests if _test_group_for_id(test.id()) == "core"]
    elif profile == "extended":
        selected = [
            test for test in tests if _test_group_for_id(test.id()) == "extended"
        ]
    elif profile == "imagetl":
        selected = [
            test for test in tests if _test_group_for_id(test.id()) == "imagetl"
        ]
    else:
        selected = [
            test
            for test in tests
            if _test_group_for_id(test.id()) in {"core", "extended"}
        ]
    return unittest.TestSuite(selected)


class TimedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.timings: list[tuple[float, str]] = []
        self._test_started = 0.0

    def startTest(self, test):  # noqa: N802 - unittest API
        self._test_started = time.perf_counter()
        super().startTest(test)

    def stopTest(self, test):  # noqa: N802 - unittest API
        elapsed = time.perf_counter() - self._test_started
        self.timings.append((elapsed, test.id()))
        super().stopTest(test)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile", nargs="?", choices=PROFILE_CHOICES, default="core"
    )
    parser.add_argument(
        "--durations", type=int, default=20, help="number of slow tests to print"
    )
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("-f", "--failfast", action="store_true")
    parser.add_argument(
        "--list", action="store_true", help="list selected test IDs without running"
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.profile == "imagetl":
        missing = _missing_imagetl_modules()
        if missing:
            print(
                "ERROR: ImageTL test dependencies are not installed "
                f"({', '.join(missing)} missing). Run "
                "`python -m util.imagetools.resources --default` first.",
                file=sys.stderr,
            )
            return 2
    suite = load_suite(args.profile)
    selected = list(_iter_tests(suite))
    if args.list:
        for test in selected:
            print(test.id())
        print(f"Selected {len(selected)} {args.profile} tests.")
        return 0

    print(
        f"Running {len(selected)} {args.profile} tests "
        f"(count ceiling {SUITE_TEST_COUNT_BUDGETS[args.profile]}; "
        f"target {SUITE_TARGETS_SECONDS[args.profile]:.1f}s; "
        f"time ceiling {SUITE_BUDGETS_SECONDS[args.profile]:.1f}s).",
        flush=True,
    )
    started = time.perf_counter()
    runner = unittest.TextTestRunner(
        verbosity=0 if args.quiet else 1,
        failfast=args.failfast,
        buffer=True,
        resultclass=TimedResult,
    )
    result = runner.run(unittest.TestSuite(selected))
    elapsed = time.perf_counter() - started

    duration_count = max(0, args.durations)
    if duration_count:
        print(f"\nSlowest {min(duration_count, len(result.timings))} tests:")
        for duration, test_id in sorted(result.timings, reverse=True)[:duration_count]:
            print(f"{duration:8.3f}s  {test_id}")

    violations = []
    count_budget = SUITE_TEST_COUNT_BUDGETS[args.profile]
    if len(selected) > count_budget:
        violations.append(
            f"{args.profile} suite selected {len(selected)} tests; "
            f"count budget is {count_budget}"
        )
    suite_budget = SUITE_BUDGETS_SECONDS[args.profile]
    if elapsed > suite_budget:
        violations.append(
            f"{args.profile} suite took {elapsed:.3f}s; budget is {suite_budget:.3f}s"
        )
    per_test_budget = PER_TEST_BUDGETS_SECONDS[args.profile]
    slow_tests = [
        (duration, test_id)
        for duration, test_id in result.timings
        if duration > per_test_budget
    ]
    for duration, test_id in sorted(slow_tests, reverse=True):
        violations.append(
            f"{test_id} took {duration:.3f}s; per-test budget is {per_test_budget:.3f}s"
        )

    print(
        f"\n{args.profile.capitalize()} suite: {result.testsRun} tests in "
        f"{elapsed:.3f}s (target {SUITE_TARGETS_SECONDS[args.profile]:.3f}s; "
        f"ceiling {suite_budget:.3f}s)."
    )
    if elapsed > SUITE_TARGETS_SECONDS[args.profile] and not violations:
        print(
            "Legacy runtime debt remains above the ratchet target, "
            "but is within the enforced ceiling."
        )
    if violations:
        print("\nTEST RUNTIME BUDGET FAILED:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
