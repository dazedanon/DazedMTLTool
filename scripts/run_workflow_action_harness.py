#!/usr/bin/env python3
"""Run the side-effect-safe RPG Maker workflow action regression harness."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main() -> int:
    print(
        "RPG Maker workflow action harness: "
        "49 control routes + disposable handler contracts"
    )
    suite = unittest.defaultTestLoader.loadTestsFromName(
        "tests.test_workflow_actions"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())

