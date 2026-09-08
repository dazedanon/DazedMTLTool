"""Expand actual rank substitutions and measure English with embedded font metrics."""
import json
from pathlib import Path
import re
import build_catalog as bc

def wrap(text, width, font):
    lines = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            candidate = line + " " + word if line else word
            if line and bc.gmtt.font_measure(candidate, font)["line_widths"][0] > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        lines.append(line)
    return lines

def main():
    catalog = bc.read(bc.ROOT / "build/catalog.en.json")
    snap = bc.read(bc.PROJECT / "source/snapshot.json")
    fonts = {f["name"]: f for f in snap["fonts"]}
    translations = {e["source"]: bc.gmtt.restore(e["translation"], e["tokens"]) for e in catalog["entries"] if e.get("translation_context", {}).get("field") == "fragment.equipment_target"}
    variants = {}
    for typ in ("skill", "equip"):
        source = (bc.PROJECT / f"source/gml/gml_GlobalScript_scr_text_{typ}.gml").read_text(encoding="utf-8")
        parts = re.split(r"if \(arg1 == (\d)\)", source)[1:]
        for rank, body in zip(parts[::2], parts[1::2]):
            values = re.findall(r'case (\d+):\s*tmp_n = ("(?:\\.|[^"\\])*");', body)
            for item, value in values:
                variants[(typ, int(item), int(rank))] = json.loads(value)
    assert len(variants) == 391, len(variants)
    report = []
    singular = []
    for entry in catalog["entries"]:
        ctx = entry.get("translation_context", {})
        field = ctx.get("field")
        text = bc.gmtt.restore(entry["translation"], entry["tokens"])
        items = [(None, text)]
        if field in ("description.skill", "description.equipment"):
            typ = "skill" if field == "description.skill" else "equip"
            items = [(rank, text.replace("#", translations.get(value, value))) for (kind, case, rank), value in variants.items() if kind == typ and case == ctx["case_id"]]
            assert len(items) == (2 if typ == "skill" else 3)
        contexts = {
            "description.skill": [("talent", "font_b2", 280)],
            "description.stat": [("talent", "font_b2", 280)],
            "description.equipment": [("inventory", "font_2", 900), ("shop", "font_2", 900), ("combat-skill", "font_b1", 390), ("combat-equipment", "font_b2", 358)],
            "description.quest": [("quest", "font_2", 900)],
            "scene.narration": [("scene", "font_1", 789)],
            "dialogue.merchant": [("merchant", "font_2", 510)],
            "description.help": [("help", "font_b2", 999)],
        }.get(field, [])
        for rank, rendered in items:
            if re.search(r"\b1 (?:seconds|attacks|levels|projectiles|Holy Pillars|Magic Follow-Ups|Bonus Attacks|enemies)\b", rendered, re.I):
                singular.append({"id": entry["id"], "rank": rank, "text": rendered})
            for label, face, width in contexts:
                lines = wrap(rendered, width, fonts[face])
                widths = [bc.gmtt.font_measure(s, fonts[face])["line_widths"][0] for s in lines]
                assert max(widths, default=0) <= width, (entry["id"], face, lines)
                limit = {"talent": 3, "help": 2, "inventory": 3, "combat-skill": 3,
                         "combat-equipment": 3, "quest": 3, "shop": 3, "merchant": 4, "scene": 5}[label]
                assert len(lines) <= limit, (entry["id"], label, lines)
                assert re.sub(r"\s+", "", rendered) == re.sub(r"\s+", "", "".join(lines))
                report.append({"id": entry["id"], "rank": rank, "context": label, "font": face, "width": width, "rows": len(lines), "lines": lines})
    bc.write(bc.ROOT / "build/layout-measurements.json", report)
    from quest_audit import audit as audit_quest
    audit_quest(report)
    from narration_audit import audit as audit_narration
    narration_report = audit_narration(report)
    print(json.dumps({k:v for k,v in narration_report.items() if k!='rows'}))
    bc.write(bc.ROOT / "build/singular-review.json", singular)
    assert not singular, singular
    maxima = {}
    for row in report:
        maxima[row["context"]] = max(maxima.get(row["context"], 0), row["rows"])
    print(json.dumps({"measured_forms": len(report), "rank_substitutions": len(variants), "max_rows": maxima, "singular_review": singular}, indent=2))
    import tooltip_audit
    tooltip_audit.main()
    import importlib.util
    status_spec = importlib.util.spec_from_file_location('status_followup', bc.ROOT/'followup-status/build_followup.py')
    status_module = importlib.util.module_from_spec(status_spec)
    status_spec.loader.exec_module(status_module)
    status_report = status_module.audit()
    print(json.dumps({k:v for k,v in status_report.items() if k!='rows'}))

if __name__ == "__main__":
    main()
