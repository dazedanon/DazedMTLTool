#!/usr/bin/env python3
"""Validate the complete four-view walkthrough publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from index_rpgmaker_dependencies import build_index


SCHEMA_VERSION = 17
MILESTONE = "complete-four-view-walkthrough"
PROJECT_CONTEXT_FILES = {
    "glossary": ".dazedtl/glossary.txt",
    "quirks": ".dazedtl/skills/quirks.md",
}
REQUIRED_VIEWS = {
    "main-route": "view-main-route",
    "optional-content": "view-optional-content",
    "bosses": "view-bosses",
    "scenes-cg": "view-scenes-cg",
}
COMPLETE_VIEWS = set(REQUIRED_VIEWS)
PLACEHOLDER_VIEWS: set[str] = set()
REQUIRED_HOOKS = {
    "topbar",
    "topbar-location",
    "sidebar",
    "brand",
    "section-nav",
    "sidebar-progress",
    "sidebar-scrim",
    "primary-tabs",
    "page",
    "guide-content",
    "hero",
    "search-dialog",
    "resume-toast",
    "back-to-top",
}
CLAIM_KINDS = {"navigation", "objective", "pickup", "equipment", "boss", "choice", "gate"}
CLAIM_STATUSES = {"verified"}
OPTIONAL_KINDS = {
    "activity",
    "collection",
    "companion-recruitment",
    "optional-area",
    "postgame-event",
    "progression-guide",
    "service-unlock",
    "side-event",
}
RECRUITMENT_FAILURE_KINDS = {
    "missable",
    "permanent-lockout",
    "point-of-no-return",
    "retryable",
}
DEPENDENCY_NODE_KINDS = {
    "automatic",
    "battle-outcome",
    "choice",
    "item-change",
    "player-action",
    "state-predicate",
    "state-transition",
    "story-gate",
    "terminal",
    "unresolved",
}
DEPENDENCY_LEAF_KINDS = {"automatic", "player-action", "story-gate"}
DEPENDENCY_COVERAGE_STATUSES = {"complete", "partial"}
DEPENDENCY_CARRIER_KINDS = {"actor", "armor", "item", "switch", "variable", "weapon"}
SYSTEM_DECISIONS = {"deep-audit", "trace-on-demand", "ignore"}
BOSS_KINDS = {"story-boss", "side-boss", "apex-monster"}
SCENE_KINDS = {
    "character-scene",
    "combat-scene",
    "defeat-scene",
    "encounter-scene",
    "gallery-entry",
    "other-scene",
    "relationship-scene",
    "story-scene",
}
SCENE_ACQUISITION_MODES = {"normal-play", "gallery-only"}
ROUTE_ANCHOR_POSITIONS = {"before", "after"}
ROUTE_STRUCTURE_MODES = {"chapters-and-sections", "sections"}
SOURCE_TYPES = {"event-command", "database-record", "file-excerpt", "file-hash"}
ID_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\Z")
CLAIM_MARKER_RE = re.compile(
    r"<!--\s*route-claim:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
SECTION_MARKER_RE = re.compile(
    r"<!--\s*route-section:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
CHAPTER_MARKER_RE = re.compile(
    r"<!--\s*route-chapter:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
OPTIONAL_GROUP_MARKER_RE = re.compile(
    r"<!--\s*optional-group:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
OPTIONAL_ENTRY_MARKER_RE = re.compile(
    r"<!--\s*optional-entry:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
BOSS_GROUP_MARKER_RE = re.compile(
    r"<!--\s*boss-group:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
BOSS_ENTRY_MARKER_RE = re.compile(
    r"<!--\s*boss-entry:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
SCENE_GROUP_MARKER_RE = re.compile(
    r"<!--\s*scene-group:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
SCENE_ENTRY_MARKER_RE = re.compile(
    r"<!--\s*scene-entry:(?P<id>[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)\s*-->"
)
INTERNAL_LOCATOR_PATTERNS = (
    re.compile(r"\bMap\d{3,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:map|event|common event|switch|variable|troop)\s+"
        r"(?:ID\s*)?#?\d+\b",
        re.IGNORECASE,
    ),
    re.compile(r"\(\s*\d+\s*,\s*\d+\s*\)"),
    re.compile(r"\b[xy]\s*[:=]\s*\d+\b", re.IGNORECASE),
)
MECHANICAL_PROGRESSION_PATTERNS = (
    re.compile(r"\b(?:victory|success|loss) branch\b", re.IGNORECASE),
    re.compile(r"\b(?:route|story|objective|opening|progression) state\b", re.IGNORECASE),
    re.compile(r"\b(?:shared )?(?:completion|progression) process\b", re.IGNORECASE),
    re.compile(r"\bthe event (?:advances|sets|calls|enables)\b", re.IGNORECASE),
)
ENGINE_CONTROL_CODE_RE = re.compile(
    r"\\(?:C|I|FS|PX|PY|OW|OC|V|N|P)\s*\[[^\]\r\n]*\]",
    re.IGNORECASE,
)
VOID_ELEMENTS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
GLOSSARY_GENDER_RE = re.compile(
    r"^\s*[^\n()]+\((?P<name>[^()]+)\)\s*-\s*(?P<gender>Female|Male)\b",
    re.IGNORECASE | re.MULTILINE,
)
GLOSSARY_ENTRY_RE = re.compile(r"^\s*[^\n()]+\((?P<name>[^()]+)\)\s*-", re.MULTILINE)
OPPOSING_PRONOUNS = {
    "female": ("he", "him", "his", "himself"),
    "male": ("she", "her", "hers", "herself"),
}


class ValidationInputError(ValueError):
    """Raised when a required walkthrough input cannot be read."""


def _validate_recruitment_contract(
    entry: dict[str, Any],
    kind: str,
    phrases: list[str],
    markdown: str,
    local_source_ids: set[str],
) -> list[str]:
    failures: list[str] = []
    recruitment = entry.get("recruitment")
    if kind != "companion-recruitment":
        if recruitment is not None:
            failures.append("recruitment is only valid for companion-recruitment entries")
        return failures
    if not isinstance(recruitment, dict):
        return ["companion-recruitment entries require a recruitment object"]

    normalized_markdown = _normalize(markdown)
    for field, needs_kind in (("success_steps", False), ("failure_modes", True)):
        raw_rows = recruitment.get(field)
        if not isinstance(raw_rows, list) or not raw_rows:
            failures.append(f"recruitment.{field} must contain at least one source-bound row")
            continue
        for row_index, raw_row in enumerate(raw_rows):
            row = raw_row if isinstance(raw_row, dict) else {}
            row_text = str(row.get("text", "")).strip()
            row_sources = row.get("source_ids")
            if not row_text:
                failures.append(f"recruitment.{field}[{row_index}].text must be nonempty")
            else:
                if row_text not in phrases:
                    failures.append(
                        f"recruitment.{field}[{row_index}].text must also appear in guide_phrases"
                    )
                if _normalize(row_text) not in normalized_markdown:
                    failures.append(f"recruitment.{field}[{row_index}].text is missing from Markdown")
            if not isinstance(row_sources, list) or not row_sources or any(
                not isinstance(source_id, str) for source_id in row_sources
            ):
                failures.append(f"recruitment.{field}[{row_index}].source_ids must be a nonempty list")
            else:
                unknown_sources = sorted(set(row_sources) - local_source_ids)
                if unknown_sources:
                    failures.append(
                        f"recruitment.{field}[{row_index}] references unknown local source {unknown_sources[0]!r}"
                    )
            if needs_kind and str(row.get("kind", "")).strip() not in RECRUITMENT_FAILURE_KINDS:
                failures.append(
                    f"recruitment.{field}[{row_index}].kind must be one of {sorted(RECRUITMENT_FAILURE_KINDS)}"
                )
    return failures


def _normalize(value: str) -> str:
    return " ".join(value.split()).strip()


def _issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    **details: Any,
) -> None:
    issues.append({"severity": severity, "code": code, "message": message, **details})


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationInputError(f"Could not read JSON from {path}: {exc}") from exc


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_project_context(
    game_root: Path,
    evidence: dict[str, Any],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[str], list[dict[str, str]]]:
    declared = evidence.get("project_context")
    failures: list[str] = []
    observed: dict[str, Any] = {}
    if not isinstance(declared, dict):
        failures.append("project_context must be an object")
        declared = {}

    unknown = sorted(set(declared) - set(PROJECT_CONTEXT_FILES))
    if unknown:
        failures.append(f"project_context contains unknown keys: {unknown}")

    for key, relative in PROJECT_CONTEXT_FILES.items():
        path = game_root / relative
        entry = declared.get(key)
        if not path.is_file():
            if entry is not None:
                failures.append(f"{key} is declared but {relative} does not exist")
            observed[key] = {"available": False, "file": relative}
            continue
        digest = _sha256(path)
        observed[key] = {"available": True, "file": relative, "sha256": digest}
        if not isinstance(entry, dict):
            failures.append(f"{key} must snapshot the available {relative}")
            continue
        if entry.get("file") != relative:
            failures.append(f"{key}.file must be {relative!r}")
        declared_digest = entry.get("sha256")
        if not isinstance(declared_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", declared_digest):
            failures.append(f"{key}.sha256 must be a lowercase SHA-256 digest")
        elif declared_digest != digest:
            failures.append(f"{key} changed after the walkthrough context was recorded")

    if failures:
        _issue(
            issues,
            "error",
            "project-context-invalid",
            f"Walkthrough project context is invalid: {failures[0]}",
            failures=failures,
        )

    glossary_names: list[str] = []
    gender_facts: list[dict[str, str]] = []
    glossary_path = game_root / PROJECT_CONTEXT_FILES["glossary"]
    if glossary_path.is_file():
        try:
            glossary = glossary_path.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeError) as exc:
            _issue(
                issues,
                "error",
                "project-context-unreadable",
                f"Could not read the project glossary: {exc}",
            )
        else:
            glossary_names = sorted(
                {_normalize(match.group("name")) for match in GLOSSARY_ENTRY_RE.finditer(glossary)},
                key=len,
                reverse=True,
            )
            seen: set[str] = set()
            for match in GLOSSARY_GENDER_RE.finditer(glossary):
                name = _normalize(match.group("name"))
                folded = name.casefold()
                if not name or folded in seen:
                    continue
                seen.add(folded)
                gender_facts.append(
                    {
                        "name": name,
                        "gender": match.group("gender").casefold(),
                        "source": PROJECT_CONTEXT_FILES["glossary"],
                    }
                )
    gender_facts.sort(key=lambda row: len(row["name"]), reverse=True)
    return observed, glossary_names, gender_facts


def _is_one_edit_apart(left: str, right: str) -> bool:
    left = left.casefold()
    right = right.casefold()
    if left == right or abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right)) == 1
    short_index = 0
    long_index = 0
    skipped = False
    while short_index < len(left) and long_index < len(right):
        if left[short_index] == right[long_index]:
            short_index += 1
            long_index += 1
            continue
        if skipped:
            return False
        skipped = True
        long_index += 1
    return True


def _validate_glossary_names(
    text: str,
    label: str,
    glossary_names: list[str],
    issues: list[dict[str, Any]],
) -> None:
    canonical = {name.casefold() for name in glossary_names}
    eligible = [name for name in glossary_names if len(name) >= 6 and " " not in name]
    tokens = {
        match.group(0).removesuffix("'s").removesuffix("’s")
        for match in re.finditer(r"(?<![\w])[A-Z][A-Za-z'’]+(?![\w])", text)
    }
    reported: set[str] = set()
    for token in sorted(tokens):
        folded_token = token.casefold()
        if folded_token in canonical or folded_token in reported:
            continue
        for name in eligible:
            folded_name = name.casefold()
            if folded_name.endswith("s") and folded_token == folded_name[:-1]:
                continue
            if folded_token.endswith(("'", "’")) and folded_token[:-1] == folded_name:
                continue
            if token[0].casefold() != name[0].casefold() or not _is_one_edit_apart(token, name):
                continue
            reported.add(folded_token)
            _issue(
                issues,
                "error",
                "glossary-name-near-miss",
                f"{label} uses {token!r}, one edit from glossary name {name!r}; use the canonical spelling or rewrite the prose.",
                observed=token,
                canonical=name,
                glossary_file=PROJECT_CONTEXT_FILES["glossary"],
            )
            break


def _validate_glossary_pronouns(
    text: str,
    label: str,
    gender_facts: list[dict[str, str]],
    issues: list[dict[str, Any]],
) -> None:
    if not gender_facts:
        return
    without_comments = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    name_patterns = [
        (
            fact,
            re.compile(rf"(?<![\w]){re.escape(fact['name'])}(?:['’]s)?(?![\w])", re.IGNORECASE),
        )
        for fact in gender_facts
    ]
    blocks = [block for block in re.split(r"\n\s*\n", without_comments) if block.strip()]
    reported: set[tuple[str, str]] = set()
    for block in blocks:
        normalized = _normalize(block)
        if not normalized:
            continue
        all_name_starts = sorted(
            match.start()
            for _fact, pattern in name_patterns
            for match in pattern.finditer(normalized)
        )
        for fact, pattern in name_patterns:
            forbidden = re.compile(
                rf"\b(?:{'|'.join(OPPOSING_PRONOUNS[fact['gender']])})\b",
                re.IGNORECASE,
            )
            for name_match in pattern.finditer(normalized):
                next_name = next(
                    (start for start in all_name_starts if start > name_match.start()),
                    len(normalized),
                )
                window_end = min(len(normalized), next_name, name_match.end() + 180)
                conflict = forbidden.search(normalized, name_match.end())
                if conflict is None or conflict.start() >= window_end:
                    continue
                key = (fact["name"].casefold(), conflict.group(0).casefold())
                if key in reported:
                    continue
                reported.add(key)
                _issue(
                    issues,
                    "error",
                    "glossary-pronoun-conflict",
                    f"{label} uses {conflict.group(0)!r} for {fact['name']}, whose glossary entry identifies "
                    f"the character as {fact['gender']}.",
                    character=fact["name"],
                    pronoun=conflict.group(0),
                    glossary_file=fact["source"],
                )


def _project_file(game_root: Path, relative: Any) -> tuple[Path | None, str | None]:
    raw = str(relative or "").strip().replace("\\", "/")
    if not raw:
        return None, "file must be a nonempty project-relative path"
    rel = Path(raw)
    if rel.is_absolute() or ".." in rel.parts:
        return None, "file must stay inside the game root"
    root = game_root.resolve()
    path = (root / rel).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        return None, "file resolves outside the game root"
    if not path.is_file():
        return None, f"file does not exist: {raw}"
    return path, None


def _integer(source: dict[str, Any], field: str) -> tuple[int | None, str | None]:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None, f"{field} must be a nonnegative integer"
    return value, None


def _event_command(data: Any, source: dict[str, Any], filename: str) -> tuple[dict[str, Any] | None, list[str]]:
    failures: list[str] = []
    event_id, failure = _integer(source, "event_id")
    if failure:
        failures.append(failure)
    page_index, failure = _integer(source, "page_index")
    if failure:
        failures.append(failure)
    command_index, failure = _integer(source, "command_index")
    if failure:
        failures.append(failure)
    if failures:
        return None, failures
    assert event_id is not None and page_index is not None and command_index is not None

    event: Any = None
    commands: Any = None
    if Path(filename).name.casefold() == "commonevents.json":
        if not isinstance(data, list) or event_id >= len(data):
            failures.append(f"common event {event_id} does not exist")
            return None, failures
        if page_index != 0:
            failures.append("CommonEvents.json page_index must be 0")
            return None, failures
        event = data[event_id]
        commands = event.get("list") if isinstance(event, dict) else None
    else:
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list) or event_id >= len(events):
            failures.append(f"map event {event_id} does not exist")
            return None, failures
        event = events[event_id]
        pages = event.get("pages") if isinstance(event, dict) else None
        if not isinstance(pages, list) or page_index >= len(pages):
            failures.append(f"page {page_index} does not exist on event {event_id}")
            return None, failures
        page = pages[page_index]
        commands = page.get("list") if isinstance(page, dict) else None
    if not isinstance(event, dict):
        failures.append(f"event {event_id} is empty or invalid")
        return None, failures
    if not isinstance(commands, list) or command_index >= len(commands):
        failures.append(f"command {command_index} does not exist")
        return None, failures
    command = commands[command_index]
    if not isinstance(command, dict):
        failures.append(f"command {command_index} is not an object")
        return None, failures
    return command, failures


def _validate_source(game_root: Path, source: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    source_id = str(source.get("id", "")).strip()
    if not ID_RE.fullmatch(source_id):
        failures.append("id must be a nonempty kebab-case identifier")
    source_type = str(source.get("type", "")).strip()
    if source_type not in SOURCE_TYPES:
        failures.append(f"type must be one of {sorted(SOURCE_TYPES)}")
    if not str(source.get("supports", "")).strip():
        failures.append("supports must explain what this source proves")
    path, failure = _project_file(game_root, source.get("file"))
    if failure:
        failures.append(failure)
        return failures
    assert path is not None

    if source_type == "event-command":
        try:
            data = _read_json(path)
        except ValidationInputError as exc:
            failures.append(str(exc))
            return failures
        command, command_failures = _event_command(data, source, str(source.get("file", "")))
        failures.extend(command_failures)
        expected = source.get("expected")
        if not isinstance(expected, dict) or set(expected) != {"code", "parameters"}:
            failures.append("expected must snapshot exactly code and parameters")
        elif not isinstance(expected.get("code"), int) or not isinstance(expected.get("parameters"), list):
            failures.append("expected.code must be an integer and expected.parameters must be a list")
        elif command is not None:
            if command.get("code") != expected["code"]:
                failures.append(
                    f"command code changed: expected {expected['code']!r}, observed {command.get('code')!r}"
                )
            if command.get("parameters") != expected["parameters"]:
                failures.append("command parameters changed")

    elif source_type == "database-record":
        try:
            data = _read_json(path)
        except ValidationInputError as exc:
            failures.append(str(exc))
            return failures
        record_id, integer_failure = _integer(source, "record_id")
        if integer_failure:
            failures.append(integer_failure)
        expected = source.get("expected")
        if not isinstance(expected, dict) or not expected:
            failures.append("expected must contain at least one database field")
        if record_id is not None:
            if not isinstance(data, list) or record_id >= len(data) or not isinstance(data[record_id], dict):
                failures.append(f"database record {record_id} does not exist")
            elif isinstance(expected, dict):
                record = data[record_id]
                for field, value in expected.items():
                    if field not in record:
                        failures.append(f"database field {field!r} does not exist")
                    elif record[field] != value:
                        failures.append(
                            f"database field {field!r} changed: expected {value!r}, observed {record[field]!r}"
                        )

    elif source_type == "file-excerpt":
        needle = source.get("contains")
        if not isinstance(needle, str) or not needle:
            failures.append("contains must be a nonempty exact excerpt")
        else:
            try:
                source_text = path.read_text(encoding="utf-8-sig")
            except (OSError, UnicodeError) as exc:
                failures.append(f"could not read excerpt source: {exc}")
            else:
                if needle not in source_text:
                    failures.append("the exact excerpt is no longer present")
    elif source_type == "file-hash":
        expected_sha256 = str(source.get("sha256", "")).strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            failures.append("sha256 must be 64 lowercase hexadecimal characters")
        else:
            try:
                observed_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError as exc:
                failures.append(f"could not hash source file: {exc}")
            else:
                if observed_sha256 != expected_sha256:
                    failures.append(
                        f"file hash changed: expected {expected_sha256}, observed {observed_sha256}"
                    )
    return failures


def _validate_player_copy(text: str, label: str, issues: list[dict[str, Any]]) -> None:
    without_comments = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    control_code = ENGINE_CONTROL_CODE_RE.search(without_comments)
    if control_code:
        _issue(
            issues,
            "error",
            "engine-control-code-in-player-copy",
            f"{label} contains engine control code {control_code.group(0)!r} outside an Evidence disclosure.",
            control_code=control_code.group(0),
        )
    for pattern in INTERNAL_LOCATOR_PATTERNS:
        match = pattern.search(without_comments)
        if match:
            _issue(
                issues,
                "error",
                "technical-locator-in-player-copy",
                f"{label} contains technical locator {match.group(0)!r} outside an Evidence disclosure.",
                locator=match.group(0),
            )
    for pattern in MECHANICAL_PROGRESSION_PATTERNS:
        match = pattern.search(without_comments)
        if match:
            _issue(
                issues,
                "error",
                "mechanical-progression-language",
                f"{label} exposes authoring jargon {match.group(0)!r}; describe the player-visible result instead.",
                phrase=match.group(0),
            )


def _validate_route_claims(
    game_root: Path,
    markdown: str,
    evidence: dict[str, Any],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], set[str]]:
    claims_raw = evidence.get("route_claims")
    if not isinstance(claims_raw, list) or not claims_raw:
        _issue(issues, "error", "route-claims-missing", "evidence.json must contain at least one Main Route claim.")
        claims_raw = []

    markers = Counter(match.group("id") for match in CLAIM_MARKER_RE.finditer(markdown))
    claims: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    all_source_ids: set[str] = set()

    for index, raw_claim in enumerate(claims_raw):
        claim = raw_claim if isinstance(raw_claim, dict) else {}
        claim_id = str(claim.get("id", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(claim_id):
            failures.append("id must be a nonempty kebab-case identifier")
            claim_id = claim_id or f"invalid-claim-{index + 1}"
        if claim_id in claims:
            failures.append("claim id is duplicated")
        claims[claim_id] = claim

        kind = str(claim.get("kind", "")).strip()
        if kind not in CLAIM_KINDS:
            failures.append(f"kind must be one of {sorted(CLAIM_KINDS)}")
        status = str(claim.get("status", "")).strip()
        if status not in CLAIM_STATUSES:
            failures.append(f"status must be one of {sorted(CLAIM_STATUSES)}")
        if "limitations" in claim:
            failures.append("limitations are not publishable; narrow the prose to verified main details")

        phrases = claim.get("guide_phrases")
        if not isinstance(phrases, list) or not phrases or any(not isinstance(row, str) or not row.strip() for row in phrases):
            failures.append("guide_phrases must contain at least one nonempty string")
            phrases = []
        normalized_markdown = _normalize(markdown)
        for phrase in phrases:
            if _normalize(phrase) not in normalized_markdown:
                failures.append(f"guide phrase is missing from Markdown: {phrase!r}")

        if markers.get(claim_id, 0) != 1:
            failures.append(f"Markdown must contain exactly one route-claim marker; observed {markers.get(claim_id, 0)}")

        sources = claim.get("sources")
        if not isinstance(sources, list) or not sources:
            failures.append("sources must contain at least one source snapshot")
            sources = []
        local_source_ids: set[str] = set()
        source_results: list[dict[str, Any]] = []
        for raw_source in sources:
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = str(source.get("id", "")).strip()
            if source_id in local_source_ids:
                failures.append(f"source id {source_id!r} is duplicated within the claim")
            if source_id in all_source_ids:
                failures.append(f"source id {source_id!r} must be globally unique")
            local_source_ids.add(source_id)
            all_source_ids.add(source_id)
            source_failures = _validate_source(game_root, source)
            failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
            source_results.append({"id": source_id, "failures": source_failures})

        if failures:
            _issue(
                issues,
                "error",
                "route-claim-invalid",
                f"Route claim {claim_id!r} is invalid: {failures[0]}",
                claim_id=claim_id,
                failures=failures,
            )
            result_status = "contradicted"
        else:
            result_status = "verified"
        results.append(
            {
                "id": claim_id,
                "kind": kind,
                "status": result_status,
                "evidence_status": status,
                "sources": source_results,
                "failures": failures,
            }
        )

    for marker, count in sorted(markers.items()):
        if marker not in claims:
            _issue(
                issues,
                "error",
                "undeclared-route-claim",
                f"Markdown marker {marker!r} has no evidence.json claim.",
                claim_id=marker,
            )
        elif count > 1:
            _issue(
                issues,
                "error",
                "duplicate-route-claim-marker",
                f"Markdown marker {marker!r} occurs {count} times.",
                claim_id=marker,
            )
    return claims, results, all_source_ids


def _validate_route_structure(
    game_root: Path,
    markdown: str,
    evidence: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    all_source_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    raw = evidence.get("route_structure")
    if not isinstance(raw, dict):
        _issue(issues, "error", "route-structure-missing", "evidence.json must define route_structure.")
        return {}, {}, {"mode": "", "source_label": "", "chapters": [], "sections": []}

    mode = str(raw.get("mode", "")).strip()
    source_label = str(raw.get("source_label", "")).strip()
    if mode not in ROUTE_STRUCTURE_MODES:
        _issue(
            issues,
            "error",
            "route-structure-mode-invalid",
            f"route_structure.mode must be one of {sorted(ROUTE_STRUCTURE_MODES)}.",
        )
    if not source_label:
        _issue(issues, "error", "route-structure-label-missing", "route_structure.source_label is required.")

    section_rows = raw.get("sections")
    if not isinstance(section_rows, list) or not section_rows:
        _issue(issues, "error", "route-sections-missing", "route_structure.sections must not be empty.")
        section_rows = []

    section_markers = Counter(match.group("id") for match in SECTION_MARKER_RE.finditer(markdown))
    sections: dict[str, dict[str, Any]] = {}
    section_results: list[dict[str, Any]] = []
    assigned_claims: list[str] = []
    for index, raw_section in enumerate(section_rows):
        section = raw_section if isinstance(raw_section, dict) else {}
        section_id = str(section.get("id", "")).strip()
        label = str(section.get("label", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(section_id):
            failures.append("id must be a nonempty kebab-case identifier")
            section_id = section_id or f"invalid-section-{index + 1}"
        if section_id in sections:
            failures.append("section id is duplicated")
        sections[section_id] = section
        if not label:
            failures.append("label must be nonempty")
        elif _normalize(label) not in _normalize(markdown):
            failures.append(f"section label is missing from Markdown: {label!r}")
        if section_markers.get(section_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one route-section marker; observed {section_markers.get(section_id, 0)}"
            )

        claim_ids = section.get("claim_ids")
        if not isinstance(claim_ids, list) or not claim_ids or any(not isinstance(row, str) for row in claim_ids):
            failures.append("claim_ids must contain at least one claim id")
            claim_ids = []
        if len(set(claim_ids)) != len(claim_ids):
            failures.append("claim_ids contains duplicates")
        for claim_id in claim_ids:
            if claim_id not in claims:
                failures.append(f"claim {claim_id!r} does not exist")
        assigned_claims.extend(claim_ids)

        sources = section.get("sources")
        if not isinstance(sources, list) or not sources:
            failures.append("sources must prove the game-authored section label or boundary")
            sources = []
        source_results: list[dict[str, Any]] = []
        local_ids: set[str] = set()
        for raw_source in sources:
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = str(source.get("id", "")).strip()
            if source_id in local_ids or source_id in all_source_ids:
                failures.append(f"source id {source_id!r} must be globally unique")
            local_ids.add(source_id)
            all_source_ids.add(source_id)
            source_failures = _validate_source(game_root, source)
            failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
            source_results.append({"id": source_id, "failures": source_failures})

        if failures:
            _issue(
                issues,
                "error",
                "route-section-invalid",
                f"Route section {section_id!r} is invalid: {failures[0]}",
                section_id=section_id,
                failures=failures,
            )
        section_results.append(
            {
                "id": section_id,
                "label": label,
                "claim_ids": claim_ids,
                "sources": source_results,
                "failures": failures,
            }
        )

    duplicates = sorted(claim_id for claim_id, count in Counter(assigned_claims).items() if count > 1)
    missing = sorted(set(claims) - set(assigned_claims))
    if duplicates or missing:
        _issue(
            issues,
            "error",
            "route-section-claim-coverage-invalid",
            "Every Main Route claim must belong to exactly one route section.",
            duplicated_claims=duplicates,
            missing_claims=missing,
        )
    undeclared_section_markers = sorted(set(section_markers) - set(sections))
    if undeclared_section_markers:
        _issue(
            issues,
            "error",
            "undeclared-route-section",
            f"Markdown section marker {undeclared_section_markers[0]!r} has no route_structure entry.",
            section_ids=undeclared_section_markers,
        )

    chapter_rows = raw.get("chapters", [])
    if not isinstance(chapter_rows, list):
        _issue(issues, "error", "route-chapters-invalid", "route_structure.chapters must be a list.")
        chapter_rows = []
    if mode == "chapters-and-sections" and not chapter_rows:
        _issue(
            issues,
            "error",
            "route-chapters-missing",
            "chapters-and-sections mode requires at least one source-backed chapter.",
        )
    if mode == "sections" and chapter_rows:
        _issue(
            issues,
            "error",
            "route-chapters-unexpected",
            "sections mode must not declare chapters.",
        )

    chapter_markers = Counter(match.group("id") for match in CHAPTER_MARKER_RE.finditer(markdown))
    chapters: dict[str, dict[str, Any]] = {}
    chapter_results: list[dict[str, Any]] = []
    assigned_sections: list[str] = []
    for index, raw_chapter in enumerate(chapter_rows):
        chapter = raw_chapter if isinstance(raw_chapter, dict) else {}
        chapter_id = str(chapter.get("id", "")).strip()
        label = str(chapter.get("label", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(chapter_id):
            failures.append("id must be a nonempty kebab-case identifier")
            chapter_id = chapter_id or f"invalid-chapter-{index + 1}"
        if chapter_id in chapters:
            failures.append("chapter id is duplicated")
        chapters[chapter_id] = chapter
        if not label:
            failures.append("label must be nonempty")
        elif _normalize(label) not in _normalize(markdown):
            failures.append(f"chapter label is missing from Markdown: {label!r}")
        if chapter_markers.get(chapter_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one route-chapter marker; observed {chapter_markers.get(chapter_id, 0)}"
            )

        section_ids = chapter.get("section_ids")
        if not isinstance(section_ids, list) or not section_ids or any(not isinstance(row, str) for row in section_ids):
            failures.append("section_ids must contain at least one route section id")
            section_ids = []
        if len(set(section_ids)) != len(section_ids):
            failures.append("section_ids contains duplicates")
        for section_id in section_ids:
            if section_id not in sections:
                failures.append(f"section {section_id!r} does not exist")
        assigned_sections.extend(section_ids)

        sources = chapter.get("sources")
        if not isinstance(sources, list) or not sources:
            failures.append("sources must prove the game-authored chapter label or boundary")
            sources = []
        source_results: list[dict[str, Any]] = []
        local_ids: set[str] = set()
        for raw_source in sources:
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = str(source.get("id", "")).strip()
            if source_id in local_ids or source_id in all_source_ids:
                failures.append(f"source id {source_id!r} must be globally unique")
            local_ids.add(source_id)
            all_source_ids.add(source_id)
            source_failures = _validate_source(game_root, source)
            failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
            source_results.append({"id": source_id, "failures": source_failures})

        if failures:
            _issue(
                issues,
                "error",
                "route-chapter-invalid",
                f"Route chapter {chapter_id!r} is invalid: {failures[0]}",
                chapter_id=chapter_id,
                failures=failures,
            )
        chapter_results.append(
            {
                "id": chapter_id,
                "label": label,
                "section_ids": section_ids,
                "sources": source_results,
                "failures": failures,
            }
        )

    if mode == "chapters-and-sections":
        duplicate_sections = sorted(
            section_id for section_id, count in Counter(assigned_sections).items() if count > 1
        )
        missing_sections = sorted(set(sections) - set(assigned_sections))
        if duplicate_sections or missing_sections:
            _issue(
                issues,
                "error",
                "route-chapter-section-coverage-invalid",
                "Every route section must belong to exactly one chapter.",
                duplicated_sections=duplicate_sections,
                missing_sections=missing_sections,
            )
    undeclared_chapter_markers = sorted(set(chapter_markers) - set(chapters))
    if undeclared_chapter_markers:
        _issue(
            issues,
            "error",
            "undeclared-route-chapter",
            f"Markdown chapter marker {undeclared_chapter_markers[0]!r} has no route_structure entry.",
            chapter_ids=undeclared_chapter_markers,
        )
    if mode == "sections" and chapter_markers:
        _issue(
            issues,
            "error",
            "route-chapter-marker-unexpected",
            "sections mode must not render route-chapter markers.",
        )
    return chapters, sections, {
        "mode": mode,
        "source_label": source_label,
        "chapters": chapter_results,
        "sections": section_results,
    }


def _validate_system_reconnaissance(
    evidence_path: Path,
    evidence: dict[str, Any],
    record_ids: set[str],
    source_ids: set[str],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    raw = evidence.get("system_reconnaissance")
    if not isinstance(raw, dict):
        _issue(
            issues,
            "error",
            "system-reconnaissance-missing",
            "evidence.json must bind its active-system inventory and deep-audit coverage.",
        )
        return {"inventory_artifact": "", "systems": [], "coverage": []}

    artifact_name = str(raw.get("inventory_artifact", "")).strip()
    artifact_path = evidence_path.parent / artifact_name
    if (
        not artifact_name
        or Path(artifact_name).name != artifact_name
        or artifact_path.resolve().parent != evidence_path.parent.resolve()
        or not artifact_path.is_file()
    ):
        _issue(
            issues,
            "error",
            "systems-inventory-missing",
            "system_reconnaissance.inventory_artifact must name an existing sibling JSON file.",
            inventory_artifact=artifact_name,
        )
        return {"inventory_artifact": artifact_name, "systems": [], "coverage": []}
    try:
        inventory = _read_json(artifact_path)
    except ValidationInputError as exc:
        _issue(issues, "error", "systems-inventory-invalid", str(exc))
        return {"inventory_artifact": artifact_name, "systems": [], "coverage": []}

    inventory_rows = inventory.get("systems") if isinstance(inventory, dict) else None
    if not isinstance(inventory_rows, list) or not inventory_rows:
        _issue(
            issues,
            "error",
            "systems-inventory-invalid",
            "systems-inventory.json must contain a nonempty systems list.",
        )
        inventory_rows = []

    declared_decisions = raw.get("decisions")
    if not isinstance(declared_decisions, dict):
        declared_decisions = {}
        _issue(
            issues,
            "error",
            "system-decisions-invalid",
            "system_reconnaissance.decisions must map every inventory system to its decision.",
        )

    coverage_rows = raw.get("coverage")
    if not isinstance(coverage_rows, list):
        coverage_rows = []
        _issue(
            issues,
            "error",
            "system-coverage-invalid",
            "system_reconnaissance.coverage must be a list.",
        )
    coverage_by_system: dict[str, dict[str, Any]] = {}
    for raw_coverage in coverage_rows:
        coverage = raw_coverage if isinstance(raw_coverage, dict) else {}
        system_id = str(coverage.get("system_id", "")).strip()
        if not ID_RE.fullmatch(system_id) or system_id in coverage_by_system:
            _issue(
                issues,
                "error",
                "system-coverage-invalid",
                "Every coverage row needs a unique kebab-case system_id.",
                system_id=system_id,
            )
            continue
        coverage_by_system[system_id] = coverage

    inventory_decisions: dict[str, str] = {}
    system_results: list[dict[str, Any]] = []
    for raw_system in inventory_rows:
        system = raw_system if isinstance(raw_system, dict) else {}
        system_id = str(system.get("id", "")).strip()
        decision = str(system.get("decision", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(system_id) or system_id in inventory_decisions:
            failures.append("system id must be unique kebab-case")
        if decision not in SYSTEM_DECISIONS:
            failures.append(f"decision must be one of {sorted(SYSTEM_DECISIONS)}")
        inventory_decisions[system_id] = decision
        if declared_decisions.get(system_id) != decision:
            failures.append("evidence decision does not match the inventory")

        required_rows = system.get("required_topics", [])
        if decision == "deep-audit" and (not isinstance(required_rows, list) or not required_rows):
            failures.append("deep-audit systems require at least one required_topics row")
            required_rows = []
        elif not isinstance(required_rows, list):
            failures.append("required_topics must be a list")
            required_rows = []

        coverage = coverage_by_system.get(system_id, {})
        topic_rows = coverage.get("topics", []) if isinstance(coverage, dict) else []
        if decision == "deep-audit" and (not isinstance(topic_rows, list) or not topic_rows):
            failures.append("deep-audit system has no evidence coverage topics")
            topic_rows = []
        elif not isinstance(topic_rows, list):
            failures.append("coverage topics must be a list")
            topic_rows = []
        topics_by_id: dict[str, dict[str, Any]] = {}
        for raw_topic in topic_rows:
            topic = raw_topic if isinstance(raw_topic, dict) else {}
            topic_id = str(topic.get("id", "")).strip()
            if not ID_RE.fullmatch(topic_id) or topic_id in topics_by_id:
                failures.append("coverage topic ids must be unique kebab-case")
                continue
            topics_by_id[topic_id] = topic

        required_ids: list[str] = []
        for raw_required in required_rows:
            required = raw_required if isinstance(raw_required, dict) else {}
            topic_id = str(required.get("id", "")).strip()
            label = str(required.get("label", "")).strip()
            if not ID_RE.fullmatch(topic_id) or topic_id in required_ids:
                failures.append("required topic ids must be unique kebab-case")
                continue
            required_ids.append(topic_id)
            if not label:
                failures.append(f"required topic {topic_id!r} needs a label")
            topic = topics_by_id.get(topic_id)
            if topic is None:
                failures.append(f"required topic {topic_id!r} has no coverage row")
                continue
            guide_ids = topic.get("guide_record_ids")
            bound_sources = topic.get("source_ids")
            if not isinstance(guide_ids, list) or not guide_ids or any(
                not isinstance(record_id, str) for record_id in guide_ids
            ):
                failures.append(f"topic {topic_id!r} needs guide_record_ids")
            else:
                unknown_records = sorted(set(guide_ids) - record_ids)
                if unknown_records:
                    failures.append(
                        f"topic {topic_id!r} references unknown guide record {unknown_records[0]!r}"
                    )
            if not isinstance(bound_sources, list) or not bound_sources or any(
                not isinstance(source_id, str) for source_id in bound_sources
            ):
                failures.append(f"topic {topic_id!r} needs source_ids")
            else:
                unknown_sources = sorted(set(bound_sources) - source_ids)
                if unknown_sources:
                    failures.append(
                        f"topic {topic_id!r} references unknown evidence source {unknown_sources[0]!r}"
                    )
        extra_topics = sorted(set(topics_by_id) - set(required_ids))
        if extra_topics:
            failures.append(f"coverage topic {extra_topics[0]!r} is not required by the inventory")
        if failures:
            _issue(
                issues,
                "error",
                "system-deep-audit-coverage-invalid",
                f"System {system_id!r} is invalid: {failures[0]}",
                system_id=system_id,
                failures=failures,
            )
        system_results.append(
            {"id": system_id, "decision": decision, "required_topic_ids": required_ids, "failures": failures}
        )

    undeclared_decisions = sorted(set(declared_decisions) - set(inventory_decisions))
    if undeclared_decisions:
        _issue(
            issues,
            "error",
            "system-decisions-invalid",
            f"Evidence declares unknown system decision {undeclared_decisions[0]!r}.",
        )
    unknown_coverage = sorted(set(coverage_by_system) - set(inventory_decisions))
    if unknown_coverage:
        _issue(
            issues,
            "error",
            "system-coverage-invalid",
            f"Evidence covers unknown system {unknown_coverage[0]!r}.",
        )
    return {
        "inventory_artifact": artifact_name,
        "systems": system_results,
        "coverage": coverage_rows,
    }


def _validate_optional_content(
    game_root: Path,
    markdown: str,
    evidence: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    chapters: dict[str, dict[str, Any]],
    all_source_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    raw = evidence.get("optional_content")
    if not isinstance(raw, dict):
        _issue(
            issues,
            "error",
            "optional-content-missing",
            "evidence.json must define the completed Optional Content catalog.",
        )
        return {}, {}, {"source_label": "", "groups": [], "entries": []}

    source_label = str(raw.get("source_label", "")).strip()
    if not source_label:
        _issue(
            issues,
            "error",
            "optional-content-label-missing",
            "optional_content.source_label is required.",
        )

    entry_rows = raw.get("entries")
    if not isinstance(entry_rows, list) or not entry_rows:
        _issue(
            issues,
            "error",
            "optional-entries-missing",
            "optional_content.entries must not be empty.",
        )
        entry_rows = []

    entry_markers = Counter(match.group("id") for match in OPTIONAL_ENTRY_MARKER_RE.finditer(markdown))
    entries: dict[str, dict[str, Any]] = {}
    entry_results: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entry_rows):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        entry_id = str(entry.get("id", "")).strip()
        title = str(entry.get("title", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(entry_id):
            failures.append("id must be a nonempty kebab-case identifier")
            entry_id = entry_id or f"invalid-optional-entry-{index + 1}"
        if entry_id in entries:
            failures.append("entry id is duplicated")
        if entry_id in claims:
            failures.append("entry id must be globally unique from Main Route claim ids")
        entries[entry_id] = entry
        if not title:
            failures.append("title must be nonempty")
        elif _normalize(title) not in _normalize(markdown):
            failures.append(f"title is missing from Markdown: {title!r}")
        kind = str(entry.get("kind", "")).strip()
        if kind not in OPTIONAL_KINDS:
            failures.append(f"kind must be one of {sorted(OPTIONAL_KINDS)}")
        status = str(entry.get("status", "")).strip()
        if status not in CLAIM_STATUSES:
            failures.append(f"status must be one of {sorted(CLAIM_STATUSES)}")
        if "limitations" in entry:
            failures.append("limitations are not publishable; narrow the prose to verified main details")
        if entry_markers.get(entry_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one optional-entry marker; observed {entry_markers.get(entry_id, 0)}"
            )

        anchor_id = str(entry.get("route_anchor_id", "")).strip()
        if anchor_id not in claims:
            failures.append(f"route_anchor_id {anchor_id!r} is not a Main Route claim")
        anchor_position = str(entry.get("route_anchor_position", "")).strip()
        if anchor_position not in ROUTE_ANCHOR_POSITIONS:
            failures.append(
                f"route_anchor_position must be one of {sorted(ROUTE_ANCHOR_POSITIONS)}"
            )

        prerequisites = entry.get("prerequisite_entry_ids", [])
        if not isinstance(prerequisites, list) or any(not isinstance(row, str) for row in prerequisites):
            failures.append("prerequisite_entry_ids must be a list of entry ids")
            prerequisites = []
        if len(set(prerequisites)) != len(prerequisites):
            failures.append("prerequisite_entry_ids contains duplicates")
        if entry_id in prerequisites:
            failures.append("an optional entry cannot require itself")

        phrases = entry.get("guide_phrases")
        if not isinstance(phrases, list) or not phrases or any(
            not isinstance(row, str) or not row.strip() for row in phrases
        ):
            failures.append("guide_phrases must contain at least one nonempty string")
            phrases = []
        normalized_markdown = _normalize(markdown)
        for phrase in phrases:
            if _normalize(phrase) not in normalized_markdown:
                failures.append(f"guide phrase is missing from Markdown: {phrase!r}")

        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            failures.append("sources must contain at least one source snapshot")
            sources = []
        source_results: list[dict[str, Any]] = []
        local_ids: set[str] = set()
        for raw_source in sources:
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = str(source.get("id", "")).strip()
            if source_id in local_ids or source_id in all_source_ids:
                failures.append(f"source id {source_id!r} must be globally unique")
            local_ids.add(source_id)
            all_source_ids.add(source_id)
            source_failures = _validate_source(game_root, source)
            failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
            source_results.append({"id": source_id, "failures": source_failures})

        failures.extend(
            _validate_recruitment_contract(entry, kind, phrases, markdown, local_ids)
        )
        if failures:
            _issue(
                issues,
                "error",
                "optional-entry-invalid",
                f"Optional entry {entry_id!r} is invalid: {failures[0]}",
                entry_id=entry_id,
                failures=failures,
            )
        entry_results.append(
            {
                "id": entry_id,
                "title": title,
                "kind": kind,
                "status": "contradicted" if failures else "verified",
                "evidence_status": status,
                "route_anchor_id": anchor_id,
                "route_anchor_position": anchor_position,
                "prerequisite_entry_ids": prerequisites,
                "sources": source_results,
                "failures": failures,
            }
        )

    for entry_id, entry in entries.items():
        missing = sorted(
            prerequisite
            for prerequisite in (entry.get("prerequisite_entry_ids") or [])
            if prerequisite not in entries
        )
        if missing:
            _issue(
                issues,
                "error",
                "optional-prerequisite-missing",
                f"Optional entry {entry_id!r} references unknown prerequisite {missing[0]!r}.",
                entry_id=entry_id,
                prerequisite_entry_ids=missing,
            )
    undeclared_entry_markers = sorted(set(entry_markers) - set(entries))
    if undeclared_entry_markers:
        _issue(
            issues,
            "error",
            "undeclared-optional-entry",
            f"Markdown optional-entry marker {undeclared_entry_markers[0]!r} has no evidence entry.",
            entry_ids=undeclared_entry_markers,
        )

    group_rows = raw.get("groups")
    if not isinstance(group_rows, list) or not group_rows:
        _issue(
            issues,
            "error",
            "optional-groups-missing",
            "optional_content.groups must not be empty.",
        )
        group_rows = []
    group_markers = Counter(match.group("id") for match in OPTIONAL_GROUP_MARKER_RE.finditer(markdown))
    groups: dict[str, dict[str, Any]] = {}
    group_results: list[dict[str, Any]] = []
    assigned_entries: list[str] = []
    for index, raw_group in enumerate(group_rows):
        group = raw_group if isinstance(raw_group, dict) else {}
        group_id = str(group.get("id", "")).strip()
        label = str(group.get("label", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(group_id):
            failures.append("id must be a nonempty kebab-case identifier")
            group_id = group_id or f"invalid-optional-group-{index + 1}"
        if group_id in groups or group_id in claims or group_id in entries:
            failures.append("group id must be globally unique")
        groups[group_id] = group
        if not label:
            failures.append("label must be nonempty")
        elif _normalize(label) not in _normalize(markdown):
            failures.append(f"group label is missing from Markdown: {label!r}")
        if group_markers.get(group_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one optional-group marker; observed {group_markers.get(group_id, 0)}"
            )
        entry_ids = group.get("entry_ids")
        if not isinstance(entry_ids, list) or not entry_ids or any(not isinstance(row, str) for row in entry_ids):
            failures.append("entry_ids must contain at least one optional entry id")
            entry_ids = []
        if len(set(entry_ids)) != len(entry_ids):
            failures.append("entry_ids contains duplicates")
        for entry_id in entry_ids:
            if entry_id not in entries:
                failures.append(f"optional entry {entry_id!r} does not exist")
        assigned_entries.extend(entry_ids)

        route_chapter_id = group.get("route_chapter_id")
        route_anchor_id = group.get("route_anchor_id")
        if route_chapter_id is not None and route_anchor_id is not None:
            failures.append("use route_chapter_id or route_anchor_id, not both")
        elif route_chapter_id is not None:
            if str(route_chapter_id) not in chapters:
                failures.append(f"route_chapter_id {route_chapter_id!r} does not exist")
        elif route_anchor_id is not None:
            if str(route_anchor_id) not in claims:
                failures.append(f"route_anchor_id {route_anchor_id!r} does not exist")
        else:
            failures.append("group must bind to a route_chapter_id or route_anchor_id")

        if failures:
            _issue(
                issues,
                "error",
                "optional-group-invalid",
                f"Optional group {group_id!r} is invalid: {failures[0]}",
                group_id=group_id,
                failures=failures,
            )
        group_results.append(
            {"id": group_id, "label": label, "entry_ids": entry_ids, "failures": failures}
        )

    duplicate_entries = sorted(
        entry_id for entry_id, count in Counter(assigned_entries).items() if count > 1
    )
    missing_entries = sorted(set(entries) - set(assigned_entries))
    if duplicate_entries or missing_entries:
        _issue(
            issues,
            "error",
            "optional-group-entry-coverage-invalid",
            "Every Optional Content entry must belong to exactly one group.",
            duplicated_entries=duplicate_entries,
            missing_entries=missing_entries,
        )
    undeclared_group_markers = sorted(set(group_markers) - set(groups))
    if undeclared_group_markers:
        _issue(
            issues,
            "error",
            "undeclared-optional-group",
            f"Markdown optional-group marker {undeclared_group_markers[0]!r} has no evidence group.",
            group_ids=undeclared_group_markers,
        )

    return groups, entries, {
        "source_label": source_label,
        "groups": group_results,
        "entries": entry_results,
    }


def _validate_bosses(
    game_root: Path,
    markdown: str,
    evidence: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    optional_entries: dict[str, dict[str, Any]],
    all_source_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    raw = evidence.get("bosses")
    if not isinstance(raw, dict):
        _issue(issues, "error", "bosses-missing", "evidence.json must define the completed Bosses catalog.")
        return {}, {}, {"source_label": "", "groups": [], "entries": []}

    source_label = str(raw.get("source_label", "")).strip()
    if not source_label:
        _issue(issues, "error", "bosses-label-missing", "bosses.source_label is required.")

    entry_rows = raw.get("entries")
    if not isinstance(entry_rows, list) or not entry_rows:
        _issue(issues, "error", "boss-entries-missing", "bosses.entries must not be empty.")
        entry_rows = []
    entry_markers = Counter(match.group("id") for match in BOSS_ENTRY_MARKER_RE.finditer(markdown))
    entries: dict[str, dict[str, Any]] = {}
    entry_results: list[dict[str, Any]] = []
    reserved_ids = set(claims) | set(optional_entries)
    normalized_markdown = _normalize(markdown)
    for index, raw_entry in enumerate(entry_rows):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        entry_id = str(entry.get("id", "")).strip()
        title = str(entry.get("title", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(entry_id):
            failures.append("id must be a nonempty kebab-case identifier")
            entry_id = entry_id or f"invalid-boss-entry-{index + 1}"
        if entry_id in entries:
            failures.append("boss id is duplicated")
        if entry_id in reserved_ids:
            failures.append("boss id must be globally unique from route and optional entry ids")
        entries[entry_id] = entry
        if not title:
            failures.append("title must be nonempty")
        elif _normalize(title) not in normalized_markdown:
            failures.append(f"title is missing from Markdown: {title!r}")
        kind = str(entry.get("kind", "")).strip()
        if kind not in BOSS_KINDS:
            failures.append(f"kind must be one of {sorted(BOSS_KINDS)}")
        status = str(entry.get("status", "")).strip()
        if status not in CLAIM_STATUSES:
            failures.append(f"status must be one of {sorted(CLAIM_STATUSES)}")
        if entry_markers.get(entry_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one boss-entry marker; observed {entry_markers.get(entry_id, 0)}"
            )

        route_claim_ids = entry.get("route_claim_ids")
        optional_entry_ids = entry.get("optional_entry_ids")
        if not isinstance(route_claim_ids, list) or any(not isinstance(row, str) for row in route_claim_ids):
            failures.append("route_claim_ids must be a list of Main Route claim ids")
            route_claim_ids = []
        if not isinstance(optional_entry_ids, list) or any(not isinstance(row, str) for row in optional_entry_ids):
            failures.append("optional_entry_ids must be a list of Optional Content entry ids")
            optional_entry_ids = []
        if not route_claim_ids and not optional_entry_ids:
            failures.append("at least one route_claim_id or optional_entry_id is required")
        if len(set(route_claim_ids)) != len(route_claim_ids):
            failures.append("route_claim_ids contains duplicates")
        if len(set(optional_entry_ids)) != len(optional_entry_ids):
            failures.append("optional_entry_ids contains duplicates")
        for claim_id in route_claim_ids:
            if claim_id not in claims:
                failures.append(f"route claim {claim_id!r} does not exist")
        for optional_id in optional_entry_ids:
            if optional_id not in optional_entries:
                failures.append(f"optional entry {optional_id!r} does not exist")

        phases = entry.get("phases")
        if not isinstance(phases, list) or not phases:
            failures.append("phases must contain at least one verified boss form")
            phases = []
        for phase_index, phase in enumerate(phases, 1):
            if not isinstance(phase, dict):
                failures.append(f"phase {phase_index} must be an object")
                continue
            if not str(phase.get("label", "")).strip():
                failures.append(f"phase {phase_index} label must be nonempty")
            enemy_id = phase.get("enemy_id")
            if not isinstance(enemy_id, int) or enemy_id <= 0:
                failures.append(f"phase {phase_index} enemy_id must be a positive integer")
            participants = phase.get("participants")
            if not isinstance(participants, dict):
                failures.append(f"phase {phase_index} participants must be an object")
                participants = {}
            mode = str(participants.get("mode", "")).strip()
            if mode not in {"fixed", "solo", "variable"}:
                failures.append(f"phase {phase_index} participants.mode must be fixed, solo, or variable")
            participant_lists: dict[str, list[int]] = {}
            for field, allow_empty in (
                ("active_actor_ids", False),
                ("conditional_actor_ids", True),
                ("removed_actor_ids", True),
            ):
                values = participants.get(field)
                if (
                    not isinstance(values, list)
                    or (not allow_empty and not values)
                    or any(not isinstance(value, int) or value <= 0 for value in values)
                ):
                    failures.append(
                        f"phase {phase_index} participants.{field} must be "
                        f"{'a nonempty' if not allow_empty else 'a'} list of positive actor ids"
                    )
                    values = []
                if len(set(values)) != len(values):
                    failures.append(f"phase {phase_index} participants.{field} contains duplicates")
                participant_lists[field] = values
            all_participant_ids = [value for values in participant_lists.values() for value in values]
            if len(set(all_participant_ids)) != len(all_participant_ids):
                failures.append(f"phase {phase_index} participant actor ids must not overlap between lists")
            max_active_battlers = participants.get("max_active_battlers")
            if not isinstance(max_active_battlers, int) or max_active_battlers <= 0:
                failures.append(f"phase {phase_index} participants.max_active_battlers must be a positive integer")
                max_active_battlers = 0
            active_count = len(participant_lists["active_actor_ids"])
            eligible_count = active_count + len(participant_lists["conditional_actor_ids"])
            if max_active_battlers and not active_count <= max_active_battlers <= eligible_count:
                failures.append(
                    f"phase {phase_index} participants.max_active_battlers must cover the active actors "
                    "without exceeding the active and conditional roster"
                )
            if mode == "fixed" and (
                participant_lists["conditional_actor_ids"]
                or max_active_battlers != active_count
            ):
                failures.append(
                    f"phase {phase_index} fixed participant mode requires no conditional actors and a maximum equal to the active roster"
                )
            if mode == "variable" and not participant_lists["conditional_actor_ids"]:
                failures.append(f"phase {phase_index} variable participant mode requires conditional actors")
            if mode == "solo" and (
                active_count != 1
                or participant_lists["conditional_actor_ids"]
                or max_active_battlers != 1
            ):
                failures.append(
                    f"phase {phase_index} solo participant mode requires exactly one active actor, no conditional actors, and a maximum of one"
                )
            if not str(participants.get("text", "")).strip():
                failures.append(f"phase {phase_index} participants.text must be nonempty player-facing text")
            participant_source_ids = participants.get("source_ids")
            if (
                not isinstance(participant_source_ids, list)
                or not participant_source_ids
                or any(not isinstance(value, str) or not value for value in participant_source_ids)
            ):
                failures.append(f"phase {phase_index} participants must cite one or more source_ids")
            stats = phase.get("stats")
            if not isinstance(stats, dict) or not stats:
                failures.append(f"phase {phase_index} stats must be a nonempty object")
            if not isinstance(phase.get("exp"), int) or int(phase.get("exp", -1)) < 0:
                failures.append(f"phase {phase_index} exp must be a nonnegative integer")
            if not isinstance(phase.get("gold"), int) or int(phase.get("gold", -1)) < 0:
                failures.append(f"phase {phase_index} gold must be a nonnegative integer")
            if not isinstance(phase.get("drops"), str) or not str(phase.get("drops", "")).strip():
                failures.append(f"phase {phase_index} drops must be nonempty player-facing text")
            if not isinstance(phase.get("element_read"), str) or not str(phase.get("element_read", "")).strip():
                failures.append(f"phase {phase_index} element_read must be nonempty player-facing text")
            threats = phase.get("threats")
            if not isinstance(threats, list) or not threats:
                failures.append(f"phase {phase_index} threats must contain at least one explained battle threat")
                threats = []
            for threat_index, threat in enumerate(threats, 1):
                if not isinstance(threat, dict) or not str(threat.get("text", "")).strip():
                    failures.append(f"phase {phase_index} threat {threat_index} must contain nonempty player-facing text")
                    continue
                source_ids = threat.get("source_ids")
                if not isinstance(source_ids, list) or not source_ids or any(not isinstance(row, str) or not row for row in source_ids):
                    failures.append(f"phase {phase_index} threat {threat_index} must cite one or more source_ids")
            how_to_win = phase.get("how_to_win")
            if not isinstance(how_to_win, dict):
                failures.append(f"phase {phase_index} how_to_win must be an object")
                how_to_win = {}
            for section_name in ("tools", "plan"):
                rows = how_to_win.get(section_name)
                if not isinstance(rows, list):
                    failures.append(f"phase {phase_index} how_to_win.{section_name} must be a list")
                    continue
                if section_name == "plan" and not rows:
                    failures.append(f"phase {phase_index} how_to_win.plan must not be empty")
                    continue
                for row_index, row in enumerate(rows, 1):
                    if not isinstance(row, dict) or not str(row.get("text", "")).strip():
                        failures.append(f"phase {phase_index} how_to_win.{section_name} row {row_index} requires text")
                        continue
                    source_ids = row.get("source_ids")
                    if not isinstance(source_ids, list) or not source_ids or any(not isinstance(value, str) or not value for value in source_ids):
                        failures.append(f"phase {phase_index} how_to_win.{section_name} row {row_index} must cite source_ids")
                    if section_name == "tools" and not str(row.get("availability", "")).strip():
                        failures.append(f"phase {phase_index} how_to_win.tools row {row_index} requires an availability label")

        phrases = entry.get("guide_phrases")
        if not isinstance(phrases, list) or not phrases or any(not isinstance(row, str) or not row.strip() for row in phrases):
            failures.append("guide_phrases must contain nonempty player-facing text")
            phrases = []
        for phrase in phrases:
            if _normalize(phrase) not in normalized_markdown:
                failures.append(f"guide phrase is missing from Markdown: {phrase!r}")

        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            failures.append("sources must contain encounter, enemy, action, and outcome snapshots")
            sources = []
        local_ids: set[str] = set()
        source_results: list[dict[str, Any]] = []
        for raw_source in sources:
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = str(source.get("id", "")).strip()
            if source_id in local_ids or source_id in all_source_ids:
                failures.append(f"source id {source_id!r} must be globally unique")
            local_ids.add(source_id)
            all_source_ids.add(source_id)
            source_failures = _validate_source(game_root, source)
            failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
            source_results.append({"id": source_id, "failures": source_failures})

        battle_sources = [
            source
            for source in sources
            if isinstance(source, dict)
            and source.get("type") == "event-command"
            and isinstance(source.get("expected"), dict)
            and source["expected"].get("code") == 301
        ]
        if not battle_sources:
            failures.append("sources must include a battle-processing event command")
        troop_sources = [
            source
            for source in sources
            if isinstance(source, dict)
            and source.get("type") == "database-record"
            and source.get("file") == "data/Troops.json"
        ]
        if not troop_sources:
            failures.append("sources must include the initial troop record")
        required_enemy_fields = {"name", "params", "exp", "gold", "dropItems", "actions", "traits"}
        for phase_index, phase in enumerate(phases, 1):
            if not isinstance(phase, dict) or not isinstance(phase.get("enemy_id"), int):
                continue
            enemy_sources = [
                source
                for source in sources
                if isinstance(source, dict)
                and source.get("type") == "database-record"
                and source.get("file") == "data/Enemies.json"
                and source.get("record_id") == phase["enemy_id"]
                and isinstance(source.get("expected"), dict)
            ]
            if not any(required_enemy_fields <= set(source["expected"]) for source in enemy_sources):
                failures.append(
                    f"phase {phase_index} requires one enemy snapshot covering {sorted(required_enemy_fields)}"
                )
        for phase_index, phase in enumerate(phases, 1):
            if not isinstance(phase, dict):
                continue
            guidance_rows = [
                phase.get("participants") or {},
                *(phase.get("threats") or []),
                *((phase.get("how_to_win") or {}).get("tools") or []),
                *((phase.get("how_to_win") or {}).get("plan") or []),
            ]
            for guidance_index, guidance in enumerate(guidance_rows, 1):
                if not isinstance(guidance, dict):
                    continue
                references = guidance.get("source_ids") or []
                missing = sorted(set(references) - local_ids) if isinstance(references, list) else []
                if missing:
                    failures.append(
                        f"phase {phase_index} guidance row {guidance_index} cites unknown source_ids {missing}"
                    )
        uses_element_mapping = any(
            isinstance(phase, dict)
            and isinstance(phase.get("element_read"), str)
            and "no encoded elemental weakness or resistance" not in phase["element_read"]
            for phase in phases
        )
        if uses_element_mapping and not any(
            isinstance(source, dict)
            and source.get("type") == "file-excerpt"
            and source.get("file") == "data/System.json"
            for source in sources
        ):
            failures.append("published element rates require a pinned System.json element-name excerpt")

        if failures:
            _issue(
                issues,
                "error",
                "boss-entry-invalid",
                f"Boss entry {entry_id!r} is invalid: {failures[0]}",
                boss_id=entry_id,
                failures=failures,
            )
        entry_results.append(
            {
                "id": entry_id,
                "title": title,
                "kind": kind,
                "status": "contradicted" if failures else "verified",
                "evidence_status": status,
                "sources": source_results,
                "failures": failures,
            }
        )

    undeclared_entry_markers = sorted(set(entry_markers) - set(entries))
    if undeclared_entry_markers:
        _issue(
            issues,
            "error",
            "undeclared-boss-entry",
            f"Markdown boss-entry marker {undeclared_entry_markers[0]!r} has no evidence entry.",
            boss_ids=undeclared_entry_markers,
        )

    group_rows = raw.get("groups")
    if not isinstance(group_rows, list) or not group_rows:
        _issue(issues, "error", "boss-groups-missing", "bosses.groups must not be empty.")
        group_rows = []
    group_markers = Counter(match.group("id") for match in BOSS_GROUP_MARKER_RE.finditer(markdown))
    groups: dict[str, dict[str, Any]] = {}
    group_results: list[dict[str, Any]] = []
    assigned_entries: list[str] = []
    for index, raw_group in enumerate(group_rows):
        group = raw_group if isinstance(raw_group, dict) else {}
        group_id = str(group.get("id", "")).strip()
        label = str(group.get("label", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(group_id):
            failures.append("id must be a nonempty kebab-case identifier")
            group_id = group_id or f"invalid-boss-group-{index + 1}"
        if group_id in groups or group_id in reserved_ids or group_id in entries:
            failures.append("boss group id must be globally unique")
        groups[group_id] = group
        if not label:
            failures.append("label must be nonempty")
        elif _normalize(label) not in normalized_markdown:
            failures.append(f"label is missing from Markdown: {label!r}")
        if group_markers.get(group_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one boss-group marker; observed {group_markers.get(group_id, 0)}"
            )
        entry_ids = group.get("entry_ids")
        if not isinstance(entry_ids, list) or not entry_ids or any(not isinstance(row, str) for row in entry_ids):
            failures.append("entry_ids must contain at least one boss id")
            entry_ids = []
        if len(set(entry_ids)) != len(entry_ids):
            failures.append("entry_ids contains duplicates")
        for entry_id in entry_ids:
            if entry_id not in entries:
                failures.append(f"boss entry {entry_id!r} does not exist")
        assigned_entries.extend(entry_ids)
        if failures:
            _issue(
                issues,
                "error",
                "boss-group-invalid",
                f"Boss group {group_id!r} is invalid: {failures[0]}",
                group_id=group_id,
                failures=failures,
            )
        group_results.append({"id": group_id, "label": label, "entry_ids": entry_ids, "failures": failures})

    duplicate_entries = sorted(entry_id for entry_id, count in Counter(assigned_entries).items() if count > 1)
    missing_entries = sorted(set(entries) - set(assigned_entries))
    if duplicate_entries or missing_entries:
        _issue(
            issues,
            "error",
            "boss-group-entry-coverage-invalid",
            "Every boss entry must belong to exactly one boss group.",
            duplicated_entries=duplicate_entries,
            missing_entries=missing_entries,
        )
    undeclared_group_markers = sorted(set(group_markers) - set(groups))
    if undeclared_group_markers:
        _issue(
            issues,
            "error",
            "undeclared-boss-group",
            f"Markdown boss-group marker {undeclared_group_markers[0]!r} has no evidence group.",
            group_ids=undeclared_group_markers,
        )

    return groups, entries, {
        "source_label": source_label,
        "groups": group_results,
        "entries": entry_results,
    }


def _validate_scene_source_roles(
    roles: Any,
    required_roles: set[str],
    local_source_ids: set[str],
    failures: list[str],
    *,
    cg_image_count: int | None = None,
) -> None:
    if not isinstance(roles, dict):
        failures.append("source_roles must be an object")
        return
    missing_roles = sorted(required_roles - set(roles))
    if missing_roles:
        failures.append(f"source_roles is missing required roles {missing_roles}")
    for role, source_ids in roles.items():
        if (
            not isinstance(role, str)
            or not role
            or not isinstance(source_ids, list)
            or not source_ids
            or any(not isinstance(source_id, str) or not source_id for source_id in source_ids)
        ):
            failures.append(f"source_roles.{role} must contain one or more source ids")
            continue
        unknown = sorted(set(source_ids) - local_source_ids)
        if unknown:
            failures.append(f"source_roles.{role} cites unknown source ids {unknown}")
    if cg_image_count is not None and isinstance(roles.get("cg_viewer"), list):
        if len(roles["cg_viewer"]) != cg_image_count:
            failures.append("source_roles.cg_viewer must cite exactly one source per illustrated set")


def _scene_source_locator(source: dict[str, Any]) -> tuple[Any, ...]:
    """Return the executable locator used to distinguish live play from a catalog surface."""
    source_type = str(source.get("type", ""))
    base: tuple[Any, ...] = (source_type, str(source.get("file", "")))
    if source_type == "event-command":
        return base + (
            source.get("event_id"),
            source.get("page_index"),
            source.get("command_index"),
        )
    if source_type == "database-record":
        return base + (source.get("record_id"),)
    if source_type == "file-excerpt":
        return base + (source.get("contains"),)
    if source_type == "file-hash":
        return base + (source.get("sha256"),)
    return base


def _validate_scenes_cg(
    game_root: Path,
    markdown: str,
    evidence: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    optional_entries: dict[str, dict[str, Any]],
    boss_entries: dict[str, dict[str, Any]],
    all_source_ids: set[str],
    issues: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    raw = evidence.get("scenes_cg")
    if not isinstance(raw, dict):
        _issue(issues, "error", "scenes-cg-missing", "evidence.json must define the completed Scenes & CG catalog.")
        return {}, {}, {}, {"source_label": "", "catalog": {}, "groups": [], "entries": []}

    source_label = str(raw.get("source_label", "")).strip()
    if not source_label:
        _issue(issues, "error", "scenes-cg-label-missing", "scenes_cg.source_label is required.")
    normalized_markdown = _normalize(markdown)
    reserved_ids = set(claims) | set(optional_entries) | set(boss_entries)

    catalog_raw = raw.get("catalog")
    catalog = catalog_raw if isinstance(catalog_raw, dict) else {}
    catalog_failures: list[str] = []
    catalog_id = str(catalog.get("id", "")).strip()
    if catalog_id != "scenes-cg-system":
        catalog_failures.append("catalog.id must be 'scenes-cg-system'")
    title = str(catalog.get("title", "")).strip()
    if not title:
        catalog_failures.append("catalog.title must be nonempty")
    entry_count = catalog.get("entry_count")
    cg_total = catalog.get("cg_image_count")
    if not isinstance(entry_count, int) or entry_count <= 0:
        catalog_failures.append("catalog.entry_count must be a positive integer")
    if not isinstance(cg_total, int) or cg_total < 0:
        catalog_failures.append("catalog.cg_image_count must be a nonnegative integer")
    catalog_phrases = catalog.get("guide_phrases")
    if not isinstance(catalog_phrases, list) or not catalog_phrases or any(
        not isinstance(row, str) or not row.strip() for row in catalog_phrases
    ):
        catalog_failures.append("catalog.guide_phrases must contain nonempty player-facing text")
        catalog_phrases = []
    for phrase in catalog_phrases:
        if _normalize(phrase) not in normalized_markdown:
            catalog_failures.append(f"catalog guide phrase is missing from Markdown: {phrase!r}")
    completion_shortcut = str(catalog.get("completion_shortcut", "")).strip()
    if completion_shortcut:
        if completion_shortcut not in catalog_phrases:
            catalog_failures.append("catalog.completion_shortcut must also be one exact catalog guide phrase")
        if _normalize(completion_shortcut) not in normalized_markdown:
            catalog_failures.append("catalog.completion_shortcut is missing from Markdown")
    interface_files = catalog.get("interface_files")
    if not isinstance(interface_files, list) or not interface_files or any(
        not isinstance(row, str) or not row.strip() for row in interface_files
    ):
        catalog_failures.append("catalog.interface_files must list the dedicated catalog/recollection interface files")
        interface_files = []
    elif len(set(interface_files)) != len(interface_files):
        catalog_failures.append("catalog.interface_files must not contain duplicates")
    for interface_file in interface_files:
        _path, failure = _project_file(game_root, interface_file)
        if failure:
            catalog_failures.append(f"catalog.interface_files entry {interface_file!r}: {failure}")
    catalog_sources = catalog.get("sources")
    if not isinstance(catalog_sources, list) or not catalog_sources:
        catalog_failures.append("catalog.sources must prove its player-facing entry point and scope boundary")
        catalog_sources = []
    catalog_source_results: list[dict[str, Any]] = []
    catalog_source_ids: set[str] = set()
    for raw_source in catalog_sources:
        source = raw_source if isinstance(raw_source, dict) else {}
        source_id = str(source.get("id", "")).strip()
        if source_id in catalog_source_ids or source_id in all_source_ids:
            catalog_failures.append(f"source id {source_id!r} must be globally unique")
        catalog_source_ids.add(source_id)
        all_source_ids.add(source_id)
        source_failures = _validate_source(game_root, source)
        catalog_failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
        catalog_source_results.append({"id": source_id, "failures": source_failures})
    required_catalog_roles = {"entry_point", "scope_boundary"}
    if completion_shortcut:
        required_catalog_roles.add("completion_shortcut")
    _validate_scene_source_roles(
        catalog.get("source_roles"),
        required_catalog_roles,
        catalog_source_ids,
        catalog_failures,
    )
    catalog_source_locators = {
        _scene_source_locator(source)
        for source in catalog_sources
        if isinstance(source, dict)
    }
    if catalog_failures:
        _issue(
            issues,
            "error",
            "scenes-cg-catalog-invalid",
            f"Scenes & CG catalog metadata is invalid: {catalog_failures[0]}",
            failures=catalog_failures,
        )

    entry_rows = raw.get("entries")
    if not isinstance(entry_rows, list) or not entry_rows:
        _issue(issues, "error", "scene-entries-missing", "scenes_cg.entries must not be empty.")
        entry_rows = []
    entry_markers = Counter(match.group("id") for match in SCENE_ENTRY_MARKER_RE.finditer(markdown))
    entries: dict[str, dict[str, Any]] = {}
    entry_results: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(entry_rows):
        entry = raw_entry if isinstance(raw_entry, dict) else {}
        entry_id = str(entry.get("id", "")).strip()
        title = str(entry.get("title", "")).strip()
        catalog_title = str(entry.get("catalog_title", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(entry_id):
            failures.append("id must be a nonempty kebab-case identifier")
            entry_id = entry_id or f"invalid-scene-entry-{index + 1}"
        if entry_id in entries:
            failures.append("scene id is duplicated")
        if entry_id in reserved_ids:
            failures.append("scene id must be globally unique from route, optional, and boss entry ids")
        entries[entry_id] = entry
        if not title:
            failures.append("title must be nonempty")
        elif _normalize(title) not in normalized_markdown:
            failures.append(f"title is missing from Markdown: {title!r}")
        if not catalog_title:
            failures.append("catalog_title must preserve the exact player-facing catalog/replay title")
        elif _normalize(catalog_title) not in normalized_markdown:
            failures.append(f"catalog_title is missing from Markdown: {catalog_title!r}")
        elif _normalize(catalog_title) != _normalize(title):
            catalog_label = f"Recollection title: {catalog_title}"
            if _normalize(catalog_label) not in normalized_markdown:
                failures.append("a differing catalog_title must be rendered once as 'Recollection title: <catalog title>' in Markdown")
        kind = str(entry.get("kind", "")).strip()
        if kind not in SCENE_KINDS:
            failures.append(f"kind must be one of {sorted(SCENE_KINDS)}")
        status = str(entry.get("status", "")).strip()
        if status not in CLAIM_STATUSES:
            failures.append(f"status must be one of {sorted(CLAIM_STATUSES)}")
        if entry_markers.get(entry_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one scene-entry marker; observed {entry_markers.get(entry_id, 0)}"
            )
        requirements = entry.get("requirements")
        if not isinstance(requirements, list) or not requirements or any(
            not isinstance(row, str) or not row.strip() for row in requirements
        ):
            failures.append("requirements must contain player-visible unlock requirements")
            requirements = []
        route_anchor_id = str(entry.get("route_anchor_id", "")).strip()
        if route_anchor_id not in claims:
            failures.append(f"route_anchor_id {route_anchor_id!r} is not a Main Route claim")
        route_anchor_position = str(entry.get("route_anchor_position", "")).strip()
        if route_anchor_position not in ROUTE_ANCHOR_POSITIONS:
            failures.append(f"route_anchor_position must be one of {sorted(ROUTE_ANCHOR_POSITIONS)}")
        prerequisite_scene_ids = entry.get("prerequisite_scene_ids")
        if not isinstance(prerequisite_scene_ids, list) or any(
            not isinstance(row, str) or not row.strip() for row in prerequisite_scene_ids
        ):
            failures.append("prerequisite_scene_ids must be a list of scene ids")
            prerequisite_scene_ids = []
        elif len(set(prerequisite_scene_ids)) != len(prerequisite_scene_ids):
            failures.append("prerequisite_scene_ids must not contain duplicates")
        story_gate_claim_ids = entry.get("story_gate_claim_ids")
        if not isinstance(story_gate_claim_ids, list) or any(
            not isinstance(row, str) or not row.strip() for row in story_gate_claim_ids
        ):
            failures.append("story_gate_claim_ids must be a list of Main Route claim ids")
            story_gate_claim_ids = []
        elif len(set(story_gate_claim_ids)) != len(story_gate_claim_ids):
            failures.append("story_gate_claim_ids must not contain duplicates")
        for claim_id in story_gate_claim_ids:
            if claim_id not in claims:
                failures.append(f"story_gate_claim_id {claim_id!r} is not a Main Route claim")
        acquisition_mode = str(entry.get("acquisition_mode", "")).strip()
        if acquisition_mode not in SCENE_ACQUISITION_MODES:
            failures.append(f"acquisition_mode must be one of {sorted(SCENE_ACQUISITION_MODES)}")
        acquisition_steps = entry.get("acquisition_steps")
        if not isinstance(acquisition_steps, list) or not acquisition_steps or any(
            not isinstance(row, str) or not row.strip() for row in acquisition_steps
        ):
            failures.append("acquisition_steps must contain the actionable normal-play path or a proven gallery-only explanation")
            acquisition_steps = []
        combatants: list[str] = []
        encounter_locations: list[str] = []
        combat_mechanic = ""
        if kind == "combat-scene":
            if acquisition_mode != "normal-play":
                failures.append("combat-scene entries must use normal-play acquisition")
            raw_combatants = entry.get("combatants")
            if not isinstance(raw_combatants, list) or not raw_combatants or any(
                not isinstance(row, str) or not row.strip() for row in raw_combatants
            ):
                failures.append("combatants must list every exact player-visible enemy needed for the combat scene")
            else:
                combatants = raw_combatants
                if len(set(combatants)) != len(combatants):
                    failures.append("combatants must not contain duplicates")
            raw_locations = entry.get("encounter_locations")
            if not isinstance(raw_locations, list) or not raw_locations or any(
                not isinstance(row, str) or not row.strip() for row in raw_locations
            ):
                failures.append("encounter_locations must list a recognizable player-visible battle area or encounter")
            else:
                encounter_locations = raw_locations
                if len(set(encounter_locations)) != len(encounter_locations):
                    failures.append("encounter_locations must not contain duplicates")
            combat_mechanic = str(entry.get("combat_mechanic", "")).strip()
            if not combat_mechanic:
                failures.append("combat_mechanic must explain the action/state sequence that triggers the scene")
            elif combat_mechanic not in acquisition_steps:
                failures.append("combat_mechanic must be one exact acquisition_steps sentence")
        aliases = entry.get("aliases")
        if not isinstance(aliases, list) or any(not isinstance(row, str) or not row.strip() for row in aliases):
            failures.append("aliases must be a list of nonempty trigger-title aliases")
        viewer_mode = str(entry.get("viewer_mode", "")).strip()
        if not ID_RE.fullmatch(viewer_mode):
            failures.append("viewer_mode must be a nonempty kebab-case description")
        cg_image_count = entry.get("cg_image_count")
        if not isinstance(cg_image_count, int) or cg_image_count < 0:
            failures.append("cg_image_count must be a nonnegative integer")
            cg_image_count = 0
        phrases = entry.get("guide_phrases")
        if not isinstance(phrases, list) or not phrases or any(
            not isinstance(row, str) or not row.strip() for row in phrases
        ):
            failures.append("guide_phrases must contain nonempty player-facing text")
            phrases = []
        for phrase in phrases:
            if _normalize(phrase) not in normalized_markdown:
                failures.append(f"guide phrase is missing from Markdown: {phrase!r}")
        if kind == "combat-scene":
            acquisition_copy = _normalize(" ".join([*requirements, *acquisition_steps]))
            for combatant in combatants:
                if _normalize(combatant) not in acquisition_copy:
                    failures.append(f"combatant {combatant!r} must be named in requirements or acquisition_steps")
                if _normalize(combatant) not in _normalize(title):
                    failures.append(f"combat-scene title must name combatant {combatant!r}")
            for location in encounter_locations:
                if _normalize(location) not in acquisition_copy:
                    failures.append(f"encounter location {location!r} must appear in requirements or acquisition_steps")
        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            failures.append("sources must prove requirements, title, live trigger, unlock, replay/viewer dispatch, and illustrated-set coverage")
            sources = []
        local_source_ids: set[str] = set()
        local_sources: dict[str, dict[str, Any]] = {}
        source_results: list[dict[str, Any]] = []
        for raw_source in sources:
            source = raw_source if isinstance(raw_source, dict) else {}
            source_id = str(source.get("id", "")).strip()
            if source_id in local_source_ids or source_id in all_source_ids:
                failures.append(f"source id {source_id!r} must be globally unique")
            local_source_ids.add(source_id)
            local_sources[source_id] = source
            all_source_ids.add(source_id)
            source_failures = _validate_source(game_root, source)
            failures.extend(f"source {source_id or '<unnamed>'}: {failure}" for failure in source_failures)
            source_results.append({"id": source_id, "failures": source_failures})
        required_source_roles = {"requirements", "availability", "replay_title", "replay_call"}
        if acquisition_mode == "normal-play":
            required_source_roles.update({"normal_acquisition", "live_trigger", "live_completion"})
        elif acquisition_mode == "gallery-only":
            required_source_roles.add("gallery_access")
            if kind != "gallery-entry":
                failures.append("gallery-only acquisition requires kind 'gallery-entry'")
        if cg_image_count > 0:
            required_source_roles.add("cg_viewer")
        if kind == "combat-scene":
            required_source_roles.update({"combat_enemy", "combat_trigger", "encounter_access"})
        _validate_scene_source_roles(
            entry.get("source_roles"),
            required_source_roles,
            local_source_ids,
            failures,
            cg_image_count=cg_image_count,
        )
        roles = entry.get("source_roles") if isinstance(entry.get("source_roles"), dict) else {}
        if acquisition_mode == "normal-play":
            live_roles = ["availability", "normal_acquisition", "live_trigger", "live_completion"]
            if "unlock" in roles:
                live_roles.append("unlock")
            if kind == "combat-scene":
                live_roles.extend(["combat_enemy", "combat_trigger", "encounter_access"])
            for role in live_roles:
                role_sources = [
                    local_sources[source_id]
                    for source_id in roles.get(role, [])
                    if source_id in local_sources
                ]
                if role_sources and not any(
                    str(source.get("file", "")) not in interface_files
                    and _scene_source_locator(source) not in catalog_source_locators
                    for source in role_sources
                ):
                    failures.append(
                        f"source_roles.{role} must include evidence from normal play outside the catalog/recollection interface"
                    )
        elif acquisition_mode == "gallery-only" and any(
            role in roles for role in ("normal_acquisition", "live_trigger", "live_completion", "unlock")
        ):
            failures.append("gallery-only entries must not claim normal_acquisition, live_trigger, live_completion, or unlock roles")
        for phrase in [*requirements, *acquisition_steps]:
            if phrase not in phrases:
                failures.append(f"guide_phrases must include requirement/acquisition text exactly: {phrase!r}")
        if completion_shortcut and acquisition_mode == "normal-play":
            entry_copy = " ".join([*requirements, *acquisition_steps, *phrases])
            if _normalize(completion_shortcut) in _normalize(entry_copy):
                failures.append("normal-play entries must not repeat the catalog-wide completion shortcut")
        if failures:
            _issue(
                issues,
                "error",
                "scene-entry-invalid",
                f"Scene entry {entry_id!r} is invalid: {failures[0]}",
                scene_id=entry_id,
                failures=failures,
            )
        entry_results.append(
            {
                "id": entry_id,
                "title": title,
                "catalog_title": catalog_title,
                "kind": kind,
                "status": "contradicted" if failures else "verified",
                "evidence_status": status,
                "cg_image_count": cg_image_count,
                "acquisition_mode": acquisition_mode,
                "route_anchor_id": route_anchor_id,
                "route_anchor_position": route_anchor_position,
                "prerequisite_scene_ids": prerequisite_scene_ids,
                "story_gate_claim_ids": story_gate_claim_ids,
                "sources": source_results,
                "failures": failures,
            }
        )
    undeclared_entry_markers = sorted(set(entry_markers) - set(entries))
    if undeclared_entry_markers:
        _issue(
            issues,
            "error",
            "undeclared-scene-entry",
            f"Markdown scene-entry marker {undeclared_entry_markers[0]!r} has no evidence entry.",
            scene_ids=undeclared_entry_markers,
        )

    route_order = {claim_id: index for index, claim_id in enumerate(claims)}
    for entry_id, entry in entries.items():
        failures: list[str] = []
        anchor_id = str(entry.get("route_anchor_id", "")).strip()
        anchor_position = str(entry.get("route_anchor_position", "")).strip()
        anchor_key = (route_order.get(anchor_id, -1), 0 if anchor_position == "before" else 1)
        anchor_slot = route_order.get(anchor_id, -1) * 2 + (0 if anchor_position == "before" else 1)
        boundary_slots: list[int] = []
        for claim_id in entry.get("story_gate_claim_ids") or []:
            if claim_id in route_order and anchor_key < (route_order[claim_id], 1):
                failures.append(
                    f"route anchor {anchor_id!r} is earlier than story gate {claim_id!r}"
                )
            if claim_id in route_order:
                boundary_slots.append(route_order[claim_id] * 2 + 1)
        for prerequisite_id in entry.get("prerequisite_scene_ids") or []:
            if prerequisite_id == entry_id:
                failures.append("a scene cannot depend on itself")
                continue
            prerequisite = entries.get(prerequisite_id)
            if prerequisite is None:
                failures.append(f"prerequisite scene {prerequisite_id!r} does not exist")
                continue
            prerequisite_key = (
                route_order.get(str(prerequisite.get("route_anchor_id", "")), -1),
                0 if prerequisite.get("route_anchor_position") == "before" else 1,
            )
            boundary_slots.append(
                route_order.get(str(prerequisite.get("route_anchor_id", "")), -1) * 2
                + (0 if prerequisite.get("route_anchor_position") == "before" else 1)
            )
            if anchor_key < prerequisite_key:
                failures.append(
                    f"route anchor is earlier than prerequisite scene {prerequisite_id!r}"
                )
        if boundary_slots and anchor_slot > max(boundary_slots) + 1:
            failures.append(
                "route anchor is later than the latest declared story gate or prerequisite availability boundary"
            )
        if failures:
            _issue(
                issues,
                "error",
                "scene-availability-order-invalid",
                f"Scene entry {entry_id!r} has an invalid Main Route availability order: {failures[0]}",
                scene_id=entry_id,
                failures=failures,
            )

    group_rows = raw.get("groups")
    if not isinstance(group_rows, list) or not group_rows:
        _issue(issues, "error", "scene-groups-missing", "scenes_cg.groups must not be empty.")
        group_rows = []
    group_markers = Counter(match.group("id") for match in SCENE_GROUP_MARKER_RE.finditer(markdown))
    groups: dict[str, dict[str, Any]] = {}
    group_results: list[dict[str, Any]] = []
    assigned_entries: list[str] = []
    for index, raw_group in enumerate(group_rows):
        group = raw_group if isinstance(raw_group, dict) else {}
        group_id = str(group.get("id", "")).strip()
        label = str(group.get("label", "")).strip()
        failures: list[str] = []
        if not ID_RE.fullmatch(group_id):
            failures.append("id must be a nonempty kebab-case identifier")
            group_id = group_id or f"invalid-scene-group-{index + 1}"
        if group_id in groups or group_id in reserved_ids or group_id in entries:
            failures.append("scene group id must be globally unique")
        groups[group_id] = group
        if not label:
            failures.append("label must be nonempty")
        elif _normalize(label) not in normalized_markdown:
            failures.append(f"label is missing from Markdown: {label!r}")
        if group_markers.get(group_id, 0) != 1:
            failures.append(
                f"Markdown must contain exactly one scene-group marker; observed {group_markers.get(group_id, 0)}"
            )
        entry_ids = group.get("entry_ids")
        if not isinstance(entry_ids, list) or not entry_ids or any(not isinstance(row, str) for row in entry_ids):
            failures.append("entry_ids must contain at least one scene id")
            entry_ids = []
        if len(set(entry_ids)) != len(entry_ids):
            failures.append("entry_ids contains duplicates")
        for entry_id in entry_ids:
            if entry_id not in entries:
                failures.append(f"scene entry {entry_id!r} does not exist")
            elif entries[entry_id].get("group_id") != group_id:
                failures.append(f"scene entry {entry_id!r} declares a different group_id")
        assigned_entries.extend(entry_ids)
        route_anchor_id = str(group.get("route_anchor_id", "")).strip()
        if route_anchor_id not in claims:
            failures.append(f"route_anchor_id {route_anchor_id!r} is not a Main Route claim")
        route_anchor_position = str(group.get("route_anchor_position", "")).strip()
        if route_anchor_position not in ROUTE_ANCHOR_POSITIONS:
            failures.append(f"route_anchor_position must be one of {sorted(ROUTE_ANCHOR_POSITIONS)}")
        if failures:
            _issue(
                issues,
                "error",
                "scene-group-invalid",
                f"Scene group {group_id!r} is invalid: {failures[0]}",
                group_id=group_id,
                failures=failures,
            )
        group_results.append(
            {
                "id": group_id,
                "label": label,
                "entry_ids": entry_ids,
                "route_anchor_id": route_anchor_id,
                "route_anchor_position": route_anchor_position,
                "failures": failures,
            }
        )
    duplicate_entries = sorted(entry_id for entry_id, count in Counter(assigned_entries).items() if count > 1)
    missing_entries = sorted(set(entries) - set(assigned_entries))
    if duplicate_entries or missing_entries:
        _issue(
            issues,
            "error",
            "scene-group-entry-coverage-invalid",
            "Every scene entry must belong to exactly one scene group.",
            duplicated_entries=duplicate_entries,
            missing_entries=missing_entries,
        )
    undeclared_group_markers = sorted(set(group_markers) - set(groups))
    if undeclared_group_markers:
        _issue(
            issues,
            "error",
            "undeclared-scene-group",
            f"Markdown scene-group marker {undeclared_group_markers[0]!r} has no evidence group.",
            group_ids=undeclared_group_markers,
        )
    if isinstance(entry_count, int) and entry_count != len(entries):
        _issue(
            issues,
            "error",
            "scene-catalog-entry-count-mismatch",
            "scenes_cg.catalog.entry_count must equal the number of declared scene entries.",
            expected=len(entries),
            observed=entry_count,
        )
    observed_cg_total = sum(
        entry.get("cg_image_count", 0)
        for entry in entries.values()
        if isinstance(entry.get("cg_image_count"), int)
    )
    if isinstance(cg_total, int) and cg_total != observed_cg_total:
        _issue(
            issues,
            "error",
            "scene-catalog-cg-count-mismatch",
            "scenes_cg.catalog.cg_image_count must equal the sum of entry CG counts.",
            expected=observed_cg_total,
            observed=cg_total,
        )

    return groups, entries, catalog, {
        "source_label": source_label,
        "catalog": {
            "id": catalog_id,
            "entry_count": entry_count,
            "cg_image_count": cg_total,
            "sources": catalog_source_results,
            "failures": catalog_failures,
        },
        "groups": group_results,
        "entries": entry_results,
    }


class WalkthroughHTMLParser(HTMLParser):
    """Collect the structural contract without requiring third-party HTML packages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: Counter[str] = Counter()
        self.id_views: dict[str, str | None] = {}
        self.hooks: Counter[str] = Counter()
        self.hero_stats = 0
        self.tabs: Counter[str] = Counter()
        self.tab_hrefs: dict[str, Counter[str]] = defaultdict(Counter)
        self.views: Counter[str] = Counter()
        self.view_ids: dict[str, str] = {}
        self.view_placeholders: dict[str, str] = {}
        self.route_chapters: Counter[str] = Counter()
        self.route_chapter_labels: dict[str, Counter[str]] = defaultdict(Counter)
        self.route_chapter_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.route_chapter_views: dict[str, set[str | None]] = defaultdict(set)
        self.route_chapter_text_parts: dict[str, list[str]] = defaultdict(list)
        self.route_sections: Counter[str] = Counter()
        self.route_section_labels: dict[str, Counter[str]] = defaultdict(Counter)
        self.route_section_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.route_section_heading_tags: dict[str, Counter[str]] = defaultdict(Counter)
        self.route_section_chapter_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.route_section_views: dict[str, set[str | None]] = defaultdict(set)
        self.route_section_text_parts: dict[str, list[str]] = defaultdict(list)
        self.route_steps: Counter[str] = Counter()
        self.route_step_views: dict[str, set[str | None]] = defaultdict(set)
        self.route_step_section_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.route_step_text_parts: dict[str, list[str]] = defaultdict(list)
        self.route_lead_started: set[str] = set()
        self.route_outcome_started: set[str] = set()
        self.route_tasks: Counter[str] = Counter()
        self.route_task_claim_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.route_task_views: dict[str, set[str | None]] = defaultdict(set)
        self.optional_groups: Counter[str] = Counter()
        self.optional_group_labels: dict[str, Counter[str]] = defaultdict(Counter)
        self.optional_group_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.optional_group_views: dict[str, set[str | None]] = defaultdict(set)
        self.optional_group_text_parts: dict[str, list[str]] = defaultdict(list)
        self.optional_entries: Counter[str] = Counter()
        self.optional_entry_views: dict[str, set[str | None]] = defaultdict(set)
        self.optional_entry_group_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.optional_entry_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.optional_entry_text_parts: dict[str, list[str]] = defaultdict(list)
        self.optional_tasks: Counter[str] = Counter()
        self.optional_task_entry_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.optional_task_views: dict[str, set[str | None]] = defaultdict(set)
        self.boss_groups: Counter[str] = Counter()
        self.boss_group_labels: dict[str, Counter[str]] = defaultdict(Counter)
        self.boss_group_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.boss_group_views: dict[str, set[str | None]] = defaultdict(set)
        self.boss_group_text_parts: dict[str, list[str]] = defaultdict(list)
        self.boss_entries: Counter[str] = Counter()
        self.boss_entry_views: dict[str, set[str | None]] = defaultdict(set)
        self.boss_entry_group_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.boss_entry_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.boss_entry_text_parts: dict[str, list[str]] = defaultdict(list)
        self.boss_phase_sections: dict[str, Counter[str]] = defaultdict(Counter)
        self.boss_stat_cells: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
        self.boss_stat_text_parts: dict[str, dict[str, dict[str, list[str]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(list))
        )
        self.boss_tasks: Counter[str] = Counter()
        self.boss_task_entry_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.boss_task_views: dict[str, set[str | None]] = defaultdict(set)
        self.scene_groups: Counter[str] = Counter()
        self.scene_group_labels: dict[str, Counter[str]] = defaultdict(Counter)
        self.scene_group_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.scene_group_views: dict[str, set[str | None]] = defaultdict(set)
        self.scene_group_text_parts: dict[str, list[str]] = defaultdict(list)
        self.scene_entries: Counter[str] = Counter()
        self.scene_entry_views: dict[str, set[str | None]] = defaultdict(set)
        self.scene_entry_group_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.scene_entry_heading_ids: dict[str, Counter[str]] = defaultdict(Counter)
        self.scene_entry_catalog_titles: dict[str, Counter[str]] = defaultdict(Counter)
        self.scene_entry_text_parts: dict[str, list[str]] = defaultdict(list)
        self.scene_entry_acquisition_modes: dict[str, Counter[str]] = defaultdict(Counter)
        self.scene_acquisition_sections: dict[str, Counter[str]] = defaultdict(Counter)
        self.scene_system_text_parts: list[str] = []
        self.scene_tasks: Counter[str] = Counter()
        self.scene_task_entry_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.scene_task_views: dict[str, set[str | None]] = defaultdict(set)
        self.evidence: Counter[str] = Counter()
        self.evidence_claim_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.evidence_optional_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.evidence_boss_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.evidence_scene_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.evidence_statuses: dict[str, Counter[str]] = defaultdict(Counter)
        self.evidence_sources: dict[str, Counter[str]] = defaultdict(Counter)
        self.evidence_text_parts: dict[str, list[str]] = defaultdict(list)
        self.source_text_parts: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        self.guide_links: list[str] = []
        self.guide_link_claim_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.guide_link_optional_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.guide_link_boss_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.guide_link_scene_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.guide_link_scene_group_contexts: dict[str, set[str | None]] = defaultdict(set)
        self.guide_link_positions: dict[str, Counter[str]] = defaultdict(Counter)
        self.guide_link_dom_positions: dict[str, Counter[str]] = defaultdict(Counter)
        self.guide_link_kinds_in_claims: dict[str, Counter[str]] = defaultdict(Counter)
        self.external_references: list[str] = []
        self.public_text_parts: list[str] = []
        self.all_text_parts: list[str] = []
        self._view: str | None = None
        self._chapter: str | None = None
        self._section: str | None = None
        self._claim: str | None = None
        self._optional_group: str | None = None
        self._optional_entry: str | None = None
        self._boss_group: str | None = None
        self._boss_entry: str | None = None
        self._boss_phase_index: str | None = None
        self._boss_stat: str | None = None
        self._scene_group: str | None = None
        self._scene_entry: str | None = None
        self._scene_system = False
        self._evidence: str | None = None
        self._source: str | None = None
        self._ignored_depth = 0
        self._stack: list[
            tuple[
                str,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                str | None,
                bool,
                int,
            ]
        ] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        attrs = {key: value or "" for key, value in attrs_list}
        classes = set(attrs.get("class", "").split())
        previous = (
            tag,
            self._view,
            self._chapter,
            self._section,
            self._claim,
            self._optional_group,
            self._optional_entry,
            self._boss_group,
            self._boss_entry,
            self._boss_phase_index,
            self._boss_stat,
            self._scene_group,
            self._scene_entry,
            self._scene_system,
            self._evidence,
            self._source,
            self._ignored_depth,
        )

        if "guide-view" in classes:
            self._view = attrs.get("data-view") or None
            if self._view:
                self.views[self._view] += 1
                self.view_ids[self._view] = attrs.get("id", "")
                self.view_placeholders[self._view] = attrs.get("data-placeholder", "")
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        if tag not in VOID_ELEMENTS:
            self._stack.append(previous)

        for class_name in classes:
            if class_name in REQUIRED_HOOKS:
                self.hooks[class_name] += 1
        if "hero-stat" in classes:
            self.hero_stats += 1
        element_id = attrs.get("id", "")
        if element_id:
            self.ids[element_id] += 1
            self.id_views[element_id] = self._view
        if "primary-tab" in classes:
            target = attrs.get("data-view-target", "")
            self.tabs[target] += 1
            self.tab_hrefs[target][attrs.get("href", "")] += 1
        if "route-chapter" in classes:
            chapter_id = attrs.get("data-chapter-id", "")
            self._chapter = chapter_id
            self.route_chapters[chapter_id] += 1
            self.route_chapter_labels[chapter_id][attrs.get("data-chapter-label", "")] += 1
            self.route_chapter_views[chapter_id].add(self._view)
        if "route-section" in classes:
            section_id = attrs.get("data-section-id", "")
            self._section = section_id
            self.route_sections[section_id] += 1
            self.route_section_labels[section_id][attrs.get("data-section-label", "")] += 1
            self.route_section_chapter_contexts[section_id].add(self._chapter)
            self.route_section_views[section_id].add(self._view)
        if tag == "h2" and self._chapter is not None and self._section is None:
            self.route_chapter_heading_ids[self._chapter][attrs.get("id", "")] += 1
        if tag in {"h2", "h3"} and self._section is not None and self._claim is None:
            self.route_section_heading_ids[self._section][attrs.get("id", "")] += 1
            self.route_section_heading_tags[self._section][tag] += 1
        if "route-step" in classes:
            claim_id = attrs.get("data-claim-id", "")
            self._claim = claim_id
            self.route_steps[claim_id] += 1
            self.route_step_views[claim_id].add(self._view)
            self.route_step_section_contexts[claim_id].add(self._section)
        if "route-lead" in classes and self._claim is not None:
            self.route_lead_started.add(self._claim)
        if "route-outcome" in classes and self._claim is not None:
            self.route_outcome_started.add(self._claim)
        if "optional-group" in classes:
            group_id = attrs.get("data-optional-group-id", "")
            self._optional_group = group_id
            self.optional_groups[group_id] += 1
            self.optional_group_labels[group_id][attrs.get("data-optional-group-label", "")] += 1
            self.optional_group_views[group_id].add(self._view)
        if "optional-entry" in classes:
            entry_id = attrs.get("data-optional-id", "")
            self._optional_entry = entry_id
            self.optional_entries[entry_id] += 1
            self.optional_entry_views[entry_id].add(self._view)
            self.optional_entry_group_contexts[entry_id].add(self._optional_group)
        if tag == "h2" and self._optional_group is not None and self._optional_entry is None:
            self.optional_group_heading_ids[self._optional_group][attrs.get("id", "")] += 1
        if tag == "h3" and self._optional_entry is not None:
            self.optional_entry_heading_ids[self._optional_entry][attrs.get("id", "")] += 1
        if "boss-group" in classes:
            group_id = attrs.get("data-boss-group-id", "")
            self._boss_group = group_id
            self.boss_groups[group_id] += 1
            self.boss_group_labels[group_id][attrs.get("data-boss-group-label", "")] += 1
            self.boss_group_views[group_id].add(self._view)
        if "boss-entry" in classes:
            boss_id = attrs.get("data-boss-id", "")
            self._boss_entry = boss_id
            self.boss_entries[boss_id] += 1
            self.boss_entry_views[boss_id].add(self._view)
            self.boss_entry_group_contexts[boss_id].add(self._boss_group)
        if "boss-phase" in classes and self._boss_entry is not None:
            self._boss_phase_index = attrs.get("data-boss-phase-index", "")
            self.boss_phase_sections[self._boss_entry][self._boss_phase_index] += 1
        if tag == "td" and "data-boss-stat" in attrs and self._boss_entry is not None and self._boss_phase_index is not None:
            self._boss_stat = attrs.get("data-boss-stat", "")
            self.boss_stat_cells[self._boss_entry][self._boss_phase_index][self._boss_stat] += 1
        if tag == "h2" and self._boss_group is not None and self._boss_entry is None:
            self.boss_group_heading_ids[self._boss_group][attrs.get("id", "")] += 1
        if tag == "h3" and self._boss_entry is not None:
            self.boss_entry_heading_ids[self._boss_entry][attrs.get("id", "")] += 1
        if "scene-group" in classes:
            group_id = attrs.get("data-scene-group-id", "")
            self._scene_group = group_id
            self.scene_groups[group_id] += 1
            self.scene_group_labels[group_id][attrs.get("data-scene-group-label", "")] += 1
            self.scene_group_views[group_id].add(self._view)
        if "scene-system" in classes and attrs.get("id") == "scenes-cg-system":
            self._scene_system = True
        if "scene-entry" in classes:
            scene_id = attrs.get("data-scene-id", "")
            self._scene_entry = scene_id
            self.scene_entries[scene_id] += 1
            self.scene_entry_views[scene_id].add(self._view)
            self.scene_entry_group_contexts[scene_id].add(self._scene_group)
            self.scene_entry_acquisition_modes[scene_id][attrs.get("data-acquisition-mode", "")] += 1
            self.scene_entry_catalog_titles[scene_id][attrs.get("data-catalog-title", "")] += 1
        if "scene-acquisition" in classes and self._scene_entry is not None:
            self.scene_acquisition_sections[self._scene_entry][attrs.get("data-acquisition-mode", "")] += 1
        if tag == "h2" and self._scene_group is not None and self._scene_entry is None:
            self.scene_group_heading_ids[self._scene_group][attrs.get("id", "")] += 1
        if tag == "h3" and self._scene_entry is not None:
            self.scene_entry_heading_ids[self._scene_entry][attrs.get("id", "")] += 1
        if "task-checkbox" in classes:
            task_id = attrs.get("data-task-id", "")
            if self._claim is not None:
                self.route_tasks[task_id] += 1
                self.route_task_claim_contexts[task_id].add(self._claim)
                self.route_task_views[task_id].add(self._view)
            elif self._optional_entry is not None:
                self.optional_tasks[task_id] += 1
                self.optional_task_entry_contexts[task_id].add(self._optional_entry)
                self.optional_task_views[task_id].add(self._view)
            elif self._boss_entry is not None:
                self.boss_tasks[task_id] += 1
                self.boss_task_entry_contexts[task_id].add(self._boss_entry)
                self.boss_task_views[task_id].add(self._view)
            elif self._scene_entry is not None:
                self.scene_tasks[task_id] += 1
                self.scene_task_entry_contexts[task_id].add(self._scene_entry)
                self.scene_task_views[task_id].add(self._view)
        if tag == "details" and "evidence" in classes:
            self._evidence = attrs.get("data-evidence-id", "")
            self.evidence[self._evidence] += 1
            self.evidence_claim_contexts[self._evidence].add(self._claim)
            self.evidence_optional_contexts[self._evidence].add(self._optional_entry)
            self.evidence_boss_contexts[self._evidence].add(self._boss_entry)
            self.evidence_scene_contexts[self._evidence].add(self._scene_entry)
        evidence_status = attrs.get("data-evidence-status", "")
        if evidence_status and self._evidence is not None:
            self.evidence_statuses[self._evidence][evidence_status] += 1
        source_id = attrs.get("data-source-id", "")
        if source_id and self._evidence is not None:
            self._source = source_id
            self.evidence_sources[self._evidence][source_id] += 1
        if "data-guide-link" in attrs:
            href = attrs.get("href", "")
            self.guide_links.append(href)
            self.guide_link_claim_contexts[href].add(self._claim)
            self.guide_link_optional_contexts[href].add(self._optional_entry)
            self.guide_link_boss_contexts[href].add(self._boss_entry)
            self.guide_link_scene_contexts[href].add(self._scene_entry)
            self.guide_link_scene_group_contexts[href].add(self._scene_group)
            if self._claim is not None:
                self.guide_link_kinds_in_claims[href][attrs.get("data-guide-kind", "")] += 1
                self.guide_link_positions[href][attrs.get("data-guide-link-position", "")] += 1
                if self._claim in self.route_outcome_started:
                    dom_position = "after"
                elif self._claim not in self.route_lead_started:
                    dom_position = "before"
                else:
                    dom_position = "during"
                self.guide_link_dom_positions[href][dom_position] += 1

        src = attrs.get("src", "")
        if src and not src.startswith("data:"):
            self.external_references.append(src)
        if tag == "link" and attrs.get("href"):
            self.external_references.append(attrs["href"])

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag not in VOID_ELEMENTS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "h1", "h2", "h3", "aside", "li"} and self._evidence is None:
            self.public_text_parts.append("\n\n")
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] != tag:
                continue
            (
                _tag,
                previous_view,
                previous_chapter,
                previous_section,
                previous_claim,
                previous_optional_group,
                previous_optional_entry,
                previous_boss_group,
                previous_boss_entry,
                previous_boss_phase_index,
                previous_boss_stat,
                previous_scene_group,
                previous_scene_entry,
                previous_scene_system,
                previous_evidence,
                previous_source,
                previous_ignored,
            ) = self._stack[index]
            del self._stack[index:]
            self._view = previous_view
            self._chapter = previous_chapter
            self._section = previous_section
            self._claim = previous_claim
            self._optional_group = previous_optional_group
            self._optional_entry = previous_optional_entry
            self._boss_group = previous_boss_group
            self._boss_entry = previous_boss_entry
            self._boss_phase_index = previous_boss_phase_index
            self._boss_stat = previous_boss_stat
            self._scene_group = previous_scene_group
            self._scene_entry = previous_scene_entry
            self._scene_system = previous_scene_system
            self._evidence = previous_evidence
            self._source = previous_source
            self._ignored_depth = previous_ignored
            return

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        self.all_text_parts.append(data)
        if self._evidence is not None:
            self.evidence_text_parts[self._evidence].append(data)
            if self._source is not None:
                self.source_text_parts[self._evidence][self._source].append(data)
        elif self._claim is not None:
            self.route_step_text_parts[self._claim].append(data)
        elif self._optional_entry is not None:
            self.optional_entry_text_parts[self._optional_entry].append(data)
        elif self._boss_entry is not None:
            self.boss_entry_text_parts[self._boss_entry].append(data)
            if self._boss_phase_index is not None and self._boss_stat is not None:
                self.boss_stat_text_parts[self._boss_entry][self._boss_phase_index][self._boss_stat].append(data)
        elif self._scene_entry is not None:
            self.scene_entry_text_parts[self._scene_entry].append(data)
        elif self._scene_system:
            self.scene_system_text_parts.append(data)
        if self._chapter is not None:
            self.route_chapter_text_parts[self._chapter].append(data)
        if self._section is not None:
            self.route_section_text_parts[self._section].append(data)
        if self._optional_group is not None:
            self.optional_group_text_parts[self._optional_group].append(data)
        if self._boss_group is not None:
            self.boss_group_text_parts[self._boss_group].append(data)
        if self._scene_group is not None:
            self.scene_group_text_parts[self._scene_group].append(data)
        if self._evidence is None:
            self.public_text_parts.append(data)


