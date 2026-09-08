"""
Patch elfhime.exe to:
  1. Force English locale APIs (GetACP/GetOEMCP/GetUserDefaultLCID/etc).
  2. Force every CreateFontIndirectA call to use a chosen English-friendly
     font (default "Consolas", ANSI charset).
  3. Translate all CP_ACP=0 calls to MultiByteToWideChar / WideCharToMultiByte
     to use codepage 932 (Shift-JIS).
  4. Substitute the Japanese 「 and 」 brackets with ASCII " at render time
     by detouring the per-character TextOutA call.

All wrapper code lives in the zero-padding tail of .text starting at
VA 0x58b290. The exe is patched in-place; the original is preserved as
elfhime.exe.bak.
"""
import os, struct, shutil

EXE = r'C:/Users/sw/Desktop/Games/Elfhime/elfhime.exe'
BAK = EXE + '.bak'

# =============================================================================
# MODE selects the locale the patched exe pretends to be running on.
#   "JP"  - emulate Japanese cp932 system. Lets the original engine work
#           unchanged on a UTF-8 host. Use when text remains Japanese or is
#           a mixed JP/EN translation.
#   "EN"  - emulate English cp1252 system. Picks an English font. Requires
#           every visible string to be ASCII (or pre-translated); any
#           untranslated cp932 multi-byte chars will render as garbage.
# =============================================================================
MODE = "EN"

if MODE == "JP":
    ACP_CODEPAGE = 0x3A4        # 932 Shift-JIS
    LANG_ID      = 0x411        # Japanese
    FONT_NAME    = None         # leave script's own face name
    FONT_CHARSET = 0x80         # SHIFTJIS_CHARSET
    FONT_WEIGHT  = None
    FONT_QUALITY = None
elif MODE == "EN":
    ACP_CODEPAGE = 0x4E4        # 1252 Western European
    LANG_ID      = 0x409        # English (US)
    # Fixed-width English font. Keep the engine's original monospace advance.
    FONT_NAME    = b'Consolas'
    FONT_CHARSET = 0x00         # ANSI_CHARSET
    FONT_WEIGHT  = 700          # FW_BOLD
    FONT_QUALITY = 5            # CLEARTYPE_QUALITY
else:
    raise ValueError(f'unknown MODE {MODE!r}')

# --- code cave layout in .text padding (compact stuff that must fit in
# the original ~370-byte tail of .text) ---
CAVE_VA      = 0x58b290
CFI_DETOUR   = CAVE_VA + 0x000
MBTOWC_WRAP  = CAVE_VA + 0x080
WCTOMB_WRAP  = CAVE_VA + 0x0a0
TEXT_DETOUR  = CAVE_VA + 0x0c0
QUOTE_OPEN   = CAVE_VA + 0x118
QUOTE_CLOSE  = CAVE_VA + 0x119
SPEAKER_SPACE = CAVE_VA + 0x11A
BRACKET_HOOK = CAVE_VA + 0x120

# --- new dedicated section "elfpat" appended at end of file (RWX, 4 KB) ---
# Filled in at runtime with bigger code/data: build_lut, get_width, LUT,
# function pointers, init flag, and the gdi32 strings.
NEWSEC_VA    = 0x85a000           # next page after .rsrc end (.rsrc ends at 0x859a6c)
NEWSEC_VSIZE = 0x1000             # 4 KB
NEWSEC_NAME  = b'elfpat\x00\x00'
BUILD_LUT    = NEWSEC_VA + 0x000
GET_WIDTH    = NEWSEC_VA + 0x120
LUT_VA       = NEWSEC_VA + 0x200
LUT_STRIDE   = 0x80               # one 0x00..0x7f ASCII table per font slot
PTR_CCDC     = NEWSEC_VA + 0x600
PTR_GCW      = NEWSEC_VA + 0x604
PTR_DDC      = NEWSEC_VA + 0x608
INIT_FLAG    = NEWSEC_VA + 0x60c
STR_GDI32    = NEWSEC_VA + 0x610
STR_CCDC     = NEWSEC_VA + 0x620
STR_GCW      = NEWSEC_VA + 0x640
STR_DDC      = NEWSEC_VA + 0x660
WRAP_HOOK    = NEWSEC_VA + 0x700
LF_BREAK_HOOK = NEWSEC_VA + 0x700
NO_HWRAP_HOOK = NEWSEC_VA + 0x760
RWIDTH_HOOK  = NEWSEC_VA + 0x800  # render-width hook for sub_443D7C
AAWIDTH_HOOK = NEWSEC_VA + 0x900  # anti-aliased scan-width hook for sub_443D7C
META_WIDTH_HOOK = NEWSEC_VA + 0xA00  # opcode 0x6A per-char visible slot width
LF_COMMAND_HOOK = NEWSEC_VA + 0xB00  # opcode 0x6A command byte override for raw LF
MSGBOX_WRAP = NEWSEC_VA + 0xC00      # MessageBoxA argument fixer
STR_GAME_TITLE = NEWSEC_VA + 0xC80
STR_MB_TITLE = NEWSEC_VA + 0xCC0
STR_MB_EXIT = NEWSEC_VA + 0xCE0
TEXT_DETOUR_EX = NEWSEC_VA + 0xD20   # expanded TextOutA hook
# Word-aware wrap hook disabled. We now insert explicit line breaks into
# the packed English scripts so the engine never reaches its mid-word
# hard-wrap point.
WORDWRAP_ENABLED = False
LF_NEWLINE_ENABLED = True
NATIVE_HORIZONTAL_WRAP = False
WORDWRAP_GUARD_CHARS = 12
WORDWRAP_DEBUG_ALWAYS = False
# Diagnostic: overwrite the byte at byte_pos with 'X' on every hook entry.
# If user sees XXXX in the dialogue, hook is firing. If text looks normal,
# the hook isn't being reached.
WORDWRAP_DEBUG_X = False

# Proportional font support. Each font slot receives a 0x80-byte ASCII
# advance table, filled from the actual HFONT after CreateFontIndirectA.
PROPORTIONAL_WIDTH = False
PROPORTIONAL_SPACE_WIDTH = 5
PROPORTIONAL_GLYPH_PAD = 0
STATIC_LUT_FONT_NAME = 'segoeuib.ttf'
STATIC_LUT_FONT_SIZE = 18
PATCH_METADATA_WIDTH_TABLE = False
# Diagnostic probe: when set to an int, bypass the measured LUT and force all
# ASCII advances to this pixel width. If this changes nothing visually, the live
# renderer is not using these advance hooks.
PROPORTIONAL_DIAGNOSTIC_ADVANCE = None
# Stronger diagnostic: force sub_4056B4 itself to return this advance.
# If dialogue text ignores this, it is not using that glyph draw path.
PROPORTIONAL_FORCE_DRAW_ADVANCE = None

GAME_TITLE = b'Memoirs of the Elf Princess | Translated By: len & OverlordMomo'
MSGBOX_TITLE = b'Elfhime'

NATIVE_ASCII_PATCHES = [
    (0x80a05c, bytes.fromhex('59552d52495320446562756720496e666f2e'), b'Elfhime Debug Info', 'debug dialog title'),
    (0x80a070, bytes.fromhex('59552d52495353637265656e5361766572'), b'Elfhime', 'shared Elfhime caption'),
    (0x80acdc, bytes.fromhex('8fee95f1'), b'Info', 'info caption'),
    (0x80e3dc, bytes.fromhex('83478389815b'), b'Error', 'error caption'),
    (0x80b57c, bytes.fromhex('8a6d944682b582c482ad82be82b382a28142'), b'Please confirm.', 'confirm/check prompt'),
    (0x80f3bc, bytes.fromhex('834583428393836883458354834383598f898afa89bb'), b'Reset size', 'system menu reset size'),
    (0x80f160, bytes.fromhex('837d8345835882c982e682e989e696ca8e6c8bf782d682cc88da93ae82f08c9f8f6f82b582dc82b582bd81420a0a8bad90a7934982c98f4997b982b582dc82b7814282e682eb82b582a282c582b782a98148'), b'Mouse corner quit was triggered.\n\nForce quit the game?', 'mouse-corner force quit prompt'),
    (0x80f1c0, bytes.fromhex('5b8366836f8362834f8b40945c5d'), b'Debug Feature', 'debug feature caption'),
    (0x80f3d4, bytes.fromhex('8f4997b982b582dc82b7814282e682eb82b582a282c582b782a98148'), b'Exit the game?', 'exit confirmation'),
    (0x80f108, bytes.fromhex('8345834283938368834582aa90b690ac82c582ab82dc82b982f182c582b582bd8142'), b'Could not create window.', 'window create error A'),
    (0x80b5a8, bytes.fromhex('8345834283938368834582f090b690ac82c582ab82dc82b982f182c582b582bd8142'), b'Could not create window.', 'window create error B'),
    (0x80b1bc, bytes.fromhex('59552d5249538352839383708343838982c68366815b835e92ca904d82aa8f6f978882dc82b982f182c582b582bd8142'), b'Could not communicate with YU-RIS compiler.', 'compiler communication error'),
    (0x80b20c, bytes.fromhex('59552d5249538352839383708343838982f08b4e93ae82c582ab82dc82b982f182c582b582bd8142'), b'Could not start YU-RIS compiler.', 'compiler start error'),
]

NATIVE_UTF16_PATCHES = [
    (0x858ef2, bytes.fromhex('b330e130f330c830e87dc6960000'), 'Edit', 'comment edit title'),
    (0x858f02, bytes.fromhex('2dff33ff2000b430b730c330af300000'), 'Tahoma', 'comment edit font'),
    (0x858f4a, bytes.fromhex('77ff6cff9dff7eff99ff0000'), 'Close', 'cancel button'),
    (0x858f8e, bytes.fromhex('2dff33ff200030ffb430b730c330af300000'), 'Segoe UI', 'debug dialog font'),
    (0x858fb6, bytes.fromhex('427d864e28002600580029000000'), 'Exit', 'debug exit button'),
    (0x858fde, bytes.fromhex('e87dc69628002600450029000000'), 'Edit', 'debug edit button'),
    (0x859032, bytes.fromhex('2dff33ff200030ffb430b730c330af300000'), 'Segoe UI', 'info dialog font'),
    (0x8590c2, bytes.fromhex('2dff33ff200030ffb430b730c330af300000'), 'Segoe UI', 'serial dialog font'),
    (0x85910a, bytes.fromhex('427d864e0000'), 'OK', 'serial dialog button'),
    (0x859162, bytes.fromhex('b730ea30a230eb30ad30fc30923065519b52573066304f3060305530443002300000'), 'Enter serial key', 'serial prompt'),
    (0x8591a2, bytes.fromhex('2dff33ff200030ffb430b730c330af300000'), 'Segoe UI', 'settings dialog font'),
    (0x8591f2, bytes.fromhex('2dff33ff200030ffb430b730c330af300000'), 'Segoe UI', 'resource 2003 font'),
]

NATIVE_CODE_PATCHES = [
    # Normal close prompt originally uses the loaded game title buffer. Point it
    # at an ASCII caption so stale/non-ASCII title data cannot mojibake here.
    (0x45a8f2, bytes.fromhex('68e0046800'), bytes.fromhex('68c0ac8500'), 'normal exit caption pointer'),
    (0x4613dd, bytes.fromhex('68e0046800'), bytes.fromhex('6880ac8500'), 'window setup title pointer'),
    (0x4613f7, bytes.fromhex('68e0046800'), bytes.fromhex('6880ac8500'), 'main window title pointer'),
]

