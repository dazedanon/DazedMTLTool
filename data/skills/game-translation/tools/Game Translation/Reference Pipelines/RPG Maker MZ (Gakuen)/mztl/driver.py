#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
driver.py - the two ways to spend money, sharing one request builder, one
parser and one apply path.

  batch   Message Batches API. 50% off every token class, including the cache
          multipliers. Submit / poll / fetch, resumable from `_batch_state.json`.
  live    Direct Messages API with a thread pool. Costs 2x, returns in minutes
          with visible per-request progress. Worth it for a small remainder,
          for a retry round, or for a batch that has sat queued for hours.

Both go through `requests.build_request`. A live path that built its own
requests would stop testing the batch path, and the two would drift until a
retry produced different output from the run it was repairing.

Things worth knowing before you watch a batch:

* `request_counts` is NOT a progress bar. A 113-request run sat at
  `processing=113, succeeded=0` for its entire 93-minute life and then flipped
  to 113 succeeded in one step - while the console usage graph showed the input
  being consumed within minutes. Do not tell anyone "nothing has been billed
  yet" because `succeeded` is 0, and never cancel a stalled-LOOKING batch to
  re-run it live without checking usage first: you would pay twice.
* Results arrive in ANY order. Key by `custom_id`, never by position.
* `fallbacks` is rejected on the Batches API.
"""

import os
import sys
import time
import json
import random
import threading
import concurrent.futures as futures

from . import store, requests as R, parse, client as C

POLL_DEFAULT = 60

# On a BATCH, caching can cost MORE than not caching, because a batch fans its
# requests out independently and most of them WRITE the prefix instead of
# reading it. The break-even hit rate is where the blend stops beating plain
# input:  (1 - f) * write_multiplier + f * 0.10 < 1.00
#     1h TTL, write 2.00x  ->  needs f > 53%
#     5m TTL, write 1.25x  ->  needs f > 22%
# A measured 411-request Sonnet 5 batch with a byte-stable prefix reached
# 30.9% - above 22%, nowhere near 53%. So 5m is the right default for a batch
# despite the "requests are processed minutes apart" reasoning, and the run
# reports its real hit rate at the end so the choice can be checked.
BATCH_TTL = "5m"


# --------------------------------------------------------------------------
def build_all(store_dir, cfg, model, max_units, retranslate_all=False,
              include_names=True, include_text=True, only_ids=None,
              effort="low", ttl="1h", retry_notes=None):
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    reqs, id_maps, name_maps = [], {}, {}

    if include_names:
        nreqs, name_maps = R.build_name_requests(
            glossary, model, store_dir, effort=effort, ttl=ttl,
            retranslate_all=retranslate_all)
        reqs.extend(nreqs)

    if include_text:
        for ch in R.build_chunks(docs, max_units, retranslate_all, only_ids):
            note = ""
            if retry_notes:
                bits = [retry_notes.get(u["id"]) for u in ch["units"]
                        if retry_notes.get(u["id"])]
                seen = []
                for b in bits:
                    for part in b.split(", "):
                        if part not in seen:
                            seen.append(part)
                if seen:
                    note = ("Fix these named failure modes: " + "; ".join(seen)
                            + ". Translate fully with no Japanese left, keep "
                            "every ⟦n⟧ sentinel exactly and in the same "
                            "relative position, emit no empty values and no "
                            "long runs of one character, and keep every number "
                            "the source has.")
            req, idmap = R.build_request(ch, model, store_dir, glossary,
                                         effort=effort, ttl=ttl,
                                         retry_note=note)
            reqs.append(req)
            id_maps[ch["custom_id"]] = idmap

    return docs, glossary, reqs, id_maps, name_maps


def _extract_text(message):
    return "".join(getattr(b, "text", "") or "" for b in message.content
                   if getattr(b, "type", "") == "text")


def _parse_message(message):
    raw = _extract_text(message)
    return parse.parse(parse.normalize_reply(raw))


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------
def submit(store_dir, cfg, model, max_units, retranslate_all=False,
           include_names=True, include_text=True, only_ids=None,
           effort="low", label="text", retry_notes=None):
    docs, glossary, reqs, id_maps, name_maps = build_all(
        store_dir, cfg, model, max_units, retranslate_all,
        include_names, include_text, only_ids, effort, ttl=BATCH_TTL,
        retry_notes=retry_notes)
    if not reqs:
        return None, 0
    cl = C.get_client()
    _guard_single_submission(store_dir)
    batch = cl.messages.batches.create(requests=reqs)
    store.save_state(store_dir, {
        "batch_id": batch.id, "model": model, "effort": effort,
        "phase": label, "n_requests": len(reqs),
        "id_maps": id_maps, "name_maps": name_maps,
        "created": str(getattr(batch, "created_at", "") or ""),
    })
    return batch.id, len(reqs)


_LOCK_NAME = "_submitting.lock"


def _guard_single_submission(store_dir):
    """Non-blocking cross-process guard. A second window submitting the same
    corpus is how you get billed twice for one game, so this fails loudly
    rather than queueing."""
    p = os.path.join(store_dir, _LOCK_NAME)
    if os.path.exists(p):
        age = time.time() - os.path.getmtime(p)
        if age < 3600:
            sys.exit("ERROR: another submission started %ds ago (%s).\n"
                     "  Delete that file if you are certain it is stale."
                     % (int(age), p))
    with open(p, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))


def _release_lock(store_dir):
    p = os.path.join(store_dir, _LOCK_NAME)
    if os.path.exists(p):
        os.unlink(p)


def status(store_dir):
    st = store.load_state(store_dir)
    if not st:
        return None
    cl = C.get_client()
    b = cl.messages.batches.retrieve(st["batch_id"])
    return b


def fetch(store_dir, verbose=True):
    st = store.load_state(store_dir)
    if not st:
        sys.exit("No batch state - run submit first.")
    cl = C.get_client()
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    usage = C.Usage()
    results, errored = {}, []
    for r in cl.messages.batches.results(st["batch_id"]):
        cid = r.custom_id
        res = r.result
        if res.type != "succeeded":
            err = getattr(res, "error", None)
            inner = getattr(err, "error", err) if err is not None else None
            errored.append((cid, "%s | %s: %s" % (
                res.type, getattr(inner, "type", ""),
                (getattr(inner, "message", "") or str(err))[:200])))
            continue
        usage.add(getattr(res.message, "usage", None))
        stop = getattr(res.message, "stop_reason", "")
        try:
            results[cid] = _parse_message(res.message)
        except Exception as e:
            errored.append((cid, "parse_error(%s, stop=%s): %s"
                            % (type(e).__name__, stop, e)))

    applied, names, errs = R.apply_results(docs, glossary, results,
                                           st.get("id_maps") or {},
                                           st.get("name_maps") or {})
    store.save_docs(docs)
    store.save_glossary(store_dir, glossary)
    _release_lock(store_dir)
    if verbose:
        print("Applied %d translations, %d names." % (applied, names))
        print(usage.report(st.get("model", R.MODEL_DEFAULT), batch=True))
        for cid, why in errored[:30]:
            print("  ! request %s: %s" % (cid, why))
        for e in errs[:20]:
            print("  ! " + e)
        if errored:
            print("  (results stay on the server for 29 days - fix the parser "
                  "and re-run `fetch`, no re-billing)")
    return applied, names, errored, errs


def poll_until_ended(store_dir, poll=POLL_DEFAULT, verbose=True):
    st = store.load_state(store_dir)
    if not st:
        sys.exit("No batch state.")
    cl = C.get_client()
    while True:
        b = cl.messages.batches.retrieve(st["batch_id"])
        if verbose:
            rc = getattr(b, "request_counts", None)
            print("  %s  %s  %s" % (time.strftime("%H:%M:%S"),
                                    b.processing_status, rc or ""), flush=True)
        if b.processing_status == "ended":
            return b
        time.sleep(poll)


# --------------------------------------------------------------------------
# live
# --------------------------------------------------------------------------
def live(store_dir, cfg, model, max_units, retranslate_all=False,
         include_names=True, include_text=True, only_ids=None,
         effort="low", workers=4, retry_notes=None, verbose=True):
    """Same requests, sent synchronously. 2x the price, minutes not hours.

    Concurrency and prompt caching fight on the first wave: fire N requests at
    once and all N WRITE the cache and none reads it. The first request is sent
    alone and awaited, then the rest fan out - one extra round trip buys the
    whole run its cache reads."""
    docs, glossary, reqs, id_maps, name_maps = build_all(
        store_dir, cfg, model, max_units, retranslate_all,
        include_names, include_text, only_ids, effort, ttl="5m",
        retry_notes=retry_notes)
    if not reqs:
        if verbose:
            print("Nothing to translate.")
        return 0, 0, []

    cl = C.get_client()
    usage = C.Usage()
    lock = threading.Lock()
    results = {}
    errored = []
    done = [0]

    def send(req):
        for attempt in range(5):
            try:
                msg = cl.messages.create(**req["params"])
                return req["custom_id"], msg, None
            except Exception as e:
                st = getattr(e, "status_code", None)
                if st in (400, 401, 403, 404, 422):
                    return req["custom_id"], None, "%s %s" % (st, e)
                ra = None
                resp = getattr(e, "response", None)
                if resp is not None:
                    try:
                        ra = float(resp.headers.get("retry-after"))
                    except (TypeError, ValueError):
                        ra = None
                delay = ra if ra else min(60, 2 ** attempt + random.random() * 2)
                if attempt == 4:
                    return req["custom_id"], None, "%s (gave up): %s" % (st, e)
                time.sleep(delay)
        return req["custom_id"], None, "unreachable"

    def record(cid, msg, err):
        with lock:
            done[0] += 1
            if err:
                errored.append((cid, err))
            else:
                usage.add(getattr(msg, "usage", None))
                try:
                    results[cid] = _parse_message(msg)
                except Exception as e:
                    errored.append((cid, "parse_error: %s" % e))
            if verbose:
                print("  [%d/%d] %s%s" % (done[0], len(reqs), cid,
                                          "  ERROR" if err else ""), flush=True)

    # Serial cache warm-up, then fan out.
    first = reqs[0]
    record(*send(first))
    if len(reqs) > 1:
        with futures.ThreadPoolExecutor(max_workers=workers) as ex:
            for cid, msg, err in ex.map(send, reqs[1:]):
                record(cid, msg, err)

    applied, names, errs = R.apply_results(docs, glossary, results,
                                           id_maps, name_maps)
    store.save_docs(docs)
    store.save_glossary(store_dir, glossary)
    if verbose:
        print("\nApplied %d translations, %d names." % (applied, names))
        print(usage.report(model, batch=False))
        for cid, why in errored[:30]:
            print("  ! %s: %s" % (cid, why))
        for e in errs[:20]:
            print("  ! " + e)
    return applied, names, errored


# --------------------------------------------------------------------------
def smoke(store_dir, cfg, model, max_units, effort="low", verbose=True):
    """One real request on a MEDIAN-sized chunk. Saves nothing.

    Not the smallest chunk: chunking always leaves one-unit requests at the
    tail, and a one-unit round trip exercises no ordering, no key-count check
    and no multi-line placeholder set. For a few cents this proves credentials,
    the model id, the sampling and effort params, both cache breakpoints, the
    JSON parser and the index-to-unit map before a 200-request run does not."""
    docs, glossary, reqs, id_maps, name_maps = build_all(
        store_dir, cfg, model, max_units, include_names=False, effort=effort,
        ttl="5m")
    text_reqs = [r for r in reqs if r["custom_id"] in id_maps]
    if not text_reqs:
        print("Nothing pending to smoke-test.")
        return 1
    text_reqs.sort(key=lambda r: len(id_maps[r["custom_id"]]))
    req = text_reqs[len(text_reqs) // 2]
    cid = req["custom_id"]
    ids = id_maps[cid]
    print("smoke: %s  (%d units, median of %d requests)"
          % (cid, len(ids), len(text_reqs)))
    cl = C.get_client()
    msg = cl.messages.create(**req["params"])
    usage = C.Usage()
    usage.add(getattr(msg, "usage", None))
    raw = _extract_text(msg)
    try:
        obj = parse.parse(parse.normalize_reply(raw))
    except Exception as e:
        print("PARSE FAILED: %s\n---\n%s\n---" % (e, raw[:1500]))
        return 1
    keys = sorted(int(k) for k in obj if str(k).isdigit())
    missing = [i for i in range(1, len(ids) + 1) if i not in keys]
    print("  stop_reason: %s" % getattr(msg, "stop_reason", "?"))
    print("  keys returned: %d / %d   missing: %s"
          % (len(keys), len(ids), missing[:10] or "none"))
    print(usage.report(model, batch=False))
    by_id = {u["id"]: u for _d, u in store.all_units(docs)}
    shown = 0
    for k in keys[:8]:
        u = by_id.get(ids[k - 1])
        if u is None:
            continue
        print("   %-28s %s" % ("[" + u["kind"] + "]", u["src"][:70]))
        print("   %-28s %s" % ("", str(obj[str(k)])[:70]))
        shown += 1
    return 0 if not missing else 1
