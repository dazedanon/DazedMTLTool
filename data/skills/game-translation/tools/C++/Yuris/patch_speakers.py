"""
Patch yst00080.ybn to replace Japanese speaker display names with English ones.

The engine's dialogue lines use 【JapaneseKey】 to look up a speaker in the
table, then renders the table's *display* name in the speaker plate. We
keep the JapaneseKey untouched (so all dialogue files keep matching) and
only rewrite the display names.

Input: a JSON map { "侍女": "Handmaid", "アイリア": "Aria", ... }
Missing entries are left as the original Japanese.

Centering: the plate renders text left-aligned starting from the left
edge of its text area. To visually center an English name, we prepend
ASCII spaces. Each ASCII char in EN mode renders at half-width; a Japanese
fullwidth char is 2 half-widths. The plate fits roughly TARGET_HW=10
half-width slots, so pad = (10 - len(name_in_half_widths)) // 2.

Set the special key "_target_half_widths" in the mapping JSON to override
the target. Set "_no_pad": true (top-level) to disable padding entirely.
"""
import os, sys, struct, json, re

KEY = bytes.fromhex('605e414a')

def xor_apply(data):
    return bytes(b ^ KEY[i & 3] for i, b in enumerate(data))

# Inner-content extractor: each speaker-table arg is "M<sz_le16>\"...\""
def parse_m_inner(b):
    if len(b) < 4 or b[0] != 0x4d: return None
    size = struct.unpack('<H', b[1:3])[0]
    if 3 + size > len(b): return None
    payload = b[3:3+size]
    if size >= 2 and payload[0] == 0x22 and payload[-1] == 0x22:
        return payload[1:-1]
    return None

def make_m_record(text):
    payload = b'"' + text + b'"'
    return b'M' + struct.pack('<H', len(payload)) + payload

def patch_yst00080(in_path, mapping_json, out_path):
    with open(in_path, 'rb') as f:
        blob = f.read()
    if blob[:4] != b'YSTB':
        raise ValueError('not YSTB')
    ver, ic, code_sz, arg_sz, str_sz, line_sz, reserved = struct.unpack('<7I', blob[4:32])
    code = xor_apply(blob[32:32+code_sz])
    args = bytearray(xor_apply(blob[32+code_sz:32+code_sz+arg_sz]))
    strs = bytearray(xor_apply(blob[32+code_sz+arg_sz:32+code_sz+arg_sz+str_sz]))
    lines = blob[32+code_sz+arg_sz+str_sz:]

    with open(mapping_json, 'r', encoding='utf-8') as f:
        raw_mapping = json.load(f)
    target_hw = int(raw_mapping.get('_target_half_widths', 10))
    no_pad = bool(raw_mapping.get('_no_pad', False))
    mapping = {k: v for k, v in raw_mapping.items() if not k.startswith('_')}

    def display_width_hw(s):
        """Visual width in half-width slots: ASCII = 1, anything else = 2."""
        return sum(1 if ord(c) < 0x80 else 2 for c in s)

    def center_pad_bytes(name):
        """Return raw cp932-encoded bytes for the display name, with a
        leading run of cp1252 non-breaking-space bytes (0xA0) sized for
        center alignment. NBSP is used because the engine strips ASCII
        spaces from the start of the speaker display string."""
        encoded = name.encode('cp932')
        if no_pad:
            return encoded
        w = display_width_hw(name)
        if w >= target_hw:
            return encoded
        pad = (target_hw - w) // 2
        return b'\xa0' * pad + encoded

    arg_pos = 0
    n_patched = 0
    n_seen = 0
    for i in range(ic):
        op = code[i*4]
        argc = code[i*4+1]
        if op == 0x2c and argc >= 3:
            # Read arg0 (function name) and only proceed for es.CHAR.NAME
            t0, sz0, off0 = struct.unpack('<3I', args[arg_pos:arg_pos+12])
            inner0 = parse_m_inner(strs[off0:off0+sz0]) if 0 <= off0 < len(strs) else None
            if inner0 == b'es.CHAR.NAME':
                # arg1 = bracketed key, arg2 = display name
                a1 = struct.unpack('<3I', args[arg_pos+12:arg_pos+24])
                a2 = struct.unpack('<3I', args[arg_pos+24:arg_pos+36])
                key_inner = parse_m_inner(strs[a1[2]:a1[2]+a1[1]])
                disp_inner = parse_m_inner(strs[a2[2]:a2[2]+a2[1]])
                if key_inner and disp_inner:
                    n_seen += 1
                    # The bracketed key looks like "【侍女】"; strip 【】 to get the lookup name.
                    key_str = key_inner.decode('cp932')
                    m = re.match(r'^【(.*)】$', key_str)
                    if m and m.group(1) in mapping:
                        new_record = make_m_record(center_pad_bytes(mapping[m.group(1)]))
                        new_off = len(strs)
                        strs.extend(new_record)
                        args[arg_pos+24:arg_pos+36] = struct.pack('<3I', a2[0], len(new_record), new_off)
                        n_patched += 1
        arg_pos += argc * 12

    new_strs = xor_apply(bytes(strs))
    new_args = xor_apply(bytes(args))
    new_code = blob[32:32+code_sz]
    header = struct.pack('<4s7I', b'YSTB', ver, ic, code_sz,
                         len(args), len(strs), line_sz, reserved)
    out = header + new_code + new_args + new_strs + lines
    with open(out_path, 'wb') as f:
        f.write(out)
    print(f'wrote {out_path}: speaker registrations seen={n_seen} patched={n_patched}')

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print('usage: patch_speakers.py <yst00080.ybn> <mapping.json> <out.ybn>')
        sys.exit(1)
    patch_yst00080(sys.argv[1], sys.argv[2], sys.argv[3])
