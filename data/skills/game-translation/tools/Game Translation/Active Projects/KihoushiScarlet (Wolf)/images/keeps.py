"""Proposed decoration keep-lists per overlay; render both halves to check."""
import sys, os
sys.path.insert(0, '.')
from PIL import Image
from probe import load
from imgtl import components, comp_sheet

KEEP = {
    'T1': ('tousaturakugaki010101.png', [1, 2, 3, 13, 17]),
    'T2': ('tousaturakugaki010201.png',
           [6, 7, 13, 16, 19, 20, 25, 29, 38, 49, 50, 51, 55, 59, 61]),
    'T3': ('tousaturakugaki010301.png',
           [4, 12, 15, 22, 24, 25, 30, 48, 56, 62, 63, 64, 88, 91, 93, 95,
            97, 99, 114]),
    'Y2': ('yuuwakurakugaki010201.png',
           [15, 23, 65, 71, 72, 74, 79, 80, 84, 85, 91]),
    'Y3': ('yuuwakurakugaki010301.png',
           [82, 91, 97, 100, 112, 124, 143, 148, 151, 158, 162, 163, 164,
            165, 172, 179, 180]),
}

os.makedirs('probe', exist_ok=True)
for tag, (name, keep) in KEEP.items():
    im = load(name)
    lab, recs = components(im)
    allids = [r['id'] for r in recs]
    erase = [i for i in allids if i not in keep]
    comp_sheet(im, lab, keep, 'probe/%s_KEEP.png' % tag)
    comp_sheet(im, lab, erase, 'probe/%s_ERASE.png' % tag)
    print(tag, 'total', len(allids), 'keep', len(keep), 'erase', len(erase))
