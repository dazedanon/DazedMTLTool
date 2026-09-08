"""Rename Aria to Airia in translated script sources."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"\bAria\b")


def rename_text(value):
    if isinstance(value, str):
        return NAME_RE.sub("Airia", value)
    return value


def rename_recursive(value):
    if isinstance(value, str):
        return rename_text(value)
    if isinstance(value, list):
        return [rename_recursive(item) for item in value]
    if isinstance(value, dict):
        return {key: rename_recursive(item) for key, item in value.items()}
    return value


def update_dialogue_json(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for entry in data.get("lines", []):
        old = entry.get("text")
        new = rename_text(old)
        if new != old:
            entry["text"] = new
            changed += 1
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return changed


def update_speakers(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    changed = 0
    for key, value in list(data.items()):
        new = rename_text(value)
        if new != value:
            data[key] = new
            changed += 1
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return changed


def update_translated_txt(path):
    old = path.read_text(encoding="utf-8")
    new = rename_text(old)
    if new != old:
        try:
            path.write_text(new, encoding="utf-8")
        except PermissionError:
            print(f"{path.relative_to(ROOT)}: skipped, permission denied")
            return 0
        return old.count("Aria")
    return 0


def update_json_recursive(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    new_data = rename_recursive(data)
    if new_data != data:
        path.write_text(json.dumps(new_data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return True
    return False


def main():
    total_json = 0
    for path in sorted((ROOT / "dialogue").glob("yst*.json")):
        count = update_dialogue_json(path)
        if count:
            print(f"{path.relative_to(ROOT)}: {count} dialogue entries")
            total_json += count

    speaker_count = update_speakers(ROOT / "dialogue" / "_speakers.json")
    print(f"dialogue/_speakers.json: {speaker_count} speaker values")

    glossary_changed = update_json_recursive(ROOT / "dialogue" / "_glossary.json")
    print(f"dialogue/_glossary.json: {'updated' if glossary_changed else 'already clean'}")

    total_txt = 0
    translated_dir = ROOT / "dialogue_translated_done"
    if translated_dir.exists():
        for path in sorted(translated_dir.glob("yst*.txt")):
            count = update_translated_txt(path)
            if count:
                print(f"{path.relative_to(ROOT)}: {count} text hits")
                total_txt += count

    print(f"updated {total_json} dialogue entries, {speaker_count} speaker values, {total_txt} translated-text hits")


if __name__ == "__main__":
    main()
