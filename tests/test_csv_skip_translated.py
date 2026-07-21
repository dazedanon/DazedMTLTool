import unittest
from unittest.mock import MagicMock, patch

import modules.csv as csv_mod


class TargetTranslatedDetectionTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "SOURCE_COLUMN": csv_mod.SOURCE_COLUMN,
            "TARGET_COLUMN": csv_mod.TARGET_COLUMN,
            "WRITE_TO_NEXT_COLUMN": csv_mod.WRITE_TO_NEXT_COLUMN,
            "USE_TARGET_IF_NOT_EMPTY": csv_mod.USE_TARGET_IF_NOT_EMPTY,
            "SKIP_HEADER_ROW": csv_mod.SKIP_HEADER_ROW,
            "SKIP_COMMENT_ROWS": csv_mod.SKIP_COMMENT_ROWS,
            "SKIP_IF_TARGET_TRANSLATED": csv_mod.SKIP_IF_TARGET_TRANSLATED,
            "BATCHSIZE": csv_mod.BATCHSIZE,
        }
        csv_mod.SOURCE_COLUMN = 0
        csv_mod.TARGET_COLUMN = 1
        csv_mod.WRITE_TO_NEXT_COLUMN = False
        csv_mod.USE_TARGET_IF_NOT_EMPTY = False
        csv_mod.SKIP_HEADER_ROW = False
        csv_mod.SKIP_COMMENT_ROWS = False

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(csv_mod, key, value)

    def test_empty_target_not_translated(self):
        self.assertFalse(csv_mod._target_is_translated(["こんにちは", ""]))

    def test_missing_target_column_not_translated(self):
        self.assertFalse(csv_mod._target_is_translated(["こんにちは"]))

    def test_english_target_is_translated(self):
        self.assertTrue(csv_mod._target_is_translated(["こんにちは", "Hello"]))

    def test_japanese_target_not_translated(self):
        self.assertFalse(csv_mod._target_is_translated(["こんにちは", "こんにちは"]))

    def test_write_to_next_column_checks_next(self):
        csv_mod.WRITE_TO_NEXT_COLUMN = True
        self.assertFalse(csv_mod._target_is_translated(["こんにちは", "Hello", ""]))
        self.assertTrue(csv_mod._target_is_translated(["こんにちは", "Hello", "Hello there"]))


class SkipTranslatedBatchIndexTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "SOURCE_COLUMN": csv_mod.SOURCE_COLUMN,
            "TARGET_COLUMN": csv_mod.TARGET_COLUMN,
            "WRITE_TO_NEXT_COLUMN": csv_mod.WRITE_TO_NEXT_COLUMN,
            "USE_TARGET_IF_NOT_EMPTY": csv_mod.USE_TARGET_IF_NOT_EMPTY,
            "SKIP_HEADER_ROW": csv_mod.SKIP_HEADER_ROW,
            "SKIP_COMMENT_ROWS": csv_mod.SKIP_COMMENT_ROWS,
            "SKIP_IF_TARGET_TRANSLATED": csv_mod.SKIP_IF_TARGET_TRANSLATED,
            "BATCHSIZE": csv_mod.BATCHSIZE,
        }
        csv_mod.SOURCE_COLUMN = 0
        csv_mod.TARGET_COLUMN = 1
        csv_mod.WRITE_TO_NEXT_COLUMN = False
        csv_mod.USE_TARGET_IF_NOT_EMPTY = False
        csv_mod.SKIP_HEADER_ROW = False
        csv_mod.SKIP_COMMENT_ROWS = False
        csv_mod.BATCHSIZE = 30

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(csv_mod, key, value)

    def test_default_off_keeps_all_candidates(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = False
        data = [
            ["こんにちは", "Hello"],
            ["さようなら", ""],
        ]
        self.assertEqual(csv_mod._collect_process_indices(data), [0, 1])

    def test_fully_translated_batch_is_skipped(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = True
        csv_mod.BATCHSIZE = 2
        data = [
            ["あ", "A"],
            ["い", "I"],
            ["う", ""],
            ["え", ""],
        ]
        # First batch (0,1) all translated -> skip; second batch (2,3) needs work
        self.assertEqual(csv_mod._collect_process_indices(data), [2, 3])

    def test_partial_batch_queues_only_untranslated_rows(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = True
        csv_mod.BATCHSIZE = 3
        data = [
            ["あ", "A"],
            ["い", ""],
            ["う", "U"],
            ["え", "E"],
            ["お", "O"],
            ["か", "Ka"],
        ]
        # Batch [0,1,2] has work -> keep only untranslated row 1
        # Batch [3,4,5] all translated -> skip
        self.assertEqual(csv_mod._collect_process_indices(data), [1])

    def test_uses_global_batch_size(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = True
        csv_mod.BATCHSIZE = 30
        data = [["行" + str(i), f"Line {i}"] for i in range(30)]
        data.append(["未翻訳", ""])
        # First 30 fully translated -> skipped; last singleton batch needs work
        self.assertEqual(csv_mod._collect_process_indices(data), [30])

    def test_header_with_english_target_skipped_when_opt_in(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = True
        csv_mod.SKIP_HEADER_ROW = False
        csv_mod.BATCHSIZE = 10
        data = [
            ["Source", "Target"],
            ["こんにちは", ""],
            ["ありがとう", "Thank you."],
        ]
        # Header target looks translated; thank-you row preserved; only empty target queued
        self.assertEqual(csv_mod._collect_process_indices(data), [1])


class SkipIfTargetTranslatedCollectTests(unittest.TestCase):
    def setUp(self):
        self._orig = {
            "SOURCE_COLUMN": csv_mod.SOURCE_COLUMN,
            "TARGET_COLUMN": csv_mod.TARGET_COLUMN,
            "SPEAKER_COLUMN": csv_mod.SPEAKER_COLUMN,
            "SKIP_HEADER_ROW": csv_mod.SKIP_HEADER_ROW,
            "USE_TARGET_IF_NOT_EMPTY": csv_mod.USE_TARGET_IF_NOT_EMPTY,
            "SKIP_IF_TARGET_TRANSLATED": csv_mod.SKIP_IF_TARGET_TRANSLATED,
            "BATCHSIZE": csv_mod.BATCHSIZE,
            "WRITE_TO_NEXT_COLUMN": csv_mod.WRITE_TO_NEXT_COLUMN,
            "PARSE_NAME_TAGS": csv_mod.PARSE_NAME_TAGS,
            "PARSE_M_MARKERS": csv_mod.PARSE_M_MARKERS,
            "REMOVE_FURIGANA": csv_mod.REMOVE_FURIGANA,
            "SKIP_COMMENT_ROWS": csv_mod.SKIP_COMMENT_ROWS,
            "ESTIMATE": csv_mod.ESTIMATE,
        }
        csv_mod.SOURCE_COLUMN = 0
        csv_mod.TARGET_COLUMN = 1
        csv_mod.SPEAKER_COLUMN = -1
        csv_mod.SKIP_HEADER_ROW = False
        csv_mod.USE_TARGET_IF_NOT_EMPTY = False
        csv_mod.WRITE_TO_NEXT_COLUMN = False
        csv_mod.PARSE_NAME_TAGS = False
        csv_mod.PARSE_M_MARKERS = False
        csv_mod.REMOVE_FURIGANA = False
        csv_mod.SKIP_COMMENT_ROWS = False
        csv_mod.ESTIMATE = True
        csv_mod.BATCHSIZE = 30

    def tearDown(self):
        for key, value in self._orig.items():
            setattr(csv_mod, key, value)

    def test_default_off_does_not_skip_translated_targets(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = False
        data = [
            ["こんにちは", "Hello"],
            ["さようなら", ""],
        ]
        pbar = MagicMock()
        with patch.object(csv_mod, "translateAI", return_value=(["Hello", "Goodbye"], [0, 0])) as mock_ai:
            with patch.object(csv_mod, "dazedwrap") as mock_wrap:
                mock_wrap.wrapText.side_effect = lambda text, _width: text
                csv_mod.translateCSV(data, pbar, None, MagicMock(), "test.csv", None)
        self.assertEqual(mock_ai.call_args[0][0], ["こんにちは", "さようなら"])

    def test_opt_in_skips_only_fully_translated_batches(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = True
        csv_mod.BATCHSIZE = 2
        data = [
            ["こんにちは", "Hello"],
            ["おはよう", "Good morning"],
            ["さようなら", ""],
            ["ありがとう", "ありがとう"],
        ]
        pbar = MagicMock()
        with patch.object(
            csv_mod, "translateAI", return_value=(["Goodbye", "Thank you"], [0, 0])
        ) as mock_ai:
            with patch.object(csv_mod, "dazedwrap") as mock_wrap:
                mock_wrap.wrapText.side_effect = lambda text, _width: text
                csv_mod.translateCSV(data, pbar, None, MagicMock(), "test.csv", None)
        # First batch fully translated -> skipped; second batch keeps unfinished only
        self.assertEqual(mock_ai.call_args[0][0], ["さようなら", "ありがとう"])
        self.assertEqual(data[0][1], "Hello")
        self.assertEqual(data[1][1], "Good morning")
        self.assertEqual(data[2][1], "Goodbye")
        self.assertEqual(data[3][1], "Thank you")

    def test_partial_batch_preserves_already_done_rows(self):
        csv_mod.SKIP_IF_TARGET_TRANSLATED = True
        csv_mod.BATCHSIZE = 2
        data = [
            ["こんにちは", "Hello"],
            ["さようなら", ""],
        ]
        pbar = MagicMock()
        with patch.object(
            csv_mod, "translateAI", return_value=(["Goodbye"], [0, 0])
        ) as mock_ai:
            with patch.object(csv_mod, "dazedwrap") as mock_wrap:
                mock_wrap.wrapText.side_effect = lambda text, _width: text
                csv_mod.translateCSV(data, pbar, None, MagicMock(), "test.csv", None)
        # Mixed batch: only the unfinished row is sent; existing translation kept
        self.assertEqual(mock_ai.call_args[0][0], ["さようなら"])
        self.assertEqual(data[0][1], "Hello")
        self.assertEqual(data[1][1], "Goodbye")


if __name__ == "__main__":
    unittest.main()
