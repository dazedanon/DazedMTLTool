#!/usr/bin/env python3
"""
js_text_tool.py — extract & re-inject player-facing Japanese strings in
SRPG Studio JS plugins/scripts (the text that lives in .js source, NOT in
project.dat, so the SRPG_Unpacker patch workflow cannot reach it).

Workflow:
  1) Unpack data.dts with SRPG_Unpacker  (gives an extracted/ folder with Script/ + Plugin/)
  2) python js_text_tool.py extract extracted -o js_strings.json
  3) Translate: fill in each "translation" field in js_strings.json
  4) python js_text_tool.py apply   extracted js_strings.json
  5) Repack:  SRPG_Unpacker.exe extracted -o data.dts   (then use in game)

Commands:
  extract <root> -o <json>   Scan *.js under <root>, write translatable strings to <json>
  apply   <root> <json>      Inject non-empty "translation" values back into the .js files
  stats   <json>             Show per-file / total counts

How it works (and why it's safe):
  * A small JS lexer finds string literals while skipping // and /* */ comments.
  * Only literals containing Japanese (hiragana/katakana/kanji) are taken; pure
    English/ASCII strings and code identifiers are ignored.
  * Template literals containing ${...} interpolation are skipped (not translated).
  * Each string is keyed by (file, index-of-Nth-Japanese-literal). On apply, the
    file is re-tokenized with the SAME filter, so indices line up, and the stored
    "original" is checked against the current text before replacing (mismatch =>
    skipped with a warning, so a hand-edited file can't be silently corrupted).
  * "original"/"translation" are the RAW text between the quotes (escapes like \n
    are literal). "preview" is an unescaped, human-readable copy (informational).
    Keep \n and escape a literal quote (' -> \') in your translation.

Byte preservation: files are read/written as UTF-8 bytes with original line
endings (CRLF/LF) and BOM preserved.
"""
import sys, os, json, argparse


# ---------------------------------------------------------------- JP detection
def has_japanese(s: str) -> bool:
    for ch in s:
        o = ord(ch)
        if (0x3040 <= o <= 0x30FF or   # hiragana + katakana
                0x3400 <= o <= 0x4DBF or  # CJK Ext-A
                0x4E00 <= o <= 0x9FFF or  # CJK Unified
                0xF900 <= o <= 0xFAFF):   # CJK Compatibility
            return True
    return False


