import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from util.image_manager import (
    PROFILE_GENERIC,
    PROFILE_RPGMAKER_MVMZ,
    copy_plain_assets_to_workspace,
    detect_image_engine,
    make_profile_assets_editable,
    prepare_plain_assets_for_patch,
    prepare_profile_assets_for_patch,
    preview_profile_png_bytes,
    registered_image_profiles,
    scan_generic_image_assets,
    scan_profile_assets,
    thumbnail_profile_png_bytes,
)
from util.rpgmaker_images import decrypt_image_bytes, encrypt_image_bytes


def png_bytes(color: str) -> bytes:
    output = BytesIO()
    Image.new("RGBA", (10, 8), color).save(output, format="PNG")
    return output.getvalue()


class GenericImageManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "Game"
        self.images = self.root / "assets" / "ui"
        self.images.mkdir(parents=True)
        self.source = self.images / "menu.png"
        self.source.write_bytes(png_bytes("red"))

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_mirrors_game_relative_path_in_workspace(self):
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]

        self.assertEqual(asset.engine_id, PROFILE_GENERIC)
        self.assertEqual(asset.asset_id, "assets/ui/menu.png")
        self.assertEqual(
            asset.plain_path,
            self.root / ".dazedtl" / "images" / "assets" / "ui" / "menu.png",
        )

    def test_make_editable_is_non_destructive_and_does_not_overwrite(self):
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]
        original = self.source.read_bytes()

        first = copy_plain_assets_to_workspace(self.root, [asset])
        asset.plain_path.write_bytes(png_bytes("blue"))
        second = copy_plain_assets_to_workspace(self.root, [asset])

        self.assertEqual(first.completed, 1)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(asset.plain_path.read_bytes(), png_bytes("blue"))
        self.assertTrue((self.root / ".dazedtl" / "image_manager" / "manifest.json").is_file())

    def test_patch_publishes_backup_and_exact_allow_rule(self):
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]
        original = self.source.read_bytes()
        copy_plain_assets_to_workspace(self.root, [asset])
        translated = png_bytes("green")
        asset.plain_path.write_bytes(translated)
        self.root.joinpath(".gitignore").write_text("*.png\n/.dazedtl/\n", encoding="utf-8")

        result = prepare_plain_assets_for_patch(self.root, [asset])

        self.assertEqual(result.completed, 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(self.source.read_bytes(), translated)
        backup = self.root / ".dazedtl" / "image_backups" / "assets/ui/menu.png"
        self.assertEqual(backup.read_bytes(), original)
        self.assertIn(
            "!/assets/ui/menu.png",
            self.root.joinpath(".gitignore").read_text(encoding="utf-8"),
        )

    def test_patch_rejects_source_changed_after_editable_copy(self):
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]
        copy_plain_assets_to_workspace(self.root, [asset])
        asset.plain_path.write_bytes(png_bytes("green"))
        external = png_bytes("purple")
        self.source.write_bytes(external)

        result = prepare_plain_assets_for_patch(self.root, [asset])

        self.assertEqual(result.completed, 0)
        self.assertIn("runtime image changed", result.errors[0])
        self.assertEqual(self.source.read_bytes(), external)

    def test_patch_batch_preflight_is_all_or_nothing(self):
        second_source = self.images / "title.png"
        second_source.write_bytes(png_bytes("yellow"))
        first, second = scan_generic_image_assets(self.root, self.root / "assets")
        copy_plain_assets_to_workspace(self.root, [first, second])
        first.plain_path.write_bytes(png_bytes("green"))
        second.plain_path.write_bytes(png_bytes("blue"))
        second_source.write_bytes(png_bytes("purple"))
        first_original = self.source.read_bytes()

        result = prepare_plain_assets_for_patch(self.root, [first, second])

        self.assertEqual(result.completed, 0)
        self.assertEqual(self.source.read_bytes(), first_original)
        self.assertIn("runtime image changed", result.errors[0])

    def test_patch_rolls_back_runtime_if_gitignore_update_fails(self):
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]
        original = self.source.read_bytes()
        copy_plain_assets_to_workspace(self.root, [asset])
        asset.plain_path.write_bytes(png_bytes("green"))

        with patch(
            "util.rpgmaker_images.add_patch_exceptions",
            side_effect=OSError("ignore file is read-only"),
        ):
            result = prepare_plain_assets_for_patch(self.root, [asset])

        self.assertEqual(result.completed, 0)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertIn("rolled back", result.errors[0])
        stage = self.root / ".dazedtl" / "image_patch_stage"
        self.assertFalse(stage.exists() and any(stage.iterdir()))

    def test_patch_rejects_corrupt_editable_png(self):
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]
        original = self.source.read_bytes()
        copy_plain_assets_to_workspace(self.root, [asset])
        asset.plain_path.write_bytes(b"not a PNG")

        result = prepare_plain_assets_for_patch(self.root, [asset])

        self.assertEqual(result.completed, 0)
        self.assertIn("not a valid PNG", result.errors[0])
        self.assertEqual(self.source.read_bytes(), original)

    def test_case_only_asset_collision_is_rejected(self):
        self.images.joinpath("Menu.png").write_bytes(png_bytes("blue"))

        with self.assertRaisesRegex(ValueError, "differ only by letter case"):
            scan_profile_assets(PROFILE_GENERIC, self.root, self.root / "assets")

    def test_generic_root_must_remain_inside_game(self):
        outside = Path(self.temp.name) / "Outside"
        outside.mkdir()

        with self.assertRaisesRegex(ValueError, "outside the selected game folder"):
            scan_generic_image_assets(self.root, outside)

    def test_scan_is_read_only(self):
        scan_generic_image_assets(self.root, self.root / "assets")

        self.assertFalse((self.root / ".dazedtl").exists())
        self.assertFalse((self.root / ".gitignore").exists())

    def test_preview_strips_icc_profile_without_changing_source(self):
        output = BytesIO()
        Image.new("RGBA", (10, 8), "red").save(
            output, format="PNG", icc_profile=b"outdated sRGB profile"
        )
        source = output.getvalue()
        self.source.write_bytes(source)
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]

        preview = preview_profile_png_bytes(PROFILE_GENERIC, asset, None)
        thumbnail = thumbnail_profile_png_bytes(PROFILE_GENERIC, asset, None)

        self.assertIn(b"iCCP", source)
        self.assertNotIn(b"iCCP", preview)
        self.assertNotIn(b"iCCP", thumbnail)
        self.assertEqual(self.source.read_bytes(), source)
        with Image.open(BytesIO(preview)) as image:
            self.assertEqual(image.getpixel((0, 0)), (255, 0, 0, 255))

    def test_preview_leaves_png_without_icc_profile_byte_identical(self):
        source = self.source.read_bytes()
        asset = scan_generic_image_assets(self.root, self.root / "assets")[0]

        self.assertEqual(preview_profile_png_bytes(PROFILE_GENERIC, asset, None), source)


