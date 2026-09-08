#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tl.py — RPG Maker MV/MZ translation tool (Anthropic Message Batches).

Pipeline:
    extract   www/data        -> tooling/tl/ store (+ glossary)
    dryrun    preview cost / sample prompt (no API key needed)
    run       submit a batch, poll, fetch translations into the store
              (or: submit / status / fetch as separate steps)
    validate  completeness / quality / control-code integrity checks
    inject    store            -> patched www/data (drop-in, or --in-place)
    selftest  offline extract->fake-translate->validate (no API)

Typical use:
    set ANTHROPIC_API_KEY=sk-...
    python tooling/tl.py extract
    python tooling/tl.py dryrun --show-sample
    python tooling/tl.py run
    python tooling/tl.py validate
    python tooling/tl.py inject              # writes tooling/out/www/data
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rpgmvtl import extract as extract_mod, inject as inject_mod, batch as batch_mod, store  # noqa: E402
from rpgmvtl.config import Config  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# RPG Maker MZ layout: the data dir is <game>/data (MV games use <game>/www/data).
# Fall back to www/data automatically if this ever runs on an MV game.
DEF_DATA = os.path.join(ROOT, "data")
if not os.path.isdir(DEF_DATA) and os.path.isdir(os.path.join(ROOT, "www", "data")):
    DEF_DATA = os.path.join(ROOT, "www", "data")
DEF_STORE = os.path.join(ROOT, "tooling", "tl")
DEF_OUT = os.path.join(ROOT, "tooling", "out", "data")


def _cfg(args) -> Config:
    c = Config()
    for attr in ("width", "list_width", "note_width"):
        if getattr(args, attr, None) is not None:
            setattr(c, attr, getattr(args, attr))
    if getattr(args, "no_wrap", False):
        c.fix_wrap = False
    for flag in ("notes", "code_122", "code_356", "code_355", "code_108",
                 "system_switches", "system_variables"):
        if getattr(args, flag, False):
            setattr(c, flag, True)
    c.game_jp = getattr(args, "game_jp", "") or ""
    c.game_en = getattr(args, "game_en", "") or ""
    return c


def cmd_extract(args):
    cfg = _cfg(args)
    summary, glossary = extract_mod.extract_store(args.data, args.store, cfg,
                                                  only=args.only or None,
                                                  force=getattr(args, "force", False))
    total = sum(n for _f, n in summary)
    print(f"Extracted {total} units across {len(summary)} files -> {args.store}")
    for f, n in summary:
        print(f"  {n:5d}  {f}")
    names = len(glossary.get("names", {}))
    print(f"Glossary: {names} character names seeded ({glossary_done(glossary)} already translated).")
    print("Next: python tooling/tl.py dryrun --show-sample")
    return 0


def glossary_done(g):
    return sum(1 for v in g.get("names", {}).values() if store.name_en(v))


