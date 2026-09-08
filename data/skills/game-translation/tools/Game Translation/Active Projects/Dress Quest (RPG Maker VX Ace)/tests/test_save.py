#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""The save translator, against a save this test builds itself.

There is no save file in the repo and none on a fresh machine, so without this
`tools/translate_save.py` would ship having never run. The synthetic save is
built to the shape `DataManager.make_save_contents` produces, read off the
game's own script:

    Marshal.dump(header)     # a Hash - the save-list row
    Marshal.dump(contents)   # a Hash keyed :system :timer :message :switches
                             # :variables :self_switches :actors :party :troop
                             # :map :player

The two things it has to get right are the two that are easy to miss: a
`Game_Actor` copied its name out of the database at new-game and never re-reads
it, and `Game_Map` carries the WHOLE `RPG::Map` of the map the player is
standing on - with the SAME `RPG::Event` objects its `Game_Event`s hold, an
identity Marshal preserves through a link.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))

from acetl import config, rvdata, store                       # noqa: E402
from acetl import rvmarshal as M                              # noqa: E402

BS = chr(92)


def S(t):
    return M.RString(t.encode("utf-8"), [(M.RSymbol(b"E"), True)])


def cmd(code, params):
    return M.RObject(M.RSymbol(b"RPG::EventCommand"), [
        (M.RSymbol(b"@code"), code),
        (M.RSymbol(b"@indent"), 0),
        (M.RSymbol(b"@parameters"), M.RArray(list(params)))])


def build_save():
    """(bytes, the RPG::Event object shared by the map and the Game_Event)."""
    lst = M.RArray([
        cmd(101, [S(""), 0, 0, 2]),
        cmd(401, [S(BS + "NAME[エリス]「行きましょう。")]),
        cmd(0, []),
    ])
    page = M.RObject(M.RSymbol(b"RPG::Event::Page"), [(M.RSymbol(b"@list"), lst)])
    ev = M.RObject(M.RSymbol(b"RPG::Event"), [
        (M.RSymbol(b"@id"), 3), (M.RSymbol(b"@name"), S("EV003")),
        (M.RSymbol(b"@x"), 4), (M.RSymbol(b"@y"), 5),
        (M.RSymbol(b"@pages"), M.RArray([page]))])
    rpg_map = M.RObject(M.RSymbol(b"RPG::Map"), [
        (M.RSymbol(b"@display_name"), S("コロン村")),
        (M.RSymbol(b"@events"), M.RHash([(3, ev)]))])

    # Game_Event holds the SAME RPG::Event instance, exactly as
    # `Game_Map#setup_events` builds it.
    game_event = M.RObject(M.RSymbol(b"Game_Event"), [
        (M.RSymbol(b"@map_id"), 1), (M.RSymbol(b"@event"), ev),
        (M.RSymbol(b"@id"), 3), (M.RSymbol(b"@list"), lst)])
    game_map = M.RObject(M.RSymbol(b"Game_Map"), [
        (M.RSymbol(b"@map_id"), 1), (M.RSymbol(b"@map"), rpg_map),
        (M.RSymbol(b"@events"), M.RHash([(3, game_event)])),
        (M.RSymbol(b"@interpreter"), M.RObject(M.RSymbol(b"Game_Interpreter"), [
            (M.RSymbol(b"@index"), 1), (M.RSymbol(b"@list"), lst)]))])

    actor = M.RObject(M.RSymbol(b"Game_Actor"), [
        (M.RSymbol(b"@actor_id"), 1), (M.RSymbol(b"@name"), S("エリス")),
        (M.RSymbol(b"@nickname"), S("白蓮の騎士")), (M.RSymbol(b"@level"), 12)])
    actors = M.RObject(M.RSymbol(b"Game_Actors"), [
        (M.RSymbol(b"@data"), M.RArray([None, actor]))])

    header = M.RHash([
        (M.RSymbol(b"playtime_s"), 3600),
        (M.RSymbol(b"map_name"), S("コロン村"))])
    contents = M.RHash([
        (M.RSymbol(b"system"), M.RObject(M.RSymbol(b"Game_System"),
                                         [(M.RSymbol(b"@save_count"), 3)])),
        (M.RSymbol(b"switches"), M.RObject(M.RSymbol(b"Game_Switches"),
                                           [(M.RSymbol(b"@data"), M.RArray([]))])),
        (M.RSymbol(b"actors"), actors),
        (M.RSymbol(b"map"), game_map),
    ])
    return M.dumps_many([header, contents]), ev


