"""Stage shipped runtime files and install them without copying local user data.

This module uses only the standard library so the bundled Python can run it
before a writable per-user environment exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
import venv
from pathlib import Path, PurePosixPath

TOP_LEVEL = {"util", "modules", "scripts", "data", "assets", "gameupdate"}
ROOT_FILES = {"LICENSE.md", "README.md", ".env.example", "requirements.txt"}
PRIVATE_FILES = {"api_keys.json", "vocab.txt", "last_update_sha.txt", "wolf_safe_notes.json", "wolf_speakers.json"}
MARKER = ".desktop-managed.json"
NATIVE_EXECUTABLES = {"util/wolfdawn/bin/linux/wolf", "util/wolfdawn/bin/macos/wolf"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def relative_path(value):
    if not isinstance(value, str) or "\\" in value or "\0" in value or ":" in value:
        raise ValueError("Invalid packaged file path.")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Packaged paths must stay inside their runtime directory.")
    return Path(*path.parts)


def shippable(value):
    path = relative_path(value)
    if value in ROOT_FILES or value in {'desktop/bootstrap.py', 'desktop/source_updates.py'}:
        return True
    if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__", ".dazedtl"} for part in path.parts):
        return False
    if path.name.startswith(".env") or path.name in {".api_key", "api_keys.json"} or path.suffix in {".pyc", ".pyo"}:
        return False
    if path.parts[:2] == ("desktop", "backend"):
        return path.suffix == ".py"
    if path.parts[0] not in TOP_LEVEL:
        return False
    if path.parts[0] == "data":
        return path.name not in PRIVATE_FILES and (
            len(path.parts) > 2 and path.parts[1] in {"skills", "help", "sfx_reference", "tokenizers"}
            or value in {"data/glossary_base.txt", "data/translation_contexts.json"}
        )
    return True


def regular_path(root, relative):
    path = root / relative_path(relative)
    for candidate in (path, *path.parents):
        if candidate == root.parent:
            break
        if candidate.is_symlink():
            raise ValueError(f"Runtime files must not use symbolic links: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("A runtime path left its destination.")
    return path


def write_atomic(path, raw, mode=0o644):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".desktop-tmp")
    if temporary.is_symlink():
        raise ValueError("A runtime temporary file was replaced by a symbolic link.")
    try:
        temporary.write_bytes(raw)
        temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path, value):
    write_atomic(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def stage_backend(source, destination, candidates):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or source.is_relative_to(destination):
        raise ValueError("Stage the package in a separate build directory.")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Use an empty runtime staging directory.")
    files = {}
    for name in sorted(set(candidates)):
        if not shippable(name):
            continue
        original = regular_path(source, name)
        if not original.is_file():
            raise ValueError(f"A selected runtime file is missing: {name}")
        raw, mode = original.read_bytes(), original.stat().st_mode & 0o777
        # A ZIP checkout or a repository with core.filemode=false may have
        # lost the executable bit. Set it before recording the package mode;
        # a read-only application cannot repair its shipped helpers later.
        if os.name != "nt" and name in NATIVE_EXECUTABLES:
            mode = 0o755
        write_atomic(regular_path(destination, name), raw, mode)
        files[name] = {"sha256": digest(raw), "mode": mode, "bytes": len(raw)}
    bundle_id = digest(json.dumps(files, sort_keys=True).encode())
    manifest = {"version": 1, "bundle_id": bundle_id, "files": files}
    write_json(destination / "runtime-manifest.json", manifest)
    return manifest


def read_manifest(source):
    manifest = json.loads((source / "runtime-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("version") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported desktop runtime manifest.")
    if digest(json.dumps(manifest["files"], sort_keys=True).encode()) != manifest.get("bundle_id"):
        raise ValueError("The desktop runtime manifest is damaged.")
    for name, details in manifest["files"].items():
        if not shippable(name) or not isinstance(details, dict) or len(details.get("sha256", "")) != 64:
            raise ValueError("The package contains an unsupported or private runtime path.")
    return manifest


def file_digest(path):
    return digest(path.read_bytes()) if path.is_file() else None


def recover_install(target, transactions):
    for journal_path in sorted(transactions.glob("*/journal.json")):
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        if journal["status"] != "pending":
            continue
        marker = target / MARKER
        current = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {}
        if current.get("bundle_id") == journal["bundle_id"]:
            journal["status"] = "complete"
            write_json(journal_path, journal)
            continue
        operations = []
        log = journal_path.with_name("operations.jsonl")
        if log.exists():
            for line in log.read_bytes().splitlines(keepends=True):
                # A process killed while appending has not executed that last
                # operation yet. Earlier complete records still roll back.
                if not line.endswith(b"\n"):
                    break
                operations.append(json.loads(line))
        for operation in reversed(operations):
            if not shippable(operation["path"]):
                raise ValueError("Runtime recovery cannot replace private files.")
            destination = regular_path(target, operation["path"])
            actual = file_digest(destination)
            if actual == operation["before"]:
                continue
            if actual != operation["after"]:
                raise ValueError("A file changed during runtime recovery. Preserve your edits and inspect the runtime backup before retrying.")
            if operation["before"] is None:
                destination.unlink(missing_ok=True)
            else:
                backup = regular_path(journal_path.parent / "files", operation["path"])
                if file_digest(backup) != operation["before"]:
                    raise ValueError("The runtime recovery backup changed.")
                write_atomic(destination, backup.read_bytes(), operation["mode"])
        journal["status"] = "rolled_back"
        write_json(journal_path, journal)


def install_backend(source, target):
    if Path(target).is_symlink() or (Path(target).parent / "runtime-backups").is_symlink():
        raise ValueError("Runtime directories must not be symbolic links.")
    source, target = Path(source).resolve(), Path(target).resolve()
    if source == target or source.is_relative_to(target) or target.is_relative_to(source):
        raise ValueError("Install the managed runtime outside the application bundle.")
    target.mkdir(parents=True, exist_ok=True)
    transactions = target.parent / "runtime-backups"
    recover_install(target, transactions)
    manifest = read_manifest(source)
    marker = target / MARKER
    if marker.is_symlink():
        raise ValueError("Runtime metadata must be a regular file.")
    previous = json.loads(marker.read_text(encoding="utf-8")) if marker.exists() else {"files": {}}
    if previous.get("bundle_id") == manifest["bundle_id"]:
        return {"changed": 0, "backup": None}
    transaction = transactions / uuid.uuid4().hex
    journal = {"status": "pending", "bundle_id": manifest["bundle_id"]}
    operations = []
    preserved = []
    try:
        for name in sorted(set(manifest["files"]) | set(previous["files"])):
            if not shippable(name):
                raise ValueError("Existing runtime metadata contains an unsupported path.")
            path = regular_path(target, name)
            old_hash = file_digest(path)
            expected = manifest["files"].get(name)
            new_hash = expected["sha256"] if expected else None
            if old_hash == new_hash:
                continue
            prior_hash = previous["files"].get(name, {}).get("sha256")
            # Keep local customizations when the shipped file is unchanged or
            # removed. Updated defaults retain a recoverable copy before replace.
            if old_hash is not None and old_hash != prior_hash and (new_hash == prior_hash or new_hash is None):
                preserved.append(name)
                continue
            raw = None
            if expected:
                original = regular_path(source, name)
                raw = original.read_bytes()
                if digest(raw) != new_hash:
                    raise ValueError(f"A bundled runtime file changed: {name}")
            mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
            if old_hash is not None:
                write_atomic(regular_path(transaction / "files", name), path.read_bytes(), mode)
            operation = {"path": name, "before": old_hash, "after": new_hash, "mode": mode}
            if not operations:
                write_json(transaction / "journal.json", journal)
            with (transaction / "operations.jsonl").open("ab") as log:
                log.write(json.dumps(operation, ensure_ascii=False).encode() + b"\n")
            operations.append(operation)
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                write_atomic(path, raw, expected["mode"])
        write_json(marker, {**manifest, "preserved_customizations": preserved})
        journal["status"] = "complete"
        write_json(transaction / "journal.json", journal)
    except BaseException:
        recover_install(target, transactions)
        raise
    return {"changed": len(operations), "backup": str(transaction) if any(item["before"] for item in operations) else None}


def prepare_environment(base, destination):
    if Path(destination).is_symlink():
        raise ValueError("The Python environment must not be a symbolic link.")
    base, destination = Path(base).resolve(), Path(destination).resolve()
    if destination.is_symlink() or base == destination or base.is_relative_to(destination) or destination.is_relative_to(base):
        raise ValueError("Create the writable Python environment outside the bundled runtime.")
    stamp = destination / ".desktop-python.json"
    expected = {"base": str(base), "version": sys.version, "executable": sys.executable}
    executable = destination / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if stamp.is_file() and json.loads(stamp.read_text()) == expected and executable.is_file():
        return executable
    destination.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        for name in ("python", "python3", f"python3.{sys.version_info.minor}"):
            launcher = destination / "bin" / name
            if launcher.is_symlink():
                launcher.unlink()
    # Recreating the venv launchers rebinds a moved package while retaining any
    # optional dependencies installed into this per-user environment.
    venv.EnvBuilder(system_site_packages=True, with_pip=False, symlinks=os.name != "nt").create(destination)
    write_json(stamp, expected)
    return executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    args = parser.parse_args()
    profile = args.profile.expanduser().resolve()
    report = install_backend(args.source, profile / "tool")
    python = prepare_environment(Path(sys.prefix), profile / "python-env")
    print(json.dumps({"root": str(profile / "tool"), "python": str(python), "workspace": str(profile / "workspace"), **report}))


if __name__ == "__main__":
    main()
