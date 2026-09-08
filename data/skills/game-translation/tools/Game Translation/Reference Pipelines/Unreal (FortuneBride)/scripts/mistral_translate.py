#!/usr/bin/env python3
"""Translate translation_master.json JP->EN via Mistral (free tier optimized).

Free-tier limits measured from response headers for this key:
  50 requests/minute, 50,000 tokens/minute (input+output combined).
The system prompt (game bible + glossary, ~5k tokens) is resent per request, so
throughput is maximized by few LARGE batches; pacing adapts to the live
x-ratelimit-remaining-tokens-minute header instead of a fixed RPM.

Usage:
  python scripts/mistral_translate.py run [--model mistral-large-latest]
  python scripts/mistral_translate.py status
  python scripts/mistral_translate.py inject     # state -> master json + translations.csv

Resumable: results stream into work/mistral_translations.json after every batch.
"""
import argparse
import concurrent.futures
import csv
import json
import random
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

TOOLING = Path(__file__).resolve().parent.parent
WORK = TOOLING / "work"
MASTER = WORK / "translation_master.json"
STATE = WORK / "mistral_translations.json"
CSV_PATH = WORK / "translations.csv"
PROMPT_MD = TOOLING / "tl" / "game_prompt.md"
GLOSSARY = TOOLING / "tl" / "glossary.json"

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
API_KEY = ""

REQ_PER_MIN = 50
TOK_PER_MIN = 50000
TOKEN_HEADROOM = 4000          # leave a margin under the TPM cap
JP_RE = re.compile(r"[぀-ヿ一-鿿]")
DEV_PAT = re.compile(
    r"Warning:|ConstructionScript|AnimSequence|モンタージュ|シェイプキー|Morph|"
    r"コンポーネント|取得失敗|想定されていない|DAに|ＢＳ|デフォルトになるような|優先度が高いのはダメ"
)


ALLOWED_CHAR_RE = re.compile(
    r"[ -~　-ヿ一-鿿！-～"
    r"—-‧Ⅰ-ⅿ①-⓿■-◿♠-♧✀-➿"
    r"⭐★☆♪-♭♥♡㈱\n\r\t]"
)
KANA_RE = re.compile(r"[぀-ゟ゠-ヿ]")


def looks_garbage(text):
    if not JP_RE.search(text):
        return True
    # any char outside the JP/ASCII/markup allowlist => binary misread as text
    if any(not ALLOWED_CHAR_RE.match(ch) for ch in text):
        return True
    # kanji-only runs are valid only when short (item names like 緑札, 呪春画)
    if not KANA_RE.search(text) and not re.search(r"[ -~！-～]", text) and len(text) > 6:
        return True
    return False


def estimate_tokens(text):
    # JP ~1 token/char with Mistral tokenizers; EN ~1 per 3.5 chars. Be pessimistic.
    return int(len(text) * 1.1) + 8


def build_system_prompt():
    bible = PROMPT_MD.read_text(encoding="utf-8")
    g = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    names = "\n".join(
        f"- {jp} => {v['en']} ({v['gender']}; {v['role']}) voice: {v['register']}"
        for jp, v in g["names"].items()
    )
    terms = "\n".join(f"- {jp} = {en}" for jp, en in g["terms"].items())
    return f"""You are a professional JP->EN game localizer. Translate the given numbered Japanese strings into natural English following the game bible and glossary EXACTLY.

{bible}

## Glossary — names (use these spellings, never romanize differently)
{names}

## Glossary — terms (always translate consistently)
{terms}

## Output format
Return ONLY a JSON object: {{"t": {{"<id>": "<english translation>", ...}}}} with one entry per input id.
Rules:
- Natural English, concise (target <= 1.8x the Japanese character count where possible; UI labels terse).
- Preserve markup exactly: <Green></>, <LightGreen></>, <Red></>, <yellow></>, <img id=\"...\"/>, {{Placeholder}}, \\n, leading/trailing whitespace.
- Keep （） parentheses for inner monologue, keep ♥ ♪ … ！？ punctuation flavor (ASCII equivalents fine: ! ? ...).
- Never output Japanese characters in translations.
- Do not add quotes, speaker names, or notes that are not in the source."""


def load_master():
    return json.loads(MASTER.read_text(encoding="utf-8"))


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"translations": {}, "skipped": {}}


