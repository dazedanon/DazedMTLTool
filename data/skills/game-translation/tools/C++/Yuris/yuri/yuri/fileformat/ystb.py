from .common import *
from .yscm import MCmd
from .expr import Typ, TIns, many_ins
from xor_cipher import cyclic_xor_in_place
SArg = St('<HBBII')
SArg2xxR = St('<HBB')
SCmdV200 = St('<BBI')
SCmdV300 = St('<BBH')
KEY_200 = 0x07B4024A
KEY_290 = 0xD36FAC96
YstbMagic = b'YSTB'
SYstbHead = St('<4s7I')
AOpChar: list[str] = ['=', '+=', '-=', '*=', '/=', '%=', '&=', '|=', '^=']


class AOp(IntEnum):
    def __str__(self): return AOpChar[self]
    EQL = 0
    ADD = 1
    SUB = 2
    MUL = 3
    DIV = 4
    MOD = 5
    BAND = 6
    BOR = 7
    BXOR = 8


@dataclass(slots=True)
class RArg:
    id: int
    typ: Typ
    aop: AOp
    siz: int
    off: int
    dat: None | str | list[TIns]

    @classmethod
    def read(cls, r: Rdr, word_enc: str, dat: bytes | None = None, word: bool = False):
        da = None
        id_, typ, aop, siz, off = r.unpack(SArg)
        if dat is not None:
            assert len(dat := dat[off:off+siz]) == siz
            da = str(dat, word_enc) if word else many_ins(Rdr(dat, r.enc))
        # YSCom used some uninitialized value for typ in var defs
        return cls(id_, Typ(typ & 0b11), AOp(aop), siz, off, da)

    @classmethod
    def readV2xxR(cls, r: Rdr, v290: bool):
        id_, typ, aop = r.unpack(SArg2xxR)
        siz = r.ui(4) if v290 else 0
        return cls(id_, Typ(typ), AOp(aop), siz, 0, None)


@dataclass(slots=True)
class RCmd:
    off: int
    lno: int
    code: int
    args: list[RArg]
    npar: int  # V3xx: parameter count for GOSUB, RETURN

    @classmethod
    def readV2xx(cls, r: Rdr, dat: bytes, v: int, codes: CmdCodes, word_enc: str):
        off = r.idx
        c, na, lno = r.unpack(SCmdV200)
        if c == codes.RETURNCODE:
            assert na == 1
            return cls(off, lno, c, [RArg.readV2xxR(r, v == 290)], 0)
        return cls(off, lno, c, cls._readArgs(r, na, dat, c, codes, word_enc), 0)

    @classmethod
    def readV300(cls, r: Rdr, ra: Rdr, rl: Rdr, dat: bytes, codes: CmdCodes, word_enc: str):
        off = r.idx
        lno = rl.ui(4)
        c, na, npar = r.unpack(SCmdV300)
        # print(c, na, npar)
        if c == codes.RETURNCODE:
            assert na == 1
            return cls(off, lno, c, [RArg.read(ra, word_enc, None)], npar)
        return cls(off, lno, c, cls._readArgs(ra, na, dat, c, codes, word_enc), npar)

    @staticmethod
    def _readArgs(ra: Rdr, na: int, dat: bytes, c: int, codes: CmdCodes, word_enc: str) -> list[RArg]:
        match c:
            case codes.IF | codes.ELSE if na == 3:
                return [RArg.read(ra, word_enc, dat), RArg.read(ra, word_enc), RArg.read(ra, word_enc)]
            case codes.ELSE:
                assert na == 0
                return []
            case codes.LOOP:
                assert na == 2
                return [RArg.read(ra, word_enc, dat), RArg.read(ra, word_enc)]
            case codes.WORD:
                assert na == 1
                return [RArg.read(ra, word_enc, dat, True)]
            case _: return [RArg.read(ra, word_enc, dat) for _ in range(na)]


