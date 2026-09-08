#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tl.py — Belphegor (SRPG Studio) JP->EN batch translation (Anthropic Message Batches).

Pipeline:
    extract   patch/*.json + js_strings.json  -> tooling/tl/ store (+ glossary)
    dryrun    preview cost / sample prompt (no API key needed)
    run       names-first, then translate everything, polling to completion
              (or: submit / status / fetch as separate steps)
    validate  completeness / residual-JP / control-code integrity checks
    retry     re-translate hard-failing units with scene context
    inject    store -> translated patch/*.json (for SRPG_Unpacker -a) + js_strings.json
    selftest  offline extract->fake-translate->validate (no API)

Typical use (PowerShell):
    pip install anthropic tiktoken
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python tooling/tl.py extract
    python tooling/tl.py dryrun --show-sample
    python tooling/tl.py run
    python tooling/tl.py validate
    python tooling/tl.py inject          # writes translated patch + js_strings.json
    # then assemble the game:  python tooling/tl.py build   (see README)
"""

import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from srpgtl import extract as extract_mod, inject as inject_mod, batch as batch_mod, store  # noqa: E402

TOOLING = os.path.dirname(os.path.abspath(__file__))
DEF_PATCH = os.path.join(TOOLING, "patch")
DEF_JS = os.path.join(TOOLING, "js_strings.json")
DEF_STORE = os.path.join(TOOLING, "tl")


def cmd_extract(args):
    summary, glossary, counts = extract_mod.extract_store(args.patch, args.js, args.store)
    print(f"Store written -> {args.store}")
    print(f"  dialogue units : {counts['dialogue']} across {counts['maps_with_dialogue']} maps")
    print(f"  names (deduped): {counts['names']}")
    print(f"  descriptions   : {counts['desc']}")
    print(f"  UI/conds/pages : {counts['ui']}")
    print(f"  misc text      : {counts['info_global']}")
    print(f"  customParameters: {counts['customparams']}")
    print(f"  plugin strings : {counts['plugins']}")
    print(f"  characters seeded into glossary: {counts['characters_seeded']} "
          f"({sum(1 for v in glossary['names'].values() if store.name_en(v))} already have EN)")
    print("Next: edit tooling/tl/glossary.json (verify genders/roles), then: python tooling/tl.py dryrun --show-sample")
    return 0


def cmd_inject(args):
    s1, target = inject_mod.inject_patch(args.patch, args.store, width=args.width,
                                         in_place=not args.copy,
                                         out_dir=(args.patch + "_translated"))
    print(f"Patch injected -> {target}")
    print(f"  files written={s1['files']}  fields={s1['fields']}  "
          f"glossary-names={s1['names_glossary']}  customParam-subs={s1['customparam_subs']}")
    s2 = inject_mod.inject_js(args.js, args.store, width=args.width)
    print(f"js_strings.json filled: {s2['filled']} translations across {s2['files']} files")
    print("\nAssemble the game:")
    print("  1) SRPG_Unpacker.exe <extracted>\\project.dat -a -o tooling\\patch")
    print("  2) python tooling\\js_text_tool.py apply <extracted> tooling\\js_strings.json")
    print("  3) SRPG_Unpacker.exe <extracted> -o data.dts   (back up the original first)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--patch", default=DEF_PATCH)
        p.add_argument("--js", default=DEF_JS)
        p.add_argument("--store", default=DEF_STORE)

    def batch_flags(p):
        p.add_argument("--model", default=batch_mod.MODEL_DEFAULT)
        p.add_argument("--max-units", dest="max_units", type=int, default=80)
        p.add_argument("--retranslate-all", dest="retranslate_all", action="store_true")
        p.add_argument("--effort", default=batch_mod.EFFORT_DEFAULT,
                       choices=["low", "medium", "high", "xhigh", "max"])

    p = sub.add_parser("extract"); common(p); p.set_defaults(func=cmd_extract)

    p = sub.add_parser("dryrun"); common(p); batch_flags(p)
    p.add_argument("--show-sample", dest="show_sample", action="store_true")
    p.set_defaults(func=lambda a: batch_mod.cmd_dryrun(a.store, a.model, a.max_units, a.retranslate_all, a.show_sample))

    p = sub.add_parser("submit"); common(p); batch_flags(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_submit(a.store, a.model, a.max_units, a.retranslate_all))

    p = sub.add_parser("status"); common(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_status(a.store))

    p = sub.add_parser("fetch"); common(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_fetch(a.store))

    p = sub.add_parser("run"); common(p); batch_flags(p)
    p.add_argument("--poll", type=int, default=60)
    p.set_defaults(func=lambda a: batch_mod.cmd_run(a.store, a.model, a.max_units, a.retranslate_all, a.poll))

    p = sub.add_parser("validate"); common(p)
    p.add_argument("--max-issues", dest="max_issues", type=int, default=25)
    p.set_defaults(func=lambda a: batch_mod.cmd_validate(a.store, a.max_issues))

    p = sub.add_parser("retry"); common(p); batch_flags(p)
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--max-rounds", dest="max_rounds", type=int, default=2)
    p.set_defaults(func=lambda a: batch_mod.cmd_retry(a.store, a.model, a.max_units, a.poll, a.max_rounds))

    p = sub.add_parser("selftest"); common(p); batch_flags(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_selftest(a.store, a.model, a.max_units))

    p = sub.add_parser("inject"); common(p)
    p.add_argument("--width", type=int, default=inject_mod.DEFAULT_WIDTH, help="message-box wrap width (cells)")
    p.add_argument("--copy", action="store_true", help="write to patch_translated/ instead of in place")
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
