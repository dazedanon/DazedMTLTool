#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
driver.py - the two ways to spend money, sharing one request builder, one
parser and one apply path.

  batch   Message Batches API. 50% off every token class, including the cache
          multipliers. Submit / poll / fetch, resumable from `_batch_state.json`.
  live    Direct Messages API with a thread pool. Costs 2x, returns in minutes
          with visible per-request progress. Worth it for a small remainder,
          for a retry round, or for a batch that has sat queued for hours.

Things worth knowing before you watch a batch:

* `request_counts` is NOT a progress bar. A run can sit at
  `processing=N, succeeded=0` for its whole life and then flip in one step,
  while the usage graph shows the input already consumed. Never say "nothing
  has been billed yet" because `succeeded` is 0, and never cancel a
  stalled-LOOKING batch to re-run it live without checking usage first: you
  would pay twice.
* Results arrive in ANY order. Key by `custom_id`, never by position.
* Results stay on the server for 29 days, so a parse failure is fixable and
  re-fetchable with no re-billing.
"""

import os
import sys
import time
import random
import threading
import concurrent.futures as futures

from . import store, requests as R, parse, client as C

POLL_DEFAULT = 60


# --------------------------------------------------------------------------
def build_all(store_dir, cfg, model, max_units, retranslate_all=False,
              include_names=True, include_text=True, only_ids=None,
              effort="low", ttl="1h", retry_notes=None, roster_min=0):
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
                seen = []
                for u in ch["units"]:
                    for part in (retry_notes.get(u["id"]) or "").split(", "):
                        if part and part not in seen:
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
                                         retry_note=note, roster_min=roster_min)
            reqs.append(req)
            id_maps[ch["custom_id"]] = idmap

    return docs, glossary, reqs, id_maps, name_maps


def _extract_text(message):
    return "".join(getattr(b, "text", "") or "" for b in message.content
                   if getattr(b, "type", "") == "text")


def _parse_message(message):
    # The RAW text: `parse.parse` folds curly quotes itself, and only for a
    # candidate that has already failed to parse. Folding first destroys a
    # reply that was valid JSON with a quoted word inside a value.
    return parse.parse(_extract_text(message))


# --------------------------------------------------------------------------
# batch
# --------------------------------------------------------------------------
def warm_cache(reqs, verbose=True):
    """Send ONE request live so the cached prefix exists before the batch runs.

    MEASURED, on this game's first real run: 411 batch requests sharing one
    byte-identical 8.8k-token prefix produced 2,492,100 cache-WRITE tokens and
    only 1,114,425 reads - a 30.9% hit rate. The Batch API starts the requests
    concurrently, so almost all of them arrive before any of them has finished
    writing the cache, and each one pays the 1h write multiplier (2x base
    input) instead of the read rate (0.1x).

    The arithmetic is worth knowing: a 1h cache write only pays for itself
    above a 53% hit rate ((1-f)*2 + f*0.1 < 1); a 5m write above 22%. At 30.9%
    the caching COST $1.49 more than sending everything uncached would have.

    This warm-up is UNVERIFIED and deliberately cheap. The skill's
    `llm-pipeline.md` records that a live prewarm did NOT reliably transfer to
    a batch on an earlier game, and the run that produced the numbers above
    finished before this existed. It costs about two cents and cannot make
    anything worse; the hit rate in the `fetch` report is what says whether it
    worked. If it did not, drop the TTL to 5m - break-even 22% is a rate a
    batch actually reaches, and 53% is not."""
    if not reqs:
        return
    cl = C.get_client()
    try:
        msg = cl.messages.create(**reqs[0]["params"])
        u = C.Usage()
        u.add(getattr(msg, "usage", None))
        if verbose:
            print("  cache warm-up: wrote %d token(s) of prefix in one live "
                  "request; the batch should now READ it" % u.cache_write)
    except Exception as e:                    # never block a run on the warm-up
        if verbose:
            print("  cache warm-up failed (%s) - continuing; expect a lower "
                  "hit rate" % e)


def submit(store_dir, cfg, model, max_units, retranslate_all=False,
           include_names=True, include_text=True, only_ids=None,
           effort="low", label="text", retry_notes=None, roster_min=0,
           warm=True):
    docs, glossary, reqs, id_maps, name_maps = build_all(
        store_dir, cfg, model, max_units, retranslate_all, include_names,
        include_text, only_ids, effort, ttl="1h", retry_notes=retry_notes,
        roster_min=roster_min)
    if not reqs:
        return None, 0
    cl = C.get_client()
    _guard_single_submission(store_dir)
    if warm and len(reqs) > 8:
        warm_cache(reqs)
    batch = cl.messages.batches.create(requests=reqs)
    store.save_state(store_dir, {
        "batch_id": batch.id, "model": model, "effort": effort,
        "phase": label, "n_requests": len(reqs),
        "id_maps": id_maps, "name_maps": name_maps,
        "created": str(getattr(batch, "created_at", "") or ""),
    })
    return batch.id, len(reqs)


_LOCK_NAME = "_submitting.lock"


LOCK_TTL = 26 * 3600


def _guard_single_submission(store_dir):
    """Non-blocking cross-process guard. A second window submitting the same
    corpus is how you get billed twice for one game, so this fails loudly
    rather than queueing.

    The TTL is longer than a day on purpose: a batch is allowed to take up to
    24 hours, and `fetch` is what releases the lock. An hour-long TTL expires
    while the first run is still legitimately queued, which turns the guard
    into a green light for exactly the double submission it exists to stop."""
    p = os.path.join(store_dir, _LOCK_NAME)
    if os.path.exists(p):
        age = time.time() - os.path.getmtime(p)
        if age < LOCK_TTL:
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
    return C.get_client().messages.batches.retrieve(st["batch_id"])


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
                  "and re-run `fetch`, with no re-billing)")
    return applied, names, errored, errs


def poll_until_ended(store_dir, poll=POLL_DEFAULT, verbose=True):
    st = store.load_state(store_dir)
    if not st:
        sys.exit("No batch state.")
    cl = C.get_client()
    while True:
        b = cl.messages.batches.retrieve(st["batch_id"])
        if verbose:
            print("  %s  %s  %s" % (time.strftime("%H:%M:%S"),
                                    b.processing_status,
                                    getattr(b, "request_counts", "") or ""),
                  flush=True)
        if b.processing_status == "ended":
            return b
        time.sleep(poll)


# --------------------------------------------------------------------------
# live
# --------------------------------------------------------------------------
def live(store_dir, cfg, model, max_units, retranslate_all=False,
         include_names=True, include_text=True, only_ids=None,
         effort="low", workers=4, retry_notes=None, verbose=True,
         roster_min=0):
    """Same requests, sent synchronously. 2x the price, minutes not hours.

    TWO PHASES, like `run`. Names are translated and written into the glossary
    BEFORE the text requests are built, because the roster is part of the
    cached system prefix: building both in one pass sends every dialogue
    request a roster that is still empty, and the names it locks in arrive too
    late to be used by anything.

    Concurrency and prompt caching also fight on the first wave: fire N
    requests at once and all N WRITE the cache while none reads it. The first
    request is sent alone and awaited, then the rest fan out - one extra round
    trip buys the whole run its cache reads."""
    total_applied = total_names = 0
    all_errors = []

    if include_names:
        docs, glossary, nreqs, _im, name_maps = build_all(
            store_dir, cfg, model, max_units, retranslate_all,
            include_names=True, include_text=False, effort=effort, ttl="5m")
        if nreqs:
            if verbose:
                print("[names] %d request(s)" % len(nreqs))
            res, errs, usage = _send_all(nreqs, workers, verbose)
            applied, names, aerrs = R.apply_results(docs, glossary, res, {},
                                                    name_maps)
            store.save_docs(docs)
            store.save_glossary(store_dir, glossary)
            total_applied += applied
            total_names += names
            all_errors += errs + [("apply", e) for e in aerrs]
            if verbose:
                print("  %d name(s) written into the glossary" % names)
                print(usage.report(model, batch=False, ttl="5m"))

    if not include_text:
        return total_applied, total_names, all_errors

    docs, glossary, reqs, id_maps, _nm = build_all(
        store_dir, cfg, model, max_units, retranslate_all,
        include_names=False, include_text=True, only_ids=only_ids,
        effort=effort, ttl="5m", retry_notes=retry_notes,
        roster_min=roster_min)
    if not reqs:
        if verbose:
            print("Nothing to translate.")
        return total_applied, total_names, all_errors

    results, errored, usage = _send_all(reqs, workers, verbose,
                                        on_partial=lambda part: _apply_and_save(
                                            store_dir, docs, glossary, part,
                                            id_maps))
    applied, names, errs = R.apply_results(docs, glossary, results, id_maps, {})
    store.save_docs(docs)
    store.save_glossary(store_dir, glossary)
    total_applied += applied
    total_names += names
    all_errors += errored
    if verbose:
        print("\nApplied %d translations, %d names." % (total_applied, total_names))
        print(usage.report(model, batch=False, ttl="5m"))
        for cid, why in all_errors[:30]:
            print("  ! %s: %s" % (cid, why))
        for e in errs[:20]:
            print("  ! " + e)
    return total_applied, total_names, all_errors


def _apply_and_save(store_dir, docs, glossary, results, id_maps):
    """Flush what has arrived so far.

    A live fan-out that only saves at the end loses every completed request to
    one Ctrl-C - money already spent, thrown away. Applying is idempotent per
    unit, so a partial flush costs nothing and the final apply repeats it
    harmlessly."""
    R.apply_results(docs, glossary, results, id_maps, {})
    store.save_docs(docs)
    store.save_glossary(store_dir, glossary)


def _send_all(reqs, workers, verbose, on_partial=None, flush_every=25):
    """Send a list of built requests. Returns (results, errored, usage).

    Never raises out of the fan-out: whatever arrived is returned, so an
    interrupt keeps the work that was paid for."""
    cl = C.get_client()
    usage = C.Usage()
    lock = threading.Lock()
    results = {}
    errored = []
    done = [0]
    flushed = [0]

    def send(req):
        for attempt in range(5):
            try:
                return req["custom_id"], cl.messages.create(**req["params"]), None
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
                if attempt == 4:
                    return req["custom_id"], None, "%s (gave up): %s" % (st, e)
                time.sleep(ra if ra else min(60, 2 ** attempt + random.random() * 2))
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
            if on_partial and len(results) - flushed[0] >= flush_every:
                flushed[0] = len(results)
                try:
                    on_partial(dict(results))
                except Exception as e:            # a flush must never kill a run
                    print("  ! partial save failed: %s" % e, flush=True)

    try:
        record(*send(reqs[0]))
        if len(reqs) > 1:
            with futures.ThreadPoolExecutor(max_workers=workers) as ex:
                for cid, msg, err in ex.map(send, reqs[1:]):
                    record(cid, msg, err)
    except KeyboardInterrupt:
        print("\ninterrupted - keeping the %d request(s) that finished"
              % len(results), flush=True)
    finally:
        if on_partial and results:
            try:
                on_partial(dict(results))
            except Exception as e:
                print("  ! final partial save failed: %s" % e, flush=True)
    return results, errored, usage


# --------------------------------------------------------------------------
def smoke(store_dir, cfg, model, max_units, effort="low", verbose=True):
    """One real request on a MEDIAN-sized chunk. Saves nothing.

    Not the smallest chunk: chunking always leaves one-unit requests at the
    tail, and a one-unit round trip exercises no ordering, no key-count check
    and no multi-line placeholder set. For a few cents this proves the
    credentials, the model id, the sampling and effort params, both cache
    breakpoints, the JSON parser and the index-to-unit map before a
    200-request run does not."""
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
    msg = C.get_client().messages.create(**req["params"])
    usage = C.Usage()
    usage.add(getattr(msg, "usage", None))
    raw = _extract_text(msg)
    try:
        obj = parse.parse(raw)
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
    for k in keys[:8]:
        u = by_id.get(ids[k - 1])
        if u is None:
            continue
        print("   %-14s %s" % ("[" + u["kind"] + "]", u["src"][:78]))
        print("   %-14s %s" % ("", str(obj[str(k)])[:78]))
    return 0 if not missing else 1
