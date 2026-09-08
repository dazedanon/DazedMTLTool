#!/usr/bin/env python3
"""Offline regression tests. No API key, no network, no cost.

    python tools/scripts/tests/test_pipeline.py

Covers the two places this pipeline has historically broken: the mask/restore
round-trip, and parsing model JSON that is not quite JSON.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tyranotl import (codes, inject, jsstr, kslex, layout, prompts,  # noqa: E402
                      rewrap, savetext, sites, validate, widgets)  # noqa: E402
from tyranotl.store import Glossary, Site, Store, Unit, unit_id   # noqa: E402


class TestMasking(unittest.TestCase):
    def test_round_trip(self):
        raw = '[cm][s_e6]まだイグ゛ぅ[emb exp="f.ingo[f.ingo_LV][f.ingo_rd]"]きちゃ♡[p][endif]'
        masked, tokens = codes.mask(raw)
        self.assertEqual(codes.restore(masked, tokens), raw)
        self.assertEqual(len(tokens), 5)

    def test_split_affixes(self):
        raw = "[cm][s_e6]hello[emb exp=x]world[p][endif]"
        masked, _ = codes.mask(raw)
        prefix, middle, suffix = codes.split_affixes(masked)
        self.assertEqual(prefix, "⟦0⟧⟦1⟧")          # [cm][s_e6]
        self.assertEqual(suffix, "⟦3⟧⟦4⟧")          # [p][endif]
        self.assertEqual(middle, "hello⟦2⟧world")   # inline [emb] keeps its place
        self.assertEqual(prefix + middle + suffix, masked)

    def test_split_affixes_all_tags(self):
        masked, _ = codes.mask("[cm][clearfix]")
        prefix, middle, suffix = codes.split_affixes(masked)
        self.assertEqual(middle, "")
        self.assertEqual(prefix + middle + suffix, masked)

    def test_html_is_masked(self):
        raw = "改行します<br>つづき"
        masked, tokens = codes.mask(raw)
        self.assertEqual(tokens, ["<br>"])
        self.assertEqual(codes.restore(masked, tokens), raw)

    def test_placeholder_validation(self):
        self.assertTrue(codes.placeholders_ok("a⟦0⟧b⟦1⟧", "⟦1⟧x⟦0⟧y"))
        self.assertFalse(codes.placeholders_ok("a⟦0⟧b⟦1⟧", "a⟦0⟧b"))
        self.assertFalse(codes.placeholders_ok("a⟦0⟧", "a⟦0⟧⟦0⟧"))


class TestJapaneseDetection(unittest.TestCase):
    def test_positive(self):
        for text in ("こんにちは", "カタカナ", "漢字", "々", "〆"):
            self.assertTrue(codes.has_jp(text), text)

    def test_censor_and_slur_marks_are_not_japanese(self):
        # 〇 masks an obscenity and legitimately survives; ゛ is a slur diacritic
        # the author hangs on vowels; ー and ・ are separators.
        for text in ("sh〇t", "●●●", 'aa゛', "Nero・Koko", "Aaaー"):
            self.assertFalse(codes.residual_jp(text), text)

    def test_kana_is_residual(self):
        self.assertEqual(codes.residual_jp("Cummingっ"), ["っ"])

    def test_punct_conversion_keeps_pacing_space(self):
        self.assertEqual(codes.convert_punct("！？"), "!?")
        self.assertIn("　", codes.convert_punct("あ　あ"))


class TestJsStrings(unittest.TestCase):
    def test_comment_is_not_a_literal(self):
        src = '// "コメント"\nvar a = "本文";'
        found = jsstr.scan(src)
        self.assertEqual([s.value for s in found], ["本文"])

    def test_url_inside_string_is_not_a_comment(self):
        src = 'var u = "https://example.com/x"; var t = "本文";'
        self.assertEqual([s.value for s in jsstr.scan(src)], ["https://example.com/x", "本文"])

    def test_spans_are_exact(self):
        src = "f.a=['扉','演算機']"
        found = jsstr.scan(src)
        for literal in found:
            self.assertEqual(src[literal.start:literal.end], literal.raw)

    def test_encode_escapes_delimiter(self):
        self.assertEqual(jsstr.encode("it's", "'"), "it\\'s")
        self.assertEqual(jsstr.encode('say "hi"', '"'), 'say \\"hi\\"')
        self.assertEqual(jsstr.decode(jsstr.encode("a\\b\"c", '"')), 'a\\b"c')


class TestLexer(unittest.TestCase):
    def test_line_endings_preserved(self):
        import tempfile
        for payload in (b"a\r\nb\r\n", b"a\nb", b"", b"a\r\nb\n"):
            with tempfile.NamedTemporaryFile(suffix=".ks", delete=False) as fh:
                fh.write(payload)
                path = Path(fh.name)
            try:
                script = kslex.read(path, "x.ks")
                self.assertEqual(script.render().encode("utf-8"), payload, payload)
            finally:
                path.unlink()

    def test_quoted_bracket_in_attr(self):
        tags = kslex.scan_tags('[emb exp="f.ingo[f.ingo_LV][f.rd]"]')
        self.assertEqual(len(tags), 1)
        self.assertEqual(tags[0].attrs[0].value, "f.ingo[f.ingo_LV][f.rd]")

    def test_at_line_is_a_tag(self):
        tags = kslex.scan_tags('@jump storage="title.ks"')
        self.assertEqual(tags[0].name, "jump")
        self.assertEqual(tags[0].attrs[0].value, "title.ks")

    def test_attr_span_is_exact(self):
        line = '[glink text="戻る" size="45"]'
        tag = kslex.scan_tags(line)[0]
        for attr in tag.attrs:
            self.assertEqual(line[attr.start:attr.end], attr.value)


class TestSites(unittest.TestCase):
    def test_known_and_unknown(self):
        self.assertEqual(sites.classify_attr("glink", "text"), ("text", "choice"))
        self.assertEqual(sites.classify_attr("chara_layer", "storage")[0], "skip")
        self.assertEqual(sites.classify_attr("eval", "exp")[0], "code")
        self.assertEqual(sites.classify_attr("wobble", "caption")[0], "unknown")

    def test_asset_detection(self):
        self.assertTrue(sites.looks_like_asset("kokotaiki/目笑い.png"))
        self.assertFalse(sites.looks_like_asset("戻る"))


NBSP = " "


class TestAttributeSpaces(unittest.TestCase):
    """KAG's makeTag() deletes literal spaces inside quoted attribute values, so
    English labels arrive glued together. Verified against the game's own parser;
    U+00A0 is the only character that survives it and still renders as a space in
    .html(), .text() and document.title alike."""

    @staticmethod
    def _site(form, tag=""):
        return Site(file="x.ks", line=1, start=0, end=1, form=form, tag=tag, quote='"')

    def _render(self, form, tag, text):
        unit = Unit(id="u", kind="choice", src="X")
        unit.en = text
        site = self._site(form, tag)
        unit.sites.append(site)
        return inject.render(unit, site)

    def test_attribute_value_gets_nbsp(self):
        self.assertEqual(self._render("attr", "glink", "Just talk normally"),
                         NBSP.join(['"Just', "talk", 'normally"']))

    def test_js_literal_inside_an_exp_attribute_gets_nbsp(self):
        self.assertIn("Bench" + NBSP + "Press", self._render("jsstr", "eval", "Bench Press"))

    def test_iscript_and_engine_js_keep_real_spaces(self):
        for tag in ("iscript", "js"):
            rendered = self._render("jsstr", tag, "Bench Press")
            self.assertIn("Bench Press", rendered)
            self.assertNotIn(NBSP, rendered)

    def test_message_text_keeps_real_spaces(self):
        unit = Unit(id="u", kind="dialogue", src="X")
        unit.en = "He said hello"
        site = Site(file="x.ks", line=1, start=0, end=1, form="bare")
        unit.sites.append(site)
        self.assertEqual(inject.render(unit, site), "He said hello")

    def test_round_trip(self):
        self.assertEqual(codes.unprotect_spaces(codes.protect_spaces("a b c")), "a b c")


class TestInlineInserts(unittest.TestCase):
    """[name2] and the lewd-word macros expand to a word at run time. Japanese
    needs no space around one, so a faithful translation keeps none and the
    player reads "NeroIs that alright?"."""

    MACROS = "\n".join([
        '[macro name="name2"]', '[emb exp="f.name2"]', '[endmacro]',
        '[macro name="ig_tntn"]', '[getrand var="tf.rd" min="0" max="6"]',
        '[emb exp="f.ingo_tinko[f.ingo_LV][tf.rd]"]', '[endmacro]',
        '[macro name="like_lv1"]', '[cm]', 'likes went up[p]', '[endmacro]',
    ])

    def test_emitters_found_from_the_project_macros(self):
        found = codes.inline_emitters(self.MACROS)
        self.assertIn("name2", found)
        # indexes with "]" inside the quoted exp - a naive regex misses this one
        self.assertIn("ig_tntn", found)
        self.assertIn("emb", found)
        # emits a whole line, not a word
        self.assertNotIn("like_lv1", found)

    def test_spacing_rules(self):
        yes = lambda i: True
        self.assertEqual(codes.space_around_inserts("⟦0⟧Is that ok?", yes),
                         "⟦0⟧ Is that ok?")
        self.assertEqual(codes.space_around_inserts("Koko,⟦0⟧and me", yes),
                         "Koko, ⟦0⟧ and me")
        for tight in ("⟦0⟧'s cock", "⟦0⟧-chan", "⟦0⟧♡", "(⟦0⟧)"):
            self.assertEqual(codes.space_around_inserts(tight, yes), tight)

    def test_non_emitters_are_left_alone(self):
        self.assertEqual(codes.space_around_inserts("done⟦0⟧next", lambda i: False),
                         "done⟦0⟧next")

    def test_padding_across_a_peeled_affix(self):
        # split_affixes peels a leading tag run off the unit, so an emitter
        # sitting against it is outside the unit and only injection can fix it
        line = '[emb exp="f.name2"]Is that alright?[r]'
        patch = inject.Patch(19, 35, "Is that alright?", "u")
        self.assertEqual(inject.pad_inline_inserts(line, patch, {"emb"}),
                         " Is that alright?")
        self.assertEqual(inject.pad_inline_inserts(line, patch, set()),
                         "Is that alright?")


class TestReplyParsing(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(prompts.parse_reply('{"t":{"0":"hi","1":"there"}}'),
                         {"0": "hi", "1": "there"})

    def test_fenced(self):
        self.assertEqual(prompts.parse_reply('```json\n{"t":{"0":"hi"}}\n```'), {"0": "hi"})

    def test_unescaped_quote_inside_value(self):
        # The JP uses an ASCII quote as a dakuten and the model carries it over.
        reply = '{"t":{"0":"...enjoy the show? Aa"♥"","1":"ok"}}'
        table = prompts.parse_reply(reply)
        self.assertEqual(len(table), 2)
        self.assertIn("♥", table["0"])
        self.assertEqual(table["1"], "ok")

    def test_properly_escaped_quote_survives(self):
        table = prompts.parse_reply('{"t":{"0":"he said \\"hi\\""}}')
        self.assertEqual(table["0"], 'he said "hi"')

    def test_self_correction_keeps_the_bigger_object(self):
        reply = ('{"t":{"0":"partial"}}\n\nWait, I need to output all 3 entries.\n\n'
                 '{"t":{"0":"a","1":"b","2":"c"}}')
        self.assertEqual(prompts.parse_reply(reply), {"0": "a", "1": "b", "2": "c"})

    def test_braces_and_colons_inside_text(self):
        table = prompts.parse_reply('{"t":{"0":"use {0} here: now"}}')
        self.assertEqual(table["0"], "use {0} here: now")

    def test_garbage_returns_empty(self):
        self.assertEqual(prompts.parse_reply("I cannot help with that."), {})


class TestApplyReply(unittest.TestCase):
    @staticmethod
    def _unit(src: str) -> Unit:
        unit = Unit(id=unit_id("dialogue", src), kind="dialogue", src=src)
        unit.sites.append(Site(file="x.ks", line=1, start=0, end=1, order=1))
        return unit

    def test_accepts_good(self):
        unit = self._unit("こんにちは⟦0⟧")
        request = prompts.Request(key="k", kind="dialogue", phase="text", units=[unit])
        applied, problems = prompts.apply_reply(request, {"0": "Hello⟦0⟧"})
        self.assertEqual((applied, problems), (1, []))
        self.assertEqual(unit.status, "done")

    def test_flags_placeholder_loss(self):
        unit = self._unit("こんにちは⟦0⟧")
        request = prompts.Request(key="k", kind="dialogue", phase="text", units=[unit])
        applied, problems = prompts.apply_reply(request, {"0": "Hello"})
        self.assertEqual(applied, 0)
        self.assertEqual(unit.status, "flagged")
        self.assertTrue(problems)

    def test_flags_literal_placeholder_word(self):
        unit = self._unit("こんにちは")
        request = prompts.Request(key="k", kind="dialogue", phase="text", units=[unit])
        prompts.apply_reply(request, {"0": "placeholder"})
        self.assertEqual(unit.status, "flagged")

    def test_reports_missing_id(self):
        unit = self._unit("こんにちは")
        request = prompts.Request(key="k", kind="dialogue", phase="text", units=[unit])
        applied, problems = prompts.apply_reply(request, {})
        self.assertEqual(applied, 0)
        self.assertIn("missing", problems[0])


class TestPromptShape(unittest.TestCase):
    def test_two_cache_breakpoints(self):
        glossary = Glossary(Path("nonexistent.json")).load()
        blocks = prompts.system_blocks("BIBLE", glossary, "1h")
        self.assertEqual(len(blocks), 2)
        for block in blocks:
            self.assertEqual(block["cache_control"], {"type": "ephemeral", "ttl": "1h"})

    def test_no_sampling_params_on_opus_5(self):
        from tyranotl import pricing
        self.assertEqual(pricing.sampling_params("claude-opus-5"), {})
        self.assertEqual(pricing.sampling_params("claude-haiku-4-5"), {"temperature": 0})

    def test_price_longest_prefix_wins(self):
        from tyranotl import pricing
        self.assertEqual(pricing.price_for("claude-opus-4-8")["in"], 5.0)
        self.assertEqual(pricing.price_for("claude-haiku-4-5")["out"], 5.0)
        self.assertEqual(pricing.price_for("claude-sonnet-5", batch=True)["out"], 5.0)


class TestRewrap(unittest.TestCase):
    """The line-layout pass: overflowing breaks and glued line junctions."""

    MACRO = (
        '[macro name="show_mesS"]\n'
        '[position layer="message0" width="1210" height="300" top="850" left="0"]\n'
        '[position layer="message0" page=fore margint="65" marginl="50" marginr="70"]\n'
        '[endmacro]\n'
    )

    def _tree(self, body: str) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp())
        (root / "data" / "scenario" / "system").mkdir(parents=True)
        (root / "data" / "scenario" / "system" / "macro.ks").write_text(
            self.MACRO, encoding="utf-8")
        (root / "data" / "scenario" / "scene.ks").write_text(body, encoding="utf-8")
        return root

    def _run(self, body: str) -> str:
        root = self._tree(body)
        plan = rewrap.scan(root, root, {"emb"})
        rewrap.apply(root, plan)
        return (root / "data" / "scenario" / "scene.ks").read_text(encoding="utf-8")

    def test_box_width_comes_from_the_macro(self):
        root = self._tree("[show_mesS]\nhi[p]\n")
        self.assertEqual(rewrap.message_boxes(root)["show_mesS"].width, 1090)

    def test_overflowing_break_is_dropped_and_its_join_spaced(self):
        out = self._run(
            "[show_mesS]\n"
            "Affection rises through physical contact and using the syringe,[r]\n"
            "and Lewdness rises when you have sex.[p]\n")
        self.assertNotIn("[r]", out)
        self.assertIn("_ and Lewdness", out)

    def test_a_break_that_fits_is_left_alone(self):
        out = self._run("[show_mesS]\nShort line.[r]\nSecond line.[p]\n")
        self.assertIn("Short line.[r]", out)
        self.assertNotIn("_ Second", out)

    def test_lr_keeps_its_click_wait(self):
        out = self._run(
            "[show_mesS]\n"
            "Affection rises through physical contact and using the syringe,[lr]\n"
            "and Lewdness rises when you have sex.[p]\n")
        self.assertIn("[l]", out)
        self.assertNotIn("[lr]", out)

    def test_glued_junction_is_spaced_without_touching_any_break(self):
        out = self._run("[show_mesS]\nOne sentence.\nAnother sentence.[p]\n")
        self.assertIn("_ Another sentence.", out)

    def test_japanese_junction_needs_no_space(self):
        out = self._run(
            "[show_mesS]\n完全に異なる生理構造を有する。\n彼女たちは体内の特殊器官。[p]\n")
        self.assertNotIn("_ ", out)

    def test_a_mid_line_break_keeps_exactly_one_space(self):
        out = self._run(
            "[show_mesS]\n"
            'Gather the needed materials through "Scavenge" and build a bath [r]'
            'from "Room Expansion"[p]\n')
        self.assertIn("build a bath from", out)
        self.assertNotIn("bath  from", out)

    def test_a_break_with_no_space_either_side_gains_one(self):
        out = self._run(
            "[show_mesS]\n"
            "Affection rises through physical contact and using the syringe,[r]"
            "and Lewdness rises when you have sex.[p]\n")
        self.assertIn("syringe, and Lewdness", out)

    def test_iscript_bodies_are_never_touched(self):
        body = "[iscript]\nvar a = f.x,\nb = f.y;\n[endscript]\n"
        self.assertEqual(self._run(body), body)

    def test_ruby_is_removed(self):
        out = self._run("[show_mesS]\n"
                        'could I have some [ruby  text="semen"]semen?[p]\n')
        self.assertNotIn("[ruby", out)
        self.assertIn("could I have some semen?[p]", out)

    def test_ruby_removal_leaves_the_rest_of_the_line_alone(self):
        out = self._run("[show_mesS]\n"
                        '[kutipati]A [ruby text="gloss"]word here.[p]\n')
        self.assertIn("[kutipati]A word here.[p]", out)

    LARGE = ('[macro name="show_mesL"]\n'
             '[position layer="message0" width="1920" height="300" top="850" left="0"]\n'
             '[position layer="message0" page=fore margint="65" marginl="50" marginr="70"]\n'
             "[endmacro]\n")

    def _large_tree(self, body: str) -> Path:
        root = self._tree(body)
        (root / "data" / "scenario" / "system" / "macro.ks").write_text(
            self.MACRO + self.LARGE, encoding="utf-8")
        return root

    def _flush_line(self, root: Path) -> str:
        """A line that fills 95-100% of the 1800px box under whatever metric is
        in force - the test tree has no font file, so `layout.measure` falls
        back to its cell estimate and a fixed sentence would not land in range."""
        # short words so the greedy fill lands close under the limit; a long
        # word can overshoot far enough to stop below the 95% the pass wants
        words, line = ["ab", "cd", "ef", "gh", "ij", "kl"], ""
        for i in range(200):
            trial = (line + " " + words[i % len(words)]).strip()
            if layout.measure(trial, 42, root) > 1800:
                break
            line = trial
        assert layout.measure(line, 42, root) > 1800 * rewrap.FLUSH, line
        return line

    def test_a_flush_line_is_split_near_the_middle(self):
        root = self._large_tree("[show_mesL]\nplaceholder[p]\n")
        line = self._flush_line(root)
        scene = root / "data" / "scenario" / "scene.ks"
        scene.write_text(f"[show_mesL]\n{line}[p]\n", encoding="utf-8")
        rewrap.apply(root, rewrap.scan(root, root, {"emb"}))
        out = scene.read_text(encoding="utf-8")
        self.assertIn("[r]", out)
        left, right = out.split("[r]", 1)
        left = left.rsplit("\n", 1)[-1]
        right = right.split("[p]", 1)[0]
        ratio = layout.measure(left, 42, root) / layout.measure(right, 42, root)
        self.assertTrue(0.6 < ratio < 1.7, f"lopsided: {left!r} | {right!r}")

    def test_the_split_never_lands_inside_a_tag(self):
        root = self._large_tree("[show_mesL]\nplaceholder[p]\n")
        line = self._flush_line(root)
        scene = root / "data" / "scenario" / "scene.ks"
        scene.write_text(f'[show_mesL]\n[elsif exp="!f.a&&!f.b"]{line}[p]\n',
                         encoding="utf-8")
        rewrap.apply(root, rewrap.scan(root, root, {"emb"}))
        out = scene.read_text(encoding="utf-8")
        self.assertIn('exp="!f.a&&!f.b"', out)
        for tag in re.findall(r"\[[^\]]*\]", out):
            self.assertNotIn("[r]", tag[1:-1])

    def test_a_comfortable_line_is_not_split(self):
        root = self._large_tree("[show_mesL]\nA short enough line.[p]\n")
        rewrap.apply(root, rewrap.scan(root, root, {"emb"}))
        self.assertNotIn(
            "[r]", (root / "data" / "scenario" / "scene.ks").read_text(encoding="utf-8"))

    def test_a_run_that_already_wraps_is_left_to_the_engine(self):
        root = self._large_tree("[show_mesL]\nplaceholder[p]\n")
        line = self._flush_line(root)
        scene = root / "data" / "scenario" / "scene.ks"
        scene.write_text(f"[show_mesL]\n{line} {line}[p]\n", encoding="utf-8")
        rewrap.apply(root, rewrap.scan(root, root, {"emb"}))
        self.assertNotIn("[r]", scene.read_text(encoding="utf-8"))

    def test_a_paragraph_break_resets_the_run(self):
        out = self._run("[show_mesS]\nOne sentence.[p]\nAnother sentence.[p]\n")
        self.assertNotIn("_ ", out)


class TestLowLine(unittest.TestCase):
    """U+FF3F, the author's trailing-off marker (see codes.convert_lowline)."""

    def test_trailing_run_becomes_an_ellipsis(self):
        self.assertEqual(
            codes.convert_lowline("You'd better rest quietly in your room＿＿＿ hm?"),
            "You'd better rest quietly in your room... hm?")

    def test_a_space_in_front_of_the_run_goes_with_it(self):
        self.assertEqual(codes.convert_lowline("drowning in pleasure ＿＿＿"),
                         "drowning in pleasure...")

    def test_the_speaker_form_becomes_a_colon(self):
        self.assertEqual(codes.convert_lowline("セレナ＿   Wait, wait..."),
                         "セレナ:   Wait, wait...")

    def test_ascii_underscores_fold_in_too(self):
        self.assertEqual(codes.convert_lowline("Huh... hm__?"), "Huh... hm...?")

    def test_a_following_comma_is_absorbed(self):
        self.assertEqual(codes.convert_lowline("making me＿＿, his voice"),
                         "making me... his voice")

    def test_a_longer_run_of_dots_is_left_alone(self):
        # only a comma is absorbed; a period is indistinguishable from one of
        # the author's own longer runs
        self.assertEqual(codes.convert_lowline("Ngh....."), "Ngh.....")
        self.assertEqual(codes.convert_lowline("Yeah.... right"), "Yeah.... right")


