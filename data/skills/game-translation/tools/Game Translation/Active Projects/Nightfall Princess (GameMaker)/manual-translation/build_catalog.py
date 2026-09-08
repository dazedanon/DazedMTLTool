"""Assemble the manually written translation and run offline text checks."""
import copy
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parent if (ROOT.parent / "catalog.prepared.json").exists() else Path("C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)")
TOOLKIT = Path("C:/Users/sw/Desktop/Tools/Game Translation/GameMaker")
spec = importlib.util.spec_from_file_location("gmtt", TOOLKIT / "gmtt.py")
gmtt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gmtt)

def unique(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("Duplicate key: " + key)
        out[key] = value
    return out

def read(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique)

def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def main():
    catalog = copy.deepcopy(read(PROJECT / "catalog.prepared.json"))
    snap = read(PROJECT / "source/snapshot.json")
    text = {}
    for path in sorted(ROOT.glob("*.en.json")):
        part = read(path)
        assert not set(text) & set(part), path
        text.update(part)
    assert len(text) == 368
    for row in read(PROJECT / "glossary_locks.json")["entries"]:
        assert row["id"] not in text
        text[row["id"]] = row["planned_text"]
    technical = read(PROJECT / "technical_overrides.json")
    keymap = {row["source"]: row["planned_text"] for row in technical["help_lookup_sites"]}
    for row in technical["help_lookup_sites"]:
        assert row["id"] not in text
        text[row["id"]] = row["planned_text"]
    assert set(text) == {e["id"] for e in catalog["entries"]}
    helper_issues, number_review = [], []
    for entry in catalog["entries"]:
        entry["translation"] = text[entry["id"]]
        entry["reviewed"] = True
        ctx = entry["translation_context"]
        entry["font"] = {"scene.narration": "font_1", "ui.statistic": "font_state", "description.skill": "font_b2", "description.stat": "font_b2", "description.help": "font_b2"}.get(ctx["field"], "font_2")
        restored = gmtt.restore(entry["translation"], entry["tokens"])
        assert all(32 <= ord(ch) < 127 or ch == "\n" for ch in restored), entry["id"]
        if ctx["field"] in ("description.skill", "description.equipment"):
            expected = {target for jp, target in keymap.items() if jp in entry["source"]}
            actual = {target for target in keymap.values() if target in restored}
            if actual != expected:
                helper_issues.append({"id": entry["id"], "missing": sorted(expected - actual), "extra": sorted(actual - expected)})
        if ctx["field"].startswith("description.") and ctx["field"] != "description.quest":
            jp = re.sub(r"⟦GM:\d+⟧", "", entry["masked_source"])
            en = re.sub(r"⟦GM:\d+⟧", "", entry["translation"])
            jn = sorted(re.findall(r"\d+(?:\.\d+)?", jp))
            en_n = sorted(re.findall(r"\d+(?:\.\d+)?", en))
            if jn != en_n:
                number_review.append({"id": entry["id"], "source": entry["source"], "translation": restored, "source_numbers": jn, "target_numbers": en_n})
    sites = gmtt.site_map(snap)
    for row in technical["supplemental_punctuation_sites"]:
        info = sites[row["id"]]
        masked, tokens = gmtt.mask(info["source"], catalog["token_patterns"])
        catalog["entries"].append({"id": row["id"], **info, "masked_source": masked, "tokens": tokens,
                                   "translation": row["planned_text"], "reviewed": True, "font": "font_2", "max_width": None, "max_lines": None})
    validation = gmtt.validate_catalog(catalog, snap, require_complete=True)
    assert not validation["errors"], validation["errors"]
    assert not helper_issues, helper_issues
    waivers = read(ROOT / "number-waivers.json")
    exact_waivers = [{k:v for k,v in row.items() if k != "review_reason"} for row in waivers]
    assert number_review == exact_waivers, "Numeric differences changed; manual review required"
    output = ROOT / "build"
    output.mkdir(exist_ok=True)
    write(output / "catalog.en.json", catalog)
    write(output / "number-review.json", number_review)
    write(output / "text-validation.json", {"manual_units": 368, "locked_names": 245,
          "technical_lookup_sites": 17, "punctuation_sites": 1, "total": len(catalog["entries"]),
          "helper_match_issues": helper_issues, "number_review_candidates": len(number_review),
          "number_differences_reviewed": len(waivers),
          "validation": validation, "method": "Written and reviewed by the primary assistant; no translation API or subagents used."})
    rows = []
    for e in catalog["entries"]:
        rows.append(e["id"] + "\t" + e["source"].replace("\n", "\\n") + "\t" + gmtt.restore(e["translation"], e["tokens"]).replace("\n", "\\n"))
    (output / "review-ja-en.tsv").write_text("ID\tJapanese\tEnglish\n" + "\n".join(rows) + "\n", encoding="utf-8")
    print(json.dumps({"total": len(catalog["entries"]), "helper_issues": helper_issues, "number_review_candidates": len(number_review), "validation_errors": validation["errors"]}))

if __name__ == "__main__":
    main()
