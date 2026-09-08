from os import path, makedirs
from yuri.decompiler import *
from yuri.fileformat import *
from multiprocessing import Pool
from typing import NamedTuple
__all__ = ['run', 'YDecYuris', 'YDecYuri']


class DecCtx(NamedTuple):
    cmdcodes: CmdCodes
    cmds: list[MCmd]
    ydec: YDecBase
    ienc: str
    opath: str
    ext: str
    oenc: str
    dump: bool
    key: int | None
    ver: int | None
    word_enc: str | None


def task_decompile(arg: tuple[int, str, str, str, DecCtx]):
    iscr, scrpath, ybnpath, opath, ctx = arg
    print(iscr, scrpath)
    with open(ybnpath, 'rb') as fp:
        try:
            ee = None  # dirty
            # if scrpath.endswith('キャラ名定義_cn.txt'):
            #     ee = 'gbk'
            # elif scrpath.endswith('キャラ名定義_tw.txt'):
            #     ee = 'big5'
            ystb = YSTB.read(fp, ctx.cmdcodes, enc=ee or ctx.ienc, v=ctx.ver, key=ctx.key, word_enc=ctx.word_enc)
        except Exception as e:
            e.add_note(scrpath)
            raise
    if ctx.dump:
        with open(opath+'.dump', 'w', encoding='utf-8') as fp:
            ystb.print(ctx.cmds, fp)
    text = ctx.ydec.do_ystb(iscr, ystb)
    with open(ctx.opath+ctx.ext, 'w', encoding=ctx.oenc, newline='\r\n') as fp:
        if ee:
            fp.write(f'ENC = {repr(ee)}\n')
        fp.write(text)


def run(
    iroot: str,
    oroot: str,
    ienc: str = CP932,
    oenc: str | None = None,
    yscd: YSCD | None = None,
    dcls: type[YDecBase] = YDecYuris,
    mp_parallel: bool = True, also_dump: bool = False,
    key: int | None = None, ver: int | None = None,
    word_enc: str | None = None,
):
    with open(path.join(iroot, 'ysc.ybn'), 'rb') as fp:
        yscm = YSCM.read(Rdr.from_bio(fp, CP932), v=ver)
    with open(path.join(iroot, 'ysv.ybn'), 'rb') as fp:
        ysvr = YSVR.read(Rdr.from_bio(fp, ienc), v=ver)
    with open(path.join(iroot, 'ysl.ybn'), 'rb') as fp:
        yslb = YSLB.read(Rdr.from_bio(fp, ienc), v=ver)
    with open(path.join(iroot, 'yst_list.ybn'), 'rb') as fp:
        ystl = YSTL.read(Rdr.from_bio(fp, ienc), v=ver)
    makedirs(oroot, exist_ok=True)
    if also_dump:
        with open(path.join(oroot, 'ysc.ybn.dump'), 'w', encoding=oenc) as fp:
            yscm.print(fp)
        with open(path.join(oroot, 'ysv.ybn.dump'), 'w', encoding=oenc) as fp:
            ysvr.print(fp)
        with open(path.join(oroot, 'ysl.ybn.dump'), 'w', encoding=oenc) as fp:
            yslb.print(fp)
        with open(path.join(oroot, 'yst_list.ybn.dump'), 'w', encoding=oenc) as fp:
            ystl.print(fp)
    ydec = dcls(yscm, ysvr, yslb, yscd)
    tasklist: list[tuple[int, str, str, str, DecCtx]] = []
    oenc = oenc or dcls.DefaultEnc
    for scr in ystl.scrs:
        opath = path.join(oroot, scr.path.replace('\\', '/'))
        makedirs(path.dirname(opath), exist_ok=True)
        if scr.nvar < 0:
            print(scr.iscr, scr.path)
            if ydec.out_gfile and not 'macro' in scr.path.lower():
                text = ydec.out_gfile
                ydec.out_gfile = None
            else:
                text = ydec.EmptyFile
            with open(opath+dcls.ExtraExt, 'w', encoding=oenc, newline='\r\n') as fp:
                fp.write(text)
        else:
            ybnpath = f'{iroot}/yst{scr.iscr:0>5}.ybn'
            ctx = DecCtx(yscm.cmdcodes, yscm.cmds, ydec, ienc, opath,
                         dcls.ExtraExt, oenc, also_dump, key, ver, word_enc)
            tasklist.append((scr.iscr, scr.path, ybnpath, opath, ctx))
    if mp_parallel:
        with Pool() as pool:
            pool.map(task_decompile, tasklist)
    else:
        for task in tasklist:
            task_decompile(task)
