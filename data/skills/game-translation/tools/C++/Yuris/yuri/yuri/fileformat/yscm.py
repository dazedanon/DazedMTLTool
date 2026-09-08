from .expr import *
from .common import *
YscMagic = b'YSCM'
SYscHead = St('<4sIII')
TYscHead = tuple[bytes, int, int, int]


@dataclass(slots=True)
class MArg:
    name: str
    typ: Typ
    unk: int

    @classmethod
    def read(cls, r: Rdr):
        name = r.sz()
        typ, unk = r.read(2)
        return cls(name, Typ(typ), unk)


@dataclass(slots=True)
class MCmd:
    name: str
    args: list[MArg]

    @classmethod
    def read(cls, r: Rdr):
        name = r.sz()
        narg = r.byte()
        return cls(name, [MArg.read(r) for _ in range(narg)])


class dummy:
    def __getattr__(self, k: str) -> int: raise AttributeError(name=k)


@dataclass(slots=True)
class YSCM:
    ver: int
    cmds: list[MCmd]
    errs: list[str]
    b256: memoryview
    cmdcodes: CmdCodes

    @classmethod
    def read(cls, r: Rdr, *, v: int | None = None):
        mag, v_, ncmd, pad = cast(TYscHead, r.unpack(SYscHead))
        assert mag == YscMagic, f'not YSC magic: {mag}'
        assert (v := v or v_) in VerRange, f'unsupported version: {v}'
        assert pad == 0, f'nonzero padding: {pad:0>8x}'
        cmds = [MCmd.read(r) for _ in range(ncmd)]
        errs = [r.sz() for _ in range(NErrStr)]
        b256 = r.read(256)
        r.assert_eof(v)
        cmdcodes = dummy()
        for i, c in enumerate(cmds):
            setattr(cmdcodes, c.name, i)
        return cls(v, cmds, errs, b256, cmdcodes)

    def print(self, f: TextIO = stdout):
        f.write(f'YSCM ver={self.ver} ncmd={len(self.cmds)}\n')
        for i, c in enumerate(self.cmds):
            f.write(f'[{i:>3}] Cmd {repr(c.name)}\n')
            f.writelines(f'[{i:>3}][{j:>2}] Arg {repr(a.name)} {a.typ} {a.unk}\n'
                         for j, a in enumerate(c.args))
