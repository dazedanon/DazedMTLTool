"""Lines the parser will not treat as text because of their first character.

`parseScenario` dispatches on the first character of the *trimmed* line:
`;` comment, `*` label, `@` bare tag, `#` chara_ptext, `_` literal-leading-space.
A translation that opens with one of those turns a line of dialogue into
something else entirely - `ボロンッ[p]` came back as `*fwip*[p]` and is now a
label named `fwip*[p`, so the sound effect never appears at all.
"""
from pathlib import Path

SPECIAL = ";*@#"
APP = Path("tools/extracted/app/data/scenario")
OUT = Path("tools/translated/data/scenario")

bad = []
for path in sorted(OUT.rglob("*.ks")):
    rel = path.relative_to(OUT).as_posix()
    src = APP / rel
    if not src.exists():
        continue
    ja = src.read_text(encoding="utf-8", errors="replace").split("\n")
    en = path.read_text(encoding="utf-8", errors="replace").split("\n")
    if len(ja) != len(en):
        print(f"line count differs in {rel}")
        continue
    for n, (a, b) in enumerate(zip(ja, en), 1):
        a, b = a.strip(), b.strip()
        if not b:
            continue
        was = a[:1] in SPECIAL if a else False
        now = b[:1] in SPECIAL
        if now and not was:
            bad.append((rel, n, a[:52], b[:52]))

print(f"lines the translation turned into a label/comment/tag: {len(bad)}")
for rel, n, a, b in bad:
    print(f"  {rel}:{n}")
    print(f"    JP {a!r}")
    print(f"    EN {b!r}")
