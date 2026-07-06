# SPDX-License-Identifier: LGPL-2.1-or-later

from pathlib import Path
import tempfile
import unittest


from vibecad_tests.test_provider_misc import TestVibeCADReferenceImages


class TestVibeCADThumbnailMetadata(unittest.TestCase):
    """Headless checks for transcript thumbnail rendering and turn metadata."""

    _MINIMAL_PNG = TestVibeCADReferenceImages._MINIMAL_PNG

    @classmethod
    def _gui_module(cls):
        try:
            import VibeCADGui

            return VibeCADGui
        except Exception:
            return None

    def setUp(self):
        self.gui = self._gui_module()
        if self.gui is None:
            self.skipTest("VibeCADGui unavailable")

    def _write_png(self, directory: Path, name: str = "thumb.png") -> Path:
        path = directory / name
        path.write_bytes(self._MINIMAL_PNG)
        return path

    def test_turn_image_paths_extracts_image_attachments(self):
        entry = {
            "role": "system",
            "content": "Attached reference image: bracket.png",
            "metadata": {
                "attachments": [
                    {
                        "type": "image",
                        "path": "/data/references/abc-bracket.png",
                        "name": "bracket.png",
                        "reference_id": "abc",
                    },
                    {"type": "note", "path": "/data/ignored.txt"},
                ]
            },
        }
        self.assertEqual(
            self.gui._turn_image_paths(entry),
            ["/data/references/abc-bracket.png"],
        )

    def test_turn_image_paths_ignores_malformed_metadata(self):
        gui = self.gui
        self.assertEqual(gui._turn_image_paths({}), [])
        self.assertEqual(gui._turn_image_paths({"metadata": None}), [])
        self.assertEqual(gui._turn_image_paths({"metadata": "bogus"}), [])
        self.assertEqual(
            gui._turn_image_paths({"metadata": {"attachments": "bogus"}}), []
        )
        self.assertEqual(
            gui._turn_image_paths(
                {"metadata": {"attachments": ["junk", {"type": "image", "path": ""}]}}
            ),
            [],
        )

    def test_transcript_block_html_escapes_text_and_embeds_existing_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = self._write_png(Path(tmp))
            block = self.gui._transcript_block_html(
                "User:\n<b>make it & bigger</b>", [str(image)]
            )
            self.assertIn("&lt;b&gt;make it &amp; bigger&lt;/b&gt;", block)
            self.assertNotIn("<b>make it", block)
            self.assertIn("User:", block)
            self.assertIn(image.resolve().as_uri(), block)
            self.assertIn(
                f'width="{self.gui.TRANSCRIPT_THUMBNAIL_WIDTH}"', block
            )

    def test_transcript_block_html_degrades_to_text_when_image_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "gone.png"
            block = self.gui._transcript_block_html("plain text", [str(missing)])
            self.assertIn("plain text", block)
            self.assertNotIn("<img", block)
            self.assertEqual(self.gui._transcript_block_html("no images", []), self.gui._transcript_block_html("no images", None))

    def test_saved_conversation_blocks_renders_roles_and_thumbnails(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = self._write_png(Path(tmp))
            conversation = [
                {"role": "user", "content": "build a bracket"},
                {
                    "role": "system",
                    "content": "Attached reference image: thumb.png",
                    "metadata": {
                        "attachments": [
                            {"type": "image", "path": str(image), "name": "thumb.png"}
                        ]
                    },
                },
                {"role": "assistant", "content": "done"},
                "junk-entry",
                {"role": "tool", "content": "hidden"},
            ]
            blocks = self.gui._saved_conversation_blocks(conversation)
            self.assertEqual(len(blocks), 3)
            self.assertIn("User:", blocks[0])
            self.assertIn("build a bracket", blocks[0])
            self.assertIn("System:", blocks[1])
            self.assertIn("<img", blocks[1])
            self.assertIn(image.resolve().as_uri(), blocks[1])
            self.assertIn("VibeCAD:", blocks[2])
            self.assertNotIn("<img", blocks[2])
