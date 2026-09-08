#!/bin/env python3
from __future__ import annotations
import json
from sys import stdout
from os import makedirs, path
from struct import Struct as St
from murmurhash2 import murmurhash2 as _mmh2
from collections import defaultdict as defdict
from typing import Callable, BinaryIO, TextIO, Literal, Any
from zlib import crc32 as _crc32, adler32 as _adl32, decompress
Vmi, Vma = 200, 501  # supports Vmi=..<Vma
def goodver(v: int): return Vmi <= v < Vma
def nohash(b: bytes, e: int): return False
def crc32(b: bytes, e: int): return a if (a := _crc32(b)) != e else False
def mmh2(b: bytes, e: int): return a if (a := _mmh2(b, 0)) != e else False
def adler32(b: bytes, e: int): return a if (a := _adl32(b)) != e else False
def magic(b: bytes): return int.from_bytes(b, 'little')


def swap_trans(*args: tuple[int, int]):
    bs = bytearray(range(256))
    for i, j in args:
        assert bs[i] == i
        assert bs[j] == j
        bs[i], bs[j] = bs[j], bs[i]
    return bs


def decode(b: bytes, e: str):
    try:
        return b.decode(e)
    except UnicodeDecodeError as x:
        x.add_note(f'bytes={b}')
        raise


LE = 'little'
F64 = St('<d')
CP932 = 'cp932'
U32x2 = St('<2I')
U32x3 = St('<3I')
U32x4 = St('<4I')
U32x7 = St('<7I')
U32x8 = St('<8I')
Ints = tuple[int, ...]
YpfMagic = magic(b'YPF\0')
HashFunc = Callable[[bytes, int],  Literal[False] | int]
HashPair = tuple[HashFunc, HashFunc]
V470Hash: HashPair = (mmh2, mmh2)      # 464=..<Vma
V265Hash: HashPair = (crc32, adler32)  # 265=..<464
NoneHash: HashPair = (nohash, nohash)  # Vmi=..<265
NLSwaps = ((6, 53), (9, 11), (12, 16), (13, 19), (21, 27), (28, 30), (32, 35), (38, 41), (44, 47))
NLTransV000 = swap_trans((3, 72), (17, 25), (46, 50), *NLSwaps)  # Vmi=..<500
NLTransV500 = swap_trans((3, 10), (17, 24), (20, 46), *NLSwaps)  # 500
NameXorV000 = bytes(i ^ 0xff for i in range(256))   # Vmi=..<Vma
NameXorV290 = bytes(c ^ 0x40 for c in NameXorV000)  # 290
NameXorV500 = bytes(c ^ 0x36 for c in NameXorV000)  # 500
SYpfEntName = St('<IB')
SYpfEntV000 = St('<BBIIII')  # u32 offset; Vmi=..<470
SYpfEntV470 = St('<BBIIQI')  # u64 offset; 470=..<Vma
def fYpfEntName(f: BinaryIO) -> Ints: return SYpfEntName.unpack(f.read(5))
def fYpfEntV000(f: BinaryIO) -> Ints: return SYpfEntV000.unpack(f.read(18))
def fYpfEntV470(f: BinaryIO) -> Ints: return SYpfEntV470.unpack(f.read(22))


class YPF:
    __slots__ = ['ver', 'files']
    ver: int
    files: list[tuple[str, bytes]]

    def __init__(
        self, f: BinaryIO, *,
        name_encoding: str = CP932,
        name_size_trans: bytes | None = None,
        name_byte_trans: bytes | None = None,
        hash_name_file: HashPair | None = None,
    ):
        m, v, nent, lhdr = U32x4.unpack(f.read(16))
        assert m == YpfMagic
        assert goodver(v)
        assert not any(f.read(16))
        if name_size_trans == None:
            name_size_trans = NLTransV500 if v == 500 else NLTransV000
        if name_byte_trans == None:
            match v:
                case 290: name_byte_trans = NameXorV290
                case 500: name_byte_trans = NameXorV500
                case _: name_byte_trans = NameXorV000
        if hash_name_file == None:
            match v:  # 200-264, 265-466, 470-500
                case v if Vmi <= v < 265: hash_name_file = NoneHash
                case v if 265 <= v < 470: hash_name_file = V265Hash
                case v if 470 <= v < Vma: hash_name_file = V470Hash
                case _: assert False
        hash_name, hash_file = hash_name_file
        f_ent = fYpfEntV470 if v >= 470 else fYpfEntV000
        lhdir = lhdr if v >= 300 else (lhdr+32)  # size of header+entries
        entns: list[tuple[str, Ints]] = []
        for _ in range(nent):
            name_hash, name_size = fYpfEntName(f)
            name_byte = f.read(name_size_trans[name_size ^ 0xff])
            name_byte = name_byte.translate(name_byte_trans)
            assert (a := hash_name(name_byte, name_hash)) == False, \
                f'name_hash: expect={name_hash:0>8x}, actual={a:0>8x}, bytes={name_byte}'
            entns.append((decode(name_byte, name_encoding), f_ent(f)))
        assert (a := f.tell()) == lhdir, f'head_size: expect={lhdir}, actual={a}'
        files: list[tuple[str, bytes]] = []
        for name, (_kind, comp, ul, cl, offset, hash) in entns:
            _, data = f.seek(offset), f.read(cl)
            assert (a := len(data)) == cl, \
                f'read_file: expect={cl}, actual={a}, filename={name}'
            assert (a := hash_file(data, hash)) == False, \
                f'file_hash: expect={hash:0>8x}, actual={a:0>8x}, filename={name}'
            if comp:
                assert (a := len(data := decompress(data))) == ul, \
                    f'decompress: expect={ul}, actual={a}, filename={name}'
            files.append((name, data))
        self.ver = v
        self.files = files

    def extract(self, dst_dir: str, log: TextIO | None = stdout):
        for opath, data in self.files:
            _ = log and log.write(opath+'\n')
            opath = path.join(dst_dir, opath.replace('\\', '/'))
            makedirs(path.dirname(opath), exist_ok=True)
            with open(opath, 'wb') as f:
                f.write(data)


