from .common import *
Magic = b'YSTD'
SYstd = St('<4sIII')
TYstd = tuple[bytes, int, int, int]


@dataclass(slots=True)
class YSTD:
    ver: int
    nvar: int
    ntext: int

    @classmethod
    def read(cls, f: BinIO):
        mag, v, nvar, ntext = cast(TYstd, SYstd.unpack(f.read(16)))
        assert mag == Magic, f'not yst.ybn magic: {mag}'
        assert v in VerRange, f'unsupported version: {v}'
        return cls(v, nvar, ntext)

    def tobytes(self, w_ver: int | None = None):
        return SYstd.pack(Magic, w_ver or self.ver, self.nvar, self.ntext)
