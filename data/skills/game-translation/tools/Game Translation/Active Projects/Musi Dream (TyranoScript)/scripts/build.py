"""Reproducibly inject approved English and narrowly scoped compatibility fixes."""
import json
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image
from unpack_app import read_header, iter_entries

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tl

ROOT = tl.ROOT
OUT = ROOT / 'build' / 'payload'
ORIGINAL_SHA256 = '0427999aee3dd5e6e6cc995eca1f6cf7a1a94bdc43222a247bc103a99a12b524'


def checked_images():
    """Read approved replacements and prove they target pristine packed images."""
    manifest_path = ROOT / 'images/manifest.json'
    if not manifest_path.exists():
        return [], None
    manifest = tl.read_json(manifest_path)
    if manifest.get('format_version') != 1:
        raise ValueError('Unsupported image manifest format')
    if manifest.get('original_archive_sha256') != ORIGINAL_SHA256:
        raise ValueError('Image manifest targets a different original archive')
    assets = manifest.get('assets')
    if not isinstance(assets, list):
        raise ValueError('Image manifest assets must be a list')
    archive = Path(tl.read_json(ROOT / 'source/manifest.json')['archive']['path'])
    original = archive.with_name('app.asar.original')
    if not original.exists():
        original = archive
    with original.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != ORIGINAL_SHA256:
            raise ValueError('Image source archive is not the supported Japanese original')
    header, data_offset = read_header(original)
    entries = dict(iter_entries(header))
    source_root = (ROOT / 'images/source').resolve()
    output_root = (ROOT / 'images/output').resolve()
    paths = set()
    checked = []
    with original.open('rb') as f:
        for asset in assets:
            rel = asset['path']
            if (not isinstance(rel, str) or '\\' in rel or ':' in rel
                    or any(p in ('', '.', '..') for p in rel.split('/'))
                    or rel not in entries or rel in paths):
                raise ValueError(f'Unsafe, duplicate or unknown image path: {rel!r}')
            entry = entries[rel]
            if entry.get('unpacked') or 'link' in entry or 'offset' not in entry:
                raise ValueError(f'Image is not an ordinary packed archive entry: {rel}')
            if Path(rel).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'):
                raise ValueError(f'Image replacement targets a non-raster file: {rel}')
            if asset.get('status') != 'rendered' or asset.get('reviewed') is not True:
                raise ValueError(f'Image has not passed rendering and visual review: {rel}')
            source, output = (source_root / rel).resolve(), (output_root / rel).resolve()
            if not source.is_relative_to(source_root) or not output.is_relative_to(output_root):
                raise ValueError(f'Image workspace path escapes its root: {rel}')
            source_bytes, output_bytes = source.read_bytes(), output.read_bytes()
            if tl.digest(source_bytes) != asset['source_sha256']:
                raise ValueError(f'Pristine image snapshot changed: {rel}')
            if tl.digest(output_bytes) != asset['output_sha256']:
                raise ValueError(f'Reviewed image output changed: {rel}')
            if source_bytes == output_bytes:
                raise ValueError(f'Localized image has no changes: {rel}')
            f.seek(data_offset + int(entry['offset']))
            if f.read(int(entry['size'])) != source_bytes:
                raise ValueError(f'Image snapshot differs from original archive: {rel}')
            geometry = (asset['width'], asset['height'])
            for kind, path in (('source', source), ('output', output)):
                with Image.open(path) as im:
                    im.load()
                    if im.size != geometry or im.mode != asset['mode']:
                        raise ValueError(f'Image {kind} dimensions/mode changed: {rel}')
                    if getattr(im, 'n_frames', 1) != 1:
                        raise ValueError(f'Animated image needs a frame-preservation adapter: {rel}')
                    if asset.get(kind + '_format') not in (None, im.format):
                        raise ValueError(f'Image {kind} format metadata differs: {rel}')
            # PNG content at a .jpg path is deliberate: Chromium sniffs the image
            # format, while lossless encoding preserves untouched source pixels.
            paths.add(rel)
            checked.append(dict(asset))
    actual = {p.relative_to(output_root).as_posix() for p in output_root.rglob('*') if p.is_file()}
    if actual != paths:
        raise ValueError(f'Unexpected or missing reviewed image outputs: {actual ^ paths}')
    return checked, {
        'manifest_sha256': tl.digest(manifest_path.read_bytes()),
        'original_archive_sha256': ORIGINAL_SHA256,
        'replaced_images': len(checked),
        'inventory_status': manifest.get('inventory_status'),
        'coverage_ref': manifest.get('coverage_ref'),
        'limitations': manifest.get('limitations', []),
        'assets': checked,
    }