class Rdr:
    __slots__ = ['idx', 'enc', 'buf']
    idx: int
    enc: str
    buf: bytes

    def __init__(self, data: bytes, enc: str = CP932):
        self.idx = 0
        self.enc = enc
        self.buf = data

    def read(self, n: int):
        beg = self.idx
        end = beg+n
        ret = self.buf[beg:end]
        assert (got := len(ret)) == n, f'read: want={n}, got={got}, at={beg}'
        self.idx = end
        return ret

    def byte(self):
        b = self.buf[self.idx]
        self.idx += 1
        return b

    def ui(self, n: int):
        return int.from_bytes(self.read(n), LE, signed=False)

    def si(self, n: int):
        return int.from_bytes(self.read(n), LE, signed=True)

    def bz(self):
        beg = self.idx
        end = self.buf.index(0, beg)
        self.idx = end+1
        return self.buf[beg:end]

    def sz(self, *, enc: str | None = None):
        return decode(self.bz(), enc or self.enc)

    def str(self, n: int, *, enc: str | None = None):
        return decode(self.read(n), enc or self.enc)

    def unpack(self, t: St) -> Ints:
        return t.unpack(self.read(t.size))

    def f64(self) -> float:
        return F64.unpack(self.read(8))[0]

    def assert_eof(self, ver: int):
        i = self.idx
        l = len(self.buf)
        assert i == l, f'incomplete read, idx={i}, len={l}, ver={ver}'


NErrStr = 37
SYscHead = U32x4
YscMagic = magic(b'YSCM')


class MArg:
    __slots__ = ['name', 'typ', 'chk']
    name: str
    typ: int  # 0:Any 1:Int 2:Flt 3:Str
    chk: int  # TODO: meaning?

    def __init__(self, r: Rdr):
        self.name = r.sz()
        self.typ, self.chk = r.read(2)
        assert self.typ <= 3


class MCmd:
    __slots__ = ['name', 'args']
    name: str
    args: list[MArg]

    def __init__(self, r: Rdr):
        self.name = r.sz()
        narg = r.byte()
        self.args = [MArg(r) for _ in range(narg)]


class KnownCmdCode:
    __slots__ = ['IF', 'ELSE', 'LOOP', 'RETURNCODE', 'WORD']
    IF: int
    ELSE: int
    LOOP: int
    RETURNCODE: int
    WORD: int

    def __init__(self, y: YSCM | YSCD):
        dic = {cmd.name: i for i, cmd in enumerate(y.cmds)}
        for name in self.__slots__:
            setattr(self, name, dic[name])


class YSCM:
    __slots__ = ['ver', 'cmds', 'errs', 'b256', 'dic', 'kcc']
    ver: int
    cmds: list[MCmd]
    errs: list[str]
    b256: bytes
    dic: dict[str, int]
    kcc: KnownCmdCode

    def __init__(self, r: Rdr):
        magi, ver, ncmd, pad = r.unpack(SYscHead)
        assert magi == YscMagic
        assert Vmi <= ver < Vma
        assert pad == 0
        self.ver = ver
        self.cmds = [MCmd(r) for _ in range(ncmd)]
        self.errs = [r.sz() for _ in range(NErrStr)]
        self.b256 = r.read(256)
        self.kcc = KnownCmdCode(self)
        r.assert_eof(ver)

    def print(self, f: TextIO):
        f.write('- COMMANDS -\n')
        for i, c in enumerate(self.cmds):
            f.write(f'[{i}]C:{c.name}\n')
            for j, a in enumerate(c.args):
                f.write(f'\t[{i}][{j}]A:{a.name} typ={a.typ} val={a.chk}\n')


class Err:
    __slots__ = ['id', 'msg']
    id: int
    msg: str

    def __init__(self, r: Rdr):
        self.id = r.ui(4)
        self.msg = r.sz()


SYseHead = U32x4
YseMagic = magic(b'YSER')


