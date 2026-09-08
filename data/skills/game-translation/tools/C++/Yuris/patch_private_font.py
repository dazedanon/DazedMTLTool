"""
Hotfix an already-patched EN-mode Elfhime executable so it loads a bundled
private monospace font before CreateFontIndirectA runs.

This intentionally uses the earlier, minimal relative-path loader. The game
must be run normally from an ASCII-only install path, with ElfhimeMono.ttf
beside elfhime.exe.
"""
import os
import shutil
import struct

IMAGE_BASE = 0x400000

CFI_SITE_VA = 0x4443A8
CFI_RETURN_VA = CFI_SITE_VA + 18
PRIVATE_CFI_DETOUR = 0x85AE20

FONT_INIT_FLAG = 0x85AF20
PTR_ADD_FONT_RESOURCE_EX_A = 0x85AF24
STR_ADD_FONT_RESOURCE_EX_A = 0x85AF28
STR_PRIVATE_FONT_FILE = 0x85AF40
STR_PRIVATE_GDI32 = 0x85AF60

IAT = {
    "CreateFontIndirectA": 0x58C030,
    "GetModuleHandleA": 0x58C09C,
    "GetProcAddress": 0x58C214,
}

FONT_FACE = b"DejaVu Sans Mono"
FONT_FILE = b"ElfhimeMono.ttf"
FONT_WEIGHT = 700
FONT_CHARSET = 0x00       # ANSI_CHARSET
FONT_QUALITY = 5          # CLEARTYPE_QUALITY
FR_PRIVATE = 0x10

TARGETS = [
    r"C:\Users\sw\Desktop\Games\Elfhime English\elfhime.exe",
    r"C:\Users\sw\Desktop\Elfhime_translation\shipping\Elfhime\elfhime.exe",
]


def le32(value):
    return struct.pack("<I", value & 0xFFFFFFFF)


def parse_pe(data):
    pe_off = struct.unpack("<I", data[0x3C:0x40])[0]
    nsec = struct.unpack("<H", data[pe_off + 6:pe_off + 8])[0]
    opt_size = struct.unpack("<H", data[pe_off + 0x14:pe_off + 0x16])[0]
    sec_off = pe_off + 0x18 + opt_size
    image_base = struct.unpack("<I", data[pe_off + 0x34:pe_off + 0x38])[0]
    sections = []
    for index in range(nsec):
        s = data[sec_off + index * 40:sec_off + (index + 1) * 40]
        name = s[:8].rstrip(b"\x00").decode(errors="replace")
        vsize, vaddr, rsize, raddr = struct.unpack("<4I", s[8:24])
        sections.append((name, vaddr, vsize, raddr, rsize))
    return image_base, sections


def make_va_to_off(image_base, sections):
    def va2off(va):
        rva = va - image_base
        for _name, vaddr, vsize, raddr, rsize in sections:
            limit = max(vsize, rsize)
            if vaddr <= rva < vaddr + limit:
                return raddr + (rva - vaddr)
        raise ValueError(f"VA 0x{va:x} not in any section")
    return va2off


def patch(data, off, new):
    data[off:off + len(new)] = new


def jmp_rel32(from_va, to_va):
    return b"\xE9" + le32(to_va - (from_va + 5))


