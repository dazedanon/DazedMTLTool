"""Unit checks plus optional real-archive integration: python test_gmtt.py --data PATH."""
import copy
import json
from pathlib import Path
import struct
import sys
import unittest

import gmtt

DATA = None
if "--data" in sys.argv:
    index = sys.argv.index("--data")
    DATA = Path(sys.argv[index + 1]).resolve()
    del sys.argv[index:index + 2]


def fixture(text="開始\n終了"):
    return {"schema": 1, "source_sha256": "fixture", "source_size": 100, "yyc": False,
            "strings": [text], "display_name_id": 0, "fonts": [],
            "code": [{"index": 0, "name": "gml_test", "parent": -1, "length": 16,
                      "instructions": [{"index": i, "string_id": 0, "asm": "Push.String:STRING",
                                        "address_words": i * 2, "size_words": 2} for i in range(2)]}]}


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.snap = fixture()
        self.cat = gmtt.make_catalog(self.snap)
        self.entry = self.cat["entries"][0]
        self.entry.update(translation="Start⟦GM:0000⟧End", reviewed=True)

    def issues(self):
        return gmtt.validate_catalog(self.cat, self.snap)["errors"]

    def test_validator_accepts_and_restores(self):
        result = gmtt.validate_catalog(self.cat, self.snap)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["changes"][0]["text"], "Start\nEnd")

    def test_unreviewed_rejected(self):
        self.entry["reviewed"] = False
        self.assertTrue(self.issues())

    def test_missing_duplicated_unknown_or_reordered_tokens(self):
        for text in ("Start End", "⟦GM:0000⟧⟦GM:0000⟧", "⟦GM:0001⟧", "⟦GM:bad⟧"):
            with self.subTest(text=text):
                self.entry["translation"] = text
                self.assertTrue(self.issues())
        with self.assertRaises(gmtt.ToolError):
            gmtt.restore("⟦GM:0001⟧⟦GM:0000⟧", [{"token": f"⟦GM:{i:04d}⟧", "value": "x"} for i in range(2)])

    def test_raw_added_control_code(self):
        self.entry["translation"] += "\n"
        self.assertTrue(self.issues())

    def test_stale_source_and_coordinates_rejected(self):
        for key, value in (("source", "different"), ("code_index", 99), ("string_id", 99)):
            old = self.entry[key]
            self.entry[key] = value
            self.assertTrue(self.issues())
            self.entry[key] = old

    def test_wrong_archive_rejected(self):
        self.cat["source_sha256"] = "other"
        with self.assertRaises(gmtt.ToolError):
            self.issues()

    def test_duplicate_site_rejected(self):
        self.cat["entries"].append(copy.deepcopy(self.entry))
        self.assertTrue(self.issues())

    def test_modified_mask_rejected(self):
        self.entry["tokens"][0]["value"] = "!"
        self.assertTrue(self.issues())

    def test_empty_and_nul_rejected(self):
        snap = fixture("開始")
        cat = gmtt.make_catalog(snap)
        for value in ("", "start\x00end"):
            cat["entries"][0].update(translation=value, reviewed=True)
            self.assertTrue(gmtt.validate_catalog(cat, snap)["errors"])

    def test_complete_rejects_untranslated(self):
        self.assertTrue(gmtt.validate_catalog(self.cat, self.snap, True)["errors"])

    def test_empty_translation_set_is_noop(self):
        self.entry["translation"] = None
        self.assertEqual(gmtt.validate_catalog(self.cat, self.snap)["changes"], [])

    def test_font_gate_calls_actual_validator(self):
        snap = fixture("開始")
        snap["fonts"] = [{"name": "tiny", "scale_x": 1, "glyphs": [{"char": ord("A"), "advance": 10, "kerning": []}]}]
        cat = gmtt.make_catalog(snap)
        entry = cat["entries"][0]
        entry.update(translation="AB", reviewed=True, font="tiny", max_width=5)
        errors = gmtt.validate_catalog(cat, snap)["errors"]
        self.assertTrue(any("glyph" in e for e in errors))
        self.assertTrue(any("max_width" in e for e in errors))

    def test_site_isolation_detects_unselected_change(self):
        changes = gmtt.validate_catalog(self.cat, self.snap)["changes"]
        after = copy.deepcopy(self.snap)
        after["strings"].append(changes[0]["text"])
        after["code"][0]["instructions"][0]["string_id"] = 1
        gmtt.verify_snapshots(self.snap, after, changes)
        after["code"][0]["instructions"][1]["string_id"] = 1
        with self.assertRaises(gmtt.ToolError):
            gmtt.verify_snapshots(self.snap, after, changes)

    def test_pool_prefix_must_survive(self):
        after = copy.deepcopy(self.snap)
        after["strings"][0] = "changed"
        with self.assertRaises(gmtt.ToolError):
            gmtt.verify_snapshots(self.snap, after, [])

    def test_yyc_rejected(self):
        self.snap["yyc"] = True
        with self.assertRaises(gmtt.ToolError):
            gmtt.make_catalog(self.snap)


