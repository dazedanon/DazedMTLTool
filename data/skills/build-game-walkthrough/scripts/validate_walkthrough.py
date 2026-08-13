#!/usr/bin/env python3
"""Validate RPG Maker walkthrough names and branch-dependent reward claims."""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
DATABASE_FILES = {
    "Actors.json": "actor",
    "Armors.json": "armor",
    "Classes.json": "class",
    "Enemies.json": "enemy",
    "Items.json": "item",
    "MapInfos.json": "map",
    "Skills.json": "skill",
    "States.json": "state",
    "Troops.json": "troop",
    "Weapons.json": "weapon",
}
REWARD_COMMANDS = {126: "item", 127: "weapon", 128: "armor"}
BADGE_RE = re.compile(r"`\[(?P<badge>[A-Z]{1,3}\d{1,3})\]`")
BADGE_PAIR_RE = re.compile(
    r"\*\*(?P<name>[^*]+?)\*\*\s*`\[(?P<badge>[A-Z]{1,3}\d{1,3})\]`",
    re.DOTALL,
)
CHOICE_CALLOUT_RE = re.compile(r"\*\*Choice Ahead(?:\s+[—-]\s+(?P<name>[^:*\n]+))?:\*\*")
INTERNAL_ID_PATTERNS = (
    re.compile(r"\bMap\d{3,}\b", re.IGNORECASE),
    re.compile(
        r"\b(?:map|event|common event|switch|variable|troop)\s+"
        r"(?:ID\s*)?#?\d+\b",
        re.IGNORECASE,
    ),
)
COVERAGE_STATUSES = {
    "verified",
    "contradicted",
    "unresolved",
    "unsupported",
    "not_applicable",
}


class ValidationInputError(ValueError):
    """Raised when the project or evidence manifest cannot be analyzed."""


@dataclass
class Analysis:
    data_dir: Path
    names_by_kind: dict[str, dict[int, str]]
    source_strings: set[str]
    conditional_branches: list[dict[str, Any]] = field(default_factory=list)
    rewards: list[dict[str, Any]] = field(default_factory=list)
    switch_writes: list[dict[str, Any]] = field(default_factory=list)
    battles: list[dict[str, Any]] = field(default_factory=list)
    choice_branches: list[dict[str, Any]] = field(default_factory=list)
    common_event_calls: list[dict[str, Any]] = field(default_factory=list)
    transfers: list[dict[str, Any]] = field(default_factory=list)
    plugin_commands: list[dict[str, Any]] = field(default_factory=list)
    script_commands: list[dict[str, Any]] = field(default_factory=list)
    event_terminations: list[dict[str, Any]] = field(default_factory=list)
    achievements: dict[str, dict[str, Any]] = field(default_factory=dict)
    achievement_awards: list[dict[str, Any]] = field(default_factory=list)
    troop_enemy_names: dict[int, list[str]] = field(default_factory=dict)
    common_event_names: dict[int, str] = field(default_factory=dict)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValidationInputError(f"Could not read JSON data from {path}: {exc}") from exc


def _find_data_dir(game_root: Path) -> Path:
    for candidate in (game_root / "data", game_root / "www" / "data"):
        if (candidate / "System.json").is_file() or (candidate / "Items.json").is_file():
            return candidate
    raise ValidationInputError(f"Could not find RPG Maker JSON data under {game_root / 'data'} or {game_root / 'www' / 'data'}")


def _all_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
    elif isinstance(value, list):
        for item in value:
            yield from _all_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _all_strings(item)


