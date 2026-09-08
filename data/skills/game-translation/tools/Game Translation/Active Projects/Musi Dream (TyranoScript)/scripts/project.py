"""musi_dream preparation adapter. Local files only; no translation service."""
from __future__ import annotations

import bisect
import collections
import hashlib
import json
import posixpath
import re
from pathlib import Path

from tyranotl import codes, extract, jsstr, kslex, sites
from tyranotl.store import Site, Unit, unit_id

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "source/app"
STORE = ROOT / "store"
REPORTS = ROOT / "reports"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def verify_source():
    manifest = read_json(ROOT / "source/manifest.json")
    for rel, sha in manifest["files"].items():
        if digest((SOURCE / rel).read_bytes()) != sha:
            raise ValueError(f"Source snapshot changed: {rel}. Restore it; never extract from a patched tree.")
    return digest((ROOT / "source/manifest.json").read_bytes())


def discover():
    """Follow literal runtime references, including JS sample/config paths.

    Root config is included as the engine fallback. Dynamic references are
    reported, never used to exclude a file silently.
    """
    reasons = {}
    queue = []
    edges = []
    dynamic = []

    def add(rel, owner, why):
        rel = posixpath.normpath(rel.removeprefix("./"))
        if rel.startswith("../") or not (SOURCE / rel).is_file():
            return
        edges.append({"from": owner, "to": rel, "reason": why})
        if rel not in reasons:
            reasons[rel] = why
            queue.append(rel)

    for rel in ("index.html", "main.js", "data/system/KeyConfig.js", "data/scenario/first.ks", "data/scenario/config.ks"):
        add(rel, "entry", "entry point or built-in configuration fallback")
    while queue:
        rel = queue.pop(0)
        raw = (SOURCE / rel).read_bytes().decode("utf-8", errors="replace")
        if rel.endswith(".ks"):
            script = kslex.read(SOURCE / rel, rel)
            for line in script.lines:
                if line.kind == "comment":
                    continue
                for tag in line.tags:
                    pm = {a.name: a.value for a in tag.attrs}
                    if tag.name == "plugin" and "name" in pm:
                        add(f"data/others/plugin/{pm['name']}/init.ks", rel, "plugin entry")
                    for key in ("storage", "file"):
                        val = pm.get(key, "")
                        if val.startswith(("&", "%")):
                            dynamic.append({"file": rel, "line": line.number, "tag": tag.name, "param": key, "value": val})
                        elif val.endswith(".ks"):
                            add("data/scenario/" + val, rel, "scenario storage")
                        elif tag.name == "loadjs":
                            add("data/others/" + val, rel, "loadjs")
                        elif tag.name in ("sysview", "loadcss"):
                            add(val, rel, tag.name)
        # Exact asset references in code and HTML. Do not crawl links or run code.
        if rel.endswith((".html", ".js", ".ks", ".css")):
            cleaned = re.sub(r"<!--.*?-->", "", raw, flags=re.S)
            if rel.endswith(".js"):
                cleaned = jsstr._blank_comments(cleaned)
            for val in re.findall(r'''["']([^"'\r\n]+\.(?:ks|js|html|css))["']''', cleaned):
                if val.startswith(("./", "data/", "tyrano/")):
                    add(val, rel, "literal runtime reference")
                elif val.startswith("../others/"):
                    add("data/scenario/" + val, rel, "configuration scenario reference")
    return reasons, edges, dynamic