def cmd_inject(args):
    cfg = _cfg(args)
    per_file, totals, target = inject_mod.inject_store(
        args.data, args.store, args.out, cfg, in_place=args.in_place)
    print(f"Injected into: {target}")
    for src, st in per_file:
        if "error" in st:
            print(f"  ! {src}: {st['error']}")
        else:
            extra = f"  (mismatch {st['mismatch']})" if st.get("mismatch") else ""
            print(f"  {src}: text={st.get('text',0)} choice={st.get('choice',0)} "
                  f"+{sum(v for k,v in st.items() if k not in ('text','choice','mismatch'))} fields{extra}")
    print("Totals:", {k: v for k, v in totals.items()})
    if not args.in_place:
        print(f"\nDrop-in: copy {target} over the game's data dir (back up first), or re-run with --in-place.")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_common(p):
        p.add_argument("--data", default=DEF_DATA, help="www/data dir (default: %(default)s)")
        p.add_argument("--store", default=DEF_STORE, help="translation store dir")

    def add_cfg(p):
        p.add_argument("--width", type=int, help="message wrap width (chars)")
        p.add_argument("--list-width", dest="list_width", type=int, help="description wrap width")
        p.add_argument("--note-width", dest="note_width", type=int)
        p.add_argument("--no-wrap", action="store_true", help="disable text wrapping")
        p.add_argument("--notes", action="store_true", help="also extract <tag:...> note fields")
        p.add_argument("--code-122", dest="code_122", action="store_true", help="control-variable strings (risky)")
        p.add_argument("--code-356", dest="code_356", action="store_true", help="MV plugin commands (risky)")
        p.add_argument("--code-355", dest="code_355", action="store_true", help="script lines (very risky)")
        p.add_argument("--code-108", dest="code_108", action="store_true", help="comment annotations (risky)")
        p.add_argument("--system-switches", dest="system_switches", action="store_true")
        p.add_argument("--system-variables", dest="system_variables", action="store_true")

    def add_batch(p):
        p.add_argument("--model", default=batch_mod.MODEL_DEFAULT)
        p.add_argument("--max-units", dest="max_units", type=int, default=80,
                       help="max segments per batch request (default 80)")
        p.add_argument("--retranslate-all", dest="retranslate_all", action="store_true",
                       help="re-translate every unit (overwrites existing translations)")
        p.add_argument("--effort", default=batch_mod.EFFORT_DEFAULT,
                       choices=["low", "medium", "high", "xhigh", "max"],
                       help="reasoning effort / token spend (default %(default)s; "
                            "'high' is the model default and costs much more)")

    p = sub.add_parser("extract"); add_common(p); add_cfg(p)
    p.add_argument("--force", action="store_true",
                   help="extract even if --data looks already translated (bypasses the safety guard)")
    p.add_argument("--only", nargs="*", default=[], help="only these data files (e.g. CommonEvents.json)")
    p.add_argument("--game-jp", dest="game_jp", default=""); p.add_argument("--game-en", dest="game_en", default="")
    p.set_defaults(func=cmd_extract)

    p = sub.add_parser("dryrun"); add_common(p); add_batch(p)
    p.add_argument("--show-sample", dest="show_sample", action="store_true")
    p.set_defaults(func=lambda a: batch_mod.cmd_dryrun(a.store, a.model, a.max_units, a.retranslate_all, a.show_sample))

    p = sub.add_parser("submit"); add_common(p); add_batch(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_submit(a.store, a.model, a.max_units, a.retranslate_all))

    p = sub.add_parser("status"); add_common(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_status(a.store))

    p = sub.add_parser("fetch"); add_common(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_fetch(a.store))

    p = sub.add_parser("run"); add_common(p); add_batch(p)
    p.add_argument("--poll", type=int, default=60, help="seconds between status polls")
    p.set_defaults(func=lambda a: batch_mod.cmd_run(a.store, a.model, a.max_units, a.retranslate_all, a.poll))

    p = sub.add_parser("validate"); add_common(p)
    p.add_argument("--max-issues", dest="max_issues", type=int, default=25)
    p.set_defaults(func=lambda a: batch_mod.cmd_validate(a.store, a.max_issues))

    p = sub.add_parser("retry", help="re-translate units failing hard validation, with scene context")
    add_common(p); add_batch(p)
    p.add_argument("--poll", type=int, default=60, help="seconds between status polls")
    p.add_argument("--max-rounds", dest="max_rounds", type=int, default=2)
    p.set_defaults(func=lambda a: batch_mod.cmd_retry(a.store, a.model, a.max_units, a.poll, a.max_rounds))

    p = sub.add_parser("selftest"); add_common(p); add_batch(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_selftest(a.store, a.model, a.max_units))

    p = sub.add_parser("inject"); add_common(p); add_cfg(p)
    p.add_argument("--out", default=DEF_OUT, help="output data dir (default: %(default)s)")
    p.add_argument("--in-place", dest="in_place", action="store_true",
                   help="patch www/data directly (takes a timestamped backup first)")
    p.set_defaults(func=cmd_inject)

    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if getattr(args, "effort", None):
        batch_mod.set_effort(args.effort)
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
