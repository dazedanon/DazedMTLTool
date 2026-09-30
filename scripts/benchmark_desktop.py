#!/usr/bin/env python3
"""Measure clean desktop launches on Linux, including the Python process tree.

Uses the production build with no debugger attached. PSS avoids counting shared
pages once per renderer. Cold OS cache and other platforms require separate runs.
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def process_tree(pid):
    found = {pid}
    pending = [pid]
    while pending:
        current = pending.pop()
        for task in Path(f"/proc/{current}/task").glob("*"):
            try:
                children = (task / "children").read_text().split()
            except (OSError, ProcessLookupError):
                continue
            for child in map(int, children):
                if child not in found:
                    found.add(child)
                    pending.append(child)
    return sorted(found)


def memory(pid):
    totals = {"rss_kib": 0, "pss_kib": 0, "processes": []}
    for child in process_tree(pid):
        try:
            fields = {}
            for line in Path(f"/proc/{child}/smaps_rollup").read_text().splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    if key in {"Rss", "Pss"}:
                        fields[key] = int(value.strip().split()[0])
            name = Path(f"/proc/{child}/comm").read_text().strip()
        except (OSError, ProcessLookupError):
            continue
        totals["rss_kib"] += fields.get("Rss", 0)
        totals["pss_kib"] += fields.get("Pss", 0)
        totals["processes"].append({"pid": child, "name": name, **fields})
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--packaged", type=Path, help="Measure a built application executable")
    parser.add_argument("--profile", type=Path, help="Reuse a chosen isolated application profile")
    args = parser.parse_args()
    if not 1 <= args.runs <= 5:
        parser.error("Choose 1–5 measurement runs.")
    if not sys.platform.startswith("linux"):
        parser.error("Process-tree PSS measurement currently requires Linux.")
    binary = args.packaged.resolve() if args.packaged else ROOT / "desktop/node_modules/electron/dist/electron"
    results = []
    with tempfile.TemporaryDirectory(prefix="dazedtl-perf-") as tmp:
        for index in range(args.runs):
            ready = Path(tmp) / f"ready-{index}.json"
            env = {**os.environ, "DAZEDTL_DESKTOP_WORKSPACE": str(args.workspace or Path(tmp) / "workspace"),
                   "DAZEDTL_DESKTOP_PROFILE": str(args.profile or Path(tmp) / "profile"),
                   "DAZEDTL_DESKTOP_METRICS_FILE": str(ready), "DAZEDTL_DESKTOP_ALLOW_LIVE": "0"}
            env.pop("ELECTRON_RUN_AS_NODE", None)
            command = [str(binary)] + ([] if args.packaged else [str(ROOT / "desktop")])
            start = time.perf_counter()
            with tempfile.TemporaryFile() as stderr:
                proc = subprocess.Popen(command, cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=stderr)
                try:
                    while not ready.exists():
                        if proc.poll() is not None or time.perf_counter() - start > 12:
                            stderr.seek(0)
                            diagnostic = ready.with_suffix(".diagnostic")
                            detail = diagnostic.read_text() if diagnostic.exists() else "No page diagnostic available."
                            raise RuntimeError("Desktop did not become ready: " + stderr.read().decode(errors="replace")[-2000:] + "\n" + detail)
                        time.sleep(.025)
                    ready_ms = (time.perf_counter() - start) * 1000
                    time.sleep(.5)
                    sample = {"ready_ms": round(ready_ms, 1), **memory(proc.pid)}
                    results.append(sample)
                    proc.wait(timeout=8)
                    print(json.dumps({"shell": "electron", "run": index + 1, "ready_ms": sample["ready_ms"],
                                      "pss_mb": round(sample["pss_kib"] / 1024, 1), "rss_mb": round(sample["rss_kib"] / 1024, 1)}), flush=True)
                finally:
                    if proc.poll() is None:
                        for pid in reversed(process_tree(proc.pid)):
                            try:
                                os.kill(pid, 15)
                            except ProcessLookupError:
                                pass
                        proc.wait(timeout=10)
    evidence = ROOT / ".tmp-ui/desktop-evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"shell": "electron", "packaged": bool(args.packaged), "workspace": "existing" if args.workspace else "empty", "runs": results,
              "binary_bytes": binary.stat().st_size, "measurement": "Linux display session; warm filesystem cache; no debugger; process-tree PSS includes Python"}
    suffix = ("-packaged" if args.packaged else "") + ("-loaded" if args.workspace else "")
    (evidence / f"electron-performance{suffix}.json").write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
