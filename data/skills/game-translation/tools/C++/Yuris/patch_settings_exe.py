from __future__ import annotations

import argparse
import ctypes
import shutil
import struct
import sys
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")


RT_DIALOG = 5
LANG_JAPANESE = 1041
DS_SETFONT = 0x40


DIALOG_REPLACEMENTS: dict[str, dict[str, Any]] = {
    "IDD_DIALOG1": {
        "title": "Engine Settings",
        "font": "Segoe UI",
        "controls": {
            0: "Rendering Method",
            1: "GPU (Bicubic) - Direct3D, best quality, high load.",
            2: "GPU (Bilinear) - Direct3D, good quality, normal load.",
            3: "CPU (Bilinear) - good quality, may be heavy.",
            4: "CPU (Nearest) - rough quality, light load.",
            5: "Fullscreen",
            6: "Resolution",
            7: "Change - choose the best matching aspect ratio.",
            8: "Keep - do not change the resolution.",
            9: "Scaling",
            10: "Fit - keep aspect ratio within the screen.",
            11: "Crop - fill the screen, keeping aspect ratio.",
            12: "Stretch - fill screen, ignore aspect ratio.",
            13: "None - do not scale.",
            14: "Title-bar double click",
            15: "Maximize window",
            16: "Reset window size",
            17: "Startup window position/size",
            18: "Use last saved state",
            19: "Center, normal size",
            20: "DPI",
            21: "Follow Windows display scaling",
            22: "CPU",
            23: "Use SSE if available",
            24: "Use SSE2 if available",
            25: "Use multicore if available",
            26: "Video Playback",
            27: "Use DirectShow for video playback",
            28: "OK",
            29: "Cancel",
            30: "Reset",
        },
    },
    "IDD_VERSIONINFO": {
        "title": "Version Info",
        "font": "Segoe UI",
        "controls": {
            0: "OK",
        },
    },
}


SJIS_REPLACEMENTS = [
    ("\u0057\u0069\u006e\u0064\u006f\u0077\u0073\u0039\u0035\u002f\u004e\u0054\u0033\u002e\u0035\u002f\u004e\u0054\u0034\u0020\u3067\u306f\u8d77\u52d5\u3067\u304d\u307e\u305b\u3093\u3002", "Cannot run on this Windows."),
    ("\u30a8\u30e9\u30fc", "Error"),
    ("\u8d77\u52d5\u30d1\u30b9\u304c\u4e0d\u6b63\u3067\u3059\u3002", "Bad launch path."),
    (
        "\u8a2d\u5b9a\u30c7\u30fc\u30bf\u30d5\u30a1\u30a4\u30eb\u3092\u65b0\u898f\u4f5c\u6210\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\r\n\r\n"
        "\u66f8\u304d\u8fbc\u307f\u3067\u304d\u306a\u3044\u30d5\u30a9\u30eb\u30c0\u3067\u3042\u308b\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002",
        "Could not create settings data.\r\n\r\nThe folder may not be writable.",
    ),
    (
        "\u8a2d\u5b9a\u30c7\u30fc\u30bf\u30d5\u30a1\u30a4\u30eb\u306b\u8a2d\u5b9a\u3092\u4fdd\u5b58\u3067\u304d\u307e\u305b\u3093\u3067\u3057\u305f\u3002\r\n\r\n"
        "\u005b\u0020\u0079\u0073\u0063\u0066\u0067\u002e\u0064\u0061\u0074\u0020\u005d\u30d5\u30a1\u30a4\u30eb\u304c\u8aad\u307f\u53d6\u308a\u5c02\u7528\u306b\u306a\u3063\u3066\u3044\u308b\u53ef\u80fd\u6027\u304c\u3042\u308a\u307e\u3059\u3002",
        "Could not save settings.\r\n\r\n[yscfg.dat] may be read-only.",
    ),
    (
        "\u203b\u30e0\u30fc\u30d3\u30fc\u518d\u751f\u306b\u0020\u0044\u0069\u0072\u0065\u0063\u0074\u0053\u0068\u006f\u0077\u0020\u3092\u4f7f\u7528\u3057\u306a\u3044\u5834\u5408\u3067\u3001\r\n"
        "\u3000\u30d5\u30eb\u30b9\u30af\u30ea\u30fc\u30f3\u6642\u306e\u62e1\u5927\u65b9\u6cd5\u304c\u300c\u62e1\u5927\u0028\u5916\u63a5\u0029\u300d\u306e\u5834\u5408\u3001\r\n"
        "\u3000\u5f37\u5236\u7684\u306b\u300c\u62e1\u5927\u0028\u5185\u63a5\u0029\u300d\u3067\u30e0\u30fc\u30d3\u30fc\u304c\u518d\u751f\u3055\u308c\u307e\u3059\u3002",
        "Note: If DirectShow video is disabled and fullscreen scaling is Crop,\r\nvideos will play with Fit scaling instead.",
    ),
    ("\u60c5\u5831", "Info"),
    ("\u30bd\u30d5\u30c8\u304c\u8d77\u52d5\u4e2d\u3067\u3059\u3002\u4e00\u65e6\u7d42\u4e86\u3055\u305b\u3066\u304f\u3060\u3055\u3044\u3002", "Game is running. Close it first."),
    ("\u30a8\u30f3\u30b8\u30f3\u8a2d\u5b9a", "Engine Setup"),
]