def _validate_dependency_closure(
    game_root: Path,
    evidence_path: Path,
    evidence: dict[str, Any],
    guide_record_ids: set[str],
    companion_entry_ids: set[str],
    source_ids: set[str],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate source-bound prerequisite graphs and their carrier-use accounting."""
    raw = evidence.get("dependency_closure")
    if not isinstance(raw, dict):
        _issue(
            issues,
            "error",
            "dependency-closure-missing",
            "evidence.json must declare dependency_closure and its reviewed artifacts.",
        )
        return {"chains": [], "bindings": [], "failures": ["dependency_closure is missing"]}

    failures: list[str] = []
    artifact_name = str(raw.get("artifact", "")).strip()
    index_name = str(raw.get("index_artifact", "")).strip()
    if not artifact_name or Path(artifact_name).name != artifact_name:
        failures.append("artifact must name a sibling JSON file")
    if not index_name or Path(index_name).name != index_name:
        failures.append("index_artifact must name a sibling JSON file")

    artifact_path = evidence_path.parent / artifact_name
    index_path = evidence_path.parent / index_name
    artifact: Any = None
    index: Any = None
    if artifact_name:
        try:
            artifact = _read_json(artifact_path)
        except ValidationInputError as exc:
            failures.append(f"could not read dependency artifact: {exc}")
    if index_name:
        try:
            index = _read_json(index_path)
        except ValidationInputError as exc:
            failures.append(f"could not read dependency index: {exc}")

    if isinstance(index, dict):
        if index.get("schema_version") != 1:
            failures.append("dependency index schema_version must be 1")
        else:
            source_files = index.get("source_files")
            if not isinstance(source_files, list) or not source_files:
                failures.append("dependency index source_files must pin every indexed data file")
            else:
                for source_file in source_files:
                    source_file = source_file if isinstance(source_file, dict) else {}
                    path, failure = _project_file(game_root, source_file.get("file"))
                    if failure:
                        failures.append(f"dependency index source file is invalid: {failure}")
                        break
                    expected_hash = str(source_file.get("sha256", ""))
                    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
                        failures.append("dependency index source file has an invalid sha256")
                        break
                    assert path is not None
                    if _sha256(path) != expected_hash:
                        failures.append(
                            f"dependency index no longer matches executable file {source_file.get('file')!r}"
                        )
                        break
    elif index is not None:
        failures.append("dependency index must be a JSON object")

    if not isinstance(artifact, dict):
        if artifact is not None:
            failures.append("dependency artifact must be a JSON object")
        artifact = {}
    if artifact.get("schema_version") != 1:
        failures.append("dependency artifact schema_version must be 1")

    raw_chains = artifact.get("chains")
    if not isinstance(raw_chains, list) or not raw_chains:
        failures.append("dependency artifact chains must be a nonempty list")
        raw_chains = []
    chains: dict[str, dict[str, Any]] = {}
    chain_results: list[dict[str, Any]] = []
    index_sites = {
        str(site.get("id", "")): site
        for site in (index.get("carrier_sites", []) if isinstance(index, dict) else [])
        if isinstance(site, dict) and str(site.get("id", ""))
    }

    for chain_index, raw_chain in enumerate(raw_chains):
        chain = raw_chain if isinstance(raw_chain, dict) else {}
        chain_id = str(chain.get("id", "")).strip()
        chain_failures: list[str] = []
        if not ID_RE.fullmatch(chain_id):
            chain_failures.append("id must be a nonempty kebab-case identifier")
            chain_id = chain_id or f"invalid-dependency-chain-{chain_index + 1}"
        if chain_id in chains:
            chain_failures.append("chain id is duplicated")
        chains[chain_id] = chain
        if not str(chain.get("title", "")).strip():
            chain_failures.append("title must be nonempty")
        coverage_status = str(chain.get("coverage_status", "")).strip()
        if coverage_status not in DEPENDENCY_COVERAGE_STATUSES:
            chain_failures.append(
                f"coverage_status must be one of {sorted(DEPENDENCY_COVERAGE_STATUSES)}"
            )

        raw_nodes = chain.get("nodes")
        if not isinstance(raw_nodes, list) or not raw_nodes:
            chain_failures.append("nodes must be a nonempty list")
            raw_nodes = []
        nodes: dict[str, dict[str, Any]] = {}
        predecessor_map: dict[str, list[str]] = {}
        for node_index, raw_node in enumerate(raw_nodes):
            node = raw_node if isinstance(raw_node, dict) else {}
            node_id = str(node.get("id", "")).strip()
            if not ID_RE.fullmatch(node_id):
                chain_failures.append(f"nodes[{node_index}].id must be kebab-case")
                node_id = node_id or f"invalid-node-{node_index + 1}"
            if node_id in nodes:
                chain_failures.append(f"node {node_id!r} is duplicated")
            nodes[node_id] = node
            kind = str(node.get("kind", "")).strip()
            if kind not in DEPENDENCY_NODE_KINDS:
                chain_failures.append(
                    f"node {node_id!r}.kind must be one of {sorted(DEPENDENCY_NODE_KINDS)}"
                )
            if not str(node.get("text", "")).strip():
                chain_failures.append(f"node {node_id!r}.text must be nonempty")
            node_sources = node.get("source_ids")
            if not isinstance(node_sources, list) or not node_sources or any(
                not isinstance(source_id, str) for source_id in node_sources
            ):
                chain_failures.append(f"node {node_id!r}.source_ids must be a nonempty list")
            else:
                unknown = sorted(set(node_sources) - source_ids)
                if unknown:
                    chain_failures.append(
                        f"node {node_id!r} references unknown source {unknown[0]!r}"
                    )
            predecessors = node.get("predecessor_ids", [])
            if not isinstance(predecessors, list) or any(not isinstance(row, str) for row in predecessors):
                chain_failures.append(f"node {node_id!r}.predecessor_ids must be a list")
                predecessors = []
            if len(predecessors) != len(set(predecessors)):
                chain_failures.append(f"node {node_id!r}.predecessor_ids contains duplicates")
            if node_id in predecessors:
                chain_failures.append(f"node {node_id!r} cannot depend on itself")
            predecessor_map[node_id] = predecessors

        for node_id, predecessors in predecessor_map.items():
            unknown = sorted(set(predecessors) - set(nodes))
            if unknown:
                chain_failures.append(
                    f"node {node_id!r} references unknown predecessor {unknown[0]!r}"
                )
            if not predecessors and str(nodes[node_id].get("kind", "")) not in DEPENDENCY_LEAF_KINDS | {"unresolved"}:
                chain_failures.append(
                    f"leaf node {node_id!r} must be a player-action, story-gate, automatic, or unresolved leaf"
                )

        terminal_ids = chain.get("terminal_node_ids")
        if not isinstance(terminal_ids, list) or not terminal_ids or any(
            not isinstance(row, str) for row in terminal_ids
        ):
            chain_failures.append("terminal_node_ids must be a nonempty list")
            terminal_ids = []
        for terminal_id in terminal_ids:
            if terminal_id not in nodes:
                chain_failures.append(f"terminal node {terminal_id!r} does not exist")
            elif str(nodes[terminal_id].get("kind", "")) != "terminal":
                chain_failures.append(f"terminal node {terminal_id!r} must have kind 'terminal'")

        visiting: set[str] = set()
        visited: set[str] = set()
        cycle_found = False

        def walk(node_id: str) -> None:
            nonlocal cycle_found
            if node_id in visiting:
                cycle_found = True
                return
            if node_id in visited or node_id not in nodes:
                return
            visiting.add(node_id)
            for predecessor_id in predecessor_map.get(node_id, []):
                walk(predecessor_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for terminal_id in terminal_ids:
            walk(terminal_id)
        if cycle_found:
            chain_failures.append("dependency graph contains a cycle")
        unconnected = sorted(set(nodes) - visited)
        if unconnected:
            chain_failures.append(
                f"node {unconnected[0]!r} is not connected to a declared terminal"
            )

        unresolved_ids = chain.get("unresolved_leaf_ids", [])
        if not isinstance(unresolved_ids, list) or any(not isinstance(row, str) for row in unresolved_ids):
            chain_failures.append("unresolved_leaf_ids must be a list")
            unresolved_ids = []
        actual_unresolved = {
            node_id for node_id, node in nodes.items() if str(node.get("kind", "")) == "unresolved"
        }
        if set(unresolved_ids) != actual_unresolved:
            chain_failures.append("unresolved_leaf_ids must exactly list every unresolved node")
        if coverage_status == "complete" and unresolved_ids:
            chain_failures.append("complete chains cannot contain unresolved leaves")

        raw_invalidators = chain.get("invalidators")
        if not isinstance(raw_invalidators, list):
            chain_failures.append("invalidators must be a list")
            raw_invalidators = []
        for invalidator_index, raw_invalidator in enumerate(raw_invalidators):
            invalidator = raw_invalidator if isinstance(raw_invalidator, dict) else {}
            label = f"invalidators[{invalidator_index}]"
            if str(invalidator.get("kind", "")).strip() not in RECRUITMENT_FAILURE_KINDS:
                chain_failures.append(
                    f"{label}.kind must be one of {sorted(RECRUITMENT_FAILURE_KINDS)}"
                )
            if not str(invalidator.get("text", "")).strip():
                chain_failures.append(f"{label}.text must be nonempty")
            invalidator_sources = invalidator.get("source_ids")
            if not isinstance(invalidator_sources, list) or not invalidator_sources:
                chain_failures.append(f"{label}.source_ids must be a nonempty list")
            else:
                unknown = sorted(set(invalidator_sources) - source_ids)
                if unknown:
                    chain_failures.append(f"{label} references unknown source {unknown[0]!r}")
            invalidator_nodes = invalidator.get("node_ids")
            if not isinstance(invalidator_nodes, list) or not invalidator_nodes:
                chain_failures.append(f"{label}.node_ids must be a nonempty list")
            else:
                unknown = sorted(set(invalidator_nodes) - set(nodes))
                if unknown:
                    chain_failures.append(f"{label} references unknown node {unknown[0]!r}")

        raw_carriers = chain.get("tracked_carriers")
        if not isinstance(raw_carriers, list) or not raw_carriers:
            chain_failures.append("tracked_carriers must be a nonempty list")
            raw_carriers = []
        seen_carriers: set[tuple[str, Any]] = set()
        for carrier_index, raw_carrier in enumerate(raw_carriers):
            carrier = raw_carrier if isinstance(raw_carrier, dict) else {}
            label = f"tracked_carriers[{carrier_index}]"
            kind = str(carrier.get("kind", "")).strip()
            carrier_id = carrier.get("id")
            if kind not in DEPENDENCY_CARRIER_KINDS:
                chain_failures.append(
                    f"{label}.kind must be one of {sorted(DEPENDENCY_CARRIER_KINDS)}"
                )
            if not isinstance(carrier_id, int) or isinstance(carrier_id, bool) or carrier_id < 1:
                chain_failures.append(f"{label}.id must be a positive integer")
            key = (kind, carrier_id)
            if key in seen_carriers:
                chain_failures.append(f"tracked carrier {kind} {carrier_id!r} is duplicated")
            seen_carriers.add(key)
            expected_sites = {
                site_id
                for site_id, site in index_sites.items()
                if (
                    site.get("carrier") == {"kind": kind, "id": carrier_id}
                    or (
                        isinstance(site.get("carrier"), dict)
                        and site["carrier"].get("kind") == kind
                        and isinstance(site["carrier"].get("start_id"), int)
                        and isinstance(site["carrier"].get("end_id"), int)
                        and site["carrier"]["start_id"] <= carrier_id <= site["carrier"]["end_id"]
                    )
                )
            }
            if not expected_sites:
                chain_failures.append(f"tracked carrier {kind} {carrier_id!r} has no indexed sites")
            classified_rows = carrier.get("classified_sites")
            if not isinstance(classified_rows, list):
                chain_failures.append(f"{label}.classified_sites must be a list")
                classified_rows = []
            if not classified_rows:
                chain_failures.append(f"{label}.classified_sites must bind at least one indexed site")
            classified_ids: list[str] = []
            for classified_index, raw_classified in enumerate(classified_rows):
                classified = raw_classified if isinstance(raw_classified, dict) else {}
                site_id = str(classified.get("site_id", "")).strip()
                classified_ids.append(site_id)
                node_ids = classified.get("node_ids")
                if not isinstance(node_ids, list) or not node_ids:
                    chain_failures.append(
                        f"{label}.classified_sites[{classified_index}].node_ids must be nonempty"
                    )
                elif sorted(set(node_ids) - set(nodes)):
                    chain_failures.append(
                        f"{label}.classified_sites[{classified_index}] references an unknown node"
                    )
            excluded_rows = carrier.get("excluded_sites")
            if not isinstance(excluded_rows, list):
                chain_failures.append(f"{label}.excluded_sites must be a list")
                excluded_rows = []
            excluded_ids: list[str] = []
            for excluded_index, raw_excluded in enumerate(excluded_rows):
                excluded = raw_excluded if isinstance(raw_excluded, dict) else {}
                excluded_ids.append(str(excluded.get("site_id", "")).strip())
                if len(str(excluded.get("reason", "")).strip()) < 12:
                    chain_failures.append(
                        f"{label}.excluded_sites[{excluded_index}].reason must explain the exclusion"
                    )
            accounted = classified_ids + excluded_ids
            if len(accounted) != len(set(accounted)):
                chain_failures.append(f"{label} classifies or excludes a site more than once")
            unknown_sites = sorted(set(accounted) - expected_sites)
            missing_sites = sorted(expected_sites - set(accounted))
            if unknown_sites:
                chain_failures.append(f"{label} references unrelated site {unknown_sites[0]!r}")
            if missing_sites:
                chain_failures.append(f"{label} leaves indexed site {missing_sites[0]!r} unclassified")

        if chain_failures:
            _issue(
                issues,
                "error",
                "dependency-chain-invalid",
                f"Dependency chain {chain_id!r} is invalid: {chain_failures[0]}",
                chain_id=chain_id,
                failures=chain_failures,
            )
        chain_results.append(
            {
                "id": chain_id,
                "coverage_status": coverage_status,
                "nodes": len(nodes),
                "unresolved_leaves": len(unresolved_ids),
                "failures": chain_failures,
            }
        )

    required_chain_ids = raw.get("required_chain_ids")
    if not isinstance(required_chain_ids, list) or not required_chain_ids or any(
        not isinstance(row, str) for row in required_chain_ids
    ):
        failures.append("required_chain_ids must be a nonempty list")
        required_chain_ids = []
    if len(required_chain_ids) != len(set(required_chain_ids)):
        failures.append("required_chain_ids contains duplicates")
    missing_required = sorted(set(required_chain_ids) - set(chains))
    if missing_required:
        failures.append(f"required dependency chain {missing_required[0]!r} does not exist")
    for chain_id in required_chain_ids:
        if chain_id in chains and chains[chain_id].get("coverage_status") != "complete":
            failures.append(f"required dependency chain {chain_id!r} is not complete")

    raw_bindings = raw.get("bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        failures.append("bindings must be a nonempty list")
        raw_bindings = []
    binding_results: list[dict[str, str]] = []
    bound_records: list[str] = []
    for binding_index, raw_binding in enumerate(raw_bindings):
        binding = raw_binding if isinstance(raw_binding, dict) else {}
        guide_record_id = str(binding.get("guide_record_id", "")).strip()
        chain_id = str(binding.get("chain_id", "")).strip()
        if guide_record_id not in guide_record_ids:
            failures.append(
                f"bindings[{binding_index}] references unknown guide record {guide_record_id!r}"
            )
        if chain_id not in chains:
            failures.append(f"bindings[{binding_index}] references unknown chain {chain_id!r}")
        elif chains[chain_id].get("coverage_status") != "complete":
            failures.append(
                f"bindings[{binding_index}] cannot publish incomplete chain {chain_id!r}"
            )
        bound_records.append(guide_record_id)
        binding_results.append({"guide_record_id": guide_record_id, "chain_id": chain_id})
    if len(binding_results) != len({(row["guide_record_id"], row["chain_id"]) for row in binding_results}):
        failures.append("bindings contains duplicate guide-record/chain pairs")
    missing_companions = sorted(companion_entry_ids - set(bound_records))
    if missing_companions:
        failures.append(
            f"companion recruitment {missing_companions[0]!r} has no complete dependency-chain binding"
        )

    if failures:
        _issue(
            issues,
            "error",
            "dependency-closure-invalid",
            f"Dependency closure is invalid: {failures[0]}",
            failures=failures,
        )
    return {
        "artifact": artifact_name,
        "index_artifact": index_name,
        "chains": chain_results,
        "bindings": binding_results,
        "failures": failures,
    }


def _validate_publication(
    html_path: Path | None,
    claims: dict[str, dict[str, Any]],
    chapters: dict[str, dict[str, Any]],
    sections: dict[str, dict[str, Any]],
    optional_groups: dict[str, dict[str, Any]],
    optional_entries: dict[str, dict[str, Any]],
    boss_groups: dict[str, dict[str, Any]],
    boss_entries: dict[str, dict[str, Any]],
    scene_groups: dict[str, dict[str, Any]],
    scene_entries: dict[str, dict[str, Any]],
    scene_catalog: dict[str, Any],
    glossary_names: list[str],
    gender_facts: list[dict[str, str]],
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    if html_path is None or not html_path.is_file():
        _issue(issues, "error", "publication-missing", "Published WALKTHROUGH.html is required.")
        return {"checked": False}
    try:
        raw_html = html_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationInputError(f"Could not read published walkthrough {html_path}: {exc}") from exc
    parser = WalkthroughHTMLParser()
    parser.feed(raw_html)
    parser.close()

    for hook in sorted(REQUIRED_HOOKS):
        if parser.hooks[hook] == 0:
            _issue(issues, "error", "publication-hook-missing", f"Published HTML is missing .{hook}.", hook=hook)
    if parser.hero_stats != 4:
        _issue(
            issues,
            "error",
            "hero-stat-count-invalid",
            f"Published HTML must contain exactly four .hero-stat elements; observed {parser.hero_stats}.",
        )

    duplicate_ids = sorted(element_id for element_id, count in parser.ids.items() if count > 1)
    if duplicate_ids:
        _issue(
            issues,
            "error",
            "duplicate-html-id",
            f"Published HTML contains duplicate id {duplicate_ids[0]!r}.",
            ids=duplicate_ids,
        )

    observed_tabs = {key for key, count in parser.tabs.items() if key and count}
    if observed_tabs != set(REQUIRED_VIEWS) or any(parser.tabs[key] != 1 for key in REQUIRED_VIEWS):
        _issue(
            issues,
            "error",
            "view-tabs-invalid",
            "Published HTML must contain exactly one tab for each required view.",
            expected=sorted(REQUIRED_VIEWS),
            observed=dict(parser.tabs),
        )
    for view, panel_id in REQUIRED_VIEWS.items():
        if parser.tab_hrefs[view] != Counter({f"#{panel_id}": 1}):
            _issue(
                issues,
                "error",
                "view-tab-destination-invalid",
                f"Tab {view!r} must link to #{panel_id}.",
                view=view,
                observed=dict(parser.tab_hrefs[view]),
            )
    observed_views = {key for key, count in parser.views.items() if key and count}
    if observed_views != set(REQUIRED_VIEWS) or any(parser.views[key] != 1 for key in REQUIRED_VIEWS):
        _issue(
            issues,
            "error",
            "guide-views-invalid",
            "Published HTML must contain exactly the four required guide views.",
            expected=sorted(REQUIRED_VIEWS),
            observed=dict(parser.views),
        )
    for view, panel_id in REQUIRED_VIEWS.items():
        if parser.view_ids.get(view) != panel_id:
            _issue(
                issues,
                "error",
                "guide-view-id-invalid",
                f"View {view!r} must use id {panel_id!r}.",
                view=view,
            )
        placeholder = parser.view_placeholders.get(view)
        if view in PLACEHOLDER_VIEWS and placeholder != "true":
            _issue(
                issues,
                "error",
                "future-view-not-placeholder",
                f"View {view!r} must remain a milestone placeholder.",
                view=view,
            )
        if view in COMPLETE_VIEWS and placeholder == "true":
            _issue(
                issues,
                "error",
                "completed-view-is-placeholder",
                f"Completed view {view!r} cannot be a placeholder.",
                view=view,
            )

    declared_ids = set(claims)
    declared_chapter_ids = set(chapters)
    rendered_chapter_ids = {
        chapter_id for chapter_id, count in parser.route_chapters.items() if chapter_id and count
    }
    for chapter_id in sorted(declared_chapter_ids | rendered_chapter_ids):
        if chapter_id not in declared_chapter_ids:
            _issue(
                issues,
                "error",
                "rendered-chapter-undeclared",
                f"Rendered route chapter {chapter_id!r} has no route_structure entry.",
                chapter_id=chapter_id,
            )
            continue
        chapter = chapters[chapter_id]
        if parser.route_chapters[chapter_id] != 1:
            _issue(
                issues,
                "error",
                "route-chapter-binding-invalid",
                f"Route chapter {chapter_id!r} must render exactly once; observed {parser.route_chapters[chapter_id]}.",
                chapter_id=chapter_id,
            )
        if parser.route_chapter_views.get(chapter_id, set()) != {"main-route"}:
            _issue(
                issues,
                "error",
                "route-chapter-outside-main-route",
                f"Route chapter {chapter_id!r} must be inside the Main Route view.",
                chapter_id=chapter_id,
            )
        label = str(chapter.get("label", ""))
        if parser.route_chapter_labels[chapter_id] != Counter({label: 1}):
            _issue(
                issues,
                "error",
                "route-chapter-label-mismatch",
                f"Route chapter {chapter_id!r} must bind its exact game-authored label.",
                chapter_id=chapter_id,
                expected=label,
                observed=dict(parser.route_chapter_labels[chapter_id]),
            )
        if parser.route_chapter_heading_ids[chapter_id] != Counter({chapter_id: 1}):
            _issue(
                issues,
                "error",
                "route-chapter-heading-link-invalid",
                f"Route chapter {chapter_id!r} must expose one h2 with that exact id for local navigation.",
                chapter_id=chapter_id,
                expected=chapter_id,
                observed=dict(parser.route_chapter_heading_ids[chapter_id]),
            )
        chapter_text = _normalize(" ".join(parser.route_chapter_text_parts[chapter_id]))
        if _normalize(label) not in chapter_text:
            _issue(
                issues,
                "error",
                "route-chapter-label-not-visible",
                f"Route chapter {chapter_id!r} does not visibly render its label.",
                chapter_id=chapter_id,
            )

    declared_section_ids = set(sections)
    rendered_section_ids = {section_id for section_id, count in parser.route_sections.items() if section_id and count}
    for section_id in sorted(declared_section_ids | rendered_section_ids):
        if section_id not in declared_section_ids:
            _issue(
                issues,
                "error",
                "rendered-section-undeclared",
                f"Rendered route section {section_id!r} has no route_structure entry.",
                section_id=section_id,
            )
            continue
        section = sections[section_id]
        if parser.route_sections[section_id] != 1:
            _issue(
                issues,
                "error",
                "route-section-binding-invalid",
                f"Route section {section_id!r} must render exactly once; observed {parser.route_sections[section_id]}.",
                section_id=section_id,
            )
        if parser.route_section_views.get(section_id, set()) != {"main-route"}:
            _issue(
                issues,
                "error",
                "route-section-outside-main-route",
                f"Route section {section_id!r} must be inside the Main Route view.",
                section_id=section_id,
            )
        expected_chapters = {
            chapter_id
            for chapter_id, chapter in chapters.items()
            if section_id in (chapter.get("section_ids") or [])
        }
        observed_chapters = parser.route_section_chapter_contexts.get(section_id, set())
        if observed_chapters != (expected_chapters or {None}):
            _issue(
                issues,
                "error",
                "route-section-chapter-context-invalid",
                f"Route section {section_id!r} must be nested in its declared chapter.",
                section_id=section_id,
                expected=sorted(expected_chapters),
                observed=sorted(row or "" for row in observed_chapters),
            )
        label = str(section.get("label", ""))
        if parser.route_section_labels[section_id] != Counter({label: 1}):
            _issue(
                issues,
                "error",
                "route-section-label-mismatch",
                f"Route section {section_id!r} must bind its exact game-authored label.",
                section_id=section_id,
                expected=label,
                observed=dict(parser.route_section_labels[section_id]),
            )
        if parser.route_section_heading_ids[section_id] != Counter({section_id: 1}):
            _issue(
                issues,
                "error",
                "route-section-heading-link-invalid",
                f"Route section {section_id!r} must expose one h2 with that exact id for local navigation.",
                section_id=section_id,
                expected=section_id,
                observed=dict(parser.route_section_heading_ids[section_id]),
            )
        expected_heading_tag = "h3" if chapters else "h2"
        if parser.route_section_heading_tags[section_id] != Counter({expected_heading_tag: 1}):
            _issue(
                issues,
                "error",
                "route-section-heading-level-invalid",
                f"Route section {section_id!r} must use one {expected_heading_tag} beneath the active hierarchy.",
                section_id=section_id,
                expected=expected_heading_tag,
                observed=dict(parser.route_section_heading_tags[section_id]),
            )
        section_text = _normalize(" ".join(parser.route_section_text_parts[section_id]))
        if _normalize(label) not in section_text:
            _issue(
                issues,
                "error",
                "route-section-label-not-visible",
                f"Route section {section_id!r} does not visibly render its label.",
                section_id=section_id,
            )

    rendered_ids = {claim_id for claim_id, count in parser.route_steps.items() if claim_id and count}
    rendered_task_ids = {task_id for task_id, count in parser.route_tasks.items() if task_id and count}
    for task_id in sorted(rendered_task_ids - declared_ids):
        _issue(
            issues,
            "error",
            "rendered-task-undeclared",
            f"Rendered checklist task {task_id!r} has no evidence claim.",
            claim_id=task_id,
        )
    for claim_id in sorted(declared_ids | rendered_ids):
        if claim_id not in declared_ids:
            _issue(
                issues,
                "error",
                "rendered-claim-undeclared",
                f"Rendered route step {claim_id!r} has no evidence claim.",
                claim_id=claim_id,
            )
            continue
        if parser.route_steps[claim_id] != 1:
            _issue(
                issues,
                "error",
                "route-step-binding-invalid",
                f"Claim {claim_id!r} must render as exactly one route step; observed {parser.route_steps[claim_id]}.",
                claim_id=claim_id,
            )
        if parser.route_step_views.get(claim_id, set()) != {"main-route"}:
            _issue(
                issues,
                "error",
                "route-step-outside-main-route",
                f"Route step {claim_id!r} must be inside the Main Route view.",
                claim_id=claim_id,
            )
        expected_sections = {
            section_id
            for section_id, section in sections.items()
            if claim_id in (section.get("claim_ids") or [])
        }
        if parser.route_step_section_contexts.get(claim_id, set()) != expected_sections:
            _issue(
                issues,
                "error",
                "route-step-section-context-invalid",
                f"Route step {claim_id!r} must be nested in its declared route section.",
                claim_id=claim_id,
                expected=sorted(expected_sections),
                observed=sorted(row or "" for row in parser.route_step_section_contexts.get(claim_id, set())),
            )
        if parser.route_tasks[claim_id] != 1:
            _issue(
                issues,
                "error",
                "route-task-binding-invalid",
                f"Claim {claim_id!r} must render exactly one matching .task-checkbox; observed {parser.route_tasks[claim_id]}.",
                claim_id=claim_id,
            )
        if parser.route_task_claim_contexts.get(claim_id, set()) != {claim_id}:
            _issue(
                issues,
                "error",
                "route-task-context-invalid",
                f"Checklist task {claim_id!r} must be nested in its matching route step.",
                claim_id=claim_id,
            )
        if parser.route_task_views.get(claim_id, set()) != {"main-route"}:
            _issue(
                issues,
                "error",
                "route-task-outside-main-route",
                f"Checklist task {claim_id!r} must be inside the Main Route view.",
                claim_id=claim_id,
            )
        if parser.evidence[claim_id] != 1:
            _issue(
                issues,
                "error",
                "evidence-disclosure-binding-invalid",
                f"Claim {claim_id!r} must have exactly one matching Evidence disclosure.",
                claim_id=claim_id,
            )
        if parser.evidence_claim_contexts[claim_id] != {claim_id}:
            _issue(
                issues,
                "error",
                "evidence-outside-route-step",
                f"Evidence disclosure {claim_id!r} must be nested in its matching route step.",
                claim_id=claim_id,
            )
        expected_status = str(claims[claim_id].get("status", ""))
        if parser.evidence_statuses[claim_id] != Counter({expected_status: 1}):
            _issue(
                issues,
                "error",
                "evidence-status-mismatch",
                f"Claim {claim_id!r} must render evidence status {expected_status!r} exactly once.",
                claim_id=claim_id,
            )
        expected_sources = Counter(
            str(source.get("id", ""))
            for source in claims[claim_id].get("sources") or []
            if isinstance(source, dict)
        )
        if parser.evidence_sources[claim_id] != expected_sources:
            _issue(
                issues,
                "error",
                "rendered-evidence-sources-mismatch",
                f"Claim {claim_id!r} does not render the same source IDs as evidence.json.",
                claim_id=claim_id,
                expected=dict(expected_sources),
                observed=dict(parser.evidence_sources[claim_id]),
            )
        step_text = _normalize(" ".join(parser.route_step_text_parts[claim_id]))
        for phrase in claims[claim_id].get("guide_phrases") or []:
            if _normalize(str(phrase)) not in step_text:
                _issue(
                    issues,
                    "error",
                    "published-guide-phrase-missing",
                    f"Route step {claim_id!r} is missing its guide phrase: {phrase!r}",
                    claim_id=claim_id,
                )
        evidence_text = _normalize(" ".join(parser.evidence_text_parts[claim_id]))
        for source in claims[claim_id].get("sources") or []:
            if not isinstance(source, dict):
                continue
            supports = _normalize(str(source.get("supports", "")))
            source_id = str(source.get("id", ""))
            source_text = _normalize(" ".join(parser.source_text_parts[claim_id][source_id]))
            if supports and supports not in source_text:
                _issue(
                    issues,
                    "error",
                    "evidence-explanation-missing",
                    f"Evidence source {source_id!r} in claim {claim_id!r} does not show what it proves.",
                    claim_id=claim_id,
                    source_id=source_id,
                )
    declared_optional_group_ids = set(optional_groups)
    rendered_optional_group_ids = {
        group_id for group_id, count in parser.optional_groups.items() if group_id and count
    }
    for group_id in sorted(declared_optional_group_ids | rendered_optional_group_ids):
        if group_id not in declared_optional_group_ids:
            _issue(
                issues,
                "error",
                "rendered-optional-group-undeclared",
                f"Rendered optional group {group_id!r} has no optional_content entry.",
                group_id=group_id,
            )
            continue
        group = optional_groups[group_id]
        if parser.optional_groups[group_id] != 1:
            _issue(
                issues,
                "error",
                "optional-group-binding-invalid",
                f"Optional group {group_id!r} must render exactly once; observed {parser.optional_groups[group_id]}.",
                group_id=group_id,
            )
        if parser.optional_group_views.get(group_id, set()) != {"optional-content"}:
            _issue(
                issues,
                "error",
                "optional-group-outside-view",
                f"Optional group {group_id!r} must be inside Optional Content.",
                group_id=group_id,
            )
        label = str(group.get("label", ""))
        if parser.optional_group_labels[group_id] != Counter({label: 1}):
            _issue(
                issues,
                "error",
                "optional-group-label-mismatch",
                f"Optional group {group_id!r} must bind its declared label.",
                group_id=group_id,
                expected=label,
                observed=dict(parser.optional_group_labels[group_id]),
            )
        if parser.optional_group_heading_ids[group_id] != Counter({group_id: 1}):
            _issue(
                issues,
                "error",
                "optional-group-heading-link-invalid",
                f"Optional group {group_id!r} must expose one h2 with that exact id.",
                group_id=group_id,
            )
        group_text = _normalize(" ".join(parser.optional_group_text_parts[group_id]))
        if _normalize(label) not in group_text:
            _issue(
                issues,
                "error",
                "optional-group-label-not-visible",
                f"Optional group {group_id!r} does not visibly render its label.",
                group_id=group_id,
            )

    declared_optional_ids = set(optional_entries)
    rendered_optional_ids = {
        entry_id for entry_id, count in parser.optional_entries.items() if entry_id and count
    }
    rendered_optional_task_ids = {
        task_id for task_id, count in parser.optional_tasks.items() if task_id and count
    }
    for task_id in sorted(rendered_optional_task_ids - declared_optional_ids):
        _issue(
            issues,
            "error",
            "rendered-optional-task-undeclared",
            f"Rendered optional checklist task {task_id!r} has no evidence entry.",
            entry_id=task_id,
        )
    for entry_id in sorted(declared_optional_ids | rendered_optional_ids):
        if entry_id not in declared_optional_ids:
            _issue(
                issues,
                "error",
                "rendered-optional-entry-undeclared",
                f"Rendered optional entry {entry_id!r} has no evidence entry.",
                entry_id=entry_id,
            )
            continue
        entry = optional_entries[entry_id]
        if parser.optional_entries[entry_id] != 1:
            _issue(
                issues,
                "error",
                "optional-entry-binding-invalid",
                f"Optional entry {entry_id!r} must render exactly once; observed {parser.optional_entries[entry_id]}.",
                entry_id=entry_id,
            )
        if parser.optional_entry_views.get(entry_id, set()) != {"optional-content"}:
            _issue(
                issues,
                "error",
                "optional-entry-outside-view",
                f"Optional entry {entry_id!r} must be inside Optional Content.",
                entry_id=entry_id,
            )
        expected_groups = {
            group_id
            for group_id, group in optional_groups.items()
            if entry_id in (group.get("entry_ids") or [])
        }
        if parser.optional_entry_group_contexts.get(entry_id, set()) != expected_groups:
            _issue(
                issues,
                "error",
                "optional-entry-group-context-invalid",
                f"Optional entry {entry_id!r} must be nested in its declared group.",
                entry_id=entry_id,
                expected=sorted(expected_groups),
                observed=sorted(
                    row or "" for row in parser.optional_entry_group_contexts.get(entry_id, set())
                ),
            )
        if parser.optional_entry_heading_ids[entry_id] != Counter({entry_id: 1}):
            _issue(
                issues,
                "error",
                "optional-entry-heading-link-invalid",
                f"Optional entry {entry_id!r} must expose one h3 with that exact id.",
                entry_id=entry_id,
            )
        if parser.optional_tasks[entry_id] != 1:
            _issue(
                issues,
                "error",
                "optional-task-binding-invalid",
                f"Optional entry {entry_id!r} must render one matching checklist task.",
                entry_id=entry_id,
            )
        if parser.optional_task_entry_contexts.get(entry_id, set()) != {entry_id}:
            _issue(
                issues,
                "error",
                "optional-task-context-invalid",
                f"Optional checklist task {entry_id!r} must be inside its matching entry.",
                entry_id=entry_id,
            )
        if parser.optional_task_views.get(entry_id, set()) != {"optional-content"}:
            _issue(
                issues,
                "error",
                "optional-task-outside-view",
                f"Optional checklist task {entry_id!r} must be inside Optional Content.",
                entry_id=entry_id,
            )
        if parser.evidence[entry_id] != 1:
            _issue(
                issues,
                "error",
                "optional-evidence-binding-invalid",
                f"Optional entry {entry_id!r} must have exactly one matching Evidence disclosure.",
                entry_id=entry_id,
            )
        if parser.evidence_optional_contexts[entry_id] != {entry_id}:
            _issue(
                issues,
                "error",
                "optional-evidence-outside-entry",
                f"Evidence disclosure {entry_id!r} must be inside its matching Optional Content entry.",
                entry_id=entry_id,
            )
        expected_status = str(entry.get("status", ""))
        if parser.evidence_statuses[entry_id] != Counter({expected_status: 1}):
            _issue(
                issues,
                "error",
                "optional-evidence-status-mismatch",
                f"Optional entry {entry_id!r} must render evidence status {expected_status!r} exactly once.",
                entry_id=entry_id,
            )
        expected_sources = Counter(
            str(source.get("id", ""))
            for source in entry.get("sources") or []
            if isinstance(source, dict)
        )
        if parser.evidence_sources[entry_id] != expected_sources:
            _issue(
                issues,
                "error",
                "optional-evidence-sources-mismatch",
                f"Optional entry {entry_id!r} does not render the same source IDs as evidence.json.",
                entry_id=entry_id,
                expected=dict(expected_sources),
                observed=dict(parser.evidence_sources[entry_id]),
            )
        entry_text = _normalize(" ".join(parser.optional_entry_text_parts[entry_id]))
        title = _normalize(str(entry.get("title", "")))
        if title and title not in entry_text:
            _issue(
                issues,
                "error",
                "optional-title-not-visible",
                f"Optional entry {entry_id!r} does not visibly render its title.",
                entry_id=entry_id,
            )
        for phrase in entry.get("guide_phrases") or []:
            if _normalize(str(phrase)) not in entry_text:
                _issue(
                    issues,
                    "error",
                    "optional-guide-phrase-missing",
                    f"Optional entry {entry_id!r} is missing its guide phrase: {phrase!r}",
                    entry_id=entry_id,
                )
        for source in entry.get("sources") or []:
            if not isinstance(source, dict):
                continue
            supports = _normalize(str(source.get("supports", "")))
            source_id = str(source.get("id", ""))
            source_text = _normalize(" ".join(parser.source_text_parts[entry_id][source_id]))
            if supports and supports not in source_text:
                _issue(
                    issues,
                    "error",
                    "optional-evidence-explanation-missing",
                    f"Evidence source {source_id!r} in optional entry {entry_id!r} does not show what it proves.",
                    entry_id=entry_id,
                    source_id=source_id,
                )
        anchor_id = str(entry.get("route_anchor_id", ""))
        anchor_position = str(entry.get("route_anchor_position", ""))
        href = f"#{entry_id}"
        observed_claim_contexts = {
            row for row in parser.guide_link_claim_contexts.get(href, set()) if row is not None
        }
        if observed_claim_contexts != {anchor_id}:
            _issue(
                issues,
                "error",
                "optional-main-route-link-invalid",
                f"Optional entry {entry_id!r} must have a Main Route link from its declared anchor.",
                entry_id=entry_id,
                expected_anchor=anchor_id,
                observed=sorted(
                    row for row in observed_claim_contexts
                ),
            )
        if parser.guide_link_positions.get(href, Counter()) != Counter({anchor_position: 1}):
            _issue(
                issues,
                "error",
                "optional-main-route-link-position-invalid",
                f"Optional entry {entry_id!r} must render at its declared point relative to the Main Route step.",
                entry_id=entry_id,
                expected_position=anchor_position,
                observed=dict(parser.guide_link_positions.get(href, Counter())),
            )
        if parser.guide_link_dom_positions.get(href, Counter()) != Counter({anchor_position: 1}):
            _issue(
                issues,
                "error",
                "optional-main-route-link-order-invalid",
                f"Optional entry {entry_id!r} is not placed {anchor_position} its Main Route prose.",
                entry_id=entry_id,
                expected_position=anchor_position,
                observed=dict(parser.guide_link_dom_positions.get(href, Counter())),
            )
        if parser.guide_link_kinds_in_claims.get(href, Counter()) != Counter({"optional": 1}):
            _issue(
                issues,
                "error",
                "optional-main-route-link-kind-invalid",
                f"Optional entry {entry_id!r} must use the optional cross-tab link style.",
                entry_id=entry_id,
                observed=dict(parser.guide_link_kinds_in_claims.get(href, Counter())),
            )

    declared_boss_group_ids = set(boss_groups)
    rendered_boss_group_ids = {
        group_id for group_id, count in parser.boss_groups.items() if group_id and count
    }
    for group_id in sorted(declared_boss_group_ids | rendered_boss_group_ids):
        if group_id not in declared_boss_group_ids:
            _issue(
                issues,
                "error",
                "rendered-boss-group-undeclared",
                f"Rendered boss group {group_id!r} has no bosses entry.",
                group_id=group_id,
            )
            continue
        group = boss_groups[group_id]
        if parser.boss_groups[group_id] != 1:
            _issue(
                issues,
                "error",
                "boss-group-binding-invalid",
                f"Boss group {group_id!r} must render exactly once; observed {parser.boss_groups[group_id]}.",
                group_id=group_id,
            )
        if parser.boss_group_views.get(group_id, set()) != {"bosses"}:
            _issue(
                issues,
                "error",
                "boss-group-outside-view",
                f"Boss group {group_id!r} must be inside Bosses.",
                group_id=group_id,
            )
        label = str(group.get("label", ""))
        if parser.boss_group_labels[group_id] != Counter({label: 1}):
            _issue(
                issues,
                "error",
                "boss-group-label-mismatch",
                f"Boss group {group_id!r} must bind its declared label.",
                group_id=group_id,
                expected=label,
                observed=dict(parser.boss_group_labels[group_id]),
            )
        if parser.boss_group_heading_ids[group_id] != Counter({group_id: 1}):
            _issue(
                issues,
                "error",
                "boss-group-heading-link-invalid",
                f"Boss group {group_id!r} must expose one h2 with that exact id.",
                group_id=group_id,
            )
        group_text = _normalize(" ".join(parser.boss_group_text_parts[group_id]))
        if _normalize(label) not in group_text:
            _issue(
                issues,
                "error",
                "boss-group-label-not-visible",
                f"Boss group {group_id!r} does not visibly render its label.",
                group_id=group_id,
            )

    declared_boss_ids = set(boss_entries)
    rendered_boss_ids = {
        boss_id for boss_id, count in parser.boss_entries.items() if boss_id and count
    }
    rendered_boss_task_ids = {
        task_id for task_id, count in parser.boss_tasks.items() if task_id and count
    }
    for task_id in sorted(rendered_boss_task_ids - declared_boss_ids):
        _issue(
            issues,
            "error",
            "rendered-boss-task-undeclared",
            f"Rendered boss checklist task {task_id!r} has no evidence entry.",
            boss_id=task_id,
        )

    expected_boss_backlinks: dict[str, set[str]] = defaultdict(set)
    for boss_id in sorted(declared_boss_ids | rendered_boss_ids):
        if boss_id not in declared_boss_ids:
            _issue(
                issues,
                "error",
                "rendered-boss-entry-undeclared",
                f"Rendered boss entry {boss_id!r} has no evidence entry.",
                boss_id=boss_id,
            )
            continue
        entry = boss_entries[boss_id]
        if parser.boss_entries[boss_id] != 1:
            _issue(
                issues,
                "error",
                "boss-entry-binding-invalid",
                f"Boss entry {boss_id!r} must render exactly once; observed {parser.boss_entries[boss_id]}.",
                boss_id=boss_id,
            )
        if parser.boss_entry_views.get(boss_id, set()) != {"bosses"}:
            _issue(
                issues,
                "error",
                "boss-entry-outside-view",
                f"Boss entry {boss_id!r} must be inside Bosses.",
                boss_id=boss_id,
            )
        expected_groups = {
            group_id
            for group_id, group in boss_groups.items()
            if boss_id in (group.get("entry_ids") or [])
        }
        if parser.boss_entry_group_contexts.get(boss_id, set()) != expected_groups:
            _issue(
                issues,
                "error",
                "boss-entry-group-context-invalid",
                f"Boss entry {boss_id!r} must be nested in its declared group.",
                boss_id=boss_id,
                expected=sorted(expected_groups),
                observed=sorted(row or "" for row in parser.boss_entry_group_contexts.get(boss_id, set())),
            )
        if parser.boss_entry_heading_ids[boss_id] != Counter({f"boss-{boss_id}": 1}):
            _issue(
                issues,
                "error",
                "boss-entry-heading-link-invalid",
                f"Boss entry {boss_id!r} must expose one h3 with id 'boss-{boss_id}'.",
                boss_id=boss_id,
            )
        phases = entry.get("phases") or []
        expected_phase_sections = Counter({str(index): 1 for index in range(1, len(phases) + 1)})
        if parser.boss_phase_sections[boss_id] != expected_phase_sections:
            _issue(
                issues,
                "error",
                "boss-phase-binding-invalid",
                f"Boss entry {boss_id!r} must render one indexed section for every declared phase.",
                boss_id=boss_id,
                expected=dict(expected_phase_sections),
                observed=dict(parser.boss_phase_sections[boss_id]),
            )
        for phase_index, phase in enumerate(phases, 1):
            if not isinstance(phase, dict):
                continue
            phase_key = str(phase_index)
            expected_cells = {
                "Form": str(phase.get("label", "")),
                **{str(key): str(value) for key, value in (phase.get("stats") or {}).items()},
                "EXP": str(phase.get("exp", "")),
                "Gold": str(phase.get("gold", "")),
                "Database drops": str(phase.get("drops", "")),
            }
            expected_stat_bindings = Counter({key: 1 for key in expected_cells})
            observed_stat_bindings = parser.boss_stat_cells[boss_id][phase_key]
            if observed_stat_bindings != expected_stat_bindings:
                _issue(
                    issues,
                    "error",
                    "boss-stat-binding-invalid",
                    f"Boss entry {boss_id!r} phase {phase_index} must render each declared stat exactly once.",
                    boss_id=boss_id,
                    phase_index=phase_index,
                    expected=dict(expected_stat_bindings),
                    observed=dict(observed_stat_bindings),
                )
                continue
            for stat_name, expected_value in expected_cells.items():
                observed_value = _normalize(
                    " ".join(parser.boss_stat_text_parts[boss_id][phase_key][stat_name])
                )
                if observed_value != _normalize(expected_value):
                    _issue(
                        issues,
                        "error",
                        "boss-stat-value-mismatch",
                        f"Boss entry {boss_id!r} phase {phase_index} renders the wrong {stat_name} value.",
                        boss_id=boss_id,
                        phase_index=phase_index,
                        stat=stat_name,
                        expected=expected_value,
                        observed=observed_value,
                    )
        if parser.boss_tasks[boss_id] != 1:
            _issue(
                issues,
                "error",
                "boss-task-binding-invalid",
                f"Boss entry {boss_id!r} must render one matching checklist task.",
                boss_id=boss_id,
            )
        if parser.boss_task_entry_contexts.get(boss_id, set()) != {boss_id}:
            _issue(
                issues,
                "error",
                "boss-task-context-invalid",
                f"Boss checklist task {boss_id!r} must be inside its matching dossier.",
                boss_id=boss_id,
            )
        if parser.boss_task_views.get(boss_id, set()) != {"bosses"}:
            _issue(
                issues,
                "error",
                "boss-task-outside-view",
                f"Boss checklist task {boss_id!r} must be inside Bosses.",
                boss_id=boss_id,
            )
        if parser.evidence[boss_id] != 1:
            _issue(
                issues,
                "error",
                "boss-evidence-binding-invalid",
                f"Boss entry {boss_id!r} must have exactly one matching Evidence disclosure.",
                boss_id=boss_id,
            )
        if parser.evidence_boss_contexts[boss_id] != {boss_id}:
            _issue(
                issues,
                "error",
                "boss-evidence-outside-entry",
                f"Evidence disclosure {boss_id!r} must be inside its matching boss entry.",
                boss_id=boss_id,
            )
        expected_status = str(entry.get("status", ""))
        if parser.evidence_statuses[boss_id] != Counter({expected_status: 1}):
            _issue(
                issues,
                "error",
                "boss-evidence-status-mismatch",
                f"Boss entry {boss_id!r} must render evidence status {expected_status!r} exactly once.",
                boss_id=boss_id,
            )
        expected_sources = Counter(
            str(source.get("id", ""))
            for source in entry.get("sources") or []
            if isinstance(source, dict)
        )
        if parser.evidence_sources[boss_id] != expected_sources:
            _issue(
                issues,
                "error",
                "boss-evidence-sources-mismatch",
                f"Boss entry {boss_id!r} does not render the same source IDs as evidence.json.",
                boss_id=boss_id,
                expected=dict(expected_sources),
                observed=dict(parser.evidence_sources[boss_id]),
            )
        entry_text = _normalize(" ".join(parser.boss_entry_text_parts[boss_id]))
        title = _normalize(str(entry.get("title", "")))
        if title and title not in entry_text:
            _issue(
                issues,
                "error",
                "boss-title-not-visible",
                f"Boss entry {boss_id!r} does not visibly render its title.",
                boss_id=boss_id,
            )
        for phrase in entry.get("guide_phrases") or []:
            if _normalize(str(phrase)) not in entry_text:
                _issue(
                    issues,
                    "error",
                    "boss-guide-phrase-missing",
                    f"Boss entry {boss_id!r} is missing its guide phrase: {phrase!r}",
                    boss_id=boss_id,
                )
        for source in entry.get("sources") or []:
            if not isinstance(source, dict):
                continue
            supports = _normalize(str(source.get("supports", "")))
            source_id = str(source.get("id", ""))
            source_text = _normalize(" ".join(parser.source_text_parts[boss_id][source_id]))
            if supports and supports not in source_text:
                _issue(
                    issues,
                    "error",
                    "boss-evidence-explanation-missing",
                    f"Evidence source {source_id!r} in boss entry {boss_id!r} does not show what it proves.",
                    boss_id=boss_id,
                    source_id=source_id,
                )

        href = f"#boss-{boss_id}"
        expected_route_contexts = set(entry.get("route_claim_ids") or [])
        observed_route_contexts = {
            row for row in parser.guide_link_claim_contexts.get(href, set()) if row is not None
        }
        if observed_route_contexts != expected_route_contexts:
            _issue(
                issues,
                "error",
                "boss-main-route-link-invalid",
                f"Boss entry {boss_id!r} must be linked from every declared Main Route encounter.",
                boss_id=boss_id,
                expected=sorted(expected_route_contexts),
                observed=sorted(observed_route_contexts),
            )
        expected_route_link_kinds = Counter({"boss": len(expected_route_contexts)})
        if parser.guide_link_kinds_in_claims.get(href, Counter()) != expected_route_link_kinds:
            _issue(
                issues,
                "error",
                "boss-main-route-link-kind-invalid",
                f"Boss dossier {boss_id!r} must use the boss cross-tab link style from every Main Route source.",
                boss_id=boss_id,
                expected=dict(expected_route_link_kinds),
                observed=dict(parser.guide_link_kinds_in_claims.get(href, Counter())),
            )
        expected_optional_contexts = set(entry.get("optional_entry_ids") or [])
        observed_optional_contexts = {
            row for row in parser.guide_link_optional_contexts.get(href, set()) if row is not None
        }
        if observed_optional_contexts != expected_optional_contexts:
            _issue(
                issues,
                "error",
                "boss-optional-link-invalid",
                f"Boss entry {boss_id!r} must be linked from every declared Optional Content entry.",
                boss_id=boss_id,
                expected=sorted(expected_optional_contexts),
                observed=sorted(observed_optional_contexts),
            )
        for destination in expected_route_contexts | expected_optional_contexts:
            expected_boss_backlinks[f"#{destination}"].add(boss_id)

    for href, expected_bosses in expected_boss_backlinks.items():
        observed_bosses = {
            row for row in parser.guide_link_boss_contexts.get(href, set()) if row is not None
        }
        if observed_bosses != expected_bosses:
            _issue(
                issues,
                "error",
                "boss-source-backlink-invalid",
                f"Boss dossier backlinks to {href!r} do not match the evidence bindings.",
                href=href,
                expected=sorted(expected_bosses),
                observed=sorted(observed_bosses),
            )

    catalog_id = str(scene_catalog.get("id", ""))
    if parser.ids[catalog_id] != 1 or parser.id_views.get(catalog_id) != "scenes-cg":
        _issue(
            issues,
            "error",
            "scene-catalog-binding-invalid",
            "The Scenes & CG system overview must render once inside its completed view.",
            catalog_id=catalog_id,
        )
    if parser.evidence[catalog_id] != 1:
        _issue(
            issues,
            "error",
            "scene-catalog-evidence-binding-invalid",
            "The Scenes & CG system overview must have one matching Evidence disclosure.",
            catalog_id=catalog_id,
        )
    if parser.evidence_scene_contexts[catalog_id] != {None}:
        _issue(
            issues,
            "error",
            "scene-catalog-evidence-context-invalid",
            "The Scenes & CG system evidence must sit outside individual scene entries.",
            catalog_id=catalog_id,
        )
    if parser.evidence_statuses[catalog_id] != Counter({"verified": 1}):
        _issue(
            issues,
            "error",
            "scene-catalog-evidence-status-mismatch",
            "The Scenes & CG system overview must render verified evidence status exactly once.",
            catalog_id=catalog_id,
        )
    expected_catalog_sources = Counter(
        str(source.get("id", ""))
        for source in scene_catalog.get("sources") or []
        if isinstance(source, dict)
    )
    if parser.evidence_sources[catalog_id] != expected_catalog_sources:
        _issue(
            issues,
            "error",
            "scene-catalog-evidence-sources-mismatch",
            "The Scenes & CG system overview does not render the same source IDs as evidence.json.",
            expected=dict(expected_catalog_sources),
            observed=dict(parser.evidence_sources[catalog_id]),
        )
    catalog_text = _normalize(" ".join(parser.scene_system_text_parts))
    for phrase in scene_catalog.get("guide_phrases") or []:
        if _normalize(str(phrase)) not in catalog_text:
            _issue(
                issues,
                "error",
                "scene-catalog-guide-phrase-missing",
                f"Scenes & CG system overview is missing its guide phrase: {phrase!r}",
            )
    for source in scene_catalog.get("sources") or []:
        if not isinstance(source, dict):
            continue
        supports = _normalize(str(source.get("supports", "")))
        source_id = str(source.get("id", ""))
        source_text = _normalize(" ".join(parser.source_text_parts[catalog_id][source_id]))
        if supports and supports not in source_text:
            _issue(
                issues,
                "error",
                "scene-catalog-evidence-explanation-missing",
                f"Catalog evidence source {source_id!r} does not show what it proves.",
                source_id=source_id,
            )

    declared_scene_group_ids = set(scene_groups)
    rendered_scene_group_ids = {
        group_id for group_id, count in parser.scene_groups.items() if group_id and count
    }
    for group_id in sorted(declared_scene_group_ids | rendered_scene_group_ids):
        if group_id not in declared_scene_group_ids:
            _issue(
                issues,
                "error",
                "rendered-scene-group-undeclared",
                f"Rendered scene group {group_id!r} has no scenes_cg entry.",
                group_id=group_id,
            )
            continue
        group = scene_groups[group_id]
        if parser.scene_groups[group_id] != 1:
            _issue(
                issues,
                "error",
                "scene-group-binding-invalid",
                f"Scene group {group_id!r} must render exactly once.",
                group_id=group_id,
            )
        if parser.scene_group_views.get(group_id, set()) != {"scenes-cg"}:
            _issue(
                issues,
                "error",
                "scene-group-outside-view",
                f"Scene group {group_id!r} must be inside Scenes & CG.",
                group_id=group_id,
            )
        label = str(group.get("label", ""))
        if parser.scene_group_labels[group_id] != Counter({label: 1}):
            _issue(
                issues,
                "error",
                "scene-group-label-mismatch",
                f"Scene group {group_id!r} must bind its declared label.",
                group_id=group_id,
            )
        if parser.scene_group_heading_ids[group_id] != Counter({group_id: 1}):
            _issue(
                issues,
                "error",
                "scene-group-heading-link-invalid",
                f"Scene group {group_id!r} must expose one h2 with that exact id.",
                group_id=group_id,
            )
        group_text = _normalize(" ".join(parser.scene_group_text_parts[group_id]))
        if _normalize(label) not in group_text:
            _issue(
                issues,
                "error",
                "scene-group-label-not-visible",
                f"Scene group {group_id!r} does not visibly render its label.",
                group_id=group_id,
            )
        member_entries = [
            scene_entries[scene_id]
            for scene_id in group.get("entry_ids") or []
            if scene_id in scene_entries
        ]
        route_order = {claim_id: index for index, claim_id in enumerate(claims)}
        if member_entries:
            earliest = min(
                member_entries,
                key=lambda entry: (
                    route_order.get(str(entry.get("route_anchor_id", "")), -1),
                    0 if entry.get("route_anchor_position") == "before" else 1,
                ),
            )
            expected_group_anchor = str(earliest.get("route_anchor_id", ""))
            expected_group_position = str(earliest.get("route_anchor_position", ""))
            if (
                str(group.get("route_anchor_id", "")) != expected_group_anchor
                or str(group.get("route_anchor_position", "")) != expected_group_position
            ):
                _issue(
                    issues,
                    "error",
                    "scene-group-earliest-anchor-invalid",
                    f"Scene group {group_id!r} must use its earliest member's Main Route anchor.",
                    group_id=group_id,
                    expected_anchor=expected_group_anchor,
                    expected_position=expected_group_position,
                )
        anchor_id = str(group.get("route_anchor_id", ""))
        anchor_position = str(group.get("route_anchor_position", ""))
        href = f"#{group_id}"
        observed_claim_contexts = {
            row for row in parser.guide_link_claim_contexts.get(href, set()) if row is not None
        }
        if observed_claim_contexts != {anchor_id}:
            _issue(
                issues,
                "error",
                "scene-main-route-link-invalid",
                f"Scene group {group_id!r} must have a Main Route link from its declared anchor.",
                group_id=group_id,
                expected_anchor=anchor_id,
                observed=sorted(observed_claim_contexts),
            )
        if parser.guide_link_positions.get(href, Counter()) != Counter({anchor_position: 1}):
            _issue(
                issues,
                "error",
                "scene-main-route-link-position-invalid",
                f"Scene group {group_id!r} must render at its declared point relative to the Main Route step.",
                group_id=group_id,
                expected_position=anchor_position,
                observed=dict(parser.guide_link_positions.get(href, Counter())),
            )
        if parser.guide_link_dom_positions.get(href, Counter()) != Counter({anchor_position: 1}):
            _issue(
                issues,
                "error",
                "scene-main-route-link-order-invalid",
                f"Scene group {group_id!r} is not placed {anchor_position} its Main Route prose.",
                group_id=group_id,
                expected_position=anchor_position,
                observed=dict(parser.guide_link_dom_positions.get(href, Counter())),
            )
        if parser.guide_link_kinds_in_claims.get(href, Counter()) != Counter({"scene": 1}):
            _issue(
                issues,
                "error",
                "scene-group-main-route-link-kind-invalid",
                f"Scene group {group_id!r} must use the scene cross-tab link style.",
                group_id=group_id,
                observed=dict(parser.guide_link_kinds_in_claims.get(href, Counter())),
            )
        observed_group_backlinks = {
            row
            for row in parser.guide_link_scene_group_contexts.get(f"#{anchor_id}", set())
            if row is not None
        }
        expected_group_backlinks = {
            candidate_id
            for candidate_id, candidate in scene_groups.items()
            if str(candidate.get("route_anchor_id", "")) == anchor_id
        }
        if observed_group_backlinks != expected_group_backlinks:
            _issue(
                issues,
                "error",
                "scene-route-backlink-invalid",
                f"Scene groups bound to {anchor_id!r} must each link back to that Main Route context.",
                group_id=group_id,
                expected_anchor=anchor_id,
                expected_groups=sorted(expected_group_backlinks),
                observed=sorted(observed_group_backlinks),
            )

    declared_scene_ids = set(scene_entries)
    rendered_scene_ids = {
        scene_id for scene_id, count in parser.scene_entries.items() if scene_id and count
    }
    rendered_scene_task_ids = {
        task_id for task_id, count in parser.scene_tasks.items() if task_id and count
    }
    for task_id in sorted(rendered_scene_task_ids - declared_scene_ids):
        _issue(
            issues,
            "error",
            "rendered-scene-task-undeclared",
            f"Rendered scene checklist task {task_id!r} has no evidence entry.",
            scene_id=task_id,
        )
    for scene_id in sorted(declared_scene_ids | rendered_scene_ids):
        if scene_id not in declared_scene_ids:
            _issue(
                issues,
                "error",
                "rendered-scene-entry-undeclared",
                f"Rendered scene entry {scene_id!r} has no evidence entry.",
                scene_id=scene_id,
            )
            continue
        entry = scene_entries[scene_id]
        acquisition_mode = str(entry.get("acquisition_mode", ""))
        if parser.scene_entries[scene_id] != 1:
            _issue(
                issues,
                "error",
                "scene-entry-binding-invalid",
                f"Scene entry {scene_id!r} must render exactly once.",
                scene_id=scene_id,
            )
        if parser.scene_entry_views.get(scene_id, set()) != {"scenes-cg"}:
            _issue(
                issues,
                "error",
                "scene-entry-outside-view",
                f"Scene entry {scene_id!r} must be inside Scenes & CG.",
                scene_id=scene_id,
            )
        anchor_id = str(entry.get("route_anchor_id", ""))
        anchor_position = str(entry.get("route_anchor_position", ""))
        href = f"#{scene_id}"
        observed_claim_contexts = {
            row for row in parser.guide_link_claim_contexts.get(href, set()) if row is not None
        }
        if observed_claim_contexts != {anchor_id}:
            _issue(
                issues,
                "error",
                "scene-entry-main-route-link-invalid",
                f"Scene entry {scene_id!r} must have a Main Route link from its declared availability anchor.",
                scene_id=scene_id,
                expected_anchor=anchor_id,
                observed=sorted(observed_claim_contexts),
            )
        if parser.guide_link_positions.get(href, Counter()) != Counter({anchor_position: 1}):
            _issue(
                issues,
                "error",
                "scene-entry-main-route-link-position-invalid",
                f"Scene entry {scene_id!r} must render at its declared point relative to the Main Route step.",
                scene_id=scene_id,
                expected_position=anchor_position,
                observed=dict(parser.guide_link_positions.get(href, Counter())),
            )
        if parser.guide_link_dom_positions.get(href, Counter()) != Counter({anchor_position: 1}):
            _issue(
                issues,
                "error",
                "scene-entry-main-route-link-order-invalid",
                f"Scene entry {scene_id!r} is not placed {anchor_position} its Main Route prose.",
                scene_id=scene_id,
                expected_position=anchor_position,
                observed=dict(parser.guide_link_dom_positions.get(href, Counter())),
            )
        if parser.guide_link_kinds_in_claims.get(href, Counter()) != Counter({"scene": 1}):
            _issue(
                issues,
                "error",
                "scene-entry-main-route-link-kind-invalid",
                f"Scene entry {scene_id!r} must use the scene cross-tab link style.",
                scene_id=scene_id,
                observed=dict(parser.guide_link_kinds_in_claims.get(href, Counter())),
            )
        expected_groups = {
            group_id
            for group_id, group in scene_groups.items()
            if scene_id in (group.get("entry_ids") or [])
        }
        if parser.scene_entry_group_contexts.get(scene_id, set()) != expected_groups:
            _issue(
                issues,
                "error",
                "scene-entry-group-context-invalid",
                f"Scene entry {scene_id!r} must be nested in its declared group.",
                scene_id=scene_id,
                expected=sorted(expected_groups),
                observed=sorted(row or "" for row in parser.scene_entry_group_contexts.get(scene_id, set())),
            )
        if parser.scene_entry_heading_ids[scene_id] != Counter({scene_id: 1}):
            _issue(
                issues,
                "error",
                "scene-entry-heading-link-invalid",
                f"Scene entry {scene_id!r} must expose one h3 with its exact id.",
                scene_id=scene_id,
            )
        catalog_title = str(entry.get("catalog_title", "")).strip()
        if parser.scene_entry_catalog_titles[scene_id] != Counter({catalog_title: 1}):
            _issue(
                issues,
                "error",
                "scene-catalog-title-binding-invalid",
                f"Scene entry {scene_id!r} must bind its exact catalog title on the article.",
                scene_id=scene_id,
                expected=catalog_title,
                observed=dict(parser.scene_entry_catalog_titles[scene_id]),
            )
        if parser.scene_entry_acquisition_modes[scene_id] != Counter({acquisition_mode: 1}):
            _issue(
                issues,
                "error",
                "scene-acquisition-mode-binding-invalid",
                f"Scene entry {scene_id!r} must bind its declared acquisition mode on the article.",
                scene_id=scene_id,
                expected=acquisition_mode,
                observed=dict(parser.scene_entry_acquisition_modes[scene_id]),
            )
        if parser.scene_acquisition_sections[scene_id] != Counter({acquisition_mode: 1}):
            _issue(
                issues,
                "error",
                "scene-acquisition-section-invalid",
                f"Scene entry {scene_id!r} must render one acquisition section for its declared mode.",
                scene_id=scene_id,
                expected=acquisition_mode,
                observed=dict(parser.scene_acquisition_sections[scene_id]),
            )
        if parser.scene_tasks[scene_id] != 1:
            _issue(
                issues,
                "error",
                "scene-task-binding-invalid",
                f"Scene entry {scene_id!r} must render one matching checklist task.",
                scene_id=scene_id,
            )
        if parser.scene_task_entry_contexts.get(scene_id, set()) != {scene_id}:
            _issue(
                issues,
                "error",
                "scene-task-context-invalid",
                f"Scene checklist task {scene_id!r} must be inside its matching entry.",
                scene_id=scene_id,
            )
        if parser.scene_task_views.get(scene_id, set()) != {"scenes-cg"}:
            _issue(
                issues,
                "error",
                "scene-task-outside-view",
                f"Scene checklist task {scene_id!r} must be inside Scenes & CG.",
                scene_id=scene_id,
            )
        if parser.evidence[scene_id] != 1:
            _issue(
                issues,
                "error",
                "scene-evidence-binding-invalid",
                f"Scene entry {scene_id!r} must have one matching Evidence disclosure.",
                scene_id=scene_id,
            )
        if parser.evidence_scene_contexts[scene_id] != {scene_id}:
            _issue(
                issues,
                "error",
                "scene-evidence-outside-entry",
                f"Evidence disclosure {scene_id!r} must be inside its matching scene entry.",
                scene_id=scene_id,
            )
        expected_status = str(entry.get("status", ""))
        if parser.evidence_statuses[scene_id] != Counter({expected_status: 1}):
            _issue(
                issues,
                "error",
                "scene-evidence-status-mismatch",
                f"Scene entry {scene_id!r} must render evidence status {expected_status!r} exactly once.",
                scene_id=scene_id,
            )
        expected_sources = Counter(
            str(source.get("id", ""))
            for source in entry.get("sources") or []
            if isinstance(source, dict)
        )
        if parser.evidence_sources[scene_id] != expected_sources:
            _issue(
                issues,
                "error",
                "scene-evidence-sources-mismatch",
                f"Scene entry {scene_id!r} does not render the same source IDs as evidence.json.",
                scene_id=scene_id,
                expected=dict(expected_sources),
                observed=dict(parser.evidence_sources[scene_id]),
            )
        entry_text = _normalize(" ".join(parser.scene_entry_text_parts[scene_id]))
        title = _normalize(str(entry.get("title", "")))
        if title and title not in entry_text:
            _issue(
                issues,
                "error",
                "scene-title-not-visible",
                f"Scene entry {scene_id!r} does not visibly render its title.",
                scene_id=scene_id,
            )
        normalized_catalog_title = _normalize(catalog_title)
        if normalized_catalog_title and normalized_catalog_title != title:
            catalog_label = _normalize(f"Recollection title: {catalog_title}")
            if catalog_label not in entry_text:
                _issue(
                    issues,
                    "error",
                    "scene-catalog-title-not-visible",
                    f"Scene entry {scene_id!r} must visibly render its differing catalog title beneath the guide title.",
                    scene_id=scene_id,
                )
        for phrase in entry.get("guide_phrases") or []:
            if _normalize(str(phrase)) not in entry_text:
                _issue(
                    issues,
                    "error",
                    "scene-guide-phrase-missing",
                    f"Scene entry {scene_id!r} is missing its guide phrase: {phrase!r}",
                    scene_id=scene_id,
                )
        completion_shortcut = str(scene_catalog.get("completion_shortcut", "")).strip()
        if (
            completion_shortcut
            and acquisition_mode == "normal-play"
            and _normalize(completion_shortcut) in entry_text
        ):
            _issue(
                issues,
                "error",
                "scene-completion-shortcut-repeated",
                f"Scene entry {scene_id!r} repeats the catalog-wide completion shortcut instead of leading with normal acquisition.",
                scene_id=scene_id,
            )
        cg_count = entry.get("cg_image_count")
        cg_label = "set" if cg_count == 1 else "sets"
        expected_cg_text = f"{cg_count} illustrated {cg_label}"
        if _normalize(expected_cg_text) not in entry_text:
            _issue(
                issues,
                "error",
                "scene-cg-count-not-visible",
                f"Scene entry {scene_id!r} does not visibly render its evidence-backed illustrated-set count.",
                scene_id=scene_id,
            )
        for source in entry.get("sources") or []:
            if not isinstance(source, dict):
                continue
            supports = _normalize(str(source.get("supports", "")))
            source_id = str(source.get("id", ""))
            source_text = _normalize(" ".join(parser.source_text_parts[scene_id][source_id]))
            if supports and supports not in source_text:
                _issue(
                    issues,
                    "error",
                    "scene-evidence-explanation-missing",
                    f"Evidence source {source_id!r} in scene entry {scene_id!r} does not show what it proves.",
                    scene_id=scene_id,
                    source_id=source_id,
                )

    for href in parser.guide_links:
        if not href.startswith("#") or len(href) == 1:
            _issue(
                issues,
                "error",
                "guide-cross-link-invalid",
                f"Cross-view link {href!r} must use a nonempty in-document hash.",
                href=href,
            )
            continue
        destination = href[1:]
        if parser.ids[destination] != 1:
            _issue(
                issues,
                "error",
                "guide-cross-link-missing",
                f"Cross-view link {href!r} does not resolve to one unique destination.",
                href=href,
            )
        elif parser.id_views.get(destination) in PLACEHOLDER_VIEWS:
            _issue(
                issues,
                "error",
                "guide-cross-link-to-placeholder",
                f"Cross-view link {href!r} targets an unfinished placeholder view.",
                href=href,
            )

    css_or_network_references = re.findall(
        r"(?i)(?:@import\s+[^;]+|url\(\s*['\"]?(?:https?:)?//[^)]+|\b(?:fetch|importScripts)\s*\(\s*['\"](?:https?:)?//[^'\"]+)",
        raw_html,
    )
    references = parser.external_references + css_or_network_references
    if references:
        _issue(
            issues,
            "error",
            "external-resource-reference",
            f"Published HTML must be self-contained; found external/local resource {references[0]!r}.",
            references=references,
        )

    public_text = " ".join(parser.public_text_parts)
    _validate_player_copy(public_text, "Published HTML", issues)
    _validate_glossary_names(public_text, "Published HTML", glossary_names, issues)
    _validate_glossary_pronouns(public_text, "Published HTML", gender_facts, issues)
    return {
        "checked": True,
        "views": dict(parser.views),
        "tabs": dict(parser.tabs),
        "route_steps": dict(parser.route_steps),
        "route_chapters": dict(parser.route_chapters),
        "route_sections": dict(parser.route_sections),
        "route_tasks": dict(parser.route_tasks),
        "optional_groups": dict(parser.optional_groups),
        "optional_entries": dict(parser.optional_entries),
        "optional_tasks": dict(parser.optional_tasks),
        "boss_groups": dict(parser.boss_groups),
        "boss_entries": dict(parser.boss_entries),
        "boss_tasks": dict(parser.boss_tasks),
        "scene_groups": dict(parser.scene_groups),
        "scene_entries": dict(parser.scene_entries),
        "scene_tasks": dict(parser.scene_tasks),
        "evidence_disclosures": dict(parser.evidence),
        "guide_links": parser.guide_links,
    }


def validate_project(
    game_root: Path,
    walkthrough_path: Path,
    evidence_path: Path,
    html_path: Path | None,
) -> dict[str, Any]:
    """Return a deterministic machine-readable validation report."""
    game_root = game_root.resolve()
    walkthrough_path = walkthrough_path.resolve()
    evidence_path = evidence_path.resolve()
    if not game_root.is_dir():
        raise ValidationInputError(f"Game root does not exist: {game_root}")
    if not walkthrough_path.is_file():
        raise ValidationInputError(f"Walkthrough source does not exist: {walkthrough_path}")
    if not evidence_path.is_file():
        raise ValidationInputError(f"Evidence ledger does not exist: {evidence_path}")
    try:
        markdown = walkthrough_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationInputError(f"Could not read walkthrough source {walkthrough_path}: {exc}") from exc
    evidence = _read_json(evidence_path)
    if not isinstance(evidence, dict):
        raise ValidationInputError("Evidence must be a JSON object.")
    if evidence.get("schema_version") != SCHEMA_VERSION:
        raise ValidationInputError(f"Evidence schema_version must be {SCHEMA_VERSION}.")

    issues: list[dict[str, Any]] = []
    if evidence.get("milestone") != MILESTONE:
        _issue(
            issues,
            "error",
            "evidence-milestone-invalid",
            f"Evidence milestone must be {MILESTONE!r}.",
        )
    project_context, glossary_names, gender_facts = _validate_project_context(game_root, evidence, issues)
    _validate_player_copy(markdown, "WALKTHROUGH.md", issues)
    _validate_glossary_names(markdown, "WALKTHROUGH.md", glossary_names, issues)
    _validate_glossary_pronouns(markdown, "WALKTHROUGH.md", gender_facts, issues)
    claims, claim_results, all_source_ids = _validate_route_claims(game_root, markdown, evidence, issues)
    chapters, sections, route_structure = _validate_route_structure(
        game_root,
        markdown,
        evidence,
        claims,
        all_source_ids,
        issues,
    )
    optional_groups, optional_entries, optional_content = _validate_optional_content(
        game_root,
        markdown,
        evidence,
        claims,
        chapters,
        all_source_ids,
        issues,
    )
    boss_groups, boss_entries, bosses = _validate_bosses(
        game_root,
        markdown,
        evidence,
        claims,
        optional_entries,
        all_source_ids,
        issues,
    )
    scene_groups, scene_entries, scene_catalog, scenes_cg = _validate_scenes_cg(
        game_root,
        markdown,
        evidence,
        claims,
        optional_entries,
        boss_entries,
        all_source_ids,
        issues,
    )
    system_reconnaissance = _validate_system_reconnaissance(
        evidence_path,
        evidence,
        set(claims) | set(optional_entries) | set(boss_entries) | set(scene_entries) | {"scenes-cg-system"},
        all_source_ids,
        issues,
    )
    dependency_closure = _validate_dependency_closure(
        game_root,
        evidence_path,
        evidence,
        set(claims) | set(optional_entries) | set(boss_entries) | set(scene_entries) | {"scenes-cg-system"},
        {
            entry_id
            for entry_id, entry in optional_entries.items()
            if entry.get("kind") == "companion-recruitment"
        },
        all_source_ids,
        issues,
    )
    publication = _validate_publication(
        html_path,
        claims,
        chapters,
        sections,
        optional_groups,
        optional_entries,
        boss_groups,
        boss_entries,
        scene_groups,
        scene_entries,
        scene_catalog,
        glossary_names,
        gender_facts,
        issues,
    )

    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    counts = Counter(result["status"] for result in claim_results)
    optional_counts = Counter(result["status"] for result in optional_content["entries"])
    boss_counts = Counter(result["status"] for result in bosses["entries"])
    scene_counts = Counter(result["status"] for result in scenes_cg["entries"])
    status = "failed" if errors else "passed"
    return {
        "schema_version": SCHEMA_VERSION,
        "milestone": MILESTONE,
        "status": status,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "route_claims": len(claim_results),
            "verified": counts["verified"],
            "contradicted": counts["contradicted"],
            "optional_entries": len(optional_content["entries"]),
            "optional_verified": optional_counts["verified"],
            "optional_contradicted": optional_counts["contradicted"],
            "boss_entries": len(bosses["entries"]),
            "boss_verified": boss_counts["verified"],
            "boss_contradicted": boss_counts["contradicted"],
            "scene_entries": len(scenes_cg["entries"]),
            "scene_verified": scene_counts["verified"],
            "scene_contradicted": scene_counts["contradicted"],
            "scene_cg_images": scene_catalog.get("cg_image_count", 0),
        },
        "issues": issues,
        "route_claims": claim_results,
        "route_structure": route_structure,
        "optional_content": optional_content,
        "bosses": bosses,
        "scenes_cg": scenes_cg,
        "system_reconnaissance": system_reconnaissance,
        "dependency_closure": dependency_closure,
        "project_context": project_context,
        "publication": publication,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--walkthrough", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    game_root = args.game_root.resolve()
    work = game_root / ".dazedtl" / "walkthrough"
    walkthrough = args.walkthrough or (work / "WALKTHROUGH.md")
    evidence = args.evidence or (work / "evidence.json")
    html_path = args.html or (game_root / "WALKTHROUGH.html")
    report_path = args.report or (work / "validation-report.json")
    try:
        report = validate_project(game_root, walkthrough, evidence, html_path)
    except ValidationInputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary = report["summary"]
    print(
        f"{report['status'].upper()}: {summary['errors']} errors, {summary['warnings']} warnings; "
        f"route claims {summary['verified']} verified, {summary['contradicted']} contradicted; "
        f"optional entries {summary['optional_verified']} verified, "
        f"{summary['optional_contradicted']} contradicted; "
        f"boss entries {summary['boss_verified']} verified, "
        f"{summary['boss_contradicted']} contradicted; "
        f"scene entries {summary['scene_verified']} verified, "
        f"{summary['scene_contradicted']} contradicted across "
        f"{summary['scene_cg_images']} illustrated sets"
    )
    print(f"Report: {report_path}")
    for issue in report["issues"]:
        print(f"- {issue['severity'].upper()} {issue['code']}: {issue['message']}")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
