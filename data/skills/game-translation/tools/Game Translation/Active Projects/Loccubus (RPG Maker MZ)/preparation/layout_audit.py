"""Source-only font-advance inventory for the reviewed MUUI widgets."""
from fontTools.ttLib import TTFont

import tl
from vendor.core import read_json, write_json


def main():
    tl.verify_source()
    font = TTFont(tl.SOURCE / 'fonts/yuyang-W03.ttf')
    cmap = font.getBestCmap()
    widths = font['hmtx'].metrics
    units = font['head'].unitsPerEm
    rows = []
    for site in read_json(tl.BASE / 'sites.json'):
        if 'layout' not in site:
            continue
        layout = site['layout']
        size = layout['style']['fontSize']
        missing = sorted({c for c in site['source'] if not c.isspace() and ord(c) not in cmap})
        width = max(sum(widths[cmap[ord(c)]][0] for c in line if ord(c) in cmap) / units * size
                    for line in site['source'].splitlines())
        rows.append({'file': site['file'], 'path': site['path'], 'source': site['source'],
                     'font_size': size, 'advance_width': round(width, 2),
                     'declared_width': layout['transform']['width'],
                     'over_declared_width': width > layout['transform']['width'],
                     'missing_glyphs': missing})
    report = {'font': 'fonts/yuyang-W03.ttf', 'source_widgets': rows,
              'ascii_missing_glyphs': [chr(c) for c in range(32, 127) if c not in cmap],
              'source_over_declared_width': sum(r['over_declared_width'] for r in rows),
              'status': 'Static source advances only; no English or native visual fit signoff',
              'limits': 'No browser kerning, outline ink, painted plate bounds, dynamic values or screenshots measured'}
    write_json(tl.BASE / 'reports/layout_source.json', report)
    font.close()
    print('Source UI widgets:', len(rows), 'static width flags:', report['source_over_declared_width'])


if __name__ == '__main__':
    main()
