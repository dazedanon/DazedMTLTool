"""Install or restore this exact local patch, with hashes and an original backup."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
ORIGINAL = '2c22ad3c7dd540f4e870c195935a206eeafc58665c458673c88c3acb9a5ab611'
PREVIOUS_ENGLISH = '9ce062c0ec2f3466d5f83e4a730026c4cd5241fdf529aff49a339d434b51f59a'
TOOLTIP_ENGLISH = '86b0e41ed359927d103db5ef8f61e4fe215accff0c7738fa3831544704043884'
CREDITED_ENGLISH = '048ab7108d911f15be6cd1e1751b489c645a70c2c32ac7c59962fea08116d3aa'
STATUS_ENGLISH = 'ea0fd75ab30a5e5e3c64dddebd518ea54043cdaae646eac7a93d4e4843312b0a'
QUEST_ENGLISH = '713a7fe971a7784e015605035aa0cd32fe4bcfe04b779ddf2346ceb8c2878076'
ENGLISH = '744fd77d3ab6968f71f581a6e5d015e75028f2d4b763dc03063992efe6fa6d1d'

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--game', type=Path, default=HERE.parent)
    parser.add_argument('--restore', action='store_true')
    args = parser.parse_args()
    game = args.game.resolve()
    assert (game/'Nightfall Princess.exe').is_file(), 'Specify the game directory with --game'
    target = game/'data.win'
    expected = ORIGINAL if args.restore else ENGLISH
    if sha(target) == expected:
        print('Already installed: '+('Japanese original' if args.restore else 'English translation'))
        return
    process_list = subprocess.run(['tasklist','/FI','IMAGENAME eq Nightfall Princess.exe','/FO','CSV','/NH'],
                                  capture_output=True,text=True,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    assert not any(row and row[0].lower()=='nightfall princess.exe' for row in csv.reader(process_list.stdout.splitlines())), 'Close the game before installing or restoring'
    current = sha(target)
    allowed = {ENGLISH, PREVIOUS_ENGLISH, TOOLTIP_ENGLISH, CREDITED_ENGLISH, STATUS_ENGLISH, QUEST_ENGLISH} if args.restore else {ORIGINAL, PREVIOUS_ENGLISH, TOOLTIP_ENGLISH, CREDITED_ENGLISH, STATUS_ENGLISH, QUEST_ENGLISH}
    assert current in allowed, 'Unexpected data.win; refusing to overwrite it'
    backup = game/'manual-translation/backup/data.original.win'
    if not args.restore:
        backup.parent.mkdir(parents=True,exist_ok=True)
        if not backup.exists():
            assert current == ORIGINAL, 'Original backup missing; cannot upgrade safely'
            with backup.open('xb') as out, target.open('rb') as src:
                shutil.copyfileobj(src,out)
        assert sha(backup)==ORIGINAL, 'Original backup hash mismatch'
        earlier = {PREVIOUS_ENGLISH:'data.english-v1.win', TOOLTIP_ENGLISH:'data.english-v2.win', CREDITED_ENGLISH:'data.english-v3.win', STATUS_ENGLISH:'data.english-v4.win', QUEST_ENGLISH:'data.english-v5.win'}
        if current in earlier:
            previous = backup.parent/earlier[current]
            if not previous.exists():
                with previous.open('xb') as out, target.open('rb') as src:
                    shutil.copyfileobj(src,out)
            assert sha(previous)==current
    source = backup if args.restore else HERE/'release/data.win'
    assert sha(source)==expected, 'Patch or backup hash mismatch'
    staged = game/'data.translation.pending.win'
    with staged.open('xb') as out, source.open('rb') as src:
        shutil.copyfileobj(src,out)
    assert sha(staged)==expected
    os.replace(staged,target)
    assert sha(target)==expected
    report={'installed':str(target),'sha256':expected,'original_backup':str(backup),'restore':args.restore}
    (HERE/'installation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
