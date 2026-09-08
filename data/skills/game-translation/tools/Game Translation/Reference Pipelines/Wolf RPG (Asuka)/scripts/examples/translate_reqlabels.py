"""Translate the required-value window's stat labels (CommonEvent event 639).

The window reads each stat's field NAME from type 66 via a dataID=-3 name-get
into CSelf[6], then draws "CSelf[6]:CSelf[14]" ("行動力:10"). The game already
overrides one label (field 8 -> "(Secret Account) Fans"). We extend that same
override to all 14 T66 field indices with English labels. This edits ONLY the
event's string-setting - no DB schema field name, no lookup key, no condition
literal is touched - so it cannot cause the by-name-lookup DB error that the
earlier schema patch did.
"""
import sys
from pathlib import Path

# T66 field index -> English label (field 8 keeps the game's own relabel)
LABELS = [
    "Singing", "Looks", "Stamina", "Wisdom", "Courage", "Lewd", "Morality",
    "Fans", "(Secret Account) Fans", "Lucky Star", "Money", "AP", "Stress", "AP",
]

OLD = (
    '            branch {\n'
    '            } when (CSelf[10 "loop"] == 8) {\n'
    '                SetString(targetRef=CSelf[6], modeFlags=0, arg2=0) "(Secret Account) Fans"\n'
    '            }\n'
)


def build_new():
    lines = ["            branch {"]
    for i, lbl in enumerate(LABELS):
        esc = lbl.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'            }} when (CSelf[10 "loop"] == {i}) {{')
        lines.append(f'                SetString(targetRef=CSelf[6], modeFlags=0, arg2=0) "{esc}"')
    lines.append("            }")
    return "\n".join(lines) + "\n"


def main():
    src, dst = sys.argv[1], sys.argv[2]
    text = Path(src).read_text(encoding="utf-8")
    if OLD not in text:
        sys.exit("ERROR: target block not found (event structure changed?)")
    if text.count(OLD) != 1:
        sys.exit(f"ERROR: target block found {text.count(OLD)} times, expected 1")
    Path(dst).write_text(text.replace(OLD, build_new(), 1), encoding="utf-8")
    print(f"replaced 1 block; {len(LABELS)} stat labels set")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