class ParserTests(unittest.TestCase):
    def test_unicode_lengths_and_corruption(self):
        text = "開始🙂".encode("utf-8")
        # FORM at 0, STRG header at 8, count at 16, pointer at 20, record at 24.
        payload = struct.pack("<II", 1, 24) + struct.pack("<I", len(text)) + text + b"\0"
        blob = b"FORM" + struct.pack("<I", len(payload) + 8) + b"STRG" + struct.pack("<I", len(payload)) + payload
        with gmtt.work_directory(Path.cwd(), ".gmtt-test-") as root:
            file = root / "data.win"
            file.write_bytes(blob)
            self.assertEqual(gmtt.raw_archive(file)["strings"], ["開始🙂"])
            variants = [b"BAD!" + blob[4:], blob[:-1], blob[:20] + struct.pack("<I", 0) + blob[24:], blob[:-1] + b"x"]
            for bad in variants:
                file.write_bytes(bad)
                with self.assertRaises(gmtt.ToolError):
                    gmtt.raw_archive(file)

    def test_duplicate_json_keys_fail(self):
        with gmtt.work_directory(Path.cwd(), ".gmtt-test-") as root:
            path = root / "bad.json"
            path.write_text('{"schema":1,"schema":2}')
            with self.assertRaises(gmtt.ToolError):
                gmtt.read_json(path)

    def test_no_overwrite_of_translation_store(self):
        with gmtt.work_directory(Path.cwd(), ".gmtt-test-") as root:
            path = root / "catalog.json"
            gmtt.write_json(path, {"translation": "finished"})
            with self.assertRaises(FileExistsError):
                gmtt.write_json(path, {})
            self.assertEqual(gmtt.read_json(path)["translation"], "finished")


@unittest.skipUnless(DATA, "Pass --data PATH for real archive integration")
class IntegrationTests(unittest.TestCase):
    def test_real_archive_roundtrips_and_site_isolation(self):
        before_hash = gmtt.sha256(DATA)
        snap = gmtt.snapshot(DATA)
        with gmtt.work_directory(Path.cwd(), ".gmtt-integration-") as root:
            catalog = gmtt.make_catalog(snap, "all")
            file = root / "catalog.json"
            gmtt.write_json(file, catalog)
            noop = root / "noop.win"
            gmtt.patch_archive(DATA, file, noop)
            self.assertEqual(gmtt.sha256(noop), before_hash)
            # Pick a literal with multiple bytecode uses, so a global replacement is caught.
            counts = {}
            for e in catalog["entries"]:
                if e["id"].startswith("CODE:"):
                    counts[e["string_id"]] = counts.get(e["string_id"], 0) + 1
            entry = next(e for e in catalog["entries"] if e["id"].startswith("CODE:") and counts[e["string_id"]] > 1 and not e["tokens"])
            entry.update(translation="Longer UTF-8 test: Ω café 🙂 " * 20, reviewed=True)
            caption = next(e for e in catalog["entries"] if e["id"] == "GEN8:display_name")
            caption.update(translation="GameMaker archive test caption", reviewed=True)
            catalog["entries"] = [entry, caption]
            patch_file = root / "changed.json"
            gmtt.write_json(patch_file, catalog)
            output = root / "changed.win"
            gmtt.patch_archive(DATA, patch_file, output)
            raw = gmtt.raw_archive(output)
            self.assertEqual(raw["strings"][:len(snap["strings"])], snap["strings"])
            self.assertEqual(raw["strings"][-2:], [entry["translation"], caption["translation"]])
            report = gmtt.read_json(str(output) + ".report.json")
            self.assertEqual(report["verification"]["changed_sites"], 2)
            with self.assertRaises(gmtt.ToolError):
                gmtt.patch_archive(DATA, patch_file, DATA)
            with self.assertRaises(gmtt.ToolError):
                gmtt.patch_archive(DATA, patch_file, output)
        self.assertEqual(gmtt.sha256(DATA), before_hash)


if __name__ == "__main__":
    unittest.main(verbosity=2)
