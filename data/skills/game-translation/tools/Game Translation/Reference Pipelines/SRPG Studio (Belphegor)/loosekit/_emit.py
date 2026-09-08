"""Extract the load_table shellcode from the COFF .obj; verify it has no relocations."""
import struct, os

HERE = os.path.dirname(os.path.abspath(__file__))
obj = open(os.path.join(HERE, 'load_table.obj'), 'rb').read()
mach, nsec, ts, symoff, nsym, optsz, chars = struct.unpack_from('<HHIIIHH', obj, 0)
strtab = symoff + nsym * 18

def symname(o):
    if obj[o:o + 4] == b'\0\0\0\0':
        so = struct.unpack_from('<I', obj, o + 4)[0]
        e = obj.index(b'\0', strtab + so)
        return obj[strtab + so:e].decode()
    return obj[o:o + 8].rstrip(b'\0').decode()

# locate the load_table symbol -> its section index + offset
entry_sec = entry_off = None
i = 0
while i < nsym:
    o = symoff + i * 18
    nm = symname(o)
    val, secn, typ, cls, naux = struct.unpack_from('<IhHBB', obj, o + 8)
    if nm in ('_load_table@4', 'load_table', '_load_table'):
        entry_sec, entry_off = secn, val
        print("load_table -> section %d offset 0x%x" % (secn, val))
    i += 1 + naux
assert entry_sec is not None, "load_table symbol not found"

# read that section header (sections are 1-based in symbol table)
o = 20 + (entry_sec - 1) * 40
name = obj[o:o + 8].rstrip(b'\0').decode()
vsz, va, rsz, prd, preloc, plnno, nreloc, nlnno, sc = struct.unpack_from('<IIIIIIHHI', obj, o + 8)
text = obj[prd:prd + rsz]
print("section '%s' size %d relocations %d" % (name, rsz, nreloc))
for k in range(nreloc):
    ro = preloc + k * 10
    vaddr, sidx, rtyp = struct.unpack_from('<IIH', obj, ro)
    print("  RELOC @0x%x type %d -> %s" % (vaddr, rtyp, symname(symoff + sidx * 18)))

open(os.path.join(HERE, 'load_table.bin'), 'wb').write(text)
print("wrote load_table.bin (%d bytes), entry offset 0x%x, relocs %d" % (len(text), entry_off, nreloc))
