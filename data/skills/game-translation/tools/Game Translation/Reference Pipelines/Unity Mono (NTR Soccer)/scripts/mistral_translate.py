#!/usr/bin/env python3
"""Translate NTR Soccer JP strings via Mistral (free tier, dual API keys).

Ported from FortuneBride1.12/tooling/scripts/mistral_translate.py.

Free-tier limits measured live from response headers (2026-07-02), PER KEY:
  x-ratelimit-limit-req-minute:    50
  x-ratelimit-limit-tokens-minute: 25000
Two keys are used in parallel (one worker pool per key), each paced by its own
AdaptiveLimiter that syncs to the live x-ratelimit-remaining-* headers.

Inputs  (tools/extracted/):  needs_translation.json  (default)
                             dialogue/ui/actors json (--all mode retranslates everything)
Outputs (tools/translated/): mistral_state.json      (resumable, atomic writes)
                             translations_final.json (merge: official EN + mistral)
                             mistral_report.txt

Usage:
  python scripts/mistral_translate.py run [--model mistral-medium-latest] [--all]
  python scripts/mistral_translate.py status
  python scripts/mistral_translate.py merge     # build translations_final.json
Resumable: rerun `run` after any failure — completed items are skipped.
Validation: placeholders ([pic=N], <tags>, {N}, \\n) must survive translation;
violating items are auto-retried individually, then flagged in the report.
"""
import argparse
import concurrent.futures
import json
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
EXTRACTED = TOOLS / "extracted"
OUTDIR = TOOLS / "translated"
STATE = OUTDIR / "mistral_state.json"
PROMPT_MD = TOOLS / "tl" / "game_prompt.md"
GLOSSARY = TOOLS / "tl" / "glossary.json"

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"


def _load_api_keys():
    """Keys live outside the source so the tools tree can be shared safely:
    env MISTRAL_API_KEYS (comma-separated) or tools/tl/mistral_keys.txt
    (one key per line). Rotate the keys before distributing this folder."""
    import os
    env = os.environ.get("MISTRAL_API_KEYS", "").strip()
    if env:
        return [k.strip() for k in env.split(",") if k.strip()]
    keyfile = TOOLS / "tl" / "mistral_keys.txt"
    if keyfile.exists():
        return [ln.strip() for ln in keyfile.read_text(encoding="utf-8").splitlines()
                if ln.strip() and not ln.startswith("#")]
    sys.exit("no API keys: set MISTRAL_API_KEYS or create tools/tl/mistral_keys.txt")


API_KEYS = _load_api_keys()
REQ_PER_MIN = 50          # per key, measured
TOK_PER_MIN = 25000       # per key, measured
TOKEN_HEADROOM = 3000

JP_RE = re.compile(r"[぀-ヿ一-鿿]")
PLACEHOLDER_RE = re.compile(r"(\[pic=\d+\]|<[^<>]+>|\{\d+\}|\\n)")


def estimate_tokens(text):
    # JP ~1 token/char with Mistral tokenizers; EN ~1 per 3.5 chars. Be pessimistic.
    return int(len(text) * 1.1) + 8


def build_system_prompt():
    bible = PROMPT_MD.read_text(encoding="utf-8")
    g = json.loads(GLOSSARY.read_text(encoding="utf-8"))
    names = "\n".join(
        f"- {jp} => {v['en']} ({v['gender']}; {v['role']})"
        + (f" voice: {v['register']}" if v.get("register") else "")
        for jp, v in g["names"].items()
    )
    terms = "\n".join(f"- {jp} = {en}" for jp, en in g["terms"].items())
    dnt = "\n".join(f"- {x}" for x in g.get("do_not_translate", []))
    return f"""You are a professional JP->EN game localizer. Translate the given Japanese strings into natural English following the game bible and glossary EXACTLY.

{bible}

## Glossary — names (use these spellings, never romanize differently)
{names}

## Glossary — terms (always translate consistently)
{terms}

## Do not translate
{dnt}

## Output format
Return ONLY a JSON object: {{"t": {{"<id>": "<english translation>", ...}}}} with one entry per input id.
Rules:
- Natural English, concise (UI labels terse).
- Preserve markup exactly: [pic=N], <color=...></color>, <b></b>, <i></i>, {{0}}-style placeholders, \\n, leading/trailing whitespace.
- Keep （） parentheses for inner monologue; ♥ ♪ punctuation flavor stays (ASCII ! ? ... fine).
- Never output Japanese characters in translations.
- Do not add quotes, speaker names, or notes that are not in the source."""


