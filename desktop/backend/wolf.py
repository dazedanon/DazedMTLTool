"""WOLF guided actions using the shared extraction and injection workflow."""
from __future__ import annotations
import json
from pathlib import Path

from util.project_preparation import _game_path
from util.project_scanner import detect_wolf_layout, find_wolf_archives, list_wolf_json_files
from util.wolf_workflow import WolfWorkflow

LABELS = {
    "wolf_unpack": "Unpack WOLF archives", "wolf_extract": "Extract WOLF text and preserve originals",
    "wolf_maps": "Extract missing maps", "wolf_discover": "Discover database sheets",
    "wolf_profile": "Save database profile", "wolf_names": "Inspect name safety",
    "wolf_precheck": "Reconcile names and check injection", "wolf_inject": "Apply all translated WOLF files",
    "wolf_inject_game": "Apply all files from wolf_json", "wolf_restore": "Restore source layout",
    "wolf_loose": "Back up archives for loose playtest", "wolf_repack": "Repack Data.wolf",
    "wolf_saves": "Update existing WOLF saves", "wolf_search": "Find translated text",
    "wolf_wrap_preview": "Preview WOLF wrapping", "wolf_wrap": "Apply WOLF wrapping",
}
READ_ONLY = {"wolf_discover", "wolf_names", "wolf_search", "wolf_wrap_preview"}


def manifest(root):
    root = Path(root)
    path = _game_path(root, root / "wolf_json/manifest.json")
    if not path.is_file():
        return None
    if path.stat().st_size > 10_000_000:
        raise ValueError("The WOLF manifest is too large.")
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    old_root = Path(value["root"])
    data_relative = Path(value["data_dir"]).relative_to(old_root)
    data = _game_path(root, root / data_relative)
    if data not in {root, root / "Data"}:
        raise ValueError("The WOLF manifest must refer to this game's data folder.")
    entries, names = [], set()
    for entry in value.get("entries", []):
        name = entry.get("json", "")
        if not name or Path(name).name != name or "\\" in name or not name.endswith(".json") or name in names:
            raise ValueError("The WOLF manifest has an invalid or repeated JSON filename.")
        names.add(name)
        base = _game_path(root, root / Path(entry["base"]).relative_to(old_root))
        if not base.is_relative_to(data):
            raise ValueError("A WOLF base file points outside this game's Data folder.")
        _game_path(root, root / "wolf_json" / name)
        entries.append({**entry, "base": str(base)})
    return {**value, "root": str(root), "data_dir": str(data), "entries": entries}


def describe(root):
    layout = detect_wolf_layout(root)
    if layout["engine"] != "WOLF":
        return None
    value = manifest(root)
    work = _game_path(root, root / "wolf_json")
    rows = list_wolf_json_files(work, value)
    kinds = {e["json"]: e["kind"] for e in value["entries"]} if value else {}
    return {"source": str(root), "engine": "WOLF", "data": str(work), "plugins": "",
            "encrypted": [str(_game_path(root, p)) for p in layout["archives"]],
            "binary_data": str(_game_path(root, layout["data_dir"] or root / "Data")),
            "files": [{**row, "path": str(_game_path(root, row["path"])), "kind": kinds.get(row["name"], "")} for row in rows]}


