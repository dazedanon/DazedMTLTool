#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tl.py — CoinPussy (コイン☆プッシー) JP->EN translation pipeline.

Unity 2022 Mono + PlayMaker. No localization system, no strings in
Assembly-CSharp: text lives in UI.Text / TextMeshPro components and in PlayMaker
FSM action params + string variables. Delivery is a BepInEx 5 runtime JP->EN
dictionary hook, so extraction dedupes globally by exact source string.

    derive     scan the AssetRipper export, solve PlayMaker's paramDataType
               encoding, and prove it (run once per export)
    extract    export -> tools/tl/ store + tools/extracted/ reports
    dryrun     scope + token/cost estimate + a sample prompt (no API call)
    submit / status / fetch     manual three-step Claude batch
    run        submit, poll, and fetch in one go (names pass first)
    validate   completeness / residual-JP / placeholder / line-count checks
    retry      re-translate units failing hard validation, with context
    selftest   offline extract -> fake-translate -> validate (no API)
    dict       store -> translations.json for the BepInEx plugin

Usage:
    pip install anthropic tiktoken
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    python tools/tl.py derive
    python tools/tl.py extract
    python tools/tl.py dryrun --show-sample
    python tools/tl.py run
    python tools/tl.py validate
    python tools/tl.py dict
"""

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts"))

from unitytl import batch as batch_mod          # noqa: E402
from unitytl import extract as extract_mod      # noqa: E402
from unitytl import codes, pmparams, store      # noqa: E402

GAME = os.path.dirname(HERE)
DEF_STORE = os.path.join(HERE, "tl")
DEF_OUT = os.path.join(HERE, "extracted")
DEF_LOGS = os.path.join(HERE, "logs")


def default_assets():
    """Newest AssetRipper export's Assets dir."""
    cands = sorted(glob.glob(os.path.join(GAME, "AssetRipper_export_*",
                                          "ExportedProject", "Assets")))
    if not cands:
        sys.exit("No AssetRipper export found next to the game — pass --assets.")
    return cands[-1]


def cmd_derive(args):
    files = extract_mod._list_assets(args.assets)
    print(f"Scanning {len(files)} asset files for PlayMaker actionData...")
    obs, nblocks = [], 0
    for i, p in enumerate(files):
        for ad in pmparams.iter_action_data(p):
            nblocks += 1
            pmparams._observe(ad, obs)
        if i % 1000 == 0:
            print(f"  {i}/{len(files)}  blocks={nblocks}", flush=True)
    mapping, report = pmparams.derive_mapping(obs)
    pmparams.save_mapping(args.store, mapping, report)
    print(f"\n{nblocks} actionData blocks, {report['codes']} paramDataType codes, "
          f"{report['mapped']} mapped.")
    for code, col in sorted(mapping.items()):
        print(f"  {code:3d} -> {col}")
    if report["unmapped"]:
        print(f"  UNMAPPED: {report['unmapped']}")
    nv = len(report["violations"])
    print(f"saturation violations: {nv}  "
          f"({'PROVEN — every column exactly filled' if nv == 0 else 'MAPPING IS WRONG'})")
    print(f"-> {pmparams.mapping_path(args.store)}")
    return 0 if nv == 0 and not report["unmapped"] else 1


