#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
forum_post.py - fill ForumPostGen's autosave from what the pipeline already
knows, so the release thread opens near-finished instead of blank.

The autosave is a LIVE SESSION file: whatever game was open last is still in
it. Loading it and updating the fields you know leaks every field you did not
set - the previous game's version, store links, download hosts, translator
notes. Those are exactly the fields nobody re-reads before posting, and a wrong
download link on a release thread is worse than a missing one. So this goes
through `new_post.start`, which backs up, blanks EVERY key, re-applies the
tool's own defaults, and only then writes this game's values.

**Every URL and date left blank here is blank because it has not been
verified**, with its label in place so the gap is visible in the GUI rather
than invented in the JSON.

    python tools/forum_post.py --dry-run
    python tools/forum_post.py --apply --version "v1.0 EN"
"""

import os
import re
import sys
import json
import argparse

# The borderline-tag report quotes Japanese evidence; a cp1252 console must not
# be able to kill the run over it.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

FPG = r"C:\Users\sw\Desktop\Games\ForumPostGen"

from mvtl import store, config  # noqa: E402

# Read the evidence, then decide. `tools/tag_evidence.py` prints the hits these
# came from; the two judgement calls are recorded beside them.
TAGS = [
    "2D Game",
    "2DCG",
    "Corruption",
    "Fantasy",
    "Female Protagonist",
    "Humiliation",
    "Japanese Game",
    "Male Domination",
    "Monster",
    "Rape",
    "Tentacles",
    "Vaginal Sex",
]

# Called out for the user rather than silently included or excluded - they know
# the forum's norms better than the corpus does.
BORDERLINE = """\
Tags to settle before posting - the corpus is ambiguous and the forum's norms
decide, not the script:

  Anal Sex      DEPICTED once, in CE28 'E紫ミニスライム接触'
                (お尻とオマンコ…両方同時にピストン). One scene. Include?
  Group Sex     One line, and it is Mineria RECALLING being surrounded by
                slimes rather than a depicted scene. Probably not a tag.
  Ahegao        The CG stills show it (S_*_H.png variants), the script does
                not say it. A visual tag, so judge it from the images.
  Oral Sex      No script evidence found. Check the CGs.
  Bestiality    The dog is a recurring nuisance and there is a
                '犬みたいなBADEND'. Check whether that ending is depicted or
                implied before tagging it.
  Censored      Assumed 'Yes (Mosaics)' as a DLsite JP release. VERIFY against
                the CGs - it is one of the few fields a reader notices.

Settled from the build, no judgement needed:
  Voiced        NO. www/audio has bgm/ bgs/ me/ se/ and no voice/ folder.
  Combat        NO. Troops, Enemies and Skills are empty; zero code-301
                commands. Monster contact is a trap, not a fight.
"""

OVERVIEW_SHORT = """\
Mineria is the Demon Lord: the strongest being alive, several centuries old, \
and so far above every challenger that she is dying of boredom. When a human \
book describes a magic-powered "trap dungeon", she builds one under her own \
castle - purely as something to do.

It works. On her.

Now she is inside her own ero trap dungeon with her magic drained to nothing, \
someone has layered illusion magic over the exit, and the traps are not trying \
to kill her. Escape three floors and a nameless village of monsters who have \
no idea who their new neighbour is."""

OVERVIEW_SPOILER = """\
[B]Lewdness[/B] rises every time a trap or a monster catches her, and climbs on \
its own the longer she stays down there. Hit the cap and you lose - which is a \
scene, not a death. Water and food push it back down.

[B]Mana[/B] is her spell budget and her dignity. Every spell costs it, and at \
zero she is an ordinary girl in a very expensive dress. Back in the village she \
can convert her Lewdness Cap into Mana at two-to-one: literally trading how \
much she can endure for how much she can do. Escaping with new scenes seen \
raises the cap, which is the progression loop.

Three stages - the Demon Lord's Castle, the Cave of Everdark, the Bewildering \
Forest - a hub village, a shop, a tavern, a Recollection Room, and six endings."""

INSTALL = """\
1. Extract the patch archive.
2. Copy the contents of [B]patch/[/B] over your game folder, keeping the folder \
structure. Overwrite when asked.
3. Run Game.exe.

To revert, restore [B]www/data[/B] and [B]www/js/plugins.js[/B] from your own \
backup. The patch touches nothing else."""

