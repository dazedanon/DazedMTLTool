#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract.py — walk www/data/*.json and build the translation store.

Produces one tl/<Name>.json per source file plus a seeded glossary.json
(character names collected from Actors + \\kw/\\nw speakers, left untranslated).

Re-running is safe: it rebuilds the store from the source data but MERGES with
any existing store/glossary so previously fetched translations are preserved
(matched by unit id).
"""

import os
import glob
import json
import re

from . import codes, store, patterns
from .config import Config

_VREF_RE = re.compile(r"\\[vV]\[(\d+)\]")


def _collect_displayed_vars(data_dir):
    """Variable ids referenced via \\V[n] in any PLAYER-FACING text (show-text,
    scrolling, plugin-picture, script display) — used to decide which code-122
    string variables hold display text vs internal keys/filenames."""
    displayed = set()
    for path in glob.glob(os.path.join(data_dir, "*.json")):
        try:
            data = _load(path)
        except Exception:
            continue
        stem = os.path.splitext(os.path.basename(path))[0]
        if not (stem in ("CommonEvents", "Troops") or
                (stem.startswith("Map") and stem != "MapInfos")):
            continue
        for _ptr, lst, _ctx, _idp in _iter_command_lists(data, stem):
            for c in (lst or []):
                if not isinstance(c, dict):
                    continue
                code, ps = c.get("code"), c.get("parameters") or []
                if code in (401, 405, 355, 655) and ps and isinstance(ps[0], str):
                    displayed.update(int(x) for x in _VREF_RE.findall(ps[0]))
                elif code == 357 and len(ps) >= 4 and isinstance(ps[3], dict):
                    for v in ps[3].values():
                        if isinstance(v, str):
                            displayed.update(int(x) for x in _VREF_RE.findall(v))
    return displayed

# Event command codes
C_TEXT = 401
C_SCROLL = 405
C_CHOICE = 102

# Per-game presets seeded into the glossary. Only fills fields that are still
# empty, so hand-edits in glossary.json are never clobbered. Harmless for other
# games (keys just won't match). Hand-authored from reading this game's dialogue
# (サキュバス将軍の兵力増産所 / "Brood General Succubus", RPG Maker MZ, circle 丸宝堂).
SEED_CHARACTER_META = {
    "アインアイク": {
        "en": "Einaike", "gender": "female",
        "role": "protagonist; succubus general, the '紫焔将 / Purple-Flame General', one of the Three Generals (三鼎将)",
        "register": "dutiful, proud, serious military officer; mostly polite/formal; loyal to the Demon Lord. "
                    "Defeated and forced into the breeding facility — desperate, anguished and eventually broken in H-scenes.",
        "note": "name romanization tentative (アインアイク → Einaike); verify. The main playable character (~4000 lines).",
    },
    "フォルファクス": {
        "en": "Furfur", "gender": "female",
        "role": "antagonist; a great demon (大魔族), the '凶角卿 / Vicious-Horn Lord'; a cow-girl Minotaur-type; "
                "commands the 凶角団 (Vicious-Horn Brigade); a former superior of Einaike's, later bred in the facility",
        "register": "theatrical sadist; first person アタシ; cackles ('キッヒ', 'キヒヒッヒ'); mock-courteous, elongated vowels (サァ); "
                    "calls Einaike '優等生ドノ (honor-student)'; oily and cruel.",
        "note": "FEMALE (Hydra refers to her as 彼女; mocked as a 牛娘/'cow-girl'). The 卿/Lord rank is gender-neutral. "
                "Ars Goetia demon Furfur/Forfax (bull/stag form fits the cow-girl design). Keep romanization 'Furfur', not 'Forfax'.",
    },
    "カロン": {
        "en": "Charon", "gender": "male",
        "role": "administrator / lore-guide of the 'ケートゥス (Cetus)' troop-production facility",
        "register": "archaic, courteous, unflappable elder; calm exposition (〜ですな / ほほ / おりませぬ); addresses Einaike as 貴女.",
        "note": "named for Charon the ferryman; the prison-facility caretaker.",
    },
    "ヴィネ": {
        "en": "Vine", "gender": "male",
        "role": "the '氷爆将 / Ice-Blast General', one of the Three Generals (三鼎将)",
        "register": "crude, rough, blunt soldier; coarse slang (ッカァー / 〜だぞ / ねぇ / ボコボコ); irreverent.",
        "note": "Ars Goetia demon Vine/Vinea.",
    },
    "モレク": {
        "en": "Moloch", "gender": "male",
        "role": "the '雷穏将 / Thunder-Calm General', one of the Three Generals (三鼎将)",
        "register": "formal, measured military aide / strategist (おります / 〜かと / ですな); reports and analyses calmly.",
        "note": "Ars Goetia demon Moloch/Molech.",
    },
    "魔王": {
        "en": "Demon Lord", "gender": "male",
        "role": "the reigning Demon Lord (currently 赤冠王マクドネル / Red-Crown King McDonnell)",
        "register": "regal, archaic, grave (汝/なれ, 〜がよい); speaks of the Dark God and of Einaike's fate.",
        "note": "generic name-box label 魔王; the current holder is McDonnell.",
    },
    "赤冠王マクドネル": {
        "en": "Red-Crown King McDonnell", "gender": "male",
        "role": "the current Demon Lord ('赤冠王 / Red-Crown King')",
        "register": "regal, terse, grave (……うむ); commands the demon armies.",
        "note": "has a retainer, Marchosias (マルコシアス).",
    },
    "マルコシアス": {
        "en": "Marchosias", "gender": "male",
        "role": "retainer of the Demon Lord McDonnell",
        "register": "deferential to the king, sharp toward others.",
        "note": "Ars Goetia demon Marchosias.",
    },
    '"蒼"の魔王、リバイアサン': {
        "en": "Leviathan, the Azure Demon Lord", "gender": "unknown",
        "role": "primordial eldritch entity — the true nature/origin of all demon-kin (魔族); sent by the Dark God",
        "register": "grand, ancient, eerie; plural self (我/我ら, '無数にして一つ'); ceremonial archaic speech.",
        "note": "'蒼 (Azure)' Demon Lord; speaks of 創世神ヴェンディア (creator goddess Vendia) and the Dark God '\"ニンゲン\"/Human'.",
    },
    "囚人": {
        "en": "Prisoner", "gender": "unknown",
        "role": "captives sent into the breeding facility (both male and female variants speak)",
        "register": "vulgar, jeering, cruel; mocks the heroine's predicament ('クヒヒッ', 'ウフフッ', テメェ/アンタ).",
        "note": "gender varies per scene — infer from the surrounding speech.",
    },
    '英雄・"勇者"': {
        "en": 'Hero - "the Valiant"', "gender": "male",
        "role": "leader of the human Heroes (英雄), champion of the natives (原住民)",
        "register": "noble, resolute commander (我ら, 〜のだ); fights to protect the creator goddess's world.",
        "note": "英雄 = 'Hero' (a special elite born among the natives); 勇者 = 'the Valiant / Brave'.",
    },
    '英雄・"魔女"': {
        "en": 'Hero - "the Witch"', "gender": "female",
        "role": "one of the human Heroes; strategist/spellcaster",
        "register": "composed, analytical, polite (ですね / ますよ).",
        "note": "",
    },
    '英雄・"賢者"': {"en": 'Hero - "the Sage"', "gender": "unknown", "role": "one of the human Heroes", "register": "", "note": ""},
    '英雄・"戦士"': {"en": 'Hero - "the Warrior"', "gender": "unknown", "role": "one of the human Heroes", "register": "", "note": ""},
    '英雄・"武人"': {"en": 'Hero - "the Champion"', "gender": "unknown", "role": "one of the human Heroes", "register": "", "note": ""},
    "サキュバス": {
        "en": "Succubus", "gender": "female",
        "role": "generic succubus name-box (the violated/bred females, sometimes Einaike herself in H-scenes)",
        "register": "in H-scenes: explicit, desperate, broken, ahegao; non-consensual register — do not soften.",
        "note": "the species; also a generic dialogue label.",
    },
    "？？？": {"en": "???", "gender": "unknown", "role": "concealed/unknown speaker", "register": "", "note": "mystery name-box label"},
}

# Recurring terms for consistency. Injected per-chunk only when the JP appears,
# so the list can be generous without bloating prompts. Covers the breeding/war
# setting, the demon races, titles, and the gritty/erotic vocabulary.
SEED_TERMS = {
    # --- setting / factions ---
    "兵力増産所": "Troop Production Facility",
    "ケートゥス": "Cetus",
    "魔族": "demon-kin",
    "魔王": "Demon Lord",
    "邪神": "Dark God",
    "創世神": "Creator Goddess",
    "ヴェンディア": "Vendia",
    "原住民": "natives",
    "英雄": "Hero",
    "勇者": "the Valiant",
    "魔女": "the Witch",
    "賢者": "the Sage",
    "魔導師": "the Magus",
    "サキュバス": "succubus",
    # --- titles / ranks ---
    "三鼎将": "the Three Generals",
    "四方鼎将": "the Four Generals",
    "鼎将": "Cauldron General",
    "紫焔将": "Purple-Flame General",
    "雷穏将": "Thunder-Calm General",
    "氷爆将": "Ice-Blast General",
    "凶角卿": "Vicious-Horn Lord",
    "赤冠王": "Red-Crown King",
    "紫焔軍": "the Purple-Flame Army",
    # --- breeding / core loop ---
    "種付け": "breeding",
    "種付": "breeding",
    "種付け値": "breeding value",
    "種付値": "breeding value",
    "種付品質": "breeding quality",
    "種馬": "stud",
    "出産": "birth",
    "繁殖": "breeding",
    "孕み": "conception",
    "兵力増産": "troop production",
    "ユニット": "unit",
    "誠心誠意度": "Devotion",
    "褒章": "decoration",
    "邪神の細胞片": "Dark God cell fragment",
    # --- demon races (基底 base / 飛行 flying / 獣 beast / 不定形 amorphous) ---
    "基底魔族": "Base demon-kin",
    "飛行魔族": "Flying demon-kin",
    "獣魔族": "Beast demon-kin",
    "不定形魔族": "Amorphous demon-kin",
    "ゴブリン": "Goblin",
    "コボルド": "Kobold",
    "リザードマン": "Lizardman",
    "トロール": "Troll",
    "ミノタウロス": "Minotaur",
    "ハルピュイア": "Harpy",
    "コカトリス": "Cockatrice",
    "ヤマチチ": "Yamachichi",
    "セイレーン": "Siren",
    "バジリスク": "Basilisk",
    "セワッジラット": "Sewage Rat",
    "ドレッドウルフ": "Dread Wolf",
    "スレイプニル": "Sleipnir",
    "スライム": "Slime",
    "イールワーム": "Eel Worm",
    "ゼリーフレシュ": "Jelly Flesh",
    "ヘドロスラッグ": "Sludge Slug",
    "ヒュドラ": "Hydra",
}


# Targeted MZ plugin-command (code 357) text extraction. Maps a plugin name to
# the arg keys (in parameters[3]) that hold PLAYER-FACING text. Anything not
# listed here is left untouched (most 357 args are config: filenames, ids, camera
# targets). This game's prologue narration + status/UI labels live in
# triacontane/DTextPicture's `text` arg. Extend per-plugin if a new game needs it.
PLUGIN_357_TEXT = {
    "triacontane/DTextPicture": ["text"],
    "triacontane/TextPicture": ["text"],
}


def _seed_tl(content, seed_map, src_codes):
    """A pre-known EN for a label/script string, masked to match the source's
    control codes so placeholder integrity holds. '' if unknown or the codes don't
    line up (then the batch translates it normally, like any other game)."""
    en = seed_map.get(content)
    if not en:
        return ""
    masked_en, en_codes = codes.mask_codes(en)
    return masked_en if en_codes == src_codes else ""


def _seed_vartext(content, glossary, src_codes):
    """A code-122 literal that is exactly a known character name or glossary term
    is pre-filled from the glossary (keeps names consistent, shrinks the batch).
    Whole sentences fall through to '' and translate normally."""
    en = store.name_lookup(glossary, content)
    if not en or en == content:
        en = (glossary.get("terms") or {}).get(content, "")
    if not en or en == content:
        return ""
    masked_en, en_codes = codes.mask_codes(en)
    return masked_en if en_codes == src_codes else ""


def _extract_note_tags(data, stem, cfg, units):
    """Auto-extract DISPLAYED note tags (<LB:..> map labels, <desc1/2/3:..> enemy
    book) as 'label' units, from a Map's events OR a flat database list. Only the
    tag CONTENT is translated; internal tags (<TE:..> etc.) are never touched."""
    if not cfg.note_labels:
        return
    if isinstance(data, dict):                        # Map: events[].note
        items = [(["events", e, "note"], "e", ev.get("id", e), ev)
                 for e, ev in enumerate(data.get("events", []) or [])
                 if ev and isinstance(ev, dict) and isinstance(ev.get("note"), str)]
        where = "map label"
    elif isinstance(data, list):                      # database file: entries[].note
        items = [([i, "note"], "n", (en.get("id", i)), en)
                 for i, en in enumerate(data)
                 if en and isinstance(en, dict) and isinstance(en.get("note"), str)]
        where = "enemy book" if stem == "Enemies" else "note"
    else:
        return
    for ptr, pfx, oid, obj in items:
        name = obj.get("name") or f"#{oid}"
        note = obj.get("note", "")
        for idx, (tag, content) in enumerate(patterns.iter_note_tags(note)):
            if not codes.has_jp(content):
                continue
            masked, code_map = codes.mask_codes(content)
            units.append({
                "id": f"{stem}:{pfx}{oid}:note{idx}",
                "kind": "label", "tag": tag,
                "ptr": list(ptr),
                "ctx": _ctx(name, where),
                "codes": code_map, "src": masked, "raw": content,
                "tl": _seed_tl(content, patterns.SEED_NOTE_LABELS, code_map),
            })
        # bare <LB> (map events only): EventLabel shows the event NAME -> translate it
        if pfx == "e" and patterns.BARE_LB_RE.search(note) and codes.has_jp(obj.get("name", "")):
            masked, code_map = codes.mask_codes(obj["name"])
            units.append({
                "id": f"{stem}:{pfx}{oid}:lbname",
                "kind": "label", "tag": "LB", "lb_kind": "name",
                "ptr": list(ptr[:-1]) + ["name"],
                "ctx": _ctx(obj["name"], "map label (name)"),
                "codes": code_map, "src": masked, "raw": obj["name"],
                "tl": _seed_tl(obj["name"], patterns.SEED_NAME_LABELS, code_map),
            })


def _seed_name(glossary, name):
    """Add/upgrade a character name to a rich entry (without clobbering data)."""
    cur = glossary["names"].get(name)
    if cur is None or cur == "":
        glossary["names"][name] = {"en": "", "gender": "", "role": "", "register": "", "note": ""}


# --------------------------------------------------------------------------
def _load(path):
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def _ctx(*parts):
    return " / ".join(str(p) for p in parts if p)


# --------------------------------------------------------------------------
# event command lists (Maps, CommonEvents, Troops)
# --------------------------------------------------------------------------
def _iter_command_lists(data, stem):
    """Yield (ptr_to_list, list_obj, context_label, id_prefix)."""
    if stem == "CommonEvents":
        for i, ev in enumerate(data):
            if not ev or "list" not in ev:
                continue
            yield [i, "list"], ev["list"], _ctx(ev.get("name")), f"CE:{i}"
    elif stem == "Troops":
        for t, tr in enumerate(data):
            if not tr:
                continue
            for p, page in enumerate(tr.get("pages", []) or []):
                if page and "list" in page:
                    yield ([t, "pages", p, "list"], page["list"],
                           _ctx(tr.get("name")), f"TR:{t}:{p}")
    elif stem.startswith("Map") and stem != "MapInfos":
        for e, ev in enumerate(data.get("events", []) or []):
            if not ev:
                continue
            for p, page in enumerate(ev.get("pages", []) or []):
                if page and "list" in page:
                    yield (["events", e, "pages", p, "list"], page["list"],
                           _ctx(ev.get("name") or f"event {ev.get('id', e)}"),
                           f"{stem}:e{ev.get('id', e)}:p{p}")


def _extract_commands(ptr, lst, ctx, idp, cfg, glossary, units):
    """Scan one command list for text blocks (401/405) and choices (102)."""
    last_speaker = ""
    native_speaker = ""      # MZ: parameters[4] of the most recent Show-Text (101)
    i = 0
    n = len(lst)
    while i < n:
        cmd = lst[i]
        code = cmd.get("code") if isinstance(cmd, dict) else None

        # ---- MZ native name box (Show Text header, code 101) -------------------
        # In RPG Maker MZ the speaker name is stored as parameters[4] of the 101
        # command that introduces a 401 text block (NOT inside the 401 text). Track
        # it and seed it into the glossary so it is translated once and injected
        # back into the 101 command consistently with in-prose mentions. An empty
        # parameters[4] means "no name box", which clears the carried speaker.
        if code == 101:
            p = cmd.get("parameters") or []
            native_speaker = p[4].strip() if (len(p) >= 5 and isinstance(p[4], str)) else ""
            if native_speaker:
                _seed_name(glossary, native_speaker)
            i += 1
            continue

        # ---- text / scrolling-text blocks ----
        is_text = (code == C_TEXT and cfg.code_text) or (code == C_SCROLL and cfg.code_scroll)
        if is_text:
            run_code = code
            start = i
            lines = []
            while i < n and isinstance(lst[i], dict) and lst[i].get("code") == run_code:
                params = lst[i].get("parameters") or [""]
                lines.append(params[0] if params else "")
                i += 1
            count = i - start
            raw = "\n".join(lines)

            speaker, prefix, body = codes.parse_speaker(raw)
            # MZ name-box speaker (parameters[4]) when the 401 text carries no inline
            # \kw[]/\nw[]/【】 speaker. prefix stays "" — inject rewrites the 101
            # command's parameters[4] separately, so the name is never embedded here.
            if not speaker and run_code == C_TEXT and native_speaker:
                speaker = native_speaker
            if speaker:
                last_speaker = speaker
            ctx_speaker = speaker or (last_speaker if cfg.carry_speaker else "")

            body = codes.clean_source(body).replace("\n", " ").strip()
            if codes.has_jp(body):
                masked, code_map = codes.mask_codes(body)
                if speaker:
                    _seed_name(glossary, speaker)
                units.append({
                    "id": f"{idp}:c{start}",
                    "kind": "text",
                    "ptr": ptr,
                    "block": {"start": start, "count": count, "code": run_code},
                    "speaker": speaker,
                    "ctx_speaker": ctx_speaker,
                    "ctx": ctx,
                    "prefix": prefix,
                    "codes": code_map,
                    "src": masked,
                    "raw": raw,
                    "tl": "",
                })
            continue  # i already advanced past the block

        # ---- choices ----
        if code == C_CHOICE and cfg.code_choices:
            params = cmd.get("parameters") or []
            if params and isinstance(params[0], list):
                for k, choice in enumerate(params[0]):
                    if not isinstance(choice, str) or not codes.has_jp(choice):
                        continue
                    masked, code_map = codes.mask_codes(codes.clean_source(choice))
                    units.append({
                        "id": f"{idp}:c{i}:ch{k}",
                        "kind": "choice",
                        "ptr": ptr + [i, "parameters", 0, k],
                        "ctx": _ctx(ctx, "choice"),
                        "codes": code_map,
                        "src": masked,
                        "raw": choice,
                        "tl": "",
                    })

        # ---- targeted MZ plugin-command text (code 357) ----------------------
        # MZ plugin commands store args in parameters[3] (a dict). Only the args
        # named in PLUGIN_357_TEXT for that plugin are player-facing (e.g.
        # DTextPicture's `text` — the prologue narration + status/UI labels). The
        # editor-mirror (657) lines are ignored by the engine, so we never touch
        # them. Newlines are PRESERVED (picture text is laid out by hand).
        if code == 357 and cfg.code_357:
            params = cmd.get("parameters") or []
            plugin = params[0] if params else ""
            argkeys = PLUGIN_357_TEXT.get(plugin)
            if argkeys and len(params) >= 4 and isinstance(params[3], dict):
                for ak in argkeys:
                    val = params[3].get(ak)
                    if isinstance(val, str) and codes.has_jp(val):
                        masked, code_map = codes.mask_codes(codes.clean_source(val))
                        units.append({
                            "id": f"{idp}:c{i}:357:{ak}",
                            "kind": "ptext",
                            "ptr": ptr + [i, "parameters", 3, ak],
                            "ctx": _ctx(ctx, plugin.split("/")[-1]),
                            "codes": code_map,
                            "src": masked,
                            "raw": val,
                            "tl": "",
                        })

        # ---- safe code-355/655 script DISPLAY text (addText('...'), …) -------
        # Only the captured display string is taken; the surrounding script (logic,
        # the ~hundreds of dev comments) is never touched.
        if code in (355, 655) and cfg.code_355_text:
            params = cmd.get("parameters") or []
            line = params[0] if params else ""
            if isinstance(line, str):
                for s, content in enumerate(patterns.iter_script_text(line)):
                    if codes.has_jp(content):
                        masked, code_map = codes.mask_codes(content)
                        units.append({
                            "id": f"{idp}:c{i}:script{s}",
                            "kind": "scripttext",
                            "ptr": ptr + [i, "parameters", 0],
                            "ctx": _ctx(ctx, "battle/script text"),
                            "codes": code_map,
                            "src": masked,
                            "raw": content,
                            "tl": _seed_tl(content, patterns.SEED_SCRIPT_TEXT, code_map),
                        })

        # ---- code-122 control-variable DISPLAY strings (set var = '…' shown via
        # \V[n]). Only variables actually \V-referenced somewhere are taken — that
        # excludes CG filenames / expression keys (e.g. 通常) which are never shown.
        if code == 122 and getattr(cfg, "code_122_display", False) and patterns.is_var_string_cmd(cmd):
            ps = cmd.get("parameters")
            dvars = getattr(cfg, "_displayed_vars", set())
            if any(v in dvars for v in range(ps[0], ps[1] + 1)):
                for s, lit in enumerate(patterns.iter_var_literals(ps[4])):
                    if codes.has_jp(lit):
                        masked, code_map = codes.mask_codes(lit)
                        units.append({
                            "id": f"{idp}:c{i}:var{s}",
                            "kind": "vartext",
                            "ptr": ptr + [i, "parameters", 4],
                            "ctx": _ctx(ctx, "variable display text"),
                            "codes": code_map,
                            "src": masked,
                            "raw": lit,
                            "tl": _seed_vartext(lit, glossary, code_map),
                        })
        i += 1


# --------------------------------------------------------------------------
# scalar string field helper
# --------------------------------------------------------------------------
def _scalar_unit(units, ptr, value, kind, ctx, uid, collapse_nl=False):
    if not isinstance(value, str) or not codes.has_jp(value):
        return
    src = codes.clean_source(value)
    if collapse_nl:
        src = src.replace("\n", " ")
    masked, code_map = codes.mask_codes(src)
    units.append({
        "id": uid, "kind": kind, "ptr": ptr, "ctx": ctx,
        "codes": code_map, "src": masked, "raw": value, "tl": "",
    })


# --------------------------------------------------------------------------
# data files (names / descriptions / messages)
# --------------------------------------------------------------------------
def _extract_database(data, stem, cfg, glossary, units):
    if stem == "Actors":
        if not cfg.actor_names:
            return
        for i, e in enumerate(data):
            if not e:
                continue
            if codes.has_jp(e.get("name", "")):
                _seed_name(glossary, e["name"])  # actor name -> glossary
            _scalar_unit(units, [i, "nickname"], e.get("nickname", ""), "nickname",
                         _ctx("actor", e.get("name")), f"Actors:{i}:nickname")
            _scalar_unit(units, [i, "profile"], e.get("profile", ""), "profile",
                         _ctx("actor", e.get("name")), f"Actors:{i}:profile", collapse_nl=True)
        return

    if stem in ("Items", "Weapons", "Armors"):
        if not cfg.names:
            return
        for i, e in enumerate(data):
            if not e:
                continue
            _scalar_unit(units, [i, "name"], e.get("name", ""), "name",
                         _ctx(stem[:-1], "name"), f"{stem}:{i}:name")
            _scalar_unit(units, [i, "description"], e.get("description", ""), "desc",
                         _ctx(stem[:-1], "description"), f"{stem}:{i}:desc", collapse_nl=True)
        return

    if stem == "Skills":
        if not cfg.names:
            return
        for i, e in enumerate(data):
            if not e:
                continue
            _scalar_unit(units, [i, "name"], e.get("name", ""), "name",
                         "skill name", f"Skills:{i}:name")
            _scalar_unit(units, [i, "description"], e.get("description", ""), "desc",
                         "skill description", f"Skills:{i}:desc", collapse_nl=True)
            for m in (1, 2):
                _scalar_unit(units, [i, f"message{m}"], e.get(f"message{m}", ""), "message",
                             "skill use message (action log)", f"Skills:{i}:msg{m}", collapse_nl=True)
        return

    if stem in ("Enemies", "Classes"):
        if not cfg.names:
            return
        for i, e in enumerate(data):
            if not e:
                continue
            _scalar_unit(units, [i, "name"], e.get("name", ""), "name",
                         f"{stem[:-1].lower()} name", f"{stem}:{i}:name")
        return

    if stem == "States":
        if not cfg.names:
            return
        for i, e in enumerate(data):
            if not e:
                continue
            _scalar_unit(units, [i, "name"], e.get("name", ""), "name",
                         "state name", f"States:{i}:name")
            for m in (1, 2, 3, 4):
                _scalar_unit(units, [i, f"message{m}"], e.get(f"message{m}", ""), "message",
                             "state message (action log)", f"States:{i}:msg{m}", collapse_nl=True)
        return

    if stem == "MapInfos":
        if not cfg.map_names:
            return
        for i, e in enumerate(data):
            if not e:
                continue
            _scalar_unit(units, [i, "name"], e.get("name", ""), "mapname",
                         "map / location name", f"MapInfos:{i}:name")
        return


def _extract_system(data, cfg, units):
    if not cfg.system:
        return
    _scalar_unit(units, ["gameTitle"], data.get("gameTitle", ""), "title",
                 "game window title bar", "System:gameTitle")
    _scalar_unit(units, ["currencyUnit"], data.get("currencyUnit", ""), "currency",
                 "in-game currency unit", "System:currencyUnit")

    terms = data.get("terms", {})
    for key in ("basic", "commands", "params"):
        arr = terms.get(key, []) or []
        for k, v in enumerate(arr):
            _scalar_unit(units, ["terms", key, k], v, "term",
                         f"UI label ({key})", f"System:terms.{key}:{k}")
    for mkey, v in (terms.get("messages", {}) or {}).items():
        _scalar_unit(units, ["terms", "messages", mkey], v, "term",
                     "battle/system message", f"System:terms.messages.{mkey}", collapse_nl=True)

    for key in ("armorTypes", "weaponTypes", "skillTypes", "equipTypes", "elements"):
        arr = data.get(key, []) or []
        for k, v in enumerate(arr):
            _scalar_unit(units, [key, k], v, "term",
                         key.replace("Types", " type"), f"System:{key}:{k}")

    if cfg.system_switches:
        for k, v in enumerate(data.get("switches", []) or []):
            _scalar_unit(units, ["switches", k], v, "term", "switch name", f"System:switch:{k}")
    if cfg.system_variables:
        for k, v in enumerate(data.get("variables", []) or []):
            _scalar_unit(units, ["variables", k], v, "term", "variable name", f"System:var:{k}")


def _extract_map_extras(data, stem, cfg, units):
    if not cfg.map_names:
        return
    _scalar_unit(units, ["displayName"], data.get("displayName", ""), "mapname",
                 "map display name", f"{stem}:displayName")


# --------------------------------------------------------------------------
# top-level
# --------------------------------------------------------------------------
SKIP_FILES = {"Animations", "Tilesets", "ContainerProperties", "MapInfos"}  # MapInfos handled in db


def _jp_ratio(data_dir):
    """Fraction of representative player-text fields that still contain Japanese.
    A normal source game is ~1.0; an already-TRANSLATED data dir is near 0."""
    jp = total = 0
    for base in ("Items.json", "Skills.json", "Weapons.json", "Armors.json",
                 "Enemies.json", "States.json"):
        p = os.path.join(data_dir, base)
        if not os.path.exists(p):
            continue
        try:
            arr = _load(p)
        except Exception:
            continue
        for e in (arr or []):
            if not isinstance(e, dict):
                continue
            for f in ("name", "description"):
                s = e.get(f)
                if isinstance(s, str) and s.strip():
                    total += 1
                    if codes.has_jp(s):
                        jp += 1
    return (jp / total) if total else 1.0


def extract_store(data_dir, store_dir, cfg: Config, only=None, force=False):
    """Build the store from data_dir. `only` = optional list of file basenames.

    Guard: extracting from an already-TRANSLATED data dir (e.g. the live game's
    `data/` after inject) silently destroys the store — English text has no JP so
    most units vanish, and merge can't tell. If the dir looks translated, refuse
    and point at the original; pass force=True to override deliberately."""
    if not force:
        ratio = _jp_ratio(data_dir)
        if ratio < 0.30:
            raise SystemExit(
                f"refusing to extract: {data_dir} looks ALREADY TRANSLATED "
                f"(only {ratio:.0%} of item/skill fields contain Japanese).\n"
                f"Extracting English data would wipe the store. Point --data at the "
                f"ORIGINAL Japanese data (e.g. a *_backup_* dir), or pass --force if "
                f"this really is untranslated source.")
    glossary = store.load_glossary(store_dir)
    os.makedirs(store_dir, exist_ok=True)

    # which variables get shown via \V[n] — gates code-122 display-string extraction
    if getattr(cfg, "code_122_display", False):
        cfg._displayed_vars = _collect_displayed_vars(data_dir)

    files = sorted(glob.glob(os.path.join(data_dir, "*.json")))
    summary = []
    # Preserve existing translations: map id -> tl from any current store doc.
    prev_tl = {}
    for _p, doc in store.load_docs(store_dir):
        for u in doc.get("units", []):
            if u.get("tl"):
                prev_tl[u["id"]] = u["tl"]

    for path in files:
        base = os.path.basename(path)
        stem = os.path.splitext(base)[0]
        if only and base not in only:
            continue
        if stem == "Animations" or stem == "Tilesets" or stem == "ContainerProperties":
            continue
        data = _load(path)
        units = []

        if stem in ("CommonEvents", "Troops") or (stem.startswith("Map") and stem != "MapInfos"):
            for ptr, lst, ctx, idp in _iter_command_lists(data, stem):
                _extract_commands(ptr, lst, ctx, idp, cfg, glossary, units)
            if stem.startswith("Map"):
                _extract_map_extras(data, stem, cfg, units)
                _extract_note_tags(data, stem, cfg, units)
        elif stem == "System":
            _extract_system(data, cfg, units)
        else:
            _extract_database(data, stem, cfg, glossary, units)
            _extract_note_tags(data, stem, cfg, units)   # <desc1/2/3:..> enemy book etc.

        if not units:
            continue
        # Re-apply previously fetched translations by id.
        for u in units:
            if u["id"] in prev_tl:
                u["tl"] = prev_tl[u["id"]]
        store.save_doc(store_dir, base, units,
                       meta={"engine": cfg.engine, "game_jp": cfg.game_jp, "game_en": cfg.game_en})
        summary.append((base, len(units)))

    # Fill presets for known characters (only empty fields — never clobber edits).
    for jp, meta in SEED_CHARACTER_META.items():
        entry = glossary["names"].get(jp)
        if isinstance(entry, dict):
            for k, v in meta.items():
                if not entry.get(k):
                    entry[k] = v
    # Seed recurring terms (don't overwrite existing).
    for jp, en in SEED_TERMS.items():
        glossary.setdefault("terms", {}).setdefault(jp, en)

    store.save_glossary(store_dir, glossary)
    return summary, glossary
