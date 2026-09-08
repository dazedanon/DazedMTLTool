#!/usr/bin/env python3
"""Extract all player-facing text from NTR Soccer's AssetRipper export.

Sources (verified to be the ONLY places Japanese text exists in the game):
  1. Assets/MonoBehaviour/Dialogue Database.asset  (Pixel Crushers Dialogue System)
     - dialogue entries: base "Dialogue Text" = official English, "ja" = Japanese
     - actors: "Name"/"Display Name" (EN base) + "Name ja"/"Display Name ja"
  2. Assets/MonoBehaviour/UI Localization Text Table.asset (Pixel Crushers TextTable)
     - ~232 UI fields x languages [Default(EN), ja, zh, zh-tw, ko]

Outputs (tools/extracted/):
  dialogue.csv / dialogue.json      every dialogue entry: conv/entry ids, actor, ja, en_official
  actors.csv / actors.json          actor name pairs
  ui_texttable.csv / ui_texttable.json  UI field pairs
  jp_all_strings.txt                every unique Japanese string (one per line, escaped \n)
  needs_translation.json            JP strings with NO official EN -> input for mistral_translate.py
  jp_to_en.json                     JP -> official EN map (from dev's own localization)
  extract_report.txt                summary + integrity checks
"""
import csv
import io
import json
import os
import re
import sys
from collections import OrderedDict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # tools/
GAME = os.path.dirname(ROOT)
EXPORT = os.path.join(GAME, "AssetRipper_export_20260703_000727", "ExportedProject", "Assets")
DB_PATH = os.path.join(EXPORT, "MonoBehaviour", "Dialogue Database.asset")
TT_PATH = os.path.join(EXPORT, "MonoBehaviour", "UI Localization Text Table.asset")
OUT = os.path.join(ROOT, "extracted")

JP_RE = re.compile(r"[぀-ヿ一-鿿！-｠　-〿]")
JP_KANA_KANJI = re.compile(r"[぀-ヿ一-鿿]")


def has_jp(s):
    return bool(s) and bool(JP_KANA_KANJI.search(s))


# ---------------------------------------------------------------- YAML value
def unquote_yaml(v, follow_lines=None):
    """Unquote a single-line YAML scalar the way Unity emits them."""
    v = v.rstrip("\r\n")
    if v.startswith("'") :
        # single-quoted: '' escapes '
        body = v[1:]
        if body.endswith("'"):
            body = body[:-1]
        return body.replace("''", "'")
    if v.startswith('"'):
        body = v[1:]
        if body.endswith('"'):
            body = body[:-1]
        try:
            return body.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
        except (UnicodeDecodeError, UnicodeEncodeError):
            # fallback: just handle the common escapes
            return body.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")
    return v


def read_lines(path):
    with io.open(path, encoding="utf-8", errors="replace") as f:
        return f.read().splitlines()


def parse_title_value_stream(lines):
    """Yield (line_idx, title, value) for every `- title: X / value: Y` pair,
    joining Unity's wrapped multi-line scalars."""
    i = 0
    n = len(lines)
    while i < n:
        m = re.match(r"^(\s*)- title: (.*)$", lines[i])
        if not m:
            i += 1
            continue
        title = m.group(2).strip()
        if i + 1 >= n:
            break
        vm = re.match(r"^(\s*)value: ?(.*)$", lines[i + 1])
        if not vm:
            i += 1
            continue
        indent = len(vm.group(1))
        raw = vm.group(2)
        j = i + 2
        # Unity wraps long scalars onto continuation lines indented deeper than `value:`
        parts = [raw]
        while j < n:
            ln = lines[j]
            if not ln.strip():
                # blank line inside a quoted scalar = paragraph break; only join if
                # the scalar is quoted and unterminated
                if parts and (parts[0].startswith("'") or parts[0].startswith('"')):
                    q = parts[0][0]
                    joined = "\n".join(parts)
                    body = joined[1:]
                    terminated = (
                        body.endswith(q)
                        and not (q == "'" and body.endswith("''") and not body.endswith("'''"))
                    )
                    if not terminated:
                        parts.append("")
                        j += 1
                        continue
                break
            li = len(ln) - len(ln.lstrip())
            if li > indent and not re.match(r"^\s*(- title:|type:|typeString:)", ln):
                parts.append(ln.strip())
                j += 1
            else:
                break
        # Unity folds line-wraps as single spaces
        raw_joined = parts[0]
        for p in parts[1:]:
            if p == "":
                raw_joined += "\n"
            elif raw_joined.endswith("\n"):
                raw_joined += p
            else:
                raw_joined += " " + p
        yield i, title, unquote_yaml(raw_joined)
        i = j


