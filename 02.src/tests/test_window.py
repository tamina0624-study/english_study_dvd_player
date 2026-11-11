import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import logging
from concurrent.futures import Future
import unittest
from unittest.mock import MagicMock, patch

from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtCore import QCoreApplication, QEvent, QRect, QModelIndex
from PySide6.QtWidgets import QApplication, QAbstractSlider, QStyleOptionViewItem

from dvd_player.core import Cue, CueIndex
from dvd_player.window import MainWindow
from dvd_player.storage import CachedTrack


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {"DVD_PLAYER_DATA_DIR": self.temp.name})
        self.env_patch.start()
        self.player_patch = patch("dvd_player.window.Player", side_effect=OSError("test environment"))
        self.player_patch.start()
        self.window = MainWindow()
        self.window.timer.stop()
        self.app.processEvents()

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()
        self.player_patch.stop()
        self.env_patch.stop()
        logger = logging.getLogger("dvd_player")
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)
        self.temp.cleanup()

    def test_missing_vlc_does_not_crash(self):
        with patch("dvd_player.window.Player", side_effect=OSError("missing")):
            self.window._initialize()
        self.assertFalse(self.window.play_button.isEnabled())
        self.assertIn("VLC", self.window.statusBar().currentMessage())

    def test_current_subtitle_highlight_is_painted_for_images_and_text(self):
        for cue in (Cue("image", 1000, 3000, Path("unused.png")),
                    Cue("text", 1000, 3000, text="Example")):
            with self.subTest(text=cue.text):
                self.window._apply_subtitles((CueIndex([cue]), "en"))
                listing = self.window.subtitle_list
                option = QStyleOptionViewItem()
                option.rect = QRect(0, 0, 400, 100)
                for ms, expected in ((1500, "#75dcc7"), (4000, "#1b2839")):
                    self.window._sync(ms)
                    canvas = QImage(400, 100, QImage.Format.Format_RGB32)
                    canvas.fill(QColor("black"))
                    painter = QPainter(canvas)
                    listing.itemDelegate().paint(painter, option, listing.model().index(0, 0))
                    painter.end()
                    self.assertEqual(canvas.pixelColor(6, 45).name(), expected)

    def test_follow_resume_scrolls_to_current_subtitle(self):
        cues = [Cue(str(i), i * 2000, i * 2000 + 1500, text=f"Subtitle {i}")
                for i in range(30)]
        self.window._apply_subtitles((CueIndex(cues), "en"))
        self.window.show()
        self.app.processEvents()
        self.window._manual_scroll()
        self.window._sync(50000)
        self.assertFalse(self.window.follow_button.isChecked())
        self.window.subtitle_list.verticalScrollBar().setValue(0)
        self.window.follow_button.click()
        self.assertTrue(self.window.follow)
        self.assertTrue(self.window.follow_button.isChecked())
        rect = self.window.subtitle_list.visualItemRect(self.window.subtitle_list.item(25))
        self.assertTrue(self.window.subtitle_list.viewport().rect().intersects(rect))

    def test_follow_resume_loads_images_when_viewport_corner_is_padding(self):
        path = Path(self.temp.name) / "subtitle.png"
        image = QImage(160, 50, QImage.Format.Format_RGB32)
        image.fill(QColor("white"))
        self.assertTrue(image.save(str(path)))
        cues = [Cue(str(i), i * 2000, i * 2000 + 1500, path) for i in range(80)]
        self.window._apply_subtitles((CueIndex(cues), "en"))
        self.window.show()
        self.app.processEvents()
        listing = self.window.subtitle_list
        real_index_at = listing.indexAt
        # A corner inside list padding must not make image loading restart at 0.
        def index_at(point):
            return QModelIndex() if point.x() <= 1 else real_index_at(point)
        with patch.object(listing, "indexAt", side_effect=index_at):
            self.window._sync(0)
            self.window._manual_scroll()
            listing.verticalScrollBar().setValue(0)
            self.window._sync(120000)
            self.assertTrue(listing.item(60).icon().isNull())
            self.window.follow_button.click()
            # Resume must load the image immediately, including while paused.
            self.assertFalse(listing.item(60).icon().isNull())
            for _ in range(3):
                self.app.processEvents()
                self.window._sync(120000)
                rect = listing.visualItemRect(listing.item(60))
                self.assertTrue(listing.viewport().rect().intersects(rect))
                self.assertFalse(listing.item(60).icon().isNull())
            self.assertTrue(listing.item(0).icon().isNull())

    def test_english_and_japanese_subtitles_share_one_wide_list(self):
        with tempfile.TemporaryDirectory() as temp:
            image = QImage(160, 50, QImage.Format.Format_RGB32)
            image.fill(0xFFFFFF)
            path = Path(temp) / "subtitle.png"
            self.assertTrue(image.save(str(path)))
            english_cues = [Cue(f"en-{i}", 1000 + i * 6000, 3000 + i * 6000, path)
                            for i in range(3)]
            self.window._apply_subtitles((CueIndex(english_cues), "en"))
            self.window._apply_subtitles((CueIndex([Cue("ja", 1000, 3000, text="日本語")]), "ja"))
            self.window.show()
            self.app.processEvents()
            self.window._sync(1500)
            self.assertEqual(self.window.active_rows, {"en": (0,), "ja": (0,)})
            listing = self.window.subtitle_list
            self.assertEqual(listing.count(), 4)
            self.assertFalse(listing.item(0).icon().isNull())
            self.assertIn("日本語", listing.item(1).text())
            self.assertTrue(listing.isVisible())
            self.assertGreater(listing.height(), 400)
            self.assertGreater(listing.width(), 450)
            self.assertFalse(hasattr(self.window, "track_selectors"))
            self.assertFalse(hasattr(self.window, "subtitle_groups"))
            self.assertFalse(hasattr(self.window, "operation_language"))
            for button in (self.window.import_button, self.window.extract_button,
                           self.window.ocr_button, self.window.edit_button,
                           self.window.cancel_extract_button, self.window.assign_language_button,
                           self.window.follow_button):
                self.assertEqual(button.text(), "")
                self.assertFalse(button.icon().isNull())
                self.assertTrue(button.toolTip())
                self.assertEqual(button.size().width(), 30)
            self.assertLessEqual(listing.iconSize().height(), 64)
            image_rows_height = sum(listing.item(i).sizeHint().height()
                                    for i in (0, 2, 3))
            self.assertLessEqual(image_rows_height, listing.viewport().height())
            self.assertGreaterEqual(listing.item(1).font().pointSizeF(), 20)
            self.window._select_subtitle_item(listing.item(1))
            self.assertEqual(self.window.active_language, "ja")
            self.window._sync(4000)
            self.assertEqual(self.window.highlight_rows["en"], set())
            self.assertEqual(listing.item(0).background().color().alpha(), 0)
            self.assertLessEqual(
                abs(self.window.import_button.geometry().center().y()
                    - self.window.volume.geometry().center().y()), 10)

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
        self.window.engine.play.assert_called_once()
        self.window.engine.pause.assert_not_called()
        p.get_time.return_value = 6000
        self.window._update_playback()
        self.window.engine.pause.assert_called_once()

    def test_cached_tracks_can_switch_without_changing_playback(self):
        first = CueIndex([Cue("a", 0, 1000, Path("unused"))])
        second = CueIndex([Cue("b", 2000, 3000, Path("unused"))])
        self.window.engine = MagicMock()
        self.window._add_cached_track(CachedTrack("one", "en", first))
        self.window._add_cached_track(CachedTrack("two", "en", second), select=False)
        self.assertIs(self.window.indexes["en"], first)
        self.window.track_menus["en"].actions()[1].trigger()
        self.assertIs(self.window.indexes["en"], second)
        self.assertEqual(self.window.track_menus["en"].actions()[1].text(), "画像トラック 2")
        self.window.engine.player.set_time.assert_not_called()

    def test_cancel_rejects_queued_extraction_results(self):
        generation = self.window.generation
        self.window.extraction_events.put((generation, "progress", "古い進捗"))
        self.window._stop_extraction()
        self.window._tick()
        self.assertNotIn("古い進捗", self.window.subtitle_status.text())
        self.assertTrue(self.window.extraction_cancel.is_set())

    def test_unknown_track_language_can_be_assigned_and_saved(self):
        self.window.unknown_tracks = [9]
        self.window.media_id = "test"
        with patch("dvd_player.window.QInputDialog.getItem", return_value=("英語", True)), \
                patch.object(self.window, "_start_extraction") as restart:
            self.window._assign_language()
        self.assertEqual(self.window.cache.language_map("test", 0), {9: "en"})
        restart.assert_called_once()

    def test_media_removal_resets_playback_and_cancels_io(self):
        self.window.engine = MagicMock()
        self.window.ready = True
        self.window.media_id = "test"
        self.window._media_removed()
        self.window.navigation_job.result(timeout=2)
        self.assertFalse(self.window.ready)
        self.assertTrue(self.window.media_cancel.is_set())
        self.assertFalse(self.window.play_button.isEnabled())
        self.window.engine.player.stop.assert_called_once()

    def test_partial_subtitles_do_not_show_stale_cue_outside_coverage(self):
        self.window._display_track(CueIndex([], complete=False, coverage=[(0, 2000)]), "en")
        self.window._sync(3000)
        self.assertIn("未取得", self.window.coverage_status.text())
        self.window._sync(1000)
        self.assertEqual(self.window.coverage_status.text(), "")

    def test_chapter_change_runs_outside_gui_and_does_not_poll_busy_vlc(self):
        self.window.engine = MagicMock()
        self.window.ready = True
        p = self.window.engine.player
        p.get_chapter.return_value = 1
        p.get_chapter_count.return_value = 3
        p.get_length.return_value = 2000000
        job = Future()
        with patch.object(self.window.navigation_executor, "submit", return_value=job) as submit:
            self.window._chapter(1)
            submit.assert_called_once_with(self.window.engine.change_chapter, 1, None)
            self.window._tick()
            self.window._chapter(1)
            submit.assert_called_once()
        self.assertEqual(p.mock_calls, [])
        self.assertFalse(self.window.ready)
        self.assertFalse(self.window.open_button.isEnabled())
        self.assertFalse(self.window.volume.isEnabled())
        job.set_result(None)
        with patch.object(self.window, "_update_playback"):
            self.window._tick()
        self.assertTrue(self.window.ready)
        self.assertIsNone(self.window.navigation_job)

    def test_chapter_worker_preserves_pending_pause_and_reports_failure(self):
        self.window.engine = MagicMock()
        self.window.ready = True
        self.window.engine.player.get_chapter.return_value = 0
        self.window.engine.player.get_chapter_count.return_value = 3
        self.window.engine.player.get_length.return_value = 2000000
        self.window.seek.request(1000, False)
        job = Future()
        with patch.object(self.window.navigation_executor, "submit", return_value=job) as submit:
            self.window._chapter(-1)
            submit.assert_called_once_with(self.window.engine.change_chapter, -1, False)
        job.set_exception(RuntimeError("navigation failed"))
        with patch.object(self.window, "_update_playback"):
            self.window._tick()
        self.assertTrue(self.window.ready)
        self.assertIsNone(self.window.seek.target)
        self.assertIn("移動できません", self.window.statusBar().currentMessage())

    def test_title_selection_does_not_stop_or_open_vlc_on_gui_thread(self):
        self.window.engine = MagicMock()
        self.window.ready = True
        self.window.titles.addItem("Title 1", 0)
        self.window.titles.addItem("Title 2", 1)
        self.window.loaded_drive = "D:/"
        job = Future()
        with patch.object(self.window.navigation_executor, "submit", return_value=job) as submit:
            self.window._select_title(1)
            submit.assert_called_once_with(self.window.engine.open, "D:/", 1, volume=0)
            self.window._tick()
        self.assertEqual(self.window.engine.method_calls, [])
        self.assertFalse(self.window.ready)
        self.assertTrue(self.window.preparing)
        self.assertFalse(self.window.titles.isEnabled())
        job.set_result(None)

    def test_identity_completion_does_not_poll_vlc_after_starting_open(self):
        self.window.engine = MagicMock()
        identity = Future()
        identity.set_result("disc-id")
        self.window.jobs.append(("identity", self.window.generation, identity))
        opening = Future()
        with patch.object(self.window.navigation_executor, "submit", return_value=opening):
            self.window._tick()
        self.assertEqual(self.window.engine.method_calls, [])
        self.assertEqual(self.window.navigation_kind, "open")
        opening.set_result(None)

    def test_slow_navigation_records_diagnostics_once_without_polling_vlc(self):
        self.window.engine = MagicMock()
        self.window.ready = True
        job = Future()
        with patch.object(self.window.navigation_executor, "submit", return_value=job):
            self.window._chapter(1)
        self.window.navigation_started = 0
        with patch("dvd_player.diagnostics.dump_threads") as dump:
            self.window._tick()
            self.window._tick()
            dump.assert_called_once()
        self.assertEqual(self.window.engine.method_calls, [])
        job.set_result(None)

    def test_failed_paused_seek_restores_pause(self):
        self.window.engine = MagicMock()
        p = self.window.engine.player
        p.is_playing.return_value = False
        p.get_time.return_value = 10000
        p.get_length.return_value = 2000000
        self.window.seek.request(1332000, False)
        self.window.engine.seek.side_effect = RuntimeError("seek failed")
        self.window._update_playback()
        self.window.engine.pause.assert_called_once()
        self.assertIsNone(self.window.seek.target)

    def test_complete_empty_track_has_explicit_message(self):
        self.window._display_track(CueIndex(), "ja")
        self.assertIn("字幕がありません", self.window.subtitle_status.text())

    def test_keyboard_seek_and_title_restart_clear_old_request(self):
        self.window.engine = MagicMock()
        self.window.ready = True
        p = self.window.engine.player
        p.is_seekable.return_value = True
        p.is_playing.return_value = False
        p.get_length.return_value = 30000
        self.window.slider.triggerAction(QAbstractSlider.SliderAction.SliderToMaximum)
        self.app.processEvents()
        self.assertEqual(self.window.seek.target, 30000)
        self.window._start_title()
        self.assertIsNone(self.window.seek.target)

    def test_text_subtitles_render_and_sync_without_images(self):
        self.window._display_track(CueIndex([Cue("text", 1000, 3000, text="Hello\n日本語")]), "en")
        self.window.show()
        self.app.processEvents()
        self.window._sync(2000)
        item = self.window.subtitle_list.item(0)
        self.assertIn("Hello\n日本語", item.text())
        self.assertTrue(item.icon().isNull())
        self.assertEqual(self.window.active_rows["en"], (0,))

    def test_editor_button_exports_then_launches_editor(self):
        executable = Path(self.temp.name) / "SubtitleEdit.exe"
        executable.write_bytes(b"test-only")
        self.window.editor_path = executable
        self.window.media_id = "test"
        self.window.indexes["en"] = CueIndex([Cue("1", 1000, 2000, text="Editable text")])
        with patch("dvd_player.window.QFileDialog.getExistingDirectory", return_value=self.temp.name):
            self.window._open_editor()
        self.window.jobs[-1][2].result(timeout=5)
        with patch("dvd_player.window.launch_editor") as launch:
            self.window._tick()
        exported = launch.call_args.args[1]
        self.assertTrue(exported.is_file())
        self.assertEqual(exported.suffix, ".srt")
        self.assertEqual(self.window.srt_sources[("test", 0, "en")], exported)

    def test_background_srt_import_updates_text_without_playback(self):
        source = Path(self.temp.name) / "sample.srt"
        source.write_text("1\n00:00:01,000 --> 00:00:02,000\nImported text\n", encoding="utf-8")
        self.window.media_id = "test"
        self.window._queue_srt(source, "en")
        self.window.jobs[-1][2].result(timeout=5)
        self.window._tick()
        self.assertEqual(self.window.indexes["en"].cues[0].text, "Imported text")


if __name__ == "__main__":
    unittest.main()
