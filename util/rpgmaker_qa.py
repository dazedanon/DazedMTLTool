"""Deterministic local tooling for AI-helper RPG Maker translation QA.

DazedTL owns inventory, compact bundles, checkpoints, context expansion,
result validation, finding propagation, correction maps, and regression.  The
AI helper only reviews immutable bundle files and writes the documented JSON
result shape; this module never calls a model provider.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import tempfile
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from util.paths import (
    GAME_GLOSSARY_RELATIVE,
    GAME_QUIRKS_RELATIVE,
    GAME_SKILL_RELATIVE,
    GAME_SKILL_RESERVED_NAMES,
    GAME_SKILLS_RELATIVE,
)
from util.rpgmaker_qa_manifest import build_manifest, resolve_pointer, write_manifest
from util.rpgmaker_qa_verify import verify_manifest
from util.reference_games import reference_context


TASK_SCHEMA = "rpgmaker-qa-task-v3"
CHECKPOINT_SCHEMA = "rpgmaker-qa-checkpoint-v3"
BUNDLE_SCHEMA = "rpgmaker-qa-bundle-v3"
SCREEN_RESULT_SCHEMA = "rpgmaker-qa-screen-result-v2"
DEEP_RESULT_SCHEMA = "rpgmaker-qa-deep-result-v3"
FINDINGS_SCHEMA = "rpgmaker-qa-findings-v5"
CORRECTION_MAP_SCHEMA = "rpgmaker-qa-correction-map-v1"
REGRESSION_SCHEMA = "rpgmaker-qa-regression-v1"
EDITORIAL_REVIEW_SCHEMA = "rpgmaker-qa-final-editorial-v1"

DEFAULT_SCREEN_CHAR_BUDGET = 48_000
DEFAULT_SCREEN_ITEM_LIMIT = 160
DEFAULT_DEEP_CHAR_BUDGET = 56_000
DEFAULT_DEEP_ITEM_LIMIT = 24

SCREEN_VERDICTS = frozenset({"suspect", "needs-context"})
MOTIF_DISPOSITIONS = frozenset({"preserved", "suspect", "uncertain-playtest"})
DEEP_DISPOSITIONS = frozenset({"clean", "actionable", "uncertain-playtest"})
SEVERITIES = frozenset({"critical", "high", "medium"})
FINDING_CATEGORIES = frozenset({
    "meaning",
    "terminology",
    "fluency",
    "wordplay",
    "voice",
    "ui",
    "gameplay",
    "runtime",
    "formatting",
    "other",
})
EDITORIAL_JUDGMENT_CATEGORIES = frozenset({"fluency", "voice", "wordplay"})
APPROVED_NONBLOCKING_MECHANICAL_FLAGS = frozenset({"suspicious-length-ratio"})

QA_POLICY_VERSION = "rpgmaker-qa-scene-motif-editorial-reference-v11"
FORCED_DEEP_MECHANICAL_FLAGS = frozenset({
    "empty-live",
    "unchanged-source",
    "source-language-residue",
    "runtime-token-mismatch",
    "visible-number-mismatch",
})
FORCED_DEEP_EVENT_CODES = frozenset({102})

_JP_RISK_CUES = {
    "negation": re.compile(
        r"(?:ない|なかった|ません|ませぬ|禁止|不可|[ぬず](?:[、。！？!?…\s]|$))"
    ),
    "condition": re.compile(r"(?:なら|れば|たら|場合|条件|限り|とき|時に)"),
    "quantity": re.compile(r"(?:\d|[０-９]|一|二|三|四|五|六|七|八|九|十|百|千|万)(?:人|個|回|日|年|枚|本|匹|体|つ)?"),
    "identity": re.compile(r"(?:彼|彼女|あいつ|こいつ|そいつ|父|母|兄|姉|弟|妹|夫|妻|先生|様|殿)"),
    "choice-or-order": re.compile(r"(?:選|決|必ず|先に|後で|前に|まで|以降|以前)"),
    "wordplay": re.compile(r"(?:駄洒落|冗談|笑|ふふ|はは|クク|語呂|謎|暗号)"),
}
_GLOSSARY_PAIR_RE = re.compile(r"^(.+?)\s+\((.+)\)\s*$")
_QUOTED_VALUE_RE = re.compile(r"(['\"`])(.*)(\1)", re.DOTALL)
_MOTIF_GUIDANCE_RE = re.compile(
    r"(?:recurring|running|joke|wordplay|pun|catchphrase|humou?r|冗談|駄洒落|語呂)",
    re.IGNORECASE,
)
_JAPANESE_ANCHOR_RE = re.compile(r"[一-龠々〆〤ぁ-ゔァ-ヴー]{2,}")
_CANONICAL_QUIRK_MAPPING_RE = re.compile(
    r"`([^`\n]+)`\s*→\s*\"([^\"\n]+)\""
)
_JAPANESE_FIELD_LABEL_RE = re.compile(r"【([^】\n]+)】")
_ENGLISH_FIELD_LABEL_RE = re.compile(
    r"\[([A-Za-z][A-Za-z0-9 /&'’-]{0,79})\]"
)
_EN_PRONOUN_RE = re.compile(
    r"\b(?:I|me|my|mine|myself|we|us|our|ours|ourselves|you|your|yours|yourself|"
    r"yourselves|he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b",
    re.IGNORECASE,
)
_EN_THIRD_PERSON_PRONOUN_RE = re.compile(
    r"\b(?:he|him|his|himself|she|her|hers|herself|they|them|their|theirs|"
    r"themselves)\b",
    re.IGNORECASE,
)


class QAResultError(ValueError):
    """Raised when an AI-helper result violates its immutable bundle contract."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _normalize_category(value: Any) -> str:
    """Collapse reviewer-specific labels into a stable report taxonomy."""
    label = re.sub(r"[^a-z0-9]+", "-", str(value or "").casefold()).strip("-")
    tokens = set(label.split("-"))
    if tokens & {"runtime", "control", "code"}:
        return "runtime"
    if "ui" in tokens:
        return "ui"
    if tokens & {"gameplay", "mechanics"}:
        return "gameplay"
    if tokens & {"wordplay", "comic", "timing", "pun"}:
        return "wordplay"
    if tokens & {"terminology", "consistency", "glossary", "name", "title"}:
        return "terminology"
    if tokens & {"voice", "tone", "characterization"}:
        return "voice"
    if tokens & {"formatting", "capitalization"}:
        return "formatting"
    if tokens & {"fluency", "grammar", "naturalness", "idiom", "agreement"}:
        return "fluency"
    if tokens & {
        "meaning", "accuracy", "context", "referent", "pronoun", "subject",
        "identity", "condition", "number", "modality", "action", "explicit",
    }:
        return "meaning"
    return "other"


def _normalize_family_key(value: Any) -> str:
    key = re.sub(r"\s+", " ", str(value or "").strip()).casefold()
    return key[:200]


