#!/usr/bin/env python3
"""Run deterministic unittest tiers and enforce their runtime budgets."""

from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import time
import unittest
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DAZEDTL_TEST_OFFLINE"] = "1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

# Before PyQt5, exactly as the launchers do - see util/msvc_runtime.py. It is
# repeated here rather than left to tests/__init__.py because discovery below
# passes no top_level_dir, so test modules are imported as top-level names and
# the tests package itself is never imported. A no-op off Windows.
from util.msvc_runtime import prepare as _prepare_msvc_runtime  # noqa: E402

_prepare_msvc_runtime()


# Full widget/workflow construction belongs here. Whole-module classifications
# also let focused profiles avoid importing modules they cannot select.
EXTENDED_TEST_MODULES = (
    "test_batch_tab",
    "test_evaluation_tab",
    "test_file_list_selection",
    "test_gui_ux_contract",
    "test_image_manager_ui",
    "test_log_viewer",
    "test_workflow_actions",
)
EXTENDED_TEST_PREFIXES = (
    "test_config_tab.ConfigTabRegressionTests.test_loads_every_option",
    "test_config_tab.ConfigTabRegressionTests.test_selecting_saved_provider",
    "test_config_tab.ConfigTabRegressionTests.test_provider_refresh",
    "test_config_tab.ConfigTabRegressionTests.test_manual_model_refresh",
    "test_config_tab.ConfigTabRegressionTests.test_save_and_reload",
    "test_config_tab.ConfigTabRegressionTests.test_reset_restores",
    "test_qt_icons.TestQtIcons.test_apply_button_icon",
    "test_translation_engine_dropdown.TranslationEngineDropdownTests.test_all_engines",
    "test_translation_engine_dropdown.TranslationEngineDropdownTests.test_translation_tab",
    "test_translation_tab_ui.TranslationTabUITests.",
    "test_version_update.VersionUpdateUITests.",
    "test_workflow_ui.WorkflowShellTests.",
    "test_workflow_ui.WolfWorkflowShellTests.",
)

