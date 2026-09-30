"""Saved guided projects, confirmations and phase-to-phase handoffs."""
from __future__ import annotations

import json
from pathlib import Path
import re
import shutil
import uuid

from util.engine_options import validate_engine_options, engine_options
from util.game_settings import load_game_wrap_widths, normalize_wrap_widths, save_game_wrap_widths
from util.rpgmaker_profiles import DB_FILES, EVENT_FILES_EXACT, PHASE0_CONFIG, PHASE1_CONFIG, PHASE1B_CONFIG, PHASE2_CONFIG
from .project import atomic_json, digest
from .settings import SettingsStore
from .workflow_actions import LABELS, READ_ONLY, action_guard, describe_game, regular, validate_plan

from .guidance import documents, document_save, valid_document_name


class Workflows:
    def __init__(self, workspace, lock, operations, manual):
        self.workspace = Path(workspace)
        self.root = self.workspace / "workflows"
        self.lock, self.operations, self.manual = lock, operations, manual
        self.projects, self.previews = {}, {}
        self.current = ""
        for path in self.root.glob("*/project.json"):
            project = json.loads(path.read_text(encoding="utf-8"))
            self.projects[project["id"]] = project
        selection = self.root / "selection.json"
        if selection.is_file():
            self.current = json.loads(selection.read_text(encoding="utf-8")).get("id", "")

    def folder(self, identity):
        if identity not in self.projects:
            raise ValueError("Select a guided project first.")
        return self.root / identity

    def save(self, project):
        atomic_json(self.folder(project["id"]) / "project.json", project)

    def open(self, source):
        game = describe_game(source)
        root = Path(game["source"])
        if root.is_relative_to(self.workspace) or self.workspace.is_relative_to(root):
            raise ValueError("The game and desktop workspace must be separate folders.")
        existing = next((item for item in self.projects.values() if item["source"] == game["source"]), None)
        if existing:
            existing.update(game)
            existing["widths"] = load_game_wrap_widths(root) or existing["widths"]
            project = existing
        else:
            settings = SettingsStore(self.workspace).describe()
            project = {"id": uuid.uuid4().hex, **game, "revision": 0, "step": 0, "done": [], "imported": [],
                       "selected": [item["name"] for item in game["files"] if item["default"]],
                       "engine_options": settings["engines"]["rpgmakermvmz"],
                       "wolf": {"literal_line1_lowconf": True, "db_groups": []},
                       "widths": load_game_wrap_widths(root) or normalize_wrap_widths(settings["values"]),
                       "mode": "translate", "phase1_comments": False, "manual_job": "", "collected": [], "collection_error": ""}
            self.projects[project["id"]] = project
            for name in ("files", "translated", "log"):
                (self.folder(project["id"]) / name).mkdir(parents=True, exist_ok=True)
        self.current = project["id"]
        atomic_json(self.root / "selection.json", {"id": self.current})
        self.save(project)
        return self.state()

    def state(self, project_id=""):
        with self.lock:
            identity = project_id or self.current
            project = self.projects.get(identity)
            if project:
                self._collect(project)
            jobs = sorted((job for job in self.operations.jobs.values() if job["project_id"] == identity), key=lambda job: job["created"], reverse=True)
            if project:
                for job in reversed(jobs):
                    if job["status"] == "complete" and job["action"] == "import" and not job.get("applied"):
                        project["imported"] = job["result"]["selected"]
                        self.save(project)
                        job["applied"] = True
                        self.operations.save(job)
                    if job["status"] == "complete" and job["action"] in {"wolf_discover", "wolf_profile"} and not job.get("applied"):
                        project["wolf"]["db_groups"] = job["result"]["selected"]
                        project["revision"] += 1
                        self.save(project)
                        job["applied"] = True
                        self.operations.save(job)
                    if job["status"] == "complete" and job["action"] in {"ace_decrypt", "ace_extract", "wolf_unpack", "wolf_extract", "wolf_maps"} and not job.get("applied"):
                        project.update(describe_game(project["source"]))
                        if job["action"] in {"ace_extract", "wolf_extract", "wolf_maps"}:
                            project["selected"] = [row["name"] for row in project["files"] if row["default"]]
                        self.save(project)
                        job["applied"] = True
                        self.operations.save(job)
            draft_path = self.folder(identity) / "draft.json" if project else None
            from util.reference_games import load_registry
            return json.loads(json.dumps({"draft": json.loads(draft_path.read_text(encoding="utf-8")) if draft_path and draft_path.is_file() else {},
                                         "projects": [{"id": p["id"], "source": p["source"], "engine": p["engine"]} for p in self.projects.values()],
                                         "project": project, "jobs": jobs[:30], "active": self.operations.active or self.manual.active or None,
                                         "manual_job": self.manual.jobs.get(project["manual_job"]) if project else None,
                                         "references": load_registry(project["source"])["references"] if project else [],
                                         "engine_schema": engine_options()["rpgmakermvmz"]["fields"], "allow_providers": self.manual.allow_providers}))

    def draft(self, project_id, draft):
        folder = self.folder(project_id)
        if not isinstance(draft, dict) or set(draft) - {"documents", "widths", "engine_options", "wolf"} or len(json.dumps(draft).encode()) > 3_500_000:
            raise ValueError("Invalid workflow draft.")
        if "documents" in draft:
            if not isinstance(draft["documents"], dict) or any(not valid_document_name(name) for name in draft["documents"]):
                raise ValueError("Invalid guidance draft.")
            for value in draft["documents"].values():
                if not isinstance(value, dict) or set(value) != {"text", "revision"} or not all(isinstance(item, str) for item in value.values()):
                    raise ValueError("Invalid guidance draft.")
        if "wolf" in draft and not isinstance(draft["wolf"], dict):
            raise ValueError("Invalid WOLF draft.")
        atomic_json(folder / "draft.json", draft)
        return {"saved": True}

    def update(self, project_id, revision, values):
        self.folder(project_id)
        project = self.projects[project_id]
        if revision != project["revision"]:
            raise ValueError("The guided project changed elsewhere. Reload before saving.")
        allowed = {"step", "done", "selected", "engine_options", "mode", "phase1_comments", "widths", "wolf"}
        if not isinstance(values, dict) or set(values) - allowed:
            raise ValueError("Unknown guided workflow setting.")
        updated = dict(project)
        for key, value in values.items():
            if key == "step" and (type(value) is not int or not 0 <= value <= (7 if project["engine"] == "ACE" else 9)):
                raise ValueError("Choose a visible workflow stage.")
            if key == "done" and (not isinstance(value, list) or any(type(item) is not int or not 0 <= item <= 9 for item in value)):
                raise ValueError("Invalid completed stages.")
            if key == "selected":
                self._names(value, [item["name"] for item in project["files"]], allow_empty=True)
            if key == "wolf":
                if not isinstance(value, dict) or set(value) != {"literal_line1_lowconf", "db_groups"} or type(value["literal_line1_lowconf"]) is not bool:
                    raise ValueError("Invalid WOLF settings.")
                from util.wolfdawn.db_classify import analyze_content_distribution
                groups = [g.key for g in analyze_content_distribution(self.folder(project_id) / "files").groups]
                self._names(value["db_groups"], groups, allow_empty=True)
            if key == "engine_options":
                value = {**project["engine_options"], **validate_engine_options({"rpgmakermvmz": value})["rpgmakermvmz"]}
            if key == "widths":
                if not isinstance(value, dict) or set(value) != {"width", "faceWidth", "listWidth", "noteWidth"} or any(type(v) is not int or not 20 <= v <= 300 for v in value.values()):
                    raise ValueError("Line widths must be whole numbers from 20 to 300.")
                value = normalize_wrap_widths(value)
            if key == "mode" and value not in {"translate", "batch", "estimate", "offline"}:
                raise ValueError("Choose a translation mode.")
            if key == "phase1_comments" and type(value) is not bool:
                raise ValueError("Comment translation must be enabled or disabled.")
            updated[key] = value
        if "wolf" in values:
            from util.wolfdawn import db_classify as db
            work = Path(project["source"]) / "wolf_json"
            regular(Path(project["source"]), work / "db_profile.json")
            distribution = db.analyze_content_distribution(self.folder(project_id) / "files")
            profile = db.load_db_profile(work)
            selected = set(updated["wolf"]["db_groups"])
            profile.update(archetype=distribution.archetype,
                           foundation_groups=[g.key for g in distribution.groups if g.key in selected and g.tier != db.TIER_NARRATIVE],
                           narrative_groups=[g.key for g in distribution.groups if g.key in selected and g.tier == db.TIER_NARRATIVE],
                           defer_groups=[g.key for g in distribution.groups if g.key not in selected])
            db.save_db_profile(work, profile)
        if "widths" in values:
            save_game_wrap_widths(project["source"], updated["widths"])
        updated["revision"] += 1
        self.projects[project_id] = updated
        self.save(updated)
        return self.state(project_id)

    @staticmethod
    def _names(names, available, *, allow_empty=False):
        if not isinstance(names, list) or not allow_empty and not names or any(not isinstance(name, str) or name not in available for name in names) or len(set(names)) != len(names):
            raise ValueError("Select files from this project's current list.")

    def preview(self, project_id, action, options):
        folder = self.folder(project_id)
        project = self.projects[project_id]
        if action not in LABELS or not isinstance(options, dict):
            raise ValueError("Unknown guided action.")
        project = {**project, **describe_game(project["source"])}
        current_names = [item["name"] for item in project["files"]]
        selected = {}
        if action.startswith("wolf_"):
            from .wolf import prepare_options
            if project["engine"] != "WOLF":
                raise ValueError("This action requires a WOLF project.")
            selected = prepare_options(action, options, project, folder)
        if action == "import":
            self._names(options.get("files"), current_names)
            selected["files"] = options["files"]
        if action.startswith("rewrap_"):
            self._names(options.get("files"), current_names)
            from util.rpgmaker_rewrap import ALL_CATEGORIES, parse_event_codes
            categories = options.get("categories", list(ALL_CATEGORIES))
            if not isinstance(categories, list) or not categories or any(value not in ALL_CATEGORIES for value in categories):
                raise ValueError("Choose at least one rewrap category.")
            codes = options.get("codes", "401,405")
            parse_event_codes(codes)
            rows = options.get("max_rows", 4)
            if type(rows) is not int or not 1 <= rows <= 100:
                raise ValueError("Choose a protected row limit from 1 to 100.")
            widths = options.get("widths", project["widths"])
            if not isinstance(widths, dict) or set(widths) != {"width", "faceWidth", "listWidth", "noteWidth"} or any(type(value) is not int or not 20 <= value <= 300 for value in widths.values()):
                raise ValueError("Line widths must be whole numbers from 20 to 300.")
            selected = {"files": options["files"], "widths": normalize_wrap_widths(widths), "categories": categories, "codes": codes, "max_rows": rows,
                        "protect_rows": options.get("protect_rows", True) is True, "over_limit": options.get("over_limit", False) is True}
        if action.startswith("qa_"):
            from util.skills import RPGMAKER_QA_FOCUSES
            if options.get("focus") not in dict(RPGMAKER_QA_FOCUSES):
                raise ValueError("Choose an existing QA focus.")
            selected["focus"] = options["focus"]
        if action.startswith(("playtest_", "inspector_", "forge_")) and action != "playtest_status":
            values = SettingsStore(self.workspace).read()["values"]
            selected["playtest"] = {"hotkey": values["tlHotkey"], "forgeHotkey": values["forgeHotkey"],
                                    "uiScale": values["playtestUiScale"], "editorCmd": values["tlEditorCmd"], "workspaceFolder": "auto"}
        if action == "release":
            from util.release_package import normalize_release_zip_path
            output = normalize_release_zip_path(options.get("output", ""))
            if not str(options.get("output", "")).strip() or output.is_relative_to(Path(project["source"])) or output.is_relative_to(self.workspace):
                raise ValueError("Save the release ZIP outside the game and desktop workspace.")
            selected["output"] = str(output)
        if action == "git_setup":
            selected = {"version": str(options.get("version", "")).strip(), "untranslated": options.get("untranslated") is True,
                        "original": str(Path(options["original"]).expanduser().resolve(strict=True)) if options.get("original") else ""}
        if action in {"reference_add", "reference_pair"}:
            title = str(options.get("title", "")).strip()
            if not title or len(title) > 200:
                raise ValueError("Enter a short reference title.")
            if not str(options.get("translated", "")).strip() or action == "reference_pair" and not str(options.get("original", "")).strip():
                raise ValueError("Choose the reference folder or both folders for a pair.")
            selected = {"title": title, "translated": str(Path(options.get("translated", "")).expanduser().resolve(strict=True))}
            if action == "reference_pair":
                selected["original"] = str(Path(options.get("original", "")).expanduser().resolve(strict=True))
        if action == "reference_remove":
            from util.reference_games import load_registry
            if options.get("id") not in {row["id"] for row in load_registry(project["source"])["references"]}:
                raise ValueError("Select a registered reference game.")
            selected = {"id": options["id"]}
        if action in {"prepare", "gameupdate"}:
            # Only public updater configuration belongs in this helper file.
            values = SettingsStore(self.workspace).read()["values"]
            public = {key: value for key, value in values.items() if key.startswith("gameUpdate")}
            selected["public_settings"] = public
        token = uuid.uuid4().hex
        plan = {"project_id": project_id, "project": project, "folder": str(folder), "action": action, "options": selected,
                "label": LABELS[action], "guard": action_guard(project, folder)}
        if action == "release":
            path = Path(selected["output"])
            plan["output_hash"] = digest(path.read_bytes()) if path.is_file() else None
        self.previews = {token: plan}  # A newer preview invalidates the earlier confirmation.
        destination = str(folder / "files") if action == "import" else selected.get("output") or project["source"]
        return {"token": token, "label": plan["label"], "destination": destination, "confirmation": action not in READ_ONLY,
                "files": len(selected.get("files", [])), "options": selected,
                "overwrite": action == "release" and plan.get("output_hash") is not None}

    def execute(self, token):
        plan = self.previews.pop(token, None)
        if not plan:
            raise ValueError("This preview expired. Preview the action again.")
        validate_plan(plan)
        return self.operations.start(plan)

    def documents(self, project_id):
        self.folder(project_id)
        return documents(self.projects[project_id]["source"])

    def document_save(self, project_id, name, revision, text):
        self.folder(project_id)
        return document_save(self.projects[project_id]["source"], name, revision, text)

    def skill(self, project_id, name):
        self.folder(project_id)
        project = self.projects[project_id]
        from util.skills import load_project_setup, load_clipboard_skill, load_walkthrough_skill, load_rpgmaker_qa_skill, build_known_speakers_context
        if name == "setup":
            text = self.documents(project_id)["glossary"]["text"]
            from util.reference_games import setup_reference_note
            pairs = []
            for header in ("Game Characters", "Speakers"):
                match = re.search(rf"^[\t ]*#\s*{header}\s*$\r?\n(.*?)(?=^[\t ]*#|\Z)", text, re.M | re.S)
                if match:
                    pairs.extend(re.findall(r"^[\t ]*(.+?)\s+\((.+?)\)[\t ]*$", match.group(1), re.M))
            engine = "wolf" if project["engine"] == "WOLF" else "rpgmaker"
            return load_project_setup(engine, prepend=build_known_speakers_context(engine, pairs) + ("" if engine == "wolf" else setup_reference_note(project["source"], project["data"])))
        if name == "walkthrough":
            return load_walkthrough_skill(project["source"], "WOLF RPG" if project["engine"] == "WOLF" else "RPG Maker " + project["engine"])
        if name == "qa":
            return load_rpgmaker_qa_skill("release")
        files = {"wolf_speakers": "wolf_speakers.md", "advanced": "risky_codes.md", "wrap": "wrap_config.md", "investigation": "localization_investigation.md",
                 "plugins": "ace_script_translation.md" if project["engine"] == "ACE" else "plugin_translation.md"}
        if name not in files:
            raise ValueError("Unknown workflow skill.")
        return f"Selected game: `{project['source']}`\nData folder: `{project['data']}`\n\n" + load_clipboard_skill(files[name])

    def phase(self, project_id, phase, sync):
        folder = self.folder(project_id)
        project = self.projects[project_id]
        self._collect(project)
        if project.get("collection_error"):
            raise ValueError(project["collection_error"])
        allowed = {"names", "database", "foundation", "narrative", "db_selected", "maps"} if project["engine"] == "WOLF" else {"database", "dialogue", "variables", "advanced", "speakers"}
        if phase not in allowed:
            raise ValueError("Choose an existing translation phase.")
        if type(sync) is not bool:
            raise ValueError("Choose whether to sync completed translations before this phase.")
        if sync:
            for path in (folder / "translated").glob("*.json"):
                if (folder / "files" / path.name).is_file():
                    regular(folder, path)
                    regular(folder, folder / "files" / path.name)
                    shutil.copyfile(path, folder / "files" / path.name)
        if project["engine"] == "WOLF":
            return self._wolf_phase(project, phase)
        inventory = self.manual.inspect(folder / "files", "RPG Maker MV/MZ", managed=True)
        files = [row["name"] for row in inventory["files"] if row["name"] in DB_FILES] if phase == "database" else [
            row["name"] for row in inventory["files"] if row["name"] in EVENT_FILES_EXACT or re.fullmatch(r"Map\d+\.json", row["name"])]
        if not files:
            raise ValueError("Import files belonging to this phase in Project first.")
        settings = dict(project["engine_options"])
        profile = {"database": PHASE0_CONFIG, "dialogue": PHASE1_CONFIG, "variables": PHASE1B_CONFIG, "advanced": PHASE2_CONFIG}.get(phase, {})
        if phase == "advanced":
            advanced_codes = {"CODE122", "CODE357", "CODE355655", "CODE657", "CODE356", "CODE320", "CODE324", "CODE325", "CODE108"}
            profile = {**profile, **{key: value for key, value in settings.items() if key in advanced_codes}}
        settings.update(profile)
        if phase == "dialogue":
            settings["CODE408"] = project["phase1_comments"]
        mode = "speakers" if phase == "speakers" else project["mode"]
        job = self.manual.start(str(folder / "files"), "RPG Maker MV/MZ", files, inventory["revision"], mode, project["source"],
                                workflow={"id": project_id, "phase": phase, "engine_options": settings, "widths": project["widths"],
                                          "glossary_revision": self.documents(project_id)["glossary"]["revision"]})
        project["manual_job"] = job["id"]
        self.save(project)
        return job

    def _wolf_phase(self, project, phase):
        from .wolf import manifest
        from util.wolfdawn import db_classify as db
        folder = self.folder(project["id"])
        value = manifest(Path(project["source"]))
        if not value:
            raise ValueError("Extract and import WOLF text first.")
        kinds = {e["json"]: e["kind"] for e in value["entries"]}
        target = {"names"} if phase == "names" else {"map", "common", "gamedat", "txt", "txt-dir"} if phase == "maps" else {"db"}
        inventory = self.manual.inspect(folder / "files", "Wolf RPG (WolfDawn)", managed=True)
        files = [row["name"] for row in inventory["files"] if kinds.get(row["name"]) in target]
        if not files:
            raise ValueError("Import files belonging to this phase first.")
        groups = []
        if phase in {"foundation", "narrative"}:
            distribution = db.analyze_content_distribution(folder / "files")
            tiers = frozenset({db.TIER_NARRATIVE}) if phase == "narrative" else db.FOUNDATION_TIERS
            groups = db.selected_groups_for_tiers(distribution.groups, tiers)
        if phase == "db_selected":
            groups = project["wolf"]["db_groups"]
        if phase in {"foundation", "narrative", "db_selected"} and not groups:
            raise ValueError("No database sheets match this selection.")
        job = self.manual.start(str(folder / "files"), "Wolf RPG (WolfDawn)", files, inventory["revision"], project["mode"], project["source"],
            workflow={"id": project["id"], "phase": phase, "widths": project["widths"], "engine_options": {},
                      "wolf_speakers": {"literal_line1_lowconf": project["wolf"]["literal_line1_lowconf"]},
                      "environment": {"wolfDbIncludeGroups": json.dumps(groups, ensure_ascii=False) if groups else "", "wolfDbIncludeTiers": ""},
                      "glossary_revision": self.documents(project["id"])["glossary"]["revision"]})
        project["manual_job"] = job["id"]
        self.save(project)
        return job

    def _collect(self, project):
        identity = project.get("manual_job")
        job = self.manual.jobs.get(identity)
        if not job or job["status"] != "complete" or self.manual.running() or identity in project["collected"]:
            return
        try:
            folder, source = self.folder(project["id"]), self.manual.folder(identity)
            plan = json.loads((source / "plan.json").read_text(encoding="utf-8"))
            if digest((source / "plan.json").read_bytes()) != job["plan_hash"] or plan["workflow"]["id"] != project["id"]:
                raise ValueError("The completed phase's saved plan changed.")
            if job["mode"] != "estimate":
                for name, expected in job["outputs"].items():
                    if Path(name).name != name or file_digest(source, source / "translated" / name) != expected:
                        raise ValueError("A completed phase output changed. Its original saved run is retained.")
                from util.vocab import _split_base
                glossary = _split_base((source / "game/.dazedtl/glossary.txt").read_text(encoding="utf-8"))[0].rstrip("\n")
                current = self.documents(project["id"])["glossary"]
                if glossary != current["text"]:
                    if current["revision"] != plan["workflow"]["glossary_revision"]:
                        raise ValueError("The game glossary changed during this phase. Review the run's glossary before continuing; both copies are retained.")
                    self.document_save(project["id"], "glossary", current["revision"], glossary)
                for name in job["outputs"]:
                    shutil.copyfile(source / "translated" / name, regular(folder, folder / "translated" / name))
                cache = source / "log/var_translation_map.json"
                if cache.is_file():
                    regular(source, cache)
                    shutil.copyfile(cache, regular(folder, folder / "log/var_translation_map.json"))
            project["collected"].append(identity)
            project["collection_error"] = ""
        except (ValueError, OSError, KeyError) as exc:
            project["collection_error"] = str(exc)
        self.save(project)


def file_digest(root, path):
    return digest(regular(root, path).read_bytes())