class GameExtractor(extract.Extractor):
    def __init__(self, app_root):
        super().__init__(app_root)
        self.current_speaker = ""
        self.registered = set()
        self.speaker_sites = []

    def _add(self, kind, masked, tokens, site, bucket, scene="", speaker=""):
        # Occurrence IDs for prose: no accidental cross-speaker or cross-route
        # deduplication inherited from the old extractor.
        if kind in ("dialogue", "punct"):
            uid = unit_id(kind, f"{site.file}:{site.line}:{site.start}\0{masked}")
        else:
            uid = unit_id(kind, masked)
        site.tokens = tokens
        if uid not in self.units:
            self.units[uid] = Unit(id=uid, kind=kind, src=masked, scene=scene, speaker=speaker)
            self.bucket_of[uid] = bucket
        self.order += 1
        site.order = self.order
        self.units[uid].sites.append(site)

    def scan_scripts(self, scripts):
        for script in scripts:
            for line in script.lines:
                for tag in line.tags:
                    if tag.name == "chara_new":
                        pm = {a.name: a.value for a in tag.attrs}
                        self.registered.add(pm["name"])
        for script in scripts:
            self.current_speaker = ""
            # Classify # lines before the reference message extractor sees them.
            for line in script.lines:
                if line.text.lstrip().startswith("#"):
                    line.kind = "speaker"
            super().scan_scripts([script])

    def _scan_attrs(self, script, line, bucket, label, body_span):
        if line.kind == "speaker":
            start = line.text.index("#") + 1
            raw = line.text[start:].split(":", 1)[0].strip()
            start = line.text.index(raw, start) if raw else start
            self.current_speaker = raw
            self.speaker_sites.append({"file": script.rel, "line": line.number, "key": raw,
                                       "registered_id": raw in self.registered})
            if raw in self.registered:
                self._drop(script.rel, line.number, "character-id", "#", "name", raw)
            elif raw:
                site = Site(script.rel, line.number, start, start + len(raw), raw=raw,
                            form="speaker", tag="#", param="name", label=label, context=line.text)
                self._add("name", raw, [], site, "Names", f"{script.rel}#{label}", raw)
            else:
                # Empty # explicitly resets to narration.
                self._drop(script.rel, line.number, "narration-reset", "#", "name", "")
            return
        super()._scan_attrs(script, line, bucket, label, body_span)

    def _add_message(self, script, line, bucket, label, span):
        before = set(self.units)
        super()._add_message(script, line, bucket, label, span)
        for uid in set(self.units) - before:
            if self.units[uid].kind in ("dialogue", "punct"):
                self.units[uid].speaker = self.current_speaker or "(narration)"

    def scan_js_file(self, rel):
        script = kslex.read(SOURCE / rel, rel)
        raw = script.render()
        if rel.startswith("tyrano/libs/") or rel == "tyrano/plugins/kag/kag.tag_three.js":
            # Vendor CJK numeral alphabets are algorithms, not game labels.
            # 3D is disabled in Config.tjs and no game script calls 3d_*.
            reason = "vendor-library-data" if rel.startswith("tyrano/libs/") else "disabled-3d-tooling"
            for line in script.lines:
                if codes.has_jp(line.text):
                    self._drop(rel, line.number, reason, "js", "", line.text[:200])
            return
        starts = []
        offset = 0
        for line in script.lines:
            starts.append(offset)
            offset += len(line.text + line.sep)
        for literal in jsstr.scan(raw):
            if not codes.has_jp(literal.value):
                continue
            i = bisect.bisect_right(starts, literal.start - 1) - 1
            line = script.lines[i]
            start, end = literal.start - 1 - starts[i], literal.end + 1 - starts[i]
            if end > len(line.text):
                self._drop(rel, line.number, "review-multiline-js", "js", "", literal.raw)
                continue
            if sites.looks_like_asset(literal.value) or literal.value == "メイリオ":
                self._drop(rel, line.number, "asset-or-font", "js", "", literal.value)
                continue
            if literal.quote == "`":
                self._drop(rel, line.number, "developer-template-diagnostic", "js", "", literal.value)
                continue
            if literal.value in {"現在登録されているイベントリスナ\n", "セーブデータ。localstorageが利用できません。", "セーブデータ作成エラー", "callスタックが残っている場合、fixボタンは反応しません", "trace出力：", "*error:この環境は[speak_on]の読み上げ機能に対応していません"}:
                self._drop(rel, line.number, "console-diagnostic", "js", "", literal.value)
                continue
            # The reference's line-by-line scan extracted block-comment examples.
            # Whole-file scanning above preserves comment state.
            masked, tokens = codes.mask(literal.value)
            site = Site(rel, line.number, start, end, form="jsstr", raw=line.text[start:end],
                        tag="js", quote=literal.quote,
                        context=line.text[max(0, start-180):min(len(line.text), end+180)])
            self._add("js", masked, tokens, site, "Engine" if rel.startswith("tyrano/") else "UI")


