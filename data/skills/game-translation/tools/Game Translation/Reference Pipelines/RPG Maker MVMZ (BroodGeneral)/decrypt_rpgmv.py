import os

KEY = bytes.fromhex("41482469aa2d1ec391fedd5a2f25b744")
HEADER_LEN = 16  # RPG Maker MV fake header length

# Resolve paths relative to the project root (the parent of this tooling/ folder),
# so the script works no matter where it's run from.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "www", "img")
DST = os.path.join(ROOT, "imagestotranslate")

count = 0
errors = []

for root, _dirs, files in os.walk(SRC):
    for name in files:
        if not name.lower().endswith(".rpgmvp"):
            continue
        src_path = os.path.join(root, name)
        rel = os.path.relpath(src_path, SRC)
        out_rel = os.path.splitext(rel)[0] + ".png"
        out_path = os.path.join(DST, out_rel)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        try:
            with open(src_path, "rb") as f:
                data = f.read()
            # strip the 16-byte fake header, then XOR the next 16 bytes with the key
            body = bytearray(data[HEADER_LEN:])
            for i in range(min(HEADER_LEN, len(body))):
                body[i] ^= KEY[i]
            with open(out_path, "wb") as f:
                f.write(body)
            count += 1
        except Exception as e:  # noqa: BLE001
            errors.append((src_path, str(e)))

print(f"Decrypted {count} files into '{DST}/'")
if errors:
    print(f"{len(errors)} errors:")
    for p, e in errors[:20]:
        print(f"  {p}: {e}")