class TestStraySentinel(unittest.TestCase):
    """A dropped or invented bracket that the set comparison cannot see."""

    def test_well_formed_sentinels_are_clean(self):
        self.assertEqual(codes.stray_sentinel("⟦0⟧semen⟦1⟧"), "")

    def test_a_dropped_half_is_caught(self):
        self.assertTrue(codes.stray_sentinel("could I have some ⟦0⟧semen⟧?"))

    def test_an_invented_named_one_is_caught(self):
        self.assertTrue(codes.stray_sentinel("Got 5 ⟦item⟧"))

    def test_the_set_comparison_alone_would_miss_it(self):
        # both sides carry exactly ⟦0⟧, so placeholders_ok is satisfied
        self.assertTrue(codes.placeholders_ok("⟦0⟧精液", "⟦0⟧semen⟧"))
        self.assertTrue(codes.stray_sentinel("⟦0⟧semen⟧"))


class TestLineHijack(unittest.TestCase):
    """A translation must not take over the parser's line dispatch."""

    def _tree(self, line: str) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp())
        (root / "data" / "scenario").mkdir(parents=True)
        (root / "data" / "scenario" / "s.ks").write_text(line + "\n", encoding="utf-8")
        return root

    def _check(self, jp: str, en: str, line: str, start: int = 0):
        root = self._tree(line)
        store = Store(root)
        unit = Unit(id="u", kind="dialogue", src=jp, en=en, status="done",
                    sites=[Site(file="data/scenario/s.ks", line=1,
                                start=start, end=start + len(jp), form="bare",
                                raw=jp)])
        store.buckets["b"] = [unit]
        return [f for f in validate.run(store, Glossary(root / "g.json").load(), root)
                if f.severity == "hard"]

    def test_a_leading_asterisk_is_a_hard_failure(self):
        found = self._check("ボロンッ", "*fwip*", "ボロンッ[p]")
        self.assertTrue(found, "a leading * turns the line into a label")
        self.assertIn("label", found[0].message)

    def test_every_dispatch_character_is_caught(self):
        for opener in ";*@#_":
            with self.subTest(opener=opener):
                self.assertTrue(self._check("ボロンッ", opener + "x", "ボロンッ[p]"))

    def test_ordinary_text_passes(self):
        self.assertEqual(self._check("ボロンッ", "Fwip", "ボロンッ[p]"), [])

    def test_mid_line_units_are_not_flagged(self):
        # something precedes it on the line, so its first character is not the
        # line's first character
        self.assertEqual(
            self._check("ボロンッ", "*fwip*", "[se_nn1]ボロンッ[p]", start=9), [])


