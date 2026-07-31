"""WolfDawn database sheet classification for the WOLF translation workflow.

Database JSON (``kind: "db"``) varies widely across games: standard RPG sheets
(items, skills, states) vs custom narrative sheets (event dialogue, profiles).
This module classifies each ``groups[]`` sheet into tiers so translators can
translate foundational content before narrative-heavy custom tables.

Tiers:
    foundation - standard RPG sheets (items, skills, weapons, enemies, etc.)
    system     - UI / system messages in database fields
    narrative  - custom dialogue / profile sheets (defer until foundation is done)
    unknown    - unclassified sheets (included in foundation runs by default)
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from util.wolfdawn.names import _LABEL_SEP

TIER_FOUNDATION = "foundation"
TIER_SYSTEM = "system"
TIER_NARRATIVE = "narrative"
TIER_UNKNOWN = "unknown"

FOUNDATION_TIERS = frozenset({TIER_FOUNDATION, TIER_SYSTEM, TIER_UNKNOWN})
NARRATIVE_TIERS = frozenset({TIER_NARRATIVE})

DB_PROFILE_NAME = "db_profile.json"

# Japanese halves of standard WolfDawn bilingual typeName labels.
STANDARD_SHEETS_JP = frozenset({
    "武器",
    "防具",
    "技能",
    "アイテム",
    "状態設定",
    "用語設定",
    "戦闘コマンド",
    "システム設定",
    "属性名の設定",
    "主人公ステータス",
    "敵グループ",
    "敵ｷｬﾗ個体ﾃﾞｰﾀ",
})

STANDARD_FIELDS_RE = re.compile(
    r"説明|Description|商品説明|セーブ|ロード|使用時文章|発生時の文章|回復時の文章",
    re.IGNORECASE,
)
SYSTEM_FIELDS_RE = re.compile(
    r"メッセージ|Message|タイトル|用語|Terms?",
    re.IGNORECASE,
)
CUSTOM_SHEET_RE = re.compile(
    r"^[■├■]|イベント|セリフ|プロフィール|MOB|感想|所持アイテム|CG",
)
DIALOGUE_FIELDS_RE = re.compile(
    r"セリフ|コメント|相手|行為|台詞|会話|メッセージ_",
)

# Foundation DB lines that are short display labels (map names, term titles),
# not descriptions / battle messages / dialogue. Used when seeding glossary.txt.
_DB_VOCAB_FIELD_RE = re.compile(
    r"マップ名|"
    r"属性名|"
    r"用語名|"
    r"コマンド名|"
    r"(?:^|·\s*)タイトル(?:$|[（(\s])|"
    r"(?:^|·\s*)Name(?:\s*·|$)|"
    r"(?:^|·\s*)Title(?:\s*·|$)|"
    r"(?:^|·\s*)名称(?:$|[（(\s·])|"
    r"(?:^|·\s*)称号(?!.*コメント)|"
    r"(?:^|·\s*)好きなもの(?!.*コメント)",
    re.IGNORECASE,
)
_DB_VOCAB_SKIP_FIELD_RE = re.compile(
    r"説明|Description|文章|メッセージ|Message|セリフ|コメント|Comment|"
    r"行為|相手|台詞|会話",
    re.IGNORECASE,
)
_DB_VOCAB_HARVEST_MAX_LEN = 72

ARCHETYPE_CLASSIC = "classic_rpg"
ARCHETYPE_DB_HEAVY = "simulation_db_heavy"
ARCHETYPE_HYBRID = "hybrid"
ARCHETYPE_UNKNOWN = "unknown"


@dataclass
class DbGroupInfo:
    """One classified database sheet (a ``groups[]`` entry)."""

    json_file: str
    type_name: str
    tier: str
    line_count: int
    sample_fields: list[str] = field(default_factory=list)
    default_checked: bool = True

    @property
    def key(self) -> str:
        return group_key(self.json_file, self.type_name)


def group_key(json_file: str, type_name: str) -> str:
    """Stable id for a sheet: ``DataBase.project.json|Skill · 技能``."""
    return f"{json_file}|{type_name}"


def _japanese_sheet_name(type_name: str) -> str:
    if _LABEL_SEP in type_name:
        _, _, jp = type_name.partition(_LABEL_SEP)
        return jp.strip()
    return type_name.strip()


def json_file_from_doc(doc: dict[str, Any], path: Path | None = None) -> str:
    if path is not None:
        return path.name
    file_field = str(doc.get("file") or "")
    if file_field:
        return f"{file_field}.json" if not file_field.endswith(".json") else file_field
    return "unknown.project.json"


def classify_group_tier(type_name: str, lines: list[dict[str, Any]]) -> str:
    """Return the tier for one database sheet."""
    jp = _japanese_sheet_name(type_name)
    if CUSTOM_SHEET_RE.search(type_name) or CUSTOM_SHEET_RE.search(jp):
        return TIER_NARRATIVE
    if jp in STANDARD_SHEETS_JP:
        return TIER_FOUNDATION

    field_names = [str(line.get("fieldName") or "") for line in lines]
    dialogue_hits = sum(1 for fn in field_names if DIALOGUE_FIELDS_RE.search(fn))
    standard_hits = sum(1 for fn in field_names if STANDARD_FIELDS_RE.search(fn))
    system_hits = sum(1 for fn in field_names if SYSTEM_FIELDS_RE.search(fn))

    if lines and dialogue_hits > max(standard_hits, system_hits):
        return TIER_NARRATIVE
    if standard_hits > 0:
        return TIER_FOUNDATION
    if system_hits > 0:
        return TIER_SYSTEM
    if not lines:
        return TIER_UNKNOWN
    return TIER_UNKNOWN


def classify_db_document(
    doc: dict[str, Any],
    *,
    json_file: str | None = None,
    path: Path | None = None,
) -> list[DbGroupInfo]:
    """Classify every group in one ``kind: db`` document."""
    if doc.get("kind") != "db":
        return []
    jf = json_file or json_file_from_doc(doc, path)
    groups: list[DbGroupInfo] = []
    for group in doc.get("groups") or []:
        type_name = str(group.get("typeName") or "")
        lines = group.get("lines") or []
        tier = classify_group_tier(type_name, lines)
        fields: Counter[str] = Counter()
        for line in lines:
            fn = str(line.get("fieldName") or "").strip()
            if fn:
                fields[fn] += 1
        sample = [fn for fn, _ in fields.most_common(3)]
        default_checked = tier in FOUNDATION_TIERS
        groups.append(
            DbGroupInfo(
                json_file=jf,
                type_name=type_name,
                tier=tier,
                line_count=len(lines),
                sample_fields=sample,
                default_checked=default_checked,
            )
        )
    return groups


def _count_json_lines(doc: dict[str, Any]) -> int:
    kind = doc.get("kind")
    if kind in ("map", "common"):
        return sum(len(scene.get("lines") or []) for scene in doc.get("scenes") or [])
    if kind == "gamedat":
        return len(doc.get("lines") or [])
    if kind == "txt-dir":
        return sum(
            len(f.get("lines") or [])
            for f in doc.get("files") or []
        )
    if kind == "txt":
        return len(doc.get("lines") or [])
    return 0


def _load_json(path: Path) -> dict[str, Any] | None:
    """Load a WolfDawn JSON object. Skip arrays / non-objects (e.g. RPGMaker files/)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


