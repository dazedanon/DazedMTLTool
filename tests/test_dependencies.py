"""Tests for the lightweight launcher dependency probe."""

from __future__ import annotations

import unittest

from util.dependencies import REQUIRED_MODULES, missing_dependencies


class DependencyProbeTests(unittest.TestCase):
    def test_probe_reports_requirements_without_importing_modules(self):
        resolved = []
        unavailable = {"google.genai", "PIL"}

        def resolver(module):
            resolved.append(module)
            return None if module in unavailable else object()

        self.assertEqual(
            missing_dependencies(resolver),
            ["google-genai", "pillow"],
        )
        self.assertEqual(resolved, list(REQUIRED_MODULES.values()))


if __name__ == "__main__":
    unittest.main()