class TestValueSpacing(unittest.TestCase):
    """The blue "+N" on an upgrade screen has to clear the words on its left."""

    def _run(self, body: str):
        import tempfile
        root = Path(tempfile.mkdtemp())
        (root / "data" / "scenario").mkdir(parents=True)
        screen = root / "data" / "scenario" / "screen.ks"
        screen.write_text(body, encoding="utf-8")
        moved = widgets.space(root, root)
        return screen.read_text(encoding="utf-8"), moved, root

    def _value_x(self, text: str, which: int = 0) -> int:
        tags = [m.group() for m in codes.TAG_RE.finditer(text)
                if widgets.VALUE_COLOR in m.group()]
        return int(re.search(r'x="(\d+)"', tags[which]).group(1))

    def _row(self, label: str, label_x: int, value_x: int, value: str = "+5") -> str:
        return (f'[ptext layer="1" x="{label_x}" y="900" size="28" text="{label}"]\n'
                f'[ptext layer="1" x="{value_x}" y="900" size="28" text="{value}" '
                f'color="{widgets.VALUE_COLOR}"]\n')

    LONG = "A considerably longer English description"

    def test_a_value_is_pushed_clear_of_a_longer_description(self):
        text, moved, root = self._run("*bonus\n" + self._row(self.LONG, 100, 150))
        end = 100 + layout.measure(self.LONG, 28, root)
        self.assertGreaterEqual(self._value_x(text), end)
        self.assertEqual(self._value_x(text), int(end) + widgets.VALUE_GAP)
        self.assertEqual(len(moved), 1)

    def test_a_value_that_already_clears_is_left_alone(self):
        text, moved, _ = self._run("*bonus\n" + self._row("Short", 100, 1500))
        self.assertEqual(moved, [])
        self.assertEqual(self._value_x(text), 1500)

    def test_rows_are_scoped_to_their_own_screen(self):
        body = ("*one\n" + self._row(self.LONG, 100, 1500, "+1")
                + "*two\n" + self._row("Short", 100, 150, "+2"))
        text, _, root = self._run(body)
        # the long description belongs to another screen and must not push this
        # value; only "Short" is on the row that matters
        self.assertEqual(self._value_x(text, 0), 1500)
        self.assertEqual(self._value_x(text, 1),
                         int(100 + layout.measure("Short", 28, root)) + widgets.VALUE_GAP)

    def test_running_it_twice_changes_nothing(self):
        text, _, root = self._run("*bonus\n" + self._row(self.LONG, 100, 150))
        screen = root / "data" / "scenario" / "screen.ks"
        self.assertEqual(widgets.space(root, root), [])
        self.assertEqual(screen.read_text(encoding="utf-8"), text)


