#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
tl.py - the whole pipeline, one command at a time.

Run them in this order the first time. Every step before `submit` is free.

    py tl.py unpack        data.rbpack  -> proj\   (descrambled rom tree)
    py tl.py roundtrip     GATE: the catalog must write back byte-identical
    py tl.py export        proj\        -> work\units.jsonl + scripts.jsonl
    py tl.py extract       work\        -> tl\units\*.json + seeded glossary
    py tl.py noop          GATE: inject the SOURCE back, must be byte-identical
    py tl.py speakers      the 465 nameplate speakers, most frequent first
    <write tl\game_prompt.md and fill tl\glossary.json for the main cast>
    py tl.py dryrun --show-sample     scope + cost, no API call
    py tl.py selftest      offline wiring, writes nothing
    py tl.py smoke         ONE real request on a median chunk, saves nothing
    py tl.py names         translate the roster first, into the glossary
    py tl.py submit        the batch
    py tl.py status / watch / fetch
    py tl.py validate
    py tl.py retry         re-queue only what failed a hard check
    py tl.py ui            dump every label JP -> EN and READ it
    py tl.py inject        write the English rom tree to out\
    py tl.py scan-output   grep the injected build for leaks
    py tl.py patch         build the shippable patch into dist\

`live` replaces `submit`+`fetch` at 2x the price and returns in minutes.
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from artl import (config, driver, estimate, extract, inject, qa, qa_scan, provenance,
                  requests as R, store, validate)

HERE = os.path.dirname(os.path.abspath(__file__))


def _env(cfg):
    return dict(os.environ, BAKIN_DATA=os.path.join(cfg["game_dir"], "data"))


def _bakintl(cfg, *args):
    cmd = [cfg["bakintl"]] + list(args)
    print("$ " + " ".join(cmd))
    return subprocess.call(cmd, env=_env(cfg))


# --------------------------------------------------------------------------
def cmd_unpack(cfg, a):
    pack = os.path.join(cfg["game_dir"], "data", "data.rbpack")
    rc = subprocess.call([sys.executable, os.path.join(HERE, "tools", "unpack.py"),
                          pack, cfg["proj_dir"]])
    if rc == 0:
        provenance.write(cfg["proj_dir"], {"pack": provenance.pack_id(cfg)})
    return rc


def cmd_roundtrip(cfg, a):
    rc = _bakintl(cfg, "roundtrip", cfg["proj_dir"])
    if rc:
        print("\nGATE FAILED. Nothing downstream can be trusted until every "
              "rom file writes back byte-identical: a diff here is the "
              "engine's own writer disagreeing with its own reader, and an "
              "injected build would carry that difference silently.")
    return rc


def cmd_export(cfg, a):
    return _bakintl(cfg, "export", cfg["proj_dir"], cfg["work_dir"])


def cmd_layout(cfg, a):
    return _bakintl(cfg, "layout", cfg["proj_dir"],
                    os.path.join(HERE, "layout.tsv"))


def cmd_census(cfg, a):
    rc = _bakintl(cfg, "census", cfg["proj_dir"], os.path.join(HERE, "census.tsv"))
    rc |= _bakintl(cfg, "attrcensus", cfg["proj_dir"],
                   os.path.join(HERE, "attrcensus.tsv"))
    return rc


def cmd_extract(cfg, a):
    extract.run(cfg)
    return 0


def cmd_noop(cfg, a):
    """The gate the whole pipeline rests on.

    Turn every unit into `{key, en: raw}` and inject it. Every rom file must
    come back byte-identical. Anything else means the extractor or the injector
    is corrupting data rather than translating it, and no amount of good
    translation makes that safe."""
    out = os.path.join(HERE, "out_noop")
    rc = inject.run(cfg, out_dir=out, noop=True)
    if rc:
        print("\nNO-OP GATE FAILED - see the DIFF lines above.")
    return rc


def cmd_speakers(cfg, a):
    return qa_scan.speaker_report(cfg, cfg["store_dir"],
                                  os.path.join(HERE, "speakers.txt"))


def cmd_dryrun(cfg, a):
    return estimate.run(cfg, cfg["store_dir"], a.model or cfg["model"],
                        a.max_units or cfg["max_units"],
                        retranslate_all=a.all, effort=a.effort or cfg["effort"],
                        show_sample=a.show_sample)


def cmd_exact(cfg, a):
    return estimate.exact(cfg, cfg["store_dir"], a.model or cfg["model"],
                          a.max_units or cfg["max_units"],
                          effort=a.effort or cfg["effort"])


def cmd_smoke(cfg, a):
    return driver.smoke(cfg["store_dir"], cfg, a.model or cfg["model"],
                        a.max_units or cfg["max_units"],
                        effort=a.effort or cfg["effort"])


