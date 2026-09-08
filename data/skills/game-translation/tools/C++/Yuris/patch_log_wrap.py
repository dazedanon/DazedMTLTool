"""Backlog-only text cleanup patch for yst00028.ybn.

The dialogue packer uses short runs of spaces to make the main textbox wrap at
safe word boundaries. The backlog renderer has a separate LOG.MES/LOGTX path,
so those padding spaces show up as visible gaps.

Important: do not insert bytecode instructions here. YU-RIS compiled scripts
use instruction indexes in branch expressions, and shifting indexes broke game
startup. This patch replaces existing no-op instructions with calls and inserts
only their argument records at the matching arg-stream positions, preserving the
instruction count, code size, line table size, and all instruction indexes.
"""
import os
import struct
import sys

KEY = bytes.fromhex("605e414a")

# Existing no-op instruction indexes in yst00028.
# 805/806 are after LOG.MES.OF is populated in the first path.
# 831/832 are after LOG.MES.OV is populated in the second path before draw.
# The main dialogue renderer uses these spaces to trigger its own wrapping.
# The backlog renderer shows them literally, so convert them to line breaks
# only inside LOG.MES.*.
REPLACEMENTS = {
    805: (798, "    ", "\n"),
    806: (798, "   ", "\n"),
    831: (817, "    ", "\n"),
    832: (817, "   ", "\n"),
}


def xor_apply(data):
    return bytes(b ^ KEY[i & 3] for i, b in enumerate(data))


def m_literal(text):
    raw = text.encode("cp932")
    return b"M" + struct.pack("<H", len(raw) + 2) + b'"' + raw + b'"'


def first_literal(expr):
    if len(expr) < 5 or expr[0] != 0x4D:
        return None
    n = struct.unpack("<H", expr[1:3])[0]
    if len(expr) < 3 + n or expr[3] != 0x22 or expr[2 + n] != 0x22:
        return None
    try:
        return expr[4:2 + n].decode("cp932")
    except UnicodeDecodeError:
        return None


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


def append_arg(strs, arg_blob, atype, payload):
    off = len(strs)
    strs.extend(payload)
    arg_blob.extend(struct.pack("<3I", atype, len(payload), off))


def strreplace_args(strs, target_expr, old, new):
    args = bytearray()
    append_arg(strs, args, 0x00030000, m_literal("es._strreplace"))
    append_arg(strs, args, 0x00030021, target_expr)
    append_arg(strs, args, 0x00030022, m_literal(old))
    append_arg(strs, args, 0x00030023, m_literal(new))
    return bytes(args)


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


def first_arg_expr(args, strs, start):
    atype, size, off = struct.unpack("<3I", args[start:start + 12])
    if atype != 0x00030000:
        raise ValueError(f"unexpected target arg type {atype:08x}")
    return bytes(strs[off:off + size])


def patch_log_script(in_path, out_path):
    ver, ic, reserved, code, args, strs, lines = read_ystb(in_path)
    slices = arg_slices(code, args)

    target_exprs = {}
    for source_idx in sorted({src for src, _old, _new in REPLACEMENTS.values()}):
        start, end = slices[source_idx]
        target_expr = first_arg_expr(args, strs, start)
        target_name = first_literal(target_expr)
        if target_name not in ("LOG.MES.OF", "LOG.MES.OV"):
            raise RuntimeError(f"target {source_idx} mismatch: got {target_name!r}")
        target_exprs[source_idx] = target_expr

    new_args = bytearray()
    patched = []
    for i in range(ic):
        start, end = slices[i]
        if i in REPLACEMENTS:
            if code[i * 4] != 0x31 or code[i * 4 + 1] != 0:
                raise RuntimeError(f"instruction {i} is no longer a no-op")
            source_idx, old, new = REPLACEMENTS[i]
            call_args = strreplace_args(strs, target_exprs[source_idx], old, new)
            code[i * 4:i * 4 + 4] = bytes([0x2C, 0x04, 0x03, 0x00])
            new_args.extend(call_args)
            patched.append((i, first_literal(target_exprs[source_idx]), old, new))
        else:
            new_args.extend(args[start:end])

    if sorted(i for i, *_ in patched) != sorted(REPLACEMENTS):
        raise RuntimeError(f"missed patch targets: {patched!r}")

    header = struct.pack(
        "<4s7I",
        b"YSTB",
        ver,
        ic,
        len(code),
        len(new_args),
        len(strs),
        len(lines),
        reserved,
    )
    out = header + xor_apply(code) + xor_apply(new_args) + xor_apply(strs) + lines
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(out)

    for idx, target, old, new in patched:
        print(f"{idx}: {target} {old!r}->{new!r}")
    print(f"patched {out_path}: instruction count unchanged ({ic})")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: patch_log_wrap.py <input yst00028.ybn> <output yst00028.ybn>")
        sys.exit(1)
    patch_log_script(sys.argv[1], sys.argv[2])
