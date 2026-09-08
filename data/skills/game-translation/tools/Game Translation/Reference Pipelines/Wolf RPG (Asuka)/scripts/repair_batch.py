"""Mechanical post-fetch repairs on batch.json translations.

1. JSON escape collision: the model writes Wolf codes \\f[..] / \\r[..] as "\\f"/"\\r"
   inside JSON strings, which json.loads decodes to form-feed / carriage-return
   characters. Game text has no legitimate FF/CR, so FF+'[' -> \\f[ and CR+'[' -> \\r[.
2. Speaker tags left in Japanese: [社長] etc. at the start of a message line.
   Replaced from the glossary (names + aliases) and the translated names.json lines.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_translate import (load_batch, save_batch, load_glossary,
                              is_names_file, JP_RE)


def build_name_map(batch, glossary):
    m = {}
    for l in batch["lines"]:
        if is_names_file(l["file"]) and (l.get("text") or "").strip():
            src, tl = l["source"].strip(), l["text"].strip()
            if src != tl and JP_RE.search(src):
                m[src] = tl
    # glossary wins over the names batch
    for jp, v in glossary.get("names", {}).items():
        en = v.get("en") if isinstance(v, dict) else str(v)
        if not en:
            continue
        m[jp] = en
        for alias in (v.get("aliases") or []) if isinstance(v, dict) else []:
            m.setdefault(alias, en)
    return m


def main():
    batch = load_batch()
    glossary = load_glossary()
    name_map = build_name_map(batch, glossary)

    ff_fixed = cr_fixed = tag_fixed = 0
    tag_re = re.compile(r"\[([^\[\]\n]{1,24})\]")
    for l in batch["lines"]:
        tl = l.get("text") or ""
        if not tl:
            continue
        orig = tl
        if "\x0c[" in tl:
            tl = tl.replace("\x0c[", "\\f[")
            ff_fixed += 1
        if "\x0d[" in tl:
            tl = tl.replace("\x0d[", "\\r[")
            cr_fixed += 1

        def sub_tag(m):
            nonlocal tag_fixed
            inner = m.group(1)
            if JP_RE.search(inner) and inner in name_map:
                tag_fixed += 1
                return f"[{name_map[inner]}]"
            return m.group(0)

        tl = tag_re.sub(sub_tag, tl)
        if tl != orig:
            l["text"] = tl

    save_batch(batch)
    print(f"form-feed \\f repairs : {ff_fixed} lines")
    print(f"carriage  \\r repairs : {cr_fixed} lines")
    print(f"speaker-tag repairs  : {tag_fixed} tags")
    print(f"name map size        : {len(name_map)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
