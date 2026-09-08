#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
extract.py - turn `BakinTL export`'s units.jsonl into the translation store.

The C# side is deliberately dumb: it walks the catalog with the engine's own
parser and emits every whitelisted field as `{key, kind, owner, ctx, order,
file, src}`. Everything that needs judgement happens here, where it is testable
without a .NET runtime:

  * peel `\NPL[speaker]` off a dialogue line into its own field, so the model
    is told who is talking rather than handed an opaque sentinel;
  * mask the remaining control codes to `⟦n⟧`;
  * lift a code whose BRACKET holds display text (`\r[ruby]`,
    `\currentskillconsumptionhp[消費HP : {0} ]`) out as its own unit, because
    masking it opaquely would ship the Japanese inside it;
  * shard into docs so a scene stays whole and the store stays diffable.

Two rules the shapes exist to enforce:

  * `raw` is write-once and is the re-run source of truth. Feeding `tl` back to
    the model on a second pass destroys honorifics and codes with no
    recoverable original. The SKIP decision reads `tl`; the model INPUT reads
    `src`.
  * A re-extraction that finds materially less than the store already holds is
    a MISTAKE, not an update, and is refused. After an in-place inject the
    catalog is the English build, so a naive re-run finds no Japanese, yields
    zero units, and saves those empty docs over 90,000 finished translations.
