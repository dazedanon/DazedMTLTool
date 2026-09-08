#!/usr/bin/env python3
"""Compile shared Len/Workflow context or import a reviewed Len glossary. No API calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from util.len_translation import (  # noqa: E402
    _write_atomic, import_glossary, load_project, prepare_project, request_context, shared_context,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Prepare shared guidance, setup instructions and the skill handoff")
    prepare.add_argument("--game-root", type=Path, required=True)
    context = commands.add_parser("context", help="Read current shared guidance; optionally compile one source batch")
    context.add_argument("--game-root", type=Path, required=True)
    context.add_argument("--sources", type=Path, help="JSON list of Japanese strings or ID-to-string object")
    context.add_argument("--instruction-key", help="Shared section.key field template")
    context.add_argument("--source-context", type=Path, help="Preceding untranslated Japanese text file")
    context.add_argument("--output", type=Path)
    importer = commands.add_parser("import-glossary", help="Merge reviewed names/terms; reject conflicting existing decisions")
    importer.add_argument("--game-root", type=Path, required=True)
    importer.add_argument("--input", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        project = load_project(args.game_root)
        if args.command == "prepare":
            print(prepare_project(project))
        elif args.command == "import-glossary":
            result = import_glossary(project, json.loads(args.input.read_text(encoding="utf-8-sig")))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not args.sources and (args.instruction_key or args.source_context):
                parser.error("--instruction-key and --source-context require --sources")
            if args.sources:
                sources = json.loads(args.sources.read_text(encoding="utf-8-sig"))
                previous = args.source_context.read_text(encoding="utf-8-sig") if args.source_context else ""
                result = request_context(project, sources, instruction_key=args.instruction_key, source_context=previous)
                filename = "request-context.json"
            else:
                result = shared_context(project)
                filename = "context.json"
            output = args.output or project.workspace / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(output)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Len context error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
