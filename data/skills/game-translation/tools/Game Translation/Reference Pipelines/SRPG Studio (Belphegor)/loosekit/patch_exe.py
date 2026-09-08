#!/usr/bin/env python3
r"""Patch a stock Belphegor game.exe into the full loose-translation build.

One pass over the unmodified v1.23 exe applies every edit:

  P1  stability   - never force-quit on a momentarily-missing resource.
  P2  loose code  - load loose Script\/Plugin\ *.js over the data.dts copies.
  P3  loose db    - load a loose project.dat over the one in data.dts (kept for
                    completeness; the live build translates via P5b instead).
  P5b translate   - read the editable Project\ folder at runtime and translate
                    every database string JP->EN at parse time (no translation.bin).
  P6  loose font  - load loose Fonts\<name>.ttf over the embedded (broken) font.
  P7  window title- set the OS window caption from Project\titles.json (windowTitle
                    en -> jp -> engine original); nothing game-specific is baked in.
  P8  loose fontSize - apply Project\fonts.json fontSize edits at font-system init
                    (the one non-string DB field; read live, no loose project.dat).

Only the exe changes; data.dts stays the original Japanese and the loose files do
the translating. Needs probe.bin + load_table.bin + apply_fontsize.bin + apply_title.bin
next to this script.

    python patch_exe.py game.exe.orig.bak -o game.exe
"""
import argparse, hashlib, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
STOCK_SHA = "afd79d5bbfd4d95d0650987b101a203ea8c38e8f671bc2134a144a8ca37213e6"

# ---- section / cave addresses (imagebase 0x400000) ----
PERCAVE_VA = 0x4A8620                 # P2 cave, in .text padding (file 0xA7A20)
MOD_RVA, MOD_RAW = 0x157000, 0x153000  # P3 .mod section (== stock file size)
MTL_VA, MTL_RVA = 0x558000, 0x158000   # P5b/P6/P7/P8 .mtl section (0x2000)
MTL_SIZE = 0x2000
FONT_VA = 0x5581B8
STUB_VA = 0x558300
STUB_LEN = 0xD7
STUB8_LEN = 0x81                      # P8 fontSize stub (fixed-length)
STUB7_LEN = 0x8D                      # P7 title stub (fixed-length)

def le32(x): return struct.pack("<i", x if x < 0x80000000 else x - 0x100000000) if x < 0 else struct.pack("<I", x & 0xFFFFFFFF)
def rel(src, dst): return struct.pack("<i", dst - (src + 5))

# P2 loose Script/Plugin replace-loader, assembled for PERCAVE_VA
PERCAVE = bytes.fromhex(
    "56525181ec2004000089e6e800000000582d30864a00898614040000837f14000f84"
    "0b0000008d88ccfd4b00e9060000008d88dcfd4b0089c28b82f41a4e0005e8080000"
    "ff770c51508d8284d14b005056ff92d8924a0083c4148b961404000056ff92d8904a"
    "0083f8ff0f840e00000081c420040000595a5ee916dcfaff81c420040000595a5e85"
    "d20f8405dcfaffe977dbfaff")
# P3 loose project.dat loader, assembled for 0x557000
CAVE2 = bytes.fromhex(
    "81ec2002000089e6e8000000005981e90d7055008d9178705500528b81f41a4e0005"
    "e8080000508d9194d04b00528d0650ff91d8924a0083c4108d0e33d2e8dd40f2ff85"
    "c00f841a0000008b008907c747040000000081c42002000089c209ffe9f5fbeeff81"
    "c4200200008b1733c0837b4401e9e2fbeeff70007200"
    "6f006a006500630074002e006400610074000000")


def expect(d, off, want, what):
    got = bytes(d[off:off + len(want)])
    if got != want:
        sys.exit("refusing: %s at %#x is %s, expected %s (not the stock v1.23 exe)."
                 % (what, off, got.hex(), want.hex()))


