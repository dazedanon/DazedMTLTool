import ast
from .assembler import *
from .vardefs import TVarDef, DefVarCmd, do_var as parse_var, do_constexpr
ESym = tuple[list[int], str]
LSym = tuple[list[int], Lit[VScope.L]]
SSym = tuple[list[int], TVarDef]
InitEInt = ast.Constant(0)
InitEFlt = ast.Constant(0.0)
InitEStr = ast.Constant('')
# ntxt, nsvar, nlvar, (eoff, name, if_lv, loop_lv), syms, asm
TCompile = tuple[int, int, int, list[tuple[int, str, int, int]],
                 list[ESym | LSym | SSym], TAsmV200 | TAsmV300]


@dataclass(slots=True)
class ComOpts:
    opt_custom_npar: bool = False  # For Yuri Love Slave


def custom_npar(kwargs: dict[str, Arg]):
    ni, ns, nf = 0, 0, 0
    for kw in kwargs:
        if 'INT' in kw:
            k = kw.rpartition('INT')[2]
            ni = max(ni, int(k) if k.isnumeric() else 1)
        elif 'STR' in kw:
            k = kw.rpartition('STR')[2]
            ns = max(ns, int(k) if k.isnumeric() else 1)
        elif 'FLT' in kw:
            k = kw.rpartition('FLT')[2]
            nf = max(nf, int(k) if k.isnumeric() else 1)
        else:
            assert kw == 'LBL'
    return ((nf & 0b11) << 14)+(ns << 9)+(ni << 3)+(nf >> 2)


