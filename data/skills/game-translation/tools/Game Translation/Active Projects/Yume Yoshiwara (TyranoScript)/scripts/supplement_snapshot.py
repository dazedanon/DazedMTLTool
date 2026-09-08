"""Add archive-wide text and fonts missed by the reference prefix filter."""
from pathlib import Path
from unpack_app import read_header,iter_entries,safe_join,TEXT_SUFFIXES
import project as p

archive=p.ROOT.parent/'resources/app.asar'
header,offset=read_header(archive)
written=[]
with archive.open('rb') as fh:
    for rel,entry in iter_entries(header):
        if rel.startswith('node_modules/') or not rel.lower().endswith(TEXT_SUFFIXES+('.otf','.ttf')):continue
        out=safe_join(p.SOURCE,rel)
        if out.exists():continue
        fh.seek(offset+int(entry['offset']));data=fh.read(entry['size'])
        if len(data)!=entry['size']:raise ValueError('archive truncated')
        out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data);written.append(rel)
print('Added:',written)