def build_store(tmp, ptr):
    """A one-unit store whose pointer addresses the synthetic map's line."""
    os.makedirs(os.path.join(tmp, "units"), exist_ok=True)
    doc = {"meta": {"source_file": "Map001.rvdata2"}, "units": [{
        "id": "Map001:ev3:p0:c1", "kind": "text",
        "sites": [{"ptr": ptr, "start": 1, "count": 1}],
        "src": "「行きましょう。", "raw": BS + "NAME[エリス]「行きましょう。",
        "nametag": BS + "NAME[エリス]", "speaker": "エリス", "codes": {},
        "tl": "Let's go."}]}
    with open(os.path.join(tmp, "units", "Map001.json"), "w",
              encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    with open(os.path.join(tmp, "glossary.json"), "w", encoding="utf-8") as f:
        json.dump({"names": {"エリス": {"en": "Eris"},
                             "白蓮の騎士": {"en": "Knight of the White Lotus"}},
                   "terms": {}, "do_not_translate": []}, f, ensure_ascii=False)
    return tmp


class TestSaveTranslation(unittest.TestCase):
    def setUp(self):
        import translate_save
        self.ts = translate_save
        self.cfg = config.Config()
        self.tmp = tempfile.mkdtemp(prefix="acetl_save_")
        self.save = os.path.join(self.tmp, "Save01.rvdata2")
        blob, _ev = build_save()
        with open(self.save, "wb") as f:
            f.write(blob)
        self.store = build_store(os.path.join(self.tmp, "tl"),
                                 ["@events", {"h": 3}, "@pages", 0, "@list"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self):
        by_map, raw_to_en, glossary = self.ts.build_maps(self.cfg, self.store)
        self.ts.process(self.save, self.cfg, by_map, raw_to_en, glossary,
                        apply=True, verbose=False)
        return M.loads_many(open(self.save, "rb").read())

    def test_the_save_still_parses_and_keeps_its_two_documents(self):
        docs = self._run()
        self.assertEqual(len(docs), 2)

    def test_actor_name_and_nickname_come_from_the_glossary(self):
        _header, contents = self._run()
        actors = contents.get("actors")
        a = actors.get("@data").items[1]
        self.assertEqual(a.get("@name").text(), "Eris")
        self.assertEqual(a.get("@nickname").text(), "Knight of the White Lotus")

    def test_the_baked_map_is_translated_through_the_store(self):
        _header, contents = self._run()
        gm = contents.get("map")
        lst = gm.get("@map").get("@events").pairs[0][1] \
                .get("@pages").items[0].get("@list")
        line = lst.items[1].get("@parameters").items[0].text()
        self.assertEqual(line, BS + "NAME[Eris]Let's go.")

    def test_the_game_event_sees_the_same_change(self):
        """`Game_Event#@event` IS `@map.events[i]`. If the injector replaced
        the RPG::Event instead of editing inside it, the running event would
        still be Japanese and only the stored copy would look right."""
        _header, contents = self._run()
        gm = contents.get("map")
        from_map = gm.get("@map").get("@events").pairs[0][1]
        from_events = gm.get("@events").pairs[0][1].get("@event")
        self.assertIs(from_map, from_events)
        line = from_events.get("@pages").items[0].get("@list") \
            .items[1].get("@parameters").items[0].text()
        self.assertIn("Let's go.", line)

    def test_the_interpreter_index_is_untouched(self):
        _header, contents = self._run()
        interp = contents.get("map").get("@interpreter")
        self.assertEqual(interp.get("@index"), 1)
        self.assertEqual(len(interp.get("@list").items), 3)

    def test_a_backup_is_kept(self):
        self._run()
        self.assertTrue(os.path.exists(self.save + ".bak"))
        # and the backup is still the untranslated original
        _h, c = M.loads_many(open(self.save + ".bak", "rb").read())
        self.assertEqual(c.get("actors").get("@data").items[1].get("@name").text(),
                         "エリス")


if __name__ == "__main__":
    unittest.main(verbosity=2)
