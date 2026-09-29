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
from util.skills import load_generic_project_setup, load_project_setup, load_system_prompt
from util.reference_games import load_registry, reference_context
from util.project_preparation import rpgmaker_layout


BUNDLED_SKILL = SKILLS_DIR / "game-translation"
WORKSPACE_RELATIVE = Path(".dazedtl") / "len-method"
_WORK_IGNORE_BEGIN = "# BEGIN DazedTL Len project work"
_WORK_IGNORE_END = "# END DazedTL Len project work"
_WORK_IGNORE_BLOCK = f"""{_WORK_IGNORE_BEGIN}
# Len work, guidance, translation stores and QA artifacts stay local.
# Runtime patch files are selected separately with git-scope.
/.dazedtl/**
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
{_WORK_IGNORE_END}
"""
MODES = {
    "local": "Agent Translation",
    "api": "API Batch Translation",
}


@dataclass(frozen=True)
class LenProject:
    game_root: Path
    mode: str = "local"
    include_images: bool = True
    instructions: str = ""
    include_glossary_base: bool = True
    install_forge: bool = True

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
    if project.mode not in MODES:
        raise ValueError("Choose a supported translation mode.")
    if any(type(value) is not bool for value in (project.include_images, project.include_glossary_base, project.install_forge)):
        raise ValueError("Image scope, base glossary and Forge installation must be enabled or disabled.")
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
        if not isinstance(data, dict) or data.get("version") not in {1, 2, 3}:
            raise ValueError("Unsupported Len project settings version.")
        # Resolve against the selected game so a moved folder remains portable.
        # Legacy task selection and quote approval do not constrain a new run.
        # The skill resumes from artifacts and reviews costs before paid work.
        project = LenProject(game_root, include_glossary_base=data.get("include_glossary_base", True),
                             install_forge=data.get("install_forge", True),
                             **{key: data[key] for key in (
            "mode", "include_images", "instructions"
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


def _line_speakers(sources, speakers):
    """Validate a complete speaker map/list before context files can be prepared."""
    if speakers is None:
        return None
    if isinstance(sources, dict):
        if not isinstance(speakers, dict) or set(speakers) != set(sources):
            raise ValueError("Speakers must have exactly the same IDs as sources; use null for unidentified speakers.")
        values = [speakers[key] for key in sources]
    else:
        if not isinstance(speakers, list) or len(speakers) != len(sources):
            raise ValueError("Speakers must be a list aligned with every source line; use null for unidentified speakers.")
        values = speakers
    normalized = []
    for value in values:
        if value is None:
            normalized.append(None)
        elif not isinstance(value, str) or any(char in value for char in "\r\n\0"):
            raise ValueError("Each speaker must be a single-line name or null.")
        else:
            normalized.append(value.strip() or None)
    return dict(zip(sources, normalized)) if isinstance(sources, dict) else normalized


def request_context(project: LenProject, sources: list[str] | dict[str, str], *,
                    instruction_key: str | None = None, source_context: str = "",
                    speakers: list[str | None] | dict[str, str | None] | None = None,
                    _shared=None, _reference_pack=None) -> dict:
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
    line_speakers = _line_speakers(sources, speakers)
    speaker_names = list(line_speakers.values()) if isinstance(line_speakers, dict) else line_speakers or []
    shared = _shared if _shared is not None else shared_context(project)
    payload = json.dumps(sources, ensure_ascii=False)
    config = SimpleNamespace(prompt=shared["system"], vocab=shared["glossary"], language="English", useSfxReference=True)
    system, glossary, sfx, user = createContextParts(
        config, payload, "json", speaker_names=tuple(dict.fromkeys(name for name in speaker_names if name)),
    )
    if line_speakers is not None:
        metadata = json.dumps(line_speakers, ensure_ascii=False)
        user = (
            "Speaker metadata for the source below, matched by the same IDs or list positions. "
            "Use it with the glossary for character voice and pronoun context. "
            "Null means no identified speaker; do not automatically carry a previous speaker forward. "
            "These labels are context only: do not translate this metadata, add it to dialogue, "
            "or include it as extra output fields. Preserve any speaker tags actually present in the source.\n"
            f"```json\n{metadata}\n```\n\n"
            "Translate only the following source text, keeping its IDs/order and the required output schema:\n"
            + user
        )
    result = {
        "schema": 1, "context_sha256": shared["content_sha256"],
        "system": system, "glossary": glossary, "sfx_reference": sfx,
        "request_instructions": ctx(instruction_key, language="English", context=source_context) if instruction_key else "",
        "preceding_japanese_source_context": source_context,
        "user": user,
        "reference_translations": (_reference_pack if _reference_pack is not None
                                   else reference_context(project.game_root, values)),
    }
    if line_speakers is not None:
        result["speakers"] = line_speakers
    result["request_sha256"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return result


def _reference_subset(references, sources):
    """Keep canonical reference evidence identical to a single-batch lookup."""
    wanted = set(sources.values() if isinstance(sources, dict) else sources)
    pack = dict(references)
    if pack["status"] == "ready":
        pack["matches"] = {key: value for key, value in pack["matches"].items() if key in wanted}
        pack["source_count"] = len(pack["matches"])
        pack.pop("content_sha256")
        pack["content_sha256"] = hashlib.sha256(json.dumps(
            pack, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()).hexdigest()
    return pack


def request_contexts(project: LenProject, batches: list[dict]) -> list[dict]:
    """Compile a scene-ordered set with one guidance load and one reference census.

    Returned requests are identical to independent request_context calls. A changed
    dependency aborts the whole operation; no persistent cache can bless stale work.
    """
    if not isinstance(batches, list) or not batches:
        raise ValueError("Supply a nonempty list of context batches.")
    identities = set()
    sources = []
    for batch in batches:
        if not isinstance(batch, dict) or batch.keys() - {"id", "sources", "speakers", "instruction_key", "source_context"}:
            raise ValueError("Context batches accept id, sources, speakers, instruction_key and source_context.")
        identity = batch.get("id")
        if not isinstance(identity, str) or not identity or identity in identities:
            raise ValueError("Each context batch needs a unique nonempty id.")
        identities.add(identity)
        values = batch.get("sources")
        values = list(values.values()) if isinstance(values, dict) else values
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            raise ValueError("Each batch needs a nonempty source list or source object.")
        sources.extend(values)
    shared = shared_context(project)
    references = reference_context(project.game_root, sources)
    result = []
    for batch in batches:
        values = batch["sources"]
        pack = _reference_subset(references, values)
        request = request_context(project, **{key: value for key, value in batch.items() if key != "id"},
                                  _shared=shared, _reference_pack=pack)
        result.append({"id": batch["id"], "sources": batch["sources"], "context": request})
    if shared_context(project)["content_sha256"] != shared["content_sha256"] or reference_context(project.game_root, sources) != references:
        raise ValueError("Guidance or references changed during compilation; retry the entire operation.")
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
    mode = (
        "Translate with the coding assistant's existing access. No DazedTL translation API calls, "
        "API-driver setup or hosted image generation are authorized. Delegation follows the user's instructions."
        if project.mode == "local" else
        "Use the app's saved API Settings and supported Batch backend. Prepare extraction, guidance and "
        "the complete request plan yourself, then run api-estimate and present the cost in this conversation. "
        "Follow references/api-batch.md: obtain any missing spending authorization before paid submission, "
        "revalidate the exact requests and resume persisted jobs. Continue through collection, review and "
        "delivery in this same run; do not send the user back to the app for another prompt. "
        "Never silently switch to Live requests. Copying this prompt does not approve an unknown bill."
    )
    images = (
        "Translate all images containing player-facing Japanese text, including archived assets, UI states "
        "and animation frames; fit and validate their text in game. This opts into the skill's image scope."
        if project.include_images else
        "Image translation is excluded. Report remaining baked Japanese labels separately."
    )
    return f"""Use Len's game-translation skill to translate this Japanese game into English and deliver a validated local patch.

Game folder: {json.dumps(str(project.game_root), ensure_ascii=False)}
Skill entrypoint: {json.dumps(str(skill_root / 'SKILL.md'), ensure_ascii=False)}
Workspace: {json.dumps(str(project.workspace), ensure_ascii=False)}
DazedTL application (DAZEDTL_ROOT): {json.dumps(str(DATA_DIR.parent), ensure_ascii=False)}
Python executable: {json.dumps(sys.executable)}

Read the skill entrypoint first. Resolve references/ and tools/ relative to that file and use the live DazedTL application for its helpers. Run the skill's scripts/check_tools.py with the Python executable above. Follow references/project-lifecycle.md and references/progress-reporting.md throughout.

Own the complete workflow: inspect existing artifacts and Git state, preserve the source, prepare the engine and guidance, extract, translate, fit text and images in scope, inject, run targeted QA, and package the local patch. Infer what remains from verified artifacts; start fresh work or resume existing work automatically. Preserve valid translations, curated guidance, local adaptations and checkpoints. Revalidate only work whose dependencies changed. Do not stop after setup, extraction, a batch or a phase to ask for another task selection or prompt. If delivery is already complete and current, report its paths and evidence without repeating translation.

Translation mode: {MODES[project.mode]}
{mode}

Image scope: {images}
Include DazedTL base glossary: {json.dumps(project.include_glossary_base)}
Install Forge for MV/MZ: {json.dumps(project.install_forge)}. The preparation helper honors this choice; skip installation on other engines. Disabled means skip installation/updates, leaving existing copies in place.

Use this game's shared .dazedtl/glossary.txt and .dazedtl/skills/*.md as authoritative guidance. Read setup.md in the workspace and complete its guidance phase yourself before continuing; its guidance-only boundary ends with that phase. Refresh context.json through the live context/context-many helpers after guidance changes. Extract speaker metadata and handle user-supplied reference games yourself. Keep authored tools, translations and QA records in the workspace's work/ folder and back up ignored work separately.

Before creating a missing original baseline, verify the selected folder is still untranslated and pass --current-is-untranslated to git-setup, or supply --original with a verified matching source. This is an agent check, not a user task or a requirement for a second download. Normal tool preparation does not make a game translated. Never replace a known Japanese baseline with current English. Preserve source metadata during injection, use the MV/MZ source-preserving writer where applicable, and synchronize the reviewed runtime patch with git-scope before local checkpoint commits.

Maintain status.md and progress.json yourself using progress-update after saved batches and milestones, at least every 10 minutes during active work, and before long waits or handoff. Show completed/discovered units, coverage status, phase, estimated remaining active work, next checkpoint and any blocker. Keep translation, review, images, injection, runtime QA and packaging distinct. The user should be able to watch progress without maintaining files or issuing phase prompts.

Continue until the local delivery is verified or a concrete blocker needs user input. Resolve routine implementation choices yourself. Ask only for missing information or authorization that materially blocks progress, complete independent work while waiting, and resume from the checkpoint after the answer. Full playthroughs and extra playtesters are optional unless requested. Mark unavailable runtime checks pending; never report them as passed. Creating remotes, pushing, uploading and publishing require a separate user request.

Additional project instructions (including any explicitly narrower scope):
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


def _prepare_local_work(project: LenProject) -> None:
    """Keep all Len working state local, after the shared portable-settings rules."""
    ignore = project.game_root / ".gitignore"
    text = ignore.read_text(encoding="utf-8", errors="surrogateescape") if ignore.exists() else ""
    if text.count(_WORK_IGNORE_BEGIN) != text.count(_WORK_IGNORE_END) or text.count(_WORK_IGNORE_BEGIN) > 1:
        raise ValueError("The Len project .gitignore block is incomplete or duplicated.")
    if _WORK_IGNORE_BEGIN in text:
        start = text.index(_WORK_IGNORE_BEGIN)
        end = text.index(_WORK_IGNORE_END) + len(_WORK_IGNORE_END)
        if end < start:
            raise ValueError("The Len project .gitignore block is out of order.")
        text = text[:start] + text[end:]
    patch_start = text.find("# BEGIN DazedTL Len patch files")
    if patch_start >= 0:
        updated = text[:patch_start].rstrip() + "\n\n" + _WORK_IGNORE_BLOCK + "\n" + text[patch_start:].lstrip("\r\n")
    else:
        updated = text.rstrip() + "\n\n" + _WORK_IGNORE_BLOCK
    if not ignore.exists() or ignore.read_text(encoding="utf-8", errors="surrogateescape") != updated:
        _write_atomic(ignore, updated)
    project.work_root.mkdir(parents=True, exist_ok=True)


def setup_forge(project: LenProject) -> dict:
    """Honor Len's saved opt-in using Workflow's existing offline Forge installer."""
    _validate_project(project)
    layout = rpgmaker_layout(project.game_root)
    if not layout or layout["engine"] != "MVMZ":
        return {"status": "unsupported", "message": "Forge supports RPG Maker MV/MZ only."}
    if not project.install_forge:
        return {"status": "skipped", "message": "Forge installation is disabled for this project."}
    from util.forge.installer import install
    from util.playtest.config import load_config
    from util.project_preparation import format_plugins_js

    try:
        ok, message = install(project.game_root, cfg=load_config(DATA_DIR.parent / ".env"))
        if not ok:
            raise ValueError(message)
        format_plugins_js(layout["plugins_js"])
    finally:
        # The shared installer exposes Workflow's portable guidance. Len's
        # runtime-patch repositories keep all of that working material local.
        _prepare_local_work(project)
    return {"status": "installed", "message": message}


def prepare_project(project: LenProject, skill_root: Path = BUNDLED_SKILL) -> Path:
    """Prepare shared guidance and handoff; leave prior project tools and translations intact."""
    prompt = build_handoff(project, skill_root)
    _validate_skill(skill_root)
    context = shared_context(project)
    project.workspace.mkdir(parents=True, exist_ok=True)
    _prepare_local_work(project)
    settings = asdict(project)
    settings.pop("game_root")
    _write_atomic(project.workspace / "project.json", json.dumps({"version": 3, **settings}, indent=2) + "\n")
    _write_atomic(project.workspace / "context.json", json.dumps(context, ensure_ascii=False, indent=2) + "\n")
    layout = rpgmaker_layout(project.game_root)
    setup = (load_project_setup("rpgmaker", prepend=(
        f"Selected game folder: {json.dumps(str(project.game_root), ensure_ascii=False)}\n"
        f"RPG Maker JSON directory (default export location for Ace): {json.dumps(str(layout['data_path']), ensure_ascii=False)}\n"
        "Use this selected game's sources and portable guidance files. If Ace JSON is not available, "
        "complete the engine's extraction/conversion prerequisite first; use the actual reviewed "
        "export if it lives elsewhere. Collect source speaker names "
        "within the selected direct/API mode; do not introduce paid name collection in direct mode."
    )) if layout else load_generic_project_setup(project.game_root))
    _write_atomic(project.workspace / "setup.md", setup)
    from util.len_progress import initialize_progress

    initialize_progress(project)
    handoff = project.workspace / "handoff.md"
    _write_atomic(handoff, prompt)
    return handoff
