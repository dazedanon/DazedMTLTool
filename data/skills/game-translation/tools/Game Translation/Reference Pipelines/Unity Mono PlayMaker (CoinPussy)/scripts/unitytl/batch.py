#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
batch.py — translate the store with Claude via the Anthropic Message Batches API.

Cost shape (why it is built this way):
  * ONE cached system prefix (localization rules + the per-game bible) shared by
    every request, with a 1h TTL so async batch requests processed minutes apart
    still hit the cache instead of expiring at the 5-minute default.
  * The glossary is the uncached tail, so editing it never invalidates the prefix.
  * Batch mode is a further 50% off, and reasoning effort is pinned to `low`:
    straight translation gains nothing from deep reasoning and higher effort
    multiplies output tokens.
  * Requests carry short integer indices, never the long unit ids — the id map is
    kept locally and reattached on fetch.

Two phases: character names first (they land in the glossary), then all text with
the filled glossary in the prompt, so a name inside prose matches its name box.
"""

import json
import os
import re
import sys
import time

from . import codes, layout, store

MODEL_DEFAULT = "claude-opus-5"

# USD per 1M tokens, transcribed from the published pricing table (checked
# 2026-08-18). Columns are exactly the ones Anthropic publishes: base input,
# 5-minute cache write, 1-hour cache write, cache hits/refreshes, output.
# Longest key first — "claude-opus-4-8" must not be matched by "claude-opus-4".
PRICE_BY_MODEL = {
    "claude-fable-5":    {"in": 10.0, "w5m": 12.50, "w1h": 20.0, "read": 1.00, "out": 50.0},
    "claude-mythos-5":   {"in": 10.0, "w5m": 12.50, "w1h": 20.0, "read": 1.00, "out": 50.0},
    "claude-opus-5":     {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-8":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-7":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-6":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-opus-4-5":   {"in": 5.0, "w5m": 6.25, "w1h": 10.0, "read": 0.50, "out": 25.0},
    "claude-sonnet-5":   {"in": 2.0, "w5m": 2.50, "w1h": 4.0, "read": 0.20, "out": 10.0},
    "claude-sonnet-4-6": {"in": 3.0, "w5m": 3.75, "w1h": 6.0, "read": 0.30, "out": 15.0},
    "claude-sonnet-4-5": {"in": 3.0, "w5m": 3.75, "w1h": 6.0, "read": 0.30, "out": 15.0},
    "claude-haiku-4-5":  {"in": 1.0, "w5m": 1.25, "w1h": 2.0, "read": 0.10, "out": 5.0},
}

# Batch is a 50% discount, and the pricing docs state the cache multipliers "stack
# with other pricing modifiers, including the Batch API discount" — so every column
# halves, cache writes and reads included. Cross-checks against the published batch
# table exactly (Sonnet 5 $1/$5, Opus 5 $2.50/$12.50, Haiku 4.5 $0.50/$2.50).
BATCH_DISCOUNT = 0.5

# Measured against the real run (msgbatch_01Diiv…, Sonnet 5, 118 requests, this
# game's 5,680 units):
#
#   input   961,930 estimated vs   960,000 actual   — x0.998
#   output  103,383 estimated vs   147,669 actual   — x1.43
#
# So the tiktoken proxy tracks input almost exactly, despite Sonnet 5 using the
# post-4.7 tokenizer that the pricing docs say yields ~30% more tokens than 4.6-era
# models. Do NOT inflate the input estimate for those models on that basis; it did
# not show up here. The real error is on OUTPUT: the ratios below are applied to
# source tokens, and this run came in at an effective 2.36 including the JSON
# scaffolding the model emits around each segment. Read ratio 1.6 as the floor for
# chatty content, not the ceiling.
MEASURED_OUTPUT_RATIO = 2.36


def price_for(model, batch=False):
    """Published per-MTok rates for a model, optionally at the batch discount."""
    m = (model or "").lower()
    pr = None
    for key in sorted(PRICE_BY_MODEL, key=len, reverse=True):
        if key in m:
            pr = PRICE_BY_MODEL[key]
            break
    if pr is None:
        pr = PRICE_BY_MODEL["claude-opus-5"]
    if not batch:
        return dict(pr)
    return {k: v * BATCH_DISCOUNT for k, v in pr.items()}


# Models that reject the sampling params (temperature/top_p/top_k) with a 400:
# Opus 4.7 and up, Opus 5, Sonnet 5, Fable 5 all retired them for adaptive thinking.
_NO_SAMPLING_RE = re.compile(r"(opus-(?:5|4-(?:[7-9]\b|[1-9]\d))|sonnet-5|fable-5|mythos-5)", re.I)


def _sampling_params(model):
    return {} if _NO_SAMPLING_RE.search(model or "") else {"temperature": 0}


# Translation is high-volume and direct; `low` is the right effort. The API default
# is `high`, which spends "as many tokens as needed" and inflates cost for no gain.
EFFORT_DEFAULT = "low"
_EFFORT = EFFORT_DEFAULT
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}


def set_effort(effort):
    global _EFFORT
    if effort:
        _EFFORT = effort


def _output_config():
    if _EFFORT and _EFFORT in _EFFORT_LEVELS and _EFFORT != "high":
        return {"output_config": {"effort": _EFFORT}}
    return {}


KIND_LABEL = {
    "hdialogue": "H-scene subtitle (the heroine, mid-sex)",
    "narration": "live-broadcast narrator commentary",
    "dialogue": "story dialogue",
    "bark": "in-game voice line",
    "comment": "live-stream viewer comment",
    "speaker": "speaker name (name box)",
    "subtitle": "on-screen dialogue / popup line",
    "message": "system or popup message",
    "screen": "on-screen panel / tutorial text",
    "ui": "UI label / button",
    "stagename": "stage title",
    "stagehint": "stage blurb",
    "controlhint": "control hint",
}

SYSTEM_SHARED = (
    "You are an expert Japanese-to-English eroge (adult game) translator and localizer. You "
    "translate dialogue, narration, on-screen messages and menu/UI text for a Japanese Unity "
    "game into natural, fluent, idiomatic English.\n\n"
    "You receive a numbered list of short segments from ONE part of the game. Each is tagged "
    "with its role (H-scene subtitle, story dialogue, viewer comment, UI label, …) and, where "
    "known, the speaker. A character & term glossary follows in the next block — read it first "
    "and apply ALL of it.\n\n"
    "OUTPUT FORMAT\n"
    "- Translate EVERY numbered segment. Output ONLY a JSON object mapping each number (as a "
    'string) to its English translation, e.g. {"1":"...","2":"..."}. No preamble, notes, '
    "romaji, or Japanese in the output.\n\n"
    "PROTECTED CODES & LAYOUT\n"
    "- Tokens like ⟦0⟧, ⟦1⟧ are game markup. Keep each one EXACTLY as written and in the "
    "SAME relative position. Never translate, renumber, reorder, add, or drop them.\n"
    "- Keep the SAME NUMBER OF LINES as the source. These strings go into fixed-size subtitle "
    "and UI boxes, so a 2-line source must come back as 2 lines. Break at a natural phrase "
    "boundary and keep the lines roughly balanced.\n"
    "- A full-width space (　) inside a line is a PACING GAP between separate gasps or "
    "phrases, not indentation. Render it as a normal space (or keep it) — do not delete the "
    "gap and run the phrases together. A run of full-width spaces used to centre or space out "
    "a heading (　　　, or エ　ロ　ス　ギ) is layout: keep comparable spacing.\n"
    "- … and ～ are punctuation — keep them. ♪ ♫ ♥ ☆ ♡ and similar are tone markers — keep them "
    "where they fall, they carry the character's mood.\n\n"
    "QUALITY & CONSISTENCY\n"
    "- Prefer natural, fluent English over literal gloss. Preserve tone (comedic / panicked / "
    "smug / broken) and each speaker's register from the glossary. Use the SAME English name "
    "for a character every time.\n"
    "- Don't merge or split segments. Keep UI labels terse — a button that says 4 characters in "
    "Japanese must not become a sentence.\n\n"
    "CHARACTERS, GENDER & PRONOUNS\n"
    "- Japanese omits pronouns constantly; infer the subject from context and the glossary. "
    "Resolve 彼 / 彼女 / あいつ / こいつ / コイツ to match the referenced character's stated gender.\n"
    "- If a character refers to herself by her own name as a stylistic trait, keep that.\n\n"
    "HONORIFICS & NAMES\n"
    "- Preserve Japanese honorifics: -san, -kun, -chan, -sama, -senpai, -sensei.\n"
    "- Follow the glossary's romanization exactly; never re-romanize a glossed name.\n\n"
    "ADULT CONTENT (this is an 18+ game — do NOT censor, soften, or euphemize unless the "
    "Japanese itself is euphemistic, and never moralize)\n"
    "- Translate explicit sexual content directly and vividly, matching the source register "
    "(clinical / vulgar / colloquial / babyish). Keep dominant speech dominant and submissive "
    "begging submissive.\n"
    "- Erotic onomatopoeia (ぴちゃ, ぐちゅ, じゅぽ, くちゅ, ぬぷ, くぱㅁ …) → evocative English "
    "sounds. Moans and climax cues (あぁ, んっ, はぁ, イく, イっちゃう …) → render expressively: "
    "\"Aah...\", \"Ngh...\", \"I'm cumming...\", \"I'm gonna cum...\".\n"
    "- Slurred, broken speech (ひゃっ, いぐ, だして, あ\"っ) is deliberate: the character's mouth or mind "
    "is not working. Render it as slurred English (\"c-cummin'\", \"nnghaa\"), not as clean prose.\n\n"
    "EXAMPLE\n"
    "Input:\n"
    "[1] (UI label) もどる\n"
    "[2] (story dialogue; 受付ちゃん) いらっしゃいませ～！お客様！\n"
    "[3] (H-scene subtitle (the heroine, mid-sex); 受付ちゃん) やめっ♥　やめっっ♥\n"
    "あ…げんかっ♥　げんかいいっ♥\n"
    "Output:\n"
    '{"1":"Back","2":"Welcome, sir! Right this way!",'
    '"3":"Stop it♥ Stop—♥\\nI-I can\'t♥ I\'m at my limit♥"}'
)

NAME_SYSTEM = (
    "You are localizing an adult Japanese Unity game (a casino coin-pusher eroge). For each "
    "Japanese CHARACTER NAME or SPEAKER LABEL below, give the clean, consistent English form "
    "that will appear in dialogue and in the name box, plus your best guess of the character's "
    "gender (male / female / unknown). Keep it short — these render in a narrow name box. "
    "Descriptive labels (roles rather than proper names) should become natural English role "
    "names, not romaji.\n"
    "Output ONLY a JSON object mapping each number (as a string) to an object "
    '{"en": "<english>", "gender": "male|female|unknown"}, e.g. '
    '{"1":{"en":"Receptionist","gender":"female"},"2":{"en":"Manager","gender":"male"}}.'
)


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

    All character entries are always included (small, high value, and the gender
    field drives pronoun resolution). Terms are filtered to those that actually
    occur in this chunk so the block stays lean.
    """
    lines, name_lines = [], []
    for jp, v in glossary.get("names", {}).items():
        en = store.name_en(v)
        if not en:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing documentation and is deliberately not sent.
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


