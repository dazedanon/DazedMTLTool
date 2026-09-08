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
  overhead dwarfed the payload.
* Nor one request per store shard. The shards here are how the store is FILED
  (by owner, capped at 1,200 units), not how the game is structured, so
  breaking at every shard boundary pays per-request overhead for a filing
  decision: strict per-doc chunking gave 480 requests averaging 51 units
  against a budget of 80, and packing scenes in play order across shards gave
  400. A SCENE is still never split unless it alone exceeds the budget.
* A scene that does exceed it is split, and the split parts carry the previous
  lines as do-not-translate CONTEXT - the SOURCE lines, never the English
  produced a moment ago, which is how one bad rendering compounds.
* Dedup identity is `store.dedup_key`, which on this game covers dialogue too,
  keyed on (speaker, src). One translation fans out to every unit sharing it.
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
    """`temperature` is a hard 400 on the 5 family and on 4.7/4.8.

    Matched by SUBSTRING, longest-first, exactly as `price_for` does. An exact
    set membership test looks equivalent and is not: a dated id such as
    `claude-sonnet-5-20260219`, or anything set through `ARTL_MODEL`, prices
    correctly and then gets `temperature: 0` attached - which `_send_all`
    treats as non-retryable, so a live run walks through every request failing
    and a batch submits hundreds that all error."""
    m = (model or "").lower()
    for key in sorted(NO_SAMPLING, key=len, reverse=True):
        if key in m:
            return {}
    return {"temperature": 0}


# The SDK refuses a non-streaming request whose max_tokens implies a call that
# could exceed ten minutes:
#
#   expected_time = 3600 * max_tokens / 128_000    (_base_client.py)
#   raise if expected_time > 600
#
# so the hard ceiling is max_tokens <= 21,333. It is a ValueError raised BEFORE
# the request goes out - no HTTP status, which is why `_send_all` logged a bare
# "ERROR". Batch requests do not go through `messages.create` and are not bound
# by it, but the live path, `smoke` and the names pass all are, and sizing a
# request over the line makes them fail 100% of the time rather than sometimes.
MAX_NONSTREAM_TOKENS = 21000

# Output tokens a single unit of each shape actually costs. A dialogue line is
# a sentence; a NAME is two or three words plus a gender field. Using the
# dialogue figure for names is what pushed a 200-name request to 32,000 and
# over the ceiling.
OUT_PER_UNIT = 200
OUT_PER_NAME = 60


def cap_tokens(n, per_unit=OUT_PER_UNIT):
    """max_tokens for a request of `n` units, floored and capped.

    The floor is 4096 because even a short structured reply needs room for JSON
    scaffolding and reasoning tokens; the cap is the SDK's own non-streaming
    limit."""
    return min(MAX_NONSTREAM_TOKENS, max(4096, n * per_unit))


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
# A Bakin dialogue id is `S:<scriptGuid>:<commandIndex>:<attrIndex>`, and a
# Script IS a scene - one event sheet's whole command list. Dropping the last
# two segments groups a scene; anything that is not a script id (a database
# row, a UI label) has no scene and groups under itself.
_SCENE_RE = re.compile(r"^(S:[0-9a-fA-F-]+):\d+:\d+")


def scene_key(uid):
    m = _SCENE_RE.match(uid or "")
    return m.group(1) if m else uid


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


