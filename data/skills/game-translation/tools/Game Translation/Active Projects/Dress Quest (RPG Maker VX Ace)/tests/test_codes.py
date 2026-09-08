#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Text primitives. Every case here is a real failure someone shipped."""

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import codes, measure, wrap          # noqa: E402

BS = chr(92)                                    # keep the source readable


class TestDetection(unittest.TestCase):
    def test_has_jp(self):
        self.assertTrue(codes.has_jp("エリス"))
        self.assertTrue(codes.has_jp("１０年"))       # fullwidth digits
        self.assertTrue(codes.has_jp("ＯＰ"))          # fullwidth latin
        self.assertFalse(codes.has_jp("Eris"))
        self.assertFalse(codes.has_jp("100G"))

    def test_censor_masks_survive(self):
        """〇 and ● are censor marks, not untranslated text. Flagging them
        sends good lines into a retry that can only reproduce them."""
        self.assertFalse(codes.has_untranslated_jp("sh〇t"))
        self.assertFalse(codes.has_untranslated_jp("●●● took her"))

    def test_lone_katakana_is_residue_two_is_a_word(self):
        self.assertFalse(codes.has_untranslated_jp("Nhagiッ"))
        self.assertTrue(codes.has_untranslated_jp("Nhagi エリス"))

    def test_dakuten_survives_on_a_moan(self):
        self.assertFalse(codes.has_untranslated_jp("Agh゛-"))

    def test_strip_residual_kana_bails_on_a_real_miss(self):
        self.assertEqual(codes.strip_residual_kana("ぁ Eris"), "a Eris")
        # A full-size kana means a real miss: leave it for the retry queue.
        self.assertEqual(codes.strip_residual_kana("か Eris"), "か Eris")


class TestNameTag(unittest.TestCase):
    def test_split_and_retag(self):
        line = BS + "NAME[エリス]「おはよう"
        tag, body = codes.split_nametag(line)
        self.assertEqual(tag, BS + "NAME[エリス]")
        self.assertEqual(body, "「おはよう")
        self.assertEqual(codes.nametag_name(tag), "エリス")
        self.assertEqual(codes.retag(tag, "Eris"), BS + "NAME[Eris]")

    def test_no_tag(self):
        self.assertEqual(codes.split_nametag("ただの地の文"), ("", "ただの地の文"))

    def test_case_insensitive(self):
        tag, _b = codes.split_nametag(BS + "Name[町人]hello")
        self.assertEqual(codes.nametag_name(tag), "町人")

    def test_a_name_with_a_bracket_is_refused_not_written(self):
        """The engine's tag regex is non-greedy, so a `]` inside the name
        closes it early and the remainder prints into the message body. A
        Japanese plate is cosmetic; a broken tag corrupts the line."""
        tag = BS + "NAME[エリス]"
        self.assertTrue(codes.name_is_safe("Eris [the Knight]"))
        self.assertEqual(codes.retag(tag, "Eris [the Knight]"), tag)
        self.assertEqual(codes.retag(tag, "Eris"), BS + "NAME[Eris]")
        self.assertEqual(codes.name_is_safe("Eris"), "")

    def test_tag_costs_no_width(self):
        """`convert_escape_characters` deletes the tag before a glyph is drawn,
        so it must measure as zero. Missing this made every name-tagged line
        read ten cells too wide."""
        m = measure.Measurer()
        self.assertEqual(m.cells(BS + "NAME[調理場のおばちゃん]"), 0)
        self.assertEqual(m.cells(BS + "NAME[エリス]abc"), 3)


