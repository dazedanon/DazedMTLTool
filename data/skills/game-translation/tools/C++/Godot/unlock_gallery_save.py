#!/usr/bin/env python3
"""Unlock specific gallery scene IDs in Godot's encrypted progress.cfg."""

from __future__ import annotations

import argparse
import re
import shutil
import struct
from datetime import datetime
from hashlib import md5
from pathlib import Path

from Crypto.Cipher import AES


MAGIC = b"GDEC"
PASSWORD = "pass"
DEFAULT_PROGRESS = Path("save") / "-1" / "progress.cfg"
DEFAULT_IDS = ("ticket_minuki_hanyou_1", "ticket_minuki_hanyou_2")


def _key_from_password(password: str) -> bytes:
    return md5(password.encode("utf-8")).hexdigest().encode("ascii")


def decrypt_godot4_encrypted_config(path: Path, password: str) -> tuple[bytes, bytes]:
    data = path.read_bytes()
    if data[:4] != MAGIC:
        raise ValueError(f"{path} is not a Godot encrypted file")

    expected_md5 = data[4:20]
    plain_len = struct.unpack_from("<Q", data, 20)[0]
    iv = data[28:44]
    ciphertext = data[44:]

    key = _key_from_password(password)
    plaintext = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).decrypt(ciphertext)
    plaintext = plaintext[:plain_len]
    if md5(plaintext).digest() != expected_md5:
        raise ValueError("decrypted MD5 did not match; password or format is wrong")

    return plaintext, iv


def encrypt_godot4_encrypted_config(plaintext: bytes, iv: bytes, password: str) -> bytes:
    padded_len = len(plaintext)
    if padded_len % 16:
        padded_len += 16 - (padded_len % 16)
    padded = plaintext + (b"\x00" * (padded_len - len(plaintext)))

    key = _key_from_password(password)
    ciphertext = AES.new(key, AES.MODE_CFB, iv=iv, segment_size=128).encrypt(padded)
    return MAGIC + md5(plaintext).digest() + struct.pack("<Q", len(plaintext)) + iv + ciphertext


def unlock_ids(config_text: str, scene_ids: tuple[str, ...]) -> tuple[str, list[str], list[str]]:
    pattern = re.compile(r"^unlocked=Array\[StringName\]\(\[(?P<body>.*)\]\)$", re.MULTILINE)
    match = pattern.search(config_text)
    if not match:
        raise ValueError("could not find GalleryScenes unlocked array")

    body = match.group("body")
    existing = re.findall(r'&"([^"]+)"', body)
    updated = list(existing)
    added: list[str] = []
    for scene_id in scene_ids:
        if scene_id not in updated:
            updated.append(scene_id)
            added.append(scene_id)

    if not added:
        return config_text, existing, added

    replacement_body = ", ".join(f'&"{scene_id}"' for scene_id in updated)
    replacement = f"unlocked=Array[StringName]([{replacement_body}])"
    return pattern.sub(replacement, config_text, count=1), existing, added


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--progress", type=Path, default=DEFAULT_PROGRESS)
    parser.add_argument("--password", default=PASSWORD)
    parser.add_argument("--id", dest="ids", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    scene_ids = tuple(args.ids) if args.ids else DEFAULT_IDS
    plaintext, iv = decrypt_godot4_encrypted_config(args.progress, args.password)
    config_text = plaintext.decode("utf-8")
    updated_text, existing, added = unlock_ids(config_text, scene_ids)

    print("Existing unlocked IDs:")
    for scene_id in existing:
        print(f"  - {scene_id}")

    if not added:
        print("No change needed; requested IDs are already unlocked.")
        return 0

    print("Adding IDs:")
    for scene_id in added:
        print(f"  - {scene_id}")

    if args.dry_run:
        print("Dry run only; progress.cfg was not changed.")
        return 0

    backup_root = Path("backups") / f"save_unlock_gallery_{datetime.now():%Y%m%d_%H%M%S}"
    backup_root.mkdir(parents=True, exist_ok=True)
    backup_path = backup_root / args.progress.name
    shutil.copy2(args.progress, backup_path)

    args.progress.write_bytes(encrypt_godot4_encrypted_config(updated_text.encode("utf-8"), iv, args.password))
    verify_plaintext, _ = decrypt_godot4_encrypted_config(args.progress, args.password)
    if verify_plaintext.decode("utf-8") != updated_text:
        raise ValueError("verification failed after writing progress.cfg")

    print(f"Backed up original to: {backup_path}")
    print(f"Updated: {args.progress}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