@dataclass(slots=True)
class YSTB:
    ver: int
    key: int
    cmds: list[RCmd]
    codes: CmdCodes

    @classmethod
    def read(cls, f: BinIO, codes: CmdCodes, *, key: int | None = None,
             v: int | None = None, enc: str = CP932, word_enc: str | None = None):
        mag, v_, *rest = cast(Ints, SYstbHead.unpack(f.read(32)))
        assert mag == YstbMagic, f'not YSTB magic: {mag}'
        assert (v := v or v_) in VerRange, f'unsupported version: {v}'
        key = (KEY_290 if v >= 290 else KEY_200) if key is None else key
        word_enc = word_enc or enc
        kbs = key.to_bytes(4)
        if v < 300:
            lcmd, lexp, exp_off, *pads = rest
            assert not any(pads), f'nonzero in padding: {pads}'
            assert 32+lcmd == exp_off  # cpython/issues/133492
            assert f.readinto(dcmd := bytearray(lcmd)) == lcmd  # type: ignore
            assert f.readinto(dexp := bytearray(lexp)) == lexp  # type: ignore
            cyclic_xor_in_place(dcmd, kbs)
            cyclic_xor_in_place(dexp, kbs)
            rc = Rdr(dcmd, enc)
            cmds: list[RCmd] = []
            while rc.idx < lcmd:
                cmds.append(RCmd.readV2xx(rc, dexp, v, codes, word_enc))
            return cls(v, key, cmds, codes)
        ncmd, lcmd, larg, lexp, llno, pad = rest
        assert ncmd * 4 == lcmd == llno
        assert larg % 12 == 0
        assert pad == 0  # cpython/issues/133492
        assert f.readinto(dcmd := bytearray(lcmd)) == lcmd  # type: ignore
        assert f.readinto(darg := bytearray(larg)) == larg  # type: ignore
        assert f.readinto(dexp := bytearray(lexp)) == lexp  # type: ignore
        assert f.readinto(dlno := bytearray(llno)) == llno  # type: ignore
        # print('cmd', *map(hex, dcmd[0:16]))
        # print('arg', *map(hex, darg[0:16]))
        # print('exp', *map(hex, dexp[0:16]))
        guess = ','.join(map(hex, dlno[0:16]))
        cyclic_xor_in_place(dcmd, kbs)
        cyclic_xor_in_place(darg, kbs)
        cyclic_xor_in_place(dexp, kbs)
        cyclic_xor_in_place(dlno, kbs)
        rc = Rdr(dcmd, enc)
        ra = Rdr(darg, enc)
        rl = Rdr(dlno, enc)
        try:
            cmds = [RCmd.readV300(rc, ra, rl, dexp, codes, word_enc) for _ in range(ncmd)]
        except Exception as e:
            e.add_note('lineno guess key: '+guess)
            raise
        return cls(v, key, cmds, codes)

    def print(self, cmds: Seq[MCmd], f: TextIO = stdout, show_idx: bool = True):
        kcc = self.codes
        f.write(f'YSTB ver={self.ver} key={self.key:0>8x} ncmd={len(self.cmds)}\n')
        for i, cmd in enumerate(self.cmds):
            code = cmd.code
            args = cmd.args
            desc = cmds[cmd.code]
            darg = desc.args
            if not show_idx:
                i = '-'
            f.write(f'[{i}] off={cmd.off} lno={cmd.lno} npar={cmd.npar} {code}:{desc.name}\n')
            match code:
                case kcc.IF | kcc.ELSE if len(args) == 3:
                    f.write('-  cond: '+repr(args[0])+'\n')
                    f.write('-  else: '+repr(args[1])+'\n')
                    f.write('- ifend: '+repr(args[2])+'\n')
                    continue
                case kcc.LOOP:
                    f.write('- count: '+repr(args[0])+'\n')
                    f.write('- break: '+repr(args[1])+'\n')
                    continue
                case kcc.WORD:
                    assert isinstance(dat := args[0].dat, str)
                    f.write('# '+dat+'\n')
                    continue
                case _: pass
            for j, arg in enumerate(args):
                aname = darg[arg.id].name+' ' if arg.id < len(darg) else ''
                f.write(f'- [{j}] {aname}{repr(arg)}\n')