def cmd_names(cfg, a):
    """Phase 1, on its own and BEFORE any dialogue.

    The roster lives in the cached system prefix, so a run that builds names
    and text in one pass sends every dialogue request an EMPTY roster and the
    names it locks in arrive too late to constrain anything."""
    applied, names, errs = driver.live(
        cfg["store_dir"], cfg, a.model or cfg["model"],
        a.max_units or cfg["max_units"], retranslate_all=a.all,
        include_names=True, include_text=False,
        effort=a.effort or cfg["effort"], workers=a.workers)
    return 0 if not errs else 1


def cmd_submit(cfg, a):
    g = store.load_glossary(cfg["store_dir"])
    todo = [k for k, v in g.get("names", {}).items() if not store.name_en(v)]
    if todo and not a.force:
        sys.exit("REFUSING to submit: %d character names are still "
                 "untranslated, and the roster is part of the CACHED system "
                 "prefix.\n  Run `tl.py names` first, or pass --force to "
                 "accept prose names that will not match the name box.\n"
                 "  e.g. %s" % (len(todo), ", ".join(todo[:6])))
    bid, n = driver.submit(
        cfg["store_dir"], cfg, a.model or cfg["model"],
        a.max_units or cfg["max_units"], retranslate_all=a.all,
        include_names=False, include_text=True,
        effort=a.effort or cfg["effort"], roster_min=cfg["roster_min"],
        dedup_dialogue=cfg["dedup_dialogue"], warm=not a.no_warm)
    if not bid:
        print("Nothing to submit.")
        return 0
    print("submitted %s  (%d requests)" % (bid, n))
    print("`request_counts` is queue depth, NOT progress: a run can sit at "
          "processing=N succeeded=0 for its whole life and flip in one step, "
          "while the tokens are already being spent. Check the console usage "
          "page, never cancel a stalled-LOOKING batch without doing so.")
    return 0


def cmd_status(cfg, a):
    b = driver.status(cfg["store_dir"])
    if b is None:
        print("no batch state")
        return 1
    print("%s  %s  %s" % (b.id, b.processing_status,
                          getattr(b, "request_counts", "")))
    return 0


def cmd_watch(cfg, a):
    driver.poll_until_ended(cfg["store_dir"], poll=a.poll)
    # [2] is `errored` - requests that failed or would not parse. [3] is
    # `errs`, which is only index-mapping noise. `cmd_fetch` uses [2] and this
    # used to use [3], so `watch` reported success on a run where every
    # request errored.
    applied, names, errored, errs = driver.fetch(cfg["store_dir"])
    return 0 if not errored else 1


def cmd_fetch(cfg, a):
    applied, names, errored, errs = driver.fetch(cfg["store_dir"])
    return 0 if not errored else 1


def cmd_live(cfg, a):
    applied, names, errs = driver.live(
        cfg["store_dir"], cfg, a.model or cfg["model"],
        a.max_units or cfg["max_units"], retranslate_all=a.all,
        include_names=not a.no_names, include_text=True,
        effort=a.effort or cfg["effort"], workers=a.workers,
        roster_min=cfg["roster_min"], dedup_dialogue=cfg["dedup_dialogue"])
    return 0 if not errs else 1


def cmd_validate(cfg, a):
    return validate.run(cfg, cfg["store_dir"], max_show=a.show)


def cmd_retry(cfg, a):
    ids = validate.failing_ids(cfg, cfg["store_dir"])
    if not ids:
        print("nothing failing")
        return 0
    print("%d unit(s) failing a hard check" % len(ids))
    if a.live:
        applied, names, errs = driver.live(
            cfg["store_dir"], cfg, a.model or cfg["model"],
            a.max_units or cfg["max_units"], retranslate_all=True,
            include_names=False, only_ids=set(ids),
            effort=a.effort or cfg["effort"], workers=a.workers,
            retry_notes=ids, roster_min=cfg["roster_min"],
            dedup_dialogue=cfg["dedup_dialogue"])
        return 0 if not errs else 1
    bid, n = driver.submit(
        cfg["store_dir"], cfg, a.model or cfg["model"],
        a.max_units or cfg["max_units"], retranslate_all=True,
        include_names=False, only_ids=set(ids),
        effort=a.effort or cfg["effort"], label="retry", retry_notes=ids,
        roster_min=cfg["roster_min"], dedup_dialogue=cfg["dedup_dialogue"])
    print("submitted %s (%d requests)" % (bid, n))
    return 0


