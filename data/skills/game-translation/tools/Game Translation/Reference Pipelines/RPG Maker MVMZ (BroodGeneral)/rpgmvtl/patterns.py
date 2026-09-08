#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patterns.py — the "special" player-facing string types beyond plain dialogue,
so the pipeline EXTRACTS them automatically (future games need no manual hunting):

  * Event-note display tags  <LB:text>  (triacontane/EventLabel floating labels)
  * Script-line display text  BattleManager._logWindow.addText('text')  (code 355/655)

extract.py turns these into normal translatable units (kinds "label" / "scripttext");
inject.py builds a JP->EN map from the translated units and rewrites them in place
(notes for labels, with JS-string escaping for script text). The SEED_* maps below
are this game's known translations — they pre-fill the store so no re-translation is
needed; for a different game they simply don't match and the units translate normally.

To support a new note tag or script pattern, extend NOTE_DISPLAY_TAGS /
SCRIPT_TEXT_PATTERNS — nothing else changes.
"""
import re

# --- which event/data note tags are DISPLAYED (translate their content) ------
# These are scanned in BOTH map-event notes AND database notes (enemies/items/…).
#   LB            triacontane/EventLabel  — floating map labels
#   desc1..desc6  ABMZ/ABMZ_EnemyBook     — enemy-book stat/resist description rows
#                                           (this game uses 1-3; plugin allows up to 6)
# NOT listed (internal, never translated): TE (TemplateEvent), LB_Y (label
# offset), and any tag a plugin reads as data rather than rendering as text.
NOTE_DISPLAY_TAGS = ["LB"] + ["desc%d" % i for i in range(1, 7)]

# --- safe code-355/655 script patterns whose capture group is display text --
# (compiled_regex_with_quote_group_then_text_group). Only the captured string is
# touched; surrounding script logic / comments are left exactly as-is.
ADDTEXT_RE = re.compile(r"(addText\(\s*)(['\"])((?:\\.|(?!\2).)*)(\2\s*\))")
# .push('…') display strings — the recollection-unlock grid (kaisou.push) and the
# CG thumbnail list (TitleList.push) build display arrays this way. Match only the
# literal (the closing quote, NOT the paren) so `push('【Goblin:' + v + '】')` works.
PUSH_RE = re.compile(r"(push\(\s*)(['\"])((?:\\.|(?!\2).)*)(\2)")
SCRIPT_TEXT_PATTERNS = [ADDTEXT_RE, PUSH_RE]

# A BARE <LB> tag (no ":value") makes EventLabel display the event NAME instead of
# explicit text. We translate the name and rewrite the bare tag to <LB:translated>
# so the floating label shows English WITHOUT touching the name field or the
# <TE:..> template-reference (which reuses that JP name as its lookup key).
BARE_LB_RE = re.compile(r"<LB>")


def iter_note_tags(note):
    """Yield (tag, content) for every <TAG:content> in a DISPLAYED tag."""
    if not isinstance(note, str) or "<" not in note:
        return
    for tag in NOTE_DISPLAY_TAGS:
        for m in re.finditer(r"<%s:([^>]*)>" % re.escape(tag), note):
            yield tag, m.group(1)


def iter_script_text(line):
    """Yield the display-text content of each safe pattern match in a script line."""
    if not isinstance(line, str):
        return
    for rx in SCRIPT_TEXT_PATTERNS:
        for m in rx.finditer(line):
            yield m.group(3)


def iter_note_bearers(data):
    """Yield every object that owns a `note` string — works for a Map document
    (events[].note) and a flat DATABASE list (Enemies/Items/… entries[].note)."""
    if isinstance(data, dict):                        # Map
        for ev in data.get("events", []) or []:
            if ev and isinstance(ev, dict) and isinstance(ev.get("note"), str):
                yield ev
    elif isinstance(data, list):                      # database file
        for e in data:
            if e and isinstance(e, dict) and isinstance(e.get("note"), str):
                yield e


def apply_note_labels(data, label_map):
    """Rewrite <TAG:jp> -> <TAG:en> in every note of a Map OR a database file."""
    if not label_map:
        return 0
    n = 0
    for obj in iter_note_bearers(data):
        note = obj["note"]
        if "<" not in note:
            continue
        new = note
        for tag in NOTE_DISPLAY_TAGS:
            for jp, en in label_map.items():
                t = "<%s:%s>" % (tag, jp)
                if t in new:
                    new = new.replace(t, "<%s:%s>" % (tag, en)); n += 1
        if new != note:
            obj["note"] = new
    return n


def apply_name_labels(data, name_map):
    """For events whose note has a BARE <LB> (floating label = event NAME), rewrite
    the bare tag to <LB:translated-name> via name_map. The name field and <TE:..>
    template reference are left untouched."""
    if not name_map:
        return 0
    n = 0
    for obj in iter_note_bearers(data):
        note = obj.get("note", "")
        if not BARE_LB_RE.search(note):
            continue
        en = name_map.get(obj.get("name", ""))
        if en:
            obj["note"] = BARE_LB_RE.sub("<LB:%s>" % en, note, count=1)
            n += 1
    return n


def _command_lists(data):
    """Every command list in a Map / CommonEvents / Troops document."""
    if isinstance(data, dict):                       # Map
        for ev in data.get("events", []) or []:
            if ev and isinstance(ev, dict):
                for pg in ev.get("pages", []) or []:
                    if pg and "list" in pg:
                        yield pg["list"]
    elif isinstance(data, list):                     # CommonEvents / Troops
        for e in data:
            if e and isinstance(e, dict):
                if "list" in e:
                    yield e["list"]
                for pg in (e.get("pages") or []):
                    if pg and "list" in pg:
                        yield pg["list"]


# code-122 (Control Variables, operand 4 = script) holds a JS expression. When the
# variable is shown via \V[n] it is DISPLAY text; we translate the quoted string
# LITERALS inside the expression and leave concatenation / $gameVariables logic
# intact. Same JS-string escaping as addText.
VAR_LITERAL_RE = re.compile(r"(['\"])((?:\\.|(?!\1).)*)\1")


def is_var_string_cmd(c):
    """True for a code-122 'set variable = <script string>' command."""
    if not (isinstance(c, dict) and c.get("code") == 122):
        return False
    ps = c.get("parameters")
    return bool(ps and len(ps) >= 5 and ps[2] == 0 and ps[3] == 4 and isinstance(ps[4], str))


def iter_var_literals(value):
    """Yield each quoted string literal's content in a code-122 script value."""
    if isinstance(value, str):
        for m in VAR_LITERAL_RE.finditer(value):
            yield m.group(2)


