from .common import *
from .yser import Err
from .expr import *
YcdMagic = b'YSCD'
Tu32x2 = St('<2I')
SYcdHead = St('<4sIII')
TYcdHead = tuple[bytes, int, int, int]


@dataclass(slots=True)
class DArg:
    name: str
    unk1: int
    unk2: int
    typ: Typ
    unk: int

    @classmethod
    def read(cls, r: Rdr):
        name = r.sz()
        unk1, unk2, typ, unk = r.read(4)
        return cls(name, unk1, unk2, Typ(typ), unk)


@dataclass(slots=True)
class DCmd:
    name: str
    args: list[DArg]

    @classmethod
    def read(cls, r: Rdr):
        name = r.sz()
        narg = r.byte()
        return cls(name, [DArg.read(r) for _ in range(narg)])


@dataclass(slots=True)
class DVar:
    name: str
    typ: Typ
    dims: list[int]

    @classmethod
    def read(cls, r: Rdr):
        name = r.sz()
        typ, ndim = r.read(2)
        return cls(name, Typ(typ), [r.ui(4) for _ in range(ndim)])


@dataclass(slots=True)
class YSCD:
    ver: int
    cmds: list[DCmd]
    vars: list[DVar]
    errs: list[Err]
    estr: list[str]
    blks: list[memoryview]
    b800: memoryview

    @classmethod
    def read(cls, r: Rdr, *, v: int | None = None):
        mag, v_, ncmd, pad1 = cast(TYcdHead, r.unpack(SYcdHead))
        assert mag == YcdMagic, f'not YSCom.ycd magic: {mag}'
        assert (v := v or v_) in VerRange, f'unsupported version: {v}'
        assert pad1 == 0, f'nonzero in padding: {pad1:0>8x}'
        cmds = [DCmd.read(r) for _ in range(ncmd)]
        nvar, pad2 = cast(Ints, r.unpack(Tu32x2))
        assert nvar < VMinUsr, f'too many vars: {nvar}'
        assert pad2 == 0, f'nonzero in padding: {pad2:0>8x}'
        vars = [DVar.read(r) for _ in range(nvar)]
        nerr, pad3 = cast(Ints, r.unpack(Tu32x2))
        assert pad3 == 0, f'nonzero in padding: {pad3:0>8x}'
        errs = [Err.read(r) for _ in range(nerr)]
        estr = [r.sz() for _ in range(NErrStr)]
        lblk, pad4 = cast(Ints, r.unpack(Tu32x2))
        assert pad4 == 0, f'nonzero in padding: {pad4:0>8x}'
        blks = [r.read(lblk) for _ in range(lblk)]
        b800 = r.read(0x800)
        r.assert_eof(v)
        return cls(v, cmds, vars, errs, estr, blks, b800)

    def print(self, f: TextIO = stdout):
        f.write(f'YSCD ver={self.ver} ncmd={len(self.cmds)} nvar={len(self.vars)}\n')
        f.write('-- CMDS --\n')
        for i, c in enumerate(self.cmds):
            f.write(f'[{i:>3}] Cmd {repr(c.name)}\n')
            f.writelines(f'[{i:>3}][{j:>2}] Arg {repr(a.name)} {a.unk1} {a.unk2} {a.typ} {a.unk}\n'
                         for j, a in enumerate(c.args))
        f.write('-- VARS --\n')
        f.writelines(f'[{i:>3}] {repr(v)}\n' for i, v in enumerate(self.vars))