def load_needs(all_mode=False):
    """Return list of {id, ja, kind, context} to translate."""
    items = []
    if all_mode:
        dialogue = json.loads((EXTRACTED / "dialogue.json").read_text(encoding="utf-8"))
        for r in dialogue:
            if r["ja"].strip() and JP_RE.search(r["ja"]):
                items.append({
                    "id": f"c{r['conversation']}e{r['entry']}",
                    "ja": r["ja"].strip(),
                    "kind": "dialogue",
                    "context": f"{r['conv_title']} / speaker: {r['actor']}",
                })
        tt = json.loads((EXTRACTED / "ui_texttable.json").read_text(encoding="utf-8"))
        for r in tt:
            if r["ja"].strip() and JP_RE.search(r["ja"]):
                items.append({"id": "ui:" + r["field"], "ja": r["ja"].strip(),
                              "kind": "ui", "context": "UI text table"})
        actors = json.loads((EXTRACTED / "actors.json").read_text(encoding="utf-8"))
        for a in actors:
            if a["ja"].strip() and JP_RE.search(a["ja"]):
                items.append({"id": f"a{a['id']}", "ja": a["ja"].strip(),
                              "kind": "actor", "context": "actor name"})
    else:
        needs = json.loads((EXTRACTED / "needs_translation.json").read_text(encoding="utf-8"))
        for x in needs:
            items.append({"id": f"{x['kind']}:{x['key']}", "ja": x["ja"],
                          "kind": x["kind"], "context": x.get("context", "")})
    # dedupe by ja text, keep first id; remember all ids per ja
    by_ja = {}
    for it in items:
        by_ja.setdefault(it["ja"], it)
    return list(by_ja.values())


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8"))
    return {"translations": {}, "flagged": {}}


