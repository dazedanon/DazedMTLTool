from .fileformat import *


class YEnv:
    __slots__ = ['ver', 'vars', 'lbls', 'cmds', 'vtyq', 'ysvr', 'global_yst', 'to_new_tostr']
    ver: int
    vars: list[str | None]  # Nones are non-existent comvars and locals
    lbls: defdict[int, defdict[int, list[str]]]  # scr_idx -> offset -> name[]
    cmds: list[tuple[str, list[str]]]
    vtyq: dict[int, str]
    ysvr: YSVR
    global_yst: str | None
    to_new_tostr: bool

    def __init__(self, yscd: YSCD | None, ysvr: YSVR, yslb: YSLB, yscm: YSCM, *, to_new_tostr: bool = False):
        assert (ver := ysvr.ver) == yslb.ver, f'version mismatch: ysvr:{ver}, yslb:{yslb.ver}'
        max_vidx = max(v.var_idx for v in ysvr.vars)
        vars: list[str | None] = [None] * (max_vidx+1)
        self.ver = ver
        self.cmds = []
        self.vars = vars
        self.ysvr = ysvr
        self.to_new_tostr = to_new_tostr
        cmds = self.cmds
        for c in yscm.cmds:
            cmds.append((c.name, list(a.name for a in c.args)))
        if yscd:
            # assert ver == yscd.ver, f'version mismatch: ysvr:{ver}, yscd:{yscd.ver}'
            for i, v in enumerate(yscd.vars):
                vars[i] = TypChar[v.typ]+v.name
            for v in filter(lambda v: v.var_idx < VarUsrMi, ysvr.vars):
                i = v.var_idx
                in_ysvr = v.typ != 0
                in_yscd = vars[i] != None
                assert in_ysvr == in_yscd, f'#{i} in_ysvr={in_ysvr} in_yscd={in_yscd}'
                if in_ysvr:
                    dvar = yscd.vars[i]
                    assert v.typ == dvar.typ, f'#{i} ysvr.typ={v.typ} yscd({dvar.name}).typ={dvar.typ}'
                    assert v.dim == dvar.dim, f'#{i} ysvr.dim={v.dim} yscd({dvar.name}).dim={dvar.dim}'
        else:  # fill in dummy names with ysvr
            assert ver == yscm.ver, f'version mismatch: ysvr:{ver}, yscm:{yscm.ver}'
            for v in ysvr.vars:
                if v.var_idx >= VarUsrMi or (typ := v.typ) == 0:  # non-existent
                    continue
                i = v.var_idx
                vars[i] = f'{TypChar[typ]}_com{i}'
        match ver:  # TODO: version range
            case v if Vmi <= v < 300:
                self.vtyq = InsTyqV200
                lbl_pc_to_off = False
                emit_global_txt = v == 290  # 290 is half-new, half-old
            case v if 300 <= v < Vma:
                self.vtyq = InsTyqV300
                lbl_pc_to_off = True
                emit_global_txt = True
            case v: assert False
        for v in ysvr.vars:
            if v.var_idx < VarUsrMi:
                continue
            assert (typ := v.typ) > 0  # asserted in YSVR
            i = v.var_idx
            vars[i] = f'{TypChar[typ]}{ScopeChar[v.scope]}{GExtChar[v.g_ext]}{TypName[v.typ]}{i}'
        self.global_yst = None
        if emit_global_txt:
            g_lines: list[str] = []
            for v in ysvr.vars:
                if v.var_idx < VarUsrMi or v.scope != 1:
                    continue
                var_cmd = 'G_'+TypDefCmd[v.typ]+GExtChar[v.g_ext]
                var_def = vars[v.var_idx]
                var_dim = f'({','.join(map(str, v.dim))})' if len(v.dim) else ''
                match v.typ:
                    case 1 | 2: var_val = '='+str(v.initv) if v.initv else ''
                    case 3:
                        assert isinstance(initv := v.initv, list)
                        var_val = '='+self.dat_to_argstr(initv) if initv else ''
                    case _: assert False
                g_lines.append(f'{var_cmd}[{var_def}{var_dim}{var_val}]')
            self.global_yst = '\n'.join(g_lines)
        lbls_: defdict[int, defdict[int, list[str]]] = defdict(lambda: defdict(lambda: []))
        for l in yslb.lbls:
            ip = l.ip*4 if lbl_pc_to_off else l.ip  # in v300, Ins is 4B:BBH
            lbls_[l.scr_idx][ip].append(l.name)
        for v in lbls_.values():
            v.default_factory = None
        self.lbls = lbls_

    def ins_get_var(self, x: int):
        idx = x >> 8
        tyq = x & 255
        assert tyq in self.vtyq, f'unknown typ: x={hex(x)}'
        assert (n := self.vars[idx]), f'undefined var: x={hex(x)}'
        assert (t0 := self.vtyq[tyq])[-1] == (t1 := n[0]), f'var {n} type mismatch: want={t0} defined={t1}'
        return n if t0[0] == t1 else t0+n[1:]  # $@ for V200

    def ins_def_local(self, x: int, typ: int):
        idx = x >> 8
        typch = TypChar[typ]
        tyqch = InsTyq[x & 255]  # never pointer
        self.vars.extend(None for _ in range(len(self.vars), idx+1))
        assert self.vars[idx] == None, f'already defined: x={hex(x)}'
        assert tyqch == typch, f'type mismatch: ins={tyqch} cmd={TypChar[typ]}'
        ret = self.vars[idx] = f'{tyqch}v{TypName[typ]}{idx}'
        return ret

    def dat_to_argstr(self, lst: list[Ins]):
        tree = Ins.list_to_tree(lst, str, self.ins_get_var, self.to_new_tostr)
        tstr = Ins.tree_to_str(tree)
        return '('+tstr+')' if tree[0] == '&' and len(tree) == 3 else tstr