def build_detour():
    code = bytearray()
    code += bytes.fromhex("a144155d00")                    # mov eax, [0x5d1544]
    code += bytes.fromhex("8b1485b84a8000")                # mov edx, [eax*4 + 0x804ab8]

    # flag: 0 = not attempted, 1 = bundled font loaded, 2 = use Consolas fallback
    code += b"\x83\x3D" + le32(FONT_INIT_FLAG) + b"\x00"  # cmp dword [flag], 0
    code += b"\x75\x00"; jne_loaded = len(code)           # jne loaded
    code += b"\x52"                                       # push edx
    code += b"\x68" + le32(STR_PRIVATE_GDI32)
    code += b"\xFF\x15" + le32(IAT["GetModuleHandleA"])
    code += b"\x85\xC0"
    code += b"\x74\x00"; jz_load_failed_a = len(code)
    code += b"\x68" + le32(STR_ADD_FONT_RESOURCE_EX_A)
    code += b"\x50"
    code += b"\xFF\x15" + le32(IAT["GetProcAddress"])
    code += b"\xA3" + le32(PTR_ADD_FONT_RESOURCE_EX_A)
    code += b"\x85\xC0"
    code += b"\x74\x00"; jz_load_failed_b = len(code)
    code += b"\x6A\x00"                                   # pv = NULL
    code += b"\x6A" + bytes([FR_PRIVATE])                  # flags = FR_PRIVATE
    code += b"\x68" + le32(STR_PRIVATE_FONT_FILE)
    code += b"\xFF\xD0"                                   # call eax
    code += b"\x85\xC0"                                    # test eax, eax
    code += b"\x74\x00"; jz_load_failed_c = len(code)
    code += b"\xC7\x05" + le32(FONT_INIT_FLAG) + le32(1)
    code += b"\xEB\x00"; jmp_load_done = len(code)
    load_failed_at = len(code)
    code += b"\xC7\x05" + le32(FONT_INIT_FLAG) + le32(2)
    load_done_at = len(code)
    code += b"\x5A"                                       # pop edx
    loaded_at = len(code)

    code += bytes([0xC7, 0x42, 0x10]) + le32(FONT_WEIGHT)
    code += bytes([0xC6, 0x42, 0x17, FONT_CHARSET])
    code += bytes([0xC6, 0x42, 0x1A, FONT_QUALITY])
    face = (FONT_FACE + b"\x00" * 32)[:32]
    fallback_face = (b"Consolas" + b"\x00" * 32)[:32]
    code += b"\x83\x3D" + le32(FONT_INIT_FLAG) + b"\x02"  # cmp dword [flag], 2
    code += b"\x74\x00"; je_fallback_face = len(code)
    for index in range(0, 32, 4):
        code += bytes([0xC7, 0x42, 0x1C + index]) + face[index:index + 4]
    code += b"\xEB\x00"; jmp_face_done = len(code)
    fallback_face_at = len(code)
    for index in range(0, 32, 4):
        code += bytes([0xC7, 0x42, 0x1C + index]) + fallback_face[index:index + 4]
    face_done_at = len(code)

    code += b"\x52"
    code += b"\xFF\x15" + le32(IAT["CreateFontIndirectA"])
    code += jmp_rel32(PRIVATE_CFI_DETOUR + len(code), CFI_RETURN_VA)

    code[jne_loaded - 1] = (loaded_at - jne_loaded) & 0xFF
    code[jz_load_failed_a - 1] = (load_failed_at - jz_load_failed_a) & 0xFF
    code[jz_load_failed_b - 1] = (load_failed_at - jz_load_failed_b) & 0xFF
    code[jz_load_failed_c - 1] = (load_failed_at - jz_load_failed_c) & 0xFF
    code[jmp_load_done - 1] = (load_done_at - jmp_load_done) & 0xFF
    code[je_fallback_face - 1] = (fallback_face_at - je_fallback_face) & 0xFF
    code[jmp_face_done - 1] = (face_done_at - jmp_face_done) & 0xFF

    if len(code) > 0x100:
        raise RuntimeError(f"private font detour too large: {len(code)} bytes")
    return bytes(code)


def patch_exe(path):
    with open(path, "rb") as f:
        data = bytearray(f.read())
    image_base, sections = parse_pe(data)
    if image_base != IMAGE_BASE:
        raise RuntimeError(f"{path}: unexpected image base 0x{image_base:x}")
    va2off = make_va_to_off(image_base, sections)

    site_off = va2off(CFI_SITE_VA)
    existing = bytes(data[site_off:site_off + 18])
    if existing.startswith(b"\xE9"):
        pass
    elif existing == bytes.fromhex("a144155d00ff3485b84a8000ff1530c05800"):
        pass
    else:
        raise RuntimeError(f"{path}: unexpected CreateFontIndirectA site bytes: {existing.hex()}")

    backup = path + ".pre_custom_font_en.bak"
    make_backup = "\\shipping\\" not in path.lower()
    if make_backup and not os.path.exists(backup):
        shutil.copy(path, backup)

    patch(data, site_off, jmp_rel32(CFI_SITE_VA, PRIVATE_CFI_DETOUR) + b"\x90" * 13)
    patch(data, va2off(PRIVATE_CFI_DETOUR), build_detour())
    patch(data, va2off(FONT_INIT_FLAG), b"\x00" * 8)
    patch(data, va2off(STR_ADD_FONT_RESOURCE_EX_A), b"AddFontResourceExA\x00")
    patch(data, va2off(STR_PRIVATE_FONT_FILE), FONT_FILE + b"\x00")
    patch(data, va2off(STR_PRIVATE_GDI32), b"gdi32.dll\x00")

    with open(path, "wb") as f:
        f.write(data)
    print(f"patched private font hook -> {path}")


def main():
    for target in TARGETS:
        if not os.path.exists(target):
            raise FileNotFoundError(target)
        patch_exe(target)


if __name__ == "__main__":
    main()
