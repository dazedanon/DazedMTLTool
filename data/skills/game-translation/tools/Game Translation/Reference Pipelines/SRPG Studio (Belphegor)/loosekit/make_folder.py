#!/usr/bin/env python3
r"""Build the editable Project\ folder from the game's project.dat.

Unpacks project.dat (via SRPG_Unpacker) and writes the native SRPG JSON tree exactly
as extracted (items.json, Maps\map_000.json, ...), except every translatable string is
wrapped as {"jp": "<original>", "en": ""}. Drop it in as Project\ and the game reads
it directly; fill in the "en" fields to translate. Blank "en" stays Japanese.

    python make_folder.py                                  # _jpbase\project.dat -> Project\
    python make_folder.py --en translation_en_backup       # also fill EN from an old folder
    python make_folder.py --project <project.dat> --out Project
    python make_folder.py --unpacked <dump>                # reuse an existing unpack

Only string fields containing Japanese are wrapped; speaker / comment / fontName fields
are left alone (speaker names translate through the unit-name entries).
"""
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))
def _find_unpacker():
    for c in (os.path.join(HERE, "..", "SRPG_Unpacker", "SRPG_Unpacker.exe"),                    # kit layout
              os.path.join(HERE, "..", "SRPG-ToolBox", "SRPG_Unpacker", "x64", "Release", "SRPG_Unpacker.exe"),
              os.path.join(ROOT, "tooling", "SRPG-ToolBox", "SRPG_Unpacker", "x64", "Release", "SRPG_Unpacker.exe")):
        if os.path.exists(c):
            return c
    return c
UNPACKER = _find_unpacker()

JPAT = re.compile("[぀-ヿ㐀-鿿＀-￯　-〿]")
SKIP = {"speaker", "comment", "fontName"}


def leaf(path):
    return re.sub(r"\[\d+\]$", "", path.split("/")[-1]) if path else ""


def transform(node, path, src, en):
    if isinstance(node, dict):
        return {k: transform(v, (path + "/" + k) if path else k, src, en) for k, v in node.items()}
    if isinstance(node, list):
        return [transform(v, "%s[%d]" % (path, i), src, en) for i, v in enumerate(node)]
    if isinstance(node, str) and node and leaf(path) not in SKIP and JPAT.search(node):
        e = en.get("%s#%s" % (src, path), "")
        return {"jp": node, "en": "" if e == node else e}     # e==jp means untranslated
    return node


def ser(node, ind):
    pad = "    " * ind
    if isinstance(node, dict):
        if list(node.keys()) == ["jp", "en"]:
            return json.dumps(node, ensure_ascii=False)          # wrapped string -> one line
        if not node:
            return "{}"
        body = ",\n".join("%s    %s: %s" % (pad, json.dumps(k, ensure_ascii=False), ser(v, ind + 1))
                          for k, v in node.items())
        return "{\n%s\n%s}" % (body, pad)
    if isinstance(node, list):
        if not node:
            return "[]"
        body = ",\n".join("%s    %s" % (pad, ser(v, ind + 1)) for v in node)
        return "[\n%s\n%s]" % (body, pad)
    return json.dumps(node, ensure_ascii=False)


def load_en(folder):
    """Build {id -> en} from an existing category folder (translation_en_backup)."""
    en = {}
    if not folder or not os.path.isdir(folder):
        return en
    for dp, _, names in os.walk(folder):
        for n in names:
            if not n.endswith(".jsonl"):
                continue
            for line in open(os.path.join(dp, n), encoding="utf-8"):
                line = line.strip()
                if not line:
                    continue
                o = json.loads(line)
                if "_group" not in o and o.get("en"):
                    en[o["id"]] = o["en"]
    return en


def walk_en_tree(root):
    """Build {<file>#<path> -> value} from an EN JSON tree (the inject output)."""
    en = {}
    def walk(node, path, src):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, (path + "/" + k) if path else k, src)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, "%s[%d]" % (path, i), src)
        elif isinstance(node, str):
            en["%s#%s" % (src, path)] = node
    for dp, _, names in os.walk(root):
        for n in names:
            if not n.endswith(".json"):
                continue
            src = os.path.relpath(os.path.join(dp, n), root).replace(os.sep, "/")
            try:
                walk(json.load(open(os.path.join(dp, n), encoding="utf-8")), "", src)
            except (OSError, ValueError):
                pass
    return en


def main():
    ap = argparse.ArgumentParser(description="Build the Project folder from project.dat.")
    ap.add_argument("--project", default=os.path.join(ROOT, "tooling", "_jpbase", "project.dat"))
    ap.add_argument("--unpacked", help="use an already-unpacked dump instead of running the unpacker")
    ap.add_argument("--out", default=os.path.join(ROOT, "Project"))
    ap.add_argument("--en", help="an existing category folder to copy 'en' values from")
    ap.add_argument("--store", help="translation store (e.g. tooling/tl) — reflows EN via inject")
    ap.add_argument("--keep-unpack", action="store_true")
    args = ap.parse_args()

    tmp = None
    if args.unpacked:
        unpacked = args.unpacked
    else:
        tmp = unpacked = os.path.join(HERE, "_jpunpack")
        if os.path.exists(tmp):
            shutil.rmtree(tmp)
        subprocess.run([UNPACKER, args.project, "-c", "-o", tmp], check=True, stdout=subprocess.DEVNULL)

    if args.store:
        # run the translation pipeline's inject (reflow / page-align / glossary names)
        # and copy EN from its output, so the folder matches what data.dts shows.
        sys.path.insert(0, os.path.join(HERE, ".."))
        from srpgtl import inject
        enroot = os.path.join(HERE, "_entree")
        if os.path.exists(enroot):
            shutil.rmtree(enroot)
        inject.inject_patch(unpacked, args.store, in_place=False, out_dir=enroot)
        en = walk_en_tree(enroot)
        shutil.rmtree(enroot, ignore_errors=True)
    else:
        en = load_en(args.en)

    if os.path.exists(args.out):
        shutil.rmtree(args.out)
    files = wrapped = 0
    for dp, _, names in os.walk(unpacked):
        for n in names:
            if not n.endswith(".json"):
                continue
            src = os.path.relpath(os.path.join(dp, n), unpacked).replace(os.sep, "/")
            data = json.load(open(os.path.join(dp, n), encoding="utf-8"))
            out = transform(data, "", src, en)
            text = ser(out, 0)
            wrapped += text.count('{"jp":')
            op = os.path.join(args.out, *src.split("/"))
            os.makedirs(os.path.dirname(op), exist_ok=True)
            open(op, "w", encoding="utf-8", newline="\n").write(text + "\n")
            files += 1

    if tmp and not args.keep_unpack:
        shutil.rmtree(tmp, ignore_errors=True)
    print("wrote %s: %d files, %d strings wrapped (%d filled from --en)"
          % (args.out, files, wrapped, len(en)))


if __name__ == "__main__":
    main()
