#!/usr/bin/env python3
"""Opt-in manual acceptance on a real game's original branch; never a unit fixture.

Paid tests require --live. Every request passes through the same persistent $5
ledger as the desktop prototype. No game worktree or branch is modified.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop.backend.service import WorkspaceService


def git_state(source):
    def run(*args):
        return subprocess.run(["git", "-C", str(source), *args], check=True, capture_output=True, timeout=30).stdout.decode()
    return {"head": run("rev-parse", "HEAD"), "branch": run("branch", "--show-current"), "status": run("status", "--porcelain=v1")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, nargs="?")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--synthetic", action="store_true", help="Use only generated fixture text, with no user game content")
    args = parser.parse_args()
    if bool(args.source) == args.synthetic:
        parser.error("Choose either a source game or --synthetic.")
    if args.synthetic:
        source = ROOT / ".tmp-ui/desktop-evidence/synthetic-source"
        (source / "data").mkdir(parents=True, exist_ok=True)
        (source / "js").mkdir(exist_ok=True)
        (source / "data/System.json").write_text('{}', encoding="utf-8")
        (source / "data/Items.json").write_text(json.dumps([None, *({"id": i, "name": text} for i, text in enumerate(
            ["回復薬", "鉄の剣", "炎の魔法", "村へ戻る"], start=1))], ensure_ascii=False), encoding="utf-8")
        (source / "js/plugins.js").write_text('var $plugins = [];', encoding="utf-8")
        before = None
    else:
        source = args.source.resolve(strict=True)
        before = git_state(source)
    workspace = ROOT / ".tmp-ui/desktop-workspace"
    service = WorkspaceService(workspace, allow_live=args.live)
    started = time.perf_counter()
    try:
        project = service.import_project(str(source), original=not args.synthetic)["project"]
        import_seconds = time.perf_counter() - started
        full = service.records(project["id"])
        records = [r for r in full if r["file"] == "Items.json" and r["pointer"].endswith("/name")][:4]
        if not records:
            records = [r for r in full if r["category"] == "database"][:4]
        if not records:
            raise ValueError("No suitable short database sample was found.")
        service.save_guidance(project["id"], "Translate these RPG item names into concise English. Keep names consistent and preserve runtime tokens.")
        job = service.start(project["id"], [r["id"] for r in records], "live" if args.live else "offline")
        service.worker.join(timeout=55)
        if service.worker.is_alive():
            service.stop(job["id"])
            raise ValueError("Acceptance run exceeded its time limit.")
        result = service.jobs[job["id"]]
        report = {"project_id": project["id"], "job_id": job["id"], "source": source.name,
                  "source_revision": project["revision"], "data_files": len(project["files"]),
                  "supported_entries": project["total_records"], "import_seconds": import_seconds,
                  "elapsed_seconds": time.perf_counter() - started, "mode": result["mode"],
                  "status": result["status"], "message": result["message"], "budget": service.ledger.summary(),
                  "source_unchanged": None if args.synthetic else before == git_state(source),
                  "generated_fixture": args.synthetic,
                  "sample": [{"source": r["source"], **result["results"].get(r["id"], {})} for r in records]}
        evidence = ROOT / ".tmp-ui/desktop-evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        (evidence / (job["id"] + ".json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "complete" and (args.synthetic or report["source_unchanged"]) else 1
    finally:
        service.close()


if __name__ == "__main__":
    raise SystemExit(main())