def cmd_extract(args):
    s = extract_mod.extract_store(args.assets, args.store, args.out)
    print(f"\nAsset-embedded text ({s['files']} files scanned)")
    print(f"  unique translatable JP : {s['units']}  "
          f"(carried over: {s['carried']})")
    print(f"  excluded and logged    : {s['excluded']}   "
          f"display/key collisions: {s['collisions']} (kept, exact-match only)")
    for b, n in sorted(s["buckets"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:6d}  {b}")
    print(f"\nScripted-dialogue CSVs: {s['csv_units']} units "
          f"across {s['csv_cells']} cells")
    for b, n in sorted(s["csv_buckets"].items(), key=lambda kv: -kv[1]):
        print(f"    {n:6d}  {b}")
    total = s["units"] + s["csv_units"]
    print(f"\nTOTAL translatable units: {total}")
    print("\nby kind:")
    for k, n in (s["kinds"] + s["csv_kinds"]).most_common():
        print(f"  {n:6d}  {k}")
    print(f"\nReports -> {args.out}")
    print("Next: python tools/tl.py dryrun --show-sample")
    return 0


def cmd_inject(args):
    """Write translated copies of the five script CSVs (plugin swaps them at runtime)."""
    from unitytl import csvtext
    src_dir = os.path.join(args.out, "textassets")
    out_dir = args.csv_out
    docs = {d["meta"].get("bucket"): d for _p, d in store.load_docs(args.store)}
    total = {"written": 0, "missing": 0}
    for name, pol in sorted(csvtext.POLICY.items()):
        doc = docs.get(pol["bucket"])
        src = os.path.join(src_dir, name)
        if doc is None or not os.path.exists(src):
            print(f"  ! skipped {name} (no store bucket or missing source)")
            continue
        st = csvtext.inject_file(src, os.path.join(out_dir, name), doc["units"])
        total["written"] += st["written"]
        total["missing"] += st["missing"]
        print(f"  {name:32s} cells written={st['written']:5d} "
              f"left japanese={st['missing']:5d}  ({st['bytes']:,} bytes)")
    print(f"\n{total['written']} cells translated, {total['missing']} still Japanese -> {out_dir}")
    return 0


def cmd_reflow(args):
    """Re-wrap translations whose line count drifted from the source's.

    Pure layout, no model call: the boxes are fixed-size and authored around the
    Japanese line breaks, so a 2-line source rendered as one long English line
    overflows even when the translation itself is right.
    """
    from unitytl import layout

    docs = store.load_docs(args.store)

    # One definition of the box, shared with `shorten` and `validate` — when these
    # drifted apart, reflow reported 9 units as unfittable while shorten insisted
    # everything already fit.
    budget = batch_mod.box_widths(docs)
    if args.max_width:
        budget = {b: args.max_width for b in budget}
    HEIGHT = args.max_lines or batch_mod.BOX_HEIGHT

    changed = skipped = 0
    too_long = []
    dirty_docs = []
    for path, doc in docs:
        bucket = doc["meta"].get("bucket")
        width = budget.get(bucket, 0)
        height = HEIGHT if width else 0
        dirty = False
        for u in doc["units"]:
            tl = u.get("tl") or ""
            if not tl.strip():
                continue
            want = layout.line_count(u.get("src") or u["raw"])
            raw = u["raw"]
            env = batch_mod.envelope(u, bucket)
            if env:
                width, height = env      # individually-sized widget: match the JP
            else:
                width, height = budget.get(bucket, 0), HEIGHT if budget.get(bucket) else 0
            inside = (width <= 0 or layout.widest(tl) <= width) and \
                     (height <= 0 or layout.line_count(tl) <= height)
            want_indent = layout.restore_indent(tl, raw)
            indent_ok = want_indent == tl or (
                width > 0 and layout.widest(want_indent) > width)
            # Already inside the box, not collapsed against the source, and either
            # carrying its indents or unable to. Without this the steps below fight
            # each other: step 1 pulls the width-driven extra lines back down to the
            # source count, step 2 splits them again at possibly different points,
            # and every run reports changes.
            if inside and layout.line_count(tl) >= want and indent_ok:
                continue
            # 1. restore the source's line count (aesthetic: keeps the box rhythm)
            new = tl if layout.line_count(tl) == want else layout.reflow(tl, want)
            # 2. fit the box: wrap to width, and re-flow wholesale if that overruns
            #    the height rather than letting a line fall outside the box
            new, ok = layout.fit_box(new, width, height)
            # 3. put back the 　 indents that wrapping drops — but only if they still
            #    fit. A 　 is two cells, so restoring one can push a line that was
            #    exactly at budget back over the edge, and an indent is decoration
            #    while a clipped line loses words.
            indented = layout.restore_indent(new, raw)
            if width <= 0 or layout.widest(indented) <= width:
                new = indented
            if not ok:
                too_long.append((doc["meta"].get("bucket"), u["id"], tl))
            if new == tl:
                continue
            if new != tl:
                if args.dry_run:
                    print(f"[{doc['meta'].get('bucket')}] {u['id'].split(':')[-1][:8]}")
                    for ln in tl.split("\n"):
                        print(f"    was | {ln}")
                    for ln in new.split("\n"):
                        print(f"    now | {ln}")
                else:
                    u["tl"] = new
                    dirty = True
                changed += 1
        if dirty:
            dirty_docs.append((path, doc))
    if dirty_docs and not args.dry_run:
        store.save_docs(dirty_docs)

    verb = "would rewrap" if args.dry_run else "rewrapped"
    print("\nbox budget per bucket (cells wide x lines tall):")
    for b in sorted(budget):
        print(f"  {b:16s} {budget[b]} x {HEIGHT}")
    print(f"\n{verb} {changed} units; {skipped} left alone (no usable break point)")
    if too_long:
        print(f"\n{len(too_long)} units CANNOT fit their box at any breaking — these need a "
              f"SHORTER translation, not better wrapping:")
        for b, uid, tl in too_long[:12]:
            print(f"  [{b}] {uid.split(':')[-1][:8]}  {tl[:66]!r}")
        if len(too_long) > 12:
            print(f"  ... and {len(too_long) - 12} more")
        print("  Fix with: python tools/tl.py shorten")
    if args.dry_run:
        print("Re-run without --dry-run to apply.")
    return 0


def cmd_package(args):
    """Build the payload the BepInEx plugin loads.

        translations/translations.json   flat JP->EN for the Text-setter hook
        translations/denylist.json       engine-key strings, never translated
        translations/csv_manifest.json   sha1(original CSV) -> translated filename
        translations/csv/*.csv           translated script CSVs

    The manifest is keyed by checksum rather than filename so the plugin can only
    ever substitute a translation for the exact file it was built from.
    """
    import hashlib
    from unitytl import csvtext

    root = args.package_out
    tdir = os.path.join(root, "translations")
    cdir = os.path.join(tdir, "csv")
    os.makedirs(cdir, exist_ok=True)

    docs = {d["meta"].get("bucket"): d for _p, d in store.load_docs(args.store)}

    # 1. dictionary — asset-embedded buckets only; CSV buckets ship as whole files.
    mapping, pending = {}, 0
    for bucket, doc in docs.items():
        if bucket.startswith("CSV_"):
            continue
        for u in doc["units"]:
            tl = (u.get("tl") or "").strip()
            if tl:
                mapping[u["raw"]] = tl
            else:
                pending += 1
    _write_json(os.path.join(tdir, "translations.json"), mapping)

    # 2. denylist — engine keys, minus any string we are deliberately translating
    #    (a few name-box labels double as StringSwitch keys and must still swap).
    keys_path = os.path.join(args.out, "key_strings.json")
    deny = []
    if os.path.exists(keys_path):
        with open(keys_path, encoding="utf-8") as f:
            deny = [s for s in json.load(f).get("strings", []) if s not in mapping]

    # Hand-maintained additions, each with a recorded reason, for strings that break
    # the game when translated for reasons the site-based classifier cannot see.
    manual_path = os.path.join(args.store, "manual_denylist.json")
    manual = {}
    if os.path.exists(manual_path):
        with open(manual_path, encoding="utf-8") as f:
            manual = json.load(f).get("strings", {})
        for s in manual:
            if s not in deny:
                deny.append(s)
            mapping.pop(s, None)          # must not reach the dictionary either
        _write_json(os.path.join(tdir, "translations.json"), mapping)
    _write_json(os.path.join(tdir, "denylist.json"), sorted(deny))

    # 3. translated CSVs + checksum manifest
    src_dir = os.path.join(args.out, "textassets")
    manifest, csv_pending = {}, 0
    for name, pol in sorted(csvtext.POLICY.items()):
        doc = docs.get(pol["bucket"])
        src = os.path.join(src_dir, name)
        if doc is None or not os.path.exists(src):
            print(f"  ! skipped {name} (no store bucket or missing source)")
            continue
        st = csvtext.inject_file(src, os.path.join(cdir, name), doc["units"])
        csv_pending += st["missing"]
        raw = open(src, "rb").read()
        body = raw[3:] if raw.startswith(b"\xef\xbb\xbf") else raw
        manifest[hashlib.sha1(body).hexdigest()] = name
        print(f"  {name:32s} cells written={st['written']:5d} "
              f"left japanese={st['missing']:5d}")
    _write_json(os.path.join(tdir, "csv_manifest.json"), manifest)

    print(f"\ndictionary : {len(mapping)} entries ({pending} units still untranslated)")
    print(f"denylist   : {len(deny)} engine-key strings")
    print(f"CSVs       : {len(manifest)} files ({csv_pending} cells still Japanese)")
    print(f"payload    -> {root}")
    print("Next: tools/mod/CoinPussyEnglish/build.ps1")
    return 0


def _write_json(path, obj):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def cmd_dict(args):
    """Flatten the store into the dictionary the BepInEx plugin loads."""
    docs = store.load_docs(args.store)
    out = {}
    skipped = 0
    for _p, doc in docs:
        for u in doc["units"]:
            tl = (u.get("tl") or "").strip()
            if not tl:
                skipped += 1
                continue
            out[u["raw"]] = tl
    keys = os.path.join(args.out, "key_strings.json")
    deny = []
    if os.path.exists(keys):
        with open(keys, encoding="utf-8") as f:
            deny = json.load(f).get("strings", [])
    payload = {"_meta": {"game": "CoinPussy", "entries": len(out)},
               "_denylist": deny, "translations": out}
    os.makedirs(os.path.dirname(os.path.abspath(args.dict_out)), exist_ok=True)
    with open(args.dict_out, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"{len(out)} entries -> {args.dict_out}  ({skipped} units still untranslated)")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_paths(p, assets=True):
        if assets:
            p.add_argument("--assets", default=None, help="AssetRipper Assets dir")
        p.add_argument("--store", default=DEF_STORE)
        p.add_argument("--out", default=DEF_OUT)

    def add_batch(p):
        p.add_argument("--model", default=batch_mod.MODEL_DEFAULT)
        p.add_argument("--max-units", dest="max_units", type=int, default=60,
                       help="segments per batch request (default 60)")
        p.add_argument("--retranslate-all", dest="retranslate_all", action="store_true")
        p.add_argument("--effort", default=batch_mod.EFFORT_DEFAULT,
                       choices=["low", "medium", "high", "xhigh", "max"])

    p = sub.add_parser("derive"); add_paths(p); p.set_defaults(func=cmd_derive)
    p = sub.add_parser("extract"); add_paths(p); p.set_defaults(func=cmd_extract)

    p = sub.add_parser("dryrun"); add_paths(p, assets=False); add_batch(p)
    p.add_argument("--show-sample", dest="show_sample", action="store_true")
    p.set_defaults(func=lambda a: batch_mod.cmd_dryrun(
        a.store, a.model, a.max_units, a.retranslate_all, a.show_sample))

    p = sub.add_parser("submit"); add_paths(p, assets=False); add_batch(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_submit(
        a.store, a.model, a.max_units, a.retranslate_all))

    p = sub.add_parser("status"); add_paths(p, assets=False)
    p.set_defaults(func=lambda a: batch_mod.cmd_status(a.store))

    p = sub.add_parser("fetch"); add_paths(p, assets=False)
    p.set_defaults(func=lambda a: batch_mod.cmd_fetch(a.store))

    p = sub.add_parser("run"); add_paths(p, assets=False); add_batch(p)
    p.add_argument("--poll", type=int, default=60)
    p.set_defaults(func=lambda a: batch_mod.cmd_run(
        a.store, a.model, a.max_units, a.retranslate_all, a.poll))

    p = sub.add_parser("live", help="translate via the synchronous API (2x cost, minutes not hours)")
    add_paths(p, assets=False); add_batch(p)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-attempts", dest="max_attempts", type=int, default=5)
    p.set_defaults(func=lambda a: batch_mod.cmd_live(
        a.store, a.model, a.max_units, a.retranslate_all,
        a.concurrency, a.max_attempts))

    p = sub.add_parser("shorten", help="re-translate units whose English overflows its box")
    add_paths(p, assets=False); add_batch(p)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--max-attempts", dest="max_attempts", type=int, default=5)
    p.add_argument("--max-lines", dest="max_lines", type=int, default=3)
    p.add_argument("--rounds", type=int, default=2)
    p.set_defaults(func=lambda a: batch_mod.cmd_shorten(
        a.store, a.model, a.concurrency, a.max_attempts, a.max_lines, a.rounds))

    p = sub.add_parser("usage", help="real billed tokens + cost for a finished batch")
    add_paths(p, assets=False)
    p.add_argument("--batch-id", dest="batch_id", default=None)
    p.set_defaults(func=lambda a: batch_mod.cmd_usage(a.store, a.batch_id))

    p = sub.add_parser("validate"); add_paths(p, assets=False)
    p.add_argument("--max-issues", dest="max_issues", type=int, default=25)
    p.set_defaults(func=lambda a: batch_mod.cmd_validate(a.store, a.max_issues))

    p = sub.add_parser("retry"); add_paths(p, assets=False); add_batch(p)
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--max-rounds", dest="max_rounds", type=int, default=2)
    p.set_defaults(func=lambda a: batch_mod.cmd_retry(
        a.store, a.model, a.max_units, a.poll, a.max_rounds))

    p = sub.add_parser("selftest"); add_paths(p, assets=False); add_batch(p)
    p.set_defaults(func=lambda a: batch_mod.cmd_selftest(a.store, a.model, a.max_units))

    p = sub.add_parser("reflow", help="re-wrap translations to the source's line count")
    add_paths(p, assets=False)
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    p.add_argument("--max-width", dest="max_width", type=int, default=0,
                   help="override the per-bucket width budget, in display cells")
    p.add_argument("--max-lines", dest="max_lines", type=int, default=0,
                   help="override the box height in lines (default 3)")
    p.set_defaults(func=cmd_reflow)

    p = sub.add_parser("package"); add_paths(p, assets=False)
    p.add_argument("--package-out", dest="package_out",
                   default=os.path.join(HERE, "translated", "plugin"))
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("inject"); add_paths(p, assets=False)
    p.add_argument("--csv-out", dest="csv_out",
                   default=os.path.join(HERE, "translated", "textassets"))
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("dict"); add_paths(p, assets=False)
    p.add_argument("--dict-out", dest="dict_out",
                   default=os.path.join(HERE, "translated", "translations.json"))
    p.set_defaults(func=cmd_dict)

    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if getattr(args, "assets", None) is None and hasattr(args, "assets"):
        args.assets = default_assets()
    if getattr(args, "effort", None):
        batch_mod.set_effort(args.effort)
    os.makedirs(DEF_LOGS, exist_ok=True)
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
