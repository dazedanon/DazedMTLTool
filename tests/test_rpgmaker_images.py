import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from PIL import Image

from util.rpgmaker_images import (
    add_patch_exceptions,
    clean_runtime_image_duplicates,
    decrypt_assets,
    decrypt_image_bytes,
    editable_workspace_root,
    encrypt_assets,
    encrypt_image_bytes,
    migrate_legacy_editable_workspace,
    prepare_assets_for_patch,
    read_encryption_key,
    remove_editable_assets,
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
        self.assertEqual(
            assets[0].plain_path,
            self.root / ".dazedtl" / "images" / "www" / "img" / "pictures" / "001.png",
        )

        result = decrypt_assets(
            assets, read_encryption_key(self.root), game_root=self.root
        )
        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(assets[0].plain_path.read_bytes(), png_bytes("red"))
        self.assertEqual(encrypted.read_bytes(), original)
        ignore = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertIn("/.dazedtl/", ignore)

    def test_existing_editable_png_is_not_overwritten_by_decrypt_all(self):
        self._encrypted_asset()
        asset = scan_image_assets(self.root)[0]
        plain = asset.plain_path
        plain.parent.mkdir(parents=True)
        translated = png_bytes("blue")
        plain.write_bytes(translated)

        result = decrypt_assets(
            scan_image_assets(self.root), KEY, game_root=self.root
        )

        self.assertEqual(result.completed, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(plain.read_bytes(), translated)

    def test_remove_editable_image_deletes_only_workspace_copy(self):
        self._encrypted_asset()
        asset = scan_image_assets(self.root)[0]
        decrypt_assets([asset], KEY, game_root=self.root)
        edited = png_bytes("blue")
        asset.plain_path.write_bytes(edited)

        result = remove_editable_assets(self.root, [asset])

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertFalse(asset.plain_path.exists())
        self.assertTrue(asset.encrypted_path.exists())

    def test_prepare_reencrypts_selected_image_backs_up_original_and_updates_ignore(self):
        encrypted = self._encrypted_asset()
        original = encrypted.read_bytes()
        asset = scan_image_assets(self.root)[0]
        decrypt_assets([asset], KEY, game_root=self.root)
        translated = png_bytes("blue")
        asset.plain_path.write_bytes(translated)
        self.root.joinpath(".gitignore").write_text("*.*\n", encoding="utf-8")

        result = prepare_assets_for_patch(self.root, [asset], KEY)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(decrypt_image_bytes(encrypted.read_bytes(), KEY), translated)
        self.assertEqual(asset.plain_path.read_bytes(), translated)
        backup = self.root / ".dazedtl" / "image_backups" / "www/img/pictures/001.rpgmvp"
        self.assertEqual(backup.read_bytes(), original)
        ignore = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertIn("/.dazedtl/", ignore)
        self.assertIn("!/www/img/pictures/001.rpgmvp", ignore)
        self.assertNotIn("!/www/img/pictures/001.png", ignore)

        second = prepare_assets_for_patch(self.root, [asset], KEY)
        again = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertEqual(second.completed, 0)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(again.count("!/www/img/pictures/001.rpgmvp"), 1)
        self.assertEqual(backup.read_bytes(), original)

    def test_prepare_skips_unchanged_decrypted_image(self):
        encrypted = self._encrypted_asset()
        original = encrypted.read_bytes()
        asset = scan_image_assets(self.root)[0]
        decrypt_assets([asset], KEY, game_root=self.root)

        result = prepare_assets_for_patch(self.root, [asset], KEY)

        self.assertEqual(result.completed, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.patch_files, [])
        self.assertEqual(encrypted.read_bytes(), original)
        self.assertFalse(
            (self.root / ".dazedtl" / "image_backups" / "www/img/pictures/001.rpgmvp").exists()
        )
        ignore = self.root.joinpath(".gitignore").read_text(encoding="utf-8")
        self.assertNotIn("!/www/img/pictures/001.rpgmvp", ignore)

    def test_prepare_skips_unchanged_unencrypted_workspace_copy(self):
        runtime = self.content / "img" / "pictures" / "menu.png"
        original = png_bytes("yellow")
        runtime.write_bytes(original)
        asset = scan_image_assets(self.root)[0]
        asset.plain_path.parent.mkdir(parents=True, exist_ok=True)
        asset.plain_path.write_bytes(original)

        result = prepare_assets_for_patch(self.root, [asset], None)

        self.assertEqual(result.completed, 0)
        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.patch_files, [])
        self.assertEqual(runtime.read_bytes(), original)
        self.assertFalse((self.root / ".dazedtl" / "image_backups").exists())

    def test_mz_png_uses_same_crypto_and_logical_png_name(self):
        encrypted = self._encrypted_asset("title.png_", "green")
        asset = scan_image_assets(self.root)[0]

        self.assertEqual(asset.asset_id, "img/pictures/title.png")
        self.assertEqual(asset.encrypted_path, encrypted)
        result = decrypt_assets([asset], KEY, game_root=self.root)
        self.assertEqual(result.completed, 1)
        self.assertEqual(asset.plain_path.read_bytes(), png_bytes("green"))

    def test_encrypt_only_rebuilds_runtime_file_without_changing_gitignore(self):
        encrypted = self._encrypted_asset()
        asset = scan_image_assets(self.root)[0]
        decrypt_assets([asset], KEY, game_root=self.root)
        translated = png_bytes("black")
        asset.plain_path.write_bytes(translated)
        ignore_before = self.root.joinpath(".gitignore").read_text(encoding="utf-8")

        result = encrypt_assets(self.root, [asset], KEY)

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(decrypt_image_bytes(encrypted.read_bytes(), KEY), translated)
        self.assertEqual(
            self.root.joinpath(".gitignore").read_text(encoding="utf-8"),
            ignore_before,
        )

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

    def test_workspace_edit_of_plain_game_image_is_published_and_backed_up(self):
        runtime = self.content / "img" / "pictures" / "menu.png"
        original = png_bytes("yellow")
        translated = png_bytes("blue")
        runtime.write_bytes(original)
        asset = scan_image_assets(self.root)[0]
        asset.plain_path.parent.mkdir(parents=True)
        asset.plain_path.write_bytes(translated)

        result = prepare_assets_for_patch(self.root, [asset], None)

        self.assertEqual(result.completed, 1)
        self.assertEqual(runtime.read_bytes(), translated)
        backup = self.root / ".dazedtl" / "image_backups" / "www/img/pictures/menu.png"
        self.assertEqual(backup.read_bytes(), original)
        self.assertEqual(result.patch_files, [runtime])

    def test_legacy_side_by_side_editable_png_is_migrated_to_workspace(self):
        self._encrypted_asset()
        legacy = self.content / "img" / "pictures" / "001.png"
        translated = png_bytes("purple")
        legacy.write_bytes(translated)
        asset = scan_image_assets(self.root)[0]

        result = decrypt_assets([asset], KEY, game_root=self.root)

        self.assertEqual(result.completed, 1)
        self.assertEqual(asset.plain_path.read_bytes(), translated)
        self.assertFalse(legacy.exists())

    def test_conflicting_runtime_duplicate_is_preserved_outside_game_images(self):
        self._encrypted_asset()
        runtime_duplicate = self.content / "img" / "pictures" / "001.png"
        runtime_duplicate.write_bytes(png_bytes("blue"))
        asset = scan_image_assets(self.root)[0]
        asset.plain_path.parent.mkdir(parents=True)
        workspace_edit = png_bytes("purple")
        asset.plain_path.write_bytes(workspace_edit)

        cleaned = clean_runtime_image_duplicates(self.root)

        self.assertEqual(cleaned, 1)
        self.assertFalse(runtime_duplicate.exists())
        self.assertEqual(asset.plain_path.read_bytes(), workspace_edit)
        conflict = (
            self.root
            / ".dazedtl"
            / "runtime_plain_conflicts"
            / "www"
            / "img"
            / "pictures"
            / "001.png"
        )
        self.assertEqual(conflict.read_bytes(), png_bytes("blue"))

    def test_mz_workspace_preserves_runtime_hierarchy(self):
        mz_root = Path(self.temp.name) / "MZGame"
        image_dir = mz_root / "img" / "pictures"
        data_dir = mz_root / "data"
        image_dir.mkdir(parents=True)
        data_dir.mkdir(parents=True)
        data_dir.joinpath("System.json").write_text(
            '{"encryptionKey":"' + KEY_HEX + '"}', encoding="utf-8"
        )
        encrypted = image_dir / "title.png_"
        encrypted.write_bytes(encrypt_image_bytes(png_bytes("green"), KEY))

        asset = scan_image_assets(mz_root)[0]
        result = decrypt_assets([asset], KEY, game_root=mz_root)

        self.assertEqual(result.completed, 1)
        self.assertEqual(
            asset.plain_path,
            editable_workspace_root(mz_root) / "img" / "pictures" / "title.png",
        )

    def test_legacy_editable_folder_is_moved_under_dazedtl(self):
        legacy = self.root / "DazedTL_Images" / "www" / "img" / "pictures"
        legacy.mkdir(parents=True)
        translated = png_bytes("purple")
        legacy.joinpath("001.png").write_bytes(translated)

        moved = migrate_legacy_editable_workspace(self.root)

        destination = (
            self.root / ".dazedtl" / "images" / "www" / "img" / "pictures" / "001.png"
        )
        self.assertEqual(moved, 1)
        self.assertEqual(destination.read_bytes(), translated)
        self.assertFalse((self.root / "DazedTL_Images").exists())

    def test_scan_uses_editable_workspace_as_the_edit_list(self):
        self._encrypted_asset("001.rpgmvp")
        self._encrypted_asset("002.rpgmvp", "blue")
        assets = scan_image_assets(self.root)
        assets[1].plain_path.parent.mkdir(parents=True, exist_ok=True)
        assets[1].plain_path.write_bytes(png_bytes("purple"))

        rescanned = scan_image_assets(self.root)

        self.assertEqual(
            {asset.asset_id for asset in rescanned if asset.has_plain},
            {assets[1].asset_id},
        )


if __name__ == "__main__":
    unittest.main()
