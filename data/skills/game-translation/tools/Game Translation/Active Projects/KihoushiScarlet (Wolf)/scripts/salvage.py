#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
salvage.py - recover translations from batch requests whose JSON failed to parse.

    python scripts/salvage.py <batch_id> [--apply]

A request that SUCCEEDED at the API but whose body this pipeline could not parse is
paid-for work sitting on the server: batch results stay retrievable for 29 days, and
retrieving them is free. Re-translating instead pays twice for the same lines.

Two failure shapes seen on this game, both recoverable:

  Extra data: line 3 column 1     the model appended prose after the JSON object
  Unterminated string ...         the response hit max_tokens mid-string, so every
                                  complete pair before the cut is still good

The second is why this walks the object incrementally instead of requiring the whole
body to parse: a truncated response still carries most of its translations, and
throwing them away because the tail is broken is a self-inflicted cost.
"""

import os
import re
import sys
import json
import argparse

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(WS, "scripts"))

import claude_translate as ct  # noqa: E402

_PAIR_RE = re.compile(r'"(\d+)"\s*:\s*"((?:[^"\\]|\\.)*)"\s*(?=[,}])', re.S)


def salvage_pairs(text):
    """Every complete "n": "..." pair, in order, from a body that will not parse.

    Anchored on the closing quote being followed by , or } so a string containing an
    escaped quote is not cut short, and a half-written final pair is simply not
    matched rather than guessed at.
    """
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
    out = {}
    for m in _PAIR_RE.finditer(s):
        try:
            out[m.group(1)] = json.loads('"' + m.group(2) + '"')
        except json.JSONDecodeError:
            try:
                out[m.group(1)] = json.loads(
                    '"' + ct._repair_json_escapes(m.group(2)) + '"')
            except json.JSONDecodeError:
                pass
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("batch_id")
    ap.add_argument("--apply", action="store_true",
                    help="write the recovered translations into batch.json")
    args = ap.parse_args()

    state = ct.load_state() or {}
    id_maps = state.get("id_maps", {})
    if state.get("batch_id") != args.batch_id:
        print(f"note: tl/_batch_state.json holds {state.get('batch_id')!r}; "
              "id_maps may not cover this batch.")

    client = ct.get_client()
    batch = ct.load_batch()
    lines = batch["lines"]
    recovered = {}
    for r in client.messages.batches.results(args.batch_id):
        res = r.result
        if getattr(res, "type", None) != "succeeded":
            continue
        text = "".join(getattr(b, "text", "") for b in res.message.content
                       if b.type == "text")
        try:
            ct.parse_json_object(text)
            continue                      # parsed fine, nothing to salvage
        except Exception as e:
            pairs = salvage_pairs(text)
            n_expected = len(id_maps.get(r.custom_id, []))
            stop = getattr(res.message, "stop_reason", None)
            print(f"{r.custom_id}: {type(e).__name__} -> salvaged {len(pairs)}"
                  f"/{n_expected} pair(s)  (stop_reason={stop})")
            if pairs:
                recovered[r.custom_id] = pairs

    if not recovered:
        print("nothing to salvage.")
        return 0
    total = sum(len(v) for v in recovered.values())
    if not args.apply:
        print(f"\n{total} translation(s) recoverable. Re-run with --apply to write them.")
        return 0

    applied, errs = ct.apply_results(batch, recovered, id_maps)
    ct.fanout(batch, verbose=True)
    ct.save_batch(batch)
    print(f"applied {applied} salvaged translation(s); {len(errs)} index error(s)")
    for e in errs[:10]:
        print("  !", e)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
