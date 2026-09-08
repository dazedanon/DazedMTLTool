#!/usr/bin/env python3
"""Patch punctuation-only Japanese quote pairs in translated scenario text."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT_DEFAULT = Path("translated_assets") / "scenarios"
REPORT_DEFAULT = Path("tooling") / "punctuation_dialogue_patch_report.json"

QUOTE_RE = re.compile(r"(?P<open>[\u300c\u300e])(?P<body>.*?)(?P<close>[\u300d\u300f])")
TAG_RE = re.compile(r"\[[^\]\[]+\]")
TEXTUAL_JAPANESE_RE = re.compile(r"[\u3040-\u30fa\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")

PUNCT_TRANSLATION = str.maketrans(
    {
        "\u2026": "...",
        "\u30fb": ".",
        "\u3001": ",",
        "\u3002": ".",
        "\uff01": "!",
        "\uff1f": "?",
        "\uff0e": ".",
        "\uff0c": ",",
        "\u301c": "~",
        "\uff5e": "~",
        "\u30fc": "-",
        "\u2014": "-",
        "\u2015": "-",
        "\u3000": " ",
    }
)


def normalize_punctuation(body: str) -> str:
    return body.translate(PUNCT_TRANSLATION)


def should_patch_quote_body(body: str) -> bool:
    visible_text = TAG_RE.sub("", body).strip()
    return bool(visible_text) and not TEXTUAL_JAPANESE_RE.search(visible_text)


def patch_line(line: str) -> tuple[str, list[dict[str, str]]]:
    changes: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        original = match.group(0)
        if not should_patch_quote_body(match.group("body")):
            return original
        replacement = f'"{normalize_punctuation(match.group("body"))}"'
        if replacement != original:
            changes.append({"from": original, "to": replacement})
        return replacement

    return QUOTE_RE.sub(replace, line), changes


def patch_file(path: Path, dry_run: bool) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    patched_lines: list[str] = []
    report: list[dict[str, object]] = []

    for line_number, line in enumerate(lines, start=1):
        patched, changes = patch_line(line)
        patched_lines.append(patched)
        if changes:
            report.append(
                {
                    "line": line_number,
                    "before": line.rstrip("\r\n"),
                    "after": patched.rstrip("\r\n"),
                    "changes": changes,
                }
            )

    if report and not dry_run:
        path.write_text("".join(patched_lines), encoding="utf-8", newline="")

    return report


def patch_tree(root: Path, dry_run: bool) -> dict[str, object]:
    files: list[dict[str, object]] = []
    line_count = 0
    replacement_count = 0

    for path in sorted(root.rglob("*.txt")):
        file_report = patch_file(path, dry_run)
        if not file_report:
            continue

        line_count += len(file_report)
        replacement_count += sum(len(item["changes"]) for item in file_report)
        files.append({"file": path.relative_to(root).as_posix(), "lines": file_report})

    return {
        "root": str(root),
        "dry_run": dry_run,
        "files_changed": len(files),
        "lines_changed": line_count,
        "replacements": replacement_count,
        "files": files,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch punctuation-only Japanese quote pairs.")
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        default=ROOT_DEFAULT,
        help="Translated scenarios folder to patch.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=REPORT_DEFAULT,
        help="JSON report path.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing files.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.root.exists():
        raise FileNotFoundError(f"Scenario folder missing: {args.root}")

    report = patch_tree(args.root, args.dry_run)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("Files changed:", report["files_changed"])
    print("Lines changed:", report["lines_changed"])
    print("Replacements:", report["replacements"])
    print("Report:", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
