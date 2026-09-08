from .common import *
from .expr import Typ, TIns, many_ins, ins_tob
VInit = tuple[Lit[Typ.Int], int]\
    | tuple[Lit[Typ.Flt], float]\
    | tuple[Lit[Typ.Str], Seq[TIns]]
SVarV000 = St('<B HHBB')
SVarV481 = St('<BBHHBB')
YsvMagic = b'YSVR'
SYsvHead = St('<4sIH')
TYsvHead = tuple[bytes, int, int]


@dataclass(slots=True)
class Var:
    scope: VScope
    scoex: VScoEx
    iscr: int
    ivar: int
    dims: Seq[int]
    init: VInit | None

    @classmethod
    def readV000(cls, r: Rdr):
        sc, iscr, ivar, typ, ndim = cast(Ints, r.unpack(SVarV000))
        scex = VScoEx.SYS if ivar < VMinUsr else VScoEx.DEF
        return cls(VScope(sc), scex, iscr, ivar, *cls._dims_init(r, typ, ndim))

    @classmethod
    def readV481(cls, r: Rdr):
        sc, scex, iscr, ivar, typ, ndim = cast(Ints, r.unpack(SVarV481))
        assert ivar >= VMinUsr or scex == VScoEx.SYS
        return cls(VScope(sc), VScoEx(scex), iscr, ivar, *cls._dims_init(r, typ, ndim))

    @classmethod
    def _dims_init(cls, r: Rdr, typ: int, ndim: int):
        dims = [r.ui(4) for _ in range(ndim)]
        match (typ := Typ(typ)):
            case Typ.Unk: init = None
            case Typ.Int: init = (typ, r.si(8))
            case Typ.Flt: init = (typ, r.f64())
            case Typ.Str:
                buf = r.read(r.ui(2)).tobytes()
                init = (typ, many_ins(Rdr(buf, r.enc)))
        return dims, init

    def writeV000(self, f: BinIO, enc: str):
        typ = 0 if self.init is None else self.init[0]
        f.write(SVarV000.pack(self.scope, self.iscr, self.ivar, typ, len(self.dims)))
        self._write_dims_init(f, enc)

    def writeV481(self, f: BinIO, enc: str):
        typ = 0 if self.init is None else self.init[0]
        f.write(SVarV481.pack(self.scope, self.scoex, self.iscr, self.ivar, typ, len(self.dims)))
        self._write_dims_init(f, enc)

    def _write_dims_init(self, f: BinIO, enc: str):
        f.writelines(d.to_bytes(4, LE) for d in self.dims)
        match self.init:
            case None: pass
            case (Typ.Int, i): f.write(i.to_bytes(8, LE, signed=True))
            case (Typ.Flt, v): f.write(F64.pack(v))
            case (Typ.Str, v):
                bs = list(ins_tob(i, enc) for i in v)
                f.write(sum(map(len, bs)).to_bytes(2, LE))
                f.writelines(bs)


@dataclass(slots=True)
class YSVR:
    ver: int
    vars: list[Var]

    @classmethod
    def read(cls, r: Rdr, *, v: int | None = None):
        mag, v_, nvar = cast(TYsvHead, r.unpack(SYsvHead))
        assert mag == YsvMagic, f'not YSV magic: {mag}'
        assert (v := v or v_) in VerRange, f'unsupported version: {v}'
        fun = Var.readV481 if v >= 481 else Var.readV000
        vars = [fun(r) for _ in range(nvar)]
        r.assert_eof(v)
        return cls(v, vars)

    def write(self, f: BinIO, enc: str = CP932, *, v: int | None = None, w_ver: int | None = None):
        assert (v := v or self.ver) in VerRange, f'unsupported version: {v}'
        f.write(SYsvHead.pack(YsvMagic, w_ver or v, len(self.vars)))
        fun = Var.writeV481 if v >= 481 else Var.writeV000
        for var in self.vars:
            fun(var, f, enc)

    def print(self, f: TextIO = stdout):
        f.write(f'YSVR ver={self.ver} nvar={len(self.vars)}\n')
        f.writelines(f'[{i:>3}] {repr(v)}\n' for i, v in enumerate(self.vars))