def cmd_ui(cfg, a):
    qa.dump_ui(cfg, cfg["store_dir"], os.path.join(HERE, "ui_review.txt"))
    print("\nREAD that file. It is the only pass that catches a short verb "
          "rendered as the wrong part of speech - English, short, no "
          "placeholders, no residual Japanese, every automated check green, "
          "and it sends the player the opposite way.")
    return 0


def cmd_repeats(cfg, a):
    qa.unify_repeats(cfg["store_dir"], apply=a.apply)
    return 0


def cmd_inject(cfg, a):
    provenance.check(
        cfg["proj_dir"], {"pack": provenance.pack_id(cfg)},
        "the descrambled rom tree",
        "the game archive is not the one it was extracted from: run `tl.py unpack`")
    rc = inject.run(cfg, include_failing=a.include_failing)
    if rc == 0:
        provenance.write(cfg["out_dir"], provenance.build_id(cfg))
    return rc


def cmd_scan_output(cfg, a):
    return qa_scan.scan_output(cfg)


def cmd_patch(cfg, a):
    # `patch` packages out_dir and does not build it. Shipping a stale one is
    # invisible: every other gate reads the store and the source tree.
    provenance.check(cfg["out_dir"], provenance.build_id(cfg),
                     "the injected tree", "run `tl.py inject` first")
    return subprocess.call([sys.executable,
                            os.path.join(HERE, "tools", "build_patch.py"),
                            cfg["proj_dir"], cfg["out_dir"], cfg["dist_dir"],
                            os.path.join(HERE, "BakinTLHook",
                                         "BakinTranslationHook.dll")])


def cmd_selftest(cfg, a):
    return subprocess.call([sys.executable, "-m", "pytest", "-q",
                            os.path.join(HERE, "tests")]) if a.pytest else \
        subprocess.call([sys.executable, os.path.join(HERE, "tests", "selftest.py")])


def cmd_stats(cfg, a):
    docs = store.load_docs(cfg["store_dir"])
    import collections
    kinds = collections.Counter()
    done = collections.Counter()
    dedup = set()
    pend_dedup = set()
    for _p, u in store.all_units(docs):
        kinds[u["kind"]] += 1
        if (u.get("tl") or "").strip():
            done[u["kind"]] += 1
        k = store.dedup_key(u, cfg["dedup_dialogue"]) or ("#", u["id"])
        dedup.add(k)
        if not (u.get("tl") or "").strip() and not u.get("locked"):
            pend_dedup.add(k)
    total = sum(kinds.values())
    print("STORE  %d docs  %d units  %d after dedup" % (len(docs), total, len(dedup)))
    print("  %-12s %8s %8s" % ("kind", "units", "done"))
    for k in sorted(kinds, key=lambda x: -kinds[x]):
        print("  %-12s %8d %8d" % (k, kinds[k], done[k]))
    print("  %-12s %8d %8d" % ("TOTAL", total, sum(done.values())))
    print("  requests still to send: ~%d at %d units each"
          % ((len(pend_dedup) + cfg["max_units"] - 1) // cfg["max_units"],
             cfg["max_units"]))
    return 0


# --------------------------------------------------------------------------
COMMANDS = {
    "unpack": cmd_unpack, "roundtrip": cmd_roundtrip, "export": cmd_export,
    "layout": cmd_layout, "census": cmd_census, "extract": cmd_extract,
    "noop": cmd_noop, "speakers": cmd_speakers, "stats": cmd_stats,
    "dryrun": cmd_dryrun, "exact": cmd_exact, "smoke": cmd_smoke,
    "names": cmd_names, "submit": cmd_submit, "status": cmd_status,
    "watch": cmd_watch, "fetch": cmd_fetch, "live": cmd_live,
    "validate": cmd_validate, "retry": cmd_retry, "ui": cmd_ui,
    "repeats": cmd_repeats, "inject": cmd_inject,
    "scan-output": cmd_scan_output, "patch": cmd_patch,
    "selftest": cmd_selftest,
}


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=sorted(COMMANDS))
    p.add_argument("--model")
    p.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    p.add_argument("--max-units", type=int, dest="max_units")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--show", type=int, default=25)
    p.add_argument("--all", action="store_true",
                   help="retranslate everything, not only what is pending")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--live", action="store_true", help="retry live, not batched")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-warm", action="store_true", dest="no_warm")
    p.add_argument("--no-names", action="store_true", dest="no_names")
    p.add_argument("--show-sample", action="store_true", dest="show_sample")
    p.add_argument("--include-failing", action="store_true",
                   dest="include_failing",
                   help="inject units that fail a hard check (do not ship this)")
    p.add_argument("--pytest", action="store_true")
    a = p.parse_args(argv)
    cfg = config.load()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return COMMANDS[a.command](cfg, a) or 0


if __name__ == "__main__":
    sys.exit(main())
