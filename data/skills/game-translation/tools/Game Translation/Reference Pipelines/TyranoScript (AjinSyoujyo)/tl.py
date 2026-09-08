#!/usr/bin/env python3
"""亜人少女 - JP->EN translation pipeline.

    python tools/tl.py unpack        pull the TyranoScript project out of app.asar
    python tools/tl.py extract       -> tl/ store + extracted/ reports
    python tools/tl.py selftest      offline proof the pipeline round-trips (free)
    python tools/tl.py dryrun        scope + cost + a real prompt, no API call
    python tools/tl.py names         translate the cast first, into the glossary
    python tools/tl.py live          synchronous run, minutes, 2x batch price
    python tools/tl.py submit        queue a Message Batch (cheapest)
    python tools/tl.py status        poll it
    python tools/tl.py fetch         apply the results
    python tools/tl.py run           submit + poll + fetch in one go
    python tools/tl.py validate      completeness / residual JP / placeholders / layout
    python tools/tl.py retry         re-run everything that failed validation
    python tools/tl.py inject        -> translated/
    python tools/tl.py deploy        -> the game's resources/app  (patch|full|asar)
    python tools/tl.py status-store  what is done, by kind
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "scripts"))

from tyranotl import (                       # noqa: E402
    batch as batch_mod, codes, deploy as deploy_mod, extract as extract_mod,
    debugmenu as debugmenu_mod, elements as elements_mod,
    inject as inject_mod, live as live_mod, pricing,
    prompts, rewrap as rewrap_mod, validate as validate_mod,
    widgets as widgets_mod,
)
from tyranotl.store import Glossary, Store   # noqa: E402

GAME = HERE.parent
APP = HERE / "extracted" / "app"
STORE_DIR = HERE / "tl"
REPORTS = HERE / "extracted"
TRANSLATED = HERE / "translated"
IMAGES = HERE / "translated_images"
PATCH_SRC = HERE / "patch_src"
BIBLE = STORE_DIR / "game_prompt.md"
GLOSSARY = STORE_DIR / "glossary.json"
BATCH_STATE = STORE_DIR / "_batch_state.json"


def _store() -> Store:
    if not any(STORE_DIR.glob("*.json")):
        raise SystemExit("no store yet - run `tl.py extract`")
    return Store(STORE_DIR).load()


def _glossary() -> Glossary:
    return Glossary(GLOSSARY).load()


def _bible() -> str:
    return prompts.load_bible(BIBLE)


# --------------------------------------------------------------------- unpack


def cmd_unpack(args) -> int:
    import subprocess
    archive = GAME / "resources" / "app.asar"
    script = HERE / "scripts" / "unpack_app.py"
    for mode, target in (("text", APP), ("images", HERE / "extracted" / "images")):
        if mode == "images" and not args.images:
            continue
        print(f"-- {mode} -> {target}")
        subprocess.run([sys.executable, str(script), str(archive), str(target),
                        "--mode", mode], check=True)
    return 0


# -------------------------------------------------------------------- extract


def cmd_extract(args) -> int:
    if not APP.exists():
        raise SystemExit(f"{APP} missing - run `tl.py unpack` first")
    previous = Store(STORE_DIR).load() if any(STORE_DIR.glob("*.json")) else None

    store, ex = extract_mod.run(APP, STORE_DIR, REPORTS)
    if previous is not None:
        kept, lost = store.merge_previous(previous)
        print(f"carried over {kept} finished translations ({lost} no longer match a unit)")

    problems = inject_mod.verify(APP, store)
    if problems:
        for line in problems[:20]:
            print(f"  ! {line}")
        raise SystemExit(f"extraction is not reversible ({len(problems)} problems) - aborting")

    for stale in STORE_DIR.glob("*.json"):
        if stale.name not in ("glossary.json",) and not stale.name.startswith("_"):
            if stale.stem not in store.buckets:
                stale.unlink()
    store.save()

    report = _extract_report(store, ex)
    (REPORTS / "extract_report.txt").write_text(report, encoding="utf-8")
    print(report)
    return 0


def _extract_report(store: Store, ex: extract_mod.Extractor) -> str:
    import collections
    lines = ["亜人少女 extraction report", "=" * 46, ""]
    total_units = len(store.all_units())
    total_sites = sum(len(u.sites) for u in store.all_units())
    lines.append(f"units {total_units}   sites {total_sites}   "
                 f"source chars {sum(len(u.src) for u in store.all_units())}")
    lines.append("")
    lines.append("by kind:")
    for kind, row in sorted(store.stats().items(), key=lambda kv: -kv[1]["total"]):
        lines.append(f"  {row['total']:6d}  {kind:10s}  done={row['done']} flagged={row['flagged']}")
    lines.append("")
    lines.append("by bucket:")
    for name in sorted(store.buckets):
        lines.append(f"  {len(store.buckets[name]):6d}  {name}")
    lines.append("")
    lines.append("excluded (see excluded.jsonl for every row):")
    for reason, count in collections.Counter(e.reason for e in ex.excluded).most_common():
        lines.append(f"  {count:6d}  {reason}")
    if ex.unknown_sites:
        lines.append("")
        lines.append("UNKNOWN SITES - new (tag, param) pairs carrying Japanese.")
        lines.append("Classify them in scripts/tyranotl/sites.py and re-extract:")
        for (tag, param), count in sorted(ex.unknown_sites.items(), key=lambda kv: -kv[1]):
            lines.append(f"  {count:6d}  [{tag} {param}=]")
    locked = [u for u in store.all_units() if u.status == "manual"]
    if locked:
        lines.append("")
        lines.append(f"locked as engine keys ({len(locked)}) - never translated:")
        for unit in locked[:20]:
            lines.append(f"  {unit.src}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- selftest


def cmd_selftest(args) -> int:
    store = _store()
    problems = inject_mod.verify(APP, store)
    print(f"round-trip: {len(problems)} problems")
    for line in problems[:20]:
        print(f"  ! {line}")

    # Deep-copy through JSON, fake-translate, and check nothing structural breaks.
    scratch = Store(STORE_DIR)
    scratch.buckets = {
        name: [type(u).from_json(json.loads(json.dumps(u.to_json()))) for u in units]
        for name, units in store.buckets.items()
    }
    for unit in scratch.all_units():
        if unit.status == "manual":
            continue
        unit.en = codes.SENTINEL_RE.sub(lambda m: m.group(0), unit.src)
        unit.status = "done"

    bad = 0
    for unit in scratch.all_units():
        if unit.en and not codes.placeholders_ok(unit.src, unit.en):
            bad += 1
    print(f"placeholder integrity on fake translations: {bad} failures")

    out = REPORTS / "_selftest"
    files, spans = inject_mod.write(APP, out, scratch)
    # Attribute values come back with their spaces as U+00A0 so they survive the
    # KAG parser, so identity is "identical once that is undone" - not byte
    # equality. A handful of the *Japanese* originals hold ASCII spaces the
    # engine was silently eating (text="仕 事 受 注"), and those legitimately
    # change.
    # Normalise both sides: the shipped tyrano/libs.js already contains U+00A0 in
    # its own indentation, so comparing only the output would report a false diff.
    diffs = [p for p in out.rglob("*") if p.is_file()
             and codes.unprotect_spaces(p.read_text(encoding="utf-8"))
             != codes.unprotect_spaces(
                 (APP / p.relative_to(out)).read_text(encoding="utf-8"))]
    print(f"identity injection: {files} files, {spans} spans, {len(diffs)} differ (expect 0)")
    import shutil
    shutil.rmtree(out, ignore_errors=True)
    return 0 if not problems and not bad and not diffs else 1


# --------------------------------------------------------------------- dryrun


def cmd_dryrun(args) -> int:
    store = _store()
    requests = prompts.plan(store.all_units())
    info = batch_mod.dryrun(requests, _bible(), _glossary(), args.model, args.effort,
                            show_sample=args.show_sample)
    print(f"model              {args.model}   effort {args.effort}")
    print(f"requests           {info['requests']}")
    print(f"units              {info['units']}")
    print(f"source characters  {info['source_chars']}")
    print(f"cached prefix      {info['prefix_tokens']} tokens")
    print(f"variable input     {info['variable_input_tokens']} tokens")
    print(f"estimated output   {info['estimated_output_tokens']} tokens "
          f"(ratio {pricing.MEASURED_OUTPUT_RATIO})")
    print()
    print("estimated cost (USD)")
    for label in ("batch+cache", "batch only", "live+cache", "live only"):
        print(f"  {label:12s}  ${info['costs'][label]:8.2f}")
    print()
    for model in ("claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"):
        costs = pricing.four_ways(model, info["prefix_tokens"], info["requests"],
                                  info["variable_input_tokens"], info["estimated_output_tokens"])
        print(f"  {model:20s} batch+cache ${costs['batch+cache']:7.2f}   "
              f"live+cache ${costs['live+cache']:7.2f}")
    if args.show_sample and "sample" in info:
        print("\n" + "-" * 60 + "\nSAMPLE REQUEST\n" + "-" * 60)
        print(info["sample"][:4000])
    return 0


# ------------------------------------------------------------------ mechanical


def cmd_punct(args) -> int:
    """Translate the ``punct`` units offline - no model, no cost."""
    store = _store()
    done = 0
    for unit in store.all_units():
        if unit.kind != "punct" or unit.en:
            continue
        unit.en = codes.convert_punct(unit.src)
        unit.status = "done"
        done += 1
    store.save()
    print(f"converted {done} punctuation-only units offline")
    return 0


# ---------------------------------------------------------------------- names


NAME_PROMPT = """\
# Cast and proper nouns

