"""Editable shared instructions stored in the desktop profile, never the package."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
from string import Formatter
import tempfile

from util.paths import DATA_DIR, runtime_data_file
from .project import atomic_json, digest


def read_text(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1_000_000:
        raise ValueError("Choose a regular instruction file below 1 MB.")
    return path.read_text(encoding="utf-8-sig")


def validate_instruction(name, text, default):
    if not isinstance(text, str) or not text.strip() or "\x00" in text or len(text.encode("utf-8")) > 1_000_000:
        raise ValueError("Instructions must contain text below 1 MB without null characters.")
    if name == "translation_contexts.json":
        try:
            value, original = json.loads(text), json.loads(default)
            def validate(current, reference, key="contexts"):
                if isinstance(reference, dict):
                    if not isinstance(current, dict) or set(current) != set(reference):
                        raise ValueError(f"Keep the existing keys in {key}.")
                    for name, item in reference.items():
                        validate(current[name], item, key + "." + name)
                elif isinstance(reference, str):
                    if not isinstance(current, str) or not current.strip():
                        raise ValueError(f"{key} must contain an instruction.")
                    fields = lambda template: {(field, spec, conversion) for _, field, spec, conversion in Formatter().parse(template) if field is not None}
                    if fields(current) != fields(reference):
                        raise ValueError(f"Keep the existing format placeholders in {key}.")
                elif type(current) is not type(reference) or current != reference:
                    raise ValueError(f"Keep the supported {key} value.")
            validate(value, original)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Translation contexts must be a valid JSON object.") from exc
        return json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if name.endswith(".md"):
        # These tokens connect shared prompts to engine-specific context. Text
        # around them remains editable; dropped/duplicated tokens break handoffs.
        pattern = r"\{\{[A-Z][A-Z0-9_]*\}\}|<!--\s*/?(?:engine:[\w-]+|qa-focus:[\w-]+|investigation-phase)\s*-->"
        expected = re.findall(pattern, default)
        actual = re.findall(pattern, text)
        if Counter(expected) != Counter(actual):
            raise ValueError("Keep all template placeholders and section markers, including their original counts.")
        markers = lambda values: [value for value in values if value.startswith("<!--")]
        if markers(expected) != markers(actual):
            raise ValueError("Keep instruction section markers in their original order.")
    return text if text.endswith("\n") else text + "\n"


class InstructionLibrary:
    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.root = self.workspace / "shared-data"
        self.state = self.workspace / "shared-instructions"
        self.files = {p.relative_to(DATA_DIR).as_posix(): p for p in (DATA_DIR / "skills").glob("*.md") if p.is_file()}
        for name in ("skills/build-game-walkthrough/SKILL.md", "skills/setup-generic-game/SKILL.md", "translation_contexts.json", "glossary_base.txt"):
            self.files[name] = DATA_DIR / name

    def _path(self, name):
        if not isinstance(name, str) or name not in self.files:
            raise ValueError("Choose a shared instruction from the library.")
        return self.files[name]

    def _state_path(self, name, suffix):
        return self.state / (digest(name.encode()) + suffix)

    def catalog(self):
        titles = {"skills/system.md": "Translation system instructions", "translation_contexts.json": "Translation contexts", "glossary_base.txt": "Base glossary",
                  "skills/rpgmaker_translation_qa.md": "RPG Maker translation QA", "skills/ace_script_translation.md": "Ace script translation",
                  "skills/wolf_speakers.md": "WOLF speakers", "skills/wolf_precheck_repair.md": "WOLF precheck repair",
                  "skills/evaluation_csv_review.md": "Evaluation CSV review"}
        first = ["skills/system.md", "skills/project_setup.md", "skills/localization_investigation.md", "skills/character_identity.md", "translation_contexts.json", "glossary_base.txt"]
        return [{"name": name, "title": titles.get(name, (Path(name).parent.name if Path(name).name == "SKILL.md" else Path(name).stem).replace("_", " ").replace("-", " ").title()),
                 "customized": runtime_data_file(path, self.workspace) != path} for name, path in sorted(self.files.items(), key=lambda pair: (first.index(pair[0]) if pair[0] in first else len(first), pair[0]))]

    def get(self, name):
        bundled = self._path(name)
        path = runtime_data_file(bundled, self.workspace)
        default, text = read_text(bundled), read_text(path)
        metadata = self._state_path(name, ".json")
        record = json.loads(metadata.read_text()) if metadata.is_file() else {}
        draft_path = self._state_path(name, ".draft.json")
        draft = json.loads(draft_path.read_text()) if draft_path.is_file() else None
        bundled_hash = digest(default.encode())
        return {"name": name, "text": text, "default": default, "revision": digest((bundled_hash + text).encode()),
                "customized": path != bundled, "bundled_changed": path != bundled and record.get("bundled_hash") != bundled_hash,
                "path": str(path), "draft": draft}

    def draft(self, name, revision, text):
        self._path(name)
        if not isinstance(text, str) or len(text.encode()) > 1_000_000 or not isinstance(revision, str) or len(revision) > 128:
            raise ValueError("Invalid shared instruction draft.")
        atomic_json(self._state_path(name, ".draft.json"), {"revision": revision, "text": text})
        return {"saved": True}

    def save(self, name, revision, text):
        current = self.get(name)
        if current["revision"] != revision:
            raise ValueError("These instructions changed elsewhere. Reload before saving.")
        text = validate_instruction(name, text, current["default"])
        bundled = self._path(name)
        runtime_data_file(bundled, self.workspace)  # Check every override path component.
        destination = self.root / name
        if text == current["default"]:
            destination.unlink(missing_ok=True)
            self._state_path(name, ".json").unlink(missing_ok=True)
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary = tempfile.mkstemp(prefix=".instruction-", dir=destination.parent)
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
            atomic_json(self._state_path(name, ".json"), {"bundled_hash": digest(current["default"].encode())})
        self._state_path(name, ".draft.json").unlink(missing_ok=True)
        return self.get(name)

    def import_text(self, name, source):
        current = self.get(name)
        return {"text": validate_instruction(name, read_text(Path(source).expanduser()), current["default"])}