# --------------------------------------------------------------- sections
def find_sections(lines):
    """Locate top-level list sections (actors:, conversations:, variables:...)
    inside the MonoBehaviour body."""
    sections = {}
    for idx, ln in enumerate(lines):
        m = re.match(r"^  (\w[\w ]*):\s*$", ln)
        if m:
            sections[m.group(1)] = idx
    return sections


def section_range(sections, name, total):
    starts = sorted(sections.values())
    if name not in sections:
        return None
    s = sections[name]
    later = [x for x in starts if x > s]
    return s, (later[0] if later else total)


def parse_db(lines):
    sections = find_sections(lines)
    total = len(lines)

    def parse_records(name, id_re=r"^  - id: (\d+)"):
        rng = section_range(sections, name, total)
        if not rng:
            return []
        s, e = rng
        recs = []
        cur = None
        for i in range(s + 1, e):
            m = re.match(id_re, lines[i])
            if m:
                cur = {"id": int(m.group(1)), "_start": i, "fields": OrderedDict()}
                recs.append(cur)
        # attach field ranges
        for k, rec in enumerate(recs):
            fs = rec["_start"]
            fe = recs[k + 1]["_start"] if k + 1 < len(recs) else e
            seg = lines[fs:fe]
            for _, t, v in parse_title_value_stream(seg):
                if t not in rec["fields"]:
                    rec["fields"][t] = v
            del rec["_start"]
        return recs

    actors = parse_records("actors")
    variables = parse_records("variables")

    # conversations: nested (conversation -> dialogueEntries). Parse manually.
    rng = section_range(sections, "conversations", total)
    conversations = []
    if rng:
        s, e = rng
        conv_starts = [i for i in range(s + 1, e) if re.match(r"^  - id: (\d+)", lines[i])]
        for k, cs in enumerate(conv_starts):
            ce = conv_starts[k + 1] if k + 1 < len(conv_starts) else e
            conv_id = int(re.match(r"^  - id: (\d+)", lines[cs]).group(1))
            # find dialogueEntries: subsection
            de_idx = None
            for i in range(cs, ce):
                if re.match(r"^    dialogueEntries:\s*$", lines[i]):
                    de_idx = i
                    break
            conv_fields = OrderedDict()
            head_end = de_idx if de_idx is not None else ce
            for _, t, v in parse_title_value_stream(lines[cs:head_end]):
                if t not in conv_fields:
                    conv_fields[t] = v
            entries = []
            if de_idx is not None:
                entry_starts = [
                    i for i in range(de_idx + 1, ce) if re.match(r"^    - id: (\d+)", lines[i])
                ]
                for m2, es in enumerate(entry_starts):
                    ee = entry_starts[m2 + 1] if m2 + 1 < len(entry_starts) else ce
                    ent_id = int(re.match(r"^    - id: (\d+)", lines[es]).group(1))
                    f = OrderedDict()
                    for _, t, v in parse_title_value_stream(lines[es:ee]):
                        if t not in f:
                            f[t] = v
                    # actor id line
                    am = None
                    for i in range(es, min(es + 400, ee)):
                        mm = re.match(r"^      actor: (\-?\d+)", lines[i])
                        if mm:
                            am = int(mm.group(1))
                            break
                    entries.append({"id": ent_id, "actor": am, "fields": f})
            conversations.append({"id": conv_id, "fields": conv_fields, "entries": entries})
    return actors, variables, conversations