def u16(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<H", buf, off)[0]


def s16(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<h", buf, off)[0]


def u32(buf: bytes | bytearray, off: int) -> int:
    return struct.unpack_from("<I", buf, off)[0]


def align4(value: int) -> int:
    return (value + 3) & ~3


def pad4(out: bytearray) -> None:
    while len(out) % 4:
        out.append(0)


def read_res_name(buf: bytes, off: int) -> tuple[tuple[str, Any], int]:
    marker = u16(buf, off)
    if marker == 0:
        return ("none", ""), off + 2
    if marker == 0xFFFF:
        return ("atom", u16(buf, off + 2)), off + 4

    start = off
    while u16(buf, off) != 0:
        off += 2
    text = buf[start:off].decode("utf-16le")
    return ("string", text), off + 2


def write_res_name(out: bytearray, value: tuple[str, Any]) -> None:
    kind, payload = value
    if kind == "none":
        out += struct.pack("<H", 0)
    elif kind == "atom":
        out += struct.pack("<HH", 0xFFFF, int(payload))
    elif kind == "string":
        out += str(payload).encode("utf-16le") + b"\0\0"
    else:
        raise ValueError(f"unknown resource name kind: {kind}")


def parse_standard_dialog(buf: bytes) -> dict[str, Any]:
    if u16(buf, 0) == 0xFFFF and u16(buf, 2) == 1:
        raise ValueError("DIALOGEX resources are not handled by this patcher")

    off = 0
    style, ex_style, control_count = struct.unpack_from("<IIH", buf, off)
    x, y, cx, cy = struct.unpack_from("<hhhh", buf, off + 10)
    off = 18

    menu, off = read_res_name(buf, off)
    window_class, off = read_res_name(buf, off)
    title, off = read_res_name(buf, off)

    font = None
    if style & DS_SETFONT:
        point_size = u16(buf, off)
        off += 2
        typeface, off = read_res_name(buf, off)
        font = {"point_size": point_size, "typeface": typeface}

    off = align4(off)
    controls = []
    for index in range(control_count):
        off = align4(off)
        style_c, ex_style_c = struct.unpack_from("<II", buf, off)
        x_c, y_c, cx_c, cy_c, control_id = struct.unpack_from("<hhhhH", buf, off + 8)
        off += 18
        control_class, off = read_res_name(buf, off)
        text, off = read_res_name(buf, off)
        extra_len = u16(buf, off)
        off += 2
        extra = buf[off:off + extra_len]
        off += extra_len
        controls.append(
            {
                "index": index,
                "style": style_c,
                "ex_style": ex_style_c,
                "rect": (x_c, y_c, cx_c, cy_c),
                "id": control_id,
                "class": control_class,
                "text": text,
                "extra": extra,
            }
        )

    return {
        "style": style,
        "ex_style": ex_style,
        "rect": (x, y, cx, cy),
        "menu": menu,
        "class": window_class,
        "title": title,
        "font": font,
        "controls": controls,
    }


def build_standard_dialog(dialog: dict[str, Any], repl: dict[str, Any]) -> bytes:
    out = bytearray()
    controls = dialog["controls"]
    x, y, cx, cy = dialog["rect"]
    out += struct.pack("<IIHhhhh", dialog["style"], dialog["ex_style"], len(controls), x, y, cx, cy)
    write_res_name(out, dialog["menu"])
    write_res_name(out, dialog["class"])
    write_res_name(out, ("string", repl.get("title", dialog["title"][1])))

    font = dialog["font"]
    if font is not None:
        out += struct.pack("<H", font["point_size"])
        write_res_name(out, ("string", repl.get("font", font["typeface"][1])))

    pad4(out)
    control_replacements = repl.get("controls", {})
    for control in controls:
        pad4(out)
        cx_c, cy_c, cw_c, ch_c = control["rect"]
        out += struct.pack(
            "<IIhhhhH",
            control["style"],
            control["ex_style"],
            cx_c,
            cy_c,
            cw_c,
            ch_c,
            control["id"],
        )
        write_res_name(out, control["class"])
        new_text = control_replacements.get(control["index"], control["text"][1])
        if control["text"][0] == "string" or control["text"][0] == "none":
            write_res_name(out, ("string", new_text) if new_text else ("none", ""))
        else:
            write_res_name(out, control["text"])
        extra = control["extra"]
        out += struct.pack("<H", len(extra)) + extra

    return bytes(out)


def rva_to_file_offset(rva: int, sections: list[tuple[str, int, int, int, int]]) -> int:
    for _name, va, vsize, raw, raw_size in sections:
        if va <= rva < va + max(vsize, raw_size):
            return raw + (rva - va)
    raise ValueError(f"RVA not mapped: {rva:#x}")


def parse_resource_entries(data: bytes) -> list[dict[str, Any]]:
    pe = u32(data, 0x3C)
    coff = pe + 4
    section_count = u16(data, coff + 2)
    optional_size = u16(data, coff + 16)
    optional = coff + 20
    magic = u16(data, optional)
    data_dir = optional + (96 if magic == 0x10B else 112)
    rsrc_rva = u32(data, data_dir + 8 * 2)
    section_header = optional + optional_size
    sections = []
    for index in range(section_count):
        off = section_header + index * 40
        name = data[off:off + 8].split(b"\0", 1)[0].decode("ascii", "replace")
        sections.append((name, u32(data, off + 12), u32(data, off + 8), u32(data, off + 20), u32(data, off + 16)))

    rsrc_base = rva_to_file_offset(rsrc_rva, sections)

    def read_name(name_value: int) -> str:
        off = rsrc_base + (name_value & 0x7FFFFFFF)
        length = u16(data, off)
        return data[off + 2:off + 2 + length * 2].decode("utf-16le")

    def walk(dir_off: int, ids: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        off = rsrc_base + dir_off
        named = u16(data, off + 12)
        numbered = u16(data, off + 14)
        entries = []
        for entry_index in range(named + numbered):
            entry_off = off + 16 + entry_index * 8
            name_value = u32(data, entry_off)
            data_or_dir = u32(data, entry_off + 4)
            name = read_name(name_value) if name_value & 0x80000000 else name_value
            if data_or_dir & 0x80000000:
                entries.extend(walk(data_or_dir & 0x7FFFFFFF, ids + (name,)))
            else:
                data_entry = rsrc_base + data_or_dir
                rva = u32(data, data_entry)
                size = u32(data, data_entry + 4)
                entries.append(
                    {
                        "ids": ids + (name,),
                        "rva": rva,
                        "size": size,
                        "file_offset": rva_to_file_offset(rva, sections),
                    }
                )
        return entries

    return walk(0)


def update_dialog_resource(path: Path, name: str, lang: int, blob: bytes) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    begin = kernel32.BeginUpdateResourceW
    begin.argtypes = [ctypes.c_wchar_p, ctypes.c_bool]
    begin.restype = ctypes.c_void_p
    update = kernel32.UpdateResourceW
    update.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ushort, ctypes.c_void_p, ctypes.c_uint]
    update.restype = ctypes.c_bool
    end = kernel32.EndUpdateResourceW
    end.argtypes = [ctypes.c_void_p, ctypes.c_bool]
    end.restype = ctypes.c_bool

    handle = begin(str(path), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())

    buffer = ctypes.create_string_buffer(blob)
    type_ptr = ctypes.c_void_p(RT_DIALOG)
    name_ptr = ctypes.cast(ctypes.c_wchar_p(name), ctypes.c_void_p)
    try:
        if not update(handle, type_ptr, name_ptr, lang, buffer, len(blob)):
            raise ctypes.WinError(ctypes.get_last_error())
    except Exception:
        end(handle, True)
        raise
    if not end(handle, False):
        raise ctypes.WinError(ctypes.get_last_error())


def patch_dialogs(path: Path) -> list[str]:
    data = path.read_bytes()
    updates = []
    patched = []
    for entry in parse_resource_entries(data):
        ids = entry["ids"]
        if len(ids) != 3 or ids[0] != RT_DIALOG:
            continue
        name, lang = ids[1], ids[2]
        if name not in DIALOG_REPLACEMENTS:
            continue
        blob = data[entry["file_offset"]:entry["file_offset"] + entry["size"]]
        dialog = parse_standard_dialog(blob)
        new_blob = build_standard_dialog(dialog, DIALOG_REPLACEMENTS[name])
        updates.append((str(name), int(lang), blob, new_blob))

    for name, lang, blob, new_blob in updates:
        update_dialog_resource(path, name, lang, new_blob)
        patched.append(f"{name} ({len(blob)} -> {len(new_blob)} bytes)")
    return patched


def patch_sjis_strings(path: Path) -> list[str]:
    data = bytearray(path.read_bytes())
    patched = []
    for old_text, new_text in SJIS_REPLACEMENTS:
        old = old_text.encode("cp932")
        new = new_text.encode("cp932")
        if len(new) > len(old):
            raise ValueError(f"replacement too long for {old_text!r}: {len(new)} > {len(old)}")
        count = 0
        start = 0
        replacement = new + b"\0" * (len(old) - len(new))
        while True:
            offset = data.find(old, start)
            if offset < 0:
                break
            data[offset:offset + len(old)] = replacement
            count += 1
            start = offset + len(old)
        if count:
            patched.append(f"{old_text!r} -> {new_text!r} ({count})")
    path.write_bytes(data)
    return patched


def dump_dialogs(path: Path) -> None:
    data = path.read_bytes()
    for entry in parse_resource_entries(data):
        ids = entry["ids"]
        if len(ids) != 3 or ids[0] != RT_DIALOG:
            continue
        blob = data[entry["file_offset"]:entry["file_offset"] + entry["size"]]
        dialog = parse_standard_dialog(blob)
        print(f"\n{ids[1]} lang={ids[2]} size={entry['size']}")
        print(f"  title: {dialog['title'][1]!r}")
        if dialog["font"] is not None:
            print(f"  font: {dialog['font']['typeface'][1]!r}")
        for control in dialog["controls"]:
            print(f"  {control['index']:02d}: {control['text'][1]!r}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate the YU-RIS engine settings executable.")
    parser.add_argument("exe", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--dump", action="store_true")
    args = parser.parse_args()

    target = args.exe
    if args.output:
        shutil.copy2(args.exe, args.output)
        target = args.output

    if args.dump:
        dump_dialogs(target)
        return 0

    dialog_changes = patch_dialogs(target)
    sjis_changes = patch_sjis_strings(target)

    print("Patched dialogs:")
    for change in dialog_changes:
        print(f"  {change}")
    print("Patched Shift-JIS strings:")
    for change in sjis_changes:
        print(f"  {change}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
