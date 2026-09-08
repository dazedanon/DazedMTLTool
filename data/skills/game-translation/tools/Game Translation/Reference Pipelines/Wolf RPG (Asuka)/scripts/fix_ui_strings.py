"""UI string fixes on the deployed CommonEvent wscript.

Covers what the item/menu/save screens surfaced in play testing:
  * full-width punctuation in composed UI strings (save-time ：, volume ％,
    money ￥, masks ？？, list digits １２３...) -> ASCII, with an
    adjacency guard so a letter/digit never lands directly after a
    single-letter control code (\\E + x would tokenize as \\Ex);
  * four never-extracted Japanese display strings (settings voice help,
    talent requirement failures, the 3/31 date line);
  * fixed-position labels that overflow into their values: settings labels,
    the status window's Appearance column, Knockdown Rate.

Only depth-0 string literals of display commands are touched; bracketed
operand annotations (compiler symbol labels) are never modified.

Usage: python scripts/fix_ui_strings.py IN.wscript OUT.wscript
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from relayout import unescape, escape

DISPLAY_CMDS = ("Message", "Picture", "SetString", "choose", "case", "Choices")

# transforms run on the UNESCAPED literal text, in order
EXACT = {
    "ボイスのON/OFFを設定します": "Sets voice ON/OFF.",
    "今日は春も穏やかな3/31": "Today is 3/31, a calm spring day.",
    " Save Cursor Position": " Save Cursor Pos.",
    " Auto-Repeat in Battle": " Battle Repeat",
    "Knockdown Rate": "KO Rate",
}
REGEX = [
    (re.compile(r"　「(\\cself\[\d+\])」の回数が足りません\((\\cself\[\d+\])/(\\cself\[\d+\])\)"),
     r"　Not enough uses of \1 (\2/\3)"),
    (re.compile(r"　ステータス「(\\cself\[\d+\])」が足りません\((\\cself\[\d+\])/(\\cself\[\d+\])\)"),
     r"　Status \1 is too low (\2/\3)"),
    (re.compile(r"Appearance (?=\\cdb\[28:0:5\])"), "Looks "),
    # letters/digits are unsafe directly after a single-letter code (\E, \f...)
    (re.compile(r"(?<![A-Za-z])×"), "x"),
    (re.compile(r"(?<![A-Za-z0-9])([０-９])"),
     lambda m: chr(ord(m.group(1)) - 0xFF10 + ord("0"))),
]
CHARMAP = str.maketrans({
    "：": ":", "？": "?", "％": "%", "￥": "¥", "、": ",", "。": ".",
    "＋": "+", "＜": "<", "＞": ">", "『": '"', "』": '"',
    "－": "-", "―": "-", "─": "-", "（": "(", "）": ")",
})


def fix_literal(text):
    for src, dst in EXACT.items():
        if src in text:
            text = text.replace(src, dst)
    for rx, rep in REGEX:
        text = rx.sub(rep, text)
    return text.translate(CHARMAP)


def literal_spans(line):
    """Spans of depth-0 string literals (raw, incl. quotes). Bracketed
    operand annotations are at depth > 0 and skipped."""
    spans = []
    depth = 0
    i = 0
    n = len(line)
    while i < n:
        c = line[i]
        if c == "[":
            depth += 1
        elif c == "]":
            depth = max(0, depth - 1)
        elif c == '"':
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == '"':
                    break
                j += 1
            if depth == 0:
                spans.append((i, j + 1))
            i = j
        i += 1
    return spans


def main():
    src, dst = sys.argv[1], sys.argv[2]
    changed = 0
    out = []
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        cmd = line.strip().split(" ", 1)[0].split("(", 1)[0]
        if cmd in DISPLAY_CMDS:
            new = line
            for a, b in reversed(literal_spans(line)):
                lit = unescape(line[a + 1:b - 1])
                fixed = fix_literal(lit)
                if fixed != lit:
                    new = new[:a] + '"' + escape(fixed) + '"' + new[b:]
            if new != line:
                changed += 1
                line = new
        out.append(line)
    Path(dst).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{Path(src).name}: {changed} lines fixed")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