def _fixed_source_key(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def _fixed_translation_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _audit_final_findings(
    findings: list[dict[str, Any]], context: dict[str, Any]
) -> None:
    """Stop publication when accepted corrections contradict fixed project wording."""
    quirks = str((context.get("quirks") or {}).get("text") or "")
    canonical: dict[str, set[str]] = defaultdict(set)
    for source, translation in _CANONICAL_QUIRK_MAPPING_RE.findall(quirks):
        source_parts = re.split(r"\s+/\s+", source)
        translation_parts = re.split(r"\s+/\s+", translation)
        mappings = (
            zip(source_parts, translation_parts, strict=True)
            if len(source_parts) > 1 and len(source_parts) == len(translation_parts)
            else ((source, translation),)
        )
        for mapped_source, mapped_translation in mappings:
            canonical[_fixed_source_key(mapped_source)].add(
                _fixed_translation_key(mapped_translation)
            )

    violations = []
    for finding in findings:
        expected = canonical.get(_fixed_source_key(finding.get("source"))) or set()
        if len(expected) != 1:
            continue
        correction = _fixed_translation_key(finding.get("correction"))
        if correction not in expected:
            violations.append(
                f"{finding['id']} conflicts with fixed wording "
                f"{next(iter(expected))!r}"
            )

    field_labels: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    for finding in findings:
        source_labels = _JAPANESE_FIELD_LABEL_RE.findall(
            str(finding.get("source") or "")
        )
        correction_labels = _ENGLISH_FIELD_LABEL_RE.findall(
            str(finding.get("correction") or "")
        )
        if not source_labels or len(source_labels) != len(correction_labels):
            continue
        for source_label, correction_label in zip(
            source_labels, correction_labels, strict=True
        ):
            field_labels[source_label][correction_label].add(finding["id"])
    for source_label, translations in sorted(field_labels.items()):
        if len(translations) < 2:
            continue
        rendered = ", ".join(
            f"{translation!r} ({', '.join(sorted(finding_ids))})"
            for translation, finding_ids in sorted(translations.items())
        )
        violations.append(
            f"structured field 【{source_label}】 has conflicting labels: {rendered}"
        )

    if violations:
        raise QAResultError(
            "Final editorial consistency audit failed; revise the named deep "
            "receipts and rebuild-final: " + "; ".join(violations)
        )


def _validate_editorial_basis(review: dict[str, Any], identity: str) -> None:
    """Require subjective findings to prove a defect rather than state a preference."""
    category = _normalize_category(review.get("category"))
    basis = review.get("editorial_basis")
    if category not in EDITORIAL_JUDGMENT_CATEGORIES:
        if basis is not None:
            raise QAResultError(
                f"Objective review cannot have editorial_basis for {identity}"
            )
        return
    if not isinstance(basis, dict) or set(basis) != {
        "defect", "source_support", "not_preference"
    }:
        raise QAResultError(
            f"Subjective actionable review needs editorial_basis for {identity}"
        )
    if not str(basis.get("defect") or "").strip():
        raise QAResultError(f"Editorial basis has no concrete defect for {identity}")
    if not str(basis.get("source_support") or "").strip():
        raise QAResultError(f"Editorial basis has no source support for {identity}")
    if basis.get("not_preference") is not True:
        raise QAResultError(f"Editorial basis is only a preference for {identity}")


def _engine_fingerprint() -> str:
    """Fingerprint every rule/configuration that affects reusable QA evidence."""
    contract = {
        "policy": QA_POLICY_VERSION,
        "engine_source_sha256": _sha256(Path(__file__).read_bytes()),
        "schemas": {
            "task": TASK_SCHEMA,
            "checkpoint": CHECKPOINT_SCHEMA,
            "bundle": BUNDLE_SCHEMA,
            "screen_result": SCREEN_RESULT_SCHEMA,
            "deep_result": DEEP_RESULT_SCHEMA,
            "findings": FINDINGS_SCHEMA,
        },
        "bundle_limits": {
            "screen_chars": DEFAULT_SCREEN_CHAR_BUDGET,
            "screen_items": DEFAULT_SCREEN_ITEM_LIMIT,
            "deep_chars": DEFAULT_DEEP_CHAR_BUDGET,
            "deep_items": DEFAULT_DEEP_ITEM_LIMIT,
        },
        "forced_deep_mechanical_flags": sorted(FORCED_DEEP_MECHANICAL_FLAGS),
        "forced_deep_event_codes": sorted(FORCED_DEEP_EVENT_CODES),
        "risk_cues": {
            label: pattern.pattern for label, pattern in sorted(_JP_RISK_CUES.items())
        },
        "screen_inconsistent_source_evidence": True,
    }
    return _sha256(_canonical_bytes(contract))


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_bytes(_canonical_bytes(value) + b"\n")
    temporary.replace(path)


def _atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(value.rstrip() + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _safe_task_root(output_root: str | Path, game_root: Path) -> Path:
    root = Path(output_root).expanduser().resolve()
    if root == game_root or game_root in root.parents:
        raise ValueError("QA task storage must be outside the selected game folder")
    root.mkdir(parents=True, exist_ok=True)
    return root


@contextmanager
def _task_lock(task_dir: Path):
    """Serialize cross-process checkpoint mutations for parallel helpers."""
    lock_path = task_dir / ".checkpoint.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return cleaned[:80] or "game"


def _read_optional(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {"path": "", "status": "missing", "sha256": "", "text": ""}
    resolved = path.expanduser().resolve()
    if not resolved.is_file() or resolved.is_symlink():
        return {
            "path": str(resolved),
            "status": "missing",
            "sha256": "",
            "text": "",
        }
    raw = resolved.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return {
            "path": str(resolved),
            "status": f"unreadable: {exc}",
            "sha256": _sha256(raw),
            "text": "",
        }
    return {
        "path": str(resolved),
        "status": "loaded" if text.strip() else "empty",
        "sha256": _sha256(raw),
        "text": text,
    }


def _context_pack(
    game_root: Path, current_sources: Iterable[str] = ()
) -> dict[str, Any]:
    skills_dir = game_root / GAME_SKILLS_RELATIVE
    reserved = {name.casefold() for name in GAME_SKILL_RESERVED_NAMES}
    overlay_paths = []
    if skills_dir.is_dir() and not skills_dir.is_symlink():
        for path in sorted(skills_dir.glob("*.md"), key=lambda item: item.name.casefold()):
            if path.name.casefold() in reserved:
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Unsafe custom QA context path: {path}")
            overlay_paths.append(path)
    glossary = _read_optional(game_root / GAME_GLOSSARY_RELATIVE)
    quirks = _read_optional(game_root / GAME_QUIRKS_RELATIVE)
    game = _read_optional(game_root / GAME_SKILL_RELATIVE)
    overlays = [_read_optional(path) for path in overlay_paths]
    pack = {
        "schema": "rpgmaker-qa-context-v2",
        "glossary": glossary,
        "quirks": quirks,
        "game": game,
        "overlays": overlays,
        "reference_translations": reference_context(game_root, current_sources),
    }
    pack["content_sha256"] = _sha256(_canonical_bytes(pack))
    return pack


def _glossary_pairs(text: str) -> list[tuple[str, str]]:
    pairs: dict[str, str] = {}
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _GLOSSARY_PAIR_RE.match(line)
        if match:
            source, target = match.group(1).strip(), match.group(2).strip()
            if source and target:
                pairs[source] = target
    return sorted(pairs.items(), key=lambda item: (-len(item[0]), item[0]))


def _record_maps(manifest: dict[str, Any]) -> tuple[dict[str, dict], dict[str, dict]]:
    records = {record["identity"]: record for record in manifest["records"]}
    clusters = {cluster["representative"]: cluster for cluster in manifest["clusters"]}
    return records, clusters


def _semantic_manifest_sha256(manifest: dict[str, Any]) -> str:
    """Hash inventory semantics while excluding recomputable detector evidence."""
    projection = {
        key: value for key, value in manifest.items() if key != "content_sha256"
    }
    projection["records"] = [
        {key: value for key, value in record.items() if key != "mechanical"}
        for record in manifest.get("records") or []
    ]
    return _sha256(_canonical_bytes(projection))


def _risk_reasons(
    cluster: dict[str, Any], records: dict[str, dict], glossary: list[tuple[str, str]]
) -> tuple[list[str], list[list[str]]]:
    members = [records[identity] for identity in cluster["identities"]]
    reasons: set[str] = set()
    for record in members:
        reasons.update(record.get("mechanical", {}).get("flags") or [])
        if record.get("event_code") == 102:
            reasons.add("choice")
        if record.get("classification") == "risky-codes":
            reasons.add("runtime-sensitive")
    source = str(cluster["source"])
    if len(source.strip()) <= 4:
        reasons.add("short-ambiguous")
    for label, pattern in _JP_RISK_CUES.items():
        if pattern.search(source):
            reasons.add(label)
    hits = [[src, dst] for src, dst in glossary if src in source]
    if hits:
        reasons.add("glossary")
    facets = {
        (
            record.get("file"),
            record.get("event_code"),
            (record.get("speaker") or {}).get("display_name", ""),
            record.get("display_shape"),
        )
        for record in members
    }
    if len(facets) > 1:
        reasons.add("multiple-contexts")
    return sorted(reasons), hits


def _compact_items(manifest: dict[str, Any], context: dict[str, Any]) -> list[dict]:
    records, clusters = _record_maps(manifest)
    glossary = _glossary_pairs(context["glossary"]["text"])
    live_by_source: dict[str, set[str]] = defaultdict(set)
    for cluster in manifest["clusters"]:
        live_by_source[str(cluster["source"])].add(str(cluster["live"]))
    items = []
    for ordinal, representative in enumerate(manifest["review_sequence"], start=1):
        cluster = clusters[representative]
        reasons, hits = _risk_reasons(cluster, records, glossary)
        alternatives = sorted(
            live for live in live_by_source[str(cluster["source"])]
            if live != str(cluster["live"])
        )
        if alternatives:
            reasons = sorted({*reasons, "inconsistent-source"})
        reference_rows = list(
            ((context.get("reference_translations") or {}).get("matches") or {}).get(
                str(cluster["source"]), []
            )
        )
        if reference_rows and any(
            str(row.get("translation") or "") != str(cluster["live"])
            for row in reference_rows
        ):
            reasons = sorted({*reasons, "reference-difference"})
        member_records = [records[identity] for identity in cluster["identities"]]
        speakers = sorted({
            str((record.get("speaker") or {}).get("display_name") or "")
            for record in member_records
            if str((record.get("speaker") or {}).get("display_name") or "")
        })
        item = {
            "ordinal": ordinal,
            "id": representative,
            "occurrences": len(cluster["identities"]),
            "context_facets": len({
                (
                    record.get("file"), record.get("event_code"),
                    (record.get("speaker") or {}).get("display_name", ""),
                    record.get("display_shape"),
                )
                for record in member_records
            }),
            "risk": reasons,
            "glossary": hits,
            "event_codes": sorted({
                int(record["event_code"])
                for record in member_records if record.get("event_code") is not None
            }),
            "speakers": speakers[:8],
            "display_shapes": sorted({
                str(record.get("display_shape") or "") for record in member_records
            }),
            "source": cluster["source"],
            "translation": cluster["live"],
        }
        if reference_rows:
            item["reference_translations"] = reference_rows
        if alternatives:
            item["same_source_alternatives"] = alternatives[:20]
        items.append(item)
    return items


def _cluster_by_identity(manifest: dict[str, Any]) -> dict[str, str]:
    return {
        identity: cluster["representative"]
        for cluster in manifest["clusters"]
        for identity in cluster["identities"]
    }


def _scene_position(record: dict[str, Any]) -> tuple[str, int] | None:
    """Return the owning command-list ID and command index for a dialogue record."""
    parts = _decode_pointer(str(record.get("source_pointer") or ""))
    list_positions = [index for index, part in enumerate(parts[:-1]) if part == "list"]
    if not list_positions:
        return None
    list_pos = list_positions[-1]
    try:
        command_index = int(parts[list_pos + 1])
    except (ValueError, IndexError):
        return None
    list_pointer = "/" + "/".join(
        part.replace("~", "~0").replace("/", "~1")
        for part in parts[: list_pos + 1]
    )
    return f"{record['file']}#{list_pointer}", command_index


def _scene_signature(records: list[dict[str, Any]]) -> str:
    content = [{
        "source": record["source"],
        "translation": record["live"],
        "speaker": (record.get("speaker") or {}).get("display_name", ""),
        "event_code": record.get("event_code"),
        "display_shape": record.get("display_shape"),
        "choice_context": record.get("choice_context"),
    } for record in records]
    return _sha256(_canonical_bytes(content))


def _pronoun_context_requirements(
    groups: list[dict[str, Any]], compact: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], set[str]]:
    """Return narrowly scoped repeated-scene targets that need local context."""
    groups_by_cluster: dict[str, list[dict[str, Any]]] = defaultdict(list)
    speakers_by_cluster: dict[str, set[str]] = defaultdict(set)
    for group in groups:
        for cluster_id in group["clusters"]:
            groups_by_cluster[cluster_id].append(group)
            speakers_by_cluster[cluster_id].update(
                group["cluster_speakers"].get(cluster_id, set())
            )

    requirements: dict[tuple[str, str], set[str]] = defaultdict(set)
    for cluster_id, contexts in groups_by_cluster.items():
        if len(contexts) < 2:
            continue
        translation = str(compact[cluster_id]["translation"])
        if _EN_THIRD_PERSON_PRONOUN_RE.search(translation):
            for group in contexts:
                requirements[(group["signature"], cluster_id)].add(
                    "repeated-third-person-context"
                )

        speakers = speakers_by_cluster[cluster_id]
        if len(speakers) < 2 or not _EN_PRONOUN_RE.search(translation):
            continue
        for speaker in sorted(speakers):
            candidates = [
                group for group in contexts
                if speaker in group["cluster_speakers"].get(cluster_id, set())
            ]
            if not candidates:
                continue
            chosen = min(candidates, key=lambda group: group["scene_id"])
            requirements[(chosen["signature"], cluster_id)].add(
                "cross-speaker-pronoun-context"
            )
    return requirements


def _scene_items(
    manifest: dict[str, Any], compact: dict[str, dict[str, Any]]
) -> tuple[list[dict[str, Any]], set[str], dict[str, dict[str, str]]]:
    """Build indivisible scenes that cover each dialogue cluster exactly once."""
    cluster_ids = _cluster_by_identity(manifest)
    scenes: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for record in manifest["records"]:
        if record.get("classification") != "dialogue":
            continue
        position = _scene_position(record)
        if position is None:
            continue
        scene_id, command_index = position
        scenes[scene_id].append((command_index, record))

    equivalent: dict[str, list[tuple[str, list[dict[str, Any]]]]] = defaultdict(list)
    for scene_id, positioned in scenes.items():
        ordered = [
            record for _index, record in sorted(
                positioned, key=lambda item: (item[0], item[1]["source_pointer"])
            )
        ]
        equivalent[_scene_signature(ordered)].append((scene_id, ordered))

    groups = []
    for signature, copies in equivalent.items():
        copies.sort(key=lambda item: item[0])
        scene_id, representative_records = copies[0]
        cluster_speakers: dict[str, set[str]] = defaultdict(set)
        for record in representative_records:
            speaker = str((record.get("speaker") or {}).get("display_name") or "")
            if speaker:
                cluster_speakers[cluster_ids[record["identity"]]].add(speaker)
        groups.append({
            "signature": signature,
            "scene_id": scene_id,
            "copies": copies,
            "records": representative_records,
            "clusters": {cluster_ids[record["identity"]] for record in representative_records},
            "cluster_speakers": cluster_speakers,
        })

    uncovered = set().union(*(group["clusters"] for group in groups)) if groups else set()
    selected_by_signature: dict[str, dict[str, Any]] = {}
    while uncovered:
        candidates = [
            (len(group["clusters"] & uncovered), group["scene_id"], group)
            for group in groups
            if group["clusters"] & uncovered
        ]
        _coverage, _scene_id, chosen = min(
            candidates, key=lambda item: (-item[0], item[1])
        )
        chosen = dict(chosen)
        chosen["targets"] = chosen["clusters"] & uncovered
        chosen["context_expansion"] = defaultdict(set)
        selected_by_signature[chosen["signature"]] = chosen
        uncovered.difference_update(chosen["targets"])

    groups_by_signature = {group["signature"]: group for group in groups}
    for (signature, cluster_id), reasons in _pronoun_context_requirements(
        groups, compact
    ).items():
        selected = selected_by_signature.get(signature)
        if selected is None:
            selected = dict(groups_by_signature[signature])
            selected["targets"] = set()
            selected["context_expansion"] = defaultdict(set)
            selected_by_signature[signature] = selected
        selected["targets"].add(cluster_id)
        selected["context_expansion"][cluster_id].update(reasons)

    selected = sorted(
        selected_by_signature.values(), key=lambda group: group["scene_id"]
    )

    items = []
    screen_index: dict[str, dict[str, str]] = {}
    for group in selected:
        signature = group["signature"]
        target_clusters = set(group["targets"])
        emitted_clusters: set[str] = set()
        lines = []
        for position, record in enumerate(group["records"]):
            cluster_id = cluster_ids[record["identity"]]
            line = {
                "source": record["source"],
                "translation": record["live"],
            }
            speaker = str((record.get("speaker") or {}).get("display_name") or "")
            if speaker:
                line["speaker"] = speaker
            if record.get("event_code") != 401:
                line["event_code"] = record.get("event_code")
            if cluster_id in target_clusters and cluster_id not in emitted_clusters:
                emitted_clusters.add(cluster_id)
                cluster_item = compact[cluster_id]
                review_id = "scene-target-" + _sha256(
                    f"{signature}\0{position}\0{cluster_id}"
                )[:20]
                line["id"] = review_id
                if cluster_item["risk"]:
                    line["risk"] = cluster_item["risk"]
                if cluster_item["glossary"]:
                    line["glossary"] = cluster_item["glossary"]
                if cluster_item.get("same_source_alternatives"):
                    line["same_source_alternatives"] = cluster_item[
                        "same_source_alternatives"
                    ]
                if cluster_item.get("reference_translations"):
                    line["reference_translations"] = cluster_item[
                        "reference_translations"
                    ]
                if record.get("choice_context"):
                    line["choice_context"] = record["choice_context"]
                context_expansion = sorted(
                    group["context_expansion"].get(cluster_id, set())
                )
                if context_expansion:
                    line["context_expansion"] = context_expansion
                screen_index[review_id] = {
                    "cluster_id": cluster_id,
                    "representative_identity": record["identity"],
                }
            else:
                context_id = "scene-context-" + _sha256(
                    f"{signature}\0{position}\0{cluster_id}\0context"
                )[:20]
                line["context_id"] = context_id
                screen_index[context_id] = {
                    "cluster_id": cluster_id,
                    "representative_identity": record["identity"],
                }
            lines.append(line)
        if emitted_clusters != target_clusters:
            raise ValueError("Scene target assignment lost a dialogue cluster")
        items.append({
            "kind": "scene",
            "id": "scene-" + group["signature"][:20],
            "scene_id": group["scene_id"],
            "scene_occurrences": len(group["copies"]),
            "target_count": len(target_clusters),
            "line_count": len(lines),
            "lines": lines,
        })
    items.sort(key=lambda item: _sha256("scene-screen-v1\0" + item["id"]))
    return items, {
        index_item["cluster_id"] for index_item in screen_index.values()
    }, screen_index


def _motif_seeds(quirks_text: str) -> list[dict[str, Any]]:
    seeds = []
    for raw in str(quirks_text or "").splitlines():
        guidance = raw.strip().lstrip("-* ").strip()
        if not guidance or not _MOTIF_GUIDANCE_RE.search(guidance):
            continue
        anchors = sorted(set(_JAPANESE_ANCHOR_RE.findall(guidance)))
        if not anchors:
            continue
        seeds.append({
            "id": "motif-" + _sha256(guidance)[:20],
            "guidance": guidance,
            "anchors": anchors,
        })
    return seeds


def _motif_items(
    manifest: dict[str, Any], context: dict[str, Any], compact: dict[str, dict[str, Any]],
    data_root: Path,
) -> list[dict[str, Any]]:
    records, clusters = _record_maps(manifest)
    document_cache: dict[str, Any] = {}
    items = []
    for seed in _motif_seeds(context["quirks"]["text"]):
        matching = [
            cluster for cluster in manifest["clusters"]
            if any(anchor in str(cluster["source"]) for anchor in seed["anchors"])
        ]
        if len(matching) < 2:
            continue
        variants = []
        for cluster in matching:
            cluster_id = cluster["representative"]
            representative = records[cluster["identities"][0]]
            item = compact[cluster_id]
            variants.append({
                "id": cluster_id,
                "representative_identity": representative["identity"],
                "occurrences": len(cluster["identities"]),
                "source": cluster["source"],
                "translation": cluster["live"],
                "speakers": item["speakers"],
                "risk": item["risk"],
                "nearby_commands": _nearby_commands(
                    data_root, representative, document_cache
                ),
            } | (
                {"reference_translations": item["reference_translations"]}
                if item.get("reference_translations") else {}
            ))
        variants.sort(key=lambda item: (item["source"], item["translation"], item["id"]))
        items.append({
            "kind": "motif-family",
            "id": seed["id"],
            "guidance": seed["guidance"],
            "anchors": seed["anchors"],
            "target_count": 1,
            "variant_count": len(variants),
            "variants": variants,
            "exclusive_bundle": True,
        })
    return items


def _screen_items(
    manifest: dict[str, Any], context: dict[str, Any], data_root: Path
) -> tuple[list[dict[str, Any]], dict[str, dict[str, str]]]:
    compact_items = _compact_items(manifest, context)
    compact = {item["id"]: item for item in compact_items}
    items: list[dict[str, Any]] = []
    covered_dialogue: set[str] = set()
    screen_index: dict[str, dict[str, str]] = {}
    if manifest["focus"] in {"dialogue", "release"}:
        scenes, covered_dialogue, screen_index = _scene_items(manifest, compact)
        items.extend(scenes)

    clusters = {
        cluster["representative"]: cluster for cluster in manifest["clusters"]
    }
    member_records = {
        record["identity"]: record for record in manifest["records"]
    }
    for item in compact_items:
        cluster = clusters[item["id"]]
        has_non_scene_member = any(
            member_records[identity].get("classification") != "dialogue"
            or _scene_position(member_records[identity]) is None
            for identity in cluster["identities"]
        )
        if (
            manifest["focus"] not in {"dialogue", "release"}
            or item["id"] not in covered_dialogue
            or (manifest["focus"] == "release" and has_non_scene_member)
        ):
            item = {**item, "kind": "cluster", "target_count": 1}
            items.append(item)

    if manifest["focus"] in {"dialogue", "release"}:
        items.extend(_motif_items(manifest, context, compact, data_root))

    # Preserve deterministic load balancing while assigning exact coverage ordinals.
    items.sort(key=lambda item: _sha256("rpgmaker-qa-screen-v3\0" + item["id"]))
    ordinal = 1
    for item in items:
        item["ordinal"] = ordinal
        if item["kind"] == "scene":
            for line in item["lines"]:
                if "id" in line:
                    line["ordinal"] = ordinal
                    ordinal += 1
        elif item["kind"] == "motif-family":
            ordinal += 1
        else:
            ordinal += 1
    return items, screen_index


def _forced_deep_reasons(item: dict[str, Any]) -> list[str]:
    """Return only high-confidence reasons that override a clean screen receipt."""
    reasons = {
        reason for reason in item.get("risk") or []
        if reason in FORCED_DEEP_MECHANICAL_FLAGS
    }
    if set(item.get("event_codes") or []) & FORCED_DEEP_EVENT_CODES:
        reasons.add("choice-context")
    return sorted(reasons)


def _candidate(reasons: Iterable[str], identities: Iterable[str] = ()) -> dict[str, Any]:
    return {
        "reasons": sorted(set(reasons)),
        "context_identities": sorted(set(identity for identity in identities if identity)),
    }


def _merge_candidate(
    candidates: dict[str, dict[str, Any]], cluster_id: str,
    reasons: Iterable[str], identities: Iterable[str] = (),
) -> None:
    existing = candidates.get(cluster_id) or _candidate(())
    candidates[cluster_id] = _candidate(
        [*(existing.get("reasons") or []), *reasons],
        [*(existing.get("context_identities") or []), *identities],
    )


def _bundle_items(
    items: list[dict], *, stage: str, char_budget: int, item_limit: int
) -> list[dict]:
    if char_budget < 2_000 or item_limit < 1:
        raise ValueError("QA bundle limits are too small")
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for item in items:
        size = len(_canonical_bytes(item))
        if item.get("exclusive_bundle"):
            if current:
                groups.append(current)
                current, current_chars = [], 0
            groups.append([item])
            continue
        if current and (len(current) >= item_limit or current_chars + size > char_budget):
            groups.append(current)
            current, current_chars = [], 0
        current.append(item)
        current_chars += size
    if current:
        groups.append(current)
    bundles = []
    for index, group in enumerate(groups, start=1):
        ordinals = []
        for item in group:
            if item.get("kind") == "scene":
                ordinals.extend(
                    line["ordinal"] for line in item["lines"] if "id" in line
                )
            elif item.get("kind") == "motif-family":
                ordinals.append(item["ordinal"])
            else:
                ordinals.append(item["ordinal"])
        item_count = sum(int(item.get("target_count", 1)) for item in group)
        bundle = {
            "schema": BUNDLE_SCHEMA,
            "stage": stage,
            "bundle_id": f"{stage}-{index:04d}",
            "ordinal_start": min(ordinals),
            "ordinal_end": max(ordinals),
            "item_count": item_count,
            "review_unit_count": len(group),
            "scene_count": sum(item.get("kind") == "scene" for item in group),
            "motif_count": sum(
                item.get("kind") == "motif-family" for item in group
            ),
            "items": group,
        }
        bundle["content_sha256"] = _sha256(_canonical_bytes(bundle))
        bundles.append(bundle)
    return bundles


def _write_bundles(
    task_dir: Path, bundles: list[dict], *, recorded_root: Path | None = None
) -> list[dict]:
    summaries = []
    stage = bundles[0]["stage"] if bundles else "screen"
    folder = task_dir / "bundles" / stage
    folder.mkdir(parents=True, exist_ok=True)
    for bundle in bundles:
        path = folder / f"{bundle['bundle_id']}.json"
        _atomic_write_json(path, bundle)
        recorded_path = (recorded_root or task_dir) / "bundles" / stage / path.name
        summaries.append({
            "id": bundle["bundle_id"],
            "path": str(recorded_path),
            "sha256": bundle["content_sha256"],
            "item_count": bundle["item_count"],
            "status": "pending",
            "assigned_to": "",
            "result_path": "",
        })
    return summaries


def _task_instructions(task_dir: Path, task: dict[str, Any]) -> str:
    cli = Path(__file__).resolve().parents[1] / "scripts" / "rpgmaker_qa.py"
    receipt_dir = (
        Path(task["game_root"]) / ".dazedtl" / "qa-receipts" / task_dir.name
    )
    if task["focus"] == "release":
        correction_workflow = f"""9. After every actionable correction passes, continue automatically; do not ask the user to
   approve stable finding IDs. Run
   `python "{cli}" corrections --task "{task_dir}" --approve-all`, followed by
   `python "{cli}" dry-run --task "{task_dir}"`, then
   `python "{cli}" apply --task "{task_dir}"`. The first command is restricted to the full-game
   release focus and refuses to proceed when unresolved `uncertain_playtests` remain. If it
   refuses, ask the user only about those named playtest/context decisions. After the user
   explicitly chooses to apply the independently verified findings while leaving those records
   unchanged, rerun corrections with `--approve-all --allow-uncertain`. Pause and report any
   deterministic audit, dry-run, apply, or regression error; never bypass a failed safeguard."""
    else:
        correction_workflow = f"""9. After every actionable correction passes, show the targeted findings to the user and wait
   for approval of specific stable IDs. Create and validate the selected correction map with
   `python "{cli}" corrections --task "{task_dir}" --approve QA-0001 ...` and
   `python "{cli}" dry-run --task "{task_dir}"`. Only then apply it with
   `python "{cli}" apply --task "{task_dir}"`. Targeted reruns never use `--approve-all`."""
    return f"""# AI-helper QA task

This task is managed by DazedTL. Do not create another manifest, index, checkpoint, registry,
or pipeline. Do not call a model-provider API; use the current AI helper for semantic review.
Do not edit the game during discovery.

Task directory: `{task_dir}`
Reviewer receipt workspace: `{receipt_dir}`

If the AI helper supports parallel reviewers, use two to four persistent workers. Each worker must
use a unique name with `next`; DazedTL assigns non-overlapping bundles and keeps global coverage.
Dialogue is scene-affine: every command-list scene is an indivisible review unit and can occur in
only one bundle. A bundle may contain multiple complete scenes, but workers must never split or
redistribute a scene outside the claim/release commands.

1. Read `context.json` once for the game glossary and translation guidance.
   If `reference_translations.status` is `ready`, use its exact Japanese-source matches as
   advisory evidence of established wording. A reference difference is a reason to compare
   referent, function, tone, and scene context—not an automatic defect. The current source and
   explicit current-game glossary remain authoritative.
2. Run `python "{cli}" status --task "{task_dir}"`.
3. Claim work with `python "{cli}" next --task "{task_dir}" --worker "<unique-worker-name>"`.
4. Read the returned immutable bundle and write the result schema described below. Create the
   reviewer receipt workspace above and write every temporary screen/deep result there using a
   unique filename containing its bundle ID. Never write `.qa-*.json` or `qa-*.json` in the game
   root. DazedTL copies accepted receipts into the managed task directory; the ignored workspace
   only preserves convenient reviewer history.
5. Submit it with `python "{cli}" accept --task "{task_dir}" --result "<result.json>"`.
6. Continue until `next` says the current stage is complete, then run
   `python "{cli}" advance --task "{task_dir}"` and continue the next stage.
7. When every deep bundle is accepted, run `python "{cli}" finalize --task "{task_dir}"`.
   Finalization audits exact mappings from the translation quirks and repeated structured UI
   headers across all proposed corrections. If it reports a conflict, do not present a partial
   report; reconcile the named deep receipts and run `rebuild-final` until the audit passes.
8. Before showing findings to the user, perform a final editorial pass over every actionable
   correction in `findings.json`. Prefer a reviewer who did not author the correction when another
   reviewer is available. Compare the source, current translation, correction, evidence, and
   supplied scene context. Confirm publication-ready meaning, natural English, speaker voice,
   terminology and honorific policy, runtime controls, line breaks, and dialogue or UI fit. Keep
   this pass scoped to the proposed findings; do not reopen clean inventory records. Do not edit
   `findings.json` directly. Treat stylistic preference as clean: change a line only when you can
   name a concrete defect, use the smallest natural correction that resolves it, and withdraw the
   finding when the current and proposed wordings are merely equally valid stylistic alternatives.
   For `fluency`, `voice`, and `wordplay`, require a reviewer who did not author the correction to
   independently confirm the recorded `editorial_basis`: the reader-facing defect, its source or
   scene support, and why the correction is not merely preferred wording. If independent review is
   unavailable or does not agree, withdraw the finding as clean before presenting results.
   If a correction needs revision, revise its corresponding deep result receipt, run
   `python "{cli}" rebuild-final --task "{task_dir}" --output-root
   "<separate-output-root>"`, and repeat this pass on the returned task.
{correction_workflow}

   DazedTL applies correction maps atomically and runs regression.
   If a final editorial adjustment is needed after approval but before applying, write one
   checksum-recorded review covering every approved finding exactly once, create its delta map
   with `python "{cli}" editorial-corrections --task "{task_dir}" --review
   "<editorial-review.json>"`, then run `editorial-dry-run` and `editorial-apply` instead of the
   ordinary `apply`. A rejected finding requires fresh user approval; use this route only for an
   accepted correction or a publication-ready wording revision within the approved finding scope.

   The editorial review format is:

```json
{{"schema":"{EDITORIAL_REVIEW_SCHEMA}","task":"{task_dir}","reviews":[{{"finding_id":"QA-0001","verdict":"accept"}},{{"finding_id":"QA-0002","verdict":"revise","replacement":"Publication-ready wording."}}]}}
```

   Every approved finding must occur exactly once. Use `accept` without a `replacement` when the
   approved correction is unchanged, `revise` with a replacement string for a wording adjustment,
   or `reject` to stop and obtain fresh approval.

For a screen bundle, inspect every target. A `scene` item contains one complete ordered `lines`
array; lines with an `id` are required review targets and lines with `context_id` were targeted in
another representative scene. Read every line so speaker continuity, callbacks, pronouns, and
comic timing remain visible. If this scene exposes a context-specific problem on a `context_id`
line, it may also be reported as an exception. A `cluster` item is isolated non-dialogue text. Omit
clean scene/cluster targets from
`exceptions`; one accepted bundle receipt covers them. `risk` values are attention hints, not
defects and not automatic deep-review instructions. When present, compare
`same_source_alternatives` for genuine consistency problems. When present, compare
`reference_translations` with the current wording, but accept a deliberate current-game
translation when the referent or context differs or older references conflict.

For every scene target, explicitly verify: who performs each action and to whom; pronouns,
possessives, and relationships; negation, conditions, certainty, and obligation; quantities and
chronology; omitted or invented information; and speaker voice plus natural English. A
`context_expansion` value means a repeated pronoun-bearing translation was intentionally assigned
in more than one scene. Judge it against this scene rather than assuming the wording that worked in
another context still works here.

A `motif-family` item gathers all translations matching one recurring-joke or wordplay rule from
the project's quirks. Return exactly one `motif_reviews` entry for every motif in the bundle,
including preserved families. Name concrete affected variant IDs in `suspect_ids`; do not flag
intentional functional variation merely because wording differs. Before marking a family
`preserved`, name the single recognizable English joke mechanism in the note and verify that every
nonliteral variant still reads as a callback to it; merely mentioning the same name is not enough.
Write:

```json
{{"schema":"{SCREEN_RESULT_SCHEMA}","bundle_id":"screen-0001","bundle_sha256":"...","reviewed_all":true,"exceptions":[{{"id":"scene-target-...","verdict":"suspect","categories":["meaning"],"note":"short concrete reason"}}],"motif_reviews":[{{"id":"motif-...","disposition":"preserved","note":"The English variants retain the named joke and its function.","suspect_ids":[]}}]}}
```

For a deep bundle, return exactly one review per item:

```json
{{"schema":"{DEEP_RESULT_SCHEMA}","bundle_id":"deep-0001","bundle_sha256":"...","reviews":[{{"id":"...","disposition":"clean","severity":null,"category":"","family_key":"","motif_ids":[],"evidence":"","correction":null,"apply_identities":[]}}]}}
```

Each deep item states the high-confidence `deep_reasons` that caused escalation. Do not expand the
queue yourself. `screen_evidence` preserves the screening reviewer's concrete reason, and
`screen_scene_contexts` preserves every complete scene used to reach that judgment. Explicitly
adjudicate that evidence; do not clear a screen suspect merely because its problem is absent from
the small `nearby_commands` window. A `clean` review for an item with `screen_evidence` must rebut
the screening rationale concretely in its own `evidence`; silent clearing is rejected.
`motif_contexts` contains the family-level wordplay review. When scene and motif evidence disagree,
reconcile both in the evidence for your disposition. If `deep_reasons` contains
`motif-scene-contradiction`, a scene reviewer disputed a wordplay variant after the family screen
called it preserved, so every family variant has been reopened. Judge each one against a single
recognizable English joke mechanism rather than accepting unrelated name-bearing phrases.
Set `motif_ids` to the exact bundle-provided motif IDs only when this review's correction or
playtest uncertainty actually concerns those joke mechanisms. Use an empty list for ordinary name
mentions, anchor collisions, and unrelated defects on a motif-matched line; motif summaries use
this attribution and must not claim that an unrelated correction is a family failure.

Use `actionable` only for a concrete source-supported defect with a supported correction; its
severity must be lowercase `critical`, `high`, or `medium`. Use `uncertain-playtest` for
runtime/context uncertainty and give its playtest reason in `evidence`. `apply_identities` may be
empty to target the whole exact cluster, or list only bundle-provided identity locators when the
correction is context-specific. Never write game files yourself.

For actionable reviews, use one category from: {", ".join(sorted(FINDING_CATEGORIES))}. Set
`family_key` to a reusable generic key when multiple lines express one underlying problem—for
example `term:黄泉の巌` or `ui:ＢＧＭ`; otherwise use an empty string. Clean and uncertain reviews
must use an empty `family_key`.

Actionable `fluency`, `voice`, and `wordplay` reviews must also include exactly this object:

```json
{{"editorial_basis":{{"defect":"Concrete reader-facing defect in the current wording.","source_support":"Source, scene, or project guidance that makes it defective.","not_preference":true}}}}
```

Do not use these categories for equally valid alternatives. Other categories and non-actionable
reviews must omit `editorial_basis`.

If a worker cannot finish an assigned bundle, release it with
`python "{cli}" release --task "{task_dir}" --bundle "<bundle-id>"`.
"""


def prepare_task(
    game_root: str | Path,
    data_root: str | Path,
    focus: str,
    output_root: str | Path,
    *,
    screen_char_budget: int = DEFAULT_SCREEN_CHAR_BUDGET,
    screen_item_limit: int = DEFAULT_SCREEN_ITEM_LIMIT,
) -> tuple[Path, dict[str, Any]]:
    """Create or reuse one immutable QA task and its exhaustive screen bundles."""
    game = Path(game_root).expanduser().resolve()
    data = Path(data_root).expanduser().resolve()
    if not game.is_dir() or not data.is_dir() or game not in data.parents:
        raise ValueError("The QA data folder must be inside the selected game folder")
    storage = _safe_task_root(output_root, game)
    manifest = build_manifest(data, focus)
    validation = verify_manifest(data, manifest)
    if not validation["valid"]:
        raise ValueError("QA inventory validation failed: " + "; ".join(validation["errors"]))
    context = _context_pack(
        game, (str(record.get("source") or "") for record in manifest["records"])
    )
    engine_fingerprint = _engine_fingerprint()
    screen_configuration = {
        "char_budget": int(screen_char_budget),
        "item_limit": int(screen_item_limit),
    }
    task_key = _sha256(
        f"{TASK_SCHEMA}\0{engine_fingerprint}\0{focus}\0"
        f"{manifest['content_sha256']}\0{context['content_sha256']}\0"
        f"{_sha256(_canonical_bytes(screen_configuration))}"
    )[:16]
    task_parent = storage / _slug(game.name) / focus
    task_parent.mkdir(parents=True, exist_ok=True)
    task_dir = task_parent / task_key
    with _task_lock(task_parent):
        existing = task_dir / "task.json"
        if existing.is_file():
            task = _read_json(existing)
            if task.get("schema") != TASK_SCHEMA:
                raise ValueError(f"Existing QA task has an unsupported schema: {task_dir}")
            return task_dir, status(task_dir)

        staging = Path(tempfile.mkdtemp(prefix=f".{task_key}.", dir=task_parent))
        try:
            write_manifest(manifest, staging / "inventory.json")
            _atomic_write_json(staging / "inventory-validation.json", validation)
            _atomic_write_json(staging / "context.json", context)
            compact_items = _compact_items(manifest, context)
            forced_candidates = {
                item["id"]: _candidate(forced_reasons)
                for item in compact_items
                if (forced_reasons := _forced_deep_reasons(item))
            }
            items, screen_index = _screen_items(manifest, context, data)
            screen_index_document = {
                "schema": "rpgmaker-qa-screen-index-v1",
                "targets": screen_index,
            }
            screen_index_document["content_sha256"] = _sha256(
                _canonical_bytes(screen_index_document)
            )
            _atomic_write_json(staging / "screen-index.json", screen_index_document)
            bundles = _bundle_items(
                items,
                stage="screen",
                char_budget=screen_char_budget,
                item_limit=screen_item_limit,
            )
            bundle_summaries = _write_bundles(
                staging, bundles, recorded_root=task_dir
            )
            task = {
                "schema": TASK_SCHEMA,
                "created_at": _utc_now(),
                "game_root": str(game),
                "data_root": str(data),
                "focus": focus,
                "engine_fingerprint": engine_fingerprint,
                "screen_configuration": screen_configuration,
                "manifest_sha256": manifest["content_sha256"],
                "context_sha256": context["content_sha256"],
                "screen_index_sha256": screen_index_document["content_sha256"],
                "counts": manifest["counts"],
            }
            checkpoint = {
                "schema": CHECKPOINT_SCHEMA,
                "task_sha256": _sha256(_canonical_bytes(task)),
                "updated_at": _utc_now(),
                "stage": "screen",
                "screen": {
                    "total_items": sum(
                        int(item.get("target_count", 1)) for item in items
                    ),
                    "accepted_items": 0,
                    "exception_ids": [],
                    "motif_total": sum(
                        item.get("kind") == "motif-family" for item in items
                    ),
                    "motif_accepted": 0,
                    "bundles": bundle_summaries,
                },
                "deep": {
                    "total_items": 0,
                    "accepted_items": 0,
                    "projected_items": len(forced_candidates),
                    "candidate_reasons": forced_candidates,
                    "bundles": [],
                },
                "findings_file": "",
            }
            _atomic_write_json(staging / "task.json", task)
            _atomic_write_json(staging / "checkpoint.json", checkpoint)
            _atomic_write_text(
                staging / "README.md", _task_instructions(task_dir, task)
            )
            staging.replace(task_dir)
        except Exception:
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise
    return task_dir, status(task_dir)


def _load_task(task_dir: str | Path) -> tuple[Path, dict, dict]:
    root = Path(task_dir).expanduser().resolve()
    task = _read_json(root / "task.json")
    checkpoint = _read_json(root / "checkpoint.json")
    if task.get("schema") != TASK_SCHEMA or checkpoint.get("schema") != CHECKPOINT_SCHEMA:
        raise ValueError(f"Unsupported or corrupt QA task: {root}")
    if task.get("engine_fingerprint") != _engine_fingerprint():
        raise ValueError(
            f"QA rules changed after this task was prepared; create a fresh task: {root}"
        )
    return root, task, checkpoint


def _stage_metrics(stage: dict[str, Any], *, active: bool) -> dict[str, Any]:
    bundles = stage["bundles"]
    assigned = [row for row in bundles if row["status"] == "assigned"]
    accepted = [row for row in bundles if row["status"] == "accepted"]
    starts = [
        datetime.fromisoformat(row["assigned_at"])
        for row in bundles if row.get("assigned_at")
    ]
    elapsed_seconds = 0.0
    if starts:
        if active:
            end = datetime.now(timezone.utc)
        else:
            accepted_times = [
                datetime.fromisoformat(row["accepted_at"])
                for row in accepted if row.get("accepted_at")
            ]
            end = max(accepted_times) if accepted_times else min(starts)
        elapsed_seconds = max(0.0, (end - min(starts)).total_seconds())
    accepted_items = int(stage["accepted_items"])
    items_per_minute = (
        accepted_items / elapsed_seconds * 60 if elapsed_seconds > 0 else 0.0
    )
    remaining = max(0, int(stage["total_items"]) - accepted_items)
    eta_seconds = remaining / (items_per_minute / 60) if items_per_minute else None
    return {
        "bundles_accepted": len(accepted),
        "bundles_assigned": len(assigned),
        "bundles_pending": sum(row["status"] == "pending" for row in bundles),
        "bundles_total": len(bundles),
        "assigned_workers": sorted({
            str(row.get("assigned_to") or "") for row in assigned
            if str(row.get("assigned_to") or "")
        }),
        "elapsed_seconds": round(elapsed_seconds, 1),
        "items_per_minute": round(items_per_minute, 1),
        "eta_seconds": round(eta_seconds, 1) if eta_seconds is not None else None,
    }


def status(task_dir: str | Path) -> dict[str, Any]:
    root, task, checkpoint = _load_task(task_dir)
    screen = checkpoint["screen"]
    deep = checkpoint["deep"]
    return {
        "task": str(root),
        "focus": task["focus"],
        "engine_fingerprint": task["engine_fingerprint"],
        "stage": checkpoint["stage"],
        "mechanical": {
            "checked": task["counts"]["records"],
            "total": task["counts"]["records"],
            "unresolved": task["counts"]["unresolved"],
        },
        "screen": {
            "accepted": screen["accepted_items"],
            "total": screen["total_items"],
            "exceptions": len(screen.get("exception_ids") or []),
            "motif_families": {
                "accepted": int(screen.get("motif_accepted", 0)),
                "total": int(screen.get("motif_total", 0)),
            },
            **_stage_metrics(screen, active=checkpoint["stage"] == "screen"),
        },
        "deep": {
            "accepted": deep["accepted_items"],
            "total": deep["total_items"],
            "projected": deep.get("projected_items", deep["total_items"]),
            **_stage_metrics(deep, active=checkpoint["stage"] == "deep"),
        },
        "findings_file": checkpoint.get("findings_file") or "",
    }


def next_bundle(task_dir: str | Path, worker: str) -> dict[str, Any] | None:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, task, checkpoint = _load_task(root)
        stage = checkpoint["stage"]
        if stage not in {"screen", "deep"}:
            return None
        bundles = checkpoint[stage]["bundles"]
        for row in bundles:
            if row["status"] == "assigned" and row.get("assigned_to") == worker:
                return copy.deepcopy(row)
        pending = next((row for row in bundles if row["status"] == "pending"), None)
        if pending is None:
            return None
        pending["status"] = "assigned"
        pending["assigned_to"] = str(worker or "worker")
        pending["assigned_at"] = _utc_now()
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
        return copy.deepcopy(pending)


def release_bundle(task_dir: str | Path, bundle_id: str) -> dict[str, Any]:
    """Return one unfinished assignment to the queue without changing coverage."""
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, _task, checkpoint = _load_task(root)
        _stage, row = _bundle_row(checkpoint, bundle_id)
        if row["status"] == "accepted":
            raise ValueError("An accepted QA bundle cannot be released")
        if row["status"] != "assigned":
            raise ValueError("Only an assigned QA bundle can be released")
        row["status"] = "pending"
        row["assigned_to"] = ""
        row.pop("assigned_at", None)
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


def _bundle_row(checkpoint: dict, bundle_id: str) -> tuple[str, dict]:
    for stage in ("screen", "deep"):
        for row in checkpoint[stage]["bundles"]:
            if row["id"] == bundle_id:
                return stage, row
    raise QAResultError(f"Unknown bundle id {bundle_id!r}")


def _load_screen_index(root: Path, task: dict[str, Any]) -> dict[str, dict[str, str]]:
    document = _read_json(root / "screen-index.json")
    checksum_value = dict(document)
    claimed = checksum_value.pop("content_sha256", "")
    if (
        document.get("schema") != "rpgmaker-qa-screen-index-v1"
        or claimed != _sha256(_canonical_bytes(checksum_value))
        or claimed != task.get("screen_index_sha256")
    ):
        raise QAResultError("Screen target index checksum is invalid")
    targets = document.get("targets")
    if not isinstance(targets, dict):
        raise QAResultError("Screen target index is invalid")
    return targets


def _screen_target_map(
    bundle: dict[str, Any], screen_index: dict[str, dict[str, str]] | None = None
) -> dict[str, dict[str, Any]]:
    targets: dict[str, dict[str, Any]] = {}
    for item in bundle["items"]:
        if item.get("kind") == "scene":
            candidates = [
                {**line, "id": line.get("id") or line["context_id"]}
                for line in item["lines"]
                if "id" in line or "context_id" in line
            ]
        elif item.get("kind") == "cluster":
            candidates = [{**item, "cluster_id": item["id"]}]
        else:
            continue
        for target in candidates:
            identity = target["id"]
            if identity in targets:
                raise QAResultError(f"Duplicate screen target {identity!r}")
            targets[identity] = {
                **target,
                **((screen_index or {}).get(identity) or {}),
            }
    return targets


def _screen_motif_map(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["id"]: item for item in bundle["items"]
        if item.get("kind") == "motif-family"
    }


def _validate_screen_result(bundle: dict, result: dict) -> None:
    if result.get("schema") != SCREEN_RESULT_SCHEMA:
        raise QAResultError("Screen result has the wrong schema")
    if result.get("reviewed_all") is not True:
        raise QAResultError("Screen result must confirm reviewed_all=true")
    allowed = set(_screen_target_map(bundle))
    seen: set[str] = set()
    exceptions = result.get("exceptions")
    if not isinstance(exceptions, list):
        raise QAResultError("Screen result exceptions must be a list")
    for item in exceptions:
        if not isinstance(item, dict):
            raise QAResultError("Screen exception must be an object")
        identity = str(item.get("id") or "")
        if identity not in allowed or identity in seen:
            raise QAResultError(f"Invalid or duplicate screen identity {identity!r}")
        seen.add(identity)
        if item.get("verdict") not in SCREEN_VERDICTS:
            raise QAResultError(f"Invalid screen verdict for {identity}")
        categories = item.get("categories")
        if not isinstance(categories, list) or not all(
            isinstance(value, str) and value.strip() for value in categories
        ):
            raise QAResultError(f"Screen categories are invalid for {identity}")
        if not str(item.get("note") or "").strip():
            raise QAResultError(f"Screen exception has no reason for {identity}")

    expected_motifs = _screen_motif_map(bundle)
    motif_reviews = result.get("motif_reviews")
    if not isinstance(motif_reviews, list):
        raise QAResultError("Screen result motif_reviews must be a list")
    actual_motifs = [
        str(item.get("id") or "") for item in motif_reviews
        if isinstance(item, dict)
    ]
    if len(actual_motifs) != len(set(actual_motifs)) or set(actual_motifs) != set(
        expected_motifs
    ):
        raise QAResultError("Screen result must review every assigned motif exactly once")
    for review in motif_reviews:
        motif_id = review["id"]
        disposition = review.get("disposition")
        if disposition not in MOTIF_DISPOSITIONS:
            raise QAResultError(f"Invalid motif disposition for {motif_id}")
        if not str(review.get("note") or "").strip():
            raise QAResultError(f"Motif review has no evidence for {motif_id}")
        suspect_ids = review.get("suspect_ids")
        if not isinstance(suspect_ids, list):
            raise QAResultError(f"Motif suspect_ids are invalid for {motif_id}")
        allowed_variants = {
            variant["id"] for variant in expected_motifs[motif_id]["variants"]
        }
        if len(suspect_ids) != len(set(suspect_ids)) or not set(
            suspect_ids
        ).issubset(allowed_variants):
            raise QAResultError(f"Motif suspect_ids are invalid for {motif_id}")
        if disposition == "preserved" and suspect_ids:
            raise QAResultError(f"Preserved motif cannot name suspects for {motif_id}")
        if disposition != "preserved" and not suspect_ids:
            raise QAResultError(f"Non-clean motif must name suspects for {motif_id}")


def _validate_deep_result(bundle: dict, result: dict) -> None:
    if result.get("schema") != DEEP_RESULT_SCHEMA:
        raise QAResultError("Deep result has the wrong schema")
    expected = {item["id"] for item in bundle["items"]}
    reviews = result.get("reviews")
    if not isinstance(reviews, list):
        raise QAResultError("Deep result reviews must be a list")
    actual = [str(item.get("id") or "") for item in reviews if isinstance(item, dict)]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise QAResultError("Deep result must contain every assigned identity exactly once")
    bundle_items = {item["id"]: item for item in bundle["items"]}
    for review in reviews:
        identity = review["id"]
        disposition = review.get("disposition")
        if disposition not in DEEP_DISPOSITIONS:
            raise QAResultError(f"Invalid deep disposition for {identity}")
        if disposition == "actionable":
            if review.get("severity") not in SEVERITIES:
                raise QAResultError(f"Actionable review has invalid severity for {identity}")
            if _normalize_category(review.get("category")) not in FINDING_CATEGORIES:
                raise QAResultError(f"Actionable review has invalid category for {identity}")
            if not str(review.get("evidence") or "").strip():
                raise QAResultError(f"Actionable review has no evidence for {identity}")
            correction = review.get("correction")
            if not isinstance(correction, str) or not correction.strip():
                raise QAResultError(f"Actionable review has no correction for {identity}")
            _validate_editorial_basis(review, identity)
        elif review.get("severity") not in {None, ""}:
            raise QAResultError(f"Non-actionable review cannot have severity for {identity}")
        elif review.get("editorial_basis") is not None:
            raise QAResultError(
                f"Non-actionable review cannot have editorial_basis for {identity}"
            )
        if (
            disposition == "clean"
            and bundle_items[identity].get("screen_evidence")
            and not str(review.get("evidence") or "").strip()
        ):
            raise QAResultError(
                f"Clean review must rebut preserved screen evidence for {identity}"
            )
        if disposition == "uncertain-playtest" and not str(
            review.get("evidence") or ""
        ).strip():
            raise QAResultError(f"Uncertain review has no playtest reason for {identity}")
        family_key = review.get("family_key")
        if not isinstance(family_key, str):
            raise QAResultError(f"Review has invalid family_key for {identity}")
        if disposition != "actionable" and family_key.strip():
            raise QAResultError(f"Non-actionable review cannot have family_key for {identity}")
        apply_ids = review.get("apply_identities") or []
        allowed_ids = set(bundle_items[identity].get("identities") or [])
        if not isinstance(apply_ids, list) or not set(apply_ids).issubset(allowed_ids):
            raise QAResultError(f"Invalid apply_identities for {identity}")
        motif_ids = review.get("motif_ids") or []
        allowed_motif_ids = {
            str(context.get("id") or "")
            for context in bundle_items[identity].get("motif_contexts") or []
        }
        if (
            not isinstance(motif_ids, list)
            or len(motif_ids) != len(set(motif_ids))
            or not set(motif_ids).issubset(allowed_motif_ids)
        ):
            raise QAResultError(f"Invalid motif_ids for {identity}")
        if motif_ids and disposition == "clean":
            raise QAResultError(f"Clean review cannot attribute a motif for {identity}")
        if (
            motif_ids
            and disposition == "actionable"
            and _normalize_category(review.get("category")) != "wordplay"
        ):
            raise QAResultError(
                f"Motif-attributed actionable review must use wordplay for {identity}"
            )


def accept_result(task_dir: str | Path, result_path: str | Path) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        root, task, checkpoint = _load_task(root)
        result = _read_json(Path(result_path).expanduser().resolve())
        bundle_id = str(result.get("bundle_id") or "")
        stage, row = _bundle_row(checkpoint, bundle_id)
        bundle = _read_json(Path(row["path"]))
        if result.get("bundle_sha256") != row["sha256"]:
            raise QAResultError("Result does not match the immutable bundle checksum")
        if stage == "screen":
            _validate_screen_result(bundle, result)
        else:
            _validate_deep_result(bundle, result)
        canonical_path = root / "results" / stage / f"{bundle_id}.json"
        if row["status"] == "accepted" and canonical_path.is_file():
            if _read_json(canonical_path) != result:
                raise QAResultError("An accepted bundle result cannot be replaced")
            return status(root)
        _atomic_write_json(canonical_path, result)
        if stage == "screen":
            exception_ids = checkpoint["screen"].setdefault("exception_ids", [])
            candidate_reasons = checkpoint["deep"].setdefault(
                "candidate_reasons", {}
            )
            screen_targets = _screen_target_map(
                bundle, _load_screen_index(root, task)
            )
            for exception in result["exceptions"]:
                review_id = exception["id"]
                target = screen_targets[review_id]
                cluster_id = target.get("cluster_id") or review_id
                exception_ids.append(review_id)
                _merge_candidate(
                    candidate_reasons,
                    cluster_id,
                    [f"screen-{exception['verdict']}"],
                    [target.get("representative_identity", "")],
                )
            motifs = _screen_motif_map(bundle)
            for review in result["motif_reviews"]:
                if review["disposition"] == "preserved":
                    continue
                motif = motifs[review["id"]]
                variants = {variant["id"]: variant for variant in motif["variants"]}
                for cluster_id in review["suspect_ids"]:
                    variant = variants[cluster_id]
                    _merge_candidate(
                        candidate_reasons,
                        cluster_id,
                        [f"motif-{review['disposition']}"],
                        [variant["representative_identity"]],
                    )
            checkpoint["screen"]["motif_accepted"] = int(
                checkpoint["screen"].get("motif_accepted", 0)
            ) + len(result["motif_reviews"])
            checkpoint["deep"]["projected_items"] = len(candidate_reasons)
        checkpoint[stage]["accepted_items"] += int(row["item_count"])
        row["status"] = "accepted"
        row["result_path"] = str(canonical_path)
        row["accepted_at"] = _utc_now()
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


def _decode_pointer(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON pointer {pointer!r}")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _resolve_parts(value: Any, parts: Iterable[str]) -> Any:
    current = value
    for part in parts:
        if isinstance(current, list):
            current = current[int(part)]
        else:
            current = current[part]
    return current


def _nearby_commands(data_root: Path, record: dict, cache: dict[str, Any]) -> list[dict]:
    parts = _decode_pointer(record["source_pointer"])
    list_positions = [index for index, part in enumerate(parts[:-1]) if part == "list"]
    if not list_positions:
        return []
    list_pos = list_positions[-1]
    try:
        command_index = int(parts[list_pos + 1])
    except (ValueError, IndexError):
        return []
    filename = record["file"]
    if filename not in cache:
        cache[filename] = json.loads((data_root / filename).read_text(encoding="utf-8-sig"))
    commands = _resolve_parts(cache[filename], parts[: list_pos + 1])
    if not isinstance(commands, list):
        return []
    compact = []
    for index in range(max(0, command_index - 3), min(len(commands), command_index + 4)):
        command = commands[index]
        if not isinstance(command, dict):
            continue
        compact.append({
            "index": index,
            "code": command.get("code"),
            "indent": command.get("indent"),
            "parameters": command.get("parameters"),
            "original": command.get("_original"),
        })
    return compact


def _screen_handoff_context(
    root: Path,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
    dict[str, list[dict[str, Any]]],
]:
    """Recover accepted screen rationale, full scenes, and motif adjudication."""
    task = _read_json(root / "task.json")
    checkpoint = _read_json(root / "checkpoint.json")
    screen_index = _load_screen_index(root, task)
    evidence: dict[str, list[dict[str, Any]]] = defaultdict(list)
    scenes: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    motifs: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in checkpoint["screen"]["bundles"]:
        if row.get("status") != "accepted" or not row.get("result_path"):
            continue
        bundle = _read_json(Path(row["path"]))
        result = _read_json(Path(row["result_path"]))
        target_scenes: dict[str, dict[str, Any]] = {}
        motif_items = _screen_motif_map(bundle)
        for item in bundle["items"]:
            if item.get("kind") != "scene":
                continue
            scene = {
                "scene_id": item["scene_id"],
                "line_count": item["line_count"],
                "lines": item["lines"],
            }
            for line in item["lines"]:
                target_id = line.get("id") or line.get("context_id")
                if target_id:
                    target_scenes[target_id] = scene

        for exception in result["exceptions"]:
            target_id = exception["id"]
            target = screen_index.get(target_id) or {}
            cluster_id = target.get("cluster_id") or target_id
            evidence[cluster_id].append({
                "target_id": target_id,
                "verdict": exception["verdict"],
                "categories": list(exception["categories"]),
                "note": exception["note"],
            })
            scene = target_scenes.get(target_id)
            if scene:
                scenes[cluster_id][scene["scene_id"]] = scene

        for review in result["motif_reviews"]:
            motif = motif_items[review["id"]]
            context = {
                "id": motif["id"],
                "guidance": motif["guidance"],
                "anchors": motif["anchors"],
                "variant_count": motif["variant_count"],
                "variants": motif["variants"],
                "disposition": review["disposition"],
                "note": review["note"],
                "suspect_ids": review["suspect_ids"],
            }
            for variant in motif["variants"]:
                motifs[variant["id"]].append(context)

    return (
        {key: value for key, value in evidence.items()},
        {key: list(value.values()) for key, value in scenes.items()},
        {key: value for key, value in motifs.items()},
    )


def _reopen_disputed_preserved_motifs(
    candidate_reasons: dict[str, dict[str, Any]],
    screen_evidence: dict[str, list[dict[str, Any]]],
    motif_contexts: dict[str, list[dict[str, Any]]],
) -> None:
    """Deep-review a whole preserved motif when scene evidence disputes its wordplay."""
    disputed = {
        motif["id"]
        for cluster_id, evidence_rows in screen_evidence.items()
        if cluster_id in candidate_reasons
        and any(
            _normalize_category(category) == "wordplay"
            for evidence in evidence_rows
            for category in evidence.get("categories") or []
        )
        for motif in motif_contexts.get(cluster_id) or []
        if motif.get("disposition") == "preserved"
    }
    if not disputed:
        return

    for cluster_id, contexts in motif_contexts.items():
        for motif in contexts:
            if motif.get("id") not in disputed:
                continue
            variant = next(
                (
                    item for item in motif.get("variants") or []
                    if item.get("id") == cluster_id
                ),
                {},
            )
            _merge_candidate(
                candidate_reasons,
                cluster_id,
                ["motif-scene-contradiction"],
                [str(variant.get("representative_identity") or "")],
            )
            break


def _motif_translation_roster(context: dict[str, Any]) -> dict[str, Any]:
    """Keep family-wide comparison evidence without repeating every context window."""
    return {
        key: value for key, value in context.items() if key != "variants"
    } | {
        "variants": [
            {
                key: variant[key]
                for key in ("source", "translation")
                if key in variant
            }
            for variant in context.get("variants") or []
        ]
    }


def _deep_items(
    root: Path, candidate_reasons: dict[str, dict[str, Any]]
) -> list[dict]:
    manifest = _read_json(root / "inventory.json")
    context = _read_json(root / "context.json")
    records, clusters = _record_maps(manifest)
    compact = {item["id"]: item for item in _compact_items(manifest, context)}
    by_source: dict[str, list[dict]] = defaultdict(list)
    for cluster in manifest["clusters"]:
        by_source[cluster["source"]].append(cluster)
    data_root = Path(_read_json(root / "task.json")["data_root"])
    document_cache: dict[str, Any] = {}
    screen_evidence, screen_scenes, motif_contexts = _screen_handoff_context(root)
    _reopen_disputed_preserved_motifs(
        candidate_reasons, screen_evidence, motif_contexts
    )
    items = []
    for identity in manifest["review_sequence"]:
        if identity not in candidate_reasons:
            continue
        cluster = clusters[identity]
        member_records = [records[item] for item in cluster["identities"]]
        candidate = candidate_reasons[identity]
        context_identities = [
            item for item in candidate.get("context_identities") or []
            if item in records and item in cluster["identities"]
        ]
        representative = (
            records[context_identities[0]] if context_identities else member_records[0]
        )
        alternatives = sorted({
            other["live"] for other in by_source[cluster["source"]]
            if other["live"] != cluster["live"]
        })
        item = {
            **compact[identity],
            "deep_reasons": list(candidate.get("reasons") or []),
            "identities": list(cluster["identities"]),
            "screen_context_identities": context_identities,
            "locators": [{
                "identity": record["identity"],
                "file": record["file"],
                "source_pointer": record["source_pointer"],
                "live_pointers": record["live_pointers"],
                "event_code": record.get("event_code"),
                "speaker": record.get("speaker"),
                "database_entity": record.get("database_entity"),
                "choice_context": record.get("choice_context"),
            } for record in member_records],
            "nearby_commands": _nearby_commands(data_root, representative, document_cache),
            "suspect_contexts": [{
                "identity": context_identity,
                "nearby_commands": _nearby_commands(
                    data_root, records[context_identity], document_cache
                ),
            } for context_identity in context_identities[:4]],
            "same_source_alternatives": alternatives[:20],
        }
        if screen_evidence.get(identity):
            item["screen_evidence"] = screen_evidence[identity]
        if screen_scenes.get(identity):
            item["screen_scene_contexts"] = screen_scenes[identity]
        if motif_contexts.get(identity):
            contexts = motif_contexts[identity]
            if "motif-scene-contradiction" in item["deep_reasons"]:
                contexts = [_motif_translation_roster(value) for value in contexts]
            item["motif_contexts"] = contexts
        items.append(item)
    return items


def _advance_unlocked(task_dir: str | Path) -> dict[str, Any]:
    root, _task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] != "screen":
        return status(root)
    if any(row["status"] != "accepted" for row in checkpoint["screen"]["bundles"]):
        raise ValueError("Every screen bundle must be accepted before deep review")
    candidate_reasons = checkpoint["deep"].get("candidate_reasons") or {}
    deep_items = _deep_items(root, candidate_reasons)
    bundles = _bundle_items(
        deep_items,
        stage="deep",
        char_budget=DEFAULT_DEEP_CHAR_BUDGET,
        item_limit=DEFAULT_DEEP_ITEM_LIMIT,
    ) if deep_items else []
    checkpoint["deep"] = {
        "total_items": len(deep_items),
        "accepted_items": 0,
        "projected_items": len(deep_items),
        "candidate_reasons": candidate_reasons,
        "bundles": _write_bundles(root, bundles) if bundles else [],
    }
    checkpoint["stage"] = "deep" if bundles else "ready-finalize"
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


def advance(task_dir: str | Path) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        return _advance_unlocked(root)


def rebuild_deep_from_screen(
    source_task_dir: str | Path, output_root: str | Path | None = None
) -> tuple[Path, dict[str, Any]]:
    """Create a current task by replaying immutable receipts from a completed screen."""
    source = Path(source_task_dir).expanduser().resolve()
    source_task = _read_json(source / "task.json")
    source_checkpoint = _read_json(source / "checkpoint.json")
    if (
        source_task.get("schema") != TASK_SCHEMA
        or source_checkpoint.get("schema") != CHECKPOINT_SCHEMA
        or source_checkpoint.get("task_sha256")
        != _sha256(_canonical_bytes(source_task))
    ):
        raise ValueError(f"Unsupported or corrupt source QA task: {source}")
    source_rows = source_checkpoint["screen"]["bundles"]
    if (
        not source_rows
        or any(row.get("status") != "accepted" for row in source_rows)
        or source_checkpoint["screen"]["accepted_items"]
        != source_checkpoint["screen"]["total_items"]
    ):
        raise ValueError("The source task must have a fully accepted screen stage")

    reusable_results: dict[str, Path] = {}
    reusable_summaries: dict[str, tuple[str, int]] = {}
    for row in source_rows:
        bundle_path = source / "bundles" / "screen" / f"{row['id']}.json"
        result_path = source / "results" / "screen" / f"{row['id']}.json"
        bundle = _read_json(bundle_path)
        checksum_value = dict(bundle)
        claimed = checksum_value.pop("content_sha256", "")
        if (
            bundle.get("schema") != BUNDLE_SCHEMA
            or bundle.get("stage") != "screen"
            or bundle.get("bundle_id") != row["id"]
            or claimed != row.get("sha256")
            or claimed != _sha256(_canonical_bytes(checksum_value))
        ):
            raise ValueError(f"Source screen bundle checksum is invalid: {row['id']}")
        result = _read_json(result_path)
        if result.get("bundle_sha256") != claimed:
            raise ValueError(f"Source screen result checksum is invalid: {row['id']}")
        _validate_screen_result(bundle, result)
        reusable_results[row["id"]] = result_path
        reusable_summaries[row["id"]] = (claimed, int(row["item_count"]))

    destination_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else source.parents[2]
    )
    rebuilt, _state = prepare_task(
        source_task["game_root"],
        source_task["data_root"],
        source_task["focus"],
        destination_root,
        screen_char_budget=int(
            (source_task.get("screen_configuration") or {}).get(
                "char_budget", DEFAULT_SCREEN_CHAR_BUDGET
            )
        ),
        screen_item_limit=int(
            (source_task.get("screen_configuration") or {}).get(
                "item_limit", DEFAULT_SCREEN_ITEM_LIMIT
            )
        ),
    )
    if rebuilt == source:
        raise ValueError("The source task already uses the current QA rules")
    _rebuilt_root, rebuilt_task, rebuilt_checkpoint = _load_task(rebuilt)
    for key in ("manifest_sha256", "context_sha256"):
        if rebuilt_task.get(key) != source_task.get(key):
            raise ValueError(f"Cannot reuse screening after {key} changed")
    rebuilt_summaries = {
        row["id"]: (row["sha256"], int(row["item_count"]))
        for row in rebuilt_checkpoint["screen"]["bundles"]
    }
    if rebuilt_summaries != reusable_summaries:
        raise ValueError("Current screen bundles differ; screening cannot be reused")

    if rebuilt_checkpoint["stage"] == "screen":
        for bundle_id in sorted(reusable_results):
            accept_result(rebuilt, reusable_results[bundle_id])
        return rebuilt, advance(rebuilt)
    return rebuilt, status(rebuilt)


def _finalize_unlocked(task_dir: str | Path) -> dict[str, Any]:
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] == "screen":
        raise ValueError("Advance the completed screen stage first")
    if any(row["status"] != "accepted" for row in checkpoint["deep"]["bundles"]):
        raise ValueError("Every deep-review bundle must be accepted before finalizing")
    manifest = _read_json(root / "inventory.json")
    _records, clusters = _record_maps(manifest)
    findings = []
    uncertain = []
    motif_families = []
    deep_dispositions: dict[str, str] = {}
    deep_motif_attributions: dict[str, set[str] | None] = {}
    for row in checkpoint["screen"]["bundles"]:
        bundle = _read_json(Path(row["path"]))
        motifs = _screen_motif_map(bundle)
        if not motifs:
            continue
        result = _read_json(Path(row["result_path"]))
        for review in result["motif_reviews"]:
            motif = motifs[review["id"]]
            motif_families.append({
                "id": review["id"],
                "guidance": motif["guidance"],
                "anchors": motif["anchors"],
                "variant_count": len(motif["variants"]),
                "disposition": review["disposition"],
                "note": review["note"],
                "suspect_ids": review["suspect_ids"],
                "screen_review": {
                    "disposition": review["disposition"],
                    "note": review["note"],
                    "suspect_ids": review["suspect_ids"],
                },
                "_variant_ids": [variant["id"] for variant in motif["variants"]],
            })
    for row in checkpoint["deep"]["bundles"]:
        result = _read_json(Path(row["result_path"]))
        for review in result["reviews"]:
            deep_dispositions[review["id"]] = review["disposition"]
            deep_motif_attributions[review["id"]] = (
                set(review.get("motif_ids") or [])
                if "motif_ids" in review
                else None
            )
            if review["disposition"] == "actionable":
                cluster = clusters[review["id"]]
                target_ids = review.get("apply_identities") or cluster["identities"]
                findings.append({
                    "id": "",
                    "cluster_id": review["id"],
                    "severity": review["severity"],
                    "category": _normalize_category(review.get("category")),
                    "family_key": _normalize_family_key(review.get("family_key")),
                    "evidence": review["evidence"],
                    "source": cluster["source"],
                    "current": cluster["live"],
                    "correction": review["correction"],
                    "target_identities": target_ids,
                    **(
                        {"editorial_basis": review["editorial_basis"]}
                        if _normalize_category(review.get("category"))
                        in EDITORIAL_JUDGMENT_CATEGORIES
                        else {}
                    ),
                })
            elif review["disposition"] == "uncertain-playtest":
                uncertain.append(review)
    findings.sort(key=lambda item: (
        {"critical": 0, "high": 1, "medium": 2}[item["severity"]],
        item["cluster_id"],
    ))
    for index, finding in enumerate(findings, start=1):
        finding["id"] = f"QA-{index:04d}"
    _audit_final_findings(findings, _read_json(root / "context.json"))
    finding_by_cluster = {item["cluster_id"]: item for item in findings}
    uncertain_ids = {item["id"] for item in uncertain}
    for motif in motif_families:
        variant_ids = set(motif.pop("_variant_ids"))
        screen_review = motif["screen_review"]
        screen_suspects = set(screen_review["suspect_ids"])
        actionable_variants = sorted(
            cluster_id
            for cluster_id in variant_ids & set(finding_by_cluster)
            if (
                motif["id"] in deep_motif_attributions[cluster_id]
                if deep_motif_attributions.get(cluster_id) is not None
                else (
                    cluster_id in screen_suspects
                    and finding_by_cluster[cluster_id]["category"] == "wordplay"
                )
            )
        )
        uncertain_variants = sorted(
            cluster_id
            for cluster_id in variant_ids & uncertain_ids
            if (
                motif["id"] in deep_motif_attributions[cluster_id]
                if deep_motif_attributions.get(cluster_id) is not None
                else cluster_id in screen_suspects
            )
        )
        finding_ids = [finding_by_cluster[item]["id"] for item in actionable_variants]
        cleared_screen_suspects = sorted(
            item for item in screen_suspects
            if deep_dispositions.get(item) == "clean"
        )
        if actionable_variants:
            motif["disposition"] = "suspect"
            motif["suspect_ids"] = sorted(
                screen_suspects | set(actionable_variants) | set(uncertain_variants)
            )
            motif["note"] = (
                "Deep review superseded the screen receipt: "
                f"{len(actionable_variants)} variant(s) are actionable; "
                f"see {', '.join(finding_ids)}."
            )
        elif uncertain_variants:
            motif["disposition"] = "uncertain-playtest"
            motif["suspect_ids"] = sorted(screen_suspects | set(uncertain_variants))
            motif["note"] = (
                "Deep review superseded the screen receipt: "
                f"{len(uncertain_variants)} variant(s) require playtesting."
            )
        elif screen_suspects and len(cleared_screen_suspects) == len(screen_suspects):
            motif["disposition"] = "preserved"
            motif["suspect_ids"] = []
            motif["note"] = (
                "Deep review cleared every variant suspected by the screen receipt."
            )
        motif["deep_reconciliation"] = {
            "actionable_variant_ids": actionable_variants,
            "uncertain_variant_ids": uncertain_variants,
            "cleared_screen_suspect_ids": cleared_screen_suspects,
            "finding_ids": finding_ids,
        }
    family_members: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for finding in findings:
        if finding["family_key"]:
            family_members[finding["family_key"]].append(finding)
    finding_families = []
    for family_key, members in sorted(family_members.items()):
        if len(members) < 2:
            continue
        finding_families.append({
            "id": f"QAF-{len(finding_families) + 1:04d}",
            "family_key": family_key,
            "severity": min(
                (item["severity"] for item in members),
                key={"critical": 0, "high": 1, "medium": 2}.__getitem__,
            ),
            "categories": sorted({item["category"] for item in members}),
            "finding_ids": [item["id"] for item in members],
            "affected_occurrences": sum(
                len(item["target_identities"]) for item in members
            ),
        })
    document = {
        "schema": FINDINGS_SCHEMA,
        "created_at": _utc_now(),
        "task_sha256": checkpoint["task_sha256"],
        "focus": task["focus"],
        "coverage": status(root),
        "findings": findings,
        "finding_families": finding_families,
        "uncertain_playtests": uncertain,
        "motif_families": sorted(motif_families, key=lambda item: item["id"]),
    }
    findings_path = root / "findings.json"
    _atomic_write_json(findings_path, document)
    checkpoint["stage"] = "complete"
    checkpoint["findings_file"] = str(findings_path)
    checkpoint["updated_at"] = _utc_now()
    _atomic_write_json(root / "checkpoint.json", checkpoint)
    return status(root)