def _unit_scene(u):
    """Grouping key: the CSV scene family, else the FSM/GameObject context."""
    return u.get("scene") or u.get("ctx") or ""


def _iter_pending(docs, retranslate_all):
    for _p, doc in docs:
        for u in doc["units"]:
            if retranslate_all or not (u.get("tl") or "").strip():
                yield doc, u


def build_text_chunks(docs, max_units, retranslate_all):
    """Chunk pending units per bucket, scene-aligned and in source order.

    Whole scenes travel together so the model sees a coherent run of dialogue. A
    scene larger than `max_units` is split, and each split part carries a short
    context tail of the preceding lines so the break doesn't sever a reference.
    """
    chunks = []
    by_doc = {}
    for doc, u in _iter_pending(docs, retranslate_all):
        by_doc.setdefault(id(doc), (doc, []))[1].append(u)
    for _k, (doc, units) in sorted(by_doc.items(), key=lambda kv: kv[1][0]["meta"]["bucket"]):
        bucket = doc["meta"]["bucket"]
        scenes, cur = [], object()
        for u in units:
            key = _unit_scene(u)
            if key != cur:
                scenes.append([])
                cur = key
            scenes[-1].append(u)

        part = [0]
        buf = []

        def emit(sub, context=None):
            chunks.append({"custom_id": store.sanitize_id(f"{bucket}__{part[0]:03d}"),
                           "units": sub, "bucket": bucket, "context": context or []})
            part[0] += 1

        def flush():
            if buf:
                emit(list(buf))
                buf.clear()

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


