"""
Export dialogue/*.json -> .txt files in DazedMTLTool's `[Speaker]: line`
format, one line per entry. Order matches the JSON's `lines[]` array
exactly so dialogue_import.py can match them back by index.

Usage:
    python tools/dialogue_export.py [<output_dir>]

Default output_dir is C:/Users/sw/Downloads/DazedMTLTool-main/files/.
Speaker names are translated up-front using dialogue/_speakers.json so
DazedMTLTool doesn't waste API calls re-translating them.
"""
import os, sys, json, re

DIALOGUE_DIR  = r'C:/Users/sw/Desktop/Elfhime_translation/dialogue'
DEFAULT_OUT   = r'C:/Users/sw/Downloads/DazedMTLTool-main/files'
SPEAKERS_JSON = os.path.join(DIALOGUE_DIR, '_speakers.json')
GLOSSARY_JSON = os.path.join(DIALOGUE_DIR, '_glossary.json')

# Special characters that often appear in YU-RIS dialog and should NOT
# leak into the .txt format because they look like wrap markers.
def normalise_text(s):
    # Strip leading/trailing whitespace; keep internal whitespace as-is.
    return s.strip()

def load_speakers():
    """Build a JP -> EN speaker name map by merging _speakers.json (simple
    map used by patch_speakers.py) and _glossary.json's `characters`
    section (richer; only the `name` field is used here)."""
    mapping = {}
    if os.path.exists(SPEAKERS_JSON):
        with open(SPEAKERS_JSON, 'r', encoding='utf-8') as f:
            for k, v in json.load(f).items():
                if not k.startswith('_') and isinstance(v, str):
                    mapping[k] = v
    if os.path.exists(GLOSSARY_JSON):
        with open(GLOSSARY_JSON, 'r', encoding='utf-8') as f:
            chars = json.load(f).get('characters', {}) or {}
        for jp, info in chars.items():
            name = (info.get('name') or '').strip() if isinstance(info, dict) else ''
            if name:
                mapping[jp] = name
    return mapping

def export_one(json_path, out_path, speakers):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    out_lines = []
    for entry in data.get('lines', []):
        speaker_jp = entry.get('speaker', '') or ''
        text = normalise_text(entry.get('text', '') or '')
        # Pre-translate known speakers; unknown ones stay Japanese and the
        # tool's getSpeaker() will translate them via AI on first sight.
        speaker_disp = speakers.get(speaker_jp, speaker_jp)
        if speaker_disp:
            out_lines.append(f'[{speaker_disp}]: {text}')
        else:
            out_lines.append(text)
    with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(out_lines) + '\n')
    return len(out_lines)

def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    os.makedirs(out_dir, exist_ok=True)
    speakers = load_speakers()
    print(f'speaker mappings loaded: {len(speakers)}')
    total = 0
    files = 0
    for name in sorted(os.listdir(DIALOGUE_DIR)):
        if not name.startswith('yst') or not name.endswith('.json'):
            continue
        out_name = name[:-5] + '.txt'  # yst00125.json -> yst00125.txt
        in_path = os.path.join(DIALOGUE_DIR, name)
        out_path = os.path.join(out_dir, out_name)
        n = export_one(in_path, out_path, speakers)
        total += n
        files += 1
    print(f'exported {files} files / {total} lines -> {out_dir}')

if __name__ == '__main__':
    main()