class TestColumns(unittest.TestCase):
    """A label that leaves gaps with values drawn into them at a fixed x."""

    SIZE = 30
    START = 100
    GAP = "　　"

    def _run(self, japanese: str, english: str):
        import tempfile
        root = Path(tempfile.mkdtemp())
        for name, body in (("jp", japanese), ("en", english)):
            (root / name / "data" / "scenario").mkdir(parents=True)
            (root / name / "data" / "scenario" / "screen.ks").write_text(
                body, encoding="utf-8")
        english_root, japanese_root = root / "en", root / "jp"
        changed = widgets.columns(english_root, english_root, japanese_root)
        screen = english_root / "data" / "scenario" / "screen.ks"
        return screen.read_text(encoding="utf-8"), changed, english_root

    def _panel(self, label: str, value_line: str) -> str:
        return ('[macro name="panel"]\n'
                f'[ptext layer="1" x="{self.START}" y="10" size="{self.SIZE}" '
                f'text="{label}"]\n' + value_line + '[endmacro]\n')

    def _value_line(self, x: int, comment: str = "") -> str:
        return (f'{comment}[ptext layer="1" x="{x}" y="10" size="{self.SIZE}" '
                f'text="&f.n"]\n')

    def _gap_x(self, first: str, root=Path(".")) -> int:
        """An x just inside the gap that follows the first column."""
        return int(self.START + layout.measure(first, self.SIZE, root)) + 2

    def _xs(self, text: str) -> list[int]:
        return [int(re.search(r'x="(\d+)"', m.group()).group(1))
                for m in codes.TAG_RE.finditer(text) if m.group(1) == "ptext"]

    def test_each_column_becomes_its_own_label_and_the_value_lands_in_the_gap(self):
        value_x = self._gap_x("あい")
        text, changed, root = self._run(
            self._panel(f"あい{self.GAP}うえ", self._value_line(value_x)),
            self._panel(f"First column{self.GAP}Second", self._value_line(value_x)))

        tags = [m.group() for m in codes.TAG_RE.finditer(text) if m.group(1) == "ptext"]
        self.assertEqual(len(tags), 3, "two columns and the value")
        self.assertIn('text="First column"', text)
        self.assertIn('text="Second"', text)

        first_end = self.START + layout.measure("First column", self.SIZE, root)
        second = int(re.search(r'x="(\d+)"', tags[1]).group(1))
        moved_value = int(re.search(r'x="(\d+)"', tags[2]).group(1))
        self.assertEqual(second,
                         int(first_end + layout.measure(self.GAP, self.SIZE, root)))
        self.assertGreaterEqual(moved_value, int(first_end))
        self.assertLess(moved_value, second)
        self.assertTrue(changed)

    def test_a_gap_with_nothing_drawn_into_it_is_left_alone(self):
        body = self._panel(f"あい{self.GAP}うえ", "")
        english = self._panel(f"First column{self.GAP}Second", "")
        text, changed, _ = self._run(body, english)
        self.assertEqual(changed, [])
        self.assertEqual(text, english)

    def test_a_commented_value_does_not_make_a_column(self):
        value_x = self._gap_x("あい")
        english = self._panel(f"First column{self.GAP}Second",
                              self._value_line(value_x, comment=";"))
        text, changed, _ = self._run(
            self._panel(f"あい{self.GAP}うえ", self._value_line(value_x, comment=";")),
            english)
        self.assertEqual(changed, [])
        self.assertEqual(text, english)

    def test_running_it_twice_changes_nothing(self):
        value_x = self._gap_x("あい")
        japanese = self._panel(f"あい{self.GAP}うえ", self._value_line(value_x))
        text, _, root = self._run(
            japanese, self._panel(f"First column{self.GAP}Second", self._value_line(value_x)))
        japanese_root = root.parent / "jp"
        self.assertEqual(widgets.columns(root, root, japanese_root), [])
        self.assertEqual(
            (root / "data" / "scenario" / "screen.ks").read_text(encoding="utf-8"), text)

