"""Yume Yoshiwara 1.041ex adapter. Reuses AjinSyoujyo's span lexer.

Original game files and Japanese state values are never modified by extraction.
All offsets refer to an immutable UTF-8 snapshot; the store owns translations.
"""
from __future__ import annotations

import bisect
import collections
import hashlib
import html
import json
import re
from pathlib import Path

from tyranotl import codes, extract, jsstr, kslex, sites
from tyranotl.store import Site, Unit, unit_id

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'source'
REPORTS = ROOT / 'reports'
FORMAT_RE = re.compile(r'\$\{[^{}\r\n]*\}|\{\s*[A-Za-z_]\w*\s*\}|%(?:\d+\$)?[sdif]|[\r\n\t]|\\[nrt]')
codes.MASK_RE = re.compile(f'{FORMAT_RE.pattern}|{codes.TAG_RE.pattern}|{codes.HTML_RE.pattern}')
sites.EXPLICIT.update({('dialog', 'text'): 'notice', ('pushlog', 'text'): 'notice',
                       ('chara_new', 'jname'): 'name', ('chara_ptext', 'name'): 'name',
                       ('chara_mod', 'jname'): 'name', ('edit', 'placeholder'): 'edit'})
for tag in [*(f'char_sample{i}_clone' for i in range(9)),
            *(f'char_sample{i}_m' for i in range(9)), *(f'home_char{i}' for i in range(6))]:
    sites.EXPLICIT[(tag, 'jname')] = 'name'


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return hashlib.sha256(value).hexdigest()


def strict_json(text):
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError(f'duplicate JSON key: {k}')
            result[k] = v
        return result
    return json.loads(text, object_pairs_hook=pairs)


