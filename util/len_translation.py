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
STAGES = {
    "translate": "Translate the whole game",
    "prepare": "Prepare extraction and guidance",
    "continue": "Continue existing work",
    "qa": "Review and fix the translation",
}
MODES = {
    "local": "Agent / Sub Direct Translation",
    "api": "API Batch Translation",
}


@dataclass(frozen=True)
class LenProject:
    game_root: Path
    stage: str = "translate"
    mode: str = "local"
    include_images: bool = True
    instructions: str = ""
    include_glossary_base: bool = True
    api_estimate: dict | None = None

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
        project = LenProject(game_root, include_glossary_base=data.get("include_glossary_base", True),
                             api_estimate=data.get("api_estimate"), **{key: data[key] for key in (
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
    api_summary = ""
    if project.mode == "api" and project.stage != "prepare":
        from util.len_api import validate_estimate, estimate_summary
        validate_estimate(project, project.api_estimate)
        api_summary = estimate_summary(project.api_estimate)
    task = {
        "translate": "Carry the game through extraction, translation, injection, layout fixes, in-game QA and a local translation patch.",
        "prepare": "Preparation only: inspect the engine, extract and audit the corpus, and prepare the glossary, game bible, prompt and validation plan. Stop before translation, injection or API-driver implementation.",
        "continue": "Read the existing status and artifacts, verify what has already been completed, and resume the remaining translation, injection, layout, QA and patch work without discarding valid progress.",
        "qa": "Review the existing translated game against its source. Repair confirmed omissions, translation errors, layout issues and patch defects; re-inject affected outputs and validate them in game.",
    }[project.stage]
    mode = (
        "Translate directly with the AI assistant. No translation API calls, API-driver setup or hosted image generation are authorized by this handoff. Local extraction, image lettering, measurement and patch tools are allowed."
        if project.mode == "local" else
        ("API preparation only. No paid calls or API-driver implementation. Export the complete request plan "
         "with context-many, then return to Len’s Method for the provider estimate and API handoff."
         if project.stage == "prepare" else
         "Use API Batch Translation with the reviewed estimate below. Read references/api-batch.md before "
         "provider work. Revalidate this estimate before submitting the exact quoted request set; a changed "
         "model, source, prompt or scope needs a fresh quote. Reuse the application’s provider configuration, "
         "batch collection, approval and history where the engine adapter supports them. Never fall back "
         "to live paid requests silently. The estimate is not a spending cap; additional retries need their "
         "own estimate and approval. Keep keys out of prompts, logs and project artifacts.\n" + api_summary)
    )
    images = (
        "Include all images containing player-facing Japanese text: inventory archives, UI states and animation frames, translate and fit their text, and validate the resulting assets in game. This explicitly opts into the skill's image-translation scope."
        if project.include_images else
        "Image translation is excluded. Report known baked Japanese labels separately; do not replace images or claim whole-game coverage while those labels remain."
    )
    rpgmaker = rpgmaker_layout(project.game_root)
    preparation = (
        "This is an RPG Maker game. Before extraction or the first Git baseline, preserve a recoverable "
        "copy of the starting game and run the same file preparation as Workflow: format game JSON with "
        "dazedformat, format plugins.js, install the bundled GameUpdate helper using saved Config defaults, "
        "and install the MV/MZ TranslationUpdateCheck. Use this application's scripts/len_translation.py "
        "rpgmaker-prep --game-root <game> command, then retain a recoverable prepared untranslated "
        "snapshot and run git-setup as described below. Use that matching prepared source for later "
        "git-scope checks; keep the pre-preparation backup separately. For Ace, complete "
        "Workflow's extraction/RV2JSON prerequisite first and use --data-path <existing JSON export> "
        "when it is not in ace_json; never format native Marshal bytes as text. On resume, inspect "
        "existing preparation and run only missing or requested repair work; never replace a known "
        "Japanese Git baseline with the current translation. Read the generated setup.md: it uses "
        "Workflow's RPG Maker speaker, glossary, wrapping and localization investigation instructions. "
        "Collect source speakers within the selected translation mode; direct mode does not authorize "
        "API calls just to collect names. Keep the configured game-specific updater settings and patch scope."
        if rpgmaker else
        "Use the detected engine's preparation tools and native-byte safeguards. RPG Maker formatting "
        "and GameUpdate installation do not apply to an unrelated engine."
    )
    return f"""Use Len's game-translation skill to translate this Japanese game into English.

Game folder: {json.dumps(str(project.game_root), ensure_ascii=False)}
Skill entrypoint: {json.dumps(str(skill_root / 'SKILL.md'), ensure_ascii=False)}
Workspace: {json.dumps(str(project.workspace), ensure_ascii=False)}
DazedTL application: {json.dumps(str(DATA_DIR.parent), ensure_ascii=False)}

Read the skill entrypoint first and resolve its references/ and tools/ relative to that file. DAZEDTL_ROOT means the application folder above. Use its live code when a reference points there. Run the skill's scripts/check_tools.py with {json.dumps(sys.executable)}. Copy only tools you need to this project's workspace before adapting or running code that writes beside itself. Historical game paths in examples are not this project's paths.

Task: {task}

Project preparation: {preparation}

Before changing game files, complete the project lifecycle in references/project-lifecycle.md from Len's skill. Inspect Git with this application command (argument array):
{json.dumps([sys.executable, str(DATA_DIR.parent / 'scripts/len_translation.py'), 'git-status', '--game-root', str(project.game_root)], ensure_ascii=False)}
Set up or reuse local version tracking with the same script's git-setup command and --version <release label>. For a fresh translation or preparation task, the selected game folder IS the intended untranslated starting source by default; --original is optional and only needed to select a different source. Do a bounded check of the current game and user instructions for evidence of an injected player-facing translation or a source-version mismatch. An enabled TranslationUpdateCheck plugin, GameUpdate files, .dazedtl metadata, extracted data, prepared glossaries, JSON formatting or Git scaffolding are normal tool preparation, not evidence of an already translated game. English titles, stock UI labels and plugin metadata alone are not evidence either. If the user identifies this folder as the starting original and there is no concrete contradictory evidence, proceed with it; do not search downloads, mounted media or unrelated folders for a supposedly cleaner copy or ask the user to reconfirm it. Record known preparation in status.md and snapshot the folder as supplied; do not remove the updater or undo preparation to manufacture a pristine-looking release. When resuming preparation and the game is still untranslated, use --current-is-untranslated; an actual translated game or unsuitable source release without a usable baseline needs --original <untranslated source>. Ask for another source only when concrete evidence or the user's statement establishes that the selected folder cannot serve as the starting original. Verify the version from local evidence, or label an unversioned snapshot initial-unversioned and record that limitation. The helper uses the shared Workflow backend and preserves native bytes and existing history. Resolve Git prerequisites without resetting, discarding, relabeling a known translation as original, or changing unrelated repository state. Local Git setup and reviewed checkpoints are part of this task; remote creation, pushing and publishing require a separate user request.

Before the first baseline, review the game's complete file inventory and use an exact-path .gitignore allowlist for the intended runtime patch, plus .gitignore, .gitattributes and installation README.md. Keep unchanged vendor artwork, engine/runtime files, unused plugins, source copies, editable image sources and all .dazedtl guidance/work/QA records out of both game branches. Include translated native data, translated runtime images and only required modified or added plugins, fonts and other runtime dependencies. Include required runtime additions made during tool preparation even when their bytes match the prepared backup; inspect enabled plugin registrations and runtime references rather than relying only on a source/target diff. Preserve engine-required bytes and line endings (use scoped -text rules where appropriate). The Len Git mode does not impose Workflow's file-extension allowlist or reformat game payloads. Preserve a recoverable backup of this starting game before translation or injection; create that backup from the selected folder when needed instead of demanding a pre-existing second copy. Git's ignored-asset inventory is not a backup of those bytes. After setup, verify both baseline commits, the active translated branch and the files actually tracked before translating. Describe this as the supplied untranslated starting baseline, including recorded preparation, rather than claiming it is byte-identical to an independently verified vendor archive.

Translation mode: {mode}

Image scope: {images}
For preparation-only work, document the selected image scope in the plan; do not render or inject replacements yet.

Use targeted translation QA by default. Full start-to-finish playthroughs, grinding through battles and recruiting another playtester are separate optional scope. Test changed renderers and representative scene/UI variants, then report remaining route coverage honestly. Read references/direct-workflow.md for efficient direct batches and evidence reuse.

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

For dialogue batches, carry each unit's source speaker into --speakers <JSON file with the same IDs or list positions as --sources>. Resolve nameplates, speaker markup and actor-name variables from the engine and reviewed source; respect message-block and scene boundaries. Use null when the speaker is unidentified rather than guessing or carrying a name across a boundary. Extract this metadata as part of the task; the user need not label lines manually. The compiler attaches those speakers' glossary/voice notes even when their names are absent from the dialogue and includes the per-line speaker map as context in its user field. Send that complete user field to the model. Speaker metadata is not text to translate or a prefix to inject into dialogue. Translate actual separate nameplates as their own units (names.speaker is the shared instruction template), and preserve/translate tags that genuinely occur inside the source. Key dialogue reuse by the compiled request fingerprint, which includes speaker assignments; never deduplicate identical Japanese across different speakers or scenes using text alone. Validate speaker-to-line associations and restored nameplates during QA.

Registered reference games are listed in context.json. Exact source matches are supplied by the same reference index as Workflow when --sources is provided. Build the source list from reviewed extraction units; never infer matches from unrelated files. Treat past translations as advisory evidence and resolve disagreements against current source and curated guidance.

If the user's instructions name prequels, previous translations or a reference-corpus folder, read references/reference-translations.md from Len's skill and handle those references within this run. Inspect every specified game's existing terminology and aligned Japanese/English corpus before finalizing guidance. Reuse established names and terms where the current source supports the same meaning, and record the selected decisions in this game's shared glossary so they also apply inside new dialogue. Keep reference files read-only, preserve provenance and competing spellings, and resolve conflicts against explicit user priorities, the current source and curated guidance. Register supported aligned pairs in this project's shared reference registry for additional per-batch exact matches. The user can provide reference paths in these instructions without configuring the reference dialog.

If you already have a Len JSON glossary, use the shared import bridge in scripts/len_translation.py import-glossary --game-root <game> --input <glossary.json>. It rejects conflicting names instead of silently overwriting existing decisions. Keep the original JSON as an archive; all subsequent edits belong in the shared guidance files. Existing tools and notes under {json.dumps(str(project.legacy_skill_root))}, if present, are preserved legacy adaptations; inspect and reuse relevant work, but use the current shared guidance contract above.

Cover dialogue, choices, names, database descriptions, menus, plugin/script text and runtime-generated player-facing labels. Distinguish display text from internal identifiers. Preserve control codes, placeholders, archive structure and save compatibility.

Preserve a recoverable source before changing game files. Put authored scripts, reviewed translation records, prequel provenance and QA notes in {json.dumps(str(project.work_root), ensure_ascii=False)}. All .dazedtl files stay local and ignored on main and original, including scope, glossary, status, progress, exports and editable image sources. Preserve and back up this working material separately; Git's patch branches do not protect ignored work. Never force-add it to a patch checkpoint. Preserve legacy adaptations and existing local records.

At each validated patch checkpoint, first ensure the reviewed runtime outputs have actually been injected into the selected game folder. English staged only in an isolated QA copy is not an English patch in main. Save a COMPLETE runtime path list, or a release manifest with files mapping paths to sha256 and original_sha256 (null only for genuine translation-only additions), in the ignored workspace. Run this script's git-scope --game-root <game> --manifest <file> --original <matching untranslated backup>, optionally with --dry-run first. Supply the whole current patch, not just the latest batch. The helper stages exactly those runtime files plus repository metadata, untracks everything else without deleting local files, and adds a scope commit to original containing the matching untranslated files. Translation-only additions have no invented original. Existing original bytes must match the supplied release; use Version Update for a different source version. The helper preserves branch history and updates the ignored-asset inventory used by Version Update. Resolve existing staged changes deliberately before using it. Review git diff --cached and commit the patch on the registered translation branch; do not merge main into original or cherry-pick translation commits there. Recheck both branch file lists and source/target hashes after scope changes and official updates. Keep local checkpoint commits and artifact paths in {json.dumps(str(project.workspace / 'status.md'), ensure_ascii=False)}. On resume, verify artifact and context fingerprints before reusing results. The presence of a handoff or successful extraction is not evidence of completion.

Before the first actual MV/MZ map or database write, make the injector preserve Workflow-compatible _original metadata even when it uses an external translation store. Read the _original section of references/engine-rpgmaker.md. Stage translated JSON separately, then use this script's write-rpgmaker-json --source <matching untranslated baseline or previous game JSON with originals intact> --translated <staged JSON> --output <actual game JSON> for each changed file. Historical reference injectors do not call this helper automatically; adapt their output destination before running them. The writer retains existing originals, handles grouped dialogue, choices, speakers, database/System fields and supported event parameters, and refuses ambiguous structural changes before replacing a file. An adapter that changes command counts/order or unsupported fields must bind original source units explicitly and pass the same independent QA checks; do not bypass preservation on refusal. Never reconstruct a missing Japanese source from current English. Set System.json locale to en_US in the English output. Check enabled plugins for locale/isJapanese branches and test English name input, fonts and affected windows. Keep _original immutable through corrections, wrapping and reinjection, and verify final source/live mappings with the existing RPG Maker QA manifest and independent verifier. For native/binary formats that cannot carry this key, preserve equivalent source/translation sidecars in the separately backed-up workspace with file/unit IDs, exact source, final live text, source hashes and injection bindings; do not add unknown fields to engine containers. This happens within the current task without a separate user prompt.

Validate coverage independently of the extractor, placeholders, fonts, text width and row counts, injected output, and actual in-game scenes. Report string coverage, image coverage, and playtested scenes separately. Never claim 100% translation from string counts alone; record inaccessible content, excluded assets and untested scenes explicitly. If this environment cannot launch the game, leave that verification pending and give the user precise playtest steps. Re-inject before packaging. Build a local patch with installation instructions after the applicable QA gates pass; uploading or publishing is a separate user action.

Maintain the compact progress snapshot at {json.dumps(str(project.workspace / 'progress.json'), ensure_ascii=False)} as well as the detailed status.md log. Read references/progress-reporting.md from the live Len skill. After each saved batch or milestone, and before pausing or handing off, export saved unit records (including untranslated occurrences) and run this script's progress-update --game-root <game> --input <report JSON> command, or use --input - for JSON on stdin. Report the current phase, phase checkpoints, a short blocker and next action. The helper counts unique unit IDs, validates source/review fingerprints and writes progress atomically; it does not make API calls. Keep a discovered-unit denominator even when the independent coverage audit is unfinished; unknown full-corpus totals must remain unknown. Export cumulative active translation/review seconds and bounded remaining phase estimates with their assumptions. Refresh at least every 10 minutes during ongoing work and before any long QA or provider wait. Image scope must match this project. Include current source/evidence artifacts so changed inputs are flagged. Revalidate stale results and downstream checkpoints before reporting again. Never regenerate fingerprints to bless old translations or reviews. Preserve this file through resume and prompt refresh; the user should not maintain progress manually or need a separate prompt. Keep the detailed history in status.md; both progress files stay local and belong in the separate workspace backup, not the game patch branches.


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


def prepare_project(project: LenProject, skill_root: Path = BUNDLED_SKILL) -> Path:
    """Prepare shared guidance and handoff; leave prior project tools and translations intact."""
    prompt = build_handoff(project, skill_root)
    _validate_skill(skill_root)
    context = shared_context(project)
    project.workspace.mkdir(parents=True, exist_ok=True)
    _prepare_local_work(project)
    settings = asdict(project)
    settings.pop("game_root")
    _write_atomic(project.workspace / "project.json", json.dumps({"version": 2, **settings}, indent=2) + "\n")
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
