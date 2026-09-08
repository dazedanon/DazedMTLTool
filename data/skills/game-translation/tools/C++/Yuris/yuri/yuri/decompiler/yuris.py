from .base import *
from typing import Never


class YDecYuris(YDecBase):
    ExtraExt = ''
    EmptyFile = ';'
    DefaultEnc = CP932
    AstEmpty = ast.Name('')
    AstNameTOI = ast.Name('@')
    AstNameTOS = ast.Name('$')

    def var_to_ast(self, tyq: Tyq, idx: int, lvars: dict[int, tuple[str, Var]]) -> ast.expr:
        tyqpref, name = self.ins_get_var(tyq, idx, lvars)
        return ast.Name(tyqpref+name)

    def ins_to_expr(self, lst: Seq[TIns], lvars: dict[int, tuple[str, Var]]) -> str:
        res = ast.unparse(yuris_prec(self.ins_to_ast(lst, lvars, True))[1])
        res = res.replace(' and ', ' && ')
        res = res.replace(' or ', ' || ')
        return res

    def _init_gfile(self) -> str:
        lines: list[str] = []
        empty_lvars: dict[int, tuple[str, Var]] = {}
        for v in self.vars:
            if v is None or v[1].ivar < VMinUsr or v[1].scope != VScope.G:
                continue
            match (vi := v[1].init):
                case None: continue
                case (Typ.Int, i): rhs = f'={i}' if i else ''
                case (Typ.Flt, f): rhs = f'={f}' if f else ''
                case (Typ.Str, l): rhs = '='+self.ins_to_expr(l, empty_lvars) if len(l) else ''
            (name, var), typ = v, vi[0]
            cmd = f'G_{typ.name.upper()}{SExCh[v[1].scoex]}'
            dims = f'({','.join(map(str, var.dims))})' if len(var.dims) else ''
            lines.append(f'{cmd}[{chr(typ.tyq())}{name}{dims}{rhs}]')
        return '\n'.join(lines)

    def do_ystb(self, iscr: int, ystb: YSTB, *_args: Never, **_kwas: Never) -> str:
        assert ystb.ver == self.ver, f'ystb.ver={ystb.ver} self.ver={self.ver}'
        lno, cnames, codes, defcmds = 1, self.cnames, self.codes, self.defcmds
        lbls = self.lbls[iscr] if iscr < len(self.lbls) else {}
        preps: list[str] = []
        lvars: dict[int, tuple[str, Var]] = {}
        lines: list[list[str]] = [[] for _ in range(max(c.lno for c in ystb.cmds))]
        for i, c in enumerate(ystb.cmds):
            assert c.lno >= lno, f'lno not increasing: c.lno={c.lno}, prev_lno={lno}'
            lno, line = c.lno, lines[c.lno-1]
            if len(preps):
                line.extend(preps)
                preps.clear()
            if (off_lbls := lbls.get(c.off)):
                del lbls[c.off]
                eiter = ('#='+l for l in off_lbls)
                if len(line) or c.lno == 1 or len(prevline := lines[c.lno-2]):
                    line.extend(eiter)
                else:
                    prevline.extend(eiter)
            narg = len(args := c.args)
            match c.code:
                case codes.IFBLEND: pass
                case codes.ELSE if narg == 0:
                    line.append('ELSE[]')
                case codes.IF | codes.ELSE as code:
                    assert narg == 3 and isinstance(dat := args[0].dat, list)
                    cmdname = 'IF' if code == codes.IF else 'ELSE'
                    line.append(f'{cmdname}[{self.ins_to_expr(dat, lvars)}]')
                case codes.LOOP:
                    assert narg == 2 and isinstance(dat := args[0].dat, list)
                    match dat:
                        case [(IOpA.I8, -1)]: line.append('LOOP[]')
                        case _: line.append(f'LOOP[SET={self.ins_to_expr(dat, lvars)}]')
                case codes._:
                    assert narg == 1 and isinstance(dat := args[0].dat, list)
                    line.append(f'_[{self.ins_to_expr(dat, lvars)}]')
                case codes.WORD:
                    assert narg == 1 and isinstance(dat := args[0].dat, str)
                    line.append(dat)
                case codes.RETURNCODE:
                    assert narg == 1
                    match args[0].siz:
                        case 0: pass
                        case 1: preps.append('PREP[TEXTVAL=1]')
                        case rc: assert False, f'unknown returncode {rc}'
                case codes.END if narg == 0:
                    if i+1 < len(ystb.cmds):
                        line.append('END[]')
                case code if code in defcmds or code == codes.LET:
                    assert narg == 2
                    lhs, rhs = args
                    assert rhs.aop == AOp.EQL
                    assert isinstance(lhsdat := lhs.dat, list)
                    assert isinstance(rhsdat := rhs.dat, list)
                    if (defcmd := DefLclCmd.get(cnames[code][0])) is not None:
                        match lhsdat[0]:
                            case (IOpV(), _, idx): pass
                            case _: assert False
                        sco, sex, typ = defcmd
                        match typ:
                            case Typ.Unk: assert False
                            case Typ.Int: ini = (typ, 0)
                            case Typ.Flt: ini = (typ, 0.0)
                            case Typ.Str: ini = (typ, (''))
                        self.def_local(idx, Var(sco, sex, iscr, idx, (), ini), lvars)
                    lhsstr = self.ins_to_expr(lhsdat, lvars)
                    rhsstr = self.ins_to_expr(rhsdat, lvars)
                    if code == codes.LET:
                        line.append(f'{lhsstr}{lhs.aop}{rhsstr}')
                    else:
                        assert lhs.aop == AOp.EQL
                        match lhsdat[0]:
                            case (IOpV(), _, idx): pass
                            case _: assert False
                        assert (v := (idx < len(self.vars) and self.vars[idx]) or lvars[idx]) is not None
                        assert (vi := v[1].init) is not None
                        s_noinit = vi[1] == StrNoInit
                        n_noinit = rhsdat == IntNoInit
                        cmdname = cnames[code][0]
                        if s_noinit or n_noinit:
                            line.append(f'{cmdname}[{lhsstr}]')
                        else:
                            line.append(f'{cmdname}[{lhsstr}={rhsstr}]')
                case code:
                    argsegs: list[str] = []
                    cmdname, argnames = cnames[code]
                    for arg in args:
                        assert len(argname := argnames[arg.id]) > 0
                        assert isinstance(dat := arg.dat, list)
                        argsegs.append(f'{argname}{arg.aop}{self.ins_to_expr(dat, lvars)}')
                    line.append(f'{cmdname}[{' '.join(argsegs)}]')
        assert len(lbls) == 0, 'lables not consumed: '+str(lbls)
        return '\n'.join(';'.join(line) for line in lines)


