#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extraction, request building and injection, against a synthetic map.

The synthetic map matters: a test whose fixtures come from the real store
passes for the wrong reason once the store is full, and a test that needs the
game folder cannot run on a machine that does not have it.
"""

import io
import os
import sys
import copy
import json
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import (config, codes, extract, inject, measure, requests as R,
                   store, rvdata, validate)                    # noqa: E402
from acetl import rvmarshal as M                               # noqa: E402

BS = chr(92)


def S(text):
    return M.RString(text.encode("utf-8"), [(M.RSymbol(b"E"), True)])


def cmd(code, indent, params):
    return M.RObject(M.RSymbol(b"RPG::EventCommand"), [
        (M.RSymbol(b"@code"), code),
        (M.RSymbol(b"@indent"), indent),
        (M.RSymbol(b"@parameters"), M.RArray(list(params))),
    ])


def make_map():
    """One map, one event, one page: a faced two-line message, a plain
    message, and a two-option choice with its branches."""
    lst = M.RArray([
        cmd(101, 0, [S("デフォ鎧"), 0, 0, 2]),
        cmd(401, 0, [S(BS + "NAME[エリス]「おはよう、みんな。")]),
        cmd(401, 0, [S("　今日はいい天気ね。")]),
        cmd(101, 0, [S(""), 0, 0, 2]),
        cmd(401, 0, [S(BS + "NAME[町人]「10" + BS + "G だよ")]),
        cmd(102, 0, [M.RArray([S("はい"), S("いいえ")]), 1]),
        cmd(402, 0, [0, S("はい")]),
        cmd(402, 0, [1, S("いいえ")]),
        cmd(404, 0, []),
        cmd(118, 0, [S("村長選択肢")]),
        cmd(0, 0, []),
    ])
    page = M.RObject(M.RSymbol(b"RPG::Event::Page"), [(M.RSymbol(b"@list"), lst)])
    ev = M.RObject(M.RSymbol(b"RPG::Event"), [
        (M.RSymbol(b"@id"), 7), (M.RSymbol(b"@name"), S("EV007")),
        (M.RSymbol(b"@pages"), M.RArray([page])),
    ])
    return M.RObject(M.RSymbol(b"RPG::Map"), [
        (M.RSymbol(b"@display_name"), S("コロン村")),
        (M.RSymbol(b"@events"), M.RHash([(7, ev)])),
    ])


class TestExtract(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config()
        self.data = make_map()
        self.units = []
        glossary = {"names": {}}
        speakers = {}
        import collections
        speakers = collections.Counter()
        for el in rvdata.event_lists(self.data, "Map001.rvdata2"):
            extract.extract_list(el, self.cfg, self.units, glossary, speakers)
        self.speakers = speakers

    def test_runs_are_merged_and_the_tag_is_split_off(self):
        text = [u for u in self.units if u["kind"] == "text"]
        self.assertEqual(len(text), 2)
        first = text[0]
        self.assertEqual(first["nametag"], BS + "NAME[エリス]")
        self.assertEqual(first["speaker"], "エリス")
        self.assertEqual(first["sites"][0]["count"], 2)
        self.assertNotIn("NAME", first["src"])
        self.assertTrue(first.get("faced"), "the 101 carried a face graphic")

    def test_unfaced_message_is_not_marked_faced(self):
        text = [u for u in self.units if u["kind"] == "text"]
        self.assertFalse(text[1].get("faced"))

    def test_inline_code_is_masked(self):
        text = [u for u in self.units if u["kind"] == "text"]
        self.assertIn("⟦0⟧", text[1]["src"])
        self.assertEqual(list(text[1]["codes"].values()), [BS + "G"])

    def test_choices_extracted_with_their_branches(self):
        ch = [u for u in self.units if u["kind"] == "choice"]
        self.assertEqual([u["raw"] for u in ch], ["はい", "いいえ"])
        self.assertIn("branches: 0=はい 1=いいえ", ch[0]["note"])

    def test_label_is_never_extracted(self):
        """A code 118 label is matched by string equality; translating it makes
        the jump silently stop matching."""
        self.assertNotIn("村長選択肢", [u["raw"] for u in self.units])

    def test_speakers_are_counted_for_the_glossary(self):
        self.assertEqual(dict(self.speakers), {"エリス": 1, "町人": 1})


class TestInject(unittest.TestCase):
    def setUp(self):
        self.cfg = config.Config()
        self.m = measure.Measurer()
        self.data = make_map()
        self.units = []
        import collections
        for el in rvdata.event_lists(self.data, "Map001.rvdata2"):
            extract.extract_list(el, self.cfg, self.units, {"names": {}},
                                 collections.Counter())
        self.glossary = {"names": {"エリス": {"en": "Eris"},
                                   "町人": {"en": "Townsperson"}}}

    def _apply(self, translations):
        data = make_map()
        rep = inject.Report()
        for u in self.units:
            u = copy.deepcopy(u)
            u["tl"] = translations.get(u["id"], "")
            inject._apply_unit(data, u, self.cfg, self.m, rep, self.glossary)
        return data, rep

    def _list(self, data):
        return rvdata.ptr_get(data, ["@events", {"h": 7}, "@pages", 0, "@list"])

    def test_command_count_never_changes(self):
        text_ids = [u["id"] for u in self.units if u["kind"] == "text"]
        long_line = ("Good morning everyone, isn't it a beautiful day today, "
                     "the kind of day that makes you want to walk to the next "
                     "town and back again before lunch?")
        data, rep = self._apply({text_ids[0]: long_line})
        before = len(self._list(make_map()).items)
        after = len(self._list(data).items)
        self.assertEqual(before, after)
        self.assertEqual([c.get("@code") for c in self._list(data).items],
                         [c.get("@code") for c in self._list(make_map()).items])

    def test_nametag_is_restored_in_english(self):
        text_ids = [u["id"] for u in self.units if u["kind"] == "text"]
        data, _rep = self._apply({text_ids[0]: "Morning, everyone."})
        first = self._list(data).items[1].get("@parameters").items[0].text()
        self.assertTrue(first.startswith(BS + "NAME[Eris]"), first)

    def test_untranslated_line_still_gets_an_english_plate(self):
        """A Japanese name plate over English dialogue is visible on screen and
        invisible to every per-unit check, because the tag is not part of any
        unit's text."""
        data, _rep = self._apply({})
        first = self._list(data).items[1].get("@parameters").items[0].text()
        self.assertTrue(first.startswith(BS + "NAME[Eris]"), first)
        self.assertIn("おはよう", first)

    def test_choice_mirrors_into_its_402(self):
        ch = [u for u in self.units if u["kind"] == "choice"][0]
        data, _rep = self._apply({ch["id"]: "Yes"})
        lst = self._list(data)
        self.assertEqual(lst.items[5].get("@parameters").items[0].items[0].text(),
                         "Yes")
        self.assertEqual(lst.items[6].get("@parameters").items[1].text(), "Yes")

    def test_faced_message_uses_the_narrower_budget(self):
        faced = [u for u in self.units if u.get("faced")][0]
        plain = [u for u in self.units if u["kind"] == "text"
                 and not u.get("faced")][0]
        self.assertEqual(inject.budget(faced, self.cfg)[0], self.cfg.face_width)
        self.assertEqual(inject.budget(plain, self.cfg)[0], self.cfg.width)

    def test_a_tall_message_is_paginated_not_flagged(self):
        """`Window_Message#process_new_line` calls `input_pause` then
        `new_page`, so a message taller than the box costs a click and loses
        nothing. Treating that as a defect is what makes a pipeline pay a model
        to compress prose the engine would have handled."""
        text_ids = [u["id"] for u in self.units if u["kind"] == "text"]
        wall = "supercalifragilistic " * 40
        _data, rep = self._apply({text_ids[0]: wall})
        self.assertEqual(rep.problems, [])
        self.assertTrue(rep.written["paginated"] >= 1)

    def test_width_overflow_is_still_reported(self):
        """Horizontal is the one that loses text: nothing in the engine wraps,
        and the contents bitmap simply stops."""
        ch = [u for u in self.units if u["kind"] == "choice"][0]
        _data, rep = self._apply({ch["id"]: "An extremely long menu choice "
                                            "that no choice window could ever "
                                            "hope to contain on one line"})
        self.assertTrue(any("cells" in p for p in rep.problems), rep.problems)


