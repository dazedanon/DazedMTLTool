"""Guided actions composed from the same services as the Qt workflow."""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid

from util.paths import PROJECT_ROOT
from util.project_preparation import _game_path, rpgmaker_layout
from .project import digest
from . import wolf

LABELS = {
    "import": "Import selected files", "format_data": "Format game data", "format_plugins": "Format plugins.js",
    "gameupdate": "Install GameUpdate", "prepare": "Prepare game files", "git_status": "Inspect Git version tracking",
    "git_setup": "Set up Git version tracking", "ace_decrypt": "Decrypt Ace archive", "ace_extract": "Convert Ace data to JSON",
    "ace_pack": "Pack translated Ace data", "export_selected": "Export selected files to game", "export_all": "Export all translated files to game",
    "rewrap_preview": "Preview rewrap", "rewrap_apply": "Apply rewrap", "qa_prepare": "Prepare or resume translation QA",
    "qa_status": "Refresh translation QA", "qa_rebuild": "Create final QA rebuild handoff", "playtest_status": "Refresh playtest plugins",
    "inspector_install": "Install TL Inspector", "inspector_remove": "Remove TL Inspector", "forge_install": "Install Forge",
    "forge_remove": "Remove Forge", "playtest_install": "Install both playtest plugins", "playtest_apply": "Apply playtest settings",
    "release": "Build public release ZIP", "editors": "Find code editors",
    "reference_add": "Add DazedTL reference translation", "reference_pair": "Add Japanese / English reference pair",
    "reference_remove": "Remove reference registration", "reference_build": "Build exact reference matches", "images_status": "Refresh image readiness",
}
READ_ONLY = {"git_status", "rewrap_preview", "qa_status", "qa_rebuild", "playtest_status", "editors", "images_status"}
LABELS.update(wolf.LABELS)
READ_ONLY.update(wolf.READ_ONLY)


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [json_value(item) for item in value]
    return str(value) if isinstance(value, Path) else value


def regular(root, path):
    path = _game_path(Path(root), Path(path))
    if path.exists() and not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    return path


def file_hash(root, path):
    path = regular(root, path)
    return digest(path.read_bytes()) if path.is_file() else None


def tree_hashes(root, folder):
    root, folder = Path(root), Path(folder)
    _game_path(root, folder)
    if not folder.exists():
        return None
    result = {}
    for directory, folders, files in os.walk(folder, followlinks=False):
        for name in folders:
            _game_path(root, Path(directory) / name)
        for name in sorted(files):
            path = Path(directory) / name
            result[path.relative_to(folder).as_posix()] = file_hash(root, path)
    return result


def describe_game(source):
    root = Path(source).expanduser().resolve(strict=True)
    if not root.is_dir() or root == root.parent:
        raise ValueError("Choose an existing game folder.")
    layout = rpgmaker_layout(root)
    if not layout:
        result = wolf.describe(root)
        if result:
            return result
        raise ValueError("Select an RPG Maker MV, MZ, Ace or WOLF game root.")
    data = _game_path(root, layout["data_path"])
    if layout["plugins_js"]:
        regular(root, layout["plugins_js"])
    from util.project_scanner import list_data_files
    files = list_data_files(data, "MVMZ") if data.is_dir() else []
    rows = [{**item, "path": str(regular(root, item["path"]))} for item in files]
    encrypted = [str(regular(root, path)) for path in root.glob("Game.rgss*")]
    return {"source": str(root), "engine": layout["engine"], "data": str(data),
            "plugins": str(layout["plugins_js"] or ""), "encrypted": encrypted, "files": rows}


def action_guard(project, folder):
    """Bind a confirmation to its current source, outputs and portable guidance."""
    root, folder = Path(project["source"]), Path(folder)
    layout = describe_game(root)
    return {"layout": {key: layout[key] for key in ("source", "engine", "data", "plugins", "encrypted")},
            "data": tree_hashes(root, Path(layout["data"])),
            "binary_data": tree_hashes(root, Path(layout["binary_data"])) if layout["engine"] == "WOLF" else None,
            "archives": {str(path.relative_to(root)): file_hash(root, path) for path in sorted(root.glob("*.wolf*"))} if layout["engine"] == "WOLF" else None,
            "plugins": file_hash(root, Path(layout["plugins"])) if layout["plugins"] else None,
            "plugin_files": tree_hashes(root, Path(layout["plugins"]).parent / "plugins") if layout["plugins"] else None,
            "settings": file_hash(root, root / ".dazedtl/settings.json"),
            "glossary": file_hash(root, root / ".dazedtl/glossary.txt"),
            "legacy_glossary": file_hash(root, root / "glossary.txt"),
            "legacy_quirks": file_hash(root, root / "translation_quirks.txt"),
            "legacy_skills": tree_hashes(root, root / "skills"),
            "references": file_hash(root, root / ".dazedtl/reference-games.json"),
            "skills": tree_hashes(root, root / ".dazedtl/skills"),
            "files": tree_hashes(folder, folder / "files"), "translated": tree_hashes(folder, folder / "translated"),
            "variables": file_hash(folder, folder / "log/var_translation_map.json")}


