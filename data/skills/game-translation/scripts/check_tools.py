"""Resolve this skill's tools/ folder and report what is present.

Run from anywhere: python <skill>/scripts/check_tools.py
Exit code 0 when every bundled folder is present, 1 otherwise. Missing
third-party downloads are reported but do not fail the check, because the
skill works without most of them until a specific engine needs one.
"""
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TOOLS = SKILL / "tools"
DAZEDTL_ROOT = SKILL.parents[2]

BUNDLED = [
    "Game Translation/GameMaker/gmtt.py",
    "Game Translation/Image Translation/imgtl.py",
    "Game Translation/Text Fitting/layout.py",
    "Game Translation/Text Fitting/panel_bounds.cjs",
    "Game Translation/Text QA and Glossary/autofill_glossary.py",
    "Game Translation/Electron Text Tooling/goborin_text_tool.py",
    "Game Translation/Unity BepInEx Translation Plugin Template/SheepClickerTL",
    "Game Translation/Unity BepInEx Text Layout Plugin/VBV",
    "Game Translation/Unity IL2CPP Text Tools",
    "Game Translation/Unity Text Extraction Pipeline/LoserLife",
    "Game Translation/Reference Pipelines",
    "Game Translation/Active Projects/Artesia (Bakin)/ENGINE-CODES.md",
    "Game Archives/RPG Maker RGSSAD/install-template.ps1",
    "Game Archives/RPG Maker MZ/decrypt_rpgmz_data.js",
    "C++/Godot",
    "C++/Trois/dxa_unpack.py",
    "C++/Yuris/patch_locale.py",
    "C++/Unreal/README.md",
    "C++/Wolf/wolf_rpg_decode/target/release/wolf_rpg_decode.exe",
    "C++/Wolf/wolf_unpack/target/release/wolf_unpack.exe",
    ".NET/Il2CppDumper-ManualReg/Il2CppDumper.sln",
    ".NET/unityil2.py",
    "ForumPostGen/forum_post_generator.py",
]

# Locations the references expect once the download in THIRD-PARTY.md is done.
THIRD_PARTY = [
    ("UndertaleModTool CLI (run GameMaker/bootstrap.py)", "Game Translation/GameMaker/vendor/utmt"),
    ("AssetRipper", ".NET/AssetRipper/AssetRipper.GUI.Free.exe"),
    ("Il2CppDumper 6.7.46", ".NET/Il2CppDumper-win-v6.7.46/Il2CppDumper.exe"),
    ("Il2CppDumper-ManualReg build", ".NET/Il2CppDumper-ManualReg/Il2CppDumper/bin/Release/net8.0/Il2CppDumper.exe"),
    ("dnSpy", ".NET/dnspy/dnSpy.exe"),
    ("de4dot", ".NET/de4dotex/de4dot-x64.exe"),
    ("Detect It Easy", ".NET/die/diec.exe"),
    ("retoc", "C++/Unreal/retoc/retoc.exe"),
    ("repak", "C++/Unreal/repak/repak.exe"),
    ("UAssetGUI", "C++/Unreal/UAssetGUI/UAssetGUI.exe"),
    ("FModel", "C++/FModel/FModel.exe"),
    ("RV2JSON", "DAZEDTL_ROOT/util/ace/offline/RV2JSON.exe"),
    ("RPGMakerDecrypter CLI", "DAZEDTL_ROOT/util/ace/offline/RPGMakerDecrypter-cli.exe"),
    ("VBV reference DLLs", "Game Translation/Unity BepInEx Text Layout Plugin/VBV/References/UnityEngine.dll"),
    ("WolfDawn wolf CLI", "DAZEDTL_ROOT/util/wolfdawn/bin/windows/wolf.exe"),
]


def main() -> int:
    print(f"skill root : {SKILL}")
    print(f"tools root : {TOOLS}")
    print(f"DazedTL    : {DAZEDTL_ROOT}")
    if not TOOLS.is_dir():
        print("tools/ is missing next to SKILL.md; the bundle was not copied whole.")
        return 1

    missing = [rel for rel in BUNDLED if not (TOOLS / rel).exists()]
    print(f"\nbundled    : {len(BUNDLED) - len(missing)}/{len(BUNDLED)} present")
    for rel in missing:
        print(f"  MISSING  tools/{rel}")
    shared = ("util/len_translation.py", "util/len_git.py", "util/skills/system.py", "scripts/len_translation.py", "data/skills/project_setup.md")
    missing_shared = [rel for rel in shared if not (DAZEDTL_ROOT / rel).is_file()]
    print(f"shared     : {len(shared) - len(missing_shared)}/{len(shared)} present")
    for rel in missing_shared:
        print(f"  MISSING  DAZEDTL_ROOT/{rel}")

    print("\nthird-party:")
    for name, rel in THIRD_PARTY:
        path = DAZEDTL_ROOT / rel.removeprefix("DAZEDTL_ROOT/") if rel.startswith("DAZEDTL_ROOT/") else TOOLS / rel
        state = "present" if path.exists() else "absent "
        print(f"  {state}  {name:45s} {path}")
    print("\nAbsent third-party tools are listed with download sources in tools/THIRD-PARTY.md.")
    return 1 if missing or missing_shared else 0


if __name__ == "__main__":
    sys.exit(main())