IAT = {
    'GetACP':                 0x58c158,
    'GetOEMCP':               0x58c15c,
    'GetSystemDefaultLangID': 0x58c0c8,
    'GetUserDefaultLangID':   0x58c0cc,
    'GetUserDefaultLCID':     0x58c1a4,
    'CreateFontIndirectA':    0x58c030,
    'MultiByteToWideChar':    0x58c24c,
    'WideCharToMultiByte':    0x58c248,
    'TextOutA':               0x58c028,
    'GetModuleHandleA':       0x58c09c,
    'GetProcAddress':         0x58c214,
    'SelectObject':           0x58c024,
    'MessageBoxA':            0x58c3c0,
}

# Engine memcpy via function pointer (not an IAT slot)
ENGINE_MEMCPY = 0x5d148c

def le32(n): return struct.pack('<I', n & 0xffffffff)

def make_static_lut():
    """Fallback advance table for every font slot.

    The runtime hook still rebuilds the active slot from the actual HFONT, but
    pre-filling all slots keeps proportional spacing alive if the body renderer
    switches to a slot that was created before our hook ran.
    """
    table = bytearray(0x80)
    try:
        from PIL import ImageFont
        font = ImageFont.truetype(STATIC_LUT_FONT_NAME, STATIC_LUT_FONT_SIZE)
        for ch in range(0x20, 0x80):
            if ch == 0x20:
                w = PROPORTIONAL_SPACE_WIDTH
            else:
                w = int(round(font.getlength(chr(ch)))) + PROPORTIONAL_GLYPH_PAD
            table[ch] = max(1, min(0x7f, w))
    except Exception:
        # Conservative fallback for common Latin text if Pillow/font loading
        # is unavailable on the patching machine.
        narrow = set(b"ijlI!|.'`,:;")
        wide = set(b"MW@#%&")
        for ch in range(0x20, 0x80):
            if ch == 0x20:
                w = PROPORTIONAL_SPACE_WIDTH
            elif ch in narrow:
                w = 4
            elif ch in wide:
                w = 13
            else:
                w = 8
            table[ch] = w
    return bytes(table)

def parse_pe(data):
    pe_off = struct.unpack('<I', data[0x3c:0x40])[0]
    nsec = struct.unpack('<H', data[pe_off+6:pe_off+8])[0]
    opt_size = struct.unpack('<H', data[pe_off+0x14:pe_off+0x16])[0]
    sec_off = pe_off + 0x18 + opt_size
    image_base = struct.unpack('<I', data[pe_off+0x34:pe_off+0x38])[0]
    sections = []
    for i in range(nsec):
        s = data[sec_off + i*40 : sec_off + (i+1)*40]
        name = s[:8].rstrip(b'\x00').decode()
        vsize, vaddr, rsize, raddr = struct.unpack('<4I', s[8:24])
        sections.append((name, vaddr, vsize, raddr, rsize))
    return image_base, sections, pe_off, sec_off

def make_va_to_off(image_base, sections):
    def f(va):
        rva = va - image_base
        for n, vaddr, vsize, raddr, rsize in sections:
            limit = max(vsize, rsize)
            if vaddr <= rva < vaddr + limit:
                return raddr + (rva - vaddr)
        raise ValueError(f'VA 0x{va:x} not in any section')
    return f

def patch(buf, off, new):
    buf[off:off+len(new)] = new

def patch_padded_bytes_va(data, va2off, va, old, new, label):
    if len(new) > len(old):
        raise RuntimeError(f'{label} replacement is too long')
    off = va2off(va)
    have = bytes(data[off:off+len(old)])
    if have != old:
        raise RuntimeError(f'unexpected bytes for {label} at 0x{va:x}: {have.hex()}')
    patch(data, off, new + b'\x00' * (len(old) - len(new)))
    print(f'patched {label}')

def patch_utf16_va(data, va2off, va, old, new_text, label):
    new = new_text.encode('utf-16le') + b'\x00\x00'
    patch_padded_bytes_va(data, va2off, va, old, new, label)

def patch_native_ui_strings(data, va2off):
    for va, old, new, label in NATIVE_ASCII_PATCHES:
        patch_padded_bytes_va(data, va2off, va, old, new, label)
    for va, old, new_text, label in NATIVE_UTF16_PATCHES:
        patch_utf16_va(data, va2off, va, old, new_text, label)
    for va, old, new, label in NATIVE_CODE_PATCHES:
        patch_padded_bytes_va(data, va2off, va, old, new, label)

