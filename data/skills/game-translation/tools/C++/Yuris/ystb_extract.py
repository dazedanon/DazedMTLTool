"""
YSTB (YU-RIS script binary) parser for Elfhime.

YSTB v0x1E8 layout:
  Header (32 bytes):
    char[4]  magic "YSTB"
    uint32   version (0x1E8)
    uint32   instruction_count
    uint32   code_size       (= instruction_count * 4)
    uint32   arg_size
    uint32   str_size
    uint32   line_size       (= instruction_count * 4)
    uint32   reserved (=0)

  Code section: 4 bytes per instruction
    uint8    opcode
    uint8    arg_count
    uint16   reserved/extra

  Arg section: 12 bytes per arg (sequence per instruction order)
    uint32   type            (0x00000000 = raw bytes; 0x00010xxx = expr; 0x00030xxx = string-typed)
    uint32   size
    uint32   offset           (into str section)

  Str section: variable-length records pointed to by args
  Line section: 4 bytes per instruction (uint32 source-line number)

All four sections (code, arg, str, line) are XOR-cycled with the 4-byte key
KEY = CRC32("Nexton") = 0x60 0x5e 0x41 0x4a (in memory order DAT_00804390..3).
The cycle restarts (offset 0 -> key[0]) at the start of each section.

Dialogue opcode: 0x6A. Its single arg has type 0x00000000 and the raw bytes
are Shift-JIS text formatted as either
   '【Speaker】「Dialogue」'   for spoken lines, or
   'Narration text.'           for narration.
"""
import os, sys, re, struct, json

KEY = bytes.fromhex('605e414a')  # CRC32("Nexton")
DIALOGUE_OPCODE = 0x6A

def xor_dec(data):
    return bytes(b ^ KEY[i & 3] for i, b in enumerate(data))

def parse_ystb(blob):
    if blob[:4] != b'YSTB':
        return None
    ver, ic, code_sz, arg_sz, str_sz, line_sz, _ = struct.unpack('<7I', blob[4:32])
    code_off = 32
    arg_off = code_off + code_sz
    str_off = arg_off + arg_sz
    line_off = str_off + str_sz
    code = xor_dec(blob[code_off:arg_off])
    args = xor_dec(blob[arg_off:str_off])
    strs = xor_dec(blob[str_off:line_off])
    lines = xor_dec(blob[line_off:line_off+line_sz])
    return ver, ic, code, args, strs, lines

# Match: ASCII '[' (0x81 0x79) Speaker ASCII ']' (0x81 0x7A) ASCII '"' (0x81 0x75) Dialogue ASCII '"' (0x81 0x76)
# In Shift-JIS: 【=0x81 0x79, 】=0x81 0x7A, 「=0x81 0x75, 」=0x81 0x76
SPEAKER_DIALOGUE_RE = re.compile(r'^【(?P<speaker>[^】]*)】「(?P<dialogue>.+)」$', re.DOTALL)
SPEAKER_ONLY_RE = re.compile(r'^【(?P<speaker>[^】]*)】(?P<dialogue>.+)$', re.DOTALL)

def parse_dialogue_text(txt):
    """Returns (speaker, dialogue, kind) where kind is 'spoken', 'tagged', or 'narration'."""
    m = SPEAKER_DIALOGUE_RE.match(txt)
    if m:
        return m.group('speaker'), m.group('dialogue'), 'spoken'
    m = SPEAKER_ONLY_RE.match(txt)
    if m:
        return m.group('speaker'), m.group('dialogue'), 'tagged'
    return '', txt, 'narration'

def extract_dialogue(ystb_path):
    with open(ystb_path, 'rb') as f:
        blob = f.read()
    parsed = parse_ystb(blob)
    if not parsed:
        return None
    ver, ic, code, args, strs, lines = parsed
    str_sz = len(strs)
    arg_pos = 0
    out = []
    for i in range(ic):
        op = code[i*4]
        argc = code[i*4+1]
        line_no = struct.unpack('<I', lines[i*4:i*4+4])[0]
        if op == DIALOGUE_OPCODE:
            for a in range(argc):
                if arg_pos + 12 > len(args):
                    break
                atype, asize, aoff = struct.unpack('<3I', args[arg_pos+a*12:arg_pos+a*12+12])
                if atype == 0x00000000 and 0 <= aoff < str_sz and 0 < asize <= str_sz - aoff:
                    raw = strs[aoff:aoff+asize]
                    try:
                        text = raw.decode('cp932')
                    except UnicodeDecodeError:
                        text = raw.decode('cp932', errors='replace')
                    speaker, dialogue, kind = parse_dialogue_text(text)
                    out.append({
                        'index': i,
                        'line': line_no,
                        'speaker': speaker,
                        'text': dialogue,
                        'raw': text,
                        'kind': kind,
                    })
        arg_pos += argc * 12
    return out

if __name__ == '__main__':
    src_dir = sys.argv[1] if len(sys.argv) > 1 else 'C:/Users/sw/Desktop/Elfhime_translation/extracted_scripts/ysbin'
    out_dir = sys.argv[2] if len(sys.argv) > 2 else 'C:/Users/sw/Desktop/Elfhime_translation/dialogue'
    os.makedirs(out_dir, exist_ok=True)
    summary = []
    grand_total = 0
    for fn in sorted(os.listdir(src_dir)):
        m = re.match(r'^yst(\d{5})\.ybn$', fn)
        if not m:
            continue
        path = os.path.join(src_dir, fn)
        try:
            lines = extract_dialogue(path)
        except Exception as e:
            print(f'! {fn}: {e}')
            continue
        if not lines:
            continue
        out_name = f'yst{m.group(1)}.json'
        with open(os.path.join(out_dir, out_name), 'w', encoding='utf-8') as g:
            json.dump({'source': fn, 'count': len(lines), 'lines': lines}, g, ensure_ascii=False, indent=1)
        summary.append({'source': fn, 'count': len(lines)})
        grand_total += len(lines)
    with open(os.path.join(out_dir, '_summary.json'), 'w', encoding='utf-8') as g:
        json.dump({'total_lines': grand_total, 'scripts': summary}, g, ensure_ascii=False, indent=1)
    print(f'Wrote dialogue for {len(summary)} scripts; {grand_total} total lines.')
