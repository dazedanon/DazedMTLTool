"""
fix_plugin_strings.py — translate the player-facing JP strings that live in
PLUGIN PARAMETERS (js/plugins.js), not in data/*.json: the enemy bestiary
(ABMZ_EnemyBook) labels, the save-file delete prompt, the track-name option,
the sealed-command sign, the message-log/backlog menu labels, etc.

Developer/config params (filenames, ids, camera targets, @param help) are left
alone. The data-side text (dialogue, items, the DTextPicture prologue) is handled
by the main `tl.py` pipeline — this only covers what lives in plugins.js.

Structured edit: parse the $plugins array, set the listed params, then write the
array back (minified, like the original). Idempotent; backs up plugins.js once.
"""
import os, json, re, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGINS = os.path.join(ROOT, "js", "plugins.js")   # RPG Maker MZ layout

# --- scalar param -> English (set directly) -------------------------------
SCALAR = {
    "ABMZ/ABMZ_EnemyBook": {
        "EnemyBookCommandName": "Enemy Info",
        "EnemyBookAllCommandName": "Bestiary",
        "Achievement": "Completion",
        "HitRateName": "Hit Rate",
        "EvadeRateName": "Evade Rate",
        "WeakElementName": "Weak Element",
        "ResistElementName": "Resist Element",
        "WeakStateName": "Weak State",
        "ResistStateName": "Resist State",
        "NoEffectStateName": "Immune State",
        "DefeatNumberName": "Times Defeated",
        "AddEnemySkillMessage": "Registered %1 to the Bestiary!",
        "FailToAddEnemySkillMessage": "%1 can't be added to the Bestiary!",
        "MissToAddEnemySkillMessage": "Failed to register %1 to the Bestiary!",
        "FailToCheckEnemySkillMessage": "Couldn't find any info on %1!",
    },
    "awaya/RemoveSaveFile": {
        "message": "Which file do you want to delete?",
        "commandName": "Delete Save File",
    },
    "lulus_church/LL_TrackNameWindow": {
        "optionCommandName": "Show Track Name",
    },
    "triacontane/SealActorCommand": {
        # keep the control codes (\c[2] colour, \i[1] icon); only 禁止 -> Sealed
        "disableSign": "\\c[2]\\i[1]Sealed\\i[1]",
    },
    "Tsukimi/FilterControllerMZ": {
        "enabledAll-Text": "Filter Effects",
    },
}

# --- multi-locale JSON params {"ja_JP":"…","en_US":"…",…}: set ja_JP (shown
#     while the game's locale is ja_JP) AND en_US to the English label ----------
MULTILOCALE = {
    "siguren400/ManoUZ_MessageLog": {
        "menuCommand": "Backlog",
        "choiceText": "Choices",
        "choiceCancelText": "Cancel",
    },
}

# --- term replacements inside array/struct params (longest-first) -------------
TERM = {
    "バトルスピード": "Battle Speed",
}
ARRAY_PARAMS = {
    "kekeelabo/Keke_SpeedStarBattle": ["オプション追加リスト"],
}