@dataclass
class ContentDistribution:
    """Text distribution across WolfDawn extraction kinds."""

    db_lines: int = 0
    db_foundation_lines: int = 0
    db_narrative_lines: int = 0
    db_system_lines: int = 0
    db_unknown_lines: int = 0
    map_lines: int = 0
    map_files: int = 0
    common_lines: int = 0
    gamedat_lines: int = 0
    evtext_lines: int = 0
    groups: list[DbGroupInfo] = field(default_factory=list)
    archetype: str = ARCHETYPE_UNKNOWN

    @property
    def total_event_lines(self) -> int:
        return self.map_lines + self.common_lines + self.gamedat_lines + self.evtext_lines

    @property
    def db_narrative_pct(self) -> float:
        if self.db_lines <= 0:
            return 0.0
        return 100.0 * self.db_narrative_lines / self.db_lines


def analyze_content_distribution(files_dir: str | Path) -> ContentDistribution:
    """Scan staged ``files/`` JSON and classify database sheets."""
    base = Path(files_dir)
    dist = ContentDistribution()
    if not base.is_dir():
        return dist

    for path in sorted(base.glob("*.json")):
        doc = _load_json(path)
        if not doc:
            continue
        kind = doc.get("kind")
        if kind == "db":
            groups = classify_db_document(doc, path=path)
            dist.groups.extend(groups)
            for g in groups:
                dist.db_lines += g.line_count
                if g.tier == TIER_FOUNDATION:
                    dist.db_foundation_lines += g.line_count
                elif g.tier == TIER_NARRATIVE:
                    dist.db_narrative_lines += g.line_count
                elif g.tier == TIER_SYSTEM:
                    dist.db_system_lines += g.line_count
                else:
                    dist.db_unknown_lines += g.line_count
        elif kind == "map":
            dist.map_files += 1
            dist.map_lines += _count_json_lines(doc)
        elif kind == "common":
            dist.common_lines += _count_json_lines(doc)
        elif kind == "gamedat":
            dist.gamedat_lines += _count_json_lines(doc)
        elif kind == "txt-dir":
            dist.evtext_lines += _count_json_lines(doc)

    dist.archetype = _infer_archetype(dist)
    return dist