def dedup_groups(units, dedup_dialogue=True):
    """[[unit, ...]] - one group per thing that is translated once."""
    groups = {}
    order = []
    for u in units:
        key = store.dedup_key(u, dedup_dialogue) or ("#", u["id"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(u)
    return [groups[k] for k in order]


def build_chunks(docs, max_units, retranslate_all=False, only_ids=None,
                 context_lines=3, dedup_dialogue=True):
    """Scene-aligned dialogue chunks per doc, plus pooled non-dialogue chunks.

    Dedup for the non-dialogue kinds is GLOBAL, not per doc: `はい` occurs
    across a dozen maps and paying for it once per doc is paying for it a dozen
    times.

    Dialogue dedup is keyed on (speaker, src) and is on by measurement - see
    the note on `store.dedup_key`. The representative kept is the FIRST
    occurrence in play order, so it is translated in a real scene with real
    neighbours rather than in a bag of orphan lines."""
    chunks = []
    dialogue_by_doc = {}
    shared = []
    seen_keys = set()

    for doc, u in pending(docs, retranslate_all, only_ids):
        key = store.dedup_key(u, dedup_dialogue)
        if key is not None and u["kind"] in store.DEDUPED_KINDS:
            if key in seen_keys:
                continue
            seen_keys.add(key)
            shared.append(u)
            continue
        if key is not None:
            # A deduped DIALOGUE line still belongs to its scene, so its
            # representative stays in the doc it came from rather than being
            # pooled into the shared bucket with the UI labels.
            if key in seen_keys:
                continue
            seen_keys.add(key)
        dialogue_by_doc.setdefault(id(doc), (doc, []))[1].append(u)

    # Scenes are packed in PLAY ORDER across doc shards, not one chunk per doc.
    #
    # The doc shards here are an artifact of how the store is filed (owner, then
    # a 1,200-unit cap), not of the game's structure, so breaking a request at
    # every shard boundary is paying per-request overhead for a filing decision.
    # Measured on this game: strict per-doc chunking produced 480 requests
    # averaging 51 units against a budget of 80. The cached prefix is written
    # once per request on a batch, so those extra requests are the single
    # largest avoidable line on the bill.
    #
    # A SCENE is still never split across a chunk unless it alone exceeds the
    # budget, and `build_user_text` emits a `# scene:` header whenever the scene
    # changes, so the model still sees coherent runs.
    ordered = []
    for _k, (doc, units) in dialogue_by_doc.items():
        stem = store.doc_stem(doc)
        for u in units:
            ordered.append((u.get("order") or u["id"], stem, u))
    ordered.sort(key=lambda t: (t[0], t[2]["id"]))

    scenes, cur = [], None
    for _o, stem, u in ordered:
        k = scene_key(u["id"])
        if k != cur:
            scenes.append((stem, []))
            cur = k
        scenes[-1][1].append(u)

    part = [0]
    buf, buf_stem = [], None

    def emit(sub, stem, ctx=None):
        chunks.append({
            "custom_id": store.sanitize_id("%s__%04d" % (stem or "scene", part[0])),
            "units": sub, "stem": stem, "context": ctx or [],
        })
        part[0] += 1

    for stem, sc in scenes:
        if len(sc) > max_units:
            if buf:
                emit(list(buf), buf_stem)
                buf, buf_stem = [], None
            for s in range(0, len(sc), max_units):
                # A split scene carries the previous SOURCE lines as
                # do-not-translate context, never the English produced a moment
                # earlier, which is how one bad rendering compounds.
                ctx = sc[max(0, s - context_lines):s] if s else []
                emit(sc[s:s + max_units], stem, ctx)
        else:
            if buf and len(buf) + len(sc) > max_units:
                emit(list(buf), buf_stem)
                buf, buf_stem = [], None
            if not buf:
                buf_stem = stem
            buf.extend(sc)
    if buf:
        emit(list(buf), buf_stem)

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


def system_blocks(store_dir, glossary, payload, ttl="1h", roster_min=0,
                  roster_field_chars=prompts.ROSTER_FIELD_CHARS):
    """[0] rules+bible (cached)  [1] roster (cached)  [2] matched terms.

    `roster_min` bounds the cached block. This game has 465 distinct
    nameplate speakers; shipping all of them is ~18k tokens written on every
    request, and on a batch most requests write the prefix rather than read it.
    Names under the threshold are still enforced - they reach the model through
    the per-request matched-terms block when they actually appear."""
    blocks = [{"type": "text", "text": prompts.stable_prefix(store_dir)}]
    roster = prompts.roster_block(glossary, roster_min=roster_min,
                                  field_chars=roster_field_chars)
    if roster:
        blocks.append({"type": "text", "text": roster})
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": ttl}
    terms = prompts.matched_terms(glossary, payload, roster_min=roster_min)
    if terms:
        blocks.append({"type": "text", "text": terms})
    return blocks


def build_request(chunk, model, store_dir, glossary, effort="low", ttl="1h",
                  retry_note="", roster_min=0,
                  roster_field_chars=prompts.ROSTER_FIELD_CHARS):
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
            "max_tokens": cap_tokens(n),
            **sampling_params(model),
            **output_config(effort),
            "system": system_blocks(store_dir, glossary, user, ttl=ttl,
                                    roster_min=roster_min,
                                    roster_field_chars=roster_field_chars),
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
                # A name reply is a two-or-three-word English name plus a
                # gender, not a sentence - so the per-unit figure is the name
                # one. The text figure put a 200-name request at 32,000, over
                # the SDK's non-streaming ceiling, and every full-size name
                # request failed before it was sent.
                "max_tokens": cap_tokens(len(sub), OUT_PER_NAME),
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


def apply_results(docs, glossary, results, id_maps, name_maps,
                  dedup_dialogue=True):
    """Fill translations. A deduped group's representative fans out to every
    unit sharing its dedup key."""
    by_id = {}
    by_key = {}
    for _p, doc in docs:
        for u in doc["units"]:
            by_id[u["id"]] = u
            k = store.dedup_key(u, dedup_dialogue)
            if k is not None:
                by_key.setdefault(k, []).append(u)

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
            # Only where a dummy subject was actually PREPENDED. The RPG Maker
            # pipelines run this on every `message` unit because their battle
            # log strings are particle-initial fragments that need one; this
            # game's `Condition.messageFor*` are whole sentences that already
            # name the actor, nothing sets `dummy_subject`, and running it
            # anyway strips surrounding quotes off 561 correct translations for
            # a prefix that was never added.
            if u.get("dummy_subject"):
                text = scrub_dummy_subject(text)
            u["tl"] = text
            applied += 1
            k = store.dedup_key(u, dedup_dialogue)
            if k is not None:
                # Overwrite every sibling that is not LOCKED, not only the
                # empty ones. A deduped group is one string by definition, so
                # leaving an older rendering behind on a retry or a
                # `--retranslate-all` means the representative is repaired and
                # the other 64,000 units keep the text that failed - measured:
                # a retry round updated 24,703 of 90,195 and left 65,492
                # carrying the bad translation, at full price for the round.
                # It also manufactures the exact same-source conflict that
                # `qa.repeats` then reports.
                for sib in by_key.get(k, []):
                    if sib is not u and not sib.get("locked"):
                        if sib.get("tl") != text:
                            sib["tl"] = text
                            applied += 1
    return applied, names, errors
