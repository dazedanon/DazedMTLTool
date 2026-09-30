"""Desktop contracts: source preservation, recovery, and bounded paid calls.

Existing RPG Maker QA tests cover the shared evidence/token checks. These cases
exercise the new service boundary with tiny generated games and fake providers.
"""

import json
import io
import base64
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

from desktop.backend.budget import BudgetLedger, MAX_PROMPT_BYTES, MODEL
from desktop.backend.project import atomic_json, extract_records, snapshot, digest
from desktop.backend.service import WorkspaceService, LunaProvider
from desktop.backend.images import ImageStore


def game(root):
    (root / "data").mkdir(parents=True)
    (root / "js").mkdir()
    atomic_json(root / "data/System.json", {"gameTitle": "テスト"})
    atomic_json(root / "data/Items.json", [None, *({"id": i, "name": f"薬{i}", "note": "スクリプト保持"} for i in range(1, 10))])
    atomic_json(root / "data/Map001.json", {"events": [None, {"pages": [{"list": [
        {"code": 401, "parameters": ["\\C[2]こんにちは。"]},
        {"code": 355, "parameters": ["危険なスクリプト"]},
    ]}]}]})
    (root / "js/plugins.js").write_text("var $plugins = [];", encoding="utf-8")
    return root


class DesktopBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = game(self.root / "game")
        self.service = WorkspaceService(self.root / "workspace")
        self.environment = patch.dict(os.environ, {"BATCH_PHASE": "", "DAZED_GAME_ROOT": "", "DAZED_GLOSSARY_PATH": ""})
        self.environment.start()

    def tearDown(self):
        self.service.close()
        self.environment.stop()
        self.temporary.cleanup()

    def imported(self):
        return self.service.import_project(str(self.source), False)["project"]

    def finish(self):
        self.service.worker.join(timeout=3)
        self.assertFalse(self.service.worker.is_alive())

    def test_snapshot_selection_review_and_export_preserve_source(self):
        before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        project = self.imported()
        self.assertNotIn("危険なスクリプト", [r["source"] for r in project["records"]])
        self.assertNotIn("スクリプト保持", [r["source"] for r in project["records"]])
        selected = project["records"][:2]
        job = self.service.start(project["id"], [r["id"] for r in selected], "offline")
        self.finish()
        with self.assertRaises(ValueError):
            self.service.export(job["id"])
        for record in selected:
            self.service.review(job["id"], record["id"], "Potion")
        exported = self.service.export(job["id"])
        data = json.loads((Path(exported["path"]) / "data/Items.json").read_text())
        self.assertEqual(data[1]["name"], "Potion")
        self.assertEqual(data[3]["name"], "薬3")
        self.assertEqual(data[1]["note"], "スクリプト保持")
        self.assertEqual(before, {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()})

        # The existing image tests cover rendering pixels. This boundary checks
        # revision-bound approval and immutable import/export with a fake worker.
        from PIL import Image
        png = io.BytesIO()
        Image.new("RGBA", (40, 20), "white").save(png, format="PNG")
        image = self.service.image_import(project["id"], "menu.png", "data:image/png;base64," + base64.b64encode(png.getvalue()).decode())
        block = {"id": "label", "box": [0, 0, 40, 20], "target": "Play"}
        image = self.service.image_save(project["id"], image["id"], 0, [block], [])
        store = ImageStore(self.service.root)
        operation = self.root / "image-operation"
        operation.mkdir()
        for filename in ("preview.png", "base.png", "overlay.png"):
            (operation / filename).write_bytes(png.getvalue())
        atomic_json(operation / "result.json", {"blocks": image["blocks"], "notes": [{"block_id": "label", "ok": True, "message": "Fitted"}]})
        with patch("desktop.backend.images.subprocess.Popen", return_value=SimpleNamespace(returncode=0, poll=lambda: 0)):
            store.render(project["id"], image["id"], operation, lambda: False, self.service.lock)
        with self.assertRaisesRegex(ValueError, "Approve"):
            self.service.image_export(project["id"], image["id"])
        self.service.image_approve(project["id"], image["id"], 1)
        output = self.service.image_export(project["id"], image["id"])
        self.assertEqual((Path(output["path"]) / "menu.png").read_bytes(), png.getvalue())
        folder = store.folder(project["id"], image["id"])
        self.assertEqual((folder / "source.bin").read_bytes(), png.getvalue())
        (folder / "preview.png").write_bytes(b"changed after approval")
        with self.assertRaisesRegex(ValueError, "changed after approval"):
            self.service.image_export(project["id"], image["id"])
        block["target"] = "Continue"
        changed = self.service.image_save(project["id"], image["id"], 1, [block], [])
        self.assertIsNone(changed["approved_revision"])
        with self.assertRaisesRegex(ValueError, "Render"):
            self.service.image_approve(project["id"], image["id"], changed["revision"])
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            self.service.image_save(project["id"], image["id"], 1, [block], [])
        block["box"] = [39, 0, 40, 20]
        with self.assertRaisesRegex(ValueError, "Region width"):
            self.service.image_save(project["id"], image["id"], changed["revision"], [block], [])
        block.update(box=[0, 0, 40, 20], target="Latest edit")
        def edit_during_render(*args, **kwargs):
            self.service.image_save(project["id"], image["id"], changed["revision"], [block], [])
            return SimpleNamespace(returncode=0, poll=lambda: 0)
        with patch("desktop.backend.images.subprocess.Popen", side_effect=edit_during_render):
            result = store.render(project["id"], image["id"], operation, lambda: False, self.service.lock)
        self.assertTrue(result["stale"])
        self.assertEqual(store.read(project["id"], image["id"])["blocks"][0]["target"], "Latest edit")
        self.assertEqual(self.service.ledger.summary()["requests"], 0)

        # The same image document can bind to a portable job: saving one image
        # retains its neighbours, and a later external edit blocks a stale save.
        from desktop.backend.image_link import attach
        portable_root = self.root / "portable-images"
        portable_root.mkdir()
        (portable_root / "menu.png").write_bytes(png.getvalue())
        portable_path = portable_root / ".dazedtl/image_job.json"
        entry = {"image": "menu.png", "index": 0, "width": 40, "height": 20, "status": "confirmed",
                 "blocks": [{"id": "label", "box": [0, 0, 40, 20], "source": "Start", "target": "Play"}], "words": []}
        neighbour = {"image": "other.png", "blocks": [{"id": "other", "source": "Keep", "target": "Retain"}]}
        atomic_json(portable_path, {"format": "dazedtl-image-job", "version": 4, "images": [entry, neighbour]})
        linked_id = attach(store, project["id"], portable_root, entry)
        linked = store.read(project["id"], linked_id)
        values = linked["blocks"]
        values[0]["source"] = "Edited source"
        linked = store.save(project["id"], linked_id, linked["revision"], values, [])
        portable = json.loads(portable_path.read_text())
        self.assertEqual(portable["images"][1], neighbour)
        self.assertEqual(portable["images"][0]["status"], "needs_review")
        reviewed = store.review(project["id"], linked_id, linked["revision"], True)
        self.assertEqual(reviewed["status"], "confirmed")
        self.assertEqual(json.loads(portable_path.read_text())["images"][1], neighbour)
        portable["images"][0]["blocks"][0]["target"] = "External edit"
        atomic_json(portable_path, portable)
        values[0]["target"] = "Stale edit"
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            store.save(project["id"], linked_id, linked["revision"], values, [])
        self.assertEqual(json.loads(portable_path.read_text())["images"][0]["blocks"][0]["target"], "External edit")

        # Test the service boundary using the production output contract. The
        # desktop UI smoke test runs the actual engine in its own process.
        def finished_worker(job_dir, plan, completed, speakers, generation, provider, stopped, callback):
            native = json.loads((job_dir / "inputs/Items.json").read_text())
            native[1]["_original"] = {"name": native[1]["name"]}
            native[1]["name"] = "Potion1"
            atomic_json(job_dir / "translated/Items.json", native)
            callback({"event": "file_done", "file": "Items.json"})
            return {"status": "complete", "message": "Saved", "new_requests": 0}
        with patch("desktop.backend.rpgmaker.run_worker", side_effect=finished_worker):
            native_job = self.service.start_native(project["id"], ["Items.json"], phase="database")
            self.finish()
        self.assertEqual(self.service.jobs[native_job["id"]]["status"], "complete")
        page = self.service.review_page(native_job["id"])
        self.assertEqual(page["total"], 1)
        with self.assertRaises(ValueError):
            self.service.export(native_job["id"])
        self.service.review(native_job["id"], page["records"][0]["id"], "Healing Potion1")
        raw_output = self.service.root / "engines" / native_job["id"] / "translated/Items.json"
        self.assertEqual(json.loads(raw_output.read_text())[1]["name"], "Potion1")
        advanced = self.service.apply_reviewed(native_job["id"])
        self.assertIn("Items.json", advanced["project"]["working_files"])
        context = self.service.context(project["id"])
        self.assertIn("薬1 (Healing Potion1)", context["documents"]["glossary.txt"])
        self.assertIn("Items.json", self.service.native_preview(project["id"], ["Items.json"], phase="database")["working_files"])
        self.assertEqual(before, {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()})

    def test_wrong_scope_runtime_codes_and_changed_snapshot_block_actions(self):
        with self.assertRaisesRegex(ValueError, "separate folders"):
            self.service.import_project(str(self.root), False)
        atomic_json(self.source / "data/Actors.json", [None, {"id": 1, "name": "ノラ"}])
        project = self.imported()
        preview = self.service.native_preview(project["id"], ["Map001.json"], phase="dialogue")
        self.assertEqual(preview["dependencies"], ["Actors.json"])
        self.assertIn("Actors.json", preview["filenames"])
        for selected_files, phase, settings in ((["../Items.json"], "database", {}), (["Map001.json"], "database", {}), (["Items.json"], "database", {"CODE355655": True})):
            with self.subTest(files=selected_files, phase=phase), self.assertRaises(ValueError):
                self.service.native_preview(project["id"], selected_files, phase=phase, settings=settings)
        for identities, mode in (([], "offline"), (["foreign"], "offline"), ([project["records"][0]["id"]], "live")):
            with self.subTest(identities=identities, mode=mode), self.assertRaises(ValueError):
                self.service.preview(project["id"], identities, mode)
        record = next(r for r in project["records"] if r["category"] == "dialogue")
        job = self.service.start(project["id"], [record["id"]], "offline")
        self.finish()
        with self.assertRaisesRegex(ValueError, "runtime codes"):
            self.service.review(job["id"], record["id"], "Hello.")
        self.service.review(job["id"], record["id"], "\\C[2]Hello.")
        snap = self.service.root / "projects" / project["id"] / "source/data/Map001.json"
        snap.write_text("{}")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            self.service.export(job["id"])
        self.assertFalse((self.service.root / "builds").exists())

        manual = self.service._manual_service()
        inventory = manual.inspect(str(self.source / "data"), "RPG Maker MV/MZ")
        for selected, revision, mode in ((["../Items.json"], inventory["revision"], "estimate"),
                                         (["Items.json"], "stale", "estimate"),
                                         (["Items.json"], inventory["revision"], "translate")):
            with self.subTest(manual_mode=mode), self.assertRaises(ValueError):
                manual.start(inventory["source"], inventory["engine"], selected, revision, mode)
        # No worker launches for invalid scope, changed inputs, or disabled
        # provider execution, so none of these failures can spend money.
        self.assertFalse(manual.jobs)
        before = (self.source / "data/Items.json").read_bytes()
        with patch.object(manual, "_launch"):
            planned = manual.start(inventory["source"], inventory["engine"], ["Items.json"], inventory["revision"])
        folder = manual.folder(planned["id"])
        (folder / "plan.json").write_text("{}")
        with patch("desktop.backend.manual.subprocess.Popen") as spawn:
            manual._run(planned["id"], False)
        self.assertEqual(manual.jobs[planned["id"]]["status"], "failed")
        self.assertIn("plan changed", manual.jobs[planned["id"]]["message"])
        spawn.assert_not_called()
        self.assertEqual((self.source / "data/Items.json").read_bytes(), before)


    def test_stop_resume_restart_preserve_completed_chunks_and_frozen_guidance(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        class Provider:
            def translate(_self, identity, records, guidance):
                calls.append(([r["id"] for r in records], guidance))
                if len(calls) == 1:
                    entered.set()
                    if not release.wait(2):
                        raise ValueError("test synchronization timeout")
                return {r["id"]: "Potion" for r in records}
        self.service.provider_factory = lambda mode: Provider()
        project = self.imported()
        self.service.save_guidance(project["id"], "Original guidance")
        selected = [r["id"] for r in project["records"][:8]]
        job = self.service.start(project["id"], selected, "offline")
        self.assertTrue(entered.wait(2))
        self.service.stop(job["id"])
        release.set()
        self.finish()
        self.assertEqual(self.service.jobs[job["id"]]["status"], "stopped")
        self.assertEqual(len(self.service.jobs[job["id"]]["results"]), 4)
        self.service.close()
        self.service = WorkspaceService(self.root / "workspace", provider_factory=lambda mode: Provider())
        self.service.save_guidance(project["id"], "Changed guidance")
        self.service.resume(job["id"])
        self.finish()
        self.assertEqual(self.service.jobs[job["id"]]["status"], "complete")
        self.assertEqual(calls, [(selected[:4], "Original guidance"), (selected[4:], "Original guidance")])

        # The real parser is covered separately; simulate its pipe protocol to
        # check request caps and replay without spawning costly SDK imports.
        from desktop.backend import rpgmaker
        from desktop.backend.library import InstructionLibrary
        from util.paths import PROMPT_PATH, runtime_data_profile, runtime_data_file
        from util.skills import load_system_prompt, load_project_setup, ctx
        library = InstructionLibrary(self.service.root)
        original = library.get("skills/system.md")
        bundled = PROMPT_PATH.read_bytes()
        library.draft(original["name"], original["revision"], "Unapplied profile instruction")
        self.assertEqual(library.get(original["name"])["text"], original["text"])
        edited = library.save(original["name"], original["revision"], "Frozen profile instruction\n")
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            library.save(original["name"], original["revision"], "Stale edit")
        with runtime_data_profile(self.service.root):
            self.assertEqual(load_system_prompt(), edited["text"])
        with runtime_data_profile(self.root / "other-profile"):
            self.assertEqual(load_system_prompt(), original["text"])
        setup = library.get("skills/project_setup.md")
        with self.assertRaisesRegex(ValueError, "placeholders"):
            library.save(setup["name"], setup["revision"], "Dropped placeholders")
        library.save(setup["name"], setup["revision"], setup["text"] + "\nProfile setup rule.\n")
        with runtime_data_profile(self.service.root):
            self.assertIn("Profile setup rule.", load_project_setup("rpgmaker"))
        contexts = library.get("translation_contexts.json")
        context_value = json.loads(contexts["text"])
        context_value["names"]["npc"] = "Profile name in {language}."
        library.save(contexts["name"], contexts["revision"], json.dumps(context_value))
        from util.paths import TRANSLATION_CONTEXTS_PATH
        modified = TRANSLATION_CONTEXTS_PATH.stat().st_mtime_ns
        os.utime(self.service.root / "shared-data/translation_contexts.json", ns=(modified, modified))
        with runtime_data_profile(self.service.root):
            self.assertEqual(ctx("names.npc", language="English"), "Profile name in English.")
        with runtime_data_profile(self.root / "other-profile"):
            self.assertNotEqual(ctx("names.npc", language="English"), "Profile name in English.")
        context_value["names"]["npc"] = "Unknown {secret} placeholder"
        with self.assertRaisesRegex(ValueError, "placeholders"):
            library.save(contexts["name"], library.get(contexts["name"])["revision"], json.dumps(context_value))
        job_dir = self.root / "controller"
        plan = rpgmaker.create_plan(self.service.projects[project["id"]], self.service.root / "projects" / project["id"],
                                   job_dir, ["Items.json"], "database", {}, 1, mode="live", workspace=self.service.root)
        library.save(edited["name"], edited["revision"], "Later profile instruction\n")
        rpgmaker.prepare_workspace(self.service.root / "projects" / project["id"], job_dir, plan, lambda: False)
        self.assertEqual((job_dir / "context/system.md").read_text(), "Frozen profile instruction\n")
        with runtime_data_profile(self.service.root):
            self.assertEqual(runtime_data_file(job_dir / "context/system.md"), job_dir / "context/system.md")
        self.assertEqual(PROMPT_PATH.read_bytes(), bundled)
        restored = library.get(edited["name"])
        self.assertFalse(library.save(restored["name"], restored["revision"], restored["default"])["customized"])
        self.assertFalse(library.get(edited["name"])["draft"])
        outside = self.root / "outside.md"
        outside.write_text("Keep outside content")
        (self.service.root / "shared-data/skills/system.md").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "symbolic links"):
            library.get("skills/system.md")
        self.assertEqual(outside.read_text(), "Keep outside content")
        (self.service.root / "shared-data/skills/system.md").unlink()
        first = {"event": "request", "file": "Items.json", "params": {"messages": [{"role": "user", "content": '{"Line1":"薬1"}'}]}}
        second = {**first, "params": {"messages": [{"role": "user", "content": '{"Line1":"薬2"}'}]}}
        sent = []
        class Pipe(io.StringIO):
            def write(_self, value):
                sent.append(json.loads(value))
                return super().write(value)
        class Process:
            def __init__(_self, events):
                _self.stdout = io.StringIO("".join(json.dumps(event) + "\n" for event in events))
                _self.stdin = Pipe()
                _self.returncode = None
            def poll(_self): return _self.returncode
            def wait(_self, timeout=None): _self.returncode = 0; return 0
            def terminate(_self): _self.returncode = 0
        provider = Mock(return_value={"text": '{"translations":["Potion"]}', "prompt_tokens": 0, "completion_tokens": 0})
        events = [first, second, {"event": "stopped", "message": "allowance"}]
        with patch("desktop.backend.rpgmaker.subprocess.Popen", return_value=Process(events)):
            outcome = rpgmaker.run_worker(job_dir, plan, [], False, {}, provider, lambda: False, lambda event: None)
        self.assertEqual(outcome["status"], "stopped")
        self.assertTrue(sent[-1]["stop"])
        provider.assert_called_once()
        with patch("desktop.backend.rpgmaker.subprocess.Popen", return_value=Process([first, second, {"event": "complete"}])) as spawn:
            resumed = rpgmaker.run_worker(job_dir, plan, [], False, {}, provider, lambda: False, lambda event: None)
        self.assertEqual(resumed["status"], "complete")
        self.assertEqual(provider.call_count, 2)  # First request was replayed.
        self.assertNotIn("OPENAI_API_KEY", spawn.call_args.kwargs["env"])
        self.assertNotIn("DAZED_GAME_ROOT", spawn.call_args.kwargs["env"])
        (job_dir / "inputs/Items.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "frozen input"):
            rpgmaker.prepare_workspace(self.service.root / "projects" / project["id"], job_dir, plan, lambda: False)

    def test_luna_reserves_before_call_and_retains_failed_request_spend(self):
        ledger = self.service.ledger
        records = [{"id": "one", "source": "薬"}]
        observed = []
        def complete(**kwargs):
            observed.append((ledger.summary(), kwargs))
            raise TimeoutError("provider error must not expose a key")
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
        provider = LunaProvider(ledger, client=client)
        with self.assertRaises(TimeoutError):
            provider.translate("job", records, "")
        self.assertEqual(observed[0][0]["reserved_usd"], .02)
        self.assertEqual(observed[0][1]["model"], MODEL)
        self.assertEqual(observed[0][1]["service_tier"], "default")
        self.assertEqual(ledger.summary()["unknown_requests"], 1)
        restarted = BudgetLedger(ledger.path)
        with self.assertRaises(ValueError):
            restarted.reserve("too-long", "x" * (MAX_PROMPT_BYTES + 1))
        with restarted.connect() as db:
            db.execute("INSERT INTO requests(job,reserved) VALUES ('prior',4980000)")
        with self.assertRaisesRegex(ValueError, "budget"):
            provider.translate("blocked", records, "")
        self.assertEqual(len(observed), 1)
        self.assertEqual(restarted.summary()["reserved_usd"], 5)

    def test_original_branch_snapshot_does_not_checkout_or_use_translated_worktree(self):
        env = {**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
        def git(*args):
            return subprocess.run(["git", "-C", str(self.source), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", *args],
                                  env=env, capture_output=True, check=True).stdout
        git("init", "-q", "-b", "original")
        git("add", ".")
        git("commit", "-qm", "fixture")
        revision = git("rev-parse", "HEAD").decode().strip()
        git("switch", "-qc", "translated")
        (self.source / "data/Items.json").write_text('[null,{"name":"Translated potion"}]')
        before = git("status", "--porcelain=v1")
        result = snapshot(self.source, self.root / "snapshot", original=True)
        self.assertEqual(result["revision"], revision)
        self.assertIn("薬1", [r["source"] for r in result["records"]])
        self.assertEqual(git("status", "--porcelain=v1"), before)
        self.assertEqual(git("branch", "--show-current"), b"translated\n")

        # Shipping and installing the new runtime must not collect local keys
        # or overwrite user state. Exercise this boundary with miniature files.
        from desktop.backend import bundle
        package_source = self.root / "package-source"
        (package_source / "data/skills").mkdir(parents=True)
        (package_source / "data/skills/system.md").write_text("Shipped v1")
        (package_source / "data/api_keys.json").write_text("private fixture")
        (package_source / ".env").write_text("private fixture")
        (package_source / "files").mkdir()
        (package_source / "files/user.json").write_text("personal translation")
        selected = ["data/skills/system.md", "data/api_keys.json", ".env", "files/user.json"]
        first = self.root / "package-first"
        bundle.stage_backend(package_source, first, selected)
        self.assertFalse((first / ".env").exists())
        self.assertFalse((first / "data/api_keys.json").exists())
        self.assertFalse((first / "files").exists())
        target = self.root / "profile/tool"
        bundle.install_backend(first, target)
        (target / ".env").write_text("saved settings")
        (target / "data/api_keys.json").write_text("saved credential fixture")
        (target / "data/skills/system.md").write_text("User customization")
        (package_source / "data/skills/system.md").write_text("Shipped v2")
        second = self.root / "package-second"
        bundle.stage_backend(package_source, second, selected)
        write = bundle.write_atomic
        def interrupted_marker(path, raw, mode=0o644):
            if path == target / bundle.MARKER:
                raise OSError("interrupted installation")
            return write(path, raw, mode)
        with patch.object(bundle, "write_atomic", side_effect=interrupted_marker), self.assertRaisesRegex(OSError, "interrupted"):
            bundle.install_backend(second, target)
        self.assertEqual((target / "data/skills/system.md").read_text(), "User customization")
        installed = bundle.install_backend(second, target)
        self.assertEqual((target / "data/skills/system.md").read_text(), "Shipped v2")
        self.assertEqual((Path(installed["backup"]) / "files/data/skills/system.md").read_text(), "User customization")
        self.assertEqual((target / ".env").read_text(), "saved settings")
        self.assertEqual((target / "data/api_keys.json").read_text(), "saved credential fixture")

        # Complete-application archives must not write outside their staging
        # directory, including through a link created earlier in the archive.
        import io
        import tarfile
        from desktop.backend.package_archive import unpack
        archive = self.root / "application.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            member = tarfile.TarInfo("resources/default.txt")
            member.size = 7
            output.addfile(member, io.BytesIO(b"shipped"))
        unpack(archive, self.root / "unpacked")
        self.assertEqual((self.root / "unpacked/resources/default.txt").read_bytes(), b"shipped")
        for index, name in enumerate(("../outside", "/outside", "resources/link")):
            with tarfile.open(archive, "w:gz") as output:
                member = tarfile.TarInfo(name)
                if index == 2:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "../../outside"
                output.addfile(member)
            with self.assertRaises((ValueError, tarfile.FilterError)):
                unpack(archive, self.root / f"rejected-{index}")
        self.assertFalse((self.root / "outside").exists())

    def test_interrupted_jobs_are_recoverable_and_results_are_bound_to_ids(self):
        with self.assertRaisesRegex(ValueError, "already open"):
            WorkspaceService(self.root / "workspace")
        project = self.imported()
        job = self.service.start(project["id"], [project["records"][0]["id"]], "offline")
        self.finish()
        saved = self.service.jobs[job["id"]]
        record_id = project["records"][0]["id"]
        review_draft = {job["id"] + ":" + record_id: "Unapproved potion"}
        context_draft = {"skills/game.md": "Unapplied instructions"}
        self.service.save_drafts(project["id"], 0, context_draft, review_draft)
        with self.assertRaisesRegex(ValueError, "changed elsewhere"):
            self.service.save_drafts(project["id"], 0, {}, {})
        with self.assertRaisesRegex(ValueError, "Markdown"):
            self.service.save_drafts(project["id"], 1, {"../outside.md": "invalid"}, {})
        foreign = self.imported()
        with self.assertRaisesRegex(ValueError, "selected project"):
            self.service.save_drafts(foreign["id"], 0, {}, review_draft)
        saved["status"] = "running"
        self.service._save_job(saved)
        self.service.close()
        self.service = WorkspaceService(self.root / "workspace")
        self.assertEqual(self.service.jobs[job["id"]]["status"], "interrupted")
        recovered = self.service.get_drafts(project["id"])
        self.assertEqual(recovered["context"], context_draft)
        self.assertEqual(recovered["review"], review_draft)
        self.assertNotEqual(self.service.context(project["id"])["documents"].get("skills/game.md"), context_draft["skills/game.md"])
        self.assertFalse(self.service.jobs[job["id"]]["results"][record_id]["reviewed"])
        self.service.save_drafts(project["id"], recovered["revision"], {}, {})
        self.assertFalse(self.service.get_drafts(project["id"])["review"])
        # Approval tokens belong to one prompt and one run. Interrupted
        # prompts recover as stopped work, never as permission to submit.
        manual = self.service._manual_service()
        inventory = manual.inspect(str(self.source / "data"), "RPG Maker MV/MZ")
        with patch.object(manual, "_launch"):
            planned = manual.start(inventory["source"], inventory["engine"], ["Items.json"], inventory["revision"])
        manual_job = manual.jobs[planned["id"]]
        manual.active = planned["id"]
        manual._event(manual_job, {"event": "batch_phase", "args": ["submit", {"requests": 1}]})
        old_token = manual_job["approval"]["token"]
        with patch.object(manual, "_send") as send:
            manual.answer(planned["id"], old_token, False)
            send.assert_called_once_with({"command": "batch", "approved": False})
        manual._event(manual_job, {"event": "speaker_confirmation", "args": [{"speakers": ["騎士"]}]})
        with patch.object(manual, "_send") as send, self.assertRaisesRegex(ValueError, "no longer pending"):
            manual.answer(planned["id"], old_token, True)
        send.assert_not_called()
        manual.active = ""
        # Completed manual exports survive the same restart boundary without
        # requiring another Electron launch merely to reload this JSON state.
        csv_root = self.root / "csv-input"
        csv_root.mkdir()
        (csv_root / "items.csv").write_text("Source,Target\nName,\n")
        csv_inventory = manual.inspect(str(csv_root), "CSV")
        with patch.object(manual, "_launch"):
            completed = manual.start(str(csv_root), "CSV", ["items.csv"], csv_inventory["revision"], "offline")
        csv_job = manual.jobs[completed["id"]]
        output = manual.folder(csv_job["id"]) / "translated/items.csv"
        output.parent.mkdir()
        output.write_text("Source,Target\nName,Translated\n")
        csv_bytes = output.read_bytes()
        csv_job.update(status="complete", outputs={"items.csv": digest(csv_bytes)})
        manual.save(csv_job)
        self.service.close()
        self.service = WorkspaceService(self.root / "workspace")
        recovered_manual = next(j for j in self.service.manual_state()["jobs"] if j["id"] == planned["id"])
        self.assertEqual(recovered_manual["status"], "interrupted")
        self.assertIsNone(recovered_manual["approval"])
        recovered_csv = self.service._manual_service().jobs[csv_job["id"]]
        self.assertEqual(recovered_csv["status"], "complete")
        exported = self.service.manual_export(csv_job["id"])
        self.assertEqual((Path(exported["path"]) / "items.csv").read_bytes(), csv_bytes)
        output.write_text("changed after completion")
        with self.assertRaisesRegex(ValueError, "output changed"):
            self.service.manual_export(csv_job["id"])
        # Batch activation belongs to the original run and exact recovery
        # files, even when the UI has since selected another account or run.
        from desktop.backend.batches import recovery_hashes, recovery_profile, confirm_profile
        manual = self.service._manual_service()
        batch_root = manual.folder(planned['id'])
        batch_plan_path = batch_root / 'plan.json'
        batch_plan = json.loads(batch_plan_path.read_text())
        batch_plan['mode'] = 'batch'
        atomic_json(batch_plan_path, batch_plan)
        manual.jobs[planned['id']].update(mode='batch', plan_hash=digest(batch_plan_path.read_bytes()))
        atomic_json(batch_root / 'log/batch_history.json', {'batches': [
            {'id': 'saved-batch', 'status': 'fetched', 'key_name': 'Original', 'custom_ids': {'secret-prompt': 'cache-key'}}]})
        atomic_json(batch_root / 'log/batch_state.json', {'status': 'fetched', 'batch_ids': ['saved-batch'], 'result_keys': ['cache-key']})
        atomic_json(batch_root / 'log/batch_results.json', {'cache-key': 'Paid result'})
        batches = self.service._batches()
        local = batches.state()
        self.assertEqual(local['rows'][0]['id'], 'saved-batch')
        self.assertNotIn('custom_ids', local['rows'][0])
        with self.assertRaisesRegex(ValueError, 'disabled'):
            batches.action(local['sources'][0]['id'], 'saved-batch', 'refresh')
        activation = {'id': 'activation', 'created': 'now', 'project_id': 'batch:' + local['sources'][0]['id'],
                      'action': 'activate', 'status': 'complete', 'result': {'job_id': planned['id'], 'state': 'fetched',
                      'hashes': recovery_hashes(batch_root), 'plan_hash': digest(batch_plan_path.read_bytes())}}
        self.service.operations.jobs['activation'] = activation
        manual.allow_providers = True
        # Older RPG Maker results must not write with an unreviewed code
        # profile. Confirmation is bound to the frozen plan and recovery files.
        activation['result'].update(batch_id='saved-batch', profile_confirmation=recovery_profile(batch_root, batch_plan))
        with self.assertRaisesRegex(ValueError, 'confirm the original'):
            batches.resume('activation')
        profile_plan = {'source': {'root': str(batch_root), 'plan_root': str(batch_root)}, 'prepared': activation['result']}
        from util import translation as translation, batch_history as history
        with patch.object(translation, 'BATCH_STATE_FILE', batch_root / 'log/batch_state.json'), \
             patch.object(translation, 'BATCH_LOCK_FILE', batch_root / 'log/batch_files.lock'), \
             patch.object(history, 'BATCH_HISTORY_FILE', batch_root / 'log/batch_history.json'):
            activation['result'] = confirm_profile(profile_plan)
            self.assertIsNone(activation['result']['profile_confirmation'])
            self.assertEqual(json.loads((batch_root / 'log/batch_state.json').read_text())['runtime_profile'], batch_plan['runtime_profile'])
            self.assertEqual(json.loads((batch_root / 'log/batch_history.json').read_text())['batches'][0]['runtime_profile'], batch_plan['runtime_profile'])
            with self.assertRaisesRegex(ValueError, 'changed after activation'):
                confirm_profile(profile_plan)
        with patch.object(manual, '_launch') as launch:
            batches.resume('activation')
            launch.assert_called_once_with(manual.jobs[planned['id']], True)
        atomic_json(batch_root / 'log/batch_results.json', {'cache-key': 'Changed result'})
        with patch.object(manual, '_launch') as launch, self.assertRaisesRegex(ValueError, 'changed after activation'):
            batches.resume('activation')
        launch.assert_not_called()
        # A legacy folder is opt-in and its missing credential can never
        # silently fall back to whichever credential is currently active.
        legacy = self.root / 'legacy-run'
        atomic_json(legacy / 'log/batch_history.json', {'batches': [{'id': 'legacy', 'status': 'submitted'}]})
        registered = batches.register(str(legacy))
        legacy_source = next(s for s in registered['sources'] if s['root'] == str(legacy))
        batches.allow_providers = True
        with self.assertRaisesRegex(ValueError, 'no saved credential'):
            batches.action(legacy_source['id'], 'legacy', 'refresh')
        atomic_json(legacy / 'log/batch_history.json', {'batches': [{'id': 'bad'}, {'id': 'bad'}]})
        self.assertIn('duplicate', batches.state()['errors'][0]['message'])
        # A never-submitted legacy queue has no history file. It is still
        # discoverable, and linked recovery cannot substitute another run or
        # lose the custom IDs of already-paid requests.
        from desktop.backend.batches import available_entries, linked_queue
        (legacy / 'log/batch_history.json').unlink()
        queued = {'status': 'queued', 'run_id': 'legacy-queue', 'provider': 'openai',
                  'model': 'gpt-test', 'file_set': ['items.csv']}
        atomic_json(legacy / 'log/batch_state.json', queued)
        queue = {'queued-key': {'provider': 'openai', 'params': {'model': 'gpt-test'}}}
        atomic_json(legacy / 'log/batch_requests.json.parts/one.json', queue)
        local_row = available_entries(legacy)[0]
        self.assertTrue(local_row['local_queue'])
        link = linked_queue(legacy, local_row, [local_row])
        self.assertEqual(link['root'], str(legacy))
        self.assertTrue(any(r['id'] == local_row['id'] for r in batches.register(str(legacy))['rows']))
        with self.assertRaisesRegex(ValueError, 'no provider job'):
            batches.action(legacy_source['id'], local_row['id'], 'refresh')
        atomic_json(legacy / 'log/batch_state.json', {**queued, 'run_id': 'other'})
        with self.assertRaisesRegex(ValueError, 'does not own'):
            linked_queue(legacy, local_row, [local_row])
        paid = {'id': 'paid', 'custom_ids': {'request': 'foreign-key'}}
        atomic_json(legacy / 'log/batch_state.json', {**queued, 'status': 'partially_submitted', 'batches': [paid]})
        with self.assertRaisesRegex(ValueError, 'do not match'):
            linked_queue(legacy, {**local_row, 'local_queue': False, 'id': 'paid'}, [paid])
        # Evaluation submission consent and blind-export previews bind the
        # exact saved artifacts and vault, not merely a run name. Shared
        # evaluation tests already exercise provider/review/ZIP contracts.
        from desktop.backend.evaluations import revision, credential_signature, vault_for, _execute
        evaluations = self.service._evaluations()
        eval_root = evaluations.root / 'log/evaluation_work/fixture'
        atomic_json(eval_root / 'state.json', {'status': 'prepared'})
        atomic_json(eval_root / 'manifest.json', {'source': 'frozen text'})
        atomic_json(self.service.root / 'settings/api_keys.json', {
            'version': 1, 'active': 'Fixture', 'keys': {
                'Fixture': {'secret': 'fixture-only-secret', 'endpoint': 'https://example.invalid/v1', 'keyless': False}}})
        with self.assertRaisesRegex(ValueError, 'disabled'):
            evaluations.action('submit', 'fixture')
        evaluations.allow_providers = True
        with self.assertRaisesRegex(ValueError, 'Preview'):
            evaluations.action('submit', 'fixture')
        approved = {'id': 'cost-preview', 'created': 'now', 'project_id': 'evaluation:fixture', 'action': 'estimate',
                    'status': 'complete', 'result': {'run_id': 'fixture', 'revision': revision(eval_root),
                    'credential_signature': credential_signature(vault_for(self.service.root))}}
        self.service.operations.jobs[approved['id']] = approved
        with patch.object(self.service.operations, 'start', side_effect=lambda plan: plan):
            plan = evaluations.action('submit', 'fixture', preview_job=approved['id'])
            self.assertEqual(plan['revision'], revision(eval_root))
            self.assertNotIn('fixture-only-secret', json.dumps(plan))
            atomic_json(eval_root / 'results/candidate-1.json', {'translation': 'Changed'})
            with self.assertRaisesRegex(ValueError, 'Preview'):
                evaluations.action('submit', 'fixture', preview_job=approved['id'])
            approved['result']['revision'] = revision(eval_root)
            approved['result']['credential_signature'] = 'old-credential'
            with self.assertRaisesRegex(ValueError, 'credentials changed'):
                evaluations.action('submit', 'fixture', preview_job=approved['id'])
            approved.update(action='review_preview')
            plan = evaluations.action('review_export', 'fixture', preview_job=approved['id'])
            self.assertFalse(plan['network'])
            (eval_root / 'results/candidate-1.json').write_text('changed again')
            with self.assertRaisesRegex(ValueError, 'Preview'):
                evaluations.action('review_export', 'fixture', preview_job=approved['id'])
            with self.assertRaisesRegex(ValueError, 'changed after the action'):
                _execute(plan, evaluations.root, vault_for(self.service.root), lambda _: None, lambda: False)
        evaluations.draft({'source': str(self.source), 'candidates': []})
        self.assertEqual(evaluations.state()['draft']['source'], str(self.source))
        with self.assertRaisesRegex(ValueError, 'candidate setting'):
            evaluations.draft({'candidates': [{'secret': 'never store this'}]})
        response = SimpleNamespace(usage=None, choices=[SimpleNamespace(finish_reason="stop",message=SimpleNamespace(content='{"translations":[{"id":"wrong","text":"Potion"}]}'))])
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: response)))
        with self.assertRaisesRegex(ValueError, "identities"):
            LunaProvider(self.service.ledger, client=client).translate("bound", [{"id":"right","source":"薬"}], "")
