#!/usr/bin/env python3
"""Prepare Len's context and baselines, and write source-preserving game JSON. No API calls."""

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
    from util.version_update import GitWorkflowError

    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Prepare shared guidance, setup instructions and the skill handoff")
    prepare.add_argument("--game-root", type=Path, required=True)
    rpg_prep = commands.add_parser("rpgmaker-prep", help="Run Workflow's RPG Maker formatting and GameUpdate preparation before Git setup")
    rpg_prep.add_argument("--game-root", type=Path, required=True)
    rpg_prep.add_argument("--data-path", type=Path, help="Existing Ace JSON export; defaults to the game's ace_json folder")
    context = commands.add_parser("context", help="Read current shared guidance; optionally compile one source batch")
    context.add_argument("--game-root", type=Path, required=True)
    context.add_argument("--sources", type=Path, help="JSON list of Japanese strings or ID-to-string object")
    context.add_argument("--speakers", type=Path, help="JSON speaker names/nulls with the same IDs or list positions as --sources")
    context.add_argument("--instruction-key", help="Shared section.key field template")
    context.add_argument("--source-context", type=Path, help="Preceding untranslated Japanese text file")
    context.add_argument("--output", type=Path)
    many = commands.add_parser("context-many", help="Compile a saved multi-batch plan in one process, with dependency checks")
    many.add_argument("--game-root", type=Path, required=True)
    many.add_argument("--input", type=Path, required=True, help="JSON object with complete, inputs and batches")
    many.add_argument("--output", type=Path)
    importer = commands.add_parser("import-glossary", help="Merge reviewed names/terms; reject conflicting existing decisions")
    importer.add_argument("--game-root", type=Path, required=True)
    importer.add_argument("--input", type=Path, required=True)
    git_inspect = commands.add_parser("git-status", help="Inspect the selected game's Git baselines without changing them")
    git_inspect.add_argument("--game-root", type=Path, required=True)
    git_setup = commands.add_parser("git-setup", help="Create or reuse local original/translation baselines, preserving native game bytes")
    git_setup.add_argument("--game-root", type=Path, required=True)
    git_setup.add_argument("--original", type=Path, help="Separate untranslated source if needed; fresh tasks default to the selected game")
    git_setup.add_argument("--current-is-untranslated", action="store_true", help="Use the selected game when resuming preparation after verifying it is still untranslated")
    git_setup.add_argument("--version", help="Release label belonging to the starting game")
    scope = commands.add_parser("git-scope", help="Stage only reviewed patch files and align their untranslated original backup")
    scope.add_argument("--game-root", type=Path, required=True)
    scope.add_argument("--manifest", type=Path, required=True, help="Complete runtime path list or hash-bound release manifest")
    scope.add_argument("--original", type=Path, help="Matching untranslated backup for files not yet on the original branch")
    scope.add_argument("--dry-run", action="store_true", help="Validate and report without changing branch refs, index or game files")
    progress = commands.add_parser("progress", help="Read the last compact progress report and freshness warnings")
    progress.add_argument("--game-root", type=Path, required=True)
    progress_update = commands.add_parser("progress-update", help="Count saved unit records and replace the compact progress report")
    progress_update.add_argument("--game-root", type=Path, required=True)
    progress_update.add_argument("--input", type=Path, required=True, help="JSON report file, or - to read JSON from stdin")
    writer = commands.add_parser("write-rpgmaker-json", help="Write staged MV/MZ data JSON with Workflow-compatible _original metadata")
    writer.add_argument("--source", type=Path, required=True, help="Matching untranslated baseline or previous game file with originals intact")
    writer.add_argument("--translated", type=Path, required=True, help="Separate staged translation with the same array order and structure")
    writer.add_argument("--output", type=Path, required=True, help="Destination game JSON file; existing originals are retained")
    args = parser.parse_args(argv)
    try:
        if args.command == "write-rpgmaker-json":
            from util.len_originals import write_rpgmaker_json

            print(write_rpgmaker_json(args.source, args.translated, args.output))
            return 0
        project = load_project(args.game_root)
        if args.command == "prepare":
            print(prepare_project(project))
        elif args.command == "rpgmaker-prep":
            from util.project_preparation import prepare_rpgmaker

            result = prepare_rpgmaker(project.game_root, data_path=args.data_path,
                                     log=lambda message: print(message, file=sys.stderr))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "context-many":
            from util.len_api import compile_plan
            result = compile_plan(project, json.loads(args.input.read_text(encoding="utf-8-sig")))
            output = args.output or project.workspace / "api-requests.json"
            output.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(output)
        elif args.command in {"progress", "progress-update"}:
            from util.len_progress import read_progress, update_progress

            if args.command == "progress-update":
                report = json.loads(sys.stdin.read() if args.input == Path("-") else args.input.read_text(encoding="utf-8-sig"))
                result = update_progress(project, report)
            else:
                result = read_progress(project)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "import-glossary":
            result = import_glossary(project, json.loads(args.input.read_text(encoding="utf-8-sig")))
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command == "git-scope":
            from util.len_patch_scope import sync_patch_scope

            result = sync_patch_scope(project, json.loads(args.manifest.read_text(encoding="utf-8-sig")),
                                      original_game=args.original, dry_run=args.dry_run)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        elif args.command in {"git-status", "git-setup"}:
            from util.len_git import git_status, setup_git

            result = git_status(project) if args.command == "git-status" else setup_git(
                project, original_game=args.original, version=args.version,
                current_is_untranslated=args.current_is_untranslated,
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            if not args.sources and (args.instruction_key or args.source_context or args.speakers):
                parser.error("--instruction-key, --source-context and --speakers require --sources")
            if args.sources:
                sources = json.loads(args.sources.read_text(encoding="utf-8-sig"))
                previous = args.source_context.read_text(encoding="utf-8-sig") if args.source_context else ""
                speakers = json.loads(args.speakers.read_text(encoding="utf-8-sig")) if args.speakers else None
                if args.speakers and not isinstance(speakers, (list, dict)):
                    raise ValueError("Speakers JSON must be an ID-to-name object or an aligned list; use null for individual unknown speakers.")
                result = request_context(project, sources, instruction_key=args.instruction_key, source_context=previous, speakers=speakers)
                filename = "request-context.json"
            else:
                result = shared_context(project)
                filename = "context.json"
            output = args.output or project.workspace / filename
            output.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(output, json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            print(output)
    except (OSError, ValueError, KeyError, TypeError, IndexError, GitWorkflowError) as exc:
        print(f"Len error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