def finalize(task_dir: str | Path) -> dict[str, Any]:
    root = Path(task_dir).expanduser().resolve()
    with _task_lock(root):
        return _finalize_unlocked(root)


def rebuild_findings_from_results(
    source_task_dir: str | Path, output_root: str | Path | None = None
) -> tuple[Path, dict[str, Any]]:
    """Re-finalize a completed task by replaying compatible deep receipts."""
    source = Path(source_task_dir).expanduser().resolve()
    source_task = _read_json(source / "task.json")
    source_checkpoint = _read_json(source / "checkpoint.json")
    if (
        source_task.get("schema") != TASK_SCHEMA
        or source_checkpoint.get("schema") != CHECKPOINT_SCHEMA
        or source_checkpoint.get("task_sha256")
        != _sha256(_canonical_bytes(source_task))
    ):
        raise ValueError(f"Unsupported or corrupt source QA task: {source}")
    source_rows = source_checkpoint["deep"]["bundles"]
    if (
        not source_rows
        or any(row.get("status") != "accepted" for row in source_rows)
        or source_checkpoint["deep"]["accepted_items"]
        != source_checkpoint["deep"]["total_items"]
    ):
        raise ValueError("The source task must have a fully accepted deep stage")

    current_manifest = build_manifest(source_task["data_root"], source_task["focus"])
    validation = verify_manifest(source_task["data_root"], current_manifest)
    if not validation["valid"]:
        raise ValueError(
            "Current QA inventory validation failed: "
            + "; ".join(validation.get("errors") or [])
        )
    source_manifest = _read_json(source / "inventory.json")
    current_context = _context_pack(
        Path(source_task["game_root"]),
        (
            str(record.get("source") or "")
            for record in current_manifest["records"]
        ),
    )
    mechanical_only_change = (
        current_manifest["content_sha256"] != source_task.get("manifest_sha256")
        and _semantic_manifest_sha256(current_manifest)
        == _semantic_manifest_sha256(source_manifest)
        and current_context["content_sha256"] == source_task.get("context_sha256")
    )
    if mechanical_only_change:
        return _rebuild_final_from_frozen_semantics(
            source,
            source_task,
            source_checkpoint,
            current_manifest,
            output_root,
        )

    destination_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else source.parents[2]
    )
    rebuilt, rebuilt_state = rebuild_deep_from_screen(source, destination_root)
    if rebuilt_state["stage"] == "complete":
        return rebuilt, rebuilt_state
    if rebuilt_state["stage"] != "deep":
        raise ValueError("The rebuilt task did not reach deep review")

    _rebuilt_root, _rebuilt_task, rebuilt_checkpoint = _load_task(rebuilt)
    source_summaries = {
        row["id"]: (row["sha256"], int(row["item_count"]))
        for row in source_rows
    }
    rebuilt_summaries = {
        row["id"]: (row["sha256"], int(row["item_count"]))
        for row in rebuilt_checkpoint["deep"]["bundles"]
    }
    if rebuilt_summaries != source_summaries:
        raise ValueError("Current deep bundles differ; deep review cannot be reused")

    for row in source_rows:
        bundle_path = source / "bundles" / "deep" / f"{row['id']}.json"
        result_path = source / "results" / "deep" / f"{row['id']}.json"
        bundle = _read_json(bundle_path)
        checksum_value = dict(bundle)
        claimed = checksum_value.pop("content_sha256", "")
        if (
            bundle.get("schema") != BUNDLE_SCHEMA
            or bundle.get("stage") != "deep"
            or bundle.get("bundle_id") != row["id"]
            or claimed != row.get("sha256")
            or claimed != _sha256(_canonical_bytes(checksum_value))
        ):
            raise ValueError(f"Source deep bundle checksum is invalid: {row['id']}")
        result = _read_json(result_path)
        if result.get("bundle_sha256") != claimed:
            raise ValueError(f"Source deep result checksum is invalid: {row['id']}")
        _validate_deep_result(bundle, result)
        accept_result(rebuilt, result_path)
    return rebuilt, finalize(rebuilt)


