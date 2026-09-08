from __future__ import annotations
from typing import Any
from ..fileformat.expr import *
CmdSkip = Callable[[int], bool]
PostIns = Callable[[bytearray, int, TIns], Any]  # expr_dat, pre_len, ins
def SkipLabel(v: int): return True
def SkipNever(v: int): return False
def SkipGVDef(v: int): return v >= 300 or v == 290


@dataclass(slots=True)
class Cmd:
    code: int
    args: Seq[Arg]
    line: int
    npar: int = 0
    cmds_idx: int = -1
    cmds_off: int = -1
    expr_off: int = -1
    skip: CmdSkip = SkipNever


@dataclass(slots=True)
class Arg:
    aid: int
    typ: int
    aop: int
    dat: ArgData
    expr_off: int = -1
    expr_siz: int = -1

    def size(self, ver: int):
        if ver >= 300 or not isinstance(self.dat, int):
            return 12
        return 8 if ver == 290 else 4

    def to_bs(self, ver: int):
        if isinstance(dat := self.dat, int):
            if ver >= 300:
                return TArgFull.pack(self.aid, self.typ, self.aop, dat, 0)
            elif ver == 290:
                return TArgR290.pack(self.aid, self.typ, self.aop, dat)
            else:
                return TArgR200.pack(self.aid, self.typ, self.aop)
        elif isinstance(dat, Cmd):
            if ver >= 300:
                return TArgFull.pack(self.aid, self.typ, self.aop, dat.cmds_idx, dat.expr_off)
            else:
                return TArgFull.pack(self.aid, self.typ, self.aop, dat.cmds_off, dat.expr_off)
        elif dat is None:
            return TArgFull.pack(self.aid, self.typ, self.aop, 0, 0)
        else:
            return TArgFull.pack(self.aid, self.typ, self.aop, self.expr_siz, self.expr_off)

    def into_expr(self, expr_dat: bytearray, enc: str, post_ins: PostIns | None):
        self.expr_off = beg = len(expr_dat)
        if isinstance(dat := self.dat, int | Cmd | None):
            pass
        elif isinstance(dat, str):
            expr_dat += dat.encode(enc)
        elif isinstance(dat, Buffer):
            expr_dat += dat
        elif post_ins is None:
            expr_dat += b''.join(Ins.to_b(i, enc) for i in dat)
        else:
            for i in dat:
                pre_len = len(expr_dat)
                expr_dat += Ins.to_b(i, enc)
                post_ins(expr_dat, pre_len, i)
        self.expr_siz = len(expr_dat) - beg


Tu32 = St('<I')
TArgR200 = St('<HBB')    # aid:H typ:B aop:B => 4
TArgR290 = St('<HBBI')   # aid:H typ:B aop:B ret:I => 8
TArgFull = St('<HBBII')  # aid:H typ:B aop:B len:I off:I => 12
ArgData = None | Seq[TIns] | Cmd | int | str | Buffer
TCmdV200 = St('<BBI')  # code:B narg:B line:I => 6
TCmdV300 = St('<BBH')  # code:B narg:B npar:H => 4
TYstb200 = St('<4s4I12x')  # YSTB:4s ver,lcmd,lexp,oexp:4I       12x => 32
TYstb300 = St('<4s6I4x')   # YSTB:4s ver,ncmd,lcmd,larg,lexp,llno 4x => 32
TAsmV200 = tuple[bytes, bytearray, bytearray]
TAsmV300 = tuple[bytes, bytearray, bytearray, bytearray, bytearray]


def assemble_ystb(cmds: Seq[Cmd], v: int, enc: str, post_ins: PostIns | None,
                  w_ver: int | None) -> TAsmV200 | TAsmV300:
    cmds_idx = 0
    cmds_off = [0]
    expr_dat = bytearray()
    cmd_size = 4 if v >= 300 else 6
    args_off = [0] if v >= 300 else cmds_off
    for c in cmds:
        c.cmds_idx = cmds_idx
        c.cmds_off = cmds_off[0]
        c.expr_off = len(expr_dat)
        if c.skip(v):
            continue
        cmds_idx += 1
        cmds_off[0] += cmd_size
        for a in c.args:
            args_off[0] += a.size(v)
            a.into_expr(expr_dat, enc, post_ins)
    cmds_dat = bytearray()
    args_dat = bytearray() if v >= 300 else cmds_dat
    lnos_dat = bytearray() if v >= 300 else cmds_dat  # not used in v200
    for c in cmds:
        if c.skip(v):
            continue
        if v >= 300:
            cmds_dat += TCmdV300.pack(c.code, len(c.args), c.npar)
            lnos_dat += Tu32.pack(c.line)
        else:
            cmds_dat += TCmdV200.pack(c.code, len(c.args), c.line)
        for a in c.args:
            args_dat += a.to_bs(v)
    if v >= 300:
        h = TYstb300.pack(b'YSTB', w_ver or v, cmds_idx, len(cmds_dat),
                          len(args_dat), len(expr_dat), len(lnos_dat))
        return (h, cmds_dat, args_dat, expr_dat, lnos_dat)
    else:
        h = TYstb200.pack(b'YSTB', w_ver or v, lc := len(cmds_dat), len(expr_dat), 32+lc)
        return (h, cmds_dat, expr_dat)
