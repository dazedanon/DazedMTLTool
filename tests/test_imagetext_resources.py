"""The on-demand downloader for the semi-manual image workflow.

Everything here runs on a checkout with none of the extras installed and with
no network, because that is the state the module exists to get out of. Nothing
below reaches HuggingFace or GitHub: downloads are pointed at ``file://`` URLs
or at a stub, and pip is a recorder.
"""

from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from util.imagetools import resources as resmod
from util.paths import DATA_DIR


class ManifestTests(unittest.TestCase):
    """The manifest is data, so the things that can rot in it are checked."""

    def test_keys_are_unique(self):
        keys = [resource.key for resource in resmod.RESOURCES]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_download_has_a_destination_and_the_other_way_round(self):
        for resource in resmod.RESOURCES:
            with self.subTest(resource.key):
                self.assertEqual(bool(resource.url), resource.dest is not None)

    def test_every_url_is_https(self):
        for resource in resmod.RESOURCES:
            if not resource.url:
                continue
            with self.subTest(resource.key):
                self.assertTrue(
                    resource.url.startswith("https://"),
                    f"{resource.key} would be fetched over an insecure transport",
                )

    def test_nothing_is_written_outside_the_data_folder(self):
        """A manifest typo must not be able to write into the user's game."""
        root = DATA_DIR.resolve()
        for resource in resmod.RESOURCES:
            if resource.dest is None:
                continue
            with self.subTest(resource.key):
                destination = resource.dest.resolve()
                self.assertIn(root, [destination, *destination.parents])

    def test_an_archive_declares_how_to_tell_it_unpacked(self):
        for resource in resmod.RESOURCES:
            if resource.archive:
                with self.subTest(resource.key):
                    self.assertTrue(resource.proof)

    def test_exactly_one_required_resource_and_it_is_the_python_packages(self):
        required = [r for r in resmod.RESOURCES if r.required]
        self.assertEqual([r.key for r in required], ["core"])
        self.assertIn("cv2", required[0].modules)

    def test_the_defaults_are_the_required_set_plus_the_cheap_model(self):
        """Nobody is charged 400 MB for pressing a button once."""
        self.assertEqual(resmod.defaults(), ["core", "aot"])

    def test_the_two_big_models_are_never_pre_ticked(self):
        for key in ("lama", "lama_manga"):
            with self.subTest(key):
                self.assertFalse(resmod.get(key).default)
                self.assertGreater(resmod.get(key).size, 100_000_000)

    def test_unknown_keys_are_refused_by_name(self):
        with self.assertRaises(KeyError):
            resmod.get("lamaa")


class PlatformTests(unittest.TestCase):
    def test_patchmatch_is_hidden_where_no_build_is_published(self):
        """No Linux library exists, so it must not be offered and then fail."""
        with patch.object(sys, "platform", "linux"):
            keys = [resource.key for resource in resmod.available()]
        self.assertNotIn("patchmatch", keys)

    def test_patchmatch_is_offered_on_windows(self):
        with patch.object(sys, "platform", "win32"):
            keys = [resource.key for resource in resmod.available()]
            self.assertIn("patchmatch", keys)
            self.assertIn("windows", resmod._patchmatch_asset())

    def test_intel_macs_get_nothing_because_only_arm64_is_published(self):
        with patch.object(sys, "platform", "darwin"), \
                patch.object(resmod, "_is_arm", lambda: False):
            self.assertEqual(resmod._patchmatch_asset(), "")


class PresenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="imgtl-res-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _resource(self, **kwargs):
        base = dict(key="probe", label="Probe", detail="", modules=(), url="")
        base.update(kwargs)
        return resmod.Resource(**base)

    def test_a_file_resource_is_present_only_once_the_file_is(self):
        target = self.tmp / "weights.onnx"
        resource = self._resource(url="https://x/y", dest=target)
        self.assertFalse(resmod.installed(resource))
        target.write_bytes(b"0")
        self.assertTrue(resmod.installed(resource))

    def test_a_part_file_does_not_count_as_installed(self):
        """The whole point of the .part suffix."""
        target = self.tmp / "weights.onnx"
        (self.tmp / "weights.onnx.part").write_bytes(b"half")
        resource = self._resource(url="https://x/y", dest=target)
        self.assertFalse(resmod.installed(resource))

    def test_an_archive_is_present_when_any_of_its_proof_files_is(self):
        resource = self._resource(
            url="https://x/y.7z",
            dest=self.tmp,
            archive=True,
            proof=("libfoo.so", "foo.dll"),
        )
        self.assertFalse(resmod.installed(resource))
        (self.tmp / "foo.dll").write_bytes(b"0")
        self.assertTrue(resmod.installed(resource))

    def test_a_missing_package_keeps_a_present_file_from_counting(self):
        target = self.tmp / "weights.onnx"
        target.write_bytes(b"0")
        resource = self._resource(
            modules=("a_package_that_does_not_exist",),
            url="https://x/y",
            dest=target,
        )
        self.assertFalse(resmod.installed(resource))

    def test_ready_follows_the_required_resource(self):
        with patch.object(resmod, "installed", lambda r: False):
            self.assertFalse(resmod.ready())
        with patch.object(resmod, "installed", lambda r: True):
            self.assertTrue(resmod.ready())

    def test_missing_keeps_manifest_order(self):
        with patch.object(resmod, "installed", lambda r: False):
            keys = [resource.key for resource in resmod.missing()]
        self.assertEqual(keys, [r.key for r in resmod.available()])


class EstimateTests(unittest.TestCase):
    def test_a_shared_package_is_counted_once(self):
        """All three models need onnxruntime; the user downloads it once."""
        with patch.object(resmod, "_importable", lambda name: False), \
                patch.object(resmod, "installed", lambda r: False):
            one = resmod.estimate([resmod.get("aot")])
            three = resmod.estimate(
                [resmod.get("aot"), resmod.get("lama"), resmod.get("lama_manga")]
            )
        onnx = resmod.PIP_SIZES["onnxruntime"]
        self.assertEqual(
            three,
            one + resmod.get("lama").size + resmod.get("lama_manga").size,
        )
        self.assertEqual(one, onnx + resmod.get("aot").size)

    def test_something_already_present_costs_nothing(self):
        with patch.object(resmod, "_importable", lambda name: True), \
                patch.object(resmod, "installed", lambda r: True):
            self.assertEqual(resmod.estimate(list(resmod.RESOURCES)), 0)

    def test_sizes_read_as_people_write_them(self):
        self.assertEqual(resmod.human(23_068_213), "23 MB")
        self.assertEqual(resmod.human(999), "999 bytes")
        self.assertEqual(resmod.human(2_500_000_000), "2.5 GB")


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="imgtl-fetch-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.payload = b"x" * (resmod.CHUNK * 2 + 17)
        source = self.tmp / "source.bin"
        source.write_bytes(self.payload)
        self.url = source.as_uri()
        self.target = self.tmp / "out" / "weights.onnx"

    def test_the_file_appears_only_when_it_is_complete(self):
        """The invariant that keeps a truncated 200 MB model from being used.

        Checked from inside the download rather than after it: the final name
        must not exist at any point while bytes are still arriving.
        """
        seen = []

        def progress(done, total):
            seen.append(self.target.exists())

        resmod._fetch(self.url, self.target, progress=progress, log=lambda m: None)
        self.assertGreater(len(seen), 1, "expected more than one chunk")
        self.assertEqual(seen, [False] * len(seen))
        self.assertEqual(self.target.read_bytes(), self.payload)

    def test_progress_reports_the_declared_length(self):
        totals = []
        resmod._fetch(
            self.url, self.target,
            progress=lambda done, total: totals.append(total),
            log=lambda m: None,
        )
        self.assertEqual(set(totals), {len(self.payload)})

    def test_a_failed_download_leaves_nothing_behind(self):
        missing = (self.tmp / "not-there.bin").as_uri()
        with self.assertRaises(urllib.error.URLError):
            resmod._fetch(missing, self.target, log=lambda m: None)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_name(self.target.name + ".part").exists())

    def test_stopping_mid_download_keeps_nothing(self):
        with self.assertRaises(resmod.Cancelled):
            resmod._fetch(
                self.url, self.target,
                log=lambda m: None,
                should_stop=lambda: True,
            )
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_name(self.target.name + ".part").exists())

    def test_a_short_read_is_a_failure_not_a_file(self):
        """A proxy that closes early must not look like a finished download."""

        class Truncated(io.BytesIO):
            headers = {"Content-Length": str(len(self.payload) + 1000)}

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with patch.object(
            urllib.request, "urlopen", lambda *a, **k: Truncated(self.payload)
        ):
            with self.assertRaises(OSError):
                resmod._fetch(self.url, self.target, log=lambda m: None)
        self.assertFalse(self.target.exists())
        self.assertFalse(self.target.with_name(self.target.name + ".part").exists())