class TestRebreak(unittest.TestCase):
    """Hard <br> breaks placed for Japanese, re-placed for English."""

    SIZE = 28

    def _run(self, japanese: str, english: str):
        import tempfile
        root = Path(tempfile.mkdtemp())
        for name, body in (("jp", japanese), ("en", english)):
            (root / name / "data" / "scenario").mkdir(parents=True)
            (root / name / "data" / "scenario" / "screen.ks").write_text(
                body, encoding="utf-8")
        english_root = root / "en"
        checked = widgets.rebreak(english_root, english_root, root / "jp")
        screen = english_root / "data" / "scenario" / "screen.ks"
        return screen.read_text(encoding="utf-8"), checked, english_root

    def _label(self, text: str) -> str:
        return (f'[ptext layer="1" x="50" y="770" size="{self.SIZE}" '
                f'text="{text}"]\n')

    def _lines(self, text: str) -> list[str]:
        raw = widgets._attr(
            next(m.group() for m in codes.TAG_RE.finditer(text)), "text")
        return [codes.unprotect_spaces(part) for part in widgets.BREAK.split(raw)]

    JAPANESE = "ああああああああ<br>いいいいいい"
    LONG = ("You can hand over an item you have and have her go <br>"
            "gather supplies")

    def test_a_label_that_outgrew_its_box_is_re_broken(self):
        text, checked, root = self._run(self._label(self.JAPANESE),
                                        self._label(self.LONG))
        lines = self._lines(text)
        self.assertEqual(len(lines), 2, "the block must not grow downward")

        # the promise is the narrowest box that still holds the line count, not
        # that English ever reaches the width Japanese managed
        before = max(layout.measure(part, self.SIZE, root)
                     for part in self.LONG.split("<br>"))
        widest = max(layout.measure(line, self.SIZE, root) for line in lines)
        self.assertLess(widest, before)
        self.assertEqual(checked[0][5], int(widest))

    def test_no_word_is_lost_or_gained(self):
        text, _, _ = self._run(self._label(self.JAPANESE), self._label(self.LONG))
        before = codes.unprotect_spaces(self.LONG.replace("<br>", " ")).split()
        self.assertEqual(" ".join(self._lines(text)).split(), before)

    def test_a_label_inside_its_box_is_left_alone(self):
        english = self._label("Tiny<br>bit")
        text, checked, _ = self._run(self._label(self.JAPANESE), english)
        self.assertEqual(text, english)
        self.assertEqual(checked, [])

    def test_a_trailing_break_is_not_a_second_line(self):
        # the Japanese ends with <br> and nothing after it, so it is one line
        # and the English must not be split in two
        english = self._label("A single English line that is wider than the source")
        text, checked, _ = self._run(self._label("ああああ<br>"), english)
        self.assertEqual(text, english)
        self.assertTrue(all(row[5] is None for row in checked))

    def test_running_it_twice_changes_nothing(self):
        text, _, root = self._run(self._label(self.JAPANESE), self._label(self.LONG))
        again = widgets.rebreak(root, root, root.parent / "jp")
        self.assertTrue(all(row[5] is None for row in again))
        self.assertEqual(
            (root / "data" / "scenario" / "screen.ks").read_text(encoding="utf-8"), text)