def exact_replace(rel, before, after):
    path = OUT / rel
    data = path.read_bytes() if rel in written else (tl.SOURCE / rel).read_bytes()
    a, b = before.encode(), after.encode()
    if data.count(a) != 1:
        raise ValueError(f'Compatibility anchor is not unique: {rel}')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.replace(a, b, 1))
    written.add(rel)
    fixes.append({'file': rel, 'before': before, 'after': after})

images, image_report = checked_images()
store = tl.checked_store()
tl.validate(store, complete=True)
issues = tl.inject.verify(tl.SOURCE, store)
if issues:
    raise ValueError(issues)
files, spans = tl.inject.write(tl.SOURCE, OUT, store, emitters={'emb'})
written = set(tl.inject.collect(store))
fixes = []
# This plugin has a separate CSS whitespace filter. Touch only its sample loader.
exact_replace('data/others/plugin/theme_kopanda_16/testMessagePlus/gMessageTester.js',
    'data = data.replace(/;.*/g, "\\n");\r\n\t\t// 改行、空白、タブの削除\r\n\t\tdata = data.replace(/(\\n|\\s|\\t)/g, "");',
    'data = data.replace(/;.*/g, "\\n");\r\n\t\t// Preserve English word spaces; remove only line separators and tabs.\r\n\t\tdata = data.replace(/[\\r\\n\\t]/g, "");')
# Display aliases only: retain the original registered names and CSS classes.
names = {'undress_bug':'Giant Katydid', 'kosuri_bug':'Giant Katydid',
    'insert_bug':'Giant Katydid', 'sanran_ch':'Giant Katydid',
    'kosuri_face':'Himarii', 'insert_face':'Himarii', 'sanran_face':'Himarii',
    'sanran_bl':'Himarii', 'ev_baby':'Himarii'}
exact_replace('tyrano/plugins/kag/kag.tag.js',
    '${chara_name}</b>：<span class="backlog_text',
    '${(' + json.dumps(names, separators=(',', ':')) + ')[chara_name]||chara_name}</b>: <span class="backlog_text')

# Reviewed continuation-space and fit adjustments are exact source-anchored edits.
adjustments = ROOT / 'manual' / 'build_adjustments.json'
if adjustments.exists():
    for change in tl.read_json(adjustments):
        if 'line' not in change:
            exact_replace(change['file'], change['before'], change['after'])
            continue
        path = OUT / change['file']
        lines = path.read_bytes().decode('utf-8').splitlines(keepends=True)
        at = change['line'] - 1
        if lines[at].rstrip('\r\n') != change['before']:
            raise ValueError(f'Line adjustment drifted: {change}')
        ending = lines[at][len(change['before']):]
        lines[at] = change['after'] + ending
        path.write_bytes(''.join(lines).encode('utf-8'))
        fixes.append(change)

# Generate legacy-save display refresh from this exact translation build.
archive = Path(tl.read_json(ROOT / 'source/manifest.json')['archive']['path'])
runtime = archive.parent.parent / 'musi_dream.exe'
compat = ROOT / 'manual/runtime_audit/save_compat_append.js'
env = dict(os.environ, ELECTRON_RUN_AS_NODE='1')
subprocess.run([str(runtime), str(ROOT / 'manual/runtime_audit/save_compat_generate.cjs'),
    str(tl.SOURCE), str(OUT), str(ROOT / 'manual/complete.packet.json'),
    str(ROOT / 'manual/complete.reply.json'), str(compat)], env=env, check=True,
    capture_output=True)
rel = 'tyrano/plugins/kag/kag.menu.js'
target = OUT / rel
base = target.read_bytes() if rel in written else (tl.SOURCE / rel).read_bytes()
target.parent.mkdir(parents=True, exist_ok=True)
target.write_bytes(base + b'\n' + compat.read_bytes())
written.add(rel)
fixes.append({'file': rel, 'action': 'append generated legacy-save display refresh',
              'sha256': tl.digest(compat.read_bytes())})
for asset in images:
    rel = asset['path']
    if rel in written:
        raise ValueError(f'Image replacement collides with text injection: {rel}')
    target = OUT / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / 'images/output' / rel, target)
    if tl.digest(target.read_bytes()) != asset['output_sha256']:
        raise ValueError(f'Copied image payload hash differs: {rel}')
    written.add(rel)
if {p.relative_to(OUT).as_posix() for p in OUT.rglob('*') if p.is_file()} != written:
    raise ValueError('Unexpected stale files in payload; inspect output before packaging')
tl.write_json(ROOT / 'reports' / 'build.json', {'injected_files': files,
    'translated_spans': spans, 'compatibility_changes': fixes,
    'images': image_report,
    'payload': {p.relative_to(OUT).as_posix(): tl.digest(p.read_bytes())
                for p in sorted(OUT.rglob('*')) if p.is_file()}})
print(f'Injected {spans} spans in {files} files; {len(fixes)} compatibility/fit edits; '
      f'{len(images)} reviewed image replacements.')
