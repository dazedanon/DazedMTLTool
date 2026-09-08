#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch.py — translate the store with Claude via the Anthropic Message Batches API.

Commands (exposed through tl.py): dryrun, submit, status, fetch, run, validate,
selftest.

Design (improves on the reference per-line tool):
  * One cached system block shared across every request (prompt caching → cheap).
  * A cached per-game glossary block (character names + recurring terms) so the
    model stays consistent across thousands of lines.
  * Compact requests: units are listed with short integer indices grouped by
    context; the model returns {index: english}. Long unit ids never hit the
    wire — they are mapped back locally.
  * Control codes are already masked to ⟦n⟧ placeholders in the store, so the
    model can't corrupt them.
  * Character names are translated in their own requests and written to the
    glossary; inject is the single source of truth for name windows.
"""

import os
import re
import sys
import json
import time

from . import store

MODEL_DEFAULT = "claude-opus-4-8"

# USD per 1M tokens (standard <=200K context; our per-request size is ~12-15K so
# no long-context surcharge applies). batch_* = 50% off. cache_write uses the 1h
# TTL rate (2x base input, since the tool caches the prefix with ttl="1h");
# cache_read = 10% of base input. Verified Jun 2026.
PRICE_BY_MODEL = {
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "batch_in": 1.5, "batch_out": 7.5,
                          "cache_write": 6.0, "cache_read": 0.30},
    "claude-opus-4-8":   {"in": 5.0, "out": 25.0, "batch_in": 2.5, "batch_out": 12.5,
                          "cache_write": 10.0, "cache_read": 0.50},
}


def price_for(model):
    """Pricing dict for a model id; falls back to Sonnet 4.6 for unknown ids."""
    m = (model or "").lower()
    for key, pr in PRICE_BY_MODEL.items():
        if key in m:
            return pr
    return PRICE_BY_MODEL["claude-sonnet-4-6"]


# Back-compat alias (default model) for any external reference.
PRICE = PRICE_BY_MODEL["claude-sonnet-4-6"]

# Models that REJECT the sampling params (temperature/top_p/top_k) with a 400 —
# Claude Opus 4.7 and up retired them in favour of adaptive thinking. Matches
# opus-4-7, opus-4-8, opus-4-9, opus-4-10+, … but NOT opus-4-6 or Sonnet/Haiku.
_NO_SAMPLING_RE = re.compile(r"opus-4-(?:[7-9]\b|[1-9]\d)", re.I)


def _sampling_params(model):
    """{'temperature': 0} for models that accept it; {} for Opus 4.7+ (which 400
    on temperature/top_p/top_k). Spread into the request params."""
    return {} if _NO_SAMPLING_RE.search(model or "") else {"temperature": 0}


# --- reasoning effort (cost lever) ----------------------------------------
# Opus 4.8 / Sonnet 4.6 / Opus 4.5+ DEFAULT to 'high' effort, which spends "as
# many tokens as needed" and inflates output (and any adaptive thinking) — the
# reason a run costs more than the naive output estimate. Translation is a direct,
# high-volume task, so 'low' (Anthropic's recommended level for high-volume / simple
# work) is the default here. Raise to 'medium'/'high' if a pass needs more nuance.
# We never enable adaptive thinking (no `thinking` param) — that would add cost.
EFFORT_DEFAULT = "low"
_EFFORT = EFFORT_DEFAULT
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def set_effort(effort):
    global _EFFORT
    if effort:
        _EFFORT = effort


def _output_config():
    """output_config.effort for the request. Omitted when 'high' (== the API
    default) so older models that don't know the field are unaffected."""
    if _EFFORT and _EFFORT in _EFFORT_LEVELS and _EFFORT != "high":
        return {"output_config": {"effort": _EFFORT}}
    return {}

KIND_LABEL = {
    "text": "dialogue", "choice": "menu choice", "name": "name",
    "nickname": "title/nickname", "profile": "character profile",
    "desc": "description", "message": "action-log message", "term": "UI text",
    "title": "window title", "currency": "currency unit", "mapname": "location name",
    "note": "note", "ptext": "on-screen text (narration / picture / UI)",
}

