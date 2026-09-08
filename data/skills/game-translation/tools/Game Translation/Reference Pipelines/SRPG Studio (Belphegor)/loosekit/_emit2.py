"""Extract a named function's shellcode from a COFF .obj; verify no relocations.

    python _emit2.py <obj> <symbol> <out.bin>
"""
import struct, os, sys

obj_path, want_sym, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
obj = open(obj_path, 'rb').read()
mach, nsec, ts, symoff, nsym, optsz, chars = struct.unpack_from('<HHIIIHH', obj, 0)
strtab = symoff + nsym * 18


def symname(o):
    if obj[o:o + 4] == b'\0\0\0\0':
        so = struct.unpack_from('<I', obj, o + 4)[0]
        e = obj.index(b'\0', strtab + so)
        return obj[strtab + so:e].decode()
    return obj[o:o + 8].rstrip(b'\0').decode()


entry_sec = entry_off = None
i = 0
while i < nsym:
    o = symoff + i * 18
    nm = symname(o)
    val, secn, typ, cls, naux = struct.unpack_from('<IhHBB', obj, o + 8)
    if nm in ('_%s@4' % want_sym, want_sym, '_%s' % want_sym):
        entry_sec, entry_off = secn, val
        print("%s -> section %d offset 0x%x" % (want_sym, secn, val))
    i += 1 + naux
assert entry_sec is not None, "%s symbol not found" % want_sym

o = 20 + (entry_sec - 1) * 40
name = obj[o:o + 8].rstrip(b'\0').decode()
vsz, va, rsz, prd, preloc, plnno, nreloc, nlnno, sc = struct.unpack_from('<IIIIIIHHI', obj, o + 8)
text = obj[prd:prd + rsz]
print("section '%s' size %d relocations %d" % (name, rsz, nreloc))
for k in range(nreloc):
    ro = preloc + k * 10
    vaddr, sidx, rtyp = struct.unpack_from('<IIH', obj, ro)
    print("  RELOC @0x%x type %d -> %s" % (vaddr, rtyp, symname(symoff + sidx * 18)))
assert nreloc == 0, "shellcode has relocations -- not position-independent"
open(out_path, 'wb').write(text)
print("wrote %s (%d bytes)" % (out_path, len(text)))