def _tag(u):
    label = KIND_LABEL.get(u["kind"], u["kind"])
    spk = (u.get("speaker") or "").strip()
    if spk:
        return f"{label}; {spk}"
    obj = ""
    for site in (u.get("sites") or [])[:1]:
        obj = site.get("obj") or ""
    return f"{label}; {obj}" if obj else label


def build_user_text(chunk):
    """Compact numbered list; returns (text, id_map) with id_map[idx-1] = unit id."""
    lines = ["Translate every numbered segment below. Return ONLY the JSON object."]
    ctx = chunk.get("context") or []
    if ctx:
        lines.append("\nCONTEXT — earlier lines of this SAME scene, for reference only; "
                     "do NOT translate or include these in the output:")
        for u in ctx:
            spk = (u.get("speaker") or "").strip()
            shown = (u.get("tl") or u.get("src") or "").replace("\n", " / ")
            lines.append(f"  ({spk}) {shown}" if spk else f"  {shown}")
        lines.append("")
    id_map = []
    last_scene = None
    for u in chunk["units"]:
        scene = _unit_scene(u)
        if scene and scene != last_scene:
            lines.append(f"# scene: {scene}")
            last_scene = scene
        id_map.append(u["id"])
        lines.append(f"[{len(id_map)}] ({_tag(u)}) {u['src']}")
    lines.append('\nJSON object {"1":"...", ...} with a translation for every number above.')
    return "\n".join(lines), id_map


def _system_blocks(stable_extra, dynamic_text, game_prompt):
    """Stable prefix (rules + game bible) is cached; the glossary tail is not."""
    blocks = [{"type": "text", "text": stable_extra}]
    if game_prompt:
        blocks.append({"type": "text", "text": "GAME-SPECIFIC GUIDANCE:\n" + game_prompt})
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    if dynamic_text is not None:
        blocks.append({"type": "text", "text": dynamic_text})
    return blocks


def build_request(chunk, model, glossary, game_prompt=""):
    user_text, id_map = build_user_text(chunk)
    n = len(id_map)
    return {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": min(16000, max(2000, n * 160)),
            **_sampling_params(model),
            **_output_config(),
            "system": _system_blocks(SYSTEM_SHARED,
                                     _glossary_block(glossary, user_text), game_prompt),
            "messages": [{"role": "user", "content": user_text}],
        },
    }, id_map


