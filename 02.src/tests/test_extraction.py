from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtGui import QImage, QColor

from dvd_player.core import read_manifest
from dvd_player.extraction import (
    ExtractionCancelled, bitmap_bounds, dvd_input, find_tool,
    frames_to_manifest, render_command, run_tool, DvdSubtitleExtractor,
    checked_identity, probe_media,
)
from dvd_player.storage import CacheStore


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cancel = threading.Event()

    def frame(self, timestamp, opaque=True):
        image = QImage(10, 8, QImage.Format.Format_RGBA8888)
        image.fill(QColor(0, 0, 0, 0))
        if opaque:
            image.setPixelColor(3, 4, QColor("white"))
            image.setPixelColor(4, 4, QColor("white"))
        image.save(str(self.root / f"{timestamp:012}.png"))
        return image

    def test_alpha_crop_and_clear(self):
        image = bitmap_bounds(self.frame(1000))
        self.assertEqual((image.width(), image.height()), (2, 1))
        self.assertIsNone(bitmap_bounds(self.frame(2000, False)))

    def test_frame_times_repetitions_and_clear(self):
        self.frame(1000)
        self.frame(1500)
        self.frame(2000, False)
        self.frame(3000)
        self.frame(3500, False)
        manifest = frames_to_manifest(self.root, "media", 0, "en", "2", 4000, self.cancel)
        index, _ = read_manifest(manifest, "media", 0)
        self.assertEqual([(c.start_ms, c.end_ms) for c in index.cues], [(1000, 2000), (3000, 3500)])
        self.assertEqual(index.active(2000), [])

    def test_unknown_last_end_is_not_invented(self):
        self.frame(1000)
        with self.assertRaises(ValueError):
            frames_to_manifest(self.root, "media", 0, "en", "2", None, self.cancel)

    def test_cancel_stops_child_process(self):
        self.cancel.set()
        with self.assertRaises(ExtractionCancelled):
            run_tool([sys.executable, "-c", "import time; time.sleep(60)"], self.cancel)

    def test_dvd_input_uses_real_title_not_vob_concatenation(self):
        inputs = dvd_input("D:/", 2)
        self.assertEqual(inputs[inputs.index("-title") + 1], "3")
        self.assertEqual(inputs[inputs.index("-trim") + 1], "0")
        self.assertEqual(inputs[-1], "D:")
        self.assertEqual(dvd_input("D:\\", 0)[-1], "D:")
        with self.assertRaises(ValueError):
            dvd_input("D:/", -1)

    def test_replaced_disc_is_rejected_before_extraction(self):
        with patch("dvd_player.extraction.find_tool", return_value="ffmpeg"), \
                patch("dvd_player.extraction.checked_identity", return_value="other"), \
                patch("dvd_player.extraction.run_tool") as runner:
            with self.assertRaises(ValueError):
                DvdSubtitleExtractor(CacheStore(self.root / "cache")).extract(
                    "D:/", "media", 0, self.cancel, lambda *args: None)
            runner.assert_not_called()

    def test_pipeline_routes_languages_and_persists(self):
        metadata = dict(format=dict(duration="5"), streams=[
            dict(index=2, codec_type="subtitle", codec_name="dvd_subtitle", tags=dict(language="eng")),
            dict(index=3, codec_type="subtitle", codec_name="dvd_subtitle", tags=dict(language="jpn")),
            dict(index=4, codec_type="subtitle", codec_name="dvd_subtitle", tags=dict(language="und"))])
        def fake_run(args, cancel, timeout=900, image_directory=None, on_poll=None):
            if "-demuxers" in args:
                return b" D dvdvideo"
            if "-show_streams" in args:
                return json.dumps(metadata).encode()
            for directory in image_directory.iterdir():
                image = QImage(2, 2, QImage.Format.Format_RGBA8888)
                image.fill(QColor("white"))
                image.save(str(directory / "000000001000.png"))
                image.fill(QColor(0, 0, 0, 0))
                image.save(str(directory / "000000002000.png"))
            return b""
        cache = CacheStore(self.root / "cache")
        notifications = []
        with patch("dvd_player.extraction.find_tool", side_effect=lambda name: name), \
                patch("dvd_player.extraction.checked_identity", return_value="media"), \
                patch("dvd_player.extraction.run_tool", side_effect=fake_run):
            tracks, unknown = DvdSubtitleExtractor(cache).extract("D:/", "media", 0, self.cancel,
                                                                lambda *args: notifications.append(args))
        self.assertEqual({t.language for t in tracks}, {"en", "ja"})
        self.assertEqual(unknown, [4])
        self.assertEqual(len(cache.load_tracks("media", 0)), 2)
        self.assertEqual(len([n for n in notifications if n[0] == "track"]), 2)

    def test_partial_manifest_excludes_unfinished_cue(self):
        self.frame(0, False)
        self.frame(1000)
        self.frame(1500)
        self.frame(2000, False)
        self.frame(3000)
        self.frame(3500, False)
        manifest = frames_to_manifest(self.root, "media", 0, "en", "4", 5000,
                                      self.cancel, complete=False)
        index, _ = read_manifest(manifest, "media", 0)
        self.assertFalse(index.complete)
        self.assertEqual([(c.start_ms, c.end_ms) for c in index.cues], [(1000, 2000)])
        self.assertTrue(index.covers(1500))
        self.assertFalse(index.covers(3000))

    def test_resume_seeks_merges_previews_and_skips_completed_track(self):
        self.frame(10000)
        self.frame(12000, False)
        self.frame(14000, False)
        self.frame(15000, False)
        cache = CacheStore(self.root / "cache")
        manifest = frames_to_manifest(self.root, "media", 0, "en", "2", 30000,
                                      self.cancel, complete=False)
        original = cache.save_snapshot(manifest, "media", 0)
        original_image = original.index.cues[0].image.read_bytes()
        metadata = dict(format=dict(duration="30"), streams=[
            dict(index=2, codec_type="subtitle", codec_name="dvd_subtitle", tags=dict(language="eng"))])
        renders = []
        def fake_run(args, cancel, timeout=900, image_directory=None, on_poll=None):
            if "-demuxers" in args:
                return b" D dvdvideo"
            if "-show_streams" in args:
                return json.dumps(metadata).encode()
            renders.append(args)
            self.assertLess(args.index("-ss"), args.index("-i"))
            self.assertEqual(args[args.index("-ss") + 1], "8.000")
            image = QImage(2, 2, QImage.Format.Format_RGBA8888)
            for timestamp, color in [(10000, "white"), (12000, "transparent"),
                                     (20000, "red"), (21000, "transparent"),
                                     (22000, "transparent"), (23000, "transparent")]:
                image.fill(QColor(color))
                image.save(str(image_directory / "2" / f"{timestamp:012}.png"))
            on_poll()
            preview = cache.load_tracks("media", 0)[0]
            self.assertFalse(preview.index.complete)
            self.assertEqual([(c.start_ms, c.end_ms) for c in preview.index.cues],
                             [(10000, 12000), (20000, 21000)])
            return b""
        with patch("dvd_player.extraction.find_tool", side_effect=lambda name: name), \
                patch("dvd_player.extraction.checked_identity", return_value="media"), \
                patch("dvd_player.extraction.run_tool", side_effect=fake_run):
            extractor = DvdSubtitleExtractor(cache)
            tracks, _ = extractor.extract("D:/", "media", 0, self.cancel, lambda *args: None)
            self.assertTrue(tracks[0].index.complete)
            self.assertEqual(tracks[0].index.cues[0].image.read_bytes(), original_image)
            self.assertEqual([(c.start_ms, c.end_ms) for c in tracks[0].index.cues],
                             [(10000, 12000), (20000, 21000)])
            extractor.extract("D:/", "media", 0, self.cancel, lambda *args: None)
        self.assertEqual(len(renders), 1)

    def test_identity_helper_output_is_validated(self):
        with patch("dvd_player.extraction.run_tool", return_value=b""):
            with self.assertRaises(ValueError):
                checked_identity("D:/", self.cancel)

    def test_media_presence_probe_runs_outside_gui_process(self):
        video = self.root / "VIDEO_TS"
        video.mkdir()
        (video / "VIDEO_TS.IFO").write_bytes(b"navigation")
        self.assertTrue(probe_media(str(self.root), self.cancel))
        (video / "VIDEO_TS.IFO").unlink()
        self.assertFalse(probe_media(str(self.root), self.cancel))

    @unittest.skipUnless(importlib.util.find_spec("av"), "optional PyAV test fixture generator not installed")
    def test_real_ffmpeg_decodes_synthetic_dvd_bitmap(self):
        try:
            ffmpeg = find_tool("ffmpeg")
        except ValueError:
            self.skipTest("FFmpeg not installed")
        import av
        source = self.root / "sample.mkv"
        # Authored two-pixel DVD SPU, not copied from a commercial disc.
        raw = bytes.fromhex("0024000690900000001e0103321004fff0050000010000010600040005ff005a001e02ff")
        with av.open(str(source), "w") as container:
            stream = container.add_stream("dvdsub")
            stream.time_base = Fraction(1, 1000)
            stream.codec_context.extradata = (b"size: 720x480\npalette: " +
                b", ".join([b"000000", b"ffffff", b"888888", b"ff0000"] * 4) + b"\n")
            packet = av.Packet(raw)
            packet.stream = stream
            packet.pts = packet.dts = 2000
            packet.duration = 1024
            packet.time_base = Fraction(1, 1000)
            container.mux(packet)
        run_tool(render_command(ffmpeg, ["-i", str(source)], 0, self.root), self.cancel, 30)
        manifest = frames_to_manifest(self.root, "media", 0, "en", "0", 3024, self.cancel)
        index, _ = read_manifest(manifest, "media", 0)
        self.assertEqual(len(index.cues), 1)
        self.assertEqual((index.cues[0].start_ms, index.cues[0].end_ms), (2000, 3024))
        self.assertEqual(QImage(str(index.cues[0].image)).size().width(), 2)


if __name__ == "__main__":
    unittest.main()
