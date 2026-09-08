#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tl_translate.py — translate the extracted VN JSON (from script_tl.py) with
Claude Sonnet 4.6 via the Anthropic **Message Batches** API, then validate.

Pipeline:  script_tl.py extract  ->  tl_translate.py run  ->  script_tl.py inject

Sub-commands
------------
  dryrun     build the requests and print token/cost estimate + a sample prompt
             (no API key needed — use this to preview)
  submit     create the batch, save its id + id-map to <json>/_batch_state.json
  status     show batch processing status
  fetch      download finished results and write translations into the JSON
  run        submit + poll until done + fetch (one shot)
  validate   completeness / quality checks on the translated JSON
  selftest   build->fake-translate->apply->validate fully offline (no API)

The requests use a compact format: a shared (cached) instruction block, the
per-file character glossary, and the segments to translate listed with short
per-chunk indices grouped under their scene headers. The model returns a JSON
object {index: english}. Indices are mapped back to segment ids locally, so the
expensive long ids are never sent or returned.

Examples
--------
  python tl_translate.py dryrun   tl_json
  python tl_translate.py run      tl_json --max-segments 100
  python tl_translate.py validate tl_json
"""

import os
import re
import sys
import json
import glob
import time
import argparse

MODEL_DEFAULT = "claude-sonnet-4-6"
PRICE = {  # USD per 1M tokens; standard Sonnet 4.x (<=200K ctx). Batch = 50% off.
    "in": 3.0, "out": 15.0,
    "batch_in": 1.5, "batch_out": 7.5,
    "cache_write": 3.75, "cache_read": 0.30,
}
TYPE_ABBR = {"dialogue": "D", "monologue": "M(inner thought)", "narration": "N"}
STATE_NAME = "_batch_state.json"

SYSTEM_SHARED = (
    "You are a professional Japanese-to-English visual-novel translator. You translate an "
    "adult (18+) Japanese VN into natural, fluent, idiomatic English while preserving meaning, "
    "tone, character voice and nuance (including explicit content) — never a stiff literal gloss.\n"
    "You will be given a character glossary and a numbered list of text segments from ONE scene "
    "context. Each segment is tagged D (spoken dialogue), M (inner thought/monologue) or "
    "N (narration). Translate every segment.\n"
    "Rules:\n"
    "- Match each speaker's register/personality from the glossary; keep pronouns and "
    "relationships consistent.\n"
    "- Dialogue keeps its quotation feel; narration reads as prose; monologue as inner thought.\n"
    "- Keep honorifics only when they carry meaning; otherwise render naturally.\n"
    "- A full-width space (　) is just indentation — ignore it.\n"
    "- Do NOT add notes, romaji, or the Japanese text. Do NOT merge or split segments.\n"
    "- Output ONLY a JSON object mapping each segment number (as a string) to its English "
    'translation, e.g. {"1":"...","2":"..."}. Every number present in the input must appear.'
)


# --------------------------------------------------------------------------
# tokenizer (tiktoken proxy; optional)
# --------------------------------------------------------------------------
def get_counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
        return lambda s: len(enc.encode(s))
    except Exception:
        return lambda s: max(1, int(len(s) / 2.0))  # crude fallback


# --------------------------------------------------------------------------
# load / chunk
# --------------------------------------------------------------------------
def load_docs(json_dir):
    files = [p for p in sorted(glob.glob(os.path.join(json_dir, "*.json")))
             if os.path.basename(p) not in (STATE_NAME, "_glossary.json")]
    docs = []
    for p in files:
        docs.append((p, json.load(open(p, encoding="utf-8"))))
    return docs


def build_chunks(docs, max_segments, only_missing=False):
    """Yield chunk dicts that never cross files and stay <= max_segments.
       only_missing: skip segments that already have a translation (gap-fill / retry)."""
    chunks = []
    for path, doc in docs:
        stem = os.path.splitext(os.path.basename(doc["meta"]["source_file"]))[0]
        # flatten this file's segments with their scene header
        flat = []
        for sc in doc["scenes"]:
            header = sc.get("label") or sc.get("scene_id")
            if sc.get("title"):
                header = "%s (%s)" % (header, sc["title"])
            for seg in sc["segments"]:
                if only_missing and seg.get("translation", "").strip():
                    continue
                flat.append((header, seg))
        if not flat:
            continue
        n = max(1, max_segments)
        part = 0
        for i in range(0, len(flat), n):
            part += 1
            sub = flat[i:i + n]
            chunks.append({
                "custom_id": "%s-%02d" % (re.sub(r'[^A-Za-z0-9_-]', '_', stem), part),
                "file": os.path.basename(path),
                "stem": stem,
                "meta": doc["meta"],
                "items": sub,  # list of (header, seg)
            })
    return chunks


def build_user_text(chunk):
    """Compact, scene-grouped segment list with short indices (1..N)."""
    lines = []
    lines.append("Game: %s (%s). Scene context — translate every numbered segment below."
                 % (chunk["meta"].get("game_en", ""), chunk["meta"].get("game_jp", "")))
    cur = None
    idx = 0
    index_map = []  # idx -> seg id
    for header, seg in chunk["items"]:
        if header != cur:
            cur = header
            lines.append("\n# scene: %s" % header)
        idx += 1
        index_map.append(seg["id"])
        spk = seg.get("speaker") or "narration"
        tag = TYPE_ABBR.get(seg["type"], seg["type"])
        src = seg["source"].replace("\n", " / ")  # keep on one line; / = manual line break
        lines.append("[%d] (%s; %s) %s" % (idx, spk, tag, src))
    lines.append('\nReturn ONLY the JSON object {"1":"...", ...} with a translation for every number.')
    return "\n".join(lines), index_map


def build_request(chunk, model, counter):
    user_text, index_map = build_user_text(chunk)
    glossary = json.dumps(chunk["meta"].get("characters", []), ensure_ascii=False, indent=1)
    n = len(index_map)
    # output budget: generous per-segment headroom so verbose chunks don't truncate
    max_tokens = min(60000, max(4000, n * 300))
    req = {
        "custom_id": chunk["custom_id"],
        "params": {
            "model": model,
            "max_tokens": max_tokens,
            "system": [
                {"type": "text", "text": SYSTEM_SHARED,
                 "cache_control": {"type": "ephemeral"}},  # shared across all requests
                {"type": "text", "text": "Character glossary for this file:\n" + glossary},
            ],
            "messages": [
                {"role": "user", "content": user_text},
            ],  # no assistant prefill — Sonnet 4.6 rejects it; rely on JSON-only instruction
        },
    }
    return req, index_map


# --------------------------------------------------------------------------
# response parsing
# --------------------------------------------------------------------------
def parse_json_object(text, prefilled=False):
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r'^```(?:json)?', '', s).strip()
        s = re.sub(r'```$', '', s).strip()
    if prefilled and not s.lstrip().startswith("{"):
        s = "{" + s
    try:
        return json.loads(s)
    except Exception:
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j != -1 and j > i:
            return json.loads(s[i:j + 1])
        raise


def apply_translations(docs, results_by_custom_id, id_maps):
    """results_by_custom_id: {custom_id: {index_str: translation}}.
       id_maps: {custom_id: [seg_id,...]}.  Writes into docs (and to disk)."""
    # build seg_id -> translation
    tr = {}
    errors = []
    for cid, obj in results_by_custom_id.items():
        idmap = id_maps.get(cid, [])
        for k, v in obj.items():
            try:
                n = int(k)
            except ValueError:
                continue
            if 1 <= n <= len(idmap):
                tr[idmap[n - 1]] = v
            else:
                errors.append("%s: index %s out of range" % (cid, k))
    applied = 0
    for path, doc in docs:
        changed = False
        for sc in doc["scenes"]:
            for seg in sc["segments"]:
                if seg["id"] in tr and isinstance(tr[seg["id"]], str):
                    seg["translation"] = tr[seg["id"]]
                    changed = True
                    applied += 1
        if changed:
            json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return applied, errors


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


def save_state(json_dir, state):
    json.dump(state, open(os.path.join(json_dir, STATE_NAME), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2, default=str)  # default=str: datetimes etc.


def snapshot(json_dir):
    """Copy the translation JSON files to a timestamped backup before an overwrite."""
    import datetime, shutil
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(json_dir, "_backup_" + ts)
    os.makedirs(dst, exist_ok=True)
    for p in glob.glob(os.path.join(json_dir, "*.json")):
        if os.path.basename(p) == STATE_NAME:
            continue
        shutil.copy2(p, dst)
    return dst


def load_state(json_dir):
    p = os.path.join(json_dir, STATE_NAME)
    if not os.path.exists(p):
        sys.exit("No batch state at %s — run submit first." % p)
    return json.load(open(p, encoding="utf-8"))


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_dryrun(args):
    docs = load_docs(args.json)
    if getattr(args, "limit_files", 0):
        docs = docs[:args.limit_files]
    chunks = build_chunks(docs, args.max_segments, only_missing=not getattr(args, "retranslate_all", False))
    counter = get_counter()
    in_tok = out_scaffold = src_tok = 0
    sample = None
    for ch in chunks:
        req, idmap = build_request(ch, args.model, counter)
        sysblk = "".join(b["text"] for b in req["params"]["system"])
        usr = req["params"]["messages"][0]["content"]
        in_tok += counter(sysblk) + counter(usr) + 8
        for _h, seg in ch["items"]:
            src_tok += counter(seg["source"])
        out_scaffold += counter("".join('"%d":"",' % i for i in range(1, len(idmap) + 1)))
        if sample is None:
            sample = usr
    n_seg = sum(len(c["items"]) for c in chunks)
    print("files=%d  chunks=%d  segments=%d  model=%s  max-seg/req=%d"
          % (len(docs), len(chunks), n_seg, args.model, args.max_segments))
    print("INPUT  tokens (system+glossary+segments): %s" % f"{in_tok:,}")
    print("JP source-only tokens: %s" % f"{src_tok:,}")
    print("OUTPUT scaffold tokens: %s" % f"{out_scaffold:,}")
    print("\nCost estimate (JP->EN output ratio 1.0 / 1.2 / 1.4):")
    for r in (1.0, 1.2, 1.4):
        out = int(src_tok * r) + out_scaffold
        batch = in_tok / 1e6 * PRICE["batch_in"] + out / 1e6 * PRICE["batch_out"]
        full = in_tok / 1e6 * PRICE["in"] + out / 1e6 * PRICE["out"]
        print("  ratio %.1f: out~%-9s  BATCH=$%.2f   non-batch=$%.2f"
              % (r, f"{out:,}", batch, full))
    print("\n(Token counts via tiktoken o200k_base proxy; Anthropic's tokenizer may differ ~15%.)")
    if args.show_sample and sample:
        print("\n----- SAMPLE USER PROMPT (first chunk) -----\n")
        print(sample[:2500])


def _build_state(args):
    docs = load_docs(args.json)
    if getattr(args, "limit_files", 0):
        docs = docs[:args.limit_files]
    chunks = build_chunks(docs, args.max_segments, only_missing=not getattr(args, "retranslate_all", False))
    counter = get_counter()
    requests = []
    id_maps = {}
    for ch in chunks:
        req, idmap = build_request(ch, args.model, counter)
        requests.append(req)
        id_maps[ch["custom_id"]] = idmap
    return docs, requests, id_maps


def cmd_submit(args):
    docs, requests, id_maps = _build_state(args)
    if not requests:
        sys.exit("Nothing to translate: every selected segment is already translated "
                 "(or the file(s) have no story text). Use --retranslate-all to redo them.")
    if getattr(args, "retranslate_all", False):
        bak = snapshot(args.json)
        print("--retranslate-all: backed up current translations -> %s" % bak)
    client = get_client()
    batch = client.messages.batches.create(requests=requests)
    print("Submitted batch %s  (%d requests)." % (batch.id, len(requests)))  # print id first
    state = {"batch_id": batch.id, "model": args.model, "json_dir": args.json,
             "id_maps": id_maps, "n_requests": len(requests),
             "created": str(getattr(batch, "created_at", "") or "")}
    save_state(args.json, state)
    print("State saved -> %s. Track with: status / fetch / run" % os.path.join(args.json, STATE_NAME))


def cmd_status(args):
    state = load_state(args.json)
    client = get_client()
    b = client.messages.batches.retrieve(state["batch_id"])
    rc = getattr(b, "request_counts", None)
    print("batch %s : %s" % (b.id, b.processing_status))
    if rc:
        print("  counts:", rc)
    return 0 if b.processing_status == "ended" else 2


def _fetch_into(client, state, docs):
    bid = state["batch_id"]
    results = {}
    errored = []
    for r in client.messages.batches.results(bid):
        cid = r.custom_id
        res = r.result
        if res.type != "succeeded":
            detail = res.type
            err = getattr(res, "error", None)
            if err is not None:
                inner = getattr(err, "error", err)
                detail = "%s | %s: %s" % (res.type, getattr(inner, "type", ""),
                                          getattr(inner, "message", "") or str(err)[:300])
            errored.append((cid, detail))
            continue
        text = "".join(getattr(b, "text", "") for b in res.message.content)
        try:
            results[cid] = parse_json_object(text)
        except Exception as e:
            errored.append((cid, "parse_error: %s" % e))
    applied, errs = apply_translations(docs, results, state["id_maps"])
    return applied, errored, errs


def cmd_fetch(args):
    state = load_state(args.json)
    client = get_client()
    docs = load_docs(args.json)
    applied, errored, errs = _fetch_into(client, state, docs)
    print("Applied %d translations." % applied)
    for cid, why in errored:
        print("  ! request %s: %s" % (cid, why))
    for e in errs[:20]:
        print("  ! %s" % e)
    print("Now run: python script_tl.py inject %s --scripts <orig> -o <out>" % args.json)


def cmd_run(args):
    cmd_submit(args)
    state = load_state(args.json)
    client = get_client()
    print("Polling (Ctrl-C is safe — resume later with: fetch)...")
    while True:
        b = client.messages.batches.retrieve(state["batch_id"])
        print("  %s  %s" % (time.strftime("%H:%M:%S"), b.processing_status), flush=True)
        if b.processing_status == "ended":
            break
        time.sleep(args.poll)
    docs = load_docs(args.json)
    applied, errored, errs = _fetch_into(client, state, docs)
    print("Applied %d translations (%d request errors)." % (applied, len(errored)))
    for cid, why in errored:
        print("  ! %s: %s" % (cid, why))
    cmd_validate(args)


def cmd_selftest(args):
    """Offline end-to-end: build -> fake-translate -> apply -> validate."""
    docs, requests, id_maps = _build_state(args)
    print("built %d requests over %d files" % (len(requests), len(docs)))
    # fabricate model responses (echo a marker so validation sees 'translated')
    results = {}
    for req in requests:
        cid = req["custom_id"]
        n = len(id_maps[cid])
        results[cid] = {str(i): "[EN %d] %s" % (i, "test") for i in range(1, n + 1)}
    # round-trip the JSON serialization the model would produce
    for cid in list(results):
        text = json.dumps(results[cid], ensure_ascii=False)
        results[cid] = parse_json_object(text)  # full JSON object (no prefill)
    applied, errs = apply_translations(docs, results, id_maps)
    total = sum(len(s["segments"]) for _p, d in docs for s in d["scenes"])
    print("selftest: applied %d / %d segments, %d map errors" % (applied, total, len(errs)))
    for e in errs[:10]:
        print("  !", e)
    ok = (applied == total and not errs)
    print("SELFTEST", "PASS" if ok else "FAIL")
    return 0 if ok else 1


JP_RE = re.compile(r'[぀-ヿ㐀-鿿ｦ-ﾝ]')


def cmd_validate(args):
    docs = load_docs(args.json)
    total = done = empty = same = jp_left = short = 0
    issues = []
    for path, doc in docs:
        for sc in doc["scenes"]:
            for seg in sc["segments"]:
                total += 1
                tr = seg.get("translation", "")
                if not tr.strip():
                    empty += 1
                    continue
                done += 1
                src = seg.get("source", "")
                if tr.strip() == src.strip():
                    same += 1
                    issues.append("%s identical to source" % seg["id"])
                if JP_RE.search(tr):
                    jp_left += 1
                    issues.append("%s has residual JP: %r" % (seg["id"], tr[:30]))
                # crude length sanity (EN should not be absurdly shorter than JP)
                if src and len(tr) < len(src) * 0.25:
                    short += 1
                    issues.append("%s suspiciously short: %r" % (seg["id"], tr[:30]))
    print("VALIDATION  files=%d segments=%d" % (len(docs), total))
    print("  translated : %d (%.1f%%)" % (done, 100.0 * done / total if total else 0))
    print("  untranslated: %d" % empty)
    print("  identical-to-source: %d" % same)
    print("  residual-Japanese  : %d" % jp_left)
    print("  suspiciously-short : %d" % short)
    maxi = getattr(args, "max_issues", 25)
    for s in issues[:maxi]:
        print("   - %s" % s)
    if len(issues) > maxi:
        print("   ... (%d more)" % (len(issues) - maxi))
    return 0 if (empty == 0 and jp_left == 0 and same == 0) else 1


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("json", help="directory of extracted JSON (from script_tl.py extract)")
        p.add_argument("--model", default=MODEL_DEFAULT)
        p.add_argument("--max-segments", type=int, default=100,
                       help="max segments per batch request (default 100)")
        p.add_argument("--limit-files", type=int, default=0,
                       help="only process the first N json files (pilot/cost test; 0 = all)")
        p.add_argument("--only-missing", action="store_true",
                       help="(default behaviour) translate ONLY still-empty segments")
        p.add_argument("--retranslate-all", action="store_true",
                       help="re-translate & OVERWRITE every segment (full redo). Auto-backs-up "
                            "tl_json/ first. Without this, existing translations are never touched.")

    p = sub.add_parser("dryrun"); common(p)
    p.add_argument("--show-sample", action="store_true"); p.set_defaults(func=cmd_dryrun)
    p = sub.add_parser("submit"); common(p); p.set_defaults(func=cmd_submit)
    p = sub.add_parser("status"); common(p); p.set_defaults(func=cmd_status)
    p = sub.add_parser("fetch"); common(p); p.set_defaults(func=cmd_fetch)
    p = sub.add_parser("run"); common(p)
    p.add_argument("--poll", type=int, default=60, help="seconds between status polls")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("selftest"); common(p); p.set_defaults(func=cmd_selftest)
    p = sub.add_parser("validate"); common(p)
    p.add_argument("--max-issues", type=int, default=25); p.set_defaults(func=cmd_validate)

    args = ap.parse_args()
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