class PipTests(unittest.TestCase):
    class _Recorder:
        def __init__(self, command, **kwargs):
            PipTests.commands.append(command)
            self.stdout = io.StringIO("Collecting numpy\nSuccessfully installed\n")

        def wait(self):
            return 0

        def terminate(self):
            pass

    def setUp(self):
        PipTests.commands = []

    def test_pip_runs_through_this_interpreter_and_never_the_shim(self):
        """A copied virtualenv's Scripts\\pip.exe installs into the wrong tree.

        It hardcodes the interpreter it was built against, so bare ``pip``
        silently installs somewhere else and the caller then reports the
        package as missing no matter how many times it is installed.
        """
        with patch.object(subprocess, "Popen", self._Recorder):
            resmod._pip(["numpy>=2.0"], log=lambda m: None)
        self.assertEqual(len(PipTests.commands), 1)
        command = PipTests.commands[0]
        self.assertEqual(command[:4], [sys.executable, "-m", "pip", "install"])
        self.assertIn("numpy>=2.0", command)

    def test_a_pip_failure_is_raised_not_swallowed(self):
        class Failing(self._Recorder):
            def wait(self):
                return 1

        with patch.object(subprocess, "Popen", Failing):
            with self.assertRaises(RuntimeError):
                resmod._pip(["numpy"], log=lambda m: None)

    def test_pip_output_reaches_the_log(self):
        lines = []
        with patch.object(subprocess, "Popen", self._Recorder):
            resmod._pip(["numpy"], log=lines.append)
        self.assertIn("Collecting numpy", lines)


class InstallOrderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="imgtl-install-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pips = []
        self.fetched = []

    def _run(self, resources):
        with patch.object(resmod, "_pip", lambda specs, **kw: self.pips.append(specs)), \
                patch.object(
                    resmod, "_fetch",
                    lambda url, dest, **kw: self.fetched.append(dest.name)), \
                patch.object(resmod, "_importable", lambda name: False), \
                patch.object(resmod, "installed", lambda r: False), \
                patch.object(resmod, "activate", lambda: None):
            resmod.install(resources, log=lambda m: None)

    def test_a_shared_package_is_installed_once_across_resources(self):
        self._run([resmod.get("aot"), resmod.get("lama")])
        installed = [spec for call in self.pips for spec in call]
        self.assertEqual(
            [s for s in installed if s.startswith("onnxruntime")],
            ["onnxruntime>=1.17"],
        )

    def test_both_models_are_still_downloaded(self):
        self._run([resmod.get("aot"), resmod.get("lama")])
        self.assertEqual(self.fetched, ["aot.onnx", "lama_fp32.onnx"])

    def test_packages_come_before_the_files_that_need_them(self):
        """py7zr has to exist before the archive it unpacks is fetched."""
        order = []
        with patch.object(resmod, "_pip", lambda specs, **kw: order.append("pip")), \
                patch.object(resmod, "_fetch", lambda *a, **kw: order.append("fetch")), \
                patch.object(resmod, "_unpack", lambda *a, **kw: order.append("unpack")), \
                patch.object(resmod, "_importable", lambda name: False), \
                patch.object(resmod, "installed", lambda r: False), \
                patch.object(resmod, "activate", lambda: None), \
                patch.object(sys, "platform", "win32"):
            resmod.install([resmod.get("patchmatch")], log=lambda m: None)
        self.assertEqual(order, ["pip", "fetch", "unpack"])

    def test_the_archive_is_staged_outside_the_library_folder(self):
        """A failed unpack must not leave a .7z where the DLL loader looks."""
        staged = []
        with patch.object(resmod, "_pip", lambda specs, **kw: None), \
                patch.object(
                    resmod, "_fetch",
                    lambda url, dest, **kw: staged.append(dest)), \
                patch.object(resmod, "_unpack", lambda *a, **kw: None), \
                patch.object(resmod, "_importable", lambda name: False), \
                patch.object(resmod, "installed", lambda r: False), \
                patch.object(resmod, "activate", lambda: None), \
                patch.object(sys, "platform", "win32"):
            resmod.install([resmod.get("patchmatch")], log=lambda m: None)
        self.assertEqual(len(staged), 1)
        self.assertNotEqual(staged[0].parent, resmod.LIB_DIR)

    def test_a_failure_stops_the_run_rather_than_carrying_on(self):
        def explode(specs, **kwargs):
            raise RuntimeError("no wheel for this Python")

        with patch.object(resmod, "_pip", explode), \
                patch.object(resmod, "_fetch", lambda *a, **kw: self.fetched.append(1)), \
                patch.object(resmod, "_importable", lambda name: False), \
                patch.object(resmod, "installed", lambda r: False):
            with self.assertRaises(RuntimeError):
                resmod.install(
                    [resmod.get("core"), resmod.get("aot")], log=lambda m: None
                )
        self.assertEqual(self.fetched, [])

    def test_progress_names_the_resource_it_is_reporting(self):
        keys = []
        with patch.object(resmod, "_pip", lambda specs, **kw: None), \
                patch.object(resmod, "_fetch", lambda *a, **kw: None), \
                patch.object(resmod, "_importable", lambda name: False), \
                patch.object(resmod, "installed", lambda r: False), \
                patch.object(resmod, "activate", lambda: None):
            resmod.install(
                [resmod.get("core"), resmod.get("aot")],
                progress=lambda key, done, total: keys.append(key),
                log=lambda m: None,
            )
        self.assertEqual(keys[:2], ["core", "aot"])


