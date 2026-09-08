"""Independent read-only coverage audit using Esprima and HTMLParser."""
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter
import json
import re
import sys
import esprima

sys.stdout.reconfigure(encoding="utf-8")
PROJECT = Path(__file__).resolve().parents[1]
APP = PROJECT / "source/app"
JP = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
ACTIVE = json.loads((PROJECT / "reports/runtime_files.json").read_text(encoding="utf-8"))["active"]
UNITS = []
for f in (PROJECT / "store").glob("*.json"):
    if not f.name.startswith("_"):
        UNITS.extend(json.loads(f.read_text(encoding="utf-8"))["units"])
SITES = {}
for u in UNITS:
    for s in u["sites"]:
        SITES.setdefault(s["file"], []).append(s)

def source_info(rel):
    text = (APP / rel).read_text(encoding="utf-8")
    starts, offset = [], 0
    for line in text.splitlines(keepends=True):
        starts.append(offset)
        offset += len(line)
    spans = [(starts[s["line"] - 1] + s["start"], starts[s["line"] - 1] + s["end"])
             for s in SITES.get(rel, [])]
    return text, starts, spans

counts = Counter()
findings = []
for rel in ACTIVE:
    if not rel.endswith(".js"):
        continue
    text, starts, spans = source_info(rel)
    try:
        tokens = esprima.tokenize(text, {"loc": True, "range": True, "tolerant": True})
    except Exception as ex:
        findings.append({"file": rel, "tokenize_error": str(ex)})
        continue
    counts["js_files_tokenized"] += 1
    if getattr(tokens, "errors", []):
        findings.append({"file": rel, "tokenize_error": tokens.errors,
                         "raw_jp_in_entire_file": len(JP.findall(text)),
                         "escaped_jp_in_entire_file": [m.group() for m in re.finditer(r"\\u[0-9A-Fa-f]{4}", text)
                                                        if JP.search(chr(int(m.group()[2:], 16)))]})
    for token in tokens:
        if token.type not in ("String", "Template"):
            continue
        raw = token.value
        try:
            value = esprima.parseScript("(" + raw + ")").body[0].expression.value if token.type == "String" else raw
        except Exception:
            value = raw
        if not isinstance(value, str) or not JP.search(value):
            continue
        counts["jp_js_literals"] += 1
        a, b = token.range
        covered = [(x, y) for x, y in spans if x < b and y > a]
        jp_positions = [a + m.start() for m in JP.finditer(raw)]
        if covered and all(any(x <= pos < y for x, y in covered) for pos in jp_positions):
            counts["jp_js_literals_overlapping_units"] += 1
            continue
        counts["unextracted_jp_js_literals"] += 1
        findings.append({"file": rel, "line": token.loc.start.line, "column": token.loc.start.column,
                         "value": value, "context": text[max(0, a-100):min(len(text), b+100)]})

class HtmlAudit(HTMLParser):
    def __init__(self, rel):
        super().__init__(convert_charrefs=True)
        self.rel = rel
    def handle_data(self, data):
        if JP.search(data):
            findings.append({"file": self.rel, "line": self.getpos()[0], "kind": "html-text", "value": data})
            counts["jp_html_text"] += 1
    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and JP.search(value):
                findings.append({"file": self.rel, "line": self.getpos()[0], "kind": "html-attribute", "tag": tag, "attribute": key, "value": value})
                counts["jp_html_attributes"] += 1

for rel in ACTIVE:
    if rel.endswith(".html"):
        counts["html_files_parsed"] += 1
        HtmlAudit(rel).feed((APP / rel).read_text(encoding="utf-8"))

report = {"counts": dict(counts), "findings": findings}
(PROJECT / "manual/unextracted_audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