SYSTEM_SHARED = (
    "You are an expert Japanese-to-English eroge (adult game) translator and localizer. You "
    "translate dialogue, narration, menu/UI text, item and skill descriptions for a Japanese "
    "RPG Maker game into natural, fluent, idiomatic English.\n\n"
    "You receive a numbered list of short segments from ONE game file. Each is tagged with its "
    "role (dialogue, menu choice, name, description, action-log message, UI text, location "
    "name, …) and, for dialogue, the speaker. A character & term glossary follows in the next "
    "block — read it first and apply ALL of it.\n\n"
    "OUTPUT FORMAT\n"
    "- Translate EVERY numbered segment. Output ONLY a JSON object mapping each number (as a "
    'string) to its English translation, e.g. {\"1\":\"...\",\"2\":\"...\"}. No preamble, notes, '
    "romaji, or Japanese in the output.\n\n"
    "PROTECTED CODES\n"
    "- Tokens like ⟦0⟧, ⟦1⟧ are game control codes (icons, colors, variables, ruby, pauses). "
    "Keep each one EXACTLY as written and in the SAME relative position (e.g. a ⟦0⟧ icon at the "
    "start of a menu choice stays at the start). Never translate, renumber, reorder, add, or "
    "drop them. Keep %1, %2 markers unchanged.\n\n"
    "QUALITY & CONSISTENCY\n"
    "- Prefer natural, fluent English over literal gloss. Preserve tone (comedic / tense / "
    "tender) and each speaker's register and personality from the glossary. Use the SAME "
    "English name for a character every time.\n"
    "- A full-width space (　) is just indentation — ignore it. '...' is valid punctuation — "
    "keep it. Don't merge or split segments.\n\n"
    "CHARACTERS, GENDER & PRONOUNS\n"
    "- Japanese omits pronouns constantly; infer the subject/pronoun from context and the "
    "glossary. Resolve 彼 / 彼女 / あいつ / こいつ / そいつ / コイツ to match the referenced "
    "character's stated gender.\n"
    "- Translate コイツ as 'this bastard' (male) or 'this bitch' (female) per gender.\n"
    "- If a character refers to themselves by their own name (third-person self-reference) as a "
    "stylistic trait, keep that in English.\n\n"
    "HONORIFICS & NAMES\n"
    "- Preserve Japanese honorifics: -san, -kun, -chan, -sama, -senpai, -sensei, -dono, -tan, "
    "etc.\n"
    "- A '=' or '＝' inside a name marks a foreign/nickname part — wrap it in parentheses "
    "(バンカー＝ベット → Bunker (Bet)).\n\n"
    "ADULT CONTENT (this is an 18+ game — do NOT censor or euphemize unless the Japanese itself "
    "is euphemistic)\n"
    "- Translate explicit sexual content directly and vividly, matching the source register "
    "(clinical / vulgar / colloquial). Keep dominant speech dominant and submissive begging "
    "submissive.\n"
    "- Erotic onomatopoeia (ぴちゃ, ぐちゅ, じゅぽ, くちゅ, ぬぷ, くぱぁ …) → evocative English "
    "sounds/phrases. Moans & climax cues (あぁ, んっ, はぁ, イく, イっちゃう, イくっ …) → render "
    "expressively: 'Aah...', 'Ngh...', \"I'm cumming...\", \"I'm gonna cum...\".\n\n"
    "EXAMPLE\n"
    "Input:\n"
    "[1] (dialogue; Moloch) 雷穏将の名をもって同じく。\n"
    "[2] (menu choice) ⟦0⟧種付けする\n"
    "[3] (dialogue; Succubus) あぁ…んっ♡ そんなに激しくされたらイっちゃう…\n"
    "Output:\n"
    '{"1":"By the name of the Thunder-Calm General, I concur.","2":"⟦0⟧Breed",'
    '"3":"Aah... ngh♡ If you take me that hard, I\'m gonna cum..."}'
)

NAME_SYSTEM = (
    "You are localizing an adult Japanese RPG Maker game. For each Japanese CHARACTER NAME "
    "below, give the clean, consistent English name that will appear in dialogue and name "
    "windows, plus your best guess of the character's gender from the name (male / female / "
    "unknown). No honorifics unless part of the name.\n"
    "Output ONLY a JSON object mapping each number (as a string) to an object "
    '{\"en\": \"<english name>\", \"gender\": \"male|female|unknown\"}, e.g. '
    '{\"1\":{\"en\":\"Einaike\",\"gender\":\"female\"},\"2\":{\"en\":\"Furfur\",\"gender\":\"male\"}}.'
)


# --------------------------------------------------------------------------
# tokenizer proxy
# --------------------------------------------------------------------------
def get_counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        return lambda s: max(1, int(len(s) / 2.0))


# --------------------------------------------------------------------------
# request building
# --------------------------------------------------------------------------
def _glossary_block(glossary, chunk_text=""):
    """Render the glossary for one request.

    All character entries are always included (small, high value, gives gender
    for pronoun resolution). Terms are filtered to those appearing in this
    chunk's text, to keep the block lean.
    """
    lines = []
    name_lines = []
    for jp, v in glossary.get("names", {}).items():
        en = store.name_en(v)
        if not en:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing documentation (verification evidence, etc.) and
            # is intentionally NOT sent to the model — it would bloat every request.
            for key in ("gender", "role", "register"):
                if v.get(key):
                    meta.append(str(v[key]))
            for alias in (v.get("aliases") or []):
                meta.append(f"aka {alias}")
        suffix = f"  ({'; '.join(meta)})" if meta else ""
        name_lines.append(f"  {jp} → {en}{suffix}")
    if name_lines:
        lines.append("# Characters (use these English names and genders consistently)")
        lines += name_lines

    term_lines = []
    for jp, en in glossary.get("terms", {}).items():
        if en and (not chunk_text or jp in chunk_text):
            term_lines.append(f"  {jp} → {en}")
    if term_lines:
        lines.append("# Terms")
        lines += term_lines

    if not lines:
        return "Character & term glossary: (none yet — romanize names consistently)."
    return "Character & term glossary — apply consistently:\n" + "\n".join(lines)