def extraction():
    active, edges, dynamic = discover()
    ex = GameExtractor(SOURCE)
    scripts = [kslex.read(SOURCE / rel, rel) for rel in sorted(active) if rel.endswith(".ks")]
    ex.collect_keys(scripts)
    ex.scan_scripts(scripts)
    for rel in sorted(active):
        if rel.endswith(".js"):
            ex.scan_js_file(rel)
    ex.lock_key_collisions()
    store = ex.build_store(STORE)
    for u in store.all_units():
        if u.status == "manual":
            u.en = None
            u.status = "hold"
    write_json(REPORTS / "runtime_files.json", {"active": active, "edges": edges, "dynamic_references": dynamic})
    write_jsonl(REPORTS / "excluded.jsonl", [x.to_json() for x in ex.excluded])
    write_json(REPORTS / "speakers.json", ex.speaker_sites)
    write_json(REPORTS / "engine_keys.json", sorted(ex.keys | ex.registered))
    # Independent line census: every JP line gets a disposition, including files
    # outside the extractor's supported text shapes. Unresolved runtime lines fail.
    covered = {(s.file, s.line) for u in store.all_units() for s in u.sites}
    excluded = collections.defaultdict(list)
    for x in ex.excluded:
        excluded[x.file, x.line].append(x.reason)
    census = []
    for p in sorted(SOURCE.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(SOURCE).as_posix()
        raw = p.read_bytes().decode("utf-8", errors="replace")
        noncomments = jsstr._blank_comments(raw).splitlines() if p.suffix == ".js" else []
        block = False
        html_script = False
        for n, text in enumerate(raw.splitlines(), 1):
            stripped = text.strip()
            comment = block or stripped.startswith((";", "//", "/*", "<!--"))
            if stripped.startswith(("/*", "<!--")):
                block = not ("*/" in stripped or "-->" in stripped)
            elif "*/" in stripped or "-->" in stripped:
                block = False
            if not codes.has_jp(text):
                continue
            if (rel, n) in covered:
                reason = "extracted"
            elif excluded[rel, n]:
                reason = ",".join(sorted(set(excluded[rel, n])))
            elif rel not in active:
                reason = "not-runtime-referenced" if rel not in ("data/system/Config.tjs", "package.json") else "technical-configuration"
            elif comment:
                reason = "comment"
            elif p.suffix == ".js" and n <= len(noncomments) and not codes.has_jp(noncomments[n-1]):
                reason = "inline-comment"
            elif p.suffix == ".css":
                clean = re.sub(r"/\*.*?\*/", "", text)
                if not codes.has_jp(clean):
                    reason = "inline-comment"
                elif "font-family:" in text or stripped.startswith('Osaka, "ＭＳ'):
                    reason = "font-family"
                else:
                    reason = "UNRESOLVED"
            else:
                reason = "UNRESOLVED"
            census.append({"file": rel, "line": n, "reason": reason, "text": text[:500]})
    write_jsonl(REPORTS / "census.jsonl", census)
    layout = []
    for s in scripts:
        for line in s.lines:
            if line.kind == "comment":
                continue
            for tag in line.tags:
                if tag.name in ("position", "fuki_chara", "ptext", "glink", "font", "deffont", "resetfont", "tb_fuki_start", "tb_fuki_stop"):
                    layout.append({"file": s.rel, "line": line.number, "tag": tag.name,
                                   "params": {a.name:a.value for a in tag.attrs}})
    write_json(REPORTS / "layout_sites.json", layout)
    summary = {"units": len(store.all_units()), "occurrences": sum(len(u.sites) for u in store.all_units()),
               "kinds": dict(collections.Counter(u.kind for u in store.all_units())),
               "source_characters": sum(len(u.src) for u in store.all_units()),
               "runtime_files": len(active), "scenario_files": len(scripts),
               "census": dict(collections.Counter(r["reason"] for r in census)),
               "unknown_sites": {str(k):v for k,v in ex.unknown_sites.items()}}
    write_json(REPORTS / "extraction.json", summary)
    return store, summary
