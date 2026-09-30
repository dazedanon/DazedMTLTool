"""Guided-service regressions; worker engines and Qt have separate coverage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from desktop.backend.project import atomic_json, digest
from desktop.backend.service import WorkspaceService
from desktop.backend.workflow_actions import run_action
from tests.test_desktop_backend import game


class DesktopWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = game(self.root / "Game")
        self.service = WorkspaceService(self.root / "workspace")
        self.project = self.service.workflow_open(str(self.source))["project"]
        self.workflow = self.service._workflows()
        self.folder = self.workflow.folder(self.project["id"])

    def tearDown(self):
        self.service.close()
        self.temporary.cleanup()

    def test_confirmations_bind_exact_inputs_and_import_and_rewrap_scope(self):
        before = (self.source / "data/Items.json").read_bytes()
        identity = self.project["id"]
        for action, options in (("import", {"files": ["../Items.json"]}), ("rewrap_apply", {"files": ["foreign.json"]})):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.service.workflow_preview(identity, action, options)
        preview = self.service.workflow_preview(identity, "import", {"files": ["Items.json"]})
        (self.source / "data/Items.json").write_bytes(before + b"\n")
        with patch.object(self.service.operations, "start") as start, self.assertRaisesRegex(ValueError, "changed after"):
            self.service.workflow_execute(preview["token"])
        start.assert_not_called()
        (self.source / "data/Items.json").write_bytes(before)
        preview = self.service.workflow_preview(identity, "import", {"files": ["Items.json"]})
        result = run_action(self.workflow.previews.pop(preview["token"]), lambda _message: None)
        self.assertEqual(result["selected"], ["Items.json"])
        self.assertEqual([path.name for path in (self.folder / "files").iterdir()], ["Items.json"])
        self.assertEqual((self.source / "data/Items.json").read_bytes(), before)
        widths = {"width": 25, "faceWidth": 30, "listWidth": 70, "noteWidth": 50}
        values = {"files": ["Items.json"], "widths": widths, "categories": ["list"], "codes": "401,405", "over_limit": True}
        preview = self.service.workflow_preview(identity, "rewrap_preview", values)
        apply = self.service.workflow_preview(identity, "rewrap_apply", values)
        self.assertEqual(preview["options"], apply["options"])
        self.assertEqual(apply["options"]["widths"]["faceWidth"], 25)
        with self.assertRaisesRegex(ValueError, "expired"):
            self.service.workflow_execute(preview["token"])
        # Public ZIP approval is tied to the shown destination, including an
        # explicit overwrite notice and a stale-output rejection.
        for output in (self.source / 'release.zip', self.service.root / 'release.zip'):
            with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'outside'):
                self.service.workflow_preview(identity, 'release', {'output': str(output)})
        output = self.root / 'public.zip'
        output.write_bytes(b'previous-release')
        preview = self.service.workflow_preview(identity, 'release', {'output': str(output)})
        self.assertTrue(preview['overwrite'])
        self.assertEqual(preview['destination'], str(output))
        output.write_bytes(b'newer-release')
        with patch.object(self.service.operations, 'start') as start, self.assertRaisesRegex(ValueError, 'destination changed'):
            self.service.workflow_execute(preview['token'])
        start.assert_not_called()
        self.assertEqual(output.read_bytes(), b'newer-release')
        # Ace conversion consumes native files as well as its JSON workspace.
        # A changed native database or archive must invalidate approval before
        # any converter/decrypter process is launched.
        ace = self.root / 'Ace game'
        native = ace / 'Data/Items.rvdata2'
        native.parent.mkdir(parents=True)
        native.write_bytes(b'original native fixture')
        archive = ace / 'Game.rgss3a'
        archive.write_bytes(b'original archive fixture')
        atomic_json(ace / 'ace_json/Items.json', [None, {'id': 1, 'name': 'Medicine'}])
        ace_id = self.service.workflow_open(str(ace))['project']['id']
        # Windows directory junctions are a separate filesystem type from
        # symbolic links. Keep the same no-indirection write boundary.
        with patch.object(Path, 'is_junction', lambda path: path == ace / 'Data', create=True):
            with self.assertRaisesRegex(ValueError, 'junction'):
                self.service.workflow_preview(ace_id, 'ace_pack')
        self.assertEqual(native.read_bytes(), b'original native fixture')
        for action, path in (('ace_extract', native), ('ace_pack', native), ('ace_decrypt', archive)):
            with self.subTest(action=action):
                preview = self.service.workflow_preview(ace_id, action)
                path.write_bytes(path.read_bytes() + b'changed')
                changed = path.read_bytes()
                with patch.object(self.service.operations, 'start') as start, self.assertRaisesRegex(ValueError, 'changed after'):
                    self.service.workflow_execute(preview['token'])
                start.assert_not_called()
                self.assertEqual(path.read_bytes(), changed)
        apply = self.service.workflow_preview(identity, 'rewrap_apply', values)
        target = self.root / "unrelated.json"
        target.write_text("{}")
        (self.source / "data/Items.json").unlink()
        (self.source / "data/Items.json").symlink_to(target)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.service.workflow_execute(apply["token"])
        self.assertEqual(target.read_text(), "{}")

    def test_phase_handoff_retains_variables_and_glossary_without_reenabling_dialogue(self):
        identity = self.project["id"]
        preview = self.service.workflow_preview(identity, "import", {"files": ["Items.json", "Map001.json"]})
        run_action(self.workflow.previews.pop(preview["token"]), lambda _message: None)
        self.service.workflow_update(identity, 0, {"mode": "offline", "engine_options": {"CODE401": True, "CODE122": True, "CODE122_VAR_RANGES": "5"}})
        manual = self.service._manual_service()
        with patch.object(manual, "_launch"):
            job = self.service.workflow_phase(identity, "database", False)
        directory = manual.folder(job["id"])
        (directory / "translated").mkdir()
        output = json.loads((self.folder / "files/Items.json").read_text())
        output[1].update(name="Potion", _original={"name": "薬1"})
        atomic_json(directory / "translated/Items.json", output)
        (directory / "log").mkdir()
        atomic_json(directory / "log/var_translation_map.json", {"名前": "Name"})
        from util.vocab import BASE_SEPARATOR
        (directory / "game/.dazedtl/glossary.txt").write_text("# Game Characters\n名前 (Name)\n\n" + BASE_SEPARATOR + "Base", encoding="utf-8")
        manual.jobs[job["id"]].update(status="complete", outputs={"Items.json": digest((directory / "translated/Items.json").read_bytes())})
        manual.save(manual.jobs[job["id"]])
        state = self.service.workflow_state(identity)
        self.assertFalse(state["project"]["collection_error"])
        self.assertEqual(state["project"]["collected"], [job["id"]])
        self.assertEqual((self.source / ".dazedtl/glossary.txt").read_text().count(BASE_SEPARATOR), 1)
        with patch.object(manual, "_launch"):
            next_job = self.service.workflow_phase(identity, "advanced", True)
        next_directory = manual.folder(next_job["id"])
        plan = json.loads((next_directory / "plan.json").read_text())
        self.assertFalse(plan["runtime_profile"]["config"]["CODE401"])
        self.assertFalse(plan["runtime_profile"]["config"]["CODE111"])
        self.assertTrue(plan["runtime_profile"]["config"]["CODE122"])
        self.assertEqual(plan["selected"], ["Map001.json"])
        self.assertEqual(json.loads((self.folder / "files/Items.json").read_text())[1]["name"], "Potion")
        self.assertEqual(json.loads((next_directory / "seed/var_translation_map.json").read_text()), {"名前": "Name"})
        self.assertIn("seed/var_translation_map.json", plan["context_hashes"])
        docs = self.service.workflow_documents(identity)
        self.assertNotIn(BASE_SEPARATOR, docs["glossary"]["text"])
        self.service.workflow_document_save(identity, "glossary", docs["glossary"]["revision"], docs["glossary"]["text"])
        self.assertEqual((self.source / ".dazedtl/glossary.txt").read_text().count(BASE_SEPARATOR), 1)
        draft = {"documents": {"quirks": {"text": "Unsaved guidance", "revision": docs["quirks"]["revision"]}}}
        self.service.workflow_draft(identity, draft)
        self.service.close()
        self.service = WorkspaceService(self.root / "workspace")
        restored = self.service.workflow_state(identity)
        self.assertEqual(restored["draft"], draft)
        self.assertEqual(restored["manual_job"]["status"], "interrupted")
        self.assertFalse((self.source / ".dazedtl/skills/quirks.md").exists())
        self.assertEqual(self.service.ledger.summary()["requests"], 0)

    def test_wolf_relocated_manifest_stale_injection_and_frozen_phase_scope(self):
        from desktop.backend.wolf import manifest
        source = self.root / "WOLF"
        data, work = source / "Data", source / "wolf_json"
        (data / "BasicData").mkdir(parents=True)
        work.mkdir()
        (data / "BasicData/CommonEvent.dat").write_bytes(b"fixture-binary")
        old = self.root / "former-location"
        atomic_json(work / "manifest.json", {"root": str(old), "data_dir": str(old / "Data"), "entries": [
            {"json": "DataBase.project.json", "kind": "db", "base": str(old / "Data/BasicData/DataBase.project")},
            {"json": "names.json", "kind": "names", "base": str(old / "Data")}]})
        atomic_json(work / "names.json", {"kind": "names", "names": []})
        atomic_json(work / "DataBase.project.json", {"kind": "db", "file": "DataBase.project", "groups": [
            {"typeName": "Item · アイテム", "lines": [{"row": 0, "fieldName": "Name", "source": "薬", "text": ""}]}]})
        self.assertEqual(manifest(source)["data_dir"], str(data))
        project = self.service.workflow_open(str(source))["project"]
        identity = project["id"]
        folder = self.workflow.folder(identity)
        def action(name, options=None):
            preview = self.service.workflow_preview(identity, name, options or {})
            return run_action(self.workflow.previews.pop(preview["token"]), lambda _msg: None)
        action("import", {"files": ["DataBase.project.json", "names.json"]})
        discovery = action("wolf_discover")
        groups = discovery["selected"]
        self.assertEqual(len(groups), 1)
        self.service.workflow_update(identity, 0, {"mode": "offline", "wolf": {"literal_line1_lowconf": False, "db_groups": groups}})
        manual = self.service._manual_service()
        with patch.object(manual, "_launch"):
            job = self.service.workflow_phase(identity, "db_selected", False)
        directory = manual.folder(job["id"])
        plan = json.loads((directory / "plan.json").read_text())
        self.assertEqual(plan["selected"], ["DataBase.project.json"])
        self.assertEqual(json.loads(plan["workflow"]["environment"]["wolfDbIncludeGroups"]), groups)
        self.assertFalse(json.loads((directory / "context/wolf_speakers.json").read_text())["literal_line1_lowconf"])
        self.assertIn("context/wolf_speakers.json", plan["context_hashes"])
        preview = self.service.workflow_preview(identity, "wolf_inject", {})
        (data / "BasicData/CommonEvent.dat").write_bytes(b"changed")
        with patch.object(self.service.operations, "start") as start, self.assertRaisesRegex(ValueError, "changed after"):
            self.service.workflow_execute(preview["token"])
        start.assert_not_called()
        value = json.loads((work / "manifest.json").read_text())
        for invalid in (str(self.root / "foreign.bin"), str(old / "../foreign.bin")):
            value["entries"][0]["base"] = invalid
            atomic_json(work / "manifest.json", value)
            with self.subTest(base=invalid), self.assertRaises(ValueError):
                self.service.workflow_preview(identity, "wolf_inject", {})
        self.assertEqual(self.service.ledger.summary()["requests"], 0)