def _validate_completed_receipts(
    source: Path, checkpoint: dict[str, Any]
) -> list[str]:
    """Validate immutable bundles/results and return their content fingerprints."""
    fingerprints = []
    for stage in ("screen", "deep"):
        for row in checkpoint[stage]["bundles"]:
            bundle_path = source / "bundles" / stage / f"{row['id']}.json"
            result_path = source / "results" / stage / f"{row['id']}.json"
            if bundle_path.is_symlink() or result_path.is_symlink():
                raise ValueError(f"QA receipt cannot be a symbolic link: {row['id']}")
            bundle = _read_json(bundle_path)
            checksum_value = dict(bundle)
            claimed = checksum_value.pop("content_sha256", "")
            if (
                bundle.get("schema") != BUNDLE_SCHEMA
                or bundle.get("stage") != stage
                or bundle.get("bundle_id") != row["id"]
                or claimed != row.get("sha256")
                or claimed != _sha256(_canonical_bytes(checksum_value))
            ):
                raise ValueError(f"Source {stage} bundle checksum is invalid: {row['id']}")
            result = _read_json(result_path)
            if result.get("bundle_sha256") != claimed:
                raise ValueError(f"Source {stage} result checksum is invalid: {row['id']}")
            if stage == "screen":
                _validate_screen_result(bundle, result)
            else:
                _validate_deep_result(bundle, result)
            fingerprints.append(_sha256(result_path.read_bytes()))
    return fingerprints