def _iter_pending_units(docs, retranslate_all):
    """Yield (doc, unit) for units that still need translating, grouped by doc."""
    for path, doc in docs:
        for u in doc["units"]:
            if retranslate_all or not u.get("tl", "").strip():
                yield doc, u


# A unit id is "<scene-prefix>:c<N>[...]" for command-list units (text/choice/
# ptext share the scene prefix) and "<File>:<i>:<field>" for database scalars.
# Stripping the trailing ":c<N>..." groups every line of one event page (one
# "scene") together so a scene is never split across requests unless it alone
# exceeds the chunk budget — which keeps within-scene references resolvable.
_SCENE_RE = re.compile(r":c\d+.*$")


def _scene_key(uid):
    return _SCENE_RE.sub("", uid)


def build_text_chunks(docs, max_units, retranslate_all):
    """Chunk pending units per source file, SCENE-ALIGNED.

    Each request holds whole scenes (event pages) in order, so the model sees a
    coherent run of dialogue with its speakers. A scene larger than max_units is
    split, and the split parts carry a short `context` tail of the preceding
    lines so the break doesn't sever local references.
    """
    chunks = []
    by_doc = {}
    for doc, u in _iter_pending_units(docs, retranslate_all):
        by_doc.setdefault(id(doc), (doc, []))[1].append(u)
    for _k, (doc, units) in by_doc.items():
        stem = os.path.splitext(os.path.basename(doc["meta"]["source_file"]))[0]
        # group consecutive units into scenes, preserving order
        scenes, cur_key = [], None
        for u in units:
            k = _scene_key(u["id"])
            if k != cur_key:
                scenes.append([]); cur_key = k
            scenes[-1].append(u)

        part = [0]
        buf = []

        def emit(sub, context=None):
            chunks.append({
                "custom_id": store.sanitize_id(f"{stem}__{part[0]:03d}"),
                "units": sub, "stem": stem, "context": context or [],
            })
            part[0] += 1

        def flush():
            if buf:
                emit(list(buf)); buf.clear()

        for sc in scenes:
            if len(sc) > max_units:
                flush()
                for s in range(0, len(sc), max_units):
                    ctx = sc[max(0, s - 3):s] if s > 0 else []
                    emit(sc[s:s + max_units], ctx)
            else:
                if buf and len(buf) + len(sc) > max_units:
                    flush()
                buf.extend(sc)
        flush()
    return chunks


def build_user_text(chunk):
    """Compact numbered list; returns (text, id_map[idx-1]=unit_id).

    Adds (a) a CONTEXT preamble of earlier lines from a split scene (reference
    only, not translated) and (b) `# scene:` separators so the model can tell
    where one event ends and the next begins inside a multi-scene chunk."""
    lines = ["Translate every numbered segment below. Return ONLY the JSON object."]
    ctx = chunk.get("context") or []
    if ctx:
        lines.append("\nCONTEXT — earlier lines of this SAME scene, for reference only; "
                     "do NOT translate or include these in the output:")
        for u in ctx:
            spk = u.get("ctx_speaker") or u.get("speaker") or ""
            shown = (u.get("tl") or u.get("src") or "").replace("\n", " ")
            lines.append(f"  ({spk}) {shown}" if spk else f"  {shown}")
        lines.append("")
    id_map = []
    last_scene = None
    for u in chunk["units"]:
        scene = u.get("ctx", "")
        if scene and scene != last_scene:
            lines.append(f"# scene: {scene}")
            last_scene = scene
        id_map.append(u["id"])
        idx = len(id_map)
        label = KIND_LABEL.get(u["kind"], u["kind"])
        spk = u.get("ctx_speaker") or u.get("speaker")
        tag = f"{label}; {spk}" if (u["kind"] == "text" and spk) else label
        lines.append(f"[{idx}] ({tag}) {u['src']}")
    lines.append('\nJSON object {"1":"...", ...} with a translation for every number above.')
    return "\n".join(lines), id_map


GAME_PROMPT_NAMES = ("game_prompt.md", "game_prompt.txt")


