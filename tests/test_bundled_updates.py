"""Integration tests for bundled-only utility updates and tool-only auto-update checks.

These tests use temporary directories and mocks — no live network or GUI window.
They guard the security model: third-party utilities must not fetch upstream unless
a maintainer explicitly uses --force / --refresh-offline / --refresh-all.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from util.wolfdawn import WolfDawnError, bundled_binary_path, ensure_wolf_binary

_REPO_ROOT = Path(__file__).resolve().parents[1]

# Shipped with tool updates from the git archive. Keep in sync with .gitignore
# exceptions under data/ — ignored files never appear in update zips.
_SHIPPED_DATA_FILES = (
    "data/translation_contexts.json",
    "data/skills/system.md",
    "data/skills/project_setup.md",
    "data/skills/localization_investigation.md",
    "data/skills/wrap_config.md",
    "data/skills/plugin_translation.md",
    "data/skills/ace_script_translation.md",
    "data/skills/rpgmaker_translation_qa.md",
    "data/skills/evaluation_csv_review.md",
    "data/skills/image_translation.md",
    "data/skills/risky_codes.md",
    "data/skills/wolf_speakers.md",
    "data/skills/wolf_precheck_repair.md",
    "data/skills/post_update_translation.md",
    "data/skills/build-game-walkthrough/SKILL.md",
    "data/skills/build-game-walkthrough/agents/openai.yaml",
    "data/skills/build-game-walkthrough/assets/walkthrough-shell.html",
    "data/skills/build-game-walkthrough/references/validation-evidence.md",
    "data/skills/build-game-walkthrough/references/walkthrough-design.md",
    "data/skills/build-game-walkthrough/scripts/index_rpgmaker_dependencies.py",
    "data/skills/build-game-walkthrough/scripts/validate_walkthrough.py",
    "data/help/index.json",
    "data/help/00-welcome.md",
    "data/help/01-git-setup.md",
    "data/help/02-ai-helper.md",
    "data/help/07-common-words.md",
    "data/help/08-problems-resuming.md",
    "data/help/09-backups-recovery.md",
    "data/help/10-playtest-checklist.md",
    "data/help/images/configuration-api.png",
    "data/help/images/workflow-project.png",
    "data/help/images/workflow-setup.png",
    "data/help/images/workflow-translate.png",
    "data/help/images/workflow-export.png",
    "data/help/images/workflow-rewrap.png",
    "data/glossary_base.txt",
    "data/sfx_reference/j_ono.json",
    "data/sfx_reference/LICENSE.md",
    "data/sfx_reference/SOURCE.md",
)


class UpdateThreadInstallFilterTests(unittest.TestCase):
    """Tool update must refresh shipped data/ assets while protecting user state."""

    def test_installs_translation_contexts_and_skills(self):
        from gui.main import UpdateThread

        for rel in (
            *_SHIPPED_DATA_FILES,
            ".git_archival.txt",
            "gui/main.py",
            "gameupdate/GameUpdate.bat",
            "gameupdate/gameupdate/patch.ps1",
        ):
            with self.subTest(rel=rel):
                self.assertTrue(UpdateThread.should_install(Path(rel)))

    def test_skips_user_local_data_and_workdir(self):
        from gui.main import UpdateThread

        for rel in (
            "data/vocab.txt",
            "data/last_update_sha.txt",
            "data/wolf_speakers.json",
            "data/wolf_safe_notes.json",
            "data/api_keys.json",
            ".env",
            "venv/pyvenv.cfg",
            "log/translations.txt",
            "files/Map001.json",
            "translated/Map001.json",
            ".agents/skills/shipped-data-assets/SKILL.md",
            ".codex/config.toml",
            ".cursor/rules/project.mdc",
            ".github/workflows/tests.yml",
            ".vscode/settings.json",
        ):
            with self.subTest(rel=rel):
                self.assertFalse(UpdateThread.should_install(Path(rel)))

    def test_preserves_archive_metadata_in_git_checkout(self):
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".git").mkdir()

            self.assertFalse(
                UpdateThread.should_install_to_root(
                    Path(".git_archival.txt"),
                    root,
                )
            )
            self.assertTrue(
                UpdateThread.should_install_to_root(Path("gui/main.py"), root)
            )

    def test_preserves_archive_metadata_with_git_file(self):
        """Linked worktrees and submodules use a .git file, not a directory."""
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")

            self.assertFalse(
                UpdateThread.should_install_to_root(
                    Path(".git_archival.txt"),
                    root,
                )
            )

    def test_installs_archive_metadata_outside_git_checkout(self):
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)

            self.assertTrue(
                UpdateThread.should_install_to_root(
                    Path(".git_archival.txt"),
                    root,
                )
            )


class UpdateThreadArchiveRootTests(unittest.TestCase):
    """Gitea zips nest files under a single top folder (repo display name)."""

    def test_prefers_configured_archive_root(self):
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            preferred = base / UpdateThread.ARCHIVE_ROOT
            preferred.mkdir()
            (base / "other").mkdir()
            self.assertEqual(UpdateThread.resolve_archive_root(base), preferred)

    def test_falls_back_to_single_subdirectory(self):
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            only = base / "renamed-repo-folder"
            only.mkdir()
            (only / "gui").mkdir()
            (only / "gui" / "main.py").write_text("# ok", encoding="utf-8")
            self.assertEqual(UpdateThread.resolve_archive_root(base), only)

    def test_raises_when_archive_root_missing(self):
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            (base / "a").mkdir()
            (base / "b").mkdir()
            with self.assertRaises(FileNotFoundError):
                UpdateThread.resolve_archive_root(base)

    def test_stale_archive_root_name_would_have_installed_nothing(self):
        """Regression: wrong ARCHIVE_ROOT used to report success with 0 files."""
        from gui.main import UpdateThread

        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            real = base / "dazedtl"
            real.mkdir()
            (real / "gui").mkdir()
            (real / "gui" / "main.py").write_text("print('hi')\n", encoding="utf-8")
            (real / "data").mkdir()
            (real / "data" / "help").mkdir()
            (real / "data" / "help" / "00-welcome.md").write_text("# hi\n", encoding="utf-8")

            # Old hardcoded slug before the DazedTL rebrand.
            stale = base / "dazed-mtl-tool"
            self.assertFalse(stale.exists())
            self.assertEqual(list(stale.rglob("*")), [])

            extracted = UpdateThread.resolve_archive_root(base)
            install_files = [
                src
                for src in extracted.rglob("*")
                if src.is_file() and UpdateThread.should_install(src.relative_to(extracted))
            ]
            self.assertGreaterEqual(len(install_files), 2)

class ShippedDataTrackingTests(unittest.TestCase):
    """Guide/help and other shipped data/ files must be git-trackable.

    Tool updates download a branch archive from git. Anything matched by
    .gitignore is omitted from that archive, so Guide markdown and index.json
    would never reach end users.
    """

    def test_shipped_data_files_exist(self):
        for rel in _SHIPPED_DATA_FILES:
            with self.subTest(rel=rel):
                self.assertTrue(
                    (_REPO_ROOT / rel).is_file(),
                    f"missing shipped asset {rel}",
                )

    def test_help_dir_markdown_matches_index(self):
        import json
        import re

        help_dir = _REPO_ROOT / "data" / "help"
        index = json.loads((help_dir / "index.json").read_text(encoding="utf-8"))
        for entry in index:
            if entry.get("type") == "group":
                self.assertTrue(entry.get("title"))
                self.assertNotIn("file", entry)
                continue
            rel = entry.get("file")
            self.assertTrue(rel, f"help page entry has no file: {entry!r}")
            with self.subTest(file=rel):
                self.assertTrue(
                    (help_dir / rel).is_file(),
                    f"data/help/index.json references missing {rel}",
                )
        for page in help_dir.glob("*.md"):
            source = page.read_text(encoding="utf-8")
            for image_ref in re.findall(r"!\[[^]]*\]\((images/[^)\s]+)\)", source):
                with self.subTest(page=page.name, image=image_ref):
                    self.assertTrue(
                        (help_dir / image_ref).is_file(),
                        f"{page.name} references missing Guide image {image_ref}",
                    )

    def test_shipped_data_files_are_not_gitignored(self):
        help_dir = _REPO_ROOT / "data" / "help"
        rels = list(_SHIPPED_DATA_FILES)
        for path in sorted(help_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel not in rels:
                rels.append(rel)

        for rel in rels:
            with self.subTest(rel=rel):
                # Plain check-ignore (no -v): exit 0 = ignored, 1 = not ignored.
                # -v also reports negation rules with exit 0, which is a false positive.
                result = subprocess.run(
                    ["git", "check-ignore", "--", rel],
                    cwd=_REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertNotEqual(
                    result.returncode,
                    0,
                    f"{rel} is gitignored; "
                    "add a !.gitignore exception under data/ so tool updates include it",
                )

    def test_runtime_evaluation_prompts_are_gitignored(self):
        result = subprocess.run(
            [
                "git", "check-ignore", "--",
                "log/evaluations/example-run/review_system_prompt.md",
            ],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            "runtime evaluation prompts must not be included by git add/archive",
        )


class SourceArchiveMetadataTests(unittest.TestCase):
    """Source archives identify their commit and omit development metadata."""

    def test_archival_info_is_configured_for_sha_expansion(self):
        archival_info = _REPO_ROOT / ".git_archival.txt"
        self.assertTrue(archival_info.is_file())
        self.assertIn("$Format:%H$", archival_info.read_text(encoding="utf-8"))

        ignored = subprocess.run(
            ["git", "check-ignore", "--", ".git_archival.txt"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(ignored.returncode, 0)

        result = subprocess.run(
            ["git", "check-attr", "export-subst", "--", ".git_archival.txt"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("export-subst: set", result.stdout)

    def test_development_directories_are_export_ignored(self):
        for rel in (".agents", ".codex", ".cursor", ".github", ".vscode"):
            with self.subTest(rel=rel):
                result = subprocess.run(
                    ["git", "check-attr", "export-ignore", "--", rel],
                    cwd=_REPO_ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0)
                self.assertIn("export-ignore: set", result.stdout)


class CheckToolUpdateTests(unittest.TestCase):
    """Tool update checks runtime state, then source-archive commit metadata."""

    def test_returns_sha_when_remote_differs(self):
        with tempfile.TemporaryDirectory() as raw:
            sha_file = Path(raw) / "last_update_sha.txt"
            sha_file.write_text("aaaaaaaa", encoding="utf-8")
            from gui.main import UpdateThread, check_tool_update

            with patch.object(UpdateThread, "SHA_FILE", str(sha_file)):
                with patch.object(
                    UpdateThread, "fetch_latest_sha", return_value="bbbbbbbb"
                ):
                    self.assertEqual(check_tool_update(), "bbbbbbbb")

    def test_returns_none_when_up_to_date(self):
        with tempfile.TemporaryDirectory() as raw:
            sha_file = Path(raw) / "last_update_sha.txt"
            sha_file.write_text("same1234", encoding="utf-8")
            from gui.main import UpdateThread, check_tool_update

            with patch.object(UpdateThread, "SHA_FILE", str(sha_file)):
                with patch.object(
                    UpdateThread, "fetch_latest_sha", return_value="same1234"
                ):
                    self.assertIsNone(check_tool_update())

    def test_archive_sha_prevents_false_update_on_first_launch(self):
        archived_sha = "a" * 40
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            sha_file = base / "missing-last-update-sha.txt"
            archive_file = base / ".git_archival.txt"
            archive_file.write_text(f"node: {archived_sha}\n", encoding="utf-8")
            from gui.main import UpdateThread, check_tool_update

            with patch.multiple(
                UpdateThread,
                SHA_FILE=str(sha_file),
                ARCHIVE_SHA_FILE=str(archive_file),
            ):
                with patch.object(
                    UpdateThread, "fetch_latest_sha", return_value=archived_sha
                ):
                    self.assertIsNone(check_tool_update())

    def test_unexpanded_archive_sha_is_ignored(self):
        latest_sha = "b" * 40
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            archive_file = base / ".git_archival.txt"
            archive_file.write_text("node: $Format:%H$\n", encoding="utf-8")
            from gui.main import UpdateThread, check_tool_update

            with patch.multiple(
                UpdateThread,
                SHA_FILE=str(base / "missing-last-update-sha.txt"),
                ARCHIVE_SHA_FILE=str(archive_file),
            ):
                with patch.object(
                    UpdateThread, "fetch_latest_sha", return_value=latest_sha
                ):
                    self.assertEqual(check_tool_update(), latest_sha)

    def test_fetch_failure_is_not_reported_as_up_to_date(self):
        from gui.main import UpdateThread, check_tool_update

        with patch.object(
            UpdateThread, "fetch_latest_sha", side_effect=OSError("offline")
        ):
            with self.assertRaisesRegex(OSError, "offline"):
                check_tool_update()

    def test_update_sources_fall_back_in_priority_order(self):
        from gui.main import UpdateCandidate, UpdateThread

        latest_sha = "b" * 40
        sources = UpdateThread.UPDATE_SOURCES
        self.assertEqual(
            UpdateThread.branch_api_url(sources[2]),
            "https://git.dazedtl.dev/api/v1/repos/dazed/DazedTL/branches/main",
        )
        self.assertEqual(
            UpdateThread.archive_zip_url(sources[2], latest_sha),
            f"https://git.dazedtl.dev/dazed/DazedTL/archive/{latest_sha}.zip",
        )
        scenarios = (
            ([OSError("primary unavailable"), latest_sha], sources[1]),
            (
                [
                    OSError("primary unavailable"),
                    OSError("GitHub unavailable"),
                    latest_sha,
                ],
                sources[2],
            ),
        )
        for side_effect, expected_source in scenarios:
            with self.subTest(source=expected_source.name):
                with patch.object(
                    UpdateThread,
                    "_fetch_source_sha",
                    side_effect=side_effect,
                ) as fetch:
                    candidate = UpdateThread.fetch_latest_sha()

                self.assertIsInstance(candidate, UpdateCandidate)
                self.assertEqual(candidate, latest_sha)
                self.assertIs(candidate.source, expected_source)
                attempted = [item.args[0] for item in fetch.call_args_list]
                expected_count = sources.index(expected_source) + 1
                self.assertEqual(attempted, list(sources[:expected_count]))

        with patch.object(
            UpdateThread,
            "_fetch_source_sha",
            side_effect=[OSError("offline")] * len(sources),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "GitHub.*GitGud.*git.dazedtl.dev",
            ):
                UpdateThread.fetch_latest_sha()

    def test_archive_fallback_requires_the_same_commit(self):
        from gui.main import UpdateCandidate, UpdateThread

        class Response:
            headers = {}

            def __init__(self):
                self._chunks = [b"verified archive", b""]

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size=-1):
                return self._chunks.pop(0)

        latest_sha = "c" * 40
        sources = UpdateThread.UPDATE_SOURCES
        candidate = UpdateCandidate(latest_sha, sources[0])
        worker = UpdateThread()
        with tempfile.TemporaryDirectory() as raw:
            destination = Path(raw) / "update.zip"
            with (
                patch(
                    "gui.main.urllib.request.urlopen",
                    side_effect=[OSError("primary archive unavailable"), Response()],
                ) as urlopen,
                patch.object(
                    worker,
                    "_fetch_source_sha",
                    return_value=latest_sha,
                ) as fetch_sha,
            ):
                worker._download_archive(destination, candidate)

            self.assertEqual(destination.read_bytes(), b"verified archive")
            fetch_sha.assert_called_once_with(sources[1])
            attempted_urls = [call.args[0].full_url for call in urlopen.call_args_list]
            self.assertEqual(
                attempted_urls,
                [
                    UpdateThread.archive_zip_url(sources[0], latest_sha),
                    UpdateThread.archive_zip_url(sources[1], latest_sha),
                ],
            )

            with (
                patch(
                    "gui.main.urllib.request.urlopen",
                    side_effect=OSError("primary archive unavailable"),
                ) as urlopen,
                patch.object(
                    worker,
                    "_fetch_source_sha",
                    return_value="d" * 40,
                ),
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "has not synchronized",
                ):
                    worker._download_archive(destination, candidate)
            urlopen.assert_called_once()


class AceBundledOnlyTests(unittest.TestCase):
    def _ace_paths(self, base: Path) -> dict:
        offline = base / "offline"
        offline.mkdir(parents=True, exist_ok=True)
        return {
            "OFFLINE_DIR": offline,
            "RV2JSON_LOCAL": base / "RV2JSON.exe",
            "DECRYPTER_LOCAL": base / "RPGMakerDecrypter-cli.exe",
            "DECRYPTER_LEGACY": base / "RPGMakerDecrypter.exe",
            "VERSION_FILE": base / ".tools_version.json",
        }

    def test_seed_overwrites_stale_runtime_copy(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)
            (paths["OFFLINE_DIR"] / "RV2JSON.exe").write_bytes(b"OFFLINE")
            paths["RV2JSON_LOCAL"].write_bytes(b"STALE")

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                ace._seed_from_offline(paths["RV2JSON_LOCAL"], "RV2JSON.exe", None)
            self.assertEqual(paths["RV2JSON_LOCAL"].read_bytes(), b"OFFLINE")

    def test_ensure_rv2json_does_not_contact_upstream(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)
            (paths["OFFLINE_DIR"] / "RV2JSON.exe").write_bytes(b"OK")

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(
                    ace,
                    "_rv2json_upstream",
                    side_effect=AssertionError("must not fetch upstream"),
                ):
                    self.assertTrue(ace.ensure_rv2json(force=False))
            self.assertEqual(paths["RV2JSON_LOCAL"].read_bytes(), b"OK")

    def test_ensure_rv2json_fails_when_nothing_bundled(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(
                    ace,
                    "_rv2json_upstream",
                    side_effect=AssertionError("must not fetch upstream"),
                ):
                    self.assertFalse(ace.ensure_rv2json(force=False))

    def test_force_delegates_to_upstream_fetch(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._ace_paths(base)

            import util.ace.update_tools as ace

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(ace, "_fetch_rv2json_upstream", return_value=True) as fetch:
                    self.assertTrue(ace.ensure_rv2json(force=True))
            fetch.assert_called_once()


class ForgeBundledOnlyTests(unittest.TestCase):
    def _forge_paths(self, base: Path, *, with_plugins: bool) -> dict:
        upstream = base / "upstream"
        upstream.mkdir(parents=True, exist_ok=True)
        plugin_body = b"// forge plugin\n"
        paths = {
            "UPSTREAM_DIR": upstream,
            "VERSION_FILE": base / ".forge_version.json",
        }
        if with_plugins:
            for name in ("Forge_MV.js", "Forge_MZ.js"):
                (upstream / name).write_bytes(plugin_body)
        return paths

    def test_ensure_forge_plugins_uses_canonical_bundle_without_copying(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=True)

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                with patch.object(
                    forge,
                    "_upstream_commit",
                    side_effect=AssertionError("must not fetch upstream"),
                ):
                    with patch.object(
                        forge,
                        "refresh_forge_plugins",
                        side_effect=AssertionError("must not refresh upstream"),
                    ):
                        self.assertTrue(forge.ensure_forge_plugins(force=False))
            self.assertFalse((base / "Forge_MV.js").exists())
            self.assertFalse((base / "Forge_MZ.js").exists())

    def test_ensure_forge_plugins_fails_when_missing_everywhere(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=False)

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                self.assertFalse(forge.ensure_forge_plugins(force=False))

    def test_force_calls_refresh_forge_plugins(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            paths = self._forge_paths(base, with_plugins=True)

            import util.forge.update_tools as forge

            with patch.multiple("util.forge.update_tools", **paths):
                with patch.object(forge, "refresh_forge_plugins", return_value=True) as refresh:
                    self.assertTrue(forge.ensure_forge_plugins(force=True))
            refresh.assert_called_once()


class WolfBundledOnlyTests(unittest.TestCase):
    def test_ensure_wolf_binary_uses_bundled_path(self):
        with tempfile.TemporaryDirectory() as raw:
            wolf = Path(raw) / "wolf"
            wolf.write_bytes(b"\x7fELF")
            with patch("util.wolfdawn.bundled_binary_path", return_value=wolf):
                self.assertEqual(ensure_wolf_binary(), wolf)

    def test_ensure_wolf_binary_makes_bundled_copy_executable(self):
        with tempfile.TemporaryDirectory() as raw:
            wolf = Path(raw) / "wolf"
            wolf.write_bytes(b"\x7fELF")
            wolf.chmod(0o644)
            with patch("util.wolfdawn.bundled_binary_path", return_value=wolf):
                with patch("util.wolfdawn._platform_dir", return_value="linux"):
                    ensure_wolf_binary()
            self.assertTrue(wolf.stat().st_mode & 0o111)

    def test_ensure_wolf_binary_raises_when_missing(self):
        missing = Path("/nonexistent/wolf/missing")
        with patch("util.wolfdawn.bundled_binary_path", return_value=missing):
            with self.assertRaises(WolfDawnError) as ctx:
                ensure_wolf_binary()
        self.assertIn("Update DazedTL", str(ctx.exception))

    def test_ensure_wolf_binary_never_downloads(self):
        missing = Path("/nonexistent/wolf/missing")
        with patch("util.wolfdawn.bundled_binary_path", return_value=missing):
            with patch(
                "util.wolfdawn.download_wolf_binary",
                side_effect=AssertionError("must not download at runtime"),
            ):
                with self.assertRaises(WolfDawnError):
                    ensure_wolf_binary()

    def test_ensure_wolfdawn_binary_does_not_refresh_by_default(self):
        import util.wolfdawn.update_tools as wd_update

        wolf = bundled_binary_path()
        if not wolf.is_file():
            self.skipTest(f"no bundled wolf binary at {wolf}")

        with patch.object(
            wd_update,
            "refresh_wolfdawn_binary",
            side_effect=AssertionError("must not refresh upstream"),
        ):
            self.assertTrue(wd_update.ensure_wolfdawn_binary(force=False))

    def test_ensure_wolfdawn_binary_force_calls_refresh(self):
        import util.wolfdawn.update_tools as wd_update

        with patch.object(wd_update, "refresh_wolfdawn_binary", return_value=True) as refresh:
            with patch.object(wd_update, "bundled_binary_path", return_value=Path("/wolf")):
                with patch("pathlib.Path.is_file", return_value=True):
                    self.assertTrue(wd_update.ensure_wolfdawn_binary(force=True))
        refresh.assert_called_once()


class MaintainerRefreshTests(unittest.TestCase):
    """Maintainer CLI paths should still wire upstream fetch when explicitly invoked."""

    def test_refresh_offline_bundle_downloads_into_offline_dir(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            offline = base / "offline"
            offline.mkdir()

            import util.ace.update_tools as ace

            paths = {
                "OFFLINE_DIR": offline,
                "RV2JSON_LOCAL": base / "RV2JSON.exe",
                "DECRYPTER_LOCAL": base / "RPGMakerDecrypter-cli.exe",
                "DECRYPTER_LEGACY": base / "RPGMakerDecrypter.exe",
                "VERSION_FILE": base / ".tools_version.json",
            }

            def fake_download(url: str, dest: Path) -> None:
                dest.write_bytes(b"downloaded")

            with patch.multiple("util.ace.update_tools", **paths):
                with patch.object(
                    ace,
                    "_rv2json_upstream",
                    return_value=("sha1", "https://example/rv2json"),
                ):
                    with patch.object(
                        ace,
                        "_decrypter_upstream",
                        return_value=("v1", "https://example/dec"),
                    ):
                        with patch.object(ace, "_download", side_effect=fake_download):
                            self.assertTrue(ace.refresh_offline_bundle(log_fn=None))

            self.assertEqual((offline / "RV2JSON.exe").read_bytes(), b"downloaded")
            self.assertEqual(
                (offline / ace.DECRYPTER_ASSET).read_bytes(), b"downloaded"
            )

    def test_refresh_forge_plugins_installs_downloaded_bytes(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw)
            upstream = base / "upstream"
            upstream.mkdir()

            import util.forge.update_tools as forge

            paths = {
                "UPSTREAM_DIR": upstream,
                "VERSION_FILE": base / ".forge_version.json",
            }
            plugin = b"// downloaded forge\n"

            with patch.multiple("util.forge.update_tools", **paths):
                with patch.object(forge, "_upstream_commit", return_value="abc123"):
                    with patch.object(forge, "_fetch_plugins", return_value=plugin):
                        self.assertTrue(forge.refresh_forge_plugins(log_fn=None))

            # The unified bundle is stored as MZ and used by both engines. The
            # legacy MV fallback is not overwritten by a maintainer refresh.
            self.assertEqual((upstream / "Forge_MZ.js").read_bytes(), plugin)
            self.assertFalse((base / "Forge_MV.js").exists())
            self.assertFalse((upstream / "Forge_MV.js").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
