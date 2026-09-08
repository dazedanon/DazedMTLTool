"""Final cleanup pass on batch.json after repair_batch.py.

1. Hand-fixed lines (JP-word lecture, gokkun ruby, dev memos, literal \\n code,
   tutorial ruby demo, font demo).
2. Global \\x0c -> \\f (JSON form-feed collision, covers \\f[..] AND \\font[..]).
3. \\x0d[ -> \\r[ ruby collision; any other stray CR is reported.
4. Strip icon codes the model ADDED to plain DB rows (tl has \\i[..] src lacks).
5. Strip an added @N\\n portrait prefix when the source has none.
6. Flatten spontaneous ruby: src has no \\r[..] but tl does -> keep base only.
7. Speaker-tag replacement from glossary + translated names (rerun after
   glossary additions).
8. ASCII multi-speaker tags: interpunct -> " & " ([Asuka・Momoka] -> [Asuka & Momoka]).
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_translate import (load_batch, save_batch, load_glossary,
                              code_multiset, JP_RE)
from repair_batch import build_name_map

HAND_FIXES = {
    ("out/CommonEvent.json", "1|/scenes/15/lines/1/text"):
        "Some equipment cannot be removed,\\nso this item could not be equipped.",
    ("out/CommonEvent.json", "1|/scenes/86/lines/11/text"):
        'In Japanese, it\'s sometimes called "toku" (virtue), "kudoku" (merit),\n'
        'or "zengyo" (good deeds), but there\'s no single word that captures it perfectly.\n'
        "That's because it's not a native Japanese concept - it comes from Buddhist (Indian) thought.",
    ("out/CommonEvent.json", "1|/scenes/463/lines/1/text"):
        "　\\E\\f[70]\\r[Perfect Swallow,Gokkun Bonus]!",
    ("out/CommonEvent.json", "1|/scenes/555/lines/7/text"):
        "Maria and Kanon's character data wasn't created during test play, so this is a supplement.\n"
        "Please use only once (Maria's calendar resets each time you use it).",
    ("out/map_Map014_1.json", "26|/scenes/0/lines/0/text"):
        "[Tone-Deaf Student]\nSensei! Can being tone-deaf actually be fixed!?",
    ("out/map_SampleMapA.json", "103|/scenes/6/lines/29/text"):
        '"Also, if you type \\\\r[life,life], it appears as\n'
        "　 \\r[life,life] with ruby text\n"
        "　on top of it…….\\f[9]\n"
        "　(Ruby color is set in System DB Type 12, Data 13)",
    ("out/map_SampleMapA.json", "103|/scenes/6/lines/37/text"):
        "MS Gothic → \\font[0]aiueo 012345 ABCDE\n"
        "Arial Black → \\font[1]　　　　　 012345 ABCDE",
}

_ICON_RE = re.compile(r"\\i\[\d+\]")
_PORTRAIT_PREFIX_RE = re.compile(r"^@\d+\n")
_RUBY_FULL_RE = re.compile(r"\\r\[([^,\]]*),[^\]]*\]")
_TAG_RE = re.compile(r"\[([^\[\]\n]{1,32})\]")
_ASCII_MULTI_RE = re.compile(r"^[A-Za-z .'&-]+(?:・[A-Za-z .'&-]+)+$")


def main():
    batch = load_batch()
    glossary = load_glossary()
    name_map = build_name_map(batch, glossary)
    stats = {k: 0 for k in ("hand", "ff", "cr", "cr_left", "icon", "portrait",
                            "ruby", "tag", "interpunct")}

    for l in batch["lines"]:
        tl = l.get("text") or ""
        if not tl:
            continue
        key = (l["file"].replace("\\", "/"), l["id"])
        if key in HAND_FIXES:
            l["text"] = HAND_FIXES[key]
            stats["hand"] += 1
            continue
        orig = tl
        if "\x0c" in tl:
            tl = tl.replace("\x0c", "\\f")
            stats["ff"] += 1
        if "\x0d[" in tl:
            tl = tl.replace("\x0d[", "\\r[")
            stats["cr"] += 1
        if "\x0d" in tl:
            stats["cr_left"] += 1

        src_codes = code_multiset(l["source"])
        tl_codes = code_multiset(tl)

        for tok in set(_ICON_RE.findall(tl)):
            excess = tl_codes.count(tok) - src_codes.count(tok)
            for _ in range(max(0, excess)):
                tl = tl.replace(tok, "", 1)
                stats["icon"] += 1

        m = _PORTRAIT_PREFIX_RE.match(tl)
        if m and m.group(0).strip() not in src_codes and not l["source"].startswith("@"):
            tl = tl[m.end():]
            stats["portrait"] += 1

        if "\\r[" in tl and "\\r[]" not in src_codes:
            tl, n = _RUBY_FULL_RE.subn(r"\1", tl)
            stats["ruby"] += n

        def sub_tag(mm):
            inner = mm.group(1)
            if JP_RE.search(inner) and inner in name_map:
                stats["tag"] += 1
                return f"[{name_map[inner]}]"
            if "・" in inner and _ASCII_MULTI_RE.match(inner):
                stats["interpunct"] += 1
                return "[" + " & ".join(p.strip() for p in inner.split("・")) + "]"
            return mm.group(0)

        tl = _TAG_RE.sub(sub_tag, tl)
        if tl != orig:
            l["text"] = tl

    save_batch(batch)
    for k, v in stats.items():
        print(f"{k:>10}: {v}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
