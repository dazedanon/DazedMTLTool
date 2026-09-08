#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""unlock_gallery.py - unlock every CG in the recollection gallery.

The gallery's unlock flags do NOT live in a save file. `Game_System_Data` is a
thin Array wrapper indexed by common-event id, dumped on its own into
`system_data.rvdata2` in the game root, which is why the gallery is reachable
from the title screen at all. So this unlocks the gallery for every save at
once, and does not touch any Save*.rvdata2.

Which ids count is not a guess: `Scene_Replay#create_event_list` keeps a common
event when `usable_event?` accepts it, which means the event holds at least one
Show Picture (code 231), contains no command in the ranges the replay engine
refuses, and is not in EXCLUSION_ARRAY. That filter is reimplemented here and
run against the game's own CommonEvents.rvdata2, so the id list always matches
the build being patched.

    python tools/unlock_gallery.py --game "C:\path\to\Dress Quest EN"
    python tools/unlock_gallery.py --game ... --apply
    python tools/unlock_gallery.py --game ... --restore
"""

import os
import sys
import shutil
import argparse
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from acetl import config                                   # noqa: E402
from acetl import rvmarshal as M                           # noqa: E402

# Scene_Replay::EXCLUSION_ARRAY
EXCLUSION = {1, 2, 3, 4, 5, 10, 11, 12, 40, 99, 100, 101, 106, 107, 108}
SYS = "system_data.rvdata2"


def iv(o, name):
    if not isinstance(o, M.RObject):
        return None
    for k, v in (o.ivars or []):
        kn = k.name.decode("utf-8") if isinstance(k.name, bytes) else k.name
        if kn == name:
            return v
    return None


def usable_code(code):
    """Scene_Replay#usable_code?"""
    if 201 <= code <= 217:
        return False
    if 125 <= code <= 138:
        return False
    if code == 236:
        return False
    if 281 <= code <= 354:
        return False
    return True


def usable_event(events, ev, cg_check=True, depth=0):
    """Scene_Replay#usable_event?, including the recursive 117 call."""
    if not isinstance(ev, M.RObject):
        return False
    if iv(ev, "@id") in EXCLUSION:
        return False
    lst = iv(ev, "@list")
    if lst is None:
        return False
    add_event = False
    for cmd in lst.items:
        code = iv(cmd, "@code")
        params = iv(cmd, "@parameters")
        if not isinstance(code, int) or not usable_code(code):
            return False
        if code == 117:
            if depth > 8:
                return False
            t = params.items[0] if params is not None and params.items else None
            sub = events[t] if isinstance(t, int) and 0 <= t < len(events) else None
            if not usable_event(events, sub, False, depth + 1):
                return False
        elif code == 231:
            add_event = True
    return True if add_event else (not cg_check)


def gallery_ids(game_root):
    ce = M.load_file(os.path.join(game_root, "Data", "CommonEvents.rvdata2"))
    events = ce.items
    return [iv(e, "@id") for e in events if usable_event(events, e, True)]


def read_flags(path):
    """-> (marshal object, the @data RArray). Creates neither."""
    obj = M.load_file(path)
    data = iv(obj, "@data")
    if data is None:
        raise SystemExit("%s has no @data - not a Game_System_Data dump" % path)
    return obj, data


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--game", help="game folder (default: acetl config)")
    ap.add_argument("--apply", action="store_true", help="write the change")
    ap.add_argument("--restore", action="store_true",
                    help="put back the most recent backup")
    args = ap.parse_args(argv)

    root = args.game or config.Config().game_root
    path = os.path.join(root, SYS)
    print("game : %s" % root)

    if args.restore:
        baks = sorted(f for f in os.listdir(root) if f.startswith(SYS + ".bak_"))
        if not baks:
            raise SystemExit("no backup to restore")
        src = os.path.join(root, baks[-1])
        shutil.copy2(src, path)
        print("restored from %s" % baks[-1])
        return 0

    if not os.path.exists(path):
        raise SystemExit(
            "%s not found. Launch the game once (it is created on first run)." % SYS)

    ids = gallery_ids(root)
    obj, data = read_flags(path)
    items = data.items

    already = sorted(i for i, x in enumerate(items) if x is True)
    print("gallery entries : %d  (ids %s..%s)" % (len(ids), min(ids), max(ids)))
    print("currently true  : %s" % (already or "(none)"))
    in_gallery = [i for i in already if i in ids]
    print("  of which are gallery CGs : %d" % len(in_gallery))
    print("  non-gallery system flags : %s"
          % ([i for i in already if i not in ids] or "(none)"))

    todo = [i for i in ids if i >= len(items) or items[i] is not True]
    print("to unlock       : %d" % len(todo))
    if not todo:
        print("nothing to do - every CG is already unlocked")
        return 0

    if not args.apply:
        print()
        print("dry run. Re-run with --apply to write.")
        return 0

    while len(items) <= max(ids):
        items.append(None)
    for i in ids:
        items[i] = True

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path + ".bak_" + stamp
    shutil.copy2(path, backup)
    M.save_file(path, obj)

    # read it back and prove it
    _obj2, data2 = read_flags(path)
    now = data2.items
    missing = [i for i in ids if i >= len(now) or now[i] is not True]
    lost = [i for i in already if i >= len(now) or now[i] is not True]
    if missing or lost:
        shutil.copy2(backup, path)
        print("ROLLED BACK - missing=%s lost=%s" % (missing, lost))
        return 1
    print()
    print("unlocked %d CGs, %d flags preserved" % (len(ids), len(already)))
    print("backup : %s" % os.path.basename(backup))
    return 0


if __name__ == "__main__":
    sys.exit(main())
