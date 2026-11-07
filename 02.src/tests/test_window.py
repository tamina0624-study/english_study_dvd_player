import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QImage
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication

from dvd_player.core import Cue, CueIndex
from dvd_player.window import MainWindow


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MainWindow()
        self.window.timer.stop()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def test_missing_vlc_does_not_crash(self):
        with patch("dvd_player.window.Player", side_effect=OSError("missing")):
            self.window._initialize()
        self.assertFalse(self.window.play_button.isEnabled())
        self.assertIn("VLC", self.window.statusBar().currentMessage())

    def test_image_subtitle_and_language_switch(self):
        with tempfile.TemporaryDirectory() as temp:
            image = QImage(160, 50, QImage.Format.Format_RGB32)
            image.fill(0xFFFFFF)
            path = Path(temp) / "subtitle.png"
            self.assertTrue(image.save(str(path)))
            index = CueIndex([Cue("a", 1000, 3000, path)])
            self.window._apply_subtitles((index, "en"))
            self.window.show()
            self.app.processEvents()
            self.window._sync(1500)
            self.assertEqual(self.window.active_rows, ("en", (0,)))
            self.assertFalse(self.window.lists["en"].item(0).icon().isNull())
            self.window.tabs.setCurrentIndex(1)
            self.window._sync(1500)
            self.assertEqual(self.window.active_rows, ("ja", ()))
            self.window.tabs.setCurrentIndex(0)
            self.window._sync(4000)
            self.assertEqual(self.window.highlight_rows["en"], set())
            self.assertEqual(self.window.lists["en"].item(0).background().color().alpha(), 0)

    def test_rewind_requests_two_seconds_and_restores_pause(self):
        self.window.engine = MagicMock()
        p = self.window.engine.player
        p.is_seekable.return_value = True
        p.is_playing.return_value = 0
        p.get_time.return_value = 10000
        p.get_length.return_value = 30000
        self.window.ready = True
        self.window._rewind()
        self.window._rewind()
        self.window._update_playback()
        self.window.engine.seek.assert_called_once_with(6000)
        p.get_time.return_value = 6000
        self.window._update_playback()
        self.window.engine.play.assert_not_called()


if __name__ == "__main__":
    unittest.main()
