from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from PySide6.QtGui import QImage, QColor

from dvd_player.core import Cue, CueIndex
from dvd_player.storage import CacheStore
from dvd_player.subtitle_edit import parse_srt, export_for_editor, launch_editor, bdn_time


class SubtitleEditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.srt = self.root / "English subtitles.srt"

    def test_utf8_multiline_formatting_and_boundaries(self):
        self.srt.write_text("1\n00:00:01,050 --> 00:00:03,000\n<i>Hello</i> &amp; welcome.\nSecond line.\n\n"
                            "2\n00:00:03,000 --> 00:00:04,250\nNext\n", encoding="utf-8-sig")
        index = parse_srt(self.srt)
        self.assertEqual(index.cues[0].text, "Hello & welcome.\nSecond line.")
        self.assertEqual(index.active(2999), [0])
        self.assertEqual(index.active(3000), [1])
        self.assertIsNone(index.cues[0].image)

    def test_japanese_cp932_and_utf16(self):
        content = "1\n00:00:01,000 --> 00:00:02,000\n日本語の字幕\n"
        for encoding in ("cp932", "utf-16"):
            with self.subTest(encoding=encoding):
                self.srt.write_text(content, encoding=encoding)
                self.assertEqual(parse_srt(self.srt).cues[0].text, "日本語の字幕")

    def test_malformed_and_reversed_times_are_rejected(self):
        for content in ("", "1\nnot a time\ntext", "1\n00:00:03,000 --> 00:00:01,000\ntext"):
            self.srt.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                parse_srt(self.srt)

    def test_srt_persists_for_same_disc_and_title(self):
        self.srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        cache = CacheStore(self.root / "cache")
        track, warning = cache.import_srt(self.srt, "disc", 1, "en")
        self.assertFalse(warning)
        self.srt.unlink()
        loaded = cache.load_tracks("disc", 1)
        self.assertEqual(loaded[0].index.cues[0].text, "Hello")
        self.assertEqual(loaded[0].track_id, track.track_id)
        self.assertTrue((cache.title_dir("disc", 1) / "subtitles.en.srt").is_file())
        self.assertEqual(cache.load_tracks("disc", 0), [])

    def test_text_export_roundtrips_without_time_loss(self):
        index = CueIndex([Cue("1", 1050, 2099, text="日本語\nEnglish")])
        exported = export_for_editor(index, "ja", self.root)
        loaded = parse_srt(exported)
        self.assertEqual(loaded.cues[0].start_ms, 1050)
        self.assertEqual(loaded.cues[0].end_ms, 2099)
        self.assertEqual(loaded.cues[0].text, index.cues[0].text)

    def test_reloading_edited_srt_replaces_text_track(self):
        cache = CacheStore(self.root / "cache")
        self.srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nOriginal\n", encoding="utf-8")
        first, _ = cache.import_srt(self.srt, "disc", 1, "en")
        self.srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nCorrected\n", encoding="utf-8")
        second, _ = cache.import_srt(self.srt, "disc", 1, "en")
        self.assertEqual(first.track_id, second.track_id)
        tracks = cache.load_tracks("disc", 1)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].index.cues[0].text, "Corrected")

    def test_image_export_writes_bdn_and_copied_png(self):
        image = QImage(100, 30, QImage.Format.Format_RGBA8888)
        image.fill(QColor("white"))
        path = self.root / "source.png"
        image.save(str(path))
        exported = export_for_editor(CueIndex([Cue("1", 1000, 2000, path)]), "en", self.root)
        root = ET.parse(exported).getroot()
        self.assertEqual(root.tag, "BDN")
        event = root.find("Events/Event")
        self.assertEqual(event.attrib["InTC"], "00:00:01:00")
        self.assertTrue((exported.parent / event.find("Graphic").text).is_file())
        self.assertEqual(root.find("Description/Language").attrib["Code"], "eng")
        self.assertEqual(bdn_time(3599999), "01:00:00:00")

    def test_launch_uses_separate_arguments_without_shell(self):
        executable = self.root / "SubtitleEdit.exe"
        executable.write_bytes(b"test-only")
        self.srt.write_text("test-only", encoding="utf-8")
        with patch("dvd_player.subtitle_edit.subprocess.Popen") as start:
            launch_editor(executable, self.srt)
        self.assertEqual(start.call_args.args[0], [str(executable), str(self.srt)])
        self.assertNotIn("shell", start.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
