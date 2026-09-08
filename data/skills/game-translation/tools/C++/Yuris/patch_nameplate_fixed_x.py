"""Diagnostic nameplate patch: force the final nameplate FONT.XY.SET X value.

This is intentionally temporary. It proves whether yst00067 instruction 1460
is the live nameplate draw point before more centering math is attempted.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")
FONT_XY_INDEX = 1460
FIXED_X = 0


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


def arg_slices(code, args):
    pos = 0
    out = []
    for i in range(len(code) // 4):
        argc = code[i * 4 + 1]
        size = argc * 12
        out.append((pos, pos + size))
        pos += size
    if pos != len(args):
        raise ValueError(f"arg stream length mismatch: walked {pos}, have {len(args)}")
    return out


def m_literal(text):
    raw = text.encode("cp932")
    return b"M" + struct.pack("<H", len(raw) + 2) + b'"' + raw + b'"'


def patch_fixed_x(in_path, out_path):
    ver, ic, reserved, code, args, strs, lines = read_ystb(in_path)
    slices = arg_slices(code, args)
    if FONT_XY_INDEX >= ic:
        raise RuntimeError("FONT.XY.SET target is outside script")

    st, _ = slices[FONT_XY_INDEX]
    if code[FONT_XY_INDEX * 4] != 0x2C or code[FONT_XY_INDEX * 4 + 1] != 3:
        raise RuntimeError("instruction 1460 is no longer a 3-arg call")
    a0 = struct.unpack("<3I", args[st:st + 12])
    a1 = struct.unpack("<3I", args[st + 12:st + 24])
    fn_expr = bytes(strs[a0[2]:a0[2] + a0[1]])
    if fn_expr != m_literal("es.FONT.XY.SET"):
        raise RuntimeError("instruction 1460 is not es.FONT.XY.SET")

    fixed_expr = bytes([0x42, 0x01, 0x00, FIXED_X])
    new_off = len(strs)
    strs.extend(fixed_expr)
    args[st + 12:st + 24] = struct.pack("<3I", a1[0], len(fixed_expr), new_off)

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
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(out)
    print(f"patched {out_path}: nameplate fixed X={FIXED_X}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: patch_nameplate_fixed_x.py <input yst00067.ybn> <output yst00067.ybn>")
        sys.exit(1)
    patch_fixed_x(sys.argv[1], sys.argv[2])
