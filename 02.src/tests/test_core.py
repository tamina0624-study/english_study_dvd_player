import json
from pathlib import Path
import tempfile
import unittest

from dvd_player.core import Cue, CueIndex, SeekCoordinator, read_manifest, timestamp
from dvd_player.playback import media_identity


class DomainTests(unittest.TestCase):
    def test_overlap_and_half_open_boundaries(self):
        index = CueIndex([Cue("a", 0, 10000, Path("a")),
                          Cue("b", 2000, 3000, Path("b")),
                          Cue("c", 3000, 4000, Path("c"))])
        self.assertEqual(index.active(-1), [])
        self.assertEqual(index.active(2000), [0, 1])
        self.assertEqual(index.active(3000), [0, 2])
        self.assertEqual(index.active(4000), [0])
        self.assertEqual(index.active(10000), [])

    def test_rewind_accumulates_and_preserves_state(self):
        seek = SeekCoordinator()
        seek.rewind(10000, True)
        self.assertEqual(seek.next_command(10000, 0), 8000)
        seek.rewind(9900, False)
        self.assertEqual(seek.target, 6000)
        self.assertTrue(seek.resume)
        self.assertEqual(seek.next_command(8000, 1), 6000)
        self.assertIsNone(seek.next_command(6000, 2))
        self.assertIsNone(seek.target)

    def test_rewind_clamps_to_zero(self):
        seek = SeekCoordinator()
        seek.rewind(1000, False)
        seek.rewind(1000, False)
        self.assertEqual(seek.target, 0)
        self.assertFalse(seek.resume)

    def test_seek_timeout_clears_queue(self):
        seek = SeekCoordinator()
        seek.request(10000, False)
        seek.next_command(0, 0)
        with self.assertRaises(TimeoutError):
            seek.next_command(0, 6)
        self.assertIsNone(seek.target)
        self.assertIsNone(seek.sent)

    def test_timestamp_unknown_and_hours(self):
        self.assertEqual(timestamp(None), "--:--")
        self.assertEqual(timestamp(-1), "--:--")
        self.assertEqual(timestamp(1000), "00:01")
        self.assertEqual(timestamp(3601000), "01:00:01")


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "image.png").write_bytes(b"example")
        self.path = self.root / "manifest.json"
        self.data = dict(schema_version=1, media_id="dvd", title_id=0,
                         language="en", complete=True,
                         cues=[dict(cue_id="a", start_ms=0, end_ms=1000,
                                    image_path="image.png")])

    def load(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        return read_manifest(self.path, "dvd", 0)

    def test_valid_manifest(self):
        index, language = self.load()
        self.assertEqual(language, "en")
        self.assertEqual(index.active(0), [0])

    def test_mismatched_media_or_title(self):
        for field, value in (("media_id", "other"), ("title_id", 1)):
            with self.subTest(field=field):
                original = self.data[field]
                self.data[field] = value
                with self.assertRaises(ValueError):
                    self.load()
                self.data[field] = original

    def test_path_escape(self):
        outside = self.root.parent / "escape-subtitle-test.png"
        outside.write_bytes(b"example")
        self.addCleanup(outside.unlink)
        self.data["cues"][0]["image_path"] = "../escape-subtitle-test.png"
        with self.assertRaises(ValueError):
            self.load()

    def test_invalid_times_duplicates_and_incomplete(self):
        self.data["cues"][0]["end_ms"] = 0
        with self.assertRaises(ValueError):
            self.load()
        self.data["cues"][0]["end_ms"] = 1000
        self.data["cues"].append(self.data["cues"][0].copy())
        with self.assertRaises(ValueError):
            self.load()
        self.data["cues"].pop()
        self.data["complete"] = False
        with self.assertRaises(ValueError):
            self.load()

    def test_disc_identity_independent_of_drive(self):
        for folder in ("disc1", "disc2"):
            directory = self.root / folder / "VIDEO_TS"
            directory.mkdir(parents=True)
            (directory / "VIDEO_TS.IFO").write_bytes(b"navigation")
        first = media_identity(str(self.root / "disc1"))
        self.assertEqual(first, media_identity(str(self.root / "disc2")))
        (self.root / "disc2" / "VIDEO_TS" / "VIDEO_TS.IFO").write_bytes(b"different")
        self.assertNotEqual(first, media_identity(str(self.root / "disc2")))

    def test_partial_manifest_requires_coverage_for_every_cue(self):
        self.data.update(complete=False, coverage=[dict(start_ms=0, end_ms=1500)])
        index, _ = self.load()
        self.assertFalse(index.complete)
        self.assertTrue(index.covers(1499))
        self.assertFalse(index.covers(1500))
        self.data["coverage"][0]["end_ms"] = 500
        with self.assertRaises(ValueError):
            self.load()


if __name__ == "__main__":
    unittest.main()
