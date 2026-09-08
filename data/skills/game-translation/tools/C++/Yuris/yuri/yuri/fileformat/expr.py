from .common import *
from enum import nonmember
from collections.abc import Buffer, Sized


class Typ(IntEnum):
    Unk = 0
    Int = 1
    Flt = 2
    Str = 3
    def tyq(self): return Tyq.STR if self == Typ.Str else Tyq.NUM


class Tyq(IntEnum):
    X23 = 0x23  # ToS in V200
    STR = 0x24
    NUM = 0x40
    X60 = 0x60


class IOpA(IntEnum):
    I8 = 0x0142
    I16 = 0x0257
    I32 = 0x0449
    I64 = 0x084C
    F64 = 0x0846
    STR = nonmember(0x4D)


class IOpV(IntEnum):
    VAR = 0x0348
    ARR = 0x0376
    IDXBEG = 0x0356


class IOpB(IntEnum):
    IDXEND = 0x0129
    NOP = 0x2C
    TOI = 0x69
    TOS = 0x73
    NEG = 0x52
    MUL = 0x2A
    DIV = 0x2F
    MOD = 0x25
    ADD = 0x2B
    SUB = 0x2D
    LT = 0x3C
    LE = 0x53
    GT = 0x3E
    GE = 0x5A
    EQ = 0x3D
    NE = 0x21
    BAND = 0x41
    BOR = 0x4F
    BXOR = 0x5E
    LAND = 0x26
    LOR = 0x7C


STyqIdx = SOpcLen = St('<BH')
TIns = IOpB | tuple[IOpV, Tyq, int] | str | Buffer \
    | tuple[Lit[IOpA.F64], float] | tuple[IOpA, int]


def read_ins(r: Rdr) -> TIns:
    if (tri := r.ui(3)) in IOpB:
        r.idx += tri == IOpB.IDXEND
        return IOpB(tri)
    if tri in IOpV:
        tyq, idx = r.unpack(STyqIdx)
        return (IOpV(tri), Tyq(tyq), idx)
    match divmod(tri, 0x100):
        case (l, IOpA.STR): return r.str(l)
        case (8, 0x46): return (IOpA.F64, r.f64())  # 08, 46
        case (n, _): return (IOpA(tri), r.si(n))


def many_ins(r: Rdr) -> list[TIns]:
    l = len(r.b)
    # if l > 0:
    #     print(*map(hex, r.b))
    lst: list[TIns] = []
    while r.idx < l:
        lst.append(read_ins(r))
    return lst


def ins_tob(ins: TIns, e: str):
    if isinstance(ins, str):
        ins = bytes(ins, e)
    if isinstance(ins, Buffer):
        assert isinstance(ins, Sized)
        return SOpcLen.pack(IOpA.STR, len(ins))+ins
    match ins:
        case IOpB.IDXEND: return b'\x29\x01\x00\x00'
        case IOpB(v): return v.to_bytes(3, LE)
        case (IOpA.F64, f): return b'\x46\x08\x00'+F64.pack(f)
        case (IOpA(v), i): return v.to_bytes(3, LE)+i.to_bytes(v >> 8, LE, signed=True)
        case (v, tyq, idx): return v.to_bytes(3, LE)+STyqIdx.pack(tyq, idx)


STRV_TRANS = {ord('\\'): '\\\\'}


class Ins:
    to_b = staticmethod(ins_tob)
    read = staticmethod(read_ins)
    read_many = staticmethod(many_ins)

    @staticmethod
    def escape_str(s: str):
        segs: list[str] = []
        for i, c in enumerate(s):
            if c == '\\':
                segs.append('\\\\')
            else:
                segs.append(c)
        return ''.join(segs)

    @staticmethod
    def intv(i: int):
        if -0x80 <= i <= 0x7F:
            return (IOpA.I8, i)
        if -0x8000 <= i <= 0x7FFF:
            return (IOpA.I16, i)
        if -0x80000000 <= i <= 0x7FFFFFFF:
            return (IOpA.I32, i)
        return (IOpA.I64, i)

    @staticmethod
    def pstr_to_ins(s: str):
        # Python str to Yu-Ris str
        assert not ('"' in s and "'" in s)
        if '"' in s:
            res = f"'{Ins.escape_str(s)}'"
        else:
            res = f'"{Ins.escape_str(s)}"'
        assert Ins.ins_to_pstr(res) == s
        return res

    @staticmethod
    def ins_to_pstr(s: str):
        assert s[0] == s[-1]
        in_esc = False
        chars: list[str] = []
        for c in s[1:-1]:
            if in_esc:
                in_esc = False
                match c:
                    case '\\': chars.append('\\')
                    case _: assert False, s
            else:
                if c == '\\':
                    in_esc = True
                else:
                    chars.append(c)
        if in_esc:
            chars.append('\\')
        return ''.join(chars)
