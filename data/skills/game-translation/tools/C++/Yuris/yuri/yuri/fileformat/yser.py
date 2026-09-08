from .common import *
YseMagic = b'YSER'
SYseHead = St('<4sIII')
TYseHead = tuple[bytes, int, int, int]


@dataclass(slots=True)
class Err:
    id: int
    msg: str

    @classmethod
    def read(cls, r: Rdr): return cls(r.ui(4), r.sz())


@dataclass(slots=True)
class YSER:
    ver: int
    errs: list[Err]

    @classmethod
    def read(cls, r: Rdr, *, v: int | None = None):
        mag, v_, nerr, pad = cast(TYseHead, r.unpack(SYseHead))
        assert mag == YseMagic, f'not YSE magic: {mag}'
        assert (v := v or v_) in VerRange, f'unsupported version: {v}'
        assert pad == 0, f'nonzero padding: {pad:0>8x}'
        errs = [Err.read(r) for _ in range(nerr)]
        r.assert_eof(v)
        return cls(v, errs)