Below are the proper nouns that occur most often in this game's script, with
their frequency. For each, decide the English rendering and lock it.

Reply with one JSON object and nothing else:

{"names": {"<japanese>": {"en": "...", "gender": "male|female|unknown",
                          "role": "...", "register": "...",
                          "aliases": ["..."]}}}

- ``en`` is the romanisation the whole patch will use. Prefer the natural
  Hepburn reading of the name as a Japanese/fantasy name.
- ``gender`` matters: Japanese omits pronouns constantly and every later request
  resolves 彼/彼女/こいつ from this field. If you are not sure, say ``unknown``.
- ``role`` is a few words on who they are.
- ``register`` is how they speak (polite/timid/blunt/crude/childish...).
- ``aliases`` lists other spellings of the *same* person that appear in the list.
- If two similar-looking entries are different people, say so in ``role``.
- Include only entries that really are names, places, or fixed proper nouns.
"""


def cmd_polish(args) -> int:
    """Mechanical cleanups of finished English - no model, no cost.

    Two of them: small kana the model left stranded in an otherwise-English
    line, and the author's trailing-off marker - a run of low lines, fullwidth
    or ASCII - which is not a Japanese character and so survives every other
    check (see ``codes.convert_lowline``).
    """
    store = _store()
    fixed = []
    for unit in store.all_units():
        if not unit.en:
            continue
        cleaned = unit.en
        if codes.residual_jp(cleaned):
            cleaned = codes.romanise_stranded_kana(cleaned)
        if codes.PAUSE_LOWLINE_RE.search(unit.src) or codes.PAUSE_LOWLINE_RE.search(cleaned):
            cleaned = codes.convert_lowline(cleaned)
        if cleaned != unit.en:
            fixed.append((unit.id, unit.en, cleaned))
            unit.en = cleaned
            unit.status = "done"
            unit.note = ""
    store.save()
    print(f"polished {len(fixed)} units")
    for uid, before, after in fixed[:20]:
        print(f"  {before}")
        print(f"    -> {after}")
    return 0


FIT_PROMPT = """# Labels that do not fit their widget

