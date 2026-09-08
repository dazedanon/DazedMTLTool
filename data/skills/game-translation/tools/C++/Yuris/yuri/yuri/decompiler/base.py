import re
import ast
from ..fileformat import *
from collections.abc import Buffer
from abc import ABC, abstractmethod
from collections import defaultdict as defdic
from typing import cast, Any, Sequence as Seq
StrNoInit = []
IntNoInit = [(IOpA.I64, 0)]
SExCh = ['', '', '2', '3']
ScoCh = [cast(str, None), 'g', 's', 'f', 'l']
RGoodName = re.compile('^[A-Z0-9_]+')
DefLclCmd: dict[str, tuple[VScope, VScoEx, Typ]] = {
    'INT': (VScope.L, VScoEx.DEF, Typ.Int),
    'FLT': (VScope.L, VScoEx.DEF, Typ.Flt),
    'STR': (VScope.L, VScoEx.DEF, Typ.Str)}
DefVarCmd = {**DefLclCmd}
DefVarCmd.update({
    f'G_{typ.name.upper()}{sex}': (VScope.G, sex, typ)
    for typ in (Typ.Int, Typ.Flt, Typ.Str)
    for sex in (VScoEx.G2, VScoEx.G3)})
DefVarCmd.update({
    f'{sco.name}_{typ.name.upper()}': (sco, VScoEx.DEF, typ)
    for sco in (VScope.G, VScope.S, VScope.F)
    for typ in (Typ.Int, Typ.Flt, Typ.Str)})
AstOpUSub = ast.USub()
IOpBBinAst: dict[IOpB, ast.operator] = {
    IOpB.MUL: ast.Mult(),
    IOpB.DIV: ast.Div(),
    IOpB.MOD: ast.Mod(),
    IOpB.ADD: ast.Add(),
    IOpB.SUB: ast.Sub(),
    IOpB.BAND: ast.BitAnd(),
    IOpB.BOR: ast.BitOr(),
    IOpB.BXOR: ast.BitXor()}
IOpBCmpAst: dict[IOpB, ast.cmpop] = {
    IOpB.LT: ast.Lt(),
    IOpB.LE: ast.LtE(),
    IOpB.GT: ast.Gt(),
    IOpB.GE: ast.GtE(),
    IOpB.EQ: ast.Eq(),
    IOpB.NE: ast.NotEq(),
}
IOpBLogAst: dict[IOpB, ast.boolop] = {
    IOpB.LOR: ast.Or(),
    IOpB.LAND: ast.And(),
}


