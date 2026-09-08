"""Rebuild and validate offline translation preparation; no service or API code.

Editorial files are read-only inputs. Output files are deterministic derivatives.
Run from any cwd: python prepare.py [--check] [--archive PATH]
"""
import argparse
from collections import Counter, defaultdict
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def literal_locations(text):
    locations = defaultdict(list)
    for match in re.finditer(r'"(?:\\.|[^"\\])*"', text):
        value = json.loads(match.group())
        line = text.count("\n", 0, match.start()) + 1
        prefix = text[:match.start()]
        cases = re.findall(r"\bcase\s+(\d+)\s*:", prefix)
        statement = text.splitlines()[line - 1].strip()
        locations[value].append({
            "line": line, "case_id": int(cases[-1]) if cases else None,
            "statement": statement,
        })
    return locations


FIELDS = {
    "scr_name_equip": "name.equipment", "scr_text_equip": "description.equipment",
    "scr_name_skill": "name.skill", "scr_text_skill": "description.skill",
    "scr_name_talent": "name.stat", "scr_text_talent": "description.stat",
    "scr_enemy_name": "name.enemy", "scr_name_quest": "name.quest",
    "scr_text_quest": "description.quest", "scr_text_h": "scene.narration",
    "scr_text_talent_down": "description.help", "obj_state_Create_0": "ui.statistic",
    "obj_dialog_Create_0": "dialogue.merchant", "obj_hall_Alarm_0": "ui.fragment",
    "obj_shop_Draw_0": "ui.label", "obj_equip_Draw_0": "ui.label",
    "obj_hall_Draw_0": "ui.label", "obj_end_Create_0": "ui.label",
    "obj_end_Step_0": "ui.notice", "obj_quest_Alarm_0": "ui.notice",
    "obj_ui_Step_0": "ui.notice", "obj_gallery_Step_0": "ui.label",
    "obj_hall_Step_0": "ui.notice",
}
PAIRS = {
    "description.equipment": "name.equipment", "description.skill": "name.skill",
    "description.quest": "name.quest", "description.stat": "name.stat",
}
HELP_KEYS = ["魔法爆発", "カウント", "遠謀", "一時的", "会心", "吹き飛ばし",
             "斬撃波", "キル数", "跳弾", "破甲", "束縛", "播種", "大爆発",
             "聖痕", "減速", "聖光柱", "光の領域"]
FREQUENCY_CORRECTIONS = {"CODE:16:549", "CODE:16:552", "CODE:16:555", "CODE:16:561"}


