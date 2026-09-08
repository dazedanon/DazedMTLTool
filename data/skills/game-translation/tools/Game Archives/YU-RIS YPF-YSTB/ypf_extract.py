"""
YPF (YU-RIS Pack File) extractor for Elfhime (version 0x1E7).

Header (32 bytes):
  char[4]  magic "YPF\0"
  uint32   version (0x1E7)
  uint32   file_count
  uint32   header_size
  char[16] reserved/padding

Per entry (variable length):
  uint32  name_hash
  uint8   name_length_encoded   (usually = name_length ^ 0xFF, but a few
                                 files in this archive encode wrong - we
                                 detect actual end of name by scanning)
  bytes   name (XOR 0xFF, cp932)
  uint8   type
  uint8   compress_flag         (0 = stored, 1 = zlib)
  uint32  raw_size
  uint32  packed_size
  uint64  offset
  uint32  data_hash
"""
import os, sys, struct, zlib, json

XOR_KEY = 0xFF
ENTRY_TAIL_SIZE = 1 + 1 + 4 + 4 + 8 + 4   # type + compress + raw + packed + offset + hash

def read_struct(f, fmt):
    size = struct.calcsize(fmt)
    return struct.unpack(fmt, f.read(size))

def detect_name_length(buf, start, hint):
    """Find true name length. Names are ASCII (XOR-FF). When the encoded
    length byte is wrong, scan for first byte that doesn't decode to a
    valid printable ASCII char (which would be the type byte)."""
    # Trust the hint if it gives a fully valid ASCII name
    def is_valid_name_bytes(b):
        try:
            s = bytes(c ^ XOR_KEY for c in b).decode('cp932')
        except UnicodeDecodeError:
            return False
        return all(0x20 <= ord(ch) < 0x7f for ch in s)
    if hint > 0 and start + hint <= len(buf) and is_valid_name_bytes(buf[start:start+hint]):
        # also verify the byte after looks like a small type id (< 32)
        if start + hint < len(buf) and buf[start+hint] < 32:
            return hint
    # otherwise scan: keep adding bytes while still valid ASCII after XOR
    n = 0
    while start + n < len(buf):
        bx = buf[start+n] ^ XOR_KEY
        if 0x20 <= bx < 0x7f:
            n += 1
        else:
            break
    return n

def parse_ypf(ypf_path):
    with open(ypf_path, 'rb') as f:
        blob = f.read()
    if blob[:4] != b'YPF\x00':
        raise ValueError('Not a YPF file')
    version, count, hdr_size = struct.unpack('<III', blob[4:16])
    pos = 0x20
    entries = []
    for i in range(count):
        if pos + 5 > len(blob):
            raise ValueError(f'Truncated header at entry {i}')
        name_hash = struct.unpack('<I', blob[pos:pos+4])[0]
        pos += 4
        nl_byte = blob[pos]
        pos += 1
        hint = nl_byte ^ XOR_KEY
        name_len = detect_name_length(blob, pos, hint)
        if name_len == 0:
            raise ValueError(f'Cannot determine name length at entry {i}')
        name_bytes = bytes(b ^ XOR_KEY for b in blob[pos:pos+name_len])
        try:
            name = name_bytes.decode('cp932')
        except UnicodeDecodeError:
            name = name_bytes.decode('utf-8', errors='replace')
        pos += name_len
        type_id = blob[pos]; pos += 1
        compress = blob[pos]; pos += 1
        raw_size, packed_size = struct.unpack('<II', blob[pos:pos+8]); pos += 8
        offset = struct.unpack('<Q', blob[pos:pos+8])[0]; pos += 8
        data_hash = struct.unpack('<I', blob[pos:pos+4])[0]; pos += 4
        entries.append({
            'name_hash': name_hash,
            'name': name,
            'name_len_hint': hint,
            'name_len_actual': name_len,
            'type': type_id,
            'compress': compress,
            'raw_size': raw_size,
            'packed_size': packed_size,
            'offset': offset,
            'data_hash': data_hash,
        })
    return version, entries, blob

def extract_ypf(ypf_path, out_dir):
    version, entries, blob = parse_ypf(ypf_path)
    print(f'YPF version 0x{version:X}, {len(entries)} entries -> {out_dir}')
    os.makedirs(out_dir, exist_ok=True)
    manifest = []
    errors = 0
    for i, e in enumerate(entries):
        data = blob[e['offset']:e['offset']+e['packed_size']]
        if e['compress'] == 1:
            try:
                data = zlib.decompress(data)
            except zlib.error as err:
                errors += 1
                print(f"  ! zlib error on {e['name']}: {err}")
                continue
            if len(data) != e['raw_size']:
                print(f"  ! size mismatch {e['name']}: got {len(data)} expected {e['raw_size']}")
        rel = e['name'].replace('\\', '/').lstrip('/')
        out_path = os.path.join(out_dir, rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'wb') as g:
            g.write(data)
        manifest.append({
            'name': e['name'],
            'type': e['type'],
            'compress': e['compress'],
            'raw_size': e['raw_size'],
            'packed_size': e['packed_size'],
            'offset': e['offset'],
        })
        if (i+1) % 500 == 0:
            print(f'  {i+1}/{len(entries)}')
    with open(os.path.join(out_dir, '_manifest.json'), 'w', encoding='utf-8') as g:
        json.dump({'version': version, 'count': len(entries), 'entries': manifest}, g, ensure_ascii=False, indent=1)
    print(f'  done: {len(entries)} ({errors} errors)')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print('usage: ypf_extract.py <input.ypf> <out_dir>')
        sys.exit(1)
    extract_ypf(sys.argv[1], sys.argv[2])