class YSER:
    __slots__ = ['ver', 'errs']
    ver: int
    errs: list[Err]

    def __init__(self, r: Rdr):
        magi, ver, nerr, pad = r.unpack(SYseHead)
        assert magi == YseMagic
        assert Vmi <= ver < Vma
        assert pad == 0
        self.ver = ver
        self.errs = [Err(r) for _ in range(nerr)]
        r.assert_eof(ver)


SYslHead = U32x3
SLbl = St('<IIHBB')
YslMagic = magic(b'YSLB')


class Lbl:
    __slots__ = ['name', 'id', 'ip', 'scr_idx', 'if_lvl', 'loop_lvl']
    name: str
    id: int
    ip: int  # 200-300:offset, 300-500:index
    scr_idx: int
    if_lvl: int
    loop_lvl: int

    def __init__(self, r: Rdr):
        self.name = r.str(r.byte())
        self.id, self.ip, self.scr_idx, self.if_lvl, self.loop_lvl = r.unpack(SLbl)


class YSLB:
    __slots__ = ['ver', 'lbls']
    ver: int
    lbls: list[Lbl]

    def __init__(self, r: Rdr):
        magi, ver, nlbl = r.unpack(SYslHead)
        assert magi == YslMagic
        assert Vmi <= ver < Vma
        r.idx += 4 * 256
        self.ver = ver
        self.lbls = [Lbl(r) for _ in range(nlbl)]
        r.assert_eof(ver)

    def print(self, f: TextIO):
        f.write(f'YSLB ver={self.ver} nlbl={len(self.lbls)}\n')
        for i, l in enumerate(self.lbls):
            f.write(f'[{i:3}] name={l.name:<10} id={l.id:0>8x} ip={l.ip} '
                    f'scr_idx={l.scr_idx} if={l.if_lvl} loop={l.loop_lvl}\n')


YstMagic = magic(b'YSTD')


class YSTD:
    __slots__ = ['ver', 'nvar', 'ntext']
    ver: int
    nvar: int
    ntext: int

    def __init__(self, r: Rdr):
        magi, ver, self.nvar, self.ntext = r.unpack(U32x4)
        assert magi == YstMagic
        assert Vmi <= ver < Vma
        self.ver = ver
        r.assert_eof(ver)


SYtlHead = U32x3
YtlMagic = magic(b'YSTL')
SScrV200 = St('<Q2i')
SScrV470 = St('<Q3i')


class Scr:
    __slots__ = ['idx', 'path', 'time', 'nvar', 'nlbl', 'ntext']
    idx: int
    path: str
    time: int
    nvar: int
    nlbl: int
    ntext: int

    @classmethod
    def initV200(cls, r: Rdr, i: int):
        s = cls()
        s.idx, path_len = r.unpack(U32x2)
        assert s.idx == i
        s.path = r.str(path_len)
        s.time, s.nvar, s.nlbl = r.unpack(SScrV200)
        s.ntext = 0
        return s

    @classmethod
    def initV470(cls, r: Rdr, i: int):
        s = cls()
        s.idx, path_len = r.unpack(U32x2)
        assert s.idx == i
        s.path = r.str(path_len)
        s.time, s.nvar, s.nlbl, s.ntext = r.unpack(SScrV470)
        return s


class YSTL:
    __slots__ = ['ver', 'scrs']
    ver: int
    scrs: list[Scr]

    def __init__(self, r: Rdr):
        magi, ver, nscr = r.unpack(SYtlHead)
        assert magi == YtlMagic
        assert Vmi <= ver < Vma
        match ver:  # 200-466, 470-500
            case v if Vmi <= v < 470: clsScr = Scr.initV200
            case v if 470 <= v < Vma: clsScr = Scr.initV470
            case _: assert False
        self.ver = ver
        self.scrs = [clsScr(r, i) for i in range(nscr)]
        r.assert_eof(ver)

    def print(self, f: TextIO):
        f.write(f'YSTL ver={self.ver} nscr={len(self.scrs)}\n')
        for i, s in enumerate(self.scrs):
            f.write(f'[{i:>3}] idx={s.idx:<3} path={s.path} time={s.time} nvar={s.nvar} nlbl={s.nlbl} ntext={s.ntext}\n')


VarUsrMi = 1000
SYsvHead = St('<IIH')
SVarV000 = St('<B HHBB')  # G_{TYP}
SvarV481 = St('<BBHHBB')  # G_{TYP}x
YsvMagic = magic(b'YSVR')


