#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
requests.py - chunking and request construction, shared by the batch and live
drivers.

Both drivers MUST build requests through this module. A live path that builds
its own requests stops testing the batch path, and the two drift silently until
a retry produces different output from the run it is repairing.

Chunking rules, from measured runs:

* Dialogue is scene-aligned but NOT one request per scene. This game has 3,600+
  message boxes in runs of one or two lines, and one request per event page
  would mean thousands of requests where the per-request overhead dwarfs the
  payload. Scenes are packed in play order up to the unit budget and broken
  only on FILE boundaries.
* A scene bigger than the budget is split, and the split parts carry the
  previous lines as do-not-translate CONTEXT - the SOURCE lines, never the
  English produced a moment ago, which is how one bad rendering compounds down
  a whole file.
* Everything that is not dialogue is deduped globally by (kind, src) before it
  is queued, and one translation fans out to every unit sharing the pair.
* Chunk sizes stay uniform, because every distinct chunk size can be a separate
  cached prefix and ragged sizes pay a full-price cache write each.
"""

import os
import re

from . import store, prompts

MODEL_DEFAULT = "claude-sonnet-5"

# Transcribed from the live pricing page, first-party API, USD per MTok. All
# five published columns, not just input and output, because an estimate that
# guesses the cache columns is wrong by the multiplier it guessed.
#
#   5m cache write = 1.25x base input
#   1h cache write = 2.00x base input
#   cache hit      = 0.10x base input
#
# The batch rate is these halved at spend time (see `client.Usage.cost`), never
# typed twice: the multipliers stack with the Batch API discount, so cache
# writes and reads halve as well.
PRICING = {
    "claude-fable-5":    {"in": 10.00, "out": 50.00, "cw5m": 12.50, "cw1h": 20.00, "cr": 1.00},
    "claude-opus-5":     {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-opus-4-8":   {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-sonnet-5":   {"in": 2.00, "out": 10.00, "cw5m": 2.50, "cw1h": 4.00, "cr": 0.20},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cw5m": 3.75, "cw1h": 6.00, "cr": 0.30},
    "claude-sonnet-4-5": {"in": 3.00, "out": 15.00, "cw5m": 3.75, "cw1h": 6.00, "cr": 0.30},
    "claude-haiku-4-5":  {"in": 1.00, "out": 5.00, "cw5m": 1.25, "cw1h": 2.00, "cr": 0.10},
}

CACHE_MULTIPLIER = {"5m": 1.25, "1h": 2.00, "hit": 0.10}
BATCH_DISCOUNT = 0.5
# `inference_geo: "us"` bills 1.1x on EVERY token category on 4.6-and-later;
# the default "global" is standard price. This pipeline never sets it, so the
# factor is 1.0 - it is recorded so an estimate stays honest if someone pins
# the geography later. Fast mode ($10/$50, Opus only) is not available with
# the Batch API at all.
INFERENCE_GEO_MULTIPLIER = {"global": 1.0, "us": 1.1}

# Models that reject temperature / top_p / top_k with a hard 400. The cut is
# between 4.6 and 4.7 and is not a numeric comparison, so it is a list.
NO_SAMPLING = {
    "claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-opus-4-8",
    "claude-opus-4-7",
}

NEW_TOKENIZER = {
    "claude-fable-5", "claude-opus-5", "claude-opus-4-8", "claude-opus-4-7",
    "claude-sonnet-5",
}


def price_for(model, warn=True):
    """The rate card for a model id, matched longest-key-first.

    An unknown id falls back to the DEFAULT model's row, which is the cheapest
    first-party tier - so an estimate for a model this table has never heard of
    comes out low, in the direction nobody re-checks. It says so out loud."""
    m = (model or "").lower()
    for key in sorted(PRICING, key=len, reverse=True):     # longest first
        if key in m:
            return PRICING[key]
    if warn and m and m not in _WARNED:
        _WARNED.add(m)
        import sys
        print("  !! no pricing row for %r - quoting %s rates, which may be far "
              "too low. Add the row before trusting any number below."
              % (model, MODEL_DEFAULT), file=sys.stderr)
    return PRICING[MODEL_DEFAULT]


_WARNED = set()


def sampling_params(model):
    """Matched by SUBSTRING, like `price_for`.

    An exact-set test fails open on any dated or suffixed id
    (`claude-sonnet-5-20260114`), and the failure is a hard 400 on every
    request in the run - after the batch has been created."""
    m = (model or "").lower()
    if any(key in m for key in NO_SAMPLING):
        return {}
    return {"temperature": 0}


def output_config(effort):
    """`effort` lives inside `output_config`, and the API default is `high` -
    a model left at the default spends as many thinking tokens as it likes.
    Translation is direct high-volume work, so `low` is this pipeline's
    default. Adaptive thinking stays on: disabling it outright is accepted only
    at effort high or below and introduces its own failure modes."""
    cfg = {"thinking": {"type": "adaptive"}}
    if effort and effort != "high":
        cfg["output_config"] = {"effort": effort}
    return cfg


# --------------------------------------------------------------------------
# chunking
# --------------------------------------------------------------------------
_SCENE_RE = re.compile(r":c\d+.*$")


def scene_key(uid):
    """Everything before the command index groups one event page together."""
    return _SCENE_RE.sub("", uid)


def pending(docs, retranslate_all=False, only_ids=None):
    for _p, doc in docs:
        for u in doc["units"]:
            # `locked` means a human or a stock-English table owns this
            # translation. It wins over EVERY selector, `only_ids` included -
            # otherwise `retry` and `tighten`, which build their id set from a
            # validator that does not know about locking, would re-request and
            # overwrite a seeded UI string.
            if u.get("locked"):
                continue
            if only_ids is not None:
                if u["id"] in only_ids:
                    yield doc, u
                continue
            if retranslate_all or not (u.get("tl") or "").strip():
                yield doc, u


def build_chunks(docs, max_units, retranslate_all=False, only_ids=None,
                 context_lines=3):
    """Scene-aligned dialogue chunks per file, plus pooled non-dialogue chunks.

    Dedup for the non-dialogue kinds is GLOBAL, not per file: `はい` occurs 56
    times across a dozen maps, and paying for it once per file is paying for it
    a dozen times. Dialogue is never deduped - the model needs a coherent run
    with speakers, and one 「わかった」 that is "I'll tell her" in the scene it
    was translated in is wrong everywhere else the engine reuses it."""
    chunks = []
    dialogue_by_doc = {}
    shared = []
    seen_keys = set()

    for doc, u in pending(docs, retranslate_all, only_ids):
        if u["kind"] in store.DEDUPED_KINDS:
            key = (u["kind"], u["src"])
            if key in seen_keys:
                continue
            seen_keys.add(key)
            shared.append(u)
        else:
            dialogue_by_doc.setdefault(id(doc), (doc, []))[1].append(u)

    for _k, (doc, units) in dialogue_by_doc.items():
        stem = os.path.splitext(os.path.basename(doc["meta"]["source_file"]))[0]
        scenes, cur = [], None
        for u in units:
            k = scene_key(u["id"])
            if k != cur:
                scenes.append([])
                cur = k
            scenes[-1].append(u)

        part = [0]
        buf = []

        def emit(sub, ctx=None, _stem=stem, _part=part):
            chunks.append({
                "custom_id": store.sanitize_id("%s__%03d" % (_stem, _part[0])),
                "units": sub, "stem": _stem, "context": ctx or [],
            })
            _part[0] += 1

        for sc in scenes:
            if len(sc) > max_units:
                if buf:
                    emit(list(buf))
                    buf = []
                for s in range(0, len(sc), max_units):
                    ctx = sc[max(0, s - context_lines):s] if s else []
                    emit(sc[s:s + max_units], ctx)
            else:
                if buf and len(buf) + len(sc) > max_units:
                    emit(list(buf))
                    buf = []
                buf.extend(sc)
        if buf:
            emit(list(buf))

    shared.sort(key=lambda u: (u["kind"], u["id"]))
    for i, s in enumerate(range(0, len(shared), max_units)):
        chunks.append({
            "custom_id": store.sanitize_id("_shared__%03d" % i),
            "units": shared[s:s + max_units], "stem": "_shared", "context": [],
        })
    return chunks


# --------------------------------------------------------------------------
# request text
# --------------------------------------------------------------------------
DUMMY_SUBJECT = "Taro"


def build_user_text(chunk):
    """Returns (text, id_map) where id_map[i-1] is the unit id for key "i"."""
    lines = ["Translate every numbered segment below. "
             "Return ONLY the JSON object."]

    kinds = []
    for u in chunk["units"]:
        if u["kind"] not in kinds:
            kinds.append(u["kind"])
    if kinds:
        lines.append("")
        lines.append("Request instructions:")
        for k in kinds:
            lines.append("  [%s] %s" % (prompts.KIND_LABEL.get(k, k),
                                        prompts.KIND_INSTRUCTION.get(k, "")))

    ctx = chunk.get("context") or []
    if ctx:
        lines.append("")
        lines.append("Preceding Japanese source context (untranslated) - use "
                     "these lines only to understand the scene. Do NOT "
                     "translate them, do not include them in the output, and "
                     "do not copy Japanese spellings from them; the glossary "
                     "is authoritative.")
        for u in ctx:
            spk = u.get("speaker") or ""
            body = (u.get("src") or "").replace("\n", " ")
            lines.append(("  (%s) %s" % (spk, body)) if spk else "  " + body)

    lines.append("")
    id_map = []
    last_scene = None
    for u in chunk["units"]:
        scene = u.get("ctx", "")
        if scene and scene != last_scene:
            lines.append("# scene: " + scene)
            last_scene = scene
        id_map.append(u["id"])
        i = len(id_map)
        tag = prompts.KIND_LABEL.get(u["kind"], u["kind"])
        spk = u.get("speaker")
        if u["kind"] == "text" and spk:
            tag = "%s; speaker %s" % (tag, spk)
        head = "[%d] (%s)" % (i, tag)
        note = u.get("note")
        if note:
            head += " <%s>" % note
        body = u["src"].replace("\n", " ")
        if u.get("dummy_subject"):
            body = DUMMY_SUBJECT + body
        lines.append("%s %s" % (head, body))

    lines.append("")
    lines.append('JSON object {"1":"...", ...} with one translation for every '
                 "number above, and nothing else.")
    return "\n".join(lines), id_map


def system_blocks(store_dir, glossary, payload, ttl="1h", roster_min=0):
    """[0] rules+bible (cached)  [1] roster (cached)  [2] matched terms."""
    blocks = [{"type": "text", "text": prompts.stable_prefix(store_dir)}]
    roster = prompts.roster_block(glossary, roster_min)
    if roster:
        blocks.append({"type": "text", "text": roster})
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": ttl}
    terms = prompts.matched_terms(glossary, payload)
    if terms:
        blocks.append({"type": "text", "text": terms})
    return blocks


def build_request(chunk, model, store_dir, glossary, effort="low", ttl="1h",
                  retry_note="", roster_min=0):
    user, id_map = build_user_text(chunk)
    if retry_note:
        # The correction goes in the USER turn. Editing the system prefix on a
        # retry busts the prompt cache and pays a full cache write per attempt.
        user += "\n\nRETRY - the previous attempt failed these checks:\n" + retry_note
    n = len(id_map)
    return {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": min(32000, max(4096, n * 220)),
            **sampling_params(model),
            **output_config(effort),
            "system": system_blocks(store_dir, glossary, user, ttl=ttl,
                                    roster_min=roster_min),
            "messages": [{"role": "user", "content": user}],
        },
    }, id_map


def build_name_requests(glossary, model, store_dir, effort="low", ttl="1h",
                        retranslate_all=False, max_units=120):
    """Names first, in their own pass, written straight back into the glossary.

    Ordered by how often the name is SPOKEN, so if a run is interrupted the
    names that matter are already locked."""
    names = [k for k, v in glossary.get("names", {}).items()
             if retranslate_all or store.name_needs_tl(v)]
    names.sort(key=lambda k: -(glossary["names"][k].get("count", 0)
                               if isinstance(glossary["names"][k], dict) else 0))
    reqs, maps = [], {}
    for part in range(0, len(names), max_units):
        sub = names[part:part + max_units]
        cid = "__names__%03d" % (part // max_units)
        body = ["Translate these character names and speaker labels. "
                "Return ONLY the JSON object."]
        for i, nm in enumerate(sub, 1):
            v = glossary["names"][nm]
            n = v.get("count", 0) if isinstance(v, dict) else 0
            body.append("[%d] %s%s" % (i, nm, ("   (%d lines)" % n) if n else ""))
        blocks = [{"type": "text",
                   "text": prompts.NAME_SYSTEM + "\n\n"
                           + prompts.load_side_file(store_dir, "game_prompt.md")}]
        blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": ttl}
        reqs.append({
            "custom_id": cid,
            "params": {
                "model": model,
                "max_tokens": max(1024, len(sub) * 60),
                **sampling_params(model),
                **output_config(effort),
                "system": blocks,
                "messages": [{"role": "user", "content": "\n".join(body)}],
            },
        })
        maps[cid] = sub
    return reqs, maps


# --------------------------------------------------------------------------
# applying results
# --------------------------------------------------------------------------
# The possessive `'s` is deliberately NOT consumed, and the space BEFORE the
# name is. `Taro's poison faded` has to become `'s poison faded`, so the
# engine's `name + message` concatenation renders `Eris's poison faded`; and a
# bled `Eris Taro's poison faded` has to become `Eris's poison faded` rather
# than `Eris 's poison faded`.
_DUMMY_RE = re.compile(r"[ \t]*\b%s\b" % DUMMY_SUBJECT, re.I)


def scrub_dummy_subject(text, prefixed=False):
    """Run this on EVERY message-kind result, prefixed or not.

    Prompt bleed puts the dummy name into neighbouring items in the same
    request, and a leaked one ships as `Eris Taro has fallen!` in a battle log
    that only appears in combat and survives every text-only review.

    `prefixed` says the engine draws this fragment as `subject.name + message`
    with NO separator of its own (`Window_BattleLog` does exactly that for
    Skill message1 and State message1-4). Japanese needs no space there and
    English does, so the leading space is restored after the dummy name is
    removed - otherwise the log reads `Erisattacks!`. It is skipped when the
    fragment opens with an apostrophe or punctuation, where a space would be
    wrong instead."""
    out = _DUMMY_RE.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out).rstrip().rstrip('"').rstrip()
    out = out.lstrip('"').lstrip(" \t")
    if prefixed and out and (out[0].isalnum() or out[0] in "([{"):
        out = " " + out
    return out


def apply_results(docs, glossary, results, id_maps, name_maps):
    """Fill translations. A deduped group's representative fans out to every
    unit sharing (kind, src)."""
    by_id = {}
    by_key = {}
    for _p, doc in docs:
        for u in doc["units"]:
            by_id[u["id"]] = u
            if u["kind"] in store.DEDUPED_KINDS:
                by_key.setdefault((u["kind"], u["src"]), []).append(u)

    applied = names = 0
    errors = []
    for cid, obj in results.items():
        if cid in name_maps:
            jp_list = name_maps[cid]
            for k, v in obj.items():
                try:
                    idx = int(k)
                except ValueError:
                    continue
                if not (1 <= idx <= len(jp_list)):
                    errors.append("%s: name index %s out of range" % (cid, k))
                    continue
                jp = jp_list[idx - 1]
                if isinstance(v, dict):
                    en = (v.get("en") or "").strip().strip('"')
                    g = (v.get("gender") or "").strip().lower()
                    if not en:
                        continue
                    store.set_name(glossary, jp, en,
                                   g if g in ("male", "female") else None)
                elif isinstance(v, str) and v.strip():
                    store.set_name(glossary, jp, v.strip().strip('"'))
                else:
                    continue
                names += 1
            continue

        idmap = id_maps.get(cid) or []
        for k, v in obj.items():
            try:
                idx = int(k)
            except ValueError:
                # A reply keyed `{"Line1": ...}` or `{"translations": {...}}`
                # applies nothing. Silently skipping it reports zero applied
                # AND zero errors, which reads as "there was nothing to do".
                errors.append("%s: key %r is not a segment number" % (cid, k))
                continue
            if not (1 <= idx <= len(idmap)) or not isinstance(v, str):
                errors.append("%s: index %s out of range" % (cid, k))
                continue
            u = by_id.get(idmap[idx - 1])
            if u is None:
                continue
            text = v
            if u["kind"] == "message" or u.get("dummy_subject"):
                text = scrub_dummy_subject(text, prefixed=u.get("dummy_subject"))
            u["tl"] = text
            applied += 1
            if u["kind"] in store.DEDUPED_KINDS:
                # Overwrite every sibling that is not locked, not only the
                # empty ones. A deduped group is one string by definition, so
                # leaving an older rendering behind on a retry or a
                # --retranslate-all is how the same menu label ends up reading
                # two ways on two screens - and `same_source_conflicts` would
                # then report a conflict the pipeline itself created.
                for sib in by_key.get((u["kind"], u["src"]), []):
                    if sib is not u and not sib.get("locked") and sib.get("tl") != text:
                        sib["tl"] = text
                        applied += 1
    return applied, names, errors