def load_game_prompt(store_dir):
    """Optional per-game prompt addendum (setting, tone, character voices, terms).

    Read from <store>/game_prompt.md (or .txt). Appended to the default system
    prompt as part of the cached prefix, so it costs almost nothing per request.
    """
    for name in GAME_PROMPT_NAMES:
        p = os.path.join(store_dir, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
    return ""


def _system_blocks(stable_extra, dynamic_text, game_prompt):
    """Build the system content blocks. The stable prefix (default rules +
    game prompt) is cached; the dynamic block (glossary) is left uncached."""
    blocks = [{"type": "text", "text": stable_extra}]
    if game_prompt:
        blocks.append({"type": "text", "text": "GAME-SPECIFIC GUIDANCE:\n" + game_prompt})
    # Cache the whole stable prefix. 1h TTL so async batch requests (which can be
    # processed minutes apart) still hit the cache instead of expiring at 5 min.
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    if dynamic_text is not None:
        blocks.append({"type": "text", "text": dynamic_text})
    return blocks


def build_request(chunk, model, glossary, game_prompt=""):
    user_text, id_map = build_user_text(chunk)
    n = len(id_map)
    max_tokens = min(32000, max(2000, n * 130))
    return {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            **_sampling_params(model),
            **_output_config(),
            "system": _system_blocks(SYSTEM_SHARED, _glossary_block(glossary, user_text), game_prompt),
            "messages": [{"role": "user", "content": user_text}],
        },
    }, id_map


def build_name_requests(glossary, retranslate_all, game_prompt="", max_units=200):
    """Requests that translate untranslated character names. Returns (reqs, name_maps)."""
    names = [k for k, v in glossary.get("names", {}).items()
             if (retranslate_all or store.name_needs_tl(v))]
    reqs, name_maps = [], {}
    for part in range(0, len(names), max_units):
        sub = names[part:part + max_units]
        cid = f"__names__{part // max_units:03d}"
        lines = ["Translate these character names. Return ONLY the JSON object."]
        for i, nm in enumerate(sub, 1):
            lines.append(f"[{i}] {nm}")
        reqs.append({
            "custom_id": cid,
            "params": {
                "model": MODEL_DEFAULT,  # overwritten by caller (sampling set there too)
                "max_tokens": max(500, len(sub) * 40),
                **_output_config(),
                "system": _system_blocks(NAME_SYSTEM, None, game_prompt),
                "messages": [{"role": "user", "content": "\n".join(lines)}],
            },
        })
        name_maps[cid] = sub
    return reqs, name_maps


# --------------------------------------------------------------------------
# response parsing
# --------------------------------------------------------------------------
def parse_json_object(text):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(s[i:j + 1])
        raise


# --------------------------------------------------------------------------
# anthropic client
# --------------------------------------------------------------------------
def get_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: set ANTHROPIC_API_KEY in the environment first.")
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("ERROR: pip install anthropic")
    return Anthropic()


# --------------------------------------------------------------------------
# build full request set (text + names)
# --------------------------------------------------------------------------
def build_all(store_dir, model, max_units, retranslate_all, include_names=True, include_text=True):
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    game_prompt = load_game_prompt(store_dir)
    requests, id_maps, name_maps = [], {}, {}

    if include_names:
        name_reqs, name_maps = build_name_requests(glossary, retranslate_all, game_prompt)
        for r in name_reqs:
            r["params"]["model"] = model
            r["params"].pop("temperature", None)
            r["params"].update(_sampling_params(model))
            requests.append(r)

    if include_text:
        for ch in build_text_chunks(docs, max_units, retranslate_all):
            req, idmap = build_request(ch, model, glossary, game_prompt)
            requests.append(req)
            id_maps[ch["custom_id"]] = idmap

    return docs, glossary, requests, id_maps, name_maps