def save_state(state, lock=None):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def build_units(master, state):
    """Yield work units: dicts with name, items [{id, text, note}], context header."""
    done = state["translations"]
    units = []

    # speakers first — one tiny unit so names lock in
    sp_items = []
    for jp, v in master["speakers"].items():
        uid = "speaker:" + jp
        if uid not in done:
            sp_items.append({"id": uid, "text": jp, "note": f"name-box, {v['lines']} lines"})
    if sp_items:
        units.append({"name": "speakers", "header": "Name-box speaker names.", "items": sp_items})

    # dialogue scenes, split big ones at ~45 lines with 3 lines of carried context
    for scene in master["dialogue_scenes"]:
        lines = scene["lines"]
        chunks = [lines[i : i + 45] for i in range(0, len(lines), 45)]
        for ci, chunk in enumerate(chunks):
            items, ctx = [], []
            if ci > 0:
                for prev in chunks[ci - 1][-3:]:
                    ctx.append(f"[{prev['speaker']}] {prev['source']}")
            for ln in chunk:
                segs = ln.get("segments")
                if segs:
                    for si, seg in enumerate(segs):
                        uid = seg["csv_id"]
                        if uid not in done:
                            items.append({"id": uid, "text": seg["source"],
                                          "note": f"speaker {ln['speaker']}, part {si+1}/{len(segs)}"})
                else:
                    uid = ln.get("csv_id")
                    if uid and uid not in done:
                        items.append({"id": uid, "text": ln["source"], "note": f"speaker {ln['speaker']}"})
            if items:
                name = scene["scene"] + (f"#{ci+1}" if len(chunks) > 1 else "")
                header = (
                    f"Dialogue scene '{scene['scene']}' in play order. Translate each line in its speaker's voice."
                    + ("\nPrevious lines for context (do NOT translate):\n" + "\n".join(ctx) if ctx else "")
                )
                units.append({"name": name, "header": header, "items": items})

    # charms: name+description pairs, ~45 strings per batch
    charm_items = []
    for asset, entries in master["charms"].items():
        for e in entries:
            if e["csv_id"] not in done:
                charm_items.append({"id": e["csv_id"], "text": e["source"], "note": asset.replace("DA_Charm_", "")})
    for i in range(0, len(charm_items), 45):
        units.append({
            "name": f"charms#{i//45+1}",
            "header": "Charm item names and slot-effect descriptions. Names short and punchy; keep stat markup intact.",
            "items": charm_items[i : i + 45],
        })

    # typewriter cards: name+flavor pairs (flavor is the GM/cult voice, dark-playful)
    tw = [e for e in master["typewriter_options"] if e["csv_id"] not in done]
    for i in range(0, len(tw), 40):
        units.append({
            "name": f"typewriter#{i//40+1}",
            "header": "Typewriter buff cards: alternating card titles and sinister-playful flavor lines from the cult. Keep flavor menacing and colloquial.",
            "items": [{"id": e["csv_id"], "text": e["source"], "note": ""} for e in tw[i : i + 40]],
        })

    # ui per widget, batched
    ui_items = []
    for asset, entries in master["ui"].items():
        for e in entries:
            if e["csv_id"] in done or e["csv_id"] in state["skipped"]:
                continue
            if asset.startswith("T_") or asset.endswith("_RedButton3D") or looks_garbage(e["source"]):
                # texture/static-mesh assets carry no real text — binary misreads only
                state["skipped"][e["csv_id"]] = "garbage"
                continue
            ui_items.append({"id": e["csv_id"], "text": e["source"], "note": asset})
    for i in range(0, len(ui_items), 45):
        units.append({
            "name": f"ui#{i//45+1}",
            "header": "UI widget strings (buttons, labels, tooltips, status text). Terse natural UI English; preserve markup/placeholders exactly.",
            "items": ui_items[i : i + 45],
        })

    # other: skip dev/debug noise
    other_items = []
    for e in master["other"]:
        if e["csv_id"] in done or e["csv_id"] in state["skipped"]:
            continue
        if DEV_PAT.search(e["source"]) or looks_garbage(e["source"]):
            state["skipped"][e["csv_id"]] = "dev/garbage"
            continue
        other_items.append({"id": e["csv_id"], "text": e["source"], "note": e.get("asset", "")})
    for i in range(0, len(other_items), 45):
        units.append({
            "name": f"other#{i//45+1}",
            "header": "Misc strings (gameplay messages, trait descriptions). Preserve markup exactly.",
            "items": other_items[i : i + 45],
        })

    return units


