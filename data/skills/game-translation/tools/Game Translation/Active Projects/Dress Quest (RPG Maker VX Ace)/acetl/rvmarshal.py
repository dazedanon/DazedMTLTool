#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
rvmarshal.py - Ruby Marshal 4.8 reader and writer, byte-exact on round trip.

RPG Maker VX Ace stores every data file (`Data\*.rvdata2`) and every save
(`Save\*.rvdata2`) as one `Marshal.dump` blob. The usual toolchain converts
those to JSON and back with `RV2JSON.exe`, but that round trip is NOT
byte-exact: on this game, 28 of 231 files come back different with zero edits
made (`Enemies.rvdata2` 35,587 -> 32,337 bytes). A patch built on a converter
that rewrites bytes it was not asked to touch cannot prove it changed only what
it meant to, which is the one thing a save-compatible patch has to prove.

So this module reads the format directly and writes it back. `roundtrip_ok()`
over the whole `Data\` folder is the acceptance test: read every file, write it
straight back, compare bytes.

WHY EVERY VALUE IS WRAPPED
--------------------------
Marshal emits a back-reference (`@n`) the second time it writes the SAME
OBJECT, judged by identity, not by value. Two Ruby strings holding `"炎"` are
two objects and are written out twice; one string referenced twice is written
once and then linked. So the reader has to preserve object identity exactly, and
that rules out mapping Marshal strings onto Python `str`: CPython interns short
strings, so two distinct Ruby strings would collapse into one Python object and
the writer would emit a link where the original had a full copy. Every non-
immediate value therefore becomes its own wrapper instance (`RString`, `RArray`,
...) whose Python identity mirrors the Ruby object's. Only nil, true, false,
Fixnum and Symbol are immediates, exactly as in `marshal.c`.

WHAT IS PRESERVED VERBATIM
--------------------------
* the object and symbol link tables, by construction
* `Table`, `Color`, `Tone` and every other `_dump`-based class: the payload is
  kept as raw bytes and never interpreted
* floats, as the ASCII text Ruby wrote (`w_float` is lossy-formatted, so
  re-formatting from a Python float would not reproduce it)
* ivar order on objects and strings
* zlib-compressed script bodies, unless a caller explicitly rewrites one

Reference: ruby/marshal.c (`w_object`, `r_object0`, `w_long`, `r_long`).
"""

import io
import os
import struct

MARSHAL_MAJOR = 4
MARSHAL_MINOR = 8


class MarshalError(ValueError):
    pass


# --------------------------------------------------------------------------
# node types
# --------------------------------------------------------------------------
class RSymbol(object):
    """An interned Ruby symbol. Compared and linked by NAME, like marshal.c."""
    __slots__ = ("name",)

    def __init__(self, name):
        self.name = name if isinstance(name, bytes) else name.encode("utf-8")

    def __repr__(self):
        return ":%s" % self.name.decode("utf-8", "replace")

    def __eq__(self, other):
        return isinstance(other, RSymbol) and other.name == self.name

    def __hash__(self):
        return hash(self.name)

    @property
    def text(self):
        return self.name.decode("utf-8", "replace")


class _Node(object):
    __slots__ = ()


class RString(_Node):
    """`ivars` is empty for a bare `"` and holds `:E`/`:encoding` for an
    `I"`-wrapped one. Keeping the distinction is what makes the round trip
    exact; RPG Maker writes both forms in the same file."""
    __slots__ = ("data", "ivars")

    def __init__(self, data=b"", ivars=None):
        self.data = data
        self.ivars = ivars if ivars is not None else []

    def text(self, encoding="utf-8"):
        return self.data.decode(encoding, "replace")

    def set_text(self, s, encoding="utf-8"):
        self.data = s.encode(encoding)

    def __repr__(self):
        return "RString(%r)" % (self.data[:40],)


class RArray(_Node):
    __slots__ = ("items",)

    def __init__(self, items=None):
        self.items = items if items is not None else []

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]

    def __setitem__(self, i, v):
        self.items[i] = v

    def __iter__(self):
        return iter(self.items)

    def __repr__(self):
        return "RArray(%d)" % len(self.items)


class RHash(_Node):
    """Pairs, in insertion order, plus the `}` default when there is one."""
    __slots__ = ("pairs", "default")

    def __init__(self, pairs=None, default=None):
        self.pairs = pairs if pairs is not None else []
        self.default = default

    def get(self, key, fallback=None):
        for k, v in self.pairs:
            if _key_eq(k, key):
                return v
        return fallback

    def keys(self):
        return [k for k, _v in self.pairs]

    def __len__(self):
        return len(self.pairs)

    def __repr__(self):
        return "RHash(%d)" % len(self.pairs)


class RObject(_Node):
    """A plain `o:` object: a class name plus ordered instance variables."""
    __slots__ = ("cls", "ivars")

    def __init__(self, cls, ivars=None):
        self.cls = cls
        self.ivars = ivars if ivars is not None else []

    def get(self, name):
        want = _sym_bytes(name)
        for k, v in self.ivars:
            if k.name == want:
                return v
        return None

    def set(self, name, value):
        want = _sym_bytes(name)
        for i, (k, _v) in enumerate(self.ivars):
            if k.name == want:
                self.ivars[i] = (k, value)
                return
        self.ivars.append((RSymbol(want), value))

    def has(self, name):
        want = _sym_bytes(name)
        return any(k.name == want for k, _v in self.ivars)

    @property
    def classname(self):
        return self.cls.text

    def __repr__(self):
        return "RObject(%s, %d ivars)" % (self.classname, len(self.ivars))


class RUserDef(_Node):
    """`u:` - a class with `_dump`/`_load` (Table, Color, Tone). The payload is
    opaque on purpose: interpreting a Table's tile grid to write it back
    unchanged would be a way to get it wrong for no benefit."""
    __slots__ = ("cls", "data", "ivars")

    def __init__(self, cls, data=b"", ivars=None):
        self.cls = cls
        self.data = data
        self.ivars = ivars if ivars is not None else []

    def __repr__(self):
        return "RUserDef(%s, %d bytes)" % (self.cls.text, len(self.data))


class RUserMarshal(_Node):
    """`U:` - a class with `marshal_dump`/`marshal_load`."""
    __slots__ = ("cls", "obj", "ivars")

    def __init__(self, cls, obj=None, ivars=None):
        self.cls = cls
        self.obj = obj
        self.ivars = ivars if ivars is not None else []


class RFloat(_Node):
    """Ruby writes a float as text. Keeping that text is the only way to write
    the same bytes back: `w_float` uses a trimmed `%.17g`, and reformatting a
    Python float does not always reproduce it."""
    __slots__ = ("raw", "ivars")

    def __init__(self, raw, ivars=None):
        self.raw = raw if isinstance(raw, bytes) else str(raw).encode("ascii")
        self.ivars = ivars if ivars is not None else []

    @property
    def value(self):
        t = self.raw.decode("ascii", "replace")
        if t == "inf":
            return float("inf")
        if t == "-inf":
            return float("-inf")
        if t == "nan":
            return float("nan")
        return float(t.split("\0")[0])

    def __repr__(self):
        return "RFloat(%s)" % self.raw.decode("ascii", "replace")


class RBignum(_Node):
    __slots__ = ("sign", "words", "ivars")

    def __init__(self, sign, words, ivars=None):
        self.sign = sign            # b'+' or b'-'
        self.words = words          # raw little-endian bytes
        self.ivars = ivars if ivars is not None else []

    @property
    def value(self):
        n = int.from_bytes(self.words, "little")
        return -n if self.sign == b"-" else n


class RRegexp(_Node):
    __slots__ = ("source", "options", "ivars")

    def __init__(self, source, options, ivars=None):
        self.source = source
        self.options = options
        self.ivars = ivars if ivars is not None else []


class RClassRef(_Node):
    """`c:` class, `m:` module, `M:` either (old form)."""
    __slots__ = ("kind", "name")

    def __init__(self, kind, name):
        self.kind = kind            # b'c' / b'm' / b'M'
        self.name = name


class RStruct(_Node):
    __slots__ = ("cls", "members", "ivars")

    def __init__(self, cls, members=None, ivars=None):
        self.cls = cls
        self.members = members if members is not None else []
        self.ivars = ivars if ivars is not None else []


class RData(_Node):
    """`d:` - a `_dump_data` object."""
    __slots__ = ("cls", "obj", "ivars")

    def __init__(self, cls, obj=None, ivars=None):
        self.cls = cls
        self.obj = obj
        self.ivars = ivars if ivars is not None else []


class RUClass(_Node):
    """`C:` - a subclass of String/Array/Hash/Regexp wrapping a builtin."""
    __slots__ = ("cls", "inner")

    def __init__(self, cls, inner):
        self.cls = cls
        self.inner = inner


class RExtended(_Node):
    """`e:` - `obj.extend(Module)`, one wrapper per module, outermost first."""
    __slots__ = ("module", "inner")

    def __init__(self, module, inner):
        self.module = module
        self.inner = inner


def _sym_bytes(name):
    if isinstance(name, RSymbol):
        return name.name
    if isinstance(name, bytes):
        return name
    return name.encode("utf-8")


def _key_eq(a, b):
    if isinstance(a, RSymbol):
        return isinstance(b, (RSymbol, bytes, str)) and a.name == _sym_bytes(b)
    if isinstance(a, RString) and isinstance(b, (bytes, str)):
        return a.data == (b if isinstance(b, bytes) else b.encode("utf-8"))
    return a is b or a == b


# --------------------------------------------------------------------------
# reader
# --------------------------------------------------------------------------
class Reader(object):
    def __init__(self, data):
        self.buf = data
        self.pos = 0
        self.objects = []
        self.symbols = []

    # -- primitives --------------------------------------------------------
    def byte(self):
        if self.pos >= len(self.buf):
            raise MarshalError("unexpected end of stream at %d" % self.pos)
        b = self.buf[self.pos]
        self.pos += 1
        return b

    def take(self, n):
        if self.pos + n > len(self.buf):
            raise MarshalError("truncated read of %d at %d" % (n, self.pos))
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def long(self):
        """marshal.c r_long, byte for byte.

        The header is a SIGNED byte: 0 is zero, 5..127 is the value itself
        minus 5, -128..-5 is the value plus 5, and anything else is a count of
        little-endian bytes that follow (negative count = negative value, filled
        from -1 so the untouched high bytes stay set)."""
        c = self.byte()
        if c == 0:
            return 0
        if c > 127:
            c -= 256
        if c > 0:
            if 4 < c < 128:
                return c - 5
            if c > 8:
                raise MarshalError("long header %d too large" % c)
            n = 0
            for i in range(c):
                n |= self.byte() << (8 * i)
            return n
        if -129 < c < -4:
            return c + 5
        count = -c
        if count > 8:
            raise MarshalError("long header %d too large" % c)
        n = -1
        for i in range(count):
            n &= ~(0xFF << (8 * i))
            n |= self.byte() << (8 * i)
        return n

    def symbol(self):
        b = self.byte()
        if b == 0x3B:                   # ';' symlink
            idx = self.long()
            try:
                return self.symbols[idx]
            except IndexError:
                raise MarshalError("symlink %d out of range" % idx)
        if b != 0x3A:                   # ':'
            raise MarshalError("expected a symbol at %d, got %r"
                               % (self.pos - 1, bytes([b])))
        n = self.long()
        sym = RSymbol(self.take(n))
        self.symbols.append(sym)
        return sym

    # -- registration ------------------------------------------------------
    def _remember(self, obj):
        self.objects.append(obj)
        return obj

    # -- object graph ------------------------------------------------------
    def read(self):
        return self._object()

    def _ivars_into(self, node):
        n = self.long()
        for _ in range(n):
            k = self.symbol()
            node.ivars.append((k, self._object()))

    def _object(self):
        t = self.byte()

        if t == 0x30:                   # '0'
            return None
        if t == 0x54:                   # 'T'
            return True
        if t == 0x46:                   # 'F'
            return False
        if t == 0x69:                   # 'i'
            return self.long()
        if t in (0x3A, 0x3B):           # ':' ';'
            self.pos -= 1
            return self.symbol()
        if t == 0x40:                   # '@' object link
            idx = self.long()
            try:
                return self.objects[idx]
            except IndexError:
                raise MarshalError("object link %d out of range" % idx)

        if t == 0x49:                   # 'I' - ivar wrapper
            inner = self._object()
            if not hasattr(inner, "ivars"):
                raise MarshalError("ivar wrapper around %r" % type(inner))
            self._ivars_into(inner)
            return inner

        if t == 0x22:                   # '"' string
            node = self._remember(RString())
            node.data = self.take(self.long())
            return node

        if t == 0x5B:                   # '[' array
            node = self._remember(RArray())
            n = self.long()
            for _ in range(n):
                node.items.append(self._object())
            return node

        if t in (0x7B, 0x7D):           # '{' hash, '}' hash with default
            node = self._remember(RHash())
            n = self.long()
            for _ in range(n):
                k = self._object()
                v = self._object()
                node.pairs.append((k, v))
            if t == 0x7D:
                node.default = self._object()
            return node

        if t == 0x6F:                   # 'o' object
            cls = self.symbol()
            node = self._remember(RObject(cls))
            self._ivars_into(node)
            return node

        if t == 0x75:                   # 'u' userdef
            cls = self.symbol()
            node = self._remember(RUserDef(cls))
            node.data = self.take(self.long())
            return node

        if t == 0x55:                   # 'U' usrmarshal
            cls = self.symbol()
            node = self._remember(RUserMarshal(cls))
            node.obj = self._object()
            return node

        if t == 0x66:                   # 'f' float
            node = self._remember(RFloat(b""))
            node.raw = self.take(self.long())
            return node

        if t == 0x6C:                   # 'l' bignum
            sign = bytes([self.byte()])
            node = self._remember(RBignum(sign, b""))
            n = self.long()
            node.words = self.take(n * 2)
            return node

        if t == 0x2F:                   # '/' regexp
            node = self._remember(RRegexp(b"", 0))
            node.source = self.take(self.long())
            node.options = self.byte()
            return node

        if t in (0x63, 0x6D, 0x4D):     # 'c' class, 'm' module, 'M' old
            node = self._remember(RClassRef(bytes([t]), b""))
            node.name = self.take(self.long())
            return node

        if t == 0x53:                   # 'S' struct
            cls = self.symbol()
            node = self._remember(RStruct(cls))
            n = self.long()
            for _ in range(n):
                k = self.symbol()
                node.members.append((k, self._object()))
            return node

        if t == 0x64:                   # 'd' data
            cls = self.symbol()
            node = self._remember(RData(cls))
            node.obj = self._object()
            return node

        if t == 0x43:                   # 'C' uclass
            cls = self.symbol()
            inner = self._object()
            # The INNER builtin is what got registered; the wrapper is not a
            # separate entry in Ruby's table, so nothing is remembered here.
            return RUClass(cls, inner)

        if t == 0x65:                   # 'e' extended
            mod = self.symbol()
            return RExtended(mod, self._object())

        raise MarshalError("unsupported Marshal type %r at %d"
                           % (bytes([t]), self.pos - 1))


# --------------------------------------------------------------------------
# writer
# --------------------------------------------------------------------------
class Writer(object):
    def __init__(self):
        self.out = io.BytesIO()
        self.objects = {}               # id(node) -> index
        self.keep = []                  # keep nodes alive so ids stay unique
        self.symbols = {}               # symbol name -> index

    def bytes(self):
        return self.out.getvalue()

    # -- primitives --------------------------------------------------------
    def byte(self, b):
        self.out.write(bytes([b]))

    def raw(self, b):
        self.out.write(b)

    def long(self, n):
        """marshal.c w_long, reproduced exactly - a shorter encoding of the
        same value would be legal Marshal and a different file."""
        if n == 0:
            self.byte(0)
            return
        if 0 < n < 123:
            self.byte(n + 5)
            return
        if -124 < n < 0:
            self.byte((n - 5) & 0xFF)
            return
        buf = []
        v = n
        for i in range(1, 5):
            buf.append(v & 0xFF)
            v >>= 8
            if v == 0:
                self.byte(i)
                break
            if v == -1:
                self.byte((-i) & 0xFF)
                break
        else:
            raise MarshalError("integer too large for w_long: %d" % n)
        self.raw(bytes(buf))

    def bytestr(self, b):
        self.long(len(b))
        self.raw(b)

    def symbol(self, sym):
        idx = self.symbols.get(sym.name)
        if idx is not None:
            self.byte(0x3B)             # ';'
            self.long(idx)
            return
        self.symbols[sym.name] = len(self.symbols)
        self.byte(0x3A)                 # ':'
        self.bytestr(sym.name)

    # -- registration ------------------------------------------------------
    def _remember(self, node):
        self.objects[id(node)] = len(self.objects)
        self.keep.append(node)

    def _link(self, node):
        idx = self.objects.get(id(node))
        if idx is None:
            return False
        self.byte(0x40)                 # '@'
        self.long(idx)
        return True

    def _write_ivars(self, ivars):
        self.long(len(ivars))
        for k, v in ivars:
            self.symbol(k)
            self.write(v)

    # -- object graph ------------------------------------------------------
    def write(self, node):
        if node is None:
            self.byte(0x30)
            return
        if node is True:
            self.byte(0x54)
            return
        if node is False:
            self.byte(0x46)
            return
        if isinstance(node, int):
            self.byte(0x69)
            self.long(node)
            return
        if isinstance(node, RSymbol):
            self.symbol(node)
            return

        # `e:` and `C:` are prefixes on the object that follows, and only that
        # inner object is in the link table. A second reference to it is a bare
        # link with no prefix, so the link check has to run against the inner
        # node before either prefix is emitted.
        if isinstance(node, RExtended):
            if self._link(node.inner):
                return
            self.byte(0x65)
            self.symbol(node.module)
            self.write(node.inner)
            return
        if isinstance(node, RUClass):
            if self._link(node.inner):
                return
            self.byte(0x43)
            self.symbol(node.cls)
            self.write(node.inner)
            return

        if self._link(node):
            return

        # A plain `o:` object carries its ivars AS its body, so it is the one
        # type that never takes the `I` wrapper (marshal.c has_ivars returns
        # false for T_OBJECT).
        ivars = None if isinstance(node, RObject) else getattr(node, "ivars", None)
        if ivars:
            self.byte(0x49)             # 'I'

        if isinstance(node, RString):
            self._remember(node)
            self.byte(0x22)
            self.bytestr(node.data)
        elif isinstance(node, RArray):
            self._remember(node)
            self.byte(0x5B)
            self.long(len(node.items))
            for it in node.items:
                self.write(it)
        elif isinstance(node, RHash):
            self._remember(node)
            self.byte(0x7D if node.default is not None else 0x7B)
            self.long(len(node.pairs))
            for k, v in node.pairs:
                self.write(k)
                self.write(v)
            if node.default is not None:
                self.write(node.default)
        elif isinstance(node, RObject):
            self._remember(node)
            self.byte(0x6F)
            self.symbol(node.cls)
            # An `o:` object writes its ivars as its BODY, so it must not also
            # get the `I` wrapper - and it never reaches the branch below.
            self._write_ivars(node.ivars)
            return
        elif isinstance(node, RUserDef):
            self._remember(node)
            self.byte(0x75)
            self.symbol(node.cls)
            self.bytestr(node.data)
        elif isinstance(node, RUserMarshal):
            self._remember(node)
            self.byte(0x55)
            self.symbol(node.cls)
            self.write(node.obj)
        elif isinstance(node, RFloat):
            self._remember(node)
            self.byte(0x66)
            self.bytestr(node.raw)
        elif isinstance(node, RBignum):
            self._remember(node)
            self.byte(0x6C)
            self.raw(node.sign)
            self.long(len(node.words) // 2)
            self.raw(node.words)
        elif isinstance(node, RRegexp):
            self._remember(node)
            self.byte(0x2F)
            self.bytestr(node.source)
            self.byte(node.options)
        elif isinstance(node, RClassRef):
            self._remember(node)
            self.raw(node.kind)
            self.bytestr(node.name)
        elif isinstance(node, RStruct):
            self._remember(node)
            self.byte(0x53)
            self.symbol(node.cls)
            self.long(len(node.members))
            for k, v in node.members:
                self.symbol(k)
                self.write(v)
        elif isinstance(node, RData):
            self._remember(node)
            self.byte(0x64)
            self.symbol(node.cls)
            self.write(node.obj)
        else:
            raise MarshalError("cannot write %r" % type(node))

        if ivars:
            self._write_ivars(ivars)


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------
def loads(data):
    if len(data) < 2:
        raise MarshalError("too short to be a Marshal stream")
    if data[0] != MARSHAL_MAJOR or data[1] != MARSHAL_MINOR:
        raise MarshalError("unsupported Marshal version %d.%d"
                           % (data[0], data[1]))
    r = Reader(data)
    r.pos = 2
    obj = r.read()
    if r.pos != len(data):
        raise MarshalError("%d trailing byte(s) after the root object"
                           % (len(data) - r.pos))
    return obj


def dumps(obj):
    w = Writer()
    w.raw(bytes([MARSHAL_MAJOR, MARSHAL_MINOR]))
    w.write(obj)
    return w.bytes()


def loads_many(data):
    """Every Marshal document in one buffer, in order.

    A VX Ace SAVE is two documents concatenated - `Marshal.dump(header)` then
    `Marshal.dump(contents)` into the same file handle (`DataManager.
    save_game_without_rescue`) - so a single-document reader sees the second
    one as trailing garbage."""
    out = []
    pos = 0
    while pos < len(data):
        if data[pos] != MARSHAL_MAJOR or data[pos + 1] != MARSHAL_MINOR:
            raise MarshalError("no Marshal header at offset %d" % pos)
        r = Reader(data)
        r.pos = pos + 2
        out.append(r.read())
        if r.pos <= pos:
            raise MarshalError("reader did not advance at %d" % pos)
        pos = r.pos
    return out


def dumps_many(objs):
    return b"".join(dumps(o) for o in objs)


def load_file(path):
    with open(path, "rb") as f:
        return loads(f.read())


def save_file(path, obj):
    """Atomic, and re-parsed before it lands: a truncated .rvdata2 in the game
    folder means the game will not boot."""
    import tempfile
    import stat
    import time

    payload = dumps(obj)
    loads(payload)                      # prove it parses before it can be seen
    d = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=os.path.basename(path) + ".",
                               suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                os.chmod(tmp, stat.S_IMODE(os.stat(path).st_mode))
            except OSError:
                pass
        for i in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if i == 4:
                    raise
                time.sleep(0.1 * (i + 1))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def roundtrip_ok(path):
    """(ok, detail) for one file. The acceptance test for this module."""
    with open(path, "rb") as f:
        original = f.read()
    try:
        obj = loads(original)
    except MarshalError as e:
        return False, "read failed: %s" % e
    out = dumps(obj)
    if out == original:
        return True, ""
    n = min(len(out), len(original))
    at = next((i for i in range(n) if out[i] != original[i]), n)
    return False, ("first difference at byte %d (%d -> %d bytes): "
                   "%r -> %r" % (at, len(original), len(out),
                                 original[max(0, at - 12):at + 12],
                                 out[max(0, at - 12):at + 12]))


# --------------------------------------------------------------------------
# convenience walkers
# --------------------------------------------------------------------------
def walk(node, path="", seen=None):
    """Yield `(path, node)` for every node, visiting each object once.

    Visiting a linked object once is deliberate: a translated string reached
    through two links is ONE object and must be edited once, not twice."""
    if seen is None:
        seen = set()
    if isinstance(node, (RString, RArray, RHash, RObject, RUserDef,
                         RUserMarshal, RStruct, RData, RUClass, RExtended)):
        if id(node) in seen:
            return
        seen.add(id(node))
    yield path, node
    if isinstance(node, RArray):
        for i, v in enumerate(node.items):
            for r in walk(v, "%s/%d" % (path, i), seen):
                yield r
    elif isinstance(node, RHash):
        for k, v in node.pairs:
            kt = k.text if isinstance(k, RSymbol) else (
                k.text() if isinstance(k, RString) else str(k))
            for r in walk(v, "%s/%s" % (path, kt), seen):
                yield r
    elif isinstance(node, RObject):
        for k, v in node.ivars:
            for r in walk(v, "%s/%s" % (path, k.text.lstrip("@")), seen):
                yield r
    elif isinstance(node, (RUserMarshal, RData)):
        for r in walk(node.obj, path + "/_", seen):
            yield r
    elif isinstance(node, RUClass):
        for r in walk(node.inner, path, seen):
            yield r
    elif isinstance(node, RExtended):
        for r in walk(node.inner, path, seen):
            yield r


def obj_ivar_names(node):
    return [k.text for k, _v in node.ivars] if isinstance(node, RObject) else []


if __name__ == "__main__":
    import sys
    import glob

    target = sys.argv[1] if len(sys.argv) > 1 else "Data"
    files = ([target] if os.path.isfile(target)
             else sorted(glob.glob(os.path.join(target, "*.rvdata2"))))
    bad = 0
    for p in files:
        ok, why = roundtrip_ok(p)
        if not ok:
            bad += 1
            print("FAIL %-28s %s" % (os.path.basename(p), why))
    print("%d/%d files round-trip byte-identically"
          % (len(files) - bad, len(files)))
    sys.exit(1 if bad else 0)