Each line below is already translated, but the English is too wide for the box it
is drawn in. Rewrite each one **shorter** so it fits, keeping the meaning and the
register. These are game UI labels: terse is correct, and dropping articles and
filler is expected ("Leave It Up to You" -> "Random").

Reply with one JSON object and nothing else:

    {"t": {"0": "...", "1": "...", ...}}

One entry per id, same ids, same order. Do not add or drop sentinels.
"""


def cmd_fit(args) -> int:
    """Re-translate labels whose English overflows the widget it is drawn in."""
    from tyranotl import layout as layout_mod

    store = _store()
    over = []
    for unit in store.all_units():
        if not unit.en or unit.kind not in ("choice", "ptext", "notice"):
            continue
        budget = layout_mod.budget_for(unit.kind, unit.sites[0])
        if not budget:
            continue
        size, limit = budget
        if unit.kind == "ptext":
            limit = max(limit, int(layout_mod.measure(
                codes.SENTINEL_RE.sub("", unit.src), size, APP) * 1.05))
        plain = codes.SENTINEL_RE.sub("", unit.en)
        width = layout_mod.measure(plain, size, APP)
        if width > limit:
            over.append((unit, size, limit, width))
    if not over:
        print("everything fits")
        return 0

    print(f"{len(over)} labels overflow; asking for shorter wording")
    lines = []
    for index, (unit, size, limit, width) in enumerate(over):
        room = layout_mod.measure("n", size, APP)
        chars = max(3, int(limit / max(1.0, room)))
        lines.append(
            f"{index}\tJP: {unit.src}\n \tnow: {unit.en}  "
            f"({width:.0f}px, needs <= {limit}px, about {chars} characters)")
    body = (FIT_PROMPT + "\n" + "\n".join(lines)
            + f"\n\nReturn exactly {len(over)} entries.")

    api = live_mod.client()
    params = {"model": args.model, "max_tokens": prompts.MAX_TOKENS,
              "system": prompts.system_blocks(_bible(), _glossary(), "5m"),
              "messages": [{"role": "user", "content": body}]}
    params.update(pricing.sampling_params(args.model))
    params.update(pricing.output_config(args.effort))
    with api.messages.stream(**params) as stream:
        message = stream.get_final_message()
    table = prompts.parse_reply("".join(b.text for b in message.content
                                        if getattr(b, "type", "") == "text"))
    if not table:
        print("no reply parsed")
        return 1

    fixed = still = 0
    for index, (unit, size, limit, _width) in enumerate(over):
        value = table.get(str(index))
        if not value or not codes.placeholders_ok(unit.src, value):
            continue
        width = layout_mod.measure(codes.SENTINEL_RE.sub("", value), size, APP)
        print(f"  {unit.en!r} -> {value!r}  ({width:.0f}px / {limit}px)")
        unit.en = value
        fixed += 1
        if width > limit:
            still += 1
    store.save()
    print(f"rewrote {fixed}; {still} still over budget")
    return 0


def cmd_spacing(args) -> int:
    """Put a space either side of an inline word-insert where English needs one.

    Japanese needs no space around an inserted word, so the source has none and a
    faithful translation keeps none: "[name2]でよろしいですか" comes back as
    "[name2]Is that alright?" and reaches the screen as "NeroIs that alright?".
    Which tags insert a word is read out of the project's own macro definitions,
    so [p] / [r] / the face-change macros are never touched.
    """
    store = _store()
    macro = APP / "data" / "scenario" / "system" / "macro.ks"
    emitters = codes.inline_emitters(macro.read_text(encoding="utf-8"))
    print(f"inline emitters: {' '.join(sorted(emitters))}")

    changed = []
    disagreed = 0
    for unit in store.all_units():
        if not unit.en or unit.kind not in ("dialogue", "punct"):
            continue

        def emitter(index: int, unit=unit) -> bool:
            verdicts = set()
            for site in unit.sites:
                if index < len(site.tokens):
                    verdicts.add(codes.tag_name(site.tokens[index]) in emitters)
            return verdicts == {True}      # unanimous across every occurrence

        fixed = codes.space_around_inserts(unit.en, emitter)
        if fixed != unit.en:
            changed.append((unit.en, fixed))
            unit.en = fixed
    store.save()

    print(f"spaced {len(changed)} lines")
    for before, after in changed[:15]:
        print(f"  {before}")
        print(f"    -> {after}")
    return 0


def cmd_names(args) -> int:
    import collections
    import re

    store = _store()
    counter: collections.Counter[str] = collections.Counter()
    token = re.compile(r"[ァ-ヺー]{2,}|[一-鿿]{2,4}")
    for unit in store.all_units():
        if unit.kind not in ("dialogue", "choice", "ptext"):
            continue
        for match in token.findall(codes.SENTINEL_RE.sub("", unit.src)):
            counter[match] += 1

    candidates = [f"{word}\t{count}" for word, count in counter.most_common(args.top)]
    glossary = _glossary()
    body = NAME_PROMPT + "\n" + "\n".join(candidates)

    api = live_mod.client()
    params = {
        "model": args.model,
        "max_tokens": prompts.MAX_TOKENS,
        "system": prompts.system_blocks(_bible(), glossary, "5m"),
        "messages": [{"role": "user", "content": body}],
    }
    params.update(pricing.sampling_params(args.model))
    params.update(pricing.output_config(args.effort))
    with api.messages.stream(**params) as stream:
        message = stream.get_final_message()
    text = "".join(b.text for b in message.content if getattr(b, "type", "") == "text")

    parsed = {}
    for span in prompts.balanced_objects(prompts.repair_quotes(text)):
        try:
            obj = json.loads(span)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("names"), dict):
            if len(obj["names"]) > len(parsed):
                parsed = obj["names"]
    if not parsed:
        print("no names parsed; reply was:\n" + text[:2000])
        return 1

    added = 0
    for jp, meta in parsed.items():
        if jp in glossary.names and not args.overwrite:
            continue
        glossary.names[jp] = meta
        added += 1
    glossary.save()
    print(f"glossary: +{added} names (now {len(glossary.names)}). Review {GLOSSARY} by hand.")
    return 0


# ----------------------------------------------------------------- translate


def _pending(store: Store, kinds: list[str] | None) -> list[prompts.Request]:
    units = store.all_units()
    if kinds:
        units = [u for u in units if u.kind in kinds]
    return prompts.plan(units)


def cmd_live(args) -> int:
    store = _store()
    requests = _pending(store, args.kinds)
    if args.limit:
        requests = requests[:args.limit]
    if not requests:
        print("nothing pending")
        return 0
    print(f"{len(requests)} requests, {sum(len(r.units) for r in requests)} units")
    result = live_mod.run(store, _bible(), _glossary(), args.model, args.effort,
                          requests, workers=args.workers)
    print(f"\napplied {result['applied']}  failed requests {result['failed']}")
    _print_usage(result["usage"])
    for line in result["problems"][:30]:
        print(f"  ! {line}")
    return 0


def cmd_submit(args) -> int:
    store = _store()
    state = batch_mod.State(BATCH_STATE).load()
    if state.data.get("batch_id") and not args.force:
        raise SystemExit(f"batch {state.data['batch_id']} already in flight "
                         f"(use `fetch`, or `submit --force` to replace it)")
    requests = _pending(store, args.kinds)
    batch_id = batch_mod.submit(store, state, _bible(), _glossary(), args.model,
                                args.effort, requests, limit=args.limit)
    print(f"submitted {state.data['submitted']} requests as {batch_id}")
    print("poll with `tl.py status`, apply with `tl.py fetch` (safe any time later)")
    return 0


def cmd_status(args) -> int:
    state = batch_mod.State(BATCH_STATE).load()
    if args.watch:
        info = batch_mod.poll(state, interval=args.interval)
    else:
        info = batch_mod.status(state)
    for key, value in info.items():
        print(f"  {key:20s} {value}")
    return 0


def cmd_fetch(args) -> int:
    store = _store()
    state = batch_mod.State(BATCH_STATE).load()
    result = batch_mod.fetch(store, state)
    print(f"applied {result['applied']} units from {result['parsed']} replies "
          f"({result['failed']} unusable)")
    _print_usage(result["usage"])
    for line in result["problems"][:30]:
        print(f"  ! {line}")
    if args.clear:
        state.clear()
    return 0


def cmd_run(args) -> int:
    if cmd_submit(args) != 0:
        return 1
    state = batch_mod.State(BATCH_STATE).load()
    batch_mod.poll(state, interval=args.interval)
    return cmd_fetch(args)


def cmd_retry(args) -> int:
    store = _store()
    stale = [u for u in store.all_units() if u.status == "flagged"]
    if not stale:
        print("nothing flagged")
        return 0
    for unit in stale:
        unit.en = None
    requests = prompts.plan(stale)
    print(f"retrying {len(stale)} units in {len(requests)} requests")
    result = live_mod.run(store, _bible(), _glossary(), args.model, args.effort,
                          requests, workers=args.workers)
    print(f"applied {result['applied']}")
    for line in result["problems"][:30]:
        print(f"  ! {line}")
    return 0


def _print_usage(usage: dict) -> None:
    if not usage:
        return
    total_cached = usage.get("cache_read", 0) + usage.get("cache_write", 0)
    share = (usage.get("cache_read", 0) / total_cached * 100) if total_cached else 0.0
    print(f"tokens: in={usage.get('input', 0)} out={usage.get('output', 0)} "
          f"cache_write={usage.get('cache_write', 0)} cache_read={usage.get('cache_read', 0)} "
          f"({share:.0f}% of cached tokens were re-reads)")


# -------------------------------------------------------------------- checks


def cmd_validate(args) -> int:
    store = _store()
    findings = validate_mod.run(store, _glossary(), APP)
    summary = validate_mod.summarise(findings)
    print(f"hard failures {summary['hard']}   soft warnings {summary['soft']}")

    out = REPORTS / "validate_report.txt"
    lines = []
    for finding in findings:
        lines.append(f"[{finding.severity}] {finding.kind} {finding.unit}: {finding.message}")
        lines.append(f"    JP {finding.src}")
        lines.append(f"    EN {finding.en}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"full report -> {out}")

    for finding in findings[:25]:
        print(f"  [{finding.severity}] {finding.kind}: {finding.message}")
    if args.flag:
        flagged = validate_mod.flag(store, findings)
        store.save()
        print(f"flagged {flagged} units for `tl.py retry`")
    return 0


def cmd_status_store(args) -> int:
    store = _store()
    total = done = 0
    for kind, row in sorted(store.stats().items(), key=lambda kv: -kv[1]["total"]):
        total += row["total"]
        done += row["done"]
        pct = row["done"] / row["total"] * 100 if row["total"] else 0
        print(f"  {kind:10s} {row['done']:5d}/{row['total']:<5d} {pct:5.1f}%"
              f"  flagged={row['flagged']}")
    print(f"  {'TOTAL':10s} {done:5d}/{total:<5d} "
          f"{(done / total * 100 if total else 0):5.1f}%")
    return 0


# -------------------------------------------------------------- inject/deploy


def _emitters() -> set:
    macro = APP / "data" / "scenario" / "system" / "macro.ks"
    return codes.inline_emitters(macro.read_text(encoding="utf-8"))


def cmd_inject(args) -> int:
    store = _store()
    if not args.allow_partial:
        findings = validate_mod.blocking(validate_mod.run(store, _glossary(), APP))
        missing = [f for f in findings if f.message == "not translated"]
        other = [f for f in findings if f.message != "not translated"]
        if other:
            for finding in other[:15]:
                print(f"  ! {finding.kind} {finding.unit}: {finding.message}")
            raise SystemExit(f"{len(other)} hard validation failures - fix or pass --allow-partial")
        if missing:
            print(f"note: {len(missing)} units are still untranslated and will stay Japanese")

    files, spans = inject_mod.write(APP, TRANSLATED, store, _emitters())
    print(f"wrote {files} files, {spans} spans -> {TRANSLATED}")
    if not args.no_rewrap:
        plan = rewrap_mod.scan(TRANSLATED, APP, _emitters())
        cuts, joins, rubies, splits, markers = rewrap_mod.apply(TRANSLATED, plan)
        print(f"rewrap: dropped {cuts} overflowing [r] breaks, "
              f"split {splits} flush lines, "
              f"spaced {joins} glued line junctions, "
              f"removed {rubies} ruby tags, "
              f"converted {markers} lone pause markers")
        refitted = widgets_mod.fit(TRANSLATED, APP)
        if refitted:
            print(f"widgets: re-fitted {len(refitted)} labelled plates")
            for rel, label, width, was, now in refitted:
                moved = f"  x {was} -> {now}" if now != was else ""
                print(f"  {rel}  {label!r:34} plate {width}px{moved}")
        rebroken = widgets_mod.rebreak(TRANSLATED, APP, APP)
        if rebroken:
            print(f"widgets: checked {len(rebroken)} hard-broken labels")
            for rel, x, y, widest, box, budget in rebroken:
                landed = f"-> {budget}px" if budget is not None else "left alone"
                print(f"  {rel}  x={x:<5} y={y:<5} {widest}px vs box {box}px  {landed}")
        unglued = widgets_mod.unglue(TRANSLATED)
        if unglued:
            print(f"widgets: spaced {len(unglued)} values off the word before them")
            for rel, line, label in unglued:
                print(f"  {rel}:{line}  {label}")
        cursored = widgets_mod.cursors(TRANSLATED, APP)
        if cursored:
            print(f"widgets: re-cut {len(cursored)} cursor-laid columns")
            for rel, expression, was, now in cursored:
                landed = "NO ROOM" if now is None else f"+{was} -> +{now}"
                print(f"  {rel}  {expression:26} {landed}")
        inside = widgets_mod.panels(TRANSLATED, APP)
        if inside:
            print(f"widgets: pulled {len(inside)} labels inside their panel")
            for rel, x, y, count, top, what in inside:
                where = "COULD NOT FIT" if top is None else (
                    f"{count} lines" + (f", y {y} -> {top}" if top != y else ""))
                print(f"  {rel}  x={x:<4} y={y:<5} {where:22} {what}")
        recut = widgets_mod.columns(TRANSLATED, APP, APP)
        if recut:
            print(f"widgets: re-placed {len(recut)} columns and values")
            for rel, block, y, what, was, now in recut:
                print(f"  {rel}  {block[:26]:28} y={y:<4} {what:6} x {was} -> {now}")
        spaced = widgets_mod.space(TRANSLATED, APP)
        if spaced:
            print(f"widgets: moved {len(spaced)} values clear of their label")
            for rel, label, was, now in spaced:
                print(f"  {rel}  {label!r:34} x {was} -> {now}")
    if args.debug_menu:
        total = debugmenu_mod.build(TRANSLATED)
        print(f"debug menu: {total} labels reachable from the title and home "
              f"screens -> {debugmenu_mod.MENU_FILE}")
    return 0


def cmd_rewrap(args) -> int:
    """Report - or fix - the line-layout faults English introduces."""
    if not TRANSLATED.exists():
        raise SystemExit("nothing injected yet - run `tl.py inject`")
    plan = rewrap_mod.scan(TRANSLATED, APP, _emitters())
    for cut in plan.cuts:
        print(f"  break  {cut.file}:{cut.line}  {cut.width:.0f}/{cut.limit}px "
              f"({cut.box})  {cut.preview}")
    for join in plan.joins:
        print(f"  glue   {join.file}:{join.line}  ...{join.before[-28:]!r} + "
              f"{join.after[:28]!r}...")
    for split in plan.splits:
        print(f"  flush  {split.file}:{split.line}  {split.width:.0f}/{split.limit}px "
              f"({split.box})  ...{split.left} | {split.right}...")
    for drop in plan.drops:
        becomes = f" -> {drop.new!r}" if drop.new else ""
        print(f"  {drop.kind:6s} {drop.file}:{drop.line}  {drop.old!r}{becomes}")
    print(f"{len(plan.cuts)} overflowing breaks, {len(plan.splits)} flush lines, "
          f"{len(plan.joins)} glued junctions, "
          f"{sum(1 for d in plan.drops if d.kind == 'ruby')} ruby tags, "
          f"{sum(1 for d in plan.drops if d.kind == 'marker')} lone markers")
    if args.apply:
        cuts, joins, rubies, splits, markers = rewrap_mod.apply(TRANSLATED, plan)
        print(f"applied: {cuts} breaks dropped, {splits} lines split, "
              f"{joins} junctions spaced, {rubies} ruby tags removed, "
              f"{markers} markers converted")
    return 0


def cmd_deploy(args) -> int:
    if not TRANSLATED.exists():
        raise SystemExit("nothing injected yet - run `tl.py inject`")

    # Saves resume by element index and macros are registered by element index,
    # so a file whose element count changes voids every save taken after the
    # change. Say so before overwriting the build those saves were made on.
    installed = GAME / "resources" / "app" / "override" / "data" / "scenario"
    if installed.exists():
        moved = elements_mod.shifts(TRANSLATED / "data" / "scenario", installed)
        if moved:
            print(f"WARNING: {len(moved)} file(s) changed element count since the "
                  f"installed build - existing saves rely on those indices:")
            for rel, was, now, drifted in moved:
                macros = f", {drifted} macros moved" if drifted else ""
                print(f"  ! {rel}  {was} -> {now} elements{macros}")
            print("  save_compat.js remaps the resume point and refreshes the macro "
                  "table on load, but prefer edits that keep the count.")
    if args.mode == "patch":
        info = deploy_mod.patch(GAME, TRANSLATED, PATCH_SRC, APP, IMAGES)
    elif args.mode == "full":
        info = deploy_mod.full(GAME, TRANSLATED, IMAGES)
    else:
        info = deploy_mod.repack_asar(GAME, TRANSLATED, HERE / "dist" / "app.asar", IMAGES)
        problems = deploy_mod.verify_asar(HERE / "dist" / "app.asar",
                                          GAME / "resources" / "app.asar",
                                          TRANSLATED, IMAGES)
        info["verified"] = "byte-exact" if not problems else f"{len(problems)} MISMATCHES"
        for line in problems[:10]:
            print(f"  ! {line}")
    for key, value in info.items():
        print(f"  {key:10s} {value}")
    if args.mode in ("patch", "full"):
        print("\nlaunch ajin_syoujyo.exe. To uninstall, delete resources/app.")
    else:
        print("\nback up resources/app.asar, then drop this file in its place.")
    return 0


# ------------------------------------------------------------------------ cli


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def model_args(parser):
        parser.add_argument("--model", default=prompts.MODEL_DEFAULT)
        parser.add_argument("--effort", default=prompts.EFFORT_DEFAULT,
                            choices=sorted(pricing.EFFORT_LEVELS))

    p = sub.add_parser("unpack"); p.add_argument("--images", action="store_true"); p.set_defaults(func=cmd_unpack)
    p = sub.add_parser("extract"); p.set_defaults(func=cmd_extract)
    p = sub.add_parser("selftest"); p.set_defaults(func=cmd_selftest)
    p = sub.add_parser("punct"); p.set_defaults(func=cmd_punct)
    p = sub.add_parser("polish"); p.set_defaults(func=cmd_polish)
    p = sub.add_parser("spacing"); p.set_defaults(func=cmd_spacing)
    p = sub.add_parser("fit"); model_args(p); p.set_defaults(func=cmd_fit)

    p = sub.add_parser("dryrun"); model_args(p)
    p.add_argument("--show-sample", action="store_true"); p.set_defaults(func=cmd_dryrun)

    p = sub.add_parser("names"); model_args(p)
    p.add_argument("--top", type=int, default=120)
    p.add_argument("--overwrite", action="store_true"); p.set_defaults(func=cmd_names)

    p = sub.add_parser("live"); model_args(p)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--kinds", nargs="*"); p.set_defaults(func=cmd_live)

    p = sub.add_parser("submit"); model_args(p)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--kinds", nargs="*")
    p.add_argument("--force", action="store_true"); p.set_defaults(func=cmd_submit)

    p = sub.add_parser("status")
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval", type=int, default=60); p.set_defaults(func=cmd_status)

    p = sub.add_parser("fetch")
    p.add_argument("--clear", action="store_true"); p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("run"); model_args(p)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--kinds", nargs="*")
    p.add_argument("--force", action="store_true")
    p.add_argument("--clear", action="store_true")
    p.add_argument("--interval", type=int, default=60); p.set_defaults(func=cmd_run)

    p = sub.add_parser("retry"); model_args(p)
    p.add_argument("--workers", type=int, default=4); p.set_defaults(func=cmd_retry)

    p = sub.add_parser("validate")
    p.add_argument("--flag", action="store_true"); p.set_defaults(func=cmd_validate)

    p = sub.add_parser("status-store"); p.set_defaults(func=cmd_status_store)

    p = sub.add_parser("inject")
    p.add_argument("--allow-partial", action="store_true")
    p.add_argument("--no-rewrap", action="store_true",
                   help="skip the line-layout pass (see tyranotl/rewrap.py)")
    p.add_argument("--debug-menu", action="store_true",
                   help="add a scene-jump menu for testing (never in a release build)")
    p.set_defaults(func=cmd_inject)

    p = sub.add_parser("rewrap")
    p.add_argument("--apply", action="store_true", help="write the changes")
    p.set_defaults(func=cmd_rewrap)

    p = sub.add_parser("deploy")
    p.add_argument("--mode", choices=("patch", "full", "asar"), default="patch")
    p.set_defaults(func=cmd_deploy)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