class Var:
    __slots__ = ['scope', 'g_ext', 'scr_idx', 'var_idx', 'dim', 'typ', 'initv']
    scope: int  # 1:G, 2:S, 3:F
    g_ext: int  # 0:Sys 123:Usr
    scr_idx: int
    var_idx: int
    dim: list[int]
    typ: int
    initv: None | int | float | list[Ins]

    @classmethod
    def initV000(cls, r: Rdr):
        v = cls()
        v.scope, v.scr_idx, v.var_idx, typ, ndim = r.unpack(SVarV000)
        v.g_ext = 0 if v.var_idx < VarUsrMi else 1
        return v._dims_initv(r, typ, ndim)

    @classmethod
    def initV481(cls, r: Rdr):
        v = cls()
        v.scope, v.g_ext, v.scr_idx, v.var_idx, typ, ndim = r.unpack(SvarV481)
        return v._dims_initv(r, typ, ndim)

    def _dims_initv(self, r: Rdr, typ: int, ndim: int):
        match self.scope:
            case 1 if self.var_idx < VarUsrMi: assert self.g_ext == 0
            case 1: assert 1 <= self.g_ext <= 3  # UserVar from #1000
            case 2 | 3: assert self.g_ext == 1
            case s: assert False, f'unknown scope={s}'
        self.typ = typ
        self.dim = [r.ui(4) for _ in range(ndim)]
        match typ:
            case 0:  # only for non-existent ComVar
                assert self.var_idx < VarUsrMi
                self.initv = None
            case 1: self.initv = r.si(8)
            case 2: self.initv = r.f64()
            case 3: self.initv = Ins.parse_buf(r.read(r.ui(2)), r.enc)
            case t: assert False, f'unknown initv typ={t}'
        return self


class YSVR:
    __slots__ = ['ver', 'vars', 'dic']
    ver: int
    vars: list[Var]  # only G,S,F, no locals
    dic: dict[int, Var]  # var_idx -> var

    def __init__(self, r: Rdr):
        magi, ver, nvar = r.unpack(SYsvHead)
        assert magi == YsvMagic
        assert Vmi <= ver < Vma
        match ver:  # 200-480, 481-501, why?
            case v if Vmi <= v < 481: clsVar = Var.initV000
            case v if 481 <= v < Vma: clsVar = Var.initV481
            case v: assert False, f'unreachable: ver={ver}'
        self.ver = ver
        self.vars = [clsVar(r) for _ in range(nvar)]
        self.dic = {v.var_idx: v for v in self.vars}
        r.assert_eof(ver)

    def print(self, f: TextIO, *, sys_only: bool = False):
        f.write(f'YSVR ver={self.ver} nvar={len(self.vars)}\n')
        for i, v in enumerate(self.vars):
            if sys_only and i >= VarUsrMi:
                break
            f.write(f'[{i}]: var_idx={v.var_idx} scope={v.scope} g_ext={v.g_ext} '
                    f'scr_idx={v.scr_idx} dims={v.dim} init={v.initv}\n')


SYcdHead = U32x4
YcdMagic = magic(b'YSCD')


class DArg:
    __slots__ = ['name', 'unk2', 'typ', 'val']
    name: str
    unk2: tuple[int, int]  # TODO: meaning?
    typ: int
    val: int

    def __init__(self, r: Rdr):
        self.name = r.sz()
        u0, u1, self.typ, self.val = tuple(r.read(4))
        assert self.typ <= 3
        self.unk2 = (u0, u1)


class DCmd:
    __slots__ = ['name', 'args']
    name: str
    args: list[DArg]

    def __init__(self, r: Rdr):
        self.name = r.sz()
        narg = r.byte()
        self.args = [DArg(r) for _ in range(narg)]


class DVar:
    __slots__ = ['name', 'typ', 'dim']
    name: str
    typ: int
    dim: list[int]

    def __init__(self, r: Rdr):
        self.name = r.sz()
        self.typ, ndim = r.read(2)
        assert 1 <= self.typ <= 3
        self.dim = [r.ui(4) for _ in range(ndim)]

    @staticmethod
    def list_to_json(lst: list[DVar]) -> str:
        lines: list[str] = []
        for v in lst:
            lines.append(json.dumps((v.name, v.typ, v.dim)))
        return '[\n'+',\n'.join(lines) + ',\nnull\n]'

    @classmethod
    def from_tuple(cls, obj: Any):  # type: ignore
        assert isinstance(obj, (list, tuple))
        name, typ, dim, *_ = obj  # type: ignore
        assert isinstance(name, str) and len(name) > 0
        assert isinstance(typ, int) and 1 <= typ <= 3
        assert isinstance(dim, list)
        assert all(isinstance(d, int) for d in dim)  # type: ignore
        c = cls.__new__(cls)
        c.name = name
        c.typ = typ
        c.dim = dim
        return c

    @classmethod
    def list_from_json(cls, obj: Any):  # type: ignore
        assert isinstance(obj, (list, tuple))
        return [cls.from_tuple(v) for v in obj[:-1]]  # type: ignore


