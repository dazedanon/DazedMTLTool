#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new_post.py — start a forum post from a CLEAN slate, then fill it.

The autosave is a live session file: whatever game was open last is still in it.
Editing it in place (load -> update the fields you know) leaks every field you did
not happen to set - the previous game's version, store links, download hosts,
translator notes. Those are exactly the fields nobody re-reads before posting.

So: back up, blank EVERY key, re-apply only the tool's own defaults, then apply the
new game's values.

    from new_post import start
    start({"title": "Coin Pussy", "developer": "Kujira 1%", ...},
          tags=["3DCG", "Anal Sex", ...],
          backup_as="AsukaVirginIdolDebut")

Run it directly for a self-check that renders the result through the tool's own
build_bbcode.
"""

import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PROFILES = os.path.join(HERE, "profiles")
AUTOSAVE = os.path.join(PROFILES, "_autosave_session.json")
TAGS_PATH = os.path.join(HERE, "tags.json")

# Every key the app round-trips, with the value a cleared form holds. Mirrors the
# GUI's own defaults (see App._build_form) so "clean" means the same thing whether
# you press Clear or run this.
BLANK = {
    "title": "", "banner_src": "", "banner_alt": "",
    "thread_updated": "", "release_date": "",
    "original_title": "", "aliases": "",
    "developer": "", "publisher": "", "translator": "",
    "version": "", "os": "Windows", "censored": "No",
    "language": "English", "language_note": "", "voice": "", "length": "",
    "vndb_url": "", "other_games_url": "",
    "download_os_label": "Win", "ss_size": "Thumbnail",
    "overview_short": "", "overview_spoiler": "",
    "installation": "1. Extract and run.",
    "developer_notes": "", "translator_notes": "", "required_note": "",
    "genre": "", "tags_selected": [],
    "developer_links": [], "publisher_links": [], "translator_links": [],
    "store_links": [], "downloads": [], "extras": [], "screenshots": [],
    "_profile": None,
}


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def backup(name=None):
    """Copy the current autosave to profiles/<name>.json. Returns the path or None."""
    if not os.path.exists(AUTOSAVE):
        return None
    cur = _load(AUTOSAVE)
    name = name or (cur.get("title") or "previous").strip() or "previous"
    safe = "".join(c if (c.isalnum() or c in " _.-") else "_" for c in name).strip()
    dst = os.path.join(PROFILES, f"{safe}_backup.json")
    shutil.copy(AUTOSAVE, dst)
    return dst


def blank():
    """A cleared session. Includes any key the installed app added since this file."""
    d = dict(BLANK)
    if os.path.exists(AUTOSAVE):
        for k, v in _load(AUTOSAVE).items():
            if k not in d:                       # unknown key: keep it, but emptied
                d[k] = [] if isinstance(v, list) else ("" if isinstance(v, str) else None)
    return d


def check_tags(tags):
    """Tags absent from tags.json render in the genre line with no chip to toggle."""
    if not os.path.exists(TAGS_PATH):
        return []
    vocab = set(_load(TAGS_PATH))
    return [t for t in tags if t not in vocab]


def start(values, tags=None, backup_as=None, write=True):
    """Blank the session, apply `values`, and keep genre in sync with the tags."""
    saved = backup(backup_as)
    d = blank()

    unknown = [k for k in values if k not in d]
    if unknown:
        raise KeyError(f"not fields the app reads: {unknown}")
    d.update(values)

    if tags is not None:
        missing = check_tags(tags)
        if missing:
            raise ValueError(f"tags not in tags.json: {missing}")
        ordered = sorted(tags, key=str.lower)     # the GUI's own genre ordering
        d["tags_selected"] = ordered
        d["genre"] = ", ".join(ordered)

    if write:
        with open(AUTOSAVE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    return d, saved


def diff_against(path):
    """Which non-empty values in the autosave also appear in an older profile.

    Overlap is not automatically wrong - 'Windows' is 'Windows' - but every hit is
    a field to justify before posting.
    """
    if not os.path.exists(path):
        return []
    new, old = _load(AUTOSAVE), _load(path)
    return [(k, new[k]) for k, v in old.items()
            if k in new and new[k] == v and v not in ("", [], None, {})]


if __name__ == "__main__":
    cur = _load(AUTOSAVE) if os.path.exists(AUTOSAVE) else {}
    print(f"autosave: {len(cur)} keys, title={cur.get('title')!r}")
    print(f"BLANK covers {len(BLANK)} keys; "
          f"missing from BLANK: {sorted(set(cur) - set(BLANK)) or 'none'}")
    missing = sorted(set(BLANK) - set(cur)) if cur else []
    print(f"in BLANK but not in autosave: {missing or 'none'}")