def save_state(state):
    OUTDIR.mkdir(exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(STATE)


def placeholders_ok(src, dst):
    return sorted(PLACEHOLDER_RE.findall(src)) == sorted(PLACEHOLDER_RE.findall(dst))


def build_units(items, state, batch_size=40):
    done = state["translations"]
    todo = [it for it in items if it["ja"] not in done]
    units = []
    by_kind = {}
    for it in todo:
        by_kind.setdefault(it["kind"], []).append(it)
    headers = {
        "dialogue": "Story dialogue lines in play order. Translate each line in its speaker's voice.",
        "menu": "Player response-menu options. Short, first-person where natural.",
        "ui": "UI strings (buttons, labels, tooltips, status text). Terse natural UI English.",
        "actor": "Character name-box names.",
        "actor_display": "Character display names.",
        "variable": "Game variable initial values shown to the player.",
    }
    for kind, its in by_kind.items():
        for i in range(0, len(its), batch_size):
            chunk = its[i:i + batch_size]
            units.append({
                "name": f"{kind}#{i // batch_size + 1}",
                "header": headers.get(kind, "Game strings."),
                "items": chunk,
            })
    return units


class AdaptiveLimiter:
    """Paces requests off live x-ratelimit headers (token budget + req budget)."""

    def __init__(self, label):
        self.label = label
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

    def update(self, headers):
        with self.lock:
            try:
                self.tokens_remaining = int(headers.get("x-ratelimit-remaining-tokens-minute",
                                                        self.tokens_remaining))
                self.req_remaining = int(headers.get("x-ratelimit-remaining-req-minute",
                                                     self.req_remaining))
            except (TypeError, ValueError):
                pass


def call_mistral(model, api_key, system_prompt, user_prompt, limiter, max_tokens, retries=6):
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
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    est = estimate_tokens(system_prompt) + estimate_tokens(user_prompt) + max_tokens // 2
    last = None
    for attempt in range(retries + 1):
        limiter.acquire(est)
        try:
            req = urllib.request.Request(ENDPOINT, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                limiter.update(dict(resp.headers))
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
                try:
                    delay = float(ra)   # RFC 9110 also allows an HTTP-date here
                except (TypeError, ValueError):
                    delay = min(60, 2 ** attempt + random.random() * 2)
                time.sleep(delay)
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
        note = f"  ({it['context']})" if it.get("context") else ""
        lines.append(f"{it['id']}{note}: {json.dumps(it['ja'], ensure_ascii=False)}")
    return "\n".join(lines)


def run_units(units, state, model, concurrency_per_key=2):
    """Run all units across both keys. Returns (translated_count, failed_unit_names)."""
    system_prompt = build_system_prompt()
    limiters = [AdaptiveLimiter(f"key{i}") for i in range(len(API_KEYS))]
    state_lock = threading.Lock()
    counter = {"done": 0}
    failed = []
    total_items = sum(len(u["items"]) for u in units)
    started = time.monotonic()

    def work(idx_unit):
        idx, unit = idx_unit
        key_i = idx % len(API_KEYS)
        prompt = build_user_prompt(unit)
        jp_chars = sum(len(it["ja"]) for it in unit["items"])
        max_out = min(12000, max(800, int(jp_chars * 2.2) + 40 * len(unit["items"])))
        tmap, usage = call_mistral(model, API_KEYS[key_i], system_prompt, prompt,
                                   limiters[key_i], max_out)
        id_to_ja = {it["id"]: it["ja"] for it in unit["items"]}
        got, flagged = 0, 0
        with state_lock:
            for k, v in tmap.items():
                ja = id_to_ja.get(k)
                if ja is None or not isinstance(v, str) or not v.strip():
                    continue
                v = v.strip()
                if JP_RE.search(v):
                    state["flagged"][ja] = {"en": v, "reason": "jp-chars-in-output"}
                    flagged += 1
                    continue
                if not placeholders_ok(ja, v):
                    state["flagged"][ja] = {"en": v, "reason": "placeholder-mismatch"}
                    flagged += 1
                    continue
                state["translations"][ja] = v
                state["flagged"].pop(ja, None)
                got += 1
            save_state(state)
            counter["done"] += got
        el = time.monotonic() - started
        print(f"[{el:5.0f}s] key{key_i} {unit['name']}: {got}/{len(unit['items'])}"
              + (f" flagged={flagged}" if flagged else "")
              + f" tok={usage.get('total_tokens', '?')} total={counter['done']}/{total_items}",
              flush=True)

    workers = max(1, concurrency_per_key * len(API_KEYS))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(work, (i, u)): u for i, u in enumerate(units)}
        for fut in concurrent.futures.as_completed(futures):
            unit = futures[fut]
            try:
                fut.result()
            except Exception as e:
                failed.append(unit["name"])
                print(f"FAILED {unit['name']}: {e}", flush=True)
    return counter["done"], failed


def cmd_run(args):
    items = load_needs(all_mode=args.all)
    state = load_state()
    units = build_units(items, state)
    if not units:
        print("nothing to translate — all done")
        return
    total = sum(len(u["items"]) for u in units)
    print(f"{len(units)} batches, {total} strings, model={args.model}, keys={len(API_KEYS)}")

    done, failed = run_units(units, state, args.model)

    # repair pass: retry flagged/missing items individually (up to 3 rounds)
    for round_no in range(1, 4):
        remaining = [it for it in items if it["ja"] not in state["translations"]]
        if not remaining:
            break
        print(f"\nrepair round {round_no}: {len(remaining)} items outstanding")
        units = build_units(remaining, state, batch_size=8)
        run_units(units, state, args.model)

    remaining = [it for it in items if it["ja"] not in state["translations"]]
    print(f"\ndone: {len(state['translations'])} translated, "
          f"{len(remaining)} unresolved, {len(state['flagged'])} flagged")
    if remaining:
        for it in remaining[:20]:
            print("  UNRESOLVED:", it["id"], it["ja"][:60])
        print("rerun `run` to retry, or fix by hand in mistral_state.json")


def cmd_status(args):
    items = load_needs(all_mode=args.all)
    state = load_state()
    remaining = [it for it in items if it["ja"] not in state["translations"]]
    print(f"needed: {len(items)}  translated: {len(state['translations'])}  "
          f"remaining: {len(remaining)}  flagged: {len(state['flagged'])}")


def cmd_merge(args):
    """official EN (jp_to_en.json) + mistral results -> translations_final.json"""
    official = json.loads((EXTRACTED / "jp_to_en.json").read_text(encoding="utf-8"))
    state = load_state()
    final = dict(official)
    added = 0
    for ja, en in state["translations"].items():
        if ja not in final:
            final[ja] = en
            added += 1
    OUTDIR.mkdir(exist_ok=True)
    out = OUTDIR / "translations_final.json"
    out.write_text(json.dumps(final, ensure_ascii=False, indent=1), encoding="utf-8")
    # integrity report
    bad = [(ja, en) for ja, en in final.items() if JP_RE.search(en)]
    ph_bad = [(ja, en) for ja, en in final.items()
              if ja in state["translations"] and not placeholders_ok(ja, en)]
    report = [
        f"total entries: {len(final)}",
        f"from official EN: {len(official)}",
        f"from mistral: {added}",
        f"entries with JP left in EN (must be 0): {len(bad)}",
        f"mistral entries with placeholder mismatch (must be 0): {len(ph_bad)}",
    ]
    (OUTDIR / "mistral_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))
    print(f"wrote {out}")


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--model", default="mistral-medium-latest")
    p.add_argument("--all", action="store_true",
                   help="retranslate every JP string, not just the gaps")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("status")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("merge")
    p.set_defaults(func=cmd_merge)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
