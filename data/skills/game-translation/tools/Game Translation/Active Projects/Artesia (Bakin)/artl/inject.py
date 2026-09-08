#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
inject.py - turn the store into the flat `{key, en}` JSONL that `BakinTL
inject` applies, and drive BakinTL.

Injection on this engine is unusually simple and unusually safe: a unit's write
site is a single opaque key (`S:<scriptGuid>:<cmd>:<attr>`, `M:<node>:<i>:text`,
`R:<guid>:<field>`, `G:<field>`, `T:<field>`) that the C# side resolves against
the catalog, and the catalog round-trips byte-for-byte. There are no JSON
pointers to walk and no file to re-parse.

What this module owns is everything that has to happen BETWEEN the store and
that key:

  * restore the masked control codes, padding the word-inserts;
  * put the translated speaker back INSIDE `\NPL[...]`, never as a `Name: `
    prefix on the line - the engine draws the nameplate in its own plate;
  * re-inline a display-text code argument into its parent;
  * refuse to write a unit that failed validation, leaving it in Japanese,
    which is a visible no-op rather than a shipped defect.
"""

import collections
import json
import os
import subprocess
import sys

from . import balance, codes, measure, recentre, store, validate


def _unwritable(cfg):
    return {p.replace("/", os.sep).lower()
            for p in (cfg.get("unwritable_files") or [])}


def _recentre_pairs(cfg, docs, blocked):
    """[(write_key, value, rom_file)] restoring each hand-centred label's centre.

    Measured at `layout_font_size`, NOT at the message `font_size`: layout
    widgets render at 24px on this build and the message box at 22px, and the
    hand-centred group is what proved it (their centres agree to 1.2px at 24
    and scatter over 5.6px at 22)."""
    import csv
    import io as _io
    path = cfg.get("layout_tsv")
    if not path or not os.path.exists(path):
        return [], {"no layout.tsv": 1}
    with _io.open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))

    lm = measure.resolve(cfg, cfg.get("layout_font_size", 24))
    texts, trans, files = {}, {}, {}
    for _p, u in store.all_units(docs):
        if u["kind"] != "ui":
            continue
        p = u["key"].split(":")
        if len(p) != 4 or p[0] != "M" or p[3] != "text":
            continue
        texts[(p[1], p[2])] = u["raw"]
        files[(p[1], p[2])] = (u.get("file") or "").replace("/", os.sep).lower()
        tl = (u.get("tl") or "").strip()
        if tl:
            trans[(p[1], p[2])] = tl

    ov = {}
    for k, v in (cfg.get("layout_scale_overrides") or {}).items():
        node, _s, idx = k.rpartition(":")
        ov[(node, idx)] = float(v)

    out, skipped = [], {}
    # A widget whose text is a bare code carries no Japanese, so it was never
    # extracted and `files` cannot name its owner - which silently dropped the
    # resize on every description panel. Every layout node lives in the one rom
    # file, so fall back to it exactly as `_pos_overrides` does.
    lay_file = next((f for f in files.values() if f), None)
    # The resize goes out as its own write, and the recentre is computed from
    # the resized width, so the two land together or not at all.
    for (node, idx), v in sorted(ov.items()):
        f = files.get((node, idx)) or lay_file
        if f is None or f in blocked:
            skipped["scale override with no writable owner"] = skipped.get(
                "scale override with no writable owner", 0) + 1
            continue
        out.append(("M:%s:%s:scaleX" % (node, idx), "%.4f" % v, f))
    if cfg.get("layout_vcentre"):
        vfx, vskip = recentre.vcentre(
            rows, cfg.get("layout_ink_offset_ratio", 0.0),
            float(cfg.get("layout_font_size", 24)),
            cfg.get("layout_vcentre_nodes"), ov,
            set(tuple(float(x) for x in sh)
                for sh in (cfg.get("layout_vcentre_panel_shapes") or [])))
        for key, val, _d in vfx:
            q = key.split(":")
            f = files.get((q[1], q[2]))
            if f is None or f in blocked:
                skipped["vcentre with no writable owner"] = skipped.get(
                    "vcentre with no writable owner", 0) + 1
                continue
            out.append((key, val, f))
        for k, v in vskip.items():
            if v and "share the plate" in k:
                skipped["(layout) not vcentred, stacked labels"] = skipped.get(
                    "(layout) not vcentred, stacked labels", 0) + v

    fixes, skip = recentre.fixes(rows, texts, trans, lm, ov)
    for k, v in skip.items():
        skipped[k] = v
    for key, val, _d in fixes:
        p = key.split(":")
        f = files.get((p[1], p[2]))
        if f is None:
            skipped["no owning file"] = skipped.get("no owning file", 0) + 1
            continue
        if f in blocked:
            skipped["unwritable-file"] = skipped.get("unwritable-file", 0) + 1
            continue
        out.append((key, val, f))
    return out, skipped


def _font_pair(cfg, docs, blocked):
    """The one write that decides which glyphs exist at all.

    `GameSettings.gameFont` names an INSTALLED system font. The author names one
    that only a Japanese Windows has, so everyone else gets whatever the native
    layer substitutes - and the substitute here has no U+2661, which the source
    uses 229,107 times. See `config.game_font_override` for why this cannot be
    fixed by swapping the character instead.

    Returns [(key, value, rom_file)] or [] when no override is configured."""
    want = cfg.get("game_font_override")
    if want is None:
        return []
    guid = cfg.get("game_settings_guid")
    if not guid:
        return []
    # The owning file comes from the store, not from a literal, so a rebuild
    # that renames or re-shards files cannot leave this pointing at nothing.
    f = None
    for _p, u in store.all_units(docs):
        if u["key"] == "R:%s:name" % guid:
            f = (u.get("file") or "").replace("/", os.sep).lower()
            break
    if f is None or f in blocked:
        return []
    return [("R:%s:gameFont" % guid, want, f)]


def _effectparam_pairs(cfg, docs, blocked):
    """Fill the nested copy of every Condition battle message.

    See `config.effectparams_tsv`. Nothing here is translated: each nested
    string is matched to an identical source already translated in the store, so
    the two copies cannot drift apart. A string with no match is reported rather
    than guessed at."""
    import csv
    import io as _io
    path = cfg.get("effectparams_tsv")
    if not path or not os.path.exists(path):
        return [], {"no effectparams.tsv - run `BakinTL effectparams`": 1}
    with _io.open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="	"))

    known, files = {}, {}
    for _p, u in store.all_units(docs):
        raw = (u.get("raw") or "").strip()
        tl = (u.get("tl") or "").strip()
        if raw and tl:
            known.setdefault(raw, tl)
        if u["key"].startswith("R:"):
            files.setdefault(u["key"].split(":")[1],
                             (u.get("file") or "").replace("/", os.sep).lower())

    out, skipped = [], {}
    for r in rows:
        val = (r.get("value") or "").strip()
        if not val or not codes.has_jp(val):
            continue
        en = known.get(val)
        if not en:
            skipped["nested message with no translated twin"] = skipped.get(
                "nested message with no translated twin", 0) + 1
            continue
        f = files.get(r["guid"])
        if f is None or f in blocked:
            skipped["nested message with no writable owner"] = skipped.get(
                "nested message with no writable owner", 0) + 1
            continue
        out.append(("R:%s:EffectParamSettings.EffectParamList[%s].%s"
                    % (r["guid"], r["index"], r["member"]), en, f))
    return out, skipped


def _pos_overrides(cfg, docs, blocked):
    """Hand-set positions from `config.layout_pos_overrides`.

    These are the one geometry input in the pipeline that is NOT derived, so
    they are applied verbatim and reported by count - a number nobody can
    reproduce should at least be visible."""
    table = cfg.get("layout_pos_overrides") or {}
    if not table:
        return []
    lay_file = None
    for _p, u in store.all_units(docs):
        if u["kind"] == "ui":
            lay_file = (u.get("file") or "").replace("/", os.sep).lower()
            break
    if lay_file is None or lay_file in blocked:
        return []
    out = []
    for key, vals in sorted(table.items()):
        node, _s, idx = key.rpartition(":")
        for axis in ("posX", "posY"):
            if axis in vals:
                out.append(("M:%s:%s:%s" % (node, idx, axis),
                            "%.2f" % float(vals[axis]), lay_file))
    return out


def _literal_fixups(cfg, docs, blocked):
    """Write layout labels the extractor could never see.

    A label with no Japanese is never a unit, so nothing in this pipeline can
    reach it - and that is a defect when its SIBLINGS were translated and it was
    aligned against them. See `config.layout_literal_fixups`."""
    from . import budgets
    table = cfg.get("layout_literal_fixups") or []
    path = cfg.get("layout_tsv")
    if not table or not path or not os.path.exists(path):
        return []
    # `budgets.load_layout` UN-ESCAPES the TSV, so `text` here is what the rom
    # actually holds. Reading the file raw instead would make a fixup match the
    # escaped form while writing the rom form - which silently matched nothing
    # for any string containing a backslash.
    rows = budgets.load_layout(path)

    # Any ui unit tells us which rom file layout lives in.
    lay_file = None
    translated = set()
    for _p, u in store.all_units(docs):
        if u["kind"] != "ui":
            continue
        if lay_file is None:
            lay_file = (u.get("file") or "").replace("/", os.sep).lower()
        q = u["key"].split(":")
        if len(q) == 4 and q[0] == "M" and (u.get("tl") or "").strip():
            translated.add((q[1], q[2]))
    if lay_file is None or lay_file in blocked:
        return []

    out = []
    for fix in table:
        for r in rows:
            if (r.get("text") or "") != fix["src"]:
                continue
            out.append(("M:%s:%s:text" % (r["nodeGuid"], r["idx"]),
                        fix["en"], lay_file))
            if not fix.get("align_to_partner"):
                continue
            # The partner is the TRANSLATED label sharing this container, this
            # anchor, AND the same trailing marker - here the full-width plus
            # that makes a label a stat effect. Without that last condition the
            # container's other four labels all qualify and nothing is aligned,
            # which is how this silently did half the job on its first run.
            mark = "＋" if "＋" in fix["src"] else None
            mates = [q for q in rows
                     if q["nodeGuid"] == r["nodeGuid"]
                     and q.get("parent") == r.get("parent")
                     and q.get("layoutType") == "TEXT_PANEL"
                     and q.get("origin") == r.get("origin")
                     and (mark is None or mark in (q.get("text") or ""))
                     and (q["nodeGuid"], q["idx"]) in translated]
            if len(mates) == 1:
                out.append(("M:%s:%s:posX" % (r["nodeGuid"], r["idx"]),
                            mates[0]["posX"], lay_file))
    return out


def build_pairs(cfg, docs, glossary, include_failing=False, noop=False,
                metrics=None):
    """[(key, english)] ready for BakinTL, the touched file set, and a skip tally."""
    # A code-argument unit is written back into its PARENT's text, so collect
    # those first and hand them to the parent's restore.
    args = {}
    arg_skips = {}
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] != "codearg" or not (u.get("tl") or "").strip():
                continue
            # A codearg is substituted straight into a code bracket, so it is
            # bound by the bracket reader. `build_pairs` skips the kind before
            # the parent's `hard_issues` call, so without this nothing checks
            # them at all and a `]` or `,` here truncates the code at run time.
            bad = validate.hard_issues(u, cfg, metrics)
            if bad and not include_failing:
                for b in bad:
                    arg_skips[b] = arg_skips.get(b, 0) + 1
                continue
            args.setdefault(u["key"], {})[u["sub"]] = u["tl"]

    name_map = {jp: store.name_en(v)
                for jp, v in (glossary.get("names") or {}).items()
                if store.name_en(v)}
    blocked = _unwritable(cfg)
    # No font, no repair - and say so, rather than silently shipping the
    # greedy wrap because a font failed to resolve.
    meas = metrics.width if metrics is not None else None
    tally = collections.Counter()
    pairs = []
    touched = set()
    skipped = dict(("codearg:" + k, v) for k, v in arg_skips.items())
    for _p, doc in docs:
        for u in doc["units"]:
            if u["kind"] == "codearg":
                continue
            f = (u.get("file") or "").replace("/", os.sep).lower()
            if f in blocked:
                # A file the catalog cannot reproduce byte-for-byte is never
                # written. See `config.unwritable_files` for the measurement
                # and the exact cost.
                skipped["unwritable-file"] = skipped.get("unwritable-file", 0) + 1
                continue
            if noop:
                pairs.append((u["key"], u["raw"]))
                touched.add(f)
                continue
            tl = (u.get("tl") or "").strip()
            if not tl:
                skipped["untranslated"] = skipped.get("untranslated", 0) + 1
                continue
            # The nameplate is not in `tl`, so no per-unit check sees it.
            # `name_lookup` falls back to the Japanese when a speaker has no
            # approved English name, which would ship an English line under a
            # Japanese name box - so refuse the unit and leave the whole line
            # in Japanese, which is a visible no-op rather than a half-patch.
            if u.get("speaker") and codes.safe_code_arg(u.get("speaker_en") or ""):
                skipped["unsafe-speaker-name"] = skipped.get(
                    "unsafe-speaker-name", 0) + 1
                continue
            # `speaker_en == speaker` means `name_lookup` fell through, which
            # is only a FAILURE when the nameplate was Japanese. A nameplate
            # that is already Latin - `VIP`, an alphanumeric mob tag - has an
            # identical correct rendering, and reading equality as
            # untranslated left four correct lines in Japanese.
            if (u.get("speaker") and u.get("speaker_en") == u.get("speaker")
                    and codes.has_jp(u["speaker"])):
                skipped["untranslated-speaker"] = skipped.get(
                    "untranslated-speaker", 0) + 1
                continue
            issues = validate.hard_issues(u, cfg, metrics)
            # A check in RETRY_EXCLUDE is REPORTED, not blocking. It carries a
            # measurement saying another round trip cannot fix it, and the
            # CONFLICT bucket behind it has been read by hand - so refusing to
            # write those units does not avoid a defect, it ships 601 lines in
            # JAPANESE to avoid a flag already judged. Reported here so the
            # decision stays visible.
            blocking = [i for i in issues if i not in validate.RETRY_EXCLUDE]
            for i in issues:
                if i in validate.RETRY_EXCLUDE:
                    skipped["(written anyway) " + i] = skipped.get(
                        "(written anyway) " + i, 0) + 1
            if blocking and not include_failing:
                for i in blocking:
                    tag = i.split(":")[0]
                    skipped[tag] = skipped.get(tag, 0) + 1
                continue
            pairs.append((u["key"], render(u, args.get(u["key"]), name_map,
                                           balance.wrap_width(cfg, u["kind"]),
                                           meas, tally)))
            touched.add(f)

    # --- put hand-positioned labels back where the author centred them -------
    # This writes a NUMBER, not text, and it is the only such write. See
    # `recentre.py`: several labels are centred on their plate by a per-label
    # `pos.X` the author tuned against the JAPANESE width, so replacing the
    # text leaves them off centre with nothing overflowing and every width
    # check passing. Off the no-op path for the same structural reason as the
    # wrap repair - `noop` returns above and never reaches here.
    if not noop:
        for key, val, f in _pos_overrides(cfg, docs, blocked):
            pairs.append((key, val))
            touched.add(f)
            skipped["(layout) hand-set positions (NOT measured)"] = skipped.get(
                "(layout) hand-set positions (NOT measured)", 0) + 1
        ep_fix, ep_skip = _effectparam_pairs(cfg, docs, blocked)
        for key, val, f in ep_fix:
            pairs.append((key, val))
            touched.add(f)
        if ep_fix:
            skipped["(rom) nested battle messages filled"] = len(ep_fix)
        for k, v in ep_skip.items():
            skipped["(rom) " + k] = v
        for key, val, f in _literal_fixups(cfg, docs, blocked):
            pairs.append((key, val))
            touched.add(f)
            skipped["(layout) literal label fixups"] = skipped.get(
                "(layout) literal label fixups", 0) + 1
        for key, val, f in _font_pair(cfg, docs, blocked):
            pairs.append((key, val))
            touched.add(f)
            skipped["(layout) gameFont set to %r" % val] = 1
        n_fix, n_skip = _recentre_pairs(cfg, docs, blocked)
        for key, val, f in n_fix:
            pairs.append((key, val))
            touched.add(f)
        n_pos = sum(1 for k, _v, _f in n_fix if k.endswith(":posX"))
        n_vc = sum(1 for k, _v, _f in n_fix if k.endswith(":posY"))
        n_scl = len(n_fix) - n_pos - n_vc
        if n_vc:
            skipped["(layout) labels vertically centred on their plate"] = n_vc
        if n_pos:
            skipped["(layout) labels recentred"] = n_pos
        if n_scl:
            skipped["(layout) labels resized to fit their plate"] = n_scl
        for k, v in n_skip.items():
            if v:
                # Some keys already carry their own "(layout) ..." prefix.
                skipped[k if k.startswith("(layout)")
                        else "(layout) not recentred, " + k] = v

    # A write key must appear once. `extract.run` deliberately LEAVES stale doc
    # shards in place so a game update never silently drops work, which means a
    # re-extraction producing fewer parts for a shard can leave an orphaned
    # `X.01.json` whose units carry the same keys as the fresh ones. BakinTL
    # would apply whichever came last and nothing would say so.
    seen = {}
    dupes = []
    for k, en in pairs:
        if k in seen and seen[k] != en:
            dupes.append(k)
        seen[k] = en
    if dupes:
        raise SystemExit(
            "REFUSING to inject: %d write key(s) resolve to two different "
            "strings, e.g. %s.\n"
            "  The usual cause is a stale doc shard left in %s by an earlier "
            "extraction with a different shard layout. Delete the orphaned "
            "units/*.json and re-run `tl.py extract`."
            % (len(dupes), ", ".join(dupes[:3]), cfg["store_dir"]))
    if meas is None and not noop:
        skipped["(no font) layout repair skipped entirely"] = 1
    for k, v in tally.items():
        if v:
            skipped["(layout) " + k] = v
    return pairs, touched, skipped


def copy_through(cfg, out_dir, touched, verbose=True):
    """Restore every rom file the patch did not actually change.

    `Catalog.save` rewrites the whole tree, so a file with no translation in it
    still comes out re-serialised. Re-serialisation is byte-identical here (the
    round-trip gate proves it), but copying the pristine bytes back makes that
    a fact about the shipped patch rather than a fact about a test - and it is
    what lets an unwritable file be excluded without leaving a half-written
    version of it behind."""
    import shutil
    n = 0
    for dirpath, _dirs, files in os.walk(cfg["proj_dir"]):
        for fn in files:
            if not fn.lower().endswith(".rbr"):
                continue
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, cfg["proj_dir"])
            if rel.lower() in touched:
                continue
            dst = os.path.join(out_dir, rel)
            if not os.path.exists(dst):
                continue
            if os.path.getsize(dst) == os.path.getsize(src):
                with open(src, "rb") as a, open(dst, "rb") as b:
                    if a.read() == b.read():
                        continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            n += 1
    if verbose and n:
        print("copied through %d untouched rom file(s) from the pristine tree" % n)
    return n


def render(u, arg_map=None, name_map=None, wrap_px=None, meas=None,
           tally=None):
    r"""The exact string that goes into the rom field.

    Order matters: clean, then restore codes (which reintroduces backslashes
    the cleaner must not have seen), then substitute any display-text code
    argument, then REBALANCE, then re-attach the nameplate.

    The rebalance sits exactly there for two reasons. It has to run on the
    FINAL visible text, so after the code and argument restoration. And it has
    to run before `join_speaker`, because `\NPL[Sister Agatha]` carries a space
    inside its bracket and a whitespace tokeniser would break the code in half.

    It is reached only when the caller supplies a width and a font, which the
    no-op path never does - `build_pairs(noop=True)` returns `u["raw"]` without
    calling this function at all, so the byte-exact round-trip gate cannot see
    a rebalanced string."""
    text = codes.clean_translation(u["tl"])
    text = codes.unmask_codes(text, u.get("codes") or {}, pad_inserts=True)
    if arg_map:
        for whole, name, arg in codes.display_args(text):
            en = arg_map.get(name)
            if en:
                text = text.replace(whole, "\\%s[%s]" % (name, en), 1)
    if wrap_px and meas is not None:
        text, n, coded = balance.rebalance_text(text, wrap_px, meas)
        if tally is not None:
            tally["lines-rebalanced"] += n
            tally["orphans-left-coded"] += coded
    if u["kind"] == "text" and u.get("plate"):
        text = codes.join_speaker(u.get("speaker_en") or u.get("speaker"),
                                 text, u.get("plate"))
    # A nameplate that is NOT the leading one. `split_speaker` peels the
    # head code into `speaker`, so a second one further down the same unit
    # is masked as an ordinary code and restores with its JAPANESE name -
    # an English line under a Japanese name box, invisible to every check
    # because the speaker is not in `tl`. One unit in 90,189 does this; the
    # mechanism is general and the fix is one substitution.
    if name_map:
        text = codes.NAMEPLATE_ANY_RE.sub(
            lambda m: "\\%s[%s]" % (
                m.group(1), name_map.get(m.group(2), m.group(2))),
            text)
    # Message bodies use real CRLF in the rom; the model works in LF.
    return codes.to_crlf(text)


def resolve_speakers(docs, glossary):
    """Stamp each dialogue unit with its speaker's approved English name.

    Done once here rather than inside `render`, so a glossary edit takes effect
    on the next inject without re-reading the glossary 84,000 times."""
    n = 0
    for _p, doc in docs:
        for u in doc["units"]:
            if u.get("speaker"):
                u["speaker_en"] = store.name_lookup(glossary, u["speaker"])
                n += 1
    return n


def write_jsonl(path, pairs):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        for k, en in pairs:
            f.write(json.dumps({"key": k, "en": en}, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def run(cfg, out_dir=None, include_failing=False, noop=False, verbose=True):
    """Build translated.jsonl and run `BakinTL inject`.

    `noop=True` writes every unit's SOURCE back instead of its translation.
    That is the gate the whole pipeline rests on: extraction and injection are
    lossless only if a no-op inject reproduces every rom file byte for byte."""
    docs = store.load_docs(cfg["store_dir"])
    glossary = store.load_glossary(cfg["store_dir"])
    resolve_speakers(docs, glossary)

    # `inject` must apply the SAME gate `validate` reports, or it writes rows
    # that `validate` calls blocking. That needs the font metrics and the
    # layout budgets loaded, exactly as `validate.run` does.
    metrics = measure.reset(cfg)
    if cfg.get("keywords"):
        codes.load_keywords(cfg["keywords"])
    if not validate.load_budgets(cfg, docs) and verbose:
        print("WARNING: no layout.tsv - the overflow gate is OFF for this "
              "inject. Run `tl.py layout` first.")
    pairs, touched, skipped = build_pairs(cfg, docs, glossary,
                                          include_failing, noop=noop,
                                          metrics=metrics)

    path = os.path.join(cfg["work_dir"], "noop.jsonl" if noop else "translated.jsonl")
    write_jsonl(path, pairs)
    if verbose:
        print("%d write sites in %d rom file(s) -> %s"
              % (len(pairs), len(touched), path))
        for k, v in sorted(skipped.items(), key=lambda x: -x[1]):
            print("   skipped %-28s %6d" % (k, v))

    out_dir = out_dir or cfg["out_dir"]
    env = dict(os.environ, BAKIN_DATA=os.path.join(cfg["game_dir"], "data"))
    cmd = [cfg["bakintl"], "inject", cfg["proj_dir"], path, out_dir]
    if verbose:
        print("$ " + " ".join(cmd))
    rc = subprocess.call(cmd, env=env)
    if rc == 0:
        copy_through(cfg, out_dir, touched, verbose)
        if noop:
            rc = verify_noop(cfg, out_dir, verbose)
    return rc


def verify_noop(cfg, out_dir, verbose=True):
    """After a no-op, EVERY rom file must be byte-identical to the source.

    BakinTL prints its own comparison, but it runs before copy-through; this is
    the one that decides, and it is the gate the whole pipeline rests on."""
    bad, same = [], 0
    for dirpath, _dirs, files in os.walk(cfg["proj_dir"]):
        for fn in files:
            if not fn.lower().endswith(".rbr"):
                continue
            src = os.path.join(dirpath, fn)
            rel = os.path.relpath(src, cfg["proj_dir"])
            dst = os.path.join(out_dir, rel)
            if not os.path.exists(dst):
                bad.append((rel, "missing from the output"))
                continue
            with open(src, "rb") as a, open(dst, "rb") as b:
                x, y = a.read(), b.read()
            if x == y:
                same += 1
            else:
                bad.append((rel, "src=%d out=%d" % (len(x), len(y))))
    if verbose:
        print("NO-OP GATE: %d identical, %d differing" % (same, len(bad)))
        for rel, why in bad[:10]:
            print("   DIFF %s  %s" % (rel, why))
    return 0 if not bad else 1


if __name__ == "__main__":
    from . import config
    sys.exit(run(config.load(), noop="--noop" in sys.argv))