def parse_texttable(lines):
    """Parse Pixel Crushers TextTable: m_languageKeys + m_fieldValues."""
    langs = []
    in_langs = False
    fields = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if re.match(r"^\s*m_languageKeys:", ln):
            in_langs = True
            i += 1
            continue
        if in_langs:
            m = re.match(r"^\s*- (.*)$", ln)
            if m and not ln.strip().startswith("- m_fieldName"):
                langs.append(m.group(1).strip())
                i += 1
                continue
            in_langs = False
        m = re.match(r"^\s*- m_fieldName: (.*)$", ln)
        if m:
            fname = unquote_yaml(m.group(1).strip())
            # keys line then values
            keys = []
            values = []
            j = i + 1
            while j < n and not re.match(r"^\s*- m_fieldName:", lines[j]):
                km = re.match(r"^\s*m_keys: ([0-9a-fA-F]*)\s*$", lines[j])
                if km:
                    hx = km.group(1)
                    keys = [
                        int.from_bytes(bytes.fromhex(hx[x : x + 8]), "little")
                        for x in range(0, len(hx), 8)
                    ]
                vm = re.match(r"^\s*- (.*)$", lines[j])
                if vm and keys:
                    # collect wrapped scalar
                    parts = [vm.group(1)]
                    base_indent = len(lines[j]) - len(lines[j].lstrip())
                    k2 = j + 1
                    while k2 < n:
                        nxt = lines[k2]
                        if not nxt.strip():
                            break
                        ind = len(nxt) - len(nxt.lstrip())
                        if ind > base_indent and not re.match(r"^\s*- ", nxt):
                            parts.append(nxt.strip())
                            k2 += 1
                        else:
                            break
                    joined = parts[0]
                    for p in parts[1:]:
                        joined += " " + p
                    values.append(unquote_yaml(joined))
                    j = k2
                    continue
                j += 1
            lang_map = OrderedDict()
            for k, v in zip(keys, values):
                if k < len(langs):
                    lang_map[langs[k]] = v
            fields.append({"field": fname, "values": lang_map})
            i = j
            continue
        i += 1
    return langs, fields