class TestMasking(unittest.TestCase):
    def test_mask_unmask_round_trip(self):
        src = "10" + BS + "G です" + BS + "$"
        masked, cmap = codes.mask_codes(src)
        self.assertNotIn(BS, masked)
        self.assertEqual(codes.unmask_codes(masked, cmap, pad_inserts=False), src)

    def test_word_insert_gets_a_space_in_english(self):
        """`Mana\\V[1]` reads `Mana25` with no pad. Japanese needs none, so the
        source has none, and the space has to be enforced on inject."""
        masked, cmap = codes.mask_codes("Mana" + BS + "V[1]")
        # pretend the model returned the same shape
        out = codes.unmask_codes(masked, cmap, pad_inserts=True)
        self.assertEqual(out, "Mana " + BS + "V[1]")

    def test_no_pad_against_punctuation_or_another_code(self):
        masked, cmap = codes.mask_codes("100" + BS + "G!")
        out = codes.unmask_codes(masked, cmap, pad_inserts=True)
        self.assertEqual(out, "100 " + BS + "G!")
        masked, cmap = codes.mask_codes(BS + "V[1]" + BS + "G")
        self.assertEqual(codes.unmask_codes(masked, cmap, pad_inserts=True),
                         BS + "V[1]" + BS + "G")

    def test_dropped_sentinel_is_visible_to_validation(self):
        masked, cmap = codes.mask_codes("a" + BS + "G b")
        self.assertEqual(codes.placeholder_ids(masked), {0})
        self.assertEqual(codes.placeholder_ids("a b"), set())


class TestCleaning(unittest.TestCase):
    def test_clean_source_keeps_a_pacing_gap(self):
        out = codes.clean_source("どうしたんだい！？　ずいぶん")
        self.assertEqual(out, "どうしたんだい！？ ずいぶん")

    def test_clean_source_drops_a_leading_indent(self):
        self.assertEqual(codes.clean_source("　向かわせた"), "向かわせた")

    def test_clean_source_keeps_fullwidth_latin(self):
        """A whole-string NFKC would flatten the fullwidth characters the
        author uses on purpose."""
        self.assertEqual(codes.clean_source("ＯＰ１"), "ＯＰ１")

    def test_clean_translation_refuses_to_dress_up_japanese(self):
        """A unit that failed still holds source text and must be written back
        byte-exact, not wearing English punctuation."""
        jp = "「大丈夫ですか！」"
        self.assertEqual(codes.clean_translation(jp), jp)

    def test_clean_translation_normalises_english(self):
        self.assertEqual(codes.clean_translation("「Hi！」"), '"Hi!"')


class TestWrap(unittest.TestCase):
    def setUp(self):
        self.m = measure.Measurer()

    def test_width_is_a_hard_constraint(self):
        text = "The quick brown fox jumps over the lazy dog " * 3
        f = wrap.fit(text, 30, 8, self.m)
        self.assertTrue(all(self.m.cells(l) <= 30 for l in f.text.split("\n")))

    def test_rows_overflow_is_reported_not_hidden(self):
        text = "word " * 80
        f = wrap.fit(text, 20, 4, self.m)
        self.assertTrue(f.overflow_rows)
        self.assertFalse(f.ok)

    def test_last_line_is_charged(self):
        """Free-tail Knuth-Plass ships a two-word orphan under a full line."""
        text = ("Let me divine the path you should walk. "
                "It will cost you 500G, how about it?")
        f = wrap.fit(text, 45, 4, self.m)
        lines = f.text.split("\n")
        self.assertGreaterEqual(len(lines), 2)
        self.assertGreater(len(lines[-1]), 12, f.text)

    def test_a_control_code_is_one_atom(self):
        """A break inside a code produces one the engine cannot parse. The tag
        is wider than the box here, so a character-wise wrapper would split
        it."""
        text = "aaa " + BS + "NAME[Someone] bbb"
        f = wrap.fit(text, 8, 6, self.m)
        self.assertIn(BS + "NAME[Someone]", f.text)
        for line in f.text.split("\n"):
            self.assertEqual(line.count("["), line.count("]"), line)

    def test_redistribute_keeps_the_command_count(self):
        self.assertEqual(wrap.redistribute(["a", "b", "c"], 2), [["a", "b"], ["c"]])
        self.assertEqual(wrap.redistribute(["a"], 3), [["a"], [], []])


if __name__ == "__main__":
    unittest.main(verbosity=2)
