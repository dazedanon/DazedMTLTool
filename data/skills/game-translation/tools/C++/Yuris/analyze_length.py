import struct
with open(r'C:/Users/sw/Desktop/Elfhime/pac/Scripts.ypf', 'rb') as f:
    data = f.read()
ver, cnt, hdr = struct.unpack('<III', data[4:16])

# All names start with "ysbin\\" - encoded with XOR 0xFF
prefix_decoded = b'ysbin\x5c'  # backslash
prefix_xored = bytes(c ^ 0xFF for c in prefix_decoded)
ext_decoded = b'.ybn'
ext_xored = bytes(c ^ 0xFF for c in ext_decoded)

pos = 0x20
results = []
for i in range(cnt):
    if pos + 5 > len(data):
        print(f'EOF at entry {i}')
        break
    h = struct.unpack('<I', data[pos:pos+4])[0]
    nl_byte = data[pos+4]
    name_start = pos+5
    if data[name_start:name_start+6] != prefix_xored:
        print(f'BAD prefix at entry {i} pos=0x{pos:x}: got {data[name_start:name_start+6].hex()} expected {prefix_xored.hex()}')
        break
    idx = data.find(ext_xored, name_start, name_start + 100)
    if idx < 0:
        print(f'no .ybn at entry {i} pos=0x{pos:x}')
        break
    name_len = idx - name_start + 4
    decoded = bytes(b ^ 0xFF for b in data[name_start:name_start+name_len]).decode('cp932')
    results.append((i, pos, h, nl_byte, name_len, decoded))
    pos = pos + 5 + name_len + 22

print(f'parsed {len(results)} entries')
mismatches = [r for r in results if (r[3] ^ 0xff) != r[4]]
print(f'mismatches (length byte != XOR 0xFF): {len(mismatches)}')
for m in mismatches[:30]:
    i, p, h, nlb, l, n = m
    expect = nlb ^ 0xff
    diff = expect - l
    print(f'  entry {i:3} hash=0x{h:08x} nl_byte=0x{nlb:02x} actual_len={l:2} (XOR_FF says {expect}) diff={diff} name={n}')