# --------------------------------------------------------------------------
# apply results
# --------------------------------------------------------------------------
def apply_results(docs, glossary, results, id_maps, name_maps):
    unit_by_id = {}
    for _p, doc in docs:
        for u in doc["units"]:
            unit_by_id[u["id"]] = u
    applied = names_set = 0
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
                    continue
                jp = jp_list[idx - 1]
                if isinstance(v, dict):
                    en = (v.get("en") or "").strip().strip('"')
                    gender = (v.get("gender") or "").strip().lower()
                    if gender in ("male", "female"):
                        store.set_name(glossary, jp, en, gender)
                    elif en:
                        store.set_name(glossary, jp, en)
                elif isinstance(v, str):
                    store.set_name(glossary, jp, v.strip().strip('"'))
                else:
                    continue
                names_set += 1
            continue
        idmap = id_maps.get(cid, [])
        for k, v in obj.items():
            try:
                idx = int(k)
            except ValueError:
                continue
            if 1 <= idx <= len(idmap) and isinstance(v, str):
                u = unit_by_id.get(idmap[idx - 1])
                if u is not None:
                    u["tl"] = v
                    applied += 1
            else:
                errors.append(f"{cid}: index {k} out of range")
    store.save_docs(docs)
    # glossary is saved by the caller (it owns store_dir)
    return applied, names_set, errors


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_dryrun(store_dir, model, max_units, retranslate_all, show_sample=False):
    from collections import defaultdict
    docs, glossary, requests, id_maps, name_maps = build_all(store_dir, model, max_units, retranslate_all)
    counter = get_counter()
    src_tok = out_scaffold = dyn_in_tok = 0
    sample = None
    prefix_count = defaultdict(int)   # cached prefix text -> how many requests reuse it
    prefix_tok = {}                   # cached prefix text -> token count
    for req in requests:
        blocks = req["params"]["system"]
        cut = len(blocks)             # split system blocks at the cache breakpoint
        for i, b in enumerate(blocks):
            if "cache_control" in b:
                cut = i + 1
                break
        prefix = "".join(b["text"] for b in blocks[:cut])      # cached across requests
        dyn = "".join(b["text"] for b in blocks[cut:])         # uncached (glossary)
        prefix_count[prefix] += 1
        prefix_tok.setdefault(prefix, counter(prefix))
        usr = req["params"]["messages"][0]["content"]
        dyn_in_tok += counter(dyn) + counter(usr) + 8
        cid = req["custom_id"]
        n = len(id_maps.get(cid, name_maps.get(cid, [])))
        out_scaffold += counter("".join('"%d":"",' % i for i in range(1, n + 1)))
        if sample is None and cid not in name_maps:
            sample = usr
    for _p, doc in docs:
        for u in doc["units"]:
            if retranslate_all or not u.get("tl", "").strip():
                src_tok += counter(u["src"])

    # cached-prefix accounting: each distinct prefix is written once, then re-read.
    cache_write_tok = sum(prefix_tok[p] for p in prefix_count)
    cache_read_tok = sum(prefix_tok[p] * (prefix_count[p] - 1) for p in prefix_count)
    raw_in_tok = sum(prefix_tok[p] * prefix_count[p] for p in prefix_count) + dyn_in_tok

    n_text = sum(len(v) for k, v in id_maps.items())
    n_names = sum(len(v) for v in name_maps.values())
    gp = load_game_prompt(store_dir)
    print(f"requests={len(requests)}  text/data units={n_text}  names={n_names}  model={model}")
    print(f"game prompt: {'loaded (' + str(len(gp)) + ' chars)' if gp else 'none'}")
    print(f"cached prefix: {cache_write_tok:,} tok (written once, re-read {len(requests) - len(prefix_count)}x)")
    print(f"dynamic input (glossary+segments): {dyn_in_tok:,} tok | raw input w/o cache: {raw_in_tok:,} tok")
    print(f"JP source-only tokens: {src_tok:,}")
    pr = price_for(model)
    print(f"\nCost estimate for {model}  (in=${pr['in']}/M out=${pr['out']}/M, batch 50% off):")
    print("  (EN/JP output ratio 1.0 / 1.3 / 1.6)")
    for r in (1.0, 1.3, 1.6):
        out = int(src_tok * r) + out_scaffold
        # batch + prompt caching: prefix written once (cache_write), re-read cheap;
        # dynamic input at batch rate; output at batch rate.
        in_cached = (cache_write_tok / 1e6 * pr["cache_write"]
                     + cache_read_tok / 1e6 * pr["cache_read"]
                     + dyn_in_tok / 1e6 * pr["batch_in"])
        batch_cached = in_cached + out / 1e6 * pr["batch_out"]
        batch_nocache = raw_in_tok / 1e6 * pr["batch_in"] + out / 1e6 * pr["batch_out"]
        full = raw_in_tok / 1e6 * pr["in"] + out / 1e6 * pr["out"]
        print(f"  ratio {r}: out~{out:,}  BATCH+cache=${batch_cached:.2f}  "
              f"batch(no cache)=${batch_nocache:.2f}  non-batch=${full:.2f}")
    print(f"\nreasoning effort: {_EFFORT}  (the output estimate above assumes minimal "
          "reasoning; 'high'/'max' effort can MULTIPLY output tokens & cost).")
    print("(tiktoken o200k_base proxy; Anthropic's tokenizer differs ~10-15%. "
          "Cache hits in batch require the 1h-TTL prefix to stay warm. Run "
          "`python tooling/batches.py usage <batch_id>` after a run for the real billed tokens.)")
    if show_sample and sample:
        print("\n----- SAMPLE USER PROMPT -----\n" + sample[:2500])
    return 0


def cmd_submit(store_dir, model, max_units, retranslate_all):
    docs, glossary, requests, id_maps, name_maps = build_all(store_dir, model, max_units, retranslate_all)
    if not requests:
        sys.exit("Nothing to translate — every unit already has a translation. "
                 "Use --retranslate-all to redo them.")
    client = get_client()
    batch = client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id}  ({len(requests)} requests).")
    store.save_state(store_dir, {
        "batch_id": batch.id, "model": model, "store_dir": store_dir,
        "id_maps": id_maps, "name_maps": name_maps, "n_requests": len(requests),
        "created": str(getattr(batch, "created_at", "") or ""),
    })
    print(f"State saved. Track with: status / fetch / run")
    return 0


