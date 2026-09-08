"""Prototype for `mt-export --sentinel-mask`.

An external LLM emits WOLF codes (\\f \\r \\cself ...) into JSON. Backslash escapes
either decode to control chars (\\f, \\r) or fail the parse outright (\\cself is not
a valid JSON escape). Masking every WOLF code to a backslash-free `{Wn}` sentinel
before the text leaves for translation makes that corruption impossible, and the
per-line legend restores the exact original codes on the way back.
"""
import sys
import json
import argparse

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from wolfscript import WOLF_CODE_RE, load_json


def mask(text):
    """Replace every WOLF code with an opaque `{Wn}` token, unique per distinct code.

    Tokens are pure `{`, `W`, digits, `}` - no backslash and no char JSON escapes -
    so the masked text survives a JSON round-trip untouched. Returns (masked, legend)
    where legend maps token -> original code."""
    legend = {}
    code_to_token = {}

    def sub(m):
        code = m.group(0)
        token = code_to_token.get(code)
        if token is None:
            token = "{W%d}" % len(code_to_token)
            code_to_token[code] = token
            legend[token] = code
        return token

    return WOLF_CODE_RE.sub(sub, text), legend


def unmask(masked_text, legend):
    """Restore original WOLF codes. Longest tokens first so `{W1}` never eats the
    `{W1` prefix of `{W10}`."""
    out = masked_text
    for token in sorted(legend, key=len, reverse=True):
        out = out.replace(token, legend[token])
    return out


def _load(path):
    return load_json(path)


def _dump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def cmd_mask(args):
    batch = _load(args.batch)
    lines = batch.get("lines", [])
    legends = {}
    for i, line in enumerate(lines):
        key = str(line.get("id", i))
        masked, legend = mask(line.get("source", ""))
        line["source"] = masked
        legends[key] = legend
    out = args.out or args.batch
    _dump(batch, out)
    _dump(legends, args.legend)
    print("masked %d lines -> %s (legend: %s)" % (len(lines), out, args.legend))


def cmd_unmask(args):
    batch = _load(args.filled)
    legends = _load(args.legend)
    lines = batch.get("lines", [])
    for i, line in enumerate(lines):
        key = str(line.get("id", i))
        legend = legends.get(key, {})
        line["text"] = unmask(line.get("text", ""), legend)
    out = args.out or args.filled
    _dump(batch, out)
    print("unmasked %d lines -> %s" % (len(lines), out))


def build_parser():
    p = argparse.ArgumentParser(description="Mask/unmask WOLF codes as backslash-free sentinels for MT round-trips.")
    sub = p.add_subparsers(dest="command", required=True)

    m = sub.add_parser("mask", help="mask each line's 'source' and write per-line legends")
    m.add_argument("batch", help="WolfDawn mt-export batch json")
    m.add_argument("-o", "--out", help="output batch (default: overwrite input)")
    m.add_argument("--legend", default="legend.json", help="legend output json (default: legend.json)")
    m.set_defaults(func=cmd_mask)

    u = sub.add_parser("unmask", help="restore codes in each line's 'text'")
    u.add_argument("filled", help="batch json with LLM-filled 'text'")
    u.add_argument("legend", help="legend json from the mask step")
    u.add_argument("-o", "--out", help="output batch (default: overwrite input)")
    u.set_defaults(func=cmd_unmask)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
