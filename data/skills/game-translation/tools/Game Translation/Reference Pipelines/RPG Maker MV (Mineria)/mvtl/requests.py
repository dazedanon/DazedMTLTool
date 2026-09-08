#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
requests.py - chunking and request construction, shared by the batch and live
drivers.

Both drivers MUST build requests through this module. A live "fallback" that
builds its own requests stops testing the batch path, and the two silently
drift until a retry produces different output from the run it is repairing.

Chunking rules that came out of measured runs:

* Dialogue is scene-aligned but NOT one request per scene. A game with hundreds
  of two-line scenes produced 510 requests averaging 10 units, where per-request
  overhead dwarfed the payload. Pack scenes in play order up to the unit budget
  and break only on FILE boundaries.
* A scene that alone exceeds the budget is split, and the split parts carry the
  previous lines as do-not-translate CONTEXT - the SOURCE lines, never the
  English produced a moment ago, which is how one bad rendering compounds
  through a whole file.
* Everything that is not dialogue is deduped globally by (kind, src) before it
  is queued, and one translation fans out to every unit that shares the pair.
* Chunk sizes stay uniform. Every distinct chunk size is a separate cached
  prefix if the output contract varies with N, and ragged sizes pay a
  full-price cache write each.
"""

import os
import re
import json

from . import store, prompts

MODEL_DEFAULT = "claude-opus-5"

# Transcribed from the live pricing page, first-party API, USD per MTok.
# All five published columns, not just input and output, because an estimate
# that guesses the cache columns is wrong by the multiplier it guessed.
#
#   5m cache write = 1.25x base input
#   1h cache write = 2.00x base input
#   cache hit      = 0.10x base input
#
# The batch rate is these halved at spend time (see `Usage.cost`), never typed
# twice: the multipliers "stack with other pricing modifiers, including the
# Batch API discount", so cache writes and reads halve as well.
#
# DO NOT record a promotional expiry here. The previous version of this table
# carried `claude-sonnet-5` as "$3.00, intro $2.00 through 2026-08-31". The
# increase was cancelled and $2.00/$10.00 is now the standard price - so a
# caveat written to be careful would have made every Sonnet 5 estimate run 50%
# high, in the direction nobody re-checks. Re-read the page instead.
PRICING = {
    "claude-fable-5":   {"in": 10.00, "out": 50.00, "cw5m": 12.50, "cw1h": 20.00, "cr": 1.00},
    "claude-mythos-5":  {"in": 10.00, "out": 50.00, "cw5m": 12.50, "cw1h": 20.00, "cr": 1.00},
    "claude-opus-5":    {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-opus-4-8":  {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-opus-4-7":  {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-opus-4-6":  {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-opus-4-5":  {"in": 5.00, "out": 25.00, "cw5m": 6.25, "cw1h": 10.00, "cr": 0.50},
    "claude-sonnet-5":  {"in": 2.00, "out": 10.00, "cw5m": 2.50, "cw1h": 4.00, "cr": 0.20},
    "claude-sonnet-4-6": {"in": 3.00, "out": 15.00, "cw5m": 3.75, "cw1h": 6.00, "cr": 0.30},
    "claude-sonnet-4-5": {"in": 3.00, "out": 15.00, "cw5m": 3.75, "cw1h": 6.00, "cr": 0.30},
    "claude-haiku-4-5": {"in": 1.00, "out": 5.00, "cw5m": 1.25, "cw1h": 2.00, "cr": 0.10},
}

# Multipliers on top of the table. Each of these silently moves the total and
# is easy to leave out of an estimate entirely.
CACHE_MULTIPLIER = {"5m": 1.25, "1h": 2.00, "hit": 0.10}
BATCH_DISCOUNT = 0.5
# `inference_geo: "us"` bills 1.1x on EVERY token category on 4.6-and-later.
# The default `"global"` is standard price. This pipeline never sets the
# parameter, so the factor is 1.0 - it is here so an estimate stays honest if
# somebody pins the geography later.
INFERENCE_GEO_MULTIPLIER = {"global": 1.0, "us": 1.1}
# Fast mode: Opus 5 / Opus 4.8 only, $10 in / $50 out, stacks with the cache
# multipliers, and is NOT available with the Batch API. A fast-mode plan and a
# batch plan are different plans, not a toggle.
FAST_MODE_PRICING = {"in": 10.00, "out": 50.00}

# Models whose tokenizer is the post-4.7 one, which the pricing page says
# yields "approximately 30% more tokens for the same text". A measured
# 118-request run on one of them came in at x0.998 against the tiktoken proxy,
# so the estimator does NOT inflate on this basis - but it says which tokenizer
# it is quoting, so a later reconciliation against the bill has something to
# blame. Sonnet 4.6 and earlier use the previous tokenizer.
NEW_TOKENIZER = {
    "claude-fable-5", "claude-mythos-5", "claude-opus-5", "claude-opus-4-8",
    "claude-opus-4-7", "claude-sonnet-5",
}

# 4.6-and-later ship the full 1M context window at standard rates - a
# 900k-token request bills per token exactly like a 9k one, and caching and
# batch apply across the whole window. There is no long-context premium to
# budget for.

# Models that reject temperature / top_p / top_k with a hard 400. The cut is
# between 4.6 and 4.7 and is NOT a numeric comparison, so it is an explicit
# list.
NO_SAMPLING = {
    "claude-fable-5", "claude-mythos-5", "claude-opus-5", "claude-sonnet-5",
    "claude-opus-4-8", "claude-opus-4-7",
}


def price_for(model):
    m = (model or "").lower()
    for key in sorted(PRICING, key=len, reverse=True):     # longest first
        if key in m:
            return PRICING[key]
    return PRICING[MODEL_DEFAULT]


def sampling_params(model):
    return {} if (model or "") in NO_SAMPLING else {"temperature": 0}


def output_config(effort):
    """`effort` lives inside output_config, not top-level, and the API default
    is `high` - a model left at the default spends as many thinking tokens as
    it wants. Translation is direct high-volume work, so `low` is the default
    here. Adaptive thinking stays ON: `thinking: {"type": "disabled"}` is
    accepted on Opus 5 only at effort high or below and introduces two failure
    modes (a tool call written into visible text, <thinking> tags leaking)."""
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
            if only_ids is not None:
                if u["id"] in only_ids:
                    yield doc, u
                continue
            if u.get("locked"):
                continue
            if retranslate_all or not (u.get("tl") or "").strip():
                yield doc, u


def dedup_groups(units):
    """{(kind, src): [unit, ...]} for the deduped kinds; dialogue passes
    through as singleton groups."""
    groups = {}
    order = []
    for u in units:
        if u["kind"] in store.DEDUPED_KINDS:
            key = (u["kind"], u["src"])
        else:
            key = ("#", u["id"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(u)
    return [groups[k] for k in order]


def build_chunks(docs, max_units, retranslate_all=False, only_ids=None,
                 context_lines=3):
    """Scene-aligned dialogue chunks per file, plus pooled non-dialogue chunks.

    Dedup for the non-dialogue kinds is GLOBAL, not per file: `はい` occurs 42
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

    # Non-dialogue: group by kind so each request carries one widget type, then
    # pool the leftovers into mixed requests rather than spending a request on
    # a single title.
    shared.sort(key=lambda u: (u["kind"], u["id"]))
    part = 0
    for s in range(0, len(shared), max_units):
        chunks.append({
            "custom_id": store.sanitize_id("_shared__%03d" % part),
            "units": shared[s:s + max_units], "stem": "_shared", "context": [],
        })
        part += 1
    return chunks


