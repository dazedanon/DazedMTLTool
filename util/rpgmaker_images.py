"""RPG Maker MV/MZ image encryption and patch-selection helpers.

RPG Maker encrypts only the first 16 bytes of an asset, prefixes a fixed
16-byte header, and changes the file extension.  This module intentionally
handles images only; audio assets use the same container but are outside the
image-translation workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable
import io
import json
import os
import re
import shutil
import tempfile

from util.image_manager import ImageActionResult, ImageAsset


RPGMV_HEADER = bytes(
    [0x52, 0x50, 0x47, 0x4D, 0x56, 0x00, 0x00, 0x00,
     0x00, 0x03, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00]
)
KEY_LEN = 16
ENCRYPTED_IMAGE_EXTENSIONS = (".rpgmvp", ".png_")
EDITABLE_WORKSPACE_NAME = "images"
LEGACY_EDITABLE_WORKSPACE_NAME = "DazedTL_Images"


def resolve_content_root(game_root: str | Path) -> Path:
    """Return the directory containing ``data/`` and ``img/``."""

    root = Path(game_root).expanduser().resolve()
    for candidate in (root / "www", root):
        if (candidate / "img").is_dir():
            return candidate
    raise FileNotFoundError(
        f"Could not find an img folder under {root} or {root / 'www'}."
    )


def read_encryption_key(game_root: str | Path) -> bytes:
    """Read and validate the 16-byte encryption key from System.json."""

    content_root = resolve_content_root(game_root)
    system_path = content_root / "data" / "System.json"
    if not system_path.is_file():
        raise FileNotFoundError(f"System.json not found: {system_path}")
    text = system_path.read_text(encoding="utf-8-sig", errors="replace")
    try:
        raw_key = json.loads(text).get("encryptionKey", "")
    except json.JSONDecodeError:
        match = re.search(r'"encryptionKey"\s*:\s*"([a-fA-F0-9]{32})"', text)
        raw_key = match.group(1) if match else ""
    normalized = str(raw_key).strip().replace(" ", "")
    if not re.fullmatch(r"[a-fA-F0-9]{32}", normalized):
        raise ValueError(
            "System.json does not contain a valid 32-character encryptionKey."
        )
    return bytes.fromhex(normalized)


def editable_workspace_root(game_root: str | Path) -> Path:
    """Return the DazedTL working folder used for editable image copies."""

    return (
        Path(game_root).expanduser().resolve()
        / ".dazedtl"
        / EDITABLE_WORKSPACE_NAME
    )


def _logical_png(path: Path) -> Path:
    lower = path.name.casefold()
    if lower.endswith(".rpgmvp"):
        return path.with_name(path.name[:-7] + ".png")
    if lower.endswith(".png_"):
        return path.with_name(path.name[:-5] + ".png")
    return path


def scan_image_assets(game_root: str | Path) -> list[ImageAsset]:
    """Scan runtime and editable image trees and combine matching files."""

    root = Path(game_root).expanduser().resolve()
    content_root = resolve_content_root(root)
    image_root = content_root / "img"
    workspace_root = editable_workspace_root(root)
    workspace_content_root = workspace_root / content_root.relative_to(root)
    by_id: dict[str, dict[str, Path]] = {}
    for path in image_root.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.casefold()
        if not (name.endswith(".png") or name.endswith(ENCRYPTED_IMAGE_EXTENSIONS)):
            continue
        logical = _logical_png(path)
        relative = logical.relative_to(content_root)
        asset_id = relative.as_posix()
        entry = by_id.setdefault(
            asset_id,
            {
                "relative": relative,
                "workspace_relative": logical.relative_to(root),
            },
        )
        if name.endswith(ENCRYPTED_IMAGE_EXTENSIONS):
            entry["encrypted"] = path
        else:
            entry["runtime_plain"] = path

    editable_image_root = workspace_content_root / "img"
    if editable_image_root.is_dir():
        for path in editable_image_root.rglob("*"):
            if not path.is_file() or path.suffix.casefold() != ".png":
                continue
            relative = path.relative_to(workspace_content_root)
            asset_id = relative.as_posix()
            entry = by_id.setdefault(
                asset_id,
                {
                    "relative": relative,
                    "workspace_relative": path.relative_to(workspace_root),
                },
            )
            entry["plain"] = path

    assets = [
        ImageAsset(
            asset_id=asset_id,
            relative_png=entry["relative"],
            plain_path=entry.get(
                "plain", workspace_root / entry["workspace_relative"]
            ),
            encrypted_path=entry.get("encrypted"),
            runtime_plain_path=entry.get("runtime_plain"),
        )
        for asset_id, entry in by_id.items()
    ]
    return sorted(assets, key=lambda asset: asset.asset_id.casefold())


def decrypt_image_bytes(data: bytes, key: bytes) -> bytes:
    if len(key) != KEY_LEN:
        raise ValueError("The RPG Maker encryption key must contain 16 bytes.")
    if len(data) < len(RPGMV_HEADER) + KEY_LEN:
        raise ValueError("Encrypted image is too small.")
    if data[: len(RPGMV_HEADER)] != RPGMV_HEADER:
        raise ValueError("Encrypted image has an invalid RPG Maker header.")
    start = len(RPGMV_HEADER)
    block = bytes(value ^ key[index] for index, value in enumerate(data[start:start + KEY_LEN]))
    return block + data[start + KEY_LEN:]


def encrypt_image_bytes(data: bytes, key: bytes) -> bytes:
    if len(key) != KEY_LEN:
        raise ValueError("The RPG Maker encryption key must contain 16 bytes.")
    if len(data) < KEY_LEN:
        raise ValueError("PNG image is too small.")
    block = bytes(value ^ key[index] for index, value in enumerate(data[:KEY_LEN]))
    return RPGMV_HEADER + block + data[KEY_LEN:]


def preview_png_bytes(asset: ImageAsset, key: bytes | None) -> bytes:
    """Return displayable PNG bytes, decrypting in memory when necessary."""

    if asset.has_plain:
        return asset.plain_path.read_bytes()
    if asset.has_runtime_plain:
        return asset.runtime_plain_path.read_bytes()
    if not asset.has_encrypted:
        raise FileNotFoundError(asset.runtime_plain_path or asset.plain_path)
    if key is None:
        raise ValueError("The encryption key is required to preview this image.")
    return decrypt_image_bytes(asset.encrypted_path.read_bytes(), key)


def thumbnail_png_bytes(asset: ImageAsset, key: bytes | None, size: int = 128) -> bytes:
    """Create a small PNG thumbnail without writing a decrypted working file."""

    from PIL import Image

    raw = preview_png_bytes(asset, key)
    with Image.open(io.BytesIO(raw)) as image:
        image.thumbnail((size, size))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        output = io.BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="wb", prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            handle.write(data)
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _ensure_image_manager_ignores(game_root: str | Path) -> None:
    root = Path(game_root).expanduser().resolve()
    ignore_path = root / ".gitignore"
    existing = (
        ignore_path.read_text(encoding="utf-8", errors="surrogateescape")
        if ignore_path.exists()
        else ""
    )
    rules = ("/.dazedtl/",)
    additions = [rule for rule in rules if rule not in existing.splitlines()]
    if additions:
        text = existing
        if text and not text.endswith("\n"):
            text += "\n"
        if "# DazedTL image manager working files" not in text:
            text += "\n# DazedTL image manager working files\n"
        text += "\n".join(additions) + "\n"
        _atomic_write(ignore_path, text.encode("utf-8", errors="surrogateescape"))


def ensure_editable_workspace(game_root: str | Path) -> Path:
    """Create the editable folder and keep working files out of patches."""

    root = Path(game_root).expanduser().resolve()
    workspace = editable_workspace_root(root)
    workspace.mkdir(parents=True, exist_ok=True)
    migrate_legacy_editable_workspace(root)
    _ensure_image_manager_ignores(root)
    return workspace


def migrate_legacy_editable_workspace(game_root: str | Path) -> int:
    """Move editable PNGs from the former top-level workspace into .dazedtl."""

    root = Path(game_root).expanduser().resolve()
    legacy = root / LEGACY_EDITABLE_WORKSPACE_NAME
    if not legacy.is_dir():
        return 0
    destination_root = editable_workspace_root(root)
    conflict_root = root / ".dazedtl" / "legacy_image_conflicts"
    moved = 0
    for source in sorted(path for path in legacy.rglob("*") if path.is_file()):
        relative = source.relative_to(legacy)
        destination = destination_root / relative
        if destination.exists():
            destination = conflict_root / relative
            counter = 2
            while destination.exists():
                destination = conflict_root / relative.with_name(
                    f"{relative.stem}_{counter}{relative.suffix}"
                )
                counter += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        moved += 1

    directories = sorted(
        (path for path in legacy.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        legacy.rmdir()
    except OSError:
        pass
    _ensure_image_manager_ignores(root)
    return moved


def clean_runtime_image_duplicates(game_root: str | Path) -> int:
    """Move PNGs that duplicate encrypted assets out of the runtime image tree."""

    root = Path(game_root).expanduser().resolve()
    cleaned = 0
    for asset in scan_image_assets(root):
        if not (asset.has_encrypted and asset.has_runtime_plain):
            continue
        source = asset.runtime_plain_path
        destination = asset.plain_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.move(str(source), str(destination))
        elif source.read_bytes() == destination.read_bytes():
            source.unlink()
        else:
            relative = source.relative_to(root)
            conflict_root = root / ".dazedtl" / "runtime_plain_conflicts"
            conflict = conflict_root / relative
            counter = 2
            while conflict.exists():
                conflict = (conflict_root / relative).with_name(
                    f"{relative.stem}_{counter}{relative.suffix}"
                )
                counter += 1
            conflict.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(conflict))
        cleaned += 1
    if cleaned:
        _ensure_image_manager_ignores(root)
    return cleaned


def decrypt_assets(
    assets: Iterable[ImageAsset],
    key: bytes,
    *,
    game_root: str | Path | None = None,
    overwrite: bool = False,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    """Decrypt images into the game-local editable image workspace."""

    result = ImageActionResult()
    assets = list(assets)
    if game_root is not None:
        ensure_editable_workspace(game_root)
    for asset in assets:
        if not asset.has_encrypted:
            result.skipped += 1
            continue
        if asset.has_plain and not overwrite:
            result.skipped += 1
            continue
        try:
            # Older versions of the image manager placed the editable PNG
            # beside its encrypted runtime file.  Preserve any work done in
            # that layout by migrating it instead of decrypting over it.
            if asset.has_runtime_plain and not asset.has_plain and not overwrite:
                if progress:
                    progress(f"Moving editable copy for {asset.asset_id}")
                _atomic_write(asset.plain_path, asset.runtime_plain_path.read_bytes())
                asset.runtime_plain_path.unlink()
                result.completed += 1
                continue
            if progress:
                progress(f"Decrypting {asset.asset_id}")
            raw = decrypt_image_bytes(asset.encrypted_path.read_bytes(), key)
            _atomic_write(asset.plain_path, raw)
            result.completed += 1
        except Exception as exc:  # continue a large batch and report all failures
            result.errors.append(f"{asset.asset_id}: {exc}")
    if game_root is not None:
        try:
            clean_runtime_image_duplicates(game_root)
        except Exception as exc:
            result.errors.append(f"Runtime image cleanup: {exc}")
    return result


def _path_inside(root: Path, path: Path) -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Image is outside the selected game folder: {path}") from exc


def remove_editable_assets(
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    """Delete editable copies while leaving their runtime assets untouched."""

    root = Path(game_root).expanduser().resolve()
    workspace = editable_workspace_root(root)
    result = ImageActionResult()
    for asset in assets:
        try:
            if not asset.has_plain:
                result.skipped += 1
                continue
            _path_inside(workspace, asset.plain_path)
            if progress:
                progress(f"Removing {asset.asset_id} from editable images")
            asset.plain_path.unlink()
            result.completed += 1

            parent = asset.plain_path.parent
            while parent != workspace:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        except Exception as exc:
            result.errors.append(f"{asset.asset_id}: {exc}")
    return result


def _escape_gitignore_component(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("Image paths containing line breaks cannot be added to .gitignore.")
    escaped = ""
    for char in value:
        if char in "\\*?[]!# " or char == "\t":
            escaped += "\\"
        escaped += char
    return escaped


def _gitignore_pattern(relative: Path, *, directory: bool = False) -> str:
    parts = [_escape_gitignore_component(part) for part in relative.parts]
    pattern = "!/" + "/".join(parts)
    if directory:
        pattern += "/"
    return pattern


def add_patch_exceptions(
    game_root: str | Path, targets: Iterable[str | Path]
) -> list[Path]:
    """Append exact allow-rules to applicable .gitignore files.

    Root and nested ignore files can both affect an asset.  Adding a precise
    exception to each existing file ensures a deeper rule cannot hide a chosen
    image again.  Existing content is preserved and entries are idempotent.
    """

    root = Path(game_root).expanduser().resolve()
    relative_targets = sorted(
        {_path_inside(root, Path(target)) for target in targets},
        key=lambda path: path.as_posix().casefold(),
    )
    if not relative_targets:
        return []

    ignore_to_targets: dict[Path, list[Path]] = {root / ".gitignore": relative_targets}
    for relative in relative_targets:
        parent = root
        for part in relative.parts[:-1]:
            parent /= part
            nested = parent / ".gitignore"
            if nested.is_file():
                ignore_to_targets.setdefault(nested, []).append(
                    Path(*relative.parts[len(parent.relative_to(root).parts):])
                )

    changed: list[Path] = []
    for ignore_path, entries in ignore_to_targets.items():
        existing = (
            ignore_path.read_text(encoding="utf-8", errors="surrogateescape")
            if ignore_path.exists()
            else ""
        )
        rules: list[str] = []
        if ignore_path == root / ".gitignore":
            rules.append("/.dazedtl/")
        for relative in entries:
            for depth in range(1, len(relative.parts)):
                rules.append(_gitignore_pattern(Path(*relative.parts[:depth]), directory=True))
            rules.append(_gitignore_pattern(relative))
        additions = [rule for rule in dict.fromkeys(rules) if rule not in existing.splitlines()]
        if not additions:
            continue
        text = existing
        if text and not text.endswith("\n"):
            text += "\n"
        if "# DazedTL selected image patches" not in text:
            text += "\n# DazedTL selected image patches\n"
        text += "\n".join(additions) + "\n"
        ignore_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(ignore_path, text.encode("utf-8", errors="surrogateescape"))
        changed.append(ignore_path)
    return changed


def prepare_assets_for_patch(
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    key: bytes | None,
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    """Re-encrypt edited PNGs and add only selected runtime assets to gitignore."""

    root = Path(game_root).expanduser().resolve()
    result = ImageActionResult()
    targets: list[Path] = []
    for asset in assets:
        try:
            if asset.has_encrypted:
                if not asset.has_plain:
                    raise FileNotFoundError("decrypt this image before preparing it")
                if key is None:
                    raise ValueError("the encryption key is required")
                if progress:
                    progress(f"Checking {asset.asset_id}")
                plain_bytes = asset.plain_path.read_bytes()
                runtime_bytes = asset.encrypted_path.read_bytes()
                if decrypt_image_bytes(runtime_bytes, key) == plain_bytes:
                    result.skipped += 1
                    continue
                relative_encrypted = _path_inside(root, asset.encrypted_path)
                backup = root / ".dazedtl" / "image_backups" / relative_encrypted
                if not backup.exists():
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(asset.encrypted_path, backup)
                if progress:
                    progress(f"Encrypting {asset.asset_id}")
                encrypted = encrypt_image_bytes(plain_bytes, key)
                _atomic_write(asset.encrypted_path, encrypted)
                targets.append(asset.encrypted_path)
            elif asset.has_runtime_plain:
                # Unencrypted games load the PNG from the runtime image tree.
                # If the user made a workspace copy, publish it back there and
                # preserve the original once, just like encrypted assets.
                if asset.has_plain:
                    if progress:
                        progress(f"Checking {asset.asset_id}")
                    plain_bytes = asset.plain_path.read_bytes()
                    if asset.runtime_plain_path.read_bytes() == plain_bytes:
                        result.skipped += 1
                        continue
                    relative_plain = _path_inside(root, asset.runtime_plain_path)
                    backup = root / ".dazedtl" / "image_backups" / relative_plain
                    if not backup.exists():
                        backup.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(asset.runtime_plain_path, backup)
                    if progress:
                        progress(f"Publishing {asset.asset_id}")
                    _atomic_write(asset.runtime_plain_path, plain_bytes)
                targets.append(asset.runtime_plain_path)
            else:
                raise FileNotFoundError("image file no longer exists")
            result.completed += 1
        except Exception as exc:
            result.errors.append(f"{asset.asset_id}: {exc}")

    if targets:
        if progress:
            progress("Updating .gitignore image allow-rules")
        result.patch_files = targets
        try:
            result.gitignore_files = add_patch_exceptions(root, targets)
        except Exception as exc:
            result.errors.append(f".gitignore: {exc}")
    try:
        clean_runtime_image_duplicates(root)
    except Exception as exc:
        result.errors.append(f"Runtime image cleanup: {exc}")
    return result


def encrypt_assets(
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    key: bytes,
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    """Re-encrypt workspace PNGs without changing gitignore files."""

    root = Path(game_root).expanduser().resolve()
    result = ImageActionResult()
    for asset in assets:
        try:
            if not asset.has_encrypted:
                raise FileNotFoundError("no matching encrypted runtime image exists")
            if not asset.has_plain:
                raise FileNotFoundError("decrypt this image before encrypting it")
            relative_encrypted = _path_inside(root, asset.encrypted_path)
            backup = root / ".dazedtl" / "image_backups" / relative_encrypted
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(asset.encrypted_path, backup)
            if progress:
                progress(f"Encrypting {asset.asset_id}")
            encrypted = encrypt_image_bytes(asset.plain_path.read_bytes(), key)
            _atomic_write(asset.encrypted_path, encrypted)
            result.patch_files.append(asset.encrypted_path)
            result.completed += 1
        except Exception as exc:
            result.errors.append(f"{asset.asset_id}: {exc}")
    try:
        clean_runtime_image_duplicates(root)
    except Exception as exc:
        result.errors.append(f"Runtime image cleanup: {exc}")
    return result
