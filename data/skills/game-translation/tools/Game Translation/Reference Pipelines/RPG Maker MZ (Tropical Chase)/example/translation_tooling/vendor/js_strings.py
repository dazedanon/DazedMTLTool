"""Find Japanese STRING LITERALS in plugin source - not comments, not help blocks.

`plugins_js.py` covers plugin PARAMETERS, which is where most plugin-authored
UI text lives. It cannot see text a plugin hardcodes in its own code, and that
text has no unit, so nothing downstream knows it exists. A casino minigame
shipped fully Japanese because of exactly this gap.

The scanner is a JS tokenizer rather than a regex: the `/*: @help` annotation
block at the top of every MZ plugin is a huge Japanese comment that must NOT be
picked up, and the only reliable way to tell it from a string is to walk the
source.
"""
import json, os, re, sys

JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uff66-\uff9d]")


def literals(src):
    """[(quote, raw_body, start, end)] for every string/template literal."""
    out = []
    i, n = 0, len(src)
    # `prev` is the last significant char, used only to tell a regex literal
    # from a division - a false regex would just hide a string, never corrupt.
    prev = ""
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == "/" and prev in "" "(,=:[!&|?{};\n" and prev != "":
            j, esc, cls = i + 1, False, False
            while j < n:
                d = src[j]
                if esc:
                    esc = False
                elif d == "\\":
                    esc = True
                elif d == "[":
                    cls = True
                elif d == "]":
                    cls = False
                elif d == "/" and not cls:
                    break
                elif d == "\n":
                    j = i    # not a regex after all
                    break
                j += 1
            if j > i:
                i = j + 1
                prev = "/"
                continue
        if c in "'\"`":
            j, esc = i + 1, False
            while j < n:
                d = src[j]
                if esc:
                    esc = False
                elif d == "\\":
                    esc = True
                elif d == c:
                    break
                elif d == "\n" and c != "`":
                    break
                j += 1
            if j < n and src[j] == c:
                out.append((c, src[i + 1:j], i, j + 1))
                i = j + 1
                prev = c
                continue
        if not c.isspace():
            prev = c
        i += 1
    return out


def scan(path):
    src = open(path, encoding="utf-8-sig").read()
    hits = []
    for q, body, a, b in literals(src):
        if JP.search(body):
            line = src.count("\n", 0, a) + 1
            hits.append({"line": line, "quote": q, "text": body,
                         "start": a, "end": b})
    return src, hits


def enabled(root):
    t = open(os.path.join(root, "js", "plugins.js"), encoding="utf-8-sig").read()
    arr = json.loads(re.search(r"\$plugins\s*=\s*(\[.*\])\s*;", t, re.S).group(1))
    return [p["name"] for p in arr if p.get("status")]


if __name__ == "__main__":
    root = sys.argv[1]
    total = 0
    for name in enabled(root):
        p = os.path.join(root, "js", "plugins", name + ".js")
        if not os.path.exists(p):
            continue
        _src, hits = scan(p)
        if hits:
            total += len(hits)
            print("%-42s %3d" % (name, len(hits)))
    print("-- %d Japanese string literals in enabled plugin source" % total)
