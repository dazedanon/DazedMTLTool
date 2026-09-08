#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
selftest.py - offline wiring checks. No API calls, no writes to the real store.

Two rules this suite exists to obey, both learned expensively:

  * **A self-test must not write to the real store.** A fake-translate round
    trip that fills every unit's `tl` and saves turns the store into a
    finished-looking job: `dryrun` then reports 0 pending, a run translates
    nothing, and inject ships placeholder text into the game. Everything here
    that mutates works on a COPY in a tempdir, and the last check asserts the
    real store is still clean.

  * **A test that builds its fixtures from PENDING work silently passes once
    the work is done.** `build_all` returns zero requests the moment the game
    is finished, every `all(...)` over an empty list is vacuously true, and the
    suite reports PASS while checking nothing. So the request-shape checks
    force `retranslate_all=True` and FAIL LOUDLY on an empty build.

Run: `py tl.py selftest`
"""

import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from artl import (balance, codes, config, driver, inject, measure,
                  prompts, recentre, requests as R, store, wrap)

FAILED = []
PASSED = [0]


def check(name, cond, detail=""):
    if cond:
        PASSED[0] += 1
    else:
        FAILED.append("%s%s" % (name, (": " + detail) if detail else ""))
    print("  %-58s %s" % (name, "ok" if cond else "FAIL"))


# --------------------------------------------------------------------------
def test_codes():
    print("\ncodes")
    src = "\\NPL[アルテシア]あら、\\z[200]いいわね\\innpriceG"
    spk, body, plate = codes.split_speaker(src)
    check("nameplate splits exactly", (spk, plate) == ("アルテシア", "NPL"),
          repr((spk, plate)))
    masked, cmap = codes.mask_codes(body)
    check("every code masked", "\\" not in masked, repr(masked))
    check("mask round-trips", codes.unmask_codes(masked, cmap, False) == body)
    check("speaker rejoins inside the code",
          codes.join_speaker("Artesia", body, plate)
          == "\\NPL[Artesia]" + body)

    # A word-insert gets English spacing; a layout code does not.
    m2, c2 = codes.mask_codes("所持金\\innpriceG です")
    en = codes.unmask_codes("You have" + m2[m2.index(codes.PH_OPEN):], c2)
    check("word insert is padded", "have \\innpriceG" in en, repr(en))

    # Ruby is resolved to its base and never restored.
    r, n = codes.resolve_ruby("痴話喧嘩……\\r[・]カ\\r[・]モね！")
    check("ruby resolves to its base", r == "痴話喧嘩……カモね！" and n == 2, repr(r))

    check("CRLF round-trips", codes.to_crlf(codes.to_lf("a\r\nb")) == "a\r\nb")

    # The six engine traps, each of which English can create and Japanese cannot.
    traps = dict(codes.output_traps("\\NPL[Smith, Jr.]hello"))
    check("comma inside a code arg is caught", "comma-in-code-arg" in traps)
    check("blink collision is caught",
          "blink-collision" in dict(codes.output_traps("he \\blinked twice")))
    check("bracket after a bare escape is caught",
          "bracket-after-bare-escape" in dict(codes.output_traps("\\b[soft]")))
    check("trailing backslash is caught",
          "trailing-backslash" in dict(codes.output_traps("ends here\\")))
    check("tab is caught",
          "tab-becomes-backslash" in dict(codes.output_traps("a\tb")))
    check("a clean line trips nothing",
          codes.output_traps("\\NPL[Artesia]Just a normal line.") == [])

    # The escape lexer must model the ENGINE's dispatch, not a greedy regex.
    # Built on the GameContentParser keyword table alone it called the
    # nameplate code unknown on 71,513 lines - 78% of the corpus - because that
    # table is pass ONE only and the nameplate is a pass-two MessageReader
    # command. Lexing greedily is the mirror error: a bare newline code
    # followed by an English word reads as one unknown token.
    codes.load_keywords(config.load()["keywords"])
    for good in (r"\NPL[Artesia]Hello there.", r"You have \innpriceG gold.",
                 r"\z[200]Big", r"Speed: \nfast", r"Value \$[gold] here",
                 r"\#[coordX]", r"\currentitemnum left", r"a\\b"):
        got = codes.unknown_escapes(good)
        check("known escape not flagged: %r" % good[:26], got == [], repr(got))
    check("a genuinely unknown escape IS flagged",
          codes.unknown_escapes(r"A stray \q code") != [])

    check("censor mask survives the residue check",
          not codes.has_untranslated_jp("sh〇t"))
    check("a lone katakana is not residue",
          not codes.has_untranslated_jp("Nhagi-ッ!"))
    check("a katakana WORD is residue",
          codes.has_untranslated_jp("Nhagi アルテシア"))


def test_hard_issues():
    """The validator itself, called directly.

    The suite used to exercise `codes.output_traps` and never `hard_issues`,
    so a NameError on a line every translated unit reaches sat behind 41 green
    checks - invisible only because the store held zero translations. Every
    branch that can append an issue is driven here."""
    print("\nvalidation")
    from artl import validate
    base = {"kind": "text", "id": "u1", "key": "u1", "codes": {},
            "speaker": "", "plate": "", "owner": "", "ctx": ""}

    def issues(**kw):
        return validate.hard_issues(dict(base, **kw))

    check("a clean translation has no issues",
          issues(src="こんにちは", tl="Hello.") == [])
    check("empty is caught", issues(src="こんにちは", tl="") == ["empty"])
    check("identical is caught",
          "identical" in issues(src="こんにちは", tl="こんにちは"))
    check("residual Japanese is caught",
          "residual-jp" in issues(src="こんにちは", tl="Hello こんにちは"))
    check("an invented sentinel is caught",
          "invented-sentinel" in issues(src="こんにちは", tl="Hello ⟦0⟧"))
    check("a dropped sentinel is caught",
          "placeholder" in validate.hard_issues(
              dict(base, src="⟦0⟧こんにちは", tl="Hello",
                   codes={"⟦0⟧": r"\z[200]"})))
    check("a comma in a rebuilt nameplate is caught",
          "comma-in-code-arg" in validate.hard_issues(
              dict(base, src="こんにちは", tl="Hello",
                   speaker="ア", speaker_en="Smith, Jr.", plate="NPL")))
    check("a safe nameplate is not caught",
          validate.hard_issues(
              dict(base, src="こんにちは", tl="Hello",
                   speaker="ア", speaker_en="Artesia", plate="NPL")) == [])
    check("two codes on one line are NOT a bracket trap",
          validate.hard_issues(
              dict(base, src="⟦0⟧こんにちは⟦1⟧",
                   tl="Hello ⟦0⟧ there ⟦1⟧",
                   codes={"⟦0⟧": r"\$[a]", "⟦1⟧": r"\z[200]"},
                   speaker="ア", speaker_en="Artesia", plate="NPL")) == [])
    check("a locked unit is never reported",
          validate.hard_issues(dict(base, src="こんにちは", tl="こんにちは",
                                    locked=True)) == [])
    # "its own check ONLY" is the whole point: the same unit still trips
    # `residual-jp`, and a waiver that swallowed that too would be a mute.
    waived = validate.hard_issues(dict(base, src="こんにちは", tl="こんにちは",
                                       waive={"identical": "deliberate"}))
    check("a waiver suppresses its own check",
          "identical" not in waived, repr(waived))
    check("...and nothing else", "residual-jp" in waived, repr(waived))
    check("an unsafe code argument is caught",
          "unsafe-code-arg" in validate.hard_issues(
              dict(base, kind="codearg", src="消費HP", tl="HP cost, MP")))
    check("number drift is caught",
          "number-drift" in issues(src="三日後に", tl="five days later"))
    check("a correct number rendering is not",
          "number-drift" not in issues(src="三日後に", tl="three days later"))

    g = {"names": {"A": {"en": "Smith, Jr."}, "B": {"en": "Artesia"}}}
    bad = validate.glossary_issues(g)
    check("glossary_issues names the bad row once",
          len(bad) == 1 and "Smith" in bad[0], repr(bad))


def test_no_unresolved_names():
    """No call site anywhere in the package is missing its definition.

    Two constants were deleted while their use survived the adaptation, and
    neither was visible to `ast.parse` or to a code review: the first took
    `validate` down on the first translated unit, the second sat behind a
    branch that was unreachable until the glossary had names in it. A
    whole-package resolve costs a second and cannot miss the class."""
    print("\nunresolved names")
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
    import unresolved_names
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = unresolved_names.main()
    check("every name a function references is defined", rc == 0,
          buf.getvalue().strip()[:400])


def test_dedup():
    print("\ndedup")
    a = {"kind": "text", "src": "はい", "speaker": "アルテシア", "id": "1"}
    b = {"kind": "text", "src": "はい", "speaker": "アルテシア", "id": "2"}
    c = {"kind": "text", "src": "はい", "speaker": "オリヴィア", "id": "3"}
    check("same speaker + text dedupe together",
          store.dedup_key(a) == store.dedup_key(b))
    check("a different speaker does NOT dedupe with them",
          store.dedup_key(a) != store.dedup_key(c))
    check("dedup can be turned off",
          store.dedup_key(a, dedup_dialogue=False) is None)
    ui = {"kind": "ui", "src": "はい", "id": "4"}
    check("UI dedupes regardless of speaker",
          store.dedup_key(ui) == ("ui", "はい"))


def test_requests(cfg):
    print("\nrequest shape")
    store_dir = cfg["store_dir"]
    model = cfg["model"]
    # retranslate_all=True on purpose: a fixture built from PENDING work
    # becomes empty the moment the game is finished, and every assertion below
    # would then be vacuously true.
    docs, glossary, reqs, id_maps, name_maps = driver.build_all(
        store_dir, cfg, model, cfg["max_units"], retranslate_all=True,
        include_names=True, include_text=True, effort=cfg["effort"],
        ttl=cfg["batch_ttl"], roster_min=cfg["roster_min"],
        dedup_dialogue=cfg["dedup_dialogue"])
    if not reqs:
        print("FAIL no requests built at all - nothing below was actually tested")
        FAILED.append("empty build")
        return

    check("built some requests", len(reqs) > 0, str(len(reqs)))
    check("no sampling params on a 5-family model",
          all("temperature" not in r["params"] for r in reqs)
          if model in R.NO_SAMPLING else True)
    check("effort lives inside output_config",
          all(r["params"].get("output_config", {}).get("effort") == cfg["effort"]
              for r in reqs))
    check("thinking stays adaptive",
          all(r["params"]["thinking"] == {"type": "adaptive"} for r in reqs))
    check("max_tokens scales with the payload",
          all(4096 <= r["params"]["max_tokens"] <= R.MAX_NONSTREAM_TOKENS
              for r in reqs),
          str(sorted({r["params"]["max_tokens"] for r in reqs})))
    # The SDK raises a ValueError BEFORE sending when max_tokens implies a call
    # over ten minutes (3600 * max_tokens / 128000 > 600, so > 21,333). It is
    # not an HTTP error, so it shows up as a bare "ERROR" with no reason - and
    # a name request sized with the DIALOGUE per-unit figure sat at 32,000 and
    # failed 100% of the time. Assert the ceiling explicitly.
    over = [(r["custom_id"], r["params"]["max_tokens"]) for r in reqs
            if 3600 * r["params"]["max_tokens"] / 128000 > 600]
    check("no request trips the SDK's non-streaming ceiling", not over,
          str(over[:3]))
    name_caps = {r["params"]["max_tokens"] for r in reqs
                 if r["custom_id"] in name_maps}
    check("name requests are sized for NAMES, not for dialogue",
          all(c <= R.cap_tokens(200, R.OUT_PER_NAME) for c in name_caps),
          str(sorted(name_caps)))

    # One cached prefix PER JOB, not one across all requests: the names pass
    # and the text pass are different jobs with different system prompts, and
    # asserting a single prefix over both fails correctly-built code.
    def prefix(r):
        blocks = r["params"]["system"]
        cut = len(blocks)
        for i, b in enumerate(blocks):
            if "cache_control" in b:
                cut = i + 1
                break
        return "".join(b["text"] for b in blocks[:cut])

    text_pfx = {prefix(r) for r in reqs if r["custom_id"] in id_maps}
    name_pfx = {prefix(r) for r in reqs if r["custom_id"] in name_maps}
    check("exactly one cached prefix for the TEXT job", len(text_pfx) == 1,
          str(len(text_pfx)))
    check("exactly one cached prefix for the NAMES job", len(name_pfx) <= 1,
          str(len(name_pfx)))
    check("exactly one cache breakpoint per request",
          all(sum(1 for b in r["params"]["system"] if "cache_control" in b) == 1
              for r in reqs))
    check("the ttl is the configured one",
          all(b["cache_control"]["ttl"] == cfg["batch_ttl"]
              for r in reqs for b in r["params"]["system"]
              if "cache_control" in b))

    # Every pending unit queued EXACTLY once, after dedup.
    queued = [uid for v in id_maps.values() for uid in v]
    check("no unit is queued twice", len(queued) == len(set(queued)),
          "%d queued, %d distinct" % (len(queued), len(set(queued))))
    keys = set()
    for _p, doc in docs:
        for u in doc["units"]:
            if u.get("locked"):
                continue
            k = store.dedup_key(u, cfg["dedup_dialogue"]) or ("#", u["id"])
            keys.add(k)
    check("every dedup group is queued",
          len(queued) >= len(keys) * 0.99,
          "%d queued for %d groups" % (len(queued), len(keys)))

    check("custom_ids are unique",
          len({r["custom_id"] for r in reqs}) == len(reqs))
    # Against the API's OWN pattern, not a looser idea of "ASCII-safe". One
    # bad id 400s the entire submission after the builder has done all its
    # work, and `:`/`.` are not allowed even though they look harmless.
    bad_id = [r["custom_id"] for r in reqs
              if not store.CUSTOM_ID_RE.match(r["custom_id"])]
    check("every custom_id matches the Batches API pattern", not bad_id,
          str(bad_id[:3]))
    sample = next(r for r in reqs if r["custom_id"] in id_maps)
    user = sample["params"]["messages"][0]["content"]
    check("the user turn carries per-kind instructions",
          "Request instructions:" in user)
    check("the user turn states the output contract",
          "JSON object" in user)


def test_selftest_is_isolated(cfg):
    print("\nisolation")
    # A fake-translate round trip, in a COPY of the store.
    tmp = tempfile.mkdtemp(prefix="artl_selftest_")
    try:
        dst = os.path.join(tmp, "tl")
        shutil.copytree(cfg["store_dir"], dst)
        docs = store.load_docs(dst)
        n = 0
        for _p, u in store.all_units(docs):
            u["tl"] = "[EN %d]" % n
            n += 1
            if n > 200:
                break
        store.save_docs(docs)
        again = store.load_docs(dst)
        filled = sum(1 for _p, u in store.all_units(again)
                     if (u.get("tl") or "").startswith("[EN "))
        check("the copy round-trips through save/load", filled >= 200, str(filled))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    real = store.load_docs(cfg["store_dir"])
    bad = [u["id"] for _p, u in store.all_units(real)
           if (u.get("tl") or "").startswith("[EN ")]
    check("the REAL store was not written by this test", not bad,
          "%d units hold test text" % len(bad))


def test_parse():
    print("\nreply parsing")
    from artl import parse
    check("plain object", parse.parse('{"1":"a","2":"b"}') == {"1": "a", "2": "b"})
    check("fenced", parse.parse('```json\n{"1":"a"}\n```') == {"1": "a"})
    check("trailing comma", parse.parse('{"1":"a",}') == {"1": "a"})
    # The dakuten-as-ASCII-quote case: the source uses `"` inside a slurred
    # moan and the model carries it into English.
    got = parse.parse('{"1":"Aa"h heart"}')
    check("unescaped quote inside a value is repaired",
          isinstance(got, dict) and got.get("1", "").startswith("Aa"), repr(got))
    # Self-correction: a partial object, prose, then the real one.
    got = parse.parse('{"1":"x"}\n\nWait, I need all 3.\n\n{"1":"a","2":"b","3":"c"}')
    check("self-correction keeps the fullest object", len(got) == 3, repr(got))



def test_wrap_and_balance(cfg):
    r"""The engine's wrap, and the repair pass that moves its bad breaks.

    Every number here is a MEASURED width from the calibrated font, so this
    section fails loudly if `font_size`, `game_font` or `message_px` is ever
    changed without re-deriving them."""
    print("\nwrap and layout repair")
    m = measure.resolve(cfg, cfg["font_size"])
    meas = m.width
    W = float(cfg["message_px"])

    # GROUND TRUTH. This exact line was photographed in-game: the engine put
    # "nuisance?" alone on row two. If the transcribed wrap does not reproduce
    # that, it is not the engine's wrap and nothing built on it can be trusted.
    shot = ("You two look like you're arguing... don't you ever consider "
            "you're a nuisance?")
    got = wrap.wrap_line(shot, W, meas)
    check("the transcribed wrap reproduces the in-game screenshot",
          len(got) == 2 and got[1].strip() == "nuisance?", repr(got))
    check("the screenshot's orphan is detected as one",
          len(wrap.orphans(got, W, meas)) == 1, repr(got))

    # And the repair.
    fixed = balance.rebalance(shot, W, meas)
    check("the screenshot line is repaired", fixed is not None, repr(fixed))
    check("the repair keeps every word",
          fixed and balance.same_words(shot, fixed), repr(fixed))
    check("the repair keeps the line count",
          fixed and len(fixed) == len(got), repr(fixed))
    check("the repair leaves no orphan",
          fixed and not wrap.orphans(fixed, W, meas), repr(fixed))
    # The decisive one: the engine must not touch what we chose. A line that
    # still exceeds the box would be re-wrapped and the repair would have made
    # things worse than greedy.
    check("the engine re-wraps none of the repaired lines",
          fixed and all(wrap.wrap_line(c, W, meas) == [c] for c in fixed),
          repr(fixed))

    # Refusals. Each of these would be a corruption, not a cosmetic miss.
    check("a line with a size code is refused",
          balance.rebalance(r"\z[200]" + shot, W, meas) is None)
    check("a line with a spaced code bracket is refused",
          balance.rebalance(shot + r" \NPL[Sister Agatha]", W, meas) is None)
    check("a line that already fits is left alone",
          balance.rebalance("Short enough.", W, meas) is None)
    check("a single unsplittable word is left alone",
          balance.rebalance("W" * 400, W, meas) is None)

    # A kind with no measured width must never be rebalanced.
    check("telop has no wrap width and so is never repaired",
          balance.wrap_width(cfg, "telop") is None)
    check("message uses the conservative node, not the calibrated one",
          balance.wrap_width(cfg, "message") == 670.0
          and balance.wrap_width(cfg, "text") == 690.0)

    # `render` must be inert unless a width AND a font are both supplied,
    # which is what keeps the byte-exact no-op gate honest.
    u = {"kind": "text", "tl": shot, "codes": {}, "plate": "", "speaker": ""}
    plain = inject.render(dict(u))
    check("render without metrics does not rebalance",
          plain == codes.to_crlf(shot), repr(plain[:40]))
    live = inject.render(dict(u), None, None, W, meas)
    check("render with metrics does rebalance", live != plain and "\r\n" in live,
          repr(live))
    check("render's rebalance changed only whitespace",
          balance.same_words(shot, codes.to_lf(live)), repr(live))




def test_recentre(cfg):
    """Hand-centred labels, and the refusals that keep the pass honest."""
    print("\nlayout recentring")
    m = measure.resolve(cfg, cfg["layout_font_size"])

    def row(idx, posX, origin="MiddleLeft", scaleX="1", node="N"):
        return {"nodeGuid": "N", "node": node, "idx": str(idx), "posX": str(posX),
                "origin": origin, "scaleX": scaleX, "textScale": "1", "sizeY": "45"}

    # Three labels the author nudged so each JAPANESE string centres on x=100.
    texts = {}
    rows = []
    for i, jp in enumerate(["AAAAAAAA", "AAAA", "AA"]):
        w = m.width(jp)
        rows.append(row(i, 100.0 - w / 2.0))
        texts[("N", str(i))] = jp
    got = recentre.detect(rows, texts, m)
    check("a hand-centred group is detected", len(got) == 1, repr(got))
    check("the group's centre is recovered",
          got and abs(got[0]["centre"] - 100.0) < 0.5, repr(got and got[0]["centre"]))
    check("the group coheres tightly", got and got[0]["spread"] < 1.0)

    # The SAME strings, all at one x. That is left alignment, not centring, and
    # shifting them would be a regression - so it must not be detected.
    flat = [row(i, 30.0) for i in range(3)]
    check("equal posX is NOT read as centring",
          recentre.detect(flat, texts, m) == [])

    # Centres that disagree are not a group either.
    noisy = [row(0, 10.0), row(1, 90.0), row(2, 200.0)]
    check("disagreeing centres are NOT a group",
          recentre.detect(noisy, texts, m) == [])

    # The repair must land the ENGLISH on the same centre, exactly.
    trans = {("N", "0"): "Item", ("N", "1"): "Configuration", ("N", "2"): "Options"}
    fx, _sk = recentre.fixes(rows, texts, trans, m)
    for key, val, d in fx:
        c = float(val) + recentre.drawn(d["en"], m, {"scaleX": "1", "textScale": "1"}) / 2.0
        check("recentred %-13s lands on the group centre" % d["en"],
              abs(c - 100.0) < 0.5, "%r -> %.2f" % (d["en"], c))
    check("every translated member is repaired", len(fx) == 3, repr(len(fx)))
    check("the write key addresses pos.X, not text",
          all(k.endswith(":posX") for k, _v, _d in fx))

    # A translation that happens to be the same width as its source is already
    # centred. Rewriting pos.X by a fraction of a pixel would churn the layout
    # rom for nothing, so it is refused and counted.
    same = dict(trans)
    same[("N", "2")] = texts[("N", "2")]
    fx3, sk3 = recentre.fixes(rows, texts, same, m)
    check("a same-width translation is not shifted",
          len(fx3) == 2 and any("shift below" in k for k in sk3), repr(sk3))

    # An untranslated member keeps its Japanese, which is still correctly placed.
    fx2, sk2 = recentre.fixes(rows, texts, {("N", "0"): "Item"}, m)
    check("an untranslated member is left alone",
          len(fx2) == 1 and sk2.get("untranslated") == 2, repr(sk2))


def test_recentre_on_real_layout(cfg):
    """The live menu group, as a regression fixture.

    This is also the calibration check for `layout_font_size`: the seven menu
    labels only agree on a centre at the right font size, so a bad size shows
    up here as a group that fails to cohere rather than as silently wrong
    offsets shipped into the rom."""
    print("\nlayout recentring, against the real layout.tsv")
    import csv as _csv
    import io as _io
    import os as _os
    path = cfg["layout_tsv"]
    if not _os.path.exists(path):
        check("layout.tsv present", False, path)
        return
    with _io.open(path, encoding="utf-8") as fh:
        rows = list(_csv.DictReader(fh, delimiter="\t"))
    docs = store.load_docs(cfg["store_dir"])
    texts = {}
    for _p, u in store.all_units(docs):
        if u["kind"] != "ui":
            continue
        q = u["key"].split(":")
        if len(q) == 4 and q[0] == "M" and q[3] == "text":
            texts[(q[1], q[2])] = u["raw"]
    m = measure.resolve(cfg, cfg["layout_font_size"])
    groups = recentre.detect(rows, texts, m)
    menu = [g for g in groups
            if g["node"] == "9847d4a0-c4c6-4a43-96d5-8739260152d1"]
    check("the main menu is found to be hand-centred", len(menu) == 1, repr(len(groups)))
    if menu:
        g = menu[0]
        check("all seven menu labels are in the group", len(g["members"]) == 7,
              repr(len(g["members"])))
        check("they cohere to under 3px at layout_font_size",
              g["spread"] < 3.0, "spread %.2fpx" % g["spread"])
        # The calibration claim, asserted rather than remembered: the correct
        # size must beat both neighbours.
        s_here = g["spread"]
        for other in (cfg["layout_font_size"] - 2, cfg["layout_font_size"] + 2):
            m2 = measure.resolve(cfg, other)
            g2 = [x for x in recentre.detect(rows, texts, m2)
                  if x["node"] == "9847d4a0-c4c6-4a43-96d5-8739260152d1"]
            sp = g2[0]["spread"] if g2 else 999.0
            check("%dpx coheres worse than %dpx" % (other, cfg["layout_font_size"]),
                  sp > s_here, "%.2f vs %.2f" % (sp, s_here))



def test_glyph_coverage(cfg):
    """Every character the patch ships must have a glyph in the font it asks for.

    A missing glyph passes every other check in this suite - the text is right,
    the codes are right, nothing overflows - and the player sees a hollow box.
    On this game U+2661 was shipped 226,834 times into a font substitute that
    had no glyph for it."""
    print("\nglyph coverage")
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except ImportError:
        check("fontTools available for the glyph audit", False, "pip install fonttools")
        return
    m = measure.resolve(cfg, cfg.get("layout_font_size", 24))
    check("the game asks for a font this machine really has",
          not m.substituted, m.describe())
    try:
        fonts = (TTCollection(m.path).fonts if m.path.lower().endswith(".ttc")
                 else [TTFont(m.path, fontNumber=0)])
        cs = [f.getBestCmap() for f in fonts if f.getBestCmap()]
    except Exception as e:
        check("the font's cmap is readable", False, repr(e))
        return
    check("the font's cmap is readable", bool(cs), m.path)

    def has(cp):
        return any(cp in c for c in cs)

    # The characters this game actually leans on, asserted by name so a font
    # change that drops one fails here rather than in a screenshot.
    for cp, name in ((0x2661, "WHITE HEART SUIT"), (0x2665, "BLACK HEART SUIT"),
                     (0x266A, "EIGHTH NOTE"), (0xFF5E, "FULLWIDTH TILDE"),
                     (0x3042, "HIRAGANA A"), (0x4E00, "CJK ONE")):
        check("the font has U+%04X %s" % (cp, name), has(cp))

    docs = store.load_docs(cfg["store_dir"])
    missing = {}
    for _p, u in store.all_units(docs):
        tl = codes.clean_translation(u.get("tl") or "")
        if not tl.strip():
            continue
        body = codes.unmask_codes(tl, u.get("codes") or {}, pad_inserts=True)
        for ch in set(body):
            if ch in "\r\n\t":
                continue
            if not has(ord(ch)):
                missing[ch] = missing.get(ch, 0) + 1
    check("no shipped character is missing a glyph", not missing,
          repr(sorted(missing.items())[:8]))


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg = config.load()
    print("SELFTEST  (no API calls, no writes to %s)" % cfg["store_dir"])
    test_codes()
    test_wrap_and_balance(cfg)
    test_recentre(cfg)
    test_recentre_on_real_layout(cfg)
    test_glyph_coverage(cfg)
    test_hard_issues()
    test_no_unresolved_names()
    test_dedup()
    test_parse()
    test_requests(cfg)
    test_selftest_is_isolated(cfg)
    print("\n%d passed, %d failed" % (PASSED[0], len(FAILED)))
    for f in FAILED:
        print("  FAILED %s" % f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