TRANSLATOR_NOTES = """\
Full translation of every player-facing string: all dialogue, choices, item and \
equipment names and descriptions, the menu and options UI, shop text, the map \
name banners, the status gauges and the title logo.

Text is fitted to the game's real boxes rather than to a guess - the message \
window is 984px of a genuinely monospace M+ 1m at 28px, so 70 half-width cells \
by 4 rows, and item descriptions get 2 rows. The map HUD gauge was widened so \
the English label does not silently push the /max readout off the bar.

Menu labels use RPG Maker's own published English so the UI does not read \
half-localised. The title logo is redrawn in the original's style. The circle \
name さざめき通り in the corner is left as-is - it is the developer's brand \
mark, not game text.

Existing Japanese saves keep working - injection never changes the number of \
commands in an event list, so the index a save stores still points at the same \
line."""

DEV_NOTES = """\
This is the [B]trial version[/B]. The game says so itself: the demo does not \
raise your maximum Lewdness between runs."""


def build_fields(cfg, version, store_dir):
    docs = store.load_docs(store_dir)
    units = sum(len(d["units"]) for _p, d in docs)
    done = sum(1 for _d, u in store.all_units(docs)
               if (u.get("tl") or "").strip())
    return {
        "title": "Demon Lord Mineria and the Nameless Village's Ero Trap Dungeon",
        "original_title": "魔王ミネリアと名もなき村のエロトラップダンジョン",
        "aliases": ("Maou Mineria to Namonaki Mura no Ero Trap Dungeon"),
        "developer": "さざめき通り (Sazameki-dori)",
        "publisher": "",
        "translator": "",
        "version": version,
        "os": "Windows",
        "censored": "Yes (Mosaics)",
        "language": "English",
        "language_note": "machine-assisted, glossary-locked, hand-reviewed UI",
        "voice": "",
        "length": "",
        # Left blank ON PURPOSE - not verified. The labels stay so the gap is
        # visible in the GUI instead of being invented here.
        "release_date": "",
        "thread_updated": "",
        "vndb_url": "",
        "other_games_url": "",
        "banner_src": "",
        "banner_alt": "",
        "overview_short": OVERVIEW_SHORT,
        "overview_spoiler": OVERVIEW_SPOILER,
        "installation": INSTALL,
        "developer_notes": DEV_NOTES,
        "translator_notes": TRANSLATOR_NOTES,
        "required_note": "You need the original Japanese game. This is a patch only.",
        "download_os_label": "Win",
        "ss_size": "Thumbnail",
        "developer_links": [{"label": "DLsite", "url": ""}],
        "store_links": [{"label": "DLsite", "url": ""}],
        "downloads": [{"host": "PIXELDRAIN", "url": ""}],
        "extras": [{"label": "Patch Only", "url": ""}],
        "screenshots": [],
        "_units": units,
        "_done": done,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", default=os.path.join(os.path.dirname(HERE), "tl"))
    ap.add_argument("--version", default="v1.0 EN")
    ap.add_argument("--backup-as", default=None,
                    help="name for the backup of whatever post is open now")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    cfg = config.Config()
    fields = build_fields(cfg, args.version, args.store)
    units, done = fields.pop("_units"), fields.pop("_done")
    print("store: %d units, %d translated" % (units, done))
    if done < units:
        print("  !! the translation is not finished. The thread can wait.")

    vocab_path = os.path.join(FPG, "tags.json")
    vocab = set(json.load(open(vocab_path, encoding="utf-8")))
    unknown = [t for t in TAGS if t not in vocab]
    if unknown:
        sys.exit("tags missing from tags.json (the picker would have no chip "
                 "for them): %s" % unknown)

    tags = sorted(TAGS, key=str.lower)
    print("\ntags (%d): %s" % (len(tags), ", ".join(tags)))
    print("\n" + BORDERLINE)

    if not args.apply:
        print("dry run - pass --apply to write the autosave")
        print("\nfields that would be set (%d):" % len(fields))
        for k in sorted(fields):
            v = fields[k]
            s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            print("   %-20s %s" % (k, (s[:70] + "...") if len(s) > 70 else s))
        return 0

    sys.path.insert(0, FPG)
    try:
        from new_post import start
    except ImportError as e:
        sys.exit("could not import ForumPostGen's new_post (%s). It lives at "
                 "%s and needs that folder on sys.path." % (e, FPG))
    start(fields, tags=tags, backup_as=args.backup_as)
    print("\nautosave written. Open ForumPostGen (Run.bat) and it restores "
          "this session.")
    print("Still to fill by hand, because none of it is verified here:")
    print("  release date, thread date, DLsite URL, download hosts, banner, "
          "screenshots, translator credit, and every borderline tag above.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
