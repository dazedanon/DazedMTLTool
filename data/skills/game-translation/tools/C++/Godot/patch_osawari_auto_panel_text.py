#!/usr/bin/env python3
"""Patch safe visible labels in restored osawari scene files."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


SOURCE_ROOT = Path("unpacked_pck")
OUTPUT_ROOT = Path("translated_assets")
REPORT_DEFAULT = Path("tooling") / "osawari_auto_panel_text_patch_report.json"


SCENE_PATCHES = {
    Path(
        ".godot/exported/133200997/"
        "export-601fabb4f35176ade03fcb1151faa183-osawari_auto_panel.scn"
    ): {
        "\u304a\u305d\u3044": "Slow",
        "\u306f\u3084\u3044": "Fast",
        "\u53f3\u624b": "R Hand",
        "\u5de6\u624b": "L Hand",
        "\u30ad\u30b9": "Kiss",
        "\u8170": "Hip",
    },
    Path(
        ".godot/exported/133200997/"
        "export-26d25f74b2a44cf0f39713778bd690a6-statistics_modal.scn"
    ): {
        "\u5168\u8eab": "Body",
        "\u304a\u304f\u3061": "Mouth",
        "\u306b\u304a\u3044": "Smell",
        "\u4e73\u9996": "Nipple",
        "\u304a\u3057\u308a": "Butt",
        "\u982d": "Top",
        "\u30af\u30ea\u30c8\u30ea\u30b9": "Clitoris",
        "\u81a3": "Vag",
    },
}


def padded(source: str, replacement: str) -> bytes:
    source_bytes = source.encode("utf-8")
    replacement_bytes = replacement.encode("utf-8")
    if len(replacement_bytes) > len(source_bytes):
        raise ValueError(f"replacement is too long: {source!r} -> {replacement!r}")
    return replacement_bytes + (b" " * (len(source_bytes) - len(replacement_bytes)))


def main() -> int:
    report: dict[str, list[dict[str, str]]] = {}
    for scene_rel, patches in SCENE_PATCHES.items():
        source_path = SOURCE_ROOT / scene_rel
        output_path = OUTPUT_ROOT / scene_rel
        if not source_path.exists():
            raise FileNotFoundError(source_path)

        data = source_path.read_bytes()
        changes: list[dict[str, str]] = []
        for source, replacement in patches.items():
            source_bytes = source.encode("utf-8")
            if source_bytes not in data:
                continue
            data = data.replace(source_bytes, padded(source, replacement))
            changes.append({"from": source, "to": replacement})

        if changes:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if not output_path.exists():
                shutil.copy2(source_path, output_path)
            output_path.write_bytes(data)
            report[scene_rel.as_posix()] = changes

    REPORT_DEFAULT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("patched safe restored scene labels:", sum(len(changes) for changes in report.values()))
    print("report:", REPORT_DEFAULT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