def _infer_archetype(dist: ContentDistribution) -> str:
    total = dist.db_lines + dist.total_event_lines
    if total <= 0:
        return ARCHETYPE_UNKNOWN
    db_share = dist.db_lines / total
    narrative_share = dist.db_narrative_lines / max(dist.db_lines, 1)
    if db_share > 0.5 and narrative_share > 0.4:
        return ARCHETYPE_DB_HEAVY
    if dist.total_event_lines > dist.db_lines * 2 and dist.db_narrative_lines < dist.db_lines * 0.2:
        return ARCHETYPE_CLASSIC
    return ARCHETYPE_HYBRID


def format_discovery_summary(dist: ContentDistribution) -> str:
    """Multi-line discovery report for the Database workflow step."""
    lines = ["This game's text distribution:"]
    if dist.db_lines:
        pct_narr = f"{dist.db_narrative_pct:.0f}% narrative sheets"
        lines.append(
            f"  Database: {dist.db_lines:,} lines "
            f"({dist.db_foundation_lines + dist.db_system_lines:,} foundation/system, "
            f"{dist.db_narrative_lines:,} narrative, {pct_narr})"
        )
    else:
        lines.append("  Database: (no DB JSON in files/)")
    lines.append(f"  Maps: {dist.map_files} file(s), {dist.map_lines:,} dialogue lines")
    lines.append(f"  CommonEvent: {dist.common_lines:,} lines")
    if dist.gamedat_lines:
        lines.append(f"  Game.dat: {dist.gamedat_lines:,} lines")
    if dist.evtext_lines:
        lines.append(f"  Evtext: {dist.evtext_lines:,} lines")

    lines.append("")
    lines.append(archetype_guidance(dist))
    return "\n".join(lines)


def archetype_guidance(dist: ContentDistribution) -> str:
    foundation = dist.db_foundation_lines + dist.db_system_lines + dist.db_unknown_lines
    if dist.archetype == ARCHETYPE_DB_HEAVY:
        return (
            "Recommended order: Names → DB foundation "
            f"({foundation:,} lines) → DB narrative "
            f"({dist.db_narrative_lines:,} lines) → Maps/events.\n"
            "This game stores most story dialogue in custom database sheets, not maps."
        )
    if dist.archetype == ARCHETYPE_CLASSIC:
        return (
            "Recommended order: Names → DB foundation "
            f"({foundation:,} lines) → Maps/events "
            f"({dist.total_event_lines:,} lines).\n"
            "Classic layout: most story dialogue is in maps and common events. "
            "You can skip DB narrative if there are no custom sheets."
        )
    if dist.db_narrative_lines == 0:
        return (
            "Recommended order: Names → DB foundation "
            f"({foundation:,} lines) → Maps/events.\n"
            "No custom narrative DB sheets detected — skip narrative DB translation."
        )
    return (
        "Recommended order: Names → DB foundation "
        f"({foundation:,} lines) → DB narrative "
        f"({dist.db_narrative_lines:,} lines) → Maps/events.\n"
        "Hybrid layout: significant text in both database sheets and maps."
    )