AstEmpty = ast.Name('')
def force_paren(e: ast.expr) -> ast.expr: return ast.Call(AstEmpty, [e])


def yuris_prec(e: ast.expr) -> tuple[int, ast.expr]:
    match e:
        case ast.Name(): return (-1, e)
        case ast.Constant(): return (-1, e)
        case ast.Call(_, args):
            e.args = [yuris_prec(a)[1] for a in args]
            return (-1, e)
        case ast.BinOp(l, op, r):
            match op:
                case ast.Mult() | ast.Div() | ast.Mod(): p = 3
                case ast.Add() | ast.Sub(): p = 4
                case ast.BitAnd(): p = 8
                case ast.BitXor(): p = 9
                case ast.BitOr(): p = 10
                case _: assert False
            lp, l = yuris_prec(l)
            rp, r = yuris_prec(r)
            l = force_paren(l) if p < lp else l
            r = force_paren(r) if p <= rp else r
            return (p, ast.BinOp(l, op, r))
        case ast.BoolOp(op, [l, r]):
            match op:
                case ast.And(): p = 11
                case ast.Or(): p = 12
                case _: assert False
            lp, l = yuris_prec(l)
            rp, r = yuris_prec(r)
            l = force_paren(l) if p < lp else l
            r = force_paren(r) if p <= rp else r
            return (p, ast.BoolOp(op, [l, r]))
        case ast.Compare(l, [op], [r]):
            match op:
                case ast.Eq() | ast.NotEq(): p = 7
                case _: p = 6
            lp, l = yuris_prec(l)
            rp, r = yuris_prec(r)
            l = force_paren(l) if p < lp else l
            r = force_paren(r) if p <= rp else r
            return (p, ast.Compare(l, [op], [r]))
        case ast.UnaryOp(ast.USub(), r):
            p = 2
            rp, r = yuris_prec(r)
            e.operand = force_paren(r) if p <= rp else r
            return (p, e)
        case _: assert False, ast.unparse(e)
