#!/usr/bin/env python3
"""Create a Godot exe candidate with shader/pipeline caches forced off.

This patches only three register moves after Godot reads the project settings:

- rendering/rendering_device/pipeline_cache/enable
- rendering/shader_compiler/shader_cache/enabled
- RendererCompositorRD shader_cache/enabled

The live exe is not overwritten unless --in-place is passed.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


DEFAULT_INPUT = Path("usa01.exe")
DEFAULT_OUTPUT = Path("usa01_cache_disabled.exe")

PATCHES = (
    # 0x14238cc93: mov ebx, eax -> xor ebx, ebx
    (0x238C093, bytes.fromhex("89 c3"), bytes.fromhex("31 db"), "pipeline_cache_enable"),
    # 0x14129cd7e: mov r12d, eax -> xor r12d, r12d
    (0x129C17E, bytes.fromhex("41 89 c4"), bytes.fromhex("45 31 e4"), "shader_cache_enabled_check"),
    # 0x142497997: mov r13d, eax -> xor r13d, r13d
    (0x2496D97, bytes.fromhex("41 89 c5"), bytes.fromhex("45 31 ed"), "renderer_compositor_shader_cache_enabled"),
)


def patch_file(src: Path, dst: Path, in_place: bool) -> None:
    if in_place:
        backup = src.with_suffix(src.suffix + ".bak_cache_patch")
        if not backup.exists():
            shutil.copy2(src, backup)
            print(f"Backed up original exe to: {backup}")
        dst = src
        data = bytearray(src.read_bytes())
    else:
        shutil.copy2(src, dst)
        data = bytearray(dst.read_bytes())

    for offset, expected, replacement, label in PATCHES:
        found = bytes(data[offset : offset + len(expected)])
        if found == replacement:
            print(f"{label}: already patched at file offset 0x{offset:x}")
            continue
        if found != expected:
            raise ValueError(
                f"{label}: unexpected bytes at 0x{offset:x}: "
                f"{found.hex(' ')} != {expected.hex(' ')}"
            )
        data[offset : offset + len(expected)] = replacement
        print(f"{label}: patched at file offset 0x{offset:x}")

    dst.write_bytes(data)
    print(f"Wrote patched exe: {dst}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()

    patch_file(args.input, args.output, args.in_place)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
