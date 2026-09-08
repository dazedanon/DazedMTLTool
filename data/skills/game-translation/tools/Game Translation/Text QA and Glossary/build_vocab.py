"""Compatibility entrypoint for DazedTL's shared glossary importer.

Usage: python build_vocab.py --game-root <game> --input <reviewed-glossary.json>
Run from the shipped tool location. Adapted copies should invoke the application CLI.
"""
from pathlib import Path
import sys

APP_ROOT = Path(__file__).resolve().parents[6]
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
from scripts.len_translation import main

if __name__ == "__main__":
    raise SystemExit(main(["import-glossary", *sys.argv[1:]]))
