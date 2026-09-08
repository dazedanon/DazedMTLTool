r"""Refuse to ship a tree that is older than what it was built from.

Two real incidents, one class of bug:

  * `patch` packages `out_dir`; it does NOT run `inject`. An edit to
    `config.py` followed by the gates and then `patch` shipped the PREVIOUS
    inject. Every gate was green because they read the STORE and the SOURCE
    layout - none of them opens `out_dir`. Cost a full playtest round trip.
  * `unpack` fills `proj_dir` from `data.rbpack` and is never re-run, because
    it is slow and its output "already exists". Point the pipeline at a newer
    build of the game and `proj_dir` still describes the old one - and since
    `inject.copy_through` copies pristine proj bytes into `out_dir`, and the
    patch is an OVERRIDE rather than a merge, the stale roms MASK the author's
    new ones at runtime. Silently, in English, on a build every gate calls
    green.

The gates cannot catch either, and that is structural rather than an
oversight: `verify_noop` proves `out == proj`, which says nothing about
whether `proj` still describes the game, and nothing at all about whether
`out` is current.

So each producer STAMPS what it built from, and each consumer CHECKS. Stamps
are cheap identity, not content hashes - `data.rbpack` is 1.7 GB and hashing it
on every command would be its own reason to skip the check.

Deliberately FATAL, not a warning. This bug survived precisely because its
symptom was silence, and a warning in a long log is silence with extra steps."""

import hashlib
import io
import json
import os

STAMP = ".provenance.json"


def _file_id(path):
    if not os.path.exists(path):
        return None
    st = os.stat(path)
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def _sha(path):
    if not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _newest(root, suffixes):
    newest = 0
    for dirpath, _d, files in os.walk(root):
        for fn in files:
            if suffixes and not fn.endswith(suffixes):
                continue
            try:
                newest = max(newest, int(os.stat(os.path.join(dirpath, fn)).st_mtime))
            except OSError:
                pass
    return newest


def pack_id(cfg):
    """Identity of the game archive `proj_dir` was extracted from."""
    return _file_id(os.path.join(cfg["game_dir"], "data", "data.rbpack"))


def build_id(cfg):
    """Everything `out_dir` is a function of.

    The store and the code are folded in by newest-mtime rather than by
    content: the question is only "did anything move after the inject", and a
    false positive costs a re-inject while a false negative ships the wrong
    build."""
    here = os.path.dirname(os.path.abspath(__file__))
    return {
        "pack": pack_id(cfg),
        "config": _sha(os.path.join(here, "config.py")),
        "code": _newest(here, (".py",)),
        "store": _newest(cfg["store_dir"], None),
        "translated": _file_id(os.path.join(cfg["work_dir"], "translated.jsonl")),
        "layout": _file_id(cfg["layout_tsv"]),
    }


def write(tree, data):
    with io.open(os.path.join(tree, STAMP), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)


def read(tree):
    p = os.path.join(tree, STAMP)
    if not os.path.exists(p):
        return None
    try:
        with io.open(p, encoding="utf-8") as fh:
            return json.load(fh)
    except ValueError:
        return None


def check(tree, expected, what, remedy):
    """Fatal unless `tree`'s stamp matches `expected`."""
    got = read(tree)
    if got is None:
        raise SystemExit(
            "\n%s has no provenance stamp, so it cannot be shown to be current.\n"
            "  %s\n" % (tree, remedy))
    diff = [k for k in expected if got.get(k) != expected[k]]
    if not diff:
        return
    lines = ["\n%s IS STALE - it was built from different inputs." % what,
             "  tree : %s" % tree, "  changed since it was built:"]
    for k in diff:
        lines.append("    %-11s stamped %r, now %r" % (k, got.get(k), expected[k]))
    lines.append("  %s\n" % remedy)
    raise SystemExit("\n".join(lines))
