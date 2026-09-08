"""
YPF (YU-RIS Pack File) repacker for Elfhime (version 0x1E7).

Uses the ORIGINAL YPF as a template. For each entry it checks whether the
file in src_dir matches the original packed data; if so, the entry is
copied verbatim (preserving name_hash, data_hash, the per-entry length
byte, the original compressed bytes, and the entry order). For modified
files it recompresses with zlib and recomputes both hashes.

Hash algorithm (verified against original YPF): MurmurHash2 with seed=0,
applied to:
  - filename bytes (cp932) for name_hash
  - packed (compressed) data for data_hash
"""
import os, sys, struct, zlib, json

XOR_KEY = 0xFF
ENTRY_TAIL = 1 + 1 + 4 + 4 + 8 + 4

def le32(n): return struct.pack('<I', n & 0xffffffff)

def murmur2(data, seed=0):
    m = 0x5bd1e995
    length = len(data)
    h = (seed ^ length) & 0xFFFFFFFF
    i = 0
    while length >= 4:
        k = struct.unpack('<I', data[i:i+4])[0]
        k = (k * m) & 0xFFFFFFFF
        k ^= k >> 24
        k = (k * m) & 0xFFFFFFFF
        h = (h * m) & 0xFFFFFFFF
        h ^= k
        i += 4
        length -= 4
    if length >= 3: h ^= data[i+2] << 16
    if length >= 2: h ^= data[i+1] << 8
    if length >= 1:
        h ^= data[i]
        h = (h * m) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * m) & 0xFFFFFFFF
    h ^= h >> 15
    return h & 0xFFFFFFFF

def detect_name_length(buf, start, hint):
    def is_valid(b):
        try:
            s = bytes(c ^ XOR_KEY for c in b).decode('cp932')
        except UnicodeDecodeError:
            return False
        return all(0x20 <= ord(ch) < 0x7f for ch in s)
    if hint > 0 and start + hint <= len(buf) and is_valid(buf[start:start+hint]):
        if start + hint < len(buf) and buf[start+hint] < 32:
            return hint
    n = 0
    while start + n < len(buf):
        bx = buf[start+n] ^ XOR_KEY
        if 0x20 <= bx < 0x7f:
            n += 1
        else:
            break
    return n

def parse_full_ypf(blob):
    """Parse YPF and return (version, [entries...]) where each entry
    preserves the original on-disk encoded length byte."""
    if blob[:4] != b'YPF\x00':
        raise ValueError('not YPF')
    version, count, hdr_size = struct.unpack('<III', blob[4:16])
    pos = 0x20
    entries = []
    for i in range(count):
        name_hash = struct.unpack('<I', blob[pos:pos+4])[0]; pos += 4
        nl_byte = blob[pos]; pos += 1
        hint = nl_byte ^ XOR_KEY
        nlen = detect_name_length(blob, pos, hint)
        name_bytes_xor = bytes(blob[pos:pos+nlen])      # encoded form on disk
        name = bytes(b ^ XOR_KEY for b in name_bytes_xor).decode('cp932')
        pos += nlen
        type_id = blob[pos]; pos += 1
        compress = blob[pos]; pos += 1
        raw_size, packed_size = struct.unpack('<II', blob[pos:pos+8]); pos += 8
        offset = struct.unpack('<Q', blob[pos:pos+8])[0]; pos += 8
        data_hash = struct.unpack('<I', blob[pos:pos+4])[0]; pos += 4
        entries.append({
            'name': name,
            'name_hash': name_hash,
            'nl_byte': nl_byte,
            'name_bytes_xor': name_bytes_xor,
            'type': type_id,
            'compress': compress,
            'raw_size': raw_size,
            'packed_size': packed_size,
            'offset': offset,
            'data_hash': data_hash,
            'packed_data': blob[offset:offset+packed_size],
        })
    return version, entries

def repack(src_dir, original_ypf_path, out_path):
    with open(original_ypf_path, 'rb') as f:
        orig_blob = f.read()
    version, entries = parse_full_ypf(orig_blob)

    new_entries = []
    n_changed = n_kept = 0
    for e in entries:
        local_path = os.path.join(src_dir, e['name'].replace('\\', '/'))
        with open(local_path, 'rb') as f:
            new_raw = f.read()
        # Compare against original raw (= decompressed original)
        if e['compress'] == 1:
            try:
                orig_raw = zlib.decompress(e['packed_data'])
            except zlib.error:
                orig_raw = None
        else:
            orig_raw = e['packed_data']
        if orig_raw == new_raw:
            # Unchanged - reuse everything
            new_entries.append({**e, 'new_packed': e['packed_data']})
            n_kept += 1
        else:
            # Modified - re-pack
            if e['compress'] == 1:
                new_packed = zlib.compress(new_raw, 9)
            else:
                new_packed = new_raw
            new_entries.append({
                **e,
                'raw_size': len(new_raw),
                'packed_size': len(new_packed),
                'data_hash': murmur2(new_packed, 0),
                'new_packed': new_packed,
            })
            n_changed += 1

    # Compute header size from original; it stays the same since name fields
    # and entry count are unchanged.
    header_size = 0x20
    for e in new_entries:
        header_size += 4 + 1 + len(e['name_bytes_xor']) + ENTRY_TAIL

    # Strategy: keep the ORIGINAL file layout intact.
    #   - Unchanged entries keep their original offset and data.
    #   - Modified entries get appended at the end of the file.
    # This makes the file byte-identical to the original wherever no edits
    # were made, and only grows by the diff in (new - old) packed sizes.
    orig_blob_buf = bytearray(orig_blob)
    end_of_file = len(orig_blob_buf)
    appended = bytearray()
    for e in new_entries:
        if e['new_packed'] is e['packed_data']:
            # Unchanged - keep original offset (already set in e['offset'])
            continue
        # Modified - append at end
        e['offset'] = end_of_file + len(appended)
        appended += e['new_packed']

    # Build the final blob: copy original header bytes through end-of-file,
    # then overwrite header entries (offsets/sizes/data_hash for modified
    # entries), then append modified data.
    out = bytearray(orig_blob_buf)
    # Rewrite header entries in place
    pos = 0x20
    for e in new_entries:
        # name_hash + nl_byte + name_bytes_xor unchanged (preserved from orig)
        record_len = 4 + 1 + len(e['name_bytes_xor']) + ENTRY_TAIL
        # Skip past name_hash + nl_byte + name
        meta_off = pos + 4 + 1 + len(e['name_bytes_xor'])
        # type + compress unchanged
        out[meta_off+2:meta_off+2+8] = struct.pack('<II', e['raw_size'], e['packed_size'])
        out[meta_off+10:meta_off+18] = struct.pack('<Q', e['offset'])
        out[meta_off+18:meta_off+22] = struct.pack('<I', e['data_hash'])
        pos += record_len
    assert pos == header_size, f'pos mismatch {pos} vs {header_size}'
    out += appended
    with open(out_path, 'wb') as f:
        f.write(out)
    print(f'wrote {out_path}: {len(new_entries)} entries ({n_changed} modified, {n_kept} unchanged), {len(out)} bytes (orig was {len(orig_blob)})')

if __name__ == '__main__':
    if len(sys.argv) != 4:
        print('usage: ypf_repack.py <src_dir> <original.ypf> <out.ypf>')
        sys.exit(1)
    repack(sys.argv[1], sys.argv[2], sys.argv[3])
