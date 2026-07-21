import os
import unittest
from unittest.mock import patch

from util.translation import getPricingConfig


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


if __name__ == "__main__":
    unittest.main()
