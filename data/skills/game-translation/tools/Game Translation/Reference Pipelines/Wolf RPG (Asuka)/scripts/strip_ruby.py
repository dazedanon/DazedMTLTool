"""Strip ruby markup from all translations: \\r[base,reading] -> base.

WolfDawn treats \\r[..] as droppable markup (never in the must-preserve set),
so removal is injection-safe. The escaped form \\\\r[..] (the \\\\ code followed
by literal text, used in the sample-map tutorial) is left untouched.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from claude_translate import load_batch, save_batch

# not preceded by a backslash: \\r[..] is the \\ code + plain text, keep it
RUBY_RE = re.compile(r"(?<!\\)\\r\[([^,\]]*)(?:,[^\]]*)?\]")

batch = load_batch()
lines_hit = subs = 0
for l in batch["lines"]:
    tl = l.get("text") or ""
    if "\\r[" not in tl:
        continue
    new, n = RUBY_RE.subn(r"\1", tl)
    if n:
        l["text"] = new
        lines_hit += 1
        subs += n
save_batch(batch)
print(f"stripped {subs} ruby code(s) across {lines_hit} line(s)")
