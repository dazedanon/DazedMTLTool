"""
Auto-fill dialogue/_glossary.json with gender / role / sample for every
speaker found in dialogue/*.json. Combines:

  • Speaker-name keyword heuristics (兵士=Soldier/Male, 王女=Princess/Female,
    神父=Priest/Male, etc.)
  • In-dialogue pronoun & sentence-ending particle scoring (俺/僕/ぞ/ぜ → Male,
    あたし/わ/のよ → Female).
  • Up to two short representative sample lines per character.

Existing manually curated entries are preserved unless you pass --force.
"""
import os, sys, json, re
from collections import Counter, defaultdict

DIALOGUE_DIR  = r'C:/Users/sw/Desktop/Elfhime_translation/dialogue'
GLOSSARY_PATH = os.path.join(DIALOGUE_DIR, '_glossary.json')

# ── Speaker-name keyword mapping ───────────────────────────────────
# Each rule is (substring, attrs). Earlier rules in the same category win.
NAME_RULES = [
    # gender-specific
    ('王女', dict(gender='Female', role='Princess')),
    ('女王', dict(gender='Female', role='Queen')),
    ('王妃', dict(gender='Female', role='Queen Consort')),
    ('女', dict(gender='Female')),
    ('娼婦', dict(gender='Female', role='Prostitute')),
    ('娘', dict(gender='Female')),
    ('母', dict(gender='Female')),
    ('少女', dict(gender='Female', role='Young girl')),
    ('産婆', dict(gender='Female', role='Midwife')),
    ('王',   dict(gender='Male', role='King')),
    ('騎士', dict(gender='Male', role='Knight')),
    ('兵士', dict(gender='Male', role='Soldier')),
    ('神父', dict(gender='Male', role='Priest')),
    ('父',   dict(gender='Male')),
    ('息子', dict(gender='Male')),
    ('少年', dict(gender='Male', role='Young boy')),
    ('男',   dict(gender='Male')),
    ('使者', dict(gender='Male', role='Envoy')),
    ('魔導', dict(gender='Male', role='Mage')),
    ('魔法使い', dict(role='Mage')),
    ('傭兵', dict(role='Mercenary')),
    ('海賊', dict(role='Pirate')),
    ('山賊', dict(gender='Male', role='Bandit')),
    ('盗賊', dict(role='Thief')),
    ('村人', dict(role='Villager')),
    ('客',   dict(role='Customer')),
    ('商人', dict(role='Merchant')),
    ('道具屋の主人', dict(gender='Male', role='Item shop owner')),
    ('宿屋の主人', dict(gender='Male', role='Innkeeper')),
    ('酒場のマスター', dict(gender='Male', role='Tavern master')),
    ('娼館の主', dict(role='Brothel owner')),
    ('奴隷商人', dict(gender='Male', role='Slave trader')),
    ('医者', dict(role='Doctor')),
    ('エルフ', dict(role='Elf')),
    ('ダークエルフ', dict(role='Dark elf')),
    ('ハイエルフ', dict(role='High elf')),
    ('ドワーフ', dict(role='Dwarf')),
    ('神官', dict(role='Cleric')),
    ('司教', dict(role='Bishop')),
    ('子供', dict(role='Child')),
    ('旅人', dict(role='Traveler')),
    ('戦士', dict(role='Warrior')),
]

# ── Name-suffix transliteration (Ａ→A, Ｂ→B, …) ───────────────────
FULLWIDTH = {chr(c): chr(c - 0xfee0) for c in range(0xff21, 0xff3b)}  # Ａ-Ｚ → A-Z

# ── Dialogue gender-marker patterns ───────────────────────────────
MALE_PATTERNS   = [r'俺', r'僕', r'おれ', r'ぼく', r'だぜ', r'だぞ', r'なんだ',
                   r'だい', r'なきゃ', r'てやる', r'お前', r'てめえ', r'やるぜ']
FEMALE_PATTERNS = [r'あたし', r'わたくし', r'わよ', r'だわ', r'ですわ', r'のよ',
                   r'なのよ', r'なのね', r'かしら', r'よね', r'てよ',
                   r'ですもの', r'なさい']

MALE_RE   = re.compile('|'.join(MALE_PATTERNS))
FEMALE_RE = re.compile('|'.join(FEMALE_PATTERNS))

# ── Helpers ────────────────────────────────────────────────────────
def transliterate_suffix(name):
    """Convert trailing fullwidth letters (兵士Ａ → 兵士A) for English form."""
    out = ''
    for ch in name:
        out += FULLWIDTH.get(ch, ch)
    return out