class YSCD:
    __slots__ = ['ver', 'cmds', 'vars', 'errs', 'estr', 'blok', 'b800']
    ver: int
    cmds: list[DCmd]
    vars: list[DVar]  # compiler vars
    errs: list[Err]
    estr: list[str]
    blok: list[bytes]
    b800: bytes

    def __init__(self, r: Rdr):
        magi, ver, ncmd, pad1 = r.unpack(SYcdHead)
        assert magi == YcdMagic
        assert Vmi <= ver < Vma
        assert pad1 == 0
        self.ver = ver
        self.cmds = [DCmd(r) for _ in range(ncmd)]
        nvar, pad2 = r.unpack(U32x2)
        assert nvar < VarUsrMi
        assert pad2 == 0
        self.vars = [DVar(r) for _ in range(nvar)]
        nerr, pad3 = r.unpack(U32x2)
        assert pad3 == 0
        self.errs = [Err(r) for _ in range(nerr)]
        self.estr = [r.sz() for _ in range(NErrStr)]
        blok, pad4 = r.unpack(U32x2)
        assert pad4 == 0
        self.blok = [r.read(blok) for _ in range(blok)]
        self.b800 = r.read(0x800)
        r.assert_eof(ver)

    def print(self, f:  TextIO = stdout):
        f.write(f'YSCD ver={self.ver}\n')
        f.write(f'- COMMANDS ncmd={len(self.cmds)}-\n')
        for i, c in enumerate(self.cmds):
            f.write(f'[{i}]C:{c.name}\n')
            for j, a in enumerate(c.args):
                f.write(f'\t[{i}][{j:2}]A:{a.name:10} unk={a.unk2} typ={a.typ} val={a.val}\n')
        f.write(f'- VARS nvar={len(self.vars)} -\n')
        for i, v in enumerate(self.vars):
            f.write(f'[{i}]V:{v.name} typ={v.typ}, dim={v.dim}\n')
        f.write(f'- ERRS nerr={len(self.errs)} -\n')
        for i, e in enumerate(self.errs):
            f.write(f'[{i}]E id={e.id} msg={repr(e.msg)}\n')
        f.write(f'- ESTR nestr={len(self.estr)} -\n')
        for i, e in enumerate(self.estr):
            f.write(f'[{i}]S {repr(e)}\n')

    def print_vars(self, f: TextIO):
        f.write(f'YSCD vars ver={self.ver} nvar={len(self.vars)}\n')
        for i, v in enumerate(self.vars):
            f.write(f'[{i}]V:{v.name} typ={v.typ}, dim={v.dim}\n')


SYtbHead = U32x8
SArg = St('<HBBII')
SArgHead = St('<HBB')
SCmdV200 = St('<BBI')  # code, narg, lineno
SCmdV300 = St('<BBH')
SArgR2xx = St('<HBB')
SArgR290 = St('<HBBI')
YtbMagic = int.from_bytes(b'YSTB', LE)


def xor_trans(bs: bytearray, key: int):
    o = len(bs) & ~3
    b0, b1, b2, b3 = k = key.to_bytes(4, 'big')
    for i in range(0, o, 4):
        bs[i+0] ^= b0
        bs[i+1] ^= b1
        bs[i+2] ^= b2
        bs[i+3] ^= b3
    for j in range(len(bs) & 3):
        bs[o+j] ^= k[j]
    return bs


AssignOp = ['=', '+=', '-=',  '*=',  '/=',  '%=',  '&=',  '|=',  '^=']


class Arg:
    __slots__ = ['id', 'typ', 'aop', 'len', 'off', 'dat']
    id: int
    typ: int  # 7-3:TODO:meaning? 21:type; TODO:meaning for vardef cmds?
    aop: int  # assignment op
    len: int
    off: int
    dat: None | str | list[Ins]

    @property
    def aop_str(self):
        return AssignOp[self.aop]

    def __repr__(self):
        if self.dat is None:
            return f'id={self.id} typ={self.typ:0>2x} aop={self.aop}({self.aop_str}) len={self.len} off={self.off}'
        else:
            return f'id={self.id} typ={self.typ:0>2x} aop={self.aop}({self.aop_str}): {self.dat}'

    @classmethod
    def initV0(cls, r: Rdr, dat: None | bytes = None):
        a = cls()
        a.id, a.typ, a.aop, siz, off = r.unpack(SArg)
        a.len = siz
        a.off = off
        assert a.aop <= 8
        if dat == None:
            a.dat = None
        else:
            dat = dat[off:off+siz]
            assert len(dat) == siz
            # print(*map(hex, dat))
            a.dat = Ins.parse_buf(dat, r.enc)
        return a

    @classmethod
    def initWORD(cls, r: Rdr, dat: bytes):
        a = cls()
        a.id, a.typ, a.aop, siz, off = r.unpack(SArg)
        a.len = siz
        a.off = off
        assert a.id == a.typ == a.aop == 0
        dat = dat[off:off+siz]
        assert len(dat) == siz
        a.dat = decode(dat, r.enc)
        return a

    @classmethod
    def initV2xxR(cls, r: Rdr):
        a = cls()
        a.id, a.typ, a.aop = r.unpack(SArgR2xx)
        assert a.typ == a.aop == 0
        a.len = a.off = 0
        a.dat = None
        return a

    @classmethod
    def initV290R(cls, r: Rdr):
        a = cls()
        a.id, a.typ, a.aop, a.len = r.unpack(SArgR290)
        assert a.typ == a.aop == 0
        a.off = 0
        a.dat = None
        return a