def build_ai_audit_prompt(dist: ContentDistribution) -> str:
    """Compact prompt for AI-assisted database structure analysis."""
    group_lines = []
    for g in sorted(dist.groups, key=lambda x: -x.line_count):
        fields = ", ".join(g.sample_fields[:2]) if g.sample_fields else "(none)"
        group_lines.append(
            f"  - {g.json_file} | {g.type_name}: {g.line_count} lines, "
            f"tier={g.tier}, fields: {fields}"
        )
    groups_text = "\n".join(group_lines) if group_lines else "  (no database groups found)"

    return (
        "You are an expert Japanese WOLF RPG Editor game analyst.\n"
        "\n"
        "<task>\n"
        "Classify this game's database sheets for translation workflow. "
        "Return ONLY valid JSON (no markdown fences) matching this schema:\n"
        "{\n"
        '  "archetype": "classic_rpg" | "simulation_db_heavy" | "hybrid",\n'
        '  "foundation_groups": ["DataBase.project.json|Skill · 技能", ...],\n'
        '  "narrative_groups": ["DataBase.project.json|■イベント(名前)", ...],\n'
        '  "defer_groups": [],\n'
        '  "notes": "one sentence about where this game stores dialogue"\n'
        "}\n"
        "\n"
        "foundation_groups = items, skills, descriptions, system UI (translate first).\n"
        "narrative_groups = custom dialogue/profile sheets (translate after foundation).\n"
        "defer_groups = sheets to skip entirely (rare).\n"
        "Use the exact group keys shown below (json_file|typeName).\n"
        "</task>\n"
        "\n"
        "<auto_summary>\n"
        f"{format_discovery_summary(dist)}\n"
        "</auto_summary>\n"
        "\n"
        "<database_groups>\n"
        f"{groups_text}\n"
        "</database_groups>\n"
    )


def db_profile_path(work_dir: str | Path) -> Path:
    return Path(work_dir) / DB_PROFILE_NAME


