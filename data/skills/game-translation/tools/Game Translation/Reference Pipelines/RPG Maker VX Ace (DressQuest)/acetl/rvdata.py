#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
rvdata.py - the game-data access layer: pointers into a Ruby Marshal tree.

`rvmarshal` gives back the object graph exactly as RPG Maker wrote it. This
module is the vocabulary on top of it - "the command list of page 0 of event 17
on Map006" - and the JSON-serialisable POINTER that names it, so a unit in the
store can be written back into a pristine file months later.

POINTER GRAMMAR
    "@ivar"     an instance variable on an RObject      (`@events`)
    12          an index into an RArray                 (`@pages` -> page 12)
    {"h": 5}    a key in an RHash                       (Ace stores a map's
                                                        events as a Hash keyed
                                                        by event id, NOT a
                                                        sparse array like MV)

    ["@events", {"h": 17}, "@pages", 0, "@list"]

WHY A NEW RString ON WRITE
    Marshal emits a back-reference when the same object is written twice, so
    two command parameters CAN be one shared Ruby string. Editing such a node
    in place would change both sites from one translation. Every write
    therefore builds a fresh RString and copies the ivars (`:E => true`), which
    also keeps the encoding flag the engine needs.
"""

import os
import glob

from . import rvmarshal as M


# --------------------------------------------------------------------------
# pointers
# --------------------------------------------------------------------------
def ptr_get(node, ptr):
    cur = node
    for step in ptr:
        cur = _step(cur, step)
    return cur


def ptr_parent(node, ptr):
    return ptr_get(node, ptr[:-1]), ptr[-1]


def _step(cur, step):
    if isinstance(step, str):
        if not isinstance(cur, M.RObject):
            raise TypeError("ivar %r on %r" % (step, type(cur).__name__))
        v = cur.get(step)
        if v is None and not cur.has(step):
            raise KeyError("no ivar %r on %s" % (step, cur.classname))
        return v
    if isinstance(step, dict):
        key = step["h"]
        if not isinstance(cur, M.RHash):
            raise TypeError("hash step on %r" % type(cur).__name__)
        for k, v in cur.pairs:
            if k == key or (isinstance(k, M.RString) and k.text() == key):
                return v
        raise KeyError("no hash key %r" % (key,))
    if isinstance(cur, M.RArray):
        return cur.items[step]
    raise TypeError("index %r into %r" % (step, type(cur).__name__))


def ptr_set_string(root, ptr, text, encoding="utf-8"):
    """Replace the string at `ptr` with a fresh RString carrying its ivars."""
    parent, last = ptr_parent(root, ptr)
    old = _step(parent, last)
    new = new_string(text, old, encoding)
    if isinstance(last, str):
        parent.set(last, new)
    elif isinstance(last, dict):
        key = last["h"]
        for i, (k, _v) in enumerate(parent.pairs):
            if k == key:
                parent.pairs[i] = (k, new)
                return new
        raise KeyError("no hash key %r" % (key,))
    else:
        parent.items[last] = new
    return new


def new_string(text, like=None, encoding="utf-8"):
    """A fresh RString, copying `like`'s encoding ivars when given.

    An Ace data file writes every string as `I"...` with `:E => true`. A bare
    string would load as ASCII-8BIT and the engine would draw mojibake, so the
    ivars are carried over rather than reconstructed."""
    ivars = list(like.ivars) if isinstance(like, M.RString) and like.ivars else \
        [(M.RSymbol(b"E"), True)]
    return M.RString(text.encode(encoding), ivars)


def stext(node):
    """The text of an RString node, or '' for anything else."""
    return node.text() if isinstance(node, M.RString) else ""


# --------------------------------------------------------------------------
# files
# --------------------------------------------------------------------------
def load(path):
    return M.load_file(path)


def save(path, obj):
    M.save_file(path, obj)


def data_files(data_dir):
    """Every .rvdata2 in the data folder, in a stable order."""
    return sorted(glob.glob(os.path.join(data_dir, "*.rvdata2")))


def is_map_file(base):
    return (base.startswith("Map") and base != "MapInfos.rvdata2"
            and base[3:6].isdigit())


# --------------------------------------------------------------------------
# event command lists
# --------------------------------------------------------------------------
class EventList(object):
    """One command list, with the pointer that finds it again and the context
    line a translator reads."""
    __slots__ = ("ptr", "node", "uid", "ctx")

    def __init__(self, ptr, node, uid, ctx):
        self.ptr = ptr
        self.node = node
        self.uid = uid
        self.ctx = ctx

    @property
    def commands(self):
        return [c for c in self.node.items if isinstance(c, M.RObject)]


def event_lists(data, base, map_name=""):
    """Yield every EventList in one loaded data file.

    Map events are an RHash keyed by event id, so the pointer carries the KEY
    and not a position: a hash written back in a different order would send a
    translation to the wrong event if positions were used."""
    stem = os.path.splitext(base)[0]
    if is_map_file(base):
        display = stext(data.get("@display_name"))
        label = display or map_name or stem
        events = data.get("@events")
        if not isinstance(events, M.RHash):
            return
        for key, ev in events.pairs:
            name = stext(ev.get("@name"))
            pages = ev.get("@pages")
            if not isinstance(pages, M.RArray):
                continue
            for pi, page in enumerate(pages.items):
                lst = page.get("@list")
                if not isinstance(lst, M.RArray):
                    continue
                yield EventList(
                    ["@events", {"h": key}, "@pages", pi, "@list"], lst,
                    "%s:ev%s:p%d" % (stem, key, pi),
                    "%s / %s / event %s%s / page %d"
                    % (stem, label, key, (" %r" % name) if name else "", pi))
    elif base == "CommonEvents.rvdata2":
        for idx, ce in enumerate(data.items):
            if not isinstance(ce, M.RObject):
                continue
            lst = ce.get("@list")
            if not isinstance(lst, M.RArray):
                continue
            cid = ce.get("@id")
            yield EventList([idx, "@list"], lst, "%s:ce%s" % (stem, cid),
                            "CommonEvents / CE%s %r"
                            % (cid, stext(ce.get("@name"))))
    elif base == "Troops.rvdata2":
        for idx, tr in enumerate(data.items):
            if not isinstance(tr, M.RObject):
                continue
            pages = tr.get("@pages")
            if not isinstance(pages, M.RArray):
                continue
            for pi, page in enumerate(pages.items):
                lst = page.get("@list")
                if not isinstance(lst, M.RArray):
                    continue
                yield EventList([idx, "@pages", pi, "@list"], lst,
                                "%s:t%s:p%d" % (stem, tr.get("@id"), pi),
                                "Troops / troop %s %r page %d"
                                % (tr.get("@id"), stext(tr.get("@name")), pi))


def command(node):
    """(code, [parameter nodes]) for one RPG::EventCommand."""
    ps = node.get("@parameters")
    return node.get("@code"), (ps.items if isinstance(ps, M.RArray) else [])


def map_names(data_dir):
    """{map id: editor name} from MapInfos, for context lines only.

    MapInfos names are the editor's project tree and are never drawn, so they
    are context and never units."""
    p = os.path.join(data_dir, "MapInfos.rvdata2")
    if not os.path.exists(p):
        return {}
    info = M.load_file(p)
    out = {}
    if isinstance(info, M.RHash):
        for k, v in info.pairs:
            out[k] = stext(v.get("@name"))
    return out
