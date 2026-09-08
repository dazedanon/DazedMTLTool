#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tl.py - the pipeline CLI.

    python tl.py census                  what is actually in the game data
    python tl.py extract                 data/*.json  -> tl/units/*.json
    python tl.py dryrun --show-sample    scope + cost, no API call
    python tl.py smoke                   ONE real request on a median chunk
    python tl.py selftest                offline round trip, no API, no writes
    python tl.py names                   translate character names first
    python tl.py run                     names, then everything, via batch
    python tl.py submit|status|fetch     the manual three-step version
    python tl.py live                    same requests, synchronous, 2x price
    python tl.py validate                completeness / codes / overflow
    python tl.py retry                   re-translate everything that failed
    python tl.py tighten                 re-request only what overflows its box
    python tl.py polish [--apply]        one repeated line, one English rendering
    python tl.py inject [--in-place]     store -> a drop-in www/data
    python tl.py noop                    prove an empty store injects as a no-op
    python tl.py verify                  prove the patch cannot move a saved index
    python tl.py ui [-o FILE]            dump every UI label as JP -> EN
    python tl.py scan                    grep the INJECTED output
    python tl.py mock -o FILE.png        composite the message box, real font
    python tl.py plugins refresh|apply|check|mirror
    python tl.py release -o DIR          build a player-facing archive tree

Run order before spending: `dryrun --show-sample`, then `smoke`, then
`selftest`, then the run.
"""

import os
import sys
import json
import shutil
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mvtl import (config, store, extract, inject, validate, driver, estimate,
                  measure, qa, plugins_js, requests as R)

DEFAULT_STORE = os.path.join(HERE, "tl")


def _cfg(args):
    c = config.Config()
    if getattr(args, "game", None):
        c.game_root = args.game
    if getattr(args, "width", None):
        c.width = args.width
    if getattr(args, "list_width", None):
        c.list_width = args.list_width
    return c


# --------------------------------------------------------------------------
def cmd_census(args):
    import collections
    import glob
    from mvtl import fileio
    cfg = _cfg(args)
    tot = collections.Counter()
    per = {}
    for p in sorted(glob.glob(os.path.join(cfg.data_dir, "*.json"))):
        base = os.path.basename(p)
        if base in ("Animations.json", "Tilesets.json"):
            continue
        data, _ = fileio.load(p)
        c = collections.Counter()

        def walk(lst):
            for cmd in lst:
                if isinstance(cmd, dict) and "code" in cmd:
                    c[cmd["code"]] += 1

        def rec(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k == "list" and isinstance(v, list):
                        walk(v)
                    else:
                        rec(v)
            elif isinstance(o, list):
                for v in o:
                    rec(v)
        rec(data)
        if c:
            per[base] = c
            tot.update(c)
    print("EVENT CODE CENSUS")
    for code, n in tot.most_common():
        print("  %5d  %7d" % (code, n))
    print("\nper file (401 = dialogue lines)")
    for base, c in sorted(per.items()):
        if c[401] or c[102] or c[356]:
            print("  %-20s 401=%-5d 102=%-4d 356=%-4d 355=%-4d 122=%-5d 111=%-4d"
                  % (base, c[401], c[102], c[356], c[355], c[122], c[111]))
    m = measure.reset(cfg.font_path)
    print("\nFONT  %s  exact=%s  half-cell=%.2fpx  contents=%dpx -> %d cells"
          % (os.path.basename(cfg.font_path), m.exact, m.half_px,
             measure.CONTENTS_WIDTH,
             int(measure.CONTENTS_WIDTH // m.half_px)))
    return 0


def cmd_extract(args):
    cfg = _cfg(args)
    print("extracting from %s" % cfg.data_dir)
    extract.run(cfg, args.store)
    plugins_js.refresh(cfg, args.store, verbose=True)
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
          "the spellings, add role/register/aliases. Everything there flows "
          "straight into the cached prompt.")
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
                           include_text=True, effort=args.effort, label="text")
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
    cfg = _cfg(args)
    bid, n = driver.submit(args.store, cfg, args.model, args.max_units,
                           args.retranslate_all,
                           include_names=not args.no_names,
                           include_text=not args.no_text, effort=args.effort)
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
        print("  (these are queue depth, not progress. Zero succeeded does "
              "NOT mean nothing has been billed.)")
    return 0 if b.processing_status == "ended" else 2


def cmd_fetch(args):
    driver.fetch(args.store)
    return 0


def cmd_live(args):
    cfg = _cfg(args)
    driver.live(args.store, cfg, args.model, args.max_units,
                args.retranslate_all, include_names=not args.no_names,
                include_text=not args.no_text, effort=args.effort,
                workers=args.workers)
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
        print("[retry round %d/%d] %d failing units"
              % (rnd, args.rounds, len(fails)))
        if args.live:
            driver.live(args.store, cfg, args.model, args.max_units,
                        retranslate_all=True, include_names=False,
                        only_ids=set(fails), effort=args.effort,
                        workers=args.workers, retry_notes=fails)
        else:
            bid, n = driver.submit(args.store, cfg, args.model, args.max_units,
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

    Asking for brevity up front is weaker than a targeted shortening pass with
    the real per-unit budget in lines x cells. Two passes took 34 overflows to
    5 on the reference game, and the last 5 were faster to write by hand."""
    cfg = _cfg(args)
    m = measure.reset(cfg.font_path)
    docs = store.load_docs(args.store)
    notes = {}
    for _d, u in store.all_units(docs):
        d = validate.overflow_detail(u, cfg, m)
        if d:
            if u["kind"] == "text":
                budget = "%d rows of %d cells" % (cfg.max_rows, cfg.width)
            elif u["kind"] == "desc":
                budget = "%d rows of %d cells" % (cfg.list_max_rows, cfg.list_width)
            else:
                budget = "%d cells on one line" % cfg.choice_width
            notes[u["id"]] = ("too long for its box (%s). Rewrite it SHORTER "
                              "so it fits in %s. Keep the meaning and every "
                              "sentinel; drop filler words, not information."
                              % (d, budget))
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
        bid, n = driver.submit(args.store, cfg, args.model, args.max_units,
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
    out = args.out or os.path.join(HERE, "out", "www", "data")
    inject.run(cfg, args.store, out_dir=None if args.in_place else out,
               in_place=args.in_place)
    if not args.in_place:
        print("\nCopy over the game's www/data, or re-run with --in-place "
              "(which backs data/ up first).")
    return 0


def cmd_noop(args):
    return 0 if inject.noop_test(_cfg(args), args.store) else 1


def cmd_selftest(args):
    """Offline extract -> fake-translate -> validate -> inject, in a TEMP copy.

    A self-test must not write to the real store: a fake round trip that fills
    every `tl` and saves turns the store into a finished-looking job, `dryrun`
    then reports 0 pending, and inject ships `[EN 3]` into the game."""
    import tempfile
    import glob
    cfg = _cfg(args)
    scratch = tempfile.mkdtemp(prefix="mvtl_selftest_")
    copy = os.path.join(scratch, "tl")
    shutil.copytree(args.store, copy)

    docs = store.load_docs(copy)
    n = 0
    for _p, u in store.all_units(docs):
        # Echo the placeholders so masking integrity is exercised.
        phs = "".join(sorted(set(__import__("re").findall(r"⟦\d+⟧", u["src"]))))
        u["tl"] = "EN %s test %s" % (n, phs)
        n += 1
    store.save_docs(docs)

    out = os.path.join(scratch, "data")
    rep = inject.run(cfg, copy, out_dir=out, verbose=False)
    ok_written = sum(rep.written.values()) > 0

    # The real store must be untouched.
    real = store.load_docs(args.store)
    dirty = [u["id"] for _p, u in store.all_units(real)
             if (u.get("tl") or "").startswith("EN ") and " test " in u["tl"]]

    print("SELFTEST")
    print("  fake-translated units : %d" % n)
    print("  injected units        : %d" % sum(rep.written.values()))
    print("  injector problems     : %d" % len(rep.problems))
    for p in rep.problems[:10]:
        print("     ! " + p)
    print("  real store untouched  : %s" % ("YES" if not dirty else "NO"))
    print("  files written         : %d" % len(glob.glob(os.path.join(out, "*.json"))))
    shutil.rmtree(scratch, ignore_errors=True)
    ok = ok_written and not dirty
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
    out = args.out or os.path.join(HERE, "out", "www", "data")
    if not os.path.isdir(out):
        print("no injected output at %s - run `inject` first" % out)
        return 1
    qa.scan_output(cfg, out)
    return 0


def cmd_mock(args):
    return qa.mock_screen(_cfg(args), args.store, args.out, args.limit)


def cmd_plugins(args):
    cfg = _cfg(args)
    if args.action == "refresh":
        plugins_js.refresh(cfg, args.store)
    elif args.action == "mirror":
        plugins_js.autofill_mirrors(cfg, args.store)
    elif args.action == "check":
        plugins_js.check_mirrors(cfg, args.store)
    elif args.action == "apply":
        plugins_js.check_mirrors(cfg, args.store)
        plugins_js.apply(cfg, args.store)
    return 0


def cmd_verify(args):
    sys.path.insert(0, os.path.join(HERE, "tools"))
    import verify_structure
    return verify_structure.main(["--out", args.out] if args.out else [])


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
    ap.add_argument("--list-width", type=int, default=None)
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
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(fn=cmd_ui)

    p = sub.add_parser("scan")
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("mock")
    p.add_argument("-o", "--out", default=os.path.join(HERE, "out", "mock.png"))
    p.add_argument("--limit", type=int, default=12)
    p.set_defaults(fn=cmd_mock)

    p = sub.add_parser("plugins")
    p.add_argument("action", choices=["refresh", "mirror", "check", "apply"])
    p.set_defaults(fn=cmd_plugins)

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