def prepare_options(action, options, project, folder):
    selected = {}
    if action in {"wolf_inject", "wolf_inject_game", "wolf_precheck"}:
        selected = {"en_punct": options.get("en_punct", True) is True, "sync": options.get("sync", True) is True}
    if action == "wolf_profile":
        from util.wolfdawn.db_classify import import_ai_profile
        text = options.get("profile", "")
        if not isinstance(text, str) or len(text.encode()) > 1_000_000:
            raise ValueError("Paste a database profile below 1 MB.")
        selected = {"profile": import_ai_profile(text)}
    if action == "wolf_saves":
        path = Path(options.get("path", "")).expanduser().resolve(strict=True)
        if not options.get("path") or path == path.parent or path.is_relative_to(folder.parent.parent):
            raise ValueError("Select the game's save file or save folder.")
        from .workflow_actions import tree_hashes, file_hash
        guard = tree_hashes(path, path) if path.is_dir() else file_hash(path.parent, path)
        selected = {"path": str(path), "save_hashes": guard}
    if action == "wolf_search":
        query = options.get("query", "")
        if not isinstance(query, str) or not query.strip() or len(query) > 500:
            raise ValueError("Enter the in-game text to find (up to 500 characters).")
        selected = {"query": query}
    if action in {"wolf_wrap", "wolf_wrap_preview"}:
        from util.wolfdawn.wrap_search import load_hit_from_id
        hit = options.get("hit", {})
        if not isinstance(hit, dict) or not isinstance(hit.get("json_file"), str) or Path(hit["json_file"]).name != hit["json_file"] or "\\" in hit["json_file"]:
            raise ValueError("Select a text-search result.")
        allowed = {"json_file", "kind", "sheet_name", "field_name", "row", "name_index", "scene_index", "line_index"}
        if set(hit) - allowed or any(not isinstance(v, (str, int)) for v in hit.values()):
            raise ValueError("Invalid text locator.")
        load_hit_from_id(folder / "translated", hit, files_dir=folder / "files", extra_dirs=[Path(project["source"]) / "wolf_json"])
        for key, default, lo, hi in (("width", 50, 0, 300), ("font", 0, 0, 200), ("max_lines", 0, 0, 100)):
            value = options.get(key, default)
            if type(value) is not int or not lo <= value <= hi:
                raise ValueError(f"Choose a valid {key}.")
            selected[key] = value
        selected.update(hit=hit, manual=options.get("manual", True) is True, scope=options.get("scope", "row"))
        if selected["scope"] not in {"row", "group"}:
            raise ValueError("Choose the selected row or its group.")
    return selected


def run(plan, log):
    from .workflow_actions import json_value
    root, folder = Path(plan["project"]["source"]), Path(plan["folder"])
    action, options = plan["action"], plan["options"]
    core = WolfWorkflow(root, folder)
    value = manifest(root)
    core._read_manifest = lambda: value
    work, layout = core._work_dir(), detect_wolf_layout(root)
    result = {}
    if action == "wolf_unpack":
        outcome = core.unpack_task(root, find_wolf_archives(root), log)
    elif action in {"wolf_extract", "wolf_maps"}:
        if not layout.get("data_dir"):
            raise ValueError("Unpack the game archives first.")
        outcome = core.extract_task(layout["data_dir"], work, str(root), action == "wolf_maps", log)
    elif action in {"wolf_discover", "wolf_profile"}:
        from util.wolfdawn import db_classify as db
        distribution = db.analyze_content_distribution(folder / "files")
        if action == "wolf_profile":
            profile = db.load_db_profile(work)
            profile.update(options["profile"])
            db.save_db_profile(work, profile)
        profile = db.load_db_profile(work)
        checked = db.merge_profile_with_groups(profile, distribution.groups)
        result = json_value(distribution)
        result["groups"] = [{**json_value(group), "key": group.key} for group in distribution.groups]
        return {"distribution": result, "profile": profile, "selected": [key for key, enabled in checked.items() if enabled],
                "summary": db.format_discovery_summary(distribution), "prompt": db.build_ai_audit_prompt(distribution)}
    elif action == "wolf_names":
        from util.wolfdawn import names
        path = core._translated_or_source("names.json")
        if not path:
            raise ValueError("Import names.json first.")
        document = json.loads(path.read_text(encoding="utf-8-sig"))
        return {"summary": names.format_name_safety_summary(document), "categories": names.format_note_category_summary(document, db_labels=names.derive_db_labels(folder / "files"))}
    elif action in {"wolf_precheck", "wolf_inject", "wolf_inject_game", "wolf_restore"}:
        if not value:
            raise ValueError("Extract the game's text first.")
        source = work if action == "wolf_inject_game" else folder / "translated"
        files = core._injectable_filenames(source)
        if not files:
            raise ValueError("No injectable JSON exists in the selected source.")
        if action == "wolf_precheck":
            outcome = core.precheck_task(value, set(files), options["en_punct"], result, log)
            from util.wolfdawn import inject_precheck as pre
            from util.skills import load_clipboard_skill
            issues = pre.issues_for_ui(result["report"])
            prompt = load_clipboard_skill("wolf_precheck_repair.md")
            for token, text in {"{{TRANSLATED_DIR}}": str(folder / "translated"), "{{GAME_ROOT}}": str(root), "{{ISSUES}}": pre.format_ai_repair_issues(issues)}.items():
                prompt = prompt.replace(token, text)
            result["prompt"] = prompt if issues else ""
        elif action == "wolf_restore":
            outcome = core.layout_restore_task([source / name for name in files], log)
        else:
            sync_game = action == "wolf_inject"
            sync_tool = action == "wolf_inject_game" and options["sync"]
            outcome = core.inject_task(value, set(files), options["en_punct"], work, folder / "files", folder / "translated", source, sync_game, sync_tool, sync_tool, result, log)
    elif action == "wolf_loose":
        outcome = core.loose_task(find_wolf_archives(root), log)
    elif action == "wolf_repack":
        if not layout.get("data_dir"):
            raise ValueError("No loose Data folder found.")
        like = next((p for p in (root / "Data.wolf.bak", root / "Data.wolf") if p.is_file()), None)
        outcome = core.repack_task(layout["data_dir"], root / "Data.wolf", like, log)
    elif action == "wolf_saves":
        from .workflow_actions import tree_hashes, file_hash
        path = Path(options["path"])
        current = tree_hashes(path, path) if path.is_dir() else file_hash(path.parent, path)
        if current != options["save_hashes"]:
            raise ValueError("The selected saves changed after preview. Preview again.")
        outcome = core.saves_task(str(path), Path(layout["basic_data"]) / "Game.dat" if layout.get("basic_data") else None, log)
    elif action == "wolf_search":
        from util.wolfdawn.wrap_search import search_translated_text
        return {"hits": [{**json_value(hit), "id": hit.hit_id, "summary": hit.summary()} for hit in search_translated_text(options["query"], folder / "translated", files_dir=folder / "files", extra_dirs=[work])]}
    elif action in {"wolf_wrap", "wolf_wrap_preview"}:
        return wrap(folder, work, options, preview=action.endswith("preview"))
    else:
        raise ValueError("Unknown WOLF action.")
    ok, message = outcome
    return {**json_value(result), "ok": ok, "message": message}


