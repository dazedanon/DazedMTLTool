#!/usr/bin/env python3
"""Translate workspace/units.json JP->EN with the Mistral API (free tier).

Ported from Reference Pipelines/Unity Mono (NTR Soccer)/scripts/mistral_translate.py.
Free-tier limits measured live on this account (2026-08-28), PER KEY:
    x-ratelimit-limit-req-minute:    50
    x-ratelimit-limit-tokens-minute: 25000
Both keys run in parallel, each paced by its own limiter synced to the live
x-ratelimit-remaining-* headers.

Batching follows the rule that dialogue needs continuity and everything else does
not: dialogue goes out one SCENE at a time, in play order, with speaker labels,
and is not deduped. UI / dropdown / literal strings are deduped globally and sent
in one cheap batch.

  python tools/translate_mistral.py run [--model mistral-medium-latest] [--retranslate]
  python tools/translate_mistral.py status
  python tools/translate_mistral.py report

Resumable: rerun `run` after any failure, finished units are skipped.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import random
import re
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hitonatsu import common as C  # noqa: E402

ENDPOINT = "https://api.mistral.ai/v1/chat/completions"
STATE = os.path.join(C.WORKSPACE, "mistral_state.json")
BIBLE = os.path.join(C.WORKSPACE, "bible.md")

REQ_PER_MIN = 50
TOK_PER_MIN = 25000
TOKEN_HEADROOM = 3000


def load_api_keys() -> list[str]:
    """Keys live outside the source tree so this folder can be shared safely."""
    env = os.environ.get("MISTRAL_API_KEYS", "").strip()
    if env:
        return [k.strip() for k in env.split(",") if k.strip()]
    keyfile = os.path.join(C.PROJECT, "tl", "mistral_keys.txt")
    if os.path.exists(keyfile):
        return [ln.strip() for ln in open(keyfile, encoding="utf-8")
                if ln.strip() and not ln.startswith("#")]
    sys.exit("no API keys: set MISTRAL_API_KEYS, or create tl/mistral_keys.txt "
             "(one key per line, gitignored)")


def estimate_tokens(text: str) -> int:
    # Japanese runs near 1 token/char on Mistral's tokenizer. Be pessimistic.
    return int(len(text) * 1.1) + 8


# --- prompt ---------------------------------------------------------------

KIND_HEADERS = {
    "dialogue": ("Story dialogue, in play order, one scene. Translate each line in its "
                 "speaker's voice and keep the lines separate - they are shown one at a "
                 "time and each is timed to its own voice clip."),
    "choice": "Player choice-menu buttons. Short, first person, no trailing period.",
    "ui": ("Settings / menu UI labels. Terse product English, sentence case, no trailing "
           "period. Keep them at or below the Japanese length where you can."),
    "dropdown": "Dropdown option labels. Very short noun phrases.",
    "literal": "Short UI labels compiled into the game binary.",
    "composed": ("Single units of a duration readout that the game concatenates, e.g. "
                 "hours/minutes. Give the SHORT English unit a player expects next to a "
                 "number ('h', 'm', 's', 'd'). No leading space - the injector adds spacing."),
}


def build_system_prompt() -> str:
    bible = open(BIBLE, encoding="utf-8").read()
    g = json.load(open(C.GLOSSARY, encoding="utf-8"))
    names = "\n".join(
        f"- {jp} => {v['en']} ({v['gender']}; {v['role']}) voice: {v['register']}"
        for jp, v in g["names"].items()
    )
    unnamed = "\n".join(
        f"- {k}: {v['en_reference']} ({v['gender']}) {v['role']} voice: {v['register']}"
        for k, v in g.get("unnamed_characters", {}).items()
    )
    terms = "\n".join(f"- {jp} = {en}" for jp, en in g["terms"].items())
    rules = "\n".join(f"- {k}: {v}" for k, v in g["register_rules"].items())
    dnt = "\n".join(f"- {x}" for x in g.get("do_not_translate", []))

    return f"""You are a professional JP->EN game localizer. Translate the given Japanese strings into natural English, following the game bible and glossary EXACTLY.

{bible}

## Glossary - names (use these spellings, never romanize differently)
{names}

## Glossary - unnamed characters
{unnamed}

## Glossary - terms (always translate consistently)
{terms}

## Register rules
{rules}

## Never translate these (they are keys, not text)
{dnt}

