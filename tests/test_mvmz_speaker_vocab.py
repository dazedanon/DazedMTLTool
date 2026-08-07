#!/usr/bin/env python3
"""Regression tests for deterministic RPG Maker speaker glossary handling."""

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import modules.rpgmakermvmz as mvmz
from util.translation import buildMatchedVocabText, parseVocabWithCategories


VOCAB = (
    "# Game Characters\n"
    "ユウ (Yuu) - Male protagonist.\n"
    "ハルカ (Haruka) - Female heroine.\n\n"
    "# Terms\n"
    "教室 (Classroom)\n"
)


class MVMZSpeakerVocabTests(unittest.TestCase):
    def setUp(self):
        self.original_vocab = mvmz.VOCAB
        self.original_config_vocab = mvmz.TRANSLATION_CONFIG.vocab
        self.original_names = mvmz.NAMESLIST
        self.original_collected = mvmz.SPEAKER_COLLECTED
        self.original_parse_mode = mvmz.SPEAKER_PARSE_MODE
        self.original_preflight = mvmz.PREFLIGHT_COUNT_MODE
        self.original_tokens = list(mvmz.TOKENS)
        mvmz.VOCAB = VOCAB
        mvmz.NAMESLIST = []
        mvmz.SPEAKER_COLLECTED = []
        mvmz.SPEAKER_PARSE_MODE = False
        mvmz.PREFLIGHT_COUNT_MODE = False
        with mvmz._speakerCacheLock:
            mvmz._speakerCache.clear()

    def tearDown(self):
        mvmz.VOCAB = self.original_vocab
        mvmz.TRANSLATION_CONFIG.vocab = self.original_config_vocab
        mvmz.NAMESLIST = self.original_names
        mvmz.SPEAKER_COLLECTED = self.original_collected
        mvmz.SPEAKER_PARSE_MODE = self.original_parse_mode
        mvmz.PREFLIGHT_COUNT_MODE = self.original_preflight
        mvmz.TOKENS[:] = self.original_tokens
        mvmz.THREAD_CTX.last_translation_had_mismatch = False
        with mvmz._speakerCacheLock:
            mvmz._speakerCache.clear()

    def test_exact_vocab_name_bypasses_model_and_stale_cache(self):
        with mvmz._speakerCacheLock:
            mvmz._speakerCache["ユウ"] = "Yu"

        with patch.object(mvmz, "translateAI") as translate:
            result = mvmz.getSpeaker("ユウ")

        self.assertEqual(result, ["Yuu", [0, 0]])
        translate.assert_not_called()

    def test_character_name_is_substituted_inside_compound_label(self):
        def translate(text, _context, _batch=False):
            self.assertEqual(text, "Yuuイベント5")
            return ["Yuu Event 5", [3, 2]]

        with patch.object(mvmz, "translateAI", side_effect=translate):
            result = mvmz.getSpeaker("ユウイベント5")

        self.assertEqual(result, ["Yuu Event 5", [3, 2]])

    def test_slash_alias_glossary_covers_short_speaker_names(self):
        """Curated ``JP1 / JP2 (EN)`` rows must resolve each alias without duplicates."""
        vocab = (
            "# Game Characters\n"
            "ニーナ / ネーナ・エヴァンス (Nena Evans) - Female protagonist.\n"
            "クイーン / クィーン (Queen) - Female slime queen.\n"
            "コア1A (Core 1A)\n"
            "ニーナ (Nena)\n"
        )
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(vocab, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
            ):
                mvmz._reload_vocab()
                with mvmz._speakerCacheLock:
                    mvmz._speakerCache.clear()

                self.assertEqual(mvmz._vocab_speaker_lookup("ニーナ"), "Nena")
                self.assertEqual(
                    mvmz._vocab_speaker_lookup("ネーナ・エヴァンス"), "Nena Evans"
                )
                self.assertEqual(mvmz._vocab_speaker_lookup("ニーナ様"), "Nena")
                self.assertEqual(mvmz._vocab_speaker_lookup("クイーン"), "Queen")
                self.assertEqual(mvmz._vocab_speaker_lookup("クィーン"), "Queen")
                self.assertEqual(mvmz._vocab_speaker_lookup("コア1Ａ"), "Core 1A")
                self.assertEqual(mvmz._vocab_speaker_lookup("二ーナ"), "Nena")

                mvmz.SPEAKER_PARSE_MODE = True
                mvmz.SPEAKER_COLLECTED = [
                    "ニーナ",
                    "ニーナ様",
                    "クィーン",
                    "コア1Ａ",
                    "二ーナ",
                    "村人",
                ]
                self.assertEqual(mvmz.pendingSpeakerNames(), ["村人"])

                with patch.object(
                    mvmz,
                    "translateAI",
                    return_value=[["Villager"], [3, 1]],
                ) as translate:
                    self.assertTrue(mvmz.finalizeSpeakerParse())
                translate.assert_called_once()
                written = glossary_path.read_text(encoding="utf-8")

        self.assertIn("ニーナ / ネーナ・エヴァンス (Nena Evans)", written)
        self.assertIn("村人 (Villager)", written)
        self.assertNotRegex(written, r"(?m)^ニーナ \(")
        self.assertNotRegex(written, r"(?m)^ニーナ様 \(")
        self.assertNotRegex(written, r"(?m)^クィーン \(")
        self.assertNotRegex(written, r"(?m)^二ーナ \(")
        self.assertNotRegex(written, r"(?m)^コア1Ａ \(")

    def test_clause_fragments_are_not_collected_as_speakers(self):
        self.assertFalse(mvmz._is_plausible_speaker("体の芯を縦断しながら"))
        self.assertFalse(mvmz._is_plausible_speaker("オンにすると完全に石化になった時"))
        self.assertFalse(mvmz._is_plausible_speaker("{{ニーナ"))
        self.assertFalse(mvmz._is_plausible_speaker("ウチの倉庫♥"))
        self.assertTrue(mvmz._is_plausible_speaker("村長の妻"))
        self.assertTrue(mvmz._is_plausible_speaker("ニーナ"))
        self.assertTrue(mvmz._is_plausible_speaker("はるか"))
        self.assertTrue(mvmz._is_plausible_speaker("かがやき"))
        # Trailing plugin face/font codes must not disqualify a real nameplate.
        self.assertTrue(mvmz._is_plausible_speaker(r"ニーナ\F[tt07]"))
        self.assertFalse(mvmz._is_plausible_speaker(r"\n[1]"))

    def test_speaker_display_name_strips_plugin_codes(self):
        """Visible nameplate text must drop trailing/leading \\F / \\C codes."""
        cases = (
            (r"Tsubaki\F[tt07]", "Tsubaki"),
            (r"ニーナ\F[tt07]", "ニーナ"),
            (r"\F[tt07]Tsubaki", "Tsubaki"),
            (r"\C[2]アリス\C[0]", "アリス"),
            (r"\C[2]アリス\C[0]\F[tt07]", "アリス"),
            # Ristaria Map008 shapes
            (r"メア\F[tme01]\FF[tl05]\AA[F]\FH[ON]", "メア"),
            (r"リア\FF[tl05]\F[tme02]\AA[FF]", "リア"),
            (r"ミカ\FH[ON]\F[tmi02]", "ミカ"),
            (r"見知らぬ男\AA[N]", "見知らぬ男"),
            (r"\v[007]\AA[N]", r"\v[007]"),
            (r"\v[007]\AA[N]\FH[OFF]", r"\v[007]"),
            (r"\v[007]\AA[N]\F[tmi11]\FH[ON]", r"\v[007]"),
            (r"\n[1]", r"\n[1]"),
            ("ニーナ", "ニーナ"),
        )
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(mvmz._speaker_display_name(raw), expected)

    def test_replace_speaker_keeps_trailing_f_tag(self):
        """Rewriting a nameplate must preserve trailing plugin codes on the 401 line."""
        self.assertEqual(
            mvmz._replace_speaker_in_param(r"Tsubaki\F[tt07]", r"Tsubaki\F[tt07]", "Tsubaki"),
            r"Tsubaki\F[tt07]",
        )
        self.assertEqual(
            mvmz._replace_speaker_in_param(r"椿\F[tt07]", "椿", "Tsubaki"),
            r"Tsubaki\F[tt07]",
        )
        self.assertEqual(
            mvmz._replace_speaker_in_param(
                r"メア\F[tme01]\FF[tl05]\AA[F]\FH[ON]", "メア", "Mea"
            ),
            r"Mea\F[tme01]\FF[tl05]\AA[F]\FH[ON]",
        )
        self.assertEqual(
            mvmz._replace_speaker_in_param(r"\v[007]\AA[N]", r"\v[007]", r"\v[007]"),
            r"\v[007]\AA[N]",
        )

    def test_var_speaker_resolves_from_actor_name_script(self):
        """\\v[N] mirrors Actors.json when code 122 assigns actor(N).name()."""
        seed_map = {
            "events": [
                None,
                {
                    "id": 1,
                    "pages": [
                        {
                            "list": [
                                {
                                    "code": 122,
                                    "indent": 0,
                                    "parameters": [
                                        7,
                                        7,
                                        0,
                                        4,
                                        "$gameActors.actor(1).name()",
                                    ],
                                },
                                {"code": 0, "indent": 0, "parameters": []},
                            ]
                        }
                    ],
                },
            ]
        }
        actors = [None, {"id": 1, "name": "主人公"}]
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            files_dir = tmp_path / "files"
            files_dir.mkdir()
            (files_dir / "Map019.json").write_text(
                json.dumps(seed_map, ensure_ascii=False), encoding="utf-8"
            )
            (files_dir / "Actors.json").write_text(
                json.dumps(actors, ensure_ascii=False), encoding="utf-8"
            )
            orig_cwd = Path.cwd()
            mvmz.resetActorMapCache()
            try:
                os.chdir(tmp_path)
                self.assertEqual(mvmz._get_var_actor_map(), {7: 1})
                self.assertEqual(mvmz._resolve_code_speaker_name(r"\v[007]"), "主人公")
                self.assertEqual(mvmz._resolve_code_speaker_name(r"\n[1]"), "主人公")
                self.assertIsNone(mvmz._resolve_code_speaker_name(r"\v[999]"))
                self.assertIsNone(mvmz._resolve_code_speaker_name("メア"))
            finally:
                os.chdir(orig_cwd)
                mvmz.resetActorMapCache()

    def test_blank_actor_slot_uses_real_name_fallback(self):
        """Empty Actors.json names substitute a real given name, then restore \\n[ID]."""
        mvmz.resetActorMapCache()
        mvmz._ACTOR_MAP_CACHE = {3: "Player"}
        mvmz._EMPTY_ACTOR_IDS_CACHE = {4}
        mvmz._EMPTY_ACTOR_NAME_CACHE = {}
        try:
            subbed, reverse = mvmz._substitute_actor_names(
                r'なんでPlayer\N[4] より先に',
                {3: "Player"},
            )
            # Leading space prevents PlayerAlex fusion so restore can match.
            self.assertEqual(subbed, "なんでPlayer Alex より先に")
            self.assertEqual(reverse, {"Alex": r"\N[4]"})
            self.assertEqual(
                mvmz._restore_actor_names(
                    "Why did Alex fall asleep before Player Alex?",
                    reverse,
                ),
                r"Why did \N[4] fall asleep before Player \N[4]?",
            )
            # Model often glues the spaced form back together.
            self.assertEqual(
                mvmz._restore_actor_names("before PlayerAlex...?", reverse),
                r"before Player\N[4]...?",
            )
        finally:
            mvmz.resetActorMapCache()

    def test_adjacent_actor_codes_do_not_fuse_into_playeralex(self):
        """\\n[3]\\n[4] with actor3=Player and blank 4 must not become PlayerAlex."""
        mvmz.resetActorMapCache()
        mvmz._ACTOR_MAP_CACHE = {3: "Player"}
        mvmz._EMPTY_ACTOR_IDS_CACHE = {4}
        mvmz._EMPTY_ACTOR_NAME_CACHE = {}
        try:
            subbed, reverse = mvmz._substitute_actor_names(
                r"（もし、\N[3]\N[4]が私の想いによって",
                {3: "Player"},
            )
            self.assertEqual(subbed, "（もし、Player Alexが私の想いによって")
            self.assertEqual(reverse.get("Player"), r"\N[3]")
            self.assertEqual(reverse.get("Alex"), r"\N[4]")
            self.assertEqual(
                mvmz._restore_actor_names(
                    "If PlayerAlex was summoned here by my feelings...",
                    reverse,
                ),
                r"If \N[3]\N[4] was summoned here by my feelings...",
            )
        finally:
            mvmz.resetActorMapCache()

    def test_blank_actor_fallbacks_are_distinct_per_id(self):
        """Multiple blank actor slots must not share one restore name."""
        mvmz.resetActorMapCache()
        mvmz._ACTOR_MAP_CACHE = {}
        mvmz._EMPTY_ACTOR_IDS_CACHE = {4, 5}
        mvmz._EMPTY_ACTOR_NAME_CACHE = {}
        try:
            first, rev1 = mvmz._substitute_actor_names(r"Hello \N[4]", {})
            second, rev2 = mvmz._substitute_actor_names(r"Hello \N[5]", {})
            self.assertEqual(first, "Hello Alex")
            self.assertEqual(second, "Hello Blake")
            self.assertEqual(rev1, {"Alex": r"\N[4]"})
            self.assertEqual(rev2, {"Blake": r"\N[5]"})
        finally:
            mvmz.resetActorMapCache()

    def test_unknown_actor_code_is_not_given_fallback(self):
        """Codes for IDs that are not blank Actors.json slots stay untouched."""
        mvmz.resetActorMapCache()
        mvmz._ACTOR_MAP_CACHE = {1: "Hero"}
        mvmz._EMPTY_ACTOR_IDS_CACHE = set()
        mvmz._EMPTY_ACTOR_NAME_CACHE = {}
        try:
            subbed, reverse = mvmz._substitute_actor_names(r"Meet \N[99]", {1: "Hero"})
            self.assertEqual(subbed, r"Meet \N[99]")
            self.assertEqual(reverse, {})
        finally:
            mvmz.resetActorMapCache()

    def test_actors_json_records_blank_custom_name_slots(self):
        """Actors.json blank names are tracked even when other actors are named."""
        actors = [
            None,
            {"id": 3, "name": "Player"},
            {"id": 4, "name": ""},
        ]
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            files_dir = tmp_path / "files"
            files_dir.mkdir()
            (files_dir / "Actors.json").write_text(
                json.dumps(actors, ensure_ascii=False), encoding="utf-8"
            )
            orig_cwd = Path.cwd()
            mvmz.resetActorMapCache()
            try:
                os.chdir(tmp_path)
                self.assertEqual(mvmz._get_actor_map(), {3: "Player"})
                self.assertEqual(mvmz._get_empty_actor_ids(), {4})
                self.assertEqual(
                    mvmz._actor_name_for_translation(4, {3: "Player"}),
                    "Alex",
                )
            finally:
                os.chdir(orig_cwd)
                mvmz.resetActorMapCache()

    def test_covered_nameplate_variants_are_not_persisted(self):
        """Finalize must not write NFKC/lookalike variants of curated names."""
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["コア1Ａ", "二ーナ", "クィーン"]
        vocab = (
            "# Game Characters\n"
            "ニーナ / ネーナ・エヴァンス (Nena Evans)\n"
            "クイーン / クィーン (Queen)\n"
            "コア1A (Core 1A)\n"
        )
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(vocab, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
                patch.object(mvmz, "translateAI") as translate,
            ):
                self.assertEqual(mvmz.pendingSpeakerNames(), [])
                self.assertTrue(mvmz.finalizeSpeakerParse())
            written = glossary_path.read_text(encoding="utf-8")

        translate.assert_not_called()
        self.assertEqual(written, vocab)
        self.assertNotIn("# Speakers", written)

    def test_speaker_parse_uses_original_when_live_text_is_english(self):
        """Preflight must still collect nameplates from _original on translated rows."""
        page = {
            "list": [
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": ["Nina"],
                    "_original": "ニーナ",
                },
                {
                    "code": 401,
                    "indent": 0,
                    "parameters": ['"Hello."'],
                    "_original": "「こんにちは」",
                },
                {"code": 0, "indent": 0, "parameters": []},
            ]
        }
        orig_first = mvmz.FIRSTLINESPEAKERS
        orig_401 = mvmz.CODE401
        orig_ignore = mvmz.IGNORETLTEXT
        orig_parse = mvmz.SPEAKER_PARSE_MODE
        orig_t = mvmz.translateAI
        mvmz.FIRSTLINESPEAKERS = True
        mvmz.CODE401 = True
        mvmz.IGNORETLTEXT = True
        mvmz.resetSpeakerState()
        mvmz.setSpeakerParseMode(True)
        mvmz.translateAI = lambda text, history, batch=False: [text, [0, 0]]
        try:
            mvmz.searchCodes(page, None, [], "Map001.json")
            self.assertEqual(mvmz.SPEAKER_COLLECTED, ["ニーナ"])
        finally:
            mvmz.translateAI = orig_t
            mvmz.FIRSTLINESPEAKERS = orig_first
            mvmz.CODE401 = orig_401
            mvmz.IGNORETLTEXT = orig_ignore
            mvmz.setSpeakerParseMode(orig_parse)
            mvmz.resetSpeakerState()

    def test_batch_collect_defers_unexpected_speaker_without_live_call(self):
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "collect"}),
            patch.object(mvmz, "translateAI") as translate,
        ):
            result = mvmz.getSpeaker("騎士")

        self.assertEqual(result, ["騎士", [0, 0]])
        translate.assert_not_called()

    def test_batch_collect_reuses_glossary_for_firstline_speaker(self):
        """FIRSTLINESPEAKERS nameplates must resolve from glossary during batch."""
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "collect"}),
            patch.object(mvmz, "translateAI") as translate,
        ):
            result = mvmz.getSpeaker("ニーナ")

        # Empty vocab in setUp - unresolved names stay source during batch.
        self.assertEqual(result, ["ニーナ", [0, 0]])
        translate.assert_not_called()

        mvmz.VOCAB = "# Game Characters\nニーナ (Nina)\n"
        mvmz._speakerVocabSource = None
        with mvmz._speakerCacheLock:
            mvmz._speakerCache.clear()
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "collect"}),
            patch.object(mvmz, "translateAI") as translate,
        ):
            result = mvmz.getSpeaker("ニーナ")

        self.assertEqual(result, ["Nina", [0, 0]])
        translate.assert_not_called()

    def test_invalid_live_speaker_translation_is_not_cached(self):
        def echo_japanese(text, _context, _batch=False):
            return [text if isinstance(text, str) else text[0], [2, 1]]

        with patch.object(mvmz, "translateAI", side_effect=echo_japanese) as translate:
            first = mvmz.getSpeaker("ニーナ")
            second = mvmz.getSpeaker("ニーナ")

        self.assertEqual(first, ["ニーナ", [2, 1]])
        self.assertEqual(second, ["ニーナ", [2, 1]])
        self.assertEqual(translate.call_count, 4)  # two attempts per call, no cache
        with mvmz._speakerCacheLock:
            self.assertNotIn("ニーナ", mvmz._speakerCache)

    def test_batch_consume_defers_unresolved_legacy_speaker(self):
        with (
            patch.dict(os.environ, {"BATCH_PHASE": "consume"}),
            patch.object(mvmz, "translateAI") as translate,
        ):
            result = mvmz.getSpeaker("騎士")

        self.assertEqual(result, ["騎士", [0, 0]])
        translate.assert_not_called()

    def test_game_characters_override_generated_speaker_spelling(self):
        mvmz.VOCAB = (
            "# Game Characters\nユウ (Yuu) - Male protagonist.\n\n"
            "# Speakers\nユウ (Yu)\n"
        )

        with patch.object(mvmz, "translateAI") as translate:
            result = mvmz.getSpeaker("ユウ")

        self.assertEqual(result, ["Yuu", [0, 0]])
        translate.assert_not_called()

    def test_reload_vocab_updates_translation_config(self):
        with TemporaryDirectory() as tmp:
            vocab_path = Path(tmp) / "glossary.txt"
            vocab_path.write_text("# Game Characters\nユウ (You)\n", encoding="utf-8")
            with patch.object(mvmz, "VOCAB_PATH", vocab_path):
                mvmz._reload_vocab()

        self.assertIn("ユウ (You)", mvmz.VOCAB)
        self.assertEqual(mvmz.TRANSLATION_CONFIG.vocab, mvmz.VOCAB)

    def test_parse_speakers_reuses_curated_name(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["ユウ"]
        with TemporaryDirectory() as tmp:
            vocab_path = Path(tmp) / "glossary.txt"
            vocab_path.write_text(VOCAB, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", vocab_path),
                patch.object(mvmz, "translateAI") as translate,
            ):
                self.assertTrue(mvmz.finalizeSpeakerParse())
            written = vocab_path.read_text(encoding="utf-8")

        translate.assert_not_called()
        self.assertIn("# Game Characters\nユウ (Yuu)", written)
        self.assertNotIn("# Speakers", written)

    def test_parse_speakers_translates_unresolved_names_in_one_list_call(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["騎士", "秘書官", "ユウ"]
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(VOCAB, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(
                    mvmz,
                    "translateAI",
                    return_value=[["Knight", "Secretary"], [12, 3]],
                ) as translate,
            ):
                self.assertEqual(mvmz.pendingSpeakerNames(), ["騎士", "秘書官"])
                self.assertTrue(mvmz.finalizeSpeakerParse())
            written = glossary_path.read_text(encoding="utf-8")

        translate.assert_called_once_with(
            ["騎士", "秘書官"],
            mvmz.ctx("names.speaker"),
            True,
        )
        self.assertIn("騎士 (Knight)", written)
        self.assertIn("秘書官 (Secretary)", written)
        self.assertIn("# Game Characters", written)
        self.assertNotIn("# Speakers", written)

    def test_parse_speakers_preserves_entries_from_unselected_files(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["騎士"]
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(
                "# Speakers\n騎士 (Knight)\n司祭 (Priest)\n\n# Terms\n剣 (Sword)\n",
                encoding="utf-8",
            )
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
                patch.object(mvmz, "translateAI") as translate,
            ):
                self.assertTrue(mvmz.finalizeSpeakerParse())
            written = glossary_path.read_text(encoding="utf-8")

        translate.assert_not_called()
        self.assertIn("騎士 (Knight)", written)
        self.assertIn("司祭 (Priest)", written)
        self.assertIn("# Game Characters", written)
        self.assertNotIn("# Speakers", written)

    def test_legacy_short_speaker_migrates_without_competing_in_prompt(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["果歩"]
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(
                "# Game Characters\n天草 果歩 (Kaho Amakusa)\n\n"
                "# Speakers\n果歩 (Kaho)\n",
                encoding="utf-8",
            )
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
                patch.object(mvmz, "translateAI") as translate,
            ):
                self.assertTrue(mvmz.finalizeSpeakerParse())
            written = glossary_path.read_text(encoding="utf-8")

        translate.assert_not_called()
        self.assertNotIn("# Speakers", written)
        self.assertIn("# Game Characters", written)
        self.assertIn("果歩 (Kaho)", written)
        matched = buildMatchedVocabText(
            parseVocabWithCategories(written), '果歩 "どうしたの？"'
        )
        self.assertIn("天草 果歩 (Kaho Amakusa)", matched)
        self.assertNotIn("\n果歩 (Kaho)\n", matched)

    def test_parse_speakers_rejects_source_fallback_without_touching_glossary(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["騎士"]
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            original = "# Speakers\n司祭 (Priest)\n\n# Terms\n剣 (Sword)\n"
            glossary_path.write_text(original, encoding="utf-8")

            def failed_translation(*_args, **_kwargs):
                mvmz.THREAD_CTX.last_translation_had_mismatch = True
                return [["騎士"], [3, 1]]

            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
                patch.object(mvmz, "translateAI", side_effect=failed_translation),
            ):
                self.assertFalse(mvmz.finalizeSpeakerParse())
            written = glossary_path.read_text(encoding="utf-8")

        self.assertEqual(written, original)
        self.assertNotIn("騎士 (騎士)", written)

    def test_parse_speakers_accepts_non_latin_target_name(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["騎士"]
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text("# Speakers\n", encoding="utf-8")
            with (
                patch.object(mvmz, "LANGUAGE", "Russian"),
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
                patch.object(
                    mvmz,
                    "translateAI",
                    return_value=[["Рыцарь"], [3, 1]],
                ),
            ):
                self.assertTrue(mvmz.finalizeSpeakerParse())
            written = glossary_path.read_text(encoding="utf-8")

        self.assertIn("騎士 (Рыцарь)", written)
        self.assertIn("# Game Characters", written)
        self.assertNotIn("# Speakers", written)

    def test_parse_speakers_persists_and_resolves_chinese_target_name(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["騎士"]
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text("# Speakers\n", encoding="utf-8")
            with (
                patch.object(mvmz, "LANGUAGE", "Chinese"),
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
                patch.object(
                    mvmz,
                    "translateAI",
                    return_value=[["骑士"], [3, 1]],
                ),
            ):
                self.assertTrue(mvmz.finalizeSpeakerParse())
                written = glossary_path.read_text(encoding="utf-8")
                mvmz.VOCAB = written
                mvmz._speakerVocabSource = None
                self.assertEqual(mvmz._vocab_speaker_lookup("騎士"), "骑士")

        self.assertIn("騎士 (骑士)", written)
        self.assertIn("# Game Characters", written)
        self.assertNotIn("# Speakers", written)

    def test_chinese_speaker_rejects_unchanged_japanese_kana(self):
        with patch.object(mvmz, "LANGUAGE", "Chinese"):
            self.assertFalse(
                mvmz._speaker_translation_valid("セルリア", "セルリア")
            )
            self.assertTrue(mvmz._speaker_translation_valid("騎士", "骑士"))

    def test_finalize_without_glossary_does_not_spend_on_speakers(self):
        mvmz.SPEAKER_PARSE_MODE = True
        mvmz.SPEAKER_COLLECTED = ["騎士"]
        with (
            patch.object(mvmz, "VOCAB_PATH", None),
            patch.object(mvmz, "active_glossary_path", return_value=None),
            patch.object(mvmz, "translateAI") as translate,
        ):
            self.assertFalse(mvmz.finalizeSpeakerParse())

        translate.assert_not_called()


class CharacterCompoundMatchingTests(unittest.TestCase):
    def test_slash_alias_row_matches_dialogue_and_suppresses_short_duplicate(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\n"
            "ニーナ / ネーナ・エヴァンス (Nena Evans) - Female protagonist.\n"
            "ニーナ (Nena)\n"
        )

        matched = buildMatchedVocabText(pairs, 'ニーナ "どうしたの？"')

        self.assertIn("ニーナ / ネーナ・エヴァンス (Nena Evans)", matched)
        self.assertNotIn("\nニーナ (Nena)\n", matched)

    def test_short_slash_alias_uses_short_nameplate_gloss(self):
        from util.translation import nameplate_gloss_for_alias

        aliases = ["ニーナ", "ネーナ・エヴァンス"]
        self.assertEqual(
            nameplate_gloss_for_alias("ニーナ", aliases, "Nena Evans"),
            "Nena",
        )
        self.assertEqual(
            nameplate_gloss_for_alias("ネーナ・エヴァンス", aliases, "Nena Evans"),
            "Nena Evans",
        )
        self.assertEqual(
            nameplate_gloss_for_alias("クイーン", ["クイーン", "クィーン"], "Queen"),
            "Queen",
        )
        self.assertEqual(
            nameplate_gloss_for_alias("ニーナ", aliases, "Lady Nena"),
            "Nena",
        )
        self.assertEqual(
            nameplate_gloss_for_alias("ニーナ", aliases, "Dr. Evans"),
            "Evans",
        )
        self.assertEqual(
            nameplate_gloss_for_alias("ニーナ", aliases, "Lady Nena Evans"),
            "Nena",
        )
        self.assertEqual(
            nameplate_gloss_for_alias(
                "レディ・ニーナ", ["レディ・ニーナ", "ネーナ・エヴァンス"], "Lady Nena Evans"
            ),
            "Lady Nena",
        )
        self.assertEqual(
            nameplate_gloss_for_alias(
                "ニーナ様", ["ニーナ", "ネーナ・エヴァンス"], "Lady Nena Evans"
            ),
            "Lady Nena",
        )
        self.assertEqual(
            nameplate_gloss_for_alias(
                "ニーナ様", ["ニーナ様", "ネーナ・エヴァンス"], "Lady Nena Evans"
            ),
            "Lady Nena",
        )
        self.assertEqual(
            nameplate_gloss_for_alias(
                "ヴァン", ["ヴァン", "ヴァン・ヘルシング"], "van Helsing"
            ),
            "van Helsing",
        )
        self.assertEqual(
            nameplate_gloss_for_alias(
                "ロードス", ["ロードス", "ロードス・ナイト"], "Lord Rhodes Knight"
            ),
            "Rhodes",
        )

    def test_lexicalized_san_nameplate_is_not_honorific_coverage(self):
        """``おじさん`` must not collapse to a curated ``おじ`` row."""
        vocab = (
            "# Game Characters\n"
            "おじ (Uncle)\n"
            "ニーナ / ネーナ・エヴァンス (Lady Nena Evans)\n"
        )
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(vocab, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
            ):
                mvmz._reload_vocab()
                with mvmz._speakerCacheLock:
                    mvmz._speakerCache.clear()

                self.assertEqual(mvmz._vocab_speaker_lookup("おじ"), "Uncle")
                self.assertIsNone(mvmz._vocab_speaker_lookup("おじさん"))
                self.assertEqual(mvmz._vocab_speaker_lookup("ニーナ"), "Nena")
                self.assertEqual(mvmz._vocab_speaker_lookup("ニーナ様"), "Lady Nena")

                mvmz.SPEAKER_PARSE_MODE = True
                mvmz.SPEAKER_COLLECTED = ["おじさん", "ニーナ様"]
                self.assertEqual(mvmz.pendingSpeakerNames(), ["おじさん"])

    def test_lexicalized_shi_and_dono_nameplates_are_not_honorific_coverage(self):
        """``源氏`` / ``御殿`` must not collapse to ``源`` / ``御``."""
        vocab = (
            "# Game Characters\n"
            "源 (Minamoto)\n"
            "御 (Go)\n"
            "源氏 (Genji)\n"
        )
        with TemporaryDirectory() as tmp:
            glossary_path = Path(tmp) / "glossary.txt"
            glossary_path.write_text(vocab, encoding="utf-8")
            with (
                patch.object(mvmz, "VOCAB_PATH", glossary_path),
                patch.object(mvmz, "active_glossary_path", return_value=glossary_path),
            ):
                mvmz._reload_vocab()
                with mvmz._speakerCacheLock:
                    mvmz._speakerCache.clear()

                self.assertEqual(mvmz._vocab_speaker_lookup("源"), "Minamoto")
                self.assertEqual(mvmz._vocab_speaker_lookup("源氏"), "Genji")
                self.assertEqual(mvmz._vocab_speaker_lookup("御"), "Go")
                self.assertIsNone(mvmz._vocab_speaker_lookup("御殿"))

                mvmz.SPEAKER_PARSE_MODE = True
                mvmz.SPEAKER_COLLECTED = ["源氏", "御殿"]
                self.assertEqual(mvmz.pendingSpeakerNames(), ["御殿"])

    def test_terms_slash_row_does_not_match_half_term(self):
        pairs = parseVocabWithCategories(
            "# Terms\n"
            "攻撃／防御 (Attack/Defense)\n"
            "# Game Characters\n"
            "ニーナ / ネーナ・エヴァンス (Nena Evans)\n"
        )

        terms_only = buildMatchedVocabText(pairs, "攻撃力が上がった")
        self.assertNotIn("攻撃／防御", terms_only)

        character_hit = buildMatchedVocabText(pairs, 'ニーナ "どうしたの？"')
        self.assertIn("ニーナ / ネーナ・エヴァンス (Nena Evans)", character_hit)

    def test_honorific_nameplate_reuses_curated_character_context(self):
        """``ニーナ様`` must reuse the curated row, not invent a short duplicate."""
        note = (
            "Female protagonist and Actors.json ID 1. Full name spoken once as "
            "Nena Evans; everyday lines use ニーナ."
        )
        pairs = parseVocabWithCategories(
            "# Game Characters\n"
            f"ニーナ / ネーナ・エヴァンス (Nena Evans) - {note}\n"
        )

        matched = buildMatchedVocabText(pairs, 'ニーナ様 "お願いします"')
        self.assertIn("ニーナ / ネーナ・エヴァンス (Nena Evans)", matched)
        self.assertIn(note, matched)
        self.assertNotIn("\nニーナ様 (", matched)

    def test_unique_full_name_component_matches_speaker_tag(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\n"
            "天草 果歩 (Kaho Amakusa)\n"
            "星宮 凛 (Rin Hoshimiya)\n"
        )

        matched = buildMatchedVocabText(pairs, '果歩 "どうしたの？"')

        self.assertIn("天草 果歩 (Kaho Amakusa)", matched)

    def test_full_name_component_does_not_match_ordinary_prose(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\n天草 果歩 (Kaho Amakusa)\n"
        )

        matched = buildMatchedVocabText(pairs, "果歩を見つけた。")

        self.assertEqual(matched, "")

    def test_ambiguous_name_component_does_not_choose_a_character(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\n"
            "天草 果歩 (Kaho Amakusa)\n"
            "山田 果歩 (Kaho Yamada)\n"
        )

        matched = buildMatchedVocabText(pairs, '果歩 "どうしたの？"')

        self.assertEqual(matched, "")

        pairs_with_short_alias = parseVocabWithCategories(
            "# Game Characters\n"
            "天草 果歩 (Kaho Amakusa)\n"
            "山田 果歩 (Kaho Yamada)\n"
            "果歩 (Kaho)\n"
        )
        english_prefixed = buildMatchedVocabText(
            pairs_with_short_alias, "[Kaho]: どうしたの？"
        )
        self.assertIn("果歩 (Kaho)", english_prefixed)
        self.assertNotIn("天草 果歩 (Kaho Amakusa)", english_prefixed)
        self.assertNotIn("山田 果歩 (Kaho Yamada)", english_prefixed)

    def test_curated_full_name_suppresses_generated_short_speaker_alias(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\n"
            "天草 果歩 (Kaho Amakusa)\n"
            "果歩 (Kaho)\n"
        )

        matched = buildMatchedVocabText(pairs, '果歩 "どうしたの？"')

        self.assertIn("天草 果歩 (Kaho Amakusa)", matched)
        self.assertNotIn("\n果歩 (Kaho)\n", matched)

        english_prefixed = buildMatchedVocabText(
            pairs, "[Kaho]: どうしたの？"
        )
        self.assertIn("天草 果歩 (Kaho Amakusa)", english_prefixed)
        self.assertNotIn("\n果歩 (Kaho)\n", english_prefixed)

    def test_character_entry_matches_inside_katakana_compound(self):
        pairs = parseVocabWithCategories(VOCAB)
        matched = buildMatchedVocabText(pairs, "ユウイベント5")

        self.assertIn("Here are glossary entries", matched)
        self.assertNotIn("Here are some vocabulary", matched)
        self.assertIn("ユウ (Yuu)", matched)

    def test_non_character_short_term_keeps_script_boundaries(self):
        pairs = parseVocabWithCategories("# Terms\nキス (Kiss)\n")
        matched = buildMatchedVocabText(pairs, "テキスト")

        self.assertEqual(matched, "")

    def test_curated_character_spelling_suppresses_generated_conflict(self):
        pairs = parseVocabWithCategories(
            "# Game Characters\nユウ (Yuu)\n\n# Speakers\nユウ (Yu)\n"
        )
        matched = buildMatchedVocabText(pairs, "ユウイベント5")

        self.assertIn("ユウ (Yuu)", matched)
        self.assertNotIn("ユウ (Yu)", matched)


if __name__ == "__main__":
    unittest.main()
