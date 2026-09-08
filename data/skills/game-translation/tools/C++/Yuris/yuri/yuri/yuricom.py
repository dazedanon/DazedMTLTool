import ast
import pickle
from io import BytesIO
from .compiler import *
from .fileformat import *
from struct import Struct
from hashlib import sha256
from typing import NamedTuple
from multiprocessing import Pool
from os import walk, path, makedirs
from xor_cipher import cyclic_xor_in_place
from .util.custom_encoding import CustomEncoder
from deflate import zlib_compress, zlib_decompress
__all__ = ['run', 'Typ', 'KEY_200', 'KEY_290']
YURI_EXT = '.yuri'
TLinks = list[tuple[list[int], int]]
THashCompULen = tuple[bytes, int]


def raise_error(e: Exception):
    raise e


class ComCtx(NamedTuple):
    wroot: str
    iroot: str
    force_recompile: bool
    cdefs: dict[str, tuple[int, dict[str, int]]]
    cdict: dict[str, tuple[Typ, int]]
    gvar_typ: dict[str, Typ]
    ver: int
    i_enc: str
    o_enc: str | CustomEncoder
    opts: ComOpts
    w_ver: int | None


def task_compile(arg: tuple[str, str, tuple[dict[str, Typ], bytes], ComCtx]) -> TCompile:
    filepath, _, (fvars, fghash), c = arg
    if isinstance(c.o_enc, CustomEncoder):
        c.o_enc.register()
    oe_name = o_enc.name if (custom_oenc := isinstance(o_enc := c.o_enc, CustomEncoder)) else o_enc
    workpath = path.join(c.wroot, path.relpath(filepath, c.iroot))
    ycompath = workpath+'com'
    hashpath = workpath+'hash'
    with open(filepath, 'rb') as ft:
        itbytes = ft.read()
        text = str(itbytes, c.i_enc)
        otbytes = (itbytes if oe_name == c.i_enc or not custom_oenc else bytes(text, oe_name))
        txthash = sha256(otbytes).digest()
    try:
        with open(hashpath, 'rb') as fp:
            hfg, htxt = pickle.load(fp)
        if hfg == fghash and htxt == txthash and not c.force_recompile:
            with open(ycompath, 'rb') as fp:
                return pickle.load(fp)
    except FileNotFoundError:
        pass
    print('compile', filepath)
    makedirs(path.dirname(workpath), exist_ok=True)
    mod = ast.parse(text, filepath)
    try:
        res = compile_file(c.cdefs, c.cdict, c.gvar_typ, fvars, mod, c.ver, oe_name, c.opts, c.w_ver)
    except Exception as e:
        e.add_note(f'file: {filepath}')
        raise
    with open(ycompath, 'wb') as fp:
        pickle.dump(res, fp, pickle.HIGHEST_PROTOCOL)
    with open(hashpath, 'wb') as fp:
        pickle.dump((fghash, txthash), fp, pickle.HIGHEST_PROTOCOL)
    return res


class LinkCtx(NamedTuple):
    wroot: str
    key: int


def task_link(arg: tuple[int, str, TLinks, TAsmV200 | TAsmV300, LinkCtx]) -> YPFEnt:
    U16 = Struct('<H')
    hashobj = sha256()
    SHashComp = Struct('<32sb')
    iscr, relpath, links, asm, ctx = arg
    outpath = Rf'ysbin\yst{iscr:0>5}.ybn'
    match asm:
        case (_, a, edat): hashobj.update(a)
        case (_, a, b, edat, c):
            hashobj.update(a)
            hashobj.update(b)
            hashobj.update(c)
    for eoffs, ivar in links:
        for eoff in eoffs:
            U16.pack_into(edat, eoff, ivar)
    hashobj.update(edat)
    orig_hash = hashobj.digest()
    comp_path = path.join(ctx.wroot, relpath+'.comp')
    try:
        pass
        with open(comp_path, 'rb') as fp:
            pair: THashCompULen = SHashComp.unpack(fp.read(33))
            last_hash, last_comp = pair
            if orig_hash == last_hash:  # comp, data, ulen
                ulen = sum(map(len, asm))
                assert len(last_data := fp.read()) == ulen or last_comp != 0
                return outpath, 0, last_comp, last_data, ulen
    except FileNotFoundError:
        pass
    print('compress', iscr, relpath)
    key_bytes = ctx.key.to_bytes(4)
    for buf in asm[1:]:
        cyclic_xor_in_place(buf, key_bytes)
    ulen = len(orig_data := b''.join(asm))
    if len(comp_data := zlib_compress(orig_data, 12)) < ulen:
        comp = -1
        data = comp_data
    else:
        comp = 0
        data = orig_data
    with open(comp_path, 'wb') as fp:
        fp.write(SHashComp.pack(orig_hash, comp))
        fp.write(data)
    return outpath, 0, comp, data, ulen


