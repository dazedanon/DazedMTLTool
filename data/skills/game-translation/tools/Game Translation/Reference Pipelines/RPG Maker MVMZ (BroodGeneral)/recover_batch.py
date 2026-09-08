#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
recover_batch.py — one-off recovery of translations that were lost when the store
was accidentally re-extracted from the already-ENGLISH data/ dir.

The data/ game and the JP backup are intact; re-extracting from the JP backup
restored every unit's JP source and recovered ~91% of translations by id-merge,
but ~1,500 units came back empty. Their EXACT translations still live in the
completed Anthropic batches on the server, so we fetch and re-apply them for free
instead of paying to re-translate.

Strategy: the main-run TEXT batch's id_maps were overwritten, but the chunking is
deterministic. We rebuild the chunks from the current store EXACTLY as the main run
did (force-all, SAME max_units, EXCLUDING the newly-added label/scripttext units,
which didn't exist at main-run time) — reproducing identical custom_ids and
ordered unit-id lists. We then fetch the batch results and apply each translation
by unit-id, filling ONLY currently-empty units so recovered (final, post-retry)
translations are never clobbered.

Usage:
  python tooling/recover_batch.py check                 # verify reconstruction (no writes)
  python tooling/recover_batch.py apply <batch_id> ...  # fetch + fill empties
"""
import os, sys, json, copy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rpgmvtl import store, batch as B

STORE = os.path.join(HERE, "tl")
MAIN_MAX_UNITS = 80                      # the default the main run used
EXCLUDE_KINDS = ("label", "scripttext")  # added AFTER the main run -> not in its chunks


def _load_docs_filtered():
    """Load store docs but hide label/scripttext units, so build_text_chunks
    reproduces the main run's unit set/order exactly."""
    docs = store.load_docs(STORE)
    filt = []
    for path, doc in docs:
        d = dict(doc)
        d["units"] = [u for u in doc["units"] if u["kind"] not in EXCLUDE_KINDS]
        filt.append((path, d))
    return filt


def reconstruct_id_maps():
    docs = _load_docs_filtered()
    chunks = B.build_text_chunks(docs, MAIN_MAX_UNITS, retranslate_all=True)
    id_maps = {}
    for ch in chunks:
        _txt, idmap = B.build_user_text(ch)
        id_maps[ch["custom_id"]] = idmap
    return id_maps


def cmd_check():
    id_maps = reconstruct_id_maps()
    n_units = sum(len(v) for v in id_maps.values())
    print(f"reconstructed chunks: {len(id_maps)}")
    print(f"units covered:        {n_units}")
    print("sample custom_ids:    " + ", ".join(list(id_maps)[:6]))
    # how many store units are currently empty (the recovery target)?
    docs = store.load_docs(STORE)
    empty = sum(1 for _p, d in docs for u in d["units"]
                if u["kind"] not in EXCLUDE_KINDS and not u.get("tl", "").strip())
    print(f"currently-empty text/data units (recovery target): {empty}")


def _fetch_results(client, batch_id):
    """Return {custom_id: parsed_json_obj} for a completed batch. Bad/malformed
    JSON chunks are skipped (logged) rather than aborting the whole recovery."""
    out, bad = {}, []
    for r in client.messages.batches.results(batch_id):
        if r.result.type != "succeeded":
            continue
        msg = r.result.message
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            obj = B.parse_json_object(text)
        except Exception:
            obj = None
        if obj is not None:
            out[r.custom_id] = obj
        else:
            bad.append(r.custom_id)
    if bad:
        print(f"  ! {len(bad)} chunk(s) had unparseable JSON (left empty -> retry later): "
              + ", ".join(bad))
    return out


def cmd_apply(batch_ids):
    client = B.get_client()
    docs = store.load_docs(STORE)
    glossary = store.load_glossary(STORE)
    unit_by_id = {u["id"]: u for _p, d in docs for u in d["units"]}

    recon = reconstruct_id_maps()
    # retry2 id_maps (different chunking) survive in _batch_state.json
    state = {}
    sp = os.path.join(STORE, "_batch_state.json")
    if os.path.exists(sp):
        state = json.load(open(sp, encoding="utf-8"))
    state_maps = state.get("id_maps", {})

    filled = skipped = overwrites = 0
    for bid in batch_ids:
        results = _fetch_results(client, bid)
        print(f"\n{bid}: {len(results)} succeeded chunks fetched")
        for cid, obj in results.items():
            idmap = recon.get(cid) or state_maps.get(cid)
            if not idmap:
                print(f"  ! no id_map for chunk {cid} (skipped {len(obj)} translations)")
                skipped += len(obj)
                continue
            for k, v in obj.items():
                try:
                    idx = int(k)
                except ValueError:
                    continue
                if not (1 <= idx <= len(idmap) and isinstance(v, str)):
                    continue
                u = unit_by_id.get(idmap[idx - 1])
                if u is None:
                    continue
                if u.get("tl", "").strip():
                    continue                 # keep the recovered (final) translation
                u["tl"] = v
                filled += 1
    store.save_docs(docs)
    print(f"\nfilled {filled} empty units | skipped {skipped} (no map)")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("check", "apply"):
        print(__doc__); raise SystemExit(2)
    if sys.argv[1] == "check":
        cmd_check()
    else:
        ids = sys.argv[2:]
        if not ids:
            print("give at least one batch id"); raise SystemExit(2)
        cmd_apply(ids)
