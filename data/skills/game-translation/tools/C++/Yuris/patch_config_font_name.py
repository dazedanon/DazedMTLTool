"""Hide the drawn font name on the config screen.

The font selector row is mostly graphics, but the current font name is drawn
from bytecode in yst00030's es.FONTLIST.SHOW routine. Do not disable the whole
selector script: that can break startup. This patch only no-ops the draw,
fetch, and copy instructions for the visible font-name text while preserving
all instruction indexes.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")
TARGET_SCRIPT = "yst00030.ybn"
TARGET_INSTRUCTIONS = (20, 52, 53)


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


def literal_text(expr):
    if len(expr) < 5 or expr[0] != 0x4D:
        return None
    n = struct.unpack("<H", expr[1:3])[0]
    if len(expr) < 3 + n or expr[3] != 0x22 or expr[2 + n] != 0x22:
        return None
    try:
        return expr[4:2 + n].decode("cp932")
    except UnicodeDecodeError:
        return None


def first_arg_literal(args, strs, start):
    atype, size, off = struct.unpack("<3I", args[start:start + 12])
    if atype not in (0x00030000, 0x00010000, 0x00010001):
        return None
    return literal_text(bytes(strs[off:off + size]))


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


def patch_font_name(in_path, out_path):
    ver, ic, reserved, code, args, strs, lines = read_ystb(in_path)
    slices = arg_slices(code, args)

    if ic <= max(TARGET_INSTRUCTIONS):
        raise RuntimeError(f"{in_path} has only {ic} instructions")

    start_20, _ = slices[20]
    draw_name = first_arg_literal(args, strs, start_20)
    if draw_name != "es._txfont" and code[20 * 4] != 0x31:
        raise RuntimeError(f"instruction 20 mismatch: got {draw_name!r}")

    start_52, _ = slices[52]
    func_name = first_arg_literal(args, strs, start_52)
    if func_name != "es.FONT.NAME.GET" and code[52 * 4] != 0x31:
        raise RuntimeError(f"instruction 52 mismatch: got {func_name!r}")

    new_args = bytearray()
    patched = []
    for i in range(ic):
        start, end = slices[i]
        if i in TARGET_INSTRUCTIONS:
            op = code[i * 4]
            argc = code[i * 4 + 1]
            if op == 0x31 and argc == 0:
                patched.append((i, "already noop"))
            else:
                code[i * 4:i * 4 + 4] = b"\x31\x00\x00\x00"
                patched.append((i, f"op {op:02x}/argc {argc} -> noop"))
            continue
        new_args.extend(args[start:end])

    write_ystb(out_path, ver, ic, reserved, code, new_args, strs, lines)
    for idx, action in patched:
        print(f"{idx}: {action}")
    print(f"patched {out_path}: instruction count unchanged ({ic})")


def main(argv):
    if len(argv) != 3:
        print(f"usage: patch_config_font_name.py <input {TARGET_SCRIPT}> <output {TARGET_SCRIPT}>")
        return 1
    patch_font_name(argv[1], argv[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