def main():
    os.makedirs(OUT, exist_ok=True)
    report = []

    def log(s=""):
        report.append(s)
        print(s)

    log("== NTR Soccer text extraction ==")
    db_lines = read_lines(DB_PATH)
    actors, variables, conversations = parse_db(db_lines)
    n_entries = sum(len(c["entries"]) for c in conversations)
    log(f"Dialogue DB: {len(actors)} actors, {len(variables)} variables, "
        f"{len(conversations)} conversations, {n_entries} dialogue entries")

    # ---- dialogue rows
    dialogue_rows = []
    actor_names = {}
    for a in actors:
        f = a["fields"]
        actor_names[a["id"]] = f.get("Name", "")
    for c in conversations:
        conv_title = c["fields"].get("Title", "")
        for e in c["entries"]:
            f = e["fields"]
            row = {
                "conversation": c["id"],
                "conv_title": conv_title,
                "entry": e["id"],
                "actor_id": e.get("actor"),
                "actor": actor_names.get(e.get("actor"), ""),
                "en": f.get("Dialogue Text", ""),
                "ja": f.get("ja", ""),
                "menu_en": f.get("Menu Text", ""),
                "menu_ja": f.get("Menu Text ja", ""),
                "title": f.get("Title", ""),
            }
            dialogue_rows.append(row)

    # ---- actor rows
    actor_rows = []
    for a in actors:
        f = a["fields"]
        actor_rows.append(
            {
                "id": a["id"],
                "en": f.get("Name", ""),
                "ja": f.get("Name ja", ""),
                "display_en": f.get("Display Name", ""),
                "display_ja": f.get("Display Name ja", ""),
            }
        )

    # ---- variables (check for JP just in case)
    var_jp = [
        v for v in variables if has_jp(v["fields"].get("Initial Value", ""))
    ]
    log(f"variables with JP initial values: {len(var_jp)}")

    # ---- texttable
    tt_lines = read_lines(TT_PATH)
    langs, tt_fields = parse_texttable(tt_lines)
    log(f"TextTable: languages={langs}, fields={len(tt_fields)}")
    tt_rows = []
    for fld in tt_fields:
        v = fld["values"]
        tt_rows.append(
            {
                "field": fld["field"],
                "en": v.get("Default", ""),
                "ja": v.get("ja", ""),
                "zh": v.get("zh", ""),
                "ko": v.get("ko", ""),
            }
        )

    # ---------------- outputs
    def dump_json(name, obj):
        with io.open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)

    def dump_csv(name, rows, cols):
        with io.open(os.path.join(OUT, name), "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)

    dump_json("dialogue.json", dialogue_rows)
    dump_csv(
        "dialogue.csv",
        dialogue_rows,
        ["conversation", "conv_title", "entry", "actor_id", "actor", "ja", "en", "menu_ja", "menu_en", "title"],
    )
    dump_json("actors.json", actor_rows)
    dump_csv("actors.csv", actor_rows, ["id", "ja", "en", "display_ja", "display_en"])
    dump_json("ui_texttable.json", tt_rows)
    dump_csv("ui_texttable.csv", tt_rows, ["field", "ja", "en", "zh", "ko"])

    # ---- JP->EN map + gap list
    jp_to_en = OrderedDict()
    needs = []          # {kind, key, ja, context}
    all_jp = OrderedDict()  # unique JP strings

    def add_pair(kind, key, ja, en, context=""):
        ja_n = ja.strip()
        if not ja_n or not has_jp(ja_n):
            return
        all_jp.setdefault(ja_n, kind)
        en_n = (en or "").strip()
        if en_n and not has_jp(en_n):
            # official translation exists
            if ja_n not in jp_to_en:
                jp_to_en[ja_n] = en_n
        else:
            needs.append({"kind": kind, "key": key, "ja": ja_n, "context": context})

    for r in dialogue_rows:
        add_pair(
            "dialogue",
            f"c{r['conversation']}e{r['entry']}",
            r["ja"],
            r["en"],
            context=f"{r['conv_title']} / speaker: {r['actor']}",
        )
        add_pair(
            "menu",
            f"c{r['conversation']}e{r['entry']}m",
            r["menu_ja"],
            r["menu_en"] or r["en"],
            context=f"{r['conv_title']} response menu",
        )
    for a in actor_rows:
        add_pair("actor", f"a{a['id']}", a["ja"], a["en"], "actor name")
        add_pair("actor_display", f"a{a['id']}d", a["display_ja"], a["display_en"] or a["en"], "actor display name")
    for r in tt_rows:
        add_pair("ui", r["field"], r["ja"], r["en"], "UI text table")
    for v in var_jp:
        add_pair("variable", v["fields"].get("Name", ""), v["fields"].get("Initial Value", ""), "", "variable initial value")

    # dedupe needs by ja (same string may appear multiple times)
    seen = set()
    needs_unique = []
    for x in needs:
        if x["ja"] in jp_to_en:
            continue  # some other row provided official EN for identical JP
        if x["ja"] in seen:
            continue
        seen.add(x["ja"])
        needs_unique.append(x)

    dump_json("jp_to_en.json", jp_to_en)
    dump_json("needs_translation.json", needs_unique)
    with io.open(os.path.join(OUT, "jp_all_strings.txt"), "w", encoding="utf-8") as f:
        for s, kind in all_jp.items():
            f.write(s.replace("\\", "\\\\").replace("\n", "\\n") + "\t[" + kind + "]\n")

    log("")
    log(f"unique JP strings:            {len(all_jp)}")
    log(f"JP with official EN:          {len(jp_to_en)}")
    log(f"JP needing Mistral:           {len(needs_unique)}")
    by_kind = {}
    for x in needs_unique:
        by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
    for k, v in sorted(by_kind.items()):
        log(f"   needs[{k}] = {v}")

    # integrity checks
    bad_en = [ja for ja, en in jp_to_en.items() if has_jp(en)]
    log(f"official EN entries containing JP (should be 0): {len(bad_en)}")
    # placeholder audit
    ph_re = re.compile(r"(\[pic=\d+\]|<[^>]+>|\{\d+\}|\\n)")
    mismatch = 0
    for ja, en in jp_to_en.items():
        pj = sorted(ph_re.findall(ja))
        pe = sorted(ph_re.findall(en))
        if pj != pe:
            mismatch += 1
    log(f"placeholder differences between ja/en (informational): {mismatch}")

    with io.open(os.path.join(OUT, "extract_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(report) + "\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