def apply_var_text(data, var_map, skip_vars=()):
    """Rewrite quoted literals inside code-122 variable-string assignments from
    var_map (only literals present in the map change), JS-escaped. Assignments to a
    variable in skip_vars are left untouched — those vars hold asset keys (e.g. 立ち絵
    bust-name slots) whose literal must stay Japanese even when the same string is
    translated as display text elsewhere (apply is global-by-string)."""
    if not var_map:
        return 0
    skip_vars = set(skip_vars or ())
    total = 0
    for lst in _command_lists(data):
        if not isinstance(lst, list):
            continue
        for c in lst:
            if not is_var_string_cmd(c):
                continue
            ps = c["parameters"]
            if ps[0] in skip_vars:                   # asset-key var — never translate
                continue

            def repl(m):
                q, inner = m.group(1), m.group(2)
                if inner in var_map:
                    en = var_map[inner].replace("\\", "\\\\").replace(q, "\\" + q)
                    return q + en + q
                return m.group(0)

            new = VAR_LITERAL_RE.sub(repl, ps[4])
            if new != ps[4]:
                c["parameters"] = list(ps)
                c["parameters"][4] = new
                total += 1
    return total


def apply_script_text(data, script_map):
    """Rewrite display strings inside code-355/655 script lines from script_map,
    re-escaping for the JS string context so apostrophes can't break it."""
    if not script_map:
        return 0
    total = 0
    for lst in _command_lists(data):
        if not isinstance(lst, list):
            continue
        for c in lst:
            if not (isinstance(c, dict) and c.get("code") in (355, 655)):
                continue
            ps = c.get("parameters")
            if not (ps and isinstance(ps[0], str)):
                continue
            line = ps[0]
            new = line
            for rx in SCRIPT_TEXT_PATTERNS:
                def repl(m):
                    q, inner = m.group(2), m.group(3)
                    if inner in script_map:
                        en = script_map[inner].replace("\\", "\\\\").replace(q, "\\" + q)
                        return m.group(1) + q + en + m.group(4)
                    return m.group(0)
                new = rx.sub(repl, new)
            if new != line:
                c["parameters"] = list(ps)
                c["parameters"][0] = new
                total += 1
    return total


