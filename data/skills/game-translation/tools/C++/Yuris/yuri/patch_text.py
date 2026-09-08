# 仅处理顶层的字符串语句
import ast
from sys import argv
from os import path, walk, makedirs
from typing import Sequence as Seq, NamedTuple
from multiprocessing import Pool, freeze_support
def raise_error(e: Exception): raise e


class Task(NamedTuple):
    yfn: str
    yenc: str
    tfn: str
    tenc: str


def scan_and_mkdir(yroot: str, troot: str, yexts: Seq[str],
                   ienc: str, oenc: str, for_patch: bool):
    exts_lower = [s.lower() for s in yexts]
    tasks: list[Task] = []
    for ydir, _, filenames in walk(yroot, onerror=raise_error):
        rel = path.relpath(ydir, yroot)
        tdir = path.join(troot, rel)
        if not for_patch:
            makedirs(tdir, exist_ok=True)
        for fn in filenames:
            fn_lower = fn.lower()
            for ext in exts_lower:
                if fn_lower.endswith(ext):
                    yfn = path.join(ydir, fn)
                    tfn = path.join(tdir, fn[:-len(ext)])
                    if for_patch:
                        ymtime = path.getmtime(yfn)
                        try:
                            tmtime = path.getmtime(tfn)
                        except FileNotFoundError:
                            break
                        if ymtime >= tmtime:
                            break
                    tasks.append(Task(yfn, ienc, tfn, oenc))
                    break
    return tasks


def filter_words(ylines: list[str]) -> list[int]:
    wordlines: list[int] = []
    for i, line in enumerate(ylines):
        if len(line) and line[0] in '\"\'':
            wordlines.append(i)
    return wordlines


def task_extract(t: Task):
    with open(t.yfn, 'r', encoding=t.yenc) as ft:
        ysrc = ft.read()
    ylines = ysrc.rstrip().split('\n')
    iwords = [ast.literal_eval(ylines[i]) for i in filter_words(ylines)]
    if len(iwords) == 0:
        return
    print('write', t.tfn)
    with open(t.tfn, 'w', encoding=t.tenc) as ft:
        ft.write('\n'.join(iwords))


def task_patch(t: Task):
    with open(t.yfn, 'r', encoding=t.yenc) as ft:
        ysrc = ft.read()
    with open(t.tfn, 'r', encoding=t.tenc) as ft:
        lines = ft.read()
    ylines = ysrc.rstrip().split('\n')
    iwords = filter_words(ylines)
    if len(iwords) == 0:
        return
    tlines = lines.rstrip().split('\n')
    if len(iwords) != len(tlines):
        print('行数不一致', t.yfn, len(iwords), t.tfn, len(tlines))
    print('write', t.yfn)
    for iword, tline in zip(iwords, tlines):
        ylines[iword] = repr(tline)
    with open(t.yfn, 'w', encoding=t.yenc) as ft:
        ft.write('\n'.join(ylines))


def ext_text(yroot: str,  # .yuri
             troot: str,  # .txt
             yenc: str = 'utf-8',
             tenc: str = 'utf-8',
             yexts: Seq[str] = ('.yuri',),
             parallel: bool = True):
    tasks = scan_and_mkdir(yroot, troot, yexts, yenc, tenc, False)
    if parallel:
        with Pool() as pool:
            pool.map(task_extract, tasks)
    else:
        for tsk in tasks:
            task_extract(tsk)


def pat_text(yroot: str,  # .yuri
             troot: str,  # .txt
             yenc: str = 'utf-8',
             tenc: str = 'utf-8',
             yexts: Seq[str] = ('.yuri',),
             parallel: bool = True):
    tasks = scan_and_mkdir(yroot, troot, yexts, yenc, tenc, True)
    if parallel:
        with Pool() as pool:
            pool.map(task_patch, tasks)
    else:
        for tsk in tasks:
            task_patch(tsk)
