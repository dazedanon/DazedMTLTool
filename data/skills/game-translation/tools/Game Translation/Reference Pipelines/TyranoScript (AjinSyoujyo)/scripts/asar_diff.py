import json, struct, sys
from pathlib import Path

def header(path):
    with open(path, "rb") as fh:
        struct.unpack("<I", fh.read(4))[0]
        header_size = struct.unpack("<I", fh.read(4))[0]
        struct.unpack("<I", fh.read(4))[0]
        json_size = struct.unpack("<I", fh.read(4))[0]
        return json.loads(fh.read(json_size).decode("utf-8"))

def walk(node, prefix=""):
    for name, entry in node.get("files", {}).items():
        rel = f"{prefix}/{name}" if prefix else name
        if "files" in entry:
            yield from walk(entry, rel)
        else:
            yield rel, entry.get("size", 0)

old = dict(walk(header(sys.argv[1])))
new = dict(walk(header(sys.argv[2])))
added = sorted(set(new) - set(old))
removed = sorted(set(old) - set(new))
resized = sorted(k for k in set(old) & set(new) if old[k] != new[k])
print(f"entries  old {len(old)}  new {len(new)}")
print(f"added {len(added)}  removed {len(removed)}  size-changed {len(resized)}")
for k in added: print("  + " + k)
for k in removed: print("  - " + k)
for k in resized: print(f"  ~ {k}  {old[k]} -> {new[k]}")