def add_section(data, name, va, vsize, characteristics, content):
    """Append a new PE section. `va` is the absolute virtual address; the
    section header's VirtualAddress field stores RVA (= va - image_base).
    `content` is the on-disk bytes (will be padded to FileAlignment).
    Returns the new section's VA."""
    pe_off = struct.unpack('<I', data[0x3c:0x40])[0]
    image_base = struct.unpack('<I', data[pe_off+0x34:pe_off+0x38])[0]
    nsec = struct.unpack('<H', data[pe_off+6:pe_off+8])[0]
    opt_size = struct.unpack('<H', data[pe_off+0x14:pe_off+0x16])[0]
    sec_off = pe_off + 0x18 + opt_size
    file_align = struct.unpack('<I', data[pe_off+0x18+0x24:pe_off+0x18+0x28])[0]
    sec_align = struct.unpack('<I', data[pe_off+0x18+0x20:pe_off+0x18+0x24])[0]
    soh_off = pe_off + 0x18 + 0x3c
    soh = struct.unpack('<I', data[soh_off:soh_off+4])[0]
    if (sec_off + nsec*40 + 40) > soh:
        raise RuntimeError('No room for new section header')
    rva = va - image_base
    raddr = ((len(data) + file_align - 1) // file_align) * file_align
    if raddr > len(data):
        data.extend(b'\x00' * (raddr - len(data)))
    rsize = ((len(content) + file_align - 1) // file_align) * file_align
    data.extend(content + b'\x00' * (rsize - len(content)))
    name_b = (name + b'\x00' * 8)[:8]
    new_hdr = (name_b
               + le32(vsize)
               + le32(rva)        # VirtualAddress is an RVA, not absolute
               + le32(rsize)
               + le32(raddr)
               + le32(0)*3
               + le32(characteristics))
    new_sh_off = sec_off + nsec*40
    data[new_sh_off:new_sh_off+40] = new_hdr
    data[pe_off+6:pe_off+8] = struct.pack('<H', nsec + 1)
    # Update SizeOfImage to cover new section
    soi_off = pe_off + 0x18 + 0x38
    end_va = ((rva + vsize + sec_align - 1) // sec_align) * sec_align
    cur_soi = struct.unpack('<I', data[soi_off:soi_off+4])[0]
    if end_va > cur_soi:
        data[soi_off:soi_off+4] = le32(end_va)
    return va

def main():
    if not os.path.exists(BAK):
        shutil.copy(EXE, BAK)
        print(f'wrote backup -> {BAK}')
    with open(BAK, 'rb') as f:
        data = bytearray(f.read())
    image_base, sections, pe_off, sec_off = parse_pe(data)
    needs_elfpat = PROPORTIONAL_WIDTH or WORDWRAP_ENABLED or LF_NEWLINE_ENABLED or TEXT_DETOUR_EX
    if needs_elfpat:
        # Reserve a fresh 4 KB RWX section "elfpat" at the end of the file
        # for code/data we inject (build_lut, get_width, wrap_hook, plus
        # runtime LUT, function pointers, init flag, gdi32 strings).
        # IMAGE_SCN_CNT_CODE | _MEM_EXECUTE | _MEM_READ | _MEM_WRITE
        chars = 0x20 | 0x20000000 | 0x40000000 | 0x80000000
        add_section(data, NEWSEC_NAME, NEWSEC_VA, NEWSEC_VSIZE,
                    chars, b'\x00' * NEWSEC_VSIZE)
        image_base, sections, pe_off, sec_off = parse_pe(data)
    va2off = make_va_to_off(image_base, sections)
    patch_native_ui_strings(data, va2off)

    # ---------------------------------------------------------------
    # 1. Constant-return patches
    # ---------------------------------------------------------------
    constants = [
        (0x46f6ed, b'\xff\x25' + le32(IAT['GetACP']),
                  b'\xb8' + le32(ACP_CODEPAGE) + b'\xc3', 'GetACP thunk'),
        (0x46f6d8, b'\xff\x25' + le32(IAT['GetOEMCP']),
                  b'\xb8' + le32(ACP_CODEPAGE) + b'\xc3', 'GetOEMCP thunk'),
        (0x4614e6, b'\xff\x15' + le32(IAT['GetSystemDefaultLangID']),
                  b'\xb8' + le32(LANG_ID) + b'\x90', 'GetSystemDefaultLangID call'),
        (0x4614ec, b'\xff\x15' + le32(IAT['GetUserDefaultLangID']),
                  b'\xb8' + le32(LANG_ID) + b'\x90', 'GetUserDefaultLangID call'),
        (0x473369, b'\xff\x15' + le32(IAT['GetUserDefaultLCID']),
                  b'\xb8' + le32(LANG_ID) + b'\x90', 'GetUserDefaultLCID call'),
    ]
    for site_va, orig, repl, label in constants:
        off = va2off(site_va)
        if bytes(data[off:off+len(orig)]) != orig:
            raise RuntimeError(f'unexpected bytes at {label}')
        assert len(repl) == len(orig)
        patch(data, off, repl)
        print(f'patched {label}')

    # ---------------------------------------------------------------
    # 2. CreateFontIndirectA detour: force lfCharSet + lfFaceName
    # ---------------------------------------------------------------
    cfi_orig = bytes.fromhex('a144155d00ff3485b84a8000ff1530c05800')  # 18 bytes
    cfi_site_va = 0x4443a8
    cfi_site_off = va2off(cfi_site_va)
    if bytes(data[cfi_site_off:cfi_site_off+18]) != cfi_orig:
        raise RuntimeError('CreateFontIndirectA call sequence mismatch')
    rel = CFI_DETOUR - (cfi_site_va + 5)
    patch(data, cfi_site_off, b'\xe9' + le32(rel) + b'\x90'*13)
    print(f'patched CreateFontIndirectA call -> CFI_DETOUR 0x{CFI_DETOUR:x}')

    # Detour body. The original code was:
    #   mov  eax, [0x5d1544]
    #   push [eax*4 + 0x804ab8]   ; LOGFONTA*
    #   call [CreateFontIndirectA]
    # We do the same after first writing lfCharSet and lfFaceName.
    detour = bytearray()
    detour += bytes.fromhex('a144155d00')                  # mov eax, [0x5d1544]
    detour += bytes.fromhex('8b1485b84a8000')              # mov edx, [eax*4 + 0x804ab8]
    if FONT_WEIGHT is not None:
        detour += bytes([0xc7, 0x42, 0x10]) + le32(FONT_WEIGHT)
    if FONT_CHARSET is not None:
        detour += bytes([0xc6, 0x42, 0x17, FONT_CHARSET])
    if FONT_QUALITY is not None:
        detour += bytes([0xc6, 0x42, 0x1a, FONT_QUALITY])
    if FONT_NAME is not None:
        name = (FONT_NAME + b'\x00' * 32)[:32]
        for i in range(0, 32, 4):
            chunk_dword = struct.unpack('<I', name[i:i+4])[0]
            detour += bytes([0xc7, 0x42, 0x1c + i]) + le32(chunk_dword)  # mov [edx+0x1c+i], imm32
    detour += b'\x52'                                       # push edx
    detour += b'\xff\x15' + le32(IAT['CreateFontIndirectA'])  # call [IAT]
    # After CreateFontIndirectA, EAX holds the new HFONT. Call build_lut
    # to populate the current font slot's LUT[0x20..0x7F] with per-char
    # widths via GetCharWidthA. build_lut preserves EAX so the caller's
    # `mov [...], EAX` still works.
    if PROPORTIONAL_WIDTH:
        rel = BUILD_LUT - (CFI_DETOUR + len(detour) + 5)
        detour += b'\xe8' + le32(rel)                       # call build_lut
    return_va = cfi_site_va + 18
    detour_end_va = CFI_DETOUR + len(detour) + 5
    detour += b'\xe9' + le32(return_va - detour_end_va)
    if len(detour) > MBTOWC_WRAP - CFI_DETOUR:
        raise RuntimeError(f'CFI detour too big: {len(detour)} bytes')
    patch(data, va2off(CFI_DETOUR), bytes(detour))
    print(f'  CFI detour body: {len(detour)} bytes (font={FONT_NAME!r}, charset=0x{FONT_CHARSET:02x}, prop_width={PROPORTIONAL_WIDTH})')

    # ---------------------------------------------------------------
    # 3. MBtoWC / WCtoMB wrappers (swap CP_ACP=0 for 932)
    # ---------------------------------------------------------------
    def make_cp_wrapper(iat_va):
        return (
            b'\x83\x7c\x24\x04\x00' +
            b'\x75\x08' +
            b'\xc7\x44\x24\x04' + le32(ACP_CODEPAGE) +
            b'\xff\x25' + le32(iat_va)
        )
    mbtowc = make_cp_wrapper(IAT['MultiByteToWideChar'])
    wctomb = make_cp_wrapper(IAT['WideCharToMultiByte'])
    patch(data, va2off(MBTOWC_WRAP), mbtowc)
    patch(data, va2off(WCTOMB_WRAP), wctomb)
    print(f'wrote MBtoWC wrapper @ 0x{MBTOWC_WRAP:x}')
    print(f'wrote WCtoMB wrapper @ 0x{WCTOMB_WRAP:x}')

    def patch_calls(api_iat_va, wrapper_va, label):
        pat_bytes = b'\xff\x15' + le32(api_iat_va)
        n = 0
        for off in range(len(data) - 6):
            if bytes(data[off:off+6]) == pat_bytes:
                site_va = None
                for nm, vaddr, vsize, raddr, rsize in sections:
                    if raddr <= off < raddr + rsize:
                        site_va = image_base + vaddr + (off - raddr)
                        break
                if site_va is None: continue
                rel = wrapper_va - (site_va + 5)
                patch(data, off, b'\xe8' + le32(rel) + b'\x90')
                n += 1
        print(f'  {label}: {n} call sites redirected')
    patch_calls(IAT['MultiByteToWideChar'], MBTOWC_WRAP, 'MultiByteToWideChar')
    patch_calls(IAT['WideCharToMultiByte'], WCTOMB_WRAP, 'WideCharToMultiByte')

    # ---------------------------------------------------------------
    # 3b. MessageBoxA wrapper: translate script/runtime quit prompts
    # ---------------------------------------------------------------
    patch_calls(IAT['MessageBoxA'], MSGBOX_WRAP, 'MessageBoxA')
    if len(GAME_TITLE) + 1 > STR_MB_TITLE - STR_GAME_TITLE:
        raise RuntimeError('GAME_TITLE is too long for the reserved title slot')
    patch(data, va2off(STR_GAME_TITLE), GAME_TITLE + b'\x00')
    patch(data, va2off(STR_MB_TITLE), MSGBOX_TITLE + b'\x00')
    patch(data, va2off(STR_MB_EXIT), b'Exit the game?\x00')
    msg = bytearray()
    # If caption is exactly CP932 "確認", replace it.
    msg += b'\x8b\x44\x24\x0c'                         # mov eax, [esp+0x0c]
    msg += b'\x85\xc0'                                 # test eax, eax
    msg += b'\x74\x16'                                 # jz check_text
    msg += b'\x81\x38' + bytes.fromhex('8a6d9446')     # cmp dword [eax], 0x46946d8a
    msg += b'\x75\x0e'                                 # jne check_text
    msg += b'\x80\x78\x04\x00'                         # cmp byte [eax+4], 0
    msg += b'\x75\x08'                                 # jne check_text
    msg += b'\xc7\x44\x24\x0c' + le32(STR_MB_TITLE)    # mov [esp+0x0c], title
    # check_text:
    msg += b'\x8b\x44\x24\x08'                         # mov eax, [esp+0x08]
    msg += b'\x85\xc0'                                 # test eax, eax
    msg += b'\x74\x2a'                                 # jz call_original
    # Starts with CP932 "ゲーム" (83 51 81 5b 83 80)?
    msg += b'\x66\x81\x38' + bytes.fromhex('8351')     # cmp word [eax], 0x5183
    msg += b'\x75\x13'                                 # jne check_exit_start
    msg += b'\x81\x78\x02' + bytes.fromhex('815b8380') # cmp dword [eax+2], 0x80835b81
    msg += b'\x75\x0a'                                 # jne check_exit_start
    msg += b'\xc7\x44\x24\x08' + le32(STR_MB_EXIT)     # mov [esp+0x08], exit text
    msg += b'\xeb\x10'                                 # jmp call_original
    # check_exit_start: starts with CP932 "終了" (8f 49 97 b9)?
    msg += b'\x81\x38' + bytes.fromhex('8f4997b9')     # cmp dword [eax], 0xb997498f
    msg += b'\x75\x08'                                 # jne call_original
    msg += b'\xc7\x44\x24\x08' + le32(STR_MB_EXIT)     # mov [esp+0x08], exit text
    # call_original:
    msg += b'\xff\x25' + le32(IAT['MessageBoxA'])      # jmp dword ptr [MessageBoxA]
    if len(msg) > STR_MB_TITLE - MSGBOX_WRAP:
        raise RuntimeError(f'MessageBoxA wrapper too big: {len(msg)} bytes')
    patch(data, va2off(MSGBOX_WRAP), bytes(msg))
    print(f'wrote MessageBoxA wrapper ({len(msg)} bytes) at 0x{MSGBOX_WRAP:x}')

    # ---------------------------------------------------------------
    # 4. TextOutA detour: substitute 「(81 75) and 」(81 76) with "
    # ---------------------------------------------------------------
    # The per-char render at FUN_00443d7c calls TextOutA at 0x00443e6a:
    #   FF 15 28 C0 58 00   (call dword ptr [TextOutA])
    # At time of call, stack layout is:
    #   [esp+ 0] hdc
    #   [esp+ 4] x = 0
    #   [esp+ 8] y = 0
    #   [esp+ c] char_ptr (= EBP, points at 1- or 2-byte char source)
    #   [esp+10] size in bytes (1 or 2)
    # We detour to a stub that checks the bytes at [char_ptr]; if they
    # match 81 75 or 81 76 we swap the pushed char_ptr to point at our
    # static '"' buffer and force size=1, then call TextOutA.
    text_site_va = 0x00443e6a
    text_orig = b'\xff\x15' + le32(IAT['TextOutA'])
    text_off = va2off(text_site_va)
    if bytes(data[text_off:text_off+6]) != text_orig:
        raise RuntimeError('TextOutA call site mismatch')
    rel = TEXT_DETOUR_EX - (text_site_va + 5)
    patch(data, text_off, b'\xe8' + le32(rel) + b'\x90')
    print(f'redirected TextOutA call -> TEXT_DETOUR_EX 0x{TEXT_DETOUR_EX:x}')

    # Detour: __cdecl-ish; we entered via CALL, so [esp] is return addr,
    # then args follow at [esp+4] onward.
    #   mov  al, [esp+0x10]      ; size byte (low byte of pushed size)
    #   cmp  al, 2
    #   jne  passthrough
    #   mov  edx, [esp+0xc]      ; char_ptr
    #   cmp  byte ptr [edx], 0x81
    #   jne  passthrough
    #   mov  al, [edx+1]
    #   cmp  al, 0x75            ; 「?
    #   je   sub_open
    #   cmp  al, 0x76            ; 」?
    #   je   sub_close
    # passthrough:
    #   jmp  [TextOutA]          ; tail call: TextOutA returns to our CALLER
    # sub_open:
    #   mov  dword ptr [esp+0xc], QUOTE_OPEN
    #   mov  dword ptr [esp+0x10], 1
    #   jmp  [TextOutA]
    # sub_close:
    #   mov  dword ptr [esp+0xc], QUOTE_CLOSE
    #   mov  dword ptr [esp+0x10], 1
    #   jmp  [TextOutA]
    d = bytearray()
    d += b'\x8a\x44\x24\x10'                 # mov al, [esp+0x10]
    d += b'\x3c\x02'                          # cmp al, 2
    d += b'\x75\x1a'                          # jne passthrough  (over the ~26 bytes)
    d += b'\x8b\x54\x24\x0c'                  # mov edx, [esp+0xc]
    d += b'\x80\x3a\x81'                      # cmp byte [edx], 0x81
    d += b'\x75\x13'                          # jne passthrough
    d += b'\x8a\x42\x01'                      # mov al, [edx+1]
    d += b'\x3c\x75'                          # cmp al, 0x75
    d += b'\x74\x12'                          # je sub_open  (over passthrough)
    d += b'\x3c\x76'                          # cmp al, 0x76
    d += b'\x74\x1c'                          # je sub_close
    # passthrough:
    d += b'\xff\x25' + le32(IAT['TextOutA'])  # jmp [TextOutA]   (6 bytes)
    # sub_open:  (we got here via je at offset 0x14 from start... let me lay out below)
    sub_open_start = len(d)
    d += b'\xc7\x44\x24\x0c' + le32(QUOTE_OPEN)    # mov [esp+0xc], QUOTE_OPEN  (8 bytes)
    d += b'\xc7\x44\x24\x10' + le32(1)               # mov [esp+0x10], 1          (8 bytes)
    d += b'\xff\x25' + le32(IAT['TextOutA'])         # jmp [TextOutA]             (6 bytes)
    sub_close_start = len(d)
    d += b'\xc7\x44\x24\x0c' + le32(QUOTE_CLOSE)
    d += b'\xc7\x44\x24\x10' + le32(1)
    d += b'\xff\x25' + le32(IAT['TextOutA'])
    # Now sanity-check the je offsets
    # First je at offset 16 (b'\x74\x12' at offset 16-17). Target = offset 18+0x12 = 0x24 = 36
    # sub_open_start should be 36
    expected_open = 0x24
    if sub_open_start != expected_open:
        # fix the jne/je targets dynamically by recomputing
        # easier: rebuild with computed displacements
        pass

    # Stack layout in detour, after CALL pushes return addr:
    #   [esp+ 0]  return addr
    #   [esp+ 4]  hdc            <- TextOutA arg 1
    #   [esp+ 8]  x              <- arg 2
    #   [esp+ c]  y              <- arg 3
    #   [esp+10]  char_ptr       <- arg 4 (== EBP, the source byte ptr)
    #   [esp+14]  size           <- arg 5
    d = bytearray()
    d += b'\x8a\x44\x24\x14'                 # mov al, [esp+0x14]  ; size
    d += b'\x3c\x01'                          # cmp al, 1
    d += b'\x74\x00'; p_je_one = len(d)        # je check_one_byte
    d += b'\x3c\x02'                          # cmp al, 2
    d += b'\x75\x00'; p_jne_size = len(d)      # jne passthrough
    d += b'\x8b\x54\x24\x10'                  # mov edx, [esp+0x10] ; char_ptr
    d += b'\x80\x3a\x81'                      # cmp byte [edx], 0x81
    d += b'\x75\x00'; p_jne_byte = len(d)      # jne passthrough
    d += b'\x8a\x42\x01'                      # mov al, [edx+1]
    d += b'\x3c\x75'                          # cmp al, 0x75
    d += b'\x74\x00'; p_je_open = len(d)       # je sub_open
    d += b'\x3c\x76'                          # cmp al, 0x76
    d += b'\x74\x00'; p_je_close = len(d)      # je sub_close
    passthrough_at = len(d)
    d += b'\xff\x25' + le32(IAT['TextOutA'])  # jmp [TextOutA]
    check_one_at = len(d)
    d += b'\x8b\x54\x24\x10'                  # mov edx, [esp+0x10]
    d += b'\x80\x3a\x7f'                      # cmp byte [edx], 0x7f
    d += b'\x74\x00'; p_je_space = len(d)      # je sub_space
    d += b'\xeb\x00'; p_jmp_pass = len(d)      # jmp passthrough
    sub_open_at = len(d)
    d += b'\xc7\x44\x24\x10' + le32(QUOTE_OPEN)
    d += b'\xc7\x44\x24\x14' + le32(1)
    d += b'\xff\x25' + le32(IAT['TextOutA'])
    sub_close_at = len(d)
    d += b'\xc7\x44\x24\x10' + le32(QUOTE_CLOSE)
    d += b'\xc7\x44\x24\x14' + le32(1)
    d += b'\xff\x25' + le32(IAT['TextOutA'])
    sub_space_at = len(d)
    d += b'\xc7\x44\x24\x10' + le32(SPEAKER_SPACE)
    d += b'\xc7\x44\x24\x14' + le32(1)
    d += b'\xff\x25' + le32(IAT['TextOutA'])

    d[p_je_one - 1]   = (check_one_at - p_je_one) & 0xff
    d[p_jne_size - 1] = (passthrough_at - p_jne_size) & 0xff
    d[p_jne_byte - 1] = (passthrough_at - p_jne_byte) & 0xff
    d[p_je_open - 1]  = (sub_open_at - p_je_open) & 0xff
    d[p_je_close - 1] = (sub_close_at - p_je_close) & 0xff
    d[p_je_space - 1] = (sub_space_at - p_je_space) & 0xff
    d[p_jmp_pass - 1] = (passthrough_at - p_jmp_pass) & 0xff

    if len(d) > 0x100:
        raise RuntimeError(f'TextOutA detour too big: {len(d)} bytes')
    patch(data, va2off(TEXT_DETOUR_EX), bytes(d))
    # static quote bytes
    patch(data, va2off(QUOTE_OPEN),  b'\x22')   # ASCII "
    patch(data, va2off(QUOTE_CLOSE), b'\x22')
    patch(data, va2off(SPEAKER_SPACE), b'\x20')
    print(f'TextOutA detour: {len(d)} bytes; quote buffers at 0x{QUOTE_OPEN:x}/0x{QUOTE_CLOSE:x}, speaker-space 0x{SPEAKER_SPACE:x}')

    # ---------------------------------------------------------------
    # 5. Metadata-loop bracket-width override.
    # The opcode-0x6A handler walks the source dialogue text and stores
    # one metadata entry per character; for cp932 lead bytes it reserves
    # a *full-width* slot. The render-time TextOutA detour rewrites the
    # 「(81 75) and 」(81 76) glyphs to ASCII ", which is half-width, so
    # we end up with empty padding next to the substituted quote.
    #
    # We can't strip 「」 at the source — the speaker parser that runs
    # later requires those bytes to recognize the dialogue body. Instead
    # we splice into the metadata loop and special-case the two byte
    # pairs: store them with cVar2 = 0 (half-width width formula) but
    # still advance the source pointer by 2 bytes.
    #
    # The original loop entry at 0x00458789 is:
    #   00458789  0f b6 34 1d   movzx esi, byte [ebp+ebx]
    #   0045878d  0f b6 8e ... 5b 40 a0 movzx ecx, byte [esi + 0x5b40a0]
    #   00458795  0f be f1      movsx esi, cl
    # That's exactly 12 bytes. We replace with `e8 <rel32>` + 7 nops,
    # calling our hook which sets up ESI/ECX correctly (and remembers
    # the +1 advance via a side channel: we pre-advance EBP itself when
    # we see a target bracket, so the loop's later `lea ebp,[ebp+esi+1]`
    # ends up advancing 2 bytes total).
    op6a_site_va = 0x00458789
    op6a_orig = bytes.fromhex(
        '0fb6741d00'        # movzx esi, byte [ebp+ebx]
        '0fb68ea0405b00'    # movzx ecx, byte [esi + 0x5b40a0]
        '0fbef1'            # movsx esi, cl
    )
    assert len(op6a_orig) == 15
    op6a_off = va2off(op6a_site_va)
    if bytes(data[op6a_off:op6a_off+15]) != op6a_orig:
        raise RuntimeError(f'opcode 0x6A patch site mismatch: have {bytes(data[op6a_off:op6a_off+15]).hex()}')
    rel = BRACKET_HOOK - (op6a_site_va + 5)
    patch(data, op6a_off, b'\xe8' + le32(rel) + b'\x90'*(15-5))
    print(f'patched opcode 0x6A metadata-loop entry -> BRACKET_HOOK 0x{BRACKET_HOOK:x}')

    # Hook code at BRACKET_HOOK.
    # Replicates the original 3-instruction prefix:
    #   movzx esi, byte [ebp+ebx]
    #   movzx ecx, byte [esi + 0x5b40a0]
    #   movsx esi, cl
    # then checks for one special case:
    #   - 0x81 0x75 / 0x81 0x76 brackets: store as half-width while still
    #     consuming both source bytes.
    #
    # LF is handled separately below at the metadata command-byte store. That
    # keeps LF as a normal one-byte/half-width source character here, avoiding
    # source-position drift after multiple inserted line breaks.
    # The original 3 instructions don't touch EAX; the very next instruction
    # after our hook returns reads [EAX + 0x4c]. So we must NOT clobber EAX
    # in our hook. We push/pop EAX around the byte read.
    h = bytearray()
    h += b'\x0f\xb6\x74\x1d\x00'                 # movzx esi, byte [ebp+ebx]   (original)
    h += b'\x0f\xb6\x8e' + le32(0x5b40a0)        # movzx ecx, byte [esi + 0x5b40a0]
    h += b'\x0f\xbe\xf1'                          # movsx esi, cl
    h += b'\x80\x7c\x1d\x00\x81'                  # cmp byte [ebp+ebx+0], 0x81
    h += b'\x75\x00'; jne_quick = len(h)          # jne quick_ret (preserves EAX)
    h += b'\x50'                                  # push eax  (save before clobbering AL)
    h += b'\x8a\x44\x1d\x01'                      # mov al, [ebp+ebx+1]
    h += b'\x3c\x75'                              # cmp al, 0x75
    h += b'\x74\x04'                              # je is_bracket (skip next 4 bytes)
    h += b'\x3c\x76'                              # cmp al, 0x76
    h += b'\x75\x03'                              # jne pop_ret (skip xor+inc, 3 bytes)
    h += b'\x33\xf6'                              # is_bracket: xor esi, esi
    h += b'\x45'                                  # inc ebp
    h += b'\x58'                                  # pop_ret: pop eax
    h += b'\xc3'                                  # ret
    quick_ret_at = len(h)
    h += b'\xc3'                                  # ret (no pop needed - EAX intact)
    # Fix the jne_quick displacement (target = quick_ret_at)
    h[jne_quick - 1] = (quick_ret_at - jne_quick) & 0xff
    patch(data, va2off(BRACKET_HOOK), bytes(h))
    print(f'wrote bracket-width override hook ({len(h)} bytes) at 0x{BRACKET_HOOK:x}')

    # ---------------------------------------------------------------
    # 5.5. LF-backed metadata line breaks.
    # Preserve LF's normal one-byte source accounting in the width-class
    # hook above, then override only the stored metadata command byte here:
    # normal ASCII stores 0x31, raw LF stores 0x52 (the engine's return).
    # The render loop's built-in line-break command moves X/Y and advances
    # the metadata index, but it does not consume a byte from the source text
    # buffer. For explicit LF bytes inserted by ystb_repack.py, consume that
    # one byte too; otherwise the next rendered glyph would still read the LF.
    if LF_NEWLINE_ENABLED:
        lf_cmd_site_va = 0x00458812
        lf_cmd_orig = bytes.fromhex(
            '8d4631'      # lea eax, [esi+31h]
            '8b7a3c'      # mov edi, [edx+3Ch]
            '8b5264'      # mov edx, [edx+64h]
            '88043a'      # mov [edx+edi], al
        )
        lf_cmd_off = va2off(lf_cmd_site_va)
        if bytes(data[lf_cmd_off:lf_cmd_off+len(lf_cmd_orig)]) != lf_cmd_orig:
            raise RuntimeError(f'LF command store mismatch: have {bytes(data[lf_cmd_off:lf_cmd_off+len(lf_cmd_orig)]).hex()}')
        rel = LF_COMMAND_HOOK - (lf_cmd_site_va + 5)
        patch(data, lf_cmd_off, b'\xe8' + le32(rel) + b'\x90' * (len(lf_cmd_orig) - 5))
        print(f'patched LF metadata command store at 0x{lf_cmd_site_va:x} -> LF_COMMAND_HOOK 0x{LF_COMMAND_HOOK:x}')

        lc = bytearray()
        lc += b'\x8d\x46\x31'                    # lea eax, [esi+31h] (normal command)
        lc += b'\x80\x7c\x1d\x00\x0a'            # cmp byte [ebp+ebx+0], 0x0a
        lc += b'\x75\x05'                        # jne store
        lc += b'\xb8\x52\x00\x00\x00'            # mov eax, 0x52
        lc += b'\x8b\x7a\x3c'                    # store: mov edi, [edx+3Ch]
        lc += b'\x8b\x52\x64'                    # mov edx, [edx+64h]
        lc += b'\x88\x04\x3a'                    # mov [edx+edi], al
        lc += b'\xc3'                            # ret
        if len(lc) > 0x80:
            raise RuntimeError(f'LF command hook too big: {len(lc)} bytes')
        patch(data, va2off(LF_COMMAND_HOOK), bytes(lc))
        print(f'wrote LF command hook ({len(lc)} bytes) at 0x{LF_COMMAND_HOOK:x}')

        linebreak_site_va = 0x00404972
        linebreak_orig = bytes.fromhex(
            'c7421400000000'  # mov dword ptr [edx+14h], 0
            '8b7244'          # mov esi, [edx+44h]
            '0fbf344e'        # movsx esi, word ptr [esi+ecx*2]
            '017218'          # add [edx+18h], esi
            'e93a020000'      # jmp 0x404bc2
        )
        lb_off = va2off(linebreak_site_va)
        if bytes(data[lb_off:lb_off+len(linebreak_orig)]) != linebreak_orig:
            raise RuntimeError(f'linebreak site mismatch: have {bytes(data[lb_off:lb_off+len(linebreak_orig)]).hex()}')
        rel = LF_BREAK_HOOK - (linebreak_site_va + 5)
        patch(data, lb_off, b'\xe9' + le32(rel) + b'\x90' * (len(linebreak_orig) - 5))
        print(f'patched LF linebreak render branch at 0x{linebreak_site_va:x} -> LF_BREAK_HOOK 0x{LF_BREAK_HOOK:x}')

        lb = bytearray()
        lb += b'\xc7\x42\x14' + le32(0)          # mov dword ptr [edx+14h], 0
        lb += b'\x8b\x72\x44'                    # mov esi, [edx+44h]
        lb += b'\x0f\xbf\x34\x4e'                # movsx esi, word ptr [esi+ecx*2]
        lb += b'\x01\x72\x18'                    # add [edx+18h], esi
        lb += b'\x50'                            # push eax
        lb += b'\x8b\x42\x68'                    # mov eax, [edx+68h] (source byte pos)
        lb += b'\x03\x42\x38'                    # add eax, [edx+38h] (text buffer base)
        lb += b'\x80\x38\x0a'                    # cmp byte ptr [eax], 0x0a
        lb += b'\x58'                            # pop eax (flags preserved)
        lb += b'\x75\x03'                        # jne no_consume
        lb += b'\xff\x42\x68'                    # inc dword ptr [edx+68h]
        jmp_target_va = 0x00404bc2
        jmp_from_va = LF_BREAK_HOOK + len(lb) + 5
        lb += b'\xe9' + le32(jmp_target_va - jmp_from_va)
        if len(lb) > 0x80:
            raise RuntimeError(f'LF break hook too big: {len(lb)} bytes')
        patch(data, va2off(LF_BREAK_HOOK), bytes(lb))
        print(f'wrote LF break hook ({len(lb)} bytes) at 0x{LF_BREAK_HOOK:x}')

    # ---------------------------------------------------------------
    # 5.6. Disable the original per-character horizontal hard-wrap.
    # With explicit LF metadata in the script, the native fallback wrap is
    # harmful: it can fire one character before our LF and glue fragments
    # like "dthey" or "veimmediately". Keep the vertical/page-end checks,
    # but skip the three horizontal "does this glyph fit?" branches.
    if not NATIVE_HORIZONTAL_WRAP:
        horizontal_wrap_patches = [
            (0x00404cc0, bytes.fromhex('7c3c'), bytes.fromhex('eb3c'), 'hwrap check 1'),
            (0x00404d11, bytes.fromhex('7c4c'), bytes.fromhex('eb4c'), 'hwrap check 2'),
            (0x00404d71, bytes.fromhex('0f8c50010000'), bytes.fromhex('e95101000090'), 'hwrap check 3'),
            (0x004049fb, bytes.fromhex('8bc5e85a020000'), bytes.fromhex('31c09090909090'), 'render pre-wrap call 1'),
            (0x00404af2, bytes.fromhex('8bc5e863010000'), bytes.fromhex('31c09090909090'), 'render pre-wrap call 2'),
        ]
        for site_va, orig, repl, label in horizontal_wrap_patches:
            off = va2off(site_va)
            if bytes(data[off:off+len(orig)]) != orig:
                raise RuntimeError(f'{label} mismatch: have {bytes(data[off:off+len(orig)]).hex()}')
            patch(data, off, repl)
            print(f'disabled native horizontal wrap: {label}')

        nowrap_site_va = 0x00404c6a
        nowrap_orig = bytes.fromhex('8b0d4c488000')  # mov ecx, [0x80484c]
        nowrap_off = va2off(nowrap_site_va)
        if bytes(data[nowrap_off:nowrap_off+len(nowrap_orig)]) != nowrap_orig:
            raise RuntimeError(f'nowrap entry mismatch: have {bytes(data[nowrap_off:nowrap_off+len(nowrap_orig)]).hex()}')
        rel = NO_HWRAP_HOOK - (nowrap_site_va + 5)
        patch(data, nowrap_off, b'\xe9' + le32(rel) + b'\x90')
        print(f'patched wrap-function entry at 0x{nowrap_site_va:x} -> NO_HWRAP_HOOK 0x{NO_HWRAP_HOOK:x}')

        nw = bytearray()
        nw += b'\x8b\x0d' + le32(0x0080484c)        # mov ecx, [0x80484c]
        # Keep the original vertical/page-end guard from sub_404C5C.
        nw += b'\x8b\x69\x18'                        # mov ebp, [ecx+0x18]
        nw += b'\x8b\x51\x44'                        # mov edx, [ecx+0x44]
        nw += b'\x8b\x71\x6c'                        # mov esi, [ecx+0x6c]
        nw += b'\x8d\x44\x36\x02'                    # lea eax, [esi+esi+2]
        nw += b'\x0f\xbf\x04\x10'                    # movsx eax, word [eax+edx]
        nw += b'\x8d\x44\x05\x02'                    # lea eax, [ebp+eax+2]
        nw += b'\x3b\x43\x7c'                        # cmp eax, [ebx+0x7c]
        nw += b'\x0f\x8d'; nw_jge_end = len(nw); nw += b'\x00\x00\x00\x00'
        # If the current metadata command is normal text (0x31/0x32), never
        # run the native horizontal hard-wrap code. Script LF controls wraps.
        nw += b'\x8b\x51\x3c'                        # mov edx, [ecx+0x3c]
        nw += b'\x8b\x41\x6c'                        # mov eax, [ecx+0x6c]
        nw += b'\x0f\xb6\x04\x02'                    # movzx eax, byte [edx+eax]
        nw += b'\x3c\x31'                            # cmp al, 0x31
        nw += b'\x74'; nw_je_ret31 = len(nw); nw += b'\x00'
        nw += b'\x3c\x32'                            # cmp al, 0x32
        nw += b'\x74'; nw_je_ret32 = len(nw); nw += b'\x00'
        nw_jmp_back_at = len(nw)
        nw += b'\xe9' + le32(0)                      # jmp 0x404c70
        nw_ret_zero_at = len(nw)
        nw += b'\x33\xc0'                            # xor eax, eax
        nw += b'\x83\xc4\x54'                        # add esp, 0x54
        nw += b'\x5b\x5d\x5e\x5f'                    # pop ebx; pop ebp; pop esi; pop edi
        nw += b'\xc3'                                # ret
        nw_end_at = len(nw)
        nw += b'\x8b\x51\x60'                        # mov edx, [ecx+0x60]
        nw += b'\x89\x51\x68'                        # mov [ecx+0x68], edx
        nw += b'\xb8\xff\xff\xff\xff'                # mov eax, -1
        nw += b'\x83\xc4\x54'
        nw += b'\x5b\x5d\x5e\x5f'
        nw += b'\xc3'
        nw[nw_jge_end:nw_jge_end+4] = struct.pack('<i', nw_end_at - (nw_jge_end + 4))
        nw[nw_je_ret31] = (nw_ret_zero_at - (nw_je_ret31 + 1)) & 0xff
        nw[nw_je_ret32] = (nw_ret_zero_at - (nw_je_ret32 + 1)) & 0xff
        jmp_target_va = 0x00404c70
        jmp_eip_after = NO_HWRAP_HOOK + nw_jmp_back_at + 5
        nw[nw_jmp_back_at+1:nw_jmp_back_at+5] = struct.pack('<i', jmp_target_va - jmp_eip_after)
        if len(nw) > 0x100:
            raise RuntimeError(f'no-horizontal-wrap hook too big: {len(nw)} bytes')
        patch(data, va2off(NO_HWRAP_HOOK), bytes(nw))
        print(f'wrote no-horizontal-wrap hook ({len(nw)} bytes) at 0x{NO_HWRAP_HOOK:x}')

    # ---------------------------------------------------------------
    # 6. Per-char width LUT for proportional fonts (PROPORTIONAL_WIDTH).
    # The engine assigns each char a fixed half-width slot, so proportional
    # Latin fonts (Segoe UI, Verdana, etc.) leave gaps after narrow letters
    # like 'i','l'. We replace the slot formula with a per-char lookup
    # filled from GDI metrics for the active font.
    if PROPORTIONAL_WIDTH:
        # ---- 6a. Patch metadata loop's width formula. -----------------
        # The original 13 bytes at 0x00458824 compute width = font/(2-cVar2):
        #   8b cb           mov ecx, esi
        #   f7 d9           neg ecx
        #   83 c1 02        add ecx, 2
        #   8b 47 04        mov eax, [edi+4]    ; font_size
        #   99              cdq
        #   f7 f9           idiv ecx            ; eax = font_size / (2-cVar2)
        # Replace with `call get_width` (5 bytes) + 8 NOPs.
        # get_width returns EAX = width (LUT for ASCII, font_size for CJK).
        wf_site_va = 0x00458824
        wf_orig = bytes.fromhex('8bcef7d983c1028b470499f7f9')
        wf_off = va2off(wf_site_va)
        if bytes(data[wf_off:wf_off+13]) != wf_orig:
            raise RuntimeError(f'width-formula site mismatch: {bytes(data[wf_off:wf_off+13]).hex()} vs {wf_orig.hex()}')
        rel = GET_WIDTH - (wf_site_va + 5)
        patch(data, wf_off, b'\xe8' + le32(rel) + b'\x90'*8)
        print(f'patched width formula at 0x{wf_site_va:x} -> GET_WIDTH 0x{GET_WIDTH:x}')

        # ---- 6b. get_width helper -------------------------------------
        # Inputs: ESI = cVar2, EBP+EBX = char ptr, EDI = struct ptr.
        # Returns EAX = width. The original engine formula is
        #   width = font_size / (2 - cVar2)
        # i.e. font_size for cVar2=1 (CJK), font_size/2 for cVar2=0 (ASCII).
        # We replace ASCII with the active font slot's LUT[byte] when set.
        gw = bytearray()
        if PROPORTIONAL_DIAGNOSTIC_ADVANCE is not None:
            gw += b'\x85\xf6'                              # test esi, esi  (cVar2 == 0?)
            gw += b'\x75\x18'                              # jnz cjk
            gw += b'\x0f\xb6\x44\x1d\x00'                  # movzx eax, [ebp+ebx]
            gw += b'\x3d\x80\x00\x00\x00'                  # cmp eax, 0x80
            gw += b'\x73\x06'                              # jae fallback
            gw += b'\xb8' + le32(PROPORTIONAL_DIAGNOSTIC_ADVANCE)
            gw += b'\xc3'                                  # ret
            # fallback: width = font_size / 2 (engine default for ASCII)
            gw += b'\x8b\x47\x04'                          # mov eax, [edi+4]
            gw += b'\xd1\xe8'                              # shr eax, 1
            gw += b'\xc3'                                  # ret
            # cjk: width = font_size
            gw += b'\x8b\x47\x04'                          # mov eax, [edi+4]
            gw += b'\xc3'                                  # ret
        else:
            gw += b'\x85\xf6'                              # test esi, esi  (cVar2 == 0?)
            gw += b'\x75\x2a'                              # jnz cjk
            gw += b'\x0f\xb6\x44\x1d\x00'                  # movzx eax, [ebp+ebx]
            gw += b'\x3d\x80\x00\x00\x00'                  # cmp eax, 0x80
            gw += b'\x73\x18'                              # jae fallback
            gw += b'\x8b\x15' + le32(0x005d1544)           # mov edx, [dword_5D1544]
            gw += b'\xc1\xe2\x07'                          # shl edx, 7  (LUT_STRIDE)
            gw += b'\x81\xc2' + le32(LUT_VA)               # add edx, LUT_VA
            gw += b'\x0f\xb6\x04\x02'                      # movzx eax, byte [edx+eax]
            gw += b'\x85\xc0'                              # test eax, eax
            gw += b'\x74\x01'                              # jz fallback (1 byte forward)
            gw += b'\xc3'                                  # ret  (LUT value)
            # fallback: width = font_size / 2 (engine default for ASCII)
            gw += b'\x8b\x47\x04'                          # mov eax, [edi+4]  (font_size)
            gw += b'\xd1\xe8'                              # shr eax, 1
            gw += b'\xc3'                                  # ret
            # cjk: width = font_size
            gw += b'\x8b\x47\x04'                          # mov eax, [edi+4]
            gw += b'\xc3'                                  # ret
        if len(gw) > LUT_VA - GET_WIDTH:
            raise RuntimeError(f'get_width too big: {len(gw)} bytes')
        patch(data, va2off(GET_WIDTH), bytes(gw))
        print(f'wrote get_width helper ({len(gw)} bytes) at 0x{GET_WIDTH:x}')

        if PATCH_METADATA_WIDTH_TABLE:
            # Disabled by default: this table is also used as the glyph
            # raster size in the body renderer, so narrowing it can corrupt
            # or shrink dialogue glyphs.
            meta_width_site_va = 0x004587db
            meta_width_orig = bytes.fromhex(
                '8b5020'      # mov edx, [eax+20h]
                '8b7864'      # mov edi, [eax+64h]
                '8b4040'      # mov eax, [eax+40h]
                '66891478'    # mov [eax+edi*2], dx
            )
            assert len(meta_width_orig) == 13
            meta_width_off = va2off(meta_width_site_va)
            if bytes(data[meta_width_off:meta_width_off+13]) != meta_width_orig:
                raise RuntimeError(f'metadata visible-width site mismatch: {bytes(data[meta_width_off:meta_width_off+13]).hex()}')
            rel = META_WIDTH_HOOK - (meta_width_site_va + 5)
            patch(data, meta_width_off, b'\xe8' + le32(rel) + b'\x90' * 8)
            print(f'patched metadata visible-width store at 0x{meta_width_site_va:x} -> META_WIDTH_HOOK 0x{META_WIDTH_HOOK:x}')

            mw = bytearray()
            mw += b'\x50'                                      # push eax (text struct)
            mw += b'\x8b\xf8'                                  # mov edi, eax (GET_WIDTH wants struct in EDI)
            rel = GET_WIDTH - (META_WIDTH_HOOK + len(mw) + 5)
            mw += b'\xe8' + le32(rel)                          # call get_width -> eax = slot width
            mw += b'\x8b\xd0'                                  # mov edx, eax
            mw += b'\x58'                                      # pop eax (text struct)
            mw += b'\x8b\x78\x64'                              # mov edi, [eax+64h]
            mw += b'\x8b\x40\x40'                              # mov eax, [eax+40h]
            mw += b'\x66\x89\x14\x78'                          # mov [eax+edi*2], dx
            mw += b'\xc3'                                      # ret
            if len(mw) > 0x80:
                raise RuntimeError(f'metadata width hook too big: {len(mw)} bytes')
            patch(data, va2off(META_WIDTH_HOOK), bytes(mw))
            print(f'wrote metadata width hook ({len(mw)} bytes) at 0x{META_WIDTH_HOOK:x}')

        # ---- 6c. build_lut function ------------------------------------
        # Called at end of CFI detour with EAX = HFONT. Resolves gdi32
        # functions on first call, then fills LUT[0x20..0x7F] for the new
        # font. Preserves EAX so caller's mov [...], EAX still works.
        bl = bytearray()
        bl += b'\x55'                          # push ebp
        bl += b'\x8b\xec'                      # mov ebp, esp
        bl += b'\x83\xec\x20'                  # sub esp, 32  (locals)
        bl += b'\x53\x56\x57'                  # push ebx; push esi; push edi
        bl += b'\x89\x45\xfc'                  # mov [ebp-4], eax    (save HFONT)

        # Helper: emit a placeholder long-form (rel32) je/jne and return the
        # offset where we'll patch the displacement.
        def emit_jcc_long(opcode_byte):
            # 0F <opcode> rel32  -- 6 bytes total
            bl.extend(bytes([0x0f, opcode_byte, 0, 0, 0, 0]))
            return len(bl)  # patch position points just past the jcc

        # Check init flag
        bl += b'\x83\x3d' + le32(INIT_FLAG) + b'\x00'   # cmp [INIT_FLAG], 0
        jne_skip_init = emit_jcc_long(0x85)              # jne skip_init (rel32)

        # GetModuleHandleA("gdi32.dll")
        bl += b'\x68' + le32(STR_GDI32)
        bl += b'\xff\x15' + le32(IAT['GetModuleHandleA'])
        bl += b'\x85\xc0'                                 # test eax, eax
        je_cleanup_a = emit_jcc_long(0x84)               # je cleanup (rel32)
        bl += b'\x8b\xd8'                                 # mov ebx, eax

        # GetProcAddress(gdi32, "CreateCompatibleDC")
        bl += b'\x68' + le32(STR_CCDC)
        bl += b'\x53'
        bl += b'\xff\x15' + le32(IAT['GetProcAddress'])
        bl += b'\xa3' + le32(PTR_CCDC)

        # GetProcAddress(gdi32, "GetCharABCWidthsA")
        bl += b'\x68' + le32(STR_GCW)
        bl += b'\x53'
        bl += b'\xff\x15' + le32(IAT['GetProcAddress'])
        bl += b'\xa3' + le32(PTR_GCW)

        # GetProcAddress(gdi32, "DeleteDC")
        bl += b'\x68' + le32(STR_DDC)
        bl += b'\x53'
        bl += b'\xff\x15' + le32(IAT['GetProcAddress'])
        bl += b'\xa3' + le32(PTR_DDC)

        # init flag = 1
        bl += b'\xc7\x05' + le32(INIT_FLAG) + le32(1)

        skip_init_at = len(bl)

        # Verify all three function pointers are resolved
        bl += b'\xa1' + le32(PTR_CCDC)
        bl += b'\x85\xc0'
        je_cleanup_b = emit_jcc_long(0x84)               # je cleanup
        bl += b'\xa1' + le32(PTR_GCW)
        bl += b'\x85\xc0'
        je_cleanup_d = emit_jcc_long(0x84)               # je cleanup
        bl += b'\xa1' + le32(PTR_DDC)
        bl += b'\x85\xc0'
        je_cleanup_e = emit_jcc_long(0x84)               # je cleanup

        # CreateCompatibleDC(NULL)
        bl += b'\x6a\x00'
        bl += b'\xff\x15' + le32(PTR_CCDC)
        bl += b'\x85\xc0'
        je_cleanup_c = emit_jcc_long(0x84)               # je cleanup
        bl += b'\x89\x45\xf8'

        # SelectObject(hdc, hFont)
        bl += b'\xff\x75\xfc'
        bl += b'\x50'
        bl += b'\xff\x15' + le32(IAT['SelectObject'])
        bl += b'\x89\x45\xf4'

        # EDI = LUT base for current dword_5D1544 font slot.
        bl += b'\x8b\x3d' + le32(0x005d1544)
        bl += b'\xc1\xe7\x07'                              # shl edi, 7
        bl += b'\x81\xc7' + le32(LUT_VA)                   # add edi, LUT_VA

        # Loop esi = 0x20 .. 0x7f (short 8-bit jumps fit since loop body is small)
        bl += b'\xbe\x20\x00\x00\x00'
        loop_start = len(bl)
        bl += b'\x83\xfe\x80'
        bl += b'\x7d\x00'; jge_done = len(bl)            # jge done (8-bit)

        # ABC metrics live at [ebp-0x18..-0x0d]. Keep them separate from
        # [ebp-0x08] HDC and [ebp-0x0c] old selected object.
        bl += b'\x8d\x45\xe8'
        bl += b'\x50'
        bl += b'\x56'
        bl += b'\x56'
        bl += b'\xff\x75\xf8'
        bl += b'\xff\x15' + le32(PTR_GCW)
        bl += b'\x85\xc0'                                  # test eax, eax
        bl += b'\x74\x00'; jz_gcw_failed = len(bl)          # jz next_char

        # Use the full ABC advance. The body renderer advances the pen by
        # this value after drawing each glyph; using the full advance avoids
        # both fixed-cell gaps and over-tight black-box spacing.
        bl += b'\x83\xfe\x20'                              # cmp esi, 0x20
        bl += b'\x75\x04'                                  # jne not_space
        bl += b'\xb0' + bytes([PROPORTIONAL_SPACE_WIDTH])   # mov al, space_width
        bl += b'\xeb\x13'                                  # jmp store
        bl += b'\x8b\x45\xe8'                              # mov eax, [ebp-0x18] (ABC.abcA)
        bl += b'\x03\x45\xec'                              # add eax, [ebp-0x14] (ABC.abcB)
        bl += b'\x03\x45\xf0'                              # add eax, [ebp-0x10] (ABC.abcC)
        bl += b'\x83\xf8\x01'                              # cmp eax, 1
        bl += b'\x7d\x05'                                  # jge store
        bl += b'\xb8\x01\x00\x00\x00'                      # mov eax, 1
        bl += b'\x88\x04\x37'                              # mov [edi+esi], al

        next_char_at = len(bl)
        bl += b'\x46'
        bl += b'\xeb\x00'; jmp_loop = len(bl)            # jmp loop_start (8-bit, backward)

        done_at = len(bl)
        bl += b'\xff\x75\xf4'
        bl += b'\xff\x75\xf8'
        bl += b'\xff\x15' + le32(IAT['SelectObject'])
        bl += b'\xff\x75\xf8'
        bl += b'\xff\x15' + le32(PTR_DDC)

        cleanup_at = len(bl)
        bl += b'\x5f\x5e\x5b'
        bl += b'\x8b\x45\xfc'
        bl += b'\x8b\xe5'
        bl += b'\x5d'
        bl += b'\xc3'

        # Fix displacements: long-form rel32 = (target - patch_pos) where
        # patch_pos == position 4 bytes BEFORE end-of-jcc. emit_jcc_long
        # returned the offset just after the 6-byte jcc, so the rel32
        # bytes occupy offsets [patch_pos-4 .. patch_pos-1].
        def fix_long(patch_pos, target):
            disp = target - patch_pos
            bl[patch_pos-4:patch_pos] = struct.pack('<i', disp)

        fix_long(jne_skip_init, skip_init_at)
        fix_long(je_cleanup_a, cleanup_at)
        fix_long(je_cleanup_b, cleanup_at)
        fix_long(je_cleanup_c, cleanup_at)
        fix_long(je_cleanup_d, cleanup_at)
        fix_long(je_cleanup_e, cleanup_at)
        # Short-form (8-bit) for the tight loop fits since it's < 128 bytes
        bl[jz_gcw_failed - 1] = (next_char_at - jz_gcw_failed) & 0xff
        bl[jge_done - 1] = (done_at - jge_done) & 0xff
        bl[jmp_loop - 1] = (loop_start - jmp_loop) & 0xff

        if len(bl) > GET_WIDTH - BUILD_LUT:
            raise RuntimeError(f'build_lut too big: {len(bl)} bytes (max {GET_WIDTH - BUILD_LUT})')
        # The new section is 0x1000 bytes; everything must fit within
        if (STR_DDC + 16) > NEWSEC_VA + NEWSEC_VSIZE:
            raise RuntimeError('newsec layout exceeds NEWSEC_VSIZE')
        patch(data, va2off(BUILD_LUT), bytes(bl))
        print(f'wrote build_lut ({len(bl)} bytes) at 0x{BUILD_LUT:x}')

        # ---- 6d. Data area: strings, ptrs (zero-init), LUT (zero-init) -
        # Strings
        patch(data, va2off(STR_GDI32), b'gdi32.dll\x00')
        patch(data, va2off(STR_CCDC),  b'CreateCompatibleDC\x00')
        patch(data, va2off(STR_GCW),   b'GetCharABCWidthsA\x00')
        patch(data, va2off(STR_DDC),   b'DeleteDC\x00')
        static_lut = make_static_lut()
        slot_count = (PTR_CCDC - LUT_VA) // LUT_STRIDE
        for slot in range(slot_count):
            patch(data, va2off(LUT_VA + slot * LUT_STRIDE), static_lut)
        print(f'wrote elfpat data: prefilled {slot_count} LUT slots @0x{LUT_VA:x}, ptrs @0x{PTR_CCDC:x}, strings')

        # ---- 6e. Patch sub_443D7C's render-width calculation -----------
        # At 0x443f32 the function computes the SLOT width returned via
        # *a9 (= sub_4056B4's eax = X advancement per char). For ASCII this
        # is font_height/2; for CJK font_height. We swap with LUT[char] for
        # ASCII so X advances by the actual rendered width — proportional
        # fonts now align without gaps.
        # Original 31 bytes (0x443f32..0x443f50): movzx ebp,[ebp]; movzx
        # ecx,classification; inc/movsx/neg; idiv; mov [edi],eax.
        rw_site_va = 0x00443f32
        rw_orig = bytes.fromhex(
            '0fb66d00'                  # movzx ebp, byte [ebp]
            '0fb68da0405b00'            # movzx ecx, byte [ebp+0x5b40a0]
            '41'                        # inc ecx
            '0fbef1'                    # movsx esi, cl
            'f7de'                      # neg esi
            '83c603'                    # add esi, 3
            '8bc3'                      # mov eax, ebx
            '99'                        # cdq
            'f7fe'                      # idiv esi
            '8b7c2478'                  # mov edi, [esp+0x78]
            '8907'                      # mov [edi], eax
        )
        assert len(rw_orig) == 31
        rw_off = va2off(rw_site_va)
        if bytes(data[rw_off:rw_off+31]) != rw_orig:
            raise RuntimeError(f'rwidth site mismatch: {bytes(data[rw_off:rw_off+31]).hex()}')
        rel = RWIDTH_HOOK - (rw_site_va + 5)
        patch(data, rw_off, b'\xe9' + le32(rel) + b'\x90'*26)
        print(f'patched render-width calc at 0x{rw_site_va:x} -> RWIDTH_HOOK 0x{RWIDTH_HOOK:x}')

        # RWIDTH_HOOK: use the active font slot's LUT for ASCII advances.
        # If a LUT entry is missing, fall back to the original engine formula.
        rw = bytearray()
        rw += b'\x0f\xb6\x6d\x00'                          # movzx ebp, byte [ebp]
        rw += b'\x0f\xb6\x8d' + le32(0x005b40a0)           # movzx ecx, byte [byte_5B40A0+ebp]
        rw += b'\x85\xc9'                                  # test ecx, ecx
        rw += b'\x0f\x85'; rw_jne_orig = len(rw); rw += b'\x00\x00\x00\x00'
        rw += b'\x81\xfd\x80\x00\x00\x00'                  # cmp ebp, 0x80
        rw += b'\x0f\x83'; rw_jae_orig = len(rw); rw += b'\x00\x00\x00\x00'
        if PROPORTIONAL_DIAGNOSTIC_ADVANCE is not None:
            rw += b'\xb8' + le32(PROPORTIONAL_DIAGNOSTIC_ADVANCE)
            rw_jz_orig = None
        else:
            rw += b'\x8b\x15' + le32(0x005d1544)           # mov edx, [dword_5D1544]
            rw += b'\xc1\xe2\x07'                          # shl edx, 7
            rw += b'\x81\xc2' + le32(LUT_VA)               # add edx, LUT_VA
            rw += b'\x0f\xb6\x04\x2a'                      # movzx eax, byte [edx+ebp]
            rw += b'\x85\xc0'                              # test eax, eax
            rw += b'\x0f\x84'; rw_jz_orig = len(rw); rw += b'\x00\x00\x00\x00'
        rw += b'\x8b\x7c\x24\x78'                          # mov edi, [esp+0x78]
        rw += b'\x89\x07'                                  # mov [edi], eax
        rw += b'\xe9'; rw_jmp_back_pos = len(rw); rw += b'\x00\x00\x00\x00'

        orig_at = len(rw)
        rw += b'\x41'                                      # inc ecx
        rw += b'\x0f\xbe\xf1'                              # movsx esi, cl
        rw += b'\xf7\xde'                                  # neg esi
        rw += b'\x83\xc6\x03'                              # add esi, 3
        rw += b'\x8b\xc3'                                  # mov eax, ebx
        rw += b'\x99'                                      # cdq
        rw += b'\xf7\xfe'                                  # idiv esi
        rw += b'\x8b\x7c\x24\x78'                          # mov edi, [esp+0x78]
        rw += b'\x89\x07'                                  # mov [edi], eax
        rw += b'\xe9'; rw_orig_jmp_back_pos = len(rw); rw += b'\x00\x00\x00\x00'

        def fix_rw_long(patch_pos, target):
            disp = target - (patch_pos + 4)
            rw[patch_pos:patch_pos+4] = struct.pack('<i', disp)
        fix_rw_long(rw_jne_orig, orig_at)
        fix_rw_long(rw_jae_orig, orig_at)
        if rw_jz_orig is not None:
            fix_rw_long(rw_jz_orig, orig_at)

        jmp_target = 0x00443f51
        eip_after = RWIDTH_HOOK + rw_jmp_back_pos + 4
        rw[rw_jmp_back_pos:rw_jmp_back_pos+4] = struct.pack('<i', jmp_target - eip_after)
        eip_after = RWIDTH_HOOK + rw_orig_jmp_back_pos + 4
        rw[rw_orig_jmp_back_pos:rw_orig_jmp_back_pos+4] = struct.pack('<i', jmp_target - eip_after)
        if len(rw) > 0x100:
            raise RuntimeError(f'rwidth hook too big: {len(rw)} bytes')
        patch(data, va2off(RWIDTH_HOOK), bytes(rw))
        print(f'wrote rwidth hook ({len(rw)} bytes) at 0x{RWIDTH_HOOK:x}')

        # ---- 6f. Patch anti-aliased scan-width return path ------------
        # When ClearType/AA is active, sub_443D7C scans the rendered bitmap
        # and returns (rightmost_pixel / 4) + 4. That final +4 is the visible
        # gap after narrow proportional glyphs. Use the same LUT here.
        aa_site_va = 0x00443ef4
        aa_orig = bytes.fromhex(
            '8be9'                      # mov ebp, ecx
            'd1fd'                      # sar ebp, 1
            'c1ed1e'                    # shr ebp, 0x1e
            '03e9'                      # add ebp, ecx
            'c1fd02'                    # sar ebp, 2
            '83c504'                    # add ebp, 4
            '3bdd'                      # cmp ebx, ebp
            '7c02'                      # jl short keep_ebx
            '8bdd'                      # mov ebx, ebp
            '8b4c2478'                  # mov ecx, [esp+0x78]
            '8919'                      # mov [ecx], ebx
        )
        assert len(aa_orig) == 27
        aa_off = va2off(aa_site_va)
        if bytes(data[aa_off:aa_off+27]) != aa_orig:
            raise RuntimeError(f'AA-width site mismatch: {bytes(data[aa_off:aa_off+27]).hex()}')
        rel = AAWIDTH_HOOK - (aa_site_va + 5)
        patch(data, aa_off, b'\xe9' + le32(rel) + b'\x90'*22)
        print(f'patched AA width calc at 0x{aa_site_va:x} -> AAWIDTH_HOOK 0x{AAWIDTH_HOOK:x}')

        aa = bytearray()
        aa += b'\x8b\xf1'                                  # mov esi, ecx  (save scanned width)
        aa += b'\x0f\xb6\x45\x00'                          # movzx eax, byte [ebp]
        aa += b'\x0f\xb6\x88' + le32(0x005b40a0)           # movzx ecx, byte [byte_5B40A0+eax]
        aa += b'\x85\xc9'                                  # test ecx, ecx
        aa += b'\x0f\x85'; aa_jne_fallback = len(aa); aa += b'\x00\x00\x00\x00'
        aa += b'\x3d\x80\x00\x00\x00'                      # cmp eax, 0x80
        aa += b'\x0f\x83'; aa_jae_fallback = len(aa); aa += b'\x00\x00\x00\x00'
        if PROPORTIONAL_DIAGNOSTIC_ADVANCE is not None:
            aa += b'\xb8' + le32(PROPORTIONAL_DIAGNOSTIC_ADVANCE)
            aa_jz_fallback = None
        else:
            aa += b'\x8b\x15' + le32(0x005d1544)           # mov edx, [dword_5D1544]
            aa += b'\xc1\xe2\x07'                          # shl edx, 7
            aa += b'\x81\xc2' + le32(LUT_VA)               # add edx, LUT_VA
            aa += b'\x0f\xb6\x04\x02'                      # movzx eax, byte [edx+eax]
            aa += b'\x85\xc0'                              # test eax, eax
            aa += b'\x0f\x84'; aa_jz_fallback = len(aa); aa += b'\x00\x00\x00\x00'
        aa += b'\x3b\xd8'                                  # cmp ebx, eax
        aa += b'\x7c\x02'                                  # jl keep_ebx
        aa += b'\x8b\xd8'                                  # mov ebx, eax
        aa += b'\xe9'; aa_jmp_store = len(aa); aa += b'\x00\x00\x00\x00'

        aa_fallback_at = len(aa)
        aa += b'\x8b\xee'                                  # mov ebp, esi
        aa += b'\xd1\xfd'                                  # sar ebp, 1
        aa += b'\xc1\xed\x1e'                              # shr ebp, 0x1e
        aa += b'\x03\xee'                                  # add ebp, esi
        aa += b'\xc1\xfd\x02'                              # sar ebp, 2
        aa += b'\x83\xc5\x04'                              # add ebp, 4
        aa += b'\x3b\xdd'                                  # cmp ebx, ebp
        aa += b'\x7c\x02'                                  # jl keep_ebx
        aa += b'\x8b\xdd'                                  # mov ebx, ebp

        aa_store_at = len(aa)
        aa += b'\x8b\x4c\x24\x78'                          # mov ecx, [esp+0x78]
        aa += b'\x89\x19'                                  # mov [ecx], ebx
        aa += b'\xe9'; aa_jmp_back_pos = len(aa); aa += b'\x00\x00\x00\x00'

        def fix_aa_long(patch_pos, target):
            disp = target - (patch_pos + 4)
            aa[patch_pos:patch_pos+4] = struct.pack('<i', disp)
        fix_aa_long(aa_jne_fallback, aa_fallback_at)
        fix_aa_long(aa_jae_fallback, aa_fallback_at)
        if aa_jz_fallback is not None:
            fix_aa_long(aa_jz_fallback, aa_fallback_at)
        fix_aa_long(aa_jmp_store, aa_store_at)
        aa_jmp_target = 0x00443f0f
        aa_eip_after = AAWIDTH_HOOK + aa_jmp_back_pos + 4
        aa[aa_jmp_back_pos:aa_jmp_back_pos+4] = struct.pack('<i', aa_jmp_target - aa_eip_after)
        if len(aa) > 0x100:
            raise RuntimeError(f'AA width hook too big: {len(aa)} bytes')
        patch(data, va2off(AAWIDTH_HOOK), bytes(aa))
        print(f'wrote AA width hook ({len(aa)} bytes) at 0x{AAWIDTH_HOOK:x}')

        if PROPORTIONAL_FORCE_DRAW_ADVANCE is not None:
            # loc_405C2E returns the measured glyph advance from var_14.
            # push imm8; pop eax; nop fits exactly over `mov eax, [esp+40h]`.
            ret_site_va = 0x00405c2e
            ret_orig = bytes.fromhex('8b442440')
            ret_off = va2off(ret_site_va)
            if bytes(data[ret_off:ret_off+4]) != ret_orig:
                raise RuntimeError(f'draw return site mismatch: {bytes(data[ret_off:ret_off+4]).hex()}')
            adv = int(PROPORTIONAL_FORCE_DRAW_ADVANCE)
            if not 0 <= adv <= 0x7f:
                raise RuntimeError('PROPORTIONAL_FORCE_DRAW_ADVANCE must fit in signed imm8')
            patch(data, ret_off, bytes([0x6a, adv, 0x58, 0x90]))
            print(f'patched sub_4056B4 return advance at 0x{ret_site_va:x} -> {adv}')

    # ---------------------------------------------------------------
    # 6.5 Word-aware wrap hook in FUN_00404c5c.
    # FUN_00404c5c is the per-char "should we wrap before drawing this
    # char?" check used by the dialogue render loop. The original engine
    # only wraps when the next char physically doesn't fit (= mid-word).
    # We add an EARLIER wrap: if the current char is ASCII space AND the
    # remaining width is smaller than WORDWRAP_GUARD_CHARS cells, wrap
    # at that space. That moves the next word to a fresh line.
    if WORDWRAP_ENABLED:
        # Patch site: 0x404c6a is `mov ecx, [0x80484c]` (6 bytes). Replace
        # with `jmp WRAP_HOOK + nop` so we redirect right after the
        # original prologue (push x4 + sub esp,0x54 + mov [esp+0x4c],eax +
        # mov ebx,[eax+0x34]). At this point EBX = box info, EAX = param.
        wrap_site_va = 0x00404c6a
        wrap_orig = bytes.fromhex('8b0d4c488000')   # mov ecx, [0x80484c]
        wrap_off = va2off(wrap_site_va)
        if bytes(data[wrap_off:wrap_off+6]) != wrap_orig:
            raise RuntimeError(f'wrap site mismatch: {bytes(data[wrap_off:wrap_off+6]).hex()}')

        rel = WRAP_HOOK - (wrap_site_va + 5)
        patch(data, wrap_off, b'\xe9' + le32(rel) + b'\x90')
        print(f'patched wrap entry at 0x{wrap_site_va:x} -> WRAP_HOOK 0x{WRAP_HOOK:x}')

        # Hook code at WRAP_HOOK
        # On entry: EAX=param (saved at [esp+0x4c]), EBX=box info,
        # ESP already adjusted by FUN_00404c5c prologue.
        # On exit (fall-through path): jmp 0x404c70 with ECX=struct_ptr set.
        # On exit (wrap path): cleanup stack and ret with EAX=-1.
        # Returning -1 makes the dialogue render loop skip its render branch
        # this iteration; the loop's outer `meta_idx += 1` still fires. We
        # also pre-advance byte_pos by 1 inside the hook (consuming the
        # space) so byte_pos and meta_idx stay aligned.
        wh = bytearray()
        # mov ecx, [0x80484c]   (replicates the replaced instruction)
        wh += b'\x8b\x0d' + le32(0x0080484c)
        # push eax              (preserve param)
        wh += b'\x50'
        # mov eax, [ecx+0x38]   (text buf base)
        wh += b'\x8b\x41\x38'
        # add eax, [ecx+0x68]   (+ byte pos)
        wh += b'\x03\x41\x68'
        if WORDWRAP_DEBUG_X:
            # Overwrite the byte at byte_pos with 'X' (0x58) so EVERY rendered
            # char becomes 'X' — proves the hook is being invoked. After
            # writing, fall through to not_space (engine renders as normal).
            wh += b'\xc6\x00\x58'   # mov byte [eax], 0x58
        # cmp byte [eax], 0x20  (is space?)
        wh += b'\x80\x38\x20'
        # jne not_space         (placeholder; long form 6 bytes for safety)
        wh += b'\x0f\x85'; jne_not_space = len(wh); wh += b'\x00\x00\x00\x00'
        if WORDWRAP_DEBUG_ALWAYS:
            jl_not_space = None  # guard check skipped
        else:
            # --- Compute X + current_cell_width * guard_chars + 2 ---
            # If that reaches the right edge, consume this space and wrap.
            # This uses the active metadata width table, so it tracks the
            # engine's current fixed-width font advance.
            wh += b'\x8b\x51\x40'                       # mov edx, [ecx+0x40] (width array)
            wh += b'\x8b\x41\x6c'                       # mov eax, [ecx+0x6c] (meta idx)
            wh += b'\x0f\xbf\x04\x42'                   # movsx eax, word [edx + eax*2]
            if WORDWRAP_GUARD_CHARS and (WORDWRAP_GUARD_CHARS & (WORDWRAP_GUARD_CHARS - 1)) == 0:
                import math
                wh += b'\xc1\xe0' + bytes([int(math.log2(WORDWRAP_GUARD_CHARS))])
            else:
                if not 0 <= WORDWRAP_GUARD_CHARS <= 0x7f:
                    raise RuntimeError('WORDWRAP_GUARD_CHARS must fit in signed imm8')
                wh += b'\x6b\xc0' + bytes([WORDWRAP_GUARD_CHARS])  # imul eax, eax, imm8
            wh += b'\x03\x41\x14'                       # add eax, [ecx+0x14] (current X)
            wh += b'\x83\xc0\x02'                       # add eax, 2
            wh += b'\x3b\x43\x78'                       # cmp eax, [ebx+0x78] (right edge)
            wh += b'\x0f\x8c'; jl_not_space = len(wh); wh += b'\x00\x00\x00\x00'
        # --- Trigger wrap ---
        # pop eax (balance the push)
        wh += b'\x58'
        # inc dword [ecx+0x68]   (byte_pos += 1: skip the space)
        wh += b'\xff\x41\x68'
        # mov dword [ecx+0x14], 0   (X = 0)
        wh += b'\xc7\x41\x14\x00\x00\x00\x00'
        # mov edx, [ecx+0x44]    (Y array)
        wh += b'\x8b\x51\x44'
        # mov esi, [ecx+0x6c]    (meta idx)
        wh += b'\x8b\x71\x6c'
        # movsx eax, word [edx + esi*2]   (line_height for current slot)
        wh += b'\x0f\xbf\x04\x72'
        # add [ecx+0x18], eax    (Y += line_height)
        wh += b'\x01\x41\x18'
        # --- Check if next line fits: (newY + nextLineHeight + 2) >= bottom?
        # movsx eax, word [edx + esi*2 + 2]   (next line height)
        wh += b'\x0f\xbf\x44\x72\x02'
        # add eax, [ecx+0x18]    (= newY + nextLH)
        wh += b'\x03\x41\x18'
        # add eax, 2
        wh += b'\x83\xc0\x02'
        # cmp eax, [ebx+0x7c]    (vs box bottom)
        wh += b'\x3b\x43\x7c'
        # jge end_dialog (short)
        wh += b'\x7d'; jge_end = len(wh); wh += b'\x00'
        # Wrap success (dialog continues): return -1
        wh += b'\xb8\xff\xff\xff\xff'              # mov eax, -1
        wh += b'\x83\xc4\x54'                       # add esp, 0x54
        wh += b'\x5b\x5d\x5e\x5f'                   # pop ebx; pop ebp; pop esi; pop edi
        wh += b'\xc3'                                # ret
        end_dialog_at = len(wh)
        # End-of-dialog path: byte_pos = end_marker, return -1
        wh += b'\x8b\x41\x60'                       # mov eax, [ecx+0x60]
        wh += b'\x89\x41\x68'                       # mov [ecx+0x68], eax
        wh += b'\xb8\xff\xff\xff\xff'              # mov eax, -1
        wh += b'\x83\xc4\x54'
        wh += b'\x5b\x5d\x5e\x5f'
        wh += b'\xc3'
        not_space_at = len(wh)
        # not_space: pop eax, jmp 0x00404c70
        wh += b'\x58'                                # pop eax
        wh += b'\xe9'                                # jmp rel32
        # rel = 0x404c70 - (WRAP_HOOK + len(wh) + 4)
        jmp_back_pos = len(wh)
        wh += b'\x00\x00\x00\x00'

        # Fix up displacements
        # Long-form jcc (rel32): patch_pos here points at the START of the
        # rel32 bytes; the CPU-relative anchor is the byte right after the
        # rel32 (at patch_pos+4), so disp = target - (patch_pos + 4).
        def fix_long_local(patch_pos, target):
            disp = target - (patch_pos + 4)
            wh[patch_pos:patch_pos+4] = struct.pack('<i', disp)
        fix_long_local(jne_not_space, not_space_at)
        if jl_not_space is not None:
            fix_long_local(jl_not_space,  not_space_at)
        # Short-form jge_end
        wh[jge_end] = (end_dialog_at - (jge_end + 1)) & 0xff
        # JMP back to 0x404c70
        jmp_target_va = 0x00404c70
        jmp_eip_after = WRAP_HOOK + jmp_back_pos + 4
        wh[jmp_back_pos:jmp_back_pos+4] = struct.pack('<i', jmp_target_va - jmp_eip_after)

        # Sanity: hook fits in 0x100 bytes
        if len(wh) > 0x100:
            raise RuntimeError(f'wrap hook too big: {len(wh)} bytes')
        patch(data, va2off(WRAP_HOOK), bytes(wh))
        print(f'wrote wrap hook ({len(wh)} bytes) at 0x{WRAP_HOOK:x}')

    # ---------------------------------------------------------------
    # 7. Bump .text VirtualSize so the cave is officially in-section
    # ---------------------------------------------------------------
    text_vsize_off = sec_off + 8  # first section is .text
    cur_vsize = struct.unpack('<I', data[text_vsize_off:text_vsize_off+4])[0]
    # Bump only enough to officially cover the in-.text cave (everything
    # below 0x58b400). The big build_lut/get_width/LUT/strings live in the
    # separately-added "elfpat" section now, so .text VirtualSize only
    # needs to reach the end of BRACKET_HOOK + a few bytes of slack.
    needed_vsize = (CAVE_VA + 0x180) - image_base - 0x1000
    if needed_vsize > cur_vsize:
        data[text_vsize_off:text_vsize_off+4] = le32(needed_vsize)
        print(f'extended .text VirtualSize: 0x{cur_vsize:x} -> 0x{needed_vsize:x}')

    with open(EXE, 'wb') as f:
        f.write(data)
    print(f'\nwrote patched exe -> {EXE}')

if __name__ == '__main__':
    main()
