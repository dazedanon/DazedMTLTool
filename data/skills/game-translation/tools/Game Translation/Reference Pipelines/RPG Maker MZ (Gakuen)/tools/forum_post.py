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
than invented in the JSON. The DLsite URL the RJ code implies is PRINTED for
the user to check and paste, not written into the field.

    python tools/forum_post.py --dry-run
    python tools/forum_post.py --apply --version "1.03"
"""

import os
import re
import sys
import json
import argparse

# The report quotes Japanese evidence; a cp1252 console must not be able to
# kill the run over it.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))

FPG = r"C:\Users\sw\Desktop\Games\ForumPostGen"
RJ = "RJ01090427"

from mztl import store, config  # noqa: E402

# The user supplied the tags for this release, so the corpus scan
# (`tools/tag_evidence.py`) was NOT run and nothing is asserted here. An empty
# list means the GUI opens with no chips selected and no Genre line, which is
# the honest state - a guessed tag set is worse than none, because it looks
# decided.
TAGS = []

# Settled from the BUILD, so they need no judgement and no corpus scan. Printed
# rather than applied, since the user owns the tag list for this release.
FROM_THE_BUILD = """\
Settled from the build, if any of these are in your list:

  Voiced       PARTIAL, and worth wording carefully. There is no `audio/voice`
               folder, but `audio/bgs/龍涎にこみ/` holds 12 files, all named
               `NN_喘ぎ声_小|中|大` - moans at three intensities, 2.6 MB. The
               staff roll credits `音声素材_Pincree (CV: 龍涎にこみ)`. So the
               heroine is voiced for sex, and nothing else in the game is.
  2D Game      YES. RPG Maker MZ, hand-drawn CG stills.
  Combat       YES. Troops, Enemies and Skills are all populated, there is a
               skill tree and a monster book, and battles are turn-based.
  Censored     Assumed 'Yes (Mosaics)' as a DLsite JP release. NOT verified
               here: there are no mask assets and no picture-overlay commands,
               so any censoring is painted into the CG itself and only looking
               at one settles it. It is one of the few fields a reader notices.
               (The 〇/● in the SCRIPT are text masks - ちん〇 - and are a
               separate thing; those are preserved in the translation.)
  Pregnancy    Depicted, not merely referenced: achievements E005
               'Multiparous Woman' (her first childbirth) and Bad End 01
               'Too Many Births'.
"""

OVERVIEW_SHORT = """\
Azusa is a third-year at the magic academy with no friends, no talent, and a \
body that draws far more attention than her spellwork. She cannot go home \
until she graduates as Top Maginoir. Every time the year runs out and she has \
not, April comes round again and she starts over.

Eleven months stand between her and the top of the school, each with its own \
trial, in an academy full of people who have worked out that nobody is coming \
to look for her."""

OVERVIEW_SPOILER = """\
[B]The calendar is the game.[/B] April through February, each month is a \
self-contained chapter with its own event and its own way to lose it. Losing a \
month does not end the run. It changes what Azusa carries into the months \
after it.

[B]Lewdness[/B], [B]Chastity[/B] and [B]Shame[/B] track what has happened to \
her, and the writing reads them back at you.

Turn-based combat with a magic skill tree, equipment and a shop, a monster \
book, an in-school casino (high-low, poker and blackjack), 45 achievements, \
and a recollection room that replays any scene you have already seen. Two bad \
endings and a true ending.

Non-consensual content runs through the whole game. It is the premise, not an \
occasional scene."""

INSTALL = """\
1. Extract the patch archive.
2. Copy the contents of [B]patch/[/B] over your game folder, keeping the \
folder structure. Overwrite when asked.
3. Run Game.exe.

[B]This is RPG Maker MZ, so there is no [I]www[/I] folder.[/B] [I]data[/I], \
[I]js[/I] and [I]img[/I] sit at the game root. If you are used to MV and go \
looking for [I]www[/I], you will put the files a level too deep.

To revert, restore [B]data[/B], [B]js[/B], [B]package.json[/B] and \
[B]index.html[/B] from your own backup and delete \
[B]js/plugins/GakuenTL_Patch.js[/B]. The patch touches nothing else."""

TRANSLATOR_NOTES = """\
Everything the player sees is in English. Dialogue and choices, items, \
equipment, skills and states with their descriptions, the menu, options and \
save screens, the shop, the skill tree, the monster book, the 45 achievements, \
the ero status screen, battle messages, map name banners, the floating labels \
over map objects, the three text images, and the window caption. {units:,} \
lines in total.

That includes the casino. High-low, poker and blackjack keep their text inside \
the plugins rather than in the game data, so they often get left in Japanese.

Line breaks are set to the game's own message box, so text should not run off \
the edge.

The 〇 and ● in the Japanese are kept as they are rather than spelled out.

[B]Existing Japanese saves keep working.[/B] Event scripts keep the same \
number of commands, so a save still resumes on the right line. \
[I]GakuenTL_Patch.js[/I] refreshes the map labels that a save made on the \
Japanese build had already stored."""

DEV_NOTES = ""


def build_fields(cfg, version, store_dir):
    docs = store.load_docs(store_dir)
    units = sum(len(d["units"]) for _p, d in docs)
    done = sum(1 for _d, u in store.all_units(docs)
               if (u.get("tl") or "").strip())
    return {
        "title": "All Body, No Talent: No Way Home Till I'm Top of the Academy",
        "original_title": ("体だけは立派な落ちこぼれ陰キャ魔法使い"
                           "学園トップになるまで帰れません"),
        "aliases": ("Karada dake wa Rippa na Ochikobore Inkya Mahoutsukai "
                    "Gakuen Top ni Naru made Kaeremasen / " + RJ),
        # The build names every asset author and plugin author in its staff
        # roll and never names the circle. Left blank rather than guessed.
        "developer": "",
        "publisher": "",
        "translator": "len",
        "version": version,
        "os": "Windows",
        "censored": "Yes (Mosaics)",
        "language": "English",
        "language_note": "AI-assisted, hand-checked in game",
        "voice": "Japanese (heroine, sex scenes only)",
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
        "translator_notes": TRANSLATOR_NOTES.format(units=units),
        "required_note": ("You need the original Japanese game (%s). "
                          "This is a patch only." % RJ),
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
    ap.add_argument("--version", default="1.03")
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
    print("\ntags: %s" % (", ".join(tags) if tags
                          else "NONE - supplied by the user in the GUI"))
    print("\n" + FROM_THE_BUILD)

    if not args.apply:
        print("dry run - pass --apply to write the autosave")
        print("\nfields that would be set (%d):" % len(fields))
        for k in sorted(fields):
            v = fields[k]
            s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            s = s.replace("\n", " ")
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
    print("\nStill to fill by hand, because none of it is verified here:")
    print("  developer   the build never names the circle - only asset and")
    print("              plugin authors. Take it from the store page.")
    print("  store URL   the RJ code implies")
    print("              https://www.dlsite.com/maniax/work/=/product_id/"
          "%s.html" % RJ)
    print("              - check it resolves before pasting it in.")
    print("  release date, thread date, download hosts, banner, screenshots")
    print("  tags        yours to pick; see the build-settled notes above")
    return 0


if __name__ == "__main__":
    sys.exit(main())
