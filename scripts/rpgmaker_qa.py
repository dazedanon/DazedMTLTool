#!/usr/bin/env python3
"""Prepare and coordinate local AI-helper RPG Maker translation QA."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from util import rpgmaker_qa  # noqa: E402
from util.rpgmaker_qa_manifest import FOCUSES  # noqa: E402


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--game-root", required=True, type=Path)
    prepare.add_argument("--data", required=True, type=Path)
    prepare.add_argument("--focus", required=True, choices=sorted(FOCUSES))
    prepare.add_argument("--output-root", required=True, type=Path)

    for name in ("status", "advance", "finalize", "dry-run"):
        command = sub.add_parser(name)
        command.add_argument("--task", required=True, type=Path)
    rebuild = sub.add_parser("rebuild-deep")
    rebuild.add_argument("--task", required=True, type=Path)
    rebuild.add_argument("--output-root", type=Path)
    rebuild_final = sub.add_parser("rebuild-final")
    rebuild_final.add_argument("--task", required=True, type=Path)
    rebuild_final.add_argument("--output-root", type=Path)
    next_cmd = sub.add_parser("next")
    next_cmd.add_argument("--task", required=True, type=Path)
    next_cmd.add_argument("--worker", required=True)
    accept = sub.add_parser("accept")
    accept.add_argument("--task", required=True, type=Path)
    accept.add_argument("--result", required=True, type=Path)
    release = sub.add_parser("release")
    release.add_argument("--task", required=True, type=Path)
    release.add_argument("--bundle", required=True)
    corrections = sub.add_parser("corrections")
    corrections.add_argument("--task", required=True, type=Path)
    corrections.add_argument("--approve", nargs="+", required=True)
    apply_cmd = sub.add_parser("apply")
    apply_cmd.add_argument("--task", required=True, type=Path)
    regress = sub.add_parser("regress")
    regress.add_argument("--task", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "prepare":
        task, state = rpgmaker_qa.prepare_task(
            args.game_root, args.data, args.focus, args.output_root
        )
        _print({"task": str(task), "status": state})
    elif args.command == "status":
        _print(rpgmaker_qa.status(args.task))
    elif args.command == "next":
        bundle = rpgmaker_qa.next_bundle(args.task, args.worker)
        _print(bundle or {"bundle": None, "status": rpgmaker_qa.status(args.task)})
    elif args.command == "accept":
        _print(rpgmaker_qa.accept_result(args.task, args.result))
    elif args.command == "release":
        _print(rpgmaker_qa.release_bundle(args.task, args.bundle))
    elif args.command == "advance":
        _print(rpgmaker_qa.advance(args.task))
    elif args.command == "rebuild-deep":
        task, state = rpgmaker_qa.rebuild_deep_from_screen(
            args.task, args.output_root
        )
        _print({"task": str(task), "status": state})
    elif args.command == "rebuild-final":
        task, state = rpgmaker_qa.rebuild_findings_from_results(
            args.task, args.output_root
        )
        _print({"task": str(task), "status": state})
    elif args.command == "finalize":
        _print(rpgmaker_qa.finalize(args.task))
    elif args.command == "corrections":
        _print(rpgmaker_qa.create_correction_map(args.task, args.approve))
    elif args.command == "dry-run":
        _print(rpgmaker_qa.dry_run_correction_map(args.task))
    elif args.command == "apply":
        _print(rpgmaker_qa.apply_correction_map(args.task))
    elif args.command == "regress":
        _print(rpgmaker_qa.regression_check(args.task))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
