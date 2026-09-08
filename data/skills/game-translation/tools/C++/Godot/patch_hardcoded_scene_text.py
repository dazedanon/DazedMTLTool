#!/usr/bin/env python3
"""Patch visible Japanese text baked into exported Godot binary scenes.

The normal translation injector updates scenario text and .po locale files.
Some Godot scenes also contain literal Button/Label text in exported .scn
resources. This script patches those strings in-place-length by replacing the
UTF-8 payload and padding with spaces, which avoids rewriting the binary scene
layout.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path


Patch = tuple[str, str]


RISKY_ASSET_SCENE_RE = re.compile(
    r"(?:goal|novel_front|osawari_auto_panel|posure|sleep_day|sleep_night|statistics_modal|ticket_)",
    re.IGNORECASE,
)


PATCHES: dict[str, Patch] = {
    "\u4f53\u9a13\u7248\u3092\u30d7\u30ec\u30a4\u3057\u3066\u3044\u305f\u3060\u304d\u3042\u308a\u304c\u3068\u3046\u3054\u3056\u3044\u307e\u3059\uff01\n\n\u88fd\u54c1\u7248\u3067\u306f\u30bb\u30fc\u30d6\u30c7\u30fc\u30bf\u3092\u5f15\u304d\u7d99\u304e\u3001\u7d9a\u304d\u304b\u3089\u30d7\u30ec\u30a4\u3059\u308b\u3053\u3068\u304c\u3067\u304d\u307e\u3059\u3002\n\u3088\u308d\u3057\u3051\u308c\u3070\u3001\u305c\u3072\u88fd\u54c1\u7248\u3082\u304a\u697d\u3057\u307f\u304f\u3060\u3055\u3044\u3002": (
        "Thank you for playing the demo!\n\nIn the full version, you can carry over your save data and continue from there.\nPlease enjoy the full version too.",
        "left",
    ),
    "\u5185\u90e8\u30ec\u30d3\u30e5\u30fc\u7528\n\u30dc\u30bf\u30f3\u3092\u62bc\u3059\u3068\u30a4\u30d9\u30f3\u30c8\u30b7\u30fc\u30f3\u306b\u9077\u79fb\u3057\u307e\u3059": (
        "Internal review\nPress buttons to jump scenes.",
        "left",
    ),
    "\u3053\u306e\u30c6\u30ad\u30b9\u30c8\u304c\u8868\u793a\u3055\u308c\u3066\u3044\u308b\u306e\u306f\n\u306a\u306b\u304b\u304c\n\u304a\u304b\u3057\u3044\u3067\u3059": (
        "If this text is displayed,\nsomething is wrong.",
        "left",
    ),
    "\u3053\u306e\u30c6\u30ad\u30b9\u30c8\u304c\n\u898b\u3048\u3066\u3044\u308b\u306e\u306f\n\u306a\u306b\u304b\u304c\u304a\u304b\u3057\u3044\u3067\u3059": (
        "If this text is visible,\nsomething is wrong.",
        "left",
    ),
    "\u3053\u306e\u30c6\u30ad\u30b9\u30c8\u304c\u898b\u3048\u3066\u3044\u308b\u306e\u306f\n\u306a\u306b\u304b\u304c\u304a\u304b\u3057\u3044\u3067\u3059": (
        "If this text is visible,\nsomething is wrong.",
        "left",
    ),
    "\u3053\u308c\u304c, \u898b\u3048\u3066\u3044\u308b\u306e\u306f, \u306a\u306b\u304b\u304c, \u304a\u304b\u3057\u3044\u3067\u3059": (
        "If you can see this, something is wrong.",
        "left",
    ),
    "\u3053\u308c\u304c\u307f\u3048\u3066\u3044\u308b\u306e\u306f\n\u306a\u306b\u304b\u304c\u304a\u304b\u3057\u3044\u3067\u3059": (
        "If you can see this,\nsomething is wrong.",
        "left",
    ),
    "\u9053\u5177\u5c4b\u3055\u3093\u304b\u3089\n\u30a2\u30a4\u30c6\u30e0\u3092\u8cfc\u5165\u304c\u3067\u304d\u307e\u3059": (
        "Buy items\nfrom the shopkeeper",
        "left",
    ),
    "\u203b\u5c31\u5bdd\u6642\u306b\u30aa\u30fc\u30c8\u30bb\u30fc\u30d6\u3055\u308c\u307e\u3059(\u6700\u592710\u4ef6)": (
        "Autosaves at bedtime (max 10)",
        "left",
    ),
    "\u6027\u5668\u9732\u51fa\u304c\u3042\u308b\u30b7\u30fc\u30f3\u4e00\u89a7 (\u5dee\u5206\u542b\u3080)": (
        "Exposure Scenes (Variants)",
        "left",
    ),
    "\u30a2\u30a4\u30c6\u30e0\u3092\u9078\u629e\u3057\u3066\u304f\u3060\u3055\u3044": ("Select an item", "left"),
    "\u30bb\u30fc\u30d6\u3059\u308b\u30b9\u30ed\u30c3\u30c8\u3092\u9078\u629e": ("Select save slot", "left"),
    "\u30b9\u30ed\u30c3\u30c8\u3092\u9078\u629e\u3057\u3066\u30ed\u30fc\u30c9": ("Select slot to load", "left"),
    "\u6027\u5668\u9732\u51fa\u304c\u7121\u3044\u30b7\u30fc\u30f3\u4e00\u89a7": ("Non-exposure Scenes", "left"),
    "\uff08\u30d2\u30f3\u30c8\u304c\u8868\u793a\u3055\u308c\u307e\u3059\uff09": ("(Hints shown)", "left"),
    "\u304a\u3055\u308f\u308a\u72b6\u614b\u3092\u30ea\u30bb\u30c3\u30c8": ("Reset touch state", "left"),
    "\u30af\u30a8\u30b9\u30c8\u306b\u51fa\u767a\u3067\u304d\u307e\u3059": ("Quests available", "left"),
    "sleep_night (\u304a\u3055\u308f\u308a)": ("Night Sleep (Touch)", "left"),
    "sleep_day (\u304a\u3055\u308f\u308a)": ("Day Sleep (Touch)", "left"),
    "ticket_minuki (4\u56de\u76ee)": ("Peeking (4th)", "left"),
    "ticket_minuki (3\u56de\u76ee)": ("Peeking (3rd)", "left"),
    "ticket_minuki (2\u56de\u76ee)": ("Peeking (2nd)", "left"),
    "ticket_minuki (\u521d\u56de)": ("Peeking (1st)", "left"),
    "\u3068\u3063\u3066\u304a\u304d\u306e\u5c0f\u74f6\u3092\u3064\u304b\u3046": ("Use special vial", "left"),
    "\u30aa\u30fc\u30c8\u30bb\u30fc\u30d6 (\u6700\u65b0\u21e7)": ("Autosave (newest)", "left"),
    "\u30af\u30a8\u30b9\u30c8\u3044\u304f\u304b\u2026": ("Go quest...", "left"),
    "\u3064\u3088\u3055: 9-54 HP: 111": ("Power: 9-54 HP:111", "left"),
    "\u9ad8\u901f\u6226\u95d8\u30e2\u30fc\u30c9": ("Fast Battle Mode", "left"),
    "\u30ad\u30e3\u30e9\u30af\u30bf\u30fc\u540d": ("Character Name", "left"),
    "\u30b7\u30ca\u30ea\u30aa\u30c6\u30b9\u30c8": ("Scenario Test", "left"),
    "\u6240\u6301\u91d1:": ("Money:", "left"),
    "\u30bf\u30a4\u30c8\u30eb\u306b\u623b\u308b": ("Back to Title", "center"),
    "\u6240\u6301\u6570": ("Owned", "left"),
    "\u5fc5\u8981\u7d20\u6750": ("Materials", "left"),
    "\u58f2\u5374\u4fa1\u683c": ("Sell Price", "left"),
    "\u5546\u54c1\u307f\u305b\u3066!": ("Show wares!", "left"),
    "\u3072\u307f\u3064\u3092\u307f\u308b": ("View Secrets", "center"),
    "\u3076\u3089\u3076\u3089\u3059\u308b": ("Hang out", "left"),
    "\u3082\u3046\u5bdd\u308b\u304b\u2026": ("Sleep...", "left"),
    "\u3057\u305f\u306b\u304a\u308a\u308b": ("Go down", "left"),
    "\u7d20\u6750\u58f2\u308a\u305f\u3044": ("Sell mats", "left"),
    "\u3042\u306e\u3001\u304a\u9858\u3044\u304c": ("Um, a favor...", "left"),
    "\u30a2\u30a4\u30c6\u30e0\u540d": ("Item Name", "left"),
    "\u3046\u3064\u4f0f\u305b\u306b\u3059\u308b": ("Lie prone", "left"),
    "\u3078\u3084\u306b\u3044\u304f": ("Go to room", "left"),
    "\u30d0\u30c3\u30af\u30ed\u30b0": ("Backlog", "center"),
    "\u30ec\u30d3\u30e5\u30fc\u7528": ("Review", "left"),
    "00\u65e5\u76ee \u671d": ("Day 00 AM", "left"),
    "1\u65e5\u76ee 10:00": ("Day 1 10:00", "left"),
    "XXX\u8a0e\u4f10": ("Slay XXX", "left"),
    "\u30af\u30ea\u30c8\u30ea\u30b9": ("Clitoris", "left"),
    "\u653b\u7565\u6e08\u307f!": ("Cleared!", "left"),
    "\u3053\u3093\u306b\u3061\u306f~!": ("Hello~!", "left"),
    "\u30a2\u30a4\u30c6\u30e0": ("Items", "left"),
    "\u306d\u3080\u3089\u305b\u308b": ("Sleep", "left"),
    "\u7d20\u6750:": ("Mat:", "left"),
    "\u653b\u6483\u529b:": ("ATK:", "left"),
    "\u5831\u916c:": ("Reward:", "left"),
    "\u91d1\u7389:": ("Balls:", "left"),
    "\u3064\u3088\u3055:": ("Power:", "left"),
    "\u301c\u304a\u308f\u308a\u301c": ("The End", "center"),
    "\u30a2\u30a4\u30c6\u30e0": ("Items", "left"),
    "\u306b\u304a\u3044": ("Smell", "left"),
    "\u304a\u304f\u3061": ("Mouth", "left"),
    "\u304a\u3057\u308a": ("Butt", "left"),
    "\u304a\u305d\u3044": ("Slow", "left"),
    "\u306f\u3084\u3044": ("Fast", "left"),
    "\u3059\u307e\u305f": ("Thighjob", "left"),
    "\u30bb\u30fc\u30d6": ("Save", "left"),
    "\u30ed\u30fc\u30c9": ("Load", "left"),
    "\u9589\u3058\u308b": ("Close", "center"),
    "\u30d2\u30f3\u30c8": ("Hint", "left"),
    "\u306f\u3044": ("Yes", "center"),
    "\u3044\u3044\u3048": ("No", "center"),
    "\u3084\u3081\u308b": ("Cancel", "left"),
    "\u306a\u3057": ("None", "left"),
    "\u30ad\u30b9": ("Kiss", "left"),
    "\u4e73\u9996": ("Nipple", "left"),
    "\u5168\u8eab": ("Body", "left"),
    "\u53f3\u624b": ("R Hand", "left"),
    "\u5de6\u624b": ("L Hand", "left"),
    "\u53f3\u811a": ("R Leg", "left"),
    "\u5de6\u811a": ("L Leg", "left"),
    "\u53e3": ("Mth", "left"),
    "\u982d": ("Top", "left"),
    "\u81a3": ("Vag", "left"),
    " \u8170": ("Hip", "left"),
    "\u540d\u524d": ("Name", "left"),
    "\u4fa1\u683c": ("Price", "left"),
    "\u5728\u5eab": ("Stock", "left"),
    "\u52dd\u5229!": ("Win!", "center"),
    "\u64cd\u4f5c": ("Keys", "left"),
    "\u8a2d\u5b9a": ("Config", "center"),
    "1\u500b": ("1pc", "left"),
    "\u3072\u307f\u3064": ("Secret", "left"),
}


def padded_replacement(source: str, replacement: str, mode: str) -> bytes:
    source_bytes = source.encode("utf-8")
    replacement_bytes = replacement.encode("utf-8")
    if len(replacement_bytes) > len(source_bytes):
        raise ValueError(
            f"replacement is longer than source: {source!r} -> {replacement!r} "
            f"({len(source_bytes)} < {len(replacement_bytes)})"
        )
    padding = len(source_bytes) - len(replacement_bytes)
    if mode == "center":
        left = padding // 2
        right = padding - left
        return (b" " * left) + replacement_bytes + (b" " * right)
    return replacement_bytes + (b" " * padding)


def patch_file(source_path: Path, output_path: Path, compiled_patches: list[tuple[bytes, bytes, str]]) -> list[str]:
    data = source_path.read_bytes()
    changed: list[str] = []
    for source_bytes, replacement_bytes, label in compiled_patches:
        if source_bytes in data:
            data = data.replace(source_bytes, replacement_bytes)
            changed.append(label)

    if changed:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not output_path.exists():
            shutil.copy2(source_path, output_path)
        output_path.write_bytes(data)

    return changed


def patch_tree(input_root: Path, output_root: Path) -> dict[str, list[str]]:
    compiled = [
        (source.encode("utf-8"), padded_replacement(source, replacement, mode), source)
        for source, (replacement, mode) in PATCHES.items()
    ]
    compiled.sort(key=lambda item: len(item[0]), reverse=True)

    report: dict[str, list[str]] = {}
    for source_path in sorted(input_root.rglob("*")):
        if not source_path.is_file() or source_path.suffix.lower() not in {".scn", ".res"}:
            continue
        if RISKY_ASSET_SCENE_RE.search(source_path.name):
            continue
        relative = source_path.relative_to(input_root)
        changed = patch_file(source_path, output_root / relative, compiled)
        if changed:
            report[str(relative)] = changed
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Patch hard-coded Japanese UI text in exported Godot scenes.")
    parser.add_argument("--input-root", type=Path, default=Path("unpacked_pck") / ".godot" / "exported")
    parser.add_argument("--output-root", type=Path, default=Path("translated_assets") / ".godot" / "exported")
    parser.add_argument("--report", type=Path, default=Path("tooling") / "hardcoded_scene_text_patch_report.json")
    args = parser.parse_args()

    report = patch_tree(args.input_root, args.output_root)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"patched files: {len(report)}")
    print(f"patched strings: {sum(len(items) for items in report.values())}")
    print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