class UnpackTests(unittest.TestCase):
    """Only meaningful once py7zr is installed, which is itself on demand."""

    def setUp(self):
        try:
            import py7zr  # noqa: F401
        except ImportError:
            self.skipTest("py7zr is not installed")
        self.tmp = Path(tempfile.mkdtemp(prefix="imgtl-unpack-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_a_nested_archive_is_flattened_into_one_folder(self):
        import py7zr

        payload = self.tmp / "build" / "release"
        payload.mkdir(parents=True)
        (payload / "foo.dll").write_bytes(b"lib")
        archive = self.tmp / "bundle.7z"
        with py7zr.SevenZipFile(archive, "w") as bundle:
            bundle.writeall(self.tmp / "build", "build")

        target = self.tmp / "libs"
        resmod._unpack(archive, target, log=lambda m: None)
        self.assertTrue((target / "foo.dll").is_file())
        self.assertFalse((target / "build").exists())

    def test_the_staging_folder_is_cleaned_up(self):
        import py7zr

        (self.tmp / "a.dll").write_bytes(b"lib")
        archive = self.tmp / "bundle.7z"
        with py7zr.SevenZipFile(archive, "w") as bundle:
            bundle.write(self.tmp / "a.dll", "a.dll")

        target = self.tmp / "libs"
        resmod._unpack(archive, target, log=lambda m: None)
        self.assertFalse((target.parent / f"{target.name}.unpack").exists())


class ActivateTests(unittest.TestCase):
    def test_import_caches_are_dropped_so_a_new_package_is_visible(self):
        with patch("importlib.invalidate_caches") as invalidate:
            resmod.activate()
        invalidate.assert_called_once()

    def test_running_it_twice_adds_nothing_the_second_time(self):
        """It runs after every pip step, so it must not grow sys.path.

        Only what this call adds is measured. Other test modules insert the
        project root themselves, so asserting sys.path is globally duplicate
        free would be testing them rather than this.
        """
        resmod.activate()
        settled = list(sys.path)
        resmod.activate()
        self.assertEqual(sys.path, settled)

    def test_it_never_drops_anything_already_on_the_path(self):
        before = list(sys.path)
        resmod.activate()
        self.assertTrue(set(before).issubset(sys.path))


class CommandLineTests(unittest.TestCase):
    def setUp(self):
        quiet = patch("sys.stdout", new_callable=io.StringIO)
        self.stdout = quiet.start()
        self.addCleanup(quiet.stop)

    def test_no_arguments_reports_and_downloads_nothing(self):
        lines = []
        with patch.object(resmod, "_report", lambda log=print: lines.append("report")), \
                patch.object(resmod, "install", lambda *a, **k: lines.append("install")):
            self.assertEqual(resmod.main([]), 0)
        self.assertEqual(lines, ["report"])

    def test_the_report_mentions_every_available_resource(self):
        lines = []
        resmod._report(log=lines.append)
        text = "\n".join(lines)
        for resource in resmod.available():
            with self.subTest(resource.key):
                self.assertIn(resource.key, text)

    def test_an_unknown_key_fails_without_downloading(self):
        with patch.object(resmod, "install", lambda *a, **k: self.fail("downloaded")):
            self.assertEqual(resmod.main(["nonsense"]), 1)

    def test_default_selects_the_pre_ticked_set(self):
        chosen = []
        with patch.object(resmod, "installed", lambda r: False), \
                patch.object(
                    resmod, "install",
                    lambda rs, **k: chosen.extend(r.key for r in rs)):
            resmod.main(["--default"])
        self.assertEqual(chosen, ["core", "aot"])

    def test_a_download_failure_is_reported_as_a_nonzero_exit(self):
        def explode(*args, **kwargs):
            raise RuntimeError("network is down")

        with patch.object(resmod, "installed", lambda r: False), \
                patch.object(resmod, "install", explode):
            self.assertEqual(resmod.main(["--default"]), 1)


class RuntimeOrderTests(unittest.TestCase):
    """Every entry point must claim the C++ runtime before PyQt5 loads.

    PyQt5 carries its own copy (14.26), Windows resolves a DLL by base name
    against what is already loaded, and onnxruntime refuses to load against it.
    Claiming the system runtime afterwards does nothing at all, so this is
    purely a question of line order - and it fails as an unreadable "DLL
    initialization routine failed" a long way from the cause.

    It has already gone wrong once: scripts/run_test_suite.py discovers with no
    top_level_dir, so test modules load as top-level names and tests/__init__.py
    never runs. Every entry point needs its own call.
    """

    ENTRY_POINTS = (
        "gui/main.py",
        "scripts/start_gui.py",
        "scripts/run_test_suite.py",
        "tests/__init__.py",
    )

    def _lines(self, relpath):
        """Statement lines only. Both names appear in prose in these files."""
        from util.paths import PROJECT_ROOT

        text = (PROJECT_ROOT / relpath).read_text(encoding="utf-8")
        return [
            line
            for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    def _first(self, lines, predicate):
        for index, line in enumerate(lines):
            if predicate(line):
                return index
        return None

    def test_each_entry_point_claims_the_runtime(self):
        for relpath in self.ENTRY_POINTS:
            with self.subTest(relpath):
                claim = self._first(
                    self._lines(relpath),
                    lambda line: "msvc_runtime" in line and "import" in line,
                )
                self.assertIsNotNone(
                    claim, f"{relpath} never imports util.msvc_runtime"
                )

    def test_it_is_claimed_before_qt_is_imported(self):
        for relpath in self.ENTRY_POINTS:
            lines = self._lines(relpath)
            qt = self._first(
                lines,
                lambda line: line.lstrip().startswith(("from PyQt5", "import PyQt5")),
            )
            if qt is None:
                continue
            with self.subTest(relpath):
                claim = self._first(
                    lines, lambda line: "msvc_runtime" in line and "import" in line
                )
                self.assertIsNotNone(claim)
                self.assertLess(
                    claim,
                    qt,
                    f"{relpath} imports PyQt5 first, which silently disables "
                    "every onnxruntime backend",
                )

    def test_claiming_twice_is_harmless(self):
        """It runs from several entry points, which can share one process."""
        from util import msvc_runtime

        msvc_runtime.prepare()
        self.assertEqual(
            msvc_runtime.prepare(), [],
            "a second call re-claimed the runtime instead of doing nothing",
        )


class TestSuitePartitionTests(unittest.TestCase):
    """Optional ImageTL installs must not change the core/full suites."""

    def test_imagetl_modules_and_skips_share_the_optional_profile(self):
        from scripts import run_test_suite

        cases = {
            "test_imagetools.GeometryTests.test_box_coerces_numpy_integers": "imagetl",
            "test_imagetools_render.PaintTests.test_flat_background": "imagetl",
            "test_image_text_editor.GateTests.test_the_later_steps_start_shut": "imagetl",
            "unittest.loader.ModuleSkipped.test_imagetools": "imagetl",
            "unittest.loader.ModuleSkipped.test_imagetools_render": "imagetl",
            "unittest.loader.ModuleSkipped.test_image_text_editor": "imagetl",
            "test_evaluation.EvaluationManifestTests.test_default_corpus": "integration",
            "test_version_update.GitVersionUpdateTests.test_bootstrap": "integration",
            "test_version_update.VersionUpdateUITests.test_prepare_card": "extended",
            "test_workflow_ui.WorkflowShellTests.test_vertical_step_rail": "extended",
            "test_translation_cache.CacheTests.test_round_trip": "core",
        }
        for test_id, expected in cases.items():
            with self.subTest(test_id=test_id):
                self.assertEqual(run_test_suite._test_group_for_id(test_id), expected)

        with patch.object(
            run_test_suite.unittest.defaultTestLoader,
            "loadTestsFromNames",
            return_value=unittest.TestSuite(),
        ) as load:
            run_test_suite.load_suite("full")
            full_modules = set(load.call_args.args[0])
            self.assertIn("test_evaluation", full_modules)
            self.assertTrue(
                full_modules.isdisjoint(run_test_suite.IMAGETL_TEST_MODULES)
            )

            run_test_suite.load_suite("imagetl")
            self.assertEqual(
                load.call_args.args[0], list(run_test_suite.IMAGETL_TEST_MODULES)
            )

        tests_root = Path(__file__).resolve().parent
        core_modules = set(
            run_test_suite._module_names_for_profile(tests_root, "core")
        )
        integration_modules = set(
            run_test_suite._module_names_for_profile(tests_root, "integration")
        )
        self.assertTrue(
            core_modules.isdisjoint({"test_evaluation", "test_version_update"})
        )
        self.assertEqual(
            integration_modules,
            {"test_evaluation", "test_version_update"},
        )

        class NamedTest(unittest.TestCase):
            def __init__(self, test_id):
                super().__init__()
                self._test_id = test_id

            def id(self):
                return self._test_id

        grouped_ids = {
            "test_translation_cache.CacheTests.test_round_trip": "core",
            "test_evaluation.EvaluationManifestTests.test_default_corpus": "integration",
            "test_version_update.VersionUpdateUITests.test_prepare_card": "extended",
            "test_imagetools.GeometryTests.test_box": "imagetl",
        }

        def selected_ids(profile):
            discovered = unittest.TestSuite(
                NamedTest(test_id) for test_id in grouped_ids
            )
            with patch.object(
                run_test_suite.unittest.defaultTestLoader,
                "loadTestsFromNames",
                return_value=discovered,
            ):
                return {
                    test.id()
                    for test in run_test_suite._iter_tests(
                        run_test_suite.load_suite(profile)
                    )
                }

        for profile in ("core", "integration", "extended", "imagetl"):
            with self.subTest(profile=profile):
                self.assertEqual(
                    selected_ids(profile),
                    {
                        test_id
                        for test_id, group in grouped_ids.items()
                        if group == profile
                    },
                )
        self.assertEqual(
            selected_ids("full"),
            {
                test_id
                for test_id, group in grouped_ids.items()
                if group != "imagetl"
            },
        )

        timings = run_test_suite._module_timings(
            [
                (0.2, "test_example.Case.test_one"),
                (0.3, "test_example.Case.test_two"),
                (0.1, "test_other.Case.test_one"),
            ]
        )
        self.assertEqual(
            [(module_name, count) for _elapsed, module_name, count in timings],
            [("test_example", 2), ("test_other", 1)],
        )
        self.assertAlmostEqual(timings[0][0], 0.5)
        self.assertAlmostEqual(timings[1][0], 0.1)
        self.assertEqual(
            run_test_suite._module_budget_seconds("core", "test_other"),
            run_test_suite.DEFAULT_MODULE_BUDGETS_SECONDS["core"],
        )
        self.assertEqual(
            run_test_suite._module_budget_seconds(
                "integration", "test_version_update"
            ),
            15.0,
        )


class WiringTests(unittest.TestCase):
    """The manifest has to agree with the code that consumes it."""

    def test_the_paths_match_where_inpaint_actually_looks(self):
        try:
            from util.imagetools import inpaint
        except ImportError:
            self.skipTest("semi-manual image extras are not installed")
        self.assertEqual(resmod.MODEL_DIR, inpaint.MODEL_DIR)
        self.assertEqual(resmod.LIB_DIR, inpaint.LIB_DIR)

    def test_every_model_lands_where_its_backend_expects_it(self):
        try:
            from util.imagetools import inpaint
        except ImportError:
            self.skipTest("semi-manual image extras are not installed")
        for key, spec in inpaint.MODELS.items():
            with self.subTest(key):
                self.assertEqual(resmod.get(key).dest.name, spec.filename)

    def test_the_unpacked_library_names_match_what_the_loader_hunts_for(self):
        try:
            from util.imagetools import inpaint
        except ImportError:
            self.skipTest("semi-manual image extras are not installed")
        self.assertEqual(
            set(resmod.get("patchmatch").proof), set(inpaint.PATCHMATCH_NAMES)
        )


if __name__ == "__main__":
    unittest.main()
