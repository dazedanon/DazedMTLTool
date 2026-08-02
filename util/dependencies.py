"""Lightweight dependency availability checks for startup launchers."""

from __future__ import annotations

from importlib.util import find_spec
from typing import Callable


REQUIRED_MODULES = {
    "anthropic": "anthropic",
    "colorama": "colorama",
    "openai": "openai",
    "google-genai": "google.genai",
    "python-dotenv": "dotenv",
    "retry": "retry",
    "tiktoken": "tiktoken",
    "tqdm": "tqdm",
    "jsbeautifier": "jsbeautifier",
    "pillow": "PIL",
    "PyQt5": "PyQt5",
    "qtawesome": "qtawesome",
    "markdown": "markdown",
}


def missing_dependencies(
    resolver: Callable[[str], object | None] = find_spec,
) -> list[str]:
    """Return requirement names whose import modules are unavailable."""
    missing = []
    for requirement, module in REQUIRED_MODULES.items():
        try:
            available = resolver(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing.append(requirement)
    return missing


def main() -> int:
    missing = missing_dependencies()
    if missing:
        print("Missing dependencies: " + ", ".join(missing))
        return 1
    print("All dependencies satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
