"""Find a call site whose definition the adaptation dropped.

    unresolved_names.py [package ...]

Twice in this pipeline a constant was deleted while its use survived
(`_BARE_ESCAPE_RE`, then `_TOKEN_RE`). Both were adaptation damage: the
reference module defined them, the Bakin rewrite did not need the comment above
them, and the call went across without the definition. Neither is visible to
`ast.parse`, both raise `NameError` only when that branch runs, and the second
was unreachable until the names pass filled the glossary - so a test suite and
a code review both walked past it.

This resolves every module-level Load name against what the module actually
defines, imports or binds locally. It is a whole-package sweep that takes a
second and cannot miss the class.
"""

import ast
import builtins
import glob
import importlib
import os
import sys


def bound_names(tree):
    """Every name the module binds somewhere - assignment, def, import, arg."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            out.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.arg):
            out.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for al in node.names:
                out.add((al.asname or al.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, ast.Global):
            out.update(node.names)
    return out


def main(*roots):
    # The selftest captures stdout into a StringIO, which has no reconfigure.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, here)
    paths = []
    for r in (roots or ("artl", "tests")):
        paths += sorted(glob.glob(os.path.join(here, r, "*.py")))
    paths.append(os.path.join(here, "tl.py"))

    bad = []
    for path in paths:
        if not os.path.exists(path):
            continue
        rel = os.path.relpath(path, here).replace(os.sep, "/")
        tree = ast.parse(open(path, encoding="utf-8").read(), path)
        # Module dunders exist at run time but are not `dir(builtins)`.
        have = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                     "__package__", "__spec__", "__loader__"}
        if rel.startswith("artl/"):
            mod = "artl." + os.path.splitext(os.path.basename(path))[0]
            try:
                have |= set(dir(importlib.import_module(mod)))
            except Exception as e:
                bad.append((rel, 0, "IMPORT FAILED: %r" % (e,)))
                continue
        local = bound_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in have and node.id not in local:
                    bad.append((rel, node.lineno, node.id))

    if bad:
        print("UNRESOLVED NAMES - a call site whose definition is missing:")
        for rel, line, name in bad:
            print("   %s:%s  %s" % (rel, line, name))
        return 1
    print("no unresolved names in %d module(s)" % len(paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