def _rebuild_final_from_frozen_semantics(
    source: Path,
    source_task: dict[str, Any],
    source_checkpoint: dict[str, Any],
    current_manifest: dict[str, Any],
    output_root: str | Path | None,
) -> tuple[Path, dict[str, Any]]:
    """Re-finalize after a detector-only change without replaying semantic review."""
    receipt_fingerprints = _validate_completed_receipts(source, source_checkpoint)
    game = Path(source_task["game_root"]).resolve()
    destination_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else source.parents[2]
    )
    storage = _safe_task_root(destination_root, game)
    engine_fingerprint = _engine_fingerprint()
    migration_key = _sha256(_canonical_bytes({
        "kind": "mechanical-evidence-only-final-rebuild-v1",
        "engine_fingerprint": engine_fingerprint,
        "source_task_sha256": source_checkpoint["task_sha256"],
        "current_manifest_sha256": current_manifest["content_sha256"],
        "receipt_fingerprints": receipt_fingerprints,
    }))[:16]
    task_parent = storage / _slug(game.name) / source_task["focus"]
    task_parent.mkdir(parents=True, exist_ok=True)
    rebuilt = task_parent / migration_key
    with _task_lock(task_parent):
        if (rebuilt / "task.json").is_file():
            return rebuilt, status(rebuilt)
        staging = Path(tempfile.mkdtemp(prefix=f".{migration_key}.", dir=task_parent))
        try:
            for name in (
                "inventory.json",
                "inventory-validation.json",
                "context.json",
                "screen-index.json",
            ):
                path = source / name
                if path.is_symlink() or not path.is_file():
                    raise ValueError(f"Invalid frozen QA task file: {path}")
                shutil.copy2(path, staging / name)
            for name in ("bundles", "results"):
                folder = source / name
                if any(path.is_symlink() for path in folder.rglob("*")):
                    raise ValueError(f"Frozen QA task contains a symbolic link: {folder}")
                shutil.copytree(folder, staging / name)

            task = dict(source_task)
            task["created_at"] = _utc_now()
            task["engine_fingerprint"] = engine_fingerprint
            task["rebuilt_from"] = {
                "kind": "mechanical-evidence-only-final-rebuild-v1",
                "source_task": str(source),
                "source_task_sha256": source_checkpoint["task_sha256"],
                "current_manifest_sha256": current_manifest["content_sha256"],
            }
            checkpoint = json.loads(json.dumps(source_checkpoint))
            checkpoint["stage"] = "ready-finalize"
            checkpoint["findings_file"] = ""
            checkpoint["updated_at"] = _utc_now()
            for stage in ("screen", "deep"):
                for row in checkpoint[stage]["bundles"]:
                    row["path"] = str(
                        rebuilt / "bundles" / stage / f"{row['id']}.json"
                    )
                    row["result_path"] = str(
                        rebuilt / "results" / stage / f"{row['id']}.json"
                    )
            checkpoint["task_sha256"] = _sha256(_canonical_bytes(task))
            _atomic_write_json(staging / "task.json", task)
            _atomic_write_json(staging / "checkpoint.json", checkpoint)
            _atomic_write_text(
                staging / "README.md", _task_instructions(rebuilt, task)
            )
            staging.replace(rebuilt)
        except Exception:
            if staging.is_dir() and not staging.is_symlink():
                shutil.rmtree(staging)
            raise
    return rebuilt, finalize(rebuilt)