def compile_file(
        cdefs: dict[str, tuple[int, dict[str, int]]],
        cvars: dict[str, tuple[Typ, int]],
        gvars: dict[str, Typ],
        fvars: dict[str, Typ],
        module: ast.Module, ver: int, enc: str, opts: ComOpts,
        w_ver: int | None) -> TCompile:
    cmds: list[Cmd] = []
    syms: list[LSym | ESym | SSym] = []
    lbls: dict[str, tuple[Cmd, int, int]] = {}
    svars: dict[str, tuple[Typ, int]] = {}  # script vars
    lvars: dict[str, tuple[Typ, int]] = {}  # local vars - allow redefinition
    erefs: dict[str, tuple[Typ, int]] = {}  # reference to c/g/f vars
    ntxt, nsvar, nlvar, if_lv, loop_lv = 0, 0, 0, 0, 0
    last_lno: int = 0

    def add_cmd(lno: int, cmd: str, *args: Arg, **kwargs: Arg) -> Cmd:
        nonlocal last_lno
        alist: list[Arg] = []
        code, adefs = cdefs[cmd]
        for kw, arg in kwargs.items():
            arg.aid = adefs['#' if kw == 'LBL' else kw]
            alist.append(arg)
        alist.extend(args)
        match cmd:
            case 'RETURN': npar = len(kwargs)
            case 'GOSUB': npar = len(kwargs)-1
            case _: npar = 0
        if opts.opt_custom_npar and cmd in ('RETURN', 'GOSUB'):
            npar = custom_npar(kwargs)
        if lno < 0:
            lno = last_lno
        cmds.append(c := Cmd(code, alist, lno, npar))
        last_lno = lno
        return c

    def add_lbl(lbl: str):
        assert lbl not in lbls, f'already defined LBL: {lbl}'
        cmds.append(c := Cmd(-1, (), 0, 0, skip=SkipLabel))
        lbls[lbl] = (c, if_lv, loop_lv)

    def do_varref(var: ast.Attribute, ins: IOpV, into: list[TIns]) -> Typ:
        match var.value:
            case ast.Name(name):
                if (tup := lvars.get(name) or svars.get(name)
                        or erefs.get(name) or cvars.get(name)):
                    typ, idx = tup
                else:
                    typ = fvars.get(name) or gvars[name]
                    erefs[name] = (typ, idx := len(syms)+VMinUsr)
                    syms.append(([], name))  # add ERef
            case _: assert False, ast.unparse(var)
        match (suf := var.attr):
            case 'N': tyq, num = Tyq.NUM, True    # @
            case 'S': tyq, num = Tyq.STR, False   # $
            case 'AN': tyq, num = Tyq.X60, True   # &@
            case 'AS': tyq, num = Tyq.X23, False  # &$
            case 'SN': tyq, num = Tyq.X23, True   # $@
            case _: assert False, f'unknown suffix {suf}: {ast.unparse(var)}'
        assert (typ != Typ.Str) == num, f'ref {name}: suffix {suf}, but type {typ.name}'
        into.append((ins, tyq, idx))
        match suf:
            case 'N' | 'S': pass
            case 'AN': typ = Typ.Int
            case 'AS': typ = Typ.Int
            case 'SN': typ = Typ.Str  # int as str
        return typ

    def do_expr(expr: ast.expr, into: list[TIns]) -> Typ:
        match expr:
            case ast.Constant(con):
                match con:
                    case int(i):
                        into.append(Ins.intv(i))
                        return Typ.Int
                    case float(f):
                        into.append((IOpA.F64, f))
                        return Typ.Flt
                    case str(s):
                        into.append(Ins.pstr_to_ins(s))
                        return Typ.Str
                    case None: return Typ.Int  # bad expr
                    case _: assert False, f'unsupported literal: {ast.unparse(expr)}'
            case ast.Attribute(): return do_varref(expr, IOpV.VAR, into)
            case ast.Call(called, args):
                match called:
                    case ast.Attribute():
                        if len(args) == 0:
                            return do_varref(called, IOpV.ARR, into)
                        typ = do_varref(called, IOpV.IDXBEG, into)
                        for a in args:
                            atyp = do_expr(a, into)
                            assert atyp == Typ.Int, f'non-int index: {ast.unparse(a)}'
                            into.append(IOpB.NOP)
                        into[-1] = IOpB.IDXEND
                        return typ
                    case ast.Name(fun):
                        assert len(args) == 1, f'invalid conversion: {ast.unparse(expr)}'
                        typ = do_expr(args[0], into)
                        match fun:
                            case 'str':
                                assert typ != Typ.Str, f'already str: {ast.unparse(expr)}'
                                into.append(IOpB.TOS)
                                return Typ.Str
                            case 'int':
                                assert typ == Typ.Str, f'already num: {ast.unparse(expr)}'
                                into.append(IOpB.TOI)
                                return Typ.Int
                            case _: assert False, f'unknown conversion: {ast.unparse(expr)}'
                    case _: assert False, ast.unparse(expr)
            case ast.BoolOp(op, operands):
                ins = astbop_to_ins(op)
                oiter = iter(operands)
                typ = do_expr(subex := next(oiter), into)
                assert typ == Typ.Int, f'non-int in logic: {ast.unparse(subex)}'
                for right in oiter:
                    typ = do_expr(right, into)
                    assert typ == Typ.Int, f'non-int in logic: {ast.unparse(right)}'
                    into.append(ins)
                return Typ.Int
            case ast.Compare(left, op, rights):
                do_expr(left, into)
                for op, right in zip(op, rights):
                    do_expr(right, into)
                    into.append(astcmp_to_ins(op))
                return Typ.Int
            case ast.BinOp(lhs, op, rhs):
                ltyp = do_expr(lhs, into)
                rtyp = do_expr(rhs, into)
                into.append(AOpIns[astop_to_aop(op)])
                match (ltyp, rtyp):
                    case (Typ.Str, Typ.Str): return Typ.Str
                    case (Typ.Str, _) | (_, Typ.Str): assert False, f'str op int: {ast.unparse(expr)}'
                    case (Typ.Flt, _) | (_, Typ.Flt): return Typ.Flt
                    case _: return Typ.Int
            case ast.UnaryOp(op, oper):
                match expr:
                    # Boku no Yumemiru Mirai: es_subtask.yst: --9223372036854775808
                    case ast.UnaryOp(ast.USub(), ast.Constant(int(i))):
                        into.append(Ins.intv(-i))
                        return Typ.Int
                    case _: pass
                assert (typ := do_expr(oper, into)) != Typ.Str, f'neg str: {ast.unparse(expr)}'
                match op:
                    case ast.UAdd(): pass
                    case ast.USub(): into.append(IOpB.NEG)
                    case _: assert False, f'unknown op: {ast.unparse(expr)}'
                return typ
            case _: assert False, ast.unparse(expr)

    def do_defvar(stmt: ast.stmt, cmd: str, var: ast.expr, inite: ast.expr | None):
        nonlocal nsvar, nlvar
        sco, sex, typ = DefVarCmd[cmd]
        if sco not in (VScope.S, VScope.L):
            assert False, f'in non-global file: {ast.unparse(stmt)}'
        name, dims = parse_var(var, typ)
        assert name not in svars, f'already defined S: {ast.unparse(stmt)}'
        assert name not in fvars, f'already defined F: {ast.unparse(stmt)}'
        assert name not in gvars, f'already defined G: {ast.unparse(stmt)}'
        assert name not in cvars, f'system var: {ast.unparse(stmt)}'
        if inite is None:
            match typ:
                case Typ.Unk: assert False
                case Typ.Int: inite = InitEInt
                case Typ.Flt: inite = InitEFlt
                case Typ.Str: inite = InitEStr
        if sco == VScope.S:
            nsvar += 1
            assert name not in lvars, f'already defined L: {ast.unparse(stmt)}'
            init = do_constexpr(inite)
            match typ:
                case Typ.Unk: assert False
                case Typ.Int: assert isinstance(init, int)
                case Typ.Flt: assert isinstance(init, (int, float))
                case Typ.Str: assert isinstance(init, str)
            svars[name] = (typ, len(syms)+VMinUsr)  # S def
            syms.append(([], cast(TVarDef, (name, sex, dims, typ, init))))
        else:
            nlvar += 1
            lvars[name] = (typ, len(syms)+VMinUsr)  # L def
            syms.append(([], sco))
        add_cmd(stmt.lineno,
                cmd, Arg(0, do_expr(var, ins := []), 0, ins), Arg(0, do_expr(inite, ins := []), 0, ins))

    def do_stmt(stmt: ast.stmt):
        nonlocal ntxt, if_lv, loop_lv
        lno = stmt.lineno
        match stmt:
            case ast.Pass(): pass
            case ast.If(test, body, orelse):
                if_lv += 1
                add_cmd(lno, 'IF', Arg(0, do_expr(test, ins := []), 0, ins),
                        ela := Arg(0, 0, 0, None), ifend := Arg(0, 0, 0, None))
                elifs, last_else = do_elif_chain(orelse)
                do_stmt_list(body)
                for test, body in elifs:
                    add_cmd(-1, 'IFBLEND')
                    ela.dat = add_cmd(-1, 'ELSE', Arg(0, do_expr(test, ins := []), 0, ins),
                                      nela := Arg(0, 0, 0, ()), Arg(0, 0, 0, ()))
                    ela = nela
                    do_stmt_list(body)
                if len(last_else):
                    add_cmd(-1, 'IFBLEND')
                    ela.dat = add_cmd(-1, 'ELSE')
                    do_stmt_list(last_else)
                ifend.dat = add_cmd(-1, 'IFEND')
                if_lv -= 1
            case ast.While(test, body):  # TODO: literal -1
                loop_lv += 1
                add_cmd(lno, 'LOOP', Arg(0, do_expr(test, ins := []), 0, ins),
                        loopend := Arg(0, 0, 0, None))
                do_stmt_list(body)
                loopend.dat = add_cmd(-1, 'LOOPEND')
                loop_lv -= 1
            case ast.With([ast.withitem(ast.Call(ast.Name(cmd), [], kwlist))], body):
                kwargs: dict[str, Arg] = {}
                for kwitem in kwlist:
                    kw = cast(str, kwitem.arg)
                    assert kw not in kwargs, f'{kw} already set: {ast.unparse(stmt)}'
                    match kwitem.value:
                        case ast.Name('_'): arg = cast(Arg, None)
                        case e: arg = Arg(0, do_expr(e, ins := []), 0, ins)
                    kwargs[kw] = arg
                for kwaug in body:
                    match kwaug:
                        case ast.AugAssign(ast.Name(kw), op, e):
                            assert kw in kwargs, f'{kw} unwanted: {ast.unparse(stmt)}'
                            assert kwargs[kw] is None, f'{kw} already set: {ast.unparse(stmt)}'
                            kwargs[kw] = Arg(0, do_expr(e, ins := []), astop_to_aop(op), ins)
                        case _: assert False, f'must be an ?= assign: {ast.unparse(kwaug)}'
                for kw, arg in kwargs.items():
                    assert arg is not None, f'no assign for {kw}: {ast.unparse(stmt)}'
                add_cmd(lno, cmd, **kwargs)
            case ast.Expr(expr):
                match expr:
                    case ast.Constant(str(s)):
                        add_cmd(lno, 'WORD', Arg(0, 0, 0, s))
                    case ast.Yield(ast.Constant(int(retcode))):
                        ntxt += 1
                        add_cmd(lno, 'RETURNCODE', Arg(ntxt, 0, 0, retcode))
                    case ast.Call(ast.Name(cmd), [], kwlist):
                        kwargs: dict[str, Arg] = {}
                        for kwitem in kwlist:
                            kw = cast(str, kwitem.arg)
                            assert kw not in kwargs, f'{kw} already set: {ast.unparse(stmt)}'
                            kwargs[kw] = Arg(0, do_expr(kwitem.value, ins := []), 0, ins)
                        add_cmd(lno, cmd, **kwargs)
                    case ast.Subscript(ast.Name(cmd), var):
                        if cmd == '_':
                            add_cmd(lno, cmd, Arg(0, do_expr(var, ins := []), 0, ins))
                            return
                        assert cmd in DefVarCmd, ast.unparse(stmt)
                        do_defvar(stmt, cmd, var, None)
                    case _: assert False, ast.unparse(stmt)
            case ast.Assign([lhs], rhs):
                match lhs:
                    case ast.Name(lhsname):
                        match lhsname:
                            case 'LBL':
                                match rhs:
                                    case ast.Constant(str(lbl)): return add_lbl(lbl)
                                    case _: assert False, ast.unparse(stmt)
                            case 'ENC':
                                nonlocal enc
                                match rhs:
                                    case ast.Constant(str(rhss)):
                                        enc = rhss
                                        return
                                    case _: assert False, ast.unparse(stmt)
                            case _: assert False, ast.unparse(stmt)
                    case ast.Subscript(ast.Name(cmd), var):
                        if cmd != 'LET':
                            assert cmd in DefVarCmd, ast.unparse(stmt)
                            return do_defvar(stmt, cmd, var, rhs)
                    case var: pass
                add_cmd(lno, 'LET',
                        Arg(0, do_expr(var, ins := []), 0, ins),
                        Arg(0, do_expr(rhs, ins := []), 0, ins))
            case ast.AugAssign(lhs, op, rhs):
                match lhs:
                    case ast.Subscript(ast.Name('LET'), var): pass
                    case var: pass
                add_cmd(lno, 'LET',
                        Arg(0, do_expr(var, ins := []), astop_to_aop(op), ins),
                        Arg(0, do_expr(rhs, ins := []), 0, ins))
            case _: assert False, ast.unparse(stmt)

    def do_elif_chain(orelse: list[ast.stmt]):
        elifs: list[tuple[ast.expr, list[ast.stmt]]] = []
        while len(orelse) == 1 and isinstance(nextif := orelse[0], ast.If):
            elifs.append((nextif.test, nextif.body))
            orelse = nextif.orelse
        return elifs, orelse

    def do_stmt_list(lst: list[ast.stmt]):
        for stmt in lst:
            do_stmt(stmt)

    def post_ins(expr_dat: bytearray, pre_len: int, ins: TIns):
        match ins:
            case (_, _, idx): pass
            case _: return
        # assert int.from_bytes(expr_dat[pre_len+4:pre_len+6], LE) == idx
        if (isym := idx - VMinUsr) < 0:
            return
        syms[isym][0].append(pre_len+4)  # IOpV, 0x03, 0x01, Tyq, ISym:u16LE

    do_stmt_list(module.body)
    ybnseg = assemble_ystb(cmds, ver, enc, post_ins, w_ver)
    lblpos = [(v.cmds_idx if ver >= 300 else v.cmds_off, k, i, l) for k, (v, i, l) in lbls.items()]
    return ntxt, nsvar, nlvar, lblpos, syms, ybnseg


AOpIns = [IOpB.NOP, IOpB.ADD, IOpB.SUB, IOpB.MUL, IOpB.DIV, IOpB.MOD, IOpB.BAND, IOpB.BOR, IOpB.BXOR]


def astop_to_aop(op: ast.operator) -> int:
    match op:
        case ast.Add(): return 1
        case ast.Sub(): return 2
        case ast.Mult(): return 3
        case ast.Div(): return 4
        case ast.Mod(): return 5
        case ast.BitAnd(): return 6
        case ast.BitOr(): return 7
        case ast.BitXor(): return 8
        case _: assert False, f'unknown operator: {op}'


def astbop_to_ins(st: ast.boolop) -> TIns:
    match st:
        case ast.Or(): return IOpB.LOR
        case ast.And(): return IOpB.LAND
        case _: assert False, f'unknown operator: {st}'


def astcmp_to_ins(st: ast.cmpop) -> TIns:
    match st:
        case ast.Lt(): return IOpB.LT
        case ast.LtE(): return IOpB.LE
        case ast.Gt(): return IOpB.GT
        case ast.GtE(): return IOpB.GE
        case ast.Eq(): return IOpB.EQ
        case ast.NotEq(): return IOpB.NE
        case _: assert False, f'unknown operator: {st}'