# --------------------------------------------------------------- JS lexer
def find_literals(text: str):
    """Yield (content_start, content_end, quote, interpolated) for each JS
    string literal, skipping line/block comments."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
        elif c == '/' and i + 1 < n and text[i + 1] == '*':
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
        elif c in ('"', "'", '`'):
            quote = c
            cs = i + 1
            j = cs
            interp = False
            while j < n:
                cj = text[j]
                if cj == '\\':
                    j += 2
                    continue
                if quote == '`' and cj == '$' and j + 1 < n and text[j + 1] == '{':
                    interp = True
                    depth = 1
                    j += 2
                    while j < n and depth:          # skip balanced ${ ... }
                        if text[j] == '{':
                            depth += 1
                        elif text[j] == '}':
                            depth -= 1
                        j += 1
                    continue
                if cj == quote:
                    break
                j += 1
            out.append((cs, j, quote, interp))
            i = j + 1
        else:
            i += 1
    return out


def is_translatable(text: str, lit) -> bool:
    """A literal is translatable if it isn't an interpolated template and
    contains Japanese. (Indices below are into the FULL literal list so they
    stay stable after a value is translated JP->EN, enabling incremental apply.)"""
    cs, ce, quote, interp = lit
    return (not interp) and has_japanese(text[cs:ce])


_ESC = {'n': '\n', 'r': '\r', 't': '\t', '\\': '\\', "'": "'", '"': '"', '`': '`', '/': '/', '0': '\0'}


def unescape(raw: str) -> str:
    """Best-effort unescape for a human-readable preview."""
    out, i, n = [], 0, len(raw)
    while i < n:
        c = raw[i]
        if c == '\\' and i + 1 < n:
            nx = raw[i + 1]
            if nx == 'u' and i + 5 < n + 1:
                try:
                    out.append(chr(int(raw[i + 2:i + 6], 16))); i += 6; continue
                except ValueError:
                    pass
            if nx == 'x' and i + 3 < n + 1:
                try:
                    out.append(chr(int(raw[i + 2:i + 4], 16))); i += 4; continue
                except ValueError:
                    pass
            out.append(_ESC.get(nx, nx)); i += 2; continue
        out.append(c); i += 1
    return ''.join(out)


def line_of(text: str, pos: int) -> int:
    return text.count('\n', 0, pos) + 1


def context_of(text: str, pos: int) -> str:
    ls = text.rfind('\n', 0, pos) + 1
    le = text.find('\n', pos)
    if le < 0:
        le = len(text)
    return text[ls:le].strip()[:120]


def read_text(path: str) -> str:
    return open(path, 'rb').read().decode('utf-8')


def write_text(path: str, text: str):
    open(path, 'wb').write(text.encode('utf-8'))


def iter_js(root: str):
    for dp, _, files in os.walk(root):
        for fn in files:
            if fn.lower().endswith('.js'):
                full = os.path.join(dp, fn)
                yield full, os.path.relpath(full, root).replace('\\', '/')


# --------------------------------------------------------------- commands
def cmd_extract(root: str, out_path: str):
    result, total, nfiles = {}, 0, 0
    for full, rel in sorted(iter_js(root), key=lambda x: x[1]):
        text = read_text(full)
        entries = []
        for idx, lit in enumerate(find_literals(text)):
            if not is_translatable(text, lit):
                continue
            cs, ce, quote, interp = lit
            raw = text[cs:ce]
            entries.append({
                "id": idx,                       # index into the FULL literal list (stable)
                "line": line_of(text, cs),
                "context": context_of(text, cs),
                "preview": unescape(raw),
                "original": raw,
                "translation": "",
            })
        if entries:
            result[rel] = entries
            total += len(entries)
            nfiles += 1
    json.dump(result, open(out_path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    print(f"Extracted {total} player-facing JP strings from {nfiles} files -> {out_path}")


def cmd_apply(root: str, json_path: str):
    data = json.load(open(json_path, encoding='utf-8'))
    fchg = schg = warn = 0
    for rel, entries in data.items():
        full = os.path.join(root, rel.replace('/', os.sep))
        if not os.path.isfile(full):
            print(f"WARN: missing file {rel}"); warn += 1; continue
        text = read_text(full)
        lits = find_literals(text)
        repls = []
        for e in entries:
            tr = e.get("translation", "")
            if not tr:
                continue
            i = e["id"]
            if i >= len(lits):
                print(f"WARN: {rel} id {i} out of range (file changed?)"); warn += 1; continue
            cs, ce, quote, interp = lits[i]
            raw = text[cs:ce]
            if raw == tr:
                continue                      # already applied — silently skip
            if raw != e.get("original"):
                # file hand-edited / structurally changed — skip safely, surface it.
                print(f"WARN: {rel} id {i} original mismatch — skipped"); warn += 1; continue
            if quote in tr and ('\\' + quote) not in tr:
                # an unescaped closing quote would break the literal
                print(f"WARN: {rel} id {i} translation has an unescaped {quote} — escaping it")
                tr = tr.replace(quote, '\\' + quote)
            repls.append((cs, ce, tr))
        if not repls:
            continue
        for cs, ce, tr in sorted(repls, key=lambda r: r[0], reverse=True):
            text = text[:cs] + tr + text[ce:]
        write_text(full, text)
        fchg += 1
        schg += len(repls)
    print(f"Applied {schg} translations across {fchg} files ({warn} warnings)")


def cmd_stats(json_path: str):
    data = json.load(open(json_path, encoding='utf-8'))
    rows = sorted(((len(v), k, sum(1 for e in v if e.get("translation")))
                   for k, v in data.items()), reverse=True)
    total = sum(r[0] for r in rows)
    done = sum(r[2] for r in rows)
    print(f"{'strings':>8} {'done':>5}  file")
    for cnt, name, d in rows:
        print(f"{cnt:>8} {d:>5}  {name}")
    print(f"{'-'*8}")
    print(f"{total:>8} {done:>5}  TOTAL ({len(rows)} files, {done}/{total} translated)")


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass
    ap = argparse.ArgumentParser(description="Extract/inject JP strings in SRPG Studio .js files")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract"); e.add_argument("root"); e.add_argument("-o", "--out", default="js_strings.json")
    a = sub.add_parser("apply"); a.add_argument("root"); a.add_argument("json")
    s = sub.add_parser("stats"); s.add_argument("json")
    args = ap.parse_args()
    if args.cmd == "extract":
        cmd_extract(args.root, args.out)
    elif args.cmd == "apply":
        cmd_apply(args.root, args.json)
    elif args.cmd == "stats":
        cmd_stats(args.json)


if __name__ == "__main__":
    main()
