"""Verify this curated reference without game assets, saves, or network calls."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--node', default='node', help='Available Node executable; no installation is performed')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    tools = root.parents[1]
    manifest = json.loads((root / 'REFERENCE_MANIFEST.json').read_text(encoding='utf-8'))
    verified = 0
    for rel, record in manifest['files'].items():
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or hashlib.sha256(path.read_bytes()).hexdigest() != record['after_sha256']:
            raise ValueError(f'Reference hash mismatch: {rel}')
        verified += 1
    for rel, expected in manifest['shared_files'].items():
        path = (tools / rel).resolve()
        if not path.is_relative_to(tools) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f'Shared tool hash mismatch: {rel}')
        verified += 1
    commands = []
    def run(argv, expected=0):
        result = subprocess.run(argv, text=True, encoding='utf-8', capture_output=True)
        if result.returncode != expected:
            raise ValueError(f'Unexpected exit {result.returncode}, wanted {expected}: {argv}\n{result.stdout}\n{result.stderr}')
        commands.append({'command': [str(a) for a in argv], 'exit': result.returncode})
        return result.stdout
    python_count = js_count = 0
    powershell_paths = []
    for rel in manifest['files']:
        path = root / rel
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=rel)
            python_count += 1
        elif path.suffix in {'.js', '.cjs'}:
            run([args.node, '--check', str(path)])
            js_count += 1
        elif path.suffix == '.ps1':
            powershell_paths.append(path)
    if powershell_paths:
        quoted = ','.join("'" + str(p).replace("'", "''") + "'" for p in powershell_paths)
        command = "$ErrorActionPreference='Stop'; $paths=@(" + quoted + "); foreach ($p in $paths) { $tokens=$null; $errors=$null; [void][System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$tokens,[ref]$errors); if ($errors.Count) { throw ($errors | Out-String) } }"
        run(['powershell', '-NoProfile', '-Command', command])
    fitting = tools / 'Text Fitting'
    run([args.node, str(fitting / 'test_panel_bounds.cjs')])
    run([args.node, str(root / 'tools/test_mz_health.cjs')])
    before = json.loads(run([args.node, str(fitting / 'panel_bounds.cjs'), str(root / 'evidence/results_panel_before.json'), '--margin', '12', '--expect-cases', '56', '--allow-missing-health'], expected=1))
    after = json.loads(run([args.node, str(fitting / 'panel_bounds.cjs'), str(root / 'evidence/results_panel_after.json'), '--margin', '12', '--expect-cases', '112']))
    if before['failures'] != 42 or before['pass'] or not after['pass'] or after['failures']:
        raise ValueError('Recorded before/after regression disagrees')
    reports = {name: json.loads((root / f'evidence/results_panel_{name}.json').read_text(encoding='utf-8')) for name in ['before', 'after']}
    indices = {19, 24, 29, 34, 39, 44, 49, 60, 65, 70, 80, 85, 90, 102}
    # These 14 independently enumerated CE30 stages cannot silently shrink.
    observed_indices = {row['index'] for row in reports['after']['rows']}
    if observed_indices != indices:
        raise ValueError(f'Unexpected result stages: {sorted(observed_indices)}')
    profiles = {'reported', 'zero', 'five_digit', 'seven_digit'}
    reported_old = next(row for row in reports['before']['rows'] if row['profile'] == 'reported' and row['index'] == 102)
    if reported_old['displayed']['right'] <= reported_old['panel']['right']:
        raise ValueError('The player-reported ordinary result must fail before the fix')
    for name, maps in [('before', {4}), ('after', {4, 14})]:
        report = reports[name]
        actual = {(row['map'], row['profile'], row['index']) for row in report['rows']}
        expected = {(m, p, i) for m in maps for p in profiles for i in indices}
        if actual != expected:
            raise ValueError(f'Incomplete variant matrix: {name}')
    for row in reports['after']['rows']:
        if not row['sourceTextPreserved'] or row['storedPosition'] != [208, 112]:
            raise ValueError('Source text or saved picture position changed')
        if row['profile'] != 'seven_digit' and row['scale'] != 1:
            raise ValueError('Ordinary/five-digit results font was reduced')
    lifecycle = json.loads((root / 'evidence/results_fix_lifecycle.json').read_text(encoding='utf-8'))
    if (lifecycle['outsidePanelMaxPixelDelta'] != 0 or lifecycle['before'] != lifecycle['after'] or
        lifecycle['engineError'] or not lifecycle['saveUi'] or not lifecycle['loadUi']):
        raise ValueError('Recorded art-preservation/save-UI lifecycle failed')
    print(json.dumps({'pass': True, 'hash_verified_files': verified, 'python_sources_parsed': python_count,
        'javascript_sources_parsed': js_count, 'powershell_sources_parsed': len(powershell_paths),
        'old_cases': before['cases'], 'old_failures_expected': before['failures'],
        'corrected_cases': after['cases'], 'corrected_failures': after['failures'],
        'minimum_margins': after['minimumMargins'], 'native_run_performed': False,
        'scope': 'Synthetic tool tests, source syntax, hash verification and replay of recorded native observations.'}, indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