def _set_pointer(document: Any, pointer: str, value: str) -> None:
    parts = _decode_pointer(pointer)
    if not parts:
        raise ValueError("Refusing to replace an entire JSON document")
    parent = _resolve_parts(document, parts[:-1])
    key = parts[-1]
    if isinstance(parent, list):
        parent[int(key)] = value
    else:
        parent[key] = value


def create_correction_map(
    task_dir: str | Path, approved_finding_ids: Iterable[str]
) -> dict[str, Any]:
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] != "complete":
        raise ValueError("QA discovery must be complete before creating corrections")
    findings_doc = _read_json(root / "findings.json")
    approved = set(approved_finding_ids)
    selected = [item for item in findings_doc["findings"] if item["id"] in approved]
    if {item["id"] for item in selected} != approved:
        raise ValueError("One or more approved finding IDs do not exist")
    manifest = _read_json(root / "inventory.json")
    records = {record["identity"]: record for record in manifest["records"]}
    operations = []
    targets: dict[tuple[str, tuple[str, ...]], str] = {}
    for finding in selected:
        for identity in finding["target_identities"]:
            record = records[identity]
            target = (record["file"], tuple(record["live_pointers"]))
            previous = targets.get(target)
            if previous is not None and previous != finding["correction"]:
                raise ValueError(
                    f"Approved findings propose conflicting corrections for {identity}"
                )
            if previous is not None:
                continue
            targets[target] = finding["correction"]
            operations.append({
                "finding_id": finding["id"],
                "identity": identity,
                "file": record["file"],
                "live_pointers": record["live_pointers"],
                "live_transform": record["live_transform"],
                "expected": record["live"],
                "replacement": finding["correction"],
            })
    correction_map = {
        "schema": CORRECTION_MAP_SCHEMA,
        "created_at": _utc_now(),
        "manifest_sha256": task["manifest_sha256"],
        "approved_finding_ids": sorted(approved),
        "operations": operations,
    }
    correction_map["content_sha256"] = _sha256(_canonical_bytes(correction_map))
    _atomic_write_json(root / "correction-map.json", correction_map)
    return correction_map