class TestRequests(unittest.TestCase):
    """Prove the request set is well formed BEFORE a run pays for it.

    Built with `retranslate_all=True` and failing loudly on an empty build,
    because a test whose fixtures come from PENDING work silently passes once
    the work is done."""

    def setUp(self):
        self.docs = [("x", {"meta": {"source_file": "Map001.rvdata2"},
                            "units": [
            {"id": "Map001:ev1:p0:c0", "kind": "text", "src": "あ", "raw": "あ",
             "tl": "done", "speaker": "エリス", "ctx": "scene A"},
            {"id": "Map001:ev1:p0:c4", "kind": "text", "src": "い", "raw": "い",
             "tl": "", "ctx": "scene A"},
            {"id": "Map001:ev2:p0:c0:ch0", "kind": "choice", "src": "はい",
             "raw": "はい", "tl": ""},
            {"id": "Map001:ev3:p0:c0:ch0", "kind": "choice", "src": "はい",
             "raw": "はい", "tl": ""},
        ]})]

    def test_pending_skips_finished_and_locked(self):
        got = [u["id"] for _d, u in R.pending(self.docs)]
        self.assertNotIn("Map001:ev1:p0:c0", got)
        self.assertIn("Map001:ev1:p0:c4", got)

    def test_identical_choices_are_deduped_once_globally(self):
        chunks = R.build_chunks(self.docs, 60)
        queued = [u["id"] for c in chunks for u in c["units"]]
        self.assertEqual(sum(1 for q in queued if q.endswith("ch0")), 1)

    def test_retranslate_all_builds_a_non_empty_set(self):
        chunks = R.build_chunks(self.docs, 60, retranslate_all=True)
        self.assertTrue(chunks)
        self.assertTrue(sum(len(c["units"]) for c in chunks) >= 3)

    def test_user_text_carries_speaker_and_scene(self):
        chunks = R.build_chunks(self.docs, 60, retranslate_all=True)
        text, idmap = R.build_user_text(chunks[0])
        self.assertIn("# scene: scene A", text)
        self.assertIn("speaker エリス", text)
        self.assertEqual(len(idmap), len(chunks[0]["units"]))

    def test_dummy_subject_is_scrubbed_even_when_it_bleeds(self):
        self.assertEqual(R.scrub_dummy_subject("Taro has fallen!"),
                         "has fallen!")
        # Prompt bleed puts the dummy name into a neighbouring item; the space
        # in front of it goes with it, so the possessive still reads right.
        self.assertEqual(R.scrub_dummy_subject("Eris Taro's poison faded"),
                         "Eris's poison faded")

    def test_a_prefixed_fragment_keeps_its_leading_space(self):
        """`Window_BattleLog` draws `subject.name + message1` with no
        separator. Japanese needs none and English does, so dropping it ships
        `Erisattacks!` in a log that only appears in combat."""
        self.assertEqual(R.scrub_dummy_subject("Taro attacks!", prefixed=True),
                         " attacks!")
        # ...but never in front of a possessive or punctuation.
        self.assertEqual(R.scrub_dummy_subject("Taro's poison faded",
                                               prefixed=True),
                         "'s poison faded")
        # A standalone fragment (Skill message2) gets no space.
        self.assertEqual(R.scrub_dummy_subject("The attack missed!"),
                         "The attack missed!")

    def test_apply_results_fans_out_a_deduped_group(self):
        glossary = {"names": {}}
        docs = copy.deepcopy(self.docs)
        # Dialogue and the deduped kinds land in DIFFERENT chunks (one per
        # file, plus the shared pool), so a test that applies only chunk 0
        # proves nothing about the fan-out.
        chunks = R.build_chunks(docs, 60)
        self.assertGreaterEqual(len(chunks), 2)
        results, id_maps = {}, {}
        for ch in chunks:
            cid = ch["custom_id"]
            _text, idmap = R.build_user_text(ch)
            id_maps[cid] = idmap
            results[cid] = {str(i + 1): "EN%d" % i for i in range(len(idmap))}
        applied, _names, errs = R.apply_results(docs, glossary, results,
                                                id_maps, {})
        self.assertEqual(errs, [])
        tls = {u["id"]: u["tl"] for _d, u in store.all_units(docs)}
        self.assertTrue(tls["Map001:ev2:p0:c0:ch0"])
        self.assertEqual(tls["Map001:ev2:p0:c0:ch0"],
                         tls["Map001:ev3:p0:c0:ch0"])


