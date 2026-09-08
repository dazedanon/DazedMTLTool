"""
Build DazedMTLTool's vocab.txt from our project glossary.

Combines three sources:
  1. dialogue/_glossary.json — game-specific characters + terms (you edit this)
  2. dialogue/_speakers.json — Japanese speaker -> English name mapping
  3. dialogue/*.json          — scanned for speaker frequencies, so unknown
                                speakers get auto-listed at the bottom
  4. DazedMTLTool/vocab_base.txt — pre-shipped honorifics + standard terms
                                   (optional, appended verbatim)

Output goes to <DazedMTLTool>/vocab.txt by default.

Usage:
    python tools/build_vocab.py [<dazed_root>]
"""
import os, sys, json
from collections import Counter

DIALOGUE_DIR = r'C:/Users/sw/Desktop/Elfhime_translation/dialogue'
DEFAULT_DAZED = r'C:/Users/sw/Downloads/DazedMTLTool-main'

GLOSSARY_PATH  = os.path.join(DIALOGUE_DIR, '_glossary.json')
SPEAKERS_PATH  = os.path.join(DIALOGUE_DIR, '_speakers.json')

def load_json(path):
    if not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

def scan_speaker_counts():
    """Scan all yst*.json for speaker frequencies."""
    counts = Counter()
    for name in sorted(os.listdir(DIALOGUE_DIR)):
        if not name.startswith('yst') or not name.endswith('.json'):
            continue
        with open(os.path.join(DIALOGUE_DIR, name), 'r', encoding='utf-8') as f:
            data = json.load(f)
        for entry in data.get('lines', []):
            sp = entry.get('speaker', '') or ''
            if sp:
                counts[sp] += 1
    return counts

def sync_speakers(existing, glossary_chars):
    """Update _speakers.json so it contains every character name from
    _glossary.json. Preserves existing metadata (_doc, _no_pad, etc.) and
    leaves any extra simple-map entries the user added by hand."""
    if not glossary_chars:
        return
    # Load the file fresh to keep metadata keys
    with open(SPEAKERS_PATH, 'r', encoding='utf-8') as f:
        try:
            full = json.load(f)
        except json.JSONDecodeError:
            full = {}
    changed = False
    for jp, info in glossary_chars.items():
        if not isinstance(info, dict):
            continue
        name = (info.get('name') or '').strip()
        if not name:
            continue
        if full.get(jp) != name:
            full[jp] = name
            changed = True
    if changed:
        with open(SPEAKERS_PATH, 'w', encoding='utf-8') as f:
            json.dump(full, f, ensure_ascii=False, indent=1)
            f.write('\n')

def fmt_character(jp, info):
    """Render one character entry in vocab.txt format:
        Japanese (English) - Gender - role/notes
    Optional fields are omitted cleanly when empty."""
    name   = (info.get('name')        or '').strip()
    gender = (info.get('gender')      or '').strip()
    role   = (info.get('role')        or '').strip()
    pers   = (info.get('personality') or '').strip()
    speech = (info.get('speech')      or '').strip()
    if not name:
        return None  # skip entries without an English name
    parts = [f'{jp} ({name})']
    if gender:
        parts.append(gender)
    notes_bits = []
    if role:   notes_bits.append(role)
    if pers:   notes_bits.append(pers)
    if speech: notes_bits.append(f'speech: {speech}')
    if notes_bits:
        parts.append('; '.join(notes_bits))
    return ' - '.join(parts)

def build_vocab(dazed_root):
    glossary = load_json(GLOSSARY_PATH)
    speakers = {k: v for k, v in load_json(SPEAKERS_PATH).items()
                if not k.startswith('_')}
    chars = glossary.get('characters', {}) or {}
    terms = glossary.get('terms',      {}) or {}

    # Merge: _speakers.json gives a basic name; _glossary.json overrides/extends.
    merged_chars = {}
    for jp, en in speakers.items():
        merged_chars[jp] = {'name': en}
    for jp, info in chars.items():
        # _glossary.json wins; merge keys when both present
        if jp in merged_chars:
            merged_chars[jp].update(info)
        else:
            merged_chars[jp] = dict(info)

    # Detect unmapped speakers from the dialogue files
    counts = scan_speaker_counts()
    unmapped = [(sp, n) for sp, n in counts.most_common()
                if sp not in merged_chars]

    # ── Compose vocab.txt ──────────────────────────────────────────
    lines = []
    lines.append('# Game Characters')
    # Sort merged characters by frequency descending so the AI sees the
    # most common (= protagonist) first.
    sorted_chars = sorted(
        merged_chars.items(),
        key=lambda kv: -counts.get(kv[0], 0),
    )
    for jp, info in sorted_chars:
        ent = fmt_character(jp, info)
        if ent:
            lines.append(ent)
    lines.append('')

    if unmapped:
        lines.append('# Unmapped Speakers (TODO: add to _glossary.json)')
        lines.append("# These appear in dialogue/*.json but have no entry in _glossary.json or _speakers.json yet.")
        lines.append('# Counts shown to help you prioritise.')
        for sp, n in unmapped:
            lines.append(f'# {sp} ({n} lines)')
        lines.append('')

    if terms:
        lines.append('# Game Terms')
        for jp, en in terms.items():
            lines.append(f'{jp} ({en})')
        lines.append('')

    # Append the project-wide base vocab if available
    base_path = os.path.join(dazed_root, 'vocab_base.txt')
    if os.path.exists(base_path):
        lines.append('# ── DazedMTLTool base vocab ─────────────────────────────')
        with open(base_path, 'r', encoding='utf-8') as f:
            lines.append(f.read().rstrip())
        lines.append('')

    out_path = os.path.join(dazed_root, 'vocab.txt')
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines))

    # Keep _speakers.json (consumed by patch_speakers.py) in sync with
    # _glossary.json's character names so the user only edits the glossary.
    sync_speakers(speakers, chars)

    n_named   = sum(1 for jp, info in merged_chars.items() if info.get('name'))
    n_terms   = len(terms)
    n_unmap   = len(unmapped)
    summary = (
        f'wrote {out_path}\n'
        f'  characters: {n_named} named, {n_unmap} unmapped (top: '
        + ', '.join(f'{sp}({n})' for sp, n in unmapped[:5]) + ')\n'
        f'  terms:      {n_terms}\n'
    )
    # Some Windows consoles default to cp1252 — write summary as UTF-8 bytes.
    sys.stdout.buffer.write(summary.encode('utf-8'))

if __name__ == '__main__':
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DAZED
    if not os.path.isdir(root):
        sys.exit(f'DazedMTLTool dir not found: {root}')
    build_vocab(root)
