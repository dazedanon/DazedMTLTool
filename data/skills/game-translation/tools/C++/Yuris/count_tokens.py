"""
Count dialogue volume for translation pricing.

Reports per-script and grand totals for:
  - line count
  - character count (japanese chars + ascii separately)
  - cl100k_base tokens (GPT-3.5/4)
  - o200k_base tokens (GPT-4o, GPT-5; close approximation for Claude too)

Outputs a sortable CSV alongside the summary.
"""
import os, sys, json, csv, io
sys.stdout.reconfigure(encoding='utf-8')

import tiktoken
ENC_CL100K = tiktoken.get_encoding('cl100k_base')
ENC_O200K = tiktoken.get_encoding('o200k_base')

def is_jp(c):
    o = ord(c)
    return (0x3040 <= o < 0x30ff) or (0x4e00 <= o < 0x9fff) or (0xff00 <= o < 0xffef)

DIALOGUE_DIR = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/sw/Desktop/Elfhime_translation/dialogue'

per_script = []
speaker_totals = {}

g_lines = 0
g_chars = 0
g_jp_chars = 0
g_cl100k = 0
g_o200k = 0
g_speaker_chars = 0
g_dialogue_chars = 0

for fn in sorted(os.listdir(DIALOGUE_DIR)):
    if not fn.startswith('yst') or not fn.endswith('.json'):
        continue
    with open(os.path.join(DIALOGUE_DIR, fn), 'r', encoding='utf-8') as f:
        data = json.load(f)
    s_lines = data['lines']
    if not s_lines:
        continue
    s_chars = 0
    s_jp = 0
    s_cl = 0
    s_o2 = 0
    for line in s_lines:
        speaker = line.get('speaker', '') or ''
        text = line.get('text', '') or ''
        full = speaker + text
        s_chars += len(full)
        s_jp += sum(1 for c in full if is_jp(c))
        s_cl += len(ENC_CL100K.encode(full))
        s_o2 += len(ENC_O200K.encode(full))
        speaker_totals.setdefault(speaker, [0, 0, 0])  # lines, chars, tokens
        speaker_totals[speaker][0] += 1
        speaker_totals[speaker][1] += len(text)
        speaker_totals[speaker][2] += len(ENC_O200K.encode(text))
        g_speaker_chars += len(speaker)
        g_dialogue_chars += len(text)
    per_script.append({
        'file': fn,
        'lines': len(s_lines),
        'chars': s_chars,
        'jp_chars': s_jp,
        'cl100k_tokens': s_cl,
        'o200k_tokens': s_o2,
    })
    g_lines += len(s_lines); g_chars += s_chars; g_jp_chars += s_jp
    g_cl100k += s_cl; g_o200k += s_o2

# CSV
csv_path = os.path.join(DIALOGUE_DIR, '_token_counts.csv')
with open(csv_path, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=['file', 'lines', 'chars', 'jp_chars', 'cl100k_tokens', 'o200k_tokens'])
    w.writeheader()
    for r in per_script:
        w.writerow(r)
    w.writerow({'file': 'TOTAL', 'lines': g_lines, 'chars': g_chars, 'jp_chars': g_jp_chars,
                'cl100k_tokens': g_cl100k, 'o200k_tokens': g_o200k})

print('==== TOTALS ====')
print(f'  scripts with dialogue: {len(per_script)}')
print(f'  dialogue lines:        {g_lines:,}')
print(f'  total characters:      {g_chars:,}  (speaker-name {g_speaker_chars:,} + dialogue {g_dialogue_chars:,})')
print(f'  Japanese characters:   {g_jp_chars:,}')
print(f'  cl100k_base tokens:    {g_cl100k:,}  (GPT-3.5/4 / Claude legacy estimate)')
print(f'  o200k_base tokens:     {g_o200k:,}  (GPT-4o/5; close to Claude tokenizer)')
print()
print(f'  ratio chars/o200k:     {g_chars/g_o200k:.2f}')
print(f'  ratio jp_chars/o200k:  {g_jp_chars/g_o200k:.2f}')

# Top scripts
print('\n==== Largest scripts (by o200k tokens) ====')
for r in sorted(per_script, key=lambda x: -x['o200k_tokens'])[:10]:
    print(f"  {r['file']}: {r['lines']:>4} lines  {r['chars']:>6,} chars  {r['o200k_tokens']:>6,} tokens")

# Top speakers
print('\n==== Top speakers (by line count) ====')
for sp, (lc, cc, tc) in sorted(speaker_totals.items(), key=lambda x: -x[1][0])[:15]:
    label = sp if sp else '(narration)'
    print(f"  {label:<20} {lc:>5} lines  {cc:>7,} chars  {tc:>6,} o200k tokens")

# Pricing examples (input + output assumed equal volume)
print('\n==== Cost estimates (input + 1.5x output, approx Apr-2026 pricing) ====')
def cost(in_t, out_t, in_p, out_p):
    return in_t/1e6 * in_p + out_t/1e6 * out_p

# Output ~1.5x input (English translation tends to be longer in tokens)
out_tokens = int(g_o200k * 1.5)
models = [
    ('Claude Opus 4.7',         15.00, 75.00),
    ('Claude Sonnet 4.6',         3.00, 15.00),
    ('Claude Haiku 4.5',          1.00,  5.00),
    ('GPT-5',                     1.25, 10.00),
    ('GPT-5 mini',                0.25,  2.00),
    ('GPT-4o',                    2.50, 10.00),
    ('GPT-4o mini',               0.15,  0.60),
    ('DeepSeek-V3',               0.27,  1.10),
]
print(f'  (input = {g_o200k:,} tokens; output ~= {out_tokens:,} tokens)')
for name, ip, op in models:
    print(f"  {name:<22} ${cost(g_o200k, out_tokens, ip, op):>7.2f}")
print(f'\n  CSV with per-script breakdown: {csv_path}')