def cmd_status(store_dir):
    state = store.load_state(store_dir)
    if not state:
        sys.exit("No batch state — run submit first.")
    client = get_client()
    b = client.messages.batches.retrieve(state["batch_id"])
    print(f"batch {b.id} : {b.processing_status}")
    rc = getattr(b, "request_counts", None)
    if rc:
        print("  counts:", rc)
    return 0 if b.processing_status == "ended" else 2


def _fetch(client, state, store_dir):
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    results, errored = {}, []
    for r in client.messages.batches.results(state["batch_id"]):
        cid = r.custom_id
        res = r.result
        if res.type != "succeeded":
            detail = res.type
            err = getattr(res, "error", None)
            if err is not None:
                inner = getattr(err, "error", err)
                detail = f"{res.type} | {getattr(inner, 'type', '')}: {getattr(inner, 'message', '') or str(err)[:200]}"
            errored.append((cid, detail))
            continue
        text = "".join(getattr(b, "text", "") for b in res.message.content)
        try:
            results[cid] = parse_json_object(text)
        except Exception as e:
            errored.append((cid, f"parse_error: {e}"))
    applied, names_set, errs = apply_results(docs, glossary, results,
                                             state.get("id_maps", {}), state.get("name_maps", {}))
    store.save_glossary(store_dir, glossary)
    return applied, names_set, errored, errs


def cmd_fetch(store_dir):
    state = store.load_state(store_dir)
    if not state:
        sys.exit("No batch state — run submit first.")
    client = get_client()
    applied, names_set, errored, errs = _fetch(client, state, store_dir)
    print(f"Applied {applied} translations, {names_set} names.")
    for cid, why in errored[:30]:
        print(f"  ! request {cid}: {why}")
    for e in errs[:20]:
        print(f"  ! {e}")
    return 0


def _run_phase(client, store_dir, model, requests, id_maps, name_maps, poll, label):
    """Submit one batch, poll to completion, fetch into the store. Returns counts."""
    batch = client.messages.batches.create(requests=requests)
    print(f"[{label}] submitted batch {batch.id} ({len(requests)} requests).")
    store.save_state(store_dir, {
        "batch_id": batch.id, "model": model, "store_dir": store_dir,
        "id_maps": id_maps, "name_maps": name_maps, "n_requests": len(requests),
        "created": str(getattr(batch, "created_at", "") or ""), "phase": label,
    })
    state = store.load_state(store_dir)
    print(f"[{label}] polling (Ctrl-C is safe — resume with: fetch)...")
    while True:
        b = client.messages.batches.retrieve(state["batch_id"])
        print(f"  {time.strftime('%H:%M:%S')}  {b.processing_status}", flush=True)
        if b.processing_status == "ended":
            break
        time.sleep(poll)
    return _fetch(client, state, store_dir)


def cmd_run(store_dir, model, max_units, retranslate_all, poll=60):
    client = get_client()

    # Phase 1 — character names first, so the glossary is populated before the
    # dialogue batch references it (keeps prose-embedded names consistent).
    _docs, glossary, name_reqs, _idm, name_maps = build_all(
        store_dir, model, max_units, retranslate_all, include_names=True, include_text=False)
    if name_reqs:
        _a, names_set, errored, _e = _run_phase(
            client, store_dir, model, name_reqs, {}, name_maps, poll, "names")
        print(f"[names] {names_set} names translated ({len(errored)} errors).")

    # Phase 2 — dialogue / data, with the freshly filled glossary in the prompt.
    _docs, _g, requests, id_maps, _nm = build_all(
        store_dir, model, max_units, retranslate_all, include_names=False, include_text=True)
    if not requests:
        print("No text to translate.")
        return 0
    applied, names_set, errored, errs = _run_phase(
        client, store_dir, model, requests, id_maps, {}, poll, "text")
    print(f"[text] applied {applied} translations ({len(errored)} request errors).")
    for cid, why in errored[:30]:
        print(f"  ! {cid}: {why}")
    print("Next: python tooling/tl.py validate   then   python tooling/tl.py inject")
    return 0


# --------------------------------------------------------------------------
# offline self-test + validation
# --------------------------------------------------------------------------
def cmd_selftest(store_dir, model, max_units):
    docs, glossary, requests, id_maps, name_maps = build_all(store_dir, model, max_units, True)
    print(f"built {len(requests)} requests")
    results = {}
    for req in requests:
        cid = req["custom_id"]
        ln = len(id_maps.get(cid, name_maps.get(cid, [])))
        if cid in name_maps:
            results[cid] = {str(i): {"en": f"Name{i}", "gender": "female" if i % 2 else "male"}
                            for i in range(1, ln + 1)}
        else:
            # echo placeholders so masking integrity is exercised
            out = {}
            for i, uid in enumerate(id_maps[cid], 1):
                u = next(u for _p, d in docs for u in d["units"] if u["id"] == uid)
                phs = "".join(sorted(set(re.findall(r"⟦\d+⟧", u["src"]))))
                out[str(i)] = f"[EN {i}] {phs}"
            results[cid] = out
    applied, names_set, errs = apply_results(docs, glossary, results, id_maps, name_maps)
    store.save_glossary(store_dir, glossary)
    total = sum(len(d["units"]) for _p, d in docs)
    print(f"selftest: applied {applied}/{total} units, {names_set} names, {len(errs)} map errors")
    ok = applied == total and not errs
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# validation + targeted retry
# --------------------------------------------------------------------------
_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)