def build():
    cfg = read_json(ROOT / "translation_config.json")
    source_manifest = read_json(ROOT / "source/manifest.json")
    source_files = {p.relative_to(ROOT / "source").as_posix(): p for p in (ROOT / "source").rglob("*") if p.is_file() and p.name != "manifest.json"}
    assert source_manifest["source_archive_sha256"] == cfg["source_sha256"]
    assert set(source_files) == set(source_manifest["files"]), "Source evidence inventory changed"
    for name, path in source_files.items():
        assert sha256(path) == source_manifest["files"][name], f"Source evidence changed: {name}"
    glossary = read_json(ROOT / "glossary.json")
    fields = read_json(ROOT / "field_instructions.json")
    snap = read_json(ROOT / cfg["source_snapshot"])
    raw = read_json(ROOT / cfg["raw_catalog"])
    assert raw["source_sha256"] == snap["source_sha256"] == cfg["source_sha256"]
    assert raw["source_size"] == snap["source_size"] == cfg["source_size"]
    toolkit = Path(cfg["toolkit_path"]) / "gmtt.py"
    spec = importlib.util.spec_from_file_location("gmtt", toolkit)
    gmtt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gmtt)
    known = {**glossary["terms"], **{k: v["en"] for k, v in glossary["names"].items()}}
    for value in glossary["names"].values():
        assert all(key in value for key in ("en", "gender", "role", "register", "aliases"))
    for key in HELP_KEYS:
        assert key in known

    prepared = copy.deepcopy(raw)
    prepared["token_patterns"] = cfg["token_patterns"]
    gml = {p.stem: p.read_text(encoding="utf-8") for p in sorted((ROOT / "source/gml").glob("*.gml"))}
    locs = {key: literal_locations(value) for key, value in gml.items()}
    occurrences = Counter()
    technical, locks, held = [], [], []
    context_map = {}
    scene_gml = gml["gml_GlobalScript_scr_text_h"]
    aliases = {int(a): int(b) for a, b in re.findall(r"case\s+(\d+):\s*tmp_a\s*=\s*(\d+);", scene_gml)}

    for entry in prepared["entries"]:
        site, source, code = entry["id"], entry["source"], entry["code_name"]
        position = occurrences[(code, source)]
        occurrences[(code, source)] += 1
        assert position < len(locs[code][source]), f"No unique GML occurrence: {site}"
        loc = copy.deepcopy(locs[code][source][position])
        stem = code.replace("gml_GlobalScript_", "").replace("gml_Object_", "")
        if stem == "scr_text_talent" and source in ("あらゆる爆発の範囲を増やす", "「射程」を5回強化するごとに、弾幕+1"):
            loc["case_id"] = 2
            loc["role_override"] = 2 if source.startswith("あらゆる") else 3
        field = FIELDS[stem]
        if source in glossary["names"] and stem == "obj_gallery_Step_0":
            field = "name.character"
        if stem == "obj_hall_Step_0" and (source.startswith("敵のHPが") or source.startswith("敵の移動速度が") or source.startswith("％")):
            field = "ui.fragment"
        assert field in fields
        ctx = {"field": field, "source_ref": f"source/gml/{code}.gml:{loc['line']}", **loc}
        ctx["reachability"] = "Static display consumer identified; individual runtime route not playtested."
        ctx["disposition"] = "translate"
        ctx["speaker"] = "Merchant" if field == "dialogue.merchant" else None
        entry["masked_source"], entry["tokens"] = gmtt.mask(source, cfg["token_patterns"])
        assert gmtt.restore(entry["masked_source"], entry["tokens"]) == source
        assert entry["translation"] is None and entry["reviewed"] is False

        if stem == "scr_text_talent_down" and "string_pos(" in loc["statement"]:
            assert source in HELP_KEYS
            ctx["disposition"] = "technical_override"
            ctx["field"] = "technical.lookup"
            technical.append({"id": site, "source": source, "planned_text": known[source],
                              "source_ref": ctx["source_ref"], "status": "planned_not_applied"})
        elif field.startswith("name."):
            assert source in known, f"Missing locked name: {source} at {site}"
            ctx["disposition"] = "glossary_locked"
            ctx["locked_text"] = known[source]
            locks.append({"id": site, "source": source, "planned_text": known[source]})

        if stem == "scr_text_equip" and "tmp_n =" in loc["statement"]:
            ctx["field"] = "fragment.equipment_target"
            ctx["rank"] = {"前方最も近いの敵": 1, "前後最も近いの敵": 2, "全ての敵": 3}[source]
            ctx["assembly_group"] = "equipment:46:target"
            ctx["instruction"] = "Noun phrase inserted into equipment 46's Bind description. Keep the three ranks parallel. Rank 2 means the nearest enemy in front AND the nearest behind, not one nearest enemy overall."
        elif field == "description.equipment" and loc["case_id"] == 46:
            ctx["assembly_group"] = "equipment:46:target"
            ctx["instruction"] = "The marker inserts a target noun phrase, not a number. Put English boundary spaces outside the marker; Bind and cooldown must read naturally for all three ranks."
        if field in PAIRS:
            ctx["paired_name_field"] = PAIRS[field]
        if field in ("description.quest", "name.quest"):
            ctx["focus_character"] = {1: "Flavia", 2: "Irara", 3: "Luminia"}[(loc["case_id"] // 10) + 1]
        if field in ("description.skill", "name.skill"):
            ctx["skill_pool"] = "Common" if loc["case_id"] <= 11 else {0: "Flavia", 1: "Irara", 2: "Luminia"}[(loc["case_id"] - 12) // 23]
        if field == "scene.narration":
            scene_id = loc["case_id"]
            role = ((scene_id % 1000) // 100) + 1
            assert role in (1, 2, 3)
            ctx["focus_character"] = {1: "Flavia", 2: "Irara", 3: "Luminia"}[role]
            ctx["speaker"] = None
            ctx["scene_id"] = scene_id
            ctx["phase"] = "climax" if scene_id >= 1000 else "base"
            ctx["alias_scene_ids"] = [a for a, b in aliases.items() if b == scene_id]
            ctx["instruction"] = "Independent narration caption, not a spoken line. Alias IDs share this compiled literal. Paired phase text is context, not permission to invent intervening events."
        if field == "dialogue.merchant":
            ctx["story_index"] = int(re.search(r"geo_story\[(\d+)\]", loc["statement"]).group(1))
            ctx["assembly_group"] = "merchant:introduction"
            if ctx["story_index"] == 4:
                ctx["disposition"] = "hold"
                ctx["hold_reason"] = "MERCHANT-4: Step event clears and destroys the dialogue at index 4 before it can display. Retain as source context."
        if field == "ui.fragment":
            if stem == "obj_hall_Alarm_0":
                ctx["assembly_group"] = "ui:quest_reward"
            elif loc["line"] == 111:
                ctx["assembly_group"] = "ui:enemy_hp_up"
            elif loc["line"] == 115:
                ctx["assembly_group"] = "ui:enemy_hp_down"
            elif loc["line"] == 121:
                ctx["assembly_group"] = "ui:enemy_speed"
            else:
                raise AssertionError(f"Unknown fragment assembly {site}: {loc}")
            ctx["complete_expression"] = loc["statement"]
        if stem == "scr_text_talent_down" and source.startswith("跳弾："):
            ctx["disposition"] = "hold"
            ctx["hold_reason"] = "RICOCHET: no supplying description found; dormant helper retained for future research."
        if stem == "scr_text_talent_down" and source.startswith("聖痕："):
            ctx["disposition"] = "hold"
            ctx["hold_reason"] = "HOLY-MARK: help says Attack*0.5, baseline consumer uses Attack*0.75. Resolve source-number policy before translating this definition."
        if site in FREQUENCY_CORRECTIONS:
            assert "攻撃ごとに#回" in source
            ctx["verified_correction"] = "One effect every # qualifying attack hits, not # effects per attack. Normal and additional attacks count. Retain the independent Projectile +1 effect. See review/quirk-review.md F1."
        if stem == "scr_text_skill" and loc["case_id"] == 11:
            ctx["meaning_note"] = "属性 here means the ordinary upgradable stats, not elemental affinities; consumer is obj_talent_Step_0:173."
        ctx["required_helper_keywords"] = [known[k] for k in HELP_KEYS if k in source] if ctx["disposition"] != "technical_override" else []
        # The terms select help by substring. A later validator must also catch extra keys,
        # e.g. Light Field and Temporary accidentally introduced in unrelated descriptions.
        ctx["matched_glossary"] = {k: known[k] for k in sorted(known, key=lambda k: (-len(k), k)) if k in source}
        assert ctx["field"] in fields or ctx["field"] == "technical.lookup"
        context_map[site] = ctx
        entry["translation_context"] = ctx
        if ctx["disposition"] == "hold":
            held.append({"id": site, "source": source, "reason": ctx["hold_reason"]})

    assert len(technical) == 17 and {x["source"] for x in technical} == set(HELP_KEYS)
    assert len(held) == 3, held
    for (code, source), count in occurrences.items():
        assert count == len(locs[code][source]), f"Ambiguous GML occurrence mapping: {code} / {source}"
    name_lookup = {}
    for entry in prepared["entries"]:
        ctx = entry["translation_context"]
        if ctx["field"].startswith("name."):
            name_lookup[(ctx["field"], ctx["case_id"])] = entry
    for entry in prepared["entries"]:
        ctx = entry["translation_context"]
        if "paired_name_field" in ctx:
            paired = name_lookup.get((ctx["paired_name_field"], ctx["case_id"]))
            if paired:
                ctx["paired_name"] = {"id": paired["id"], "source": paired["source"], "en": known[paired["source"]]}
            elif ctx["paired_name_field"] == "name.stat" and ctx["case_id"] == 8:
                ctx["paired_name"] = {"source": "CD", "en": "CD", "note": "Already ASCII; outside CJK catalog."}
            else:
                raise AssertionError(f"Missing paired name: {entry['id']}")
    range_overrides = [e for e in prepared["entries"] if e["translation_context"].get("role_override")]
    assert len(range_overrides) == 2
    assert all(e["translation_context"]["paired_name"]["source"] == "射程" for e in range_overrides)
    scene_entries = {e["translation_context"]["scene_id"]: e for e in prepared["entries"] if e["translation_context"]["field"] == "scene.narration"}
    for scene_id, entry in scene_entries.items():
        ctx = entry["translation_context"]
        requested = scene_id + 1000 if scene_id < 1000 else scene_id - 1000
        paired_id = aliases.get(requested, requested)
        if paired_id in scene_entries:
            ctx["paired_phase_id"] = scene_entries[paired_id]["id"]

    # A CJK-letter export intentionally omits punctuation. Inventory these separately
    # and preserve per-site addresses; no global pool replacements.
    supplemental = []
    for site, info in gmtt.site_map(snap).items():
        if info["source"] == "、":
            supplemental.append({"id": site, **info, "planned_text": ", ",
                                 "status": "planned_not_applied", "reason": "Enemy-list delimiter; outside CJK-letter census."})
    assert len(supplemental) == 1, supplemental
    assert supplemental[0]["code_name"] == "gml_Object_obj_hall_Step_0"

    # Preview groups contain IDs, never executable requests. One field per future batch.
    groups = defaultdict(list)
    for entry in prepared["entries"]:
        ctx = entry["translation_context"]
        if ctx["disposition"] != "translate":
            continue
        key = ctx.get("assembly_group", ctx.get("focus_character", "all"))
        groups[(ctx["field"], key)].append(entry["id"])
    batches = [{"field": field, "group": group, "unit_ids": ids}
               for (field, group), ids in sorted(groups.items())]
    field_counts = Counter(e["translation_context"]["field"] for e in prepared["entries"])
    disposition_counts = Counter(e["translation_context"]["disposition"] for e in prepared["entries"])
    validation = gmtt.validate_catalog(prepared, snap)
    assert not validation["errors"] and not validation["changes"], validation
    assert len(prepared["entries"]) == 630
    assert len({e["id"] for e in prepared["entries"]}) == 630
    assert sum(e["source"].count("#") for e in prepared["entries"]) == 158
    assert sum("#" in e["source"] for e in prepared["entries"]) == 157
    fonts = []
    for font in snap["fonts"]:
        chars = {x["char"] for x in font["glyphs"]}
        assert all(ch in chars for ch in range(32, 127)), font["name"]
        fonts.append({"name": font["name"], "ascii_32_126": True,
                      "em_dash": 0x2014 in chars, "smart_apostrophe": 0x2019 in chars})
    assert all(all(32 <= ord(ch) < 127 for ch in text) for text in known.values()), "Glossary target outside declared typography"

    report = {
        "source_sha256": cfg["source_sha256"], "raw_candidate_uses": 630,
        "field_counts": dict(sorted(field_counts.items())),
        "dispositions": dict(sorted(disposition_counts.items())),
        "glossary_character_entries": len(glossary["names"]),
        "glossary_term_entries": len(glossary["terms"]),
        "locked_name_sites": len(locks), "name_coverage": "100% of classified name sites",
        "protected_substitution_sites": 157, "protected_substitution_occurrences": 158,
        "supplemental_punctuation_sites": len(supplemental), "held_units": held,
        "gml_files": len(gml), "fonts": fonts,
        "validation": "All 630 IDs retained; 232 evidence file hashes verified; source matches snapshot; GML literal occurrences match; masks round-trip; no translations or reviewed changes; glossary names complete; no JSON duplicate keys.",
        "limits": "Static preparation only. No translation run, API integration, runtime layout certification or patched archive. 630 is a candidate count, not a claim that all records display in release gameplay."
    }
    anchors = ["攻撃ごとに#回", "遠謀", "カウント", "キル数", "最大感度", "感度回復",
               "貫通ダメージ", "破甲", "ポイントの魔法ダメージを生成", "引爆", "跳弾",
               "高貴な王女は", "フラヴィア", "#回の追加攻撃ごとに", "魔法の指輪", "貫通強化"]
    anchor_counts = {}
    for anchor in anchors:
        matches = [e for e in prepared["entries"] if anchor in e["source"]]
        anchor_counts[anchor] = {"candidate_sites": len(matches), "unique_texts": len({e["source"] for e in matches}),
                                 "sites": [{"id": e["id"], "source_ref": e["translation_context"]["source_ref"]} for e in matches]}
    outputs = {
        "catalog.prepared.json": prepared,
        "technical_overrides.json": {"source_sha256": cfg["source_sha256"], "status": "planned_not_applied", "help_lookup_sites": technical, "supplemental_punctuation_sites": supplemental,
                                     "validation_rule": "For every assembled skill/equipment description at every rank, compare the set of helper keys detected in source with the canonical English keys detected in target. No missing or accidental extra matches. Dormant Ricochet key may be kept prepared but does not prove its help is reachable."},
        "glossary_locks.json": {"status": "planned_not_applied", "entries": locks},
        "translation_plan.json": {"status": "ready_for_translation_with_named_holds", "groups": batches, "holds": held,
                                  "instructions": "Groups are planning buckets, not API batches. Split by token budget later while preserving assembly/scene links and matched glossary. Supply source-only held merchant record as context, never as a requested output. Do not deduplicate narration or dialogue."},
        "preparation-report.json": report,
        "review/anchor-counts.json": {"scope": "Literal substring recount over all 630 raw candidate sites, including technical needles and held text; source references are verified against recovered GML.", "anchors": anchor_counts},
    }
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validate derived files without writing.")
    parser.add_argument("--archive", type=Path, help="Optionally verify the original data.win hash, read-only.")
    args = parser.parse_args()
    # Validate every editorial JSON too, including unused optional fields.
    for path in ROOT.glob("*.json"):
        read_json(path)
    outputs = build()
    for name, content in outputs.items():
        path = ROOT / name
        if args.check:
            assert path.exists() and read_json(path) == content, f"Stale derived file: {name}"
        else:
            path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.archive:
        assert sha256(args.archive) == outputs["preparation-report.json"]["source_sha256"], "Original archive hash mismatch"
    report = outputs["preparation-report.json"]
    print(json.dumps({key: report[key] for key in ("raw_candidate_uses", "dispositions", "glossary_character_entries", "glossary_term_entries", "protected_substitution_occurrences", "validation")}, indent=2))
    if args.archive:
        print("Original archive SHA-256 verified unchanged.")


if __name__ == "__main__":
    main()