# --- this game's known translations (seed the store; harmless for other games) ---
_LB_RACES = {
    "ミノタウロス": "Minotaur", "トロール": "Troll", "リザードマン": "Lizardman",
    "コボルド": "Kobold", "ゴブリン": "Goblin", "ハルピュイア": "Harpy",
    "コカトリス": "Cockatrice", "ヤマチチ": "Yamachichi", "セイレーン": "Siren",
    "バジリスク": "Basilisk", "セワッジラット": "Sewage Rat", "ドレッドウルフ": "Dread Wolf",
    "ダンバブン": "Danbabun", "スレイプニル": "Sleipnir", "ウガルルム": "Ugarurum",
    "スライム": "Slime", "イールワーム": "Eel Worm", "ゼリーフレシュ": "Jelly Flesh",
    "ヘドロスラッグ": "Sludge Slug", "ヒュドラ": "Hydra",
}
SEED_EVENT_LABELS = {
    "セーブ": "Save", "イベントムービー": "Event Movie", "ヘルプ": "Help",  # noqa: E501
    "階層移動": "Change Floor", "[奉仕する]": "[Serve]",
    "LV\\V[53]強化個体": "LV\\V[53] Enhanced Unit",
    "衰弱個体LV\\V[53]": "Weakened Unit LV\\V[53]",
    "\\C[27][フォルファクス]\\C[0]": "\\C[27][Furfur]\\C[0]",
    "[フォルファクス]": "[Furfur]",
    "戦闘テスト": "Battle Test", "本編へスキップ": "Skip to Main Story",
    "チートON": "Cheat ON", "魔王城へ": "To the Demon Lord's Castle",
    "シーンスキップ": "Scene Skip", "編成隊列保存室": "Formation Save Room",
    "壁に記された赤い線": "Red Lines on the Wall",
    "\\C[27]設定資料\\C[0]": "\\C[27]Setting Materials\\C[0]",
    "回想解放確認": "Recollection Unlock",
    "体験版終了": "End of Trial", "ケートゥスの、その先へ": "Beyond Cetus",
    "果てなき回廊": "Endless Corridor", "ケートゥスへ": "To Cetus",
    "姿を変える": "Change Form", "立ち姿を思い浮かべる": "Recall Standing Pose",
}
for _jp, _en in _LB_RACES.items():
    SEED_EVENT_LABELS["種族特性:" + _jp] = "Race Trait: " + _en

# ABMZ_EnemyBook <desc1/2/3> rows — formulaic element-resist / regen / status
# lines shown under each enemy in the bestiary (this game's full set; 元: 被ダメージN%
# = "N% dmg taken", 状態異常 = status ailments, HP再生 = HP regen, 種族 = same-element kin).
SEED_ENEMY_DESC = {
    '火水風地：被ダメージ80％': 'Fire/Water/Wind/Earth: 80% dmg taken',
    '状態異常：成功率5倍': 'Status ailments: 5x infliction rate',
    '光：被ダメージ20％　火水風地：被ダメージ80％': 'Light: 20% dmg taken  Fire/Water/Wind/Earth: 80% dmg taken',
    'HP再生率5％': 'HP regen: 5%',
    '物理・火：被ダメージ50％': 'Phys/Fire: 50% dmg taken',
    '水：被ダメージ300％': 'Water: 300% dmg taken',
    '物理：被ダメージ75％　火：被ダメージ20％': 'Phys: 75% dmg taken  Fire: 20% dmg taken',
    '水：被ダメージ500％': 'Water: 500% dmg taken',
    'HP再生率5％ 状態異常耐性[付与率75%減]': 'HP regen: 5%  Status resist [infliction -75%]',
    '物理・水：被ダメージ50％': 'Phys/Water: 50% dmg taken',
    '風：被ダメージ300％': 'Wind: 300% dmg taken',
    '物理：被ダメージ75％　水：被ダメージ20％': 'Phys: 75% dmg taken  Water: 20% dmg taken',
    '風：被ダメージ500％': 'Wind: 500% dmg taken',
    '物理・風：被ダメージ50％': 'Phys/Wind: 50% dmg taken',
    '地：被ダメージ300％': 'Earth: 300% dmg taken',
    '物理：被ダメージ75％　風：被ダメージ20％': 'Phys: 75% dmg taken  Wind: 20% dmg taken',
    '地：被ダメージ500％': 'Earth: 500% dmg taken',
    '物理・地：被ダメージ50％': 'Phys/Earth: 50% dmg taken',
    '火：被ダメージ300％': 'Fire: 300% dmg taken',
    '物理：被ダメージ75％　地：被ダメージ20％': 'Phys: 75% dmg taken  Earth: 20% dmg taken',
    '火：被ダメージ500％': 'Fire: 500% dmg taken',
    '物理火水風地：被ダメージ50％': 'Phys/Fire/Water/Wind/Earth: 50% dmg taken',
    '光：被ダメージ300％': 'Light: 300% dmg taken',
    '他属性同種に対し最大HP75％': 'Max HP 75% vs other-element kin',
    '光：被ダメージ600％ HP再生率8％': 'Light: 600% dmg taken  HP regen: 8%',
    '火水風地：被ダメージ150％': 'Fire/Water/Wind/Earth: 150% dmg taken',
    '他属性同種に比して最大HP175％': 'Max HP 175% vs other-element kin',
    '光火水風地：被ダメージ80％': 'Light/Fire/Water/Wind/Earth: 80% dmg taken',
    '物理/火：被ダメージ25％': 'Phys/Fire: 25% dmg taken',
    '物理/水：被ダメージ25％': 'Phys/Water: 25% dmg taken',
    '物理/風：被ダメージ25％': 'Phys/Wind: 25% dmg taken',
    '物理/地：被ダメージ25％': 'Phys/Earth: 25% dmg taken',
    '物理/火水風地：被ダメージ80％': 'Phys/Fire/Water/Wind/Earth: 80% dmg taken',
    '状態異常耐性・大': 'Status resist: High',
    '物理/火風：被ダメージ80％': 'Phys/Fire/Wind: 80% dmg taken',
    '物理/水風地：被ダメージ80％': 'Phys/Water/Wind/Earth: 80% dmg taken',
}