class TestSaveText(unittest.TestCase):
    """The build's copy of text that a save keeps its own version of."""

    TABLE = (
        "[iscript]\n"
        "f.task=[\n"
        '["Parts Shortage","Completed",0,"Task Item 0",0,"2",0,"Brief, with a , in it",0,0,0.1,"task0"],//0\n'
        '["Delivery","Completed",0,"Task Item 1",0,"15",0,"Second brief",0,0,1,"task1"],//1\n'
        "]\n"
        "[endscript]\n"
    )

    def _written(self, body: str) -> Path:
        import tempfile
        root = Path(tempfile.mkdtemp())
        (root / "system").mkdir(parents=True)
        (root / "system" / "exp.ks").write_text(body, encoding="utf-8")
        return root

    def _collect(self, body: str):
        return savetext.collect(self._written(body))

    def test_the_owned_fields_are_read_in_order(self):
        found = self._collect(self.TABLE)["task"]
        self.assertEqual(found["0"], ["Parts Shortage", "Delivery"])
        self.assertEqual(found["1"], ["Completed", "Completed"])
        self.assertEqual(found["7"], ["Brief, with a , in it", "Second brief"])

    def test_a_row_comment_does_not_leak_into_the_next_row(self):
        # //0 sits between the rows; swept into the next one it would leave that
        # row without its own bracket and every field after it misread
        found = self._collect(self.TABLE)["task"]
        self.assertEqual(found["0"][1], "Delivery")

    def test_a_number_is_not_mistaken_for_text(self):
        found = self._collect(self.TABLE)["task"]
        self.assertNotIn("2", found)          # f.task[2] is a count, not a caption

    def test_the_jump_target_field_is_never_shipped(self):
        # a Nemo task's name is also the label it jumps to, so replacing it
        # would send an older save to a label its own build never had
        self.assertNotIn(11, savetext.OWNED["task"])
        self.assertNotIn(0, savetext.OWNED["nemo_task"])

    def test_a_table_that_is_not_owned_is_skipped(self):
        body = self.TABLE.replace("f.task=[", "f.something_else=[")
        self.assertEqual(self._collect(body), {})

    def test_the_generated_file_is_an_assignment_of_valid_json(self):
        import json
        text = savetext.build(self._written(self.TABLE))
        self.assertTrue(text.rstrip().endswith(";"))
        body = text[text.index("=") + 1:].rstrip().rstrip(";")
        self.assertEqual(json.loads(body)["task"]["1"], ["Completed", "Completed"])