def wrap(folder, work, options, *, preview):
    from util.wolfdawn import wrap_search as ws, names
    hit = options["hit"]
    path, doc, line = ws.load_hit_from_id(folder / "translated", hit, files_dir=folder / "files", extra_dirs=[work])
    if path is None or line is None:
        raise ValueError("This text is no longer available. Search again.")
    width, font, max_lines = options["width"], options["font"], options["max_lines"]
    manual, group = options["manual"], options["scope"] == "group"
    if not width and (manual or not group or hit["kind"] != "names"):
        raise ValueError("Choose a positive width. Automatic geometry is available for names-group relayout.")
    if preview:
        text = line.get("text", "")
        info = ws.wrap_preview_info(text, width, speaker_src=line.get("speaker_src", ""), speaker=line.get("speaker", ""))
        if manual:
            info["wrapped"] = ws.apply_manual_font_and_wrap(text, width, font=font or None, speaker_src=line.get("speaker_src", ""), speaker=line.get("speaker", ""))[0]
        return info
    if manual:
        if not group:
            count = ws.wrap_hit_manual(path, doc, hit, width, font=font or None)
        else:
            count = ws.wrap_overflow_manual_in_scope(path, doc, hit, width, font=font or None, translated_dir=folder / "translated" if hit["kind"] in {"map", "common"} else None)
            if hit["kind"] == "names":
                names.upsert_name_wrap_role(names.roles_json_path_for_names(path), hit["sheet_name"], width=width, font=font or None)
    elif group and hit["kind"] == "names":
        roles = names.roles_json_path_for_names(path)
        names.upsert_name_wrap_role(roles, hit["sheet_name"], width=width or None, max_lines=max_lines or None)
        ok, message = names.apply_names_wrap(path, note=hit["sheet_name"], width=width or None, lines=max_lines or None)
        if not ok:
            raise ValueError(message)
        count = message
    elif group:
        count = ws.wrap_overflow_in_scope(path, doc, hit, width, max_lines=max_lines or None, translated_dir=folder / "translated" if hit["kind"] in {"map", "common"} else None)
    else:
        count = ws.wrap_hit_in_file(path, doc, hit, width, max_lines=max_lines or None)
    if hit["kind"] in {"map", "common"}:
        ws.set_format_geometry(work, line.get("speaker_src", ""), width=width, font=font if manual else None, max_lines=max_lines if not manual else None)
    elif width:
        ws.set_sheet_width(work, hit["sheet_name"], width, json_file=hit["json_file"], max_lines=max_lines if not manual else None)
        if manual:
            profile = ws.load_wrap_profile(work)
            profile["sheets"][hit["sheet_name"]]["font"] = font
            ws.save_wrap_profile(work, profile)
    return {"message": f"Updated: {count}", "path": str(path)}