class Cmd:
    __slots__ = ['off', 'lno', 'code', 'args', 'npar']
    off: int
    lno: int
    code: int
    args: list[Arg]
    npar: int  # V300: for gosub, return: parameter count (PINT, PSTR)

    @classmethod
    def initV2xx(cls, r: Rdr, dat: bytes, kcc: KnownCmdCode):
        c = cls()
        c.off = r.idx
        c.npar = 0
        code, narg, c.lno = r.unpack(SCmdV200)
        c.code = code
        if code != kcc.RETURNCODE:
            return c._initArgs(r, narg, dat, kcc)
        assert narg == 1
        c.args = [Arg.initV2xxR(r)]
        return c

    @classmethod
    def initV290(cls, r: Rdr, dat: bytes, kcc: KnownCmdCode):
        c = cls()
        c.off = r.idx
        c.npar = 0
        code, narg, c.lno = r.unpack(SCmdV200)
        c.code = code
        if code != kcc.RETURNCODE:
            return c._initArgs(r, narg, dat, kcc)
        assert narg == 1
        c.args = [Arg.initV290R(r)]
        return c

    @classmethod
    def initV300(cls, r: Rdr, rArg: Rdr, rLno: Rdr, dat: bytes, kcc: KnownCmdCode):
        c = cls()
        c.off = r.idx
        c.lno = rLno.ui(4)
        code, narg, c.npar = r.unpack(SCmdV300)
        c.code = code
        if code != kcc.RETURNCODE:
            return c._initArgs(rArg, narg, dat, kcc)
        assert narg == 1
        c.args = [Arg.initV0(rArg, None)]
        return c

    def _initArgs(self, r: Rdr, narg: int, dat: bytes, kcc: KnownCmdCode):
        match self.code:
            case kcc.IF | kcc.ELSE if narg == 3:
                assert narg == 3
                self.args = [Arg.initV0(r, dat), Arg.initV0(r), Arg.initV0(r)]
            case kcc.LOOP:
                assert narg == 2
                self.args = [Arg.initV0(r, dat), Arg.initV0(r)]
            case kcc.ELSE:
                assert narg == 0
                self.args = []
            case kcc.WORD:
                assert narg == 1
                self.args = [Arg.initWORD(r, dat)]
            case _: self.args = [Arg.initV0(r, dat) for _ in range(narg)]
        return self


class YSTB:
    __slots__ = ['ver', 'cmds', 'key', 'kcc']
    ver: int
    cmds: list[Cmd]
    key: int
    kcc: KnownCmdCode

    def __init__(self, f: BinaryIO, kcc: KnownCmdCode,  key: int, *, encoding: str = CP932):
        magi, ver, *rest = SYtbHead.unpack(f.read(32))
        assert magi == YtbMagic
        assert Vmi <= ver < Vma
        if ver < 300:
            lcmd, lexp, exp_off, *pads = rest
            assert not any(pads)
            assert 32+lcmd == exp_off  # cpython/issues/133492
            assert f.readinto(dcmd := bytearray(lcmd)) == lcmd  # type: ignore
            assert f.readinto(dexp := bytearray(lexp)) == lexp  # type: ignore
            rcmd = Rdr(xor_trans(dcmd, key), encoding)
            dexp = xor_trans(dexp, key)
            func = Cmd.initV290 if ver == 290 else Cmd.initV2xx
            cmds: list[Cmd] = []
            while rcmd.idx < lcmd:
                cmds.append(func(rcmd, dexp, kcc))
            self.cmds = cmds
        else:
            ncmd, lcmd, larg, lexp, llno, pad = rest
            assert ncmd * 4 == lcmd == llno
            assert larg % 12 == 0
            assert pad == 0  # cpython/issues/133492
            assert f.readinto(dcmd := bytearray(lcmd)) == lcmd  # type: ignore
            assert f.readinto(darg := bytearray(larg)) == larg  # type: ignore
            assert f.readinto(dexp := bytearray(lexp)) == lexp  # type: ignore
            assert f.readinto(dlno := bytearray(llno)) == llno  # type: ignore
            rcmd = Rdr(xor_trans(dcmd, key), encoding)
            rarg = Rdr(xor_trans(darg, key), encoding)
            rlno = Rdr(xor_trans(dlno, key), encoding)
            dexp = xor_trans(dexp, key)
            self.cmds = [Cmd.initV300(rcmd, rarg, rlno, dexp, kcc) for _ in range(ncmd)]
            rcmd.assert_eof(ver)
            rarg.assert_eof(ver)
            rlno.assert_eof(ver)
        self.ver = ver
        self.key = key
        self.kcc = kcc
        assert len(f.read(1)) == 0

    def print(self, f: TextIO, cmds: list[DCmd] | list[MCmd]):
        kcc = self.kcc
        f.write(f'YSTB ver={self.ver} key={self.key:0>8x} ncmd={len(self.cmds)}\n')
        for i, cmd in enumerate(self.cmds):
            code = cmd.code
            args = cmd.args
            desc = cmds[cmd.code]
            darg = desc.args
            # f.write(f'[{i}] off={cmd.off} lno={cmd.lno} npar={cmd.npar} {code}:{desc.name}\n')
            f.write(f'[{i}] off={cmd.off} npar={cmd.npar} {code}:{desc.name}\n')
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


