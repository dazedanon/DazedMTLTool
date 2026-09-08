"""Walk the TyranoScript project and build the translation store.

Text lives in five shapes and each is handled at source:

1. message lines in ``.ks``      -> ``dialogue`` (scene-grouped, never deduped)
2. tag attributes                -> ``choice`` / ``ptext`` / ``notice`` / ...
3. JS literals in ``exp=``/``cond=`` and in ``&``-expressions -> ``code``
4. JS literals in ``[iscript]`` blocks   -> ``code``
5. JS literals in the three engine ``.js`` files -> ``js``

Anything Japanese that is *not* turned into a unit is written to
``excluded.jsonl`` with a reason, so nothing is ever dropped silently.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import codes, jsstr, kslex, sites
from .store import Site, Store, Unit, unit_id


@dataclass
class Excluded:
    file: str
    line: int
    reason: str
    tag: str
    param: str
    text: str

    def to_json(self) -> dict:
        return {"file": self.file, "line": self.line, "reason": self.reason,
                "tag": self.tag, "param": self.param, "text": self.text}


class Extractor:
    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.units: dict[str, Unit] = {}
        self.bucket_of: dict[str, str] = {}
        self.excluded: list[Excluded] = []
        self.order = 0
        self.unknown_sites: dict[tuple[str, str], int] = {}
        #: every label name and jump/call target in the project. A string that
        #: appears here is an engine key: translating it would break control flow.
        self.keys: set[str] = set()

    # ------------------------------------------------------------------ util

    def _add(self, kind: str, masked: str, tokens: list[str], site: Site,
             bucket: str, scene: str = "", speaker: str = "") -> None:
        uid = unit_id(kind, masked)
        site.tokens = tokens
        unit = self.units.get(uid)
        if unit is None:
            unit = Unit(id=uid, kind=kind, src=masked, scene=scene, speaker=speaker)
            self.units[uid] = unit
            self.bucket_of[uid] = bucket
        self.order += 1
        site.order = self.order
        unit.sites.append(site)

    def _drop(self, rel: str, line: int, reason: str, tag: str, param: str, text: str) -> None:
        self.excluded.append(Excluded(rel, line, reason, tag, param, text))
        if reason == "unknown-site":
            key = (tag, param)
            self.unknown_sites[key] = self.unknown_sites.get(key, 0) + 1

    # ------------------------------------------------------------- .ks files

    def collect_keys(self, scripts: list[kslex.Script]) -> None:
        for script in scripts:
            for line in script.lines:
                if line.kind == "label":
                    self.keys.add(line.text.strip().lstrip("*").split("|")[0].strip())
                for tag in line.tags:
                    for attr in tag.attrs:
                        if attr.name in ("target", "name", "var", "key", "storage"):
                            self.keys.add(attr.value.lstrip("*&").strip())

    def scan_scripts(self, scripts: list[kslex.Script]) -> None:
        for script in scripts:
            bucket = sites.bucket_for(script.rel)
            script_ranges = kslex.iscript_ranges(script)
            in_script = set()
            for start, end in script_ranges:
                in_script.update(range(start, end))

            for index, line in enumerate(script.lines):
                if index in in_script:
                    self._scan_js_region(script.rel, line, bucket, "code")
                    continue
                if line.kind in ("blank", "comment"):
                    if line.kind == "comment" and codes.has_jp(line.text):
                        self._drop(script.rel, line.number, "author-comment", "", "", line.text.strip())
                    continue
                if line.kind == "label":
                    if codes.has_jp(line.text):
                        self._drop(script.rel, line.number, "label-identifier", "", "", line.text.strip())
                    continue

                before = (self.order, len(self.excluded))
                label = kslex.label_at(script, index)
                body_span = self._message_span(line) if line.kind in ("text", "tag") else None
                self._scan_attrs(script, line, bucket, label, body_span)
                if body_span is not None:
                    self._add_message(script, line, bucket, label, body_span)
                if (self.order, len(self.excluded)) == before and codes.has_jp(line.text):
                    # Nothing recognised the Japanese on this line - usually a
                    # malformed tag (exp.ks:366 has an unterminated quote).
                    self._drop(script.rel, line.number, "unparsed-line", "", "", line.text.strip())

    def _message_span(self, line: kslex.Line) -> tuple[int, int] | None:
        """Character range of the message-text run on this line, or ``None``.

        A ``.ks`` line can be ``[cm][s_e6]text[emb ...]more[p]``. The run starts
        after the leading tags and ends before the trailing ones; inline tags
        keep their place inside it and are masked.
        """
        masked, _tokens = codes.mask(line.text)
        prefix, middle, suffix = codes.split_affixes(masked)
        if not middle.strip():
            return None
        # Map the masked offsets back onto the raw line.
        start = self._unmask_offset(line.text, masked, len(prefix))
        end = self._unmask_offset(line.text, masked, len(masked) - len(suffix))
        raw = line.text[start:end]
        if not raw.strip():
            return None
        if not (codes.has_jp(raw) or codes.has_fullwidth_punct(raw)):
            return None
        if "[" in middle or "]" in middle:
            return None   # unmatched bracket -> malformed tag, see _drop below
        return start, end

    @staticmethod
    def _unmask_offset(raw: str, masked: str, masked_offset: int) -> int:
        """Translate an offset in the masked string back to the raw string."""
        raw_i = 0
        masked_i = 0
        tokens = list(codes.MASK_RE.finditer(raw))
        token_i = 0
        while masked_i < masked_offset:
            if token_i < len(tokens) and tokens[token_i].start() == raw_i:
                m = codes.SENTINEL_RE.match(masked, masked_i)
                if m is None:
                    raise AssertionError("sentinel expected while unmasking")
                masked_i = m.end()
                raw_i = tokens[token_i].end()
                token_i += 1
            else:
                masked_i += 1
                raw_i += 1
        return raw_i

    def _add_message(self, script: kslex.Script, line: kslex.Line, bucket: str,
                     label: str, span: tuple[int, int]) -> None:
        start, end = span
        raw = line.text[start:end]
        masked, tokens = codes.mask(raw)
        kind = "dialogue" if codes.has_jp(raw) else "punct"
        site = Site(file=script.rel, line=line.number, start=start, end=end,
                    form="bare", raw=raw, label=label)
        scene = f"{script.rel}#{label}"
        self._add(kind, masked, tokens, site, bucket, scene=scene)

        # A translatable attribute can hide inside an inline tag ("[ruby text=..]"),
        # which this span already covers. Give it its own unit and record where it
        # sits inside the parent's token so injection can splice it back in.
        for token_index, token in enumerate(tokens):
            for tag in kslex.scan_tags(token):
                for attr in tag.attrs:
                    action, detail = sites.classify_attr(tag.name, attr.name)
                    if not codes.has_jp(attr.value):
                        continue
                    if action != "text" or sites.looks_like_asset(attr.value):
                        self._drop(script.rel, line.number, f"inline-{action}",
                                   tag.name, attr.name, attr.value)
                        continue
                    child_masked, child_tokens = codes.mask(attr.value)
                    child_start = attr.start - len(attr.quote)
                    child_end = attr.end + len(attr.quote)
                    child_site = Site(
                        file=script.rel, line=line.number,
                        start=-1, end=-1,
                        form="nested", raw=token[child_start:child_end],
                        tag=tag.name, param=attr.name, label=label, quote=attr.quote,
                        context=token)
                    self._add(detail, child_masked, child_tokens, child_site, bucket,
                              scene=scene)
                    site.nested.append(
                        [token_index, child_start, child_end,
                         unit_id(detail, child_masked)])

    def _scan_attrs(self, script: kslex.Script, line: kslex.Line, bucket: str,
                    label: str, body_span: tuple[int, int] | None) -> None:
        for tag in line.tags:
            if body_span is not None and body_span[0] <= tag.start < body_span[1]:
                continue  # handled by _add_message / reported as inline-tag-attr
            for attr in tag.attrs:
                self._scan_attr(script, line, bucket, label, tag, attr)

    def _scan_attr(self, script: kslex.Script, line: kslex.Line, bucket: str,
                   label: str, tag: kslex.Tag, attr: kslex.Attr) -> None:
        action, detail = sites.classify_attr(tag.name, attr.name)
        value = attr.value

        if action == "text" and value.startswith("&"):
            action = "code"  # "&'同棲' + f.day + '日目'" is an expression, not text

        if action == "code":
            self._scan_js_span(script.rel, line, bucket, value, attr.start,
                               tag.name, attr.name, "code")
            return

        if not codes.has_jp(value):
            return

        if action == "skip":
            self._drop(script.rel, line.number, "non-text-param", tag.name, attr.name, value)
            return
        if action == "unknown":
            self._drop(script.rel, line.number, "unknown-site", tag.name, attr.name, value)
            return
        if sites.looks_like_asset(value):
            self._drop(script.rel, line.number, "asset-path", tag.name, attr.name, value)
            return

        masked, tokens = codes.mask(value)
        span_start = attr.start - len(attr.quote)
        span_end = attr.end + len(attr.quote)
        site = Site(file=script.rel, line=line.number, start=span_start, end=span_end,
                    form="attr", raw=line.text[span_start:span_end],
                    tag=tag.name, param=attr.name, label=label, quote=attr.quote,
                    context=line.text[tag.start:tag.end])
        self._add(detail, masked, tokens, site, bucket, scene=f"{script.rel}#{label}")

    # ----------------------------------------------------------- JS literals

    def _scan_js_region(self, rel: str, line: kslex.Line, bucket: str, kind: str) -> None:
        self._scan_js_span(rel, line, bucket, line.text, 0, "iscript", "", kind)

    def _scan_js_span(self, rel: str, line: kslex.Line, bucket: str, source: str,
                      base: int, tag: str, param: str, kind: str) -> None:
        if not codes.has_jp(source):
            return
        found = 0
        for literal in jsstr.scan(source, offset=base):
            if not codes.has_jp(literal.value):
                continue
            if sites.looks_like_asset(literal.value):
                self._drop(rel, line.number, "asset-path", tag, param, literal.value)
                continue
            masked, tokens = codes.mask(literal.value)
            span_start, span_end = literal.start - 1, literal.end + 1
            site = Site(file=rel, line=line.number, start=span_start, end=span_end,
                        form="jsstr", raw=source[span_start - base:span_end - base],
                        tag=tag, param=param, quote=literal.quote, context=source.strip())
            found += 1
            self._add(kind, masked, tokens, site, bucket)
        if not found:
            # e.g. "f.orgasm_in_a中に_count==2" - a variable name, not text.
            self._drop(rel, line.number, "code-identifier", tag, param, source.strip())

    def plugin_files(self, scripts: list[kslex.Script]) -> tuple[list[str], list[str]]:
        """``(js_to_scan, ks_to_scan)`` for the plugins the game actually loads.

        Plugin folders that ship but are never referenced are reported once each
        in ``excluded.jsonl`` rather than translated - patching them would put
        English into code the engine never runs.
        """
        names, extra_scripts = kslex.loaded_plugins(scripts)
        root = self.app_root / sites.PLUGIN_ROOT
        js: list[str] = []
        ks: list[str] = []
        if not root.exists():
            return js, ks

        for name in sorted(names):
            folder = root / name
            if not folder.exists():
                self._drop(f"{sites.PLUGIN_ROOT}/{name}", 0, "plugin-missing", "plugin", name, name)
                continue
            for path in sorted(folder.rglob("*")):
                if path.name.lower().startswith(("readme", "_readme", "_sample")):
                    continue
                rel = path.relative_to(self.app_root).as_posix()
                if path.suffix.lower() == ".js":
                    js.append(rel)
                elif path.suffix.lower() == ".ks":
                    ks.append(rel)
        for rel in sorted(extra_scripts):
            if rel.endswith(".js") and (self.app_root / rel).exists() and rel not in js:
                js.append(rel)

        loaded_folders = set(names)
        for rel in extra_scripts:
            parts = rel.split("/")
            if rel.startswith(sites.PLUGIN_ROOT + "/") and len(parts) > 3:
                loaded_folders.add(parts[3])

        for folder in sorted(p for p in root.iterdir() if p.is_dir()):
            if folder.name in loaded_folders:
                continue
            has_jp = False
            for path in folder.rglob("*"):
                if path.suffix.lower() in (".js", ".ks", ".html", ".csv") and path.is_file():
                    if codes.has_jp(path.read_text(encoding="utf-8", errors="replace")):
                        has_jp = True
                        break
            if has_jp:
                self._drop(f"{sites.PLUGIN_ROOT}/{folder.name}", 0, "plugin-not-loaded",
                           "plugin", folder.name,
                           "folder is never [plugin]-loaded; its Japanese never reaches the screen")
        return js, ks

    def scan_engine_js(self, extra: list[str] | None = None) -> None:
        for rel in list(sites.ENGINE_JS) + list(extra or []):
            path = self.app_root / rel
            if not path.exists():
                continue
            script = kslex.read(path, rel)
            for line in script.lines:
                if not codes.has_jp(line.text):
                    continue
                for literal in jsstr.scan(line.text):
                    if not codes.has_jp(literal.value):
                        continue
                    if literal.value in sites.JS_DENY or sites.looks_like_asset(literal.value):
                        self._drop(rel, line.number, "engine-deny", "", "", literal.value)
                        continue
                    masked, tokens = codes.mask(literal.value)
                    span_start, span_end = literal.start - 1, literal.end + 1
                    site = Site(file=rel, line=line.number, start=span_start, end=span_end,
                                form="jsstr", raw=line.text[span_start:span_end],
                                tag="js", param="", quote=literal.quote,
                                context=line.text.strip()[:200])
                    self._add("js", masked, tokens, site, sites.bucket_for(rel))

    # ---------------------------------------------------------------- output

    def lock_key_collisions(self) -> int:
        """Freeze any unit whose source doubles as an engine key.

        ``[glink target='何も言わない']`` jumps to the label ``*何も言わない``.
        A ``code`` literal that happens to equal a label or a jump target would
        break control flow the moment it became English, so it is marked
        ``manual`` and never sent to the model.
        """
        locked = 0
        for unit in self.units.values():
            if unit.kind not in ("code", "js"):
                continue
            plain = codes.restore(unit.src, unit.sites[0].tokens)
            if plain.strip() and plain.strip() in self.keys:
                unit.status = "manual"
                unit.en = plain
                unit.note = "engine key (label or jump target) - left in Japanese"
                locked += 1
        return locked

    def build_store(self, store_root: Path) -> Store:
        store = Store(store_root)
        for uid, unit in self.units.items():
            unit.sites.sort(key=lambda s: (s.file, s.line, s.start))
            store.buckets.setdefault(self.bucket_of[uid], []).append(unit)
        for units in store.buckets.values():
            units.sort(key=lambda u: u.sites[0].order)
        return store


def run(app_root: Path, store_root: Path, reports: Path) -> tuple[Store, Extractor]:
    ex = Extractor(app_root)
    scripts = kslex.iter_scripts(app_root)
    plugin_js, plugin_ks = ex.plugin_files(scripts)
    if plugin_ks:
        scripts = kslex.iter_scripts(app_root, extra=plugin_ks)
    ex.collect_keys(scripts)
    ex.scan_scripts(scripts)
    ex.scan_engine_js(extra=plugin_js)
    ex.lock_key_collisions()
    store = ex.build_store(store_root)

    reports.mkdir(parents=True, exist_ok=True)
    with (reports / "excluded.jsonl").open("w", encoding="utf-8") as fh:
        for row in ex.excluded:
            fh.write(json.dumps(row.to_json(), ensure_ascii=False) + "\n")

    strings = sorted({u.src for u in store.all_units()})
    (reports / "jp_all_strings.txt").write_text("\n".join(strings) + "\n", encoding="utf-8")

    return store, ex
