#!/usr/bin/env python3
"""Create translated data markdown overlays from the translated locale PO files."""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path


SOURCE_ROOT_DEFAULT = Path("unpacked_pck") / "data"
OVERLAY_ROOT_DEFAULT = Path("translated_assets") / "data"
ITEMS_PO_DEFAULT = Path("translated_assets") / "locale" / "ja_JP" / "items.po"
REPORT_DEFAULT = Path("tooling") / "data_markdown_patch_report.json"

ENTRY_RE = re.compile(
    r'msgctxt\s+"(?P<context>[^"]+)"\s*\n'
    r'msgid\s+"(?P<id>[^"]+)"\s*\n'
    r'msgstr\s+"(?P<value>(?:[^"\\]|\\.)*)"',
    re.MULTILINE,
)

SHOP_BODY_REPLACEMENTS = {
    "ショップ設定を一元管理。level_up_items の配列長 = max_level。": (
        "Centralized shop configuration. The length of level_up_items equals max_level."
    ),
}


def po_unescape(value: str) -> str:
    return ast.literal_eval(f'"{value}"')


def load_item_translations(path: Path) -> dict[str, dict[str, str]]:
    text = path.read_text(encoding="utf-8-sig")
    translations: dict[str, dict[str, str]] = {}
    for match in ENTRY_RE.finditer(text):
        context = match.group("context")
        if context not in {"item_name", "item_description"}:
            continue
        item_id = match.group("id")
        value = po_unescape(match.group("value"))
        translations.setdefault(item_id, {})[context] = value
    return translations


def split_frontmatter(text: str) -> tuple[str, str]:
    if not text.startswith("---\n"):
        return "", text
    end = text.find("\n---", 4)
    if end == -1:
        return "", text
    end_line = text.find("\n", end + 1)
    if end_line == -1:
        return text, ""
    return text[: end_line + 1], text[end_line + 1 :]


def build_item_markdown(original_text: str, item_id: str, translations: dict[str, dict[str, str]]) -> str | None:
    item = translations.get(item_id, {})
    name = item.get("item_name", "").strip()
    description = item.get("item_description", "").strip()
    if not name:
        return None

    frontmatter, _body = split_frontmatter(original_text)
    body_parts = [f"# {name}"]
    if description:
        body_parts.extend(["", description])
    spacer = "\n" if frontmatter else ""
    return frontmatter + spacer + "\n".join(body_parts).rstrip() + "\n"


def build_shop_markdown(original_text: str) -> str | None:
    patched = original_text
    for source, replacement in SHOP_BODY_REPLACEMENTS.items():
        patched = patched.replace(source, replacement)
    return patched if patched != original_text else None


def patch_data_tree(source_root: Path, overlay_root: Path, items_po: Path, dry_run: bool) -> list[dict[str, str]]:
    translations = load_item_translations(items_po)
    report: list[dict[str, str]] = []

    for source_path in sorted((source_root / "items").rglob("*.md")):
        item_id = source_path.stem
        original_text = source_path.read_text(encoding="utf-8-sig")
        patched = build_item_markdown(original_text, item_id, translations)
        if patched is None or patched == original_text:
            continue

        rel = source_path.relative_to(source_root)
        dest = overlay_root / rel
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(patched, encoding="utf-8", newline="\n")
        report.append({"file": rel.as_posix(), "source": "items.po"})

    shop_source = source_root / "shop" / "shop.md"
    if shop_source.exists():
        original_text = shop_source.read_text(encoding="utf-8-sig")
        patched = build_shop_markdown(original_text)
        if patched is not None:
            rel = shop_source.relative_to(source_root)
            dest = overlay_root / rel
            if not dry_run:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(patched, encoding="utf-8", newline="\n")
            report.append({"file": rel.as_posix(), "source": "inline"})

    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Patch visible text in data markdown files.")
    parser.add_argument("--source-root", type=Path, default=SOURCE_ROOT_DEFAULT)
    parser.add_argument("--overlay-root", type=Path, default=OVERLAY_ROOT_DEFAULT)
    parser.add_argument("--items-po", type=Path, default=ITEMS_PO_DEFAULT)
    parser.add_argument("--report", type=Path, default=REPORT_DEFAULT)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source_root.exists():
        raise FileNotFoundError(f"Missing source data root: {args.source_root}")
    if not args.items_po.exists():
        raise FileNotFoundError(f"Missing translated items PO: {args.items_po}")

    report = patch_data_tree(args.source_root, args.overlay_root, args.items_po, args.dry_run)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("patched data markdown files:", len(report))
    print("report:", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
