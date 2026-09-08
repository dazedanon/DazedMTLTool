"""Archive the verified baseline after external JSON formatting/bootstrap.

Existing selected values must still match their reviewed sources.
The only live plugin addition accepted here is TranslationUpdateCheck.
"""
import json
import zipfile
from pathlib import Path

import tl
from vendor.core import get, read_json, sha, write_json


def main():
    if (tl.BASE / 'source_snapshot.zip').exists():
        tl.verify_source()
        raise ValueError('An immutable archive already exists; refusing to replace it')
    game = Path(tl.config()['game_root'])
    previous = read_json(tl.BASE / 'manifest.json')
    for site in read_json(tl.BASE / 'sites.json'):
        value = get(tl.read_container(site['file'], game), site['path'])
        if site['mode'] == 'js':
            value = value[site['start']:site['end']]
        if value != site['original']:
            raise ValueError('Reviewed source changed; cannot archive a new baseline')
    for rel in previous['snapshot_files']:
        if rel.endswith(('.js', '.json')):
            before = tl.read_container(rel)
            after = tl.read_container(rel, game)
            if rel == 'js/plugins.js':
                if after[:len(before)] != before or any(p['name'] != 'TranslationUpdateCheck' for p in after[len(before):]):
                    raise ValueError('Unexpected plugin change')
            elif before != after:
                raise ValueError('Snapshot/live content differs: ' + rel)
        elif (tl.SOURCE / rel).read_bytes() != (game / rel).read_bytes():
            raise ValueError('Snapshot/live binary differs: ' + rel)
    paths = {p for folder in ['data', 'js', 'fonts', 'css']
             for p in (game / folder).rglob('*') if p.is_file()}
    paths.update([game / 'index.html', game / 'package.json'])
    hashes = {p.relative_to(game).as_posix(): sha(p.read_bytes()) for p in sorted(paths)}
    snapshot = {rel: hashes[rel] for rel in previous['snapshot_files']}
    write_json(tl.BASE / 'reports/prior_baseline.json', previous)
    with zipfile.ZipFile(tl.BASE / 'source_snapshot.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for rel in snapshot:
            raw = (game / rel).read_bytes()
            if sha(raw) != snapshot[rel]:
                raise ValueError('Source changed during snapshot capture')
            archive.writestr(rel, raw)
    manifest = dict(previous, game_files=hashes, snapshot_files=snapshot,
                    authoritative_snapshot='source_snapshot.zip',
                    source_archive_hash=sha((tl.BASE / 'source_snapshot.zip').read_bytes()))
    write_json(tl.BASE / 'manifest.json', manifest)
    write_json(tl.BASE / 'reports/external_changes.json', {
        'observed': 'DazedTL project initialization reformatted JSON and appended TranslationUpdateCheck while preparation was in progress',
        'reviewed_site_changes': 0, 'selected_json_content_changes': 0,
        'live_plugin_change': 'Unchanged original plugin entries plus TranslationUpdateCheck',
        'prior_manifest': 'reports/prior_baseline.json', 'tracked_files_now': len(hashes),
        'resolution': 'Archive current verified general-UI sources; keep prior source directory as historical evidence; use ZIP for subsequent reads',
        'game_files_modified_by_this_script': False})
    print(json.dumps({'archived_files': len(snapshot), 'tracked_files': len(hashes)}))


if __name__ == '__main__':
    main()
