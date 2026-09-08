import json
from inventory import GAME, HERE

rows = json.loads((HERE/'inventory.json').read_bytes())
selected = [*range(110,128),*range(132,139),141,571,572,*range(603,609),
            540,541,542,543,544,552,553,554,558,559,560,561,562,563,599]
for i in selected:
    r=rows[i]
    print(json.dumps({'id':i,'path':r['path'],'refs':r['literal_references'][:4],
                      'ref_count':len(r['literal_references'])},ensure_ascii=False))
tilesets=json.loads((GAME/'data/Tilesets.json').read_bytes())
for tileset in tilesets:
    if not tileset or 'SF_Inside_C' not in tileset['tilesetNames']: continue
    sheet_index=tileset['tilesetNames'].index('SF_Inside_C')
    assert sheet_index==6, sheet_index
    for path in sorted((GAME/'data').glob('Map[0-9]*.json')):
        data=json.loads(path.read_bytes())
        if data['tilesetId'] != tileset['id']:continue
        matches=[]
        for index,tile in enumerate(data['data'][:data['width']*data['height']*4]):
            if tile in (292,366,367):
                matches.append({'tileId':tile,'x':index%data['width'],'y':(index//data['width'])%data['height'],'z':index//(data['width']*data['height'])})
        # Event-page tile graphics use the same IDs.
        for e in data['events']:
            if not e:continue
            for p in e['pages']:
                if p['image']['tileId'] in (292,366,367):matches.append({'eventId':e['id'],'tileId':p['image']['tileId']})
        print(json.dumps({'tileset':tileset['id'],'map':path.name,'label_tiles':matches}))