def run(
    key: int,
    iroot: str,  # source root
    ver: int,    # target version
    wroot: str,  # for intermediate files
    troot: str,  # original ysv, ysc, yse, yscfg from your target version
    o_ypf: str,  # output ypf path
    o_ybn: str | None = None,  # a folder to save generated ybn files
    i_enc: str = 'utf-8',  # source encoding
    t_enc: str = CP932,  # encoding in troot files
    t_ver: int | None = None,  # force version in troot
    w_ver: int | None = None,  # force version when writing
    o_enc: str | CustomEncoder = CP932,  # encoding in output files
    # SysVar:name -> Typ, idx, otherwise only __SysXXX is available
    cdict: dict[str, tuple[Typ, int]] | None = None,
    mp_parallel: bool = True, force_recompile: bool = False,
    ypf_ver: int | None = None, opts: ComOpts = ComOpts()
):
    if isinstance(o_enc, CustomEncoder):
        o_enc.register()
    oe_name = o_enc.name if isinstance(o_enc, CustomEncoder) else o_enc
    # template files: YSVR, YSCM, YSCFG, YSER
    with open(f'{troot}/ysv.ybn', 'rb') as fp:
        ysvr = YSVR.read(Rdr.from_bio(fp, t_enc), v=t_ver)
        del ysvr.vars[VMinUsr:]
    with open(f'{troot}/ysc.ybn', 'rb') as fp:
        yscm_bin = fp.read()
    with open(f'{troot}/yse.ybn', 'rb') as fp:
        yser_bin = fp.read()
    with open(f'{troot}/yscfg.ybn', 'rb') as fp:
        yscf_bin = fp.read()
    # cdefs, cdict
    yscm = YSCM.read(Rdr(yscm_bin, CP932), v=t_ver)
    cdefs = {c.name: (i, {a.name: j for j, a in enumerate(c.args)})
             for i, c in enumerate(yscm.cmds)}
    cdict = cdict or {}
    for i, var in enumerate(ysvr.vars):
        assert var.ivar == i
        if var.init is not None:
            cdict[f'__Sys{i}'] = (var.init[0], i)
    # scan source files
    gfile_list: list[str] = []
    ffile_list: list[tuple[str, str]] = []
    source_list: list[tuple[str, str]] = []
    for dirpath, _, filenames in walk(iroot, onerror=raise_error):
        for filename in filenames:
            basename = path.basename(filename)
            if not basename.endswith(YURI_EXT):
                continue
            fullpath = path.join(dirpath, filename)
            match basename.partition('.')[0]:
                case 'macro': pass
                case 'global': gfile_list.append(fullpath)
                case 'global_f': ffile_list.append((dirpath, fullpath))
                case _: source_list.append((dirpath, fullpath))
    gfile_list.sort(key=lambda s: s.lower().encode(oe_name))
    ffile_list.sort(key=lambda s: s[1].lower().encode(oe_name))
    source_list.sort(key=lambda s: s[1].lower().encode(oe_name))
    # parse global
    gvar_typ: dict[str, Typ] = {}
    gvar_defs: list[TVarDef] = []
    for gfilepath in gfile_list:
        print(gfilepath)
        with open(gfilepath, 'r', encoding=i_enc) as ft:
            text = ft.read()
        mod = ast.parse(text, gfilepath)
        gdefs = do_gfile(mod, VScope.G)
        for t in gdefs:
            assert t[0] not in gvar_typ, f'same name G: {t[0]}'
        gvar_typ.update((t[0], t[3]) for t in gdefs)
        gvar_defs.extend(gdefs)
    # parse global_f
    fvar_defs: list[tuple[str, list[TVarDef]]] = []
    fvars_typ: dict[str, dict[str, Typ]] = {}
    for fdrpath, ffilepath in ffile_list:
        print(ffilepath)
        with open(ffilepath, 'r', encoding=i_enc) as ft:
            text = ft.read()
        mod = ast.parse(text, ffilepath)
        fdefs = do_gfile(mod, VScope.F)
        for t in fdefs:
            assert t[0] not in gvar_typ, f'both in F and G: {t[0]}'
        fvars = {t[0]: t[3] for t in fdefs}
        fvars_typ[fdrpath] = fvars
        fvar_defs.append((fdrpath, fdefs))
    # compile sources
    com_ctx = ComCtx(wroot, iroot, force_recompile, cdefs, cdict, gvar_typ, ver, i_enc, o_enc, opts, w_ver)
    com_tasks: list[tuple[str, str, tuple[dict[str, Typ], bytes], ComCtx]] = []
    for dirpath, filepath in source_list:
        dirsegs = dirpath.split(path.sep)
        filefvs: dict[str, Typ] = {}
        for i in range(1, len(dirsegs)+1):
            curlevel = path.sep.join(dirsegs[0:i])
            if (curfvars := fvars_typ.get(curlevel)) is not None:
                filefvs.update(curfvars)
        hashfg = sha256(pickle.dumps((gvar_typ, filefvs), pickle.HIGHEST_PROTOCOL)).digest()
        p = (filepath, dirpath, (filefvs, hashfg), com_ctx)
        com_tasks.append(p)
    if mp_parallel:
        with Pool() as pool:
            res_list = pool.map(task_compile, com_tasks)
    else:
        res_list = [task_compile(t) for t in com_tasks]
    # assign ivar to global, global_f
    var_list = ysvr.vars
    gvar_dic: dict[str, int] = {}
    fvar_dics: dict[str, dict[str, int]] = {}
    for tvd in gvar_defs:
        match tvd:
            case (name, sex, dims, Typ.Int, i):
                init = (Typ.Int, i)
            case (name, sex, dims, Typ.Flt, f):
                init = (Typ.Flt, float(f))
            case (name, sex, dims, Typ.Str, s):
                init = (Typ.Str, () if len(s) == 0 else (Ins.pstr_to_ins(s),))
        ivar = len(var_list)
        gvar_dic[name] = ivar
        var_list.append(Var(VScope.G, sex, 0, ivar, dims, init))
    for dirpath, defs in fvar_defs:
        fvar_dic = fvar_dics[dirpath] = {}
        for tvd in defs:
            match tvd:
                case (name, sex, dims, Typ.Int, i):
                    init = (Typ.Int, i)
                case (name, sex, dims, Typ.Flt, f):
                    init = (Typ.Flt, float(f))
                case (name, sex, dims, Typ.Str, s):
                    init = (Typ.Str, () if len(s) == 0 else (Ins.pstr_to_ins(s),))
            ivar = len(var_list)
            fvar_dic[name] = ivar
            var_list.append(Var(VScope.F, sex, 0, ivar, dims, init))
    # create YSLB, YSTL; assign ivar to S_; link-compress task
    all_scrs: list[Scr] = []
    all_lbls: list[Lbl] = []
    sum_ntxt = sum(res[0] for res in res_list)
    svar_rlim = lvar_idx = sum(res[1] for res in res_list)+len(var_list)
    link_ctx = LinkCtx(wroot, key)
    link_tasks: list[tuple[int, str, TLinks, TAsmV200 | TAsmV300, LinkCtx]] = []
    for iscr, ((filepath, dirpath, _, _), res) in enumerate(zip(com_tasks, res_list)):
        fvar_dic: dict[str, int] = {}
        dirsegs = dirpath.split(path.sep)
        for i in range(1, len(dirsegs)+1):
            curlevel = path.sep.join(dirsegs[0:i])
            if (curfvars := fvar_dics.get(curlevel)) is not None:
                fvar_dic.update(curfvars)
        ntxt, nsvar, nlvar, lbls, syms, asm = res
        relpath = path.relpath(filepath, iroot).removesuffix('.yuri')
        all_scrs.append(Scr(iscr, relpath.replace('/', '\\'), 0, nlvar+nsvar, len(lbls), ntxt))
        all_lbls.extend(Lbl(name, pos, iscr, if_lv, loop_lv) for pos, name, if_lv, loop_lv in lbls)
        sym_vidxs: TLinks = []
        for sym in syms:
            match sym:
                case (eoffs, VScope.L):
                    sym_vidxs.append((eoffs, lvar_idx))
                    lvar_idx += 1
                case (eoffs, str(s)):
                    ivar = fvar_dic.get(s) or gvar_dic[s]
                    sym_vidxs.append((eoffs, ivar))
                case (eoffs, tuple() as tvd):
                    match tvd:
                        case (name, sex, dims, Typ.Int, i):
                            init = (Typ.Int, i)
                        case (name, sex, dims, Typ.Flt, f):
                            init = (Typ.Flt, float(f))
                        case (name, sex, dims, Typ.Str, s):
                            init = (Typ.Str, () if len(s) == 0 else (Ins.pstr_to_ins(s),))
                    ivar = len(var_list)
                    sym_vidxs.append((eoffs, ivar))
                    var_list.append(Var(VScope.S, sex, iscr, ivar, dims, init))
        link_tasks.append((iscr, relpath, sym_vidxs, asm, link_ctx))
    assert len(var_list) == svar_rlim
    # Link and Compress
    if mp_parallel:
        with Pool() as pool:
            ypf_ents = pool.map(task_link, link_tasks)
    else:
        ypf_ents = [task_link(t) for t in link_tasks]
    # create YSVR, YSLB, YSTL, YSTD, add other files
    all_nvar = lvar_idx
    YSLB.create(yslb_bio := BytesIO(), ver, all_lbls, oe_name, w_ver=w_ver)
    ystl = YSTL(ver, all_scrs)
    ystl.write(ystl_bio := BytesIO(), oe_name, w_ver=w_ver)
    ystd_bin = YSTD(ver, all_nvar, sum_ntxt).tobytes(w_ver=w_ver)
    ysvr.write(ysvr_bio := BytesIO(), oe_name, w_ver=w_ver)
    yslb_bin = yslb_bio.getvalue()
    ystl_bin = ystl_bio.getvalue()
    ysvr_bin = ysvr_bio.getvalue()
    ypf_ents.extend((
        (R'ysbin\ysc.ybn', 0, 1, yscm_bin, len(yscm_bin)),
        (R'ysbin\yscfg.ybn', 0, 1, yscf_bin, len(yscf_bin)),
        (R'ysbin\yse.ybn', 0, 1, yser_bin, len(yser_bin)),
        (R'ysbin\ysl.ybn', 0, 1, yslb_bin, len(yslb_bin)),
        (R'ysbin\yst_list.ybn', 0, 1, ystl_bin, len(ystl_bin)),
        (R'ysbin\yst.ybn', 0, 1, ystd_bin, len(ystd_bin)),
        (R'ysbin\ysv.ybn', 0, 1, ysvr_bin, len(ysvr_bin)),
    ))
    # write YPF
    with open(o_ypf, 'wb') as fp:
        ypf_make(ypf_ents, ypf_ver or ver, fp, enc=oe_name)

        # (Optional step: export the recreated ybn files that will go inside the newly created YPF file)
        if o_ybn:
            for name, _, c, data, uncomp_size in ypf_ents:
                if c == -1:
                    data = zlib_decompress(data, uncomp_size)
                    c = 0
                full_path = path.join(o_ybn, *name.replace('\\', '/').split('/'))
                makedirs(path.dirname(full_path), exist_ok=True)
                print(f'save ybn: {full_path}')
                # Save the file to the output path
                with open(full_path, 'wb') as fo:
                    fo.write(data)