# every displayed note-tag seed, one lookup (extract.py uses this for kind="label")
SEED_NOTE_LABELS = {**SEED_EVENT_LABELS, **SEED_ENEMY_DESC}

# bare-<LB> events whose NAME is the floating label (see BARE_LB_RE): map lights +
# the per-race breeding stations (種付場). Keyed by the exact JP event name.
SEED_NAME_LABELS = {"マップ灯り": "Map Light"}
for _jp, _en in _LB_RACES.items():
    SEED_NAME_LABELS["↑" + _jp + "種付場"] = "↑" + _en + " Breeding Ground"

SEED_SCRIPT_TEXT = {
    "原住民の能力が大幅に上昇する！": "The natives' abilities rise sharply!",
    "[英雄の鼓舞]発動！": "[Hero's Inspiration] activated!",
    "味方全体の耐久力が上昇！": "All allies' endurance rises!",
    "[巨人殺しの威容]発動！": "[Giant-Slayer's Presence] activated!",
    "[縛電刃]が炸裂した！": "[Binding Lightning Blade] burst!",
    "[號旋丸]が炸裂した！": "[Howling Whirl Sphere] burst!",
}

# Recollection-unlock grid (kaisou.push) + CG thumbnail list (TitleList.push). Race
# entries are '【{race}:' + status + '】' and bare '{race}' titles — seeded from the
# race glossary; the rest are section/scene labels.
for _jp, _en in _LB_RACES.items():
    SEED_SCRIPT_TEXT["【" + _jp + ":"] = "【" + _en + ":"
    SEED_SCRIPT_TEXT[_jp] = _en
SEED_SCRIPT_TEXT.update({
    "前期一回目：": "Early 1st:", "後期一回目：": "Late 1st:", "　　二回目：": "  2nd:",
    "前期　奉仕：": "Early Service:", "後期　奉仕：": "Late Service:", "　ボテックス：": " Vortex:",
    "【前期A:": "【Early A:", "【前期B:": "【Early B:", "【前期C:": "【Early C:",
    "【後期A:": "【Late A:", "【後期B:": "【Late B:", "【後期C:": "【Late C:",
    "【基底:": "【Base:", "【飛行:": "【Flying:", "【獣　:": "【Beast:", "【不定:": "【Amorphous:",
    "【土下座:": "【Grovel:", "【奉仕:": "【Service:",
    "【奉仕LV1:": "【Service LV1:", "【奉仕LV2:": "【Service LV2:", "【奉仕LV3:": "【Service LV3:",
    "【奉仕LV4:": "【Service LV4:", "【奉仕LV5:": "【Service LV5:",
    "奉仕・尻": "Service: Butt", "奉仕・乳": "Service: Breast", "奉仕・口": "Service: Mouth",
    "ボテックスA": "Vortex A", "ボテックスB": "Vortex B", "ボテックスC": "Vortex C",
    "凶角卿　　：": "Vicious-Horn Lord:", "凶角卿の失墜": "The Vicious-Horn Lord's Fall",
    "おまけ画像": "Bonus Images", "エンディング": "Ending", "タイトル": "Title",
    "出産": "Birth", "出産時会話": "Birthing Dialogue",
    "牢獄にて": "In the Prison", "基底収容所にて": "In the Base Ward",
    "飛行収容所にて": "In the Flying Ward", "獣収容所にて": "In the Beast Ward",
    "不定形収容所にて": "In the Amorphous Ward",
})
