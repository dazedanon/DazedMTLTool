#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ruby Marshal reader/writer: the cases that are real failures, not fixtures.

The headline test is the corpus round trip - all 231 shipped .rvdata2 files
read and written back byte for byte - because that is the property the whole
injection design rests on. The unit tests below cover the three things that
would break it in a way a round trip might not notice on this particular game.
"""

import os
import sys
import glob
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import rvmarshal as M          # noqa: E402
from acetl import config                  # noqa: E402


class TestPrimitives(unittest.TestCase):
    def rt(self, obj):
        return M.loads(M.dumps(obj))

    def test_long_encoding_matches_ruby(self):
        # marshal.c w_long: 0, the 1-byte inline range, and the multi-byte
        # forms in both signs. A legal-but-different encoding of the same
        # number is a different FILE, which is why this is pinned.
        cases = {0: b"\x00", 1: b"\x06", 122: b"\x7f", 123: b"\x01\x7b",
                 -1: b"\xfa", -123: b"\x80", -124: b"\xff\x84",
                 256: b"\x02\x00\x01", 0x7fffffff: b"\x04\xff\xff\xff\x7f"}
        for n, want in cases.items():
            w = M.Writer()
            w.long(n)
            self.assertEqual(w.bytes(), want, "w_long(%d)" % n)
            r = M.Reader(want)
            self.assertEqual(r.long(), n, "r_long(%r)" % want)

    def test_scalars(self):
        for v in (None, True, False, 0, 1, -1, 300, -300, 1073741823):
            self.assertEqual(self.rt(v), v)

    def test_string_ivars_round_trip(self):
        s = M.RString("エリス".encode("utf-8"), [(M.RSymbol(b"E"), True)])
        out = self.rt(s)
        self.assertEqual(out.data, s.data)
        self.assertEqual([k.name for k, _v in out.ivars], [b"E"])
        # A bare string (no ivars) must NOT gain the `I` wrapper.
        bare = M.RString(b"abc")
        self.assertEqual(M.dumps(bare), b"\x04\x08\"\x08abc")

    def test_object_identity_becomes_a_link(self):
        """Two references to ONE string are one string plus a link; two equal
        but distinct strings are two strings. Collapsing them is exactly what
        mapping Marshal strings onto interned Python `str` would do."""
        shared = M.RString(b"same")
        linked = M.dumps(M.RArray([shared, shared]))
        twin = M.dumps(M.RArray([M.RString(b"same"), M.RString(b"same")]))
        self.assertLess(len(linked), len(twin))
        back = M.loads(linked)
        self.assertIs(back.items[0], back.items[1])
        back2 = M.loads(twin)
        self.assertIsNot(back2.items[0], back2.items[1])

    def test_symbol_links(self):
        sym = M.RSymbol(b"code")
        o1 = M.RObject(M.RSymbol(b"RPG::EventCommand"), [(sym, 401)])
        o2 = M.RObject(M.RSymbol(b"RPG::EventCommand"), [(sym, 101)])
        blob = M.dumps(M.RArray([o1, o2]))
        # The class name and the ivar name are each written once, then linked.
        self.assertEqual(blob.count(b"RPG::EventCommand"), 1)
        self.assertEqual(blob.count(b"code"), 1)

    def test_float_text_is_preserved(self):
        f = M.RFloat(b"0.5")
        self.assertEqual(M.dumps(f), M.dumps(self.rt(f)))
        self.assertEqual(self.rt(f).value, 0.5)

    def test_userdef_payload_is_opaque(self):
        t = M.RUserDef(M.RSymbol(b"Table"), b"\x01\x02\x03\x04")
        self.assertEqual(self.rt(t).data, b"\x01\x02\x03\x04")

    def test_trailing_bytes_are_an_error(self):
        with self.assertRaises(M.MarshalError):
            M.loads(M.dumps(1) + b"\x00")

    def test_many_documents(self):
        """A VX Ace save is two Marshal documents in one file."""
        blob = M.dumps_many([M.RHash([(M.RSymbol(b"a"), 1)]), M.RArray([1, 2])])
        docs = M.loads_many(blob)
        self.assertEqual(len(docs), 2)
        self.assertEqual(M.dumps_many(docs), blob)


class TestCorpusRoundTrip(unittest.TestCase):
    """The acceptance test. Skipped, loudly, when the game is not on this box."""

    def test_every_data_file(self):
        cfg = config.Config()
        files = sorted(glob.glob(os.path.join(cfg.data_dir, "*.rvdata2")))
        if not files:
            self.skipTest("no game data at %s" % cfg.data_dir)
        bad = []
        for p in files:
            ok, why = M.roundtrip_ok(p)
            if not ok:
                bad.append("%s: %s" % (os.path.basename(p), why))
        self.assertEqual(bad, [], "%d/%d files did not round-trip"
                         % (len(bad), len(files)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