def _decode_json_values(value: Any, depth: int = 0) -> Iterable[Any]:
    """Yield plugin parameter values, including recursively encoded JSON strings."""
    yield value
    if depth >= 5:
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped[:1] not in {"[", "{"}:
            return
        try:
            decoded = json.loads(stripped)
        except json.JSONDecodeError:
            return
        yield from _decode_json_values(decoded, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _decode_json_values(item, depth + 1)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _decode_json_values(item, depth + 1)


def _read_plugins_config(game_root: Path) -> tuple[str, list[dict[str, Any]]]:
    path = game_root / "js" / "plugins.js"
    if not path.is_file():
        return "", []
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValidationInputError(f"Could not read RPG Maker plugin configuration {path}: {exc}") from exc
    marker = text.find("var $plugins")
    start = text.find("[", marker if marker >= 0 else 0)
    end = text.rfind("]")
    if start < 0 or end < start:
        return text, []
    try:
        decoded = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return text, []
    return text, [row for row in decoded if isinstance(row, dict)]


def _achievement_definitions(plugins: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    definitions: dict[str, dict[str, Any]] = {}
    for plugin in plugins:
        plugin_name = str(plugin.get("name", ""))
        description = str(plugin.get("description", ""))
        parameters = plugin.get("parameters") or {}
        plugin_context = f"{plugin_name} {description} {' '.join(map(str, parameters))}"
        if "achievement" not in plugin_context.casefold() and "実績" not in plugin_context:
            continue
        for candidate in _decode_json_values(parameters):
            if not isinstance(candidate, dict):
                continue
            lowered = {str(key).casefold(): value for key, value in candidate.items()}
            key = lowered.get("key")
            title = lowered.get("title") or lowered.get("name")
            if key is None or title is None:
                continue
            key_text = str(key).strip()
            title_text = str(title).strip()
            if not key_text or not title_text:
                continue
            definitions[key_text] = {
                "key": key_text,
                "title": title_text,
                "description": str(lowered.get("description", "")).strip(),
                "plugin": plugin_name,
            }
    return definitions


def _normalize_name(value: str) -> str:
    value = re.sub(r"\s*\n\s*>\s*", " ", value)
    return " ".join(value.split()).strip()


def _page_conditions(page: dict[str, Any]) -> list[dict[str, Any]]:
    raw = page.get("conditions") or {}
    conditions: list[dict[str, Any]] = []
    for suffix in ("1", "2"):
        if raw.get(f"switch{suffix}Valid"):
            conditions.append(
                {
                    "kind": "switch",
                    "id": int(raw.get(f"switch{suffix}Id", 0)),
                    "value": True,
                    "origin": "page",
                }
            )
    if raw.get("variableValid"):
        conditions.append(
            {
                "kind": "variable",
                "id": int(raw.get("variableId", 0)),
                "operator": ">=",
                "value": raw.get("variableValue", 0),
                "origin": "page",
            }
        )
    if raw.get("selfSwitchValid"):
        conditions.append(
            {
                "kind": "self_switch",
                "id": raw.get("selfSwitchCh", "A"),
                "value": True,
                "origin": "page",
            }
        )
    if raw.get("itemValid"):
        conditions.append({"kind": "has_item", "id": int(raw.get("itemId", 0)), "origin": "page"})
    if raw.get("actorValid"):
        conditions.append({"kind": "actor", "id": int(raw.get("actorId", 0)), "origin": "page"})
    return conditions


def _conditional_branch(parameters: list[Any]) -> dict[str, Any]:
    if not parameters:
        return {"kind": "unknown", "raw": parameters, "value": True}
    kind = parameters[0]
    if kind == 0 and len(parameters) >= 3:
        return {
            "kind": "switch",
            "id": int(parameters[1]),
            "value": parameters[2] == 0,
            "origin": "conditional",
        }
    if kind == 1 and len(parameters) >= 5:
        operators = {0: "==", 1: ">=", 2: "<=", 3: ">", 4: "<", 5: "!="}
        return {
            "kind": "variable",
            "id": int(parameters[1]),
            "operand": {"type": parameters[2], "value": parameters[3]},
            "operator": operators.get(parameters[4], f"operator-{parameters[4]}"),
            "value": True,
            "origin": "conditional",
        }
    return {
        "kind": f"rpgmaker-condition-{kind}",
        "raw": parameters[1:],
        "value": True,
        "origin": "conditional",
    }


def _negate(condition: dict[str, Any]) -> dict[str, Any]:
    result = dict(condition)
    result["value"] = not bool(result.get("value", True))
    result["negated"] = not bool(result.get("negated", False))
    return result


def _locator(
    relative_file: str,
    event_id: int,
    event_name: str,
    page_index: int,
    command_index: int,
    conditions: list[dict[str, Any]],
    choices: list[str],
) -> dict[str, Any]:
    return {
        "file": relative_file,
        "event_id": event_id,
        "event_name": event_name,
        "page_index": page_index,
        "command_index": command_index,
        "conditions": conditions,
        "choices": choices,
    }


def _event_node(record: dict[str, Any]) -> str:
    return f"{record.get('file')}#event={record.get('event_id')}&page={record.get('page_index')}"


def _achievement_keys_in_command(parameters: list[Any], definitions: dict[str, dict[str, Any]]) -> list[str]:
    if len(parameters) < 2:
        return []
    plugin_name = str(parameters[0])
    command_name = str(parameters[1])
    context = f"{plugin_name} {command_name}".casefold()
    if "achievement" not in context and "実績" not in context:
        return []
    if not any(word in command_name.casefold() for word in ("gain", "unlock", "earn", "award", "獲得")):
        return []
    raw_arguments = parameters[3] if len(parameters) > 3 else {}
    values = {str(value).strip() for value in _all_strings(raw_arguments)}
    if isinstance(raw_arguments, dict):
        values.update(str(value).strip() for value in raw_arguments.values())
    return sorted(key for key in definitions if key in values)


def _analyze_command_list(
    analysis: Analysis,
    relative_file: str,
    event_id: int,
    event_name: str,
    page_index: int,
    page: dict[str, Any],
) -> None:
    conditions_by_indent: dict[int, dict[str, Any]] = {}
    choices_by_indent: dict[int, str] = {}
    choice_options_by_indent: dict[int, list[str]] = {}
    base_conditions = _page_conditions(page)
    commands = page.get("list") or []

    for command_index, command in enumerate(commands):
        if not isinstance(command, dict):
            continue
        code = int(command.get("code", 0))
        indent = int(command.get("indent", 0))
        parameters = command.get("parameters") or []

        if code == 111:
            condition = _conditional_branch(parameters)
            conditions_by_indent[indent] = condition
            analysis.conditional_branches.append(
                {
                    **_locator(
                        relative_file,
                        event_id,
                        event_name,
                        page_index,
                        command_index,
                        base_conditions + [conditions_by_indent[key] for key in sorted(conditions_by_indent)],
                        [choices_by_indent[key] for key in sorted(choices_by_indent)],
                    ),
                    "condition": condition,
                }
            )
            continue
        if code == 411:
            if indent in conditions_by_indent:
                conditions_by_indent[indent] = _negate(conditions_by_indent[indent])
            continue
        if code == 412:
            conditions_by_indent.pop(indent, None)
            continue
        if code == 102:
            raw_options = parameters[0] if parameters else []
            choice_options_by_indent[indent] = [str(value) for value in raw_options]
            continue
        if code == 402:
            option_index = int(parameters[0]) if parameters else -1
            options = choice_options_by_indent.get(indent, [])
            label = options[option_index] if 0 <= option_index < len(options) else str(parameters[1] if len(parameters) > 1 else option_index)
            choices_by_indent[indent] = label
            analysis.choice_branches.append(
                _locator(
                    relative_file,
                    event_id,
                    event_name,
                    page_index,
                    command_index,
                    base_conditions + [conditions_by_indent[key] for key in sorted(conditions_by_indent)],
                    [choices_by_indent[key] for key in sorted(choices_by_indent)],
                )
            )
            continue
        if code == 403:
            choices_by_indent[indent] = "<cancel>"
            continue
        if code == 404:
            choices_by_indent.pop(indent, None)
            choice_options_by_indent.pop(indent, None)
            continue

        active_conditions = base_conditions + [conditions_by_indent[key] for key in sorted(conditions_by_indent)]
        active_choices = [choices_by_indent[key] for key in sorted(choices_by_indent)]
        source = _locator(
            relative_file,
            event_id,
            event_name,
            page_index,
            command_index,
            active_conditions,
            active_choices,
        )

        if code == 121 and len(parameters) >= 3:
            start_id, end_id, raw_value = map(int, parameters[:3])
            for switch_id in range(start_id, end_id + 1):
                analysis.switch_writes.append({**source, "switch_id": switch_id, "value": raw_value == 0})
        elif code in REWARD_COMMANDS and len(parameters) >= 4:
            entity_kind = REWARD_COMMANDS[code]
            entity_id = int(parameters[0])
            operation = "increase" if int(parameters[1]) == 0 else "decrease"
            operand_type = "constant" if int(parameters[2]) == 0 else "variable"
            operand = int(parameters[3])
            name = analysis.names_by_kind.get(entity_kind, {}).get(entity_id, "")
            analysis.rewards.append(
                {
                    **source,
                    "kind": entity_kind,
                    "id": entity_id,
                    "name": name,
                    "operation": operation,
                    "quantity": {"type": operand_type, "value": operand},
                }
            )
        elif code == 301 and parameters:
            troop_id = int(parameters[1]) if len(parameters) > 1 and parameters[0] == 0 else 0
            analysis.battles.append(
                {
                    **source,
                    "troop_id": troop_id,
                    "name": analysis.names_by_kind.get("troop", {}).get(troop_id, ""),
                    "enemy_names": analysis.troop_enemy_names.get(troop_id, []),
                    "direct": bool(troop_id),
                }
            )
        elif code == 117 and parameters:
            analysis.common_event_calls.append({**source, "common_event_id": int(parameters[0])})
        elif code == 201 and len(parameters) >= 2:
            direct = int(parameters[0]) == 0
            analysis.transfers.append(
                {
                    **source,
                    "direct": direct,
                    "map_id": int(parameters[1]) if direct else None,
                    "map_variable_id": int(parameters[1]) if not direct else None,
                    "x": int(parameters[2]) if direct and len(parameters) > 2 else None,
                    "y": int(parameters[3]) if direct and len(parameters) > 3 else None,
                }
            )
        elif code == 357:
            row = {**source, "parameters": parameters}
            analysis.plugin_commands.append(row)
            for key in _achievement_keys_in_command(parameters, analysis.achievements):
                analysis.achievement_awards.append({**row, "key": key})
        elif code in {355, 655}:
            analysis.script_commands.append({**source, "text": str(parameters[0]) if parameters else ""})
        elif code == 115:
            analysis.event_terminations.append(source)


def analyze_project(game_root: Path) -> Analysis:
    """Build canonical names plus branch-aware switch, reward, and battle indexes."""
    data_dir = _find_data_dir(game_root)
    names_by_kind: dict[str, dict[int, str]] = {}
    source_strings: set[str] = set()

    for filename, kind in DATABASE_FILES.items():
        path = data_dir / filename
        if not path.is_file():
            names_by_kind[kind] = {}
            continue
        data = _read_json(path)
        names_by_kind[kind] = {
            index: str(row.get("name", "")).strip()
            for index, row in enumerate(data if isinstance(data, list) else [])
            if isinstance(row, dict) and str(row.get("name", "")).strip()
        }
        source_strings.update(_all_strings(data))

    system_path = data_dir / "System.json"
    if system_path.is_file():
        system = _read_json(system_path)
        switches = system.get("switches", []) if isinstance(system, dict) else []
        names_by_kind["switch"] = {
            index: str(name).strip() for index, name in enumerate(switches if isinstance(switches, list) else []) if str(name).strip()
        }
        source_strings.update(_all_strings(system))
    else:
        names_by_kind["switch"] = {}

    plugin_text, plugins = _read_plugins_config(game_root)
    if plugin_text:
        source_strings.add(plugin_text)
    achievements = _achievement_definitions(plugins)
    troop_enemy_names: dict[int, list[str]] = {}
    troops_path = data_dir / "Troops.json"
    enemies = names_by_kind.get("enemy", {})
    if troops_path.is_file():
        troops = _read_json(troops_path)
        for troop_id, troop in enumerate(troops if isinstance(troops, list) else []):
            if not isinstance(troop, dict):
                continue
            troop_enemy_names[troop_id] = list(
                dict.fromkeys(
                    enemies.get(int(member.get("enemyId", 0)), "")
                    for member in troop.get("members") or []
                    if isinstance(member, dict) and enemies.get(int(member.get("enemyId", 0)), "")
                )
            )

    analysis = Analysis(
        data_dir,
        names_by_kind,
        source_strings,
        achievements=achievements,
        troop_enemy_names=troop_enemy_names,
    )
    event_paths = sorted(data_dir.glob("Map[0-9][0-9][0-9].json"))
    common_events_path = data_dir / "CommonEvents.json"
    if common_events_path.is_file():
        event_paths.append(common_events_path)

    for path in event_paths:
        data = _read_json(path)
        analysis.source_strings.update(_all_strings(data))
        relative_file = f"data/{path.name}"
        if path.name == "CommonEvents.json":
            rows = data if isinstance(data, list) else []
            for event_id, event in enumerate(rows):
                if not isinstance(event, dict) or not event.get("list"):
                    continue
                analysis.common_event_names[event_id] = str(event.get("name", ""))
                _analyze_command_list(
                    analysis,
                    relative_file,
                    event_id,
                    str(event.get("name", "")),
                    0,
                    {"conditions": {}, "list": event.get("list", [])},
                )
            continue

        events = data.get("events", []) if isinstance(data, dict) else []
        for event_id, event in enumerate(events):
            if not isinstance(event, dict):
                continue
            for page_index, page in enumerate(event.get("pages") or []):
                if isinstance(page, dict):
                    _analyze_command_list(
                        analysis,
                        relative_file,
                        event_id,
                        str(event.get("name", "")),
                        page_index,
                        page,
                    )
    return analysis


def _issue(
    issues: list[dict[str, Any]],
    severity: str,
    code: str,
    message: str,
    **details: Any,
) -> None:
    issues.append({"severity": severity, "code": code, "message": message, **details})


def _coverage(
    rows: list[dict[str, Any]],
    category: str,
    claim_id: str,
    status: str,
    message: str,
    **details: Any,
) -> None:
    if status not in COVERAGE_STATUSES:
        raise ValueError(f"Unknown coverage status: {status}")
    rows.append(
        {
            "category": category,
            "claim_id": claim_id,
            "status": status,
            "message": message,
            **details,
        }
    )


def _record_has_fight(record: dict[str, Any], fight: str) -> bool:
    return record.get("name") == fight or fight in (record.get("enemy_names") or [])


def _reachable_common_events(
    analysis: Analysis,
    source: dict[str, Any],
    choice_label: str,
) -> set[int]:
    initial_calls = [
        int(row["common_event_id"])
        for row in analysis.common_event_calls
        if _source_matches(row, source) and choice_label in (row.get("choices") or [])
    ]
    visited: set[int] = set()
    queue = deque(initial_calls)
    while queue:
        common_event_id = queue.popleft()
        if common_event_id in visited:
            continue
        visited.add(common_event_id)
        for row in analysis.common_event_calls:
            if row.get("file") == "data/CommonEvents.json" and row.get("event_id") == common_event_id:
                queue.append(int(row["common_event_id"]))
    return visited


def _branch_battles(
    analysis: Analysis,
    source: dict[str, Any],
    choice_label: str,
) -> list[dict[str, Any]]:
    direct = [row for row in analysis.battles if _source_matches(row, source) and choice_label in (row.get("choices") or [])]
    reachable = _reachable_common_events(analysis, source, choice_label)
    nested = [row for row in analysis.battles if row.get("file") == "data/CommonEvents.json" and int(row.get("event_id", -1)) in reachable]
    return direct + nested


def _name_occurs_in_source(name: str, source_strings: set[str]) -> bool:
    folded = name.casefold()
    return any(folded in value.casefold() for value in source_strings)


def validate_walkthrough_text(
    text: str,
    analysis: Analysis,
    evidence: dict[str, Any] | None,
    issues: list[dict[str, Any]],
) -> dict[str, str]:
    """Validate badge presentation, canonical spelling, and leaked developer IDs."""
    pair_by_span: dict[tuple[int, int], tuple[str, str]] = {}
    badge_names: dict[str, set[str]] = defaultdict(set)
    for match in BADGE_PAIR_RE.finditer(text):
        name = _normalize_name(match.group("name"))
        badge = match.group("badge")
        badge_span = match.span("badge")
        pair_by_span[badge_span] = (badge, name)
        badge_names[badge].add(name)
        if not _name_occurs_in_source(name, analysis.source_strings):
            _issue(
                issues,
                "error",
                "badge-name-not-in-game-data",
                f"{badge} uses {name!r}, which was not found in RPG Maker data.",
                badge=badge,
                name=name,
            )

    for match in BADGE_RE.finditer(text):
        badge_span = match.span("badge")
        if badge_span not in pair_by_span:
            _issue(
                issues,
                "error",
                "badge-without-full-name",
                f"{match.group('badge')} is not immediately preceded by a bold full name.",
                badge=match.group("badge"),
            )

    resolved_badges: dict[str, str] = {}
    for badge, names in sorted(badge_names.items()):
        if len(names) > 1:
            _issue(
                issues,
                "error",
                "badge-name-contradiction",
                f"{badge} is paired with multiple names: {', '.join(sorted(names))}.",
                badge=badge,
                names=sorted(names),
            )
        else:
            resolved_badges[badge] = next(iter(names))

    expected_badges = (evidence or {}).get("badges") or {}
    for badge, raw_expected in expected_badges.items():
        expected = raw_expected.get("name", "") if isinstance(raw_expected, dict) else raw_expected
        expected = _normalize_name(str(expected))
        actual = resolved_badges.get(str(badge))
        if actual is None:
            _issue(
                issues,
                "error",
                "expected-badge-missing",
                f"Evidence defines {badge} as {expected!r}, but the badge is absent.",
                badge=badge,
                expected=expected,
            )
        elif actual != expected:
            _issue(
                issues,
                "error",
                "badge-name-mismatch",
                f"{badge} must be {expected!r}, not {actual!r}.",
                badge=badge,
                expected=expected,
                actual=actual,
            )

    scrubbed = BADGE_RE.sub("", text)
    for pattern in INTERNAL_ID_PATTERNS:
        for match in pattern.finditer(scrubbed):
            _issue(
                issues,
                "error",
                "player-facing-internal-id",
                f"Player-facing walkthrough contains developer locator {match.group(0)!r}.",
                value=match.group(0),
            )
    return resolved_badges


def _source_matches(record: dict[str, Any], source: dict[str, Any]) -> bool:
    for key in ("file", "event_id", "page_index"):
        if key in source and record.get(key) != source[key]:
            return False
    return True


def _switch_constraints(record: dict[str, Any]) -> tuple[dict[int, bool], bool]:
    constraints: dict[int, bool] = {}
    contradiction = False
    for condition in record.get("conditions") or []:
        if condition.get("kind") != "switch":
            continue
        switch_id = int(condition.get("id", 0))
        value = bool(condition.get("value"))
        if switch_id in constraints and constraints[switch_id] != value:
            contradiction = True
        constraints[switch_id] = value
    return constraints, contradiction


def _compatible(record: dict[str, Any], state: dict[int, bool]) -> bool:
    constraints, contradiction = _switch_constraints(record)
    return not contradiction and all(switch_id not in state or state[switch_id] == value for switch_id, value in constraints.items())


def _branch_state(branch: dict[str, Any]) -> dict[int, bool]:
    raw = (branch.get("state") or {}).get("switches") or {}
    try:
        return {int(key): bool(value) for key, value in raw.items()}
    except (TypeError, ValueError) as exc:
        raise ValidationInputError("Choice branch switch IDs must be integers.") from exc


def _validate_choice(
    choice: dict[str, Any],
    analysis: Analysis,
    issues: list[dict[str, Any]],
    prose: str,
) -> dict[str, Any]:
    name = str(choice.get("name", "")).strip()
    source = choice.get("source") or {}
    branches = choice.get("branches") or []
    reward_scope = [str(item) for item in choice.get("reward_scope") or []]
    shared_outcomes = [str(item) for item in choice.get("shared_outcomes") or []]
    initial_state = _branch_state({"state": choice.get("initial_state") or {}})
    result: dict[str, Any] = {"name": name, "branches": []}

    if not name or not isinstance(source, dict) or not branches:
        _issue(
            issues,
            "error",
            "invalid-choice-evidence",
            "Each choice needs a name, source, and at least one branch.",
            choice=name,
        )
        return result

    known_equipment = {entity_name for kind in ("item", "weapon", "armor") for entity_name in analysis.names_by_kind.get(kind, {}).values()}
    known_fights = set(analysis.names_by_kind.get("troop", {}).values()) | set(analysis.names_by_kind.get("enemy", {}).values())
    claimed_scope: set[str] = set()

    normalized_prose = _normalize_name(prose)
    for outcome in shared_outcomes:
        if _normalize_name(outcome) not in normalized_prose:
            _issue(
                issues,
                "error",
                "shared-outcome-missing-from-guide",
                f"{name}: shared outcome {outcome!r} is absent from the Choice Ahead callout.",
                choice=name,
                outcome=outcome,
            )

    for branch in branches:
        label = str(branch.get("label", "")).strip()
        state = _branch_state(branch)
        rewards = [str(item) for item in branch.get("rewards") or []]
        fights = [str(item) for item in branch.get("fights") or []]
        outcomes = [str(item) for item in branch.get("outcomes") or []]
        claimed_scope.update(rewards)

        branch_match = re.search(
            rf"(?m)^\s*>?\s*-\s+\*\*{re.escape(label)}:\*\*",
            prose,
        )
        branch_prose = ""
        if branch_match is None:
            _issue(
                issues,
                "error",
                "choice-branch-missing-from-guide",
                f"{name}: the Choice Ahead callout has no labeled {label!r} outcome.",
                choice=name,
                branch=label,
            )
        else:
            next_branch = re.search(
                r"(?m)^\s*>?\s*-\s+\*\*[^*]+:\*\*",
                prose[branch_match.end() :],
            )
            branch_end = branch_match.end() + next_branch.start() if next_branch is not None else len(prose)
            branch_prose = prose[branch_match.start() : branch_end]
        normalized_branch_prose = _normalize_name(branch_prose)
        for outcome in [*fights, *rewards, *outcomes]:
            if _normalize_name(outcome) not in normalized_branch_prose:
                _issue(
                    issues,
                    "error",
                    "branch-outcome-missing-from-guide",
                    f"{name}: {label!r} does not state {outcome!r} before the choice.",
                    choice=name,
                    branch=label,
                    outcome=outcome,
                )

        choice_rows = [row for row in analysis.choice_branches if _source_matches(row, source) and label in (row.get("choices") or [])]
        if not choice_rows:
            _issue(
                issues,
                "error",
                "choice-branch-not-found",
                f"{name}: branch {label!r} was not found at its declared source.",
                choice=name,
                branch=label,
                source=source,
            )

        branch_writes = [row for row in analysis.switch_writes if _source_matches(row, source) and label in (row.get("choices") or [])]
        for switch_id, expected in state.items():
            has_expected_write = any(row.get("switch_id") == switch_id and row.get("value") == expected for row in branch_writes)
            has_conflicting_write = any(row.get("switch_id") == switch_id and row.get("value") != expected for row in branch_writes)
            preserves_initial = initial_state.get(switch_id) == expected and not has_conflicting_write
            if not has_expected_write and not preserves_initial:
                _issue(
                    issues,
                    "error",
                    "choice-state-not-proven",
                    f"{name}: {label!r} does not set switch {switch_id} to {expected} at the declared source.",
                    choice=name,
                    branch=label,
                    switch_id=switch_id,
                    expected=expected,
                )

        for reward in rewards:
            if reward not in known_equipment:
                _issue(
                    issues,
                    "error",
                    "unknown-reward-name",
                    f"{name}: reward {reward!r} is not an exact database name.",
                    choice=name,
                    branch=label,
                    reward=reward,
                )
                continue
            compatible_rows = [
                row for row in analysis.rewards if row.get("operation") == "increase" and row.get("name") == reward and _compatible(row, state)
            ]
            if not compatible_rows:
                _issue(
                    issues,
                    "error",
                    "reward-branch-mismatch",
                    f"{name}: no acquisition of {reward!r} is compatible with {label!r}.",
                    choice=name,
                    branch=label,
                    reward=reward,
                )

        for fight in fights:
            if fight not in known_fights:
                _issue(
                    issues,
                    "error",
                    "unknown-fight-name",
                    f"{name}: fight {fight!r} is not an exact troop or enemy name.",
                    choice=name,
                    branch=label,
                    fight=fight,
                )
                continue
            direct_rows = [row for row in _branch_battles(analysis, source, label) if _record_has_fight(row, fight)]
            if not direct_rows:
                _issue(
                    issues,
                    "warning",
                    "fight-needs-manual-trace",
                    f"{name}: {fight!r} was not reached directly or through common events "
                    f"from {label!r}; trace transfers/state-gated events or confirm it in play.",
                    choice=name,
                    branch=label,
                    fight=fight,
                )

        observed_scope = sorted(
            reward
            for reward in reward_scope
            if any(row.get("operation") == "increase" and row.get("name") == reward and _compatible(row, state) for row in analysis.rewards)
        )
        if reward_scope and sorted(rewards) != observed_scope:
            _issue(
                issues,
                "error",
                "incomplete-branch-reward-list",
                f"{name}: {label!r} claims {sorted(rewards)!r}, but reverse indexing finds {observed_scope!r} within reward_scope.",
                choice=name,
                branch=label,
                claimed=sorted(rewards),
                observed=observed_scope,
            )
        result["branches"].append(
            {
                "label": label,
                "switch_state": {str(key): value for key, value in sorted(state.items())},
                "rewards": rewards,
                "fights": fights,
                "outcomes": outcomes,
                "observed_reward_scope": observed_scope,
            }
        )

    if claimed_scope and not reward_scope:
        _issue(
            issues,
            "error",
            "choice-reward-scope-missing",
            f"{name}: reward_scope is required so reverse validation can detect omissions.",
            choice=name,
        )
    missing_scope = claimed_scope - set(reward_scope)
    if missing_scope:
        _issue(
            issues,
            "error",
            "claimed-reward-outside-scope",
            f"{name}: claimed rewards missing from reward_scope: {sorted(missing_scope)!r}.",
            choice=name,
            rewards=sorted(missing_scope),
        )
    return result


def _badge_number(badge: str, prefix: str) -> int | None:
    if not badge.startswith(prefix):
        return None
    suffix = badge[len(prefix) :]
    return int(suffix) if suffix.isdigit() else None


def _validate_acquisitions(
    groups: list[dict[str, Any]],
    analysis: Analysis,
    badges: dict[str, str],
    issues: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    results: list[dict[str, Any]] = []
    authoritative_badges: dict[str, str] = {}
    if not groups:
        _coverage(
            coverage,
            "acquisition_totals",
            "acquisition-groups",
            "unresolved",
            "No acquisition groups were declared; collectible totals were not reconciled.",
        )
        return results, authoritative_badges

    for raw_group in groups:
        group = raw_group if isinstance(raw_group, dict) else {}
        name = str(group.get("name", "")).strip()
        kind = str(group.get("kind", "item")).strip()
        expected_total = group.get("expected_total")
        count_mode = str(group.get("count", "quantity"))
        claim_id = f"{kind}:{name}"
        group_errors = 0
        if not name or kind not in {"item", "weapon", "armor"} or not isinstance(expected_total, int):
            _issue(
                issues,
                "error",
                "invalid-acquisition-evidence",
                "Each acquisition group needs an exact name, item/weapon/armor kind, and integer expected_total.",
                acquisition=claim_id,
            )
            _coverage(
                coverage,
                "acquisition_totals",
                claim_id,
                "contradicted",
                "The acquisition evidence entry is invalid.",
            )
            continue
        if name not in analysis.names_by_kind.get(kind, {}).values():
            _issue(
                issues,
                "error",
                "unknown-acquisition-name",
                f"{name!r} is not an exact {kind} database name.",
                acquisition=claim_id,
            )
            group_errors += 1

        rows = [row for row in analysis.rewards if row.get("operation") == "increase" and row.get("kind") == kind and row.get("name") == name]
        constant_rows = [row for row in rows if row.get("quantity", {}).get("type") == "constant"]
        dynamic_rows = [row for row in rows if row not in constant_rows]
        observed = len(constant_rows) if count_mode == "commands" else sum(int(row["quantity"]["value"]) for row in constant_rows)
        if observed != expected_total:
            _issue(
                issues,
                "error",
                "acquisition-total-mismatch",
                f"{name!r} expects {expected_total}, but reverse indexing found {observed} by {count_mode}.",
                acquisition=claim_id,
                expected=expected_total,
                observed=observed,
            )
            group_errors += 1
        if dynamic_rows:
            _coverage(
                coverage,
                "acquisition_totals",
                f"{claim_id}:dynamic-quantity",
                "unresolved",
                f"{len(dynamic_rows)} variable-quantity acquisition commands require manual reconciliation.",
            )

        badge_spec = group.get("badges") or {}
        route_sources = group.get("sources") or []
        expected_badges: list[str] = []
        if badge_spec:
            prefix = str(badge_spec.get("prefix", ""))
            first = int(badge_spec.get("first", 1))
            last = int(badge_spec.get("last", expected_total))
            width = int(badge_spec.get("width", 0))
            expected_badges = [f"{prefix}{number:0{width}d}" if width else f"{prefix}{number}" for number in range(first, last + 1)]
            actual_badges = sorted(
                (badge for badge in badges if _badge_number(badge, prefix) is not None),
                key=lambda badge: _badge_number(badge, prefix) or 0,
            )
            if actual_badges != expected_badges:
                _issue(
                    issues,
                    "error",
                    "acquisition-badge-sequence-mismatch",
                    f"{name!r} badge sequence differs from {expected_badges[0] if expected_badges else prefix}"
                    f" through {expected_badges[-1] if expected_badges else prefix}.",
                    acquisition=claim_id,
                    expected=expected_badges,
                    observed=actual_badges,
                )
                group_errors += 1
            for badge in expected_badges:
                authoritative_badges[badge] = name
                if badges.get(badge) != name:
                    _issue(
                        issues,
                        "error",
                        "acquisition-badge-name-mismatch",
                        f"{badge} must identify {name!r}, not {badges.get(badge)!r}.",
                        acquisition=claim_id,
                        badge=badge,
                    )
                    group_errors += 1

        if route_sources:
            declared = {str(row.get("badge", "")): row for row in route_sources if isinstance(row, dict)}
            if set(declared) != set(expected_badges):
                _issue(
                    issues,
                    "error",
                    "acquisition-route-source-gap",
                    f"{name!r} route sources must cover every acquisition badge exactly once.",
                    acquisition=claim_id,
                )
                group_errors += 1
            for badge, source_row in declared.items():
                source = source_row.get("source") or {}
                matches = [row for row in rows if _source_matches(row, source)]
                if "command_index" in source:
                    matches = [row for row in matches if row.get("command_index") == source["command_index"]]
                if not matches:
                    _issue(
                        issues,
                        "error",
                        "acquisition-route-source-mismatch",
                        f"{badge} does not resolve to an acquisition of {name!r}.",
                        acquisition=claim_id,
                        badge=badge,
                        source=source,
                    )
                    group_errors += 1
            _coverage(
                coverage,
                "acquisition_route_order",
                claim_id,
                "contradicted" if group_errors else "verified",
                "Every numbered pickup is tied to an exact event command."
                if not group_errors
                else "One or more numbered pickup locators do not match the game data.",
            )
        elif expected_badges:
            _coverage(
                coverage,
                "acquisition_route_order",
                claim_id,
                "unresolved",
                "The total and badge sequence are proven, but individual badges are not tied to event commands.",
            )

        _coverage(
            coverage,
            "acquisition_totals",
            claim_id,
            "contradicted" if group_errors else "verified",
            f"Reverse-indexed {observed} of expected {expected_total} {name!r} acquisitions.",
            expected=expected_total,
            observed=observed,
            count=count_mode,
        )
        results.append(
            {
                "name": name,
                "kind": kind,
                "expected_total": expected_total,
                "observed_total": observed,
                "count": count_mode,
                "commands": rows,
                "badges": expected_badges,
            }
        )
    return results, authoritative_badges


def _validate_switch_sets(
    groups: list[dict[str, Any]],
    walkthrough: str,
    analysis: Analysis,
    issues: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate counted world objects represented by persistent switches."""
    results: list[dict[str, Any]] = []
    normalized_walkthrough = _normalize_name(walkthrough)
    switch_names = analysis.names_by_kind.get("switch", {})
    for raw_group in groups:
        group = raw_group if isinstance(raw_group, dict) else {}
        claim_id = str(group.get("id", "")).strip() or "<unnamed-switch-set>"
        expected_total = group.get("expected_total")
        switch_ids = group.get("switch_ids") or []
        phrases = [str(value) for value in group.get("guide_phrases") or []]
        failures: list[str] = []
        if not isinstance(expected_total, int) or expected_total != len(switch_ids):
            failures.append("switch count does not match expected_total")
        if any(not isinstance(value, int) for value in switch_ids) or len(set(switch_ids)) != len(switch_ids):
            failures.append("switch IDs must be distinct integers")
        for switch_id in switch_ids:
            if switch_id not in switch_names:
                failures.append(f"switch {switch_id} has no name in System.json")
                continue
            if not any(row.get("switch_id") == switch_id and row.get("value") is True for row in analysis.switch_writes):
                failures.append(f"switch {switch_id} is never turned on by native event data")
        for phrase in phrases:
            if _normalize_name(phrase) not in normalized_walkthrough:
                failures.append(f"guide phrase {phrase!r} is missing")
        if failures:
            _issue(
                issues,
                "error",
                "switch-set-mismatch",
                f"{claim_id}: {failures[0]}",
                switch_set=claim_id,
                failures=failures,
            )
        _coverage(
            coverage,
            "acquisition_totals",
            claim_id,
            "contradicted" if failures else "verified",
            f"Proved {len(switch_ids)} persistent pickup states through named switches and ON writes."
            if not failures
            else f"Could not prove the declared {expected_total}-state total.",
        )
        results.append(
            {
                "id": claim_id,
                "expected_total": expected_total,
                "switch_ids": switch_ids,
                "failures": failures,
            }
        )
    return results


def _validate_switch_achievements(
    groups: list[dict[str, Any]],
    walkthrough: str,
    analysis: Analysis,
    evidence: dict[str, Any],
    issues: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Validate event-based achievement catalogs keyed by ordinary switches."""
    results: list[dict[str, Any]] = []
    normalized_walkthrough = _normalize_name(walkthrough)
    switch_names = analysis.names_by_kind.get("switch", {})
    for raw_group in groups:
        group = raw_group if isinstance(raw_group, dict) else {}
        claim_id = str(group.get("id", "")).strip() or "<unnamed-achievement-set>"
        first = group.get("first_switch_id")
        last = group.get("last_switch_id")
        expected_total = group.get("expected_total")
        source = group.get("source") or {}
        phrases = [str(value) for value in group.get("guide_phrases") or []]
        failures: list[str] = []
        if not all(isinstance(value, int) for value in (first, last, expected_total)) or first > last:
            switch_ids: list[int] = []
            failures.append("first_switch_id, last_switch_id, and expected_total must define a valid integer range")
        else:
            switch_ids = list(range(first, last + 1))
            if len(switch_ids) != expected_total:
                failures.append("switch range does not match expected_total")
        observed: list[int] = []
        for switch_id in switch_ids:
            if switch_id not in switch_names:
                failures.append(f"achievement switch {switch_id} has no name in System.json")
            matched = any(
                _source_matches(row, source)
                and (row.get("condition") or {}).get("kind") == "switch"
                and (row.get("condition") or {}).get("id") == switch_id
                and (row.get("condition") or {}).get("value") is True
                for row in analysis.conditional_branches
            )
            if matched:
                observed.append(switch_id)
            else:
                failures.append(f"achievement switch {switch_id} is not checked at the declared award source")
        for phrase in phrases:
            if _normalize_name(phrase) not in normalized_walkthrough:
                failures.append(f"guide phrase {phrase!r} is missing")
        if failures:
            _issue(
                issues,
                "error",
                "achievement-switch-set-mismatch",
                f"{claim_id}: {failures[0]}",
                achievement_set=claim_id,
                failures=failures,
            )
        _coverage(
            coverage,
            "achievements",
            claim_id,
            "contradicted" if failures else "verified",
            f"Matched {len(observed)} point-bearing achievement switches at the award event."
            if not failures
            else f"Could not prove the declared {expected_total}-achievement catalog.",
        )
        results.append(
            {
                "id": claim_id,
                "expected_total": expected_total,
                "observed_total": len(observed),
                "source": source,
                "failures": failures,
            }
        )
    if groups:
        _coverage(
            coverage,
            "achievement_unlock_explanations",
            "achievement-guide-conditions",
            "verified" if evidence.get("achievement_unlocks_reviewed") is True else "unresolved",
            "The guide's unlock explanations were reviewed against the switch conditions."
            if evidence.get("achievement_unlocks_reviewed") is True
            else "Achievement switches are indexed, but guide conditions have not been marked as reviewed.",
        )
    return results


def _validate_achievements(
    analysis: Analysis,
    badges: dict[str, str],
    evidence: dict[str, Any],
    issues: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> None:
    if not analysis.achievements:
        if evidence.get("achievement_switch_sets"):
            return
        _coverage(
            coverage,
            "achievements",
            "achievement-system",
            "not_applicable",
            "No structured achievement definitions were found in plugin configuration.",
        )
        return
    for key, definition in sorted(analysis.achievements.items()):
        if re.fullmatch(r"[A-Z]{1,3}\d{1,3}", key) is None:
            continue
        title = definition["title"]
        actual = badges.get(key)
        awards = [row for row in analysis.achievement_awards if row.get("key") == key]
        if actual is None:
            _issue(
                issues,
                "error",
                "achievement-missing-from-guide",
                f"Achievement {title!r} [{key}] is defined by the game but absent from the walkthrough.",
                achievement=key,
            )
            status = "contradicted"
        elif actual != title:
            _issue(
                issues,
                "error",
                "achievement-title-mismatch",
                f"Achievement [{key}] must be {title!r}, not {actual!r}.",
                achievement=key,
            )
            status = "contradicted"
        elif not awards:
            status = "unresolved"
        else:
            status = "verified"
        _coverage(
            coverage,
            "achievements",
            key,
            status,
            f"Matched {title!r} to {len(awards)} award command(s).",
            title=title,
            awards=awards,
        )
    _coverage(
        coverage,
        "achievement_unlock_explanations",
        "achievement-guide-conditions",
        "verified" if evidence.get("achievement_unlocks_reviewed") is True else "unresolved",
        "The guide's unlock explanations were reviewed against indexed award conditions."
        if evidence.get("achievement_unlocks_reviewed") is True
        else "Award commands are indexed, but the guide's prose explanations have not been marked as reviewed.",
    )


def _validate_requirements(
    requirements: list[dict[str, Any]],
    walkthrough: str,
    analysis: Analysis,
    issues: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
    evidence_reviewed: bool = False,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    inverse_operators = {"==": "!=", "!=": "==", ">=": "<", "<=": ">", ">": "<=", "<": ">="}
    normalized_walkthrough = _normalize_name(walkthrough)
    for raw in requirements:
        requirement = raw if isinstance(raw, dict) else {}
        claim_id = str(requirement.get("id", "")).strip() or "<unnamed-requirement>"
        expected_total = requirement.get("expected_total")
        entries = [row for row in requirement.get("entries") or [] if isinstance(row, dict)]
        source = requirement.get("source") or {}
        phrases = [str(value) for value in requirement.get("guide_phrases") or []]
        failures: list[str] = []
        if not isinstance(expected_total, int) or expected_total != len(entries):
            failures.append("entry count does not match expected_total")
        variable_ids = [row.get("variable_id") for row in entries]
        if any(not isinstance(value, int) for value in variable_ids) or len(set(variable_ids)) != len(variable_ids):
            failures.append("variable IDs must be distinct integers")
        for phrase in phrases:
            if _normalize_name(phrase) not in normalized_walkthrough:
                failures.append(f"guide phrase {phrase!r} is missing")
        for entry in entries:
            name = str(entry.get("name", "")).strip()
            variable_id = entry.get("variable_id")
            operator = str(entry.get("operator", "=="))
            value = entry.get("value")
            if name and not _name_occurs_in_source(name, analysis.source_strings):
                failures.append(f"entry name {name!r} is absent from game data")
            inverse = inverse_operators.get(operator)
            blocked = False
            for termination in analysis.event_terminations:
                if not _source_matches(termination, source):
                    continue
                for condition in termination.get("conditions") or []:
                    operand = condition.get("operand") or {}
                    if (
                        condition.get("kind") == "variable"
                        and condition.get("id") == variable_id
                        and condition.get("operator") == inverse
                        and operand.get("type") == 0
                        and operand.get("value") == value
                    ):
                        blocked = True
                        break
                if blocked:
                    break
            if not blocked:
                failures.append(f"no early-exit guard proves variable {variable_id} must be {operator} {value}")
        if failures:
            _issue(
                issues,
                "error",
                "requirement-set-mismatch",
                f"{claim_id}: {failures[0]}",
                requirement=claim_id,
                failures=failures,
            )
        _coverage(
            coverage,
            "quantitative_requirements",
            claim_id,
            "contradicted" if failures else "verified",
            f"Proved {len(entries)} required entries through early-exit guards and guide wording."
            if not failures
            else f"Could not prove the declared {expected_total}-entry requirement.",
        )
        results.append(
            {
                "id": claim_id,
                "expected_total": expected_total,
                "entries": entries,
                "source": source,
                "failures": failures,
            }
        )
    if not requirements:
        _coverage(
            coverage,
            "quantitative_requirements",
            "requirement-sets",
            "not_applicable" if evidence_reviewed else "unresolved",
            "The guide was reviewed and contains no non-acquisition exact-count gates."
            if evidence_reviewed
            else "No non-acquisition all/only/exact-count requirement sets were declared.",
        )
    return results


def _validate_badge_coverage(
    badges: dict[str, str],
    evidence: dict[str, Any],
    analysis: Analysis,
    acquisition_badges: dict[str, str],
    coverage: list[dict[str, Any]],
) -> None:
    declared = evidence.get("badges") or {}
    declared_reviewed = evidence.get("badges_reviewed") is True
    for badge, name in sorted(badges.items()):
        expected = None
        authority = ""
        if badge in analysis.achievements:
            expected = analysis.achievements[badge]["title"]
            authority = "achievement definition"
        elif badge in acquisition_badges:
            expected = acquisition_badges[badge]
            authority = "acquisition group"
        elif badge in declared:
            raw = declared[badge]
            expected = raw.get("name", "") if isinstance(raw, dict) else raw
            expected = _normalize_name(str(expected))
            authority = "reviewed evidence manifest"
        if expected is None:
            _coverage(
                coverage,
                "badge_identity",
                badge,
                "unresolved",
                f"{badge} is consistently shown as {name!r}, but has no authoritative mapping.",
            )
        elif name == expected and (badge not in declared or declared_reviewed):
            _coverage(
                coverage,
                "badge_identity",
                badge,
                "verified",
                f"{badge} is authoritatively mapped to {name!r} by {authority}.",
            )
        elif name == expected:
            _coverage(
                coverage,
                "badge_identity",
                badge,
                "unresolved",
                f"{badge} matches the manifest as {name!r}, but badges_reviewed is not true.",
            )
        else:
            _coverage(
                coverage,
                "badge_identity",
                badge,
                "contradicted",
                f"{badge} is {name!r}, but {authority} requires {expected!r}.",
            )


def _html_visible_text(raw_html: str) -> str:
    without_blocks = re.sub(r"(?is)<(?:script|style)\b[^>]*>.*?</(?:script|style)>", " ", raw_html)
    return _normalize_name(html.unescape(re.sub(r"(?s)<[^>]+>", " ", without_blocks)))


def _validate_publication_parity(
    markdown: str,
    html_path: Path | None,
    badge_names: dict[str, str],
    issues: list[dict[str, Any]],
    coverage: list[dict[str, Any]],
) -> dict[str, Any]:
    if html_path is None or not html_path.is_file():
        _coverage(
            coverage,
            "publication_parity",
            "markdown-html",
            "unresolved",
            "Published WALKTHROUGH.html was not available for semantic comparison.",
        )
        return {"checked": False}
    try:
        visible = _html_visible_text(html_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValidationInputError(f"Could not read published walkthrough {html_path}: {exc}") from exc

    markdown_badges = Counter(match.group("badge") for match in BADGE_RE.finditer(markdown))
    html_badges = Counter(re.findall(r"\[([A-Z]{1,3}\d{1,3})\]", visible))
    mismatches: list[str] = []
    if markdown_badges != html_badges:
        mismatches.append("badge occurrence counts differ")
    for badge, name in badge_names.items():
        if _normalize_name(f"{name} [{badge}]") not in visible:
            mismatches.append(f"{name} [{badge}] is missing")
    headings = [
        _normalize_name(match.group(1))
        for match in re.finditer(r"(?m)^#{2,6}\s+(.+?)\s*$", markdown)
        if _normalize_name(match.group(1)) != "Contents"
    ]
    for heading in headings:
        if heading and heading not in visible:
            mismatches.append(f"heading {heading!r} is missing")
    if mismatches:
        _issue(
            issues,
            "error",
            "markdown-html-parity-mismatch",
            f"Published HTML is stale or incomplete: {mismatches[0]}"
            + (f" and {len(mismatches) - 1} more mismatch(es)." if len(mismatches) > 1 else "."),
            mismatches=mismatches,
        )
    _coverage(
        coverage,
        "publication_parity",
        "markdown-html",
        "contradicted" if mismatches else "verified",
        "Markdown and HTML have matching headings and named badge occurrences." if not mismatches else "Markdown and published HTML differ.",
    )
    return {
        "checked": True,
        "markdown_badges": dict(sorted(markdown_badges.items())),
        "html_badges": dict(sorted(html_badges.items())),
        "mismatches": mismatches,
    }


def _event_graph(analysis: Analysis, coverage: list[dict[str, Any]]) -> dict[str, Any]:
    call_edges = [
        {
            "from": _event_node(row),
            "to": f"data/CommonEvents.json#event={row['common_event_id']}&page=0",
            "to_name": analysis.common_event_names.get(int(row["common_event_id"]), ""),
        }
        for row in analysis.common_event_calls
    ]
    transfer_edges = [
        {
            "from": _event_node(row),
            "to_map_id": row.get("map_id"),
            "to_map_name": analysis.names_by_kind.get("map", {}).get(int(row["map_id"]), "") if row.get("map_id") is not None else "",
            "map_variable_id": row.get("map_variable_id"),
            "direct": row.get("direct"),
        }
        for row in analysis.transfers
    ]
    _coverage(
        coverage,
        "event_graph",
        "native-event-edges",
        "verified",
        f"Indexed {len(call_edges)} common-event calls and {len(transfer_edges)} transfers.",
    )
    _coverage(
        coverage,
        "scripted_event_semantics",
        "script-commands",
        "unsupported" if analysis.script_commands else "not_applicable",
        f"{len(analysis.script_commands)} script command(s) may contain behavior outside the native event analyzer."
        if analysis.script_commands
        else "No script commands require separate semantic analysis.",
    )
    return {
        "common_event_calls": call_edges,
        "transfers": transfer_edges,
        "plugin_commands": analysis.plugin_commands,
        "script_commands": analysis.script_commands,
    }


def validate_project(
    game_root: Path,
    walkthrough_path: Path,
    evidence_path: Path | None = None,
    html_path: Path | None = None,
) -> dict[str, Any]:
    """Return a deterministic machine-readable validation report."""
    game_root = game_root.resolve()
    walkthrough_path = walkthrough_path.resolve()
    if not walkthrough_path.is_file():
        raise ValidationInputError(f"Walkthrough source does not exist: {walkthrough_path}")
    analysis = analyze_project(game_root)
    text = walkthrough_path.read_text(encoding="utf-8")
    evidence: dict[str, Any] = {}
    if evidence_path is not None and evidence_path.is_file():
        loaded = _read_json(evidence_path)
        if not isinstance(loaded, dict) or loaded.get("schema_version") != SCHEMA_VERSION:
            raise ValidationInputError(f"Evidence must be an object with schema_version {SCHEMA_VERSION}.")
        evidence = loaded

    issues: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    badges = validate_walkthrough_text(text, analysis, evidence, issues)
    unnamed_callouts = [match for match in CHOICE_CALLOUT_RE.finditer(text) if not match.group("name")]
    for _match in unnamed_callouts:
        _issue(
            issues,
            "error",
            "unnamed-choice-callout",
            "Choice Ahead callouts must have a player-facing name after an em dash.",
        )
        _coverage(
            coverage,
            "choice_outcomes",
            f"unnamed-choice-{len([row for row in coverage if row['category'] == 'choice_outcomes']) + 1}",
            "contradicted",
            "An unnamed Choice Ahead callout cannot be matched to structured branch evidence.",
        )
    callout_names = {_normalize_name(match.group("name")) for match in CHOICE_CALLOUT_RE.finditer(text) if match.group("name")}
    evidence_choices = (evidence or {}).get("choices") or []
    evidence_names = {_normalize_name(str(choice.get("name", ""))) for choice in evidence_choices if isinstance(choice, dict)}
    for missing in sorted(callout_names - evidence_names):
        _issue(
            issues,
            "error",
            "choice-evidence-missing",
            f"Choice Ahead {missing!r} has no structured evidence entry.",
            choice=missing,
        )
        _coverage(
            coverage,
            "choice_outcomes",
            missing,
            "contradicted",
            "The named Choice Ahead callout has no structured branch evidence.",
        )

    choice_sections: dict[str, str] = {}
    for match in CHOICE_CALLOUT_RE.finditer(text):
        if not match.group("name"):
            continue
        heading = re.search(r"(?m)^#{1,6}\s+", text[match.end() :])
        end = match.end() + heading.start() if heading is not None else len(text)
        choice_sections[_normalize_name(match.group("name"))] = text[match.start() : end]

    choice_results: list[dict[str, Any]] = []
    for choice in evidence_choices:
        if not isinstance(choice, dict):
            continue
        choice_name = _normalize_name(str(choice.get("name", "")))
        issue_start = len(issues)
        result = _validate_choice(
            choice,
            analysis,
            issues,
            choice_sections.get(choice_name, ""),
        )
        choice_results.append(result)
        choice_issues = issues[issue_start:]
        if any(row["severity"] == "error" for row in choice_issues):
            choice_status = "contradicted"
        elif choice_issues:
            choice_status = "unresolved"
        else:
            choice_status = "verified"
        choice_message = (
            " ".join(row["message"] for row in choice_issues[:2])
            if choice_issues
            else "Branch labels, state, fights, outcomes, and reverse-indexed rewards were checked."
        )
        _coverage(
            coverage,
            "choice_outcomes",
            choice_name or "<unnamed-choice>",
            choice_status,
            choice_message,
        )

    acquisitions, acquisition_badges = _validate_acquisitions(
        [row for row in evidence.get("acquisitions") or [] if isinstance(row, dict)],
        analysis,
        badges,
        issues,
        coverage,
    )
    switch_sets = _validate_switch_sets(
        [row for row in evidence.get("switch_sets") or [] if isinstance(row, dict)],
        text,
        analysis,
        issues,
        coverage,
    )
    if switch_sets and not evidence.get("acquisitions"):
        coverage[:] = [row for row in coverage if not (row["category"] == "acquisition_totals" and row["claim_id"] == "acquisition-groups")]
    requirements = _validate_requirements(
        [row for row in evidence.get("requirements") or [] if isinstance(row, dict)],
        text,
        analysis,
        issues,
        coverage,
        evidence.get("requirements_reviewed") is True,
    )
    achievement_switch_sets = _validate_switch_achievements(
        [row for row in evidence.get("achievement_switch_sets") or [] if isinstance(row, dict)],
        text,
        analysis,
        evidence,
        issues,
        coverage,
    )
    _validate_achievements(analysis, badges, evidence, issues, coverage)
    _validate_badge_coverage(badges, evidence, analysis, acquisition_badges, coverage)
    publication = _validate_publication_parity(
        text,
        html_path,
        badges,
        issues,
        coverage,
    )
    graph = _event_graph(analysis, coverage)

    unresolved = [str(item) for item in evidence.get("unresolved") or []]
    for item in unresolved:
        _issue(
            issues,
            "warning",
            "live-play-unresolved",
            item,
        )
        _coverage(
            coverage,
            "live_play",
            f"manual-{len([row for row in coverage if row['category'] == 'live_play']) + 1}",
            "unresolved",
            item,
        )

    errors = sum(issue["severity"] == "error" for issue in issues)
    warnings = sum(issue["severity"] == "warning" for issue in issues)
    coverage_counts = Counter(row["status"] for row in coverage)
    reward_index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in analysis.rewards:
        if row.get("operation") == "increase" and row.get("name"):
            reward_index[row["name"]].append(row)
    has_gaps = bool(coverage_counts["unresolved"] or coverage_counts["unsupported"])
    status = "failed" if errors else ("passed_with_unresolved" if has_gaps else "passed")
    live_play_checklist = [
        {
            "category": row["category"],
            "claim_id": row["claim_id"],
            "reason": row["message"],
        }
        for row in coverage
        if row["status"] in {"unresolved", "unsupported"}
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "summary": {
            "errors": errors,
            "warnings": warnings,
            "badges": len(badges),
            "choice_claims": len(choice_results),
            "indexed_rewards": sum(len(rows) for rows in reward_index.values()),
            "coverage": {key: coverage_counts.get(key, 0) for key in sorted(COVERAGE_STATUSES)},
        },
        "issues": issues,
        "coverage": coverage,
        "badges": badges,
        "choices": choice_results,
        "acquisitions": acquisitions,
        "switch_sets": switch_sets,
        "requirements": requirements,
        "achievements": {
            "definitions": analysis.achievements,
            "awards": analysis.achievement_awards,
            "switch_sets": achievement_switch_sets,
        },
        "publication_parity": publication,
        "event_graph": graph,
        "reward_index": dict(sorted(reward_index.items())),
        "unresolved": unresolved,
        "live_play_checklist": live_play_checklist,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--walkthrough", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--checklist", type=Path)
    return parser.parse_args(argv)


def _write_live_play_checklist(path: Path, report: dict[str, Any]) -> None:
    rows = report["live_play_checklist"]
    lines = ["# Walkthrough Live-Play Checklist", ""]
    if not rows:
        lines.append("No unresolved or unsupported claims remain.")
    else:
        lines.append("Static analysis could not fully prove the following claims. Confirm each in play or add stronger source evidence.")
        lines.append("")
        for row in rows:
            lines.append(f"- [ ] **{row['category']} — {row['claim_id']}**: {row['reason']}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    game_root = args.game_root.resolve()
    walkthrough = args.walkthrough or (game_root / ".dazedtl" / "walkthrough" / "WALKTHROUGH.md")
    default_evidence = game_root / ".dazedtl" / "walkthrough" / "evidence.json"
    evidence = args.evidence or (default_evidence if default_evidence.is_file() else None)
    default_html = game_root / "WALKTHROUGH.html"
    html_path = args.html or (default_html if default_html.is_file() else None)
    report_path = args.report or (game_root / ".dazedtl" / "walkthrough" / "validation-report.json")
    checklist_path = args.checklist or (game_root / ".dazedtl" / "walkthrough" / "live-play-checklist.md")
    try:
        report = validate_project(game_root, walkthrough, evidence, html_path)
    except ValidationInputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_live_play_checklist(checklist_path, report)
    summary = report["summary"]
    coverage = summary["coverage"]
    print(
        f"{report['status'].upper()}: {summary['errors']} errors, "
        f"{summary['warnings']} warnings, {summary['badges']} badges, "
        f"{summary['choice_claims']} choice claims; "
        f"coverage {coverage['verified']} verified, {coverage['unresolved']} unresolved, "
        f"{coverage['unsupported']} unsupported, {coverage['contradicted']} contradicted"
    )
    print(f"Report: {report_path}")
    print(f"Live-play checklist: {checklist_path}")
    for issue in report["issues"]:
        print(f"- {issue['severity'].upper()} {issue['code']}: {issue['message']}")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
