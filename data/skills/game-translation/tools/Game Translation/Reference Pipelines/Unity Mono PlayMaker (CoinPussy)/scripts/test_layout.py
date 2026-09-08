import sys

sys.path.insert(0, r"c:\Users\sw\Desktop\Games\CoinPussy\tools\scripts")
from unitytl.layout import reflow, flatten, line_count  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    if got == want:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}:\n  got  {got!r}\n  want {want!r}")
        fails += 1


def check_pred(name, cond, detail=""):
    global fails
    if cond:
        print(f"ok   {name}")
    else:
        print(f"FAIL {name}  {detail}")
        fails += 1


# Already correct — must be returned untouched.
check("unchanged when count matches", reflow("one line", 1), "one line")
check("unchanged when 2 and 2", reflow("a b\nc d", 2), "a b\nc d")

# The dominant case: 2-line source came back as one line.
out = reflow("Whaaat!? M-me!?", 2)
check("splits after sentence punctuation", out, "Whaaat!?\nM-me!?")

out = reflow("Huh!? Y-you're... here for the \"Special Game\" again...!?", 2)
check_pred("break lands on a strong end", out.split("\n")[0].endswith(("!?", "...")),
           f"got {out!r}")
check_pred("two lines produced", line_count(out) == 2, f"got {out!r}")

# Balance: neither line should be wildly longer than the other.
out = reflow("Good, good. But one more slip-up, and every video you've ever made "
             "goes up for free!", 2)
a, b = out.split("\n")
check_pred("balanced within 40%", abs(len(a) - len(b)) <= 0.4 * max(len(a), len(b)),
           f"{len(a)} vs {len(b)}: {out!r}")

# Collapsing too many lines back down.
check("joins 3 lines into 1", reflow("a\nb\nc", 1), "a b c")
check_pred("joins 3 into 2", line_count(reflow("alpha beta\ngamma delta\nepsilon", 2)) == 2)

# Masked control codes stay intact.
out = reflow("Press ⟦0⟧ to continue and then press ⟦1⟧ to confirm your choice now", 2)
check_pred("placeholders survive", "⟦0⟧" in out and "⟦1⟧" in out, out)
check_pred("placeholders not split", "⟦0⟧" in out.replace("\n", " "), out)

# Degenerate input must not raise or lose text.
check("single word cannot split", reflow("Word", 2), "Word")
check("empty stays empty", reflow("", 2), "")
check_pred("no text lost", set(flatten(reflow(
    "The quick brown fox jumps over the lazy dog near the river", 3)).split())
    == set("The quick brown fox jumps over the lazy dog near the river".split()))
check_pred("exact line count for n=3",
           line_count(reflow("one two three four five six seven eight nine", 3)) == 3)

# Full-width pacing gap is content, not indentation.
out = reflow("A-ah\u3000ah\u3000ah it hurts so much please stop it now okay", 2)
check_pred("full-width gap preserved", "\u3000" in out, out)

# --- fit_box: width is a hard constraint, not a preference ---
from unitytl.layout import fit_box, _display_width  # noqa: E402

ELL = chr(0x2026)
case = ("But really, there's no way you could pay this off, is there" + ELL + "?"
        + chr(10) + "It'd be a shame for someone so young to drown in debt" + ELL)
got, ok = fit_box(case, 53, 3)
widths = [_display_width(ln) for ln in got.split(chr(10))]
check_pred("fit_box respects width", ok and max(widths) <= 53, f"{widths} {got!r}")
check_pred("fit_box respects height", line_count(got) <= 3, repr(got))

# This exact string used to come back as [30, 30, 54]: breaking after "is there…?"
# earned a punctuation bonus that outweighed leaving a 54-cell line clipped.
check_pred("punctuation bonus cannot buy an overflowing line",
           max(widths) <= 53, str(widths))

# Text that cannot fit at any breaking must report it rather than silently clip.
_g, ok2 = fit_box(" ".join(["word"] * 80), 20, 2)
check_pred("unfittable text reports ok=False", ok2 is False)

print(f"\n{'FAILED' if fails else 'all passed'} ({fails} failures)")
sys.exit(1 if fails else 0)