def build_mtl():
    """Assemble the whole .mtl section (MTL_SIZE): g_tablebase, the JP->EN probe, the
    font/title caves, and the loose-folder loader (PIC asm stub + compiled blob)."""
    blob = open(os.path.join(HERE, "load_table.bin"), "rb").read()
    probe = open(os.path.join(HERE, "probe.bin"), "rb").read()
    font8 = open(os.path.join(HERE, "apply_fontsize.bin"), "rb").read()
    title8 = open(os.path.join(HERE, "apply_title.bin"), "rb").read()
    BLOB_VA = (STUB_VA + STUB_LEN + 15) & ~15
    STR_VA = (BLOB_VA + len(blob) + 3) & ~3

    # P6 font cave
    fc = bytearray()
    fc += bytes([0x81, 0xEC, 0x20, 0x04, 0, 0]) + bytes([0x89, 0x8C, 0x24, 0x10, 0x04, 0, 0])
    fc += bytes([0xE8, 0, 0, 0, 0, 0x58, 0x2D]) + le32(FONT_VA + 0x12)
    fc += bytes([0x89, 0x84, 0x24, 0x14, 0x04, 0, 0]) + bytes([0x8B, 0x88, 0xF4, 0x1A, 0x4E, 0])
    fc += bytes([0x81, 0xC1, 0xE8, 0x08, 0, 0]) + bytes([0xFF, 0x73, 0x10, 0x51])
    fc += bytes([0x8D, 0x90]) + le32(FONT_VA + 0x7E) + bytes([0x52, 0x8D, 0x54, 0x24, 0x0C, 0x52])
    fc += bytes([0xFF, 0x90, 0xD8, 0x92, 0x4A, 0, 0x83, 0xC4, 0x10])
    fc += bytes([0x8B, 0xCF, 0xC1, 0xE9, 0x03, 0x51, 0x8D, 0x4C, 0x24, 0x04, 0x51])
    fc += bytes([0xE8]) + rel(FONT_VA + 0x4F, 0x441450) + bytes([0x85, 0xC0, 0x75, 0x1B])
    fc += bytes([0x8B, 0x84, 0x24, 0x14, 0x04, 0, 0]) + bytes([0x8B, 0x80, 0x24, 0x1A, 0x4E, 0])
    fc += bytes([0x8B, 0x8C, 0x24, 0x10, 0x04, 0, 0]) + bytes([0x89, 0x74, 0x07, 0x04, 0x89, 0x0C, 0x07])
    fc += bytes([0x81, 0xC4, 0x20, 0x04, 0, 0]) + bytes([0xE9]) + rel(FONT_VA + 0x79, 0x4024AA)
    fc += "%s\\Fonts\\%s.ttf\x00".encode("utf-16-le")
    assert len(fc) == 0x9E, hex(len(fc))

    # P5b loader strings
    def w(s): return s.encode("utf-16-le") + b"\x00\x00"
    strings = [("fmt_star", w("%s\\*")), ("fmt_child", w("%s\\%s")),
               ("jpkey", b'"jp": "\x00'), ("enkey", b'"en": "\x00'),
               ("rootname", w("Project"))]
    sva, cur = {}, STR_VA
    for k, v in strings:
        sva[k] = cur
        cur += len(v)

    # P5b stub: fill the imports struct (Imp, 0x4C) and call the blob
    IAT = [0x4a9230, 0x4a9090, 0x4a91b8, 0x4a91f8, 0x4a91ec, 0x4a91d8,
           0x4a9110, 0x4a91bc, 0x4a9080, 0x4a908c, 0x4a92d8, 0x4a90dc]
    SF = [(0x38, "fmt_star"), (0x3C, "fmt_child"), (0x40, "jpkey"),
          (0x44, "enkey"), (0x48, "rootname")]
    s = bytearray([0xE8, 0, 0, 0, 0, 0x5F, 0x81, 0xEF]) + le32(STUB_VA + 5)
    s += bytes([0x81, 0xEC, 0x50, 0, 0, 0, 0x8B, 0xCC])
    for i, slot in enumerate(IAT):
        s += bytes([0x8B, 0x87]) + le32(slot) + bytes([0x89, 0x41, i * 4])
    s += bytes([0x8B, 0x87]) + le32(0x4E1AF4) + bytes([0x05, 0xE8, 0x08, 0, 0, 0x89, 0x41, 0x30])
    s += bytes([0x8D, 0x87]) + le32(0x558000) + bytes([0x89, 0x41, 0x34])
    for off, key in SF:
        s += bytes([0x8D, 0x87]) + le32(sva[key]) + bytes([0x89, 0x41, off])
    s += bytes([0x51, 0xE8]) + rel(STUB_VA + len(s) + 1, BLOB_VA)
    s += bytes([0x81, 0xC4, 0x50, 0, 0, 0, 0x8B, 0x87]) + le32(0x558000) + bytes([0xC3])
    assert len(s) == STUB_LEN, hex(len(s))

    # P8 fontSize override: blob + stub + path string, laid after the P5b strings.
    FONTBLOB8_VA = (cur + 15) & ~15
    STUB8_VA = (FONTBLOB8_VA + len(font8) + 3) & ~3
    FMTPATH8_VA = (STUB8_VA + STUB8_LEN + 1) & ~1
    fmtpath8 = "%s\\Project\\fonts.json\x00".encode("utf-16-le")
    end8 = FMTPATH8_VA + len(fmtpath8)

    IAT8 = [0x4a9090, 0x4a9230, 0x4a91b8, 0x4a9110, 0x4a91bc, 0x4a9080, 0x4a908c, 0x4a92d8]
    s8 = bytearray([0x60])                                       # pushad
    s8 += bytes([0xE8, 0, 0, 0, 0, 0x5F, 0x81, 0xEF]) + le32(STUB8_VA + 6)  # call$+5;pop edi;sub edi,delta
    s8 += bytes([0x83, 0xEC, 0x28, 0x8B, 0xCC])                  # sub esp,0x28 (Imp); mov ecx,esp
    for i, slot in enumerate(IAT8):
        s8 += bytes([0x8B, 0x87]) + le32(slot) + bytes([0x89, 0x41, i * 4])
    s8 += bytes([0x8B, 0x87]) + le32(0x4E1AF4) + bytes([0x89, 0x41, 0x20])   # cfg = *(dword_4E1AF4)
    s8 += bytes([0x8D, 0x87]) + le32(FMTPATH8_VA) + bytes([0x89, 0x41, 0x24])  # fmt_path
    s8 += bytes([0x51])                                          # push ecx (&Imp)
    s8 += bytes([0xE8]) + rel(STUB8_VA + len(s8), FONTBLOB8_VA)  # call apply_fontsize
    s8 += bytes([0x83, 0xC4, 0x28, 0x61])                        # add esp,0x28; popad
    s8 += bytes([0x8B, 0x80, 0x08, 0x05, 0, 0])                  # mov eax,[eax+508h] (displaced)
    s8 += bytes([0xE9]) + rel(STUB8_VA + len(s8), 0x402192)      # jmp back
    assert len(s8) == STUB8_LEN, hex(len(s8))

    # P7 live title: read windowTitle from titles.json (replaces the baked string).
    # blob + stub + path string + a persistent UTF-16 out-buffer the stub returns.
    TITLEBLOB_VA = (end8 + 15) & ~15
    STUB7_VA = (TITLEBLOB_VA + len(title8) + 3) & ~3
    FMTPATH7_VA = (STUB7_VA + STUB7_LEN + 1) & ~1
    fmtpath7 = "%s\\Project\\titles.json\x00".encode("utf-16-le")
    OUTBUF7_VA = (FMTPATH7_VA + len(fmtpath7) + 1) & ~1
    end7 = OUTBUF7_VA + 0x200

    IAT7 = [0x4a9090, 0x4a9230, 0x4a91b8, 0x4a9110, 0x4a91bc, 0x4a9080, 0x4a908c, 0x4a92d8, 0x4a90dc]
    s7 = bytearray([0x60])                                       # pushad (saved eax @ [esp+0x1C])
    s7 += bytes([0xE8, 0, 0, 0, 0, 0x5E, 0x81, 0xEE]) + le32(STUB7_VA + 6)  # call$+5;pop esi;sub esi,delta
    s7 += bytes([0x83, 0xEC, 0x30, 0x8B, 0xCC])                  # sub esp,0x30 (Imp); mov ecx,esp
    for i, slot in enumerate(IAT7):
        s7 += bytes([0x8B, 0x86]) + le32(slot) + bytes([0x89, 0x41, i * 4])
    s7 += bytes([0x8B, 0x86]) + le32(0x4E1AF4) + bytes([0x89, 0x41, 0x24])   # cfg = *(dword_4E1AF4)
    s7 += bytes([0x8D, 0x86]) + le32(FMTPATH7_VA) + bytes([0x89, 0x41, 0x28])  # fmt_path
    s7 += bytes([0x8D, 0x86]) + le32(OUTBUF7_VA) + bytes([0x89, 0x41, 0x2C])   # outbuf
    s7 += bytes([0x51])                                          # push ecx (&Imp)
    s7 += bytes([0xE8]) + rel(STUB7_VA + len(s7), TITLEBLOB_VA)  # call resolve_title -> eax
    s7 += bytes([0x83, 0xC4, 0x30])                             # add esp,0x30
    s7 += bytes([0x89, 0x44, 0x24, 0x1C])                       # mov [esp+0x1C],eax (overwrite saved eax)
    s7 += bytes([0x61, 0xC3])                                   # popad (eax=result); ret
    assert len(s7) == STUB7_LEN, hex(len(s7))

    # lay it all out
    body = bytearray(MTL_SIZE)
    def put(va, b): body[va - MTL_VA:va - MTL_VA + len(b)] = b
    put(0x558008, probe)
    put(FONT_VA, fc)
    put(STUB_VA, s)
    put(BLOB_VA, blob)
    for k, v in strings:
        put(sva[k], v)
    put(FONTBLOB8_VA, font8)
    put(STUB8_VA, s8)
    put(FMTPATH8_VA, fmtpath8)
    put(TITLEBLOB_VA, title8)
    put(STUB7_VA, s7)
    put(FMTPATH7_VA, fmtpath7)
    assert end7 <= MTL_VA + MTL_SIZE, "overflow"
    return bytes(body), STUB8_VA, STUB7_VA


