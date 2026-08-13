"""Hermetic contract tests for the blind character-name regression fixture."""

import json
import tempfile
import unittest
from pathlib import Path

from scripts.score_name_reading_fixture import (
    load_oracle,
    score_result,
    validate_fixture,
    validate_result,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "name_reading_justeza"
ORACLE_PATH = ROOT / "tests" / "oracles" / "name_reading_justeza.json"
COMMON_NOUN_FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "name_reading_subject_d"
COMMON_NOUN_ORACLE_PATH = ROOT / "tests" / "oracles" / "name_reading_common_noun.json"


def _passing_result() -> dict[str, str]:
    return {
        "subject_id": "C",
        "recommendation": "Justeza Roa",
        "confidence": "High",
        "lexical_language": "Portuguese",
        "lexical_source_word": "justeza",
        "lexical_meaning": "Conformity with justice; rightness, exactness, and truth.",
        "lexical_source_url": "https://www.infopedia.pt/dicionarios/lingua-portuguesa/justeza",
        "kana_discrepancy": (
            "Portuguese begins with a /zh/ sound, normally suggesting Japanese ジュ rather "
            "than the attested initial ユ; this is a minor kana transcription mismatch."
        ),
        "rationale": (
            "Justeza is an attested Portuguese word whose justice and rightness meaning matches "
            "the character's moral judgments about good and evil. It explains the name and lore, "
            "while Yusteza is an unexplained mechanical kana transliteration. The irregular "
            "initial transcription is contrary phonetic evidence, not an automatic veto."
        ),
    }


class NameReadingFixtureTests(unittest.TestCase):
    def setUp(self):
        self.oracle = load_oracle(ORACLE_PATH)

    def test_blind_fixture_is_hash_bound_and_contains_no_oracle_answer(self):
        fixture = validate_fixture(self.oracle, FIXTURE_ROOT)
        self.assertEqual([path.name for path in FIXTURE_ROOT.iterdir()], ["source_evidence.md"])
        lowered = fixture.read_text(encoding="utf-8").casefold()
        for leaked_answer in ("justeza", "yusteza", "lore"):
            self.assertNotIn(leaked_answer, lowered)

    def test_scorer_accepts_justeza_with_lexical_and_kana_evidence(self):
        score = score_result(self.oracle, _passing_result())
        self.assertTrue(score["quality_pass"])
        self.assertEqual(score["failures"], [])

        labeled_subject = {**_passing_result(), "subject_id": "Subject C"}
        self.assertTrue(score_result(self.oracle, labeled_subject)["quality_pass"])

        spanish_evidence = {
            **_passing_result(),
            "lexical_language": "Spanish",
            "lexical_meaning": "The quality of being just or exact.",
            "lexical_source_url": "https://www.rae.es/diccionario-estudiante/justeza",
            "kana_discrepancy": (
                "The source begins with ユ, while Spanish j is /x/; the spelling is inferred "
                "despite that exact phonetic discrepancy."
            ),
        }
        self.assertTrue(score_result(self.oracle, spanish_evidence)["quality_pass"])

    def test_scorer_rejects_mechanical_or_lore_spellings(self):
        for recommendation in (
            "Yusteza Roa",
            "Yusteza Loa",
            "Justeza Loa",
            "Justeza Lore",
        ):
            with self.subTest(recommendation=recommendation):
                result = {**_passing_result(), "recommendation": recommendation}
                score = score_result(self.oracle, result)
                self.assertFalse(score["quality_pass"])
                self.assertIn("recommendation", score["failures"])
                self.assertIn("forbidden_recommendation_absent", score["failures"])

    def test_scorer_requires_authoritative_lexical_and_discrepancy_evidence(self):
        weak = {
            **_passing_result(),
            "lexical_source_url": "https://example.com/justeza",
            "kana_discrepancy": "There is a small difference.",
            "rationale": "It sounds nicer.",
        }
        score = score_result(self.oracle, weak)
        self.assertFalse(score["quality_pass"])
        self.assertIn("lexical_source_url", score["failures"])
        self.assertIn("kana_discrepancy", score["failures"])
        self.assertIn("rationale", score["failures"])

    def test_result_schema_and_fixture_tampering_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_result({**_passing_result(), "unexpected": "field"})

        with tempfile.TemporaryDirectory() as raw:
            fixture_root = Path(raw)
            (fixture_root / "source_evidence.md").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate_fixture(self.oracle, fixture_root)

    def test_common_noun_reading_remains_eligible_with_independent_naming_signals(self):
        oracle = load_oracle(COMMON_NOUN_ORACLE_PATH)
        fixture = validate_fixture(oracle, COMMON_NOUN_FIXTURE_ROOT)
        self.assertEqual(
            [path.name for path in COMMON_NOUN_FIXTURE_ROOT.iterdir()],
            ["source_evidence.md"],
        )
        lowered = fixture.read_text(encoding="utf-8").casefold()
        for leaked_answer in ("bell", "belle", "beru"):
            self.assertNotIn(leaked_answer, lowered)
        result = {
            "subject_id": "D",
            "recommendation": "Bell",
            "confidence": "High",
            "lexical_language": "English",
            "lexical_source_word": "bell",
            "lexical_meaning": "A hollow metal instrument that makes a ringing sound.",
            "lexical_source_url": "https://www.merriam-webster.com/dictionary/bell",
            "kana_discrepancy": (
                "ベル (beru) is the ordinary Japanese adaptation of English Bell, adding an "
                "epenthetic final vowel."
            ),
            "rationale": (
                "Multiple independent naming signals converge: the parent explicitly says the "
                "siblings were named for different bell sounds; Chime and Gong demonstrate the "
                "family pattern; and the recurring ringing pun and bell emblem reinforce the "
                "wordplay."
            ),
        }
        self.assertTrue(score_result(oracle, result)["quality_pass"])

        conservative_but_wrong = {**result, "recommendation": "Belle"}
        score = score_result(oracle, conservative_but_wrong)
        self.assertFalse(score["quality_pass"])
        self.assertIn("recommendation", score["failures"])


if __name__ == "__main__":
    unittest.main()
