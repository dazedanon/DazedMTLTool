"""Prototype for `wolf verify-semantic`.

verify-roundtrip proves the wscript re-emits byte-identical, but a byte-perfect
file can still be semantically broken: a Database command resolves its operand at
runtime by NAME, so if a DB rename drops a type/row/field name that a wscript still
cites by name, the lookup fails in-game while the roundtrip stays green. This tool
cross-checks that every by-name Database operand still resolves against the DB.

The by-name operands are the trailing quoted args of a Database line:
    Database(typeID=.., dataID=.., fieldID=.., ..) "<written>" "<type>" "<data>" "<field>"
The first is the written display value (not a lookup). The other three are the
lookup names WOLF uses to bind typeID/dataID/fieldID back to DB entries.
"""
import argparse
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wolfscript import literal_spans, unescape, db_types, load_json, read_text

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Conventional defaults: `ws/` decompiled *.wscript and `db/` db-json dumps in
# the working dir. Pass --ws / --db to point elsewhere.
DEFAULT_WS = "ws"
DEFAULT_DB_GLOB = "db/*.json"

# typeID as a plain literal in the Database head. A CSelf/variable typeID is not
# statically resolvable, so field checks fall back to any-type in that case.
TYPEID_RE = re.compile(r"typeID=(-?\d+)")


class DBIndex:
    """Name resolution across the merged DBs.

    typeID is a per-DB-kind index and the wscript Database command does not tag
    which kind (CDB/UDB/SDB) it addresses, so a literal typeID can collide across
    files. Field checks therefore prefer the unambiguous typename operand; when
    that operand is empty we fall back to the UNION of fields of whatever type
    sits at that typeID in each DB. Union avoids false positives from collisions
    while still dangling a field that no type at that id defines any more.
    """

    def __init__(self):
        self.type_names = set()
        self.row_names = set()
        self.field_names = set()
        # typeName -> its own field-name set (unambiguous per-type check).
        self.fields_by_type_name = {}
        # numeric typeID -> union of field names at that id across all DBs.
        self.fields_by_type_id = {}

    def add(self, db_json):
        for idx, t in enumerate(db_types(db_json) or []):
            tid = t.get("id", idx)
            tname = t.get("name") or ""
            if tname:
                self.type_names.add(tname)
            by_name = self.fields_by_type_name.setdefault(tname, set())
            by_id = self.fields_by_type_id.setdefault(tid, set())
            for f in t.get("fields", []):
                fn = f.get("name") or ""
                if fn:
                    self.field_names.add(fn)
                    by_name.add(fn)
                    by_id.add(fn)
            for r in t.get("rows", []):
                rn = r.get("name") or ""
                if rn:
                    self.row_names.add(rn)

    def field_resolves(self, field, typename, typeid):
        if typename and typename in self.fields_by_type_name:
            return field in self.fields_by_type_name[typename]
        if typeid is not None and typeid in self.fields_by_type_id:
            return field in self.fields_by_type_id[typeid]
        return field in self.field_names


def build_index(db_paths):
    idx = DBIndex()
    for p in db_paths:
        idx.add(load_json(p))
    return idx


def scan_file(path, idx):
    """Yield (lineno, operand_role, name) for every dangling by-name operand."""
    findings = []
    checked = 0
    for lno, line in enumerate(read_text(path).splitlines(), 1):
        s = line.lstrip()
        if not s.startswith("Database"):
            continue
        spans = literal_spans(line)
        if len(spans) < 4:
            continue
        # Trailing four depth-0 literals: written, type, data, field. Some
        # Database variants trail extra literals, so anchor to the last four.
        written, typ, dat, fld = (unescape(line[a + 1:b - 1]) for a, b in spans[-4:])
        m = TYPEID_RE.search(line)
        typeid = int(m.group(1)) if m else None

        if typ:
            checked += 1
            if typ not in idx.type_names:
                findings.append((lno, "typename", typ))
        if dat:
            checked += 1
            if dat not in idx.row_names:
                findings.append((lno, "dataname", dat))
        if fld:
            checked += 1
            if not idx.field_resolves(fld, typ, typeid):
                findings.append((lno, "fieldname", fld))
    return checked, findings


def main():
    ap = argparse.ArgumentParser(
        description="Verify by-name Database operands resolve against the DB.")
    ap.add_argument("--ws", default=DEFAULT_WS,
                    help="workspace dir of .wscript files")
    ap.add_argument("--db", nargs="+", default=None,
                    help="db-json files (default: the three sandbox dumps)")
    args = ap.parse_args()

    db_paths = args.db if args.db else sorted(glob.glob(DEFAULT_DB_GLOB))
    if not db_paths:
        print("no db-json files found", file=sys.stderr)
        return 2
    idx = build_index(db_paths)

    ws_files = sorted(glob.glob(args.ws.rstrip("/\\") + "/*.wscript"))
    if not ws_files:
        print("no .wscript files found", file=sys.stderr)
        return 2

    total_checked = 0
    all_findings = []
    for wf in ws_files:
        checked, findings = scan_file(wf, idx)
        total_checked += checked
        for lno, role, name in findings:
            all_findings.append((wf, lno, role, name))

    print(f"checked {total_checked} by-name Database operands across "
          f"{len(ws_files)} wscript file(s) against {len(db_paths)} db-json file(s)")
    if not all_findings:
        print("clean")
        return 0
    print(f"{len(all_findings)} dangling by-name reference(s):")
    for wf, lno, role, name in all_findings:
        print(f"  {wf}:{lno}  {role}={name!r}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