class TestValidate(unittest.TestCase):
    def u(self, **kw):
        base = {"id": "t", "kind": "text", "src": "テスト", "raw": "テスト",
                "tl": "", "codes": {}}
        base.update(kw)
        return base

    def test_number_drift_is_caught(self):
        self.assertIn("number-drift",
                      validate.hard_issues(self.u(src="3個ください",
                                                  tl="Give me 5, please")))

    def test_myriad_grouping_is_not_a_false_positive(self):
        self.assertNotIn("number-drift",
                         validate.hard_issues(self.u(src="5000万G",
                                                     tl="50,000,000G")))

    def test_spelled_out_english_is_not_a_false_positive(self):
        self.assertNotIn("number-drift",
                         validate.hard_issues(self.u(src="100年前",
                                                     tl="a hundred years ago")))

    def test_counter_gate_ignores_lexical_kanji(self):
        self.assertNotIn("number-drift",
                         validate.hard_issues(self.u(src="一体何が？",
                                                     tl="What on earth?")))

    def test_bare_escape_that_eats_a_word(self):
        self.assertIn("bare-escape-eats-word",
                      validate.hard_issues(self.u(tl=BS + "Helen smiled")))
        self.assertNotIn("bare-escape-eats-word",
                         validate.hard_issues(self.u(tl=BS + "NAME[Helen] hi")))

    def test_the_false_positives_measured_on_the_real_run(self):
        """Each pair below made the check fire on a CORRECT translation during
        the first real run. 246 flags became 47 by fixing the check, not the
        text, and these pin the lessons so a later edit cannot quietly undo
        them."""
        pairs = [
            ("２回目だ", "That's the second time"),      # ordinal, both forms
            ("３０回目", "the thirtieth"),
            ("３１本目", "the 31st"),
            ("３日目", "three days in"),                # ordinal read as cardinal
            ("３回戦", "round three"),
            ("２回ハメた", "had her twice"),             # 回 is cardinal here
            ("３回攻撃", "Triple Attack"),
            ("エミリオン宿屋１F", "Emilion Inn, 1F"),      # ミリオン is not a million
            ("地下２階", "the second basement floor"),
            ("２階の執務室", "his office on the second floor"),
            ("２等市民", "second-class citizens"),
            ("―――３時間後―――", "---Three hours later---"),   # dash, not a minus
            ("３，４本", "three or four"),               # a list, not a decimal
            ("四つん這い", "on all fours"),
            ("２度と", "never again"),
            ("世界に２つとない", "one-of-a-kind"),
            ("数千人", "several thousand"),              # indefinite on both sides
            ("人間の倍", "twice the size of a human"),
            ("オッズは２倍", "the odds are 2x"),
            ("サウザンドアロー", "Thousand Arrows"),
            ("doubled over", "doubled over"),
        ]
        for jp, en in pairs:
            self.assertNotIn("number-drift",
                             validate.hard_issues(self.u(src=jp, tl=en)),
                             "false positive on %r -> %r" % (jp, en))

    def test_the_real_drifts_still_fire(self):
        """The other half of the same measurement: the check has to keep
        catching what it exists for. The last pair is an actual defect this
        run produced - the inn's price vanished."""
        for jp, en in [("３個ください", "give me five"),
                       ("三日後", "in a few days"),
                       ("「一泊 10⟦0⟧ です", "One night is ⟦0⟧")]:
            self.assertIn("number-drift",
                          validate.hard_issues(self.u(src=jp, tl=en)),
                          "missed a real drift: %r -> %r" % (jp, en))

    def test_waiver_is_per_unit_and_per_check(self):
        u = self.u(src="3個", tl="five", waive={"number-drift": "the line "
                                                "counts a different thing"})
        self.assertNotIn("number-drift", validate.hard_issues(u))



