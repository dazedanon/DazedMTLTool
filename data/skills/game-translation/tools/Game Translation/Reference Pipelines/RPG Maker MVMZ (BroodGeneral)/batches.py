#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batches.py — list and cancel Anthropic Message Batches (the ones `tl.py run`
submits). Handy when a `run` is stuck/polling or you submitted by mistake.

    set ANTHROPIC_API_KEY=sk-...

    python tooling/batches.py                 # list recent batches (default)
    python tooling/batches.py list --limit 50
    python tooling/batches.py cancel <batch_id> [<batch_id> ...]
    python tooling/batches.py cancel --all     # cancel every in-progress batch
    python tooling/batches.py cancel --mine     # cancel the batch from tl/_batch_state.json

Only an in-progress batch can be cancelled; cancellation finishes any in-flight
requests, so the status goes in_progress -> canceling -> ended. Already-ended
batches can't be cancelled (nothing is running / billing for them).
"""
import os
import sys
import argparse
import collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rpgmvtl import batch as batch_mod, store  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEF_STORE = os.path.join(ROOT, "tooling", "tl")
CANCELABLE = {"in_progress"}


def _counts(b):
    rc = getattr(b, "request_counts", None)
    if not rc:
        return ""
    parts = []
    for k in ("processing", "succeeded", "errored", "canceled", "expired"):
        v = getattr(rc, k, None)
        if v:
            parts.append(f"{k[:4]}={v}")
    return " ".join(parts)


def _mine(store_dir):
    st = store.load_state(store_dir) or {}
    return st.get("batch_id")


def cmd_list(client, limit, store_dir):
    mine = _mine(store_dir)
    print(f"{'BATCH ID':<28} {'STATUS':<12} {'CREATED':<22} COUNTS")
    print("-" * 90)
    n = 0
    for b in client.messages.batches.list(limit=limit):
        n += 1
        mark = "  <- yours" if b.id == mine else ""
        created = str(getattr(b, "created_at", "") or "")[:22]
        print(f"{b.id:<28} {b.processing_status:<12} {created:<22} {_counts(b)}{mark}")
    if n == 0:
        print("(no batches found)")
    else:
        print(f"\n{n} batch(es). Cancel with: python tooling/batches.py cancel <id>  (or --all / --mine)")
    return 0


def _cancel_one(client, bid):
    try:
        b = client.messages.batches.cancel(bid)
        print(f"  cancel requested: {bid} -> {getattr(b, 'processing_status', '?')}")
        return True
    except Exception as e:
        print(f"  ! {bid}: {e}")
        return False


def cmd_cancel(client, ids, do_all, do_mine, limit, store_dir):
    targets = list(ids)
    if do_mine:
        m = _mine(store_dir)
        if m:
            targets.append(m)
        else:
            print("No batch in tl/_batch_state.json.")
    if do_all:
        for b in client.messages.batches.list(limit=limit):
            if b.processing_status in CANCELABLE:
                targets.append(b.id)
    targets = list(dict.fromkeys(targets))  # de-dupe, keep order
    if not targets:
        print("Nothing to cancel (no ids given; no in-progress batches). "
              "Use 'list' to see them, or pass an id / --all / --mine.")
        return 1
    print(f"Cancelling {len(targets)} batch(es):")
    ok = sum(_cancel_one(client, t) for t in targets)
    print(f"done: {ok}/{len(targets)} cancellation(s) accepted.")
    return 0 if ok else 1


def cmd_usage(client, bid, model, store_dir):
    """Sum the REAL billed tokens across a finished batch's results and price it."""
    if not bid:
        bid = _mine(store_dir)
    if not bid:
        print("Give a batch id (or --mine). Use 'list' to find it.")
        return 1
    tot = collections.Counter()
    ok = err = 0
    for r in client.messages.batches.results(bid):
        res = r.result
        if getattr(res, "type", None) != "succeeded":
            err += 1
            continue
        ok += 1
        u = res.message.usage
        tot["in"] += getattr(u, "input_tokens", 0) or 0
        tot["out"] += getattr(u, "output_tokens", 0) or 0
        tot["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        tot["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        det = getattr(u, "output_tokens_details", None)
        if det is not None:
            tot["thinking"] += getattr(det, "thinking_tokens", 0) or 0

    pr = batch_mod.price_for(model)
    # batch = 50% off input/output; cache rates already net.
    cost = (tot["in"] / 1e6 * pr["batch_in"]
            + tot["out"] / 1e6 * pr["batch_out"]
            + tot["cache_write"] / 1e6 * pr["cache_write"]
            + tot["cache_read"] / 1e6 * pr["cache_read"])
    print(f"batch {bid}  ({ok} succeeded, {err} errored)   model={model}")
    print(f"  input (uncached)   : {tot['in']:>12,}  @ ${pr['batch_in']}/M = ${tot['in']/1e6*pr['batch_in']:.2f}")
    print(f"  cache write        : {tot['cache_write']:>12,}  @ ${pr['cache_write']}/M = ${tot['cache_write']/1e6*pr['cache_write']:.2f}")
    print(f"  cache read         : {tot['cache_read']:>12,}  @ ${pr['cache_read']}/M = ${tot['cache_read']/1e6*pr['cache_read']:.2f}")
    print(f"  OUTPUT             : {tot['out']:>12,}  @ ${pr['batch_out']}/M = ${tot['out']/1e6*pr['batch_out']:.2f}")
    print(f"    of which thinking: {tot['thinking']:>12,}  (billed inside OUTPUT above)")
    print(f"  --------------------------------------------------")
    print(f"  estimated cost     : ${cost:.2f}")
    if tot["out"]:
        print(f"  output/input ratio : {tot['out']/max(1,tot['in']+tot['cache_read']+tot['cache_write']):.2f}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", default=DEF_STORE)
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("list", help="list recent batches (default)")
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("cancel", help="cancel batches by id, or --all / --mine")
    p.add_argument("ids", nargs="*", help="batch id(s) to cancel")
    p.add_argument("--all", action="store_true", help="cancel every in-progress batch")
    p.add_argument("--mine", action="store_true", help="cancel the batch in tl/_batch_state.json")
    p.add_argument("--limit", type=int, default=50, help="how many batches to scan for --all")

    p = sub.add_parser("usage", help="show real billed tokens (input/output/cache/thinking) for a batch")
    p.add_argument("batch_id", nargs="?", help="batch id (default: the one in tl/_batch_state.json)")
    p.add_argument("--model", default="claude-opus-4-8", help="model used, for pricing (default %(default)s)")

    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    client = batch_mod.get_client()
    if args.cmd == "cancel":
        return cmd_cancel(client, args.ids, args.all, args.mine, args.limit, args.store)
    if args.cmd == "usage":
        return cmd_usage(client, args.batch_id, args.model, args.store)
    # default + "list"
    limit = getattr(args, "limit", 20)
    return cmd_list(client, limit, args.store)


if __name__ == "__main__":
    sys.exit(main() or 0)