def load_db_profile(work_dir: str | Path) -> dict[str, Any]:
    path = db_profile_path(work_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_db_profile(work_dir: str | Path, profile: dict[str, Any]) -> None:
    path = db_profile_path(work_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def merge_profile_with_groups(
    profile: dict[str, Any],
    groups: list[DbGroupInfo],
) -> dict[str, bool]:
    """Return ``{group_key: checked}`` merging AI profile with heuristic defaults."""
    selected: set[str] = set()

    for key in ("foundation_groups", "narrative_groups"):
        for item in profile.get(key) or []:
            if isinstance(item, str) and item.strip():
                selected.add(item.strip())
    defer = {str(x) for x in (profile.get("defer_groups") or []) if str(x).strip()}

    result: dict[str, bool] = {}
    for g in groups:
        if g.key in defer:
            result[g.key] = False
        elif g.key in selected:
            result[g.key] = True
        elif profile.get("foundation_groups") or profile.get("narrative_groups"):
            # Profile exists but group not listed: use tier default.
            result[g.key] = g.default_checked
        else:
            result[g.key] = g.default_checked
    return result


def selected_groups_for_tiers(
    groups: list[DbGroupInfo],
    tiers: frozenset[str],
) -> list[str]:
    return [g.key for g in groups if g.tier in tiers]


def parse_db_filter_tiers(raw: str) -> frozenset[str]:
    text = (raw or "").strip()
    if not text:
        return frozenset()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return frozenset(str(x).strip() for x in parsed if str(x).strip())
    except json.JSONDecodeError:
        pass
    return frozenset(part.strip() for part in text.split(",") if part.strip())


def parse_db_filter_groups(raw: str) -> frozenset[str]:
    text = (raw or "").strip()
    if not text:
        return frozenset()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return frozenset(str(x).strip() for x in parsed if str(x).strip())
    except json.JSONDecodeError:
        pass
    return frozenset(part.strip() for part in text.split(",") if part.strip())


def load_db_filter_config() -> tuple[frozenset[str], frozenset[str]]:
    """Read ``wolfDbIncludeTiers`` / ``wolfDbIncludeGroups`` from ``.env``."""
    import os

    return (
        parse_db_filter_tiers(os.getenv("wolfDbIncludeTiers", "")),
        parse_db_filter_groups(os.getenv("wolfDbIncludeGroups", "")),
    )


def is_db_vocab_harvest_candidate(
    line: dict[str, Any],
    *,
    type_name: str = "",
    tier: str | None = None,
) -> bool:
    """True when a foundation DB line should seed ``glossary.txt``.

    Only short label-like fields on foundation/system/unknown sheets qualify.
    Descriptions, battle messages, and narrative dialogue stay out.
    """
    resolved = tier
    if resolved is None:
        resolved = classify_group_tier(type_name, [line])
    if resolved not in FOUNDATION_TIERS:
        return False
    field_name = str(line.get("fieldName") or "")
    if _DB_VOCAB_SKIP_FIELD_RE.search(field_name):
        return False
    if not _DB_VOCAB_FIELD_RE.search(field_name):
        return False
    if DIALOGUE_FIELDS_RE.search(field_name):
        return False
    src = str(line.get("source") or "")
    if not src.strip():
        return False
    if "\n" in src or "\r" in src:
        return False
    if len(src) > _DB_VOCAB_HARVEST_MAX_LEN:
        return False
    if len(re.findall(r"[。！？]", src)) >= 2:
        return False
    return True


def collect_db_vocab_pairs(
    doc: dict[str, Any],
    *,
    include_tiers: frozenset[str] | None = None,
    include_groups: frozenset[str] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Return ``{typeName: [(source, text), ...]}`` for harvestable DB terms.

    Respects the same sheet filter used for translation when *include_tiers* /
    *include_groups* are provided. Only foundation-tier sheets contribute.
    """
    if doc.get("kind") != "db":
        return {}
    json_file = json_file_from_doc(doc)
    tiers = include_tiers if include_tiers is not None else frozenset()
    groups = include_groups if include_groups is not None else frozenset()
    by_sheet: dict[str, list[tuple[str, str]]] = {}
    for group in doc.get("groups") or []:
        type_name = str(group.get("typeName") or "")
        lines = group.get("lines") or []
        if not group_matches_filter(json_file, type_name, tiers, groups):
            continue
        tier = classify_group_tier(type_name, lines)
        if tier not in FOUNDATION_TIERS:
            continue
        pairs: list[tuple[str, str]] = []
        for line in lines:
            if not is_db_vocab_harvest_candidate(line, type_name=type_name, tier=tier):
                continue
            src, dst = line.get("source"), line.get("text")
            if not isinstance(src, str) or not isinstance(dst, str):
                continue
            pairs.append((src, dst))
        if pairs:
            by_sheet[type_name] = pairs
    return by_sheet


def group_matches_filter(
    json_file: str,
    type_name: str,
    include_tiers: frozenset[str],
    include_groups: frozenset[str],
) -> bool:
    """True when a DB sheet should be translated under the active filter."""
    if not include_tiers and not include_groups:
        return True
    key = group_key(json_file, type_name)
    if include_groups:
        return key in include_groups
    # Tier-only filter: need to classify on the fly without line data.
    tier = classify_group_tier(type_name, [])
    return tier in include_tiers


def import_ai_profile(raw: str) -> dict[str, Any]:
    """Parse AI-returned JSON profile text (strips markdown fences if present)."""
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Profile must be a JSON object")
    return data
