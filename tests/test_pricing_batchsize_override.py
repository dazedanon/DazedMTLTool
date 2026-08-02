import os
import unittest
from unittest.mock import patch

from util.translation import _lookup_model_price, getPricingConfig


class PricingBatchSizeOverrideTests(unittest.TestCase):
    def test_batch_size_environment_cases(self):
        without_batchsize = {k: v for k, v in os.environ.items() if k != "batchsize"}
        cases = (
            ("override", {"batchsize": "2"}, False, 2),
            ("model default", without_batchsize, True, 30),
        )
        for label, environment, clear, expected in cases:
            with self.subTest(label), patch.dict(
                os.environ, environment, clear=clear
            ):
                self.assertEqual(
                    getPricingConfig("claude-sonnet-4-6")["batchSize"],
                    expected,
                )

    def test_google_resource_model_name_uses_bare_model_pricing(self):
        pricing_db = {
            "gemini-3.6-flash": {
                "input_cost_per_token": 0.0000015,
                "output_cost_per_token": 0.0000075,
            },
            # This generic entry previously won an accidental prefix match.
            "models": {
                "input_cost_per_token": 0.0000001,
                "output_cost_per_token": 0.0,
            },
        }
        with patch("util.translation._load_litellm_pricing", return_value=pricing_db):
            self.assertEqual(
                _lookup_model_price("models/gemini-3.6-flash"),
                (1.5, 7.5),
            )

    def test_gemini_36_offline_fallback_uses_current_standard_rates(self):
        with patch("util.translation._lookup_model_price", return_value=None):
            cfg = getPricingConfig("models/gemini-3.6-flash")
        self.assertEqual(cfg["inputAPICost"], 1.5)
        self.assertEqual(cfg["outputAPICost"], 7.5)


if __name__ == "__main__":
    unittest.main()
