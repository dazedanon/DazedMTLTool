#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
verify_structure.py - prove the patch cannot break a save.

A VX Ace save marshals the live game objects, and `$game_map.interpreter`
carries `@index`, an INDEX into the event command list it was running.
`Game_Interpreter#setup` re-binds `@list` from the patched map data on load, so
any edit that changes the number of commands, their order or their codes moves
every index after it - and the failure has no crash and no diff. On one
reference game a third of saves resumed at the wrong element.

Extraction being reversible does not help, because the PATCHED file is the one
being indexed. So this walks the source tree and the injected tree together and
asserts, per file:

  * the same set of files, each parsing as Marshal
  * identical structure: same classes, same ivar sets, same array lengths, same
    hash keys
  * every event command list the same LENGTH
  * every command the same `@code`, in the same order, with the same `@indent`
  * every non-string leaf byte-identical (integers, floats, Tables, ids)
  * only STRING values differ

Anything else is the injector editing something it was not told to edit.

    python tools/verify_structure.py [--out out/Data]
"""

import os
import sys
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

from acetl import config, rvdata                      # noqa: E402
from acetl import rvmarshal as M                      # noqa: E402


def walk(a, b, path, out, strings, seen=None):
    if seen is None:
        seen = set()
    if isinstance(a, M._Node) and isinstance(b, M._Node):
        key = (id(a), id(b))
        if key in seen:
            return
        seen.add(key)
    if type(a) is not type(b):
        out.append("%s: type %s -> %s" % (path, type(a).__name__,
                                          type(b).__name__))
        return
    if isinstance(a, M.RString):
        if a.data != b.data:
            strings.append(path)
        if [k.name for k, _v in a.ivars] != [k.name for k, _v in b.ivars]:
            out.append("%s: string ivars changed" % path)
        return
    if isinstance(a, M.RArray):
        if len(a.items) != len(b.items):
            out.append("%s: LENGTH %d -> %d" % (path, len(a.items), len(b.items)))
            return
        for i, (x, y) in enumerate(zip(a.items, b.items)):
            walk(x, y, "%s/%d" % (path, i), out, strings, seen)
        return
    if isinstance(a, M.RHash):
        ka = [k if not isinstance(k, M.RString) else k.text() for k, _v in a.pairs]
        kb = [k if not isinstance(k, M.RString) else k.text() for k, _v in b.pairs]
        if ka != kb:
            out.append("%s: hash keys changed" % path)
            return
        for (k, x), (_k2, y) in zip(a.pairs, b.pairs):
            walk(x, y, "%s/%s" % (path, k), out, strings, seen)
        return
    if isinstance(a, M.RObject):
        if a.cls.name != b.cls.name:
            out.append("%s: class %s -> %s" % (path, a.classname, b.classname))
            return
        na = [k.name for k, _v in a.ivars]
        nb = [k.name for k, _v in b.ivars]
        if na != nb:
            out.append("%s: ivars %s -> %s" % (path, na, nb))
            return
        for (k, x), (_k2, y) in zip(a.ivars, b.ivars):
            walk(x, y, "%s/%s" % (path, k.text), out, strings, seen)
        return
    if isinstance(a, M.RUserDef):
        if a.cls.name != b.cls.name or a.data != b.data:
            out.append("%s: %s payload changed (%d -> %d bytes)"
                       % (path, a.cls.text, len(a.data), len(b.data)))
        return
    if isinstance(a, M.RFloat):
        if a.raw != b.raw:
            out.append("%s: float %r -> %r" % (path, a.raw, b.raw))
        return
    if isinstance(a, (M.RUserMarshal, M.RData)):
        walk(a.obj, b.obj, path + "/_", out, strings, seen)
        return
    if isinstance(a, M.RSymbol):
        if a.name != b.name:
            out.append("%s: symbol %r -> %r" % (path, a.name, b.name))
        return
    if a != b:
        out.append("%s: NON-STRING value %r -> %r" % (path, a, b))


def command_sequence(data, base):
    """Every event command list, as (uid, [(code, indent), ...])."""
    seq = []
    for el in rvdata.event_lists(data, base):
        seq.append((el.uid, [(c.get("@code"), c.get("@indent"))
                             for c in el.node.items if isinstance(c, M.RObject)]))
    return seq


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(HERE),
                                                  "out", "Data"))
    ap.add_argument("--game", default=None)
    args = ap.parse_args(argv)
    cfg = config.Config()
    if args.game:
        cfg.game_root = args.game

    src_files = rvdata.data_files(cfg.data_dir)
    problems = []
    changed_strings = 0
    lists_checked = commands_checked = 0

    src_names = {os.path.basename(p) for p in src_files}
    out_names = {os.path.basename(p) for p in rvdata.data_files(args.out)}
    if src_names != out_names:
        problems.append("file set differs: missing %s, extra %s"
                        % (sorted(src_names - out_names),
                           sorted(out_names - src_names)))

    for p in src_files:
        base = os.path.basename(p)
        q = os.path.join(args.out, base)
        if not os.path.exists(q):
            continue
        a = rvdata.load(p)
        b = rvdata.load(q)

        out, strings = [], []
        walk(a, b, base, out, strings)
        problems.extend(out)
        changed_strings += len(strings)

        sa = command_sequence(a, base)
        sb = command_sequence(b, base)
        if len(sa) != len(sb):
            problems.append("%s: %d command lists -> %d" % (base, len(sa), len(sb)))
            continue
        for (ua, ca), (ub, cb) in zip(sa, sb):
            lists_checked += 1
            commands_checked += len(ca)
            if ua != ub:
                problems.append("%s: command list moved: %s -> %s" % (base, ua, ub))
            elif ca != cb:
                for i, (x, y) in enumerate(zip(ca, cb)):
                    if x != y:
                        problems.append(
                            "%s: command %d changed (code,indent) %s -> %s - "
                            "THIS MOVES EVERY SAVED INDEX AFTER IT" % (ua, i, x, y))
                        break
                else:
                    problems.append("%s: command COUNT %d -> %d - THIS MOVES "
                                    "EVERY SAVED INDEX AFTER IT"
                                    % (ua, len(ca), len(cb)))

    print("STRUCTURAL VERIFY  %s" % args.out)
    print("  files compared         : %d" % len(src_files))
    print("  event command lists    : %d" % lists_checked)
    print("  commands checked       : %d" % commands_checked)
    print("  string values changed  : %d" % changed_strings)
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
    print("made on the Japanese build resumes on the same line on the patch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