def create_release_correction_map(
    task_dir: str | Path, *, allow_uncertain: bool = False
) -> dict[str, Any]:
    """Approve every finalized release finding when no user decision is pending."""
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] != "complete":
        raise ValueError("QA discovery must be complete before creating corrections")
    if task["focus"] != "release":
        raise ValueError("Automatic approval is restricted to full-game release QA")
    findings_doc = _read_json(root / "findings.json")
    uncertain = list(findings_doc.get("uncertain_playtests") or [])
    if uncertain and not allow_uncertain:
        raise ValueError(
            "Automatic approval paused because unresolved uncertain playtests remain; "
            "ask the user about those records or explicitly use --allow-uncertain to "
            "leave them unchanged"
        )
    finding_ids = [item["id"] for item in findings_doc.get("findings") or []]
    return create_correction_map(root, finding_ids)


def _load_editorial_migration_source(
    task_dir: str | Path,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load a completed frozen task without relaxing the normal fingerprint guard."""
    root = Path(task_dir).expanduser().resolve()
    required = [
        root / "task.json",
        root / "checkpoint.json",
        root / "inventory.json",
        root / "findings.json",
        root / "correction-map.json",
    ]
    for path in required:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid frozen QA task file: {path}")

    task = _read_json(root / "task.json")
    checkpoint = _read_json(root / "checkpoint.json")
    if (
        task.get("schema") != TASK_SCHEMA
        or checkpoint.get("schema") != CHECKPOINT_SCHEMA
        or checkpoint.get("task_sha256") != _sha256(_canonical_bytes(task))
    ):
        raise ValueError(f"Unsupported or corrupt frozen QA task: {root}")
    if checkpoint.get("stage") != "complete":
        raise ValueError("Editorial migration requires a completed QA task")
    for stage in ("screen", "deep"):
        state = checkpoint.get(stage) or {}
        rows = state.get("bundles") or []
        if (
            any(row.get("status") != "accepted" for row in rows)
            or int(state.get("accepted_items", -1)) != int(state.get("total_items", -2))
        ):
            raise ValueError(f"Editorial migration requires complete {stage} receipts")
    _validate_completed_receipts(root, checkpoint)

    manifest = _read_json(root / "inventory.json")
    manifest_checksum_value = dict(manifest)
    claimed_manifest_checksum = manifest_checksum_value.pop("content_sha256", "")
    if (
        claimed_manifest_checksum != _sha256(_canonical_bytes(manifest_checksum_value))
        or claimed_manifest_checksum != task.get("manifest_sha256")
    ):
        raise ValueError("Frozen QA inventory does not match its task")
    findings = _read_json(root / "findings.json")
    if (
        findings.get("schema") != FINDINGS_SCHEMA
        or findings.get("task_sha256") != checkpoint.get("task_sha256")
    ):
        raise ValueError("Frozen QA findings do not match their task")

    correction_map = _read_json(root / "correction-map.json")
    checksum_value = dict(correction_map)
    claimed_checksum = checksum_value.pop("content_sha256", "")
    if (
        correction_map.get("schema") != CORRECTION_MAP_SCHEMA
        or claimed_checksum != _sha256(_canonical_bytes(checksum_value))
        or correction_map.get("manifest_sha256") != task.get("manifest_sha256")
    ):
        raise ValueError("Frozen approved correction map is invalid")
    finding_ids = {item["id"] for item in findings.get("findings") or []}
    approved_ids = set(correction_map.get("approved_finding_ids") or [])
    if not approved_ids or not approved_ids <= finding_ids:
        raise ValueError("Frozen approved correction map has invalid finding coverage")
    return root, task, checkpoint, correction_map


def create_editorial_correction_map(
    task_dir: str | Path, editorial_review_path: str | Path
) -> dict[str, Any]:
    """Create a strict delta map from a completed final-editorial review."""
    root, task, _checkpoint, base_map = _load_editorial_migration_source(task_dir)
    review_path = Path(editorial_review_path).expanduser().resolve()
    if review_path.is_symlink() or not review_path.is_file():
        raise ValueError(f"Invalid editorial review file: {review_path}")
    review_document = _read_json(review_path)
    if review_document.get("schema") != EDITORIAL_REVIEW_SCHEMA:
        raise ValueError("Editorial review has an unsupported schema")
    recorded_task = str(review_document.get("task") or "")
    if recorded_task and Path(recorded_task).expanduser().resolve() != root:
        raise ValueError("Editorial review names a different QA task")

    decisions: dict[str, dict[str, Any]] = {}
    for review in review_document.get("reviews") or []:
        finding_id = str(review.get("finding_id") or "")
        if not finding_id or finding_id in decisions:
            raise ValueError("Editorial review finding IDs must be nonempty and unique")
        verdict = review.get("verdict")
        replacement = review.get("replacement")
        if verdict not in {"accept", "revise", "reject"}:
            raise ValueError(f"Unsupported editorial verdict for {finding_id}")
        if verdict == "accept" and replacement is not None:
            raise ValueError(f"Accepted editorial review must not replace {finding_id}")
        if verdict == "revise" and (
            not isinstance(replacement, str) or not replacement
        ):
            raise ValueError(f"Revised editorial review needs text for {finding_id}")
        decisions[finding_id] = review

    approved_ids = set(base_map["approved_finding_ids"])
    if set(decisions) != approved_ids:
        raise ValueError("Editorial review must cover every approved finding exactly once")
    counts = {
        "approved_findings": len(decisions),
        "accepted_as_written": sum(
            review["verdict"] == "accept" for review in decisions.values()
        ),
        "revisions_required": sum(
            review["verdict"] == "revise" for review in decisions.values()
        ),
        "rejected": sum(review["verdict"] == "reject" for review in decisions.values()),
    }
    for key, expected in counts.items():
        if key in review_document and int(review_document[key]) != expected:
            raise ValueError(f"Editorial review count is inconsistent: {key}")
    if counts["rejected"]:
        raise ValueError("Rejected editorial findings require new user approval")

    data_root = Path(task["data_root"]).resolve()
    documents: dict[str, Any] = {}
    operations = []
    for operation in base_map.get("operations") or []:
        finding_id = operation["finding_id"]
        filename = operation["file"]
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe editorial correction target: {path}")
        if filename not in documents:
            documents[filename] = json.loads(path.read_text(encoding="utf-8-sig"))
        values = _operation_values(documents[filename], operation)
        current = "\n".join(values)
        if operation["live_transform"] == "quoted-string":
            match = _QUOTED_VALUE_RE.search(current)
            current = match.group(2) if match else current
        if current not in {operation["expected"], operation["replacement"]}:
            raise ValueError(
                f"Live value is outside the frozen approval states: {operation['identity']}"
            )
        decision = decisions[finding_id]
        final_replacement = (
            decision["replacement"]
            if decision["verdict"] == "revise"
            else operation["replacement"]
        )
        if current == final_replacement:
            continue
        revised = dict(operation)
        revised["expected"] = current
        revised["replacement"] = final_replacement
        operations.append(revised)

    editorial_map = {
        "schema": CORRECTION_MAP_SCHEMA,
        "mode": "final-editorial-delta",
        "created_at": _utc_now(),
        "manifest_sha256": task["manifest_sha256"],
        "base_correction_map_sha256": base_map["content_sha256"],
        "editorial_review_sha256": _sha256(review_path.read_bytes()),
        "approved_finding_ids": sorted(approved_ids),
        "operations": operations,
    }
    editorial_map["content_sha256"] = _sha256(_canonical_bytes(editorial_map))
    _atomic_write_json(root / "editorial-correction-map.json", editorial_map)
    return editorial_map


def _load_editorial_correction_map(
    task_dir: str | Path,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load an editorial delta only when it remains tied to its approved map."""
    root, task, checkpoint, base_map = _load_editorial_migration_source(task_dir)
    path = root / "editorial-correction-map.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Invalid editorial correction map: {path}")
    editorial_map = _read_json(path)
    _validate_correction_map(editorial_map, task)
    if editorial_map.get("mode") != "final-editorial-delta":
        raise ValueError("Editorial correction map has an unsupported mode")
    if editorial_map.get("base_correction_map_sha256") != base_map.get("content_sha256"):
        raise ValueError("Editorial correction map does not match approved corrections")
    if set(editorial_map.get("approved_finding_ids") or []) != set(
        base_map.get("approved_finding_ids") or []
    ):
        raise ValueError("Editorial correction map does not match approved finding IDs")
    approved_ids = set(base_map.get("approved_finding_ids") or [])
    if any(
        operation.get("finding_id") not in approved_ids
        for operation in editorial_map.get("operations") or []
    ):
        raise ValueError("Editorial correction map contains an unapproved finding")
    return root, task, checkpoint, base_map, editorial_map