# --- LL_TrackNameWindow: BGM credits shown on track change (format "title/creator").
# Translate the song TITLE and romanize the creator to its official name; NEVER
# touch trackFile (the real path). Some free-BGM licenses want the credit shown
# unaltered — revert via plugins.js.bak if a track's license requires it.
TRACKLIST_PARAMS = {"lulus_church/LL_TrackNameWindow": "trackLists"}
TRACKNAMES = {
    "時の継承者/RP-MUSIC": "Inheritor of Time/RP-MUSIC",
    "滅びし文明のガーディアン・マシーン/RP-MUSIC": "Guardian Machine of a Fallen Civilization/RP-MUSIC",
    "青竜が守護する神殿/RP-MUSIC": "Temple Guarded by the Azure Dragon/RP-MUSIC",
    "彷徨う亡霊/RP-MUSIC": "Wandering Spirit/RP-MUSIC",
    "彷徨う亡霊_v1/RP-MUSIC": "Wandering Spirit (v1)/RP-MUSIC",
    "青い薔薇の物語のはじまりに/RP-MUSIC": "At the Beginning of the Blue Rose's Tale/RP-MUSIC",
    "神へ捧げる祈りの歌/RP-MUSIC": "A Hymn of Prayer to God/RP-MUSIC",
    "Mchn-forest/パラメトリカル": "Mchn-forest/Parametrical",
    "決断の時/ユーフルカ": "The Moment of Decision/YouFulca",
    "Everlasting Flame of Blue/ユーフルカ": "Everlasting Flame of Blue/YouFulca",
    "とある勇者の戦いの記憶/ユーフルカ": "Memories of a Certain Hero's Battle/YouFulca",
    "終末のリチェルカーレ/ユーフルカ": "Ricercar of the End/YouFulca",
    "己と仲間を信じて/ユーフルカ": "Believe in Yourself and Your Comrades/YouFulca",
    "闇に還る時/ユーフルカ": "The Hour of Returning to Darkness/YouFulca",
    "Face The Fear/ユーフルカ": "Face The Fear/YouFulca",
    "死を呼ぶオルゴール/ユーフルカ": "The Death-Calling Music Box/YouFulca",
    "奈落/ユーフルカ": "Abyss/YouFulca",
    "死獄/ユーフルカ": "Hell of Death/YouFulca",
    "慕情/音小屋": "Yearning/Otogoya",
    "Jupiter ～天空の神～/音小屋": "Jupiter ~God of the Heavens~/Otogoya",
    "今宵夢の終わりにて/音小屋": "Tonight, at the End of the Dream/Otogoya",
    "Overture -All of Creation-/音小屋": "Overture -All of Creation-/Otogoya",
    "天龍の郷/音小屋": "Village of the Heavenly Dragon/Otogoya",
    "闇との戦い/趣味工房にんじんわいん": "Battle Against the Darkness/Ninjin Wine",
    "Forest of the witch/趣味工房にんじんわいん": "Forest of the Witch/Ninjin Wine",
    "Mchn-boss01/パラメトリカル": "Mchn-boss01/Parametrical",
    "Mchn-boss02/パラメトリカル": "Mchn-boss02/Parametrical",
    "Mchn-evil/パラメトリカル": "Mchn-evil/Parametrical",
    "Mchn-falls/パラメトリカル": "Mchn-falls/Parametrical",
    "Mchn-ingress/パラメトリカル": "Mchn-ingress/Parametrical",
    "Mchn-lastboss01/パラメトリカル": "Mchn-lastboss01/Parametrical",
    "Mchn-prologue/パラメトリカル": "Mchn-prologue/Parametrical",
    "Mchn-recollection/パラメトリカル": "Mchn-recollection/Parametrical",
    "Mchn-roar/パラメトリカル": "Mchn-roar/Parametrical",
    "理力とオーブ / スタジオランス": "Force and Orb / Studio Lance",
    "混沌の時代 / スタジオランス": "Age of Chaos / Studio Lance",
    "Innocent Eyes / ユーフルカ": "Innocent Eyes / YouFulca",
    "Prayer -祈り- / 趣味工房にんじんわいん": "Prayer / Ninjin Wine",
}


def translate_tracklist(value):
    """value is a JSON array of JSON-string elements {trackFile, trackName, ...}.
    Replace trackName per TRACKNAMES; keep trackFile and every other field."""
    try:
        arr = json.loads(value)
    except Exception:
        return value
    out = []
    for elem in arr:
        try:
            o = json.loads(elem)
        except Exception:
            out.append(elem); continue
        nm = o.get("trackName")
        if nm in TRACKNAMES:
            o["trackName"] = TRACKNAMES[nm]
        out.append(json.dumps(o, ensure_ascii=False))
    return json.dumps(out, ensure_ascii=False)


def translate_terms(s):
    for jp in sorted(TERM, key=len, reverse=True):
        s = s.replace(jp, TERM[jp])
    return s


def set_multilocale(value, en):
    """value is a JSON string like {"ja_JP":"バックログ","en_US":"",...}; set the
    ja_JP and en_US fields to `en`. Returns the new JSON string (or value if not
    parseable)."""
    try:
        obj = json.loads(value)
    except Exception:
        return value
    if isinstance(obj, dict):
        for k in ("ja_JP", "en_US"):
            if k in obj:
                obj[k] = en
        return json.dumps(obj, ensure_ascii=False)
    return value


def main():
    if not os.path.exists(PLUGINS):
        raise SystemExit(f"not found: {PLUGINS}")
    raw = open(PLUGINS, encoding="utf-8").read()
    start = raw.find("[", raw.find("$plugins"))
    end = raw.rfind("]") + 1
    head, arr_text, tail = raw[:start], raw[start:end], raw[end:]
    plugins = json.loads(arr_text)

    changed = 0
    for p in plugins:
        name = p.get("name")
        params = p.get("parameters") or {}
        for k, en in SCALAR.get(name, {}).items():
            if k in params and params[k] != en:
                params[k] = en; changed += 1
        for k, en in MULTILOCALE.get(name, {}).items():
            if k in params:
                new = set_multilocale(params[k], en)
                if new != params[k]:
                    params[k] = new; changed += 1
        for k in ARRAY_PARAMS.get(name, []):
            if k in params:
                new = translate_terms(params[k])
                if new != params[k]:
                    params[k] = new; changed += 1
        tk = TRACKLIST_PARAMS.get(name)
        if tk and tk in params:
            new = translate_tracklist(params[tk])
            if new != params[tk]:
                params[tk] = new; changed += 1

    if changed:
        bak = PLUGINS + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(PLUGINS, bak)
        new_arr = json.dumps(plugins, ensure_ascii=False, separators=(",", ":"))
        open(PLUGINS, "w", encoding="utf-8").write(head + new_arr + tail)
    print(f"plugin string params updated: {changed}")


if __name__ == "__main__":
    main()
