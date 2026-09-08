"""Prepare Len's game-translation skill and an explicit, resumable AI handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

from util.paths import (
    DATA_DIR, GLOSSARY_BASE_SEPARATOR, SKILLS_DIR, game_glossary_path,
    prepare_game_translation_context, read_game_glossary,
)
from util.skills import load_generic_project_setup, load_system_prompt
from util.reference_games import load_registry, reference_context


BUNDLED_SKILL = SKILLS_DIR / "game-translation"
WORKSPACE_RELATIVE = Path(".dazedtl") / "len-method"
_WORK_GITIGNORE = """# Version authored tools, translation records and QA notes; keep runtime data local.
*
!*/
!.gitignore
!.gitattributes
!*.md
!*.txt
!*.json
!*.jsonl
!*.csv
!*.tsv
!*.py
!*.js
!*.cjs
!*.mjs
!*.cs
!*.csproj
!*.csx
!*.c
!*.h
!*.cpp
!*.rs
!*.toml
!*.yaml
!*.yml
!*.ps1
!*.sh
!*.bat
!*.cmd
!*.rb
!*.gml
!*.lua
!*.rpy
!*.ks
!*.tjs
!*.html
!*.css
!*.svg
!*.ini
!*.cfg
!*.sln
!*.resx
!*.def
.env
.env.*
api_keys.json
*_key.txt
*_keys.txt
__pycache__/
.venv/
venv/
node_modules/
cache/
logs/
bin/
obj/
target/
"""
_WORK_IGNORE_BEGIN = "# BEGIN DazedTL Len project work"
_WORK_IGNORE_END = "# END DazedTL Len project work"
_WORK_IGNORE_BLOCK = f"""{_WORK_IGNORE_BEGIN}
.env
.env.*
.api_key
api_keys.json
*_key.txt
*_keys.txt
.venv/
venv/
__pycache__/
node_modules/
saves/
save/
logs/
cache/
!/.dazedtl/len-method/
/.dazedtl/len-method/*
!/.dazedtl/len-method/project.json
!/.dazedtl/len-method/status.md
!/.dazedtl/len-method/work/
{_WORK_IGNORE_END}
"""
STAGES = {
    "translate": "Translate the whole game",
    "prepare": "Prepare extraction and guidance",
    "continue": "Continue existing work",
    "qa": "Review and fix the translation",
}
MODES = {
    "local": "AI assistant translates directly",
    "api": "Use a translation API",
}


@dataclass(frozen=True)
class LenProject:
    game_root: Path
    stage: str = "translate"
    mode: str = "local"
    include_images: bool = True
    instructions: str = ""
    include_glossary_base: bool = True

    @property
    def workspace(self) -> Path:
        return self.game_root / WORKSPACE_RELATIVE

    @property
    def legacy_skill_root(self) -> Path:
        """Preserve adaptations made by the initial ZIP-based integration."""
        return self.workspace / "game-translation"

    @property
    def work_root(self) -> Path:
        return self.workspace / "work"


def _validate_project(project: LenProject) -> None:
    if not project.game_root.is_absolute() or not project.game_root.is_dir():
        raise ValueError("Choose an existing game folder.")
    if project.stage not in STAGES or project.mode not in MODES:
        raise ValueError("Choose a supported task and translation mode.")
    if type(project.include_images) is not bool or type(project.include_glossary_base) is not bool:
        raise ValueError("Image scope and base glossary must be enabled or disabled.")
    if not isinstance(project.instructions, str):
        raise ValueError("Project instructions must be text.")
    # Do not write through project metadata symlinks into unrelated locations.
    for path in (project.game_root / ".dazedtl", project.workspace, project.work_root):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError(f"The Len workspace must use normal directories: {path}")


def load_project(game_root: Path) -> LenProject:
    game_root = game_root.expanduser().resolve()
    _validate_project(LenProject(game_root))
    path = game_root / WORKSPACE_RELATIVE / "project.json"
    if not path.exists():
        project = LenProject(game_root)
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") not in {1, 2}:
            raise ValueError("Unsupported Len project settings version.")
        # Resolve against the selected game so a moved folder remains portable.
        project = LenProject(game_root, include_glossary_base=data.get("include_glossary_base", True), **{key: data[key] for key in (
            "stage", "mode", "include_images", "instructions"
        )})
    _validate_project(project)
    return project


def _validate_skill(root: Path) -> None:
    for relative in ("SKILL.md", "scripts/check_tools.py", "tools/THIRD-PARTY.md"):
        if not (root / relative).is_file() or (root / relative).is_symlink():
            raise ValueError(f"Incomplete game-translation skill: missing {relative}")
    if not (root / "references").is_dir():
        raise ValueError("Incomplete game-translation skill: missing references/")


def shared_context(project: LenProject) -> dict:
    """Read the same portable guidance used by Workflow, without changing process settings."""
    _validate_project(project)
    prepare_game_translation_context(project.game_root)
    glossary = read_game_glossary(project.game_root)
    custom = glossary.split(GLOSSARY_BASE_SEPARATOR, 1)[0].rstrip()
    # The shared editor owns the custom section; refreshed shipped defaults are derived.
    base = DATA_DIR / "glossary_base.txt"
    glossary = custom + "\n"
    if project.include_glossary_base and base.is_file():
        glossary += "\n" + GLOSSARY_BASE_SEPARATOR + base.read_text(encoding="utf-8")
    context = {
        "schema": 1,
        "game_root": str(project.game_root),
        "system": load_system_prompt(project.game_root),
        "glossary": glossary,
        "glossary_file": str(game_glossary_path(project.game_root, migrate=False)),
        "skills_folder": str(project.game_root / ".dazedtl" / "skills"),
        "include_glossary_base": project.include_glossary_base,
        "references": load_registry(project.game_root),
    }
    context["content_sha256"] = hashlib.sha256(
        json.dumps(context, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return context


def request_context(project: LenProject, sources: list[str] | dict[str, str], *,
                    instruction_key: str | None = None, source_context: str = "") -> dict:
    """Compile one batch with DazedTL's actual glossary/SFX matching and current instructions.

    No provider calls. Pipelines consume these fields directly instead of rebuilding prompts.
    """
    from util.skills import ctx
    from util.translation import createContextParts

    values = list(sources.values()) if isinstance(sources, dict) else sources
    if not isinstance(values, list) or not values or not all(isinstance(value, str) and value for value in values):
        raise ValueError("Sources must be a nonempty JSON list of strings or an ID-to-string object.")
    if isinstance(sources, dict) and not all(isinstance(key, str) and key for key in sources):
        raise ValueError("Source IDs must be nonempty strings.")
    shared = shared_context(project)
    payload = json.dumps(sources, ensure_ascii=False)
    config = SimpleNamespace(prompt=shared["system"], vocab=shared["glossary"], language="English", useSfxReference=True)
    system, glossary, sfx, user = createContextParts(config, payload, "json")
    result = {
        "schema": 1, "context_sha256": shared["content_sha256"],
        "system": system, "glossary": glossary, "sfx_reference": sfx,
        "request_instructions": ctx(instruction_key, language="English", context=source_context) if instruction_key else "",
        "preceding_japanese_source_context": source_context,
        "user": user,
        "reference_translations": reference_context(project.game_root, values),
    }
    result["request_sha256"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return result


def import_glossary(project: LenProject, document: dict) -> dict:
    """Merge Len's names/en or legacy characters/name schema into the shared glossary.

    Existing decisions are preserved. Any conflicting source/alias aborts the entire import.
    Non-display identifiers remain extraction metadata in the original JSON, never prompt rows.
    """
    from util.translation import parseVocabWithCategories, split_vocab_source_aliases
    from util.vocab import read_game_vocab, write_game_vocab

    _validate_project(project)
    if not isinstance(document, dict):
        raise ValueError("The imported glossary must be a JSON object.")
    if "names" in document and "characters" in document:
        raise ValueError("Use one name schema: names or characters, not both.")
    names = document.get("names", document.get("characters", {}))
    terms = document.get("terms", {})
    if not isinstance(names, dict) or not isinstance(terms, dict) or not (names or terms):
        raise ValueError("Expected nonempty names/characters or terms objects.")

    def one_line(value, label):
        if not isinstance(value, str) or not value.strip() or any(char in value for char in "\r\n\0"):
            raise ValueError(f"{label} must be nonempty single-line text.")
        return value.strip()

    protected_pairs = set()
    pairs = document.get("do_not_merge", [])
    if not isinstance(pairs, list):
        raise ValueError("do_not_merge must be a list of Japanese name pairs.")
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or not all(isinstance(item, str) for item in pair):
            raise ValueError("do_not_merge must contain pairs of Japanese names.")
        protected_pairs.add(frozenset(one_line(item, "Protected identity") for item in pair))
    candidates: dict[str, tuple[str, str, str]] = {}

    def add(source, target, notes, category):
        source = one_line(source, "Japanese source")
        target = one_line(target, "English target")
        parsed = parseVocabWithCategories(f"{category}\n{source} ({target})")
        if not parsed or parsed[0][0] != (source, target):
            raise ValueError(f"Cannot represent {source} ({target}) in the shared glossary format.")
        aliases = split_vocab_source_aliases(source) if category == "# Game Characters" else [source]
        if any(pair.issubset(aliases) for pair in protected_pairs):
            raise ValueError(f"Give protected identities in {source} separate name entries.")
        for alias in aliases:
            if alias in candidates and candidates[alias][0] != target:
                raise ValueError(f"The imported glossary has conflicting translations for {alias}.")
            candidates.setdefault(alias, (target, notes, category))

    for source, info in names.items():
        one_line(source, "Japanese name")
        if not isinstance(info, dict):
            raise ValueError(f"Name {source} must have a structured entry.")
        target = info.get("en", info.get("name"))
        notes = []
        for key in ("gender", "role", "register", "speech", "personality", "note"):
            if info.get(key):
                notes.append(f"{key}: {one_line(info[key], key)}")
        if str(info.get("gender", "")).casefold() == "unknown":
            notes.append("Do not infer gender; preserve any deliberate uncertainty.")
        add(source, target, "; ".join(notes), "# Game Characters")
        aliases = info.get("aliases", [])
        if not isinstance(aliases, list):
            raise ValueError(f"Aliases for {source} must be a list.")
        for alias in aliases:
            alias = one_line(alias, "Alias")
            if alias in names:
                continue  # Public and revealed identities retain their own named rows.
            if frozenset((source, alias)) in protected_pairs:
                raise ValueError(f"Give protected identity {alias} its own name entry before importing.")
            add(alias, target, "; ".join(notes), "# Game Characters")
    for source, target in terms.items():
        add(source, target, "", "# Game Terms")

    current = read_game_vocab(project.game_root, create=False)
    existing: dict[str, str] = {}
    for pair, _line, category in parseVocabWithCategories(current):
        if not isinstance(pair, tuple):
            continue
        source, target = pair
        aliases = split_vocab_source_aliases(source) if category in {"# Game Characters", "# Speakers"} else [source]
        for alias in aliases:
            if alias in existing and existing[alias] != target:
                raise ValueError(f"Resolve conflicting existing glossary entries for {alias} first.")
            existing[alias] = target
    conflicts = [source for source, (target, *_rest) in candidates.items() if source in existing and existing[source] != target]
    if conflicts:
        raise ValueError("Import conflicts with the shared glossary: " + ", ".join(conflicts))
    additions = {source: entry for source, entry in candidates.items() if source not in existing}
    if additions:
        pieces = [current.rstrip()]
        for category in ("# Game Characters", "# Game Terms"):
            rows = [f"{source} ({target})" + (f" - {notes}" if notes else "")
                    for source, (target, notes, owner) in additions.items() if owner == category]
            if rows:
                pieces.append(category + "\n" + "\n".join(rows))
        write_game_vocab("\n\n".join(pieces) + "\n", project.game_root)
    return {"added": len(additions), "preserved": len(candidates) - len(additions),
            "glossary_file": str(game_glossary_path(project.game_root, migrate=False)),
            "extraction_metadata": document.get("do_not_translate", [])}


def build_handoff(project: LenProject, skill_root: Path = BUNDLED_SKILL) -> str:
    _validate_project(project)
    task = {
        "translate": "Carry the game through extraction, translation, injection, layout fixes, in-game QA and a local translation patch.",
        "prepare": "Preparation only: inspect the engine, extract and audit the corpus, and prepare the glossary, game bible, prompt and validation plan. Stop before translation, injection or API-driver implementation.",
        "continue": "Read the existing status and artifacts, verify what has already been completed, and resume the remaining translation, injection, layout, QA and patch work without discarding valid progress.",
        "qa": "Review the existing translated game against its source. Repair confirmed omissions, translation errors, layout issues and patch defects; re-inject affected outputs and validate them in game.",
    }[project.stage]
    mode = (
        "Translate directly with the AI assistant. No translation API calls, API-driver setup or hosted image generation are authorized by this handoff. Local extraction, image lettering, measurement and patch tools are allowed."
        if project.mode == "local" else
        "Use a translation API selected and configured with the user. Reuse the chosen provider/model and budget; if these are not established, ask before paid calls. Keep keys out of prompts, logs and project artifacts."
    )
    images = (
        "Include all images containing player-facing Japanese text: inventory archives, UI states and animation frames, translate and fit their text, and validate the resulting assets in game. This explicitly opts into the skill's image-translation scope."
        if project.include_images else
        "Image translation is excluded. Report known baked Japanese labels separately; do not replace images or claim whole-game coverage while those labels remain."
    )
    return f"""Use Len's game-translation skill to translate this Japanese game into English.

Game folder: {json.dumps(str(project.game_root), ensure_ascii=False)}
Skill entrypoint: {json.dumps(str(skill_root / 'SKILL.md'), ensure_ascii=False)}
Workspace: {json.dumps(str(project.workspace), ensure_ascii=False)}
DazedTL application: {json.dumps(str(DATA_DIR.parent), ensure_ascii=False)}

Read the skill entrypoint first and resolve its references/ and tools/ relative to that file. DAZEDTL_ROOT means the application folder above. Use its live code when a reference points there. Run the skill's scripts/check_tools.py with {json.dumps(sys.executable)}. Copy only tools you need to this project's workspace before adapting or running code that writes beside itself. Historical game paths in examples are not this project's paths.

Task: {task}

Before changing game files, complete the project lifecycle in references/project-lifecycle.md from Len's skill. Inspect Git with this application command (argument array):
{json.dumps([sys.executable, str(DATA_DIR.parent / 'scripts/len_translation.py'), 'git-status', '--game-root', str(project.game_root)], ensure_ascii=False)}
Set up or reuse local version tracking with the same script's git-setup command. A new baseline requires --original <verified clean game folder> and --version <release label>. Use this game as its own original only when it is verified untouched and translation has not begun; continuing or QA without a baseline requires a separate clean original. Verify the version from local evidence, or label an unversioned snapshot initial-unversioned and record that limitation. The helper uses the shared Workflow backend, preserves native game bytes, and records that policy for later official updates. It preserves existing branch names/history and refuses ambiguous parent repositories, wrong branches, dirty reconciliation, and unfinished Git operations. Do not work around a refusal by resetting, discarding, relabeling translated files as original, or changing unrelated repository state. Resolve the actual prerequisite; request a clean original location if none is available. This local Git setup and reviewed local checkpoints are part of the selected task; remote creation, pushing and publishing require a separate user request.

Before the first baseline, review the game's .gitignore and .gitattributes against the actual engine: include the game text and patch inputs that need protection, exclude secrets, saves, caches and unrelated bulk assets, and preserve engine-required bytes and line endings (use scoped -text rules where appropriate). The Len Git mode does not impose Workflow's file-extension allowlist or reformat game payloads. Keep an untouched original copy as well; Git's ignored-asset inventory is not a backup of those bytes. After setup, verify both baseline commits, the active translated branch and the files actually tracked before translating.

Translation mode: {mode}

Image scope: {images}
For preparation-only work, document the selected image scope in the plan; do not render or inject replacements yet.

Shared guidance is authoritative for BOTH Len's Method and Workflow:
- {json.dumps(str(project.game_root / '.dazedtl/glossary.txt'))}: names, terms, character identity and individual voices.
- {json.dumps(str(project.game_root / '.dazedtl/skills/game.md'))}: compact game frame.
- {json.dumps(str(project.game_root / '.dazedtl/skills/quirks.md'))}: cross-cutting voice and anchored recurring motifs.
- Other .dazedtl/skills/*.md: user-authored custom instructions.

Read {json.dumps(str(project.workspace / 'setup.md'))} for the shared setup and investigation procedure. On a new project, establish the extraction corpus, then complete that guidance phase before translation. On resume or QA, audit existing guidance against changed evidence and preserve valid decisions. Additional routes, synopsis and research notes belong under this workspace; do not create another authoritative glossary.json or duplicate character and quirks rules in a game bible.

This is the complete starting prompt for the selected task. Create any missing glossary, game frame and quirks from the reviewed source as part of this run. The guidance-only write boundary in setup.md applies to that phase; after completing it, continue with the selected task. A preparation-only task ends after preparation. Read the referenced files yourself and use the shared project files in place; the user does not need to copy guidance between tabs or supply another setup prompt.

The current assembled context is {json.dumps(str(project.workspace / 'context.json'))}. Its system field is produced by the SAME loader as Workflow, including the current shared system prompt, game frame, quirks and custom skills. Do not substitute a bundled example's prompt. Refresh after guidance edits with the application command:
{json.dumps([sys.executable, str(DATA_DIR.parent / 'scripts/len_translation.py'), 'context', '--game-root', str(project.game_root)], ensure_ascii=False)}
Command examples are argument arrays, not shell strings. For each translation batch, add --sources <JSON file containing a list of Japanese strings or an ID-to-Japanese-string object> and optionally --output <request-context.json>. Use the returned system, matched glossary, advisory SFX, source context, and advisory reference translations in direct translation or the pipeline's provider request. Keep the pipeline's required output schema. --instruction-key selects a shared field template when appropriate; --source-context supplies a text file of preceding untranslated Japanese. The request fingerprint binds retries/reviews to their source and guidance; preserve it with results and revalidate reuse after guidance changes. Context compilation performs no API calls.

Registered reference games are listed in context.json. Exact source matches are supplied by the same reference index as Workflow when --sources is provided. Build the source list from reviewed extraction units; never infer matches from unrelated files. Treat past translations as advisory evidence and resolve disagreements against current source and curated guidance.

If the user's instructions name prequels, previous translations or a reference-corpus folder, read references/reference-translations.md from Len's skill and handle those references within this run. Inspect every specified game's existing terminology and aligned Japanese/English corpus before finalizing guidance. Reuse established names and terms where the current source supports the same meaning, and record the selected decisions in this game's shared glossary so they also apply inside new dialogue. Keep reference files read-only, preserve provenance and competing spellings, and resolve conflicts against explicit user priorities, the current source and curated guidance. Register supported aligned pairs in this project's shared reference registry for additional per-batch exact matches. The user can provide reference paths in these instructions without configuring the reference dialog.

If you already have a Len JSON glossary, use the shared import bridge in scripts/len_translation.py import-glossary --game-root <game> --input <glossary.json>. It rejects conflicting names instead of silently overwriting existing decisions. Keep the original JSON as an archive; all subsequent edits belong in the shared guidance files. Existing tools and notes under {json.dumps(str(project.legacy_skill_root))}, if present, are preserved legacy adaptations; inspect and reuse relevant work, but use the current shared guidance contract above.

Cover dialogue, choices, names, database descriptions, menus, plugin/script text and runtime-generated player-facing labels. Distinguish display text from internal identifiers. Preserve control codes, placeholders, archive structure and save compatibility.

Preserve a recoverable source before changing game files. Put authored scripts, reviewed translation records, prequel provenance and QA notes in {json.dumps(str(project.work_root), ensure_ascii=False)} or existing versioned project folders. This work/ directory and the scope/status files are eligible for Git; generated prompts/context, caches, raw snapshots and API state outside work/ remain local. Check the work/ ignore policy when adding a new source format. Export database-backed translation stores to stable text records there so checkpoints protect completed translations. Preserve legacy adaptations and migrate useful authored work deliberately. After each validated milestone, review the diff and commit only the selected project files on the registered translation branch, preserving unrelated staged or working changes. Maintain {json.dumps(str(project.workspace / 'status.md'), ensure_ascii=False)} with the baseline and checkpoint commits, completed steps, artifact paths, measured coverage, unresolved issues and the next action. On resume, verify artifact and context fingerprints before reusing results. The presence of a handoff or a successful extraction is not evidence of completion.

Validate coverage independently of the extractor, placeholders, fonts, text width and row counts, injected output, and actual in-game scenes. Report string coverage, image coverage, and playtested scenes separately. Never claim 100% translation from string counts alone; record inaccessible content, excluded assets and untested scenes explicitly. If this environment cannot launch the game, leave that verification pending and give the user precise playtest steps. Re-inject before packaging. Build a local patch with installation instructions after the applicable QA gates pass; uploading or publishing is a separate user action.

Additional project instructions:
{project.instructions.strip() or '(none)'}
"""


def _write_atomic(path: Path, text: str) -> None:
    if path.is_symlink():
        raise ValueError(f"Refusing to replace a symlink: {path}")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", errors="surrogateescape", dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(text)
            handle.close()
            if path.exists():
                temporary.chmod(path.stat().st_mode)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def _prepare_versioned_work(project: LenProject) -> None:
    """Expose authored project work without tracking generated context or credentials."""
    ignore = project.game_root / ".gitignore"
    text = ignore.read_text(encoding="utf-8", errors="surrogateescape") if ignore.exists() else ""
    if text.count(_WORK_IGNORE_BEGIN) != text.count(_WORK_IGNORE_END) or text.count(_WORK_IGNORE_BEGIN) > 1:
        raise ValueError("The Len project .gitignore block is incomplete or duplicated.")
    if _WORK_IGNORE_BEGIN in text:
        start = text.index(_WORK_IGNORE_BEGIN)
        end = text.index(_WORK_IGNORE_END) + len(_WORK_IGNORE_END)
        if end < start:
            raise ValueError("The Len project .gitignore block is out of order.")
        updated = text[:start] + _WORK_IGNORE_BLOCK.rstrip() + text[end:]
    else:
        updated = text + ("\n" if text and not text.endswith("\n") else "") + "\n" + _WORK_IGNORE_BLOCK
    if updated != text:
        _write_atomic(ignore, updated)
    project.work_root.mkdir(parents=True, exist_ok=True)
    work_ignore = project.work_root / ".gitignore"
    if work_ignore.is_symlink() or (work_ignore.exists() and not work_ignore.is_file()):
        raise ValueError("The Len work .gitignore must be a regular file.")
    if not work_ignore.exists():
        _write_atomic(work_ignore, _WORK_GITIGNORE)


def prepare_project(project: LenProject, skill_root: Path = BUNDLED_SKILL) -> Path:
    """Prepare shared guidance and handoff; leave prior project tools and translations intact."""
    prompt = build_handoff(project, skill_root)
    _validate_skill(skill_root)
    context = shared_context(project)
    project.workspace.mkdir(parents=True, exist_ok=True)
    _prepare_versioned_work(project)
    settings = asdict(project)
    settings.pop("game_root")
    _write_atomic(project.workspace / "project.json", json.dumps({"version": 2, **settings}, indent=2) + "\n")
    _write_atomic(project.workspace / "context.json", json.dumps(context, ensure_ascii=False, indent=2) + "\n")
    _write_atomic(project.workspace / "setup.md", load_generic_project_setup(project.game_root))
    handoff = project.workspace / "handoff.md"
    _write_atomic(handoff, prompt)
    return handoff
