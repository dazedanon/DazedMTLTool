#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
claude_translate.py - translate a WolfDawn `mt-export` batch with Claude via the
Anthropic Message Batches API (prompt caching + batch = cheapest at scale).

Adapted from the BroodGeneral RPG Maker pipeline (Reference Pipelines\\RPG Maker
MVMZ (BroodGeneral)) for the WolfDawn mt-batch JSON contract: it fills the empty
`text` field of every line in batch.json, which then goes back into the game via

    wolf mt-import batch.json out/*.json

Pipeline:
    dryrun    preview request count / cost / sample prompt (no API key needed)
    run       phase 1: names (out/names.json lines), phase 2: everything else
              (or: submit / status / fetch as separate resumable steps)
    validate  completeness / residual-JP / control-code integrity
    retry     re-translate hard-failing lines with scene context
    selftest  offline fake-translate -> validate (proves wiring, no API)
    batches   list / cancel / usage for submitted Message Batches

Typical use:
    set ANTHROPIC_API_KEY=sk-...
    python scripts/claude_translate.py dryrun --show-sample
    python scripts/claude_translate.py run
    python scripts/claude_translate.py validate
    python scripts/claude_translate.py retry
"""

import os
import re
import sys
import json
import time
import argparse
import collections

WS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATCH_PATH = os.path.join(WS, "batch.json")
OUT_DIR = os.path.join(WS, "out")
TL_DIR = os.path.join(WS, "tl")
GLOSSARY_PATH = os.path.join(TL_DIR, "glossary.json")
STATE_PATH = os.path.join(TL_DIR, "_batch_state.json")
GAME_PROMPT_NAMES = ("game_prompt.md", "game_prompt.txt")

MODEL_DEFAULT = "claude-sonnet-4-6"
EFFORT_DEFAULT = "low"       # translation is direct high-volume work; 'high' only inflates cost
_EFFORT = EFFORT_DEFAULT
_EFFORT_LEVELS = {"low", "medium", "high", "xhigh", "max"}

# USD per 1M tokens; batch_* = 50% off; cache_write at the 1h-TTL rate (2x input),
# cache_read = 10% of input. Verified Jun 2026.
PRICE_BY_MODEL = {
    "claude-sonnet-4-6": {"in": 3.0, "out": 15.0, "batch_in": 1.5, "batch_out": 7.5,
                          "cache_write": 6.0, "cache_read": 0.30},
    "claude-opus-4-8":   {"in": 5.0, "out": 25.0, "batch_in": 2.5, "batch_out": 12.5,
                          "cache_write": 10.0, "cache_read": 0.50},
}

# Opus 4.7+ rejects temperature/top_p/top_k with a 400.
_NO_SAMPLING_RE = re.compile(r"opus-4-(?:[7-9]\b|[1-9]\d)", re.I)

# --------------------------------------------------------------------------
# Wolf control codes
# --------------------------------------------------------------------------
# Ruby first (its payload is translatable, so it is normalized for comparison),
# then bracketed codes, then single-letter / symbol codes, then @N portraits.
# The single-letter branch has NO trailing-letter lookahead on purpose: the token
# after \E or \n is Japanese in the source but English in the translation, and the
# multiset compare only works if both sides tokenize identically.
WOLF_CODE_RE = re.compile(
    r"\\r\[[^\]]*\]"
    r"|\\[A-Za-z]+\[[^\]]*\]"
    r"|\\[A-Za-z]"
    r"|\\[.!^\\<>|]"
    r"|@\d+"
)
_RUBY_RE = re.compile(r"^\\r\[[^\]]*\]$")

JP_RE = re.compile(r"[぀-ヿ一-鿿]")
# Hard residual = hiragana / kanji / katakana EXCEPT the cosmetic marks ・ー and
# iteration marks, which stranded in English are a soft problem, not a retry loop.
UNTRANSLATED_JP_RE = re.compile(r"[぀-ゟ゠-ヺ一-鿿]")


def code_multiset(s):
    """Multiset of protected tokens. Ruby \\r[..] is droppable markup (WolfDawn
    never puts it in the must-preserve set), so it is excluded entirely."""
    return sorted(m for m in WOLF_CODE_RE.findall(s) if not _RUBY_RE.match(m))


# --------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------
SYSTEM_SHARED = (
    "You are an expert Japanese-to-English eroge (adult game) translator and localizer. You "
    "translate dialogue, narration, menu/UI text, database names and descriptions for a Japanese "
    "Wolf RPG game into natural, fluent, idiomatic English.\n\n"
    "You receive a numbered list of segments from ONE game file. Each is tagged with its role "
    "(dialogue, narration, choice, UI, name, db field, ...) and, for dialogue, the speaker. A "
    "character & term glossary follows in a later block - read it first and apply ALL of it.\n\n"
    "OUTPUT FORMAT\n"
    "- Translate EVERY numbered segment. Output ONLY a JSON object mapping each number (as a "
    'string) to its English translation, e.g. {"1":"...","2":"..."}. No preamble, notes, '
    "romaji, or Japanese in the output. Use \\n inside JSON strings for line breaks.\n\n"
    "PROTECTED CODES (Wolf RPG)\n"
    "- Keep every control code EXACTLY as written and in the same relative position: @N line "
    "prefixes (e.g. @2, @10), \\cself[n], \\c[n], \\f[n], \\i[n], \\E, \\>, \\m[n], \\s[n], "
    "\\self[n], \\sysS[n], \\cdb[..], \\udb[..], \\v[n], \\ax[n], \\ay[n], \\font[n], "
    "\\space[n], \\\\, \\., \\!, \\^. Never translate, renumber, reorder, add, or drop them.\n"
    "- Ruby \\r[base,reading]: translate the base, keep the syntax - \\r[人生,じんせい] -> "
    "\\r[life,life].\n"
    "- Dialogue lines start with the @N code and a bracketed speaker tag on its own line, e.g. "
    "\"@2\\n[明日香]\\n...\". Translate the tag with the glossary name, keep the brackets and "
    "line break: [明日香] -> [Asuka]. ？？？ -> ???\n\n"
    "LAYOUT\n"
    "- Keep the source's line-break structure; the message box fits ~46 characters per line. "
    "Reflow within the existing number of lines where possible; never turn a 2-line message "
    "into 5 lines.\n"
    "- Menu choices are padded with full-width spaces (　) for centering - keep the leading/"
    "trailing 　 and translate only the label. UI labels are terse natural UI English.\n\n"
    "QUALITY & CONSISTENCY\n"
    "- Prefer natural, fluent English over literal gloss. Preserve tone and each speaker's "
    "register from the glossary. Use the SAME English name for a character every time.\n"
    "- Japanese omits pronouns; resolve 彼 / 彼女 / こいつ from the glossary's stated genders. "
    "Preserve Japanese honorifics (-san, -chan, -kun, -sama, -senpai, -sensei).\n"
    "- ・・・ -> \"...\". Keep ♥ ♡ ♪. Keep （） inner monologue as (parentheses).\n\n"
    "ADULT CONTENT (18+ game - do NOT censor or euphemize unless the Japanese itself is "
    "euphemistic)\n"
    "- Translate explicit sexual content directly and vividly, matching the source register "
    "(clinical / vulgar / colloquial). Keep dominant speech dominant and submissive begging "
    "submissive.\n"
    "- Erotic onomatopoeia (ぴちゃ, ぐちゅ, じゅぽ, ぬぷ, くぱぁ...) -> evocative English. "
    "Moans & climax cues (あぁ, んっ, はぁ, イく, イっちゃう...) -> 'Aah...', 'Ngh...', "
    "\"I'm cumming...\".\n\n"
    "EXAMPLE\n"
    "Input:\n"
    "[1] (dialogue; 明日香) @2\\n[明日香]\\nうん。\\nちょっと恥ずかしかったけど、慣れたよ。\n"
    "[2] (choice) 　はい　\n"
    "[3] (narration) 「\\cself[8]」を手に入れた。\n"
    "Output:\n"
    '{"1":"@2\\n[Asuka]\\nYeah.\\nIt was a little embarrassing, but I got used to it.",'
    '"2":"　Yes　","3":"Obtained \\"\\cself[8]\\"."}'
)

NAMES_HEADER = (
    "These segments are NAMES from the game's databases (characters, items, skills, enemies, "
    "animations, locations, flags). Translate each to a clean, short, consistent English name "
    "using the glossary; romanize unknown proper nouns consistently (Hepburn). Keep any "
    "bracketed/parenthesized tags and codes exactly. Terse - these are labels, not sentences."
)

KIND_LABEL = {
    "dialogue": "dialogue", "narration": "narration", "choice": "choice",
    "ui": "UI", "name": "name", "db": "db field", "system": "system",
}


def _sampling_params(model):
    return {} if _NO_SAMPLING_RE.search(model or "") else {"temperature": 0}


def _output_config():
    if _EFFORT in _EFFORT_LEVELS and _EFFORT != "high":
        return {"output_config": {"effort": _EFFORT}}
    return {}


def price_for(model):
    m = (model or "").lower()
    for key, pr in PRICE_BY_MODEL.items():
        if key in m:
            return pr
    return PRICE_BY_MODEL["claude-sonnet-4-6"]


# --------------------------------------------------------------------------
# store: batch.json + glossary + state
# --------------------------------------------------------------------------
def load_batch():
    with open(BATCH_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_batch(batch):
    tmp = BATCH_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=1)
    os.replace(tmp, BATCH_PATH)


def load_glossary():
    if os.path.exists(GLOSSARY_PATH):
        with open(GLOSSARY_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"names": {}, "terms": {}, "do_not_translate": []}


def load_game_prompt():
    for name in GAME_PROMPT_NAMES:
        p = os.path.join(TL_DIR, name)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return f.read().strip()
    return ""


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return None


def save_state(state):
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def dnt_set(glossary):
    return {s.strip() for s in glossary.get("do_not_translate", []) if s.strip()}


def is_names_file(fname):
    return fname.replace("\\", "/").endswith("names.json")


def line_kind(l):
    if is_names_file(l["file"]):
        return "name"
    sp = l.get("speaker") or ""
    if sp == "Narration":
        return "narration"
    if sp == "Choice":
        return "choice"
    if sp == "UI":
        return "ui"
    if sp.startswith("["):
        return "dialogue"
    if "GameDat" in l["file"]:
        return "system"
    return "db"


def pending(l, retranslate_all=False):
    return retranslate_all or not (l.get("text") or "").strip()


# --------------------------------------------------------------------------
# scene labels from the extract JSONs (event names give the model context)
# --------------------------------------------------------------------------
_scene_labels_cache = None


def scene_labels():
    """{(batch-file-string, scene-index): event/scene name} from out/*.json."""
    global _scene_labels_cache
    if _scene_labels_cache is not None:
        return _scene_labels_cache
    labels = {}
    batch_files = set()
    try:
        for l in load_batch()["lines"]:
            batch_files.add(l["file"])
    except Exception:
        pass
    for bf in batch_files:
        path = os.path.join(WS, bf.replace("/", os.sep))
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except Exception:
            continue
        for i, sc in enumerate(doc.get("scenes") or []):
            nm = sc.get("name") or ""
            ev = sc.get("event")
            if nm:
                labels[(bf, i)] = f"{nm}" + (f" (event {ev})" if ev is not None else "")
        for i, g in enumerate(doc.get("groups") or []):
            nm = g.get("name") or g.get("type") or ""
            if nm:
                labels[(bf, i)] = nm
    _scene_labels_cache = labels
    return labels


_PTR_RE = re.compile(r"/(scenes|groups)/(\d+)/")


def scene_key(l):
    """Group key: one event page / db group = one scene. Names group per-file."""
    if is_names_file(l["file"]):
        return (l["file"], "names")
    m = _PTR_RE.search(l["id"])
    if m:
        return (l["file"], f"{m.group(1)}/{m.group(2)}")
    return (l["file"], "misc")


def scene_label(l):
    m = _PTR_RE.search(l["id"])
    if m:
        return scene_labels().get((l["file"], int(m.group(2))), "")
    return ""


# --------------------------------------------------------------------------
# request building
# --------------------------------------------------------------------------
def sanitize_id(s):
    return re.sub(r"[^A-Za-z0-9_-]", "-", s)[:60]


def build_chunks(lines, max_units, retranslate_all, phase):
    """Scene-aligned chunks. phase 'names' = only names.json lines, 'text' = the
    rest, 'all' = both. A scene bigger than max_units is split with a 3-line
    context tail."""
    chunks = []
    by_file = collections.OrderedDict()
    for i, l in enumerate(lines):
        if not pending(l, retranslate_all):
            continue
        nm = is_names_file(l["file"])
        if phase == "names" and not nm:
            continue
        if phase == "text" and nm:
            continue
        by_file.setdefault(l["file"], []).append((i, l))

    for fname, items in by_file.items():
        stem = sanitize_id(os.path.splitext(os.path.basename(fname))[0])
        scenes, cur = [], None
        for i, l in items:
            k = scene_key(l)
            if k != cur:
                scenes.append([])
                cur = k
            scenes[-1].append((i, l))

        part = [0]
        buf = []

        def emit(sub, context=None):
            chunks.append({
                "custom_id": sanitize_id(f"{stem}__{part[0]:03d}"),
                "items": sub, "file": fname, "context": context or [],
                "names": is_names_file(fname),
            })
            part[0] += 1

        def flush():
            if buf:
                emit(list(buf))
                buf.clear()

        for sc in scenes:
            if len(sc) > max_units:
                flush()
                for s in range(0, len(sc), max_units):
                    ctx = [l for _i, l in sc[max(0, s - 3):s]] if s > 0 else []
                    emit(sc[s:s + max_units], ctx)
            else:
                if buf and len(buf) + len(sc) > max_units:
                    flush()
                buf.extend(sc)
        flush()
    return chunks


def build_user_text(chunk):
    """Numbered segment list; returns (text, id_map[idx-1] = line index in batch)."""
    lines = ["Translate every numbered segment below. Return ONLY the JSON object."]
    if chunk["names"]:
        lines.append("\n" + NAMES_HEADER)
    ctx = chunk.get("context") or []
    if ctx:
        lines.append("\nCONTEXT - earlier lines of this SAME scene, for reference only; "
                     "do NOT translate or include these in the output:")
        for l in ctx:
            shown = (l.get("text") or l["source"]).replace("\n", " ")
            lines.append(f"  {shown[:160]}")
        lines.append("")
    id_map = []
    last_scene = None
    for i, l in chunk["items"]:
        sk = scene_key(l)
        if sk != last_scene and not chunk["names"]:
            lbl = scene_label(l)
            if lbl:
                lines.append(f"# scene: {lbl}")
            last_scene = sk
        id_map.append(i)
        idx = len(id_map)
        kind = line_kind(l)
        tag = KIND_LABEL.get(kind, kind)
        sp = l.get("speaker") or ""
        if kind == "dialogue" and sp.startswith("["):
            tag = f"dialogue; {sp[1:-1]}"
        note = (l.get("note") or "").replace("\r\n", " ").replace("\n", " ").strip()
        if note:
            tag += f"; {note[:70]}"
        src = l["source"].replace("\n", "\\n")
        lines.append(f"[{idx}] ({tag}) {src}")
    lines.append('\nJSON object {"1":"...", ...} with a translation for every number above. '
                 "Use \\n for the line breaks shown as \\n in the source.")
    return "\n".join(lines), id_map


def _glossary_block(glossary, extra_terms, chunk_text=""):
    lines = []
    name_lines = []
    for jp, v in glossary.get("names", {}).items():
        en = v.get("en") if isinstance(v, dict) else str(v)
        if not en:
            continue
        meta = []
        if isinstance(v, dict):
            # `note` is human-facing documentation and is intentionally NOT sent.
            for key in ("gender", "role", "register"):
                if v.get(key):
                    meta.append(str(v[key]))
            for alias in (v.get("aliases") or []):
                meta.append(f"aka {alias}")
        suffix = f"  ({'; '.join(meta)})" if meta else ""
        name_lines.append(f"  {jp} -> {en}{suffix}")
    if name_lines:
        lines.append("# Characters (use these English names and genders consistently)")
        lines += name_lines

    term_lines = []
    merged = dict(glossary.get("terms", {}))
    merged.update(extra_terms or {})
    for jp, en in merged.items():
        if en and (not chunk_text or jp in chunk_text):
            term_lines.append(f"  {jp} -> {en}")
    if term_lines:
        lines.append("# Terms (translate consistently)")
        lines += term_lines

    dnt = glossary.get("do_not_translate") or []
    if dnt:
        lines.append("# Do not translate (copy verbatim if encountered)")
        lines += [f"  {s}" for s in dnt]

    if not lines:
        return "Character & term glossary: (none yet - romanize names consistently)."
    return "Character & term glossary - apply consistently:\n" + "\n".join(lines)


def _system_blocks(dynamic_text, game_prompt):
    blocks = [{"type": "text", "text": SYSTEM_SHARED}]
    if game_prompt:
        blocks.append({"type": "text", "text": "GAME-SPECIFIC GUIDANCE:\n" + game_prompt})
    # 1h TTL so async batch requests processed minutes apart still hit the cache.
    blocks[-1]["cache_control"] = {"type": "ephemeral", "ttl": "1h"}
    if dynamic_text is not None:
        blocks.append({"type": "text", "text": dynamic_text})
    return blocks


def build_request(chunk, model, glossary, extra_terms, game_prompt):
    user_text, id_map = build_user_text(chunk)
    n = len(id_map)
    src_chars = sum(len(l["source"]) for _i, l in chunk["items"])
    max_tokens = min(32000, max(2000, int(src_chars * 1.2) + n * 24))
    return {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            **_sampling_params(model),
            **_output_config(),
            "system": _system_blocks(_glossary_block(glossary, extra_terms, user_text), game_prompt),
            "messages": [{"role": "user", "content": user_text}],
        },
    }, id_map


def names_extra_terms(batch, max_len=40):
    """Translated names.json lines as extra glossary terms for the text phase."""
    out = {}
    for l in batch["lines"]:
        if is_names_file(l["file"]) and (l.get("text") or "").strip():
            src = l["source"].strip()
            if 0 < len(src) <= max_len and src != l["text"].strip():
                out[src] = l["text"].strip()
    return out


def apply_dnt(batch, glossary):
    """Pre-fill do_not_translate lines with their source so they never hit the API."""
    dnt = dnt_set(glossary)
    n = 0
    for l in batch["lines"]:
        if not (l.get("text") or "").strip() and l["source"].strip() in dnt:
            l["text"] = l["source"]
            n += 1
    return n


def build_all(batch, model, max_units, retranslate_all, phase):
    glossary = load_glossary()
    game_prompt = load_game_prompt()
    extra_terms = names_extra_terms(batch) if phase == "text" else {}
    requests, id_maps = [], {}
    for ch in build_chunks(batch["lines"], max_units, retranslate_all, phase):
        req, idmap = build_request(ch, model, glossary, extra_terms, game_prompt)
        requests.append(req)
        id_maps[ch["custom_id"]] = idmap
    return glossary, requests, id_maps


# --------------------------------------------------------------------------
# anthropic client + response parsing
# --------------------------------------------------------------------------
def get_client():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: set ANTHROPIC_API_KEY in the environment first.")
    try:
        from anthropic import Anthropic
    except ImportError:
        sys.exit("ERROR: pip install anthropic")
    return Anthropic()


# Walks escapes left-to-right so a valid pair (\\, \n, \uXXXX) is consumed
# atomically and never re-inspected from its middle character.
_ESC_RE = re.compile(r'\\u[0-9a-fA-F]{4}|\\[\\/"bfnrt]|\\(.)', re.S)


def _repair_json_escapes(s):
    """The model sometimes emits Wolf codes as raw backslash escapes inside JSON
    strings (\\cself[8] -> "\\c..." = invalid escape; \\udb[..] = invalid \\u).
    Double every backslash that does not start a valid JSON escape."""
    return _ESC_RE.sub(
        lambda m: m.group(0) if m.group(1) is None else "\\\\" + m.group(1), s)


def parse_json_object(text):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?", "", s).strip()
        s = re.sub(r"```$", "", s).strip()
    i, j = s.find("{"), s.rfind("}")
    if i != -1 and j != -1 and j > i:
        s = s[i:j + 1]
    # strict=False accepts raw control characters (literal newlines) in strings,
    # which the model occasionally emits instead of \n.
    try:
        return json.loads(s, strict=False)
    except json.JSONDecodeError:
        return json.loads(_repair_json_escapes(s), strict=False)


def apply_results(batch, results, id_maps):
    applied = 0
    errors = []
    lines = batch["lines"]
    for cid, obj in results.items():
        idmap = id_maps.get(cid, [])
        for k, v in obj.items():
            try:
                idx = int(k)
            except ValueError:
                continue
            if 1 <= idx <= len(idmap) and isinstance(v, str):
                lines[idmap[idx - 1]]["text"] = v
                applied += 1
            else:
                errors.append(f"{cid}: index {k} out of range")
    return applied, errors


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------
def hard_issues(l, dnt):
    src = l["source"]
    tl = l.get("text") or ""
    if not tl.strip():
        return ["empty"]
    if src.strip() in dnt or not JP_RE.search(src):
        return []           # verbatim / ascii-only lines are legitimately identical
    out = []
    if tl.strip() == src.strip():
        out.append("identical")
    # a do_not_translate term correctly kept verbatim inside a translation is not
    # residual Japanese - strip those before scanning
    tl_scan = tl
    for term in sorted(dnt, key=len, reverse=True):
        if term in tl_scan:
            tl_scan = tl_scan.replace(term, "")
    if UNTRANSLATED_JP_RE.search(tl_scan):
        out.append("residual_jp")
    if code_multiset(src) != code_multiset(tl):
        out.append("codes")
    return out


def _name_gender_forms(glossary):
    out = []
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g not in ("male", "female"):
            continue
        for f in [jp] + list(v.get("aliases") or []):
            if len(f) >= 2 and JP_RE.search(f):
                out.append((f, g))
    out.sort(key=lambda x: -len(x[0]))
    return out


_HE_RE = re.compile(r"\b(?:he|him|his|himself)\b", re.I)
_SHE_RE = re.compile(r"\b(?:she|her|hers|herself)\b", re.I)


def soft_warnings(l, name_forms, gender_sets):
    tl = l.get("text") or ""
    warns = []
    if not tl.strip():
        return warns
    src = l["source"]
    has_he, has_she = bool(_HE_RE.search(tl)), bool(_SHE_RE.search(tl))
    if has_he or has_she:
        male_named = any(m in src for m in gender_sets["male"])
        female_named = any(f in src for f in gender_sets["female"])
        for jp, g in name_forms:
            if jp in src:
                if g == "female" and has_he and not has_she and not male_named:
                    warns.append(f"possible misgender: '{jp}' is female but tl uses he/him")
                elif g == "male" and has_she and not has_he and not female_named:
                    warns.append(f"possible misgender: '{jp}' is male but tl uses she/her")
                break
    sv, tv = len(src.strip()), len(tl.strip())
    if sv >= 8 and tv > sv * 6:
        warns.append(f"over-expansion: tl {tv} chars vs src {sv}")
    if tl.count("\n") > src.count("\n") + 1:
        warns.append(f"line-count growth: src {src.count(chr(10)) + 1} -> tl {tl.count(chr(10)) + 1}")
    if JP_RE.search(tl) and not UNTRANSLATED_JP_RE.search(tl):
        warns.append("leftover cosmetic kana mark (・/ー)")
    return warns


def _gender_sets(glossary):
    out = {"male": set(), "female": set()}
    for jp, v in glossary.get("names", {}).items():
        if not isinstance(v, dict):
            continue
        g = (v.get("gender") or "").lower()
        if g in out:
            for f in [jp] + list(v.get("aliases") or []):
                if len(f) >= 2 and JP_RE.search(f):
                    out[g].add(f)
    return out


def cmd_validate(max_issues=25):
    batch = load_batch()
    glossary = load_glossary()
    dnt = dnt_set(glossary)
    name_forms = _name_gender_forms(glossary)
    gender_sets = _gender_sets(glossary)
    total = len(batch["lines"])
    done = empty = 0
    tally = collections.Counter()
    hard_list, warn_list = [], []
    for l in batch["lines"]:
        issues = hard_issues(l, dnt)
        if issues == ["empty"]:
            empty += 1
            continue
        done += 1
        for code in issues:
            tally[code] += 1
            detail = f": {l['text'][:40]!r}" if code == "residual_jp" else ""
            if code == "codes":
                detail = f": src{code_multiset(l['source'])} tl{code_multiset(l['text'])}"
            hard_list.append(f"[{code}] {l['file']} {l['id']}{detail}")
        for w in soft_warnings(l, name_forms, gender_sets):
            warn_list.append(f"{l['file']} {l['id']}: {w}")
    print(f"VALIDATION  lines={total}")
    print(f"  translated         : {done} ({100.0 * done / total if total else 0:.1f}%)")
    print(f"  untranslated       : {empty}")
    print(f"  identical-to-source: {tally['identical']}")
    print(f"  residual-Japanese  : {tally['residual_jp']}")
    print(f"  code-broken        : {tally['codes']}")
    print(f"  soft warnings      : {len(warn_list)}")
    for title, rows, mark in (("hard issues (fix with: retry)", hard_list, "-"),
                              ("soft warnings (review)", warn_list, "?")):
        if rows:
            print(f"  -- {title} --")
            for s in rows[:max_issues]:
                print(f"   {mark} {s}")
            if len(rows) > max_issues:
                print(f"   ... ({len(rows) - max_issues} more)")
    hard_fail = empty + tally["residual_jp"] + tally["codes"]
    if hard_fail == 0:
        print("\nOK - next: wolf mt-import batch.json out/*.json")
    return 0 if hard_fail == 0 else 1


# --------------------------------------------------------------------------
# dryrun
# --------------------------------------------------------------------------
def get_counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        return lambda s: max(1, int(len(s) / 2.0))


def cmd_dryrun(model, max_units, retranslate_all, show_sample=False):
    batch = load_batch()
    glossary = load_glossary()
    apply_dnt(batch, glossary)
    counter = get_counter()
    all_requests = []
    for phase in ("names", "text"):
        _g, reqs, id_maps = build_all(batch, model, max_units, retranslate_all, phase)
        all_requests.append((phase, reqs, id_maps))

    prefix_count = collections.defaultdict(int)
    prefix_tok = {}
    dyn_in_tok = out_scaffold = src_tok = n_units = 0
    sample = None
    for phase, reqs, id_maps in all_requests:
        for req in reqs:
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
            n = len(id_maps.get(req["custom_id"], []))
            n_units += n
            out_scaffold += counter("".join('"%d":"",' % i for i in range(1, n + 1)))
            if sample is None and phase == "text":
                sample = usr
    for l in batch["lines"]:
        if pending(l, retranslate_all):
            src_tok += counter(l["source"])

    cache_write_tok = sum(prefix_tok[p] for p in prefix_count)
    cache_read_tok = sum(prefix_tok[p] * (prefix_count[p] - 1) for p in prefix_count)
    raw_in_tok = sum(prefix_tok[p] * prefix_count[p] for p in prefix_count) + dyn_in_tok
    n_req = sum(len(r) for _p, r, _m in all_requests)
    gp = load_game_prompt()
    print(f"requests={n_req} (names phase {len(all_requests[0][1])}, text phase {len(all_requests[1][1])})  "
          f"units={n_units}  model={model}")
    print(f"game prompt: {'loaded (' + str(len(gp)) + ' chars)' if gp else 'MISSING'}   "
          f"glossary: {len(glossary.get('names', {}))} names, {len(glossary.get('terms', {}))} terms")
    print(f"cached prefix: {cache_write_tok:,} tok (re-read {n_req - len(prefix_count)}x)")
    print(f"dynamic input: {dyn_in_tok:,} tok | raw input w/o cache: {raw_in_tok:,} tok")
    print(f"JP source-only tokens: {src_tok:,}")
    pr = price_for(model)
    print(f"\nCost estimate for {model} (batch 50% off; EN/JP output ratio 1.0 / 1.3 / 1.6):")
    for r in (1.0, 1.3, 1.6):
        out = int(src_tok * r) + out_scaffold
        in_cached = (cache_write_tok / 1e6 * pr["cache_write"]
                     + cache_read_tok / 1e6 * pr["cache_read"]
                     + dyn_in_tok / 1e6 * pr["batch_in"])
        batch_cached = in_cached + out / 1e6 * pr["batch_out"]
        batch_nocache = raw_in_tok / 1e6 * pr["batch_in"] + out / 1e6 * pr["batch_out"]
        print(f"  ratio {r}: out~{out:,}  BATCH+cache=${batch_cached:.2f}  batch(no cache)=${batch_nocache:.2f}")
    print(f"\nreasoning effort: {_EFFORT} (higher effort multiplies output cost). "
          "tiktoken proxy; real billing via: batches usage <id>")
    if show_sample and sample:
        print("\n----- SAMPLE USER PROMPT -----\n" + sample[:2500])
    return 0


# --------------------------------------------------------------------------
# submit / status / fetch / run / retry / selftest
# --------------------------------------------------------------------------
def _submit(client, model, requests, id_maps, phase):
    b = client.messages.batches.create(requests=requests)
    print(f"[{phase}] submitted batch {b.id} ({len(requests)} requests).")
    save_state({
        "batch_id": b.id, "model": model, "phase": phase, "id_maps": id_maps,
        "n_requests": len(requests), "created": str(getattr(b, "created_at", "") or ""),
    })
    return b


def cmd_submit(model, max_units, retranslate_all, phase):
    batch = load_batch()
    glossary = load_glossary()
    n_dnt = apply_dnt(batch, glossary)
    if n_dnt:
        save_batch(batch)
    _g, requests, id_maps = build_all(batch, model, max_units, retranslate_all, phase)
    if not requests:
        sys.exit(f"Nothing to translate in phase '{phase}'.")
    client = get_client()
    _submit(client, model, requests, id_maps, phase)
    print("Track with: status / fetch")
    return 0


def cmd_status():
    state = load_state()
    if not state:
        sys.exit("No batch state - run submit first.")
    client = get_client()
    b = client.messages.batches.retrieve(state["batch_id"])
    print(f"batch {b.id} [{state.get('phase')}] : {b.processing_status}")
    rc = getattr(b, "request_counts", None)
    if rc:
        print("  counts:", rc)
    return 0 if b.processing_status == "ended" else 2


def _fetch(client, state):
    batch = load_batch()
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
    applied, errs = apply_results(batch, results, state.get("id_maps", {}))
    save_batch(batch)
    return applied, errored, errs


def cmd_fetch():
    state = load_state()
    if not state:
        sys.exit("No batch state - run submit first.")
    client = get_client()
    applied, errored, errs = _fetch(client, state)
    print(f"Applied {applied} translations.")
    for cid, why in errored[:30]:
        print(f"  ! request {cid}: {why}")
    for e in errs[:20]:
        print(f"  ! {e}")
    return 0


def _run_phase(client, model, requests, id_maps, poll, phase):
    _submit(client, model, requests, id_maps, phase)
    state = load_state()
    print(f"[{phase}] polling every {poll}s (Ctrl-C is safe - resume with: fetch)...")
    while True:
        b = client.messages.batches.retrieve(state["batch_id"])
        print(f"  {time.strftime('%H:%M:%S')}  {b.processing_status}", flush=True)
        if b.processing_status == "ended":
            break
        time.sleep(poll)
    applied, errored, errs = _fetch(client, state)
    print(f"[{phase}] applied {applied} translations ({len(errored)} request errors).")
    for cid, why in errored[:30]:
        print(f"  ! {cid}: {why}")
    return applied


def cmd_run(model, max_units, retranslate_all, poll):
    client = get_client()
    batch = load_batch()
    glossary = load_glossary()
    n_dnt = apply_dnt(batch, glossary)
    if n_dnt:
        save_batch(batch)
        print(f"{n_dnt} do_not_translate lines pre-filled verbatim.")

    # Phase 1 - names first, so the text phase can lock DB names as terms
    # (skill/item names embedded in usage messages stay consistent).
    _g, name_reqs, name_maps = build_all(batch, model, max_units, retranslate_all, "names")
    if name_reqs:
        _run_phase(client, model, name_reqs, name_maps, poll, "names")
    else:
        print("[names] nothing pending.")

    # Phase 2 - dialogue / DB / UI with translated names as extra glossary terms.
    batch = load_batch()
    _g, requests, id_maps = build_all(batch, model, max_units, retranslate_all, "text")
    if not requests:
        print("[text] nothing pending.")
        return 0
    _run_phase(client, model, requests, id_maps, poll, "text")
    print("Next: python scripts/claude_translate.py validate")
    return 0


def cmd_retry(model, max_units, poll, max_rounds):
    client = get_client()
    glossary = load_glossary()
    game_prompt = load_game_prompt()
    dnt = dnt_set(glossary)
    for rnd in range(1, max_rounds + 1):
        batch = load_batch()
        extra_terms = names_extra_terms(batch)
        lines = batch["lines"]
        fail_idx = {i for i, l in enumerate(lines) if hard_issues(l, dnt)}
        if not fail_idx:
            print("[retry] nothing failing - batch is clean.")
            return 0
        # one chunk per scene containing a failure; translated neighbors as context
        by_scene = collections.OrderedDict()
        for i, l in enumerate(lines):
            by_scene.setdefault(scene_key(l), []).append(i)
        chunks = []
        part = 0
        for sk, idxs in by_scene.items():
            fails = [i for i in idxs if i in fail_idx]
            if not fails:
                continue
            ctx = [lines[i] for i in idxs if i not in fail_idx and (lines[i].get("text") or "").strip()][:8]
            for s in range(0, len(fails), max_units):
                chunks.append({
                    "custom_id": sanitize_id(f"retry{part:04d}"),
                    "items": [(i, lines[i]) for i in fails[s:s + max_units]],
                    "file": sk[0], "context": ctx, "names": is_names_file(sk[0]),
                })
                part += 1
        requests, id_maps = [], {}
        for ch in chunks:
            req, idmap = build_request(ch, model, glossary, extra_terms, game_prompt)
            requests.append(req)
            id_maps[ch["custom_id"]] = idmap
        print(f"[retry round {rnd}/{max_rounds}] {len(fail_idx)} failing lines -> {len(requests)} requests.")
        _run_phase(client, model, requests, id_maps, poll, f"retry{rnd}")
    batch = load_batch()
    still = sum(1 for l in batch["lines"] if hard_issues(l, dnt))
    print(f"[retry] done. {still} lines still failing - run `validate` to inspect.")
    return 0


def cmd_selftest(model, max_units):
    batch = load_batch()
    glossary = load_glossary()
    apply_dnt(batch, glossary)
    results, id_maps_all = {}, {}
    total_reqs = 0
    for phase in ("names", "text"):
        _g, requests, id_maps = build_all(batch, model, max_units, False, phase)
        total_reqs += len(requests)
        id_maps_all.update(id_maps)
        for req in requests:
            cid = req["custom_id"]
            out = {}
            for i, li in enumerate(id_maps[cid], 1):
                # JP chars -> 'e' keeps every control code and line break intact.
                out[str(i)] = re.sub(r"[぀-ヿ一-鿿！-～]", "e",
                                     batch["lines"][li]["source"])
            results[cid] = out
    applied, errs = apply_results(batch, results, id_maps_all)
    # batch.json itself is NOT touched - the fake-filled copy goes to a side file.
    side = os.path.join(TL_DIR, "_selftest_batch.json")
    with open(side, "w", encoding="utf-8") as f:
        json.dump(batch, f, ensure_ascii=False, indent=1)
    dnt = dnt_set(glossary)
    bad = [l for l in batch["lines"]
           if (l.get("text") or "").strip() and
           [c for c in hard_issues(l, dnt) if c in ("residual_jp", "codes")]]
    total = len(batch["lines"])
    print(f"selftest: {total_reqs} requests built, applied {applied}/{total} lines, "
          f"{len(errs)} map errors, {len(bad)} code/JP failures")
    for l in bad[:10]:
        print(f"  ! {l['file']} {l['id']}: src{code_multiset(l['source'])} tl{code_multiset(l['text'])}")
    ok = not errs and not bad and applied > 0
    print("SELFTEST", "PASS" if ok else "FAIL")
    print(f"(fake-filled copy written to {side}; batch.json untouched)")
    return 0 if ok else 1


# --------------------------------------------------------------------------
# batches utility (list / cancel / usage)
# --------------------------------------------------------------------------
def cmd_batches(action, ids, limit, model):
    client = get_client()
    state = load_state() or {}
    mine = state.get("batch_id")
    if action == "list":
        print(f"{'BATCH ID':<28} {'STATUS':<12} {'CREATED':<22}")
        for b in client.messages.batches.list(limit=limit):
            mark = "  <- yours" if b.id == mine else ""
            created = str(getattr(b, "created_at", "") or "")[:22]
            print(f"{b.id:<28} {b.processing_status:<12} {created:<22}{mark}")
        return 0
    if action == "cancel":
        targets = ids or ([mine] if mine else [])
        if not targets:
            sys.exit("No batch id given and none in state.")
        for t in targets:
            try:
                b = client.messages.batches.cancel(t)
                print(f"cancel requested: {t} -> {b.processing_status}")
            except Exception as e:
                print(f"! {t}: {e}")
        return 0
    if action == "usage":
        bid = (ids[0] if ids else mine)
        if not bid:
            sys.exit("Give a batch id (or submit first).")
        tot = collections.Counter()
        ok = err = 0
        for r in client.messages.batches.results(bid):
            res = r.result
            if getattr(res, "type", None) != "succeeded":
                err += 1
                continue
            ok += 1
            u = res.message.usage
            tot["in"] += getattr(u, "input_tokens", 0) or 0
            tot["out"] += getattr(u, "output_tokens", 0) or 0
            tot["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
            tot["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        pr = price_for(model)
        cost = (tot["in"] / 1e6 * pr["batch_in"] + tot["out"] / 1e6 * pr["batch_out"]
                + tot["cache_write"] / 1e6 * pr["cache_write"]
                + tot["cache_read"] / 1e6 * pr["cache_read"])
        print(f"batch {bid} ({ok} succeeded, {err} errored)  model={model}")
        for k in ("in", "cache_write", "cache_read", "out"):
            print(f"  {k:<12}: {tot[k]:>12,}")
        print(f"  estimated cost: ${cost:.2f}")
        return 0
    return 1


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    global _EFFORT
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_batch_args(p):
        p.add_argument("--model", default=MODEL_DEFAULT)
        p.add_argument("--max-units", dest="max_units", type=int, default=80)
        p.add_argument("--retranslate-all", dest="retranslate_all", action="store_true")
        p.add_argument("--effort", default=EFFORT_DEFAULT, choices=sorted(_EFFORT_LEVELS))

    p = sub.add_parser("dryrun")
    add_batch_args(p)
    p.add_argument("--show-sample", dest="show_sample", action="store_true")

    p = sub.add_parser("submit")
    add_batch_args(p)
    p.add_argument("--phase", default="text", choices=["names", "text"])

    sub.add_parser("status")
    sub.add_parser("fetch")

    p = sub.add_parser("run")
    add_batch_args(p)
    p.add_argument("--poll", type=int, default=60)

    p = sub.add_parser("validate")
    p.add_argument("--max-issues", dest="max_issues", type=int, default=25)

    p = sub.add_parser("retry")
    add_batch_args(p)
    p.add_argument("--poll", type=int, default=60)
    p.add_argument("--max-rounds", dest="max_rounds", type=int, default=2)

    p = sub.add_parser("selftest")
    add_batch_args(p)

    p = sub.add_parser("batches")
    p.add_argument("action", choices=["list", "cancel", "usage"])
    p.add_argument("ids", nargs="*")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--model", default=MODEL_DEFAULT)

    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if getattr(args, "effort", None):
        _EFFORT = args.effort

    if args.cmd == "dryrun":
        return cmd_dryrun(args.model, args.max_units, args.retranslate_all, args.show_sample)
    if args.cmd == "submit":
        return cmd_submit(args.model, args.max_units, args.retranslate_all, args.phase)
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "fetch":
        return cmd_fetch()
    if args.cmd == "run":
        return cmd_run(args.model, args.max_units, args.retranslate_all, args.poll)
    if args.cmd == "validate":
        return cmd_validate(args.max_issues)
    if args.cmd == "retry":
        return cmd_retry(args.model, args.max_units, args.poll, args.max_rounds)
    if args.cmd == "selftest":
        return cmd_selftest(args.model, args.max_units)
    if args.cmd == "batches":
        return cmd_batches(args.action, args.ids, args.limit, args.model)
    return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
