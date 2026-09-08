"""Parser for Siglus engine Scene.pck (this game's variant).

Layout learned from inspection:
  - 0x00: header_size (= 0x5C, fixed for this game)
  - 0x04..0x57: 11 pairs of (uint32 offset, uint32 count)
  - 0x58..0x5B: trailing 8 bytes (purpose unclear; observed (1, 0x266))
  - Then 10 tables follow contiguously.

Pair groups:
  Group A — global vars #1 (count 0x36 = 54)
    [0]: type table       (8 bytes/entry: type, dim?)
    [1]: name idx table   (uint32 char_offset, uint32 char_count)
    [2]: name buffer      (UTF-16LE)
  Group B — global vars #2 (count 0xF6 = 246, same layout as A)
    [3], [4], [5]
  Group C — scenes (count 0x7E = 126, 4 sub-tables)
    [6]: name idx         (char_offset, char_count) into name buffer
    [7]: name buffer      (UTF-16LE) — scene names like "0010_e001_main"
    [8]: data idx         (byte_offset, byte_count) into data buffer
    [9]: data buffer      (encrypted/compressed bytecode per scene)
"""

import struct, os, sys, json

PCK = r"c:\Users\sw\Desktop\Games\Inmon Tougi Toshi Sodom Daikan\StartData\GameData\Scene.pck"
OUT = r"c:\Users\sw\Desktop\Games\Inmon Tougi Toshi Sodom Daikan\StartData\GameData\_workspace\out"


def u32(buf, off):
    return struct.unpack_from("<I", buf, off)[0]


def parse(pck_path: str):
    data = open(pck_path, "rb").read()
    header_size = u32(data, 0)
    assert header_size % 4 == 0
    n_words = header_size // 4
    # Read all header words
    words = [u32(data, 4 * i) for i in range(n_words)]
    # 1 word (header_size) + N pairs + maybe trailing
    pair_words = words[1:]
    # 11 pairs (22 words) + 1 trailing pair (2 words) for this layout
    pairs = []
    for i in range(0, len(pair_words) - 1, 2):
        off = pair_words[i]
        cnt = pair_words[i + 1]
        pairs.append((off, cnt))
    return data, header_size, pairs


def parse_string_table(data, idx_off, idx_count, buf_off):
    """Read (char_offset, char_count) entries indexing into a UTF-16LE buffer."""
    out = []
    for i in range(idx_count):
        eo = idx_off + i * 8
        char_off = u32(data, eo)
        char_len = u32(data, eo + 4)
        s = data[buf_off + char_off * 2 : buf_off + (char_off + char_len) * 2].decode(
            "utf-16-le", errors="replace"
        )
        out.append(s)
    return out


def main():
    data, header_size, pairs = parse(PCK)
    print(f"File:           {PCK}")
    print(f"Size:           {len(data):,} bytes (0x{len(data):X})")
    print(f"Header size:    0x{header_size:X}")
    print(f"Pairs:          {len(pairs)}")
    for i, (off, cnt) in enumerate(pairs):
        print(f"  pair[{i:02d}]    off=0x{off:08X}  count=0x{cnt:X} ({cnt})")

    # Group A
    a_type, a_idx, a_buf = pairs[0], pairs[1], pairs[2]
    var_names_A = parse_string_table(data, a_idx[0], a_idx[1], a_buf[0])
    # Group B
    b_type, b_idx, b_buf = pairs[3], pairs[4], pairs[5]
    var_names_B = parse_string_table(data, b_idx[0], b_idx[1], b_buf[0])
    # Group C — scenes
    c_name_idx, c_name_buf, c_data_idx, c_data_buf = (
        pairs[6],
        pairs[7],
        pairs[8],
        pairs[9],
    )
    scene_names = parse_string_table(data, c_name_idx[0], c_name_idx[1], c_name_buf[0])

    print(f"\nGroup A globals: {len(var_names_A)}  (e.g. {var_names_A[:3]})")
    print(f"Group B globals: {len(var_names_B)}  (e.g. {var_names_B[:3]})")
    print(f"Scenes:          {len(scene_names)}  (e.g. {scene_names[:3]})")

    os.makedirs(OUT, exist_ok=True)
    os.makedirs(os.path.join(OUT, "scenes_raw"), exist_ok=True)

    # Dump variable name lists
    with open(os.path.join(OUT, "globals_A.txt"), "w", encoding="utf-8") as f:
        for i, n in enumerate(var_names_A):
            t1, t2 = u32(data, a_type[0] + i * 8), u32(data, a_type[0] + i * 8 + 4)
            f.write(f"{i:03d}\ttype1=0x{t1:X}\ttype2=0x{t2:X}\t{n}\n")
    with open(os.path.join(OUT, "globals_B.txt"), "w", encoding="utf-8") as f:
        for i, n in enumerate(var_names_B):
            t1, t2 = u32(data, b_type[0] + i * 8), u32(data, b_type[0] + i * 8 + 4)
            f.write(f"{i:03d}\ttype1=0x{t1:X}\ttype2=0x{t2:X}\t{n}\n")

    # Dump scene info + raw bytecode chunks
    data_buf_base = c_data_buf[0]
    sizes = []
    with open(os.path.join(OUT, "scenes_index.txt"), "w", encoding="utf-8") as f:
        for i, name in enumerate(scene_names):
            eo = c_data_idx[0] + i * 8
            byte_off = u32(data, eo)
            byte_len = u32(data, eo + 4)
            abs_off = data_buf_base + byte_off
            sizes.append(byte_len)
            f.write(
                f"{i:03d}\t{name}\toff=0x{byte_off:08X}\tabs=0x{abs_off:08X}\tlen=0x{byte_len:X} ({byte_len})\n"
            )
            chunk = data[abs_off : abs_off + byte_len]
            safe_name = name.replace("/", "_").replace("\\", "_")
            with open(
                os.path.join(OUT, "scenes_raw", f"{i:03d}_{safe_name}.bin"), "wb"
            ) as g:
                g.write(chunk)

    # Trailing 8 bytes of header (after 11 pairs)
    trailing_off = 4 + 11 * 8
    if trailing_off + 8 <= header_size:
        t1 = u32(data, trailing_off)
        t2 = u32(data, trailing_off + 4)
        print(f"\nTrailing header pair: ({t1}, {t2})  (0x{t1:X}, 0x{t2:X})")

    print(
        f"\nWrote: globals_A.txt, globals_B.txt, scenes_index.txt, scenes_raw/*.bin"
    )
    print(f"Scene chunk size range: {min(sizes):,}..{max(sizes):,} bytes (avg {sum(sizes)//len(sizes):,})")
    print(f"Total scene bytes: {sum(sizes):,}")
    print(f"File size:         {len(data):,}")
    print(f"Bytecode buffer:   0x{data_buf_base:X}..0x{data_buf_base + sum(sizes):X}")


if __name__ == "__main__":
    main()