def hard_issues(u):
    """HARD (must-fix) problems for one translated unit. Empty short-circuits.
    Returns a list of issue codes: empty / identical / residual_jp / placeholder."""
    from . import codes
    tl = u.get("tl", "")
    if not tl.strip():
        return ["empty"]
    out = []
    if tl.strip() == u["src"].strip():
        out.append("identical")
    # HARD residual = real untranslated Japanese (hiragana/kanji). A lone ・ / ッ /
    # ー left inside English is cosmetic (see soft_warnings) — never a hard fail,
    # or retry would chase it forever.
    if codes.UNTRANSLATED_JP_RE.search(tl):
        out.append("residual_jp")
    if codes.placeholder_ids(u["src"]) != codes.placeholder_ids(tl):
        out.append("placeholder")
    return out


# Roles that mark a generic mob / unit rather than a real character. The
# misgender heuristic skips these — they are numerous, weakly gendered (default
# male), and rarely pronoun-referenced, so including them only adds false alarms.
_MOB_ROLE_RE = re.compile(r"bred soldier|monster|native soldier|generic|species|unit|mob|battle variant", re.I)


def _name_gender_forms(glossary):
    """[(jp_form, gender)] for glossed *named characters* with a definite gender,
    longest first — used to spot pronoun/gender contradictions in finished text.
    Auto-variant mob boxes (ゴブリンA, コカトリス[計測不能], …) are excluded."""
    from . import codes
    out = []
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g not in ("male", "female"):
            continue
        if _MOB_ROLE_RE.search(v.get("role", "") or ""):
            continue
        forms = [jp] + list(v.get("aliases") or [])
        for f in forms:
            # skip variant/suffix forms (ASCII letters, bracketed tags) and tiny strings
            if len(f) >= 2 and codes.has_jp(f) and not re.search(r"[A-Za-z\[\]]", f):
                out.append((f, g))
    out.sort(key=lambda x: -len(x[0]))
    return out


def _gender_form_sets(glossary):
    """{'male': {jp...}, 'female': {jp...}} over ALL glossed names (incl. monster
    species), used to suppress a misgender flag when a character of the pronoun's
    gender is also named in the line (the pronoun probably refers to *them*)."""
    from . import codes
    out = {"male": set(), "female": set()}
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g not in out:
            continue
        for f in [jp] + list(v.get("aliases") or []):
            if len(f) >= 2 and codes.has_jp(f):
                out[g].add(f)
    return out


def soft_warnings(u, name_forms, opp_forms=None):
    """Heuristic REVIEW warnings (not failures): possible misgender + extreme
    over-expansion. Conservative — only fires on clear signals."""
    from . import codes
    tl = u.get("tl", "")
    warns = []
    if not tl.strip():
        return warns
    raw = u.get("raw", "") or u.get("src", "")
    has_he, has_she = bool(_HE_RE.search(tl)), bool(_SHE_RE.search(tl))
    if has_he or has_she:
        male_named = bool(opp_forms and any(m in raw for m in opp_forms["male"]))
        female_named = bool(opp_forms and any(f in raw for f in opp_forms["female"]))
        for jp, g in name_forms:
            if jp in raw:
                # Only flag when NO character of the pronoun's gender is also named
                # in the line — otherwise the he/him (or she/her) most likely refers
                # to that other character (e.g. "the Lizardman shoves his cock...").
                if g == "female" and has_he and not has_she and not male_named:
                    warns.append(f"possible misgender: '{jp}' is female but tl uses he/him")
                elif g == "male" and has_she and not has_he and not female_named:
                    warns.append(f"possible misgender: '{jp}' is male but tl uses she/her")
                break
    sv = len(codes._PH_RE.sub("", u.get("src", "")).strip())
    tv = len(codes._PH_RE.sub("", tl).strip())
    if sv >= 8 and tv > sv * 6:
        warns.append(f"over-expansion: tl {tv} chars vs src {sv}")
    # leftover cosmetic kana/symbol (not real untranslated JP): surface for review.
    if codes.JP_RE.search(tl) and not codes.UNTRANSLATED_JP_RE.search(tl):
        leftover = "".join(sorted(set(ch for ch in tl if codes.JP_RE.search(ch) and ch not in "・ー")))
        if leftover:
            warns.append(f"leftover kana/symbol {leftover!r} (cosmetic; ッ/っ auto-stripped on inject)")
    return warns