class YDecBase(ABC):
    ExtraExt: str
    EmptyFile: str
    DefaultEnc: str
    AstEmpty: ast.expr
    AstNameTOI: ast.expr
    AstNameTOS: ast.expr
    ver: int
    new_adr: bool
    codes: CmdCodes
    cnames: list[tuple[str, list[str]]]
    defcmds: dict[int, tuple[VScope, VScoEx, Typ]]
    vars: list[tuple[str, Var] | None]  # [ivar]: (name, Var)
    lbls: list[dict[int, list[str]]]  # [iscr]: cmds_off -> lbl_name[]
    out_gfile: str | None

    @staticmethod
    def make_name(v: Var):
        assert (vinit := v.init) is not None
        if v.scoex == VScoEx.SYS:
            assert v.ivar < VMinUsr
            return f'__Sys{v.ivar}'
        return f'{ScoCh[v.scope]}{SExCh[v.scoex]}{vinit[0].name}{v.ivar}'

    def __init__(self, yscm: YSCM, ysvr: YSVR, yslb: YSLB, yscd: YSCD | None = None):
        max_iscr = max(l.iscr for l in yslb.lbls)
        ver = self.ver = ysvr.ver
        self.new_adr = ver >= 300
        assert yscm.ver == ver, f'yscm.ver={yscm.ver}, ysvr.ver={ver}'
        assert yslb.ver == ver, f'yslb.ver={yslb.ver}, ysvr.ver={ver}'
        self.defcmds = {}
        self.codes = yscm.cmdcodes
        self.cnames = [(c.name, [a.name for a in c.args]) for c in yscm.cmds]
        for code, (name, _) in enumerate(self.cnames):
            if (tup := DefVarCmd.get(name)):
                self.defcmds[code] = tup
        vars = self.vars = [None] * (1+max(v.ivar for v in ysvr.vars))
        lbls = self.lbls = [defdic(list) for _ in range(1+max_iscr)]
        for l in yslb.lbls:  # v>=300: sizeof(Cmd)=4: (code:H narg:B npar:B)
            p = l.pos*4 if yslb.ver >= 300 else l.pos  # <300: l.pos is cmds_off
            lbls[l.iscr][p].append(l.name)
        for v in ysvr.vars:
            vars[v.ivar] = v.init and (YDecBase.make_name(v), v)
        if yscd is not None:
            vars: list[tuple[str, Var] | None]
            for i, v in enumerate(yscd.vars):
                assert (tp := vars[i]) is not None
                name, var = tp
                assert (vi := var.init) is not None
                assert name.startswith('__Sys')
                assert vi[0] == v.typ
                assert var.dims == v.dims
                if RGoodName.match(v.name):
                    vars[i] = (v.name, var)
        self.out_gfile = self._init_gfile()if ver >= 300 or ver == 290 else None

    @abstractmethod
    def _init_gfile(self) -> str: pass

    def def_local(self, idx: int, v: Var, lvars: dict[int, tuple[str, Var]]):
        assert idx >= len(self.vars) or self.vars[idx] is None, f'redefine nonlocal #{idx}'
        assert idx not in lvars, f'redefine local #{idx}'
        lvars[idx] = (self.make_name(v), v)

    def ins_get_var(self, tyq: Tyq, idx: int, lvars: dict[int, tuple[str, Var]]) -> tuple[str, str]:
        name, var = (idx < len(self.vars) and self.vars[idx]) or lvars[idx]
        assert (vi := var.init)
        vtyq = Tyq.STR if vi[0] == Typ.Str else Tyq.NUM
        match (tyq, vtyq):
            case (Tyq.NUM, Tyq.NUM): return ('@', name)
            case (Tyq.NUM, _): assert False, f'want @, but #{idx} is $'
            case (Tyq.STR, Tyq.STR): return ('$', name)
            case (Tyq.STR, _): assert False, f'want $, but #{idx} is @'
            case (Tyq.X60, Tyq.NUM): return ('&@', name)
            case (Tyq.X60, _): assert False, f'want &@, but #{idx} is $'
            case _: pass
        if self.new_adr:  # tyq == Tyq.X23
            assert vtyq == Tyq.STR, f'want &$, but #{idx} is @'
            return ('&$', name)
        else:
            assert vtyq == Tyq.NUM, f'want $@, but #{idx} is $'
            return ('$@', name)

    @abstractmethod
    def do_ystb(self, iscr: int, ystb: YSTB, *args: Any, **kwargs: Any) -> str: pass
    @abstractmethod
    def var_to_ast(self, tyq: Tyq, idx: int, lvars: dict[int, tuple[str, Var]]) -> ast.expr: pass

    def ins_to_ast(self, lst: Seq[TIns], lvars: dict[int, tuple[str, Var]], lit_str: bool = False) -> ast.expr:
        stk: list[ast.expr | None] = []
        for ins in lst:
            assert not isinstance(ins, Buffer)
            match ins:
                case str(s):
                    if lit_str:
                        stk.append(ast.Name(s))
                    else:
                        stk.append(ast.Constant(Ins.ins_to_pstr(s)))
                case (IOpA(), v): stk.append(ast.Constant(v))
                case (IOpV(opv), tyq, idx):
                    match opv:
                        case IOpV.VAR: stk.append(self.var_to_ast(tyq, idx, lvars))
                        case IOpV.ARR: stk.append(ast.Call(self.var_to_ast(tyq, idx, lvars)))
                        case _:  # None, arr, dims
                            stk.append(None)
                            stk.append(self.var_to_ast(tyq, idx, lvars))
                case IOpB.IDXEND:
                    dims: list[ast.expr] = []
                    while (d := stk.pop()) is not None:
                        dims.append(d)
                    assert len(dims) >= 2
                    arr = dims.pop()
                    dims.reverse()
                    stk.append(ast.Call(arr, dims))
                case IOpB.NOP: pass
                case IOpB.TOI | IOpB.TOS:
                    assert (exp := stk.pop()) is not None
                    astname = self.AstNameTOI if ins == IOpB.TOI else self.AstNameTOS
                    stk.append(ast.Call(astname, [exp]))
                case IOpB.NEG:
                    assert (exp := stk.pop()) is not None
                    stk.append(ast.UnaryOp(AstOpUSub, exp))
                case _ if ins in IOpBBinAst:
                    assert (rhs := stk.pop() if len(stk) else self.AstEmpty) is not None
                    assert (lhs := stk.pop() if len(stk) else self.AstEmpty) is not None
                    stk.append(ast.BinOp(lhs, IOpBBinAst[ins], rhs))
                case _ if ins in IOpBLogAst:
                    assert (rhs := stk.pop() if len(stk) else self.AstEmpty) is not None
                    assert (lhs := stk.pop() if len(stk) else self.AstEmpty) is not None
                    stk.append(ast.BoolOp(IOpBLogAst[ins], [lhs, rhs]))
                case _:
                    assert (rhs := stk.pop() if len(stk) else self.AstEmpty) is not None
                    assert (lhs := stk.pop() if len(stk) else self.AstEmpty) is not None
                    op = IOpBCmpAst[ins]
                    stk.append(ast.Compare(lhs, [op], [rhs]))
        assert len(stk) == 1 and stk[0] is not None
        return stk[0]