# --------------------------------------------------------------------------
# request text
# --------------------------------------------------------------------------
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
            lines.append("  (%s) %s" % (spk, body) if spk else "  " + body)

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
            tag = "%s; %s" % (tag, spk)
        note = u.get("note")
        head = "[%d] (%s)" % (i, tag)
        if note:
            head += " <%s>" % note
        if u.get("dummy_subject"):
            # A bare `は触手を伸ばした！` gives the model no grammatical
            # subject. `Taro` is prepended, translated, then scrubbed
            # unconditionally on the way back - it bleeds into neighbouring
            # items in the same batch even when they never got one.
            lines.append("%s Taro%s" % (head, u["src"]))
        else:
            lines.append("%s %s" % (head, u["src"]))

    lines.append("")
    lines.append('JSON object {"1":"...", ...} with one translation for every '
                 "number above, and nothing else.")
    return "\n".join(lines), id_map


def system_blocks(store_dir, glossary, payload, ttl="1h"):
    """[0] rules+bible (cached)  [1] roster (cached)  [2] matched terms."""
    blocks = [{"type": "text", "text": prompts.stable_prefix(store_dir)}]
    roster = prompts.roster_block(glossary)
    if roster:
        blocks.append({"type": "text", "text": roster})
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": ttl}
    terms = prompts.matched_terms(glossary, payload)
    if terms:
        blocks.append({"type": "text", "text": terms})
    return blocks


def build_request(chunk, model, store_dir, glossary, effort="low", ttl="1h",
                  retry_note=""):
    user, id_map = build_user_text(chunk)
    if retry_note:
        # The correction goes in the USER turn. Editing the system prefix on
        # retry busts the prompt cache and pays a full cache write on every
        # attempt.
        user += "\n\nRETRY - the previous attempt failed these checks:\n" + retry_note
    n = len(id_map)
    return {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": min(32000, max(4096, n * 200)),
            **sampling_params(model),
            **output_config(effort),
            "system": system_blocks(store_dir, glossary, user, ttl=ttl),
            "messages": [{"role": "user", "content": user}],
        },
    }, id_map


def build_name_requests(glossary, model, store_dir, effort="low", ttl="1h",
                        retranslate_all=False, max_units=200):
    names = [k for k, v in glossary.get("names", {}).items()
             if retranslate_all or store.name_needs_tl(v)]
    reqs, maps = [], {}
    for part in range(0, len(names), max_units):
        sub = names[part:part + max_units]
        cid = "__names__%03d" % (part // max_units)
        body = ["Translate these character names. Return ONLY the JSON object."]
        for i, nm in enumerate(sub, 1):
            body.append("[%d] %s" % (i, nm))
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
_TARO_RE = re.compile(r"\bTaro(?:['’]s)?\b", re.I)


def scrub_dummy_subject(text):
    """Run this on EVERY message-kind result, prefixed or not.

    Prompt bleed inserts `Taro` into neighbouring items in the same batch, and
    a leaked placeholder ships as `Alice Taro extended a tentacle!` in a battle
    log that only appears in combat and survives every text-only review."""
    out = _TARO_RE.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out.strip(" \t\"'")


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
                continue
            if not (1 <= idx <= len(idmap)) or not isinstance(v, str):
                errors.append("%s: index %s out of range" % (cid, k))
                continue
            u = by_id.get(idmap[idx - 1])
            if u is None:
                continue
            text = v
            if u["kind"] == "message" or u.get("dummy_subject"):
                text = scrub_dummy_subject(text)
            u["tl"] = text
            applied += 1
            if u["kind"] in store.DEDUPED_KINDS:
                for sib in by_key.get((u["kind"], u["src"]), []):
                    if sib is not u and not (sib.get("tl") or "").strip():
                        sib["tl"] = text
                        applied += 1
    return applied, names, errors