def _operation_values(document: Any, operation: dict) -> list[str]:
    return [resolve_pointer(document, pointer) for pointer in operation["live_pointers"]]


def _operation_replacements(values: list[str], operation: dict) -> list[str]:
    replacement = operation["replacement"]
    transform = operation["live_transform"]
    if transform == "quoted-string":
        if len(values) != 1:
            raise ValueError("Quoted-string operation has multiple live pointers")
        match = _QUOTED_VALUE_RE.search(values[0])
        if not match:
            raise ValueError("Quoted-string live value no longer contains a quoted value")
        return [values[0][: match.start(2)] + replacement + values[0][match.end(2) :]]
    if len(values) == 1:
        return [replacement]
    lines = replacement.split("\n")
    if len(lines) != len(values):
        raise ValueError(
            f"Replacement for {operation['identity']} must have {len(values)} lines"
        )
    return lines


def _has_suspicious_length_ratio(source: Any, live: Any) -> bool:
    source_text = str(source or "")
    live_text = str(live or "")
    if len(source_text) < 8 or not live_text:
        return False
    ratio = len(live_text) / len(source_text)
    return ratio < 0.35 or ratio > 3.0


def _validate_correction_map(
    correction_map: dict[str, Any], task: dict[str, Any]
) -> None:
    if correction_map.get("schema") != CORRECTION_MAP_SCHEMA:
        raise ValueError("Correction map has an unsupported schema")
    checksum_value = dict(correction_map)
    claimed_checksum = checksum_value.pop("content_sha256", "")
    if claimed_checksum != _sha256(_canonical_bytes(checksum_value)):
        raise ValueError("Correction map checksum does not match its contents")
    if correction_map.get("manifest_sha256") != task["manifest_sha256"]:
        raise ValueError("Correction map does not match this QA inventory")


def _dry_run_loaded_correction_map(
    root: Path,
    task: dict[str, Any],
    correction_map: dict[str, Any],
    report_name: str,
) -> dict[str, Any]:
    _validate_correction_map(correction_map, task)

    data_root = Path(task["data_root"]).resolve()
    inventory_records = {
        item["identity"]: item
        for item in _read_json(root / "inventory.json").get("records") or []
    }
    documents: dict[str, Any] = {}
    preview = []
    warnings = []
    pointer_targets: dict[tuple[str, str], str] = {}
    for operation in correction_map.get("operations") or []:
        filename = str(operation.get("file") or "")
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe correction target: {path}")
        if filename not in documents:
            documents[filename] = json.loads(path.read_text(encoding="utf-8-sig"))
        values = _operation_values(documents[filename], operation)
        current = "\n".join(values)
        if operation["live_transform"] == "quoted-string":
            match = _QUOTED_VALUE_RE.search(current)
            current = match.group(2) if match else current
        if current != operation["expected"]:
            raise ValueError(
                f"Expected value changed for {operation['identity']}; rebuild QA"
            )
        replacements = _operation_replacements(values, operation)
        for pointer, replacement in zip(operation["live_pointers"], replacements):
            target = (filename, pointer)
            previous = pointer_targets.get(target)
            if previous is not None and previous != replacement:
                raise ValueError(f"Conflicting approved corrections target {filename}#{pointer}")
            pointer_targets[target] = replacement
        preview.append({
            "finding_id": operation["finding_id"],
            "identity": operation["identity"],
            "file": filename,
            "live_pointers": operation["live_pointers"],
            "expected": operation["expected"],
            "replacement": operation["replacement"],
        })
        baseline = inventory_records.get(operation["identity"]) or {}
        baseline_flags = set(
            (baseline.get("mechanical") or {}).get("flags") or []
        )
        if (
            "suspicious-length-ratio" not in baseline_flags
            and _has_suspicious_length_ratio(
                baseline.get("source"), operation["replacement"]
            )
        ):
            warnings.append(
                "approved correction projects a non-blocking mechanical flag: "
                f"{operation['identity']} suspicious-length-ratio"
            )
    report = {
        "schema": "rpgmaker-qa-correction-dry-run-v1",
        "created_at": _utc_now(),
        "valid": True,
        "operation_count": len(preview),
        "file_count": len(documents),
        "warnings": warnings,
        "operations": preview,
    }
    _atomic_write_json(root / report_name, report)
    return report


def dry_run_correction_map(task_dir: str | Path) -> dict[str, Any]:
    """Validate every approved target and return a no-write operation preview."""
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] != "complete":
        raise ValueError("QA discovery must be complete before validating corrections")
    return _dry_run_loaded_correction_map(
        root,
        task,
        _read_json(root / "correction-map.json"),
        "correction-dry-run.json",
    )


def dry_run_editorial_correction_map(task_dir: str | Path) -> dict[str, Any]:
    """Validate a frozen task's editorial delta without writing game files."""
    root, task, _checkpoint, _base_map, editorial_map = _load_editorial_correction_map(
        task_dir
    )
    return _dry_run_loaded_correction_map(
        root,
        task,
        editorial_map,
        "editorial-correction-dry-run.json",
    )


def _render_json_like(raw: bytes, document: Any) -> bytes:
    """Render JSON using the file's existing BOM, indentation, and final newline."""
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    decoded = raw.decode("utf-8-sig")
    indent_match = re.search(r"\n([ \t]+)[\"\[\]{}]", decoded)
    indent: int | str | None
    if indent_match:
        token = indent_match.group(1)
        indent = token if "\t" in token else len(token)
    else:
        indent = None
    rendered = json.dumps(
        document,
        ensure_ascii=False,
        indent=indent,
        separators=(",", ":") if indent is None else None,
    )
    if decoded.endswith("\r\n"):
        rendered = rendered.replace("\n", "\r\n") + "\r\n"
    elif decoded.endswith("\n"):
        rendered += "\n"
    payload = rendered.encode("utf-8")
    return (b"\xef\xbb\xbf" + payload) if has_bom else payload


def _apply_loaded_correction_map(
    root: Path,
    task: dict[str, Any],
    correction_map: dict[str, Any],
    before: dict[str, Any],
    *,
    dry_run_name: str,
    regression_name: str,
    nonblocking_introduced_flags: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """Apply one validated map atomically and roll back on regression failure."""
    _dry_run_loaded_correction_map(root, task, correction_map, dry_run_name)
    data_root = Path(task["data_root"]).resolve()
    by_file: dict[str, list[dict]] = defaultdict(list)
    for operation in correction_map["operations"]:
        by_file[operation["file"]].append(operation)
    originals: dict[Path, bytes] = {}
    rendered: dict[Path, bytes] = {}
    applied = 0
    for filename, operations in sorted(by_file.items()):
        path = (data_root / filename).resolve()
        if data_root not in path.parents or not path.is_file() or path.is_symlink():
            raise ValueError(f"Unsafe correction target: {path}")
        raw = path.read_bytes()
        originals[path] = raw
        document = json.loads(raw.decode("utf-8-sig"))
        for operation in operations:
            values = _operation_values(document, operation)
            current = "\n".join(values)
            if operation["live_transform"] == "quoted-string":
                match = _QUOTED_VALUE_RE.search(current)
                current = match.group(2) if match else current
            if current != operation["expected"]:
                raise ValueError(
                    f"Expected value changed for {operation['identity']}; rebuild QA"
                )
            replacements = _operation_replacements(values, operation)
            for pointer, replacement in zip(operation["live_pointers"], replacements):
                _set_pointer(document, pointer, replacement)
            applied += 1
        rendered[path] = _render_json_like(raw, document)
    temporaries: dict[Path, Path] = {}
    replaced: list[Path] = []
    try:
        for path, raw in rendered.items():
            handle, temporary_name = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".qa.tmp", dir=path.parent
            )
            temporary = Path(temporary_name)
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            json.loads(temporary.read_text(encoding="utf-8-sig"))
            temporaries[path] = temporary
        for path, temporary in temporaries.items():
            temporary.replace(path)
            replaced.append(path)
    except Exception:
        for path in replaced:
            rollback = path.with_name(path.name + ".qa.rollback")
            rollback.write_bytes(originals[path])
            rollback.replace(path)
        raise
    finally:
        for temporary in temporaries.values():
            temporary.unlink(missing_ok=True)
    regression = _regression_check_loaded(
        task,
        before,
        correction_map,
        nonblocking_introduced_flags=nonblocking_introduced_flags,
    )
    if not regression["valid"]:
        for path, raw in originals.items():
            rollback = path.with_name(path.name + ".qa.rollback")
            rollback.write_bytes(raw)
            rollback.replace(path)
        regression["rolled_back"] = True
        _atomic_write_json(root / regression_name, regression)
        raise ValueError("QA regression failed; all game-file changes were rolled back")
    regression["applied_operations"] = applied
    _atomic_write_json(root / regression_name, regression)
    return regression


def apply_correction_map(task_dir: str | Path) -> dict[str, Any]:
    """Apply an approved correction map with validation and rollback on failure."""
    root, task, checkpoint = _load_task(task_dir)
    if checkpoint["stage"] != "complete":
        raise ValueError("QA discovery must be complete before applying corrections")
    return _apply_loaded_correction_map(
        root,
        task,
        _read_json(root / "correction-map.json"),
        _read_json(root / "inventory.json"),
        dry_run_name="correction-dry-run.json",
        regression_name="regression.json",
        nonblocking_introduced_flags=APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
    )


def apply_editorial_correction_map(task_dir: str | Path) -> dict[str, Any]:
    """Apply a completed frozen task's validated final-editorial delta."""
    root, task, _checkpoint, _base_map, editorial_map = _load_editorial_correction_map(
        task_dir
    )
    before = build_manifest(task["data_root"], task["focus"])
    validation = verify_manifest(task["data_root"], before)
    if not validation["valid"]:
        raise ValueError(
            "Current QA inventory validation failed: "
            + "; ".join(validation.get("errors") or [])
        )
    return _apply_loaded_correction_map(
        root,
        task,
        editorial_map,
        before,
        dry_run_name="editorial-correction-dry-run.json",
        regression_name="editorial-regression.json",
        nonblocking_introduced_flags=APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
    )


def _regression_check_loaded(
    task: dict[str, Any],
    before: dict[str, Any],
    corrections: dict[str, Any] | None,
    *,
    nonblocking_introduced_flags: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    after = build_manifest(task["data_root"], task["focus"])
    validation = verify_manifest(task["data_root"], after)
    before_records = {item["identity"]: item for item in before["records"]}
    after_records = {item["identity"]: item for item in after["records"]}
    errors = list(validation.get("errors") or [])
    warnings = []
    if set(before_records) != set(after_records):
        errors.append("source identity coverage changed after corrections")
    for identity in sorted(set(before_records) & set(after_records)):
        if before_records[identity]["source_sha256"] != after_records[identity]["source_sha256"]:
            errors.append(f"preserved source changed: {identity}")
    if corrections is not None:
        for operation in corrections.get("operations") or []:
            record = after_records.get(operation["identity"])
            if record is None or record["live"] != operation["replacement"]:
                errors.append(f"approved correction is missing: {operation['identity']}")
                continue
            before_record = before_records.get(operation["identity"], {})
            before_flags = set(
                before_record.get("mechanical", {}).get("flags") or []
            )
            after_flags = set(record.get("mechanical", {}).get("flags") or [])
            introduced_flags = after_flags - before_flags
            warning_flags = sorted(
                introduced_flags & nonblocking_introduced_flags
            )
            blocking_flags = sorted(
                introduced_flags - nonblocking_introduced_flags
            )
            if warning_flags:
                warnings.append(
                    "approved correction introduced non-blocking mechanical flags: "
                    f"{operation['identity']} " + ", ".join(warning_flags)
                )
            if blocking_flags:
                errors.append(
                    "approved correction introduced mechanical flags: "
                    f"{operation['identity']} " + ", ".join(blocking_flags)
                )
    return {
        "schema": REGRESSION_SCHEMA,
        "created_at": _utc_now(),
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "before_manifest_sha256": before["content_sha256"],
        "after_manifest_sha256": after["content_sha256"],
        "records_checked": len(after_records),
    }


def regression_check(task_dir: str | Path) -> dict[str, Any]:
    root, task, _checkpoint = _load_task(task_dir)
    correction_path = root / "editorial-correction-map.json"
    if not correction_path.is_file():
        correction_path = root / "correction-map.json"
    corrections = _read_json(correction_path) if correction_path.is_file() else None
    return _regression_check_loaded(
        task,
        _read_json(root / "inventory.json"),
        corrections,
        nonblocking_introduced_flags=APPROVED_NONBLOCKING_MECHANICAL_FLAGS,
    )


def find_latest_task(
    output_root: str | Path, game_root: str | Path, focus: str
) -> Path | None:
    base = Path(output_root).expanduser().resolve() / _slug(Path(game_root).name) / focus
    if not base.is_dir():
        return None
    tasks = [path for path in base.iterdir() if (path / "task.json").is_file()]
    return max(tasks, key=lambda path: path.stat().st_mtime) if tasks else None


def find_latest_completed_task(
    output_root: str | Path, game_root: str | Path, focus: str
) -> Path | None:
    """Find a completed pass even when newer QA rules make its status stale."""
    game = Path(game_root).expanduser().resolve()
    base = Path(output_root).expanduser().resolve() / _slug(game.name) / focus
    if not base.is_dir():
        return None
    completed = []
    for path in base.iterdir():
        if path.is_symlink():
            continue
        try:
            task = _read_json(path / "task.json")
            checkpoint = _read_json(path / "checkpoint.json")
        except (OSError, ValueError):
            continue
        if (
            task.get("schema") != TASK_SCHEMA
            or checkpoint.get("schema") != CHECKPOINT_SCHEMA
            or checkpoint.get("task_sha256") != _sha256(_canonical_bytes(task))
            or Path(str(task.get("game_root") or "")).expanduser().resolve() != game
            or task.get("focus") != focus
            or checkpoint.get("stage") != "complete"
        ):
            continue
        screen = checkpoint.get("screen") or {}
        deep = checkpoint.get("deep") or {}
        if any(
            int(stage.get("accepted_items", -1))
            != int(stage.get("total_items", -2))
            or any(
                row.get("status") != "accepted"
                for row in stage.get("bundles") or []
            )
            for stage in (screen, deep)
        ) or not deep.get("bundles"):
            continue
        completed.append(path)
    return max(completed, key=lambda path: path.stat().st_mtime) if completed else None
