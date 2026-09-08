from __future__ import annotations
from .common import *
from io import BytesIO
from struct import Struct
from collections.abc import Buffer
from murmurhash2 import murmurhash2 as _mmh2
Ent = tuple[str, int, int, bytes, int]  # name, k, c, data, l
try:
    import deflate
    def ddec(b: Buffer, ul: int): return deflate.zlib_decompress(b, ul)
    def dcom(b: Buffer): return deflate.zlib_compress(b, 12)
    compress = dcom
    decompress = ddec
    crc32 = deflate.crc32
    adler32 = deflate.adler32
except ModuleNotFoundError:
    from zlib import crc32, adler32, compress as zcom_, decompress as zdec_
    def decompress(b: Buffer, ul: int): return zdec_(b)
    def compress(b: Buffer): return zcom_(b, level=9)


def make_swap(*args: tuple[int, int]):
    bs = bytearray(range(256))
    for i, j in args:
        bs[i], bs[j] = bs[j], bs[i]
    return bs


YpfMagic = b'YPF\0'
YpfPad16 = b'\0'*16
SYpfHead = Struct('<4s3I16s')
TYpfHead = tuple[bytes, int, int, int, bytes]
SEntName = Struct('<IB')
TEntName = tuple[int, int]
SEnt_32B = Struct('<BBIIII')
SEnt_64B = Struct('<BBIIQI')
TEnt = tuple[int, int, int, int, int, int]
THashFn = Callable[[bytes, int], int | None]
NLSwaps = ((6, 53), (9, 11), (12, 16), (13, 19), (21, 27), (28, 30), (32, 35), (38, 41), (44, 47))
NLMapV000 = make_swap((3, 72), (17, 25), (46, 50), *NLSwaps)
NLMapV500 = make_swap((3, 10), (17, 24), (20, 46), *NLSwaps)
NBXorV000 = bytes(i ^ 0xff for i in range(256))
NBXorV290 = bytes(c ^ 0x40 for c in NBXorV000)
NBXorV500 = bytes(c ^ 0x36 for c in NBXorV000)
def no_hash(d: bytes, e: int): return None
def hashA32(d: bytes, e: int): return h if (h := adler32(d)) != e else None
def hashCRC(d: bytes, e: int): return h if (h := crc32(d, 0)) != e else None
def hashMMH(d: bytes, e: int): return h if (h := _mmh2(d, 0)) != e else None
def entname(f: BinIO) -> TEntName: return SEntName.unpack(f.read(5))
def ent_32b(f: BinIO) -> TEnt: return SEnt_32B.unpack(f.read(18))
def ent_64b(f: BinIO) -> TEnt: return SEnt_64B.unpack(f.read(22))


def ver_hash(v: int, h: THashFn | None = None):
    if v >= 477:  # real number ?
        h = h or hashMMH
    elif v >= 265:
        # 476: Natsuzora Asterism Trial - CRC32
        h = h or hashCRC
    else:
        h = h or hashA32
    return h


def ver_consts(v: int,
               nl_map: bytes | None = None, nb_xor: bytes | None = None,
               h_name: THashFn | None = None, h_file: THashFn | None = None):
    h_name = ver_hash(v, h_name)
    if v >= 477:  # real number ?
        # 476: Natsuzora Asterism Trial - CRC32
        f_ent = ent_64b
        s_ent = SEnt_64B
        h_file = h_file or hashMMH
    else:
        f_ent = ent_32b
        s_ent = SEnt_32B
        h_file = h_file or hashA32
    nl_map = nl_map or (NLMapV500 if v == 500 else NLMapV000)
    nb_xor = nb_xor or (NBXorV500 if v == 500 else NBXorV290 if v == 290 else NBXorV000)
    return nl_map, nb_xor, h_name, h_file, f_ent, s_ent


