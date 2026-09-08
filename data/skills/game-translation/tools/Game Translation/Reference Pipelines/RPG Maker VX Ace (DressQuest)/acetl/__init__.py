"""acetl - RPG Maker VX Ace translation pipeline for `Dress Quest`.

Extract -> translate (Claude batch or live) -> validate -> inject, straight
into the game's Ruby Marshal data with no lossy JSON round trip in between.

Importing the package reconfigures stdout/stderr to UTF-8 with
`backslashreplace`. That is a side effect on import, and it is deliberate: the
Windows console this runs on is cp1252, every tool in here prints Japanese, and
a `UnicodeEncodeError` in the middle of a report is a crash that hides the
report. `backslashreplace` degrades a character it cannot draw instead of
losing the run.
"""

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    except (AttributeError, ValueError):
        pass

__all__ = [
    "rvmarshal", "rvdata", "config", "codes", "measure", "wrap", "store",
    "extract", "inject", "prompts", "requests", "parse", "validate", "client",
    "driver", "estimate", "scripts_rb", "qa",
]