DefLet = {*DefCmdTyp.keys(), 'LET'}


def do_ystb(yenv: YEnv, scr_idx: int, ystb: YSTB, f: TextIO):
    ysvr = yenv.ysvr
    lbls = dict(yenv.lbls[scr_idx].items())  # offset -> name[]
    lines: list[list[str]] = [[] for _ in range(max(c.lno for c in ystb.cmds))]
    preps: list[str] = []
    prev_lno = 1
    for i, cmd in enumerate(ystb.cmds):
        assert cmd.lno >= prev_lno, 'lno not increasing!'
        lidx = cmd.lno-1
        curline = lines[lidx]
        if len(preps):
            curline.extend(preps)
            preps.clear()
        if (off_lbls := lbls.get(cmd.off)):
            del lbls[cmd.off]
            lbliter = ('#'+name for name in off_lbls)
            if len(curline) or lidx == 0 or len(prevline := lines[lidx-1]):
                curline.extend(lbliter)
            else:
                prevline.extend(lbliter)
        cmd_name, arg_names = yenv.cmds[cmd.code]
        args = cmd.args
        narg = len(args)
        match cmd_name:
            case 'IFBLEND': assert narg == 0
            case 'IF' | 'ELSE' if narg == 3:
                assert isinstance(dat := cmd.args[0].dat, list)
                curline.append(f'{cmd_name}[{yenv.dat_to_argstr(dat)}]')
            case 'LOOP' if narg == 2:
                assert isinstance(dat := cmd.args[0].dat, list)
                if str(dat) == '[(i8:-0x1=-1)]':  # depends on Ins.__repr__
                    curline.append('LOOP[]')
                    continue
                curline.append(f'LOOP[SET={yenv.dat_to_argstr(dat)}]')
            case 'ELSE':
                assert narg == 0
                curline.append('ELSE[]')
            case 'IF' | 'ELSE' | 'LOOP': assert False, 'guard'
            case 'RETURNCODE':
                assert narg == 1
                match args[0].len:
                    case 0: pass
                    case 1: preps.append('PREP[TEXTVAL=1]')
                    case c: assert False, f'unknown RETURNCODE {c}'
            case 'WORD':
                assert narg == 1
                assert isinstance(s := args[0].dat, str)
                curline.append(s)
            case 'END' if i+1 == len(ystb.cmds): assert narg == 0
            case deflet if deflet in DefLet:
                assert narg == 2
                lhs, rhs = args
                assert rhs.aop == 0
                assert isinstance(lhsdat := lhs.dat, list)
                assert isinstance(rhsdat := rhs.dat, list)
                if deflet in DefLclTyp:
                    ins = lhsdat[0]
                    assert ins.op in ('idxbeg', 'var')
                    assert isinstance(insx := ins.arg, int)
                    yenv.ins_def_local(insx, DefLclTyp[deflet])
                lhsstr = yenv.dat_to_argstr(lhsdat)
                rhsstr = yenv.dat_to_argstr(rhsdat)
                if deflet == 'LET':
                    curline.append(f'{lhsstr}{lhs.aop_str}{rhsstr}')
                else:
                    ins = lhsdat[0]
                    assert lhs.aop == 0
                    assert ins.op in ('idxbeg', 'var')
                    assert isinstance(insx := ins.arg, int)
                    n_noinit = str(rhsdat) == '[(i64:0x0=0)]'  # Ins.__repr__
                    s_noinit = (k := ysvr.dic.get(insx >> 8)) and k.initv == []
                    if n_noinit or s_noinit:
                        curline.append(f'{deflet}[{lhsstr}]')
                    else:
                        curline.append(f'{deflet}[{lhsstr}={rhsstr}]')
            case '_':
                assert narg == 1
                assert isinstance(dat := args[0].dat, list)
                curline.append(f'_[{yenv.dat_to_argstr(dat)}]')
            case _:
                arg_segs: list[str] = []
                for arg in args:
                    arg_name = arg_names[arg.id]
                    assert len(arg_name) > 0
                    assert isinstance(dat := arg.dat, list)
                    arg_segs.append(f'{arg_name}{arg.aop_str}{yenv.dat_to_argstr(dat)}')
                curline.append(f'{cmd_name}[{' '.join(arg_segs)}]')
    assert len(lbls) == 0, 'lables not consumed: '+str(lbls)
    f.write('\n'.join(';'.join(l) for l in lines))  # no newline after


