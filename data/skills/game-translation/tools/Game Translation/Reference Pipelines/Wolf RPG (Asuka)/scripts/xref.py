"""xref.py - display-string / symbol tracer for WOLF decompiles.

Answers "where does this on-screen string come from". Some labels are never
written as a literal anywhere. They are read from a DB field/type NAME at
runtime (the dataID=-3 "get field name" op) and then drawn. Tracing that by
hand is slow. This makes it a query.

Given a TERM (a JP string, a DB field/type name, or a variable like CSelf[6]),
scan every *.wscript line, classify each hit by ROLE using the shared
wolfscript primitives, and print a grouped report.

Roles:
  display-literal   TERM inside a depth-0 DISPLAY literal -> drawn on screen.
  lookup-name       TERM as a Database trailing operand (not span[0]) -> a
                    by-name lookup key, internal, not drawn.
  annotation        TERM only inside a bracketed [n "..."] operand annotation ->
                    editor label, not runtime.
  var-set / var-draw  for a CSelf[N]/Sys[N] TERM: SET sites (assignValue / the
                    two SetString spellings) and DRAW sites (\\cself[N] etc.
                    inside a display literal).
  field-name-get    dataID=-3 GET sites when TERM is a DB field name -> the op
                    that fetches the field NAME and displays it.
"""
import argparse
import glob
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wolfscript import (
    literal_spans, command_name, iter_display_literals, db_types, load_json, read_text,
)

# Conventional defaults: `ws/` decompiled *.wscript and `db/` db-json dumps in
# the working dir. Pass --ws / --db to point elsewhere.
DEFAULT_WS = "ws"
DEFAULT_DBS = None  # -> glob db/*.json when --db omitted (see main)

# CSelf[6] / Self[6] / Sys[6]. Bracketed annotation on real refs is stripped
# before matching, so the TERM the user types stays clean.
VAR_RE = re.compile(r"^(CSelf|Self|Sys)\[(\d+)\]$")

# dataID=-3 => the WOLF "get field/type NAME" op (as opposed to a value read).
DATAID_M3_RE = re.compile(r"\bdataID=-3\b")
TYPEID_RE = re.compile(r"\btypeID=(\d+)\b")

SNIPPET_MAX = 150


def _snip(line):
    s = line.strip()
    if len(s) > SNIPPET_MAX:
        s = s[:SNIPPET_MAX - 1] + "…"
    return s


