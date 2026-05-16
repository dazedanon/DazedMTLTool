# Skill: Fix over-limit game dialogue messages via LLM API

## Files needed

| File | Purpose |
|------|---------|
| `scan_violations.py` | Run this first to generate violations.json |
| `vocab.txt` | Glossary — terms the LLM must preserve exactly |
| `output/` folder | The tool reads and writes JSON files here directly |

---

## scan_violations.py

Run this to produce `violations.json` before starting the rewrite tool.

```python
#!/usr/bin/env python3
"""Scan output/*.json and write violations.json listing every over-limit message."""
import json
from pathlib import Path

OUTPUT = Path("output")   # adjust if running from a different working directory
MAX_LINES = 3
MAX_LINE_LEN = 60
NEWLINE = "\r\n"

def is_violation(text: str) -> bool:
    lines = text.split(NEWLINE)
    if len(lines) > MAX_LINES:
        return True
    return any(len(line) > MAX_LINE_LEN for line in lines)

violations = []
for f in sorted(OUTPUT.glob("*.json")):
    data = json.loads(f.read_text(encoding="utf-8"))
    for i, entry in enumerate(data):
        if not isinstance(entry, dict):
            continue
        m = entry.get("message")
        if isinstance(m, str) and is_violation(m):
            violations.append({"file": f.name, "index": i, "original": m})

Path("violations.json").write_text(
    json.dumps(violations, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"Found {len(violations)} violations → violations.json")
```

---

## violations.json entry format

```json
{
  "file": "yst00183.json",
  "index": 2,
  "original": "Though significantly behind schedule, we completed the\r\nsurvey without losing a single crew member..."
}
```

---

## Inline validation

```python
def is_valid(text: str) -> list[str]:
    """Return list of issues, empty if valid."""
    issues = []
    lines = text.split("\r\n")
    if len(lines) > 3:
        issues.append(f"{len(lines)} lines (max 3)")
    for i, line in enumerate(lines, 1):
        if len(line) > 60:
            issues.append(f"line {i} is {len(line)} chars (max 60)")
    return issues
```

---

## System prompt

```
You are an editor for a visual novel translation. Rewrite dialogue so it fits
the game's text box.

Hard limits (non-negotiable):
- Maximum 3 lines
- Maximum 60 characters per line (every character counts)
- Break lines on spaces only — never mid-word
- Use \r\n between lines (not \n)

Rewriting rules:
1. Preserve ALL meaning — every fact and clause must survive in condensed form
2. NEVER truncate — do not drop the last sentence or clause to make it fit;
   rephrase earlier parts more tightly instead
3. If a line ends a sentence, the next line begins with a capital letter
4. Preserve these terms exactly: Settler, Assimilation, Synchronization,
   Those Things, We, Inspector, Suppressant, Brain Dive, Mutant Form,
   Mimicry, Resource War, Resource Crisis, Quarantine, Debris Field

Reply with ONLY the rewritten text. Use literal \r\n between lines.
No explanation, no quotes, no markdown.
```

---

## User prompt per message

```
Rewrite this to fit in 3 lines of max 60 characters each.
Keep all meaning. Do not drop the ending.

Original:
{original_flat}
```

`{original_flat}` = `original` with `\r\n` replaced by `\n` for readability.

---

## Retry prompt (on validation failure)

```
VALIDATION FAILED: {issues}

Rewrite more tightly. Every character counts — including spaces and punctuation.
Do NOT drop any meaning from the original. Rephrase earlier parts to make room.
```

---

## Good vs bad example

**Original (5 lines — over limit):**
```
Though significantly behind schedule, we completed the
survey without losing a single crew member, and should
arrive at Earth within two weeks by Earth time. Securing a
modest amount of resources during the voyage to Jupiter is
our primary achievement.
```

**Correct rewrite — all meaning kept, 3 lines:**
```
We finished behind schedule but without losing any crew.\r\nWe should reach Earth in two weeks. Securing some\r\nresources en route to Jupiter is our main achievement.
```

**Wrong rewrite — truncated (NEVER do this):**
```
We finished behind schedule but without losing any crew.\r\nWe should reach Earth in two weeks.
```

---

## Apply logic

```python
import json
from pathlib import Path

OUTPUT = Path("path/to/INKAN_RE_DL/output")

def apply(file: str, index: int, rewrite: str):
    path = OUTPUT / file
    data = json.loads(path.read_text(encoding="utf-8"))
    data[index]["message"] = rewrite
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
```

Write per-file after all rewrites for that file are collected to minimise disk writes.