class AdaptiveLimiter:
    """Paces requests off live x-ratelimit headers (token budget + req budget)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.tokens_remaining = TOK_PER_MIN
        self.req_remaining = REQ_PER_MIN
        self.window_reset = time.monotonic() + 60

    def acquire(self, est_tokens):
        while True:
            with self.lock:
                now = time.monotonic()
                if now >= self.window_reset:
                    self.tokens_remaining = TOK_PER_MIN
                    self.req_remaining = REQ_PER_MIN
                    self.window_reset = now + 60
                if self.req_remaining > 0 and self.tokens_remaining - est_tokens > TOKEN_HEADROOM:
                    self.req_remaining -= 1
                    self.tokens_remaining -= est_tokens
                    return
                sleep_for = max(0.5, self.window_reset - now)
            time.sleep(min(sleep_for, 5))

    def update(self, headers, est_tokens, actual_tokens):
        with self.lock:
            try:
                self.tokens_remaining = int(headers.get("x-ratelimit-remaining-tokens-minute", self.tokens_remaining))
                self.req_remaining = int(headers.get("x-ratelimit-remaining-req-minute", self.req_remaining))
            except (TypeError, ValueError):
                pass
            # refund estimate error (we already subtracted est; headers are authoritative anyway)


def call_mistral(model, system_prompt, user_prompt, limiter, max_tokens, retries=6):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    est = estimate_tokens(system_prompt) + estimate_tokens(user_prompt.encode("utf-8", "ignore").decode("utf-8", "ignore")) + max_tokens // 2
    last = None
    for attempt in range(retries + 1):
        limiter.acquire(est)
        try:
            req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                limiter.update(dict(resp.headers), est, data.get("usage", {}).get("total_tokens", est))
            content = data["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
            parsed = json.loads(content)
            tmap = parsed.get("t") or parsed.get("translations") or {}
            if not isinstance(tmap, dict):
                raise ValueError("no translation map in response")
            return tmap, data.get("usage", {})
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:
                pass
            last = f"HTTP {e.code} {detail}"
            if e.code == 429:
                ra = e.headers.get("Retry-After")
                time.sleep(float(ra) if ra else min(60, 2 ** attempt + random.random() * 2))
                continue
            if 500 <= e.code < 600 and attempt < retries:
                time.sleep(min(45, 2 ** attempt + random.random()))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError, KeyError) as e:
            last = str(e)
            if attempt < retries:
                time.sleep(min(45, 2 ** attempt + random.random()))
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or "request failed")


def build_user_prompt(unit):
    lines = [unit["header"], "", "Translate these strings (id => Japanese):"]
    for it in unit["items"]:
        note = f"  ({it['note']})" if it["note"] else ""
        lines.append(f"{it['id']}{note}: {json.dumps(it['text'], ensure_ascii=False)}")
    return "\n".join(lines)


def cmd_run(args):
    master = load_master()
    state = load_state()
    system_prompt = build_system_prompt()
    units = build_units(master, state)
    save_state(state)  # persist garbage/dev skips
    if not units:
        print("nothing to translate — all done")
        return
    total_items = sum(len(u["items"]) for u in units)
    print(f"{len(units)} batches, {total_items} strings to translate, model={args.model}")
    print(f"system prompt ~{estimate_tokens(system_prompt)} est tokens (resent per request)")

    limiter = AdaptiveLimiter()
    state_lock = threading.Lock()
    done_count = 0
    failed = []

    def work(unit):
        prompt = build_user_prompt(unit)
        jp_chars = sum(len(it["text"]) for it in unit["items"])
        max_out = min(12000, max(1500, int(jp_chars * 2.2) + 40 * len(unit["items"])))
        tmap, usage = call_mistral(args.model, system_prompt, prompt, limiter, max_out)
        return unit, tmap, usage

    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as ex:
        futures = {ex.submit(work, u): u for u in units}
        for fut in concurrent.futures.as_completed(futures):
            unit = futures[fut]
            try:
                unit, tmap, usage = fut.result()
            except Exception as e:
                failed.append(unit["name"])
                print(f"FAILED {unit['name']}: {e}", flush=True)
                continue
            wanted = {it["id"] for it in unit["items"]}
            got = 0
            with state_lock:
                for k, v in tmap.items():
                    if k in wanted and isinstance(v, str) and v.strip() and not JP_RE.search(v):
                        state["translations"][k] = v.strip()
                        got += 1
                save_state(state)
            done_count += got
            missing = len(wanted) - got
            el = time.monotonic() - started
            print(f"[{el:5.0f}s] {unit['name']}: {got}/{len(wanted)}"
                  + (f" (missing {missing})" if missing else "")
                  + f"  tok={usage.get('total_tokens','?')}  total={done_count}/{total_items}", flush=True)

    print(f"\ndone: {done_count} translated, {len(failed)} failed batches {failed if failed else ''}")
    print("rerun `run` to fill gaps, then `inject`.")


def cmd_status(args):
    state = load_state()
    master = load_master()
    units = build_units(master, state)
    remaining = sum(len(u["items"]) for u in units)
    print(f"translated: {len(state['translations'])}  skipped(dev/garbage): {len(state['skipped'])}  remaining: {remaining}")


ASCII_FOLD = {
    "’": "'", "‘": "'", "“": '"', "”": '"', "…": "...", "—": "-", "–": "-",
    "→": "->", "×": "x", "ō": "o", " ": " ",
}


def ascii_fold(text):
    # keep translations ANSI-encodable so they fit the fixed byte spans
    for k, v in ASCII_FOLD.items():
        text = text.replace(k, v)
    return text


def unsquash(text):
    # "CursedSpring" -> "Cursed Spring" (charm names returned as CamelCase)
    if re.fullmatch(r"(?:[A-Z][a-z]+){2,}", text):
        return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", text)
    return text


def cmd_inject(args):
    state = load_state()
    tr = {k: unsquash(ascii_fold(v)) for k, v in state["translations"].items()}
    master = load_master()

    # 1) master json (human-reviewable)
    filled = 0
    for jp, v in master["speakers"].items():
        t = tr.get("speaker:" + jp)
        if t:
            v["translation"] = t
    for scene in master["dialogue_scenes"]:
        for ln in scene["lines"]:
            if ln.get("segments"):
                for seg in ln["segments"]:
                    if seg["csv_id"] in tr:
                        seg["translation"] = tr[seg["csv_id"]]; filled += 1
            elif ln.get("csv_id") in tr:
                ln["translation"] = tr[ln["csv_id"]]; filled += 1
    for bucket in ("charms", "ui"):
        for entries in master[bucket].values():
            for e in entries:
                if e["csv_id"] in tr:
                    e["translation"] = tr[e["csv_id"]]; filled += 1
    for e in master["typewriter_options"] + master["other"]:
        if e["csv_id"] in tr:
            e["translation"] = tr[e["csv_id"]]; filled += 1
    MASTER.write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) translations.csv — speaker translations fan out to every occurrence
    speaker_ids = {}
    for jp, v in master["speakers"].items():
        t = tr.get("speaker:" + jp)
        if t:
            for cid in v["csv_ids"]:
                speaker_ids[cid] = t

    rows = list(csv.DictReader(CSV_PATH.open(encoding="utf-8-sig")))
    csv_filled = 0
    for r in rows:
        if "/NameMap/" in r["json_pointer"]:
            continue  # FName identifiers — translating corrupts the asset
        t = tr.get(r["id"]) or speaker_ids.get(r["id"])
        if t and t != r["translation"]:
            r["translation"] = t
            csv_filled += 1
    fields = ["id", "json_file", "kind", "json_pointer", "raw_offset", "encoding",
              "source", "translation", "key", "group_id", "segment_index",
              "segment_count", "segment_prefix", "segment_separator"]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"master json: {filled} translations; translations.csv: {csv_filled} rows filled")
    print("next: scripts\\05_apply_text_and_rebuild.ps1 then scripts\\06_pack_patch.ps1 -Install")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--model", default="mistral-large-latest")
    p.add_argument("--concurrency", type=int, default=3)
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("status"); p.set_defaults(func=cmd_status)
    p = sub.add_parser("inject"); p.set_defaults(func=cmd_inject)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