def cmd_validate(store_dir, max_issues=25):
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    name_forms = _name_gender_forms(glossary)
    opp_forms = _gender_form_sets(glossary)
    total = done = empty = 0
    tally = {"identical": 0, "residual_jp": 0, "placeholder": 0}
    hard_list, warn_list = [], []
    for _p, doc in docs:
        for u in doc["units"]:
            total += 1
            issues = hard_issues(u)
            if issues == ["empty"]:
                empty += 1
                continue
            done += 1
            for code in issues:
                tally[code] = tally.get(code, 0) + 1
                detail = ""
                if code == "residual_jp":
                    detail = f": {u['tl'][:30]!r}"
                elif code == "placeholder":
                    from . import codes
                    detail = (f": src{sorted(codes.placeholder_ids(u['src']))} "
                              f"tl{sorted(codes.placeholder_ids(u['tl']))}")
                hard_list.append(f"[{code}] {u['id']}{detail}")
            for w in soft_warnings(u, name_forms, opp_forms):
                warn_list.append(f"{u['id']}: {w}")
    names_total = len(glossary.get("names", {}))
    names_done = sum(1 for v in glossary.get("names", {}).values() if store.name_en(v))
    print(f"VALIDATION  files={len(docs)} units={total}")
    print(f"  translated         : {done} ({100.0 * done / total if total else 0:.1f}%)")
    print(f"  untranslated       : {empty}")
    print(f"  identical-to-source: {tally['identical']}")
    print(f"  residual-Japanese  : {tally['residual_jp']}")
    print(f"  placeholder-broken : {tally['placeholder']}")
    print(f"  names translated   : {names_done}/{names_total}")
    print(f"  soft warnings      : {len(warn_list)} (misgender / over-expansion — review)")
    if hard_list:
        print("  -- hard issues (fix with: python tooling/tl.py retry) --")
        for s in hard_list[:max_issues]:
            print("   - " + s)
        if len(hard_list) > max_issues:
            print(f"   ... ({len(hard_list) - max_issues} more)")
    if warn_list:
        print("  -- soft warnings (review) --")
        for s in warn_list[:max_issues]:
            print("   ? " + s)
        if len(warn_list) > max_issues:
            print(f"   ... ({len(warn_list) - max_issues} more)")
    # Fail only on hard, fixable problems (identical is soft-listed, not a failure).
    hard_fail = empty + tally["residual_jp"] + tally["placeholder"]
    return 0 if hard_fail == 0 else 1


def build_retry_chunks(docs, fail_ids, max_units):
    """One (or more) chunk per scene that contains a failing unit: re-translate
    the failing units, supplying the scene's already-translated lines as context
    so the fix stays consistent with its surroundings."""
    chunks = []
    for _p, doc in docs:
        stem = os.path.splitext(os.path.basename(doc["meta"]["source_file"]))[0]
        scenes = {}
        for u in doc["units"]:
            scenes.setdefault(_scene_key(u["id"]), []).append(u)
        part = 0
        for _key, units in scenes.items():
            fails = [u for u in units if u["id"] in fail_ids]
            if not fails:
                continue
            context = [u for u in units if u["id"] not in fail_ids and u.get("tl", "").strip()][:12]
            for s in range(0, len(fails), max_units):
                chunks.append({
                    "custom_id": store.sanitize_id(f"{stem}__retry{part:03d}"),
                    "units": fails[s:s + max_units], "stem": stem, "context": context,
                })
                part += 1
    return chunks


def cmd_retry(store_dir, model, max_units, poll=60, max_rounds=2):
    """Re-translate every unit that fails hard validation (empty / residual-JP /
    placeholder mismatch / identical), with scene context, up to N rounds."""
    client = get_client()
    glossary = store.load_glossary(store_dir)
    game_prompt = load_game_prompt(store_dir)
    for rnd in range(1, max_rounds + 1):
        docs = store.load_docs(store_dir)
        fail_ids = {u["id"] for _p, doc in docs for u in doc["units"] if hard_issues(u)}
        if not fail_ids:
            print("[retry] nothing failing — store is clean.")
            return 0
        chunks = build_retry_chunks(docs, fail_ids, max_units)
        requests, id_maps = [], {}
        for ch in chunks:
            req, idmap = build_request(ch, model, glossary, game_prompt)
            requests.append(req)
            id_maps[ch["custom_id"]] = idmap
        print(f"[retry round {rnd}/{max_rounds}] {len(fail_ids)} failing units -> {len(requests)} requests.")
        _run_phase(client, store_dir, model, requests, id_maps, {}, poll, f"retry{rnd}")
    docs = store.load_docs(store_dir)
    still = sum(1 for _p, doc in docs for u in doc["units"] if hard_issues(u))
    print(f"[retry] done. {still} units still failing — run `validate` to inspect.")
    return 0
