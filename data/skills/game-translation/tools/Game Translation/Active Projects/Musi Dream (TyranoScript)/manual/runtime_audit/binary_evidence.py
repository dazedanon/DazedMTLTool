"""Read-only, build-specific Electron app search order evidence."""
from pathlib import Path
import json
import pefile
import capstone

audit = Path(__file__).resolve().parent
game = audit.parents[2]
exe = game / 'musi_dream.exe'
data = exe.read_bytes()
pe = pefile.PE(str(exe), fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
cs = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
cs.detail = True
evidence = {'executable': str(exe), 'size': len(data), 'sections': []}
for address, size in [(0x140362433, 0x50), (0x14036281D, 0xF0), (0x1403C7670, 0x10)]:
    offset = pe.get_offset_from_rva(address - base)
    rows = []
    for ins in cs.disasm(data[offset:offset + size], address):
        row = {'address': hex(ins.address), 'instruction': ins.mnemonic + ' ' + ins.op_str}
        for op in ins.operands:
            if op.type == capstone.x86.X86_OP_MEM and op.mem.base == capstone.x86.X86_REG_RIP:
                target = ins.address + ins.size + op.mem.disp
                try:
                    pos = pe.get_offset_from_rva(target - base)
                    row['referenced_address'] = hex(target)
                    row['referenced_bytes'] = repr(data[pos:pos + 60])
                except Exception:
                    pass
        rows.append(row)
    evidence['sections'].append(rows)
sentinel = b'dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'
fuse = data.index(sentinel) + len(sentinel)
version, size = data[fuse:fuse + 2]
evidence['fuses'] = {'sentinel_offset': fuse - len(sentinel), 'version': version, 'count': size,
                     'bytes': data[fuse + 2:fuse + 2 + size].decode('ascii')}
(audit / 'binary_evidence.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf8')
print(json.dumps(evidence['fuses']))