def read_json(path):
    return strict_json(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def safe_path(root, rel):
    root = Path(root).resolve()
    p = (root / rel).resolve()
    if root not in p.parents:
        raise ValueError(f'unsafe path: {rel}')
    return p


def file_identity():
    return {p.relative_to(SOURCE).as_posix(): digest(p.read_bytes())
            for p in sorted(SOURCE.rglob('*')) if p.is_file()}


class GameExtractor(extract.Extractor):
    def __init__(self, root):
        super().__init__(root)
        self.speaker = ''
        self.registered = set()
        self.aliases = {}
        # main/1_1.ks creates these from char_all_list's first six records.
        self.aliases.update(dict(zip([f'char{i}' for i in range(6)],
                                    ['お鈴','甜瓜','姫乃','凛風','ハク','初音'])))
        self.state_values = set()
        self.display_units = {}
        self.dynamic_sites = []
        self.blockers = []
        self.files = {}

    def _add(self, kind, masked, tokens, site, bucket, scene='', speaker=''):
        if kind in ('dialogue', 'punct'):
            # Preserve repeated dialogue's scene and speaker, unlike the reference.
            uid = unit_id(kind, f'{site.file}:{site.line}:{site.start}:{masked}')
        else:
            uid = unit_id(kind, masked)
        site.tokens = tokens
        if uid not in self.units:
            self.units[uid] = Unit(id=uid, kind=kind, src=masked, scene=scene,
                                  speaker=speaker or (self.speaker if kind in ('dialogue', 'punct') else ''))
            self.bucket_of[uid] = bucket
        self.order += 1
        site.order = self.order
        self.units[uid].sites.append(site)

    def collect_keys(self, scripts):
        super().collect_keys(scripts)
        for script in scripts:
            for line in script.lines:
                if line.kind == 'comment':
                    continue
                for tag in line.tags:
                    attrs = {a.name: a.value for a in tag.attrs}
                    if tag.name == 'chara_new' or (('clone' in tag.name or tag.name.startswith('home_char')) and 'jname' in attrs):
                        name = attrs.get('name', '')
                        if name and not name.startswith(('%', '&')):
                            self.registered.add(name)
                            jname = attrs.get('jname', '')
                            if jname and not jname.startswith(('%', '&')):
                                self.aliases[name] = jname
                    for attr in tag.attrs:
                        if attr.name == 'exp' and tag.name in ('if', 'elsif') or attr.name == 'cond':
                            for literal in jsstr.scan(attr.value):
                                if codes.has_jp(literal.value):
                                    self.state_values.add(literal.value)
                # Also catch comparisons inside iscript, not only KAG attributes.
                if re.search(r'===?|!==?', line.text):
                    for literal in jsstr.scan(line.text):
                        before = line.text[max(0, literal.start - 6):literal.start - 1]
                        after = line.text[literal.end + 1:literal.end + 7]
                        if codes.has_jp(literal.value) and re.search(r'==|!=', before + after):
                            self.state_values.add(literal.value)

    def _drop(self, rel, line, reason, tag, param, text):
        super()._drop(rel, line, reason, tag, param, text)
        if reason in ('unknown-site', 'unparsed-line', 'inline-unknown', 'unsupported-template'):
            # Source author typo is documented and preserved byte for byte.
            if rel == 'data/scenario/status_char1.ks' and line == 156 and reason == 'unparsed-line':
                return
            self.blockers.append({'file': rel, 'line': line, 'reason': reason, 'tag': tag, 'param': param})

    def _scan_attr(self, script, line, bucket, label, tag, attr):
        if tag.name == 'night2_layer_change' and attr.name == 'char':
            self._drop(script.rel, line.number, 'character-selector', tag.name, attr.name, attr.value)
            return
        if attr.name in ('text', 'jname', 'name') and attr.value.startswith('&'):
            if attr.name != 'name' or tag.name == 'chara_ptext':
                self.dynamic_sites.append({'file': script.rel, 'line': line.number,
                                           'tag': tag.name, 'param': attr.name, 'expression': attr.value})
        if tag.name == 'chara_ptext' and attr.name == 'name' and attr.value in self.registered:
            self._drop(script.rel, line.number, 'registered-character-id', tag.name, attr.name, attr.value)
            return
        super()._scan_attr(script, line, bucket, label, tag, attr)

    def _scan_js_span(self, rel, line, bucket, source, base, tag, param, kind):
        for lit in jsstr.scan(source):
            if not codes.has_jp(lit.value):
                continue
            if lit.quote == '`' and '${' in FORMAT_RE.sub('', lit.raw):
                self._drop(rel, line.number, 'unsupported-template', tag, param, lit.raw)
                continue
            before = source[:lit.start - 1].rstrip()
            after = source[lit.end + 1:].lstrip()
            if sites.looks_like_asset(lit.value) or re.search(r'(?:font|face|selector)\s*[:=]\s*$', before, re.I):
                self._drop(rel, line.number, 'asset-or-font', tag, param, lit.value)
                continue
            if after.startswith(':') or (before.endswith('[') and after.startswith(']')):
                self._drop(rel, line.number, 'object-key', tag, param, lit.value)
                continue
            if lit.value in self.state_values or lit.value in self.keys:
                self._drop(rel, line.number, 'state-value-preserved', tag, param, lit.value)
                # Translate a display copy, never the state/condition/assignment itself.
                uid = unit_id('display_value', lit.value)
                if uid not in self.units:
                    self._add('display_value', lit.value, [], Site(file=rel, line=line.number,
                              start=-1, end=-1, form='display', raw=lit.value,
                              context=source[:400], tag=tag, param=param), 'Dynamic')
                return_value = self.units[uid]
                self.display_units[lit.value] = return_value.id
                continue
            masked, tokens = codes.mask(lit.value)
            start, end = base + lit.start - 1, base + lit.end + 1
            site = Site(file=rel, line=line.number, start=start, end=end, form='jsstr',
                        raw=source[lit.start - 1:lit.end + 1], quote=lit.quote,
                        tag=tag, param=param, context=source[:600])
            self._add(kind, masked, tokens, site, bucket)

    def scan_scripts(self, scripts):
        for script in scripts:
            self.files[script.rel] = 'scenario-or-referenced-plugin'
            self.speaker = ''
            bucket = sites.bucket_for(script.rel)
            blocks = kslex.iscript_ranges(script)
            script_lines = set()
            for start, end in blocks:
                script_lines.update(range(start, end))
                # Mask comments once per block; preserve cross-line comment state.
                region = ''.join(x.text + x.sep for x in script.lines[start:end])
                cleaned = jsstr._blank_comments(region).splitlines()
                for offset, number in enumerate(range(start, end)):
                    original = script.lines[number]
                    clean = cleaned[offset] if offset < len(cleaned) else ''
                    self._scan_js_span(script.rel, original, bucket, clean, 0, 'iscript', '', 'code')
            block_comment = False
            label = '(top)'
            for index, line in enumerate(script.lines):
                if index in script_lines:
                    continue
                stripped = line.text.strip()
                if stripped == '/*':
                    block_comment = True
                if block_comment or line.kind in ('blank', 'comment'):
                    if codes.has_jp(line.text):
                        self._drop(script.rel, line.number, 'author-comment', '', '', stripped)
                    if stripped == '*/':
                        block_comment = False
                    continue
                if line.kind == 'label':
                    label = stripped[1:].split('|')[0]
                    if codes.has_jp(line.text):
                        self._drop(script.rel, line.number, 'label-identifier', '', '', stripped)
                    continue
                if stripped.startswith('#'):
                    name = stripped[1:].split(':')[0]
                    self.speaker = self.aliases.get(name, name)
                    if name in self.registered or name.startswith('&'):
                        self._drop(script.rel, line.number, 'registered-or-dynamic-speaker', '', '', name)
                    elif name and (codes.has_jp(name) or name == '？？？'):
                        start = line.text.index('#') + 1
                        masked, tokens = codes.mask(name)
                        self._add('name', masked, tokens, Site(file=script.rel, line=line.number,
                                  start=start, end=start+len(name), raw=name, form='name'), bucket)
                    continue
                # Preserve '_' literal-space marker outside the translatable span.
                span = self._message_span(line) if line.kind in ('text', 'tag') else None
                if span and line.text[span[0]:].lstrip().startswith('_'):
                    start = line.text.index('_', span[0]) + 1
                    span = (start, span[1])
                before = self.order, len(self.excluded)
                self._scan_attrs(script, line, bucket, label, span)
                if span:
                    self._add_message(script, line, bucket, label, span)
                if (self.order, len(self.excluded)) == before and codes.has_jp(line.text):
                    # Pure technical tags need no literal extraction.
                    reason = 'technical-tag' if line.tags else 'unparsed-line'
                    self._drop(script.rel, line.number, reason, '', '', stripped)

    def scan_js_file(self, rel):
        path = self.app_root / rel
        parsed = kslex.read(path, rel)
        raw = parsed.render()
        clean = jsstr._blank_comments(raw)
        self.files[rel] = 'runtime-js'
        for original, masked_line in zip(kslex.read(path, rel).lines, kslex.LINE_SPLIT_RE.split(clean)[::2]):
            # title.ks enables only part-set runtime, with both editor UIs disabled.
            if rel.endswith('/chara_part_manager/chara_part_manager.js') and original.number >= 54:
                continue
            if rel.endswith('/tempura_camera2/tempura_camera.js') and original.number >= 409:
                continue
            self._scan_js_span(rel, original, 'Engine' if rel.startswith('tyrano/') else 'Plugins',
                               masked_line, 0, 'js', '', 'js')

    def scan_html_file(self, rel):
        script = kslex.read(self.app_root / rel, rel)
        self.files[rel] = 'html-template'
        raw = script.render()
        # Preserve comments and script/style contents, including multiline state.
        skip = [(m.start(), m.end()) for m in re.finditer(
            r'<!--[\s\S]*?-->|<(?:script|style)\b[^>]*>[\s\S]*?</(?:script|style)>', raw, re.I)]
        starts = [0]
        for l in script.lines[:-1]:
            starts.append(starts[-1] + len(l.text) + len(l.sep))
        for m in re.finditer(r'(?<=>)[^<>]+(?=<)', raw):
            if not codes.has_jp(m.group()) or any(a <= m.start() < b for a,b in skip):
                continue
            a = m.start() + len(m.group()) - len(m.group().lstrip())
            b = m.end() - len(m.group()) + len(m.group().rstrip())
            if a >= b or '\n' in raw[a:b]:
                continue
            index = bisect.bisect_right(starts,a)-1
            text = raw[a:b]
            masked,tokens = codes.mask(html.unescape(text))
            self._add('ui',masked,tokens,Site(file=rel,line=index+1,start=a-starts[index],
                      end=b-starts[index],raw=text,form='html'), 'Engine')


def extraction():
    ex = GameExtractor(SOURCE)
    scripts = kslex.iter_scripts(SOURCE)
    # Conservative scenario census includes all shipped scenarios, even route variants.
    names, extra = kslex.loaded_plugins(scripts)
    plugin_scripts = []
    plugin_js = []
    for name in sorted(names):
        folder = SOURCE / sites.PLUGIN_ROOT / name
        for p in sorted(folder.rglob('*')):
            rel = p.relative_to(SOURCE).as_posix()
            if p.name == '_SAMPLE.ks':
                # Both are demonstration scenarios; no shipped loader references them.
                ex._drop(rel, 0, 'unreferenced-plugin-example', '', '', p.name)
            elif p.suffix == '.ks':
                plugin_scripts.append(kslex.read(p, rel))
            elif p.suffix == '.js' and not p.name.endswith('.builder.js'):
                plugin_js.append(rel)
    scripts += plugin_scripts
    ex.collect_keys(scripts)
    ex.scan_scripts(scripts)
    # Include every direct engine script except vendor libraries and editor-only data.
    js_files = set(sites.ENGINE_JS) | set(plugin_js) | {'tyrano/tyrano.js', 'tyrano/tyrano.base.js', 'data/system/KeyConfig.js', 'main.js', 'data/others/other_check.js'}
    for p in (SOURCE / 'tyrano/plugins/kag').glob('*.js'):
        js_files.add(p.relative_to(SOURCE).as_posix())
    for rel in sorted(js_files):
        if (SOURCE / rel).exists():
            ex.scan_js_file(rel)
    for path in sorted(SOURCE.rglob('*.html')):
        ex.scan_html_file(path.relative_to(SOURCE).as_posix())
    units = sorted(ex.units.values(), key=lambda u: u.sites[0].order)
    # Verify every address and reject overlapping edits before producing a catalog.
    by_line = collections.defaultdict(list)
    parsed = {}
    for unit in units:
        for site in unit.sites:
            if site.start < 0:
                continue
            script = parsed.setdefault(site.file, None)
            if script is None:
                script = parsed[site.file] = kslex.read(SOURCE / site.file, site.file)
            actual = script.lines[site.line - 1].text[site.start:site.end]
            if actual != site.raw:
                raise ValueError(f'source span mismatch: {site.file}:{site.line}')
            by_line[(site.file, site.line)].append((site.start, site.end, unit.id))
    for key, spans in by_line.items():
        spans.sort()
        for a, b in zip(spans, spans[1:]):
            if a[1] > b[0]:
                raise ValueError(f'overlapping spans: {key}: {a}, {b}')
    identity = file_identity()
    old_path = ROOT / 'catalog.json'
    if old_path.exists():
        old = read_json(old_path)
        if any(identity.get(k)!=v for k,v in old['source_files'].items()):
            raise ValueError('Source changed. Use a new project revision; refusing to replace the catalog.')
    catalog = {'schema': 1, 'source_fingerprint': digest(identity), 'source_files': identity,
               'units': [u.to_json() for u in units]}
    write_json(old_path, catalog)
    REPORTS.mkdir(exist_ok=True)
    (REPORTS / 'excluded.jsonl').write_text(''.join(json.dumps(e.to_json(), ensure_ascii=False)+'\n'
                                               for e in ex.excluded), encoding='utf-8')
    write_json(REPORTS / 'dynamic_display_sites.json', ex.dynamic_sites)
    write_json(REPORTS / 'state_values.json', sorted(ex.state_values))
    write_json(REPORTS / 'blockers.json', ex.blockers)
    write_json(REPORTS / 'speaker_aliases.json', ex.aliases)
    file_census = []
    for rel in identity:
        if rel in ex.files:
            reason = ex.files[rel]
        elif '.builder.js' in rel or rel.endswith('/_SAMPLE.ks'):
            reason = 'editor-metadata'
        elif '/libs/' in rel or '/spine/assets/' in rel:
            reason = 'vendor-or-animation-runtime'
        elif rel.endswith(('.tjs', '.json')):
            reason = 'configuration-and-package-identity-preserved'
        elif rel.endswith('.js') and ('/waapi/' in rel or '/button_ex/' in rel):
            reason = 'plugin-not-loaded'
        else:
            reason = 'style-or-non-runtime-text'
        file_census.append({'file': rel, 'classification': reason})
    write_json(REPORTS / 'file_census.json', file_census)
    count = collections.Counter(u.kind for u in units)
    report = {'units': len(units), 'occurrences': sum(len(u.sites) for u in units),
              'source_characters': sum(len(u.src) for u in units), 'kinds': dict(count),
              'scenario_files': len(scripts), 'plugins': sorted(names),
              'blockers': len(ex.blockers), 'dynamic_display_sites': len(ex.dynamic_sites),
              'source_fingerprint': catalog['source_fingerprint'],
              'dialogue_dedup': False, 'ui_dedup': True,
              'distinct_speaker_dialogue_pairs': len({(u.speaker,u.src) for u in units if u.kind=='dialogue'}),
              'exclusions': dict(collections.Counter(e.reason for e in ex.excluded))}
    write_json(REPORTS / 'extraction.json', report)
    return report


def load_catalog(verify=True):
    raw = read_json(ROOT / 'catalog.json')
    if verify and digest(file_identity()) != raw['source_fingerprint']:
        raise ValueError('source snapshot changed since extraction')
    return raw, [Unit.from_json(u) for u in raw['units']]


def validate_text(unit, value):
    issues = []
    if not isinstance(value, str) or not value.strip():
        return ['empty-or-non-string']
    if codes.SENTINEL_RE.findall(unit.src) != codes.SENTINEL_RE.findall(value):
        issues.append('placeholder-sequence')
    if codes.stray_sentinel(value):
        issues.append('malformed-placeholder')
    if codes.has_jp(value):
        issues.append('residual-japanese')
    if any(c in value for c in '\r\n\x00'):
        issues.append('physical-line-or-null')
    if re.search(r'[\[\]<>]|\$\{', codes.SENTINEL_RE.sub('', value)):
        issues.append('unmasked-markup')
    if unit.kind in ('dialogue', 'punct') and value.lstrip()[:1] in codes.LINE_SPECIAL:
        issues.append('scenario-command-prefix')
    for site in unit.sites:
        if site.form in ('attr', 'nested'):
            if '"' in value and "'" in value:
                issues.append('unrepresentable-attribute-quotes')
        elif site.form == 'jsstr' and site.tag not in ('iscript', 'js'):
            # The outer KAG lexer does not understand JS escaped delimiters.
            rawline = (SOURCE/site.file).read_bytes().decode('utf-8').splitlines()[site.line-1]
            for tag in kslex.scan_tags(rawline):
                for attr in tag.attrs:
                    if attr.start <= site.start and site.end <= attr.end and attr.quote in value:
                        issues.append('outer-kag-quote-collision')
    return sorted(set(issues))


def render_site(unit, site, value):
    if site.form == 'display':
        return site.raw
    restored = codes.restore(value, site.tokens)
    if site.form == 'html':
        return html.escape(restored, quote=False)
    if site.form == 'jsstr':
        if site.tag not in ('iscript', 'js'):
            restored = codes.protect_spaces(restored)
        return site.quote + jsstr.encode(restored, site.quote) + site.quote
    if site.form in ('attr', 'nested'):
        restored = codes.protect_spaces(restored)
        quote = '"' if '"' not in restored else "'"
        if quote in restored:
            raise ValueError('cannot encode KAG attribute without changing punctuation')
        return quote + restored + quote
    return restored


def build_tree(output, translations=None, identity=False):
    catalog, units = load_catalog()
    translations = translations or {}
    grouped = collections.defaultdict(list)
    byid = {u.id: u for u in units}
    for u in units:
        if not identity and u.id in translations:
            issues = validate_text(u, translations[u.id])
            if issues:
                raise ValueError(f'{u.id}: {issues}')
        for s in u.sites:
            if s.start >= 0:
                grouped[s.file].append((u, s))
    output = Path(output).resolve()
    if output == SOURCE.resolve() or SOURCE.resolve() in output.parents:
        raise ValueError('cannot write into source snapshot')
    count = 0
    for rel, entries in grouped.items():
        script = kslex.read(SOURCE/rel, rel)
        per_line = collections.defaultdict(list)
        for u, s in entries:
            value = s.raw if identity or u.id not in translations else render_site(u, s, translations[u.id])
            # Inline attribute units splice into the occurrence's own token map.
            if not identity and u.id in translations and s.nested:
                tokens = list(s.tokens)
                edits = collections.defaultdict(list)
                for token_index, start, end, child in s.nested:
                    if child in translations:
                        cu = byid[child]
                        cs = next(x for x in cu.sites if x.file==s.file and x.line==s.line)
                        edits[token_index].append((start,end,render_site(cu,cs,translations[child])))
                for index, changes in edits.items():
                    for start,end,replacement in sorted(changes,reverse=True):
                        tokens[index] = tokens[index][:start]+replacement+tokens[index][end:]
                value = codes.restore(translations[u.id], tokens)
            per_line[s.line-1].append((s.start,s.end,value))
        for line, changes in per_line.items():
            text = script.lines[line].text
            for start,end,value in sorted(changes,reverse=True):
                text = text[:start]+value+text[end:]
            script.lines[line].text = text
        raw = script.render().encode(script.encoding)
        if identity and raw != (SOURCE/rel).read_bytes():
            raise AssertionError(f'identity splice changed bytes: {rel}')
        target = safe_path(output, rel)
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(raw)
        count += 1
    return {'files':count, 'identity_byte_exact':identity, 'output':str(output)}