def read(f: BinIO, *, v: int | None = None, enc: str = 'cp932',
         nl_map: bytes | None = None, nb_xor: bytes | None = None,
         h_name: THashFn | None = None, h_file: THashFn | None = None,
         log: TextIO | None = None, do_decompress: bool = True):
    mag, v_, n, l, pad = cast(TYpfHead, SYpfHead.unpack(f.read(32)))
    assert mag == YpfMagic, f'not YPF magic: {mag}'
    assert pad == YpfPad16, f'nonzero in padding: {pad}'
    assert (v := v or v_) in VerRange, f'unsupported version: {v}'
    assert (l := l-32 if v >= 300 else l) >= 0, f'wrong version ?'
    assert (g := len(d := f.read(l))) == l, f'ents: want {l}, got {g}'
    nl_map, nb_xor, h_name, h_file, f_ent, _ = ver_consts(v, nl_map, nb_xor, h_name, h_file)
    fe = BytesIO(d)
    ents: list[Ent] = []
    for _ in range(n):
        nh, nl = entname(fe)
        nb = fe.read(nl_map[nl ^ 0xff]).translate(nb_xor)
        assert (h := h_name(nb, nh)) is None, f'hash(name): expect {nh:0>8x}, actual {h:0>8x}, name={nb}'
        name = nb.decode(enc)
        k, c, ul, cl, off, fh = f_ent(fe)
        f.seek(off)
        assert c <= 1, f'unknown compression {c}, file: {name}'
        assert (g := len(d := f.read(cl))) == cl, f'file: want {cl}, got {g}, file: {name}'
        assert (h := h_file(d, fh)) is None, f'hash(file): expect {fh:0>8x}, actual {h:0>8x}, file: {name}'
        if do_decompress:
            assert (g := len(d := decompress(d, ul) if c else d)) == ul, f'comp: want {ul}, got {g}, file: {name}'
        elif c != 0:
            c = -1
        ents.append((name, k, c, d, ul))
        _ = log and log.write(f'k={k} c={c} ul={ul:<7} cl={cl:<7} file: {name}\n')
    return ents, v


def make(ents: Seq[Ent], v: int, f: BinIO, *, enc: str = 'cp932',
         nl_map: bytes | None = None, nb_xor: bytes | None = None,
         h_name: THashFn | None = None, h_file: THashFn | None = None,
         comp: Callable[[Buffer], bytes] = compress, force_comp: bool = False, log: TextIO | None = None):
    '''Ent[k=-1]: pass in already compressed data'''
    assert v in VerRange, f'unsupported version: {v}'
    off = 32  # name, k, c, data, ul, data_hash
    fents: list[tuple[bytes, int, int, bytes, int, int]] = []
    nl_map, nb_xor, h_name, h_file, _, s_ent = ver_consts(v, nl_map, nb_xor, h_name, h_file)
    for name, k, c, d, ul in ents:
        c = 1 if c == 0 and force_comp else c
        match c:
            case -1: c, cl = 1, len(d)
            case 0: assert (cl := len(d)) == ul, f'len(d)={cl}, ul={ul}, file: {name}'
            case 1:
                assert (ld := len(d)) == ul, f'len(d)={ld}, ul={ul}, file: {name}'
                c, d = (1, cd) if len(cd := comp(d)) < ul else (0, d)
            case _: assert False, f'unknown compression: {c}, file: {name}'
        d = bytes(d) if isinstance(d, bytearray) else d
        fents.append((n := name.encode(enc), k, c, d, ul, h_file(d, 0) or 0))
        off += SEntName.size + len(n) + s_ent.size
        _ = log and log.write(f'k={k} c={c} ul={ul:<7} cl={len(d):<7} file: {name}\n')
    siz = off if v >= 300 else off-32
    f.write(SYpfHead.pack(YpfMagic, v, len(fents), siz, YpfPad16))
    for nb, k, c, d, ul, fh in fents:
        f.write(SEntName.pack(h_name(nb, 0) or 0, nl_map[len(nb)] ^ 0xff))
        f.write(nb.translate(nb_xor))
        f.write(s_ent.pack(k, c, ul, cl := len(d), off, fh))
        off += cl
    _ = log and log.write('writing\n')
    f.writelines(t[3] for t in fents)
