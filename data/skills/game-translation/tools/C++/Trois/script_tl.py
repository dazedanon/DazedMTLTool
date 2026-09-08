#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
script_tl.py — extract / inject translatable text for the PIX-engine VN scripts
(natuiso). Produces LLM-friendly per-file JSON with full context (speaker, role,
scene separation) and re-injects translations back into the UTF-8 scripts with a
byte-exact round-trip guarantee.

Sub-commands
------------
  extract   scripts -> JSON (one .json per script, scenes separated by label)
  inject    JSON (+ original scripts) -> translated scripts
  verify    parse+rebuild every script and confirm it is byte-identical (round-trip)
  glossary  write a starter character glossary you can edit, then reuse with extract

Examples
--------
  python script_tl.py extract  natuiso_extracted/scripts -o tl_json
  # ...translate the "translation" fields in tl_json/*.json with an LLM...
  python script_tl.py inject   tl_json --scripts natuiso_extracted/scripts -o scripts_en
  python script_tl.py verify   natuiso_extracted/scripts

Design
------
A single tokenizer is used by every command. It splits a script into an ordered
token stream:
  * RAW      — commands, comments, blank lines, and ＠speaker lines (kept verbatim)
  * TEXT     — a contiguous block of dialogue / monologue / narration (translatable)
