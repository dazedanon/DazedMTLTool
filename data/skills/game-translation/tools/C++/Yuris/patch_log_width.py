"""Patch backlog text width in yst00028.ybn without touching dialogue.

The main textbox wrap is already tuned. The backlog uses a separate
es.LOG.DRAWMAIN loop with its own layout width, so it can wrap a couple of
characters earlier and split words before it reaches the packer's padding
points. This patch widens only the backlog message width expression.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")

# yst00028 instruction 115:
#   H@096e = V@045f[21,15]
# H@096e is later used in the es.LOG.DRAWMAIN right-edge calculation.
TARGET_INDEX = 115
TARGET_LHS = bytes.fromhex("480300406e09")
TARGET_RHS = bytes.fromhex("560300405f04420100152c00004201000f29010000")
DEFAULT_DELTA = 30


def xor_apply(data):
    return bytes(b ^ KEY[i & 3] for i, b in enumerate(data))


def b_imm(value):
    if not 0 <= value <= 0xFF:
        raise ValueError("delta must fit in one byte for this patch")
    return bytes([0x42, 0x01, 0x00, value])


def patch_log_width(in_path, out_path, delta):
    blob = open(in_path, "rb").read()
    if blob[:4] != b"YSTB":
        raise ValueError(f"{in_path} is not a YSTB file")
    ver, ic, code_sz, arg_sz, str_sz, line_sz, reserved = struct.unpack("<7I", blob[4:32])
    code_off = 32
    arg_off = code_off + code_sz
    str_off = arg_off + arg_sz
    line_off = str_off + str_sz

    code = xor_apply(blob[code_off:arg_off])
    args = bytearray(xor_apply(blob[arg_off:str_off]))
    strs = bytearray(xor_apply(blob[str_off:line_off]))
    lines = blob[line_off:line_off + line_sz]

    arg_pos = 0
    target_arg_pos = None
    for i in range(ic):
        argc = code[i * 4 + 1]
        if i == TARGET_INDEX:
            if code[i * 4] != 0x36 or argc != 2:
                raise RuntimeError(f"unexpected instruction at {i}")
            lhs_t, lhs_sz, lhs_off = struct.unpack("<3I", args[arg_pos:arg_pos + 12])
            rhs_t, rhs_sz, rhs_off = struct.unpack("<3I", args[arg_pos + 12:arg_pos + 24])
            lhs = bytes(strs[lhs_off:lhs_off + lhs_sz])
            rhs = bytes(strs[rhs_off:rhs_off + rhs_sz])
            if lhs != TARGET_LHS or rhs != TARGET_RHS:
                raise RuntimeError(f"target expression mismatch at {i}")
            if lhs_t != 0x00010000 or rhs_t != 0x00010000:
                raise RuntimeError("unexpected arg types")
            target_arg_pos = arg_pos + 12
            break
        arg_pos += argc * 12

    if target_arg_pos is None:
        raise RuntimeError("target instruction not found")

    new_rhs = TARGET_RHS + b_imm(delta) + bytes.fromhex("2b0000")
    new_off = len(strs)
    strs.extend(new_rhs)
    rhs_t, _rhs_sz, _rhs_off = struct.unpack("<3I", args[target_arg_pos:target_arg_pos + 12])
    args[target_arg_pos:target_arg_pos + 12] = struct.pack("<3I", rhs_t, len(new_rhs), new_off)

    header = struct.pack(
        "<4s7I",
        b"YSTB",
        ver,
        ic,
        code_sz,
        len(args),
        len(strs),
        line_sz,
        reserved,
    )
    out = header + blob[code_off:arg_off] + xor_apply(args) + xor_apply(strs) + lines
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(out)
    print(f"patched {out_path}: backlog width +{delta}")


if __name__ == "__main__":
    if len(sys.argv) not in (3, 4):
        print("usage: patch_log_width.py <input yst00028.ybn> <output yst00028.ybn> [delta]")
        sys.exit(1)
    patch_log_width(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) == 4 else DEFAULT_DELTA)
