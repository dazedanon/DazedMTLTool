"""Move config font selector text definitions offscreen.

The selector art can be hidden with loose PNG overrides, but YU-RIS also draws
the current font name through the FONTSEL/FONTLISTSEL text definitions in
yst00081. Moving only those definitions offscreen avoids no-oping the config
button setup, which previously made the game close at startup.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")

# Expression encodings seen in yst00081:
#   57 02 00 <u16>                 literal integer
#   57 02 00 <u16> 42 01 00 00 2b 00 00   literal + 0
OFFSCREEN_SHORT = bytes.fromhex("570200d007")
OFFSCREEN_PLUS_ZERO = bytes.fromhex("570200d007420100002b0000")

# (instruction index, arg index, expected old size, replacement payload)
TARGETS = {
    # FONTSEL x/y
    (1, 1): (12, OFFSCREEN_PLUS_ZERO),
    (2, 1): (12, OFFSCREEN_PLUS_ZERO),
    # FONTLISTSEL x/y
    (4, 1): (12, OFFSCREEN_PLUS_ZERO),
    (5, 1): (5, OFFSCREEN_SHORT),
}


def xor_apply(data):
    return bytes(b ^ KEY[i & 3] for i, b in enumerate(data))


def read_ystb(path):
    blob = open(path, "rb").read()
    if blob[:4] != b"YSTB":
        raise ValueError(f"{path} is not a YSTB file")
    ver, ic, code_sz, arg_sz, str_sz, line_sz, reserved = struct.unpack("<7I", blob[4:32])
    code_off = 32
    arg_off = code_off + code_sz
    str_off = arg_off + arg_sz
    line_off = str_off + str_sz
    code = bytearray(xor_apply(blob[code_off:arg_off]))
    args = bytearray(xor_apply(blob[arg_off:str_off]))
    strs = bytearray(xor_apply(blob[str_off:line_off]))
    lines = blob[line_off:line_off + line_sz]
    if ic != len(code) // 4 or line_sz != ic * 4:
        raise ValueError("unexpected YSTB instruction/line table layout")
    return ver, ic, reserved, code, args, strs, lines


def arg_positions(code, args):
    pos = 0
    out = {}
    for ins in range(len(code) // 4):
        argc = code[ins * 4 + 1]
        for arg in range(argc):
            out[(ins, arg)] = pos + arg * 12
        pos += argc * 12
    if pos != len(args):
        raise ValueError(f"arg stream length mismatch: walked {pos}, have {len(args)}")
    return out


def write_ystb(path, ver, ic, reserved, code, args, strs, lines):
    header = struct.pack(
        "<4s7I",
        b"YSTB",
        ver,
        ic,
        len(code),
        len(args),
        len(strs),
        len(lines),
        reserved,
    )
    out = header + xor_apply(code) + xor_apply(args) + xor_apply(strs) + lines
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "wb") as f:
        f.write(out)


def patch_font_text_positions(in_path, out_path):
    ver, ic, reserved, code, args, strs, lines = read_ystb(in_path)
    positions = arg_positions(code, args)

    patched = []
    for key, (expected_size, replacement) in TARGETS.items():
        if key not in positions:
            raise RuntimeError(f"missing instruction/arg {key}")
        arg_pos = positions[key]
        atype, size, off = struct.unpack("<3I", args[arg_pos:arg_pos + 12])
        if size != expected_size or len(replacement) != expected_size:
            raise RuntimeError(f"{key} size mismatch: have {size}, expected {expected_size}")
        old = bytes(strs[off:off + size])
        strs[off:off + size] = replacement
        patched.append((key, atype, old.hex(), replacement.hex()))

    write_ystb(out_path, ver, ic, reserved, code, args, strs, lines)
    for (ins, arg), atype, old, new in patched:
        print(f"{ins}:{arg} type={atype:08x} {old}->{new}")
    print(f"patched {out_path}: moved FONTSEL/FONTLISTSEL text offscreen")


def main(argv):
    if len(argv) != 3:
        print("usage: patch_config_font_text_offscreen.py <input yst00081.ybn> <output yst00081.ybn>")
        return 1
    patch_font_text_positions(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