class ImageEngineDetectionTests(unittest.TestCase):
    def test_registry_exposes_rpgmaker_and_generic_capabilities(self):
        profiles = {profile.engine_id: profile for profile in registered_image_profiles()}

        self.assertTrue(profiles[PROFILE_RPGMAKER_MVMZ].supports_encryption)
        self.assertFalse(profiles[PROFILE_GENERIC].supports_encryption)
        self.assertTrue(profiles[PROFILE_GENERIC].configurable_image_root)
        self.assertIn("RPG Maker MV/MZ", profiles[PROFILE_RPGMAKER_MVMZ].translation_skill_context)
        self.assertNotIn("RPG Maker", profiles[PROFILE_GENERIC].translation_skill_context)

    def test_detects_rpgmaker_from_system_json_and_img(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "data").mkdir()
            (root / "img").mkdir()
            (root / "data" / "System.json").write_text("{}", encoding="utf-8")

            detection = detect_image_engine(root)

            self.assertEqual(detection.engine_id, PROFILE_RPGMAKER_MVMZ)
            self.assertEqual(detection.confidence, "high")

    def test_unknown_layout_falls_back_to_generic_with_suggestion(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            images = root / "assets" / "images"
            images.mkdir(parents=True)
            images.joinpath("title.png").write_bytes(png_bytes("black"))

            detection = detect_image_engine(root)

            self.assertEqual(detection.engine_id, PROFILE_GENERIC)
            self.assertEqual(detection.suggested_image_root, images)


class RPGMakerImageProfileTests(unittest.TestCase):
    def test_profile_preserves_decrypt_edit_reencrypt_workflow(self):
        key = bytes.fromhex("00112233445566778899aabbccddeeff")
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            image_root = root / "img" / "pictures"
            data_root = root / "data"
            image_root.mkdir(parents=True)
            data_root.mkdir()
            data_root.joinpath("System.json").write_text(
                '{"encryptionKey":"00112233445566778899aabbccddeeff"}',
                encoding="utf-8",
            )
            runtime = image_root / "title.png_"
            runtime.write_bytes(encrypt_image_bytes(png_bytes("red"), key))
            asset = scan_profile_assets(PROFILE_RPGMAKER_MVMZ, root)[0]

            made = make_profile_assets_editable(
                PROFILE_RPGMAKER_MVMZ, root, [asset], key
            )
            translated = png_bytes("blue")
            asset.plain_path.write_bytes(translated)
            patched = prepare_profile_assets_for_patch(
                PROFILE_RPGMAKER_MVMZ, root, [asset], key
            )

            self.assertEqual(made.completed, 1)
            self.assertEqual(patched.completed, 1)
            self.assertEqual(patched.errors, [])
            self.assertEqual(decrypt_image_bytes(runtime.read_bytes(), key), translated)


if __name__ == "__main__":
    unittest.main()
