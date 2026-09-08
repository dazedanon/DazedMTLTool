"""Developer-only regression checks; the shipped installer does not need Python."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parent
GAME = ROOT.parents[1]
RUN = ROOT / ("selftest-run-" + str(os.getpid()))
FIXTURE = RUN / "game"
PACKAGE = RUN / "package"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def metadata(data):
    return {"algorithm": "SHA256", "hash": digest(data), "blockSize": 4,
            "blocks": [digest(data[i:i + 4]) for i in range(0, len(data), 4)] or [digest(b"")],
            "custom": "integrity metadata retained"}


def write_asar(target, files):
    # Source offsets deliberately differ from header traversal order.
    header = {"files": {}, "custom": "root metadata retained"}
    chunks = list(reversed(list(files.items())))
    offsets = {}
    offset = 0
    for rel, data in chunks:
        offsets[rel] = offset
        offset += len(data)
    for rel, data in files.items():
        header["files"][rel] = {"size": len(data), "offset": str(offsets[rel]),
                                "integrity": metadata(data), "executable": False}
    blob = json.dumps(header, separators=(",", ":")).encode()
    padded = blob + b"\0" * (-len(blob) % 4)
    target.write_bytes(struct.pack("<IIII", 4, 8 + len(padded), 4 + len(padded), len(blob))
                       + padded + b"".join(data for _, data in chunks))
    return header


def read_asar(target):
    data = target.read_bytes()
    size_pickle, header_size, pickle_payload, json_size = struct.unpack_from("<IIII", data)
    assert size_pickle == 4 and pickle_payload == header_size - 4
    header = json.loads(data[16:16 + json_size])
    files = {rel: data[8 + header_size + int(entry["offset"]):
                       8 + header_size + int(entry["offset"]) + entry["size"]]
             for rel, entry in header["files"].items()}
    return header, files


def invoke(mode, *, output=None, success=True):
    command = [str(GAME / "musi_dream.exe"), str(ROOT / "patch.cjs"),
               "--mode", mode, "--game-root", str(FIXTURE), "--package-root", str(PACKAGE)]
    if output is not None:
        command += ["--output", str(output)]
    env = dict(os.environ, ELECTRON_RUN_AS_NODE="1")
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=60,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if (result.returncode == 0) != success:
        raise AssertionError(f"{mode} returned {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def main():
    (FIXTURE / "resources").mkdir(parents=True)
    (PACKAGE / "payload").mkdir(parents=True)
    # The real bundled runtime executes patch.cjs; the fixture pathname is used
    # solely to ensure the game-root/executable identity and process guard work.
    for name in ("musi_dream.exe", "icudtl.dat", "snapshot_blob.bin", "v8_context_snapshot.bin"):
        os.link(GAME / name, FIXTURE / name)
    archive = FIXTURE / "resources/app.asar"
    source_files = {"first.txt": b"Original first file", "change.txt": b"short", "third.txt": b"Untouched third file"}
    source_header = write_asar(archive, source_files)
    original_bytes = archive.read_bytes()
    replacement = b"A longer replacement, crossing several integrity blocks."
    (PACKAGE / "payload/change.txt").write_bytes(replacement)
    manifest = {"format_version": 1, "game_executable": "musi_dream.exe",
                "original_sha256": digest(original_bytes), "files": {"change.txt": digest(replacement)}}
    manifest_path = PACKAGE / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    checks = []

    output = FIXTURE / "candidate.asar"
    invoke("build", output=output)
    assert archive.read_bytes() == original_bytes
    rebuilt_header, rebuilt_files = read_asar(output)
    assert rebuilt_files == dict(source_files, **{"change.txt": replacement})
    assert rebuilt_header["custom"] == source_header["custom"]
    for rel, entry in rebuilt_header["files"].items():
        assert entry["integrity"] == metadata(rebuilt_files[rel])
        assert entry["executable"] is False
    checks.append("Build preserves original and untouched bytes, reversed source offsets, metadata, and block hashes")

    before = output.read_bytes()
    invoke("build", output=output, success=False)
    assert output.read_bytes() == before
    checks.append("Existing output is rejected without modification")

    manifest["files"]["../escape.txt"] = digest(replacement)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    invoke("build", output=FIXTURE / "unsafe.asar", success=False)
    assert not (FIXTURE / "unsafe.asar").exists()
    del manifest["files"]["../escape.txt"]
    manifest["patched_sha256"] = digest(output.read_bytes())
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    checks.append("Manifest traversal is rejected before output creation")

    (PACKAGE / "payload/change.txt").write_bytes(b"Tampered payload")
    invoke("install", success=False)
    assert archive.read_bytes() == original_bytes
    (PACKAGE / "payload/change.txt").write_bytes(replacement)
    checks.append("Tampered payload is rejected before archive mutation")

    running = subprocess.Popen([str(FIXTURE / "musi_dream.exe"), "-e", "setTimeout(() => {}, 30000)"],
                               env=dict(os.environ, ELECTRON_RUN_AS_NODE="1"),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        time.sleep(0.25)
        assert running.poll() is None
        result = invoke("install", success=False)
        assert "is running" in result.stderr
        assert archive.read_bytes() == original_bytes
    finally:
        running.terminate()
        running.wait(timeout=10)
    checks.append("A running executable at the target game path blocks installation")

    invoke("install")
    backup = FIXTURE / "resources/app.asar.original"
    assert backup.read_bytes() == original_bytes and archive.read_bytes() == output.read_bytes()
    invoke("install")
    assert backup.read_bytes() == original_bytes and archive.read_bytes() == output.read_bytes()
    checks.append("Install retains exact backup; repeated install is idempotent")

    installed = archive.read_bytes()
    archive.write_bytes(installed[:-1] + bytes([installed[-1] ^ 1]))
    changed = archive.read_bytes()
    invoke("restore", success=False)
    assert archive.read_bytes() == changed and backup.read_bytes() == original_bytes
    archive.write_bytes(installed)
    checks.append("Restore refuses an independently modified installed archive")

    invoke("restore")
    assert archive.read_bytes() == original_bytes and backup.read_bytes() == original_bytes
    invoke("restore")
    assert archive.read_bytes() == original_bytes
    checks.append("Restore is byte-identical and idempotent, preserving backup")

    wrapper = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                              str(ROOT / "selftest-wrapper.ps1"), "-FixtureRoot", str(RUN)],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=60, creationflags=subprocess.CREATE_NO_WINDOW)
    assert wrapper.returncode == 0, wrapper.stdout + wrapper.stderr
    assert "WRAPPER_SUCCESS_FAILURE_AND_ENV_RESTORATION_PASSED" in wrapper.stdout
    checks.append("PowerShell wrapper waits for GUI runtime, reports native failure, and restores environment in both cases")

    (RUN / "report.json").write_text(json.dumps({"passed": len(checks), "checks": checks}, indent=2), encoding="utf-8")
    print(json.dumps({"passed": len(checks), "checks": checks, "artifacts": str(RUN)}, indent=2))


if __name__ == "__main__":
    main()