A line is TEXT iff its first non-space character is non-ASCII and not the ＠ marker
(every engine command/keyword in these scripts is ASCII; all on-screen Japanese text
starts with kana/kanji or a 「『（ quote). Re-emitting RAW verbatim and TEXT either as
the translation or as the original guarantees an exact round-trip; `verify` enforces it.
"""

import os
import re
import sys
import csv
import json
import glob
import argparse

SPEAKER_MARKERS = ("＠", "@")
MONOLOGUE_OPEN = set("（(｟")
LABEL_RE = re.compile(r'^\s*label[\s\t]+(\S+)', re.I)
SCENE_RE = re.compile(r'^\s*scene[\s\t]+"?([^"\t]+)"?', re.I)


# --------------------------------------------------------------------------
# Character glossary (curated; readings marked uncertain where unsure).
# `extract` embeds, per file, only the speakers that appear in that file.
# Edit the generated _glossary.json to refine names/tone, then pass --glossary.
# --------------------------------------------------------------------------
GLOSSARY_SEED = {
    "愛梨":        {"romaji": "Airi",      "name_en": "Airi",      "gender": "F", "role": "protagonist / POV; high-school girl", "speech": "casual, lively"},
    "千佳":        {"romaji": "Chika",     "name_en": "Chika",     "gender": "F", "role": "friend/classmate of Airi", "speech": "casual"},
    "智":          {"romaji": "Satoshi?",  "name_en": "Satoshi",   "gender": "?", "role": "acquaintance of Airi", "speech": "", "notes": "reading uncertain (Satoshi/Tomo/Akira) — confirm in context"},
    "愛梨母":      {"romaji": "Airi-haha", "name_en": "Airi's Mother", "gender": "F", "role": "Airi's mother", "speech": "maternal"},
    "愛梨父":      {"romaji": "Airi-chichi","name_en": "Airi's Father", "gender": "M", "role": "Airi's father", "speech": ""},
    "男教師":      {"romaji": "",          "name_en": "Male Teacher", "gender": "M", "role": "teacher", "speech": ""},
    "男教師Ａ":    {"romaji": "",          "name_en": "Male Teacher A", "gender": "M", "role": "teacher", "speech": ""},
    "保健医":      {"romaji": "",          "name_en": "School Nurse", "gender": "?", "role": "infirmary doctor/nurse", "speech": ""},
    "黒服":        {"romaji": "",          "name_en": "Man in Black", "gender": "M", "role": "suited man", "speech": ""},
    "アナウンサー":{"romaji": "",          "name_en": "Announcer", "gender": "?", "role": "TV news announcer", "speech": "formal/news register"},
    "女学生Ａ":    {"romaji": "",          "name_en": "Female Student A", "gender": "F", "role": "student", "speech": ""},
    "男子Ａ":      {"romaji": "",          "name_en": "Boy A", "gender": "M", "role": "student", "speech": ""},
    "男子Ｂ":      {"romaji": "",          "name_en": "Boy B", "gender": "M", "role": "student", "speech": ""},
    "男子Ｃ":      {"romaji": "",          "name_en": "Boy C", "gender": "M", "role": "student", "speech": ""},
    "男子学生Ａ":  {"romaji": "",          "name_en": "Male Student A", "gender": "M", "role": "student", "speech": ""},
    "白衣の男Ａ":  {"romaji": "",          "name_en": "Man in Lab Coat A", "gender": "M", "role": "lab-coated man", "speech": ""},
    "白衣の男Ｂ":  {"romaji": "",          "name_en": "Man in Lab Coat B", "gender": "M", "role": "lab-coated man", "speech": ""},
    "白衣の男Ｃ":  {"romaji": "",          "name_en": "Man in Lab Coat C", "gender": "M", "role": "lab-coated man", "speech": ""},
    "女性ｼｽﾃﾑﾎﾞｲｽ":{"romaji": "",         "name_en": "Female System Voice", "gender": "F", "role": "system/UI voice", "speech": "neutral"},
}

GAME_META = {
    "game_jp": "夏とプールとイソギンチャク",
    "game_romaji": "Natsu to Pool to Isoginchaku",
    "game_en": "Summer, the Pool, and the Sea Anemone",
    "studio": "PIX GAME STUDIO",
    "rating": "18+ (adult / explicit content)",
    "type": "kinetic visual novel (no choices/branches)",
}

INSTRUCTIONS = (
    "You are translating an adult Japanese visual novel into natural, fluent English. "
    "Translate ONLY the 'source' field of each segment into 'translation'; leave structure, "
    "ids, speakers and voice ids untouched. Segments are in reading order within each scene; "
    "scenes are independent context units. 'type' is dialogue (spoken aloud, 「」), monologue "
    "(inner thought, （）), or narration (prose). Match each speaker's register/tone using the "
    "character glossary, keep pronouns/relationships consistent, and preserve meaning and nuance "
    "(including explicit content) rather than translating word-for-word. A full-width space "
    "(\\u3000) is just indentation and may be dropped. Do not add or drop segments."
)


# --------------------------------------------------------------------------
# Tokenizer (shared by all commands)
# --------------------------------------------------------------------------
def is_text_first_char(s):
    if not s:
        return False
    c = s[0]
    return ord(c) > 0x2000 and c not in SPEAKER_MARKERS


def split_keep_newline(raw_text):
    nl = "\r\n" if "\r\n" in raw_text else "\n"
    lines = raw_text.split(nl)
    had_final_nl = False
    if len(lines) > 1 and lines[-1] == "":
        lines = lines[:-1]
        had_final_nl = True
    return lines, nl, had_final_nl


def parse_lines(lines, stem):
    """Yield ordered tokens. Each token is a dict:
       {'kind':'raw','line':str}
       {'kind':'text','seq':int,'lines':[str],'type':str,'speaker':str|None,
        'voice':str|None,'label':str|None,'scene_title':str|None}
    """
    tokens = []
    seq = 0
    cur_label = None
    cur_scene_title = None
    pending_speaker = None
    pending_voice = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        s = line.strip()

        # blank -> raw, breaks speaker association
        if s == "":
            pending_speaker = None
            pending_voice = None
            tokens.append({"kind": "raw", "line": line})
            i += 1
            continue

        # comment -> raw
        if s.startswith("//"):
            tokens.append({"kind": "raw", "line": line})
            i += 1
            continue

        # speaker tag -> raw (verbatim) + set pending speaker for next text block
        if s[0] in SPEAKER_MARKERS:
            body = s[1:]
            parts = body.split(",", 1)
            pending_speaker = parts[0].strip() or None
            pending_voice = parts[1].strip() if len(parts) > 1 else None
            tokens.append({"kind": "raw", "line": line})
            i += 1
            continue

        # translatable text block: consume consecutive TEXT lines
        if is_text_first_char(s):
            block = [line]
            j = i + 1
            while j < n:
                nxt = lines[j].strip()
                if nxt == "" or nxt.startswith("//") or nxt[:1] in SPEAKER_MARKERS \
                        or not is_text_first_char(nxt):
                    break
                block.append(lines[j])
                j += 1
            first = block[0].strip()[0]
            if pending_speaker is not None:
                seg_type = "monologue" if first in MONOLOGUE_OPEN else "dialogue"
                spk, voice = pending_speaker, pending_voice
            else:
                seg_type = "narration"
                spk, voice = None, None
            seq += 1
            tokens.append({
                "kind": "text", "seq": seq, "lines": block, "type": seg_type,
                "speaker": spk, "voice": voice,
                "label": cur_label, "scene_title": cur_scene_title,
            })
            pending_speaker = None
            pending_voice = None
            i = j
            continue

        # otherwise a command/keyword line -> raw; track label / scene title
        m = LABEL_RE.match(line)
        if m:
            cur_label = m.group(1)
        else:
            ms = SCENE_RE.match(line)
            if ms:
                cur_scene_title = ms.group(1).strip()
        tokens.append({"kind": "raw", "line": line})
        i += 1
    return tokens


def seg_id(stem, seq):
    return "%s#%04d" % (stem, seq)


# --------------------------------------------------------------------------
# extract
# --------------------------------------------------------------------------
def cmd_extract(args):
    files = expand_inputs(args.inputs, args.ext or [".txt"])
    glossary = load_glossary(args.glossary)
    os.makedirs(args.out, exist_ok=True)

    index = []
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        raw = open(path, "rb").read().decode("utf-8")
        lines, _nl, _fin = split_keep_newline(raw)
        tokens = parse_lines(lines, stem)

        # group text tokens into scenes by label (or per args.split)
        scenes = []
        scene_map = {}
        order = []
        speakers_in_file = set()
        n_seg = 0
        for t in tokens:
            if t["kind"] != "text":
                continue
            n_seg += 1
            if args.split == "file":
                key = stem
                label = None
            elif args.split == "none":
                key = stem
                label = None
            else:  # label (default)
                key = t["label"] or "(prologue)"
                label = t["label"]
            if key not in scene_map:
                scene_map[key] = {
                    "scene_id": "%s:%s" % (stem, key),
                    "label": label,
                    "title": t.get("scene_title") or "",
                    "speakers": [],
                    "segments": [],
                }
                order.append(key)
            sc = scene_map[key]
            if not sc["title"] and t.get("scene_title"):
                sc["title"] = t["scene_title"]
            spk = t["speaker"]
            if spk:
                speakers_in_file.add(spk)
                if spk not in sc["speakers"]:
                    sc["speakers"].append(spk)
            sc["segments"].append({
                "id": seg_id(stem, t["seq"]),
                "type": t["type"],
                "speaker": spk,
                "speaker_en": glossary.get(spk, {}).get("name_en", spk) if spk else None,
                "voice": t["voice"],
                "source": "\n".join(t["lines"]).strip(),
                "translation": "",
                "note": "",
            })
        scenes = [scene_map[k] for k in order]

        # merge: preserve existing translations if re-extracting over prior work
        out_path = os.path.join(args.out, stem + ".json")
        if args.merge and os.path.exists(out_path):
            merge_translations(out_path, scenes)

        chars = [dict(name=k, **glossary.get(k, {"name_en": k}))
                 for k in sorted(speakers_in_file)]
        doc = {
            "meta": dict(GAME_META, source_file=os.path.basename(path),
                         encoding="utf-8", instructions=INSTRUCTIONS,
                         scene_split=args.split, characters=chars),
            "scenes": scenes,
        }
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        nseg = sum(len(s["segments"]) for s in scenes)
        index.append((os.path.basename(out_path), len(scenes), nseg))
        if not args.quiet:
            print("  %-22s scenes=%3d segments=%4d" % (stem + ".json", len(scenes), nseg))

    # master glossary + index
    with open(os.path.join(args.out, "_glossary.json"), "w", encoding="utf-8") as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)
    total = sum(n for _, _, n in index)
    print("Extracted %d files, %d segments -> %s" % (len(index), total, os.path.abspath(args.out)))


def merge_translations(out_path, new_scenes):
    try:
        old = json.load(open(out_path, encoding="utf-8"))
    except Exception:
        return
    prev = {}
    for sc in old.get("scenes", []):
        for seg in sc.get("segments", []):
            if seg.get("translation"):
                prev[(seg["id"], seg.get("source", ""))] = (seg["translation"], seg.get("note", ""))
    for sc in new_scenes:
        for seg in sc["segments"]:
            k = (seg["id"], seg["source"])
            if k in prev:
                seg["translation"], seg["note"] = prev[k]


# --------------------------------------------------------------------------
# inject
# --------------------------------------------------------------------------
def wrap_text(text, font, max_px):
    """Word-wrap to <= max_px using the font's metrics. Existing newlines in the
    translation are treated as soft (re-flowed), since the message window wraps by width."""
    words = text.replace("\n", " ").split()
    if not words:
        return text
    lines, cur = [], words[0]
    for w in words[1:]:
        if font.getlength(cur + " " + w) <= max_px:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return "\n".join(lines)


def _get_wrap_font(args):
    """Load the EN message font once (or return None if wrapping is off/unavailable)."""
    if not getattr(args, "wrap", True):
        return None
    if hasattr(args, "_wrap_font_cache"):
        return args._wrap_font_cache
    f = None
    try:
        from PIL import ImageFont
        f = ImageFont.truetype(args.wrap_font, args.wrap_size)
    except Exception as e:
        print("  (word-wrap disabled — %s)" % e)
    args._wrap_font_cache = f
    return f


def cmd_inject(args):
    json_files = []
    if os.path.isdir(args.json):
        json_files = [p for p in glob.glob(os.path.join(args.json, "*.json"))
                      if os.path.basename(p) not in ("_glossary.json", "_batch_state.json")]
    else:
        json_files = [args.json]

    names_map = {}
    if args.translate_names:
        gpath = os.path.join(args.json if os.path.isdir(args.json) else os.path.dirname(args.json),
                             "_glossary.json")
        gl = load_glossary(gpath if os.path.exists(gpath) else None)
        names_map = {k: v.get("name_en", k) for k, v in gl.items() if v.get("name_en")}

    os.makedirs(args.out, exist_ok=True)
    tot_tr = tot_seg = tot_missing = 0
    for jp in json_files:
        doc = json.load(open(jp, encoding="utf-8"))
        src_name = doc["meta"]["source_file"]
        src_path = os.path.join(args.scripts, src_name)
        if not os.path.exists(src_path):
            print("  ! source missing for %s (%s)" % (os.path.basename(jp), src_path))
            continue
        trans = {}
        for sc in doc["scenes"]:
            for seg in sc["segments"]:
                if seg.get("translation", "").strip():
                    trans[seg["id"]] = seg["translation"]

        raw = open(src_path, "rb").read().decode("utf-8")
        lines, nl, had_final = split_keep_newline(raw)
        stem = os.path.splitext(src_name)[0]
        tokens = parse_lines(lines, stem)
        wfont = _get_wrap_font(args)

        out_lines = []
        n_tr = n_seg = n_missing = 0
        for t in tokens:
            if t["kind"] == "raw":
                line = t["line"]
                if args.translate_names and line.strip()[:1] in SPEAKER_MARKERS:
                    line = rewrite_speaker(line, names_map)
                out_lines.append(line)
            else:  # text
                n_seg += 1
                sid = seg_id(stem, t["seq"])
                if sid in trans:
                    n_tr += 1
                    txt = trans[sid]
                    if wfont is not None:
                        txt = wrap_text(txt, wfont, args.wrap_px)
                    out_lines.extend(txt.split("\n"))
                else:
                    n_missing += 1
                    if args.fallback == "empty":
                        out_lines.append("")
                    elif args.fallback == "mark":
                        out_lines.append("【UNTRANSLATED】" + "\n".join(t["lines"]))
                    else:  # original
                        out_lines.extend(t["lines"])
        out_text = nl.join(out_lines) + (nl if had_final else "")
        dest = os.path.join(args.out, src_name)
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "w", encoding="utf-8", newline="") as f:
            f.write(out_text)
        tot_tr += n_tr; tot_seg += n_seg; tot_missing += n_missing
        if not args.quiet:
            print("  %-22s %d/%d translated (%d fallback)" % (src_name, n_tr, n_seg, n_missing))
    print("Injected %d/%d segments (%d fallback) -> %s"
          % (tot_tr, tot_seg, tot_missing, os.path.abspath(args.out)))


def rewrite_speaker(line, names_map):
    # preserve leading whitespace + marker, swap the JP name before any comma
    m = re.match(r'^(\s*[＠@])([^,\r\n]*)(.*)$', line)
    if not m:
        return line
    name = m.group(2).strip()
    en = names_map.get(name)
    if not en:
        return line
    return m.group(1) + en + m.group(3)


# --------------------------------------------------------------------------
# verify (round-trip)
# --------------------------------------------------------------------------
def cmd_verify(args):
    files = expand_inputs(args.inputs, args.ext or [".txt"])
    ok = bad = 0
    for path in files:
        raw = open(path, "rb").read().decode("utf-8")
        lines, nl, had_final = split_keep_newline(raw)
        stem = os.path.splitext(os.path.basename(path))[0]
        tokens = parse_lines(lines, stem)
        out_lines = []
        for t in tokens:
            if t["kind"] == "raw":
                out_lines.append(t["line"])
            else:
                out_lines.extend(t["lines"])
        rebuilt = nl.join(out_lines) + (nl if had_final else "")
        if rebuilt == raw:
            ok += 1
        else:
            bad += 1
            print("  ! ROUND-TRIP MISMATCH: %s" % os.path.basename(path))
            _show_first_diff(raw, rebuilt)
    print("Round-trip: %d ok, %d mismatched (of %d)" % (ok, bad, ok + bad))
    return 1 if bad else 0


def _show_first_diff(a, b):
    la, lb = a.split("\n"), b.split("\n")
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else "<EOF>"
        y = lb[i] if i < len(lb) else "<EOF>"
        if x != y:
            print("     line %d:\n       orig: %r\n       new : %r" % (i + 1, x, y))
            return


# --------------------------------------------------------------------------
# glossary
# --------------------------------------------------------------------------
def cmd_glossary(args):
    out = args.out if args.out.endswith(".json") else os.path.join(args.out, "_glossary.json")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(GLOSSARY_SEED, f, ensure_ascii=False, indent=2)
    print("Wrote starter glossary -> %s (edit, then pass with --glossary)" % os.path.abspath(out))


def load_glossary(path):
    g = dict(GLOSSARY_SEED)
    if path and os.path.exists(path):
        try:
            user = json.load(open(path, encoding="utf-8"))
            for k, v in user.items():
                g[k] = v
        except Exception as e:
            print("  ! could not read glossary %s: %s" % (path, e))
    return g


# --------------------------------------------------------------------------
def expand_inputs(inputs, exts):
    exts = {e.lower() for e in exts}
    out = []
    for p in inputs:
        if os.path.isfile(p):
            out.append(p)
        elif os.path.isdir(p):
            for f in sorted(os.listdir(p)):
                if os.path.splitext(f)[1].lower() in exts:
                    out.append(os.path.join(p, f))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="scripts -> translation JSON")
    pe.add_argument("inputs", nargs="+")
    pe.add_argument("-o", "--out", default="tl_json")
    pe.add_argument("--split", choices=["label", "file", "none"], default="label",
                    help="scene granularity (default: label)")
    pe.add_argument("--glossary", default=None, help="character glossary json to embed")
    pe.add_argument("--merge", action="store_true",
                    help="keep existing translations when re-extracting over an out dir")
    pe.add_argument("--ext", nargs="*", default=[".txt"])
    pe.add_argument("--quiet", action="store_true")
    pe.set_defaults(func=cmd_extract)

    pi = sub.add_parser("inject", help="translation JSON + originals -> translated scripts")
    pi.add_argument("json", help="dir of translated json (or a single json)")
    pi.add_argument("--scripts", required=True, help="dir of ORIGINAL scripts")
    pi.add_argument("-o", "--out", default="scripts_translated")
    pi.add_argument("--fallback", choices=["original", "empty", "mark"], default="original",
                    help="what to write for untranslated segments (default: original)")
    pi.add_argument("--no-wrap", dest="wrap", action="store_false", default=True,
                    help="do NOT word-wrap translations (wrapping to the message window is ON by default)")
    pi.add_argument("--wrap-px", type=float, default=770.0,
                    help="message-window text width in px used for wrapping (default 770; the "
                         "message font is bold/weight-6 so this leaves headroom vs the ~800px area "
                         "to stop the engine re-wrapping and orphaning words)")
    pi.add_argument("--wrap-font", default="natuiso_extracted/system/fonts/fonts.en_us.otf",
                    help="EN message font used to measure wrap width")
    pi.add_argument("--wrap-size", type=int, default=26, help="message font size (default 26)")
    pi.add_argument("--translate-names", action="store_true",
                    help="also rewrite ＠speaker names to name_en from glossary "
                         "(MAY affect voice/nameplate matching — test in-game first)")
    pi.add_argument("--quiet", action="store_true")
    pi.set_defaults(func=cmd_inject)

    pv = sub.add_parser("verify", help="byte-exact round-trip check of the parser")
    pv.add_argument("inputs", nargs="+")
    pv.add_argument("--ext", nargs="*", default=[".txt"])
    pv.set_defaults(func=cmd_verify)

    pg = sub.add_parser("glossary", help="write starter character glossary")
    pg.add_argument("-o", "--out", default="tl_json")
    pg.set_defaults(func=cmd_glossary)

    args = ap.parse_args()
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    rc = args.func(args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
