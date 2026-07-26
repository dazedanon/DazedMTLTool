"""Engine-neutral image workspace, profile registry, and loose-image support."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable
import hashlib
import json
import os
import shutil
import tempfile
import uuid


PROFILE_AUTO = "auto"
PROFILE_RPGMAKER_MVMZ = "rpgmaker_mvmz"
PROFILE_GENERIC = "generic"
SUPPORTED_PLAIN_EXTENSIONS = (".png",)
_EXCLUDED_SCAN_DIRS = {".dazedtl", ".git", "__pycache__"}


@dataclass(frozen=True)
class ImageAsset:
    """One logical image and its editable/runtime representations."""

    asset_id: str
    relative_png: Path
    plain_path: Path
    encrypted_path: Path | None = None
    runtime_plain_path: Path | None = None
    engine_id: str = PROFILE_RPGMAKER_MVMZ

    @property
    def has_plain(self) -> bool:
        return self.plain_path.is_file()

    @property
    def has_encrypted(self) -> bool:
        return self.encrypted_path is not None and self.encrypted_path.is_file()

    @property
    def has_runtime_plain(self) -> bool:
        return self.runtime_plain_path is not None and self.runtime_plain_path.is_file()

    @property
    def runtime_path(self) -> Path | None:
        if self.has_encrypted:
            return self.encrypted_path
        return self.runtime_plain_path


@dataclass
class ImageActionResult:
    completed: int = 0
    skipped: int = 0
    errors: list[str] | None = None
    patch_files: list[Path] | None = None
    gitignore_files: list[Path] | None = None

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.patch_files is None:
            self.patch_files = []
        if self.gitignore_files is None:
            self.gitignore_files = []


@dataclass(frozen=True)
class ImageEngineDetection:
    engine_id: str
    confidence: str
    reason: str
    suggested_image_root: Path | None = None


@dataclass(frozen=True)
class ImageEngineProfile:
    """Discoverable capabilities for an image-engine backend."""

    engine_id: str
    label: str
    configurable_image_root: bool
    supports_encryption: bool
    translation_skill_context: str
    supported_extensions: tuple[str, ...] = SUPPORTED_PLAIN_EXTENSIONS


IMAGE_ENGINE_PROFILES = (
    ImageEngineProfile(
        PROFILE_RPGMAKER_MVMZ,
        "RPG Maker MV/MZ",
        configurable_image_root=False,
        supports_encryption=True,
        translation_skill_context=(
            "This is an RPG Maker MV/MZ project. Runtime images normally live under `img/` or "
            "`www/img/`. Inspect event commands, plugins, and scripts for image placement, "
            "scaling, opacity, dynamic values, and filename-dependent behavior. Encrypted "
            "`.rpgmvp` or `.png_` assets may be decoded read-only with the encryption key from "
            "`System.json`; never modify an encrypted runtime original."
        ),
    ),
    ImageEngineProfile(
        PROFILE_GENERIC,
        "Generic / Loose Images",
        configurable_image_root=True,
        supports_encryption=False,
        translation_skill_context=(
            "This profile manages loose PNG assets without assuming a particular game engine. "
            "Search available code, data, scenes, and asset references for runtime usage when "
            "they exist. If placement, scaling, opacity, or dynamic-value behavior cannot be "
            "established, preserve suspicious blank regions and report the uncertainty. Do not "
            "attempt archive extraction, bundle rebuilding, or format conversion."
        ),
    ),
)


def registered_image_profiles() -> tuple[ImageEngineProfile, ...]:
    return IMAGE_ENGINE_PROFILES


def get_image_profile(engine_id: str) -> ImageEngineProfile:
    for profile in IMAGE_ENGINE_PROFILES:
        if profile.engine_id == engine_id:
            return profile
    raise ValueError(f"Unsupported image engine profile: {engine_id}")


def _resolved_root(game_root: str | Path) -> Path:
    root = Path(game_root).expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Game folder not found: {root}")
    return root


def _inside(root: Path, path: Path, *, label: str = "Image path") -> Path:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} is outside the selected game folder: {path}") from exc


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


def editable_workspace_root(game_root: str | Path) -> Path:
    return Path(game_root).expanduser().resolve() / ".dazedtl" / "images"


def image_manager_state_root(game_root: str | Path) -> Path:
    return Path(game_root).expanduser().resolve() / ".dazedtl" / "image_manager"


def _ensure_workspace_ignore(root: Path) -> None:
    ignore_path = root / ".gitignore"
    existing = (
        ignore_path.read_text(encoding="utf-8", errors="surrogateescape")
        if ignore_path.exists()
        else ""
    )
    if "/.dazedtl/" in existing.splitlines():
        return
    text = existing
    if text and not text.endswith("\n"):
        text += "\n"
    if "# DazedTL image manager working files" not in text:
        text += "\n# DazedTL image manager working files\n"
    text += "/.dazedtl/\n"
    _atomic_write(ignore_path, text.encode("utf-8", errors="surrogateescape"))


def ensure_editable_workspace(game_root: str | Path) -> Path:
    """Create the workspace without migrating or touching runtime assets."""

    root = _resolved_root(game_root)
    workspace = editable_workspace_root(root)
    workspace.mkdir(parents=True, exist_ok=True)
    _ensure_workspace_ignore(root)
    return workspace


def normalize_generic_image_root(
    game_root: str | Path, image_root: str | Path | None
) -> Path:
    root = _resolved_root(game_root)
    if image_root is None or not str(image_root).strip():
        raise ValueError("Choose an image folder for the Generic / Loose Images profile.")
    candidate = Path(image_root).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    _inside(root, candidate, label="Generic image folder")
    if not candidate.is_dir():
        raise FileNotFoundError(f"Image folder not found: {candidate}")
    return candidate


def _iter_plain_images(root: Path) -> Iterable[Path]:
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in dirnames:
            child = current_path / name
            if name in _EXCLUDED_SCAN_DIRS or child.is_symlink():
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = current_path / name
            if path.is_symlink() or path.suffix.casefold() not in SUPPORTED_PLAIN_EXTENSIONS:
                continue
            yield path


def scan_generic_image_assets(
    game_root: str | Path, image_root: str | Path | None
) -> list[ImageAsset]:
    root = _resolved_root(game_root)
    source_root = normalize_generic_image_root(root, image_root)
    source_relative = _inside(root, source_root, label="Generic image folder")
    workspace = editable_workspace_root(root)
    workspace_source = workspace / source_relative
    by_id: dict[str, dict[str, Path]] = {}

    for runtime in _iter_plain_images(source_root):
        relative = _inside(root, runtime)
        asset_id = relative.as_posix()
        by_id[asset_id] = {
            "relative": relative,
            "runtime": runtime,
            "plain": workspace / relative,
        }

    if workspace_source.is_dir():
        for editable in _iter_plain_images(workspace_source):
            relative_under_source = editable.relative_to(workspace_source)
            relative = source_relative / relative_under_source
            asset_id = relative.as_posix()
            by_id.setdefault(
                asset_id,
                {
                    "relative": relative,
                    "runtime": root / relative,
                    "plain": editable,
                },
            )["plain"] = editable

    return sorted(
        (
            ImageAsset(
                asset_id=asset_id,
                relative_png=entry["relative"],
                plain_path=entry["plain"],
                runtime_plain_path=entry["runtime"],
                engine_id=PROFILE_GENERIC,
            )
            for asset_id, entry in by_id.items()
        ),
        key=lambda asset: asset.asset_id.casefold(),
    )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_png_bytes(data: bytes, asset_id: str) -> None:
    from PIL import Image

    try:
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError(f"expected PNG data, found {image.format or 'unknown'}")
            image.verify()
    except Exception as exc:
        raise ValueError(f"editable image is not a valid PNG: {asset_id}: {exc}") from exc


def _validate_asset_collisions(assets: list[ImageAsset]) -> list[ImageAsset]:
    seen: dict[str, str] = {}
    for asset in assets:
        folded = asset.asset_id.casefold()
        previous = seen.get(folded)
        if previous is not None and previous != asset.asset_id:
            raise ValueError(
                "Image paths differ only by letter case and cannot be patched safely on "
                f"Windows: {previous} and {asset.asset_id}"
            )
        seen[folded] = asset.asset_id
    return assets


def _manifest_path(game_root: str | Path) -> Path:
    return image_manager_state_root(game_root) / "manifest.json"


def load_image_manifest(game_root: str | Path) -> dict:
    path = _manifest_path(game_root)
    if not path.is_file():
        return {"version": 1, "assets": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "assets": {}}
    if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
        return {"version": 1, "assets": {}}
    return data


def save_image_manifest(game_root: str | Path, manifest: dict) -> None:
    payload = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _atomic_write(_manifest_path(game_root), payload.encode("utf-8"))


def _manifest_key(asset: ImageAsset) -> str:
    return f"{asset.engine_id}:{asset.asset_id}"


def record_asset_baseline(game_root: str | Path, asset: ImageAsset) -> None:
    record_asset_baselines(game_root, [asset])


def record_asset_baselines(
    game_root: str | Path, assets: Iterable[ImageAsset]
) -> None:
    root = Path(game_root).expanduser().resolve()
    manifest = load_image_manifest(root)
    changed = False
    for asset in assets:
        runtime = asset.runtime_path
        if runtime is None or not runtime.is_file():
            continue
        manifest["assets"][_manifest_key(asset)] = {
            "engine": asset.engine_id,
            "asset_id": asset.asset_id,
            "runtime_path": runtime.resolve().relative_to(root).as_posix(),
            "baseline_sha256": _sha256_path(runtime),
        }
        changed = True
    if changed:
        save_image_manifest(root, manifest)


def asset_source_conflict(game_root: str | Path, asset: ImageAsset) -> bool:
    runtime = asset.runtime_path
    if runtime is None or not runtime.is_file():
        return False
    entry = load_image_manifest(game_root)["assets"].get(_manifest_key(asset), {})
    baseline = entry.get("baseline_sha256")
    return bool(baseline and baseline != _sha256_path(runtime))


def copy_plain_assets_to_workspace(
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    root = _resolved_root(game_root)
    workspace = ensure_editable_workspace(root)
    result = ImageActionResult()
    for asset in assets:
        try:
            if asset.has_plain:
                result.skipped += 1
                continue
            runtime = asset.runtime_plain_path
            if runtime is None or not runtime.is_file():
                raise FileNotFoundError("runtime PNG no longer exists")
            _inside(root, runtime)
            _inside(workspace, asset.plain_path, label="Editable image target")
            if progress:
                progress(f"Making {asset.asset_id} editable")
            _atomic_write(asset.plain_path, runtime.read_bytes())
            record_asset_baseline(root, asset)
            result.completed += 1
        except Exception as exc:
            result.errors.append(f"{asset.asset_id}: {exc}")
    return result


def prepare_plain_assets_for_patch(
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    """Publish loose PNG edits through the transactional patch path."""

    return _prepare_assets_transaction(
        PROFILE_GENERIC, game_root, assets, None, progress=progress
    )


def _prepare_assets_transaction(
    engine_id: str,
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    key: bytes | None,
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    """Preflight, stage, and atomically publish a set of runtime image files."""

    from util.rpgmaker_images import (
        add_patch_exceptions,
        decrypt_image_bytes,
        encrypt_image_bytes,
    )

    root = _resolved_root(game_root)
    result = ImageActionResult()
    candidates: list[tuple[ImageAsset, Path, Path, bytes]] = []
    transaction_root = (
        root / ".dazedtl" / "image_patch_stage" / uuid.uuid4().hex
    )

    for asset in assets:
        try:
            if not asset.has_plain:
                raise FileNotFoundError("make this image editable before patching it")
            runtime = asset.runtime_path
            if runtime is None or not runtime.is_file():
                raise FileNotFoundError("runtime image no longer exists")
            relative = _inside(root, runtime)
            if asset_source_conflict(root, asset):
                raise RuntimeError(
                    "runtime image changed after the editable copy was created; "
                    "remove/recreate the editable copy or resolve the conflict manually"
                )
            editable = asset.plain_path.read_bytes()
            _validate_png_bytes(editable, asset.asset_id)
            current = runtime.read_bytes()
            if asset.has_encrypted:
                if engine_id != PROFILE_RPGMAKER_MVMZ:
                    raise ValueError("the active engine profile cannot encode this image")
                if key is None:
                    raise ValueError("the RPG Maker encryption key is required")
                if decrypt_image_bytes(current, key) == editable:
                    result.skipped += 1
                    continue
                output = encrypt_image_bytes(editable, key)
            else:
                if current == editable:
                    result.skipped += 1
                    continue
                output = editable
            staged_new = transaction_root / "new" / relative
            staged_old = transaction_root / "old" / relative
            _atomic_write(staged_new, output)
            _atomic_write(staged_old, current)
            candidates.append((asset, runtime, relative, output))
        except Exception as exc:
            result.errors.append(f"{asset.asset_id}: {exc}")

    # Treat a selected batch as one transaction. A conflict or invalid image
    # must not leave the other selected files partially published.
    if result.errors:
        if transaction_root.exists():
            shutil.rmtree(transaction_root)
        return result
    if not candidates:
        if transaction_root.exists():
            shutil.rmtree(transaction_root)
        return result

    published: list[tuple[Path, Path]] = []
    targets = [runtime for _asset, runtime, _relative, _output in candidates]
    try:
        for asset, runtime, relative, output in candidates:
            backup = root / ".dazedtl" / "image_backups" / relative
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(transaction_root / "old" / relative, backup)
            if progress:
                action = "Encrypting" if asset.has_encrypted else "Publishing"
                progress(f"{action} {asset.asset_id}")
            _atomic_write(runtime, output)
            published.append((runtime, transaction_root / "old" / relative))

        if progress:
            progress("Updating .gitignore image allow-rules")
        result.gitignore_files = add_patch_exceptions(root, targets)
        record_asset_baselines(
            root, (asset for asset, _runtime, _relative, _output in candidates)
        )
    except Exception as exc:
        rollback_errors: list[str] = []
        for runtime, staged_old in reversed(published):
            try:
                _atomic_write(runtime, staged_old.read_bytes())
            except Exception as rollback_exc:
                rollback_errors.append(f"{runtime}: {rollback_exc}")
        result.errors.append(f"Patch transaction rolled back: {exc}")
        result.errors.extend(f"Rollback failed: {error}" for error in rollback_errors)
        return result
    finally:
        if transaction_root.exists():
            shutil.rmtree(transaction_root)

    result.completed = len(candidates)
    result.patch_files = targets
    return result


def detect_image_engine(game_root: str | Path) -> ImageEngineDetection:
    root = _resolved_root(game_root)
    markers = (
        root / "Game.rpgproject",
        root / "game.rmmzproject",
        root / "www" / "data" / "System.json",
        root / "data" / "System.json",
    )
    for content in (root / "www", root):
        image_root = content / "img"
        if not image_root.is_dir():
            continue
        encrypted = next(
            (
                path
                for pattern in ("*.rpgmvp", "*.png_")
                for path in image_root.rglob(pattern)
            ),
            None,
        )
        if encrypted is not None or any(marker.exists() for marker in markers):
            evidence = encrypted.name if encrypted is not None else "System/project markers"
            return ImageEngineDetection(
                PROFILE_RPGMAKER_MVMZ,
                "high",
                f"RPG Maker MV/MZ detected from {evidence} and {image_root}",
                image_root,
            )

    candidates = (
        root / "images",
        root / "image",
        root / "assets" / "images",
        root / "assets",
        root / "game" / "images",
        root / "img",
    )
    suggested = next(
        (
            candidate
            for candidate in candidates
            if candidate.is_dir() and next(_iter_plain_images(candidate), None) is not None
        ),
        None,
    )
    reason = (
        f"No RPG Maker encryption markers found; loose PNGs found under {suggested}"
        if suggested
        else "No supported engine markers found; choose the folder containing loose PNGs"
    )
    return ImageEngineDetection(PROFILE_GENERIC, "fallback", reason, suggested)


def profile_label(engine_id: str) -> str:
    try:
        return get_image_profile(engine_id).label
    except ValueError:
        return engine_id


def scan_profile_assets(
    engine_id: str,
    game_root: str | Path,
    image_root: str | Path | None = None,
) -> list[ImageAsset]:
    if engine_id == PROFILE_RPGMAKER_MVMZ:
        from util.rpgmaker_images import scan_image_assets

        return _validate_asset_collisions(scan_image_assets(game_root))
    if engine_id == PROFILE_GENERIC:
        return _validate_asset_collisions(
            scan_generic_image_assets(game_root, image_root)
        )
    raise ValueError(f"Unsupported image engine profile: {engine_id}")


def make_profile_assets_editable(
    engine_id: str,
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    key: bytes | None,
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    assets = list(assets)
    if engine_id == PROFILE_RPGMAKER_MVMZ:
        from util.rpgmaker_images import decrypt_assets

        encrypted = [asset for asset in assets if asset.has_encrypted]
        plain = [asset for asset in assets if not asset.has_encrypted]
        result = ImageActionResult()
        if encrypted:
            if key is None:
                result.errors.append("RPG Maker encryption key is required.")
            else:
                before = {asset.asset_id: asset.has_plain for asset in encrypted}
                decrypted = decrypt_assets(
                    encrypted, key, game_root=game_root, overwrite=False, progress=progress
                )
                result.completed += decrypted.completed
                result.skipped += decrypted.skipped
                result.errors.extend(decrypted.errors)
                for asset in encrypted:
                    if not before[asset.asset_id] and asset.plain_path.is_file():
                        record_asset_baseline(game_root, asset)
        copied = copy_plain_assets_to_workspace(game_root, plain, progress=progress)
        result.completed += copied.completed
        result.skipped += copied.skipped
        result.errors.extend(copied.errors)
        return result
    if engine_id == PROFILE_GENERIC:
        return copy_plain_assets_to_workspace(game_root, assets, progress=progress)
    raise ValueError(f"Unsupported image engine profile: {engine_id}")


def prepare_profile_assets_for_patch(
    engine_id: str,
    game_root: str | Path,
    assets: Iterable[ImageAsset],
    key: bytes | None,
    *,
    progress: Callable[[str], None] | None = None,
) -> ImageActionResult:
    assets = list(assets)
    if engine_id == PROFILE_GENERIC:
        return prepare_plain_assets_for_patch(game_root, assets, progress=progress)
    if engine_id == PROFILE_RPGMAKER_MVMZ:
        return _prepare_assets_transaction(
            PROFILE_RPGMAKER_MVMZ,
            game_root,
            assets,
            key,
            progress=progress,
        )
    raise ValueError(f"Unsupported image engine profile: {engine_id}")


def preview_profile_png_bytes(
    engine_id: str, asset: ImageAsset, key: bytes | None
) -> bytes:
    if engine_id == PROFILE_RPGMAKER_MVMZ:
        from util.rpgmaker_images import preview_png_bytes

        return preview_png_bytes(asset, key)
    if asset.has_plain:
        return asset.plain_path.read_bytes()
    if asset.has_runtime_plain:
        return asset.runtime_plain_path.read_bytes()
    raise FileNotFoundError(asset.runtime_plain_path or asset.plain_path)


def thumbnail_profile_png_bytes(
    engine_id: str, asset: ImageAsset, key: bytes | None, size: int = 128
) -> bytes:
    from PIL import Image

    raw = preview_profile_png_bytes(engine_id, asset, key)
    with Image.open(BytesIO(raw)) as image:
        image.thumbnail((size, size))
        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA")
        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()