def validate_plan(plan):
    if action_guard(plan["project"], plan["folder"]) != plan["guard"]:
        raise ValueError("The game, guidance or workflow files changed after this preview. Preview the action again.")
    if plan["action"] == "release":
        output = Path(plan["options"]["output"])
        if output.is_symlink() or (digest(output.read_bytes()) if output.is_file() else None) != plan["output_hash"]:
            raise ValueError("The release destination changed after this preview. Preview the action again.")


def run_action(plan, log):
    validate_plan(plan)
    project, options = plan["project"], plan["options"]
    root, folder = Path(project["source"]), Path(plan["folder"])
    action, data = plan["action"], Path(project["data"])
    log(plan["label"])
    if action.startswith("wolf_"):
        if project["engine"] != "WOLF":
            raise ValueError("This action requires a WOLF project.")
        return wolf.run(plan, log)
    if action.startswith("reference_"):
        from util.reference_games import add_embedded_reference, add_game_pair_reference, remove_reference, prepare_overlaps, inspect_reference_game
        for name in ("reference-games.json", "reference-index.json", "reference-overlaps.json"):
            regular(root, root / ".dazedtl" / name)
        _game_path(root, root / ".dazedtl/reference-data")
        if action == "reference_add":
            reference = inspect_reference_game(options["translated"])
            if not reference["data"]:
                raise ValueError("Choose an extracted reference data folder containing _original translations.")
            return add_embedded_reference(root, options["title"], reference["data"])
        if action == "reference_pair":
            return add_game_pair_reference(root, options["title"], options["original"], options["translated"], log_fn=log)
        if action == "reference_remove":
            return remove_reference(root, options["id"])
        return prepare_overlaps(root, data, force=True)
    if action == "images_status":
        from util.rpgmaker_images import inspect_workflow
        return json_value(inspect_workflow(root))
    if action == "import":
        from util.project_scanner import import_to_files
        rows = {row["name"]: row for row in describe_game(root)["files"]}
        selected = [{**rows[name], "path": Path(rows[name]["path"])} for name in options["files"]]
        staging = folder / ("import-" + uuid.uuid4().hex)
        staging.mkdir()
        count, errors = import_to_files(selected, staging)
        if errors:
            shutil.rmtree(staging)
            raise ValueError("; ".join(errors))
        previous = folder / ("previous-import-" + uuid.uuid4().hex)
        if (folder / "files").exists():
            (folder / "files").rename(previous)
        try:
            staging.rename(folder / "files")
        except Exception:
            if previous.exists():
                previous.rename(folder / "files")
            raise
        if previous.exists():
            shutil.rmtree(previous)
        return {"files": count, "selected": options["files"]}
    if action in {"prepare", "format_data", "format_plugins", "gameupdate"}:
        from util.project_preparation import (prepare_rpgmaker, format_plugins_js, copy_files, write_gameupdate_config,
                                             install_startup_check, RPG_GAMEUPDATE_COPY_SKIP_NAMES, GAMEUPDATE_COPY_SKIP_NAMES, GAMEUPDATE_PRESERVE_EXISTING)
        regular(folder, folder / "public-settings.env").write_text("\n".join(f"{key}={json.dumps(value)}" for key, value in options.get("public_settings", {}).items()), encoding="utf-8")
        if action == "prepare":
            return prepare_rpgmaker(root, data_path=data, env_path=folder / "public-settings.env", log=log)
        if action == "format_data":
            from util.dazedformat import format_json_files
            count, errors = format_json_files(data, log=log)
            if errors:
                raise ValueError("; ".join(errors))
            return {"formatted": count}
        if action == "format_plugins":
            if not project["plugins"]:
                raise ValueError("Ace does not use plugins.js.")
            return {"characters": format_plugins_js(project["plugins"])}
        skip_names = GAMEUPDATE_COPY_SKIP_NAMES if project["engine"] == "WOLF" else RPG_GAMEUPDATE_COPY_SKIP_NAMES
        count, errors = copy_files(PROJECT_ROOT / "gameupdate", root, skip_names=skip_names,
                                   preserve_existing=GAMEUPDATE_PRESERVE_EXISTING, log=log)
        if errors:
            raise ValueError("; ".join(errors))
        configured, message = write_gameupdate_config(root, env_path=folder / "public-settings.env")
        log(message)
        if project["plugins"]:
            ok, message = install_startup_check(root)
            log(message)
            if not ok:
                raise ValueError(message)
        return {"files": count, "config_written": configured}
    if action in {"git_status", "git_setup"}:
        from util.len_translation import LenProject
        from util.len_git import git_status, setup_git
        if action == "git_status":
            return git_status(LenProject(root))
        return setup_git(LenProject(root), original_game=Path(options["original"]) if options.get("original") else None,
                         version=options.get("version"), current_is_untranslated=options.get("untranslated") is True)
    if action.startswith("ace_"):
        from util.ace.update_tools import ensure_ace_tools, build_decrypter_command, ace_tool_path
        if project["engine"] != "ACE":
            raise ValueError("This action requires an Ace game.")
        if not ensure_ace_tools(log_fn=log):
            raise ValueError("Ace tools are not installed. See the activity log.")
        command = build_decrypter_command(root) if action == "ace_decrypt" else [str(ace_tool_path("RV2JSON.exe")), "-c" if action == "ace_extract" else "-u"]
        with subprocess.Popen(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace") as child:
            try:
                for line in child.stdout:
                    log(line.rstrip())
                if child.wait():
                    raise ValueError("The Ace tool failed. See the activity log.")
            except BaseException:
                child.terminate()
                raise
        return {"completed": action}
    if action in {"export_selected", "export_all"}:
        from util.project_scanner import export_to_game
        names = list(plan["guard"]["translated"] or {})
        if action == "export_selected":
            names = [name for name in names if name in (plan["guard"]["files"] or {})]
        if not names:
            raise ValueError("No matching translated files are available.")
        for name in names:
            regular(root, data / name)
        count, errors = export_to_game(folder / "translated", data, filenames=names)
        if errors:
            raise ValueError("; ".join(errors))
        return {"files": count, "destination": str(data), "ace_packing_required": project["engine"] == "ACE"}
    if action.startswith("rewrap_"):
        from util.rpgmaker_rewrap import RewrapOptions, parse_event_codes, rewrap_directory
        widths = options["widths"]
        settings = RewrapOptions(widths["width"], widths["faceWidth"], widths["listWidth"], widths["noteWidth"],
                                 categories=frozenset(options["categories"]), event_codes=parse_event_codes(options["codes"]),
                                 max_protected_rows=options["max_rows"] if options["protect_rows"] else 0,
                                 skip_protected_overflow=options["protect_rows"], only_over_limit=options["over_limit"])
        report = rewrap_directory(data, settings, file_names=options["files"], apply=action == "rewrap_apply")
        log(report.headline(apply=action == "rewrap_apply"))
        if report.errors:
            raise ValueError("; ".join(report.errors))
        return json_value(report)
    if action.startswith("qa_"):
        from util.rpgmaker_qa import prepare_task, find_latest_task, find_latest_completed_task, status
        storage = folder.parent.parent / "qa"
        focus = options["focus"]
        if action == "qa_prepare":
            task, state = prepare_task(root, data, focus, storage)
            return {"task": str(task), "status": state, "handoff": "Continue this DazedTL-managed RPG Maker QA task. Follow its README exactly; do not invent a separate pipeline or edit game files during discovery.\n\n" + (task / "README.md").read_text(encoding="utf-8")}
        task = find_latest_task(storage, root, focus)
        completed = find_latest_completed_task(storage, root, focus)
        if action == "qa_status":
            return {"task": str(task or ""), "status": status(task) if task else {}, "completed": str(completed or "")}
        if completed is None:
            raise ValueError("No completed QA pass is available for this game and focus.")
        return {"handoff": f'Rebuild only the final report for the completed DazedTL-managed QA task `{completed}`. Do not run prepare or repeat screen/deep review.\n\nRun:\n`python "{PROJECT_ROOT / "scripts/rpgmaker_qa.py"}" rebuild-final --task "{completed}" --output-root "<new directory under {storage / "final_rebuilds"}>"`\n\nUse a new output root for every attempt. Reuse checksum-validated screen and deep receipts. Reconcile only conflicts named by the final consistency audit. After finalization, complete the final editorial pass and follow the rebuilt task\'s release-approval and safeguard workflow.'}
    if action == "editors":
        from util.tl_inspector.config import detect_editors
        return {"editors": json_value(detect_editors())}
    if action.startswith(("playtest_", "inspector_", "forge_")):
        from util.tl_inspector import installer as inspector
        from util.forge import installer as forge
        if action == "playtest_status":
            return {"inspector": inspector.status(root), "forge": forge.status(root)}
        cfg = options["playtest"]
        actions = [(inspector, "install"), (forge, "install")] if action == "playtest_install" else (
            [(module, "apply_config") for module in (inspector, forge) if module.status(root).get("plugin_file")]
            if action == "playtest_apply" else [(inspector if action.startswith("inspector") else forge, "uninstall" if action.endswith("remove") else "install")])
        messages = []
        for module, operation in actions:
            log(f"{operation}: {module.__name__}")
            ok, message = getattr(module, operation)(root, **({} if operation == "uninstall" else {"cfg": cfg}))
            log(message)
            if not ok:
                raise ValueError(message)
            messages.append(message)
        return {"messages": messages, "inspector": inspector.status(root), "forge": forge.status(root)}
    if action == "release":
        from util.release_package import create_release_zip
        return json_value(create_release_zip(root, options["output"], progress=lambda current, total, name: log(f"{current}/{total} · {name}")))
    raise ValueError("Unsupported guided action.")
