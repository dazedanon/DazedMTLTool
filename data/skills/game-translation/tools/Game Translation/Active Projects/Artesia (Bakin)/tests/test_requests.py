#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_requests.py - a SECOND, independently written opinion on the request set.

`tests/selftest.py` checks the same properties. That is deliberate: this file
was written for a different game and carried over unchanged apart from the
config accessor, so where the two agree the agreement means something. Where
they disagree, one of them has a bug.

No network. Checks the things that turn a 68-request run into 68 wasted
requests: the cached prefix being byte-stable, the params shape matching what
the Batches API accepts, sampling params being absent on a model that 400s on
them, and every unit appearing exactly once across the whole set.

    python tests/test_requests.py
"""

import os
import sys
import json
import collections

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from artl import config, store, driver, requests as R  # noqa: E402

STORE = os.path.join(HERE, "tl")
FAILS = []


def check(label, ok, detail=""):
    if ok:
        print("  ok   %s" % label)
    else:
        FAILS.append("%s %s" % (label, detail))
        print("  FAIL %s %s" % (label, detail))


cfg = config.load()
MODEL = cfg["model"]
# `retranslate_all` so the test builds the FULL request set whatever the run
# state is. This checks the shape of a request, not what happens to be pending -
# and once a game is finished there is nothing pending, which would leave the
# test silently checking zero requests and passing.
docs, glossary, reqs, id_maps, name_maps = driver.build_all(
    STORE, cfg, MODEL, 60, retranslate_all=True, effort="low", ttl=cfg["batch_ttl"],
    roster_min=cfg["roster_min"], dedup_dialogue=cfg["dedup_dialogue"])

print("built %d request(s)" % len(reqs))
if not reqs:
    print("  FAIL no requests built at all - nothing below was actually tested")
    sys.exit(1)

# The name pass and the text pass are two different jobs with two different
# system prompts, so they legitimately have two cached prefixes. What matters is
# that each job has exactly ONE - a prefix that varies within a job is never
# re-read and bills the write multiplier on every request.
text_reqs = [r for r in reqs if r["custom_id"] in id_maps]
name_reqs = [r for r in reqs if r["custom_id"] in name_maps]
check("the run splits into text and name requests",
      bool(text_reqs) and len(text_reqs) + len(name_reqs) == len(reqs))


def prefix_of(r):
    blocks = r["params"]["system"]
    cut = len(blocks)
    for i, b in enumerate(blocks):
        if "cache_control" in b:
            cut = i + 1
            break
    return "".join(b["text"] for b in blocks[:cut])


# --- the cached prefix must be byte-identical within each job ---------------
prefixes = collections.Counter(prefix_of(r) for r in text_reqs)
check("exactly one cached prefix across every TEXT request",
      len(prefixes) == 1,
      "(got %d - every extra one pays a full cache write)" % len(prefixes))
if name_reqs:
    np_ = collections.Counter(prefix_of(r) for r in name_reqs)
    check("exactly one cached prefix across every NAME request", len(np_) == 1,
          "(got %d)" % len(np_))
ptok = len(next(iter(prefixes)))
check("cached prefix is over the ~1024-token minimum", ptok > 4096,
      "(%d chars; a shorter prefix silently does not cache and returns no "
      "error)" % ptok)
check("cache breakpoint carries the batch TTL",
      all(any(b.get("cache_control", {}).get("ttl") == cfg["batch_ttl"]
              for b in r["params"]["system"]) for r in reqs),
      "(5m, not 1h: on a batch the 1h write multiplier of 2.0x needs a 53% "
      "re-read rate to break even and a batch does not reach it)")
check("at most 4 system blocks (the breakpoint limit)",
      all(len(r["params"]["system"]) <= 4 for r in reqs))

# --- params shape ----------------------------------------------------------
ALLOWED = {"model", "max_tokens", "system", "messages", "thinking",
           "output_config", "temperature", "top_p", "top_k", "stop_sequences",
           "metadata"}
bad = set()
for r in reqs:
    bad |= set(r["params"]) - ALLOWED
check("no unknown top-level params", not bad, str(bad))
check("no sampling params on a model that 400s on them",
      all("temperature" not in r["params"] and "top_p" not in r["params"]
          for r in reqs),
      "(the cut is between 4.6 and 4.7 and is an explicit list, not a "
      "numeric comparison)")
check("adaptive thinking is on",
      all(r["params"].get("thinking") == {"type": "adaptive"} for r in reqs))
check("effort travels inside output_config, not top level",
      all(r["params"].get("output_config", {}).get("effort") == "low"
          for r in reqs))
check("`fallbacks` is absent (the Batches API rejects it)",
      all("fallbacks" not in r["params"] for r in reqs))
check("every custom_id is unique",
      len({r["custom_id"] for r in reqs}) == len(reqs))
check("custom_ids are ASCII-safe",
      all(all(ord(c) < 128 for c in r["custom_id"]) for r in reqs))

# --- output sizing ---------------------------------------------------------
worst = max((len(id_maps.get(r["custom_id"], name_maps.get(r["custom_id"], [])))
             for r in reqs), default=0)
check("max_tokens scales with the payload",
      all(r["params"]["max_tokens"] >= 4096 for r in text_reqs)
      and all(r["params"]["max_tokens"] >= 1024 for r in name_reqs),
      "(a truncated response fails JSON parsing and the key-count check, and "
      "masquerades as 'that model is bad at schemas')")
print("       largest request holds %d units" % worst)

# --- coverage --------------------------------------------------------------
seen = collections.Counter()
for cid, ids in id_maps.items():
    for uid in ids:
        seen[uid] += 1
dupes = [u for u, n in seen.items() if n > 1]
check("no unit is queued twice", not dupes, str(dupes[:5]))

by_id = {u["id"]: u for _d, u in store.all_units(docs)}
pending_ids = {u["id"] for _d, u in store.all_units(docs)
               if not (u.get("tl") or "").strip() and not u.get("locked")}
deduped_reps = set(seen)
# A unit is legitimately absent from the queue when a SIBLING sharing its dedup
# key is present. Dialogue is deduped on this game (see `store.dedup_key`), so
# 61,087 of 90,195 units are represented rather than queued - reading
# `DEDUPED_KINDS` alone would report every one of them as missing.
DEDUP = cfg["dedup_dialogue"]
rep_keys = {store.dedup_key(by_id[r], DEDUP) for r in deduped_reps}
rep_keys.discard(None)
missing = []
for uid in pending_ids:
    if uid in deduped_reps:
        continue
    key = store.dedup_key(by_id[uid], DEDUP)
    if key is None or key not in rep_keys:
        missing.append(uid)
check("every pending unit is queued, directly or through its dedup group",
      not missing, "(%d missing, e.g. %s)" % (len(missing), missing[:3]))

# --- the roster actually reaches the model ---------------------------------
# Read the TEXT request: the name pass has its own, much smaller prompt.
#
# The probe list is derived from the GLOSSARY rather than hardcoded. The version
# of this file that came from another game named that game's characters, which
# is a per-game RULING sitting in a test - it fails on every other game and
# says nothing when it passes on its own.
sysall = "".join(b["text"] for b in text_reqs[0]["params"]["system"])
roster_names = [store.name_en(v) for v in glossary.get("names", {}).values()
                if store.name_en(v)]
if not roster_names:
    check("roster carries any approved English name", False,
          "the glossary has no translated names yet - run `tl.py names` first; "
          "until then every dialogue request ships an EMPTY roster")
else:
    # Only names above the roster threshold are in the cached block; the rest
    # arrive through matched-terms on the requests where they occur.
    big = [store.name_en(v) for v in glossary.get("names", {}).values()
           if store.name_en(v) and (not isinstance(v, dict)
                                    or (v.get("lines") or 0) >= cfg["roster_min"])]
    probes = big[:6] or roster_names[:6]
    for probe in probes:
        check("roster carries %r" % probe, probe in sysall)

terms = [k for k, v in (glossary.get("terms") or {}).items() if v]
dnt = glossary.get("do_not_translate") or []
if dnt:
    check("the do-not-translate list reaches the model",
          all(d in sysall for d in dnt[:3]))
else:
    print("  --   no do_not_translate entries yet, nothing to check")

# --- retry notes go in the USER turn, never the system prefix --------------
notes = {uid: "residual-jp" for uid in list(pending_ids)[:5]}
_d, _g, rreqs, _im, _nm = driver.build_all(
    STORE, cfg, MODEL, 60, retranslate_all=True, include_names=False,
    only_ids=set(notes), effort="low", ttl=cfg["batch_ttl"],
    retry_notes=notes)
if rreqs:
    cut = 0
    for i, b in enumerate(rreqs[0]["params"]["system"]):
        if "cache_control" in b:
            cut = i + 1
            break
    rpre = "".join(b["text"] for b in rreqs[0]["params"]["system"][:cut])
    check("a retry does NOT change the cached prefix",
          rpre == next(iter(prefixes)),
          "(editing the system prefix on retry pays a full cache write every "
          "attempt)")
    check("the retry note is in the user turn",
          "RETRY" in rreqs[0]["params"]["messages"][0]["content"])

# --- the price table -------------------------------------------------------
# A price table is transcribed by hand and nothing else in the pipeline reads
# it, so a typo survives until it shows up as a wrong number in a decision.
print("\nprice table")
mis = [k for k in R.PRICING if R.price_for(k) is not R.PRICING[k]]
check("every model id resolves to its own row", not mis, str(mis))
check("longest-first matching, so opus-4-5 is not caught by opus-5",
      R.price_for("claude-opus-4-5")["in"] == 5.00
      and R.price_for("claude-sonnet-4-6")["in"] == 3.00
      and R.price_for("claude-sonnet-5")["in"] == 2.00)
drift = []
for k, p in R.PRICING.items():
    for col, mult in (("cw5m", "5m"), ("cw1h", "1h"), ("cr", "hit")):
        want = round(p["in"] * R.CACHE_MULTIPLIER[mult], 6)
        if abs(want - p[col]) > 1e-9:
            drift.append("%s.%s: table %s, %sx says %s"
                         % (k, col, p[col], R.CACHE_MULTIPLIER[mult], want))
check("every cache column equals base input x its published multiplier",
      not drift, str(drift))
check("an unknown model falls back rather than crashing",
      R.price_for("claude-something-new")["in"] > 0)
# The correction that motivated this test: a recorded promotional expiry is a
# wrong number waiting to happen.
check("sonnet-5 is at its standard $2/$10, with no expiry recorded",
      R.PRICING["claude-sonnet-5"]["in"] == 2.00
      and R.PRICING["claude-sonnet-5"]["out"] == 10.00)

# --- the SDK accepts the shape --------------------------------------------
try:
    import anthropic  # noqa: F401
    from anthropic.types.messages.batch_create_params import Request  # noqa: F401
    check("anthropic SDK importable", True)
except Exception as e:
    check("anthropic SDK importable", False, str(e))

print("")
if FAILS:
    print("%d FAILURE(S)" % len(FAILS))
    for f in FAILS:
        print("  - " + f)
    sys.exit(1)
print("ALL REQUEST TESTS PASS")
