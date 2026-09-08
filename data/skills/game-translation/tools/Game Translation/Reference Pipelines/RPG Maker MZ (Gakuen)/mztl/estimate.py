#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
estimate.py - scope and cost before spending anything.

Two things this gets right that a naive estimator does not:

* **Two scripts, two ratios.** A single tokens-per-character proxy over a mixed
  prompt is badly wrong: `len(text) * 1.1` is right for Japanese and about 4x
  too heavy for English, so an English rules-and-bible prefix estimates at
  11,509 tokens against 4,261 real. Japanese and non-Japanese are counted
  separately. When `tiktoken` is installed it is used instead, and when
  `--exact` is passed `messages.count_tokens` is called (free, no generation).

* **The output ratio belongs to the output CONTRACT, not the game.** A rich
  per-unit object measures 2.36; a bare `{id: string}` map measures 1.38. This
  pipeline uses the bare map, so 1.38 is the honest centre and 1.3 runs ~6%
  light. All three are printed, and the effort level is printed beside them
  because an estimate at `low` is wrong by a multiple against the API default
  of `high`.

Input estimates are reliable (measured 0.2% off on a real run). Output
estimates are not. Check the bill against this once, then trust the
measurement.
"""

import re
import collections

from . import store, requests as R, driver, prompts

_JP_RE = re.compile(r"[぀-ヿ㐀-䶿一-鿿]")


def count_tokens(text):
    jp = len(_JP_RE.findall(text))
    return int(jp * 1.1 + (len(text) - jp) * 0.28) + 8


def _counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return lambda s: len(enc.encode(s)), "tiktoken o200k_base"
    except Exception:
        return count_tokens, "two-script char proxy"


def run(cfg, store_dir, model, max_units, retranslate_all=False,
        effort="low", show_sample=False, verbose=True):
    docs, glossary, reqs, id_maps, name_maps = driver.build_all(
        store_dir, cfg, model, max_units, retranslate_all, effort=effort,
        ttl="5m")
    tok, tokname = _counter()

    prefix_count = collections.defaultdict(int)
    prefix_tok = {}
    dyn_in = 0
    out_scaffold = 0
    src_tok = 0
    sample = None

    for req in reqs:
        blocks = req["params"]["system"]
        cut = len(blocks)
        for i, b in enumerate(blocks):
            if "cache_control" in b:
                cut = i + 1
                break
        prefix = "".join(b["text"] for b in blocks[:cut])
        dyn = "".join(b["text"] for b in blocks[cut:])
        prefix_count[prefix] += 1
        prefix_tok.setdefault(prefix, tok(prefix))
        user = req["params"]["messages"][0]["content"]
        dyn_in += tok(dyn) + tok(user) + 8
        cid = req["custom_id"]
        n = len(id_maps.get(cid, name_maps.get(cid, [])))
        out_scaffold += tok("".join('"%d":"",' % i for i in range(1, n + 1)))
        if sample is None and cid in id_maps:
            sample = user

    for _doc, u in store.all_units(docs):
        if retranslate_all or not (u.get("tl") or "").strip():
            src_tok += tok(u["src"])

    cache_write = sum(prefix_tok[p] for p in prefix_count)
    cache_read = sum(prefix_tok[p] * (prefix_count[p] - 1) for p in prefix_count)
    raw_in = sum(prefix_tok[p] * prefix_count[p] for p in prefix_count) + dyn_in

    n_text = sum(len(v) for v in id_maps.values())
    n_names = sum(len(v) for v in name_maps.values())
    p = R.price_for(model)

    if verbose:
        bible = prompts.load_side_file(store_dir, "game_prompt.md")
        quirks = prompts.load_side_file(store_dir, "quirks.md")
        tk = ("post-4.7 (the pricing page says ~30%% more tokens for the same "
              "text; a measured run came in at x0.998, so nothing is inflated "
              "here)" if model in R.NEW_TOKENIZER else "pre-4.7")
        print("DRY RUN   model=%s   effort=%s" % (model, effort))
        print("  proxy               : %s" % tokname)
        print("  model tokenizer     : %s" % tk)
        print("  requests            : %d  (%d text/data, %d name)"
              % (len(reqs), len(id_maps), len(name_maps)))
        print("  units pending       : %d text/data, %d names" % (n_text, n_names))
        print("  game bible          : %s"
              % ("%d chars" % len(bible) if bible else "MISSING - write "
                 "tl/game_prompt.md before spending anything"))
        print("  quirks file         : %s"
              % ("%d chars" % len(quirks) if quirks else "none"))
        print("  distinct cached prefixes: %d  (%d tok, re-read %d times)"
              % (len(prefix_count), cache_write, len(reqs) - len(prefix_count)))
        if len(prefix_count) > 2:
            print("     !! more than 2 distinct prefixes means the cached "
                  "block is not byte-stable; every extra one pays a full "
                  "cache write.")
        if cache_write and cache_write / max(1, len(prefix_count)) < 1024:
            print("     !! a cached prefix under ~1024 tokens silently does "
                  "not cache and returns no error.")
        print("  dynamic input       : %d tok" % dyn_in)
        print("  raw input if uncached: %d tok" % raw_in)
        print("  JP source only      : %d tok" % src_tok)
        print()
        print("  Cost, in=$%.2f out=$%.2f cache5m-write=$%.2f read=$%.2f per MTok"
              % (p["in"], p["out"], p["cw5m"], p["cr"]))
        print("  ratio | out tok  | batch+cache | batch only | live+cache | live only")
        for r in (1.30, 1.38, 1.60, 2.36):
            out = int(src_tok * r) + out_scaffold
            # OPTIMISTIC: one write and N-1 reads. A batch fans out
            # independently and does not behave like that - a measured run
            # re-read only 31% - so the cold-cache row below is the honest
            # bound and both are printed.
            cached_in = (cache_write / 1e6 * p["cw5m"]
                         + cache_read / 1e6 * p["cr"]
                         + dyn_in / 1e6 * p["in"])
            cold_in = ((cache_write + cache_read) / 1e6 * p["cw5m"]
                       + dyn_in / 1e6 * p["in"])
            raw_input_cost = raw_in / 1e6 * p["in"]
            out_cost = out / 1e6 * p["out"]
            bc = 0.5 * (cached_in + out_cost)
            bo = 0.5 * (raw_input_cost + out_cost)
            lc = cached_in + out_cost
            lo = raw_input_cost + out_cost
            tag = "  <- this contract" if abs(r - 1.38) < 1e-9 else ""
            print("  %5.2f | %8d | $%10.2f | $%9.2f | $%9.2f | $%8.2f%s"
                  % (r, out, bc, bo, lc, lo, tag))
            if abs(r - 1.38) < 1e-9:
                cold = 0.5 * (cold_in + out_cost)
                print("        |          | $%10.2f  <- batch+cache with a "
                      "COLD cache on every request (every prefix written, "
                      "none re-read). The truth is between the two."
                      % cold)
        print()
        print("  Effort is %r. An estimate at 'low' is wrong by a MULTIPLE "
              "against the API default of 'high'." % effort)
        print("  Input estimates are reliable; output estimates are not. "
              "Compare the bill once, then trust the measurement.")
        print("  Not included, because this pipeline does not use them: "
              "inference_geo='us' would bill 1.1x on EVERY category, and fast "
              "mode ($10/$50, Opus 5 and 4.8) is not available with batch at "
              "all. The 1M context window carries no premium.")
        if show_sample and sample:
            print("\n----- SAMPLE USER PROMPT -----\n" + sample[:3000])
    return 0


def exact(cfg, store_dir, model, max_units, effort="low", limit=3):
    """`messages.count_tokens` on the first few requests. Free, no generation."""
    from . import client as C
    _docs, _g, reqs, id_maps, _nm = driver.build_all(
        store_dir, cfg, model, max_units, effort=effort, ttl="5m")
    cl = C.get_client()
    total = 0
    for req in reqs[:limit]:
        r = cl.messages.count_tokens(
            model=model,
            system=req["params"]["system"],
            messages=req["params"]["messages"])
        n = r.input_tokens
        total += n
        print("  %-28s %6d input tokens (%d units)"
              % (req["custom_id"], n, len(id_maps.get(req["custom_id"], []))))
    if reqs[:limit]:
        avg = total / float(len(reqs[:limit]))
        print("  average %.0f tok/request over %d sampled -> %d requests "
              "~= %.0f input tokens for the run"
              % (avg, len(reqs[:limit]), len(reqs), avg * len(reqs)))
    return 0