# Subprocess-backed Git repositories and persisted end-to-end evaluation runs
# are valuable integration coverage, not lightweight unit/component tests.
INTEGRATION_TEST_MODULES = (
    "test_evaluation",
)
INTEGRATION_TEST_PREFIXES = (
    "test_version_update.GitVersionUpdateTests.",
)
# Every test in these mixed-class modules is explicitly classified outside
# core, so core discovery can skip their imports too.
CORE_EXCLUDED_TEST_MODULES = (
    "test_version_update",
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
PROFILE_CHOICES = ("core", "integration", "extended", "imagetl", "full")


# Targets describe healthy local performance. Ceilings leave room for slower CI
# hosts without preserving the old runtime debt. Count ceilings are capacity
# guardrails, not quotas: available headroom does not relax the requirement to
# combine or parameterize overlapping cases. Raising a ceiling requires explicit
# user approval.
SUITE_TARGETS_SECONDS = {
    "core": 5.0,
    "integration": 18.0,
    "extended": 20.0,
    "imagetl": 15.0,
    "full": 40.0,
}
SUITE_BUDGETS_SECONDS = {
    "core": 8.0,
    "integration": 20.0,
    "extended": 30.0,
    "imagetl": 30.0,
    "full": 45.0,
}
PER_TEST_TARGETS_SECONDS = {
    "core": 0.5,
    "integration": 1.0,
    "extended": 1.0,
    "imagetl": 1.0,
    "full": 1.0,
}
PER_TEST_BUDGETS_SECONDS = {
    "core": 0.5,
    "integration": 1.5,
    "extended": 1.5,
    "imagetl": 1.5,
    "full": 1.5,
}
SUITE_TEST_COUNT_BUDGETS = {
    "core": 780,
    "integration": 130,
    "extended": 100,
    "imagetl": 312,
    "full": 1000,
}

# Cumulative module ceilings catch broad modules that grow through many
# individually-fast tests. Existing integration/UI debt is explicit here so a
# new module cannot silently inherit the same allowance.
DEFAULT_MODULE_BUDGETS_SECONDS = {
    "core": 1.0,
    "integration": 2.0,
    "extended": 2.0,
    "imagetl": 10.0,
    "full": 2.0,
}
MODULE_BUDGET_OVERRIDES_SECONDS = {
    ("core", "test_walkthrough_validation"): 1.5,
    ("integration", "test_evaluation"): 5.0,
    ("integration", "test_version_update"): 15.0,
    ("extended", "test_image_manager_ui"): 2.5,
    ("extended", "test_version_update"): 3.0,
    ("extended", "test_workflow_actions"): 8.0,
    ("extended", "test_workflow_ui"): 6.0,
    ("full", "test_evaluation"): 5.0,
    ("full", "test_image_manager_ui"): 2.5,
    ("full", "test_version_update"): 18.0,
    ("full", "test_walkthrough_validation"): 1.5,
    ("full", "test_workflow_actions"): 8.0,
    ("full", "test_workflow_ui"): 6.0,
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
    module_name = _module_name_from_test_id(test_id)
    if module_name in IMAGETL_TEST_MODULES:
        return "imagetl"
    if module_name in EXTENDED_TEST_MODULES or any(
        test_id.startswith(prefix) for prefix in EXTENDED_TEST_PREFIXES
    ):
        return "extended"
    if module_name in INTEGRATION_TEST_MODULES or any(
        test_id.startswith(prefix) for prefix in INTEGRATION_TEST_PREFIXES
    ):
        return "integration"
    return "core"


def _module_timings(
    timings: list[tuple[float, str]],
) -> list[tuple[float, str, int]]:
    elapsed_by_module: dict[str, float] = defaultdict(float)
    tests_by_module: dict[str, int] = defaultdict(int)
    for elapsed, test_id in timings:
        module_name = _module_name_from_test_id(test_id)
        elapsed_by_module[module_name] += elapsed
        tests_by_module[module_name] += 1
    return sorted(
        (
            (elapsed, module_name, tests_by_module[module_name])
            for module_name, elapsed in elapsed_by_module.items()
        ),
        reverse=True,
    )


def _module_budget_seconds(profile: str, module_name: str) -> float:
    return MODULE_BUDGET_OVERRIDES_SECONDS.get(
        (profile, module_name), DEFAULT_MODULE_BUDGETS_SECONDS[profile]
    )


def _missing_imagetl_modules() -> tuple[str, ...]:
    return tuple(
        module
        for module in IMAGETL_REQUIRED_MODULES
        if importlib.util.find_spec(module) is None
    )


def _module_names_for_profile(tests_root: Path, profile: str) -> list[str]:
    all_module_names = {
        path.stem for path in tests_root.glob("test_*.py")
    }
    if profile == "imagetl":
        return list(IMAGETL_TEST_MODULES)
    if profile == "full":
        selected = all_module_names.difference(IMAGETL_TEST_MODULES)
    elif profile == "integration":
        selected = set(INTEGRATION_TEST_MODULES)
        selected.update(
            prefix.partition(".")[0] for prefix in INTEGRATION_TEST_PREFIXES
        )
    elif profile == "extended":
        selected = set(EXTENDED_TEST_MODULES)
        selected.update(prefix.partition(".")[0] for prefix in EXTENDED_TEST_PREFIXES)
    else:
        selected = all_module_names.difference(
            IMAGETL_TEST_MODULES,
            EXTENDED_TEST_MODULES,
            INTEGRATION_TEST_MODULES,
            CORE_EXCLUDED_TEST_MODULES,
        )
    return sorted(selected)


def load_suite(profile: str) -> unittest.TestSuite:
    tests_root = REPOSITORY_ROOT / "tests"
    if str(tests_root) not in sys.path:
        sys.path.insert(0, str(tests_root))
    module_names = _module_names_for_profile(tests_root, profile)
    discovered = unittest.defaultTestLoader.loadTestsFromNames(module_names)
    tests = list(_iter_tests(discovered))
    if profile == "full":
        selected_groups = {"core", "integration", "extended"}
    else:
        selected_groups = {profile}
    if profile == "imagetl":
        selected = [
            test for test in tests if _test_group_for_id(test.id()) == "imagetl"
        ]
    else:
        selected = [
            test
            for test in tests
            if _test_group_for_id(test.id()) in selected_groups
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
    parser.add_argument(
        "--module-durations",
        type=int,
        default=10,
        help="number of slow cumulative module timings to print",
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
    suite_started = time.perf_counter()
    suite = load_suite(args.profile)
    selected = list(_iter_tests(suite))
    discovery_elapsed = time.perf_counter() - suite_started
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
    execution_started = time.perf_counter()
    runner = unittest.TextTestRunner(
        verbosity=0 if args.quiet else 1,
        failfast=args.failfast,
        buffer=True,
        resultclass=TimedResult,
    )
    result = runner.run(unittest.TestSuite(selected))
    execution_elapsed = time.perf_counter() - execution_started
    elapsed = time.perf_counter() - suite_started

    duration_count = max(0, args.durations)
    if duration_count:
        print(f"\nSlowest {min(duration_count, len(result.timings))} tests:")
        for duration, test_id in sorted(result.timings, reverse=True)[:duration_count]:
            print(f"{duration:8.3f}s  {test_id}")

    module_timings = _module_timings(result.timings)
    module_duration_count = max(0, args.module_durations)
    if module_duration_count:
        print(
            f"\nSlowest {min(module_duration_count, len(module_timings))} modules:"
        )
        for duration, module_name, test_count in module_timings[
            :module_duration_count
        ]:
            print(f"{duration:8.3f}s  {module_name} ({test_count} tests)")

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
    per_test_target = PER_TEST_TARGETS_SECONDS[args.profile]
    tests_above_target = [
        (duration, test_id)
        for duration, test_id in result.timings
        if duration > per_test_target
    ]
    slow_tests = [
        (duration, test_id)
        for duration, test_id in result.timings
        if duration > per_test_budget
    ]
    for duration, test_id in sorted(slow_tests, reverse=True):
        violations.append(
            f"{test_id} took {duration:.3f}s; per-test budget is {per_test_budget:.3f}s"
        )
    for duration, module_name, _test_count in module_timings:
        module_budget = _module_budget_seconds(args.profile, module_name)
        if duration > module_budget:
            violations.append(
                f"{module_name} took {duration:.3f}s cumulatively; "
                f"module budget is {module_budget:.3f}s"
            )

    print(
        f"\n{args.profile.capitalize()} suite: {result.testsRun} tests in "
        f"{elapsed:.3f}s (target {SUITE_TARGETS_SECONDS[args.profile]:.3f}s; "
        f"ceiling {suite_budget:.3f}s)."
    )
    print(
        f"Discovery/import: {discovery_elapsed:.3f}s; "
        f"test execution: {execution_elapsed:.3f}s."
    )
    if elapsed > SUITE_TARGETS_SECONDS[args.profile] and not violations:
        print(
            "Legacy runtime debt remains above the ratchet target, "
            "but is within the enforced ceiling."
        )
    if tests_above_target and not violations:
        print(
            f"Per-test target debt: {len(tests_above_target)} test(s) exceeded "
            f"the {per_test_target:.3f}s target but remained within the "
            f"{per_test_budget:.3f}s ceiling."
        )
    if violations:
        print("\nTEST RUNTIME BUDGET FAILED:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
