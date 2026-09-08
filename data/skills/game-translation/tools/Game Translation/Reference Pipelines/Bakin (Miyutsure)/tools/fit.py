"""Measure Bakin layout text against its declared box, with the game's own font.

    fit.py validate <layout.tsv> <fontDir> [fonts.tsv]
    fit.py check    <layout.tsv> <fontDir> <fonts.tsv> <translated.jsonl> <units.jsonl>

Rendered width in the engine is

    textDrawer.MeasureString(font at Font.Size, s).X * MenuItem.scale.X

and the budget is `MenuItem.size.X`. `Font.DefaultScale` folds in too, so the
effective pixel size is `Font.Size * Font.DefaultScale`. 91% of this game's text
widgets take the default Layout font, which is `res/font/font.ttf` at 72 * 0.3333.

`validate` is the gate: measure the SHIPPED Japanese against its own box. The
author's own layout is ground truth, so a model that says the original overflows
is a broken model, not a broken game - fix the measurement before trusting any
verdict on the translation.
"""

import csv
import io
import json
import os
import sys
from PIL import ImageFont

# Installed-type fonts are referenced by system family name and are not in the
# pack; substitute the default so a width is still produced, and say so.
FALLBACK = 'font.ttf'


class Measurer:
    def __init__(self, font_dir, fonts_tsv=None):
        self.dir = font_dir
        self.cache = {}
        self.fonts = {}
        self.missing = set()
        if fonts_tsv and os.path.exists(fonts_tsv):
            for r in csv.DictReader(io.open(fonts_tsv, encoding='utf-8'), delimiter='\t'):
                px = float(r['size']) * float(r['defaultScale'])
                path = r['path'].replace('\\\\', '\\').lstrip('.\\')
                self.fonts[r['name']] = (path, px)

    def _face(self, path, px):
        key = (path, round(px))
        if key not in self.cache:
            full = os.path.join(self.dir, path.replace('\\', os.sep))
            if not os.path.exists(full):
                self.missing.add(path)
                full = os.path.join(self.dir, 'res', 'font', FALLBACK)
            self.cache[key] = ImageFont.truetype(full, max(1, int(round(px))))
        return self.cache[key]

    def width(self, text, font_name, scale):
        """Width of the WIDEST line: a literal can carry its own hard breaks, and
        measuring the whole string as one line accuses the author of overflowing
        boxes that are laid out fine."""
        path, px = self.fonts.get(font_name or '', ('res\\font\\font.ttf', 24.0))
        if not path.lower().endswith(('.ttf', '.otf')):
            self.missing.add(path)
            path = 'res\\font\\' + FALLBACK
        face = self._face(path, px)
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        return max(face.getlength(ln) for ln in lines) * scale

    def lines(self, text):
        return len(text.replace('\r\n', '\n').replace('\r', '\n').split('\n'))


def load_layout(path):
    return [r for r in csv.DictReader(io.open(path, encoding='utf-8'), delimiter='\t')]


def unesc(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s):
            out.append({'n': '\n', 'r': '\r', 't': '\t'}.get(s[i + 1], s[i + 1]))
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def literal_rows(layout):
    """Widgets holding real text, not a content-getter code."""
    for r in layout:
        t = unesc(r['text'])
        if t and '\\' not in t and float(r['sizeX']) > 0:
            yield r, t


def regime(r):
    if r['wordWrap'] == '1':
        return 'wrapping'          # width is not a constraint: the engine breaks lines
    return 'clipping' if r['clipping'] == '1' else 'overflow'


def validate(layout_path, font_dir, fonts_tsv=None):
    m = Measurer(font_dir, fonts_tsv)
    rows = load_layout(layout_path)
    buckets = {'wrapping': [0, 0, []], 'clipping': [0, 0, []], 'overflow': [0, 0, []]}
    for r, t in literal_rows(rows):
        w = m.width(t, r['font'], float(r['scaleX']))
        box = float(r['sizeX'])
        b = buckets[regime(r)]
        if w <= box:
            b[0] += 1
        else:
            b[1] += 1
            b[2].append((w / box, w, box, r['node'], t))

    print('shipped Japanese measured against its own box, by regime:')
    print('%-10s %7s %7s   %s' % ('regime', 'fits', 'over', 'meaning of "over"'))
    note = {'wrapping': 'expected - the engine wraps to size.X',
            'clipping': 'the author shipped it clipped, or the model is wrong',
            'overflow': 'drawn past the box, may be deliberate'}
    for k in ('wrapping', 'clipping', 'overflow'):
        f, o, _ = buckets[k]
        print('%-10s %7d %7d   %s' % (k, f, o, note[k]))
    if m.missing:
        print('note: %d font(s) not in the pack, measured with %s: %s'
              % (len(m.missing), FALLBACK, ', '.join(sorted(m.missing))[:110]))

    # Only the clipping bucket can lose text, so that is the one whose residue
    # has to be explained before the model is trusted on a translation.
    hard = sorted(buckets['clipping'][2], reverse=True)
    print('\nworst CLIPPING overruns in the shipped Japanese:')
    for ratio, w, box, node, t in hard[:12]:
        print('  %5.2fx %6.0f / %-5.0f px  %-24s %s' % (ratio, w, box, node[:24], t[:34]))
    return 0


def check(layout_path, font_dir, fonts_tsv, tl_path, units_path):
    m = Measurer(font_dir, fonts_tsv)
    rows = load_layout(layout_path)
    tl = {}
    for line in io.open(tl_path, encoding='utf-8'):
        r = json.loads(line)
        tl[r['key']] = r['en']
    src = {}
    for line in io.open(units_path, encoding='utf-8'):
        u = json.loads(line)
        src[u['key']] = u

    # layout.tsv rows are emitted in the same (node, index) order the exporter
    # keys M: units by, so they join directly.
    by_key = {}
    for r in rows:
        by_key['M:' + r['nodeGuid'] + ':' + r['idx'] + ':text'] = r
    hard = soft = ok = already = 0
    report = []
    for key, en in tl.items():
        if not key.startswith('M:'):
            continue
        r = by_key.get(key)
        if r is None or float(r['sizeX']) <= 0:
            continue
        if r['wordWrap'] == '1':
            continue                      # engine wraps and paginates: soft
        scale = float(r['scaleX'])
        w = m.width(en, r['font'], scale)
        box = float(r['sizeX'])
        if w <= box:
            ok += 1
            continue
        # Differential, not absolute: the author's own layout is ground truth, and
        # a slot whose Japanese ALREADY overran its box is not something the patch
        # broke. Flag only where English is wider than the text it replaced.
        jp = src.get(key, {}).get('src', '')
        jw = m.width(jp, r['font'], scale) if jp else 0.0
        if jw > box:
            already += 1
            continue
        if r['clipping'] == '1':
            hard += 1
            report.append(('CLIPPED', w / box, r['node'], en, jp))
        else:
            soft += 1
            report.append(('OVERFLOW', w / box, r['node'], en, jp))
    print('single-line UI labels: fits %d, CLIPPED %d (text lost), OVERFLOW %d (collides)'
          % (ok, hard, soft))
    print('  (%d slots were already over the box in Japanese - not counted)' % already)
    report.sort(key=lambda x: -x[1])
    for kind, ratio, node, en, jp in report[:25]:
        print('  %-8s %5.2fx %-18s %-30s <- %s' % (kind, ratio, node[:18], en[:30], jp[:22]))
    return 0


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'validate':
        sys.exit(validate(*sys.argv[2:5]))
    if cmd == 'check':
        sys.exit(check(*sys.argv[2:7]))
    print(__doc__)
    sys.exit(2)