SIns = St('<BH')
InsList: dict[int, tuple[int, str]] = {
    0x2C: (0, 'nop'),  # between indices
    # lval
    0x48: (3, 'var'),  # @x, $x, &@x, &$x, $@x
    0x76: (3, 'arr'),
    0x56: (3, 'idxbeg'),
    0x29: (1, 'idxend'),  # -> 'idx'
    # rval
    0x42: (1, 'i8'),
    0x57: (2, 'i16'),
    0x49: (4, 'i32'),
    0x4C: (8, 'i64'),
    0x46: (8, 'f64'),
    0x4D: (-1, 'str'),
    # neg/tostr/tonum
    0x73: (0, '$'),
    0x69: (0, '@'),
    0x52: (0, 'neg'),
    # mul/div/mod
    0x2A: (0, '*'),
    0x2F: (0, '/'),
    0x25: (0, '%'),
    # add/sub
    0x2B: (0, '+'),
    0x2D: (0, '-'),
    # lt/le/gt/ge
    0x3C: (0, '<'),
    0x53: (0, '<='),
    0x3E: (0, '>'),
    0x5A: (0, '>='),
    # eq/ne
    0x3D: (0, '=='),
    0x21: (0, '!='),
    # bit and/xor/or
    0x41: (0, '&'),
    0x5E: (0, '^'),
    0x4F: (0, '|'),
    # logic and/or
    0x26: (0, '&&'),
    0x7C: (0, '||'),
}

TypToTyq = [0, 0x40, 0x40, 0x24]
InsTyq = {0x24: '$', 0x40: '@'}
InsTyqV200 = {0x23: '$@', **InsTyq}
InsTyqV300 = {0x23: '&$', **InsTyq, 0x60: '&@'}
GExtChar = ['', '', '2', '3']
ScopeChar = ['', 'g', 's', 'f']
TypDefCmd = ['', 'INT', 'FLT', 'STR']
TypName = ['', 'Int', 'Flt', 'Str']
TypChar = ['', '@', '@', '$']  # 1:Int 2:Flt 3:Num
InsLeaf = tuple[Literal['i8', 'i16', 'i32', 'i64', 'str', 'f64'], str] \
    | tuple[Literal['var', 'arr'], str] \
    | tuple[Literal['idx'], str, list['InsTree']]
InsTree = InsLeaf | tuple[str, 'InsTree'] | tuple[str, 'InsTree', 'InsTree']
DefLclTyp = {'INT': 1, 'FLT': 2, 'STR': 3}
DefCmdTyp = {
    'INT': 1, 'G_INT': 1, 'G_INT2': 1, 'G_INT3': 1, 'S_INT': 1, 'F_INT': 1,
    'FLT': 2, 'G_FLT': 2, 'G_FLT2': 2, 'G_FLT3': 2, 'S_FLT': 2, 'F_FLT': 2,
    'STR': 3, 'G_STR': 3, 'G_STR2': 3, 'G_STR3': 3, 'S_STR': 3, 'F_STR': 3,
}