"""

import collections
import json
import os
import re
import sys

from . import codes, store

# Docs are sharded by owner so one scene never straddles two of them - the
# chunker packs scenes in play order WITHIN a doc and breaks on doc boundaries.
# 1,487 owners would be 1,487 files; grouping by owner prefix and capping the
# unit count keeps it to a few hundred while preserving order.
DOC_MAX_UNITS = 1200

_SAFE = re.compile(r"[^0-9A-Za-z_.\-]")


def _shard_name(owner):
    kind, _, rest = owner.partition(":")
    rest = rest.split(" / ")[0]
    return "%s__%s" % (kind, _SAFE.sub("_", rest)[:48] or "x")


def build_units(work_units_path, keywords_path=None):
    """Read the export and return {doc_stem: [unit, ...]} in play order."""
    if keywords_path and os.path.exists(keywords_path):
        codes.load_keywords(keywords_path)

    raw = []
    with open(work_units_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                raw.append(json.loads(line))
    raw.sort(key=lambda u: (u["order"], u["key"]))

    docs = collections.OrderedDict()
    counters = collections.Counter()
    for r in raw:
        for u in _units_for(r, counters):
            stem = _shard_name(r["owner"])
            n = counters["doc:" + stem]
            part = n // DOC_MAX_UNITS
            counters["doc:" + stem] = n + 1
            key = "%s.%02d" % (stem, part)
            docs.setdefault(key, []).append(u)
    return docs


def _units_for(r, counters):
    """One export row becomes one unit, plus one per display-text code arg."""
    kind = r["kind"]
    src_raw = r["src"]

    speaker, body, plate = "", src_raw, ""
    if kind == "text":
        speaker, body, plate = codes.split_speaker(src_raw)
    # Ruby resolves to its base spelling and is NOT restored - see
    # `codes.resolve_ruby`. Recorded on the unit so the count is auditable.
    body, n_ruby = codes.resolve_ruby(body)

    out = []
    # A code whose bracket is display text gets its own unit, and the code in
    # the parent is masked as usual. Translating it inside the parent line
    # would let the model rewrite the code name itself.
    extra = []
    for whole, name, arg in codes.display_args(body):
        if not codes.has_jp(arg):
            continue
        counters["arg"] += 1
        aid = "%s@%s" % (r["key"], name)
        extra.append({
            "id": aid,
            "key": r["key"],
            "sub": name,
            "kind": "codearg",
            "owner": r["owner"],
            "ctx": r["ctx"] + " / " + whole,
            "order": r["order"] + "|arg",
            "file": r["file"],
            "speaker": "",
            "plate": "",
            "codes": {},
            "raw": arg,
            "src": codes.clean_source(arg),
            "tl": "",
        })

    cleaned = codes.clean_source(body)
    masked, code_map = codes.mask_codes(cleaned)
    unit = {
        "id": r["key"],
        "key": r["key"],
        "kind": kind,
        "owner": r["owner"],
        "ctx": r["ctx"],
        "order": r["order"],
        "file": r["file"],
        "speaker": speaker,
        "plate": plate,
        "codes": code_map,
        "raw": src_raw,          # byte-exact, write-once, the re-run source
        "src": masked,           # the ONLY thing the model sees
        "tl": "",
    }
    if n_ruby:
        unit["ruby_dropped"] = n_ruby

    # A unit whose visible body holds NO Japanese - a silent beat
    # (`………………`), a rule (`────────`), a run of sentinels, an empty body once
    # the nameplate came off. There is nothing to translate, but the unit is
    # NOT inert: it still carries a `\NPL[speaker]` nameplate that has to be
    # rewritten in English.
    #
    # Measured here: 1,426 `text` units, 178 distinct dedup keys. Leaving them
    # merely untranslated is the trap - the model would return either the
    # source (caught as `identical`) or a lone ellipsis (caught as
    # `degenerate`), `build_pairs` would skip the unit either way, and the rom
    # would keep `\NPL[アルテシア]………………` in the middle of an English scene.
    #
    # So pre-fill with the source, LOCK it so it is never queued or validated,
    # and waive the `identical` flag with its reason. `inject.render` still
    # rebuilds the nameplate from `speaker_en`, which is the whole point.
    if not codes.has_jp(masked):
        unit["tl"] = masked
        unit["locked"] = True
        unit["waive"] = {"identical": (
            "the visible body carries no Japanese (a silent beat, a rule, or "
            "sentinels only); it is pre-filled so injection still rewrites its "
            "nameplate in English")}
    out.append(unit)
    out.extend(extra)
    return out


# --------------------------------------------------------------------------
def speakers(docs):
    """{jp_speaker: line_count} across the store, for the names pass."""
    c = collections.Counter()
    for _p, doc in docs:
        for u in doc["units"]:
            if u.get("speaker"):
                c[u["speaker"]] += 1
    return c


def seed_glossary(store_dir, docs, verbose=True):
    """Put every nameplate speaker into the glossary, untranslated.

    This is what makes the names pass possible at all: the roster has to exist
    before dialogue runs, or prose names drift away from the name box. The
    count travels as a human-facing `note` and is NOT sent to the model."""
    g = store.load_glossary(store_dir)
    counts = speakers(docs)
    added = 0
    for jp, n in counts.most_common():
        if jp in g["names"]:
            cur = g["names"][jp]
            if isinstance(cur, dict):
                cur["lines"] = n
            continue
        g["names"][jp] = {"en": "", "gender": "", "role": "", "register": "",
                          "aliases": [], "lines": n,
                          "note": "auto-seeded from %d nameplate lines" % n}
        added += 1
    g["meta"].setdefault("game", "執聖官アルテシア (Artesia) Ver1.06")
    g["meta"]["source"] = ("speakers harvested from the engine's own "
                           "\\NPL[..] nameplate code - exact, not heuristic")
    store.save_glossary(store_dir, g)
    if verbose:
        print("glossary: %d speakers total, %d newly seeded" % (len(counts), added))
    return added


# --------------------------------------------------------------------------
def run(cfg, verbose=True):
    """Extract into the store, merging any translations already present."""
    work = os.path.join(cfg["work_dir"], "units.jsonl")
    if not os.path.exists(work):
        raise SystemExit("no %s - run `tl.py export` first" % work)
    store_dir = cfg["store_dir"]

    fresh = build_units(work, cfg.get("keywords"))
    n_new = sum(len(v) for v in fresh.values())

    old = {os.path.splitext(os.path.basename(p))[0]: doc
           for p, doc in store.load_docs(store_dir)}
    n_old = sum(len(d["units"]) for d in old.values())
    n_tl = sum(1 for d in old.values() for u in d["units"] if (u.get("tl") or "").strip())

    # A re-extraction that finds materially less than the store already holds
    # is the in-place-inject accident, and it is unrecoverable if it saves.
    if n_old and n_new < n_old * 0.9:
        raise SystemExit(
            "REFUSING to save: fresh extraction has %d units against %d in the "
            "store (%d already translated).\nThe usual cause is extracting from "
            "an ALREADY-INJECTED project folder, which contains no Japanese.\n"
            "Point proj_dir at the pristine descrambled tree, or delete the "
            "store deliberately if this really is a smaller game."
            % (n_new, n_old, n_tl))

    kept = 0
    for stem, units in fresh.items():
        prev = old.get(stem)
        if prev:
            kept += store.merge_translations(prev["units"], units)
        store.save_doc(store_dir, stem + ".json", units,
                       meta={"engine": "bakin", "build": "r64268"})

    # Docs the fresh extraction no longer produces are stale, not deletable:
    # leave them and say so, so a game update never silently drops work.
    stale = [s for s in old if s not in fresh]
    if verbose:
        print("units %d in %d docs, carried over %d existing translations"
              % (n_new, len(fresh), kept))
        if stale:
            print("stale docs left in place (not in this extraction): %s"
                  % ", ".join(sorted(stale)[:8]))
    docs = store.load_docs(store_dir)
    seed_glossary(store_dir, docs, verbose)
    return n_new


if __name__ == "__main__":
    from . import config
    sys.exit(0 if run(config.load()) else 1)
