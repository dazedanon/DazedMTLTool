"""File preparation shared by RPG Maker Workflow and Len's Method."""

from __future__ import annotations

from pathlib import Path
import shutil

from util.paths import PROJECT_ROOT

GAMEUPDATE_COPY_SKIP_NAMES = frozenset({"previous_patch_sha.txt"})
WOLF_ONLY_GAMEUPDATE_NAMES = frozenset({"UberWolfCli.exe", "UberWolfCli.LICENSE.txt"})
RPG_GAMEUPDATE_COPY_SKIP_NAMES = GAMEUPDATE_COPY_SKIP_NAMES | WOLF_ONLY_GAMEUPDATE_NAMES | {"patch-config.txt"}
# Installing/updating the helper must not reset project-specific configuration.
GAMEUPDATE_PRESERVE_EXISTING = frozenset({".gitignore", "README.md", "gameupdate/patch-config.txt"})


def format_plugins_js(path: str | Path) -> int:
    import jsbeautifier

    path = Path(path)
    original = path.read_text(encoding="utf-8-sig")
    options = jsbeautifier.default_options()
    options.indent_size = 2
    options.indent_char = " "
    options.max_preserve_newlines = 2
    options.preserve_newlines = True
    options.end_with_newline = True
    formatted = jsbeautifier.beautify(original, options)
    if formatted != original:
        path.write_text(formatted, encoding="utf-8")
    return len(formatted)


def copy_files(src: str | Path, dst: str | Path, *, skip_names=frozenset(),
               preserve_existing=frozenset(), log=None) -> tuple[int, list[str]]:
    src, dst = Path(src), Path(dst)
    if not src.is_dir():
        return 0, [f"Source folder not found: {src}"]
    if src.resolve().is_relative_to(dst.resolve()) or dst.resolve().is_relative_to(src.resolve()):
        raise ValueError("Source and destination copy folders must not overlap.")
    dst.mkdir(parents=True, exist_ok=True)
    copied, errors = 0, []
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(src)
        target = dst / relative
        if path.name in skip_names or relative.as_posix() in preserve_existing and target.exists():
            if log:
                log(f"  kept/skipped {relative}")
            continue
        try:
            _game_path(dst, target)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied += 1
            if log:
                log(f"  copied {relative}")
        except Exception as exc:
            errors.append(f"{relative}: {exc}")
    return copied, errors


def _game_path(root: Path, path: Path) -> Path:
    """Validate a selected game path before an in-place preparation write."""
    if not path.is_relative_to(root) or ".." in path.relative_to(root).parts:
        raise ValueError(f"Preparation path is outside the selected game: {path}")
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"Preparation cannot write through a symlink: {current}")
    return path


def rpgmaker_layout(game_root: str | Path) -> dict | None:
    """Recognize actual RPG Maker layouts without treating arbitrary data JSON as RPG Maker."""
    root = Path(game_root)
    for base in (root / "www", root):
        plugins = base / "js/plugins.js"
        for data in (base / "data", base / "Data"):
            if (data / "System.json").is_file() and plugins.is_file():
                return {"engine": "MVMZ", "data_path": data, "plugins_js": plugins}
    native = root / "Data"
    if (native.is_dir() and any(native.glob("*.rvdata2"))) or any(root.glob("Game.rgss*")):
        return {"engine": "ACE", "data_path": root / "ace_json", "plugins_js": None}
    return None


def write_gameupdate_config(game_root: str | Path, *, env_path=None) -> tuple[bool, str]:
    from util.gameupdate_config import write_patch_config

    return write_patch_config(game_root, env_path=env_path or PROJECT_ROOT / ".env", overwrite=False)


def install_startup_check(game_root: str | Path) -> tuple[bool, str]:
    from util.translation_update_check import install

    ok, message = install(game_root)
    if ok:
        # The registration is part of preparation too; finish in the same
        # canonical layout so a second setup does not introduce formatting churn.
        for path in (Path(game_root) / "www/js/plugins.js", Path(game_root) / "js/plugins.js"):
            if path.is_file():
                format_plugins_js(path)
                break
    return ok, message


def prepare_rpgmaker(game_root: str | Path, *, data_path: str | Path | None = None,
                     gameupdate_source: str | Path | None = None, env_path=None, log=None) -> dict:
    """Run Workflow's three file-preparation steps, before the shared Git setup.

    Ace extraction/conversion is Workflow Step 0: supply its existing JSON export.
    Native Marshal files are never run through a text formatter.
    """
    from util.dazedformat import format_json_files

    root = Path(game_root).expanduser().resolve()
    layout = rpgmaker_layout(root)
    if layout is None:
        raise ValueError("No RPG Maker MV/MZ or Ace game was detected; other engines use their own preparation.")
    data = Path(data_path).expanduser() if data_path is not None else layout["data_path"]
    if not data.is_absolute():
        data = root / data
    data = _game_path(root, data)
    if layout["engine"] == "MVMZ" and data != layout["data_path"]:
        raise ValueError("MV/MZ preparation must use this game's detected data folder.")
    if not data.is_dir() or not any(data.glob("*.json")):
        raise ValueError("Extract/convert the Ace data using Workflow's tools first, then supply its JSON folder with --data-path.")
    json_files = [p for p in data.rglob("*") if p.suffix.lower() == ".json"]
    for path in json_files:
        _game_path(root, path)
    plugins = layout["plugins_js"]
    if plugins:
        _game_path(root, plugins)
        _game_path(root, plugins.parent / "plugins/TranslationUpdateCheck.js")
    source = Path(gameupdate_source) if gameupdate_source is not None else PROJECT_ROOT / "gameupdate"
    if not (source / "GameUpdate.bat").is_file():
        raise ValueError(f"The bundled GameUpdate helper is missing: {source}")
    _game_path(root, root / "gameupdate/patch-config.txt")

    emit = log or (lambda _message: None)
    emit("1. Format game data")
    count, errors = format_json_files(data, log=emit)
    if errors:
        raise ValueError("Game-data formatting failed; later preparation steps were not run. " + "; ".join(errors))
    emit("2. Format plugin configuration" if plugins else "2. Plugin configuration: not applicable to Ace")
    if plugins:
        format_plugins_js(plugins)
    emit("3. Install GameUpdate")
    copied, errors = copy_files(source, root, skip_names=RPG_GAMEUPDATE_COPY_SKIP_NAMES,
                                preserve_existing=GAMEUPDATE_PRESERVE_EXISTING, log=emit)
    if errors:
        raise ValueError("GameUpdate copy failed; Git setup must wait. " + "; ".join(errors))
    configured, config_message = write_gameupdate_config(root, env_path=env_path)
    emit(config_message)
    checker_message = "Startup check: not applicable to Ace"
    if plugins:
        installed, checker_message = install_startup_check(root)
        if not installed:
            raise ValueError(checker_message)
    emit(checker_message)
    return {"engine": layout["engine"], "data_path": str(data), "formatted_json": count,
            "plugins_formatted": bool(plugins), "gameupdate_files": copied,
            "config_written": configured, "config_status": config_message,
            "startup_check": checker_message,
            "next_step": "Review preparation, then run git-setup before translating."}