class Ins:
    __slots__ = ['op', 'arg', 'code', 'size']
    op: str
    code: int
    size: int
    arg: None | int | float | str
    # var 2xx: 23:$@, 24:$, 40:@
    # var 3xx: 23:&$, 24:$, 40:@, 60:&@

    def to_bytes(self):
        match self.code:
            case 0x46: return b'\x46\x08\x00' + F64.pack(self.arg)
            case 0x4d: assert False, 'encode it yourself'
            case code if self.arg == None: return SIns.pack(code, self.size)
            case code:
                assert isinstance(arg := self.arg, int)
                return SIns.pack(code, self.size) + arg.to_bytes(self.size, 'little', signed=True)

    def __init__(self, r: Rdr):
        code, size = r.unpack(SIns)
        self.code = code
        self.size = size
        dsiz, self.op = InsList[code]
        assert dsiz < 0 or dsiz == size
        match code:
            case 0x46: self.arg = r.f64()
            case 0x4d: self.arg = r.str(size)
            case _: self.arg = r.si(size) if size > 0 else None

    def __repr__(self):
        if (a := self.arg) == None:
            return self.op
        if isinstance(a, str):
            return f'({self.op}:{a[1:-1]})'
        if isinstance(a, int):
            if self.op in ('idxbeg', 'arr', 'var'):
                return f'({self.op}:{a & 0xff:0>2x}:{a >> 8})'
            return f'({self.op}:{hex(a)}={a})'
        return f'({self.op}:{a}f)'

    @classmethod
    def parse_buf(cls, b: bytes, enc: str):
        l = len(b)
        r = Rdr(b, enc)
        e: list[Ins] = []
        while r.idx < l:
            e.append(Ins(r))
        return e

    @staticmethod
    def list_to_tree(lst: list[Ins],
                     map_val: Callable[[int | str | float], str],
                     var_name: Callable[[int], str],
                     to_new_tostr: bool) -> InsTree:
        stk: list[InsTree | None] = []  # None as idxbeg marker
        for ins in lst:
            arg = ins.arg
            match (op := ins.op):
                case 'nop': pass
                case 'str':
                    assert isinstance(arg, str)
                    stk.append((op, map_val(arg)))
                case 'f64':
                    assert isinstance(arg, float)
                    stk.append((op, map_val(arg)))
                case  'i8' | 'i16' | 'i32' | 'i64':
                    assert isinstance(arg, int)
                    stk.append((op, map_val(arg)))
                case 'var':
                    assert isinstance(arg, int)
                    v = var_name(arg)
                    if to_new_tostr and v.startswith('$@'):
                        stk.append(('$', (op, v[1:])))
                    else:
                        stk.append((op, var_name(arg)))
                case 'arr':
                    assert isinstance(arg, int)
                    stk.append((op, var_name(arg)+'()'))
                case 'idxbeg':
                    assert isinstance(arg, int)
                    stk.append(('idx', var_name(arg), []))
                    stk.append(None)
                case 'idxend':  # (idx, v, [])
                    idxs: list[InsTree] = []
                    while (item := stk.pop()):
                        idxs.append(item)
                    assert (idx := stk[-1]) and idx[0] == 'idx'  # type: ignore
                    idx[2].extend(reversed(idxs))  # type: ignore
                    assert isinstance(v := idx[1], str)  # type: ignore
                    if to_new_tostr and v.startswith('$@'):
                        stk[-1] = ('$', ('idx', v[1:], idx[2]))  # type: ignore
                case 'neg' | '$' | '@':
                    assert (item := stk.pop())
                    stk.append((op, item))
                case _:
                    assert (rhs := stk.pop())
                    if len(stk) == 0:
                        return (op, rhs)
                    assert (lhs := stk.pop())
                    stk.append((op, lhs, rhs))
        assert len(stk) == 1 and stk[0]
        return stk[0]

    @staticmethod
    def tree_to_str(tree: InsTree) -> str:
        _tree_to_str_lst(tree, lst := [])
        return ''.join(lst)


OpPrec: defdict[str, int] = defdict(lambda: -1, (
    ('adr', 1),
    ('neg', 2),
    ('*', 3),
    ('/', 3),
    ('%', 3),
    ('+', 4),
    ('-', 4),
    ('<', 6),
    ('<=', 6),
    ('>', 6),
    ('>=', 6),
    ('==', 7),
    ('!=', 7),
    ('&', 8),
    ('^', 9),
    ('|', 0),
    ('&&', 1),
    ('||', 2),
))


def _tree_to_str_lst(tree: InsTree, lst: list[str]):
    match (op := tree[0]):
        case 'i8' | 'i16' | 'i32' | 'i64' | 'f64' | 'str' | 'var' | 'arr':
            lst.append(str(tree[1]))
            return
        case 'idx':  # (idx, v, [])
            lst.append(tree[1])  # type: ignore
            lst.append('(')
            assert len(tree[2]) > 0  # type: ignore
            for child in tree[2]:  # type: ignore
                _tree_to_str_lst(child, lst)  # type: ignore
                lst.append(',')
            lst[-1] = ')'
            return
        case '$' | '@':
            lst.append(op)
            lst.append('(')
            _tree_to_str_lst(tree[1], lst)  # type: ignore
            lst.append(')')
            return
        case _: pass
    if op == '&' and len(tree) == 2:
        assert isinstance(rhs := tree[1], tuple)
        my_prec = OpPrec['adr']
        rhs_prec = OpPrec[rhs[0]]
        if my_prec < rhs_prec:
            lst.append('&(')
            _tree_to_str_lst(rhs, lst)
            lst.append(')')
        else:
            lst.append('&')
            _tree_to_str_lst(rhs, lst)
        return
    my_prec = OpPrec[op]
    if len(tree) == 2:
        assert isinstance(lhs := tree[1], tuple)
        add_paren = my_prec < OpPrec[lhs[0]]
        lst.append('-' if op == 'neg' else op)
        lst.append('(') if add_paren else None
        _tree_to_str_lst(lhs, lst)
        lst.append(')') if add_paren else None
        return
    assert isinstance(lhs := tree[1], tuple)
    assert isinstance(rhs := tree[2], tuple)
    op_band = op == '&'
    add_paren = my_prec < OpPrec[lhs[0]]
    lst.append('(') if op_band else None
    lst.append('(') if add_paren else None
    _tree_to_str_lst(lhs, lst)
    lst.append(')') if add_paren else None
    lst.append(' & ' if op_band else op)
    add_paren = my_prec <= OpPrec[rhs[0]]
    lst.append('(') if add_paren else None
    _tree_to_str_lst(rhs, lst)
    lst.append(')') if add_paren else None
    lst.append(')') if op_band else None