def add_section(d, name, rva, raw, body, chars):
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    sectab = e + 24 + optsz
    falign = struct.unpack_from("<I", d, e + 24 + 36)[0]
    salign = struct.unpack_from("<I", d, e + 24 + 32)[0]
    if len(d) != raw:
        sys.exit("refusing: file ends at %#x, expected %#x." % (len(d), raw))
    hdr = sectab + nsec * 40
    rs = (len(body) + falign - 1) // falign * falign
    struct.pack_into("<8sIIIIIIHHI", d, hdr, name, len(body), rva, rs, raw, 0, 0, 0, 0, chars)
    struct.pack_into("<H", d, e + 6, nsec + 1)
    struct.pack_into("<I", d, e + 24 + 56, rva + (len(body) + salign - 1) // salign * salign)
    d += body + b"\x00" * (rs - len(body))


def kill_reloc(d, target_rva):
    """Neutralize the base-reloc over target_rva (the font trampoline reuses bytes
    that the original mov eax,lpMem's absolute operand was relocated through)."""
    e = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, e + 6)[0]
    optsz = struct.unpack_from("<H", d, e + 20)[0]
    st = e + 24 + optsz
    for i in range(nsec):
        o = st + i * 40
        if d[o:o + 8].rstrip(b"\0") == b".reloc":
            vsz, _va, _rs, prd = struct.unpack_from("<IIII", d, o + 8)
            p, end = prd, prd + vsz
            while p < end:
                page, bs = struct.unpack_from("<II", d, p)
                if bs == 0:
                    break
                for k in range((bs - 8) // 2):
                    eo = p + 8 + k * 2
                    ent = struct.unpack_from("<H", d, eo)[0]
                    if (ent >> 12) == 3 and page + (ent & 0xFFF) == target_rva:
                        struct.pack_into("<H", d, eo, 0)
                        return
                p += bs
    sys.exit("refusing: base-reloc for RVA %#x not found." % target_rva)


def patch(data):
    d = bytearray(data)

    # P1 stability
    expect(d, 0x38D86, bytes.fromhex("83f9ff75058d4102eb0733c085c90f94c0"), "ResourceErrorNotify")
    d[0x38D86:0x38D86 + 17] = b"\x33\xC0" + b"\x90" * 15

    # P2 loose Script/Plugin
    expect(d, 0xA7A20, b"\x00" * len(PERCAVE), "Script-cave padding")
    d[0xA7A20:0xA7A20 + len(PERCAVE)] = PERCAVE
    expect(d, 0x55623, bytes.fromhex("85d20f8489000000"), "Script-loop branch")
    d[0x55623:0x55623 + 8] = b"\xE9" + rel(0x456223, PERCAVE_VA) + b"\x90\x90\x90"

    # P3 loose project.dat (.mod section)
    expect(d, 0x46052, bytes.fromhex("8b1733c0837b4401"), "database-load branch")
    d[0x46052:0x46052 + 8] = b"\xE9" + rel(0x446C52, 0x557000) + b"\x90\x90\x90"
    add_section(d, b".mod", MOD_RVA, MOD_RAW, CAVE2, 0x60000020)

    # P5b/P6/P7/P8 (.mtl section + trampolines)
    mtl_body, STUB8_VA, STUB7_VA = build_mtl()
    add_section(d, b".mtl", MTL_RVA, 0x153200, mtl_body, 0xE0000020)
    # P5b: db-string reader success return -> the probe
    expect(d, 0x73567, bytes.fromhex("89335f5e5b"), "db-string hook")
    d[0x73567:0x73567 + 5] = b"\xE9" + rel(0x474167, 0x558008)
    # P6: font-table store -> the font cave (+ neutralize its stale reloc)
    expect(d, 0x167A, bytes.fromhex("a1241a4e00"), "font-store hook")
    d[0x167A:0x167A + 5] = b"\xE9" + rel(0x40227A, FONT_VA)
    kill_reloc(d, 0x227B)
    # P7: window caption load -> the live title cave (reads Project\titles.json)
    expect(d, 0x37D67, bytes.fromhex("8b8050020000"), "caption hook")
    d[0x37D67:0x37D67 + 6] = b"\xE8" + rel(0x438967, STUB7_VA) + b"\x90"
    # P8: font-system builder reads config (mov eax,[eax+508h]) -> the fontSize cave
    expect(d, 0x158C, bytes.fromhex("8b8008050000"), "fontsize hook")
    d[0x158C:0x158C + 6] = b"\xE9" + rel(0x40218C, STUB8_VA) + b"\x90"
    return bytes(d)


def main():
    ap = argparse.ArgumentParser(description="Patch game.exe into the full loose build.")
    ap.add_argument("exe", nargs="?", default="game.exe.orig.bak")
    ap.add_argument("-o", "--out", default="game.exe")
    args = ap.parse_args()
    data = open(args.exe, "rb").read()
    if hashlib.sha256(data).hexdigest() != STOCK_SHA:
        print("warning: input is not the known stock exe; patch sites are still verified.",
              file=sys.stderr)
    out = patch(data)
    open(args.out, "wb").write(out)
    print("patched %s -> %s  (%d bytes, sha %s)"
          % (args.exe, args.out, len(out), hashlib.sha256(out).hexdigest()[:16]))


if __name__ == "__main__":
    main()