def _annotation_spans(line):
    """(start, end) of bracketed operand-annotation string literals `[n "..."]`.

    literal_spans deliberately skips these (depth > 0). We want the inverse so a
    TERM found ONLY there is classified as an editor annotation, not runtime."""
    spans, depth, i, n = [], 0, 0, len(line)
    while i < n:
        c = line[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth = max(0, depth - 1)
        elif c == '"':
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == '"':
                    break
                j += 1
            if depth > 0:
                spans.append((i, j + 1))
            i = j
        i += 1
    return spans


def _covered(pos, spans):
    return any(a <= pos < b for a, b in spans)


def _var_draw_re(kind, idx):
    key = {"CSelf": "cself", "Self": "self", "Sys": "sys"}[kind]
    # Source lines keep control codes escaped, so a display literal carries the
    # doubled-backslash spelling `\\cself[6]`. Allow one or two leading
    # backslashes so both raw and unescaped spellings match.
    return re.compile(r"\\\\?%s\[%s\]" % (key, idx))


def _load_files(ws):
    out = []
    for path in sorted(glob.glob(os.path.join(ws, "*.wscript"))):
        out.append((os.path.basename(path), read_text(path).splitlines()))
    return out


def _load_dbs(paths):
    dbs = []
    for p in paths:
        if not os.path.exists(p):
            continue
        dbs.append((os.path.basename(p), db_types(load_json(p))))
    return dbs


def _db_field_hits(term, dbs):
    """DB type/field names equal to TERM.

    Returns (notes, field_type_ids). field_type_ids maps a typeID that has a
    field named TERM to a human label. A dataID=-3 GET over that typeID fetches
    the field NAME, so TERM can reach the screen without ever being a literal.
    typeIDs are numeric and not disambiguated by DB file in wscript, so the
    label carries the DB + type name to make a cross-DB coincidence visible."""
    notes, field_type_ids = [], {}
    for dbname, types in dbs:
        for ti, t in enumerate(types or []):
            if t.get("name") == term:
                notes.append(f"{dbname} type[{ti}] name == {term!r}")
            for f in t.get("fields", []) or []:
                if f.get("name") == term:
                    notes.append(
                        f"{dbname} type[{ti}] {t.get('name')!r} "
                        f"field[{f.get('id')}] == {term!r}")
                    field_type_ids.setdefault(ti, f"{dbname} {t.get('name')!r}")
    return notes, field_type_ids


def classify(term, files, field_type_ids):
    roles = {
        "display-literal": [],
        "lookup-name": [],
        "annotation": [],
        "var-set": [],
        "var-draw": [],
        "field-name-get": [],
    }
    var = VAR_RE.match(term)
    if var:
        vkind, vidx = var.group(1), var.group(2)
        draw_re = _var_draw_re(vkind, vidx)
        # SET spelling A: `SetString CSelf[6 ...] = "..."` / `assignValue=CSelf[6]`
        # SET spelling B: `SetString(targetRef=CSelf[6 ...], ...)`.
        set_re = re.compile(
            r"(?:assignValue=%s\[%s\b"
            r"|SetString\s+%s\[%s\b"
            r"|targetRef=%s\[%s\b)" % (
                vkind, vidx, vkind, vidx, vkind, vidx))
    else:
        draw_re, set_re = None, None

    for fname, lines in files:
        text = "\n".join(lines)
        # display-literal via the shared primitive so Database's lookup-name
        # operands are correctly excluded (only span[0] is display for it).
        for lno, cmd, lit in iter_display_literals(text):
            if term in lit:
                roles["display-literal"].append((fname, lno, lines[lno - 1]))

        for lno, line in enumerate(lines, 1):
            # field-name-get: a dataID=-3 GET whose typeID owns a field named
            # TERM. TERM itself is NOT on the line (the op fetches the name by
            # index), so this runs before the has_term guard below.
            if field_type_ids and DATAID_M3_RE.search(line):
                m = TYPEID_RE.search(line)
                if m and int(m.group(1)) in field_type_ids:
                    label = field_type_ids[int(m.group(1))]
                    roles["field-name-get"].append(
                        (fname, lno, f"[{label}] {line.strip()}"))

            has_term = term in line
            draw_hits = list(draw_re.finditer(line)) if draw_re else []
            if not has_term and not draw_hits:
                continue

            cmd = command_name(line)
            d0 = literal_spans(line)
            ann = _annotation_spans(line)

            if not var and has_term:
                positions = [m.start()
                             for m in re.finditer(re.escape(term), line)]
                in_d0 = any(_covered(p, d0) for p in positions)
                in_ann = any(_covered(p, ann) for p in positions)

                if cmd == "Database" and len(d0) > 1:
                    for a, b in d0[1:]:
                        if any(a <= p < b for p in positions):
                            roles["lookup-name"].append((fname, lno, line))
                            break

                if in_ann and not in_d0:
                    roles["annotation"].append((fname, lno, line))

            if var:
                if set_re and set_re.search(line):
                    roles["var-set"].append((fname, lno, line))
                if any(_covered(m.start(), d0) for m in draw_hits):
                    roles["var-draw"].append((fname, lno, line))

    return roles


ROLE_ORDER = [
    ("display-literal", "DISPLAY-LITERAL   drawn on screen as a literal"),
    ("field-name-get", "FIELD-NAME-GET    dataID=-3 op fetches field NAME -> displayed"),
    ("var-set", "VAR-SET           variable assigned here"),
    ("var-draw", "VAR-DRAW          variable drawn (\\cself[N]) inside a display literal"),
    ("lookup-name", "LOOKUP-NAME       Database by-name lookup key (internal)"),
    ("annotation", "ANNOTATION        editor [n \"...\"] label, not runtime"),
]


def report(term, roles, db_notes):
    print(f"xref: {term!r}")
    if db_notes:
        print("\nDB name matches:")
        for n in db_notes:
            print(f"  {n}")
    for key, header in ROLE_ORDER:
        hits = roles.get(key, [])
        if not hits:
            continue
        print(f"\n{header}  ({len(hits)})")
        for fname, lno, line in hits:
            print(f"  {fname}:{lno}: {_snip(line)}")

    total = sum(len(v) for v in roles.values())
    print("\nsummary:")
    for key, _ in ROLE_ORDER:
        c = len(roles.get(key, []))
        if c:
            print(f"  {key:<16} {c}")
    print(f"  {'total':<16} {total}")
    if not total and not db_notes:
        print(f"  (no hits for {term!r})")


def main():
    ap = argparse.ArgumentParser(
        description="Trace where a display string / symbol comes from in a "
                    "WOLF decompile.")
    ap.add_argument("term", help="thing to trace: a JP string, a DB "
                                  "type/field name, or a variable like CSelf[6]")
    ap.add_argument("--ws", default=DEFAULT_WS,
                    help="workspace dir of *.wscript files")
    ap.add_argument("--db", nargs="*", default=DEFAULT_DBS,
                    help="db-json dumps to check for name matches")
    args = ap.parse_args()

    db_paths = args.db if args.db is not None else sorted(glob.glob("db/*.json"))
    files = _load_files(args.ws)
    dbs = _load_dbs(db_paths)
    db_notes, field_type_ids = _db_field_hits(args.term, dbs)
    roles = classify(args.term, files, field_type_ids)
    report(args.term, roles, db_notes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
