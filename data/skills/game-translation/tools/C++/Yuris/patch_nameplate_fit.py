"""Fit only long speaker names inside the dialogue nameplate.

The vanilla script's English name positioning is acceptable for short names,
but English role names such as "Item Shop Owner" can spill into the ornamental
edge of the plate. yst00067 already has strlen(name), the plate width
(H@124d), and the font cell size (H@11e7).

This patch keeps the original x expression for short names and only switches
to corrected center math for names longer than "Soldier A":

    if strlen(name) > 9:
        x = (plate_width / 2) - ((strlen(name) * ascii_cell_width) / 2)
    else:
        x = original script x expression

No dialogue/backlog wrapping code is touched.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")

LONG_NAME_GUARD_INDEX = 1424
X_ASSIGN_INDEX = 1426

ORIGINAL_GUARD = bytes.fromhex(
    "560300405f04"      # V@045f
    "42010024"          # 36
    "2c0000"            # ,
    "42010021"          # 33
    "29010000"          # []
    "42010001"          # 1
    "3d0000"            # ==
)

ALWAYS_TRUE = bytes.fromhex("42010001420100013d0000")

H_PLATE_W = bytes.fromhex("480300404d12") # H@124d measured nameplate width
H_NAME_X = bytes.fromhex("480300405312")  # H@1253 final name x
H_FONT_SX = bytes.fromhex("48030040e711") # H@11e7 font cell size

NAME_LEN = bytes.fromhex(
    "560300403900"      # V@0039
    "42010001"          # 1
    "29010000"          # []
)

LONGER_THAN_SOLDIER_A = (
    NAME_LEN +
    bytes.fromhex("42010009") + # 9
    bytes.fromhex("3e0000")     # >
)

OLD_LEN_CENTER_X = bytes.fromhex(
    "480300404d12"      # H@124d
    "42010002"          # 2
    "2f0000"            # /
    "560300403900"      # V@0039
    "42010001"          # 1
    "29010000"          # []
    "48030040e711"      # H@11e7
    "42010002"          # 2
    "2f0000"            # /
    "2a0000"            # *
    "2d0000"            # -
)

CORRECTED_LONG_CENTER_X = (
    H_PLATE_W +
    bytes.fromhex("42010002") + # 2
    bytes.fromhex("2f0000") +   # /
    NAME_LEN +
    H_FONT_SX +
    bytes.fromhex("42010002") + # 2
    bytes.fromhex("2f0000") +   # /  -> ASCII cell width
    bytes.fromhex("2a0000") +   # *
    bytes.fromhex("42010002") + # 2
    bytes.fromhex("2f0000") +   # /  -> half total name width
    bytes.fromhex("2d0000")     # -
)

GATED_LONG_CENTER_X = (
    OLD_LEN_CENTER_X +
    LONGER_THAN_SOLDIER_A +
    CORRECTED_LONG_CENTER_X +
    OLD_LEN_CENTER_X +
    bytes.fromhex("2d0000") +   # corrected - original
    bytes.fromhex("2a0000") +   # cond * delta
    bytes.fromhex("2b0000")     # original + ...
)

PREVIOUS_LEN_CENTER_WITH_EXTRA = bytes.fromhex(
    "480300404d12"      # H@124d
    "42010002"          # 2
    "2f0000"            # /
    "560300403900"      # V@0039
    "42010001"          # 1
    "29010000"          # []
    "48030040e711"      # H@11e7
    "42010004"          # 4
    "2b0000"            # +
    "2a0000"            # *
    "42010002"          # 2
    "2f0000"            # /
    "2d0000"            # -
)

MEASURED_CENTER_X = (
    H_PLATE_W +
    bytes.fromhex("480300404f12") + # H@124f, unsafe in guard but accepted for rollback detection
    bytes.fromhex("2d0000") +
    bytes.fromhex("42010002") +
    bytes.fromhex("2f0000")
)

BAD_MEASURED_GUARD = (
    bytes.fromhex("480300404f12") +
    H_PLATE_W +
    bytes.fromhex("42010002") +
    bytes.fromhex("2f0000") +
    bytes.fromhex("3e0000")
)


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


def patch_nameplate_fit(in_path, out_path):
    ver, ic, reserved, code, args, strs, lines = read_ystb(in_path)
    slices = arg_slices(code, args)
    patched = []

    if code[LONG_NAME_GUARD_INDEX * 4] != 0x2D or code[LONG_NAME_GUARD_INDEX * 4 + 1] != 3:
        raise RuntimeError(f"unexpected guard instruction at {LONG_NAME_GUARD_INDEX}")
    st, _ = slices[LONG_NAME_GUARD_INDEX]
    atype, size, off = struct.unpack("<3I", args[st:st + 12])
    guard = bytes(strs[off:off + size])
    if guard == ALWAYS_TRUE:
        pass
    elif guard in (ORIGINAL_GUARD, BAD_MEASURED_GUARD):
        new_off = len(strs)
        strs.extend(ALWAYS_TRUE)
        args[st:st + 12] = struct.pack("<3I", atype, len(ALWAYS_TRUE), new_off)
        patched.append(f"always-on gated guard@{LONG_NAME_GUARD_INDEX}")
    else:
        raise RuntimeError(f"nameplate guard did not match a known form: {guard.hex()}")

    if code[X_ASSIGN_INDEX * 4] != 0x36 or code[X_ASSIGN_INDEX * 4 + 1] != 2:
        raise RuntimeError(f"unexpected x assignment instruction at {X_ASSIGN_INDEX}")
    st, _ = slices[X_ASSIGN_INDEX]
    dest = struct.unpack("<3I", args[st:st + 12])
    src = struct.unpack("<3I", args[st + 12:st + 24])
    dest_expr = bytes(strs[dest[2]:dest[2] + dest[1]])
    x_expr = bytes(strs[src[2]:src[2] + src[1]])
    if dest_expr != H_NAME_X:
        raise RuntimeError(f"x assignment destination changed: {dest_expr.hex()}")
    if x_expr == GATED_LONG_CENTER_X:
        pass
    elif x_expr in (OLD_LEN_CENTER_X, PREVIOUS_LEN_CENTER_WITH_EXTRA, MEASURED_CENTER_X):
        new_off = len(strs)
        strs.extend(GATED_LONG_CENTER_X)
        args[st + 12:st + 24] = struct.pack("<3I", src[0], len(GATED_LONG_CENTER_X), new_off)
        patched.append(f"length-gated x@{X_ASSIGN_INDEX}")
    else:
        raise RuntimeError(f"nameplate x expression did not match a known form: {x_expr.hex()}")

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

    if patched:
        print(f"patched {out_path}: {', '.join(patched)}")
    else:
        print(f"{out_path}: nameplate fit already patched")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: patch_nameplate_fit.py <input yst00067.ybn> <output yst00067.ybn>")
        sys.exit(1)
    patch_nameplate_fit(sys.argv[1], sys.argv[2])
