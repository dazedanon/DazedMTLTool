#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tl.py - the Dress Quest (RPG Maker VX Ace) translation pipeline.

    python tl.py census                  what is actually in the game data
    python tl.py extract                 Data/*.rvdata2 -> tl/units/*.json
    python tl.py dryrun --show-sample    scope + cost, no API call
    python tl.py smoke                   ONE real request on a median chunk
    python tl.py selftest                offline round trip, no API, no writes
    python tl.py noop                    an empty store must inject byte-identically
    python tl.py names                   translate speakers + character names first
    python tl.py run                     names, then everything, via batch
    python tl.py submit|status|fetch     the manual three-step version
    python tl.py live                    same requests, synchronous, 2x price
    python tl.py validate                completeness / codes / overflow
    python tl.py retry                   re-translate everything that failed
    python tl.py tighten                 re-request only what overflows its box
    python tl.py polish [--apply]        one repeated line, one English rendering
    python tl.py inject [--in-place]     store -> a drop-in Data folder
    python tl.py verify                  prove the patch cannot move a saved index
    python tl.py scan                    grep the INJECTED .rvdata2 files
    python tl.py ui [-o FILE]            dump every UI label as JP -> EN
    python tl.py mock -o FILE.png        composite the message box
    python tl.py scripts dump|refresh|check|apply
    python tl.py release -o DIR          build a player-facing archive tree

Run order before spending: `census`, `extract`, `dryrun --show-sample`,
`smoke`, `selftest`, `noop`, then the run.
"""

import os
import re
import sys
import glob
import shutil
import argparse
import collections

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")
except (AttributeError, ValueError):
    pass

from acetl import (config, store, extract, inject, validate, driver, estimate,
                   measure, qa, scripts_rb, rvdata, codes,
                   requests as R)
from acetl import rvmarshal as M

DEFAULT_STORE = os.path.join(HERE, "tl")


def _cfg(args):
    c = config.Config()
    if getattr(args, "game", None):
        c.game_root = args.game
    if getattr(args, "width", None):
        c.width = args.width
    return c


# --------------------------------------------------------------------------
def cmd_census(args):
    """Every ruling in config.py, re-derived from the data it came from."""
    cfg = _cfg(args)
    tot = collections.Counter()
    jp_by_code = collections.Counter()
    per = {}
    faced = collections.Counter()
    unfaced = collections.Counter()
    esc = collections.Counter()
    speakers = collections.Counter()
    m = measure.reset(cfg.font_path())

    for p in rvdata.data_files(cfg.data_dir):
        base = os.path.basename(p)
        if base in ("Animations.rvdata2", "Tilesets.rvdata2",
                    "Scripts.rvdata2", "MapInfos.rvdata2"):
            continue
        data = rvdata.load(p)
        c = collections.Counter()
        for el in rvdata.event_lists(data, base):
            face = ""
            for cmd in el.node.items:
                if not isinstance(cmd, M.RObject):
                    continue
                code, params = rvdata.command(cmd)
                c[code] += 1
                strs = []
                for x in params:
                    if isinstance(x, M.RString):
                        strs.append(x.text())
                    elif isinstance(x, M.RArray):
                        strs += [q.text() for q in x.items
                                 if isinstance(q, M.RString)]
                if code == 101:
                    face = strs[0] if strs else ""
                if any(codes.has_jp(s) for s in strs):
                    jp_by_code[code] += 1
                if code == 401 and strs:
                    t = strs[0]
                    tag, body = codes.split_nametag(t)
                    if tag:
                        speakers[codes.nametag_name(tag)] += 1
                    (faced if face else unfaced)[m.cells(t)] += 1
                for s in strs:
                    for mm in re.finditer(
                            r"\\+[A-Za-z]+\[[^\]]*\]|\\+[A-Za-z]+|\\+[^A-Za-z\s]",
                            s):
                        esc[re.sub(r"\[[^\]]*\]", "[..]", mm.group(0))] += 1
        if c:
            per[base] = c
            tot.update(c)

    print("EVENT CODE CENSUS   (%d commands over %d files)"
          % (sum(tot.values()), len(per)))
    print("   code    total   with-JP")
    for code, n in tot.most_common():
        if n >= 5 or jp_by_code[code]:
            print("  %5s %8d %9d" % (code, n, jp_by_code[code]))
    print("\nCONTROL CODES")
    for k, n in esc.most_common(20):
        print("  %8d  %s" % (n, k))
    print("\n\\NAME[] SPEAKERS: %d distinct, %d uses" % (len(speakers),
                                                        sum(speakers.values())))
    for t, n in speakers.most_common(15):
        print("  %6d  %s" % (n, t))

    for label, hist, budget in (("unfaced", unfaced, _cfg(args).hard_width),
                                ("faced", faced, _cfg(args).face_hard_width)):
        n = sum(hist.values())
        if not n:
            continue
        over = sum(v for k, v in hist.items() if k > budget)
        avail = measure.CONTENTS_WIDTH - (measure.FACE_INDENT
                                          if label == "faced" else 0)
        print("\n401 LINE WIDTH, %s: n=%d max=%d   budget %d cells, "
              "%d line(s) over it (%.3f%%)   %d px available -> the author's "
              "widest line implies a %.1f px cell"
              % (label, n, max(hist), budget, over, 100.0 * over / n, avail,
                 avail / float(max(hist))))
        acc = 0
        for c in sorted(hist):
            acc += hist[c]
            if c >= budget - 6:
                print("   %3d cells %6d  cum %.3f%%" % (c, hist[c], 100.0 * acc / n))

    print("\nFONT  %s  exact=%s" % (os.path.basename(cfg.font_path() or "-"),
                                    m.exact))
    return 0


def cmd_extract(args):
    cfg = _cfg(args)
    print("extracting from %s" % cfg.data_dir)
    extract.run(cfg, args.store)
    scripts_rb.refresh(cfg, args.store)
    return 0


def cmd_dryrun(args):
    return estimate.run(_cfg(args), args.store, args.model, args.max_units,
                        args.retranslate_all, args.effort, args.show_sample)


def cmd_counttokens(args):
    return estimate.exact(_cfg(args), args.store, args.model, args.max_units,
                          args.effort, args.limit)


def cmd_smoke(args):
    return driver.smoke(args.store, _cfg(args), args.model, args.max_units,
                        args.effort)


def cmd_names(args):
    cfg = _cfg(args)
    bid, n = driver.submit(args.store, cfg, args.model, args.max_units,
                           args.retranslate_all, include_names=True,
                           include_text=False, effort=args.effort,
                           label="names")
    if not bid:
        print("Every glossary name already has an English spelling.")
        return 0
    print("[names] batch %s (%d requests)" % (bid, n))
    driver.poll_until_ended(args.store, args.poll)
    driver.fetch(args.store)
    print("\nNow EDIT tl/glossary.json by hand: fix any inferred gender, lock "
          "the spellings, add role/register/aliases. Every one of them flows "
          "into the cached prompt AND into the name plate over the message "
          "box, so a wrong one is visible on 11,000 message boxes.")
    return 0


def cmd_run(args):
    cfg = _cfg(args)
    bid, n = driver.submit(args.store, cfg, args.model, args.max_units,
                           args.retranslate_all, include_names=True,
                           include_text=False, effort=args.effort,
                           label="names")
    if bid:
        print("[names] batch %s (%d requests)" % (bid, n))
        driver.poll_until_ended(args.store, args.poll)
        driver.fetch(args.store)

    bid, n = driver.submit(args.store, cfg, args.model, args.max_units,
                           args.retranslate_all, include_names=False,
                           include_text=True, effort=args.effort, label="text",
                           roster_min=args.roster_min)
    if not bid:
        print("Nothing to translate.")
        return 0
    print("[text] batch %s (%d requests)" % (bid, n))
    print("  request_counts is NOT a progress bar - a run can read "
          "processing=N, succeeded=0 for its whole life while the usage page "
          "shows the tokens already spent. Ctrl-C is safe; resume with `fetch`.")
    driver.poll_until_ended(args.store, args.poll)
    driver.fetch(args.store)
    print("\nNext: python tl.py validate   then   python tl.py inject")
    return 0


def cmd_submit(args):
    # One batch cannot be two phases: names submitted alongside text arrive
    # too late to be in the roster the text requests were built with, so every
    # dialogue request would go out against an empty character list. `run`
    # exists precisely to sequence them.
    if not args.no_names and not args.no_text:
        g = store.load_glossary(args.store)
        blank = sum(1 for v in g.get("names", {}).values()
                    if store.name_needs_tl(v))
        if blank:
            print("REFUSING: %d name(s) have no English yet, and a single "
                  "batch cannot translate them BEFORE the text that has to "
                  "cite them.\n"
                  "  Use `python tl.py run` (two batches, sequenced), or "
                  "`submit --no-text` then `fetch` then `submit --no-names`."
                  % blank)
            return 1
    bid, n = driver.submit(args.store, _cfg(args), args.model, args.max_units,
                           args.retranslate_all,
                           include_names=not args.no_names,
                           include_text=not args.no_text, effort=args.effort,
                           roster_min=args.roster_min)
    if not bid:
        print("Nothing to submit.")
        return 1
    print("Submitted batch %s (%d requests). Track: status / fetch" % (bid, n))
    return 0


def cmd_status(args):
    b = driver.status(args.store)
    if b is None:
        print("No batch state.")
        return 1
    print("batch %s : %s" % (b.id, b.processing_status))
    rc = getattr(b, "request_counts", None)
    if rc:
        print("  counts:", rc)
        print("  (queue depth, not progress. Zero succeeded does NOT mean "
              "nothing has been billed.)")
    return 0 if b.processing_status == "ended" else 2


def cmd_fetch(args):
    driver.fetch(args.store)
    return 0


def cmd_live(args):
    driver.live(args.store, _cfg(args), args.model, args.max_units,
                args.retranslate_all, include_names=not args.no_names,
                include_text=not args.no_text, effort=args.effort,
                workers=args.workers, roster_min=args.roster_min)
    return 0


def cmd_validate(args):
    return validate.run(_cfg(args), args.store, args.max_show)


def cmd_retry(args):
    cfg = _cfg(args)
    for rnd in range(1, args.rounds + 1):
        fails = validate.failing_ids(cfg, args.store)
        if not fails:
            print("[retry] nothing failing.")
            return 0
        print("[retry round %d/%d] %d failing units" % (rnd, args.rounds, len(fails)))
        if args.live:
            driver.live(args.store, cfg, args.model, args.max_units,
                        retranslate_all=True, include_names=False,
                        only_ids=set(fails), effort=args.effort,
                        workers=args.workers, retry_notes=fails)
        else:
            bid, _n = driver.submit(args.store, cfg, args.model, args.max_units,
                                    retranslate_all=True, include_names=False,
                                    include_text=True, only_ids=set(fails),
                                    effort=args.effort, label="retry%d" % rnd,
                                    retry_notes=fails)
            if not bid:
                break
            driver.poll_until_ended(args.store, args.poll)
            driver.fetch(args.store)
    left = validate.failing_ids(cfg, args.store)
    print("[retry] done. %d units still failing - run `validate`." % len(left))
    return 0


def cmd_tighten(args):
    """Re-request only the units that overflow, WITH their budget stated.

    Asking for brevity up front is weaker than a targeted shortening pass that
    states the real per-unit budget in rows x cells."""
    cfg = _cfg(args)
    m = measure.reset(cfg.font_path())
    docs = store.load_docs(args.store)
    notes = {}
    for _d, u in store.all_units(docs):
        detail = validate.overflow_detail(u, cfg, m)
        if detail:
            width, _hard, rows = inject.budget(u, cfg)
            budget = ("%d row(s) of %d cells" % (rows, width) if rows
                      else "%d cells" % width)
            notes[u["id"]] = ("too long for its box (%s). Rewrite it SHORTER "
                              "so it fits in %s. Keep the meaning and every "
                              "sentinel; drop filler words, not information."
                              % (detail, budget))
    if not notes:
        print("[tighten] nothing overflows its box.")
        return 0
    print("[tighten] %d unit(s) overflow" % len(notes))
    if args.live:
        driver.live(args.store, cfg, args.model, args.max_units,
                    retranslate_all=True, include_names=False,
                    only_ids=set(notes), effort=args.effort,
                    workers=args.workers, retry_notes=notes)
    else:
        bid, _n = driver.submit(args.store, cfg, args.model, args.max_units,
                                retranslate_all=True, include_names=False,
                                include_text=True, only_ids=set(notes),
                                effort=args.effort, label="tighten",
                                retry_notes=notes)
        if bid:
            driver.poll_until_ended(args.store, args.poll)
            driver.fetch(args.store)
    return 0


def cmd_inject(args):
    cfg = _cfg(args)
    out = args.out or os.path.join(HERE, "out", "Data")
    inject.run(cfg, args.store, out_dir=None if args.in_place else out,
               in_place=args.in_place)
    if not args.in_place:
        print("\nCopy this over the game's Data folder, or re-run with "
              "--in-place (which backs Data/ up first).")
    return 0


def cmd_noop(args):
    return 0 if inject.noop_test(_cfg(args), args.store) else 1


def cmd_selftest(args):
    """Offline extract -> fake-translate -> inject, in a TEMP copy of the store.

    A self-test must not write to the real store: a fake round trip that fills
    every `tl` turns the store into a finished-looking job, `dryrun` then
    reports 0 pending, and inject ships `[EN 3]` into the game."""
    import tempfile
    cfg = _cfg(args)
    scratch = tempfile.mkdtemp(prefix="acetl_selftest_")
    copy = os.path.join(scratch, "tl")
    shutil.copytree(args.store, copy)

    docs = store.load_docs(copy)
    n = 0
    for _p, u in store.all_units(docs):
        phs = "".join(sorted(set(re.findall(r"⟦\d+⟧", u["src"]))))
        u["tl"] = "EN %d test %s" % (n, phs)
        n += 1
    store.save_docs(docs)
    g = store.load_glossary(copy)
    for jp in list(g.get("names", {})):
        store.set_name(g, jp, "TestName")
    store.save_glossary(copy, g)

    out = os.path.join(scratch, "Data")
    rep = inject.run(cfg, copy, out_dir=out, verbose=False)

    real = store.load_docs(args.store)
    dirty = [u["id"] for _p, u in store.all_units(real)
             if (u.get("tl") or "").startswith("EN ") and " test " in u["tl"]]
    written = len(glob.glob(os.path.join(out, "*.rvdata2")))
    reread = 0
    for p in sorted(glob.glob(os.path.join(out, "*.rvdata2")))[:20]:
        M.load_file(p)                       # must still parse as Marshal
        reread += 1

    print("SELFTEST")
    print("  fake-translated units : %d" % n)
    print("  injected units        : %d" % sum(rep.written.values()))
    print("  injector problems     : %d" % len(rep.problems))
    for p in rep.problems[:10]:
        print("     ! " + p)
    print("  files written         : %d (%d re-parsed)" % (written, reread))
    print("  real store untouched  : %s" % ("YES" if not dirty else "NO"))
    shutil.rmtree(scratch, ignore_errors=True)
    ok = written > 0 and not dirty
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_polish(args):
    qa.unify_repeats(args.store, apply=args.apply)
    return 0


def cmd_ui(args):
    qa.dump_ui(_cfg(args), args.store, args.out)
    return 0


def cmd_scan(args):
    cfg = _cfg(args)
    out = args.out or os.path.join(HERE, "out", "Data")
    if not os.path.isdir(out):
        print("no injected output at %s - run `inject` first" % out)
        return 1
    qa.scan_output(cfg, out)
    return 0


def cmd_mock(args):
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    return qa.mock_screen(_cfg(args), args.store, args.out, args.limit,
                          args.font_px)


def cmd_scripts(args):
    cfg = _cfg(args)
    if args.action == "dump":
        return scripts_rb.dump(cfg, args.out or os.path.join(HERE, "out", "scripts"))
    if args.action == "refresh":
        scripts_rb.refresh(cfg, args.store)
        return 0
    if args.action == "check":
        return scripts_rb.check(cfg, args.store)
    if args.action == "apply":
        if scripts_rb.check(cfg, args.store) != 0:
            return 1
        return scripts_rb.apply(cfg, args.store, dry_run=args.dry_run)
    return 1


def cmd_verify(args):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import verify_structure
    argv = ["--out", args.out] if args.out else []
    if getattr(args, "game", None):
        argv += ["--game", args.game]
    return verify_structure.main(argv)


def cmd_release(args):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import build_release
    return build_release.main(_cfg(args), args.out, args.store)


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(prog="tl.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=DEFAULT_STORE)
    ap.add_argument("--game", default=None, help="game root (overrides config)")
    ap.add_argument("--model", default=R.MODEL_DEFAULT)
    ap.add_argument("--effort", default="low",
                    choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--max-units", type=int, default=60,
                    help="segments per request (keep UNIFORM: every distinct "
                         "chunk size can be a separate cached prefix)")
    ap.add_argument("--poll", type=int, default=60)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--retranslate-all", action="store_true")
    ap.add_argument("--width", type=int, default=None)
    ap.add_argument("--roster-min", type=int, default=0,
                    help="drop speakers with fewer than N lines from the "
                         "cached roster block")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("census").set_defaults(fn=cmd_census)
    sub.add_parser("extract").set_defaults(fn=cmd_extract)

    p = sub.add_parser("dryrun")
    p.add_argument("--show-sample", action="store_true")
    p.set_defaults(fn=cmd_dryrun)

    p = sub.add_parser("count-tokens")
    p.add_argument("--limit", type=int, default=3)
    p.set_defaults(fn=cmd_counttokens)

    sub.add_parser("smoke").set_defaults(fn=cmd_smoke)
    sub.add_parser("selftest").set_defaults(fn=cmd_selftest)
    sub.add_parser("names").set_defaults(fn=cmd_names)
    sub.add_parser("run").set_defaults(fn=cmd_run)

    p = sub.add_parser("submit")
    p.add_argument("--no-names", action="store_true")
    p.add_argument("--no-text", action="store_true")
    p.set_defaults(fn=cmd_submit)

    sub.add_parser("status").set_defaults(fn=cmd_status)
    sub.add_parser("fetch").set_defaults(fn=cmd_fetch)

    p = sub.add_parser("live")
    p.add_argument("--no-names", action="store_true")
    p.add_argument("--no-text", action="store_true")
    p.set_defaults(fn=cmd_live)

    p = sub.add_parser("validate")
    p.add_argument("--max-show", type=int, default=25)
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("retry")
    p.add_argument("--rounds", type=int, default=2)
    p.add_argument("--live", action="store_true")
    p.set_defaults(fn=cmd_retry)

    p = sub.add_parser("tighten")
    p.add_argument("--live", action="store_true")
    p.set_defaults(fn=cmd_tighten)

    p = sub.add_parser("inject")
    p.add_argument("--in-place", action="store_true")
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(fn=cmd_inject)

    sub.add_parser("noop").set_defaults(fn=cmd_noop)

    p = sub.add_parser("polish")
    p.add_argument("--apply", action="store_true")
    p.set_defaults(fn=cmd_polish)

    p = sub.add_parser("ui")
    p.add_argument("-o", "--out", default=os.path.join(HERE, "out", "ui_review.txt"))
    p.set_defaults(fn=cmd_ui)

    p = sub.add_parser("scan")
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("mock")
    p.add_argument("-o", "--out", default=os.path.join(HERE, "out", "mock.png"))
    p.add_argument("--limit", type=int, default=12)
    p.add_argument("--font-px", type=int, default=None)
    p.set_defaults(fn=cmd_mock)

    p = sub.add_parser("scripts")
    p.add_argument("action", choices=["dump", "refresh", "check", "apply"])
    p.add_argument("-o", "--out", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_scripts)

    p = sub.add_parser("verify")
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("release")
    p.add_argument("-o", "--out", required=True)
    p.set_defaults(fn=cmd_release)

    args = ap.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