def decompile(idir: str, odir: str, yscd: YSCD | None, ystb_key: int, *,
              i_encoding: str = CP932, o_encoding: str = CP932,
              to_new_tostr: bool = False, yscm: YSCM | None = None):
    with open(path.join(idir, 'ysv.ybn'), 'rb') as fp:
        ysvr = YSVR(Rdr(fp.read(), enc=i_encoding))
    with open(path.join(idir, 'ysl.ybn'), 'rb') as fp:
        yslb = YSLB(Rdr(fp.read(), enc=i_encoding))
    if not yscm:
        with open(path.join(idir, 'ysc.ybn'), 'rb') as fp:
            yscm = YSCM(Rdr(fp.read(), enc=i_encoding))
    with open(path.join(idir, 'yst_list.ybn'), 'rb') as fp:
        ystl = YSTL(Rdr(fp.read(), enc=i_encoding))
    yenv = YEnv(yscd, ysvr, yslb, yscm, to_new_tostr=to_new_tostr)
    glbs = yenv.global_yst
    for scr in ystl.scrs:
        out_path = path.join(odir, scr.path.replace('\\', '/'))
        makedirs(path.dirname(out_path), exist_ok=True)
        if scr.nvar < 0:
            with open(out_path, 'w', encoding=o_encoding, newline='\r\n') as ft:
                if glbs and not 'macro' in out_path.lower():
                    print(scr.idx, out_path, '- empty, we put globals here')
                    ft.writelines(glbs)
                    glbs = None
                else:
                    print(scr.idx, out_path, '- empty')
                    ft.write(';')
        else:
            print(scr.idx, out_path)
            with open(path.join(idir, f'yst{scr.idx:0>5}.ybn'), 'rb') as fp:
                ystb = YSTB(fp, yscm.kcc, ystb_key, encoding=i_encoding)
            with open(out_path, 'w', encoding=o_encoding, newline='\r\n') as ft:
                do_ystb(yenv, scr.idx, ystb, ft)
    if glbs:
        print('no empty file to put global, writing to outdir/global.yst')
        with open(path.join(odir, 'global.yst'), 'w',
                  encoding=o_encoding, newline='\r\n') as ft:
            ft.writelines(glbs)
    if not yscd:
        print('working without YSCom.ycd, you need to rename _comXXX yourself')
