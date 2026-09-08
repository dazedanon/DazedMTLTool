from .base import *
from typing import Never
from enum import IntEnum


class Ctl(IntEnum):
    IF = 0
    ELIF = 1
    ELSE = 2
    LOOP = 3


def check_pass(lst: list[ast.stmt]):
    if len(lst) == 0:
        lst.append(ast.Pass())


TyqPrefToSuf = {'$': 'S', '@': 'N', '&@': 'AN', '&$': 'AS', '$@': 'SN'}
AstListLbl: list[ast.expr] = [ast.Name('LBL')]
AstListUnderline = ast.Name('_')
CtlIfElif = (Ctl.IF, Ctl.ELIF)
Aug: list[ast.operator] = [
    ast.Add(),
    ast.Add(), ast.Sub(), ast.Mult(), ast.Div(),
    ast.Mod(), ast.BitAnd(), ast.BitOr(), ast.BitXor()
]


class YDecYuri(YDecBase):
    ExtraExt = '.yuri'
    EmptyFile = 'pass'
    DefaultEnc = 'utf-8'
    AstNameTOI = ast.Name('int')
    AstNameTOS = ast.Name('str')
    AstEmpty = ast.Constant(None)

    def var_to_ast(self, tyq: Tyq, idx: int, lvars: dict[int, tuple[str, Var]]) -> ast.expr:
        tyqpref, name = self.ins_get_var(tyq, idx, lvars)
        return ast.Attribute(ast.Name(name), TyqPrefToSuf[tyqpref])

    def _init_gfile(self) -> str:
        empty_lvars: dict[int, tuple[str, Var]] = {}
        lines: list[str] = []
        for v in self.vars:
            if v is None or v[1].ivar < VMinUsr or v[1].scope != VScope.G:
                continue
            match (vi := v[1].init):
                case None: continue
                case (Typ.Int, i): rhs = f'={i}' if i else ''
                case (Typ.Flt, f): rhs = f'={f}' if f else ''
                case (Typ.Str, l): rhs = '='+ast.unparse(self.ins_to_ast(l, empty_lvars)) if len(l) else ''
            (name, var), typ = v, vi[0]
            suf = '.S' if typ == Typ.Str else '.N'
            cmd = f'G_{typ.name.upper()}{SExCh[v[1].scoex]}'
            dims = f'({','.join(map(str, var.dims))})' if len(var.dims) else ''
            lines.append(f'{cmd}[{name}{suf}{dims}]{rhs}')
        return '\n'.join(lines)

    def do_ystb(self, iscr: int, ystb: YSTB, *_args: Never, **_kwas: Never) -> str:
        assert ystb.ver == self.ver, f'ystb.ver={ystb.ver} self.ver={self.ver}'
        cnames, codes, defcmds = self.cnames, self.codes, self.defcmds
        lbls = self.lbls[iscr] if iscr < len(self.lbls) else {}
        stk: list[list[ast.stmt]] = [root := []]
        lvars: dict[int, tuple[str, Var]] = {}
        ctl: list[Ctl] = []
        for c in ystb.cmds:
            if (off_lbls := lbls.get(c.off)):
                del lbls[c.off]  # LBL = 'LabelName'
                stk[-1].extend(ast.Assign(AstListLbl, ast.Constant(l), lineno=0) for l in off_lbls)
            narg = len(args := c.args)
            match c.code:
                case codes.IF:
                    # if      -> [-2][-1]if [-1]if.body
                    # if else -> [-2][-1]if [-1]if/elif.else
                    # if elif -> [-3][-1]if [-2]if/elif.else [-1]elif.body
                    assert narg == 3
                    assert isinstance(dat := args[0].dat, list)
                    stk[-1].append(ifs := ast.If(self.ins_to_ast(dat, lvars)))
                    stk.append(ifs.body)
                    ctl.append(Ctl.IF)
                case codes.ELSE if narg == 3:
                    assert (top := ctl[-1]) in CtlIfElif
                    assert isinstance(dat := args[0].dat, list)
                    assert isinstance(ifs := stk[-2][-1], ast.If)
                    ifs.orelse.append(eifs := ast.If(self.ins_to_ast(dat, lvars)))
                    if top == Ctl.IF:
                        stk.append(eifs.body)
                        ctl.append(Ctl.ELIF)
                    else:
                        assert ctl[-2] == Ctl.IF
                        check_pass(stk[-1])
                        stk[-1] = eifs.body
                    check_pass(stk[-2])
                    stk[-2] = ifs.orelse
                case codes.ELSE:
                    assert narg == 0
                    assert (top := ctl[-1]) in CtlIfElif
                    assert isinstance(ifs := stk[-2][-1], ast.If)
                    if top == Ctl.ELIF:
                        check_pass(stk.pop())
                        ctl[-1] = Ctl.ELSE
                    else:
                        ctl.append(Ctl.ELSE)
                    check_pass(stk[-1])
                    stk[-1] = ifs.orelse
                case codes.IFEND:
                    assert narg == 0
                    assert (top := ctl.pop()) != Ctl.LOOP
                    if top == Ctl.ELIF:
                        check_pass(stk.pop())
                    if top != Ctl.IF:
                        assert ctl.pop() == Ctl.IF
                    check_pass(stk.pop())
                case codes.IFBLEND: assert narg == 0 and ctl[-1] in CtlIfElif
                case codes.LOOP:
                    assert narg == 2
                    assert isinstance(dat := args[0].dat, list)
                    stk[-1].append(ws := ast.While(self.ins_to_ast(dat, lvars)))
                    stk.append(ws.body)
                    ctl.append(Ctl.LOOP)
                case codes.LOOPEND:
                    assert narg == 0
                    assert ctl.pop() == Ctl.LOOP
                    assert isinstance(stk[-2][-1], ast.While)
                    check_pass(stk.pop())
                case codes._:
                    assert narg == 1 and isinstance(dat := args[0].dat, list)
                    stk[-1].append(ast.Expr(ast.Subscript(AstListUnderline, self.ins_to_ast(dat, lvars))))
                case codes.WORD:
                    assert narg == 1 and isinstance(dat := args[0].dat, str)
                    stk[-1].append(ast.Expr(ast.Constant(dat)))
                case codes.RETURNCODE:
                    assert narg == 1
                    stk[-1].append(ast.Expr(ast.Yield(ast.Constant(args[0].siz))))
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
                    lhsast = self.ins_to_ast(lhsdat, lvars)
                    rhsast = self.ins_to_ast(rhsdat, lvars)
                    if code == codes.LET:
                        if not isinstance(lhsast, ast.Attribute):
                            assert isinstance(lhsast, ast.Call)
                            lhsast = ast.Subscript(ast.Name('LET'), lhsast)
                        if lhs.aop == AOp.EQL:
                            stk[-1].append(ast.Assign([lhsast], rhsast, lineno=0))
                        else:
                            stk[-1].append(ast.AugAssign(lhsast, Aug[lhs.aop], rhsast))
                    else:
                        assert lhs.aop == AOp.EQL
                        match lhsdat[0]:
                            case (IOpV(), _, idx): pass
                            case _: assert False
                        assert (v := (idx < len(self.vars) and self.vars[idx]) or lvars[idx]) is not None
                        assert (vi := v[1].init) is not None
                        s_noinit = vi[1] == StrNoInit
                        n_noinit = rhsdat == IntNoInit
                        lsub = ast.Subscript(ast.Name(cnames[code][0]), lhsast)
                        if s_noinit or n_noinit:
                            stk[-1].append(ast.Expr(lsub))
                        else:
                            stk[-1].append(ast.Assign([lsub], rhsast, lineno=0))
                case code:
                    cmdname, argnames = cnames[code]
                    c_call = ast.Call(ast.Name(cmdname))
                    kwlist = c_call.keywords
                    aolist: list[ast.stmt] = []
                    for arg in args:
                        assert isinstance(dat := arg.dat, list)
                        assert len(a_name := argnames[arg.id]) > 0
                        a_name = 'LBL' if a_name == '#' else a_name
                        a_expr = self.ins_to_ast(dat, lvars)
                        if arg.aop == 0:
                            kwlist.append(ast.keyword(a_name, a_expr))
                        else:
                            kwlist.append(ast.keyword(a_name, ast.Name('_')))
                            aolist.append(ast.AugAssign(ast.Name(a_name), Aug[arg.aop], a_expr))
                    if len(aolist):
                        stk[-1].append(ast.With([ast.withitem(c_call)], aolist, lineno=0))
                    else:
                        stk[-1].append(ast.Expr(c_call))
        return ast.unparse(ast.Module(root))
