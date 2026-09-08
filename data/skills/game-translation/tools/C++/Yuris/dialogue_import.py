"""
Import translated .txt files (DazedMTLTool output) back into the
dialogue/*.json files. Each .txt line corresponds 1:1 to an entry in
the JSON's `lines[]` array (same order as exported).

Format expected per line: `[Speaker]: dialogue` for spoken, or just
`dialogue` for narration. The speaker prefix is stripped before storing
in the JSON's `text` field (the speaker is already known from the
JSON's `speaker` field).

Usage:
    python tools/dialogue_import.py [<translated_dir>]

Default translated_dir is C:/Users/sw/Downloads/DazedMTLTool-main/translated/.
"""
import os, sys, json, re

DIALOGUE_DIR = r'C:/Users/sw/Desktop/Elfhime_translation/dialogue'
DEFAULT_IN   = r'C:/Users/sw/Downloads/DazedMTLTool-main/translated'

SPEAKER_RE = re.compile(r'^\[([^\]]+)\]\s*[:|]\s*(.*)$')

def import_one(json_path, txt_path, dry_run=False):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    with open(txt_path, 'r', encoding='utf-8') as f:
        # readlines preserves blank-line structure; strip trailing \n only
        lines = [line.rstrip('\n') for line in f.readlines()]
    # Trim a single trailing blank line that the export adds.
    if lines and lines[-1] == '':
        lines.pop()
    entries = data.get('lines', [])
    if len(lines) != len(entries):
        raise RuntimeError(
            f'line-count mismatch: {os.path.basename(txt_path)} has {len(lines)} '
            f'lines but {os.path.basename(json_path)} has {len(entries)} entries'
        )
    changed = 0
    for entry, line in zip(entries, lines):
        m = SPEAKER_RE.match(line)
        if m:
            text = m.group(2).strip()
        else:
            text = line.strip()
        if entry.get('text') != text:
            entry['text'] = text
            changed += 1
    if not dry_run:
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
            f.write('\n')
    return changed, len(entries)

def main():
    in_dir = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_IN
    if not os.path.isdir(in_dir):
        sys.exit(f'translated dir not found: {in_dir}')
    total_changed = 0
    total_entries = 0
    files = 0
    for name in sorted(os.listdir(in_dir)):
        if not name.startswith('yst') or not name.endswith('.txt'):
            continue
        json_name = name[:-4] + '.json'
        json_path = os.path.join(DIALOGUE_DIR, json_name)
        txt_path = os.path.join(in_dir, name)
        if not os.path.exists(json_path):
            print(f'  skip {name}: matching JSON not found')
            continue
        changed, total = import_one(json_path, txt_path)
        print(f'  {name}: {changed}/{total} updated')
        total_changed += changed
        total_entries += total
        files += 1
    print(f'imported {files} files: {total_changed}/{total_entries} entries updated')

if __name__ == '__main__':
    main()