class CrossTrackConflict(unittest.TestCase):
    """The defect that shipped: one town, two spellings, both tracks green.

    The units and the script ledger are translated by different passes, each
    internally consistent, so only a check that compares the two tracks can
    see it."""

    JP_TOWN = "マッスルーム"
    JP_CAPITAL = "王都バロン"

    def _store(self, ledger_en, unit_en, glossary_en=None):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with io.open(os.path.join(d, "scripts_rb.json"), "w",
                     encoding="utf-8") as f:
            json.dump({"entries": [{"jp": self.JP_TOWN, "en": ledger_en,
                                    "translate": True}]}, f)
        docs = [("units/Map001.json",
                 {"units": [{"id": "Map001:displayName", "kind": "mapname",
                             "src": self.JP_TOWN, "tl": unit_en}]})]
        glossary = {"names": {}, "terms": {}}
        if glossary_en:
            glossary["terms"][self.JP_TOWN] = glossary_en
        return docs, glossary, d

    def test_disagreement_is_reported(self):
        docs, glossary, d = self._store("Muscleroom", "Mussroom", "Mussroom")
        out = validate.cross_track_conflicts(docs, glossary, d)
        self.assertEqual(len(out), 1)
        jp, script_en, other = out[0]
        self.assertEqual(jp, self.JP_TOWN)
        self.assertEqual(script_en, "Muscleroom")
        self.assertIn(("glossary", "Mussroom"), other)
        self.assertIn(("mapname", "Mussroom"), other)

    def test_agreement_is_silent(self):
        docs, glossary, d = self._store("Muscleroom", "Muscleroom", "Muscleroom")
        self.assertEqual(validate.cross_track_conflicts(docs, glossary, d), [])

    def test_untranslated_ledger_entry_is_ignored(self):
        """A `translate: false` literal is a hash key, not a label."""
        docs, glossary, d = self._store("Muscleroom", "Mussroom")
        p = os.path.join(d, "scripts_rb.json")
        entries = json.load(io.open(p, encoding="utf-8"))
        entries["entries"][0]["translate"] = False
        with io.open(p, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        self.assertEqual(validate.cross_track_conflicts(docs, glossary, d), [])

    def test_missing_ledger_is_not_an_error(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(validate.cross_track_conflicts([], {}, d), [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