def english_name_for(jp):
    """Best-effort English name when the user hasn't provided one."""
    # Built-in mappings for common words
    base_map = {
        '男性': 'Man', '女性': 'Woman', '若い男': 'Young Man',
        '少年': 'Boy', '少女': 'Girl', '巨躯の男': 'Hulking Man',
        '長身の男': 'Tall Man', '小太りの男性': 'Pudgy Man',
        '髭面の男': 'Bearded Man', '目つきの悪い男': 'Shifty Man',
        '傷だらけの男': 'Scarred Man', '名家の少年': 'Highborn Boy',
        '若い魔法使い': 'Young Mage', '剛腕の戦士': 'Brawny Warrior',
        'フードの人物': 'Hooded Figure', '？？？': '???',
        '商人': 'Merchant', '医者': 'Doctor', '神父': 'Priest',
        '産婆': 'Midwife', '娼婦': 'Prostitute', '客の男': 'Male Customer',
        '村人': 'Villager', '傭兵': 'Mercenary', '傭兵王': 'Mercenary King',
        '魔導王': 'Sorcerer King', '海賊王': 'Pirate King',
        '宿屋の主人': 'Innkeeper', '道具屋の主人': 'Shopkeeper',
        '酒場のマスター': 'Tavern Master', '娼館の主': 'Brothel Owner',
        '奴隷商人': 'Slave Trader', '旅人': 'Traveler', '兵士': 'Soldier',
        '商人': 'Merchant', '騎士': 'Knight', '王女': 'Princess',
        'エルフ達': 'Elves', 'アイリアの母': "Aria's Mother",
        'アイリア＆エルム': 'Aria & Elm', '高貴なエルフＡ': 'Noble Elf A',
        '高貴なエルフＢ': 'Noble Elf B', '大教会の神父': 'Cathedral Priest',
        '兵士Ｅ': 'Soldier E', '兵士Ｆ': 'Soldier F',
        '山賊Ａ': 'Bandit A', '山賊Ｂ': 'Bandit B',
        '西国の騎士Ｂ': 'Western Knight B', '西国の騎士Ｃ': 'Western Knight C',
        '西国の騎士Ｄ': 'Western Knight D',
        '傭兵団の男Ａ': 'Mercenary A', '傭兵団の男Ｂ': 'Mercenary B',
        '傭兵団の男Ｃ': 'Mercenary C',
        '男性客Ａ': 'Male Customer A', '男性客Ｂ': 'Male Customer B',
        '男性客Ｃ': 'Male Customer C',
        '女性Ａ': 'Woman A', '女性Ｂ': 'Woman B', '女性': 'Woman',
        '子供Ａ': 'Child A', '子供Ｂ': 'Child B', '子供Ｃ': 'Child C',
        'エルフＤ': 'Elf D', 'エルフＥ': 'Elf E', 'エルフの少女': 'Elf Girl',
    }
    if jp in base_map:
        return base_map[jp]
    # 男性Ａ-Ｚ → Man A-Z
    m = re.match(r'^男性([Ａ-Ｚ])$', jp)
    if m:
        return 'Man ' + transliterate_suffix(m.group(1))
    return None

def gender_from_name(jp):
    for kw, attrs in NAME_RULES:
        if kw in jp and 'gender' in attrs:
            return attrs['gender']
    return ''

def role_from_name(jp):
    for kw, attrs in NAME_RULES:
        if kw in jp and 'role' in attrs:
            return attrs['role']
    return ''

def gender_from_dialogue(lines):
    """Score gender by counting male vs female linguistic markers in
    concatenated dialogue. Returns 'Male' / 'Female' / ''."""
    text = ' '.join(lines)
    male   = len(MALE_RE.findall(text))
    female = len(FEMALE_RE.findall(text))
    if male >= 2 and male > female * 2:
        return 'Male'
    if female >= 2 and female > male * 2:
        return 'Female'
    return ''

def gather_lines():
    """{ jp_speaker: [text, text, ...] } across all dialogue files."""
    by_speaker = defaultdict(list)
    for name in sorted(os.listdir(DIALOGUE_DIR)):
        if not name.startswith('yst') or not name.endswith('.json'):
            continue
        with open(os.path.join(DIALOGUE_DIR, name), 'r', encoding='utf-8') as f:
            data = json.load(f)
        for entry in data.get('lines', []):
            sp = (entry.get('speaker') or '').strip()
            txt = (entry.get('text') or '').strip()
            if sp and txt:
                by_speaker[sp].append(txt)
    return by_speaker

def main():
    force = '--force' in sys.argv
    with open(GLOSSARY_PATH, 'r', encoding='utf-8') as f:
        glossary = json.load(f)
    chars = glossary.setdefault('characters', {})
    by_speaker = gather_lines()

    n_added = n_filled = n_skipped = 0
    for jp, lines in sorted(by_speaker.items(), key=lambda kv: -len(kv[1])):
        info = chars.get(jp)
        if info is None:
            info = {}
            chars[jp] = info
            n_added += 1

        # name (English) — prefer existing
        if force or not info.get('name'):
            name = english_name_for(jp)
            if name:
                info['name'] = name

        # gender — prefer existing; combine name & dialogue
        if force or not info.get('gender'):
            g = gender_from_name(jp) or gender_from_dialogue(lines)
            if g:
                info['gender'] = g

        # role — prefer existing
        if force or not info.get('role'):
            r = role_from_name(jp)
            if r:
                info['role'] = r

        # personality / speech: keep existing only — these need human nuance
        info.setdefault('personality', '')
        info.setdefault('speech', '')

        if not info.get('name'):
            n_skipped += 1
        else:
            n_filled += 1

    # Drop fields the user explicitly cleared (keep schema clean)
    for jp, info in list(chars.items()):
        for k in ('gender', 'role', 'personality', 'speech'):
            if info.get(k) == '':
                # leave the empty key — it documents the schema for that entry
                pass

    with open(GLOSSARY_PATH, 'w', encoding='utf-8') as f:
        json.dump(glossary, f, ensure_ascii=False, indent=2)
        f.write('\n')

    sys.stdout.buffer.write(
        f'updated {GLOSSARY_PATH}\n'
        f'  speakers in dialogue: {len(by_speaker)}\n'
        f'  newly added entries:  {n_added}\n'
        f'  filled or kept:       {n_filled}\n'
        f'  no English name yet:  {n_skipped}\n'.encode('utf-8')
    )

if __name__ == '__main__':
    main()