## Placeholders
Some strings contain sentinels of the form U+27E6 digit U+27E7, for example the
bracket pair around a 0. Each stands for a control code that was removed before
translation (a TextMeshPro rich-text tag, a line break, a variable slot).
- Reproduce EVERY sentinel exactly once, unchanged, in the same relative position.
- Never invent, drop, reorder or renumber one.
- Never put a space immediately inside a sentinel.

## Output format
Return ONLY a JSON object: {{"t": {{"<id>": "<english>", ...}}}} - one entry per input id, ids unchanged.
Rules:
- Never output Japanese characters.
- Keep the fullwidth brackets, and the spaces inside them, on any line that has them: the protagonist's lines look like this and the game relies on it.
- Render fullwidth ellipsis as "..." and keep it in the same position (leading ellipsis stays leading).
- Do not add speaker names, quotes, notes or explanations that are not in the source.
- Do not merge or split lines. One input string produces exactly one output string."""


def build_user_prompt(unit: dict) -> str:
    """Ids in the prompt are batch-local and opaque (n1, n2...).

    The real unit ids look like `ui:6404:MonoBehaviour.m_text`, and the model
    reliably truncates them at the second colon - so it answered with keys that
    matched nothing and every UI batch silently scored 0/8. Short tokens it has
    no urge to "tidy" round-trip cleanly; `unit["keymap"]` maps them back.
    """
    lines = [unit["header"], "", "Translate these strings (id => Japanese):"]
    for it in unit["items"]:
        bits = [b for b in (it.get("speaker_label"), it.get("note"), it.get("why")) if b]
        note = f"  [{'; '.join(bits)}]" if bits else ""
        lines.append(f"{it['key']}{note}: {json.dumps(it['text'], ensure_ascii=False)}")
    return "\n".join(lines)


def keyed(items: list[dict]) -> tuple[list[dict], dict[str, str]]:
    """Attach batch-local keys and return the key -> unit-id map."""
    keymap = {}
    for i, it in enumerate(items, 1):
        it["key"] = f"n{i}"
        keymap[it["key"]] = it["id"]
    return items, keymap


# --- batching -------------------------------------------------------------

def build_batches(units: list[dict], done: dict, retranslate: bool) -> list[dict]:
    # A locked unit is generated by the extractor, not the model.
    todo = [u for u in units
            if not u.get("locked") and (retranslate or not done.get(u["id"]))]
    todo = [u for u in todo if u["kind"] != "composed" or True]
    batches: list[dict] = []

    # Dialogue: one batch per scene, in play order, speakers attached, NOT deduped.
    dialogue = [u for u in todo if u["kind"] in ("dialogue", "choice")]
    scenes: dict[str, list[dict]] = {}
    for u in dialogue:
        scenes.setdefault(u.get("scene") or "misc", []).append(u)
    for scene in sorted(scenes, key=lambda s: (s == "misc", s)):
        items = sorted(scenes[scene], key=lambda u: u.get("order", 0))
        its, keymap = keyed([{
            "id": u["id"],
            "text": u["masked"],
            "speaker_label": ("the protagonist (male, player)" if u.get("is_player")
                              else "Miu (female)"),
            "note": u.get("note"),
        } for u in items])
        batches.append({"name": f"dialogue/{scene}", "header": KIND_HEADERS["dialogue"],
                        "items": its, "keymap": keymap})

    # Everything else: deduped on the masked source, one batch per kind.
    for kind in ("ui", "dropdown", "literal"):
        group = [u for u in todo if u["kind"] == kind]
        seen: dict[str, dict] = {}
        for u in group:
            seen.setdefault(u["masked"], u)
        items = list(seen.values())
        if not items:
            continue
        for i in range(0, len(items), 40):
            chunk = items[i:i + 40]
            its, keymap = keyed([{"id": u["id"], "text": u["masked"],
                                  "why": u.get("why")} for u in chunk])
            batches.append({"name": f"{kind}#{i // 40 + 1}",
                            "header": KIND_HEADERS[kind],
                            "items": its, "keymap": keymap})
    return batches


# --- transport ------------------------------------------------------------

class AdaptiveLimiter:
    """Paces requests off the live x-ratelimit headers (token budget + req budget)."""

    def __init__(self, label: str):
        self.label = label
        self.lock = threading.Lock()
        self.tokens_remaining = TOK_PER_MIN
        self.req_remaining = REQ_PER_MIN
        self.window_reset = time.monotonic() + 60

    def acquire(self, est_tokens: int) -> None:
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
            # Capped so header updates written by the other thread are seen mid-wait.
            time.sleep(min(sleep_for, 5))

    def update(self, headers: dict) -> None:
        with self.lock:
            for attr, name in (("tokens_remaining", "x-ratelimit-remaining-tokens-minute"),
                               ("req_remaining", "x-ratelimit-remaining-req-minute")):
                try:
                    setattr(self, attr, int(headers.get(name, getattr(self, attr))))
                except (TypeError, ValueError):
                    pass


def call_mistral(model, api_key, system_prompt, user_prompt, limiter, max_tokens, retries=6):
    body = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system_prompt},
                     {"role": "user", "content": user_prompt}],
        "temperature": 0.2,
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
                content = "".join(p.get("text", "") if isinstance(p, dict) else str(p)
                                  for p in content)
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
                    delay = float(ra)
                except (TypeError, ValueError):
                    delay = min(60, 2 ** attempt + random.random() * 2)
                time.sleep(delay)
                continue
            if 500 <= e.code < 600 and attempt < retries:
                time.sleep(min(45, 2 ** attempt + random.random()))
                continue
            raise RuntimeError(last)
        except (urllib.error.URLError, TimeoutError, ValueError,
                json.JSONDecodeError, KeyError) as e:
            last = str(e)
            if attempt < retries:
                time.sleep(min(45, 2 ** attempt + random.random()))
                continue
            raise RuntimeError(last)
    raise RuntimeError(last or "request failed")


# --- validation -----------------------------------------------------------

def validate(src_masked: str, en: str) -> str | None:
    """Return a failure reason, or None if the translation is acceptable."""
    if not en or not en.strip():
        return "empty"
    if C.has_jp(en):
        return "japanese-left-in-output"
    if C.placeholders(src_masked) != C.placeholders(en):
        return "placeholder-mismatch"
    # The bracket convention marks the protagonist's spoken lines and the game
    # renders it; losing it silently reattributes the line.
    if "「" in src_masked and "「" not in en:
        return "lost-speaker-brackets"
    return None


# --- state ----------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE):
        return json.load(open(STATE, encoding="utf-8"))
    return {"translations": {}, "flagged": {}, "usage": {"in": 0, "out": 0, "calls": 0}}


def save_state(state: dict) -> None:
    os.makedirs(C.WORKSPACE, exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def write_back(units_doc: dict, state: dict) -> None:
    """Fold finished translations into units.json. Overwrites, never fills blanks."""
    for u in units_doc["units"]:
        if u.get("locked"):
            continue
        en = state["translations"].get(u["id"])
        if en:
            u["tl"] = C.unmask(en, u.get("codes") or {})
    tmp = C.UNITS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(units_doc, f, ensure_ascii=False, indent=1)
    os.replace(tmp, C.UNITS)


# --- run ------------------------------------------------------------------

def run_batches(batches, units_by_id, state, model, api_keys, concurrency_per_key=2):
    system_prompt = build_system_prompt()
    limiters = [AdaptiveLimiter(f"key{i}") for i in range(len(api_keys))]
    lock = threading.Lock()
    counter = {"done": 0}
    failed = []
    total = sum(len(b["items"]) for b in batches)
    started = time.monotonic()

    def work(idx_batch):
        idx, batch = idx_batch
        key_i = idx % len(api_keys)
        prompt = build_user_prompt(batch)
        jp_chars = sum(len(it["text"]) for it in batch["items"])
        max_out = min(12000, max(800, int(jp_chars * 2.6) + 60 * len(batch["items"])))
        tmap, usage = call_mistral(model, api_keys[key_i], system_prompt, prompt,
                                   limiters[key_i], max_out)
        got = flagged = 0
        with lock:
            for rkey, en in tmap.items():
                uid = batch["keymap"].get(rkey, rkey)
                u = units_by_id.get(uid)
                if u is None or not isinstance(en, str):
                    continue
                en = en.strip()
                reason = validate(u["masked"], en)
                if reason:
                    state["flagged"][uid] = {"en": en, "reason": reason,
                                             "src": u["src"]}
                    flagged += 1
                    continue
                state["translations"][uid] = en
                state["flagged"].pop(uid, None)
                got += 1
            state["usage"]["in"] += usage.get("prompt_tokens", 0)
            state["usage"]["out"] += usage.get("completion_tokens", 0)
            state["usage"]["calls"] += 1
            save_state(state)
            counter["done"] += got
        el = time.monotonic() - started
        print(f"[{el:5.0f}s] key{key_i} {batch['name']}: {got}/{len(batch['items'])}"
              + (f" flagged={flagged}" if flagged else "")
              + f" tok={usage.get('total_tokens', '?')}"
              f" total={counter['done']}/{total}", flush=True)

    workers = max(1, concurrency_per_key * len(api_keys))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(work, (i, b)): b for i, b in enumerate(batches)}
        for fut in concurrent.futures.as_completed(futs):
            b = futs[fut]
            try:
                fut.result()
            except Exception as e:
                failed.append(b["name"])
                print(f"FAILED {b['name']}: {e}", flush=True)
    return counter["done"], failed


def cmd_run(args):
    api_keys = load_api_keys()
    doc = json.load(open(C.UNITS, encoding="utf-8"))
    units = doc["units"]
    units_by_id = {u["id"]: u for u in units}
    state = load_state()

    batches = build_batches(units, state["translations"], args.retranslate)
    if not batches:
        # Still fold state back in. The store is the durable record and
        # units.json is derived from it, so a run that has nothing left to
        # translate must still be able to rebuild units.json - otherwise
        # re-extracting (which resets `tl`) strands finished work that is
        # sitting in the state file the whole time.
        write_back(doc, state)
        done = sum(1 for u in units if u.get("tl"))
        print(f"nothing to translate - {done}/{len(units)} units already done, "
              f"units.json synced from state")
        return
    total = sum(len(b["items"]) for b in batches)
    print(f"{len(batches)} batches, {total} units, model={args.model}, "
          f"keys={len(api_keys)}")

    run_batches(batches, units_by_id, state, args.model, api_keys)

    # Repair rounds: anything still missing or flagged goes back in small batches.
    for rnd in range(1, 4):
        outstanding = [u for u in units
                       if not state["translations"].get(u["id"])]
        if not outstanding:
            break
        print(f"\nrepair round {rnd}: {len(outstanding)} outstanding")
        small = build_batches(outstanding, state["translations"], False)
        for b in small:
            b["items"] = b["items"][:8]
        run_batches(small, units_by_id, state, args.model, api_keys)

    write_back(doc, state)
    missing = [u for u in units if not state["translations"].get(u["id"])]
    print(f"\ndone: {len(state['translations'])} translated, {len(missing)} unresolved, "
          f"{len(state['flagged'])} flagged")
    print(f"tokens: in={state['usage']['in']:,} out={state['usage']['out']:,} "
          f"calls={state['usage']['calls']}")
    for u in missing[:20]:
        print("  UNRESOLVED:", u["id"], u["src"][:60])


def cmd_status(args):
    doc = json.load(open(C.UNITS, encoding="utf-8"))
    state = load_state()
    units = doc["units"]
    done = sum(1 for u in units if state["translations"].get(u["id"]))
    print(f"units: {len(units)}  translated: {done}  "
          f"remaining: {len(units) - done}  flagged: {len(state['flagged'])}")
    print(f"tokens: in={state['usage']['in']:,} out={state['usage']['out']:,} "
          f"calls={state['usage']['calls']}")


def cmd_report(args):
    doc = json.load(open(C.UNITS, encoding="utf-8"))
    state = load_state()
    if state["flagged"]:
        print("=== FLAGGED ===")
        for uid, f in state["flagged"].items():
            print(f"  [{f['reason']}] {uid}")
            print(f"      JP: {f['src']}")
            print(f"      EN: {f['en']}")
    print("\n=== JP -> EN (read this; it is the only pass that catches a "
          "short label rendered as the wrong part of speech) ===")
    for u in sorted(doc["units"], key=lambda x: (x["kind"], x["id"])):
        if u.get("tl"):
            print(f"  [{u['kind']:<9}] {u['src']}")
            print(f"  {'':<12} -> {u['tl']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--model", default="mistral-medium-latest")
    p.add_argument("--retranslate", action="store_true",
                   help="redo every unit, not just the missing ones")
    p.set_defaults(func=cmd_run)
    p = sub.add_parser("status")
    p.set_defaults(func=cmd_status)
    p = sub.add_parser("report")
    p.set_defaults(func=cmd_report)
    args = ap.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
