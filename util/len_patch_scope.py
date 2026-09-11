"""Stage an explicit Len patch and align its untranslated backup without checking out branches."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path, PurePosixPath

from util.len_git import git_status
from util.len_translation import LenProject, _write_atomic
from util.paths import normalize_game_tool_gitignore_text
from util.version_update import GitWorkflowError
from util.version_update.git_workflow import (
    _AssetManifestEntry, _asset_state_path, _commit_tree, _hash_file,
    _is_local_only_asset, _is_tool_owned_path, _load_asset_manifest,
    _load_asset_manifest_metadata, _message, _reject_original_checked_out_elsewhere,
    _run_git, _save_asset_manifest, _temporary_index, _tree_files,
)

_BEGIN = "# BEGIN DazedTL Len patch files"
_END = "# END DazedTL Len patch files"
_METADATA = {".gitignore", ".gitattributes", "README.md"}


def _path(value: str) -> str:
    if not isinstance(value, str) or not value or PurePosixPath(value).as_posix() != value:
        raise GitWorkflowError(f"Use an exact game-relative file path: {value!r}")
    parts = value.split("/")
    if (value.startswith("/") or any(p.casefold() in {".", "..", ".git", ".dazedtl", ".agents", ".codex"} for p in parts)
            or any(c in value for c in "\\\x00\r\n\t:")
            or any(p.casefold() in {"save", "saves", "logs", "cache", "__pycache__", "node_modules", ".venv", "venv"} for p in parts[:-1])
            or any(p == ".env" or p.startswith(".env.") for p in parts)
            or parts[-1] in {".api_key", "api_keys.json", "previous_patch_sha.txt"}
            or parts[-1].endswith(("_key.txt", "_keys.txt", ".log", ".tmp"))):
        raise GitWorkflowError(f"Local state or unsafe path cannot enter the patch: {value!r}")
    return value


def _file(root: Path, relative: str) -> Path:
    path = root
    for part in relative.split("/"):
        path = path / part
        if path.is_symlink():
            raise GitWorkflowError(f"Patch/source paths cannot traverse symlinks: {relative}")
    if not path.is_file():
        raise GitWorkflowError(f"Required file is missing: {path}")
    return path


def patch_manifest(document: object) -> dict[str, dict]:
    """Accept a complete file list or a release manifest with optional bound hashes."""
    raw = document.get("files") if isinstance(document, dict) else document
    if isinstance(raw, list):
        if not all(isinstance(p, str) for p in raw) or len(set(raw)) != len(raw):
            raise GitWorkflowError("Patch files must be unique path strings")
        raw = {p: {} for p in raw}
    if not isinstance(raw, dict):
        raise GitWorkflowError("Supply a file list or an object containing files")
    result = {}
    for relative, row in raw.items():
        _path(relative)
        if relative in _METADATA or not isinstance(row, dict):
            raise GitWorkflowError("List runtime patch files only; repository metadata is handled separately")
        for key in ("sha256", "original_sha256"):
            if key in row and not (key == "original_sha256" and row[key] is None):
                if not isinstance(row[key], str) or not re.fullmatch(r"[0-9a-f]{64}", row[key]):
                    raise GitWorkflowError(f"Invalid {key} for {relative}")
        result[relative] = row
    return result


def _escape(path: str) -> str:
    return "".join("\\" + c if c in "*?[]! " else c for c in path)


def scope_ignore(existing: str, paths: set[str]) -> str:
    """Place exact-path rules last, after shared managed settings and project rules."""
    if existing.count(_BEGIN) != existing.count(_END) or existing.count(_BEGIN) > 1:
        raise GitWorkflowError("The Len patch .gitignore block is incomplete or duplicated")
    if _BEGIN in existing:
        start, end = existing.index(_BEGIN), existing.index(_END)
        if end < start:
            raise GitWorkflowError("The Len patch .gitignore block is out of order")
        existing = existing[:start] + existing[end + len(_END):]
    existing = normalize_game_tool_gitignore_text(existing).rstrip()
    directories = {p[:i] for p in paths for i, c in enumerate(p) if c == "/"}
    lines = [_BEGIN, "# Only reviewed runtime patch files and repository metadata belong in Git.", "/*"]
    for directory in sorted(directories, key=lambda p: (p.count("/"), p)):
        lines.extend(["!/" + _escape(directory) + "/", "/" + _escape(directory) + "/*"])
    lines.extend("!/" + _escape(p) for p in sorted(paths))
    lines.append(_END)
    return existing + "\n\n" + "\n".join(lines) + "\n"


def _blob_metadata(repo: Path, objects: set[str]) -> dict[str, tuple[str, int]]:
    """Stream a single cat-file batch, including large native assets."""
    result = {}
    if not objects:
        return result
    with tempfile.TemporaryFile() as requests:
        requests.write(("\n".join(sorted(objects)) + "\n").encode("ascii"))
        requests.seek(0)
        with subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                              stdin=requests, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as process:
            for _ in objects:
                header = process.stdout.readline().decode("ascii").split()
                if len(header) != 3 or header[1] != "blob":
                    raise GitWorkflowError("Cannot read original source blob")
                oid, _, length = header
                size = remaining = int(length)
                digest = hashlib.sha256()
                while remaining:
                    data = process.stdout.read(min(remaining, 1024 * 1024))
                    if not data:
                        raise GitWorkflowError("Incomplete original source blob")
                    digest.update(data)
                    remaining -= len(data)
                if process.stdout.read(1) != b"\n":
                    raise GitWorkflowError("Invalid original source blob boundary")
                result[oid] = (digest.hexdigest(), size)
            if process.wait() != 0:
                raise GitWorkflowError("Cannot inspect original source objects")
    return result


def _hash_paths(repo: Path, files: dict[str, Path], *, write: bool) -> dict[str, tuple[str, str]]:
    if not files:
        return {}
    args = ["hash-object", "--no-filters", "--stdin-paths"]
    if write:
        args.append("-w")
    # Git's stdin-paths accepts C-quoted names, including spaces and quote marks.
    hashes = _run_git(repo, *args, input_text="".join(json.dumps(str(p), ensure_ascii=False) + "\n" for p in files.values()), timeout=600).stdout.splitlines()
    if len(hashes) != len(files):
        raise GitWorkflowError("Git did not hash every selected file")
    return {name: ("100755" if path.stat().st_mode & 0o111 else "100644", oid)
            for (name, path), oid in zip(files.items(), hashes)}


def _tree(repo: Path, entries: dict[str, tuple[str, str]], index: dict[str, str]) -> str:
    _run_git(repo, "read-tree", "--empty", env=index)
    if entries:
        _run_git(repo, "update-index", "-z", "--index-info", env=index,
                 input_text="".join(f"{mode} {oid}\t{name}\0" for name, (mode, oid) in sorted(entries.items())))
    return _run_git(repo, "write-tree", env=index).stdout.strip()


def sync_patch_scope(project: LenProject, document: object, *, original_game: Path | None = None,
                     dry_run: bool = False) -> dict:
    """Stage only reviewed files; append an original scope commit, retaining all local files.

    A list is the COMPLETE patch, not just this batch's changes. Hash-bound release
    manifests also verify that the reviewed English bytes are in the actual game root.
    """
    selected = patch_manifest(document)
    state = git_status(project)
    repo = project.game_root
    if state["repo_root"] != str(repo) or not state["configured"]:
        raise GitWorkflowError("Run Len git-setup in this game repository first")
    if state["current_branch"] != state["translation_branch"] or state["current_branch"] == "original":
        raise GitWorkflowError("Check out the registered translation branch before synchronizing patch files")
    if state["pending_operations"] or state["asset_sync_pending"]:
        raise GitWorkflowError("Finish the pending Git or version update first")
    if not state["preserve_game_files"]:
        raise GitWorkflowError("Patch scoping requires a native-byte Len repository")
    _reject_original_checked_out_elsewhere(repo)
    if _run_git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise GitWorkflowError("Review and commit existing staged changes first; patch scoping will not overwrite them")
    if not state["original_version"]:
        raise GitWorkflowError("Record the original release version with git-setup first")
    original_ref = state["original_commit"]
    head = state["translation_commit"]
    originals = _tree_files(repo, original_ref, "")
    assets = _load_asset_manifest(repo, "")
    asset_metadata = _load_asset_manifest_metadata(repo, "")
    metadata = {p for p in _METADATA if (repo / p).exists()} | {".gitignore"}
    files = {p: _file(repo, p) for p in selected}
    files.update({p: _file(repo, p) for p in metadata if p != ".gitignore"})
    ignore = repo / ".gitignore"
    if ignore.exists() or ignore.is_symlink():
        _file(repo, ".gitignore")
    before_ignore = ignore.read_bytes() if ignore.exists() else None
    policy = scope_ignore((before_ignore or b"").decode("utf-8", errors="surrogateescape"), set(selected) | metadata)
    source = original_game.expanduser().resolve() if original_game is not None else None
    if source is not None and (source == repo or not source.is_dir()):
        raise GitWorkflowError("Use a separate, matching untranslated backup as --original")
    # Existing Git originals are authoritative; a supplied backup must match them.
    original_files = {}
    for relative, row in selected.items():
        if "sha256" in row and _hash_file(files[relative]) != row["sha256"]:
            raise GitWorkflowError(f"Reviewed patch bytes are not installed in the game root: {relative}")
        if source is not None and ((source / relative).exists() or (source / relative).is_symlink()):
            original_files[relative] = _file(source, relative)
        elif relative not in originals and not ("original_sha256" in row and row["original_sha256"] is None):
            raise GitWorkflowError(f"Supply the matching --original backup, or declare a translation-only addition with original_sha256: null: {relative}")
    source_entries = _hash_paths(repo, original_files, write=not dry_run)
    payload_entries = _hash_paths(repo, files, write=not dry_run)
    for name, entry in source_entries.items():
        if name in originals and originals[name] != entry:
            raise GitWorkflowError(f"The supplied original differs from the registered release: {name}")
    if any(originals[p][0] not in {"100644", "100755"} for p in selected if p in originals):
        raise GitWorkflowError("Original patch files must be regular files")
    original_payload = {p: originals[p] if p in originals else source_entries[p]
                        for p in selected if p in originals or p in source_entries}
    digests = _blob_metadata(repo, {v[1] for k, v in originals.items()
                                  if k in selected or (k not in metadata and not _is_tool_owned_path(k) and not _is_local_only_asset(k))})
    for name, row in selected.items():
        old = original_payload.get(name)
        source_digest = (_hash_file(original_files[name]) if name in original_files
                         else digests[old[1]][0] if old else None)
        if "original_sha256" in row and source_digest != row["original_sha256"]:
            raise GitWorkflowError(f"Original source hash disagrees with the reviewed manifest: {name}")
        if name not in originals and assets is not None and name in assets and source_digest != assets[name].sha256:
            raise GitWorkflowError(f"Original source disagrees with the registered ignored-asset backup: {name}")
    old_tracked = set(_tree_files(repo, head, ""))
    result = {"dry_run": dry_run, "translation_branch": state["translation_branch"],
              "patch_files": len(selected), "original_files": len(original_payload),
              "translation_only_files": sorted(set(selected) - set(original_payload)),
              "untrack": sorted(old_tracked - set(selected) - metadata),
              "original_commit": original_ref, "main_committed": False,
              "local_files_deleted": False}
    if dry_run:
        return result
    # Keep the official updater's ignored-asset inventory aligned when paths leave Git.
    if assets is not None:
        assets = {p: row for p, row in assets.items() if p not in selected}
        for name, (mode, oid) in originals.items():
            if name not in selected and name not in metadata and not _is_tool_owned_path(name) and not _is_local_only_asset(name):
                digest, size = digests[oid]
                assets[name] = _AssetManifestEntry(digest, size, mode)
    index_name, index_env = _temporary_index()
    original_index, original_env = _temporary_index()
    index_path = Path(_run_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "index").stdout.strip())
    lock = index_path.with_name(index_path.name + ".lock")
    asset_path = _asset_state_path(repo, "", "official-assets")
    before_assets = asset_path.read_bytes() if asset_path.exists() else None
    new_original = original_ref
    acquired = False
    applied_ignore = False
    moved_original = False
    try:
        ignore_oid = _run_git(repo, "hash-object", "-w", "--no-filters", "--stdin", input_text=policy).stdout.strip()
        payload_entries[".gitignore"] = ("100644", ignore_oid)
        original_payload.update({p: payload_entries[p] for p in metadata})
        main_tree = _tree(repo, payload_entries, index_env)
        source_tree = _tree(repo, original_payload, original_env)
        if source_tree != _run_git(repo, "rev-parse", f"{original_ref}^{{tree}}").stdout.strip():
            new_original = _commit_tree(repo, source_tree, _message("original: align patch file scope", state["original_version"]), (original_ref,))
        with lock.open("xb") as handle:
            acquired = True
            handle.write(Path(index_name).read_bytes())
        if (_run_git(repo, "rev-parse", "HEAD").stdout.strip() != head
                or _run_git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip() != state["current_branch"]
                or (asset_path.read_bytes() if asset_path.exists() else None) != before_assets
                or _run_git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0
                or (ignore.read_bytes() if ignore.exists() else None) != before_ignore
                or _hash_paths(repo, files, write=False) != {p: v for p, v in payload_entries.items() if p != ".gitignore"}
                or _hash_paths(repo, original_files, write=False) != source_entries):
            raise GitWorkflowError("The game, source, index or branch changed during patch review; retry after reviewing those changes")
        _write_atomic(ignore, policy)
        applied_ignore = True
        checks = old_tracked | set(payload_entries)
        ignored = _run_git(repo, "check-ignore", "--no-index", "-z", "--stdin", check=False,
                           input_text="\0".join(sorted(checks)) + "\0")
        if ignored.returncode not in {0, 1}:
            raise GitWorkflowError("Cannot verify the patch ignore rules")
        hidden = set(ignored.stdout.split("\0")) - {""}
        visible_new = set(_run_git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")) - {""}
        if (checks - hidden) != set(payload_entries) or visible_new - set(payload_entries):
            raise GitWorkflowError("Nested or global ignore rules conflict with the exact patch file list; review those rules first")
        _run_git(repo, "update-ref", "refs/heads/original", new_original, original_ref)
        moved_original = new_original != original_ref
        if assets is not None:
            _save_asset_manifest(repo, "", state["original_version"], new_original, assets,
                                 baseline_source_kind=asset_metadata.get("baseline_source_kind", "bootstrap"),
                                 has_unbased_tracked_assets=bool(asset_metadata.get("has_unbased_tracked_assets", False)))
        lock.replace(index_path)
        acquired = False
        result.update({"original_commit": new_original, "staged_tree": main_tree})
        return result
    except Exception:
        if moved_original:
            _run_git(repo, "update-ref", "refs/heads/original", original_ref, new_original)
        if applied_ignore:
            if before_ignore is None:
                ignore.unlink()
            else:
                _write_atomic(ignore, before_ignore.decode("utf-8", errors="surrogateescape"))
            if before_assets is None:
                asset_path.unlink(missing_ok=True)
            else:
                asset_path.write_bytes(before_assets)
        raise
    finally:
        if acquired:
            lock.unlink(missing_ok=True)
        Path(index_name).unlink(missing_ok=True)
        Path(original_index).unlink(missing_ok=True)
