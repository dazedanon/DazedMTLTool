#!/usr/bin/env python3
import argparse
import base64
import csv
import json
import re
import sys
from pathlib import Path


TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "tools" / "python"))

try:
    from pylocres.locmeta import LocmetaFile, LocmetaVersion
    from pylocres.locres import Entry, LocresFile, Namespace
except Exception as exc:
    raise SystemExit(
        "Unable to import pylocres. Run 01_bootstrap_tools.ps1, then make sure "
        ".translation_tooling/tools/python is readable."
    ) from exc


DEFAULT_CULTURES = ["en", "en-US", "ja", "ja-JP", "pt", "pt-BR"]
DEFAULT_TARGETS = ["Game", "StoryFramework"]


def pointer_unescape(part):
    return part.replace("~1", "/").replace("~0", "~")


def get_pointer(data, pointer):
    if pointer == "":
        return data
    node = data
    for part in [pointer_unescape(p) for p in pointer.split("/")[1:]]:
        if isinstance(node, list):
            node = node[int(part)]
        else:
            node = node[part]
    return node


def read_csv_rows(path):
    with Path(path).open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def select_rows(rows, row_id="", source=""):
    selected = []
    for row in rows:
        if row_id and row.get("id") == row_id:
            selected.append(row)
        elif source and row.get("source") == source:
            selected.append(row)
    return selected


def infer_locres_key(json_dir, row, explicit_key=""):
    if explicit_key:
        return explicit_key
    if row.get("encoding") != "utf16le-null":
        raise ValueError("automatic locres key inference only supports utf16le-null rows")

    json_path = Path(json_dir) / row["json_file"]
    with json_path.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)

    blob = base64.b64decode(get_pointer(data, row["json_pointer"]))
    source_bytes = row["source"].encode("utf-16le") + b"\x00\x00"
    offset = int(row["raw_offset"])
    if blob[offset:offset + len(source_bytes)] != source_bytes:
        raise ValueError(f"source bytes did not match {row['json_file']} at {offset}")

    pos = offset + len(source_bytes)
    if pos >= len(blob) or blob[pos] != 0x1F:
        raise ValueError("could not find the script string token before the locres key")

    pos += 1
    end = blob.find(b"\x00", pos)
    if end < 0:
        raise ValueError("locres key did not have a null terminator")

    key = blob[pos:end].decode("ascii", errors="strict")
    if not re.fullmatch(r"[0-9A-Fa-f]{16,64}", key):
        raise ValueError(f"inferred key did not look like a UE text key: {key!r}")
    return key


def namespace_candidates(json_file):
    asset = re.sub(r"\.json$", "", json_file.replace("\\", "/"))
    if asset.startswith("StoryFramework/Content/"):
        content_rel = asset[len("StoryFramework/Content/"):]
    else:
        content_rel = asset
    package = "/Game/" + content_rel
    asset_name = package.rsplit("/", 1)[-1]
    return [
        "",
        asset_name,
        package,
        f"{package}.{asset_name}",
        f"{asset_name}_DirectorBP_C",
        f"{package}.{asset_name}_DirectorBP_C",
    ]


def add_entry(locres_path, namespaces, key, runtime_source, translation):
    if locres_path.exists():
        locres = LocresFile()
        locres.read(locres_path)
    else:
        locres = LocresFile()

    for namespace_name in namespaces:
        namespace = locres[namespace_name]
        if namespace is None:
            namespace = Namespace(namespace_name)
            locres.add(namespace)
        namespace.add(Entry(key, translation, runtime_source, is_hash=False))

    locres_path.parent.mkdir(parents=True, exist_ok=True)
    locres.write(locres_path)


def write_locmeta(target_dir, target, cultures, native_culture):
    target_dir.mkdir(parents=True, exist_ok=True)
    locmeta = LocmetaFile(
        version=LocmetaVersion.V1,
        native_culture=native_culture,
        native_locres=f"{native_culture}/{target}.locres",
        compiled_cultures=cultures,
    )
    locmeta.write(str(target_dir / f"{target}.locmeta"))


def main():
    parser = argparse.ArgumentParser(description="Add UE locres overrides to the patch directory.")
    parser.add_argument("--csv", required=True)
    parser.add_argument("--json-dir", required=True)
    parser.add_argument("--patch-dir", required=True)
    parser.add_argument("--id", default="")
    parser.add_argument("--source", default="")
    parser.add_argument("--translation", required=True)
    parser.add_argument("--runtime-source", required=True)
    parser.add_argument("--locres-key", default="")
    parser.add_argument("--namespace", action="append", default=[])
    parser.add_argument("--culture", action="append", default=[])
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--native-culture", default="ja")
    args = parser.parse_args()

    if not args.id and not args.source and not args.locres_key:
        raise SystemExit("Pass --id, --source, or --locres-key.")

    rows = read_csv_rows(args.csv)
    selected = select_rows(rows, args.id, args.source)
    if not selected and not args.locres_key:
        raise SystemExit("No matching translation row found.")
    if len(selected) > 1 and not args.locres_key:
        raise SystemExit("More than one row matched. Use --id or --locres-key.")

    row = selected[0] if selected else {"json_file": "", "encoding": "utf16le-null"}
    locres_key = infer_locres_key(args.json_dir, row, args.locres_key)
    namespaces = []
    namespaces.extend(namespace_candidates(row["json_file"]) if row.get("json_file") else [""])
    namespaces.extend(args.namespace)
    namespaces = list(dict.fromkeys(namespaces))

    cultures = args.culture or DEFAULT_CULTURES
    targets = args.target or DEFAULT_TARGETS
    patch_dir = Path(args.patch_dir)

    written = 0
    for target in targets:
        target_dir = patch_dir / "StoryFramework" / "Content" / "Localization" / target
        write_locmeta(target_dir, target, cultures, args.native_culture)
        written += 1
        for culture in cultures:
            locres_path = target_dir / culture / f"{target}.locres"
            add_entry(locres_path, namespaces, locres_key, args.runtime_source, args.translation)
            written += 1

    print(f"wrote {written} localization files for key {locres_key}")
    print("namespaces:")
    for namespace in namespaces:
        print(f"  {namespace!r}")


if __name__ == "__main__":
    main()
