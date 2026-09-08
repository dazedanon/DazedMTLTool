import codecs
from struct import Struct
from os import walk, path
from collections.abc import Buffer
from typing import Sequence as Seq, NamedTuple, BinaryIO, Any
__all__ = ['CustomEncoder']


def raise_error(e: Exception):
    raise e


def create_mapping(idirs: Seq[str], oenc: str, ienc: str, ends: Seq[str]):
    # map: fail -> good
    chars: set[str] = set()
    for idir in idirs:
        for dirpath, _, filenames in walk(idir, onerror=raise_error):
            for filename in filenames:
                for end in ends:
                    if filename.endswith(end):
                        break
                else:
                    continue
                with open(path.join(dirpath, filename), 'r', encoding=ienc) as fp:
                    chars.update(fp.read())
    # categorize good and bad characters in target encoding
    goods: list[str] = []
    fails: list[int] = []
    for ch in sorted(chars):
        try:
            ch.encode(oenc)
            goods.append(ch)
        except UnicodeEncodeError:
            fails.append(ord(ch))
    print(''.join(map(chr, fails)))
    # map bad characters to good characters, keeping known good characters
    goodset = set(map(ord, goods))
    failmap: list[tuple[int, int]] = []
    for ich in range(256, 65536):
        try:
            if ich in goodset:
                continue
            if len(fails) == 0:
                break
            cch = chr(ich)
            if cch.encode(oenc).decode(oenc) == cch:
                failmap.append((fails.pop(), ich))
        except UnicodeEncodeError:
            pass
    assert len(fails) == 0, 'unable to map all failed characters'
    return failmap


class CustomEncoder(NamedTuple):
    oenc: str
    name: str
    fmap: list[tuple[int, int]]
    trans: list[int]

    @classmethod
    def create(cls, iroot: str, o_enc: str, name: str,
               i_enc: str = 'utf-8', ends: Seq[str] = ('.yuri',), *, extra_idirs: Seq[str] = ()):
        tlist = create_mapping([iroot, *extra_idirs], o_enc, i_enc, ends)
        trans = list(range(65536))
        for fail, good in tlist:
            trans[fail] = good
        return cls(o_enc, name, tlist, trans)

    def write_mapbin(self, f: BinaryIO):
        SGoodFail = Struct('<HH')
        for fail, good in self.fmap:
            f.write(SGoodFail.pack(good, fail))

    def register(self):
        try:
            codecs.getencoder(self.name)
        except LookupError:
            myname = self.name
            fenc = codecs.getencoder(self.oenc)
            efun = EncodeFunc(fenc, self.trans)

            def search(name: str):
                if name == myname:
                    return codecs.CodecInfo(efun, notImpl)
            codecs.register(search)


class EncodeFunc(NamedTuple):
    fenc: Any
    trans: list[int]

    def __call__(self, s: str, e: str = 'strict') -> tuple[bytes, int]:
        return self.fenc(s.translate(self.trans), e)


def notImpl(s: Buffer, e: str = 'strict'):
    raise NotImplemented
