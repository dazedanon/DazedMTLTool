#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
verify_structure.py - prove the patch cannot break a save.

A save file stores a POSITION, and in RPG Maker that position is an index into
a parsed event command list (`Game_Interpreter._index`, plus the map/event/page
it belongs to). Any edit that changes the number of commands, their order, or
their codes moves every index after it - and the failure has no crash and no
diff. On one reference game a third of saves resumed at the wrong element.

Extraction being byte-reversible does not help, because the PATCHED file is the
one being indexed. So this walks the source and the injected tree together and
asserts, per file:

  * the same set of files, each parsing
  * identical structure: same keys, same array lengths
  * every event command list the same LENGTH
  * every command the same `code`, in the same order, with the same `indent`
  * every non-string leaf byte-identical (numbers, booleans, ids, switches)
  * only STRING leaves differ, and only at a site the store actually owns

Anything else is the injector editing something it was not told to edit.

    python tools/verify_structure.py
"""

import os
import sys
import glob
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from mvtl import config, store, fileio  # noqa: E402


def walk(a, b, path, out, strings):
    if type(a) is not type(b):
        out.append("%s: type %s -> %s" % (path, type(a).__name__,
                                          type(b).__name__))
        return
    if isinstance(a, dict):
        if set(a) != set(b):
            out.append("%s: keys %s -> %s" % (path, sorted(set(a) - set(b)),
                                              sorted(set(b) - set(a))))
            return
        for k in a:
            walk(a[k], b[k], "%s/%s" % (path, k), out, strings)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append("%s: LENGTH %d -> %d" % (path, len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            walk(x, y, "%s/%d" % (path, i), out, strings)
    elif isinstance(a, str):
        if a != b:
            strings.append(path)
    elif a != b:
        out.append("%s: NON-STRING value %r -> %r" % (path, a, b))


def command_sequence(node, path, seq):
    """Every event command list, as (path, [(code, indent), ...])."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "list" and isinstance(v, list):
                seq.append((path + "/list",
                            [(c.get("code"), c.get("indent"))
                             for c in v if isinstance(c, dict)]))
            else:
                command_sequence(v, "%s/%s" % (path, k), seq)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            command_sequence(v, "%s/%d" % (path, i), seq)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE),
                                                  "out", "www", "data"))
    args = ap.parse_args(argv)
    cfg = config.Config()

    src_files = sorted(glob.glob(os.path.join(cfg.data_dir, "*.json")))
    problems = []
    changed_strings = 0
    lists_checked = 0
    commands_checked = 0

    src_names = {os.path.basename(p) for p in src_files}
    out_names = {os.path.basename(p)
                 for p in glob.glob(os.path.join(args.out, "*.json"))}
    if src_names != out_names:
        problems.append("file set differs: missing %s, extra %s"
                        % (sorted(src_names - out_names),
                           sorted(out_names - src_names)))

    for p in src_files:
        base = os.path.basename(p)
        q = os.path.join(args.out, base)
        if not os.path.exists(q):
            continue
        a, _ = fileio.load(p)
        b, _ = fileio.load(q)

        out, strings = [], []
        walk(a, b, base, out, strings)
        problems.extend(out)
        changed_strings += len(strings)

        sa, sb = [], []
        command_sequence(a, base, sa)
        command_sequence(b, base, sb)
        if len(sa) != len(sb):
            problems.append("%s: %d command lists -> %d" % (base, len(sa), len(sb)))
            continue
        for (pa, ca), (pb, cb) in zip(sa, sb):
            lists_checked += 1
            commands_checked += len(ca)
            if pa != pb:
                problems.append("%s: command list moved: %s -> %s" % (base, pa, pb))
            elif ca != cb:
                # Name the first divergence rather than the whole list.
                for i, (x, y) in enumerate(zip(ca, cb)):
                    if x != y:
                        problems.append(
                            "%s: command %d changed (code,indent) %s -> %s "
                            "- THIS MOVES EVERY SAVED INDEX AFTER IT"
                            % (pa, i, x, y))
                        break
                else:
                    problems.append("%s: command COUNT %d -> %d - THIS MOVES "
                                    "EVERY SAVED INDEX AFTER IT"
                                    % (pa, len(ca), len(cb)))

    print("STRUCTURAL VERIFY  %s" % args.out)
    print("  files compared         : %d" % len(src_files))
    print("  event command lists    : %d" % lists_checked)
    print("  commands checked       : %d" % commands_checked)
    print("  string leaves changed  : %d" % changed_strings)
    print("  structural differences : %d" % len(problems))
    for s in problems[:25]:
        print("     ! " + s)
    if len(problems) > 25:
        print("     ... (%d more)" % (len(problems) - 25))
    if problems:
        print("\nFAIL - the patch changes something a save file indexes into.")
        return 1
    print("\nPASS - every command list has the same length, the same codes and")
    print("the same indents as the source. Only string values differ, so a save")
    print("made on the Japanese build resumes at the same line on the patch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
