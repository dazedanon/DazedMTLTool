#!/usr/bin/env python3
"""Stage an Electron release's Python runtime, shipped helpers and defaults.

Run on each target OS/architecture. Node packaging is the next separate step;
this script does not sign, upload or publish a release.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.backend.bundle import stage_backend, write_json


def run(command, **kwargs):
    subprocess.run([str(value) for value in command], check=True, **kwargs)


def python_executable(home):
    return home / ("python.exe" if os.name == "nt" else "bin/python3.12")


def source_candidates():
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"]).decode().split("\0")
    # Development packages also include the new service boundary before its
    # first commit. Arbitrary untracked data and workspaces are never scanned.
    current = [str(path.relative_to(ROOT).as_posix()) for path in (ROOT / "desktop/backend").glob("*.py")]
    current.extend(["util/runtime_text.py", "util/wolf_workflow.py", "util/version_update/handoff.py", "util/rpgmaker_profiles.py", "util/translation_task.py", "util/config_integration.py", "util/model_catalog.py", "util/engine_options.py",
                    "data/tokenizers/9b5ad71b2ce5302211f9c61530b329a4922fc6a4", "data/tokenizers/README.md", "data/tokenizers/LICENSE.txt"])
    return [path for path in tracked + current if path]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=ROOT / "desktop/out/stage")
    parser.add_argument("--offline", action="store_true", help="Use only cached Python and wheels")
    args = parser.parse_args()
    stage = args.stage.expanduser().resolve()
    default_parent = (ROOT / "desktop/out").resolve()
    if not stage.is_relative_to(default_parent):
        parser.error("Keep disposable package staging inside desktop/out/.")
    stage.mkdir(parents=True, exist_ok=True)
    cache = ROOT / ".tmp-ui/desktop-build"
    config = json.loads((ROOT / "desktop/python-runtime.json").read_text())
    if importlib.metadata.version("uv") != config["uv"]:
        raise ValueError("Install desktop/requirements-build.txt to use the pinned runtime downloader.")
    uv = [sys.executable, "-m", "uv", "--cache-dir", str(cache / "uv-cache"), "--no-config"]
    if args.offline:
        uv.append("--offline")
    managed = cache / "pythons"
    run([*uv, "python", "install", f"cpython-{config['version']}", "--install-dir", managed, "--no-bin", "--no-registry"])
    homes = sorted(path for path in managed.glob(f"cpython-{config['version']}-*") if python_executable(path).is_file())
    if len(homes) != 1:
        raise ValueError("Expected exactly one managed Python for this build platform.")
    lock = ROOT / "desktop/requirements-runtime.lock"
    fingerprint = hashlib.sha256(lock.read_bytes() + (ROOT / "desktop/python-runtime.json").read_bytes()).hexdigest()
    bundled = stage / "python"
    stamp = bundled / ".desktop-build.json"
    old = json.loads(stamp.read_text()) if stamp.is_file() else {}
    if old.get("fingerprint") != fingerprint:
        if bundled.exists():
            shutil.rmtree(bundled)
        shutil.copytree(homes[0], bundled, symlinks=True)
        interpreter = python_executable(bundled)
        detected = json.loads(subprocess.check_output([str(interpreter), "-I", "-c", "import json,sys; print(json.dumps({'prefix':sys.prefix,'version':sys.version}))"]))
        if Path(detected["prefix"]).resolve() != bundled:
            raise ValueError("The staged Python did not resolve its own runtime prefix.")
        pip = [interpreter, "-I", "-m", "pip", "--isolated"]
        if not args.offline:
            run([*pip, "download", "--disable-pip-version-check", "--require-hashes", "--only-binary=:all:",
                 "--cache-dir", cache / "pip-cache", "--index-url", "https://pypi.org/simple", "--dest", cache / "wheels", "-r", lock])
        run([*pip, "install", "--disable-pip-version-check", "--no-compile", "--break-system-packages", "--require-hashes",
             "--only-binary=:all:", "--no-index", "--find-links", cache / "wheels", "-r", lock])
        write_json(stamp, {"fingerprint": fingerprint, "version": detected["version"]})
    if old.get("prefix"):
        write_json(stamp, {"fingerprint": fingerprint, "version": old["version"]})
    # Release directories may be read-only, so users cannot rely on Python
    # writing import caches on first launch. Build them with the exact bundled
    # interpreter. Hash invalidation survives archive extraction timestamps.
    bytecode_stamp = bundled / ".desktop-bytecode.json"
    bytecode_version = {"fingerprint": fingerprint, "format": 2}
    if not bytecode_stamp.is_file() or json.loads(bytecode_stamp.read_text()) != bytecode_version:
        run([python_executable(bundled), "-I", "-m", "compileall", "-q", "-f", "--invalidation-mode", "checked-hash",
             "-s", bundled, "-x", r"[/\\](?:test|tests|testdata)[/\\]", bundled / ("Lib" if os.name == "nt" else "lib")])
        write_json(bytecode_stamp, bytecode_version)
    backend = stage / "backend"
    if backend.exists():
        shutil.rmtree(backend)
    manifest = stage_backend(ROOT, backend, source_candidates())
    required = ["desktop/backend/server.py", "modules/rpgmakermvmz.py", "util/translation.py", "scripts/len_translation.py",
                "util/version_update/git_workflow.py", "util/translation_task.py", "util/engine_options.py", "util/config_integration.py", "data/skills/system.md", "data/skills/game-translation/SKILL.md",
                "data/glossary_base.txt", "data/translation_contexts.json", "data/sfx_reference/j_ono.json",
                "data/tokenizers/9b5ad71b2ce5302211f9c61530b329a4922fc6a4"]
    if any(name not in manifest["files"] for name in required):
        raise ValueError("The staged runtime is missing a required backend or shipped default.")
    write_json(stage / "runtime.json", {"version": 1, "python": "python/" + python_executable(Path()).as_posix(),
                                        "python_version": config["version"], "requirements_sha256": fingerprint,
                                        "backend_bundle": manifest["bundle_id"]})
    print(json.dumps({"stage": str(stage), "backend_files": len(manifest["files"]), "backend_bytes": sum(item["bytes"] for item in manifest["files"].values()),
                      "python": str(python_executable(bundled))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
