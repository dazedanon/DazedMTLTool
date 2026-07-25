import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from util.rpgmaker_images import (
    add_patch_exceptions,
    decrypt_assets,
    decrypt_image_bytes,
    encrypt_assets,
    encrypt_image_bytes,
    prepare_assets_for_patch,
    read_encryption_key,
    scan_image_assets,
)


KEY_HEX = "00112233445566778899aabbccddeeff"
KEY = bytes.fromhex(KEY_HEX)


def png_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (12, 8), color).save(output, format="PNG")
    return output.getvalue()


class RPGMakerImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "Game"
        self.content = self.root / "www"
        (self.content / "data").mkdir(parents=True)
        (self.content / "img" / "pictures").mkdir(parents=True)
        (self.content / "data" / "System.json").write_text(
            '{"encryptionKey":"' + KEY_HEX + '"}', encoding="utf-8"
        )

    def tearDown(self):
        self.temp.cleanup()

    def _encrypted_asset(self, name: str = "001.rpgmvp", color: str = "red") -> Path:
        path = self.content / "img" / "pictures" / name
        path.write_bytes(encrypt_image_bytes(png_bytes(color), KEY))
        return path

    def test_scan_and_decrypt_mv_image_without_touching_encrypted_original(self):
        encrypted = self._encrypted_asset()
        original = encrypted.read_bytes()

        assets = scan_image_assets(self.root)
        self.assertEqual([asset.asset_id for asset in assets], ["img/pictures/001.png"])
        self.assertFalse(assets[0].has_plain)

        result = decrypt_assets(assets, read_encryption_key(self.root))
        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(assets[0].plain_path.read_bytes(), png_bytes("red"))
        self.assertEqual(encrypted.read_bytes(), original)

    def test_existing_editable_png_is_not_overwritten_by_decrypt_all(self):
        self._encrypted_asset()
        plain = self.content / "img" / "pictures" / "001.png"
        translated = png_bytes("blue")
        plain.write_bytes(translated)

        result = decrypt_assets(scan_image_assets(self.root), KEY)

        self.assertEqual(result.completed, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(plain.read_bytes(), translated)

    def test_prepare_reencrypts_selected_image_backs_up_original_and_updates_ignore(self):
        encrypted = self._encrypted_asset()
        original = encrypted.read_bytes()
        asset = scan_image_assets(self.root)[0]
        decrypt_assets([asset], KEY)
        translated = png_bytes("blue")
        asset.plain_path.write_bytes(translated)
        self.root.joinpath(".gitignore").write_text("*.*\n", encoding="utf-8")

        result = prepare_assets_for_patch(self.root, [asset], KEY)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(decrypt_image_bytes(encrypted.read_bytes(), KEY), translated)
        backup = self.root / ".dazedtl" / "image_backups" / "www/img/pictures/001.rpgmvp"
        self.assertEqual(backup.read_bytes(), original)
        ignore = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertIn("/.dazedtl/", ignore)
        self.assertIn("!/www/img/pictures/001.rpgmvp", ignore)
        self.assertNotIn("!/www/img/pictures/001.png", ignore)

        prepare_assets_for_patch(self.root, [asset], KEY)
        again = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertEqual(again.count("!/www/img/pictures/001.rpgmvp"), 1)
        self.assertEqual(backup.read_bytes(), original)

    def test_mz_png_uses_same_crypto_and_logical_png_name(self):
        encrypted = self._encrypted_asset("title.png_", "green")
        asset = scan_image_assets(self.root)[0]

        self.assertEqual(asset.asset_id, "img/pictures/title.png")
        self.assertEqual(asset.encrypted_path, encrypted)
        result = decrypt_assets([asset], KEY)
        self.assertEqual(result.completed, 1)
        self.assertEqual(asset.plain_path.read_bytes(), png_bytes("green"))

    def test_encrypt_only_rebuilds_runtime_file_without_changing_gitignore(self):
        encrypted = self._encrypted_asset()
        asset = scan_image_assets(self.root)[0]
        decrypt_assets([asset], KEY)
        translated = png_bytes("black")
        asset.plain_path.write_bytes(translated)

        result = encrypt_assets(self.root, [asset], KEY)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(decrypt_image_bytes(encrypted.read_bytes(), KEY), translated)
        self.assertFalse((self.root / ".gitignore").exists())

    def test_nested_gitignore_receives_relative_exact_exception(self):
        target = self.content / "img" / "pictures" / "menu image.png"
        target.write_bytes(png_bytes("purple"))
        nested = self.content / "img" / ".gitignore"
        nested.write_text("*\n", encoding="utf-8")

        changed = add_patch_exceptions(self.root, [target])

        self.assertIn(self.root / ".gitignore", changed)
        self.assertIn(nested, changed)
        nested_text = nested.read_text(encoding="utf-8")
        self.assertIn("!/pictures/menu\\ image.png", nested_text)
        root_text = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertIn("!/www/img/pictures/menu\\ image.png", root_text)

    def test_plain_selected_image_is_added_without_requiring_key(self):
        plain = self.content / "img" / "pictures" / "menu.png"
        plain.write_bytes(png_bytes("yellow"))
        asset = scan_image_assets(self.root)[0]

        result = prepare_assets_for_patch(self.root, [asset], None)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        ignore = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertIn("!/www/img/pictures/menu.png", ignore)


if __name__ == "__main__":
    unittest.main()
