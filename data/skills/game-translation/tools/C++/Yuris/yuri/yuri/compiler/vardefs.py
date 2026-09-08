import ast
from .assembler import *
from ..decompiler.base import DefVarCmd
__all__ = ['do_gfile', 'do_vardef', 'VScope', 'VScoEx', 'Typ', 'TVarDef']
# name, scope_ex, dims, type, initial_value
TVarDef = tuple[str, VScoEx, Seq[int], Lit[Typ.Str], str] \
    | tuple[str, VScoEx, Seq[int], Lit[Typ.Int], int] \
    | tuple[str, VScoEx, Seq[int], Lit[Typ.Flt], int | float]


def do_gfile(mod: ast.Module, limit_sco: Lit[VScope.G, VScope.F]) -> list[TVarDef]:
    return list(filter(None, (do_vardef(stmt, limit_sco) for stmt in mod.body)))


def do_vardef(stmt: ast.stmt, limit_sco: VScope) -> TVarDef | None:
    match stmt:
        case ast.Expr(ast.Subscript(ast.Name(cmd), var)):
            return do_vardef_noinit(stmt, cmd, var, limit_sco)
        case ast.Assign([ast.Subscript(ast.Name(cmd), var)], rhs):
            return do_vardef_initval(stmt, cmd, var, rhs, limit_sco)
        case ast.Pass() | ast.Expr(ast.Call(ast.Name('END'))): return None
        case _: assert False, f'not a declaration: {ast.unparse(stmt)}'


def do_vardef_noinit(stmt: ast.stmt, cmd: str, var: ast.expr, limit_sco: VScope) -> TVarDef:
    sco, sex, typ = DefVarCmd[cmd]
    assert sco == limit_sco, f'{limit_sco.name} file: {ast.unparse(stmt)}'
    name, dims = do_var(var, typ)
    match typ:
        case Typ.Unk: assert False
        case Typ.Int: return (name, sex, dims, typ, 0)
        case Typ.Flt: return (name, sex, dims, typ, 0.0)
        case Typ.Str: return (name, sex, dims, typ, '')


def do_vardef_initval(stmt: ast.stmt, cmd: str, var: ast.expr, rhs: ast.expr, limit_sco: VScope) -> TVarDef:
    sco, sex, typ = DefVarCmd[cmd]
    assert sco == limit_sco, f'{limit_sco.name} file: {ast.unparse(stmt)}'
    name, dims = do_var(var, typ)
    init = do_constexpr(rhs)
    match typ:
        case Typ.Unk: assert False
        case Typ.Int:
            assert isinstance(init, int)
            return (name, sex, dims, typ, init)
        case Typ.Flt:
            assert isinstance(init, (int, float))
            return (name, sex, dims, typ, init)
        case Typ.Str:
            assert isinstance(init, str)
            return (name, sex, dims, typ, init)


def do_var(var: ast.expr, typ: Typ) -> tuple[str, Seq[int]]:
    match var:
        case ast.Attribute(ast.Name(name), tyq):
            assert tyq == 'NS'[typ == Typ.Str], f'type suffix: {ast.unparse(var)}'
            return name, ()
        case ast.Call(ast.Attribute(ast.Name(name), tyq), dim_exprs):
            assert tyq == 'NS'[typ == Typ.Str], f'type suffix: {ast.unparse(var)}'
            dims = tuple(do_constexpr(d) for d in dim_exprs)
            assert all(isinstance(d, int) for d in dims), f'dims: {ast.unparse(var)}'
            return name, dims
        case _: assert False, ast.unparse(var)


def do_constexpr(var: ast.expr):
    try:
        return ast.literal_eval(ast.parse(ast.unparse(var), mode='eval', optimize=2).body)
    except Exception as e:
        e.add_note(ast.unparse(var))
        raise
