from .common import *
from array import array
from sys import byteorder
from .ypf import THashFn, ver_hash
YslMagic = b'YSLB'
SYslHead = St('<4sII')
TYslHead = tuple[bytes, int, int]
SLblBody = St('<IIHBB')
TLblBody = tuple[int, int, int, int, int]


@dataclass(slots=True)
class Lbl:
    name: str
    pos: int
    iscr: int
    if_l: int
    lo_l: int
    nha: int = 0

    @classmethod
    def read(cls, r: Rdr, h: THashFn):
        nb = r.read(r.byte()).tobytes()
        nh, pos, iscr, if_l, lo_l = cast(TLblBody, r.unpack(SLblBody))
        assert (ha := h(nb, nh)) is None, f'hash(name): expect={nh:0>8x}, actual={ha:0>8x}, name: {nb}'
        return cls(str(nb, r.enc), pos, iscr, if_l, lo_l, nh)

    def __repr__(self):
        return f'Lbl({repr(self.name)}, {self.pos}, {self.iscr}, {self.if_l}, {self.lo_l}, 0x{self.nha:0>8x})'


@dataclass(slots=True)
class YSLB:
    ver: int
    lbls: list[Lbl]

    @classmethod
    def read(cls, r: Rdr, *, v: int | None = None, h: THashFn | None = None):
        mag, v_, nlbl = cast(TYslHead, r.unpack(SYslHead))
        assert mag == YslMagic, f'not YSL magic: {mag}'
        assert (v := v or v_) in VerRange, f'unsupported version: {v}'
        r.idx += 4*256
        h = ver_hash(v, h)
        lbls = [Lbl.read(r, h) for _ in range(nlbl)]
        r.assert_eof(v)
        return cls(v, lbls)

    def print(self, f: TextIO = stdout):
        f.write(f'YSLB ver={self.ver} nlbl={len(self.lbls)}\n')
        f.writelines(f'[{i}] {repr(l)}\n' for i, l in enumerate(self.lbls))

    @staticmethod
    def create(f: BinIO, v: int, lbls: Seq[Lbl], enc: str = CP932, *,
               h: THashFn | None = None, w_ver: int | None = None):
        assert v in VerRange, f'unsupported version: {v}'
        h = ver_hash(v, h)
        ls = [(nb := bytes(l.name, enc), h(nb, 0) or 0, l) for l in lbls]
        ls.sort(key=lambda t: t[1])
        idxs = array('I', (0 for _ in range(256)))
        for _, ha, _ in ls:
            idxs[ha >> 24] += 1
        idx = 0
        for i in range(0, 256):
            idxs[i], idx = idx, idx+idxs[i]
        if byteorder == 'big':
            idxs.byteswap()
        f.write(SYslHead.pack(YslMagic, w_ver or v, len(ls)))
        f.write(idxs)
        for nb, nh, l in ls:
            f.writelines((len(nb).to_bytes(), nb))
            f.write(SLblBody.pack(nh, l.pos, l.iscr, l.if_l, l.lo_l))
