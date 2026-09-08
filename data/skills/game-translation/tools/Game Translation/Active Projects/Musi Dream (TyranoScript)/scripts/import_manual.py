"""Import the reviewed manual translations atomically through the packet gate."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tl

root = tl.ROOT
store = tl.checked_store()
reply = {}
for name in ('ui', 'opening_endings', 'middle', 'scene6'):
    part = tl.strict_json(root / 'manual' / (name + '.json'))
    if reply.keys() & part.keys():
        raise ValueError('Duplicate manual unit ownership')
    reply.update(part)
assert set(reply) == set(store.by_id())
packet = root / 'manual' / 'complete.packet.json'
answer = root / 'manual' / 'complete.reply.json'
tl.write_json(packet, {'source_manifest_sha256': tl.verify_source(),
    'units': tl.packet_rows(store.all_units()), 'method': 'Manually authored; no API'})
tl.write_json(answer, reply)
tl.import_reply(store, packet, answer, replace=True)
print(tl.validate(store, complete=True))