def build_name_requests(glossary, model, retranslate_all, game_prompt="", max_units=200):
    names = [k for k, v in glossary.get("names", {}).items()
             if (retranslate_all or store.name_needs_tl(v))]
    reqs, name_maps = [], {}
    for part in range(0, len(names), max_units):
        sub = names[part:part + max_units]
        cid = f"__names__{part // max_units:03d}"
        lines = ["Translate these character names / speaker labels. Return ONLY the JSON object."]
        for i, nm in enumerate(sub, 1):
            lines.append(f"[{i}] {nm}")
        reqs.append({
            "custom_id": cid,
            "params": {
                "model": model,
                "max_tokens": max(500, len(sub) * 40),
                **_sampling_params(model),
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
def _escape_stray_quotes(s):
    """Escape `"` that appears inside a JSON string where it cannot legally close it.

    The source uses an ASCII double-quote as a dakuten on slurred moans (あ"っ), and
    the model carries it into the English ("Aa"h...♥"), which breaks the object. A
    quote only ends a value when the next non-space character is , or }, and only
    ends a key when it is :. Anything else is literal text and gets escaped.
    """
    out = []
    i, n = 0, len(s)
    in_str = is_value = False
    while i < n:
        c = s[i]
        if not in_str:
            out.append(c)
            if c == '"':
                in_str = True
                j = len(out) - 2
                while j >= 0 and out[j] in " \t\r\n":
                    j -= 1
                is_value = j >= 0 and out[j] == ":"
            i += 1
        elif c == "\\":
            out.append(c)
            if i + 1 < n:
                out.append(s[i + 1])
            i += 2
        elif c == '"':
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            nxt = s[j] if j < n else ""
            if (is_value and nxt in ",}") or (not is_value and nxt == ":"):
                out.append(c)
                in_str = False
            else:
                out.append('\\"')
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _balanced_objects(s):
    """Every top-level {...} span, so a reply that emits a draft, second-guesses
    itself ("Wait, I need to output all 53...") and then emits the real object
    yields both instead of one unparseable blob."""
    spans, depth, start = [], 0, None
    in_str = esc = False
    for i, c in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0 and start is not None:
                spans.append(s[start:i + 1])
                start = None
    return spans


def parse_json_object(text):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = re.sub(r"```$", "", s).strip()
    try:
        return json.loads(s)
    except Exception:
        pass
    # Repair stray quotes first: the brace scan below relies on string boundaries.
    repaired = _escape_stray_quotes(s)
    try:
        return json.loads(repaired)
    except Exception:
        pass
    best = None
    for span in _balanced_objects(repaired):
        try:
            obj = json.loads(span)
        except Exception:
            continue
        if isinstance(obj, dict) and (best is None or len(obj) > len(best)):
            best = obj      # a self-corrected reply's real answer is the fuller one
    if best is not None:
        return best
    raise ValueError("no parseable JSON object in response")


def get_client():
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("ERROR: pip install anthropic")
    # A bare client also resolves an `ant auth login` profile, so an unset
    # ANTHROPIC_API_KEY is not necessarily an error.
    return Anthropic()


def build_all(store_dir, model, max_units, retranslate_all,
              include_names=True, include_text=True):
    docs = store.load_docs(store_dir)
    glossary = store.load_glossary(store_dir)
    game_prompt = store.load_game_prompt(store_dir)
    requests, id_maps, name_maps = [], {}, {}

    if include_names:
        name_reqs, name_maps = build_name_requests(glossary, model, retranslate_all, game_prompt)
        requests.extend(name_reqs)

    if include_text:
        for ch in build_text_chunks(docs, max_units, retranslate_all):
            req, idmap = build_request(ch, model, glossary, game_prompt)
            requests.append(req)
            id_maps[ch["custom_id"]] = idmap

    return docs, glossary, requests, id_maps, name_maps


def apply_results(docs, glossary, results, id_maps, name_maps, persist=True):
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
                    else:
                        continue
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
    if persist:
        store.save_docs(docs)
    return applied, names_set, errors


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_dryrun(store_dir, model, max_units, retranslate_all, show_sample=False):
    from collections import defaultdict
    docs, glossary, requests, id_maps, name_maps = build_all(
        store_dir, model, max_units, retranslate_all)
    if not requests:
        print("Nothing pending — every unit already has a translation "
              "(use --retranslate-all to redo them).")
        return 0
    counter = get_counter()
    src_tok = out_scaffold = dyn_in_tok = 0
    sample = None
    prefix_count = defaultdict(int)
    prefix_tok = {}
    for req in requests:
        blocks = req["params"]["system"]
        cut = len(blocks)
        for i, b in enumerate(blocks):
            if "cache_control" in b:
                cut = i + 1
                break
        prefix = "".join(b["text"] for b in blocks[:cut])
        dyn = "".join(b["text"] for b in blocks[cut:])
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
            if retranslate_all or not (u.get("tl") or "").strip():
                src_tok += counter(u["src"])

    cache_write_tok = sum(prefix_tok[p] for p in prefix_count)
    cache_read_tok = sum(prefix_tok[p] * (prefix_count[p] - 1) for p in prefix_count)
    raw_in_tok = sum(prefix_tok[p] * prefix_count[p] for p in prefix_count) + dyn_in_tok

    n_text = sum(len(v) for v in id_maps.values())
    n_names = sum(len(v) for v in name_maps.values())
    gp = store.load_game_prompt(store_dir)
    print(f"requests={len(requests)}  text units={n_text}  names={n_names}  model={model}")
    print(f"buckets: " + ", ".join(f"{d['meta']['bucket']}={len(d['units'])}" for _p, d in docs))
    print(f"game prompt: {'loaded (' + str(len(gp)) + ' chars)' if gp else 'NONE — write tl/game_prompt.md'}")
    print(f"glossary: {len(glossary.get('names', {}))} names "
          f"({sum(1 for v in glossary.get('names', {}).values() if store.name_en(v))} translated), "
          f"{len(glossary.get('terms', {}))} terms")
    print(f"cached prefix: {cache_write_tok:,} tok "
          f"(written {len(prefix_count)}x, re-read {len(requests) - len(prefix_count)}x)")
    print(f"dynamic input (glossary+segments): {dyn_in_tok:,} tok | "
          f"raw input w/o cache: {raw_in_tok:,} tok")
    print(f"JP source-only tokens: {src_tok:,}")
    live, bat = price_for(model), price_for(model, batch=True)
    print(f"\nCost estimate for {model}  "
          f"(in=${live['in']}/M out=${live['out']}/M, batch {int(BATCH_DISCOUNT * 100)}% off):")
    print("  EN/JP output-token ratio, against the four ways of running this job.")
    print("  Batch halves EVERY token class, cache writes and reads included.")
    print(f"  {'ratio':>6} {'out tok':>10} | {'batch+cache':>12} {'batch only':>11} "
          f"| {'live+cache':>11} {'live only':>10}")
    for r in (1.0, 1.3, 1.6):
        out = int(src_tok * r) + out_scaffold
        # Live requests fire back-to-back, so the default 5-minute TTL suffices and
        # its write rate is cheaper than the 1h TTL the async batch path needs.
        live_cached = (cache_write_tok / 1e6 * live["w5m"]
                       + cache_read_tok / 1e6 * live["read"]
                       + dyn_in_tok / 1e6 * live["in"]
                       + out / 1e6 * live["out"])
        batch_cached = (cache_write_tok / 1e6 * bat["w1h"]
                        + cache_read_tok / 1e6 * bat["read"]
                        + dyn_in_tok / 1e6 * bat["in"]
                        + out / 1e6 * bat["out"])
        batch_nocache = raw_in_tok / 1e6 * bat["in"] + out / 1e6 * bat["out"]
        live_nocache = raw_in_tok / 1e6 * live["in"] + out / 1e6 * live["out"]
        print(f"  {r:>6} {out:>10,} | ${batch_cached:>11.2f} ${batch_nocache:>10.2f} "
              f"| ${live_cached:>10.2f} ${live_nocache:>9.2f}")
    measured = int(src_tok * MEASURED_OUTPUT_RATIO) + out_scaffold
    m_cost = (cache_write_tok / 1e6 * bat["w1h"] + cache_read_tok / 1e6 * bat["read"]
              + dyn_in_tok / 1e6 * bat["in"] + measured / 1e6 * bat["out"])
    print(f"  {MEASURED_OUTPUT_RATIO:>6} {measured:>10,} | ${m_cost:>11.2f} "
          f"{'':>11} |{'':>12} {'':>10}   <- measured on the real run")
    print(f"\nreasoning effort: {_EFFORT}  (the output estimate assumes minimal reasoning; "
          "'high'/'max' can MULTIPLY output tokens and cost).")
    print("(tiktoken o200k_base proxy; Anthropic's tokenizer differs ~10-15%.)")
    if show_sample and sample:
        print("\n----- SAMPLE USER PROMPT -----\n" + sample[:3000])
    return 0


def estimate_input_tokens(requests):
    """tiktoken count of everything sent, so `usage` can compare it to reality and
    expose how far off the proxy is for this model's tokenizer."""
    counter = get_counter()
    total = 0
    for req in requests:
        for b in req["params"]["system"]:
            total += counter(b["text"])
        total += counter(req["params"]["messages"][0]["content"]) + 8
    return total


def cmd_submit(store_dir, model, max_units, retranslate_all):
    docs, glossary, requests, id_maps, name_maps = build_all(
        store_dir, model, max_units, retranslate_all)
    if not requests:
        sys.exit("Nothing to translate. Use --retranslate-all to redo everything.")
    client = get_client()
    batch = client.messages.batches.create(requests=requests)
    print(f"Submitted batch {batch.id}  ({len(requests)} requests).")
    store.save_state(store_dir, {
        "batch_id": batch.id, "model": model, "store_dir": store_dir,
        "id_maps": id_maps, "name_maps": name_maps, "n_requests": len(requests),
        "est_input_tokens": estimate_input_tokens(requests),
        "created": str(getattr(batch, "created_at", "") or "")})
    print("State saved. Track with: status / fetch")
    return 0


def cmd_status(store_dir):
    state = store.load_state(store_dir)
    if not state:
        sys.exit("No batch state — run submit first.")
    b = get_client().messages.batches.retrieve(state["batch_id"])
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
        cid, res = r.custom_id, r.result
        if res.type != "succeeded":
            detail = res.type
            err = getattr(res, "error", None)
            if err is not None:
                inner = getattr(err, "error", err)
                detail = (f"{res.type} | {getattr(inner, 'type', '')}: "
                          f"{getattr(inner, 'message', '') or str(err)[:200]}")
            errored.append((cid, detail))
            continue
        msg = res.message
        if getattr(msg, "stop_reason", None) == "refusal":
            errored.append((cid, "refusal"))
            continue
        text = "".join(getattr(b, "text", "") for b in msg.content)
        try:
            results[cid] = parse_json_object(text)
        except Exception as e:
            errored.append((cid, f"parse_error: {e}"))
    applied, names_set, errs = apply_results(
        docs, glossary, results, state.get("id_maps", {}), state.get("name_maps", {}))
    store.save_glossary(store_dir, glossary)
    return applied, names_set, errored, errs


def _live_one(client, req, max_attempts, log):
    """Send one request synchronously, retrying transient failures.

    A parse failure is retried too: the response is sampled, so a reply that broke
    its own JSON can come back clean, and that is cheaper than a whole second pass.
    """
    cid, params = req["custom_id"], req["params"]
    delay = 2.0
    last = "unknown"
    for attempt in range(1, max_attempts + 1):
        try:
            msg = client.messages.create(**params)
            if getattr(msg, "stop_reason", None) == "refusal":
                return cid, None, "refusal", None      # never retried, never succeeds
            text = "".join(getattr(b, "text", "") for b in msg.content)
            return cid, parse_json_object(text), None, msg.usage
        except Exception as e:
            status = getattr(e, "status_code", None)
            name = type(e).__name__
            last = f"{name}: {str(e)[:160]}"
            fatal = status in (400, 401, 403, 404)
            if fatal or attempt == max_attempts:
                return cid, None, last, None
            wait = delay
            hdrs = getattr(getattr(e, "response", None), "headers", None)
            if hdrs:
                try:
                    wait = max(wait, float(hdrs.get("retry-after", 0)))
                except (TypeError, ValueError):
                    pass
            log(f"  {cid}: {name} (attempt {attempt}/{max_attempts}), retrying in {wait:.0f}s")
            time.sleep(wait)
            delay = min(delay * 2, 60.0)
    return cid, None, last, None


def cmd_live(store_dir, model, max_units, retranslate_all, concurrency=4, max_attempts=5):
    """Translate through the synchronous Messages API instead of the Batches API.

    Costs 2x batch, but returns in minutes with visible per-request progress. Worth
    it for a small remainder, or when a batch is sitting queued.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    docs, glossary, requests, id_maps, name_maps = build_all(
        store_dir, model, max_units, retranslate_all)
    if not requests:
        print("Nothing to translate. Use --retranslate-all to redo everything.")
        return 0

    client = get_client()
    print(f"Live: {len(requests)} requests on {model}, {concurrency} at a time.")
    print_lock = threading.Lock()

    def log(m):
        with print_lock:
            print(m, flush=True)

    results, errored = {}, []
    tot = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [pool.submit(_live_one, client, r, max_attempts, log) for r in requests]
        for f in futures:
            cid, obj, err, usage = f.result()
            done += 1
            if err:
                errored.append((cid, err))
                log(f"  [{done}/{len(requests)}] {cid}: FAILED — {err}")
            else:
                results[cid] = obj
                log(f"  [{done}/{len(requests)}] {cid}: {len(obj)} segments")
            if usage is not None:
                tot["input"] += getattr(usage, "input_tokens", 0) or 0
                tot["output"] += getattr(usage, "output_tokens", 0) or 0
                tot["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
                tot["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0

    applied, names_set, errs = apply_results(
        docs, glossary, results, id_maps, name_maps)
    store.save_glossary(store_dir, glossary)

    pr = price_for(model)
    cost = (tot["input"] / 1e6 * pr["in"] + tot["output"] / 1e6 * pr["out"]
            + tot["cache_write"] / 1e6 * pr["w5m"] + tot["cache_read"] / 1e6 * pr["read"])
    print(f"\nApplied {applied} translations, {names_set} names. "
          f"{len(errored)} request errors.")
    for cid, why in errored[:20]:
        print(f"  ! {cid}: {why}")
    for e in errs[:20]:
        print(f"  ! {e}")
    print(f"tokens: in={tot['input']:,} cache_w={tot['cache_write']:,} "
          f"cache_r={tot['cache_read']:,} out={tot['output']:,}   cost ~${cost:.2f} "
          f"(live rates, 5m cache)")
    print("Next: python tools/tl.py validate")
    return 0


SYSTEM_SHORTEN = (
    "You are an expert Japanese-to-English eroge translator doing a TIGHTENING pass.\n\n"
    "Each item below is already translated, but the English does not fit its on-screen "
    "box. Rewrite it SHORTER so it fits, without losing meaning or changing register.\n\n"
    "Each item gives:\n"
    "  JP     — the Japanese source (the authority on meaning)\n"
    "  EN     — the current translation, too long\n"
    "  BUDGET — max lines, and max width per line in display cells\n"
    "           (a Latin letter/space/punctuation = 1 cell, a full-width CJK glyph = 2)\n\n"
    "RULES\n"
    "- The result MUST fit the budget. Count cells; a line over budget is cut off "
    "mid-word on screen and the player never sees the end of it.\n"
    "- Use '\\n' to separate lines, and never exceed the stated line count.\n"
    "- Cut filler, not content: drop redundant intensifiers, contract ('it is' -> "
    "\"it's\"), prefer the shorter synonym, trim discourse padding ('well,', 'you see'). "
    "Keep every concrete fact, name, number and plot beat.\n"
    "- Keep the tone, register and explicitness EXACTLY as they are. This is an adult "
    "game: do not sanitise, soften, or moralise while shortening.\n"
    "- Keep ⟦0⟧-style codes verbatim, and keep ♥ ♪ ☆ … ～ tone marks where they carry "
    "the delivery. Keep honorifics and glossary names unchanged.\n"
    "- Do not merge separate items or add commentary.\n\n"
    'OUTPUT: only a JSON object mapping each item number to the shortened English, '
    'e.g. {"1":"...","2":"..."}. No preamble, no notes.'
)


def build_shorten_requests(docs, budgets, model, height, per_request=25):
    """One request per batch of units whose translation overflows its box."""
    items = []
    for _p, doc in docs:
        b = doc["meta"].get("bucket", "")
        for u in doc["units"]:
            tl = u.get("tl") or ""
            if not tl.strip():
                continue
            env = envelope(u, b)
            w, h = env if env else (budgets.get(b, 0), height)
            if not w:
                continue
            fitted, ok = layout.fit_box(tl, w, h)
            if not ok:
                items.append((u, w, h, fitted))
    requests, id_maps = [], {}
    for start in range(0, len(items), per_request):
        chunk = items[start:start + per_request]
        cid = f"shorten__{start // per_request:03d}"
        lines, ids = [], []
        for i, (u, w, h, fitted) in enumerate(chunk, 1):
            over = layout.widest(fitted)
            lines.append(
                f"[{i}] BUDGET {h} lines x {w} cells "
                f"(currently {over} cells on its worst line)\n"
                f"JP: {u['src']}\n"
                f"EN: {fitted}")
            ids.append(u["id"])
        id_maps[cid] = ids
        requests.append({
            "custom_id": cid,
            "params": {
                "model": model,
                "max_tokens": 8000,
                "system": [{"type": "text", "text": SYSTEM_SHORTEN,
                            "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": "\n\n".join(lines)}],
                **_sampling_params(model), **_output_config(),
            },
        })
    return requests, id_maps, len(items)


def cmd_shorten(store_dir, model, concurrency=4, max_attempts=5, height=3, rounds=2):
    """Re-translate, shorter, the units whose English overflows its on-screen box.

    Layout can only break text at spaces; when the words themselves are too long for
    the box no wrapping saves them, and a clipped line loses its ending entirely.
    Runs live rather than batched: it is a small set and worth having immediately.
    """
    client = get_client()
    for rnd in range(1, rounds + 1):
        docs = store.load_docs(store_dir)
        budgets = box_widths(docs)
        requests, id_maps, n = build_shorten_requests(docs, budgets, model, height)
        if not requests:
            print(f"round {rnd}: everything fits — nothing to shorten.")
            return 0
        print(f"round {rnd}: {n} units overflow, {len(requests)} requests")
        results = {}
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(_live_one, client, r, max_attempts, print)
                       for r in requests]
            for f in futures:
                cid, obj, err, _usage = f.result()
                if err:
                    print(f"  ! {cid}: {err}")
                else:
                    results[cid] = obj
        glossary = store.load_glossary(store_dir)
        applied, _names, errs = apply_results(docs, glossary, results, id_maps, {})
        print(f"  applied {applied} shortened translations"
              + (f", {len(errs)} map errors" if errs else ""))
        if not applied:
            break
    docs = store.load_docs(store_dir)
    budgets = box_widths(docs)
    _r, _m, left = build_shorten_requests(docs, budgets, model, height)
    print(f"\n{left} units still overflow after {rounds} round(s).")
    print("Next: python tools/tl.py reflow && python tools/tl.py validate")
    return 0


def cmd_fetch(store_dir):
    state = store.load_state(store_dir)
    if not state:
        sys.exit("No batch state — run submit first.")
    applied, names_set, errored, errs = _fetch(get_client(), state, store_dir)
    print(f"Applied {applied} translations, {names_set} names.")
    for cid, why in errored[:30]:
        print(f"  ! request {cid}: {why}")
    for e in errs[:20]:
        print(f"  ! {e}")
    return 0


def _run_phase(client, store_dir, model, requests, id_maps, name_maps, poll, label):
    batch = client.messages.batches.create(requests=requests)
    print(f"[{label}] submitted batch {batch.id} ({len(requests)} requests).")
    store.save_state(store_dir, {
        "batch_id": batch.id, "model": model, "store_dir": store_dir,
        "id_maps": id_maps, "name_maps": name_maps, "n_requests": len(requests),
        "created": str(getattr(batch, "created_at", "") or ""), "phase": label})
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
    # Phase 1 — names, so the glossary is filled before any prose references it.
    _d, _g, name_reqs, _im, name_maps = build_all(
        store_dir, model, max_units, retranslate_all, include_names=True, include_text=False)
    if name_reqs:
        _a, names_set, errored, _e = _run_phase(
            client, store_dir, model, name_reqs, {}, name_maps, poll, "names")
        print(f"[names] {names_set} names translated ({len(errored)} errors).")

    # Phase 2 — all text, with the freshly filled glossary cached in the prompt.
    _d, _g, requests, id_maps, _nm = build_all(
        store_dir, model, max_units, retranslate_all, include_names=False, include_text=True)
    if not requests:
        print("No text to translate.")
        return 0
    applied, _ns, errored, errs = _run_phase(
        client, store_dir, model, requests, id_maps, {}, poll, "text")
    print(f"[text] applied {applied} translations ({len(errored)} request errors).")
    for cid, why in errored[:30]:
        print(f"  ! {cid}: {why}")
    print("Next: python tools/tl.py validate")
    return 0


# --------------------------------------------------------------------------
# offline self-test + validation
# --------------------------------------------------------------------------
def cmd_selftest(store_dir, model, max_units):
    """Offline round-trip proof: build -> fake-translate -> apply -> validate.

    Runs entirely in memory on deep copies. It must never touch the real store or
    glossary — a self-test that overwrites finished translations with placeholders
    is worse than no self-test.
    """
    import copy
    docs, glossary, requests, id_maps, name_maps = build_all(store_dir, model, max_units, True)
    docs = copy.deepcopy(docs)
    glossary = copy.deepcopy(glossary)
    print(f"built {len(requests)} requests")
    unit_by_id = {u["id"]: u for _p, d in docs for u in d["units"]}
    results = {}
    for req in requests:
        cid = req["custom_id"]
        if cid in name_maps:
            n = len(name_maps[cid])
            results[cid] = {str(i): {"en": f"Name{i}", "gender": "female" if i % 2 else "male"}
                            for i in range(1, n + 1)}
            continue
        out = {}
        for i, uid in enumerate(id_maps[cid], 1):
            u = unit_by_id[uid]
            phs = "".join(sorted(set(re.findall(r"⟦\d+⟧", u["src"]))))
            # Echo the source's line count so the layout check is exercised too.
            body = " / ".join(f"[EN {i}.{k}]" for k in range(codes.line_count(u["src"])))
            out[str(i)] = (body.replace(" / ", "\n") + phs)
        results[cid] = out
    applied, names_set, errs = apply_results(docs, glossary, results, id_maps, name_maps,
                                             persist=False)
    total = sum(len(d["units"]) for _p, d in docs)
    # The fake translations echo the source line count and placeholder set, so the
    # layout and placeholder validators must come back clean.
    layout_drift = [u["id"] for _p, d in docs for u in d["units"]
                    if any("line count" in w for w in soft_warnings(u))]
    broken = [u["id"] for _p, d in docs for u in d["units"]
              if "placeholder" in hard_issues(u)]
    print(f"selftest: applied {applied}/{total} units, {names_set} names, {len(errs)} map errors")
    print(f"          placeholder integrity: {len(broken)} broken   "
          f"line-count integrity: {len(layout_drift)} drifted")
    ok = applied == total and not errs and not broken and not layout_drift
    print("SELFTEST", "PASS" if ok else "FAIL")
    if not ok:
        for i in (errs[:5] + broken[:5] + layout[:5]):
            print("   -", i)
    print("(nothing was written — the store and glossary are untouched)")
    return 0 if ok else 1


def hard_issues(u):
    """Must-fix problems for one translated unit."""
    tl = u.get("tl", "")
    if not tl.strip():
        return ["empty"]
    out = []
    if tl.strip() == u["src"].strip():
        out.append("identical")
    if codes.has_untranslated_jp(tl):
        out.append("residual_jp")
    if codes.placeholder_ids(u["src"]) != codes.placeholder_ids(tl):
        out.append("placeholder")
    return out


_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)


def soft_warnings(u, max_width=0):
    """Review warnings, not failures: layout drift, over-expansion, leftover kana.

    `max_width` is the bucket's box width in display cells. Given one, EXTRA lines
    are not a warning — `tl.py reflow` adds them deliberately, because a line wider
    than the box is clipped off the right edge of the screen and a line count that
    matches the Japanese is worth nothing if half of it is invisible. Losing lines,
    or still being too wide, remains worth flagging.
    """
    tl = u.get("tl", "")
    warns = []
    if not tl.strip():
        return warns
    sl, tlc = codes.line_count(u["src"]), codes.line_count(tl)
    over = [ln for ln in tl.split("\n") if max_width and layout.widest(ln) > max_width]
    if over:
        warns.append(f"line exceeds box width {max_width} "
                     f"(worst {max(layout.widest(ln) for ln in over)} cells)")
    if tlc < sl:
        warns.append(f"line count {sl} -> {tlc} (fixed-size box)")
    elif tlc > sl and not max_width:
        warns.append(f"line count {sl} -> {tlc} (fixed-size box)")
    sv = len(codes.strip_placeholders(u["src"]).strip())
    tv = len(codes.strip_placeholders(tl).strip())
    if u["kind"] in ("ui", "speaker", "controlhint") and sv >= 2 and tv > sv * 4:
        warns.append(f"UI label expanded {sv} -> {tv} chars")
    elif sv >= 8 and tv > sv * 6:
        warns.append(f"over-expansion: tl {tv} chars vs src {sv}")
    if codes.has_jp(tl) and not codes.has_untranslated_jp(tl):
        leftover = "".join(sorted({c for c in tl if codes.has_jp(c) and c not in "ー・"}))
        if leftover:
            warns.append(f"leftover kana/symbol {leftover!r} (cosmetic)")
    return warns


# The CanvasScaler reference is 800x450 in Expand mode, so the canvas is always 800
# units wide, while the dialogue RectTransforms are 959-1025 units and centred —
# ~80 units hang off each side, which is why TMP's own word wrap never rescued us.
# A full-width glyph is ~1em and scores 2 cells, so a cell is fontSize/2 units and
# the visible budget is 2*800/fontSize: 53 cells at the dialogue boxes' fontSize 30.
BOX_WIDTH_CAP = int(2 * 800 / 30)

# Those RectTransforms are 107.1 units tall at fontSize 30 with ~1.2em line spacing,
# so three lines is what actually shows; a fourth is drawn outside the panel.
BOX_HEIGHT = 3


# Widgets sized individually rather than shared, where no bucket-wide budget exists.
# For these the constraint is per unit: the English may not occupy more space than
# the Japanese did, because that text demonstrably fitted. The bonus-card panels are
# the case that forced this — a card whose Japanese ran 16/14/12 cells came back as
# 17/20/19, TMP wrapped each line in two, and the six-line result grew upward over
# the card's title. Cards with wider Japanese were unaffected, which is exactly what
# a per-unit envelope predicts and a bucket-wide budget cannot express.
ENVELOPE_KINDS = {("Stage", "message")}


def envelope(u, bucket):
    """(width, lines) this unit's Japanese occupied, or None if not envelope-bound.

    Restricted to the three-line form, which is the bonus-card panel. Stage messages
    also cover warning banners ("Danger! You're almost out of coins!") that live in a
    much wider widget, and holding those to the Japanese footprint would compress
    text that has plenty of room.
    """
    if (bucket, u.get("kind")) not in ENVELOPE_KINDS:
        return None
    lines = [ln for ln in codes.display_lines(u["raw"]) if ln.strip()]
    if len(lines) != 3:
        return None
    return max(layout.widest(ln) for ln in lines), len(lines)


def box_widths(docs):
    """Box width per CSV bucket, in display cells.

    Measured from the widest Japanese line the developer shipped in that bucket —
    those demonstrably render — then capped by BOX_WIDTH_CAP. The cap matters:
    CSV_Hscene's own corpus implies 72 cells, well past what a size-30 box holds,
    meaning the developer's longest subtitles are themselves clipped. Taking the min
    keeps us inside the box instead of inheriting that bug.

    Asset buckets are hundreds of individually-sized widgets sharing no common
    width, so no single budget applies and they get none.
    """
    widths = {}
    for _p, doc in docs:
        b = doc["meta"].get("bucket", "")
        if not b.startswith("CSV_"):
            continue
        for u in doc["units"]:
            for ln in codes.display_lines(u["raw"]):
                if ln.strip():
                    widths[b] = max(widths.get(b, 0), layout.widest(ln))
    return {b: min(w, BOX_WIDTH_CAP) for b, w in widths.items()}


def cmd_validate(store_dir, max_issues=25):
    docs = store.load_docs(store_dir)
    widths = box_widths(docs)
    glossary = store.load_glossary(store_dir)
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
                    detail = f": {u['tl'][:40]!r}"
                elif code == "placeholder":
                    detail = (f": src{sorted(codes.placeholder_ids(u['src']))} "
                              f"tl{sorted(codes.placeholder_ids(u['tl']))}")
                hard_list.append(f"[{code}] {u['id']}{detail}")
            for w in soft_warnings(u, widths.get(doc["meta"].get("bucket", ""), 0)):
                warn_list.append(f"{u['id']}: {w}")
    names_total = len(glossary.get("names", {}))
    names_done = sum(1 for v in glossary.get("names", {}).values() if store.name_en(v))
    print(f"VALIDATION  buckets={len(docs)} units={total}")
    print(f"  translated         : {done} ({100.0 * done / total if total else 0:.1f}%)")
    print(f"  untranslated       : {empty}")
    print(f"  identical-to-source: {tally['identical']}")
    print(f"  residual-Japanese  : {tally['residual_jp']}")
    print(f"  placeholder-broken : {tally['placeholder']}")
    print(f"  names translated   : {names_done}/{names_total}")
    print(f"  soft warnings      : {len(warn_list)} (layout / expansion — review)")
    if hard_list:
        print("  -- hard issues (fix with: python tools/tl.py retry) --")
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
    hard_fail = empty + tally["residual_jp"] + tally["placeholder"]
    return 0 if hard_fail == 0 else 1


def cmd_usage(store_dir, batch_id=None):
    """Report the tokens the batch was actually billed for.

    The estimate in `dryrun` is a tiktoken proxy; this reads the real per-request
    usage the API returns, so cache behaviour can be checked rather than assumed —
    if `cache_read` is ~0 across 100+ requests, the cached prefix is not being hit.
    """
    state = store.load_state(store_dir)
    if not batch_id:
        if not state:
            sys.exit("No batch state — pass a batch id, or run submit first.")
        batch_id = state["batch_id"]
    model = (state or {}).get("model", MODEL_DEFAULT)
    client = get_client()

    n = ok = 0
    tot = {"input": 0, "output": 0, "cache_write": 0, "cache_read": 0}
    for r in client.messages.batches.results(batch_id):
        n += 1
        if r.result.type != "succeeded":
            continue
        ok += 1
        u = r.result.message.usage
        tot["input"] += getattr(u, "input_tokens", 0) or 0
        tot["output"] += getattr(u, "output_tokens", 0) or 0
        tot["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        tot["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0

    bat = price_for(model, batch=True)
    cost = (tot["input"] / 1e6 * bat["in"]
            + tot["output"] / 1e6 * bat["out"]
            + tot["cache_write"] / 1e6 * bat["w1h"]
            + tot["cache_read"] / 1e6 * bat["read"])
    print(f"batch {batch_id}  model={model}  requests={n} ({ok} succeeded)")
    for k in ("input", "cache_write", "cache_read", "output"):
        print(f"  {k:12s} {tot[k]:>12,} tok")
    cached = tot["cache_read"] + tot["cache_write"]
    if cached:
        share = 100.0 * tot["cache_read"] / cached
        print(f"  cache: {share:.1f}% of cached tokens were re-reads "
              f"({'working' if share > 50 else 'NOT hitting — check the prefix is stable'})")
    # Only meaningful when the stored estimate belongs to THIS batch — the state
    # file tracks the most recent submit, which may be a different run.
    est = (state or {}).get("est_input_tokens") \
        if (state or {}).get("batch_id") == batch_id else None
    if est:
        actual_in = tot["input"] + tot["cache_write"] + tot["cache_read"]
        print(f"  tokenizer: {actual_in:,} input tok actual vs {est:,} estimated "
              f"(x{actual_in / est:.2f}) — the tiktoken proxy's error on this model")
    print(f"\n  cost at published batch rates: ${cost:.2f}")
    print("  (token counts are what the API reported; the console is the billing authority)")
    return 0


def build_retry_chunks(docs, fail_ids, max_units):
    """One chunk per scene containing a failure, with that scene's finished lines
    supplied as context so the fix stays consistent with its surroundings."""
    chunks = []
    for _p, doc in docs:
        bucket = doc["meta"]["bucket"]
        scenes = {}
        for u in doc["units"]:
            scenes.setdefault(_unit_scene(u), []).append(u)
        part = 0
        for _key, units in scenes.items():
            fails = [u for u in units if u["id"] in fail_ids]
            if not fails:
                continue
            context = [u for u in units
                       if u["id"] not in fail_ids and (u.get("tl") or "").strip()][:12]
            for s in range(0, len(fails), max_units):
                chunks.append({"custom_id": store.sanitize_id(f"{bucket}__retry{part:03d}"),
                               "units": fails[s:s + max_units], "bucket": bucket,
                               "context": context})
                part += 1
    return chunks


def cmd_retry(store_dir, model, max_units, poll=60, max_rounds=2):
    client = get_client()
    glossary = store.load_glossary(store_dir)
    game_prompt = store.load_game_prompt(store_dir)
    for rnd in range(1, max_rounds + 1):
        docs = store.load_docs(store_dir)
        fail_ids = {u["id"] for _p, doc in docs for u in doc["units"] if hard_issues(u)}
        if not fail_ids:
            print("[retry] nothing failing — store is clean.")
            return 0
        requests, id_maps = [], {}
        for ch in build_retry_chunks(docs, fail_ids, max_units):
            req, idmap = build_request(ch, model, glossary, game_prompt)
            requests.append(req)
            id_maps[ch["custom_id"]] = idmap
        print(f"[retry round {rnd}/{max_rounds}] {len(fail_ids)} failing units "
              f"-> {len(requests)} requests.")
        _run_phase(client, store_dir, model, requests, id_maps, {}, poll, f"retry{rnd}")
    docs = store.load_docs(store_dir)
    still = sum(1 for _p, doc in docs for u in doc["units"] if hard_issues(u))
    print(f"[retry] done. {still} units still failing — run `validate` to inspect.")
    return 0