class TestUnglue(unittest.TestCase):
    """A value dropped into a sentence needs a space in front of it in English."""

    def _run(self, body: str):
        import tempfile
        root = Path(tempfile.mkdtemp())
        (root / "data" / "scenario").mkdir(parents=True)
        screen = root / "data" / "scenario" / "screen.ks"
        screen.write_text(body, encoding="utf-8")
        touched = widgets.unglue(root)
        return screen.read_text(encoding="utf-8"), touched

    def test_a_word_gets_a_space_before_the_value(self):
        text, touched = self._run(
            """[glink text="&'Add a fair amount' + f.n + ' used'"]\n""")
        self.assertIn("'Add a fair amount" + NBSP + "'", text)
        self.assertEqual(len(touched), 1)

    def test_the_space_survives_the_tag_parser(self):
        # a literal space inside a quoted attribute value is deleted by
        # makeTag, so the one inserted has to be U+00A0
        text, _ = self._run("""[glink text="&'Affection' + f.n + '+'"]\n""")
        self.assertNotIn("'Affection '", text)
        self.assertIn("'Affection" + NBSP + "'", text)

    def test_punctuation_before_a_value_is_left_alone(self):
        for label in ("'Trust:'", "'+'", "'LV.'"):
            body = f"""[ptext text="&{label} + f.n"]\n"""
            text, touched = self._run(body)
            self.assertEqual(touched, [], label)
            self.assertEqual(text, body)

    def test_a_value_before_a_word_is_left_alone(self):
        # tf.tag is a lock marker printed in front of the label, not a number
        body = """[glink text="&tf.tag + 'Deepthroat'"]\n"""
        text, touched = self._run(body)
        self.assertEqual(touched, [])
        self.assertEqual(text, body)

    def test_an_unterminated_entity_is_not_a_word(self):
        body = """[ptext text="&'a&nbsp' + f.n"]\n"""
        text, touched = self._run(body)
        self.assertEqual(touched, [])
        self.assertEqual(text, body)

    def test_running_it_twice_changes_nothing(self):
        body = """[glink text="&'Add a lot' + f.n + ' used'"]\n"""
        text, _ = self._run(body)
        import tempfile
        root = Path(tempfile.mkdtemp())
        (root / "data" / "scenario").mkdir(parents=True)
        (root / "data" / "scenario" / "screen.ks").write_text(text, encoding="utf-8")
        self.assertEqual(widgets.unglue(root), [])

if __name__ == "__main__":
    unittest.main(verbosity=2)
