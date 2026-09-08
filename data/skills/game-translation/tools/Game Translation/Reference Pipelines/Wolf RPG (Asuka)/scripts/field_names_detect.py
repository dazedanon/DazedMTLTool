"""Prototype of `wolf field-names-detect`.

An event can DISPLAY a DB field's NAME via Database(dataID=-3). That op fetches
the field label text (e.g. "行動力"), not the value, and it is invisible to every
literal-extraction tool because the shown string lives in the schema, not in the
wscript. Renaming the schema field to translate it would ALSO break every
by-name lookup that keys on that same name. This tool finds those display sites
and tells you which field names are load-bearing keys (unsafe to rename) versus
display-only (safe to override event-side after the GET).
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
import glob
import re
from pathlib import Path

from wolfscript import literal_spans, unescape, db_types, load_json, read_text

# Conventional defaults: a `ws/` dir of decompiled *.wscript and a `db/` dir of
# `wolf db-json` dumps in the working dir. Pass --ws / --db to point elsewhere.
DEFAULT_WS = "ws"
DEFAULT_DB_GLOB = "db/*.json"

GETNAME_RE = re.compile(r"Database\(typeID=(\d+), dataID=-3, fieldID=([^,]+),")
ANY_DB_RE = re.compile(r"Database\(typeID=(\d+),")
INT_RE = re.compile(r"^-?\d+$")


def load_dbs(db_paths):
    """[(dbname, {typeID: (typename, {fieldID: name})})] in load order.

    typeID is a flat index WITHIN one db file. The `Database()` command can
    target any of the three dbs, so the same typeID means different types across
    files. Keep each file separate and disambiguate at the site by its typename
    operand. CDataBase is put first so it wins the empty-typename default (ids in
    those sites were compiled against CDataBase)."""
    def rank(p):
        n = Path(p).name.lower()
        return (0 if n.startswith("cdatabase") else 2 if n.startswith("sys") else 1, n)

    dbs = []
    for p in sorted(db_paths, key=rank):
        data = load_json(p)
        types = {}
        for idx, t in enumerate(db_types(data)):
            fields = {f.get("id"): f.get("name", "") for f in t.get("fields", [])}
            types[idx] = (t.get("name", ""), fields)
        dbs.append((Path(p).name, types))
    return dbs


def resolve_type(dbs, type_id, typename):
    """(dbname, typename, {fieldID: name}) for a site.

    A non-empty typename operand names the exact db (the file whose type at
    type_id has that name). An empty operand means the ids were baked from the
    first db (CDataBase) at compile time, so resolve there."""
    if typename:
        for dbname, types in dbs:
            entry = types.get(type_id)
            if entry and entry[0] == typename:
                return dbname, entry[0], entry[1]
    dbname, types = dbs[0]
    entry = types.get(type_id)
    if entry:
        return dbname, entry[0], entry[1]
    return "?", typename or "?", {}


def collect_byname_keys(ws_lines):
    """Every non-empty 4th trailing quoted operand of any Database line.

    literal_spans skips bracketed operand annotations, so the trailing quoted
    args are exactly the "typename" "dataname" "" "fieldname" lookup names. A
    field name present here is used as a runtime key and must not be renamed.
    """
    keys = set()
    for _f, _lno, line in ws_lines:
        if not ANY_DB_RE.search(line):
            continue
        spans = literal_spans(line)
        if len(spans) < 4:
            continue
        a, b = spans[3]
        name = unescape(line[a + 1:b - 1])
        if name:
            keys.add(name)
    return keys


def iter_ws_lines(ws_dir):
    for p in sorted(Path(ws_dir).glob("*.wscript")):
        text = read_text(p)
        for lno, line in enumerate(text.splitlines(), 1):
            yield p.name, lno, line.rstrip("\n")


def field_names_for(field_expr, fields):
    """(list of displayable field names, is_variable). A concrete int resolves to
    one field. A variable fieldID loops all fields so every one can display."""
    expr = field_expr.strip()
    if INT_RE.match(expr):
        fid = int(expr)
        if fid < 0:
            return [], False
        return ([fields[fid]] if fid in fields and fields[fid] else []), False
    return [n for n in fields.values() if n], True


def site_typename(line):
    """The 2nd trailing quoted operand of a Database line (the type lookup name),
    or "" if absent. literal_spans skips bracketed annotations so spans[1] is it."""
    spans = literal_spans(line)
    if len(spans) < 2:
        return ""
    a, b = spans[1]
    return unescape(line[a + 1:b - 1])


def main():
    ap = argparse.ArgumentParser(
        description="Find Database(dataID=-3) sites that DISPLAY a DB field NAME, "
                    "and flag which names are also by-name lookup keys (unsafe to rename).")
    ap.add_argument("--ws", default=DEFAULT_WS, help="directory of *.wscript files")
    ap.add_argument("--db", nargs="*", default=None,
                    help="db-json files (default: the three sandbox db jsons)")
    args = ap.parse_args()

    db_paths = args.db if args.db else sorted(glob.glob(DEFAULT_DB_GLOB))
    if not db_paths:
        print("No db-json files found.")
        return
    dbs = load_dbs(db_paths)

    ws_lines = list(iter_ws_lines(args.ws))
    if not ws_lines:
        print(f"No *.wscript files under {args.ws}")
        return

    byname_keys = collect_byname_keys(ws_lines)

    sites = []
    for fname, lno, line in ws_lines:
        m = GETNAME_RE.search(line)
        if not m:
            continue
        type_id = int(m.group(1))
        field_expr = m.group(2).strip()
        dbname, typename, fields = resolve_type(dbs, type_id, site_typename(line))
        names, is_var = field_names_for(field_expr, fields)
        sites.append((fname, lno, type_id, dbname, typename, field_expr, names, is_var))

    total_unsafe = 0
    print("=" * 78)
    print("Database(dataID=-3) FIELD-NAME DISPLAY SITES")
    print("dataID=-3 fetches a field's NAME text and shows it. Invisible to literal")
    print("extraction. The shown name may also be a runtime by-name lookup key.")
    print("=" * 78)

    for fname, lno, type_id, dbname, typename, field_expr, names, is_var in sites:
        print()
        print(f"{fname}:{lno}")
        print(f"  typeID={type_id}  \"{typename}\"  ({dbname})")
        scope = "VARIABLE fieldID (loops - ALL fields can display)" if is_var \
            else f"fieldID={field_expr}"
        print(f"  {scope}")
        if not names:
            print("  (no resolvable field name - type/field missing from db or fieldID<0)")
            continue
        for n in names:
            unsafe = n in byname_keys
            if unsafe:
                total_unsafe += 1
            tag = "UNSAFE-to-rename (also a by-name key)" if unsafe \
                else "display-only (safe to override event-side)"
            print(f"    - {n}  [{tag}]")

    print()
    print("=" * 78)
    print(f"SUMMARY: {len(sites)} dataID=-3 field-name display site(s) across "
          f"{len(set(s[0] for s in sites))} file(s).")
    n_var = sum(1 for s in sites if s[7])
    print(f"  {n_var} variable-fieldID site(s) (display any field of their type), "
          f"{len(sites) - n_var} concrete.")
    print(f"  {total_unsafe} displayed field name(s) are also by-name lookup keys "
          f"(UNSAFE to rename in schema).")
    print()
    print("RECOMMENDATION: translate these EVENT-SIDE. Override the assigned string")
    print("variable right after the dataID=-3 GET. NEVER rename the schema field -")
    print("that breaks every by-name Database lookup that keys on the same name.")
    print("=" * 78)


if __name__ == "__main__":
    main()
