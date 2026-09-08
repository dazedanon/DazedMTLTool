"""Compile the reviewed English layout changes, or just the tooltip hotfix."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = ROOT.parent if (ROOT.parent / "catalog.prepared.json").exists() else Path("C:/Users/sw/Desktop/Tools/Game Translation/Active Projects/Nightfall Princess (GameMaker)")
TOOLKIT = Path("C:/Users/sw/Desktop/Tools/Game Translation/GameMaker")
spec = importlib.util.spec_from_file_location("gmtt", TOOLKIT / "gmtt.py")
gmtt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gmtt)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tooltip-only", action="store_true", help="Update an existing English archive")
    args = parser.parse_args()
    assert args.input.is_file() and not args.output.exists()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    original = (PROJECT / "source/gml/gml_Object_obj_dialog_Step_0.gml").read_text(encoding="utf-8")
    old = "    geo_text_max = geo_story[geo_text_y];"
    assert original.count(old) == 1
    updated = original.replace(old, "    draw_set_font(font_2);\n    geo_text_max = scr_newline(geo_story[geo_text_y], 510);")
    step = HERE / "gml_Object_obj_dialog_Step_0.gml"
    step.write_text(updated, encoding="utf-8")
    option = (PROJECT / "source/gml/gml_Object_obj_option_Draw_0.gml").read_text(encoding="utf-8")
    old_option = "else\n{\n    tmp_spr = spr_option_back_2;\n}"
    assert option.count(old_option) == 1
    option = option.replace(old_option, "else if (room != room_title)\n{\n    tmp_spr = spr_option_back_2;\n}")
    (HERE / "gml_Object_obj_option_Draw_0.gml").write_text(option, encoding="utf-8")
    talent = (PROJECT / "source/gml/gml_Object_obj_talent_Draw_0.gml").read_text(encoding="utf-8")
    old_title = "        draw_text(tmp_x + 70, tmp_y + 7, scr_name_skill(geo_skill[geo_talent[geo_mouse_x][geo_mouse_y] - 10]));"
    assert talent.count(old_title) == 1
    new_title = """        var tmp_title = scr_name_skill(geo_skill[geo_talent[geo_mouse_x][geo_mouse_y] - 10]);
        var tmp_title_width = sprite_get_width(spr_talent_bg_2) - 70 - 14;
        var tmp_title_scale = min(1, tmp_title_width / max(1, string_width(tmp_title)));
        var tmp_title_y = tmp_y + 7 + ((1 - tmp_title_scale) * string_height(tmp_title) * 0.5);
        draw_text_transformed(tmp_x + 70, tmp_title_y, tmp_title, tmp_title_scale, tmp_title_scale, 0);"""
    talent = talent.replace(old_title, new_title)
    (HERE / "gml_Object_obj_talent_Draw_0.gml").write_text(talent, encoding="utf-8")
    names = ("gml_Object_obj_talent_Draw_0",) if args.tooltip_only else (
        "gml_GlobalScript_scr_newline", "gml_Object_obj_dialog_Step_0", "gml_Object_obj_option_Draw_0", "gml_Object_obj_talent_Draw_0")
    request = {"changes": [{"name": name, "source": str((HERE / (name + ".gml")).resolve())}
                           for name in names],
               "receipt": str((HERE / "compile-receipt.txt").resolve())}
    config = HERE / "request.json"
    config.write_text(json.dumps(request, indent=2), encoding="utf-8")
    before = gmtt.snapshot(args.input)
    env = os.environ.copy()
    env["NFP_LAYOUT_REQUEST"] = str(config.resolve())
    log = gmtt.run_utmt(["load", args.input.resolve(), "-s", HERE / "import.csx", "-o", args.output.resolve()], env, HERE / "compile.log")
    after = gmtt.snapshot(args.output)
    assert before["strings"] == after["strings"][:len(before["strings"])], "Original string pool changed"
    assert len(before["code"]) == len(after["code"]), "Code identities changed"
    allowed = {x["name"] for x in request["changes"]}
    allowed_indices = {c["index"] for c in before["code"] if c["name"] in allowed}
    changed_code = []
    for a, b in zip(before["code"], after["code"]):
        assert a["name"] == b["name"] and a["index"] == b["index"] and a["parent"] == b["parent"]
        if a != b:
            assert a["index"] in allowed_indices or a["parent"] in allowed_indices, a["name"]
            changed_code.append(a["name"])
    resource_changes = {}
    for key, a in before["resources"].items():
        b = after["resources"][key]
        if a != b:
            assert key in ("Variables", "Functions", "CodeLocals") and a == b[:len(a)], key
            resource_changes[key] = len(b) - len(a)
    ignored = {"strings", "code", "resources", "source_sha256", "source_size"}
    for key, value in before.items():
        if key not in ignored:
            assert after[key] == value, key
    report = {"input_sha256": before["source_sha256"], "output_sha256": after["source_sha256"],
              "changed_code": changed_code, "appended_resources": resource_changes,
              "original_strings_preserved": len(before["strings"]), "fonts_and_media_unchanged": True,
              "save_schema_unchanged": True, "runtime_tested": False}
    report["tooltip_title_fitting"] = {"right_padding": 14, "skill_name_x": 70, "shrink_only": True,
                                       "wording_and_descriptions_unchanged": True}
    Path(str(args.output) + ".layout-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))

if __name__ == "__main__":
    main()
