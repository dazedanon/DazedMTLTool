"""Force dialogue nameplates to use stable center math.

yst00067 already contains the values needed for a centered speaker-name draw,
but the active path can still reach the final FONT.XY.SET with x=2. This patch
preserves instruction indexes and forces the final draw point to:

    x = (nameplate_width / 2) - (strlen(name) * corrected_font_width / 2) - offset

Long-name left alignment is handled in patch_speakers.py by padding the
measurement string with trailing invisible speaker-space sentinels. That keeps
this script patch simple and avoids touching YU-RIS control flow.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")

TARGET_INDEX = 1424
TARGET_CONDITION = bytes.fromhex(
    "560300405f04"      # V@045f
    "42010024"          # 36
    "2c0000"            # ,
    "42010021"          # 33
    "29010000"          # []
    "42010001"          # 1
    "3d0000"            # ==
)
ALWAYS_TRUE = bytes.fromhex("42010001420100013d0000")

FONT_XY_INDEX = 1460
OLD_FONT_X_EXPR = bytes.fromhex("480300405312")
DIRECT_MEASURE_CENTER_X_EXPR = bytes.fromhex(
    "480300404d12"      # H@124d = TIP.NAMEW.TX width
    "480300404f12"      # H@124f = _NAMETMP measured width
    "2d0000"            # -
    "42010002"          # 2
    "2f0000"            # /
)
OLD_CENTER_BASE_X_EXPR = bytes.fromhex(
    "480300404d12"      # H@124d
    "42010002"          # 2
    "2f0000"            # /
    "560300403900"      # V@0039
    "42010001"          # 1
    "29010000"          # []
    "48030040e711"      # H@11e7 = font SX
    "42010002"          # 2
    "2f0000"            # /
    "2a0000"            # *
    "2d0000"            # -
)

NAME_ADVANCE_EXTRA = 4
CENTER_X_OFFSET = 48


def v_strlen_result(index):
    return bytes.fromhex("560300403900") + bytes([0x42, 0x01, 0x00, index]) + bytes.fromhex("29010000")


def int_literal(value):
    return bytes([0x42, 0x01, 0x00, value])


NAME_LENGTH_EXPR = v_strlen_result(1)
CENTER_BASE_X_EXPR = bytes.fromhex(
    "480300404d12"      # H@124d
    "42010002"          # 2
    "2f0000"            # /
) + NAME_LENGTH_EXPR + bytes.fromhex(
    "48030040e711"      # H@11e7
) + int_literal(NAME_ADVANCE_EXTRA) + bytes.fromhex(
    "2b0000"            # +
    "2a0000"            # *
    "42010002"          # 2
    "2f0000"            # /
    "2d0000"            # -
)
CENTER_FONT_X_EXPR = CENTER_BASE_X_EXPR + int_literal(CENTER_X_OFFSET) + bytes.fromhex("2d0000")


def is_previous_center_expr(expr):
    if expr in (OLD_CENTER_BASE_X_EXPR, CENTER_BASE_X_EXPR, CENTER_FONT_X_EXPR, DIRECT_MEASURE_CENTER_X_EXPR):
        return True
    for base in (OLD_CENTER_BASE_X_EXPR, CENTER_BASE_X_EXPR):
        trailer_len = 7
        if (
            len(expr) == len(base) + trailer_len
            and expr.startswith(base)
            and expr[len(base):len(base) + 3] == bytes.fromhex("420100")
            and expr[-3:] == bytes.fromhex("2d0000")
        ):
            return True
    return False


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


def patch_nameplate_center(in_path, out_path):
    ver, ic, reserved, code, args, strs, lines = read_ystb(in_path)
    slices = arg_slices(code, args)

    patched = []

    start, _end = slices[TARGET_INDEX]
    if code[TARGET_INDEX * 4] != 0x2D or code[TARGET_INDEX * 4 + 1] != 3:
        raise RuntimeError(f"unexpected instruction at {TARGET_INDEX}")

    atype, size, off = struct.unpack("<3I", args[start:start + 12])
    condition = bytes(strs[off:off + size])
    if atype == 0x00010000 and condition == ALWAYS_TRUE:
        pass
    elif atype == 0x00010000 and condition == TARGET_CONDITION:
        new_off = len(strs)
        strs.extend(ALWAYS_TRUE)
        args[start:start + 12] = struct.pack("<3I", atype, len(ALWAYS_TRUE), new_off)
        patched.append(f"guard@{TARGET_INDEX}")
    else:
        raise RuntimeError("nameplate-center guard condition did not match expected bytecode")

    st, _en = slices[FONT_XY_INDEX]
    if code[FONT_XY_INDEX * 4] != 0x2C or code[FONT_XY_INDEX * 4 + 1] != 3:
        raise RuntimeError(f"instruction {FONT_XY_INDEX} is no longer FONT.XY.SET")
    a0 = struct.unpack("<3I", args[st:st + 12])
    a1 = struct.unpack("<3I", args[st + 12:st + 24])
    fn_expr = bytes(strs[a0[2]:a0[2] + a0[1]])
    x_expr = bytes(strs[a1[2]:a1[2] + a1[1]])
    if fn_expr != m_literal("es.FONT.XY.SET"):
        raise RuntimeError("FONT.XY.SET target did not match expected bytecode")
    if x_expr == CENTER_FONT_X_EXPR:
        pass
    elif x_expr == OLD_FONT_X_EXPR or is_previous_center_expr(x_expr):
        new_off = len(strs)
        strs.extend(CENTER_FONT_X_EXPR)
        args[st + 12:st + 24] = struct.pack("<3I", a1[0], len(CENTER_FONT_X_EXPR), new_off)
        patched.append(f"xexpr@{FONT_XY_INDEX}")
    else:
        raise RuntimeError("FONT.XY.SET X expression did not match expected bytecode")

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
        print(f"{out_path}: nameplate centering already patched")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: patch_nameplate_center.py <input yst00067.ybn> <output yst00067.ybn>")
        sys.exit(1)
    patch_nameplate_center(sys.argv[1], sys.argv[2])
