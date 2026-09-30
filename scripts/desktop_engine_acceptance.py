#!/usr/bin/env python3
"""Exercise the production RPG Maker adapter through the desktop service.

Real-game runs are offline. --approved-names --live sends only the four item
names already approved by the user, with a one-request allowance and the same
cumulative prototype spending ledger.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop.backend.project import atomic_json
from desktop.backend.service import WorkspaceService, LunaProvider
from scripts.desktop_acceptance import git_state

APPROVED_NAMES = ["イヤシの実", "初心者の加護", "ワナヨケール", "ワナミエール"]


def source_payload(params):
    text = params["messages"][-1]["content"]
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _end = decoder.raw_decode(text[index:])
            if isinstance(value, dict) and value and all(key.startswith("Line") for key in value):
                return list(value.values())
        except ValueError:
            pass
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--files", nargs="+", default=["Items.json", "Map001.json"])
    parser.add_argument("--phase", choices=["standard", "database", "dialogue"], default="standard")
    parser.add_argument("--approved-names", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if bool(args.source) == args.approved_names or (args.live and not args.approved_names):
        parser.error("Choose an offline source game, or --approved-names (optionally with --live).")
    if args.approved_names:
        source = ROOT / ".tmp-ui/desktop-evidence/approved-native-source"
        (source / "data").mkdir(parents=True, exist_ok=True)
        (source / "js").mkdir(exist_ok=True)
        (source / "js/plugins.js").write_text("var $plugins = [];", encoding="utf-8")
        atomic_json(source / "data/System.json", {})
        atomic_json(source / "data/Items.json", [None, *({"id": index, "name": name, "description": "", "note": ""}
                    for index, name in enumerate(APPROVED_NAMES, start=1))])
        before = None
        files, phase = ["Items.json"], "database"
    else:
        source = args.source.resolve(strict=True)
        before = git_state(source)
        files, phase = args.files, args.phase
    service = WorkspaceService(ROOT / ".tmp-ui/desktop-workspace", allow_live=args.live)
    started = time.perf_counter()
    try:
        project = service.import_project(str(source), original=not args.approved_names)["project"]
        snapshot_seconds = time.perf_counter() - started
        if args.live:
            provider = LunaProvider(service.ledger)
            def guarded(params):
                if source_payload(params) != APPROVED_NAMES:
                    raise ValueError("The engine request did not match the exact approved names; nothing was sent.")
                return provider.complete("production-engine-acceptance", params)
            service.native_provider = guarded
        preview = service.native_preview(project["id"], files, phase=phase, mode="live" if args.live else "offline", request_limit=1)
        job = service.start_native(project["id"], files, phase=phase, mode="live" if args.live else "offline", request_limit=1)
        service.worker.join(timeout=55)
        if service.worker.is_alive():
            service.stop(job["id"])
            service.worker.join(timeout=10)
        result = service.jobs[job["id"]]
        report = {"source": source.name, "original_revision": project["revision"], "project_id": project["id"], "job_id": job["id"],
                  "kind": "production-rpgmaker", "mode": result["mode"], "snapshot_seconds": snapshot_seconds,
                  "elapsed_seconds": time.perf_counter() - started, "status": result["status"], "message": result["message"],
                  "planned_files": preview["filenames"], "dependencies": preview["dependencies"], "native": result["native"],
                  "budget": service.ledger.summary(), "source_unchanged": None if before is None else before == git_state(source)}
        evidence = ROOT / ".tmp-ui/desktop-evidence" / (job["id"] + "-engine.json")
        atomic_json(evidence, report)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.approved_names and result["status"] == "complete":
            print(json.dumps(service.review_page(job["id"]), ensure_ascii=False, indent=2))
        return 0 if result["status"] == "complete" and report["source_unchanged"] is not False else 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
