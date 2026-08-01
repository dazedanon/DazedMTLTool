import os
import unittest
from unittest.mock import patch

from util.translation import _lookup_model_price, getPricingConfig


class PricingBatchSizeOverrideTests(unittest.TestCase):
    def test_env_batchsize_overrides_model_default(self):
        with patch.dict(os.environ, {"batchsize": "2"}, clear=False):
            cfg = getPricingConfig("claude-sonnet-4-6")
        self.assertEqual(cfg["batchSize"], 2)

    def test_missing_env_keeps_model_default(self):
        env = {k: v for k, v in os.environ.items() if k != "batchsize"}
        with patch.dict(os.environ, env, clear=True):
            cfg = getPricingConfig("claude-sonnet-4-6")
        self.assertEqual(cfg["batchSize"], 30)

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
