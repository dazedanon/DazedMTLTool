#!/usr/bin/env python3
"""Build a deterministic state/dependency index for RPG Maker MV/MZ events.

The index deliberately stops short of pretending to solve arbitrary JavaScript.
It inventories structured state reads/writes and control-flow sites so a
walkthrough author can account for every use of a carrier in a smaller,
source-reviewed dependency closure.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1
MAX_EXPANDED_SITES_PER_CARRIER = 500
FOCUSABLE_CARRIER_KINDS = {"actor", "armor", "item", "switch", "variable", "weapon"}


class IndexInputError(ValueError):
    """Raised when an RPG Maker data directory cannot be indexed."""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IndexInputError(f"Could not read {path}: {exc}") from exc


def _data_dir(game_root: Path) -> Path:
    candidates = (game_root / "data", game_root / "www" / "data")
    for candidate in candidates:
        if (candidate / "MapInfos.json").is_file() or (candidate / "System.json").is_file():
            return candidate
    raise IndexInputError(
        f"Could not find RPG Maker data under {game_root / 'data'} or {game_root / 'www' / 'data'}."
    )


def _relative(path: Path, game_root: Path) -> str:
    return path.resolve().relative_to(game_root.resolve()).as_posix()


def _site_prefix(container: str, record_id: int, page_index: int | None = None) -> str:
    if container == "map":
        assert page_index is not None
        return f"map-{record_id:03d}-event-{{event_id:03d}}-page-{page_index:03d}"
    if container == "common-event":
        return f"common-event-{record_id:04d}"
    assert container == "troop"
    assert page_index is not None
    return f"troop-{record_id:04d}-page-{page_index:03d}"


def _carrier_site(
    *,
    site_id: str,
    file: str,
    container: str,
    record_id: int,
    page_index: int,
    command_index: int | None,
    role: str,
    kind: str,
    carrier_id: int | str,
    code: int | str,
    parameters: list[Any],
    event_id: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": site_id,
        "role": role,
        "carrier": {"kind": kind, "id": carrier_id},
        "code": code,
    }
    return row


def _flow_site(
    *,
    site_id: str,
    file: str,
    container: str,
    record_id: int,
    page_index: int,
    command_index: int,
    kind: str,
    code: int,
    parameters: list[Any],
    event_id: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": site_id,
        "kind": kind,
        "code": code,
        "parameters": parameters,
    }
    return row


def _append_range(
    output: list[dict[str, Any]],
    *,
    prefix: str,
    start: Any,
    end: Any,
    kind: str,
    **shared: Any,
) -> None:
    if not isinstance(start, int) or isinstance(start, bool):
        return
    if not isinstance(end, int) or isinstance(end, bool) or end < start:
        end = start
    if start == end:
        output.append(
            _carrier_site(
                site_id=f"{prefix}-{kind}-{start:04d}",
                kind=kind,
                carrier_id=start,
                **shared,
            )
        )
        return
    row = _carrier_site(
        site_id=f"{prefix}-{kind}-{start:04d}-through-{end:04d}",
        kind=kind,
        carrier_id=start,
        **shared,
    )
    row["carrier"] = {"kind": kind, "start_id": start, "end_id": end}
    output.append(row)


def _page_conditions(
    conditions: Any,
    *,
    prefix: str,
    file: str,
    container: str,
    record_id: int,
    page_index: int,
    event_id: int | None,
) -> list[dict[str, Any]]:
    if not isinstance(conditions, dict):
        return []
    output: list[dict[str, Any]] = []
    candidates = (
        ("switch1Valid", "switch1Id", "switch"),
        ("switch2Valid", "switch2Id", "switch"),
        ("switchValid", "switchId", "switch"),
        ("variableValid", "variableId", "variable"),
        ("itemValid", "itemId", "item"),
        ("actorValid", "actorId", "actor"),
    )
    for valid_key, id_key, kind in candidates:
        carrier_id = conditions.get(id_key)
        if not conditions.get(valid_key) or carrier_id in (None, 0, ""):
            continue
        suffix = f"{int(carrier_id):04d}" if isinstance(carrier_id, int) else str(carrier_id).lower()
        output.append(
            _carrier_site(
                site_id=f"{prefix}-page-condition-{kind}-{suffix}",
                file=file,
                container=container,
                record_id=record_id,
                page_index=page_index,
                command_index=None,
                role="read",
                kind=kind,
                carrier_id=carrier_id,
                code="page-condition",
                parameters=[valid_key, id_key, carrier_id],
                event_id=event_id,
            )
        )
    return output


def _command_sites(
    commands: Any,
    *,
    prefix: str,
    file: str,
    container: str,
    record_id: int,
    page_index: int,
    event_id: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    carrier_sites: list[dict[str, Any]] = []
    flow_sites: list[dict[str, Any]] = []
    if not isinstance(commands, list):
        return carrier_sites, flow_sites
    shared = {
        "file": file,
        "container": container,
        "record_id": record_id,
        "page_index": page_index,
        "event_id": event_id,
    }
    for command_index, raw_command in enumerate(commands):
        if not isinstance(raw_command, dict):
            continue
        code = raw_command.get("code")
        params = raw_command.get("parameters")
        if not isinstance(code, int) or not isinstance(params, list):
            continue
        command_prefix = f"{prefix}-command-{command_index:04d}"
        command_shared = {**shared, "command_index": command_index, "code": code, "parameters": params}

        if code == 111 and params:
            condition_type = params[0]
            kind_by_type = {0: "switch", 1: "variable", 4: "actor", 5: "enemy", 8: "item", 9: "weapon", 10: "armor"}
            kind = kind_by_type.get(condition_type)
            carrier_id = params[1] if len(params) > 1 else None
            if kind and isinstance(carrier_id, int):
                carrier_sites.append(
                    _carrier_site(
                        site_id=f"{command_prefix}-{kind}-{carrier_id:04d}",
                        role="read",
                        kind=kind,
                        carrier_id=carrier_id,
                        **command_shared,
                    )
                )
            elif condition_type in {2, 12}:
                flow_sites.append(
                    _flow_site(
                        site_id=f"{command_prefix}-opaque-condition",
                        kind="opaque-condition",
                        **command_shared,
                    )
                )
        elif code in {121, 122} and len(params) >= 2:
            _append_range(
                carrier_sites,
                prefix=command_prefix,
                start=params[0],
                end=params[1],
                kind="switch" if code == 121 else "variable",
                role="write",
                **command_shared,
            )
            if code == 122 and len(params) > 4 and params[3] == 1 and isinstance(params[4], int):
                carrier_sites.append(
                    _carrier_site(
                        site_id=f"{command_prefix}-operand-variable-{params[4]:04d}",
                        role="read",
                        kind="variable",
                        carrier_id=params[4],
                        **command_shared,
                    )
                )
        elif code in {126, 127, 128} and params:
            kind = {126: "item", 127: "weapon", 128: "armor"}[code]
            carrier_id = params[0]
            if isinstance(carrier_id, int):
                carrier_sites.append(
                    _carrier_site(
                        site_id=f"{command_prefix}-{kind}-{carrier_id:04d}",
                        role="write",
                        kind=kind,
                        carrier_id=carrier_id,
                        **command_shared,
                    )
                )
            if len(params) > 3 and params[2] == 1 and isinstance(params[3], int):
                carrier_sites.append(
                    _carrier_site(
                        site_id=f"{command_prefix}-operand-variable-{params[3]:04d}",
                        role="read",
                        kind="variable",
                        carrier_id=params[3],
                        **command_shared,
                    )
                )
        elif code == 129 and params and isinstance(params[0], int):
            carrier_sites.append(
                _carrier_site(
                    site_id=f"{command_prefix}-actor-{params[0]:04d}",
                    role="write",
                    kind="actor",
                    carrier_id=params[0],
                    **command_shared,
                )
            )

        flow_kind = {
            102: "choice",
            117: "common-event-call",
            201: "transfer",
            301: "battle",
            601: "battle-win",
            602: "battle-escape",
            603: "battle-loss",
            355: "script",
            356: "plugin-command",
            357: "plugin-command-mz",
            655: "script-continuation",
            657: "plugin-annotation",
        }.get(code)
        if flow_kind:
            flow_sites.append(
                _flow_site(site_id=f"{command_prefix}-{flow_kind}", kind=flow_kind, **command_shared)
            )
    return carrier_sites, flow_sites


def _event_lists(data_dir: Path, game_root: Path) -> Iterable[tuple[str, str, int, int, int | None, Any, Any]]:
    for path in sorted(data_dir.glob("Map[0-9][0-9][0-9].json")):
        try:
            map_id = int(path.stem[3:])
        except ValueError:
            continue
        data = _read_json(path)
        events = data.get("events") if isinstance(data, dict) else None
        if not isinstance(events, list):
            continue
        for event_id, event in enumerate(events):
            pages = event.get("pages") if isinstance(event, dict) else None
            if not isinstance(pages, list):
                continue
            for page_index, page in enumerate(pages):
                conditions = page.get("conditions") if isinstance(page, dict) else None
                commands = page.get("list") if isinstance(page, dict) else None
                prefix = _site_prefix("map", map_id, page_index).format(event_id=event_id)
                yield prefix, _relative(path, game_root), map_id, page_index, event_id, conditions, commands

    common_path = data_dir / "CommonEvents.json"
    if common_path.is_file():
        rows = _read_json(common_path)
        if isinstance(rows, list):
            for common_id, common in enumerate(rows):
                if not isinstance(common, dict):
                    continue
                prefix = _site_prefix("common-event", common_id)
                yield prefix, _relative(common_path, game_root), common_id, 0, None, None, common.get("list")

    troop_path = data_dir / "Troops.json"
    if troop_path.is_file():
        rows = _read_json(troop_path)
        if isinstance(rows, list):
            for troop_id, troop in enumerate(rows):
                pages = troop.get("pages") if isinstance(troop, dict) else None
                if not isinstance(pages, list):
                    continue
                for page_index, page in enumerate(pages):
                    conditions = page.get("conditions") if isinstance(page, dict) else None
                    commands = page.get("list") if isinstance(page, dict) else None
                    prefix = _site_prefix("troop", troop_id, page_index)
                    yield prefix, _relative(troop_path, game_root), troop_id, page_index, None, conditions, commands


def build_index(
    game_root: Path,
    include_carriers: Iterable[tuple[str, int]] = (),
) -> dict[str, Any]:
    """Return the stable dependency index for an RPG Maker game root."""
    game_root = game_root.resolve()
    focused_carriers = set(include_carriers)
    invalid_focus = sorted(
        (kind, carrier_id)
        for kind, carrier_id in focused_carriers
        if kind not in FOCUSABLE_CARRIER_KINDS
        or not isinstance(carrier_id, int)
        or isinstance(carrier_id, bool)
        or carrier_id < 1
    )
    if invalid_focus:
        kind, carrier_id = invalid_focus[0]
        raise IndexInputError(f"Invalid focused carrier {kind}:{carrier_id!r}.")
    data_dir = _data_dir(game_root)
    carrier_sites: list[dict[str, Any]] = []
    flow_sites: list[dict[str, Any]] = []
    for prefix, file, record_id, page_index, event_id, conditions, commands in _event_lists(data_dir, game_root):
        container = "map" if prefix.startswith("map-") else ("common-event" if prefix.startswith("common-") else "troop")
        carrier_sites.extend(
            _page_conditions(
                conditions,
                prefix=prefix,
                file=file,
                container=container,
                record_id=record_id,
                page_index=page_index,
                event_id=event_id,
            )
        )
        carriers, flows = _command_sites(
            commands,
            prefix=prefix,
            file=file,
            container=container,
            record_id=record_id,
            page_index=page_index,
            event_id=event_id,
        )
        carrier_sites.extend(carriers)
        flow_sites.extend(flows)

    exact_counts = Counter(
        (site["carrier"].get("kind"), site["carrier"].get("id"))
        for site in carrier_sites
        if "id" in site["carrier"]
    )
    omitted_keys = {
        key
        for key, count in exact_counts.items()
        if count > MAX_EXPANDED_SITES_PER_CARRIER and key not in focused_carriers
    }
    observed_carrier_sites = len(carrier_sites)
    carrier_sites = [
        site
        for site in carrier_sites
        if (site["carrier"].get("kind"), site["carrier"].get("id")) not in omitted_keys
    ]
    carrier_sites.sort(key=lambda row: row["id"])
    flow_sites.sort(key=lambda row: row["id"])
    indexed_paths = sorted(data_dir.glob("Map[0-9][0-9][0-9].json"))
    indexed_paths.extend(path for path in (data_dir / "CommonEvents.json", data_dir / "Troops.json") if path.is_file())
    return {
        "schema_version": SCHEMA_VERSION,
        "engine": "rpg-maker-mv-mz",
        "data_root": _relative(data_dir, game_root),
        "source_files": [
            {"file": _relative(path, game_root), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for path in indexed_paths
        ],
        "carrier_sites": carrier_sites,
        "omitted_high_frequency_carriers": [
            {"kind": kind, "id": carrier_id, "site_count": exact_counts[(kind, carrier_id)]}
            for kind, carrier_id in sorted(omitted_keys, key=lambda row: (str(row[0]), int(row[1])))
        ],
        "flow_sites": flow_sites,
        "summary": {
            "carrier_sites": len(carrier_sites),
            "observed_carrier_sites": observed_carrier_sites,
            "flow_sites": len(flow_sites),
            "opaque_sites": sum(
                row["kind"] in {"opaque-condition", "script", "script-continuation", "plugin-command", "plugin-command-mz"}
                for row in flow_sites
            ),
        },
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--flow-output", type=Path)
    parser.add_argument(
        "--include-carrier",
        action="append",
        default=[],
        metavar="KIND:ID",
        help="Keep every site for one decisive high-frequency carrier; may be repeated.",
    )
    return parser.parse_args(argv)


def _focused_carriers(values: Iterable[str]) -> set[tuple[str, int]]:
    output: set[tuple[str, int]] = set()
    for value in values:
        kind, separator, raw_id = value.partition(":")
        if not separator or kind not in FOCUSABLE_CARRIER_KINDS:
            raise IndexInputError(
                f"Invalid --include-carrier {value!r}; expected one of "
                f"{sorted(FOCUSABLE_CARRIER_KINDS)} followed by :ID."
            )
        try:
            carrier_id = int(raw_id)
        except ValueError as exc:
            raise IndexInputError(
                f"Invalid --include-carrier {value!r}; ID must be a positive integer."
            ) from exc
        if carrier_id < 1:
            raise IndexInputError(
                f"Invalid --include-carrier {value!r}; ID must be a positive integer."
            )
        output.add((kind, carrier_id))
    return output


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        index = build_index(args.game_root, _focused_carriers(args.include_carrier))
        flow_output = args.flow_output or args.output.with_name(
            f"{args.output.stem}-flows{args.output.suffix}"
        )
        flow_index = {
            "schema_version": SCHEMA_VERSION,
            "engine": index["engine"],
            "data_root": index["data_root"],
            "source_files": index["source_files"],
            "flow_sites": index.pop("flow_sites"),
        }
        index["flow_artifact"] = flow_output.name
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        flow_output.parent.mkdir(parents=True, exist_ok=True)
        flow_output.write_text(
            json.dumps(flow_index, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
    except (IndexInputError, OSError) as exc:
        print(f"Dependency indexing failed: {exc}")
        return 2
    print(
        f"Indexed {index['summary']['carrier_sites']} carrier sites and "
        f"{index['summary']['flow_sites']} flow sites."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
